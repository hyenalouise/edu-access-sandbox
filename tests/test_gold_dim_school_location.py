"""Gold dim_school_location (#217): its build and gate, run the way the job's two SQL tasks run them.

Made-up rows go straight into the published tables the build reads (deped_school_boundary_map, dim_school) in
an in-memory DuckDB. The boundary test itself is Integration's (tests/test_integration_school_boundary.py);
here Gold only projects the map and checks its own contract. No real school is used.
"""

import uuid

import pytest

from factories.deped_deliveries import REPO_ROOT
from src.ingestion.store import DuckDBStore

CONTROL = "edu_access.`01-control`"
MAP = "edu_access.`04-integration`.deped_school_boundary_map"
DIM_SCHOOL = "edu_access.`05-gold`.dim_school"
CANDIDATE = "edu_access.`05-gold`.dim_school_location_candidate"
DIM = "edu_access.`05-gold`.dim_school_location"
BUILD = REPO_ROOT / "etl" / "05_gold" / "07_build_dim_school_location.sql"
GATE = REPO_ROOT / "etl" / "05_gold" / "90_validate_dim_school_location.sql"

# school_id: (longitude, latitude, coordinate_flag, boundary_status)
ROWS = {
    "100001": (120.5, 15.5, None, "inside"),
    "100002": (122.5, 15.5, None, "outside"),
    "100003": (None, None, "missing", "no_usable_point"),
    "100004": (120.5, 15.5, None, "no_matched_city"),
    "100005": (120.5, 15.5, None, "no_boundary"),
}


class Env:
    def __init__(self, rows=ROWS, map_status="succeeded"):
        self.store = DuckDBStore()
        for path in sorted((REPO_ROOT / "etl" / "01_control").glob("0[1-4]_*.sql")):
            self.store.run_file(path)
        for schema in ("04-integration", "05-gold"):
            self.store.sql(f"CREATE SCHEMA IF NOT EXISTS edu_access.`{schema}`")
        self.store.sql(f"CREATE TABLE {MAP} (school_year STRING, school_id STRING, longitude DOUBLE, latitude DOUBLE, "
                       "coordinate_flag STRING, boundary_status STRING, run_id STRING)")
        self.store.sql(f"CREATE TABLE {DIM_SCHOOL} (school_id STRING, school_name STRING)")
        for school_id, (lon, lat, flag, status) in rows.items():
            self.store.sql(f"INSERT INTO {MAP} VALUES ('2023-24', ?, ?, ?, ?, ?, 'R-MAP')", [school_id, lon, lat, flag, status])
            self.store.sql(f"INSERT INTO {DIM_SCHOOL} VALUES (?, 'Paaralan')", [school_id])
        # Another school year is never read: the dimension is SY 2023-24's location.
        self.store.sql(f"INSERT INTO {MAP} VALUES ('2024-25', '100001', 1.0, 1.0, NULL, 'outside', 'R-MAP')")
        self.store.sql(f"INSERT INTO {CONTROL}.pipeline_runs (run_id, pipeline_name, source_id, environment, status, "
                       "code_revision, started_at_utc) VALUES ('R-MAP', 'integration_build', 'deped_psgc_coordinates', 'local', ?, "
                       "'c', TIMESTAMP '2026-10-21 00:00:00')", [map_status])

    def build(self):
        params = {"run_id": str(uuid.uuid4()), "code_revision": "c" * 40, "environment": "local"}
        self.store.run_file(BUILD, params)
        return params

    def gate(self, params):
        try:
            self.store.run_file(GATE, params)
        except Exception as e:  # the gate raises on FAIL after recording its checks
            return str(e)
        return None

    def run(self):
        params = self.build()
        return params["run_id"], self.gate(params)

    def checks(self, run_id):
        return {r["check_name"]: r for r in self.store.records(
            f"SELECT * FROM {CONTROL}.data_quality_results WHERE run_id = '{run_id}' AND layer = 'gold'")}

    def dim(self):
        return {r["school_id"]: r for r in self.store.records(f"SELECT * FROM {DIM}")}


def test_one_row_per_school_with_the_maps_values():
    env = Env()
    run_id, error = env.run()
    assert error is None
    dim = env.dim()
    assert {k: (v["longitude"], v["latitude"], v["coordinate_flag"], v["boundary_status"]) for k, v in dim.items()} == ROWS
    checks = env.checks(run_id)
    assert {c["status"] for c in checks.values()} == {"PASS"}
    assert set(checks) == {"rows_reconcile", "key_unique", "key_not_null", "school_in_dim_school", "values_match_source",
                           "boundary_status_allowed", "upstream_run_deped_school_boundary_map"}
    assert checks["rows_reconcile"]["actual"] == "5"


def test_columns_follow_the_data_model_and_carry_no_psgc_code():
    env = Env()
    env.run()
    assert env.store.columns("05-gold", "dim_school_location") == [
        ("school_id", "VARCHAR"), ("longitude", "DOUBLE"), ("latitude", "DOUBLE"), ("coordinate_flag", "VARCHAR"),
        ("boundary_status", "VARCHAR")]


def test_a_rerun_rebuilds_the_same_rows_and_leaves_no_gate_table():
    env = Env()
    env.run()
    before = env.store.query(f"SELECT * FROM {DIM} ORDER BY school_id")
    env.run()
    assert env.store.query(f"SELECT * FROM {DIM} ORDER BY school_id") == before
    assert env.store.query("SELECT COUNT(*) FROM information_schema.tables "
                           "WHERE table_name LIKE 'dim_school_location_gate_summary_r_%'") == [(0,)]


def test_a_school_missing_from_dim_school_fails_and_keeps_the_last_good_build():
    env = Env()
    env.run()
    good = env.store.query(f"SELECT * FROM {DIM} ORDER BY school_id")
    env.store.sql(f"DELETE FROM {DIM_SCHOOL} WHERE school_id = '100002'")
    run_id, error = env.run()
    assert error and "FAIL" in error
    assert env.checks(run_id)["school_in_dim_school"]["status"] == "FAIL"
    assert env.store.query(f"SELECT * FROM {DIM} ORDER BY school_id") == good


@pytest.mark.parametrize("tamper, check", [
    ("boundary_status = 'inside' WHERE school_id = '100002'", "values_match_source"),
    ("longitude = longitude + 0.001 WHERE school_id = '100001'", "values_match_source"),
    ("boundary_status = 'unknown' WHERE school_id = '100001'", "boundary_status_allowed"),
    ("school_id = '100001' WHERE school_id = '100002'", "key_unique"),
])
def test_a_candidate_that_differs_from_the_map_fails_the_gate(tamper, check):
    env = Env()
    params = env.build()
    env.store.sql(f"UPDATE {CANDIDATE} SET {tamper}")
    error = env.gate(params)
    assert error and "FAIL" in error
    assert env.checks(params["run_id"])[check]["status"] == "FAIL"


def test_a_map_run_that_did_not_succeed_fails_the_gate():
    env = Env(map_status="failed")
    run_id, error = env.run()
    assert error and "FAIL" in error
    assert env.checks(run_id)["upstream_run_deped_school_boundary_map"]["status"] == "FAIL"
