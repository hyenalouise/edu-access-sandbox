"""Analytics AP4 (#147, BP and AP metrics): the enrollment trend by city or municipality and school year, with the
school-age population gap as census-year context. Build and gate run the way the job's two SQL tasks
run them.

Made-up rows go straight into the two published Gold facts AP4 reads (fact_school_enrollment and
fact_city_school_age_population) in an in-memory DuckDB. No real DepEd or PSA row is used.
"""

import uuid

from factories.deped_deliveries import REPO_ROOT
from src.ingestion.store import DuckDBStore

CONTROL = "edu_access.`01-control`"
AP4 = "edu_access.`06-analytics`.ap4_enrollment_trend"
CANDIDATE = "edu_access.`06-analytics`.ap4_enrollment_trend_candidate"
BUILD = REPO_ROOT / "etl" / "06_analytics" / "04_answer_ap4.sql"
GATE = REPO_ROOT / "etl" / "06_analytics" / "90_validate_ap4.sql"

A, B, MAKATI = "0102801000", "0102802000", "1380300000"
YEARS = ["2020-21", "2023-24", "2024-25", "2025-26"]


def es(n):
    return {"ES": (True, n), "JHS": (False, 0), "SHS": (False, 0)}


# school_id, school_year, city, sector, {level: (is_offered, learner_count)}
SCHOOLS = [
    ("S1", "2020-21", A, "Public", {"ES": (True, 300), "JHS": (True, 200), "SHS": (False, 0)}),
    ("S2", "2020-21", A, "Private", es(50)),
    ("S3", "2020-21", A, "Public", {"ES": (True, 40), "JHS": (True, None), "SHS": (False, 0)}),  # incomplete
    ("S4", "2020-21", A, "PSO", es(999)),                                                         # never counted
    ("S1", "2023-24", A, "Public", es(560)),
    ("S1", "2024-25", A, "Public", {"ES": (True, 280), "JHS": (True, 190), "SHS": (True, 60)}),
    ("S2", "2024-25", A, "SUC/LUC", {"ES": (False, 0), "JHS": (False, 0), "SHS": (True, 30)}),
    ("S1", "2025-26", A, "Public", es(620)),
    ("S5", "2020-21", MAKATI, "Public", es(2000)),
    ("S5", "2024-25", MAKATI, "Public", es(1800)),
    ("S5", "2025-26", MAKATI, "Public", es(1500)),
    ("S8", "2020-21", B, "Public", es(70)),
    ("S8", "2025-26", B, "Public", es(70)),                                                        # no SY 2023-24 or 2024-25 rows
    ("S6", "2024-25", "UNKNOWN", "Private", es(25)),
]
# city, census year, comparable, population per sex for each age 5 to 17 (ages 4 and 18 are added and ignored)
POPULATION = [
    (A, 2020, True, 30), (A, 2024, True, 28),
    (MAKATI, 2020, False, 100), (MAKATI, 2024, False, 40),
    (B, 2020, True, 3), (B, 2024, True, 3),
    ("EXCLUDED", 2020, False, 2),
]
PER_AGE = 13 * 2  # ages 5 to 17, male and female


class Env:
    def __init__(self, schools=SCHOOLS):
        self.store = DuckDBStore()
        for path in sorted((REPO_ROOT / "etl" / "01_control").glob("0[1-4]_*.sql")):
            self.store.run_file(path)
        self.store.sql("CREATE SCHEMA IF NOT EXISTS edu_access.`05-gold`")
        self.store.sql("CREATE TABLE edu_access.`05-gold`.fact_school_enrollment (school_id STRING, school_year STRING, "
                       "education_level_code STRING, city_mun_psgc_code STRING, sector STRING, is_offered BOOLEAN, "
                       "learner_count BIGINT)")
        for school, year, city, sector, levels in schools:
            for level, (offered, count) in levels.items():
                self.store.sql("INSERT INTO edu_access.`05-gold`.fact_school_enrollment VALUES (?, ?, ?, ?, ?, ?, ?)",
                               [school, year, level, city, sector, offered, count])
        self.store.sql("CREATE TABLE edu_access.`05-gold`.fact_city_school_age_population (city_mun_psgc_code STRING, "
                       "reference_year INT, age INT, sex STRING, population BIGINT, is_2020_2024_geography_comparable BOOLEAN)")
        for city, year, comparable, per_age in POPULATION:
            for age in range(4, 19):
                for sex in ("male", "female"):
                    self.store.sql("INSERT INTO edu_access.`05-gold`.fact_city_school_age_population VALUES (?, ?, ?, ?, ?, ?)",
                                   [city, year, age, sex, per_age, comparable])

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
            f"SELECT * FROM {CONTROL}.data_quality_results WHERE run_id = '{run_id}' AND layer = 'analytics'")}

    def rows(self):
        return {(r["city_mun_psgc_code"], r["school_year"]): r for r in self.store.records(f"SELECT * FROM {AP4}")}


def test_one_row_per_member_and_school_year():
    env = Env()
    run_id, error = env.run()
    assert error is None
    rows = env.rows()
    members = {A, B, MAKATI, "UNKNOWN", "EXCLUDED"}
    assert set(rows) == {(m, y) for m in members for y in YEARS}
    checks = env.checks(run_id)
    assert {c["status"] for c in checks.values()} == {"PASS", "WARN"}
    assert checks["schools_incomplete"]["actual"] == "1"
    assert checks["learners_on_technical_members"]["actual"] == "25"
    assert checks["enrollment_2020-21"]["actual"] == str(500 + 50 + 2000 + 70)   # S3 incomplete, S4 PSO
    assert (checks["members_increasing"]["actual"], checks["members_decreasing"]["actual"],
            checks["members_no_change"]["actual"]) == ("1", "1", "1")


def test_enrollment_per_school_year_and_the_trend():
    env = Env()
    env.run()
    rows = env.rows()
    a = {y: rows[(A, y)] for y in YEARS}
    assert [a[y]["enrollment_all_sectors"] for y in YEARS] == [550, 560, 560, 620]
    assert (a["2020-21"]["public_school_enrollment"], a["2020-21"]["schools_counted"], a["2020-21"]["schools_incomplete"]) == (500, 2, 1)
    assert a["2020-21"]["enrollment_change_from_previous_year"] is None
    assert a["2023-24"]["enrollment_change_from_previous_year"] is None   # SY 2022-23 not in the data
    assert a["2024-25"]["enrollment_change_from_previous_year"] == 0
    assert abs(a["2025-26"]["enrollment_change_pct_from_previous_year"] - 60 / 560) < 1e-12
    for y in YEARS:   # the trend is the same on every row of a member
        assert (a[y]["first_school_year"], a[y]["latest_school_year"]) == ("2020-21", "2025-26")
        assert (a[y]["enrollment_change_first_to_latest"], a[y]["enrollment_trend"]) == (70, "increasing")
    assert abs(a["2025-26"]["enrollment_change_pct_first_to_latest"] - 70 / 550) < 1e-12
    assert rows[(MAKATI, "2025-26")]["enrollment_trend"] == "decreasing"
    b = {y: rows[(B, y)] for y in YEARS}
    assert [b[y]["enrollment_all_sectors"] for y in YEARS] == [70, 0, 0, 70]     # no school that year is 0
    assert b["2025-26"]["enrollment_trend"] == "no change"
    assert rows[("UNKNOWN", "2024-25")]["enrollment_trend"] is None


def test_school_age_population_is_context_on_census_school_years_only():
    env = Env()
    env.run()
    rows = env.rows()
    a2020, a2023, a2024 = rows[(A, "2020-21")], rows[(A, "2023-24")], rows[(A, "2024-25")]
    assert (a2020["census_year"], a2020["school_age_population"], a2020["census_context"]) == (2020, 30 * PER_AGE, "available")
    assert a2020["population_enrollment_gap"] == 30 * PER_AGE - 550
    assert abs(a2020["gap_share"] - (30 * PER_AGE - 550) / (30 * PER_AGE)) < 1e-12
    assert (a2020["age_min"], a2020["age_max"]) == (5, 17)
    assert (a2024["census_year"], a2024["school_age_population"]) == (2024, 28 * PER_AGE)
    assert (a2023["census_year"], a2023["school_age_population"], a2023["population_enrollment_gap"], a2023["age_min"]) == (None, None, None, None)
    assert a2023["census_context"] == "not available: no census in this school year"
    makati = rows[(MAKATI, "2024-25")]
    assert makati["population_enrollment_gap"] == 40 * PER_AGE - 1800 < 0       # negative gap kept
    assert makati["is_2020_2024_geography_comparable"] is False
    assert a2024["is_2020_2024_geography_comparable"] is True
    unknown = rows[("UNKNOWN", "2024-25")]
    assert unknown["census_context"] == "not available: no census population for this member"
    assert "not an out-of-school count" in a2024["interpretation_note"]
    assert "Philippine Schools Overseas excluded" in a2024["enrollment_scope"]


def test_rerun_gives_the_same_table():
    env = Env()
    env.run()
    first = env.rows()
    _, error = env.run()
    assert error is None
    assert env.rows() == first


def test_a_changed_value_fails_and_keeps_the_last_good_output():
    for change in ("enrollment_all_sectors = enrollment_all_sectors + 1",
                   "enrollment_trend = 'decreasing'",
                   "census_year = 2024, school_age_population = 1, population_enrollment_gap = 1 - enrollment_all_sectors",
                   "enrollment_change_from_previous_year = 10"):
        env = Env()
        env.run()
        good = env.rows()
        env.store.sql(f"UPDATE {CANDIDATE} SET {change} WHERE city_mun_psgc_code = '{A}' AND school_year = '2023-24'")
        run_id, error = env.run(build=False)
        assert error and "Analytics gate failed for ap4" in error, change
        assert env.rows() == good, change


def test_a_school_in_two_places_in_one_year_fails():
    schools = SCHOOLS + [("S7", "2024-25", A, "Public", {"ES": (True, 10)}),
                         ("S7", "2024-25", MAKATI, "Public", {"JHS": (True, 10)})]
    env = Env(schools)
    run_id, error = env.run()
    assert error
    assert env.checks(run_id)["one_place_per_school_year"]["status"] == "FAIL"


def test_the_gate_summary_is_dropped_after_a_pass_and_a_fail():
    leftovers = "SELECT table_name FROM information_schema.tables WHERE table_name LIKE '%gate_summary_r_%'"
    env = Env()
    _, error = env.run()
    assert error is None and env.store.query(leftovers) == []
    schools = SCHOOLS + [("S7", "2024-25", A, "Public", {"ES": (True, 10)}),
                         ("S7", "2024-25", MAKATI, "Public", {"JHS": (True, 10)})]
    bad = Env(schools)
    _, error = bad.run()
    assert error and bad.store.query(leftovers) == []
