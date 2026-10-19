"""Gold dim_city_municipality (#174): its build and gate, run the way the job's two SQL tasks run them.

Made-up rows go straight into the published tables the build reads (psa_psgc_clean, hdx_adm3_psgc_map,
hdx_adm3_clean) in an in-memory DuckDB. No real PSGC or COD-AB row is used.
"""

import uuid

import pytest

from factories.deped_deliveries import REPO_ROOT
from src.ingestion.store import DuckDBStore

CONTROL = "edu_access.`01-control`"
DIM = "edu_access.`05-gold`.dim_city_municipality"
BUILD = REPO_ROOT / "etl" / "05_gold" / "04_build_dim_city_municipality.sql"
GATE = REPO_ROOT / "etl" / "05_gold" / "90_validate_dim_city_municipality.sql"
RELEASE = "2025-02-13"


def record_run(store, run_id, pipeline_name, source_id, status="succeeded"):
    """The pipeline_runs row a published Silver or Integration table's run_id points to (D-025)."""
    store.sql(f"INSERT INTO {CONTROL}.pipeline_runs (run_id, pipeline_name, source_id, environment, status, code_revision, "
              f"started_at_utc) VALUES (?, ?, ?, 'local', ?, 'c', TIMESTAMP '2026-10-19 00:00:00')",
              [run_id, pipeline_name, source_id, status])

# psgc_code, name, geographic_level, region_code, province_code, city_class, income_class, retained, level_blank
PSGC = [
    ("0100000000", "Region One", "Reg", "0100000000", None, None, None, None, False),
    ("0102800000", "Province A", "Prov", "0100000000", "0102800000", None, "1st", False, False),
    ("0102801000", "Town A", "Mun", "0100000000", "0102800000", None, "2nd", True, False),
    ("0102802000", "City of A", "City", "0100000000", "0102800000", "CC", "3rd", False, False),
    ("0102802001", "Barangay 1", "Bgy", "0100000000", "0102800000", None, None, None, False),
    ("0110000000", "Big City", "City", "0100000000", None, "HUC", "1st", False, False),
    ("0990100000", "City of Isabela (Not a Province)", None, "0900000000", "0990100000", None, None, None, True),
    ("0900000000", "Region Nine", "Reg", "0900000000", None, None, None, None, False),
    ("0990101000", "City of Isabela", "City", "0900000000", "0990100000", "CC", "3rd", False, False),
    ("1900000000", "Region Nineteen", "Reg", "1900000000", None, None, None, None, False),
    ("1999900000", "Special Geographic Area", None, "1900000000", "1999900000", None, None, None, True),
    ("1999901000", "SGA Town One", "Mun", "1900000000", "1999900000", None, None, None, False),
    ("1999902000", "SGA Town Two", "Mun", "1900000000", "1999900000", None, None, None, False),
]
# adm3_pcode, psgc_code (None when unmatched), area_sqkm
HDX = [
    ("PH0102801", "0102801000", "12.34567891234567"),
    ("PH0102802", "0102802000", "50.5"),
    ("PH0110000", "0110000000", "40"),
    ("PH0990101", "0990101000", "219.8697"),
    ("PH1909901", None, "33.3"),
]


class Env:
    def __init__(self, psgc=PSGC, hdx=HDX, older_quarter=False):
        self.store = DuckDBStore()
        for path in sorted((REPO_ROOT / "etl" / "01_control").glob("0[1-4]_*.sql")):
            self.store.run_file(path)
        for schema in ("03-silver", "04-integration"):
            self.store.sql(f"CREATE SCHEMA IF NOT EXISTS edu_access.`{schema}`")
        self.store.sql("CREATE TABLE edu_access.`03-silver`.psa_psgc_clean (psgc_code STRING, name STRING, "
                       "geographic_level STRING, region_code STRING, province_code STRING, city_class STRING, "
                       "income_class STRING, income_class_retained_after_downgrade BOOLEAN, level_blank BOOLEAN, "
                       "publication_period STRING, is_master_reference BOOLEAN, run_id STRING)")
        for row in psgc:
            self.store.sql("INSERT INTO edu_access.`03-silver`.psa_psgc_clean VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '2026-Q2', TRUE, 'S1')",
                           list(row))
        if older_quarter:  # a non-master quarter, with a unit the master does not have: never read
            self.store.sql("INSERT INTO edu_access.`03-silver`.psa_psgc_clean VALUES ('0102899000', 'Old Town', 'Mun', "
                           "'0100000000', '0102800000', NULL, NULL, NULL, FALSE, '2025-Q4', FALSE, 'S0')")
        self.store.sql("CREATE TABLE edu_access.`03-silver`.hdx_adm3_clean (adm3_pcode STRING, valid_on DATE, "
                       "area_sqkm DECIMAL(20,14), run_id STRING)")
        self.store.sql("CREATE TABLE edu_access.`04-integration`.hdx_adm3_psgc_map (adm3_pcode STRING, "
                       "source_reference_date DATE, psgc_code STRING, match_status STRING, run_id STRING)")
        self.load_hdx(hdx)
        record_run(self.store, "S1", "silver_build", "psa_psgc")
        record_run(self.store, "S1", "silver_build", "hdx_boundaries")
        record_run(self.store, "M1", "integration_build", "hdx_boundaries")

    def load_hdx(self, hdx):
        for pcode, code, area in hdx:
            self.store.sql(f"INSERT INTO edu_access.`03-silver`.hdx_adm3_clean VALUES (?, DATE '{RELEASE}', ?, 'S1')", [pcode, area])
            self.store.sql(f"INSERT INTO edu_access.`04-integration`.hdx_adm3_psgc_map VALUES (?, DATE '{RELEASE}', ?, ?, 'M1')",
                           [pcode, code, "matched" if code else "unmatched"])

    def run(self):
        run_id = str(uuid.uuid4())
        params = {"run_id": run_id, "code_revision": "c" * 40, "environment": "local"}
        try:
            self.store.run_file(BUILD, params)
            self.store.run_file(GATE, params)
        except Exception as e:
            return run_id, str(e)
        return run_id, None

    def checks(self, run_id):
        return {r["check_name"]: r for r in self.store.records(
            f"SELECT * FROM {CONTROL}.data_quality_results WHERE run_id = '{run_id}' AND layer = 'gold'")}

    def dim(self):
        return {r["city_mun_psgc_code"]: r for r in self.store.records(f"SELECT * FROM {DIM}")}


def test_builds_every_city_and_municipality_and_the_technical_members():
    env = Env(older_quarter=True)
    run_id, error = env.run()
    assert error is None
    dim = env.dim()
    assert sorted(dim) == ["0102801000", "0102802000", "0110000000", "0990101000", "1999901000", "1999902000",
                           "EXCLUDED", "UNKNOWN"]
    checks = env.checks(run_id)
    assert {c["status"] for c in checks.values()} == {"PASS", "WARN"}
    assert checks["regular_rows_reconcile"]["actual"] == "6"
    assert checks["regular_without_land_area"]["status"] == "WARN"
    assert checks["regular_without_land_area"]["actual"] == "2"
    assert checks["sga_members"]["actual"] == "2"
    assert checks["regular_without_province"]["actual"] == "1"


def test_columns_follow_the_data_model():
    env = Env()
    env.run()
    dim = env.dim()
    town = dim["0102801000"]
    assert (town["city_mun_name"], town["province_psgc_code"], town["province_name"], town["region_name"]) == \
        ("Town A", "0102800000", "Province A", "Region One")
    assert (town["lgu_type"], town["city_class"], town["income_class"], town["income_class_retained"]) == \
        ("municipality", None, "2nd", True)
    assert str(town["land_area_sqkm"]) == "12.3457"
    assert town["land_area_source"] == "hdx_boundaries"
    assert (town["member_type"], town["source_psgc_quarter"], town["is_sga"]) == ("regular", "2026-Q2", False)
    huc = dim["0110000000"]
    assert (huc["lgu_type"], huc["city_class"], huc["province_psgc_code"]) == ("city", "HUC", None)
    isabela = dim["0990101000"]
    assert (isabela["province_psgc_code"], isabela["is_sga"]) == ("0990100000", False)
    sga = dim["1999901000"]
    assert (sga["is_sga"], sga["land_area_sqkm"], sga["land_area_source"]) == (True, None, None)
    for code, member_type in (("UNKNOWN", "unknown"), ("EXCLUDED", "excluded")):
        row = dim[code]
        assert row["member_type"] == member_type
        assert row["source_psgc_quarter"] == "2026-Q2"
        assert row["region_psgc_code"] is None and row["lgu_type"] is None and row["land_area_sqkm"] is None


def test_rerun_gives_the_same_table():
    env = Env()
    env.run()
    first = env.dim()
    _, error = env.run()
    assert error is None
    assert env.dim() == first


@pytest.mark.parametrize("hdx, check", [
    (HDX + [("PH0102899", "0102801000", "1")], "land_area_one_feature"),   # two features for one unit
    ([("PH0102801", "0102801000", "0")] + HDX[1:], "land_area_positive"),
])
def test_a_failed_check_stops_and_keeps_the_last_good_build(hdx, check):
    env = Env()
    _, error = env.run()
    assert error is None
    good = env.dim()
    for table in ("`03-silver`.hdx_adm3_clean", "`04-integration`.hdx_adm3_psgc_map"):
        env.store.sql(f"DELETE FROM edu_access.{table}")
    env.load_hdx(hdx)
    run_id, error = env.run()
    assert error and "Gold gate failed for dim_city_municipality" in error
    assert env.checks(run_id)[check]["status"] == "FAIL"
    assert env.dim() == good


def test_a_missing_region_name_fails():
    env = Env(psgc=[row for row in PSGC if row[0] != "0900000000"])
    run_id, error = env.run()
    assert error
    assert env.checks(run_id)["region_resolved"]["status"] == "FAIL"


def test_upstream_runs_are_recorded_and_must_have_succeeded():
    env = Env()
    run_id, error = env.run()
    assert error is None
    upstream = {(r["check_name"], r["actual"], r["status"]) for r in env.store.records(
        f"SELECT * FROM {CONTROL}.data_quality_results WHERE run_id = '{run_id}' AND check_name LIKE 'upstream_run_%'")}
    assert upstream == {("upstream_run_psa_psgc_clean", "S1", "PASS"), ("upstream_run_hdx_adm3_clean", "S1", "PASS"),
                        ("upstream_run_hdx_adm3_psgc_map", "M1", "PASS")}
    env.store.sql(f"UPDATE {CONTROL}.pipeline_runs SET status = 'failed' WHERE pipeline_name = 'integration_build'")
    run_id, error = env.run()
    assert error and "Gold gate failed for dim_city_municipality" in error
    assert env.checks(run_id)["upstream_run_hdx_adm3_psgc_map"]["status"] == "FAIL"
