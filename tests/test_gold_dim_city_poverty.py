"""Gold dim_city_poverty (#174, D-046): its build and gate, run the way the job's two SQL tasks run them.

Made-up rows go straight into the published tables the build reads (dim_city_municipality and
psa_poverty_psgc_map) in an in-memory DuckDB. No real PSA or PSGC row is used. The gate pins D-046's
counts (1,642 rows, 1,597 / 1 / 44), so the made-up geography has exactly that shape: 1,641 numbered
places plus a City of Manila whose 14 districts have their own estimates.
"""

import uuid

import pytest

from factories.deped_deliveries import REPO_ROOT
from src.ingestion.store import DuckDBStore

CONTROL = "edu_access.`01-control`"
DIM_CITY = "edu_access.`05-gold`.dim_city_municipality"
MAP = "edu_access.`04-integration`.psa_poverty_psgc_map"
DIM = "edu_access.`05-gold`.dim_city_poverty"
BUILD = REPO_ROOT / "etl" / "05_gold" / "06_build_dim_city_poverty.sql"
GATE = REPO_ROOT / "etl" / "05_gold" / "90_validate_dim_city_poverty.sql"

MANILA = "1380600000"
DISTRICTS = [f"13806{d:02d}000" for d in range(1, 15)]
PLACES = [f"01{i:05d}000" for i in range(1641)]        # 1,641 places plus Manila: 1,642 regular members
ESTIMATED, NO_ESTIMATE = PLACES[:1597], PLACES[1597]   # the other 43 places, and Manila, are not in the PSA file
NEGATIVE_LOWER = PLACES[0]

MANILA_REASON = "City of Manila not in the PSA estimates; its 14 district estimates are not combined"
NOT_IN_SOURCE_REASON = "not in the PSA city and municipal estimates"


def estimate(i):
    """incidence, cv, lower, upper: some CVs above 20, and one lower limit below 0 as PSA publishes it."""
    incidence = 10.0 + (i % 30) + 0.123456789
    cv = 5.0 + (i % 40) * 0.75
    lower = -0.02 if i == 0 else incidence - 4.5
    return incidence, cv, lower, incidence + 4.5


def map_row(code, level, status, i, year=2023, match_status="matched"):
    values = estimate(i) if status == "estimated" else (None, None, None, None)
    if status == "partial_estimate":
        values = estimate(i)[:3] + (None,)
    incidence, cv, lower, upper = values
    return (f"P{i:05d}/{year}", year, code, level, match_status, status, incidence, cv, lower, upper)


def default_map():
    rows = [map_row(code, "city_mun", "estimated", i) for i, code in enumerate(ESTIMATED)]
    rows.append(map_row(NO_ESTIMATE, "city_mun", "no_estimate", 1597))
    rows += [map_row(code, "sub_mun", "estimated", 2000 + i) for i, code in enumerate(DISTRICTS)]
    rows += [map_row(code, "city_mun", "estimated", i, year=2021) for i, code in enumerate(PLACES[:5])]  # never read
    return rows


class Env:
    def __init__(self, map_rows=None, map_run_status="succeeded"):
        self.store = DuckDBStore()
        for path in sorted((REPO_ROOT / "etl" / "01_control").glob("0[1-4]_*.sql")):
            self.store.run_file(path)
        for schema in ("04-integration", "05-gold"):
            self.store.sql(f"CREATE SCHEMA IF NOT EXISTS edu_access.`{schema}`")
        self.store.sql(f"CREATE TABLE {DIM_CITY} (city_mun_psgc_code STRING, city_mun_name STRING, city_class STRING, "
                       "member_type STRING)")
        self.store.con.executemany(
            "INSERT INTO edu_access.\"05-gold\".dim_city_municipality VALUES (?, ?, ?, ?)",
            [(c, f"Place {c}", None, "regular") for c in PLACES] + [(MANILA, "City of Manila", "HUC", "regular")]
            + [("UNKNOWN", "Unknown", None, "unknown"), ("EXCLUDED", "Excluded", None, "excluded")])
        self.store.sql(f"CREATE TABLE {MAP} (source_row_ref STRING, estimate_year INT, psgc_code STRING, "
                       "geographic_level STRING, match_status STRING, estimate_status STRING, poverty_incidence DOUBLE, "
                       "coefficient_of_variation DOUBLE, ci90_lower_limit DOUBLE, ci90_upper_limit DOUBLE, run_id STRING)")
        self.load_map(default_map() if map_rows is None else map_rows)
        self.store.sql(f"INSERT INTO {CONTROL}.pipeline_runs (run_id, pipeline_name, source_id, environment, status, "
                       "code_revision, started_at_utc) VALUES ('M1', 'integration_build', 'psa_poverty_stat', 'local', ?, "
                       "'c', TIMESTAMP '2026-10-19 00:00:00')", [map_run_status])

    def load_map(self, rows):
        self.store.sql(f"DELETE FROM {MAP}")
        self.store.con.executemany(
            "INSERT INTO edu_access.\"04-integration\".psa_poverty_psgc_map VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'M1')", rows)

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


def test_one_row_per_regular_member_with_the_d046_counts():
    env = Env()
    run_id, error = env.run()
    assert error is None
    dim = env.dim()
    assert len(dim) == 1642 and "UNKNOWN" not in dim and "EXCLUDED" not in dim
    assert not set(DISTRICTS) & set(dim)
    checks = env.checks(run_id)
    assert {c["status"] for c in checks.values()} == {"PASS"}
    statuses = [r["poverty_status"] for r in dim.values()]
    assert (statuses.count("estimated"), statuses.count("no_estimate"), statuses.count("not_in_source")) == (1597, 1, 44)
    assert checks["district_rows_kept_out"]["actual"] == "14"
    assert checks["manila_reason_on_city_of_manila"]["actual"] == "1"
    assert checks["map_rows_carried"]["actual"] == "1598"
    assert checks["upstream_run_psa_poverty_psgc_map"]["status"] == "PASS"


def test_columns_follow_the_data_model():
    env = Env()
    env.run()
    assert env.store.columns("05-gold", "dim_city_poverty") == [
        ("city_mun_psgc_code", "VARCHAR"), ("estimate_year", "INTEGER"), ("poverty_incidence", "DOUBLE"),
        ("poverty_ci90_lower", "DOUBLE"), ("poverty_ci90_upper", "DOUBLE"), ("poverty_cv", "DOUBLE"),
        ("cv_over_20", "BOOLEAN"), ("poverty_status", "VARCHAR"), ("status_reason", "VARCHAR")]
    dim = env.dim()
    row = dim[ESTIMATED[25]]
    incidence, cv, lower, upper = estimate(25)
    assert (row["poverty_incidence"], row["poverty_cv"], row["poverty_ci90_lower"], row["poverty_ci90_upper"]) == \
        (incidence, cv, lower, upper)                    # not rounded
    assert (row["estimate_year"], row["cv_over_20"], row["status_reason"]) == (2023, True, None)
    assert dim[ESTIMATED[1]]["cv_over_20"] is False
    assert dim[NEGATIVE_LOWER]["poverty_ci90_lower"] == -0.02   # stored as published, never clipped to 0
    none = dim[NO_ESTIMATE]
    assert none["poverty_status"] == "no_estimate" and none["status_reason"] == "PSA published no 2023 estimate"
    assert none["poverty_incidence"] is None and none["poverty_cv"] is None and none["cv_over_20"] is None
    manila = dim[MANILA]
    assert (manila["poverty_status"], manila["status_reason"], manila["poverty_incidence"]) == \
        ("not_in_source", MANILA_REASON, None)           # its 14 districts are not combined
    other = dim[PLACES[-1]]
    assert (other["poverty_status"], other["status_reason"], other["cv_over_20"]) == \
        ("not_in_source", NOT_IN_SOURCE_REASON, None)


def test_rerun_gives_the_same_table():
    env = Env()
    env.run()
    first = env.dim()
    _, error = env.run()
    assert error is None
    assert env.dim() == first


def partial(rows):
    """A 2023 estimate with its upper limit blank: Silver's partial_estimate."""
    return [map_row(ESTIMATED[3], "city_mun", "partial_estimate", 3) if r[2] == ESTIMATED[3] and r[1] == 2023 else r
            for r in rows]


def unmatched(rows):
    """A 2023 city row the map could not place: its estimate would be lost from Gold."""
    return [map_row(None, None, "estimated", 3, match_status="unmatched") if r[2] == ESTIMATED[3] and r[1] == 2023 else r
            for r in rows]


def doubled(rows):
    """Two 2023 rows matched to one place: the join would repeat the key."""
    return rows + [map_row(ESTIMATED[3], "city_mun", "estimated", 9999)]


def no_estimate_dropped(rows):
    """The PSA row for the no-estimate place is gone, so the place reads not_in_source."""
    return [r for r in rows if r[2] != NO_ESTIMATE]


def districts_elsewhere(rows):
    """Manila's 14 districts coded under another place not in the PSA file: the rule would give that place the
    Manila reason, and the count of Manila reasons would still be 1."""
    other = PLACES[1600][:5]
    return [map_row(other + r[2][5:], "sub_mun", "estimated", 2000) if r[3] == "sub_mun" else r for r in rows]


@pytest.mark.parametrize("change, failed", [
    (partial, {"no_partial_estimate", "poverty_status_allowed", "estimated_match_pin", "status_reason_allowed",
               "no_value_without_estimate"}),
    (unmatched, {"map_rows_matched", "map_rows_carried", "estimated_match_pin", "not_in_source_match_pin"}),
    (doubled, {"key_unique", "rows_match_pin", "estimated_match_pin", "values_equal_map"}),
    (no_estimate_dropped, {"no_estimate_match_pin", "not_in_source_match_pin"}),
    (districts_elsewhere, {"manila_reason_on_city_of_manila"}),
])
def test_a_failed_check_stops_and_keeps_the_last_good_build(change, failed):
    env = Env()
    _, error = env.run()
    assert error is None
    good = env.dim()
    env.load_map(change(default_map()))
    run_id, error = env.run()
    assert error and "Gold gate failed for dim_city_poverty" in error
    assert {name for name, c in env.checks(run_id).items() if c["status"] == "FAIL"} == failed
    assert env.dim() == good


def test_a_member_outside_the_pin_fails():
    env = Env()
    env.store.sql(f"INSERT INTO {DIM_CITY} VALUES ('0199999000', 'Place 0199999000', NULL, 'regular')")
    run_id, error = env.run()
    assert error
    failed = {name for name, c in env.checks(run_id).items() if c["status"] == "FAIL"}
    assert failed == {"rows_match_pin", "not_in_source_match_pin"}


def test_a_map_from_a_run_that_did_not_succeed_fails():
    env = Env(map_run_status="failed")
    run_id, error = env.run()
    assert error and "Gold gate failed for dim_city_poverty" in error
    assert env.checks(run_id)["upstream_run_psa_poverty_psgc_map"]["status"] == "FAIL"


def test_test_size_data_warns_on_the_pins_and_publishes():
    """Sandbox: with fewer than 1,000 regular members (test data only), the pinned counts, the Manila checks and
    the map-row checks WARN, so a small fixture still publishes; every other check still FAILs."""
    env = Env(map_rows=[map_row(code, "city_mun", "estimated", i) for i, code in enumerate(PLACES[:3])]
              + [map_row(None, None, "estimated", 3, match_status="unmatched")])
    env.store.sql(f"DELETE FROM {DIM_CITY} WHERE member_type = 'regular' AND city_mun_psgc_code NOT IN "
                  f"('{PLACES[0]}', '{PLACES[1]}', '{PLACES[2]}', '{PLACES[3]}')")
    run_id, error = env.run()
    assert error is None
    statuses = {name: c["status"] for name, c in env.checks(run_id).items()}
    assert {name for name, status in statuses.items() if status == "WARN"} == {
        "rows_match_pin", "estimated_match_pin", "no_estimate_match_pin", "not_in_source_match_pin",
        "manila_reason_match_pin", "manila_reason_on_city_of_manila", "map_rows_matched", "map_rows_carried"}
    assert "FAIL" not in statuses.values()
    assert len(env.dim()) == 4
