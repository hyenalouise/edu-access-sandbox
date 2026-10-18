"""Silver for deped_enrollment: cleaning rules, quarantine, the gate, and the run record.

Made-up deliveries (tests/factories/deped_deliveries.py) go through the real
Bronze pipeline into an in-memory DuckDB, then through the committed Silver
SQL files, run the way the job's two SQL tasks run them: the build, then the
gate, with the job parameters bound. No real DepEd row is used.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import datetime

import pytest

from factories.deped_deliveries import (
    REPO_ROOT, approve, columns, empty_config, fake_repo, make_delivery, make_rows, real_config, with_values,
    write_config,
)
from src.ingestion.errors import IngestionError
from src.ingestion.pipeline import IngestionRun
from src.ingestion.store import DuckDBStore, to_duckdb
from src.silver.generators import generator
from src.silver.spec import build_spec, load_spec
from src.silver.sql import build_sql, gate_sql

REVISION = "c" * 40
BRONZE = "edu_access.`02-bronze`.deped_enrollment_raw"
CLEAN = "edu_access.`03-silver`.deped_enrollment_clean"
QUARANTINE = "edu_access.`03-silver`.deped_enrollment_quarantine"
# What the build writes and the gate checks; the gate copies them to CLEAN and QUARANTINE only if every check passes.
CLEAN_CANDIDATE = "edu_access.`03-silver`.deped_enrollment_clean_candidate"
QUARANTINE_CANDIDATE = "edu_access.`03-silver`.deped_enrollment_quarantine_candidate"
CONTROL = "edu_access.`01-control`"
V1, V2 = columns("v1"), columns("v2")


@dataclass
class SilverResult:
    run_id: str
    status: str            # succeeded | failed | built (the gate was not run)
    error: str = None


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


class Env:
    def __init__(self, tmp_path):
        self.config = empty_config()
        self.inbox = tmp_path / "landing" / "deped"
        self.repo = fake_repo(tmp_path / "repo", self.config)
        self.store = DuckDBStore()

    def deliver(self, school_year, schema_version="v1", folder="original", version=1, supersedes=None, **kwargs):
        encoding = "cp1252" if schema_version == "v2" else "utf-8"
        path = make_delivery(self.inbox / folder, school_year, schema_version, encoding=encoding, **kwargs)
        approve(self.config, path, school_year, schema_version, encoding, delivery_version=version, supersedes=supersedes)
        write_config(self.repo, self.config)
        return path

    def bronze(self):
        summary = IngestionRun(self.store, self.repo, "deped_enrollment", self.inbox.parent, "local", REVISION).execute()
        assert summary.status == "succeeded", summary
        return summary

    def silver(self, run_id=None, hook=None, gate=True):
        """The job's two Silver SQL tasks: the build, then (if it succeeded) the gate."""
        run_id = run_id or str(uuid.uuid4())
        params = {"run_id": run_id, "code_revision": REVISION, "environment": "local"}
        folder = self.repo / "etl" / "03_silver"
        try:
            self.store.run_file(folder / "01_clean_deped_enrollment.sql", params)
        except Exception as e:
            return SilverResult(run_id, "failed", f"build: {e}")
        if hook:
            hook()
        if not gate:
            return SilverResult(run_id, "built")
        try:
            self.store.run_file(folder / "90_validate_deped_enrollment_clean.sql", params)
        except Exception as e:
            return SilverResult(run_id, "failed", str(e))
        return SilverResult(run_id, "succeeded")

    def silver_run(self, run_id):
        return self.rows(f"SELECT * FROM {CONTROL}.pipeline_runs WHERE run_id = '{run_id}' "
                         "AND pipeline_name = 'silver_build'")[0]

    def q(self, sql):
        return self.store.query(sql)

    def one(self, sql):
        return self.q(sql)[0][0]

    def rows(self, sql):
        return self.store.records(sql)

    def checks(self, run_id, status=None):
        where = f" AND status = '{status}'" if status else ""
        return {(r["check_name"], r["batch_id"]): r for r in self.rows(
            f"SELECT * FROM {CONTROL}.data_quality_results WHERE run_id = '{run_id}'{where}")}

    def failed_checks(self, run_id):
        return sorted({name for name, _ in self.checks(run_id, "FAIL")})


def v2_row(i, values=None, first_id=950001):
    """A made-up SY 2025-26 row with that year's labels; school IDs from 950001."""
    row = make_rows(V2, n_rows=i + 1, first_id=first_id)[i]
    base = {"offers_es": "Yes", "offers_jhs": "No", "offers_shs": "No", "school_management": "DepED Managed",
            "annex_status": "School with no Annexes", "sector": "Public"}
    return with_values(V2, row, {**base, **(values or {})})


def v1_rows(n=3, changes=None):
    """Made-up SY 2023-24 rows; changes = {row index: {column: value}}."""
    rows = make_rows(V1, n_rows=n)
    return [with_values(V1, row, (changes or {}).get(i, {})) for i, row in enumerate(rows)]


# --- Cleaning rules -------------------------------------------------------------------

def test_counts_are_typed_and_blanks_stay_null_not_zero(env):
    env.deliver("2023-24", rows=v1_rows(changes={1: {"g1_male": "", "g2_female": "17"}}))
    env.bronze()
    assert env.silver().status == "succeeded"
    row = env.rows(f"SELECT * FROM {CLEAN} WHERE school_id = '900002'")[0]
    assert row["g1_male"] is None                  # published blank: NULL, never 0
    assert row["g2_female"] == 17 and isinstance(row["g2_female"], int)
    assert row["g11_unique_male"] is None          # blank in every made-up v1 row, as in SY 2023-24 (O-16)
    types = dict(env.q("SELECT column_name, data_type FROM information_schema.columns "
                       "WHERE table_schema = '03-silver' AND table_name = 'deped_enrollment_clean'"))
    assert {types[c] for c in V1 if c.endswith(("_male", "_female"))} == {"INTEGER"}
    assert (types["offers_es"], types["school_id"], types["source_row_number"]) == ("BOOLEAN", "VARCHAR", "BIGINT")


def test_absent_columns_are_null_and_told_apart_by_schema_version(env):
    env.deliver("2023-24")
    env.deliver("2025-26", "v2", rows=[v2_row(0, {"g11_sshs_acad_male": "", "g11_sshs_acad_female": "4"})])
    env.bronze()
    assert env.silver().status == "succeeded"
    v1 = env.rows(f"SELECT schema_version, g11_sshs_acad_male, modified_curricular_offering_classification "
                  f"FROM {CLEAN} WHERE school_year = '2023-24'")
    assert {(r["schema_version"], r["g11_sshs_acad_male"], r["modified_curricular_offering_classification"]) for r in v1} \
        == {("v1", None, None)}                    # not in the v1 file at all
    v2 = env.rows(f"SELECT * FROM {CLEAN} WHERE school_year = '2025-26'")[0]
    assert (v2["schema_version"], v2["g11_sshs_acad_male"], v2["g11_sshs_acad_female"]) == ("v2", None, 4)  # published blank
    assert v2["modified_curricular_offering_classification"] == "Purely ES"


def test_labels_and_booleans_map_to_one_standard_set(env):
    env.deliver("2023-24", rows=v1_rows(1, {0: {"sector": "SUC/LUC", "school_management": "SUC"}}))
    env.deliver("2025-26", "v2", rows=[
        v2_row(0, {"sector": "SUCsLUCs", "school_management": "SUC Managed", "offers_shs": "Yes"}),
        v2_row(1, {"school_management": "Non-Sectarian ", "annex_status": "Mother school", "offers_es": ""}),
        v2_row(2, {"school_management": "SCHOOL ABROAD", "sector": "PSO", "region": "PSO"}),
    ])
    env.bronze()
    assert env.silver().status == "succeeded"
    got = {r["school_id"]: r for r in env.rows(f"SELECT * FROM {CLEAN}")}
    assert (got["900001"]["sector"], got["950001"]["sector"]) == ("SUC/LUC", "SUC/LUC")
    assert (got["900001"]["school_management"], got["950001"]["school_management"]) == ("SUC", "SUC")
    assert got["950002"]["school_management"] == "Non-Sectarian"      # trailing space trimmed before mapping
    assert got["950002"]["annex_status"] == "Mother School"
    assert got["950003"]["school_management"] == "PSO" and got["950003"]["is_overseas"] is True
    assert (got["900001"]["offers_es"], got["900001"]["offers_jhs"]) == (True, False)      # True/False
    assert (got["950001"]["offers_es"], got["950001"]["offers_shs"]) == (True, True)       # Yes
    assert got["950002"]["offers_es"] is None                                           # blank, not FALSE


def test_text_is_trimmed_collapsed_and_repaired_but_place_names_are_not_rewritten(env):
    env.deliver("2025-26", "v2", rows=[v2_row(0, {
        "province": "NCR   SECOND DISTRICT", "municipality": "CITY OF MALOLOS  (Capital)",
        "barangay": "AGUSAN PEQUEÃ‘O", "school_name": "Sto.\tNiÃ±o Elementary School ",
        "street_address": "-",
    }), v2_row(1, {"street_address": "N/A", "barangay": ""}), v2_row(2, {"street_address": "Purok 1"})])
    env.bronze()
    assert env.silver().status == "succeeded"
    got = {r["school_id"]: r for r in env.rows(f"SELECT * FROM {CLEAN}")}
    first = got["950001"]
    assert first["province"] == "NCR SECOND DISTRICT"
    assert first["municipality"] == "CITY OF MALOLOS (Capital)"  # "(Capital)" stays: matching is Integration's job
    assert first["barangay"] == "AGUSAN PEQUEÑO"
    assert first["school_name"] == "Sto. Niño Elementary School"
    assert first["street_address"] is None                        # placeholder
    assert (got["950002"]["street_address"], got["950002"]["barangay"]) == (None, None)
    assert got["950003"]["street_address"] == "Purok 1"
    # Bronze keeps what was published.
    assert env.one(f"SELECT barangay FROM {BRONZE} WHERE school_id = '950001'") == "AGUSAN PEQUEÃ‘O"


def test_flags_mark_rows_and_never_drop_them(env):
    long_name = "AURORA HILL PROPER (MALVAR-SGT. FLORESCA"
    assert len(long_name) == 40
    zeros = {c: "0" for c in V1 if c.endswith(("_male", "_female")) and "unique" not in c}
    env.deliver("2023-24", rows=v1_rows(4, {
        0: {**zeros, "g1_male": "5"},
        1: zeros,                                                       # every published count is 0
        2: {"region": "PSO", "sector": "PSO", "school_management": "PSO", "legislative_district": "PSO"},
        3: {"barangay": long_name},
    }))
    blanks = {c: "" for c in V2 if c.endswith(("_male", "_female"))}
    env.deliver("2025-26", "v2", rows=[v2_row(0, blanks)])  # no count published at all
    env.bronze()
    assert env.silver().status == "succeeded"
    got = {r["school_id"]: r for r in env.rows(f"SELECT * FROM {CLEAN}")}
    assert len(got) == 5
    assert got["900001"]["enrollment_status"] == "has_learners"
    assert got["900002"]["enrollment_status"] == "all_zero"
    assert got["950001"]["enrollment_status"] == "no_counts"
    assert got["950001"]["g1_male"] is None                             # blank, not zero
    assert got["900003"]["is_overseas"] is True and got["900001"]["is_overseas"] is False
    assert got["900004"]["barangay_possibly_truncated"] is True and got["900001"]["barangay_possibly_truncated"] is False


def test_flags_are_never_null_so_gold_filters_cannot_drop_rows(env):
    """`WHERE NOT flag` silently drops rows whose flag is NULL; Silver's flags are never NULL.
    Nullable values (a blank offers_shs) need IS NOT TRUE, which Gold must use."""
    env.deliver("2025-26", "v2", rows=[v2_row(0), v2_row(1, {"offers_shs": ""})])
    env.bronze()
    env.silver()
    assert env.one(f"SELECT COUNT(*) FROM {CLEAN} WHERE is_overseas IS NULL OR barangay_possibly_truncated IS NULL "
                   "OR enrollment_status IS NULL") == 0
    assert env.one(f"SELECT COUNT(*) FROM {CLEAN} WHERE NOT is_overseas") == 2
    assert env.one(f"SELECT COUNT(*) FROM {CLEAN} WHERE NOT offers_shs") == 1           # the trap: the NULL row is gone
    assert env.one(f"SELECT COUNT(*) FROM {CLEAN} WHERE offers_shs IS NOT TRUE") == 2   # NULL-safe


# --- Quarantine -------------------------------------------------------------------------

def test_negative_and_uncastable_counts_are_quarantined_with_reasons_not_dropped(env):
    env.deliver("2023-24", rows=v1_rows(150, {3: {"g1_male": "-3"}}))
    env.deliver("2024-25", rows=v1_rows(250, {7: {"g7_female": "5.0"}, 8: {"kinder_male": "abc"}}))
    env.bronze()
    summary = env.silver()
    assert summary.status == "succeeded"                      # 1 of 150 and 2 of 250 rows: under 1%, so WARN
    quarantined = {r["school_id"]: r for r in env.rows(f"SELECT * FROM {QUARANTINE}")}
    assert quarantined["900004"]["quarantine_reasons"] == ["count_negative"]
    assert quarantined["900008"]["quarantine_reasons"] == ["count_uncastable"]
    assert quarantined["900009"]["quarantine_reasons"] == ["count_uncastable"]
    assert set(quarantined) == {"900004", "900008", "900009"} and quarantined["900004"]["batch_id"].endswith(
        env.one(f"SELECT archive_sha256 FROM {CONTROL}.ingestion_batches WHERE school_year = '2023-24'")[:12])
    assert env.one(f"SELECT COUNT(*) FROM {CLEAN} WHERE (school_year = '2023-24' AND school_id = '900004') "
                   "OR (school_year = '2024-25' AND school_id IN ('900008', '900009'))") == 0
    assert env.one(f"SELECT COUNT(*) FROM {CLEAN}") == 400 - 3
    checks = env.checks(summary.run_id)
    rate = {r["batch_id"].split("__")[1]: r["status"] for (name, _), r in checks.items() if name == "quarantine_rate"}
    assert rate == {"2023-24": "WARN", "2024-25": "WARN"}
    assert env.one(f"SELECT COUNT(*) FROM {BRONZE}") == 400   # Bronze untouched


def test_a_count_with_surrounding_spaces_is_quarantined_not_trimmed(env):
    """Counts are matched exactly, never trimmed: ' 5' is not a whole number (mapping note, count_columns)."""
    env.deliver("2023-24", rows=v1_rows(200, {0: {"g1_male": " 5"}, 1: {"g1_female": "5 "}}))
    env.bronze()
    summary = env.silver()
    assert summary.status == "succeeded"                                  # 2 of 200 rows: under 1%, so WARN
    assert env.q(f"SELECT school_id, quarantine_reasons FROM {QUARANTINE} ORDER BY 1") == [
        ("900001", ["count_uncastable"]), ("900002", ["count_uncastable"])]


def test_nine_digit_counts_do_not_overflow_the_build(env):
    """Three counts of 999,999,999 add up past INT; every sum of counts is taken in BIGINT, so the
    build finishes and the row is quarantined instead of the run crashing."""
    big = {c: "999999999" for c in ("g1_male", "g1_female", "g2_male")}
    env.deliver("2023-24", rows=v1_rows(200, {0: big}))
    env.bronze()
    summary = env.silver()
    assert summary.status == "succeeded", summary.error                # 1 of 200 rows: under 1%, so WARN
    assert env.q(f"SELECT school_id, quarantine_reasons FROM {QUARANTINE}") == [("900001", ["count_above_plausible_max"])]


def test_a_count_above_the_plausible_maximum_is_quarantined_and_the_maximum_is_kept(env):
    """O-2: the largest published count is 4,097; a count above 10,000 (an extra digit) cannot be trusted."""
    env.deliver("2023-24", rows=v1_rows(200, {0: {"g1_male": "40000"}, 1: {"g1_male": "10000"}}))
    env.bronze()
    summary = env.silver()
    assert summary.status == "succeeded"
    assert env.q(f"SELECT school_id, quarantine_reasons FROM {QUARANTINE}") == [("900001", ["count_above_plausible_max"])]
    assert env.one(f"SELECT g1_male FROM {CLEAN} WHERE school_id = '900002'") == 10000
    warned = {name for name, _ in env.checks(summary.run_id, "WARN")}
    assert warned == {"quarantine_rate", "quarantine_reason_count_above_plausible_max"}


def test_nine_digit_counts_do_not_overflow_the_gate(env):
    """The gate's learner sums are BIGINT too: a broken build is reported as a FAIL, not a crash."""
    env.deliver("2023-24", n_rows=4)
    env.bronze()
    summary = env.silver(hook=lambda: env.store.sql(
        f"UPDATE {CLEAN_CANDIDATE} SET g1_male = 999999999, g1_female = 999999999, g2_male = 999999999 WHERE school_id = '900002'"))
    assert summary.status == "failed" and "Silver gate failed" in summary.error
    assert "learners_reconcile" in env.failed_checks(summary.run_id)


def test_quarantine_above_one_percent_fails_the_run(env):
    env.deliver("2023-24", rows=v1_rows(3, {0: {"g1_male": "-1"}}))
    env.bronze()
    summary = env.silver()
    assert summary.status == "failed" and "Silver gate failed" in summary.error
    assert env.failed_checks(summary.run_id) == ["quarantine_rate"]
    run = env.silver_run(summary.run_id)
    assert (run["status"], run["failure_stage"], run["error_message"]) == (
        "failed", "gate", "1 FAIL result(s) in data_quality_results")


def test_duplicate_school_id_quarantines_every_copy(env):
    rows = v1_rows(200)
    rows.append(with_values(V1, rows[0], {"g1_male": "9"}))   # same school, different counts
    env.deliver("2023-24", rows=rows)
    env.bronze()                                                # Bronze keeps both and WARNs
    summary = env.silver()
    assert summary.status == "succeeded"
    assert env.q(f"SELECT school_id, quarantine_reasons FROM {QUARANTINE} ORDER BY source_row_number") == [
        ("900001", ["school_id_duplicated"]), ("900001", ["school_id_duplicated"])]
    assert env.one(f"SELECT COUNT(*) FROM {CLEAN}") == 199
    assert env.checks(summary.run_id)[("school_id_unique", env.one(f"SELECT batch_id FROM {CLEAN} LIMIT 1"))]["status"] == "PASS"


def test_blank_null_and_malformed_school_ids_are_quarantined_without_losing_a_row(env):
    """A NULL school_id makes NULL-unsafe conditions NULL; the row must still land somewhere."""
    env.deliver("2023-24", rows=v1_rows(400, {5: {"school_id": "12345"}}))
    env.bronze()
    for number, value in ((901, "NULL"), (902, "''")):        # Bronze refuses these files, so insert directly
        env.store.sql(f"INSERT INTO {BRONZE} SELECT * REPLACE ({value} AS school_id, {number} AS source_row_number) "
                      f"FROM {BRONZE} WHERE source_row_number = 1")
    summary = env.silver()
    assert summary.status == "succeeded"                       # 3 of 402 rows: under 1%, so WARN
    reasons = dict(env.q(f"SELECT source_row_number, quarantine_reasons FROM {QUARANTINE}"))
    assert reasons == {6: ["school_id_malformed"], 901: ["school_id_blank"], 902: ["school_id_blank"]}
    assert env.one(f"SELECT COUNT(*) FROM {CLEAN}") + env.one(f"SELECT COUNT(*) FROM {QUARANTINE}") == 402
    warned = {name for name, _ in env.checks(summary.run_id, "WARN")}
    assert warned == {"quarantine_rate", "quarantine_reason_school_id_blank", "quarantine_reason_school_id_malformed"}


# --- The gate ---------------------------------------------------------------------------

def test_an_unmapped_label_fails_the_gate(env):
    env.deliver("2023-24")
    env.bronze()
    assert env.silver().status == "succeeded"
    env.deliver("2025-26", "v2", rows=[v2_row(0, {"sector": "Charter"}), v2_row(1)])   # a new year brings a new label
    env.bronze()
    summary = env.silver()
    assert summary.status == "failed"
    assert env.failed_checks(summary.run_id) == ["labels_mapped_sector"]
    assert env.one(f"SELECT sector FROM {CLEAN_CANDIDATE} WHERE school_id = '950001'") is None   # the failed build, kept for review
    assert env.silver_run(summary.run_id)["status"] == "failed"
    assert env.silver().status == "failed"   # and on every run, until the mapping is reviewed


def test_an_unknown_boolean_label_fails_the_gate(env):
    env.deliver("2023-24", rows=v1_rows(3, {1: {"offers_jhs": "Maybe"}}))
    env.bronze()
    summary = env.silver()
    assert env.failed_checks(summary.run_id) == ["labels_mapped_offers_jhs"]


def test_an_unmapped_label_on_a_quarantined_row_still_fails_the_gate(env):
    """A quarantined row has no clean value; its labels are checked against the mapping itself."""
    env.deliver("2023-24", rows=v1_rows(200, {0: {"g1_male": "-1", "sector": "Charter"},
                                              1: {"g2_female": "abc", "offers_es": "Maybe"}}))
    env.bronze()
    summary = env.silver()                               # 2 of 200 rows quarantined: under 1%, so only a WARN
    assert summary.status == "failed"
    assert env.failed_checks(summary.run_id) == ["labels_mapped_offers_es", "labels_mapped_sector"]
    assert env.one(f"SELECT COUNT(*) FROM {QUARANTINE_CANDIDATE}") == 2


def test_reconciliation_and_learner_totals_pass_on_a_clean_load(env):
    env.deliver("2023-24", n_rows=5)
    env.deliver("2025-26", "v2", rows=[v2_row(i) for i in range(4)])
    env.bronze()
    summary = env.silver()
    assert summary.status == "succeeded"
    checks = env.checks(summary.run_id)
    assert {r["status"] for r in checks.values()} == {"PASS"}
    bronze_total = env.one(f"SELECT SUM(" + " + ".join(
        f"COALESCE(TRY_CAST({c} AS BIGINT), 0)" for c in V2 if c.endswith(("_male", "_female"))) + f") FROM {BRONZE}")
    learners = [r for (name, _), r in checks.items() if name == "learners_reconcile"]
    assert sum(int(r["actual"]) for r in learners) == bronze_total
    assert all(r["expected"] == r["actual"] for r in learners)
    rows = [r for (name, _), r in checks.items() if name == "rows_reconcile"]
    assert sorted((r["expected"], r["actual"]) for r in rows) == [("4", "4"), ("5", "5")]


def test_the_gate_catches_a_count_turned_into_zero(env):
    """Blank → 0 keeps learner totals equal; missing_counts_stay_null is what catches it."""
    env.deliver("2025-26", "v2", rows=[v2_row(0, {"g1_male": ""}), v2_row(1)])
    env.bronze()

    def blank_becomes_zero():
        env.store.sql(f"UPDATE {CLEAN_CANDIDATE} SET g1_male = 0 WHERE g1_male IS NULL")

    summary = env.silver(hook=blank_becomes_zero)
    assert summary.status == "failed"
    assert env.failed_checks(summary.run_id) == ["missing_counts_stay_null"]


def test_the_gate_catches_a_lost_row_and_a_stale_row(env):
    env.deliver("2023-24", n_rows=4)
    env.bronze()

    def tamper():
        env.store.sql(f"DELETE FROM {CLEAN_CANDIDATE} WHERE school_id = '900002'")
        env.store.sql(f"UPDATE {CLEAN_CANDIDATE} SET run_id = 'an-old-run' WHERE school_id = '900003'")

    summary = env.silver(hook=tamper)
    assert env.failed_checks(summary.run_id) == ["learners_reconcile", "missing_counts_stay_null",
                                                 "rows_built_by_this_run", "rows_reconcile"]


BROKEN_BUILDS = [
    ("rows_resolve_to_current_bronze", "source_row_number = 99999"),
    ("one_timestamp_per_run", "cleaned_at_utc = cleaned_at_utc + INTERVAL 1 SECOND"),
    ("lineage_complete", "batch_id = NULL"),
    ("absent_columns_stay_null", "g11_sshs_acad_male = 0"),
    ("counts_non_negative", "g1_male = -1"),
    ("counts_within_plausible_max", "g1_male = 10001"),
    ("school_id_unique", "school_id = '900001'"),
    ("school_id_valid", "school_id = 'X'"),
    ("enrollment_status_valid", "enrollment_status = 'other'"),
]


@pytest.mark.parametrize("check, tamper", BROKEN_BUILDS, ids=[check for check, _ in BROKEN_BUILDS])
def test_each_gate_check_fails_a_broken_build(env, check, tamper):
    """Checks the cleaning rules cannot trip on their own: each must still fail a build that breaks it."""
    env.deliver("2023-24", n_rows=4)
    env.bronze()
    summary = env.silver(hook=lambda: env.store.sql(f"UPDATE {CLEAN_CANDIDATE} SET {tamper} WHERE school_id = '900002'"))
    assert summary.status == "failed"
    assert check in env.failed_checks(summary.run_id)


def test_lineage_and_code_revision_on_every_row_and_result(env):
    env.deliver("2023-24")
    env.deliver("2025-26", "v2", rows=[v2_row(0)])
    env.bronze()
    summary = env.silver()
    joined = env.one(f"SELECT COUNT(*) FROM {CLEAN} AS c JOIN {BRONZE} AS b "
                     "ON c.source_sha256 = b.source_sha256 AND c.source_row_number = b.source_row_number "
                     "AND c.batch_id = b.batch_id AND c.school_id = b.school_id AND c.delivery_version = b.delivery_version "
                     "AND c.schema_version = b.schema_version")
    assert joined == env.one(f"SELECT COUNT(*) FROM {CLEAN}") == 4
    assert env.q(f"SELECT DISTINCT run_id, code_revision FROM {CLEAN}") == [(summary.run_id, REVISION)]
    assert env.q(f"SELECT DISTINCT code_revision FROM {CONTROL}.data_quality_results "
                 f"WHERE run_id = '{summary.run_id}'") == [(REVISION,)]
    assert env.one(f"SELECT COUNT(DISTINCT layer) FROM {CONTROL}.data_quality_results WHERE run_id = '{summary.run_id}'") == 1


def test_clean_and_quarantine_share_one_timestamp(env):
    env.deliver("2023-24", rows=v1_rows(150, {0: {"g1_male": "-1"}}))
    env.bronze()
    summary = env.silver()
    stamps = env.q(f"SELECT DISTINCT cleaned_at_utc FROM {CLEAN} UNION SELECT DISTINCT cleaned_at_utc FROM {QUARANTINE}")
    assert len(stamps) == 1 and isinstance(stamps[0][0], datetime)
    assert env.silver_run(summary.run_id)["started_at_utc"] == stamps[0][0]


def test_check_results_hold_counts_not_values(env):
    env.deliver("2023-24", rows=v1_rows(3, {1: {"sector": "Secret Label"}}))
    env.bronze()
    summary = env.silver()
    texts = [str(v) for r in env.checks(summary.run_id).values() for v in (r["expected"], r["actual"])]
    assert not [t for t in texts if "Secret" in t or "Test School" in t]


# --- Which Bronze rows, and when to build ---------------------------------------------------

def test_only_current_batches_are_read_and_a_revision_replaces_its_year(env):
    env.deliver("2023-24")
    first = env.deliver("2025-26", "v2", rows=[v2_row(i) for i in range(3)])
    env.bronze()
    assert env.silver().status == "succeeded"
    v1_sha = env.config["deliveries"][1]["archive_sha256"]
    env.deliver("2025-26", "v2", folder="2026-08-01", version=2, supersedes=v1_sha,
                rows=[v2_row(i, {"g1_male": "7"}, first_id=960001) for i in range(5)])
    env.bronze()
    assert env.one(f"SELECT COUNT(*) FROM {BRONZE} WHERE school_year = '2025-26'") == 8   # both versions kept
    summary = env.silver()
    assert summary.status == "succeeded"
    assert env.q(f"SELECT DISTINCT delivery_version, school_id LIKE '96%' FROM {CLEAN} WHERE school_year = '2025-26'") \
        == [(2, True)]
    assert env.one(f"SELECT COUNT(*) FROM {CLEAN} WHERE school_year = '2025-26'") == 5
    assert env.one(f"SELECT COUNT(*) FROM {CLEAN} WHERE school_year = '2023-24'") == 3
    assert first.exists()


def test_every_run_rebuilds_the_same_tables(env):
    """Silver rebuilds on every run (D-025): the same Bronze gives the same rows, never more."""
    env.deliver("2023-24", rows=v1_rows(150, {2: {"g1_male": "-1"}}))
    env.deliver("2025-26", "v2", rows=[v2_row(i) for i in range(3)])
    env.bronze()
    content = ("SELECT * EXCLUDE (run_id, cleaned_at_utc) FROM {} ORDER BY school_year, source_row_number")
    first = env.silver()
    before = (env.q(content.format(CLEAN)), env.q(content.format(QUARANTINE)))
    env.bronze()                                           # a Bronze rerun that loads nothing new
    again = env.silver()
    assert first.status == again.status == "succeeded" and first.run_id != again.run_id
    assert (env.q(content.format(CLEAN)), env.q(content.format(QUARANTINE))) == before
    assert (env.one(f"SELECT COUNT(*) FROM {CLEAN}"), env.one(f"SELECT COUNT(*) FROM {QUARANTINE}")) == (152, 1)
    assert env.one(f"SELECT COUNT(*) - COUNT(DISTINCT school_id || school_year) FROM {CLEAN}") == 0
    assert env.q(f"SELECT DISTINCT run_id FROM {CLEAN}") == [(again.run_id,)]


def test_a_run_is_succeeded_only_after_its_gate_passes(env):
    env.deliver("2023-24")
    env.bronze()
    built = env.silver(gate=False)                       # the build task ran; the gate task never did
    run = env.silver_run(built.run_id)
    assert (run["status"], run["environment"], run["code_revision"]) == ("running", "local", REVISION)
    assert run["job_run_id"] == built.run_id             # one filter on job_run_id finds Bronze loads and Silver builds
    assert run["finished_at_utc"] is None
    done = env.silver()
    run = env.silver_run(done.run_id)
    assert run["status"] == "succeeded" and run["finished_at_utc"] >= run["started_at_utc"]
    assert env.silver_run(built.run_id)["status"] == "running"   # never mistaken for a good build


def test_a_repaired_run_is_judged_by_its_own_checks(env):
    """Databricks' Repair run keeps the run_id: the gate must not count an earlier attempt's FAIL."""
    env.deliver("2023-24", n_rows=4)
    env.bronze()

    def lose_a_row():
        env.store.sql(f"DELETE FROM {CLEAN_CANDIDATE} WHERE school_id = '900002'")

    first = env.silver(run_id="job-run-9", hook=lose_a_row)
    assert first.status == "failed"
    assert not env.q("SELECT * FROM information_schema.tables WHERE table_name = 'deped_enrollment_clean'")  # nothing published
    repaired = env.silver(run_id="job-run-9")
    assert repaired.status == "succeeded"
    assert env.silver_run("job-run-9")["status"] == "succeeded"
    assert env.q(f"SELECT run_id, COUNT(*) FROM {CLEAN} GROUP BY 1") == [("job-run-9", 4)]   # the repair published
    assert env.one(f"SELECT COUNT(*) FROM {CONTROL}.data_quality_results WHERE run_id = 'job-run-9' AND status = 'FAIL'") > 0


def test_no_current_batch_fails_the_gate(env):
    from src.ingestion import control
    control.create_tables(env.store, env.repo)          # what the job's first task does before any load
    env.store.run_file(env.repo / "etl" / "02_bronze" / "01_create_deped_enrollment_raw.sql")
    summary = env.silver()
    assert summary.status == "failed"
    assert "current_batches_present" in env.failed_checks(summary.run_id)


# --- Publishing: only a build that passes reaches the Silver tables (D-025, #119) -----------------

def live(env):
    """What Gold would read: the published tables, by run."""
    return (env.q(f"SELECT run_id, COUNT(*) FROM {CLEAN} GROUP BY 1"),
            env.q(f"SELECT run_id, COUNT(*) FROM {QUARANTINE} GROUP BY 1"))


def test_a_failed_build_never_replaces_the_last_good_one(env):
    env.deliver("2023-24", rows=v1_rows(150, {0: {"g1_male": "-1"}}))
    env.bronze()
    good = env.silver()
    assert good.status == "succeeded"
    assert live(env) == ([(good.run_id, 149)], [(good.run_id, 1)])
    env.deliver("2025-26", "v2", rows=[v2_row(0, {"sector": "Charter"}), v2_row(1)])   # a new year brings a new label
    env.bronze()
    bad = env.silver()
    assert bad.status == "failed" and env.silver_run(bad.run_id)["status"] == "failed"
    assert live(env) == ([(good.run_id, 149)], [(good.run_id, 1)])        # every school year of the good build stays
    assert env.q(f"SELECT DISTINCT run_id FROM {CLEAN_CANDIDATE}") == [(bad.run_id,)]   # the failed build, for review
    assert env.one(f"SELECT COUNT(*) FROM {CLEAN_CANDIDATE} WHERE sector IS NULL") == 1


def test_a_build_that_passes_is_published_as_built(env):
    env.deliver("2023-24", rows=v1_rows(150, {0: {"g1_male": "-1"}}))
    env.bronze()
    summary = env.silver()
    assert summary.status == "succeeded"
    for published, candidate in ((CLEAN, CLEAN_CANDIDATE), (QUARANTINE, QUARANTINE_CANDIDATE)):
        everything = f"SELECT * FROM {{}} ORDER BY school_year, source_row_number"
        assert env.q(everything.format(published)) == env.q(everything.format(candidate))
    assert live(env) == ([(summary.run_id, 149)], [(summary.run_id, 1)])
    types = dict(env.q("SELECT column_name, data_type FROM information_schema.columns "
                       "WHERE table_schema = '03-silver' AND table_name = 'deped_enrollment_clean'"))
    assert types["g1_male"] == "INTEGER" and types["offers_es"] == "BOOLEAN"


def test_only_the_candidate_tables_say_not_to_read_them(env):
    env.deliver("2023-24", n_rows=4)
    env.bronze()
    for _ in range(2):                                   # a rebuild replaces the table, and sets the comment again
        assert env.silver().status == "succeeded"
        comments = dict(env.q("SELECT table_name, comment FROM duckdb_tables() WHERE schema_name = '03-silver'"))
        assert comments["deped_enrollment_clean_candidate"].startswith("Unpublished build")
        assert "use deped_enrollment_quarantine," in comments["deped_enrollment_quarantine_candidate"]
        assert comments["deped_enrollment_clean"] is None and comments["deped_enrollment_quarantine"] is None


def test_a_run_that_dies_while_publishing_is_never_succeeded(env):
    """Quarantine is published first and clean last; a task that dies between them leaves the last
    good clean table, and the run 'running', so Gold, which trusts a table by its run_id, reads it."""
    env.deliver("2023-24", n_rows=4)
    env.bronze()
    good = env.silver()
    gate = (env.repo / "etl" / "03_silver" / "90_validate_deped_enrollment_clean.sql").read_text(encoding="utf-8")
    publish_clean = "CREATE OR REPLACE TABLE edu_access.`03-silver`.deped_enrollment_clean USING DELTA AS"
    assert gate.count(publish_clean) == 1
    interrupted = env.repo / "interrupted_gate.sql"
    interrupted.write_text(gate.replace(publish_clean, "SELECT raise_error('the task died');\n\n" + publish_clean),
                           encoding="utf-8")
    run_id = "job-run-dies"
    params = {"run_id": run_id, "code_revision": REVISION, "environment": "local"}
    env.store.run_file(env.repo / "etl" / "03_silver" / "01_clean_deped_enrollment.sql", params)
    with pytest.raises(Exception, match="the task died"):
        env.store.run_file(interrupted, params)
    assert env.silver_run(run_id)["status"] == "running"
    assert live(env) == ([(good.run_id, 4)], [])                       # quarantine was empty in both builds
    trusted = env.q(f"SELECT COUNT(*) FROM {CLEAN} AS c JOIN {CONTROL}.pipeline_runs AS p ON p.run_id = c.run_id "
                    "AND p.pipeline_name = 'silver_build' AND p.source_id = 'deped_enrollment' AND p.status = 'succeeded'")
    assert trusted == [(4,)]


def test_no_current_batch_leaves_the_published_build_in_place(env):
    env.deliver("2023-24", n_rows=4)
    env.bronze()
    good = env.silver()
    env.store.sql(f"UPDATE {CONTROL}.ingestion_batches SET status = 'failed'")   # no current batch any more
    summary = env.silver()
    assert summary.status == "failed"
    assert "current_batches_present" in env.failed_checks(summary.run_id)
    assert live(env) == ([(good.run_id, 4)], [])


def test_the_gate_stops_before_publishing_and_publishes_clean_last():
    spec = load_spec(REPO_ROOT, "deped_enrollment")
    build, gate = build_sql(spec), gate_sql(spec)
    for table in (spec.clean_table, spec.quarantine_table):
        assert f"CREATE OR REPLACE TABLE edu_access.`03-silver`.{table} USING" not in build   # the build never publishes
    order = [gate.index(marker) for marker in (
        "WHEN MATCHED AND s.fails > 0 THEN UPDATE SET",                                   # failed, recorded first
        "raise_error(",                                                                     # then the task stops
        f"CREATE OR REPLACE TABLE edu_access.`03-silver`.{spec.quarantine_table} USING",
        f"CREATE OR REPLACE TABLE edu_access.`03-silver`.{spec.clean_table} USING",
        "status = 'succeeded'",
    )]
    assert order == sorted(order)


# --- SY 2020-21, the fourth delivery ---------------------------------------------------

def test_local_government_is_kept_as_its_own_school_management_value(env):
    """SY 2020-21 alone publishes 'Local Government' (O-8): never folded into DepEd or LUC."""
    env.deliver("2020-21", rows=v1_rows(3, {1: {"school_management": "Local Government"},
                                            2: {"school_management": "LUC", "sector": "SUC/LUC"}}))
    env.bronze()
    summary = env.silver()
    assert summary.status == "succeeded"
    got = {r["school_id"]: r for r in env.rows(f"SELECT * FROM {CLEAN}")}
    assert [got[i]["school_management"] for i in ("900001", "900002", "900003")] == ["DepEd", "Local Government", "LUC"]
    assert (got["900002"]["sector"], got["900002"]["is_overseas"]) == ("Public", False)
    assert env.one(f"SELECT school_management FROM {BRONZE} WHERE school_id = '900002'") == "Local Government"
    checks = env.checks(summary.run_id)
    assert {r["status"] for (name, _), r in checks.items() if name == "labels_mapped_school_management"} == {"PASS"}


def test_four_years_reconcile_per_year_and_adding_sy_2020_21_leaves_the_others_unchanged(env):
    env.deliver("2023-24", rows=v1_rows(5))
    env.deliver("2024-25", rows=v1_rows(4))
    env.deliver("2025-26", "v2", rows=[v2_row(i) for i in range(3)])
    env.bronze()
    assert env.silver().status == "succeeded"
    content = ("SELECT * EXCLUDE (run_id, cleaned_at_utc, code_revision) FROM {} {} "
               "ORDER BY school_year, source_row_number")
    later = "WHERE school_year <> '2020-21'"
    before = (env.q(content.format(CLEAN, later)), env.q(content.format(QUARANTINE, later)))

    env.deliver("2020-21", rows=v1_rows(150, {2: {"g1_male": "-1"}, 7: {"school_management": "Local Government"}}))
    env.bronze()
    first = env.silver()
    assert first.status == "succeeded"
    assert (env.q(content.format(CLEAN, later)), env.q(content.format(QUARANTINE, later))) == before

    # Per year: every Bronze row is in clean or quarantine, never both, never lost; learners reconcile.
    per_year = env.q(
        f"SELECT b.school_year, COUNT(*), COUNT(c.school_id), COUNT(q.school_id) FROM {BRONZE} AS b "
        f"LEFT JOIN {CLEAN} AS c ON c.source_sha256 = b.source_sha256 AND c.source_row_number = b.source_row_number "
        f"LEFT JOIN {QUARANTINE} AS q ON q.source_sha256 = b.source_sha256 AND q.source_row_number = b.source_row_number "
        "GROUP BY 1 ORDER BY 1")
    assert per_year == [("2020-21", 150, 149, 1), ("2023-24", 5, 5, 0), ("2024-25", 4, 4, 0), ("2025-26", 3, 3, 0)]
    checks = env.checks(first.run_id)
    year_of = dict(env.q(f"SELECT batch_id, school_year FROM {CONTROL}.current_batches"))
    for name in ("rows_reconcile", "learners_reconcile", "labels_mapped_school_management"):
        results = {year_of[b]: r for (n, b), r in checks.items() if n == name}
        assert sorted(results) == ["2020-21", "2023-24", "2024-25", "2025-26"]
        assert all(r["status"] == "PASS" and r["expected"] == r["actual"] for r in results.values()), name
    rate = {year_of[b]: r["status"] for (n, b), r in checks.items() if n == "quarantine_rate"}
    assert rate == {"2020-21": "WARN", "2023-24": "PASS", "2024-25": "PASS", "2025-26": "PASS"}
    assert env.one(f"SELECT quarantine_reasons FROM {QUARANTINE}") == ["count_negative"]

    # A rerun rebuilds the same rows (D-025).
    snapshot = (env.q(content.format(CLEAN, "")), env.q(content.format(QUARANTINE, "")))
    env.bronze()
    again = env.silver()
    assert again.status == "succeeded" and again.run_id != first.run_id
    assert (env.q(content.format(CLEAN, "")), env.q(content.format(QUARANTINE, ""))) == snapshot


# --- The committed SQL, the mapping, and the command line ------------------------------------

MAPPINGS = sorted((REPO_ROOT / "config" / "mappings").glob("*.json"))


@pytest.mark.parametrize("mapping", MAPPINGS, ids=lambda p: p.stem)
@pytest.mark.parametrize("kind, path, function", [
    ("sql", "etl/03_silver/{clean_file}", "build_sql"),
    ("gate", "etl/03_silver/90_validate_{table}.sql", "gate_sql"),
    ("dictionary", "docs/data/silver/{doc}.md", "dictionary_markdown"),
])
def test_silver_files_match_the_mapping(mapping, kind, path, function):
    """Every source's committed Silver files equal what its generator writes (src/silver/generators.py)."""
    g = generator(mapping.stem, REPO_ROOT)
    generate = getattr(g, function)
    spec = g.load_spec(REPO_ROOT, mapping.stem)
    target = REPO_ROOT / path.format(
        table=spec.clean_table,
        clean_file=spec.clean_file,
        doc=spec.clean_table.replace("_", "-"),
    )
    assert target.is_file(), f"missing {target.relative_to(REPO_ROOT)}"
    assert target.read_text(encoding="utf-8") == generate(spec), (
        f"Regenerate: python -m src.silver.cli {kind} --source {mapping.stem} > {target.relative_to(REPO_ROOT)}")


def test_silver_names_come_from_the_table_registry():
    spec = load_spec(REPO_ROOT, "deped_enrollment")
    assert (spec.clean_table, spec.quarantine_table) == ("deped_enrollment_clean", "deped_enrollment_quarantine")


def _spec(mapping=None, contract=None):
    import yaml
    registry = yaml.safe_load((REPO_ROOT / "config" / "tables.yml").read_text(encoding="utf-8"))
    entry = next(s for s in registry["source_tables"] if s["source_id"] == "deped_enrollment")
    mapping = mapping or json.loads((REPO_ROOT / "config" / "mappings" / "deped_enrollment.json").read_text(encoding="utf-8"))
    return build_spec(mapping, contract or real_config(), entry)


def test_a_new_publisher_column_needs_a_reviewed_mapping():
    contract = real_config()
    contract["schema_versions"]["v3"] = {"first_school_year": "2026-27", "note": "test",
                                         "columns": columns("v2") + ["school_head"]}
    with pytest.raises(IngestionError, match="'school_head' must be classified exactly once"):
        _spec(contract=contract)
    contract["schema_versions"]["v3"]["columns"][-1] = "g13_male"   # a count is recognized by its name
    assert _spec(contract=contract).column("g13_male").kind == "count"


@pytest.mark.parametrize("break_it, message", [
    (lambda m: m["categories"]["sector"]["labels"].append({"published": "Charter", "standard": "Charter", "evidence": ""}),
     "not in the standard set"),
    (lambda m: m["categories"]["sector"]["labels"].append({"published": "Public", "standard": "Public", "evidence": ""}),
     "listed twice"),
    (lambda m: m["categories"]["sector"]["labels"].append({"published": "It's", "standard": "Public", "evidence": ""}),
     "quotes or backslashes"),
    (lambda m: m["booleans"]["true"].append("No"), "both true and false"),
    (lambda m: m.update(silver_table="enrollment_silver"), "config/tables.yml"),
    (lambda m: m["free_text_columns"].append("school_head"), "contract does not have"),
    (lambda m: m["count_columns"].update(plausible_max=10 ** 9), "plausible_max must be"),
])
def test_the_mapping_refuses_ambiguous_rules(break_it, message):
    mapping = json.loads((REPO_ROOT / "config" / "mappings" / "deped_enrollment.json").read_text(encoding="utf-8"))
    break_it(mapping)
    with pytest.raises(IngestionError, match=message):
        _spec(mapping=mapping)


def test_silver_sql_uses_only_what_both_engines_share():
    """DuckDB-only syntax would pass locally and fail on Databricks; backslashes in literals mean
    different things to the two engines; a ';' in a string would break store.split_statements."""
    for path in sorted((REPO_ROOT / "etl" / "03_silver").glob("*.sql")):
        code = "\n".join(line.split("--", 1)[0] for line in path.read_text(encoding="utf-8").splitlines())
        for token in ("\\", "::", "regexp_matches", "string_split", "regexp_replace_all", " EXCLUDE ", "[]"):
            assert token not in code, f"{path.name} uses {token!r}"
        assert not __import__("re").search(r"\blist_[a-z_]+\s*\(", code), f"{path.name} uses a DuckDB list function"
        for literal in __import__("re").findall(r"'[^']*'", code):
            assert ";" not in literal, f"{path.name}: ';' inside {literal}"


@pytest.mark.parametrize("databricks, duckdb", [
    ("regexp_like(x, '^[0-9]{6}$')", "regexp_matches(x, '^[0-9]{6}$')"),
    ("regexp_replace(x, ' +', ' ')", "regexp_replace_all(x, ' +', ' ')"),
    ("SELECT session.silver_run_id AS run_id", "SELECT getvariable('silver_run_id') AS run_id"),
])
def test_the_duckdb_translation_of_regular_expressions(databricks, duckdb):
    assert to_duckdb(databricks) == duckdb


def test_session_variables_work_locally_as_on_databricks(tmp_path):
    """A SQL task keeps one value for a whole file in a session variable (DECLARE, then SET from a
    job parameter); DuckDB skips the DECLARE and reads the variable through getvariable."""
    sql = tmp_path / "v.sql"
    sql.write_text("DECLARE OR REPLACE VARIABLE silver_run_id STRING;\n"
                   "SET VARIABLE silver_run_id = COALESCE(NULLIF(:run_id, ''), 'UNSET');\n"
                   "CREATE OR REPLACE TEMPORARY VIEW stamped AS SELECT session.silver_run_id AS run_id;\n")
    store = DuckDBStore()
    store.run_file(sql, {"run_id": "job-run-7"})
    assert store.query("SELECT run_id FROM stamped") == [("job-run-7",)]


def test_translated_regular_expressions_behave_like_spark():
    store = DuckDBStore()
    assert store.query("SELECT regexp_replace('a  b   c ', ' +', ' ')") == [("a b c ",)]   # every match, as Spark
    assert store.query("SELECT regexp_like('123456', '^[0-9]{6}$'), regexp_like('12345', '^[0-9]{6}$'), "
                       "regexp_like('x123456', '[0-9]{6}')") == [(True, False, True)]       # partial match, as rlike
    assert store.query("SELECT TRY_CAST('5.0' AS INT)") == [(5,)]   # why counts are checked as digits first


def test_whole_number_decimal_cast_is_explicit_for_databricks_compatibility():
    """Databricks does not cast '2.0' straight to BIGINT, so Personnel goes through DECIMAL."""
    spec = generator("deped_personnel", REPO_ROOT).load_spec(REPO_ROOT, "deped_personnel")
    sql = generator("deped_personnel", REPO_ROOT).build_sql(spec)
    assert "TRY_CAST(TRY_CAST(n.kinder_teachers_lgu_funding AS DECIMAL(38, 10)) AS BIGINT)" in sql
