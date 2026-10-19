"""Gold fact_city_school_age_population (#46): its build and gate, run the way the job's two SQL tasks run them.

Made-up rows go straight into the published tables the build and gate read (psa_school_age_population_clean,
psa_school_age_population_psgc_map, dim_city_municipality) in an in-memory DuckDB. No real PSA row is used.
"""

import uuid

from factories.deped_deliveries import REPO_ROOT
from src.ingestion.store import DuckDBStore

CONTROL = "edu_access.`01-control`"
FACT = "edu_access.`05-gold`.fact_city_school_age_population"
BUILD = REPO_ROOT / "etl" / "05_gold" / "14_build_fact_city_school_age_population.sql"
GATE = REPO_ROOT / "etl" / "05_gold" / "90_validate_fact_city_school_age_population.sql"
AGES = (5, 6, 17)

# census_year, place_row_number, psgc_code (None when unmatched), match_status, review_status, base population
PLACES = [
    (2020, 10, "0102801000", "matched", "rule", 100),
    (2020, 11, "1380300000", "matched", "rule", 200),      # City of Makati: territory changed
    (2020, 12, None, "unmatched", "reviewed", 7),           # an SGA cluster: reviewed, no PSGC unit
    (2020, 13, None, "unmatched", "reviewed", 3),           # another
    (2020, 16, None, "ambiguous", "pending", 2),            # not yet reviewed
    (2024, 10, "0102801000", "matched", "rule", 110),
    (2024, 11, "1380300000", "matched", "rule", 190),
    (2024, 12, "1999901000", "matched", "rule", 9),         # 2024 only
    (2020, 14, "1804501000", "matched", "rule", 50),        # Negros Island Region: only the region changed
    (2024, 13, "1804501000", "matched", "rule", 55),
    (2020, 15, "0906601000", "matched", "rule", 40),        # Sulu: only the province's region changed
    (2024, 14, "0906601000", "matched", "rule", 41),
]
# city_mun_psgc_code, member_type, region_psgc_code, province_psgc_code
DIM = [("0102801000", "regular", "0100000000", "0102800000"), ("1380300000", "regular", "1300000000", None),
       ("1999901000", "regular", "1900000000", "1999900000"), ("1804501000", "regular", "1800000000", None),
       ("0906601000", "regular", "0900000000", "0906600000"),
       ("UNKNOWN", "unknown", None, None), ("EXCLUDED", "excluded", None, None)]


class Env:
    def __init__(self, places=PLACES, dim=DIM):
        self.store = DuckDBStore()
        for path in sorted((REPO_ROOT / "etl" / "01_control").glob("0[1-4]_*.sql")):
            self.store.run_file(path)
        for schema in ("03-silver", "04-integration", "05-gold"):
            self.store.sql(f"CREATE SCHEMA IF NOT EXISTS edu_access.`{schema}`")
        self.store.sql("CREATE TABLE edu_access.`03-silver`.psa_school_age_population_clean (census_year INT, "
                       "level STRING, population_concept STRING, sex STRING, age INT, population BIGINT, "
                       "batch_id STRING, place_row_number BIGINT, run_id STRING)")
        self.store.sql("CREATE TABLE edu_access.`04-integration`.psa_school_age_population_psgc_map (census_year INT, "
                       "batch_id STRING, place_row_number BIGINT, psgc_code STRING, match_status STRING, review_status STRING, "
                       "run_id STRING)")
        self.store.sql("CREATE TABLE edu_access.`05-gold`.dim_city_municipality (city_mun_psgc_code STRING, "
                       "member_type STRING, region_psgc_code STRING, province_psgc_code STRING)")
        for row in dim:
            self.store.sql("INSERT INTO edu_access.`05-gold`.dim_city_municipality VALUES (?, ?, ?, ?)", list(row))
        for run, pipeline_name in (("S1", "silver_build"), ("M1", "integration_build")):
            self.store.sql(f"INSERT INTO {CONTROL}.pipeline_runs (run_id, pipeline_name, source_id, environment, status, code_revision, "
                           "started_at_utc) VALUES (?, ?, 'psa_school_age_population', 'local', 'succeeded', 'c', "
                           "TIMESTAMP '2026-10-19 00:00:00')", [run, pipeline_name])
        for year, row, code, status, review, base in places:
            batch = f"B{year}"
            self.store.sql("INSERT INTO edu_access.`04-integration`.psa_school_age_population_psgc_map VALUES (?, ?, ?, ?, ?, ?, 'M1')",
                           [year, batch, row, code, status, review])
            # a province row and a household row with the same place row: never read
            self.store.sql("INSERT INTO edu_access.`03-silver`.psa_school_age_population_clean VALUES "
                           "(?, 'province', 'total', 'male', 5, 999, ?, ?, 'S1')", [year, batch, row])
            for age in AGES:
                male, female = base + age, base + 2 * age
                for concept in ("total", "household"):
                    for sex, value in (("male", male), ("female", female), ("both", male + female)):
                        self.store.sql("INSERT INTO edu_access.`03-silver`.psa_school_age_population_clean VALUES "
                                       "(?, 'city_municipality', ?, ?, ?, ?, ?, ?, 'S1')",
                                       [year, concept, sex, age, value if concept == "total" else value - 1, batch, row])

    def run(self, build=True):
        run_id = str(uuid.uuid4())
        params = {"run_id": run_id, "code_revision": "c" * 40, "environment": "local"}
        try:
            if build:
                self.store.run_file(BUILD, params)
            self.store.run_file(GATE, params)
        except Exception as e:
            return run_id, str(e)
        return run_id, None

    def checks(self, run_id):
        return {r["check_name"]: r for r in self.store.records(
            f"SELECT * FROM {CONTROL}.data_quality_results WHERE run_id = '{run_id}' AND layer = 'gold'")}

    def fact(self):
        return {(r["city_mun_psgc_code"], r["reference_year"], r["age"], r["sex"]): r
                for r in self.store.records(f"SELECT * FROM {FACT}")}


def test_builds_male_and_female_rows_per_city_year_and_age():
    env = Env()
    run_id, error = env.run()
    assert error is None
    fact = env.fact()
    # 2020: 4 matched places + EXCLUDED + UNKNOWN; 2024: 5 matched places; 3 ages x 2 sexes each
    assert len(fact) == (6 + 5) * len(AGES) * 2
    assert {k[3] for k in fact} == {"male", "female"}
    checks = env.checks(run_id)
    assert {c["status"] for c in checks.values()} == {"PASS", "WARN"}
    assert checks["excluded_member_population"]["status"] == "WARN"
    assert checks["unknown_member_population"]["status"] == "WARN"
    assert checks["cells_match_silver"]["status"] == "PASS"


def test_total_concept_only_and_unmatched_places_go_to_a_technical_member():
    env = Env()
    env.run()
    fact = env.fact()
    assert fact[("0102801000", 2020, 17, "female")]["population"] == 100 + 34
    excluded = fact[("EXCLUDED", 2020, 5, "male")]     # the two reviewed clusters, summed
    assert (excluded["population"], excluded["psgc_match_status"]) == ((7 + 5) + (3 + 5), "unmatched")
    unknown = fact[("UNKNOWN", 2020, 5, "male")]       # the pending place
    assert (unknown["population"], unknown["psgc_match_status"]) == (2 + 5, "ambiguous")
    assert fact[("0102801000", 2024, 5, "male")]["psgc_match_status"] == "matched"


def test_comparability_flag():
    env = Env()
    env.run()
    flags = {(k[0], k[1]): r["is_2020_2024_geography_comparable"] for k, r in env.fact().items()}
    assert flags == {
        ("0102801000", 2020): True, ("0102801000", 2024): True,
        ("1380300000", 2020): False, ("1380300000", 2024): False,   # unit: territory changed
        ("1804501000", 2020): True, ("1804501000", 2024): True,     # only its region changed
        ("0906601000", 2020): True, ("0906601000", 2024): True,     # only its province's region changed
        ("1999901000", 2024): False,                                 # 2024 only
        ("EXCLUDED", 2020): False,
        ("UNKNOWN", 2020): False,
    }


def test_rerun_gives_the_same_table():
    env = Env()
    env.run()
    first = env.fact()
    _, error = env.run()
    assert error is None
    assert env.fact() == first


def test_a_code_missing_from_the_city_dimension_fails_and_keeps_the_last_good_build():
    env = Env()
    env.run()
    good = env.fact()
    env.store.sql("DELETE FROM edu_access.`05-gold`.dim_city_municipality WHERE city_mun_psgc_code = '1999901000'")
    run_id, error = env.run()
    assert error and "Gold gate failed for fact_city_school_age_population" in error
    checks = env.checks(run_id)
    assert checks["city_in_dim_city_municipality"]["status"] == "FAIL"
    assert env.fact() == good


def test_a_total_that_does_not_add_up_fails():
    env = Env()
    env.store.sql("UPDATE edu_access.`03-silver`.psa_school_age_population_clean SET population = population + 1 "
                  "WHERE sex = 'both' AND population_concept = 'total' AND level = 'city_municipality' "
                  "AND census_year = 2024 AND place_row_number = 10 AND age = 6")
    run_id, error = env.run()
    assert error
    assert env.checks(run_id)["male_plus_female_is_published_total"]["status"] == "FAIL"


def test_upstream_runs_are_recorded_and_must_have_succeeded():
    env = Env()
    run_id, error = env.run()
    assert error is None
    checks = env.checks(run_id)
    assert (checks["upstream_run_psa_school_age_population_clean"]["actual"],
            checks["upstream_run_psa_school_age_population_psgc_map"]["actual"]) == ("S1", "M1")
    env.store.sql(f"UPDATE {CONTROL}.pipeline_runs SET status = 'failed' WHERE pipeline_name = 'silver_build'")
    run_id, error = env.run()
    assert error
    assert env.checks(run_id)["upstream_run_psa_school_age_population_clean"]["status"] == "FAIL"


def test_a_swapped_sex_or_moved_population_fails_the_cell_check():
    env = Env()
    env.run()
    good = env.fact()
    candidate = "edu_access.`05-gold`.fact_city_school_age_population_candidate"
    # swap male and female for one city, year and age: every total still adds up
    env.store.sql(f"UPDATE {candidate} SET sex = CASE sex WHEN 'male' THEN 'female' ELSE 'male' END "
                  "WHERE city_mun_psgc_code = '0102801000' AND reference_year = 2024 AND age = 6")
    run_id, error = env.run(build=False)
    assert error
    checks = env.checks(run_id)
    assert checks["cells_match_silver"]["status"] == "FAIL"
    assert checks["population_reconciles_by_year"]["status"] == "PASS"
    assert checks["male_plus_female_is_published_total"]["status"] == "PASS"
    assert env.fact() == good


def test_the_gate_holds_the_same_territory_list_as_the_build():
    import re
    codes = lambda path: sorted(re.findall(r"\('(\d{10})'", path.read_text(encoding="utf-8")))
    assert codes(BUILD) == codes(GATE)
    assert len(codes(BUILD)) == 8


def test_the_gate_summary_is_dropped_after_a_pass_and_a_fail():
    leftovers = "SELECT table_name FROM information_schema.tables WHERE table_name LIKE '%gate_summary_r_%'"
    env = Env()
    _, error = env.run()
    assert error is None and env.store.query(leftovers) == []
    env.store.sql("DELETE FROM edu_access.`05-gold`.dim_city_municipality WHERE city_mun_psgc_code = '1999901000'")
    _, error = env.run()
    assert error and env.store.query(leftovers) == []
