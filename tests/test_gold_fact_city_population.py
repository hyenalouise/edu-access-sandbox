"""Gold fact_city_population (#46): its build and gate, run the way the job's two SQL tasks run them.

Made-up rows go straight into the published tables the build reads (dim_city_municipality and
psa_psgc_clean) in an in-memory DuckDB. No real PSGC row is used.
"""

import uuid

import pytest

from factories.deped_deliveries import REPO_ROOT
from src.ingestion.store import DuckDBStore

CONTROL = "edu_access.`01-control`"
DIM_CITY = "edu_access.`05-gold`.dim_city_municipality"
PSGC = "edu_access.`03-silver`.psa_psgc_clean"
FACT = "edu_access.`05-gold`.fact_city_population"
BUILD = REPO_ROOT / "etl" / "05_gold" / "13_build_fact_city_population.sql"
GATE = REPO_ROOT / "etl" / "05_gold" / "90_validate_fact_city_population.sql"

# psgc_code, geographic_level, population, population_null_reason
UNITS = [
    ("0100000000", "Reg", 1500, None),
    ("0102800000", "Prov", 600, None),        # excludes its component city: never read
    ("0102801000", "Mun", 400, None),
    ("0102802000", "City", 200, None),
    ("0102802001", "Bgy", 200, None),
    ("0110000000", "City", 900, None),
    ("0110000001", "Bgy", 0, None),
    ("1380601000", "SubMun", 50, None),       # a district: below the city grain, never read
    ("0990100000", None, None, "publisher_na"),  # a blank-level container: not a member
]
MEMBERS = ["0102801000", "0102802000", "0110000000"]


class Env:
    def __init__(self, units=UNITS, members=MEMBERS, psgc_run_status="succeeded"):
        self.store = DuckDBStore()
        for path in sorted((REPO_ROOT / "etl" / "01_control").glob("0[1-4]_*.sql")):
            self.store.run_file(path)
        for schema in ("03-silver", "05-gold"):
            self.store.sql(f"CREATE SCHEMA IF NOT EXISTS edu_access.`{schema}`")
        self.store.sql(f"CREATE TABLE {PSGC} (psgc_code STRING, geographic_level STRING, population INT, "
                       "population_null_reason STRING, publication_period STRING, is_master_reference BOOLEAN, run_id STRING)")
        for row in units:
            self.store.sql(f"INSERT INTO {PSGC} VALUES (?, ?, ?, ?, '2026-Q2', TRUE, 'S1')", list(row))
        # A non-master quarter with a different population: never read.
        self.store.sql(f"INSERT INTO {PSGC} VALUES ('0102801000', 'Mun', 1, NULL, '2025-Q4', FALSE, 'S0')")
        self.store.sql(f"CREATE TABLE {DIM_CITY} (city_mun_psgc_code STRING, member_type STRING)")
        for code in members:
            self.store.sql(f"INSERT INTO {DIM_CITY} VALUES (?, 'regular')", [code])
        self.store.sql(f"INSERT INTO {DIM_CITY} VALUES ('UNKNOWN', 'unknown'), ('EXCLUDED', 'excluded')")
        self.store.sql(f"INSERT INTO {CONTROL}.pipeline_runs (run_id, pipeline_name, source_id, environment, status, "
                       "code_revision, started_at_utc) VALUES ('S1', 'silver_build', 'psa_psgc', 'local', ?, 'c', "
                       "TIMESTAMP '2026-10-19 00:00:00')", [psgc_run_status])

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

    def failed(self, run_id):
        return {name for name, c in self.checks(run_id).items() if c["status"] == "FAIL"}

    def fact(self):
        return {r["city_mun_psgc_code"]: r for r in self.store.records(f"SELECT * FROM {FACT}")}


def test_one_2024_row_per_regular_member():
    env = Env()
    run_id, error = env.run()
    assert error is None
    fact = env.fact()
    assert sorted(fact) == MEMBERS                     # no technical member, district or container
    assert {r["reference_year"] for r in fact.values()} == {2024}
    assert {code: r["population"] for code, r in fact.items()} == {"0102801000": 400, "0102802000": 200, "0110000000": 900}
    assert {(r["estimate_status"], r["status_reason"]) for r in fact.values()} == {("available", None)}
    checks = env.checks(run_id)
    assert {c["status"] for c in checks.values()} == {"PASS"}
    assert checks["fact_total"]["actual"] == "1500"
    assert checks["total_equals_regions"]["expected"] == "1500"


def test_columns_follow_the_data_model():
    env = Env()
    env.run()
    assert env.store.columns("05-gold", "fact_city_population") == [
        ("city_mun_psgc_code", "VARCHAR"), ("reference_year", "INTEGER"), ("population", "BIGINT"),
        ("estimate_status", "VARCHAR"), ("status_reason", "VARCHAR")]


def test_a_missing_population_stays_null_with_its_reason():
    units = [u if u[0] != "0102802000" else ("0102802000", "City", None, "publisher_na") for u in UNITS]
    env = Env(units=units)
    run_id, error = env.run()
    assert error is None
    row = env.fact()["0102802000"]
    assert (row["population"], row["estimate_status"], row["status_reason"]) == \
        (None, "missing", "PSGC publishes #N/A as the 2024 population")
    checks = env.checks(run_id)
    assert checks["members_without_population"]["status"] == "WARN"
    assert checks["total_equals_regions"]["status"] == "WARN"   # 1,300 against 1,500: the missing city
    assert checks["total_equals_psgc"]["status"] == "PASS"


def test_a_published_zero_stays_zero():
    units = [u if u[0] != "0102801000" else ("0102801000", "Mun", 0, None) for u in UNITS]
    env = Env(units=units)
    run_id, error = env.run()
    assert error is None
    assert env.fact()["0102801000"]["population"] == 0
    assert env.checks(run_id)["members_with_zero_population"]["actual"] == "1"


def test_rerun_gives_the_same_table():
    env = Env()
    env.run()
    first = env.fact()
    _, error = env.run()
    assert error is None
    assert env.fact() == first


@pytest.mark.parametrize("members, units, failed", [
    (MEMBERS + ["0102899000"], UNITS, {"regular_in_psgc_master"}),        # a member PSGC does not have
    (MEMBERS[1:], UNITS, {"total_equals_psgc"}),                           # a PSGC city the dimension lacks
    (MEMBERS, UNITS + [("0102801000", "Mun", 400, None)],
     {"key_unique", "rows_reconcile"}),                                     # a repeated PSGC code
    (MEMBERS, [u if u[0] != "0102801000" else ("0102801000", "Mun", -5, None) for u in UNITS],
     {"population_not_negative"}),
    (MEMBERS, [u if u[0] != "0102801000" else ("0102801000", "Mun", None, "other") for u in UNITS],
     {"status_reason_follows_status"}),                                     # a NULL with no known reason
])
def test_a_failed_check_stops_and_keeps_the_last_good_build(members, units, failed):
    env = Env()
    _, error = env.run()
    assert error is None
    good = env.fact()
    env.store.sql(f"DELETE FROM {PSGC} WHERE is_master_reference")
    for row in units:
        env.store.sql(f"INSERT INTO {PSGC} VALUES (?, ?, ?, ?, '2026-Q2', TRUE, 'S1')", list(row))
    env.store.sql(f"DELETE FROM {DIM_CITY} WHERE member_type = 'regular'")
    for code in members:
        env.store.sql(f"INSERT INTO {DIM_CITY} VALUES (?, 'regular')", [code])
    run_id, error = env.run()
    assert error and "Gold gate failed for fact_city_population" in error
    assert env.failed(run_id) == failed
    assert env.fact() == good


def test_a_psgc_run_that_did_not_succeed_fails():
    env = Env(psgc_run_status="failed")
    run_id, error = env.run()
    assert error and "Gold gate failed for fact_city_population" in error
    assert env.failed(run_id) == {"upstream_run_psa_psgc_clean"}


def test_a_member_psgc_does_not_have_gets_its_reason():
    env = Env(members=MEMBERS + ["0102899000"])
    env.run()
    row = env.store.records(f"SELECT * FROM {FACT}_candidate WHERE city_mun_psgc_code = '0102899000'")[0]
    assert (row["population"], row["estimate_status"], row["status_reason"]) == \
        (None, "missing", "Not a City or Mun row of the PSGC master quarter")


def test_two_master_psgc_periods_fail():
    env = Env()
    env.store.sql(f"INSERT INTO {PSGC} VALUES ('0110000002', 'Bgy', 5, NULL, '2026-Q1', TRUE, 'S1')")
    run_id, error = env.run()
    assert error and "Gold gate failed for fact_city_population" in error
    assert env.failed(run_id) == {"one_psgc_version"}


@pytest.mark.parametrize("tamper, failed", [
    # A status the build has no rule for, with a reason so the presence check alone would pass.
    ("estimate_status = 'provisional', population = NULL, status_reason = 'made up'",
     {"estimate_status_allowed", "status_and_reason_equal_psgc"}),
    # The other valid-looking reason text.
    ("status_reason = 'PSGC publishes no 2024 population'", {"status_and_reason_equal_psgc"}),
])
def test_a_status_or_reason_silver_does_not_give_fails(tamper, failed):
    units = [u if u[0] != "0102802000" else ("0102802000", "City", None, "publisher_na") for u in UNITS]
    env = Env(units=units)
    params = {"run_id": str(uuid.uuid4()), "code_revision": "c" * 40, "environment": "local"}
    env.store.run_file(BUILD, params)
    env.store.sql(f"UPDATE {FACT}_candidate SET {tamper} WHERE city_mun_psgc_code = '0102802000'")
    with pytest.raises(Exception, match="Gold gate failed for fact_city_population"):
        env.store.run_file(GATE, params)
    assert env.failed(params["run_id"]) == failed
