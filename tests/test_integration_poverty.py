"""Integration for psa_poverty_stat: the PSA poverty → PSGC map (psa_poverty_psgc_map, #92, D-054).

Made-up rows go straight into the two published Silver tables it reads (psa_poverty_stat_clean and
psa_psgc_clean) in an in-memory DuckDB, then through the committed build and gate SQL, run the way
the job's two SQL tasks run them. No real PSA or PSGC row is used.
"""

import uuid

import pytest
import yaml

from factories.deped_deliveries import REPO_ROOT
from src.ingestion.store import DuckDBStore

CONTROL = "edu_access.`01-control`"
SILVER = "edu_access.`03-silver`"
MAP = "edu_access.`04-integration`.psa_poverty_psgc_map"
CANDIDATE = "edu_access.`04-integration`.psa_poverty_psgc_map_candidate"
BUILD = REPO_ROOT / "etl" / "04_integration" / "02_map_psa_poverty_psgc.sql"
GATE = REPO_ROOT / "etl" / "04_integration" / "90_validate_psa_poverty_psgc_map.sql"
YEARS = (2021, 2023)

PSGC = [  # psgc_code, name, correspondence_code, geographic_level, city_class
    ("0100000000", "Region I (Ilocos Region)", "010000000", "Reg", None),
    ("0102800000", "Ilocos Norte", "012800000", "Prov", None),
    ("0102801000", "Adams", "012801000", "Mun", None),
    ("0102801001", "Adams Barangay", "012801001", "Bgy", None),
    ("0102803000", "City of Batac", "012803000", "City", "CC"),
    ("0102804000", "Banna", "012804000", "Mun", None),
    ("0102805000", "Banna Two", "012804000", "Mun", None),        # shares Banna's code: not one-to-one
    ("0102806000", "Peñablanca", "012806000", "Mun", None),
    ("0102807000", "Kalayaan", "012807000", "Mun", None),
    ("1380600000", "City of Manila", "133900000", "City", "HUC"),
    ("1380601000", "Tondo I/II", "133901000", "SubMun", None),
    ("1380602000", "Binondo", "133902000", "SubMun", None),
    ("1380100000", "City of Caloocan", "137501000", "City", "HUC"),
    ("1381701000", "Pateros", "137606000", "Mun", None),
    ("1999901000", "Kapalawan", None, "Mun", None),               # a Special Geographic Area unit: no code
]
# psgc_id, PSA name, estimate status, and what the map should say:
# (psgc_code, match_status, match_method, review_status, geographic_level, names_agree)
POVERTY = {
    "012801": ("Adams", "estimated", ("0102801000", "matched", "correspondence_code", "rule", "city_mun", True)),
    "012803": ("City of Batac", "estimated", ("0102803000", "matched", "correspondence_code", "rule", "city_mun", True)),
    "012806": ("Penablanca", "estimated", ("0102806000", "matched", "correspondence_code", "rule", "city_mun", False)),
    "012807": ("Kalayaan", "no_estimate", ("0102807000", "matched", "correspondence_code", "rule", "city_mun", True)),
    "133901": ("Tondo", "estimated", ("1380601000", "matched", "correspondence_code", "rule", "sub_mun", False)),
    "133902": ("Binondo", "estimated", ("1380602000", "matched", "correspondence_code", "rule", "sub_mun", True)),
    "012804": ("Banna", "estimated", (None, "ambiguous", None, "pending", None, None)),
    "012800": ("Ilocos Norte", "estimated", (None, "unmatched", None, "pending", None, None)),  # a province, not a city
    "012899": ("Nowhere", "estimated", (None, "unmatched", None, "pending", None, None)),
}


class Env:
    def __init__(self, psgc_rows=None, poverty=None):
        self.store = DuckDBStore()
        for path in sorted((REPO_ROOT / "etl" / "01_control").glob("0[1-4]_*.sql")):
            self.store.run_file(path)
        self.store.sql(f"CREATE SCHEMA IF NOT EXISTS {SILVER}")
        self.store.sql(f"CREATE TABLE {SILVER}.psa_psgc_clean (psgc_code STRING, name STRING, correspondence_code STRING, "
                       "geographic_level STRING, city_class STRING, publication_period STRING, is_master_reference BOOLEAN, "
                       "batch_id STRING, source_row_number BIGINT)")
        for i, row in enumerate(psgc_rows or PSGC, 1):
            self.store.sql(f"INSERT INTO {SILVER}.psa_psgc_clean VALUES (?, ?, ?, ?, ?, '2026-Q2', TRUE, 'P1', ?)", [*row, i])
        self.store.sql(f"CREATE TABLE {SILVER}.psa_poverty_stat_clean (estimate_year INT, psgc_id STRING, "
                       "correspondence_code STRING, region STRING, municipality STRING, poverty_incidence DOUBLE, "
                       "coefficient_of_variation DOUBLE, standard_error DOUBLE, ci90_lower_limit DOUBLE, ci90_upper_limit DOUBLE, "
                       "estimate_status STRING, cv_over_20 BOOLEAN, se_cv_inconsistent BOOLEAN, lower_limit_not_positive BOOLEAN, "
                       "logical_dataset STRING, estimate_years_covered STRING, batch_id STRING, delivery_version INT, "
                       "schema_version STRING, source_sha256 STRING, source_row_number BIGINT, run_id STRING, "
                       "cleaned_at_utc TIMESTAMP, code_revision STRING)")
        for i, (psgc_id, (name, status, _)) in enumerate((poverty or POVERTY).items(), 1):
            for year in YEARS:
                values = [None] * 5 if status == "no_estimate" else [10.0 + i, 25.0 if i == 3 else 12.5, 1.25, -0.024 if i == 1 else 8.0, 12.0 + i]
                self.store.sql(f"INSERT INTO {SILVER}.psa_poverty_stat_clean VALUES (?, ?, ?, 'Region I', ?, ?, ?, ?, ?, ?, ?, "
                               "?, FALSE, ?, 'sae', '2021,2023', 'B1', 1, 'v1', 'sha', ?, 'silver-run', NULL, 'r')",
                               [year, psgc_id, psgc_id + "000", name, *values, status, i == 3 and status != "no_estimate",
                                i == 1, i + 5])

    def run(self, run_id=None):
        run_id = run_id or str(uuid.uuid4())
        params = {"run_id": run_id, "code_revision": "c" * 40, "environment": "local"}
        try:
            self.store.run_file(BUILD, params)
            self.store.run_file(GATE, params)
        except Exception as e:
            return run_id, str(e)
        return run_id, None

    def build_only(self):
        run_id = str(uuid.uuid4())
        params = {"run_id": run_id, "code_revision": "c" * 40, "environment": "local"}
        self.store.run_file(BUILD, params)
        return run_id, params

    def rows(self, sql):
        return self.store.records(sql)

    def checks(self, run_id):
        return {r["check_name"]: r for r in self.rows(
            f"SELECT * FROM {CONTROL}.data_quality_results WHERE run_id = '{run_id}' AND layer = 'integration'")}

    def run_status(self, run_id):
        return self.rows(f"SELECT status FROM {CONTROL}.pipeline_runs WHERE run_id = '{run_id}' "
                         "AND pipeline_name = 'integration_build' AND source_id = 'psa_poverty_stat'")[0]["status"]

    def published(self):
        return bool(self.rows("SELECT 1 FROM information_schema.tables WHERE table_schema = '04-integration' "
                              "AND table_name = 'psa_poverty_psgc_map'"))


def fails(checks):
    return {name for name, row in checks.items() if row["status"] == "FAIL"}


# --- The rule -----------------------------------------------------------------------------

def test_every_silver_row_gets_one_row_by_the_correspondence_code_only():
    env = Env()
    run_id, error = env.run()
    assert error is None
    rows = env.rows(f"SELECT * FROM {MAP} ORDER BY psgc_id, estimate_year")
    assert len(rows) == len(POVERTY) * len(YEARS)
    for row in rows:
        expected = POVERTY[row["psgc_id"]][2]
        got = (row["psgc_code"], row["match_status"], row["match_method"], row["review_status"],
               row["geographic_level"], row["names_agree"])
        assert got == expected, row["psgc_id"]
        assert row["source_row_ref"] == f"{row['psgc_id']}/{row['estimate_year']}"
        assert row["psgc_version"] == "2026-Q2" and row["source_id"] == "psa_poverty_stat"


def test_names_are_compared_never_used_to_match():
    """A differing PSA name keeps its code match and is listed for review (D-030); a matching name
    never rescues a row the code does not place."""
    env = Env()
    env.run()
    tondo = env.rows(f"SELECT * FROM {MAP} WHERE psgc_id = '133901' AND estimate_year = 2023")[0]
    assert (tondo["municipality"], tondo["psgc_name"], tondo["names_agree"]) == ("Tondo", "Tondo I/II", False)
    assert tondo["reason"].startswith("PSA name differs from the PSGC name")
    province = env.rows(f"SELECT * FROM {MAP} WHERE psgc_id = '012800' AND estimate_year = 2023")[0]
    assert province["psgc_code"] is None and province["psgc_name"] is None   # same name as a PSGC province row
    assert province["reason"].startswith("no PSGC city, municipality or sub-municipality")
    banna = env.rows(f"SELECT * FROM {MAP} WHERE psgc_id = '012804' AND estimate_year = 2023")[0]
    assert banna["reason"].startswith("2 PSGC units share this Correspondence Code")


def test_estimates_and_lineage_stay_on_their_own_row():
    env = Env()
    env.run()
    measures = ("poverty_incidence", "coefficient_of_variation", "standard_error", "ci90_lower_limit", "ci90_upper_limit",
                "estimate_status", "cv_over_20", "se_cv_inconsistent", "lower_limit_not_positive", "municipality", "region",
                "correspondence_code", "batch_id", "source_sha256", "source_row_number", "delivery_version", "logical_dataset")
    cols = ", ".join(measures)
    silver = env.rows(f"SELECT psgc_id, estimate_year, {cols} FROM {SILVER}.psa_poverty_stat_clean ORDER BY 1, 2")
    mapped = env.rows(f"SELECT psgc_id, estimate_year, {cols} FROM {MAP} ORDER BY 1, 2")
    assert mapped == silver
    kalayaan = env.rows(f"SELECT * FROM {MAP} WHERE psgc_id = '012807'")
    assert all(r["poverty_incidence"] is None and r["estimate_status"] == "no_estimate" for r in kalayaan)  # NULL, never 0


def test_manila_sub_municipalities_stay_and_no_city_value_is_made():
    env = Env()
    run_id, _ = env.run()
    sub = env.rows(f"SELECT * FROM {MAP} WHERE geographic_level = 'sub_mun' AND estimate_year = 2023")
    assert sorted(r["psgc_code"] for r in sub) == ["1380601000", "1380602000"]
    assert not env.rows(f"SELECT 1 FROM {MAP} WHERE psgc_code = '1380600000'")
    checks = env.checks(run_id)
    assert checks["sub_municipality_rows_2023"]["actual"] == "2"
    assert checks["not_in_source_with_sub_municipality_rows_2023"]["actual"] == "1"


# --- The gate -----------------------------------------------------------------------------

def test_the_gate_passes_warns_on_review_and_counts_the_coverage_gaps():
    env = Env()
    run_id, error = env.run()
    assert error is None and env.published() and env.run_status(run_id) == "succeeded"
    checks = env.checks(run_id)
    assert not fails(checks)
    warns = {name: row["actual"] for name, row in checks.items() if row["status"] == "WARN"}
    assert warns == {"review_pending": "6", "unmatched": "4", "ambiguous": "2", "names_differ": "4",
                     "psgc_units_not_in_source_2021": "6", "psgc_units_not_in_source_2023": "6"}
    for year in YEARS:  # Manila and Caloocan; Kapalawan; Pateros and the two Banna units
        assert checks[f"not_in_source_huc_{year}"]["actual"] == "2"
        assert checks[f"not_in_source_without_correspondence_code_{year}"]["actual"] == "1"
        assert checks[f"not_in_source_other_{year}"]["actual"] == "3"
        assert checks[f"no_estimate_rows_{year}"]["actual"] == "1"
    assert checks["rows_reconcile"]["actual"] == str(len(POVERTY) * len(YEARS))
    assert checks["match_rate_percent"]["actual"] == "66.67"


def test_a_map_with_no_match_still_passes_and_warns():
    """With no PSGC unit to match (every method NULL), no check may read a NULL count as a failure."""
    nowhere = {"999901": ("Nowhere", "estimated", None), "999902": ("Elsewhere", "no_estimate", None)}
    env = Env(poverty=nowhere)
    run_id, error = env.run()
    assert error is None and env.published()
    checks = env.checks(run_id)
    assert not fails(checks) and all(row["actual"] is not None for name, row in checks.items() if row["expected"] == "0")
    assert checks["unmatched"]["actual"] == str(len(nowhere) * len(YEARS))


def test_a_rerun_rebuilds_the_same_map():
    env = Env()
    first, _ = env.run()
    before = env.rows(f"SELECT * EXCLUDE (run_id, built_at_utc, code_revision) FROM {MAP} ORDER BY source_row_ref")
    second, error = env.run()
    assert error is None and not fails(env.checks(second))
    assert env.rows(f"SELECT * EXCLUDE (run_id, built_at_utc, code_revision) FROM {MAP} ORDER BY source_row_ref") == before
    assert {r["run_id"] for r in env.rows(f"SELECT run_id FROM {MAP}")} == {second}


TAMPER = [
    ("psgc_name = 'Somewhere Else' WHERE psgc_id = '012801'", "psgc_name_matches_unit"),
    ("psgc_code = '1381701000' WHERE psgc_id = '012801'", "psgc_name_matches_unit"),              # Pateros, name kept
    ("psgc_code = '1381701000', psgc_name = 'Pateros' WHERE psgc_id = '012801'", "correspondence_is_the_old_code"),
    ("match_method = 'name_exact' WHERE psgc_id = '012801'", "no_name_rule_match"),
    ("match_method = 'correspondence_code' WHERE psgc_id = '012804'", "method_valid"),
    ("psgc_code = '0102804000', psgc_name = 'Banna' WHERE psgc_id = '012804'", "unmatched_has_no_psgc"),
    ("review_status = 'pending' WHERE psgc_id = '012801'", "status_combination_valid"),
    ("geographic_level = 'city_mun' WHERE psgc_id = '133901'", "geographic_level_matches_unit"),
    ("poverty_incidence = 99.0 WHERE psgc_id = '012803' AND estimate_year = 2023", "estimates_unchanged"),
    ("ci90_lower_limit = 0 WHERE psgc_id = '012801' AND estimate_year = 2023", "estimates_unchanged"),
    ("names_agree = TRUE WHERE psgc_id = '012806'", "names_agree_valid"),
    ("psgc_version = '2026-Q1' WHERE psgc_id = '012801'", "psgc_version_is_master"),
    ("batch_id = NULL WHERE psgc_id = '012801'", "lineage_complete"),
]


@pytest.mark.parametrize("change, check", TAMPER)
def test_a_tampered_candidate_fails_the_gate_and_the_published_map_is_kept(change, check):
    env = Env()
    assert env.run()[1] is None                      # a first map is published
    before = env.rows(f"SELECT * EXCLUDE (run_id, built_at_utc) FROM {MAP} ORDER BY source_row_ref")
    run_id, params = env.build_only()
    env.store.sql(f"UPDATE {CANDIDATE} SET {change}")
    with pytest.raises(Exception, match="Integration gate failed"):
        env.store.run_file(GATE, params)
    assert env.checks(run_id)[check]["status"] == "FAIL"
    assert env.run_status(run_id) == "failed"
    assert env.rows(f"SELECT * EXCLUDE (run_id, built_at_utc) FROM {MAP} ORDER BY source_row_ref") == before


@pytest.mark.parametrize("change, failed", [
    (f"DELETE FROM {CANDIDATE} WHERE psgc_id = '012899'", {"rows_reconcile", "source_rows_not_dropped"}),
    (f"INSERT INTO {CANDIDATE} SELECT * FROM {CANDIDATE} WHERE psgc_id = '012801' AND estimate_year = 2023",
     {"rows_reconcile", "one_row_per_source_row", "psgc_code_taken_once"}),
    (f"UPDATE {CANDIDATE} SET psgc_code = '0102801000', psgc_name = 'Adams', correspondence_code = '012801000' "
     "WHERE psgc_id = '012803'", {"psgc_code_taken_once", "correspondence_is_the_old_code", "estimates_unchanged"}),
])
def test_a_lost_repeated_or_doubled_row_fails_the_gate(change, failed):
    env = Env()
    run_id, params = env.build_only()
    env.store.sql(change)
    with pytest.raises(Exception, match="Integration gate failed"):
        env.store.run_file(GATE, params)
    assert failed <= fails(env.checks(run_id))
    assert not env.published()


def test_a_silver_code_that_is_not_the_padded_id_fails_the_gate():
    """D-034's normalization is read again: correspondence_code must be the six-digit psgc_id + 000."""
    env = Env()
    env.store.sql(f"UPDATE {SILVER}.psa_poverty_stat_clean SET psgc_id = '12801' WHERE psgc_id = '012801'")
    run_id, error = env.run()
    assert error and "Integration gate failed" in error
    assert env.checks(run_id)["correspondence_is_the_old_code"]["actual"] == str(len(YEARS))
    assert not env.published()


def test_two_master_psgc_periods_fail_the_gate():
    env = Env()
    env.store.sql(f"INSERT INTO {SILVER}.psa_psgc_clean VALUES "
                  "('0102808000', 'Burgos', '012808000', 'Mun', NULL, '2026-Q1', TRUE, 'P0', 99)")
    run_id, error = env.run()
    assert error and "Integration gate failed" in error
    assert env.checks(run_id)["one_psgc_version"]["actual"] == "2"
    assert not env.published()


# --- The job --------------------------------------------------------------------------------

def test_the_map_tasks_run_and_wait_only_for_the_poverty_and_psgc_gates():
    tasks = {t["task_key"]: t for job in yaml.safe_load((REPO_ROOT / "databricks.yml").read_text(encoding="utf-8"))
             ["resources"]["jobs"].values() for t in job["tasks"]}
    build, gate = tasks["02_map_psa_poverty_psgc"], tasks["90_validate_psa_poverty_psgc_map"]
    assert not build.get("disabled") and not gate.get("disabled")
    assert {d["task_key"] for d in build["depends_on"]} == {"90_validate_psa_poverty_stat_clean", "90_validate_psa_psgc_clean"}
    assert [d["task_key"] for d in gate["depends_on"]] == ["02_map_psa_poverty_psgc"]
    assert build["run_if"] == gate["run_if"] == "ALL_SUCCESS"
