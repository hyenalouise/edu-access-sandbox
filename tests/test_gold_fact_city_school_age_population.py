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

# census_year, place_row_number, psgc_code (None when unmatched), match_status, base population
PLACES = [
    (2020, 10, "0102801000", "matched", 100),
    (2020, 11, "1380300000", "matched", 200),      # City of Makati: territory changed
    (2020, 12, None, "unmatched", 7),               # an SGA cluster
    (2020, 13, None, "unmatched", 3),               # another
    (2024, 10, "0102801000", "matched", 110),
    (2024, 11, "1380300000", "matched", 190),
    (2024, 12, "1999901000", "matched", 9),         # 2024 only
]
DIM = [("0102801000", "regular"), ("1380300000", "regular"), ("1999901000", "regular"),
       ("UNKNOWN", "unknown"), ("EXCLUDED", "excluded")]


class Env:
    def __init__(self, places=PLACES, dim=DIM):
        self.store = DuckDBStore()
        for path in sorted((REPO_ROOT / "etl" / "01_control").glob("0[1-4]_*.sql")):
            self.store.run_file(path)
        for schema in ("03-silver", "04-integration", "05-gold"):
            self.store.sql(f"CREATE SCHEMA IF NOT EXISTS edu_access.`{schema}`")
        self.store.sql("CREATE TABLE edu_access.`03-silver`.psa_school_age_population_clean (census_year INT, "
                       "level STRING, population_concept STRING, sex STRING, age INT, population BIGINT, "
                       "batch_id STRING, place_row_number BIGINT)")
        self.store.sql("CREATE TABLE edu_access.`04-integration`.psa_school_age_population_psgc_map (census_year INT, "
                       "batch_id STRING, place_row_number BIGINT, psgc_code STRING, match_status STRING)")
        self.store.sql("CREATE TABLE edu_access.`05-gold`.dim_city_municipality (city_mun_psgc_code STRING, member_type STRING)")
        for code, member_type in dim:
            self.store.sql("INSERT INTO edu_access.`05-gold`.dim_city_municipality VALUES (?, ?)", [code, member_type])
        for year, row, code, status, base in places:
            batch = f"B{year}"
            self.store.sql("INSERT INTO edu_access.`04-integration`.psa_school_age_population_psgc_map VALUES (?, ?, ?, ?, ?)",
                           [year, batch, row, code, status])
            # a province row and a household row with the same place row: never read
            self.store.sql("INSERT INTO edu_access.`03-silver`.psa_school_age_population_clean VALUES "
                           "(?, 'province', 'total', 'male', 5, 999, ?, ?)", [year, batch, row])
            for age in AGES:
                male, female = base + age, base + 2 * age
                for concept in ("total", "household"):
                    for sex, value in (("male", male), ("female", female), ("both", male + female)):
                        self.store.sql("INSERT INTO edu_access.`03-silver`.psa_school_age_population_clean VALUES "
                                       "(?, 'city_municipality', ?, ?, ?, ?, ?, ?)",
                                       [year, concept, sex, age, value if concept == "total" else value - 1, batch, row])

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

    def fact(self):
        return {(r["city_mun_psgc_code"], r["reference_year"], r["age"], r["sex"]): r
                for r in self.store.records(f"SELECT * FROM {FACT}")}


def test_builds_male_and_female_rows_per_city_year_and_age():
    env = Env()
    run_id, error = env.run()
    assert error is None
    fact = env.fact()
    # 2020: 2 matched places + UNKNOWN; 2024: 3 matched places; 3 ages x 2 sexes each
    assert len(fact) == (3 + 3) * len(AGES) * 2
    assert {k[3] for k in fact} == {"male", "female"}
    checks = env.checks(run_id)
    assert {c["status"] for c in checks.values()} == {"PASS", "WARN"}
    assert checks["unknown_member_population"]["status"] == "WARN"


def test_total_concept_only_and_unmatched_places_summed_into_unknown():
    env = Env()
    env.run()
    fact = env.fact()
    assert fact[("0102801000", 2020, 17, "female")]["population"] == 100 + 34
    unknown = fact[("UNKNOWN", 2020, 5, "male")]
    assert (unknown["population"], unknown["psgc_match_status"]) == ((7 + 5) + (3 + 5), "unmatched")
    assert fact[("0102801000", 2024, 5, "male")]["psgc_match_status"] == "matched"


def test_comparability_flag():
    env = Env()
    env.run()
    flags = {(k[0], k[1]): r["is_2020_2024_geography_comparable"] for k, r in env.fact().items()}
    assert flags == {
        ("0102801000", 2020): True, ("0102801000", 2024): True,
        ("1380300000", 2020): False, ("1380300000", 2024): False,   # in the reviewed territory-change list
        ("1999901000", 2024): False,                                 # 2024 only
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
