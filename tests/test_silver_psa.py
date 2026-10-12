"""Silver for psa_poverty_stat: unpivot, missingness, flags, quarantine, the gate, and the run record.

Made-up workbooks (tests/factories/psa_workbooks.py) go through the real Bronze
pipeline into an in-memory DuckDB, then through the committed Silver SQL files,
run the way the job's two SQL tasks run them: the build, then the gate, with the
job parameters bound. No real PSA row is used.

The default workbook has two region banners and six units: a 5-digit ID, a
negative lower limit with full-precision numbers, a unit with no estimates, a
'(Continued)' label, a CV over 20, and a standard error that disagrees with CV.
"""

import copy
import json
import uuid
from dataclasses import dataclass

import pytest
import yaml

from factories.psa_workbooks import (
    REPO_ROOT, SOURCE, WORKBOOK, add_schema, approve, banner, default_rows, empty_config, fake_repo, real_config,
    unit, write_config, write_workbook,
)
from src.ingestion.errors import IngestionError
from src.ingestion.pipeline import IngestionRun
from src.ingestion.store import DuckDBStore
from src.silver import psa_poverty_stat as psa
from src.silver.generators import generator

REVISION = "c" * 40
YEARS = ("2018", "2021", "2023")
BRONZE = "edu_access.`02-bronze`.psa_poverty_stat_raw"
CLEAN = "edu_access.`03-silver`.psa_poverty_stat_clean"
QUARANTINE = "edu_access.`03-silver`.psa_poverty_stat_quarantine"
CLEAN_CANDIDATE = "edu_access.`03-silver`.psa_poverty_stat_clean_candidate"
QUARANTINE_CANDIDATE = "edu_access.`03-silver`.psa_poverty_stat_quarantine_candidate"
CONTROL = "edu_access.`01-control`"
BUILD = "05_clean_psa_poverty_stat.sql"
GATE = "90_validate_psa_poverty_stat_clean.sql"
MEASURES = ("poverty_incidence", "coefficient_of_variation", "standard_error", "ci90_lower_limit", "ci90_upper_limit")
CI = "90% Confidence Interval"
CONTENT = ("SELECT * EXCLUDE (run_id, cleaned_at_utc, code_revision) FROM {} "
           "ORDER BY estimate_year, source_sha256, source_row_number")


@dataclass
class SilverResult:
    run_id: str
    status: str            # succeeded | failed | built (the gate was not run)
    error: str = None


class Env:
    def __init__(self, tmp_path):
        self.config = empty_config()
        self.landing = tmp_path / "landing"
        self.inbox = self.landing / "psa"
        self.repo = fake_repo(tmp_path / "repo", self.config)
        self.store = DuckDBStore()

    def deliver(self, name=WORKBOOK, folder="original", years=YEARS, rows=None, **approve_kwargs):
        path = write_workbook(self.inbox / folder / name, years=years, rows=rows)
        approve(self.config, path, years=years, rows=rows, **approve_kwargs)
        write_config(self.repo, self.config)
        return path

    def bronze(self):
        summary = IngestionRun(self.store, self.repo, SOURCE, self.landing, "local", REVISION).execute()
        assert summary.status == "succeeded", summary
        return summary

    def regenerate_silver(self):
        """What a reviewer does after approving a new schema version: regenerate the Silver SQL."""
        registry = yaml.safe_load((self.repo / "config" / "tables.yml").read_text(encoding="utf-8"))
        entry = next(s for s in registry["source_tables"] if s["source_id"] == SOURCE)
        mapping = json.loads((self.repo / "config" / "mappings" / f"{SOURCE}.json").read_text(encoding="utf-8"))
        spec = psa.build_spec(mapping, self.config, entry)
        (self.repo / "etl" / "03_silver" / BUILD).write_text(psa.build_sql(spec), encoding="utf-8")
        (self.repo / "etl" / "03_silver" / GATE).write_text(psa.gate_sql(spec), encoding="utf-8")
        return spec

    def silver(self, run_id=None, hook=None, gate=True):
        """The job's two Silver SQL tasks: the build, then (if it succeeded) the gate."""
        run_id = run_id or str(uuid.uuid4())
        params = {"run_id": run_id, "code_revision": REVISION, "environment": "local"}
        folder = self.repo / "etl" / "03_silver"
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

    def silver_run(self, run_id):
        return self.rows(f"SELECT * FROM {CONTROL}.pipeline_runs WHERE run_id = '{run_id}' "
                         f"AND pipeline_name = 'silver_build' AND source_id = '{SOURCE}'")[0]

    def checks(self, run_id, status=None):
        where = f" AND status = '{status}'" if status else ""
        return {(r["check_name"], r["batch_id"]): r for r in self.rows(
            f"SELECT * FROM {CONTROL}.data_quality_results WHERE run_id = '{run_id}' AND source_id = '{SOURCE}'{where}")}

    def check_names(self, run_id, status):
        return sorted({name for name, _ in self.checks(run_id, status)})

    def row(self, psgc_id, year, table=CLEAN):
        found = self.rows(f"SELECT * FROM {table} WHERE psgc_id = '{psgc_id}' AND estimate_year = {int(year)}")
        assert len(found) == 1, found
        return found[0]


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def many_units(n=250, changes=None, first_id=99101):
    """A banner, then n made-up units with 5-digit IDs; changes = {unit index: {Bronze column: value}}."""
    rows = [banner("Test Region Many")]
    for i in range(n):
        rows.append(unit(str(first_id + i), f"Town {i}", YEARS, seed=1 + i % 7, overrides=(changes or {}).get(i)))
    return rows


# --- Shape: one row per unit and estimate year --------------------------------------------

def test_wide_rows_are_unpivoted_to_one_row_per_unit_and_year(env):
    env.deliver()
    env.bronze()
    assert env.silver().status == "succeeded"
    assert env.q(f"SELECT estimate_year, COUNT(*) FROM {CLEAN} GROUP BY 1 ORDER BY 1") == [(int(y), 6) for y in YEARS]
    assert env.one(f"SELECT COUNT(*) FROM {QUARANTINE}") == 0
    assert env.one(f"SELECT COUNT(*) - COUNT(DISTINCT (psgc_id, estimate_year)) FROM {CLEAN}") == 0
    # The year's five measures stay together, each from the column of that year.
    bronze = env.rows(f"SELECT * FROM {BRONZE} WHERE `PSGC ID` = '990104'")[0]
    for y in YEARS:
        r = env.row("990104", y)
        assert r["poverty_incidence"] == float(bronze[f"Poverty Incidence {y}"])
        assert r["coefficient_of_variation"] == float(bronze[f"Coefficient of Variation {y}"])
        assert r["standard_error"] == float(bronze[f"Standard Error {y}"])
        assert r["ci90_lower_limit"] == float(bronze[f"{CI} Lower Limit {y}"])
        assert r["ci90_upper_limit"] == float(bronze[f"{CI} Upper Limit {y}"])
        assert r["estimate_status"] == "estimated"
    types = dict(env.q("SELECT column_name, data_type FROM information_schema.columns "
                       "WHERE table_schema = '03-silver' AND table_name = 'psa_poverty_stat_clean'"))
    assert {types[m] for m in MEASURES} == {"DOUBLE"}
    assert (types["estimate_year"], types["psgc_id"], types["cv_over_20"]) == ("INTEGER", "VARCHAR", "BOOLEAN")


def test_ids_are_padded_and_the_correspondence_code_is_built_not_the_psgc_code(env):
    env.deliver()
    env.bronze()
    env.silver()
    five, six = env.row("099101", "2018"), env.row("990102", "2018")
    assert (five["psgc_id"], five["correspondence_code"]) == ("099101", "099101000")
    assert (six["psgc_id"], six["correspondence_code"]) == ("990102", "990102000")
    assert "psgc_id_published" not in five and "province_code_prefix" not in five      # not carried into Silver
    assert env.one(f"SELECT MAX(length(correspondence_code)) FROM {CLEAN}") == 9   # never the 10-digit PSGC code
    assert env.one(f"SELECT `PSGC ID` FROM {BRONZE} WHERE `PSGC ID` = '99101'") == "99101"   # Bronze keeps it


def test_regions_are_carried_down_and_province_labels_stay_in_bronze(env):
    env.deliver()
    env.bronze()
    env.silver()
    got = {r["psgc_id"]: r for r in env.rows(f"SELECT * FROM {CLEAN} WHERE estimate_year = 2023")}
    assert {k: v["region"] for k, v in got.items()} == {
        "099101": "Test Region Alpha", "099102": "Test Region Alpha", "099103": "Test Region Alpha",
        "990102": "Test Region Beta", "990103": "Test Region Beta", "990104": "Test Region Beta"}
    assert "province_label_published" not in got["099101"]                # province comes from PSGC in Integration
    assert env.one(f"SELECT `Region/Province` FROM {BRONZE} WHERE `PSGC ID` = '990102'") == "(Continued)"  # kept in Bronze
    assert got["099102"]["municipality"] == "San Test (Old Town)"    # former name stays
    assert got["099101"]["municipality"] == "Doña Test"
    banner_rows = env.q(f"SELECT source_row_number FROM {BRONZE} WHERE source_row_kind = 'region_banner'")
    assert env.one(f"SELECT COUNT(*) FROM {CLEAN} WHERE source_row_number IN ({', '.join(str(r[0]) for r in banner_rows)})") == 0


def test_text_whitespace_is_normalized_but_names_are_not_rewritten(env):
    rows = default_rows()
    rows[1] = {**rows[1], "Municipality/City": " Doña\tTest  (Old  Name) ", "Region/Province": "Province  of Test"}
    env.deliver(rows=rows)
    env.bronze()
    assert env.silver().status == "succeeded"
    r = env.row("099101", "2021")
    assert r["municipality"] == "Doña Test (Old Name)"


# --- Missingness: NULL is never zero ------------------------------------------------------

def test_a_unit_with_no_estimates_stays_with_null_measures_and_no_estimate(env):
    env.deliver()
    env.bronze()
    summary = env.silver()
    assert summary.status == "succeeded"
    for y in YEARS:
        r = env.row("099103", y)
        assert [r[m] for m in MEASURES] == [None] * 5                      # blank, never 0
        assert r["estimate_status"] == "no_estimate"
        assert (r["cv_over_20"], r["se_cv_inconsistent"], r["lower_limit_not_positive"]) == (False, False, False)
    assert env.one(f"SELECT COUNT(*) FROM {QUARANTINE}") == 0              # not a malformed record
    assert env.one(f"SELECT `Poverty Incidence 2023` FROM {BRONZE} WHERE `PSGC ID` = '99103'") == ""
    records = {name: r["actual"] for (name, _), r in env.checks(summary.run_id).items()}
    assert [records[f"rule_no_estimate_{y}"] for y in YEARS] == ["1", "1", "1"]
    assert [records[f"rule_blank_measures_to_null_{y}"] for y in YEARS] == ["5", "5", "5"]


def test_a_partly_blank_estimate_is_kept_and_warned(env):
    rows = default_rows()
    rows[7] = {**rows[7], "Standard Error 2021": ""}
    env.deliver(rows=rows)
    env.bronze()
    summary = env.silver()
    assert summary.status == "succeeded"
    r = env.row("990104", "2021")
    assert (r["standard_error"], r["estimate_status"]) == (None, "partial_estimate")
    assert env.row("990104", "2018")["estimate_status"] == "estimated"
    assert "flag_partial_estimate_2021" in env.check_names(summary.run_id, "WARN")


def test_an_absent_measure_is_null_and_named_by_schema_version():
    """A schema version without a measure column: Silver selects NULL there, and the dictionary says which
    schema version never publishes it, so NULL-because-absent is told apart from a published blank."""
    contract = copy.deepcopy(real_config())
    v2 = copy.deepcopy(contract["schema_versions"]["v1"])
    v2["columns"] = [c for c in v2["columns"] if c != "Standard Error 2023"]
    contract["schema_versions"]["v2"] = v2
    spec = _spec(contract=contract)
    assert spec.absent == {"v2": [("2023", "standard_error")]}
    assert spec.year_columns["2023"]["standard_error"] == "Standard Error 2023"   # v1 still publishes it
    assert "| `v2` | 2023 `standard_error` |" in psa.dictionary_markdown(spec)


# --- Numbers: decimal and scientific notation, no rounding --------------------------------

def test_full_precision_and_scientific_notation_are_kept_without_rounding(env):
    env.deliver()
    env.bronze()
    env.silver()
    r = env.row("099102", "2023")
    assert r["ci90_lower_limit"] == float("-2.4063453271442992E-2")
    assert r["poverty_incidence"] == float("0.69430000000000003")
    assert r["ci90_lower_limit"] != round(r["ci90_lower_limit"], 4)        # not rounded for display
    assert env.one(f"SELECT `{CI} Lower Limit 2023` FROM {BRONZE} WHERE `PSGC ID` = '99102'") == "-2.4063453271442992E-2"


# --- Statistical warnings: flagged, never corrected ---------------------------------------

def test_statistical_warnings_are_flagged_and_values_are_not_changed(env):
    env.deliver()
    env.bronze()
    summary = env.silver()
    assert summary.status == "succeeded"
    assert env.row("990102", "2018")["cv_over_20"] is True and env.row("990102", "2018")["coefficient_of_variation"] == 25.25
    assert env.row("990102", "2021")["cv_over_20"] is False
    assert env.row("990103", "2018")["se_cv_inconsistent"] is True and env.row("990103", "2018")["standard_error"] == 9.99
    neg = env.row("099102", "2023")
    assert neg["lower_limit_not_positive"] is True and neg["ci90_lower_limit"] < 0   # not clipped
    assert env.one(f"SELECT COUNT(*) FROM {CLEAN} WHERE cv_over_20 IS NULL OR se_cv_inconsistent IS NULL "
                   "OR lower_limit_not_positive IS NULL") == 0                         # never NULL
    warned = env.check_names(summary.run_id, "WARN")
    assert {"flag_cv_over_20_2018", "flag_se_cv_inconsistent_2018", "flag_lower_limit_not_positive_2023"} <= set(warned)
    assert not [n for n in warned if n.startswith("quarantine")]
    flagged = {name: r["actual"] for (name, _), r in env.checks(summary.run_id).items()}
    expected = {y: env.one(f"SELECT COUNT_IF(cv_over_20) FROM {CLEAN} WHERE estimate_year = {y}") for y in YEARS}
    assert {y: int(flagged[f"flag_cv_over_20_{y}"]) for y in YEARS} == expected


# --- Quarantine -----------------------------------------------------------------------------

def test_malformed_measures_and_ranges_are_quarantined_per_year_with_every_reason(env):
    env.deliver(rows=many_units(250, {
        3: {"Coefficient of Variation 2021": "n.a."},                                   # only 2021 is set aside
        7: {"Poverty Incidence 2018": "120"},                                           # above 100, outside its interval
        9: {"Standard Error 2023": "-1.5", "Coefficient of Variation 2023": "-2"},
        11: {f"{CI} Lower Limit 2021": "40", f"{CI} Upper Limit 2021": "30"},
    }))
    env.bronze()                                                                        # Bronze keeps and WARNs
    summary = env.silver()
    assert summary.status == "succeeded", summary.error                                 # 1 or 2 of 250 per year: WARN
    got = {(r["psgc_id"], r["estimate_year"]): r["quarantine_reasons"] for r in env.rows(f"SELECT * FROM {QUARANTINE}")}
    assert got == {
        ("099104", 2021): ["measure_uncastable"],
        ("099108", 2018): ["incidence_out_of_range", "ci_inconsistent"],
        ("099110", 2023): ["cv_negative", "se_negative"],
        ("099112", 2021): ["ci_inconsistent"],
    }
    assert env.one(f"SELECT COUNT(*) FROM {CLEAN} WHERE psgc_id = '099104'") == 2   # 2018 and 2023 stay clean
    assert env.one(f"SELECT COUNT(*) FROM {CLEAN}") + env.one(f"SELECT COUNT(*) FROM {QUARANTINE}") == 750
    rate = {name: r["status"] for (name, _), r in env.checks(summary.run_id).items() if name.startswith("quarantine_rate")}
    assert rate == {"quarantine_rate_2018": "WARN", "quarantine_rate_2021": "WARN", "quarantine_rate_2023": "WARN"}
    assert env.one(f"SELECT COUNT(*) FROM {BRONZE} WHERE source_row_kind = 'unit'") == 250   # Bronze untouched


def test_a_measure_with_surrounding_spaces_is_quarantined_not_trimmed(env):
    env.deliver(rows=many_units(200, {0: {"Poverty Incidence 2018": " 12.5"}}))
    env.bronze()
    assert env.silver().status == "succeeded"
    assert env.q(f"SELECT psgc_id, estimate_year, quarantine_reasons FROM {QUARANTINE}") == [
        ("099101", 2018, ["measure_uncastable"])]


def test_a_duplicated_id_quarantines_every_copy_in_every_year(env):
    rows = many_units(250)
    rows.append(unit("99101", "Town Again", YEARS, seed=3))                            # same ID, another Excel row
    env.deliver(rows=rows)
    env.bronze()
    summary = env.silver()
    assert summary.status == "succeeded"                                               # 2 of 251 per year: WARN
    dup = env.q(f"SELECT estimate_year, COUNT(*) FROM {QUARANTINE} WHERE array_contains(quarantine_reasons, "
                "'psgc_id_duplicated') GROUP BY 1 ORDER BY 1")
    assert dup == [(int(y), 2) for y in YEARS]
    assert env.one(f"SELECT COUNT(*) FROM {CLEAN} WHERE psgc_id = '099101'") == 0     # neither copy is chosen


def test_quarantine_above_one_percent_fails_and_nothing_is_published(env):
    rows = default_rows()
    rows[7] = {**rows[7], "Poverty Incidence 2021": "abc"}                              # 1 of 6 units in 2021
    env.deliver(rows=rows)
    env.bronze()
    summary = env.silver()
    assert summary.status == "failed" and "Silver gate failed" in summary.error
    assert env.check_names(summary.run_id, "FAIL") == ["quarantine_rate_2021"]
    run = env.silver_run(summary.run_id)
    assert (run["status"], run["failure_stage"]) == ("failed", "gate")
    assert not env.q("SELECT * FROM information_schema.tables WHERE table_name = 'psa_poverty_stat_clean'")


def test_blank_null_and_malformed_ids_are_quarantined_without_losing_a_row(env):
    """A NULL ID makes NULL-unsafe conditions NULL; every candidate must still land in one table."""
    env.deliver(rows=many_units(400))
    env.bronze()
    for number, value in ((901, "NULL"), (902, "''"), (903, "'1234567'"), (904, "'12a45'")):  # Bronze refuses these
        env.store.sql(f"INSERT INTO {BRONZE} SELECT * REPLACE ({value} AS `PSGC ID`, {number} AS source_row_number) "
                      f"FROM {BRONZE} WHERE `PSGC ID` = '99101'")
    summary = env.silver()
    assert summary.status == "succeeded", summary.error                                 # 4 of 404 per year: WARN
    reasons = {(r[0], r[1]) for r in env.q(f"SELECT source_row_number, quarantine_reasons[1] FROM {QUARANTINE}")}
    assert reasons == {(901, "psgc_id_blank"), (902, "psgc_id_blank"), (903, "psgc_id_malformed"),
                       (904, "psgc_id_malformed")}
    assert env.one(f"SELECT COUNT(*) FROM {QUARANTINE}") == 4 * 3
    assert env.one(f"SELECT COUNT(*) FROM {CLEAN}") + env.one(f"SELECT COUNT(*) FROM {QUARANTINE}") == 404 * 3
    reconciled = [r for (name, _), r in env.checks(summary.run_id).items() if name.startswith("rows_reconcile_")]
    assert sorted((r["expected"], r["actual"], r["status"]) for r in reconciled) == [("404", "404", "PASS")] * 3


# --- The gate -------------------------------------------------------------------------------

def test_a_clean_load_passes_every_check_and_accounts_for_structural_rows(env):
    env.deliver()
    env.bronze()
    summary = env.silver()
    assert summary.status == "succeeded"
    checks = env.checks(summary.run_id)
    assert {r["status"] for r in checks.values()} == {"PASS", "WARN"}
    assert not env.check_names(summary.run_id, "FAIL")
    spec = psa.load_spec(REPO_ROOT)
    scopes = [scope for _, scope, _ in psa.gate_checks(spec)]
    assert len(checks) == scopes.count("whole") + scopes.count("batch") + 3 * scopes.count("year")
    records = {name: r for (name, _), r in checks.items()}
    sheet_rows = env.one(f"SELECT COUNT(*) FROM {BRONZE}")
    assert (records["bronze_rows_accounted"]["expected"], records["bronze_rows_accounted"]["actual"]) == (str(sheet_rows),) * 2
    assert {k: records[f"rows_kind_{k}"]["actual"] for k in ("title", "header", "region_banner", "footer")} == {
        "title": "1", "header": "4", "region_banner": "2", "footer": "6"}
    assert records["rule_structural_rows_not_estimates"]["actual"] == str(sheet_rows - 6)
    assert [records[f"rows_reconcile_{y}"]["actual"] for y in YEARS] == ["6", "6", "6"]
    assert [records[f"rule_psgc_id_padded_{y}"]["actual"] for y in YEARS] == ["3", "3", "3"]
    assert {r["code_revision"] for r in env.rows(f"SELECT * FROM {CONTROL}.data_quality_results "
                                                 f"WHERE run_id = '{summary.run_id}'")} == {REVISION}


BROKEN_BUILDS = [
    ("poverty_incidence_matches_bronze_2018", "poverty_incidence = poverty_incidence + 0.000001", "2018"),
    ("coefficient_of_variation_matches_bronze_2021", "coefficient_of_variation = round(coefficient_of_variation, 1) + 0.01", "2021"),
    ("standard_error_matches_bronze_2023", "standard_error = 0", "2023"),
    ("ci90_lower_limit_matches_bronze_2023", "ci90_lower_limit = 0", "2023"),
    ("ci90_upper_limit_matches_bronze_2018", "ci90_upper_limit = NULL", "2018"),
    ("psgc_id_valid_2018", "psgc_id = '99101'", "2018"),
    ("psgc_id_valid_2021", "correspondence_code = psgc_id || '0000'", "2021"),
    ("estimate_status_valid_2023", "estimate_status = 'no_estimate'", "2023"),
    ("flags_consistent_2018", "cv_over_20 = NOT cv_over_20", "2018"),
    ("region_banner_assigned_2021", "region = NULL", "2021"),
    ("poverty_incidence_within_bounds_2018", "poverty_incidence = 150", "2018"),
    ("cv_non_negative_2018", "coefficient_of_variation = -1", "2018"),
    ("se_non_negative_2018", "standard_error = -1", "2018"),
    ("ci_contains_estimate_2018", "ci90_lower_limit = ci90_upper_limit + 1", "2018"),
    ("estimate_year_covered_2018", "estimate_years_covered = '2021,2023'", "2018"),
    ("rows_resolve_to_current_bronze_units", "source_row_number = 6", "2018"),        # the region banner's row
    ("one_timestamp_per_run", "cleaned_at_utc = cleaned_at_utc + INTERVAL 1 SECOND", "2018"),
    ("lineage_complete", "batch_id = NULL", "2018"),
    ("rows_built_by_this_run", "run_id = 'an-old-run'", "2018"),
]


@pytest.mark.parametrize("check, tamper, year", BROKEN_BUILDS, ids=[c for c, _, _ in BROKEN_BUILDS])
def test_each_gate_check_fails_a_broken_build(env, check, tamper, year):
    """Checks the cleaning rules cannot trip on their own: each must still fail a build that breaks it."""
    env.deliver()
    env.bronze()
    summary = env.silver(hook=lambda: env.store.sql(
        f"UPDATE {CLEAN_CANDIDATE} SET {tamper} WHERE psgc_id = '990104' AND estimate_year = {year}"))
    assert summary.status == "failed"
    assert check in env.check_names(summary.run_id, "FAIL")


def test_the_gate_catches_a_blank_turned_into_zero_and_a_lost_row(env):
    env.deliver()
    env.bronze()

    def tamper():
        env.store.sql(f"UPDATE {CLEAN_CANDIDATE} SET poverty_incidence = 0 WHERE psgc_id = '099103'")
        env.store.sql(f"DELETE FROM {CLEAN_CANDIDATE} WHERE psgc_id = '990104' AND estimate_year = 2021")
        env.store.sql(f"INSERT INTO {CLEAN_CANDIDATE} SELECT * FROM {CLEAN_CANDIDATE} "
                      "WHERE psgc_id = '990103' AND estimate_year = 2023")

    summary = env.silver(hook=tamper)
    failed = env.check_names(summary.run_id, "FAIL")
    assert {"missing_measures_stay_null_2018", "poverty_incidence_matches_bronze_2018", "rows_reconcile_2021",
            "psgc_id_unique_2023", "rows_reconcile_2023"} <= set(failed)


def test_check_results_hold_counts_not_values(env):
    env.deliver()
    env.bronze()
    summary = env.silver()
    texts = [str(v) for r in env.checks(summary.run_id).values() for v in (r["expected"], r["actual"])]
    assert not [t for t in texts if "Test" in t or "Doña" in t or "." in t]


def test_no_current_batch_fails_the_gate(env):
    from src.ingestion import control
    control.create_tables(env.store, env.repo)
    env.store.run_file(env.repo / "etl" / "02_bronze" / "05_create_psa_poverty_stat_raw.sql")
    summary = env.silver()
    assert summary.status == "failed"
    assert "current_batches_present" in env.check_names(summary.run_id, "FAIL")


# --- Which Bronze rows: current batches, revisions, new years -------------------------------

def test_only_current_batches_are_read_and_a_revision_replaces_the_dataset(env):
    env.deliver()
    env.bronze()
    assert env.silver().status == "succeeded"
    revised_rows = default_rows()[:-1]
    revised_rows[1] = {**revised_rows[1], "Poverty Incidence 2021": "14.6"}
    env.deliver(folder="2026-12-01", rows=revised_rows, delivery_version=2,
                supersedes=env.config["deliveries"][0]["workbook_sha256"])
    env.bronze()
    assert env.q(f"SELECT delivery_version, COUNT(*) FROM {BRONZE} WHERE source_row_kind = 'unit' "
                 "GROUP BY 1 ORDER BY 1") == [(1, 6), (2, 5)]                         # both versions kept
    summary = env.silver()
    assert summary.status == "succeeded"
    assert env.q(f"SELECT DISTINCT delivery_version FROM {CLEAN}") == [(2,)]
    assert env.q(f"SELECT estimate_year, COUNT(*) FROM {CLEAN} GROUP BY 1 ORDER BY 1") == [(int(y), 5) for y in YEARS]
    assert env.row("099101", "2021")["poverty_incidence"] == 14.6                       # v2's value
    assert env.one(f"SELECT COUNT(*) FROM {CLEAN} WHERE psgc_id = '990104'") == 0     # not in v2


def test_a_revision_that_adds_a_year_needs_regenerated_silver_and_then_keeps_every_year(env):
    env.deliver()
    env.bronze()
    good = env.silver()
    years = ("2018", "2021", "2023", "2025")
    add_schema(env.config, "v2", years)
    env.deliver("2_2025 SAE_with PSGC_noHUC_01Feb2028.xlsx", folder="2027-12-01", years=years,
                rows=default_rows(years), schema_version="v2", delivery_version=2,
                supersedes=env.config["deliveries"][0]["workbook_sha256"])
    env.bronze()
    stale = env.silver()                                                    # Silver SQL still knows three years
    assert stale.status == "failed"
    assert "estimate_years_known" in env.check_names(stale.run_id, "FAIL")
    assert env.q(f"SELECT DISTINCT run_id FROM {CLEAN}") == [(good.run_id,)]   # the last good build stays published
    spec = env.regenerate_silver()
    assert spec.years == list(years)
    fresh = env.silver()
    assert fresh.status == "succeeded", fresh.error
    assert env.q(f"SELECT estimate_year, delivery_version, COUNT(*) FROM {CLEAN} GROUP BY 1, 2 ORDER BY 1") == [
        (int(y), 2, 6) for y in years]


def test_region_labels_are_not_carried_across_deliveries(env):
    """Two logical datasets: a unit above the first banner of the second workbook must not inherit the
    last banner of the first one, so the gate fails instead of guessing."""
    env.deliver()
    years = ("2025",)
    add_schema(env.config, "v2", years)
    rows = [unit("99901", "Orphan Town", years, seed=2)] + default_rows(years, first_id=99201)
    env.deliver("2_2025 SAE_with PSGC_noHUC_01Feb2028.xlsx", folder="2027-12-01", years=years, rows=rows,
                schema_version="v2", logical_dataset="sae_city_municipal_2025")
    env.bronze()
    env.regenerate_silver()
    summary = env.silver()
    assert summary.status == "failed"
    assert env.check_names(summary.run_id, "FAIL") == ["region_banner_assigned_2025"]
    orphan = env.row("099901", "2025", CLEAN_CANDIDATE)
    assert orphan["region"] is None
    assert env.row("099201", "2025", CLEAN_CANDIDATE)["region"] == "Test Region Alpha"


# --- Rebuilds and the run record ------------------------------------------------------------

def test_repeated_full_rebuilds_give_identical_business_content(env):
    env.deliver(rows=many_units(200, {5: {"Poverty Incidence 2023": "abc"}}))
    env.bronze()
    first = env.silver()
    before = (env.q(CONTENT.format(CLEAN)), env.q(CONTENT.format(QUARANTINE)))
    env.bronze()                                                            # a Bronze rerun that loads nothing new
    again = env.silver()
    assert first.status == again.status == "succeeded" and first.run_id != again.run_id
    assert (env.q(CONTENT.format(CLEAN)), env.q(CONTENT.format(QUARANTINE))) == before
    assert (env.one(f"SELECT COUNT(*) FROM {CLEAN}"), env.one(f"SELECT COUNT(*) FROM {QUARANTINE}")) == (599, 1)
    assert env.q(f"SELECT DISTINCT run_id FROM {CLEAN}") == [(again.run_id,)]
    assert env.silver_run(first.run_id)["status"] == env.silver_run(again.run_id)["status"] == "succeeded"


def test_a_failed_build_never_replaces_the_last_good_one(env):
    env.deliver()
    env.bronze()
    good = env.silver()
    bad = env.silver(hook=lambda: env.store.sql(f"UPDATE {CLEAN_CANDIDATE} SET standard_error = -1"))
    assert bad.status == "failed" and env.silver_run(bad.run_id)["status"] == "failed"
    assert env.q(f"SELECT run_id, COUNT(*) FROM {CLEAN} GROUP BY 1") == [(good.run_id, 18)]
    assert env.q(f"SELECT DISTINCT run_id FROM {CLEAN_CANDIDATE}") == [(bad.run_id,)]   # kept for review


def test_a_run_is_succeeded_only_after_its_gate_passes_and_carries_lineage(env):
    env.deliver(rows=many_units(150, {0: {"Poverty Incidence 2018": "-3"}}))
    env.bronze()
    built = env.silver(gate=False)
    run = env.silver_run(built.run_id)
    assert (run["status"], run["environment"], run["code_revision"], run["job_run_id"]) == (
        "running", "local", REVISION, built.run_id)
    done = env.silver()
    assert env.silver_run(done.run_id)["status"] == "succeeded"
    assert env.silver_run(built.run_id)["status"] == "running"                       # never mistaken for good
    joined = env.one(f"SELECT COUNT(*) FROM {CLEAN} AS c JOIN {BRONZE} AS b "
                     "ON c.source_sha256 = b.source_sha256 AND c.source_row_number = b.source_row_number "
                     "AND c.batch_id = b.batch_id AND c.psgc_id = lpad(b.`PSGC ID`, 6, '0') "
                     "AND c.delivery_version = b.delivery_version AND c.schema_version = b.schema_version "
                     "AND c.logical_dataset = b.logical_dataset AND b.source_row_kind = 'unit'")
    assert joined == env.one(f"SELECT COUNT(*) FROM {CLEAN}") == 449
    stamps = env.q(f"SELECT DISTINCT run_id, cleaned_at_utc, code_revision FROM {CLEAN} "
                   f"UNION SELECT DISTINCT run_id, cleaned_at_utc, code_revision FROM {QUARANTINE}")
    assert len(stamps) == 1 and stamps[0][0] == done.run_id and stamps[0][2] == REVISION
    assert env.silver_run(done.run_id)["started_at_utc"] == stamps[0][1]


def test_a_repaired_run_is_judged_by_its_own_checks(env):
    env.deliver()
    env.bronze()
    first = env.silver(run_id="job-run-9", hook=lambda: env.store.sql(f"DELETE FROM {CLEAN_CANDIDATE} WHERE psgc_id = '990104'"))
    assert first.status == "failed"
    repaired = env.silver(run_id="job-run-9")
    assert repaired.status == "succeeded"
    assert env.silver_run("job-run-9")["status"] == "succeeded"


# --- The committed files and the rules file -------------------------------------------------

def test_the_psa_generator_is_chosen_by_its_rules_file():
    assert generator(SOURCE, REPO_ROOT) is psa
    assert generator("deped_enrollment", REPO_ROOT).build_sql.__module__ == "src.silver.sql"


def test_committed_psa_files_match_the_generator(repo_root):
    spec = psa.load_spec(repo_root)
    for path, text in ((f"etl/03_silver/{BUILD}", psa.build_sql(spec)), (f"etl/03_silver/{GATE}", psa.gate_sql(spec)),
                       ("docs/data/silver/psa-poverty-stat-clean.md", psa.dictionary_markdown(spec))):
        assert (repo_root / path).read_text(encoding="utf-8") == text, f"Regenerate {path} (src/silver/cli.py)"


def test_every_gate_check_is_written_by_the_gate_sql():
    spec = psa.load_spec(REPO_ROOT)
    gate = psa.gate_sql(spec)
    for name, scope, _ in psa.gate_checks(spec):
        literal = f"'{name}'" if scope != "year" else f"'{name}_' || estimate_year"
        assert f"{literal} AS check_name" in gate, name
    assert gate.count(" AS check_name") == len(psa.gate_checks(spec))


def test_only_the_candidate_tables_say_not_to_read_them(env):
    """As for DepEd (#120): each candidate is commented as an unpublished build; the published copies are not."""
    env.deliver()
    env.bronze()
    for _ in range(2):                                   # a rebuild replaces the table, and sets the comment again
        assert env.silver().status == "succeeded"
        comments = dict(env.q("SELECT table_name, comment FROM duckdb_tables() WHERE schema_name = '03-silver'"))
        assert comments["psa_poverty_stat_clean_candidate"].startswith("Unpublished build")
        assert "use psa_poverty_stat_quarantine," in comments["psa_poverty_stat_quarantine_candidate"]
        assert comments["psa_poverty_stat_clean"] is None and comments["psa_poverty_stat_quarantine"] is None


def test_the_build_never_publishes_and_the_gate_publishes_clean_last():
    spec = psa.load_spec(REPO_ROOT)
    build, gate = psa.build_sql(spec), psa.gate_sql(spec)
    for table in (spec.clean_table, spec.quarantine_table):
        assert f"CREATE OR REPLACE TABLE edu_access.`03-silver`.{table} USING" not in build
    order = [gate.index(m) for m in ("WHEN MATCHED AND s.fails > 0 THEN UPDATE SET", "raise_error(",
                                      f"CREATE OR REPLACE TABLE edu_access.`03-silver`.{spec.quarantine_table} USING",
                                      f"CREATE OR REPLACE TABLE edu_access.`03-silver`.{spec.clean_table} USING",
                                      "status = 'succeeded'")]
    assert order == sorted(order)


def _spec(mapping=None, contract=None):
    registry = yaml.safe_load((REPO_ROOT / "config" / "tables.yml").read_text(encoding="utf-8"))
    entry = next(s for s in registry["source_tables"] if s["source_id"] == SOURCE)
    mapping = mapping or json.loads((REPO_ROOT / "config" / "mappings" / f"{SOURCE}.json").read_text(encoding="utf-8"))
    return psa.build_spec(mapping, contract or real_config(), entry)


def test_the_real_rules_give_three_years_and_five_measures():
    spec = _spec()
    assert spec.years == list(YEARS) and [m.name for m in spec.measures] == list(MEASURES)
    assert spec.absent == {} and spec.cv_flag == "cv_over_20"


def test_a_new_publisher_column_needs_a_reviewed_rule():
    contract = copy.deepcopy(real_config())
    contract["schema_versions"]["v2"] = {**contract["schema_versions"]["v1"],
                                         "columns": contract["schema_versions"]["v1"]["columns"] + ["Magnitude of Poor 2023"]}
    with pytest.raises(IngestionError, match="no Silver rule"):
        _spec(contract=contract)


@pytest.mark.parametrize("break_it, message", [
    (lambda m: m.update(silver_table="poverty_silver"), "config/tables.yml"),
    (lambda m: m["identifier"].update(pattern="^[0-9]{5,6}$';"), "quotes, backslashes"),
    (lambda m: m["flags"].update(cv_threshold=-1), "non-negative"),
    (lambda m: m["quarantine"].update(fail_above_percent=100), "fail_above_percent"),
    (lambda m: m["text_columns"].update({"Province": {"to": "province", "rule": "x"}}), "contract does not have"),
    (lambda m: m["measures"].append(dict(m["measures"][0])), "share a Silver name"),
])
def test_the_rules_file_refuses_ambiguous_rules(break_it, message):
    mapping = json.loads((REPO_ROOT / "config" / "mappings" / f"{SOURCE}.json").read_text(encoding="utf-8"))
    break_it(mapping)
    with pytest.raises(IngestionError, match=message):
        _spec(mapping=mapping)
