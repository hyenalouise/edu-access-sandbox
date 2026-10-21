"""Integration deped_school_boundary_map (#217): the boundary test S-1, run the way the job's two SQL tasks run it.

Made-up rows go straight into the published tables the build reads (deped_psgc_coordinates_clean,
deped_school_psgc_map, hdx_adm3_psgc_map, hdx_adm3_clean) in an in-memory DuckDB, with square boundaries whose
answers are known. No real school, map or boundary is used.
"""

import uuid

import pytest

from factories.deped_deliveries import REPO_ROOT
from src.ingestion.store import DuckDBStore

CONTROL = "edu_access.`01-control`"
SILVER = "edu_access.`03-silver`.deped_psgc_coordinates_clean"
SCHOOL_MAP = "edu_access.`04-integration`.deped_school_psgc_map"
HDX_MAP = "edu_access.`04-integration`.hdx_adm3_psgc_map"
HDX = "edu_access.`03-silver`.hdx_adm3_clean"
CANDIDATE = "edu_access.`04-integration`.deped_school_boundary_map_candidate"
MAP = "edu_access.`04-integration`.deped_school_boundary_map"
BUILD = REPO_ROOT / "etl" / "04_integration" / "06_map_deped_school_boundary.sql"
GATE = REPO_ROOT / "etl" / "04_integration" / "90_validate_deped_school_boundary_map.sql"
LATEST, OLDER = "2026-05-01", "2024-01-01"

CITY_A, CITY_B, CITY_C, CITY_D, CITY_E = "0102800000", "0102900000", "0103000000", "0103100000", "0103200000"


def square(lon, lat, size=1.0):
    ring = [[lon, lat], [lon + size, lat], [lon + size, lat + size], [lon, lat + size], [lon, lat]]
    return '{"type": "Polygon", "coordinates": [' + str(ring) + "]}"


# school_id: (longitude, latitude, coordinate_flag, city in the SY 2023-24 map or None, map match_status)
SCHOOLS = {
    "100001": (120.5, 15.5, None, CITY_A, "matched"),        # inside A
    "100002": (122.5, 15.5, None, CITY_A, "matched"),        # outside A
    "100003": (None, None, "missing", CITY_A, "matched"),    # no point to test
    "100004": (120.5, 15.5, None, CITY_A, "ambiguous"),      # the map did not match a city
    "100005": (120.5, 15.5, None, CITY_B, "matched"),        # B has no boundary
    "100006": (125.5, 15.5, None, CITY_C, "matched"),        # C has two shapes; inside the second
    "100007": (126.5, 16.5, None, CITY_D, "matched"),        # D's only shape is in an older release
    "100008": (127.5, 17.5, None, CITY_E, "matched"),        # E's shape is not valid
    "100009": (120.5, 15.5, "zero", CITY_A, "matched"),      # flagged, even though the point would be inside
}
EXPECTED = {"100001": "inside", "100002": "outside", "100003": "no_usable_point", "100004": "no_matched_city",
            "100005": "no_boundary", "100006": "inside", "100007": "no_boundary", "100008": "no_boundary",
            "100009": "no_usable_point"}
FEATURES = [  # adm3_pcode, psgc_code, match_status, release, geometry, valid
    ("PH0102800", CITY_A, "matched", LATEST, square(120, 15), True),
    ("PH0103001", CITY_C, "matched", LATEST, square(122, 15), True),
    ("PH0103002", CITY_C, "matched", LATEST, square(125, 15), True),
    ("PH0103100", CITY_D, "matched", OLDER, square(126, 16), True),
    ("PH0103200", CITY_E, "matched", LATEST, square(127, 17), False),
    ("PH0109999", CITY_B, "unmatched", LATEST, square(120, 15), True),   # an unmatched feature is never used
]


class Env:
    def __init__(self, schools=None):
        self.store = DuckDBStore()
        for path in sorted((REPO_ROOT / "etl" / "01_control").glob("0[1-4]_*.sql")):
            self.store.run_file(path)
        for schema in ("03-silver", "04-integration", "05-gold"):
            self.store.sql(f"CREATE SCHEMA IF NOT EXISTS edu_access.`{schema}`")
        self.store.sql(f"CREATE TABLE {SILVER} (school_year STRING, school_id STRING, longitude DOUBLE, latitude DOUBLE, "
                       "coordinate_flag STRING, batch_id STRING, source_sha256 STRING, source_row_number BIGINT, run_id STRING)")
        self.store.sql(f"CREATE TABLE {SCHOOL_MAP} (school_year STRING, school_id STRING, geographic_level STRING, "
                       "psgc_code STRING, match_status STRING, run_id STRING)")
        self.store.sql(f"CREATE TABLE {HDX_MAP} (adm3_pcode STRING, psgc_code STRING, match_status STRING, "
                       "source_reference_date DATE, run_id STRING)")
        self.store.sql(f"CREATE TABLE {HDX} (adm3_pcode STRING, geometry STRING, geometry_is_valid BOOLEAN, valid_on DATE)")
        self.load(SCHOOLS if schools is None else schools)
        for pcode, psgc, status, release, geometry, valid in FEATURES:
            self.store.sql(f"INSERT INTO {HDX_MAP} VALUES (?, ?, ?, CAST(? AS DATE), 'R-HDX')", [pcode, psgc, status, release])
            self.store.sql(f"INSERT INTO {HDX} VALUES (?, ?, ?, CAST(? AS DATE))", [pcode, geometry, valid, release])

    def load(self, schools):
        for table in (SILVER, SCHOOL_MAP):
            self.store.sql(f"DELETE FROM {table}")
        for row, (school_id, (lon, lat, flag, city, status)) in enumerate(schools.items(), start=9):
            self.store.sql(f"INSERT INTO {SILVER} VALUES ('2023-24', ?, ?, ?, ?, 'B1', 'f' || repeat('0', 63), ?, 'R-SILVER')",
                           [school_id, lon, lat, flag, row])
            if city:
                self.store.sql(f"INSERT INTO {SCHOOL_MAP} VALUES ('2023-24', ?, 'city_mun', ?, ?, 'R-MAP')", [school_id, city, status])
                self.store.sql(f"INSERT INTO {SCHOOL_MAP} VALUES ('2023-24', ?, 'bgy', ?, ?, 'R-MAP')", [school_id, city[:7] + "001", status])
            # Another school year puts every school in city B: never read, each location is tested in its own year.
            self.store.sql(f"INSERT INTO {SCHOOL_MAP} VALUES ('2024-25', ?, 'city_mun', ?, 'matched', 'R-MAP')", [school_id, CITY_B])

    def build(self, run_id=None):
        params = {"run_id": run_id or str(uuid.uuid4()), "code_revision": "c" * 40, "environment": "local"}
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
            f"SELECT * FROM {CONTROL}.data_quality_results WHERE run_id = '{run_id}' AND layer = 'integration'")}

    def dim(self):
        return {r["school_id"]: r for r in self.store.records(f"SELECT * FROM {MAP}")}

    def run_status(self, run_id):
        return self.store.query(f"SELECT status FROM {CONTROL}.pipeline_runs WHERE run_id = '{run_id}' "
                                "AND pipeline_name = 'integration_build' AND source_id = 'deped_psgc_coordinates'")


def test_each_school_gets_its_boundary_status_and_one_row():
    env = Env()
    run_id, error = env.run()
    assert error is None
    rows = env.dim()
    assert {k: v["boundary_status"] for k, v in rows.items()} == EXPECTED
    assert len(rows) == len(SCHOOLS)                                   # two shapes for city C did not add a row
    checks = env.checks(run_id)
    assert {c["status"] for c in checks.values()} == {"PASS", "WARN"}
    assert {name for name, c in checks.items() if c["status"] == "WARN"} == {"schools_outside_boundary"}
    assert checks["rows_reconcile"]["actual"] == str(len(SCHOOLS))
    assert (checks["schools_inside_boundary"]["actual"], checks["schools_outside_boundary"]["actual"],
            checks["schools_no_usable_point"]["actual"], checks["schools_no_matched_city"]["actual"],
            checks["schools_no_boundary"]["actual"], checks["inside_rate_percent"]["actual"]) == ("2", "1", "2", "1", "3", "66.67")
    assert env.run_status(run_id) == [("succeeded",)]


def test_the_map_keeps_the_point_the_city_and_the_feature_that_contains_it():
    env = Env()
    env.run()
    rows = env.dim()
    inside, outside, flagged = rows["100006"], rows["100002"], rows["100003"]
    assert (inside["city_mun_psgc_code"], inside["adm3_pcode"], str(inside["hdx_release"])) == (CITY_C, "PH0103002", LATEST)
    assert (outside["city_mun_psgc_code"], outside["adm3_pcode"], outside["longitude"]) == (CITY_A, None, 122.5)
    assert (flagged["longitude"], flagged["coordinate_flag"], flagged["reason"]) == (None, "missing", "No point to test: coordinate_flag is missing")
    assert rows["100004"]["city_mun_psgc_code"] is None                 # the ambiguous city is not carried
    assert (inside["source_id"], inside["source_row_ref"], inside["batch_id"]) == ("deped_psgc_coordinates", "2023-24/100006", "B1")


def test_a_rerun_rebuilds_the_same_rows():
    env = Env()
    env.run()
    content = f"SELECT * EXCLUDE (run_id, built_at_utc) FROM {MAP} ORDER BY school_id"
    before = env.store.query(content)
    env.run()
    assert env.store.query(content) == before


def test_a_repeated_school_map_row_is_caught_not_hidden():
    """A second matched city row for one school would multiply it; the gate fails instead of DISTINCT."""
    env = Env()
    env.store.sql(f"INSERT INTO {SCHOOL_MAP} VALUES ('2023-24', '100001', 'city_mun', ?, 'matched', 'R-MAP')", [CITY_C])
    run_id, error = env.run()
    assert error and "FAIL" in error
    checks = env.checks(run_id)
    assert checks["rows_reconcile"]["status"] == "FAIL" and checks["one_row_per_source_row"]["status"] == "FAIL"
    assert env.run_status(run_id) == [("failed",)]


@pytest.mark.parametrize("tamper, check", [
    ("boundary_status = 'inside', adm3_pcode = 'PH0102800' WHERE school_id = '100005'", "boundary_status_follows_inputs"),
    ("boundary_status = 'outside' WHERE school_id = '100003'", "boundary_status_follows_inputs"),
    ("boundary_status = 'unknown' WHERE school_id = '100001'", "boundary_status_allowed"),
    ("adm3_pcode = 'PH0103002' WHERE school_id = '100001'", "boundary_feature_in_city"),   # a feature of another city
    ("adm3_pcode = NULL WHERE school_id = '100001'", "boundary_feature_in_city"),          # inside, but no feature named
    ("city_mun_psgc_code = '0103000000' WHERE school_id = '100001'", "city_matches_school_map"),
    ("longitude = longitude + 0.001 WHERE school_id = '100001'", "locations_unchanged"),
    ("source_row_number = 999 WHERE school_id = '100001'", "locations_unchanged"),
    ("hdx_release = DATE '2024-01-01'", "hdx_release_is_latest"),
])
def test_a_candidate_that_differs_from_its_inputs_fails_and_publishes_nothing(tamper, check):
    env = Env()
    params = env.build()
    env.store.sql(f"UPDATE {CANDIDATE} SET {tamper}")
    error = env.gate(params)
    assert error and "FAIL" in error
    assert env.checks(params["run_id"])[check]["status"] == "FAIL"
    assert env.store.query("SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'deped_school_boundary_map'") == [(0,)]


def test_an_empty_silver_table_fails_the_gate():
    """Silver's own gate never publishes an empty build (current_batch_present); if it ever does, the map stops."""
    env = Env(schools={})
    run_id, error = env.run()
    assert error and "FAIL" in error
    assert env.checks(run_id)["inputs_present"]["status"] == "FAIL"
