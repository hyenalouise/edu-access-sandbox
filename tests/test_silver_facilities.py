"""Silver for deped_facilities: cleaning rules, flags, quarantine, the enrollment reference, and the gate.

Made-up facilities and enrollment deliveries (tests/factories/deped_deliveries.py) go
through the real Bronze pipeline into an in-memory DuckDB, then enrollment Silver
and facilities Silver run from the committed SQL files, in the job's order: the
facilities gate reads the published enrollment Silver. No real DepEd row is used.

By default every made-up school is public and offers elementary only, so its
junior and senior high columns are blank, as DepEd publishes them (profile O-4).
"""

import copy
import json
import uuid
from dataclasses import dataclass

import pytest
import yaml

from factories.deped_deliveries import (
    REPO_ROOT, approve, columns, empty_config, fake_repo, make_delivery, make_rows, real_config, with_values,
    write_config,
)
from src.ingestion.errors import IngestionError
from src.ingestion.pipeline import IngestionRun
from src.ingestion.store import DuckDBStore
from src.silver import deped_facilities as facilities
from src.silver.generators import generator
from src.silver.spec import load_spec as load_deped_spec

SOURCE = "deped_facilities"
REVISION = "e" * 40
CONTROL = "edu_access.`01-control`"
BRONZE = "edu_access.`02-bronze`.deped_facilities_raw"
CLEAN = "edu_access.`03-silver`.deped_facilities_clean"
QUARANTINE = "edu_access.`03-silver`.deped_facilities_quarantine"
CLEAN_CANDIDATE = "edu_access.`03-silver`.deped_facilities_clean_candidate"
BUILD, GATE = "02_clean_deped_facilities.sql", "90_validate_deped_facilities_clean.sql"
HEADER = columns("v1", SOURCE)
HIGH_SCHOOL = [c for c in HEADER if c.startswith(("jhs_", "shs_", "hs_"))]


@dataclass
class SilverResult:
    run_id: str
    status: str            # succeeded | failed | built (the gate was not run)
    error: str = None


def facility_rows(n=3, changes=None):
    """Made-up public elementary schools (IDs from 900001); changes = {row index: {column: value}}."""
    rows = make_rows(HEADER, n_rows=n)
    blank_high_school = {c: "" for c in HIGH_SCHOOL}
    return [with_values(HEADER, row, {**blank_high_school, **(changes or {}).get(i, {})}) for i, row in enumerate(rows)]


class Env:
    def __init__(self, tmp_path):
        self.config = empty_config(SOURCE)
        self.enrollment = empty_config("deped_enrollment")
        self.inbox = tmp_path / "landing" / "deped"
        self.repo = fake_repo(tmp_path / "repo", self.config)
        write_config(self.repo, self.enrollment)
        self.store = DuckDBStore()

    def deliver(self, rows=None, n_rows=3, enrollment_rows=None, folder="original", version=1):
        """A facilities delivery and, the first time, the same schools' enrollment (n_rows of them)."""
        path = make_delivery(self.inbox / folder, "2023-24", rows=rows if rows is not None else facility_rows(n_rows),
                             source_id=SOURCE)
        supersedes = self.config["deliveries"][-1]["archive_sha256"] if version > 1 else None
        approve(self.config, path, "2023-24", delivery_version=version, supersedes=supersedes)
        write_config(self.repo, self.config)
        if not self.enrollment["deliveries"]:          # the same school IDs, from 900001
            enrollment = make_delivery(self.inbox / "original", "2023-24", rows=enrollment_rows,
                                       n_rows=len(rows) if rows is not None else n_rows)
            approve(self.enrollment, enrollment, "2023-24")
            write_config(self.repo, self.enrollment)
        return path

    def bronze(self):
        for source in ("deped_enrollment", SOURCE):
            summary = IngestionRun(self.store, self.repo, source, self.inbox.parent, "local", REVISION).execute()
            assert summary.status == "succeeded", summary

    def silver(self, run_id=None, hook=None, gate=True):
        """Enrollment Silver (the facilities gate reads it), then the facilities build and gate."""
        run_id = run_id or str(uuid.uuid4())
        params = {"run_id": run_id, "code_revision": REVISION, "environment": "local"}
        folder = self.repo / "etl" / "03_silver"
        self.store.run_file(folder / "01_clean_deped_enrollment.sql", params)
        self.store.run_file(folder / "90_validate_deped_enrollment_clean.sql", params)
        try:
            self.store.run_file(folder / BUILD, params)
        except Exception as e:
            return SilverResult(run_id, "failed", f"build: {e}")
        if hook:
            hook()
        if not gate:
            return SilverResult(run_id, "built")
        try:
            self.store.run_file(folder / GATE, params)
        except Exception as e:
            return SilverResult(run_id, "failed", str(e))
        return SilverResult(run_id, "succeeded")

    def q(self, sql):
        return self.store.query(sql)

    def one(self, sql):
        return self.q(sql)[0][0]

    def rows(self, sql):
        return self.store.records(sql)

    def by_id(self, table=CLEAN):
        return {r["school_id"]: r for r in self.rows(f"SELECT * FROM {table}")}

    def silver_run(self, run_id):
        return self.rows(f"SELECT * FROM {CONTROL}.pipeline_runs WHERE run_id = '{run_id}' "
                         f"AND pipeline_name = 'silver_build' AND source_id = '{SOURCE}'")[0]

    def checks(self, run_id, status=None):
        where = f" AND status = '{status}'" if status else ""
        return {r["check_name"]: r for r in self.rows(
            f"SELECT * FROM {CONTROL}.data_quality_results WHERE run_id = '{run_id}' "
            f"AND source_id = '{SOURCE}' AND layer = 'silver'{where}")}


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


# --- Cleaning rules -------------------------------------------------------------------

def test_counts_and_yes_no_columns_are_typed_and_blanks_stay_null(env):
    env.deliver(facility_rows(3, {1: {"es_classrooms_non_instructional": "", "buildings_good_condition": "12",
                                      "es_has_playground": "", "es_has_garden": " True"}}))
    env.bronze()
    assert env.silver().status == "succeeded"
    row = env.by_id()["900002"]
    assert row["es_classrooms_non_instructional"] is None       # published blank: NULL, never 0
    assert row["buildings_good_condition"] == 12 and isinstance(row["buildings_good_condition"], int)
    assert row["jhs_classrooms_instructional"] is None          # a level the school does not offer
    assert row["es_has_playground"] is None                      # blank, not FALSE
    assert row["es_has_garden"] is True                          # whitespace normalized before mapping
    assert env.by_id()["900001"]["es_has_covered_court"] is True and env.by_id()["900002"]["es_has_covered_court"] is False
    types = dict(env.q("SELECT column_name, data_type FROM information_schema.columns "
                       "WHERE table_schema = '03-silver' AND table_name = 'deped_facilities_clean'"))
    spec = facilities.load_spec(REPO_ROOT)
    assert {types[c.name] for c in spec.counts} == {"INTEGER"} and len(spec.counts) == 21
    assert {types[c.name] for c in spec.facility_booleans} == {"BOOLEAN"} and len(spec.facility_booleans) == 60
    assert (types["school_id"], types["offers_es"], types["source_row_number"]) == ("VARCHAR", "BOOLEAN", "BIGINT")


def test_labels_map_to_enrollments_standard_set_and_overseas_is_flagged(env):
    env.deliver(facility_rows(3, {1: {"sector": "SUC/LUC", "school_management": "SUC"},
                                  2: {"sector": "PSO", "school_management": "PSO"}}))
    env.bronze()
    assert env.silver().status == "succeeded"
    got = env.by_id()
    assert (got["900002"]["sector"], got["900002"]["school_management"]) == ("SUC/LUC", "SUC")
    assert [got[i]["is_overseas"] for i in ("900001", "900002", "900003")] == [False, False, True]


def test_the_standard_sets_are_enrollments():
    """Gold compares sector and management across sources, so both use one standard set (D-022)."""
    spec, enrollment = facilities.load_spec(REPO_ROOT), load_deped_spec(REPO_ROOT, "deped_enrollment")
    for name in ("sector", "school_management"):
        assert spec.categories[name].standard == enrollment.categories[name].standard


def test_non_public_schools_are_kept_without_facility_data(env):
    no_values = {c: "" for c in HEADER if c in {x.name for x in facilities.load_spec(REPO_ROOT).facility_columns}}
    env.deliver(facility_rows(3, {1: {"sector": "Private", "school_management": "Sectarian", **no_values},
                                  2: no_values}))
    env.bronze()
    summary = env.silver()
    assert summary.status == "succeeded"
    got = env.by_id()
    assert len(got) == 3                                          # every school stays; Gold scopes to public
    assert [got[i]["has_facility_data"] for i in ("900001", "900002", "900003")] == [True, False, False]
    checks = env.checks(summary.run_id)
    assert checks["flag_public_without_facility_data"]["actual"] == "1"
    assert checks["facility_data_public_only"]["status"] == "PASS"


def test_a_blank_elementary_classroom_count_is_flagged_never_zero(env):
    env.deliver(facility_rows(4, {0: {"es_classrooms_instructional": ""},
                                  1: {"es_classrooms_instructional": "", "offers_es": "False",
                                      **{c: "" for c in HEADER if c.startswith("es_")}},
                                  2: {"es_classrooms_instructional": "", "sector": "Private", "school_management": "Sectarian"}}))
    env.bronze()
    summary = env.silver()
    assert summary.status == "succeeded"
    got = env.by_id()
    assert got["900001"]["es_classrooms_instructional"] is None and got["900001"]["es_classrooms_missing"] is True
    assert got["900002"]["es_classrooms_missing"] is False     # does not offer elementary: not applicable
    assert got["900003"]["es_classrooms_missing"] is False     # not public: outside the scope (O-3)
    assert got["900004"]["es_classrooms_missing"] is False
    assert env.checks(summary.run_id)["flag_es_classrooms_missing"]["actual"] == "1"


def test_flags_are_never_null(env):
    env.deliver(facility_rows(2, {1: {"sector": "", "offers_es": ""}}))
    env.bronze()
    env.silver()
    assert env.one(f"SELECT COUNT(*) FROM {CLEAN_CANDIDATE} WHERE is_overseas IS NULL "
                   "OR has_facility_data IS NULL OR es_classrooms_missing IS NULL") == 0


# --- Quarantine -----------------------------------------------------------------------

def test_bad_counts_are_quarantined_with_every_reason(env):
    env.deliver(facility_rows(400, {0: {"es_makeshift_rooms": "-1"}, 1: {"buildings_good_condition": "5.0"},
                                    2: {"es_classrooms_instructional": " 5", "buildings_for_demolition": "-2"}}))
    env.bronze()
    summary = env.silver()
    assert summary.status == "succeeded"                          # 3 of 400: WARN, not above 1%
    reasons = {r["school_id"]: r["quarantine_reasons"] for r in env.rows(f"SELECT * FROM {QUARANTINE}")}
    assert reasons == {"900001": ["count_negative"], "900002": ["count_uncastable"],
                       "900003": ["count_negative", "count_uncastable"]}   # ' 5' is not trimmed
    assert env.one(f"SELECT COUNT(*) FROM {CLEAN}") == 397
    assert env.checks(summary.run_id)["quarantine_rate"]["status"] == "WARN"


def test_each_group_has_its_own_plausible_maximum(env):
    env.deliver(facility_rows(200, {0: {"buildings_good_condition": "201"}, 1: {"buildings_good_condition": "200"},
                                    2: {"es_classrooms_instructional": "1000"}, 3: {"hs_makeshift_rooms": "1001",
                                                                                     "offers_jhs": "True"}}))
    env.bronze()
    summary = env.silver()
    assert summary.status == "succeeded"
    reasons = {r["school_id"]: r["quarantine_reasons"] for r in env.rows(f"SELECT * FROM {QUARANTINE}")}
    assert reasons == {"900001": ["count_above_plausible_max"], "900004": ["count_above_plausible_max"]}
    got = env.by_id()
    assert got["900002"]["buildings_good_condition"] == 200       # the maximum itself is kept
    assert got["900003"]["es_classrooms_instructional"] == 1000   # 201 buildings would be impossible; 201 rooms are not
    assert env.checks(summary.run_id)["quarantine_reason_count_above_plausible_max"]["status"] == "WARN"


def test_a_duplicated_school_quarantines_every_copy(env):
    rows = facility_rows(250)
    rows.append(list(rows[0]))
    env.deliver(rows)
    env.bronze()
    summary = env.silver()
    assert summary.status == "succeeded"
    assert env.q(f"SELECT school_id, quarantine_reasons FROM {QUARANTINE}") == [
        ("900001", ["school_id_duplicated"]), ("900001", ["school_id_duplicated"])]
    assert env.checks(summary.run_id)["rows_reconcile"]["actual"] == "251"


def test_quarantine_above_one_percent_fails_and_nothing_is_published(env):
    env.deliver(facility_rows(10, {0: {"es_makeshift_rooms": "-1"}}))
    env.bronze()
    summary = env.silver()
    assert summary.status == "failed" and env.silver_run(summary.run_id)["status"] == "failed"
    assert env.checks(summary.run_id)["quarantine_rate"]["status"] == "FAIL"
    assert not env.q("SELECT * FROM information_schema.tables WHERE table_name = 'deped_facilities_clean'")


# --- The gate -------------------------------------------------------------------------

def test_a_clean_load_passes_every_check(env):
    env.deliver(facility_rows(3))
    env.bronze()
    summary = env.silver()
    assert summary.status == "succeeded" and env.silver_run(summary.run_id)["status"] == "succeeded"
    checks = env.checks(summary.run_id)
    assert set(checks) == set(facilities.gate_checks(facilities.load_spec(REPO_ROOT)))
    assert {c["status"] for c in checks.values()} == {"PASS"}
    assert checks["school_id_in_enrollment"]["actual"] == "0"
    assert all(c["batch_id"] for name, c in checks.items() if name not in (
        "current_batches_present", "lineage_complete", "rows_resolve_to_current_bronze", "rows_built_by_this_run",
        "one_timestamp_per_run"))


def test_a_school_missing_from_enrollment_is_quarantined_and_the_rest_published(env):
    env.deliver(facility_rows(250), enrollment_rows=make_rows(columns("v1"), n_rows=249))   # 900250 has no enrollment row
    env.bronze()
    summary = env.silver()
    assert summary.status == "succeeded"                                         # 1 of 250: WARN, not above 1%
    assert env.q(f"SELECT school_id, quarantine_reasons FROM {QUARANTINE}") == [("900250", ["school_id_not_in_enrollment"])]
    assert env.one(f"SELECT COUNT(*) FROM {CLEAN}") == 249
    checks = env.checks(summary.run_id)
    assert checks["quarantine_reason_school_id_not_in_enrollment"]["status"] == "WARN"
    assert checks["school_id_in_enrollment"]["actual"] == "0"                  # no clean row is missing


def test_a_facilities_year_mostly_missing_from_enrollment_fails(env):
    """A wrong file, or a facilities year delivered before its enrollment year: above 1%, nothing is published."""
    env.deliver(facility_rows(3), enrollment_rows=make_rows(columns("v1"), n_rows=2))
    env.bronze()
    summary = env.silver()
    assert summary.status == "failed"
    assert env.checks(summary.run_id, "FAIL")["quarantine_rate"]["actual"] == "1"
    assert not env.q("SELECT * FROM information_schema.tables WHERE table_name = 'deped_facilities_clean'")


def test_a_school_enrollment_set_aside_is_set_aside_here_too(env):
    """Enrollment may quarantine up to 1% and still publish; facilities follows instead of failing."""
    enrollment = make_rows(columns("v1"), n_rows=250)
    enrollment[0] = with_values(columns("v1"), enrollment[0], {"g1_male": "-1"})
    env.deliver(facility_rows(250), enrollment_rows=enrollment)
    env.bronze()
    summary = env.silver()
    assert summary.status == "succeeded"
    assert env.q(f"SELECT school_id, quarantine_reasons FROM {QUARANTINE}") == [("900001", ["school_id_not_in_enrollment"])]
    assert env.one(f"SELECT COUNT(*) FROM {CLEAN}") == 249


@pytest.mark.parametrize("change, check", [
    ({"sector": "Charter"}, "labels_mapped_sector"),
    ({"es_has_garden": "Yes"}, "labels_mapped_facility_booleans"),
    ({"offers_es": "Y"}, "labels_mapped_offers_es"),
])
def test_an_unmapped_label_fails_the_gate(env, change, check):
    env.deliver(facility_rows(3, {1: change}))
    env.bronze()
    summary = env.silver()
    assert summary.status == "failed"
    assert env.checks(summary.run_id, "FAIL")[check]["actual"] == "1"


def test_an_unmapped_label_on_a_quarantined_row_still_fails_the_gate(env):
    env.deliver(facility_rows(150, {0: {"es_makeshift_rooms": "-1", "es_has_garden": "Yes"}}))
    env.bronze()
    summary = env.silver()
    assert summary.status == "failed"
    assert "labels_mapped_facility_booleans" in env.checks(summary.run_id, "FAIL")


@pytest.mark.parametrize("change, check", [
    ({"sector": "Private", "school_management": "Sectarian"}, "facility_data_public_only"),
    ({"jhs_classrooms_instructional": "4"}, "facility_values_within_offered_levels"),
    ({"hs_has_garden": "True"}, "facility_values_within_offered_levels"),
])
def test_a_scope_change_is_warned_and_published(env, change, check):
    env.deliver(facility_rows(3, {1: change}))
    env.bronze()
    summary = env.silver()
    assert summary.status == "succeeded"
    assert env.checks(summary.run_id)[check]["status"] == "WARN"
    assert env.one(f"SELECT COUNT(*) FROM {CLEAN}") == 3


@pytest.mark.parametrize("check, tamper", [
    ("rows_reconcile", f"DELETE FROM {CLEAN_CANDIDATE} WHERE school_id = '900001'"),
    ("counts_reconcile", f"UPDATE {CLEAN_CANDIDATE} SET buildings_good_condition = buildings_good_condition + 1"),
    ("missing_counts_stay_null", f"UPDATE {CLEAN_CANDIDATE} SET es_classrooms_non_instructional = 0 "
                                 "WHERE es_classrooms_non_instructional IS NULL"),
    ("true_values_reconcile", f"UPDATE {CLEAN_CANDIDATE} SET es_has_garden = TRUE WHERE es_has_garden = FALSE"),
    ("missing_booleans_stay_null", f"UPDATE {CLEAN_CANDIDATE} SET es_has_garden = FALSE WHERE es_has_garden IS NULL"),
    ("counts_within_plausible_max", f"UPDATE {CLEAN_CANDIDATE} SET buildings_good_condition = 201 WHERE school_id = '900001'"),
    ("school_id_unique", f"INSERT INTO {CLEAN_CANDIDATE} SELECT * FROM {CLEAN_CANDIDATE} WHERE school_id = '900001'"),
    ("rows_built_by_this_run", f"UPDATE {CLEAN_CANDIDATE} SET run_id = 'old'"),
])
def test_each_gate_check_fails_a_broken_build(env, check, tamper):
    env.deliver(facility_rows(3, {1: {"es_classrooms_non_instructional": ""}}))
    env.bronze()
    summary = env.silver(hook=lambda: env.store.sql(tamper))
    assert summary.status == "failed"
    assert check in env.checks(summary.run_id, "FAIL")


def test_check_results_hold_counts_not_values(env):
    env.deliver(facility_rows(3))
    env.bronze()
    summary = env.silver()
    actual = {r["actual"] for r in env.checks(summary.run_id).values()}
    assert "900001" not in actual and "Public" not in actual


def test_no_current_batch_fails_the_gate(env):
    path = make_delivery(env.inbox / "original", "2023-24")              # enrollment only
    approve(env.enrollment, path, "2023-24")
    write_config(env.repo, env.enrollment)
    env.bronze()
    summary = env.silver()
    assert summary.status == "failed"
    assert "current_batches_present" in env.checks(summary.run_id, "FAIL")


# --- Reruns and publishing (D-025) -------------------------------------------------------

def test_every_run_rebuilds_the_same_content(env):
    env.deliver(facility_rows(3))
    env.bronze()
    content = f"SELECT * EXCLUDE (run_id, cleaned_at_utc, code_revision) FROM {CLEAN} ORDER BY source_row_number"
    assert env.silver().status == "succeeded"
    first = env.q(content)
    assert env.silver().status == "succeeded"
    assert env.q(content) == first


def test_a_revision_replaces_the_school_year(env):
    env.deliver(facility_rows(3))
    env.bronze()
    env.silver()
    env.deliver(facility_rows(3, {0: {"buildings_good_condition": "9"}}), folder="revised", version=2)
    env.bronze()
    assert env.silver().status == "succeeded"
    assert env.q(f"SELECT DISTINCT delivery_version FROM {CLEAN}") == [(2,)]
    assert env.by_id()["900001"]["buildings_good_condition"] == 9


def test_a_failed_build_never_replaces_the_last_good_one(env):
    env.deliver(facility_rows(3))
    env.bronze()
    good = env.silver()
    assert good.status == "succeeded"
    env.deliver(facility_rows(3, {1: {"sector": "Charter"}}), folder="revised", version=2)
    env.bronze()
    bad = env.silver()
    assert bad.status == "failed"
    assert env.q(f"SELECT DISTINCT run_id FROM {CLEAN}") == [(good.run_id,)]
    assert env.q(f"SELECT DISTINCT run_id FROM {CLEAN_CANDIDATE}") == [(bad.run_id,)]


def test_lineage_and_run_stamp_on_every_row(env):
    env.deliver(facility_rows(3))
    env.bronze()
    summary = env.silver()
    rows = env.rows(f"SELECT * FROM {CLEAN}")
    assert {(r["run_id"], r["code_revision"], r["delivery_version"], r["schema_version"]) for r in rows} == {
        (summary.run_id, REVISION, 1, "v1")}
    assert sorted(r["source_row_number"] for r in rows) == [1, 2, 3]


# --- The generator and the rules file ----------------------------------------------------

def test_the_facilities_generator_is_chosen_by_its_rules_file():
    assert generator(SOURCE, REPO_ROOT) is facilities


def test_every_gate_check_is_written_by_the_gate_sql():
    spec = facilities.load_spec(REPO_ROOT)
    gate = facilities.gate_sql(spec)
    for name in facilities.gate_checks(spec):
        assert f"'{name}' AS check_name" in gate, name
    assert gate.count(" AS check_name") == len(facilities.gate_checks(spec))


def test_the_build_never_publishes_and_the_gate_publishes_clean_last():
    spec = facilities.load_spec(REPO_ROOT)
    build, gate = facilities.build_sql(spec), facilities.gate_sql(spec)
    for table in (spec.clean_table, spec.quarantine_table):
        assert f"CREATE OR REPLACE TABLE edu_access.`03-silver`.{table} USING" not in build
    order = [gate.index(m) for m in ("WHEN MATCHED AND s.fails > 0 THEN UPDATE SET", "raise_error(",
                                      f"CREATE OR REPLACE TABLE edu_access.`03-silver`.{spec.quarantine_table} USING",
                                      f"CREATE OR REPLACE TABLE edu_access.`03-silver`.{spec.clean_table} USING",
                                      "status = 'succeeded'")]
    assert order == sorted(order)


def _spec(mapping=None, contract=None):
    registry = yaml.safe_load((REPO_ROOT / "config" / "tables.yml").read_text(encoding="utf-8"))
    entries = {s["source_id"]: s for s in registry["source_tables"]}
    mapping = mapping or json.loads((REPO_ROOT / "config" / "mappings" / f"{SOURCE}.json").read_text(encoding="utf-8"))
    return facilities.build_spec(mapping, contract or real_config(SOURCE), entries[SOURCE], entries["deped_enrollment"])


def test_the_real_rules_classify_every_column():
    spec = _spec()
    kinds = [c.kind for c in spec.columns]
    assert (kinds.count("count"), kinds.count("boolean"), kinds.count("category")) == (21, 63, 2)
    assert {g.name: g.plausible_max for g in spec.groups} == {
        "buildings": 200, "classrooms": 1000, "temporary_and_makeshift": 1000}


def test_a_new_publisher_column_needs_a_reviewed_rule():
    contract = copy.deepcopy(real_config(SOURCE))
    contract["schema_versions"]["v1"]["columns"].append("es_wifi_rooms")
    with pytest.raises(IngestionError, match="'es_wifi_rooms' must be classified exactly once"):
        _spec(contract=contract)
    contract["schema_versions"]["v1"]["columns"][-1] = "es_has_wifi"     # a facility yes/no is recognized by its name
    assert _spec(contract=contract).column("es_has_wifi").kind == "boolean"


@pytest.mark.parametrize("break_it, message", [
    (lambda m: m.update(silver_table="facilities_silver"), "config/tables.yml"),
    (lambda m: m["count_groups"]["groups"]["buildings"]["columns"].append("es_classrooms_instructional"),
     "classified exactly once"),
    (lambda m: m["count_groups"]["groups"]["buildings"].update(plausible_max=0), "plausible_max"),
    (lambda m: m["categories"]["sector"]["labels"].append({"published": "Charter", "standard": "Charter"}),
     "not in the standard set"),
    (lambda m: m["booleans"].update(false=["False", "True"]), "both true and false"),
    (lambda m: m["public_scope"].update(value="Government"), "public_scope"),
    (lambda m: m["levels"]["prefixes"].update(es_=["sector"]), "offers_"),
    (lambda m: m["categories"]["sector"]["labels"].append({"published": "Pub'lic", "standard": "Public"}), "quotes"),
])
def test_the_rules_file_refuses_ambiguous_rules(break_it, message):
    mapping = json.loads((REPO_ROOT / "config" / "mappings" / f"{SOURCE}.json").read_text(encoding="utf-8"))
    break_it(mapping)
    with pytest.raises(IngestionError, match=message):
        _spec(mapping=mapping)
