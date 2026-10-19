"""Gold fact_school_enrollment (#46): its build and gate, run the way the job's two SQL tasks run them.

Made-up rows go straight into the published tables the build reads (deped_enrollment_clean,
deped_school_psgc_map) and the five dimensions its gate checks keys against, in an in-memory DuckDB.
No real DepEd or PSGC row is used.
"""

import uuid

import pytest

from factories.deped_deliveries import REPO_ROOT
from src.ingestion.store import DuckDBStore

CONTROL = "edu_access.`01-control`"
SILVER = "edu_access.`03-silver`.deped_enrollment_clean"
MAP = "edu_access.`04-integration`.deped_school_psgc_map"
GOLD = "edu_access.`05-gold`"
FACT = f"{GOLD}.fact_school_enrollment"
BUILD = REPO_ROOT / "etl" / "05_gold" / "10_build_fact_school_enrollment.sql"
GATE = REPO_ROOT / "etl" / "05_gold" / "90_validate_fact_school_enrollment.sql"

SEXES = ("male", "female")
ES = [f"{g}_{s}" for g in ["kinder"] + [f"g{i}" for i in range(1, 7)] + ["esng"] for s in SEXES]
JHS = [f"{g}_{s}" for g in [f"g{i}" for i in range(7, 11)] + ["jhsng"] for s in SEXES]
STRANDS = ["abm", "arts", "gas", "humss", "maritime", "sports", "stem", "tvl"]
SHS = [f"{g}_{t}_{s}" for g in ("g11", "g12") for t in STRANDS for s in SEXES]
UNIQUE = [f"{g}_unique_{s}" for g in ("g11", "g12") for s in SEXES]
SSHS = [f"g11_sshs_{t}_{s}" for t in ("acad", "techpro") for s in SEXES]
CELLS = ES + JHS + SHS + UNIQUE + SSHS

CITY, BARANGAY, OTHER_CITY, OTHER_BARANGAY = "0102801000", "0102801001", "0102802000", "0102802001"


def school(school_id, school_year="2023-24", sector="Public", offers=(True, True, False), cells=None, overseas=False):
    """A Silver row: ES and JHS cells 1 when offered, every other cell NULL unless `cells` says otherwise."""
    row = {"school_year": school_year, "school_id": school_id, "sector": sector, "annex_status": "Mother school",
           "offers_es": offers[0], "offers_jhs": offers[1], "offers_shs": offers[2], "is_overseas": overseas}
    row.update({c: (1 if (c in ES and offers[0]) or (c in JHS and offers[1]) else None) for c in CELLS})
    row.update(cells or {})
    return row


def geography(school_id, school_year="2023-24", city=("matched", CITY), barangay=("matched", BARANGAY)):
    return [(school_year, school_id, "city_mun", city[1], city[0]), (school_year, school_id, "bgy", barangay[1], barangay[0])]


def shs(n, school_year):
    """SHS cells for a school year: n in every applicable cell, NULL where DepEd had not started the cell."""
    year = int(school_year[:4])
    cells = {c: n for c in SHS}
    cells.update({c: (n if year >= 2024 else None) for c in UNIQUE})
    cells.update({c: (n if year >= 2025 else None) for c in SSHS})
    return cells


SCHOOLS = [
    school("100001"),                                                         # matched, ES and JHS offered
    school("100002", cells={"g7_male": None}),                                # JHS offered with one blank cell
    school("100003", offers=(True, False, True), cells={**{c: None for c in JHS}, **shs(2, "2023-24")}),
    school("100004", sector="Private"),                                       # city not matched
    school("100005", sector="PSO", overseas=True),                            # overseas: excluded
    school("100001", school_year="2025-26", offers=(True, False, True), cells={**{c: None for c in JHS}, **shs(1, "2025-26")}),
    school("100003", school_year="2025-26", offers=(False, False, True),
           cells={**{c: None for c in ES + JHS}, **shs(1, "2024-25")}),       # SSHS cells blank in 2025-26
]
GEOGRAPHY = (geography("100001") + geography("100002", barangay=("unmatched", None))
             + geography("100003") + geography("100004", city=("unmatched", None), barangay=("unmatched", None))
             + geography("100005", city=("excluded", None), barangay=("excluded", None))
             + geography("100001", "2025-26") + geography("100003", "2025-26", city=("matched", OTHER_CITY),
                                                          barangay=("matched", OTHER_BARANGAY)))


class Env:
    def __init__(self, schools=SCHOOLS, geo=GEOGRAPHY, map_run_status="succeeded"):
        self.store = DuckDBStore()
        for path in sorted((REPO_ROOT / "etl" / "01_control").glob("0[1-4]_*.sql")):
            self.store.run_file(path)
        for schema in ("03-silver", "04-integration", "05-gold"):
            self.store.sql(f"CREATE SCHEMA IF NOT EXISTS edu_access.`{schema}`")
        cells = ", ".join(f"{c} INT" for c in CELLS)
        self.store.sql(f"CREATE TABLE {SILVER} (school_year STRING, school_id STRING, sector STRING, annex_status STRING, "
                       f"offers_es BOOLEAN, offers_jhs BOOLEAN, offers_shs BOOLEAN, is_overseas BOOLEAN, {cells}, run_id STRING)")
        self.store.sql(f"CREATE TABLE {MAP} (school_year STRING, school_id STRING, geographic_level STRING, "
                       "psgc_code STRING, match_status STRING, run_id STRING)")
        self.load(schools, geo)
        self.store.sql(f"CREATE TABLE {GOLD}.dim_education_level (education_level_code STRING, education_level_name STRING)")
        self.store.sql(f"INSERT INTO {GOLD}.dim_education_level VALUES ('ES', 'Elementary School'), "
                       "('JHS', 'Junior High School'), ('SHS', 'Senior High School')")
        self.store.sql(f"CREATE TABLE {GOLD}.dim_city_municipality (city_mun_psgc_code STRING, member_type STRING)")
        self.store.sql(f"INSERT INTO {GOLD}.dim_city_municipality VALUES ('{CITY}', 'regular'), ('{OTHER_CITY}', 'regular'), "
                       "('UNKNOWN', 'unknown'), ('EXCLUDED', 'excluded')")
        self.store.sql(f"CREATE TABLE {GOLD}.dim_barangay (barangay_psgc_code STRING, city_mun_psgc_code STRING, member_type STRING)")
        self.store.sql(f"INSERT INTO {GOLD}.dim_barangay VALUES ('{BARANGAY}', '{CITY}', 'regular'), "
                       f"('{OTHER_BARANGAY}', '{OTHER_CITY}', 'regular'), ('{CITY}-UNKNOWN', '{CITY}', 'unknown'), "
                       f"('{OTHER_CITY}-UNKNOWN', '{OTHER_CITY}', 'unknown'), ('UNKNOWN', 'UNKNOWN', 'unknown'), "
                       "('EXCLUDED', 'EXCLUDED', 'excluded')")
        for pipeline, status in (("silver_build", "succeeded"), ("integration_build", map_run_status)):
            self.store.sql(f"INSERT INTO {CONTROL}.pipeline_runs (run_id, pipeline_name, source_id, environment, status, "
                           "code_revision, started_at_utc) VALUES (?, ?, 'deped_enrollment', 'local', ?, 'c', "
                           "TIMESTAMP '2026-10-19 00:00:00')", ["S1" if pipeline == "silver_build" else "M1", pipeline, status])

    def load(self, schools, geo):
        """Replace the published Silver and map rows, and the school dimensions built from them."""
        for table in (SILVER, MAP):
            self.store.sql(f"DELETE FROM {table}")
        columns = ["school_year", "school_id", "sector", "annex_status", "offers_es", "offers_jhs", "offers_shs",
                   "is_overseas"] + CELLS
        marks = ", ".join("?" for _ in columns)
        for row in schools:
            self.store.sql(f"INSERT INTO {SILVER} ({', '.join(columns)}, run_id) VALUES ({marks}, 'S1')",
                           [row[c] for c in columns])
        for row in geo:
            self.store.sql(f"INSERT INTO {MAP} VALUES (?, ?, ?, ?, ?, 'M1')", list(row))
        self.store.sql(f"CREATE OR REPLACE TABLE {GOLD}.dim_school AS SELECT DISTINCT school_id FROM {SILVER}")
        self.store.sql(f"CREATE OR REPLACE TABLE {GOLD}.dim_school_year AS SELECT DISTINCT school_year FROM {SILVER}")

    def run(self, tamper=None):
        """Run the build and the gate; `tamper` is SQL run on the candidate between them, a stand-in for a build error."""
        run_id = str(uuid.uuid4())
        params = {"run_id": run_id, "code_revision": "c" * 40, "environment": "local"}
        try:
            self.store.run_file(BUILD, params)
            if tamper:
                self.store.sql(tamper)
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
        return {(r["school_id"], r["school_year"], r["education_level_code"]): r
                for r in self.store.records(f"SELECT * FROM {FACT}")}


def test_three_rows_per_school_year_and_the_data_model_columns():
    env = Env()
    run_id, error = env.run()
    assert error is None
    assert len(env.fact()) == 3 * len(SCHOOLS)
    assert env.store.columns("05-gold", "fact_school_enrollment") == [
        ("school_id", "VARCHAR"), ("school_year", "VARCHAR"), ("education_level_code", "VARCHAR"),
        ("city_mun_psgc_code", "VARCHAR"), ("barangay_psgc_code", "VARCHAR"), ("psgc_match_status", "VARCHAR"),
        ("sector", "VARCHAR"), ("annex_status", "VARCHAR"), ("is_offered", "BOOLEAN"), ("learner_count", "BIGINT")]
    checks = env.checks(run_id)
    assert not env.failed(run_id)
    assert checks["rows_reconcile"]["actual"] == "21"
    assert {checks[n]["actual"] for n in ("upstream_run_deped_enrollment_clean", "upstream_run_deped_school_psgc_map")} == {"S1", "M1"}


def test_learner_count_follows_the_metric_specification():
    env = Env()
    env.run()
    fact = env.fact()
    count = lambda s, y, l: fact[(s, y, l)]["learner_count"]
    assert count("100001", "2023-24", "ES") == 16                      # every cell published
    assert count("100001", "2023-24", "SHS") == 0                      # not offered: 0, cells left upstream
    assert fact[("100001", "2023-24", "SHS")]["is_offered"] is False
    assert count("100002", "2023-24", "JHS") is None                   # offered, one blank cell: never a partial sum
    assert count("100003", "2023-24", "SHS") == 64                     # 32 strand cells; unique and SSHS not yet started
    assert count("100001", "2025-26", "SHS") == 40                     # 32 + unique 4 + SSHS 4
    assert count("100003", "2025-26", "SHS") is None                   # SSHS cells blank in 2025-26
    checks = env.checks(env.run()[0])
    assert checks["offered_partial/2023-24/JHS"]["status"] == "WARN"
    assert checks["offered_partial/2025-26/SHS"]["actual"] == "1"
    assert checks["partial_published_cells/2025-26/SHS"]["actual"] == "36"  # an audit value, not a learner_count
    assert checks["learners/2023-24/ES"]["actual"] == "80"


def test_geography_takes_a_member_for_every_status():
    env = Env()
    run_id, _ = env.run()
    fact = env.fact()
    geo = lambda s, y: (lambda r: (r["city_mun_psgc_code"], r["barangay_psgc_code"], r["psgc_match_status"]))(fact[(s, y, "ES")])
    assert geo("100001", "2023-24") == (CITY, BARANGAY, "matched")
    assert geo("100002", "2023-24") == (CITY, f"{CITY}-UNKNOWN", "matched")    # city found, no single barangay
    assert geo("100004", "2023-24") == ("UNKNOWN", "UNKNOWN", "unmatched")
    assert geo("100005", "2023-24") == ("EXCLUDED", "EXCLUDED", "excluded")
    assert geo("100003", "2025-26") == (OTHER_CITY, OTHER_BARANGAY, "matched")  # moved: counted where it was that year
    assert geo("100003", "2023-24") == (CITY, BARANGAY, "matched")
    checks = env.checks(run_id)
    assert (checks["schools_city_unknown"]["status"], checks["schools_city_unknown"]["actual"]) == ("WARN", "1")
    assert checks["schools_barangay_unknown"]["actual"] == "1"
    assert checks["schools_excluded"]["actual"] == "1"


def test_rerun_gives_the_same_table():
    env = Env()
    env.run()
    first = env.fact()
    _, error = env.run()
    assert error is None
    assert env.fact() == first


def replace(rows, school_id, **changes):
    return [dict(r, **changes) if r["school_id"] == school_id and r["school_year"] == "2023-24" else r for r in rows]


@pytest.mark.parametrize("schools, geo, failed", [
    (replace(SCHOOLS, "100001", offers_jhs=None), GEOGRAPHY, {"offering_flag_published", "offering_flag_blank/2023-24/JHS"}),
    (replace(SCHOOLS, "100001", g11_abm_male=3), GEOGRAPHY,
     {"not_offered_without_learners", "not_offered_positive/2023-24/SHS"}),
    (replace(SCHOOLS, "100003", g11_unique_male=5), GEOGRAPHY, {"cells_before_start_blank"}),  # unique cells start 2024-25
    (SCHOOLS, [g for g in GEOGRAPHY if g[1] != "100002"],
     {"geography_not_null", "member_follows_status", "city_in_dimension", "barangay_in_dimension"}),
    (SCHOOLS, [g if g[:3] != ("2023-24", "100001", "bgy") else ("2023-24", "100001", "bgy", OTHER_BARANGAY, "matched")
               for g in GEOGRAPHY], {"barangay_in_city"}),
    (SCHOOLS, GEOGRAPHY + geography("100001"), {"key_unique", "rows_reconcile"}),        # two map rows for one school year
    (replace(SCHOOLS, "100004", sector="Charter"), GEOGRAPHY, {"sector_allowed"}),
])
def test_a_failed_check_stops_and_keeps_the_last_good_build(schools, geo, failed):
    env = Env()
    _, error = env.run()
    assert error is None
    good = env.fact()
    env.load(schools, geo)
    run_id, error = env.run()
    assert error and "Gold gate failed for fact_school_enrollment" in error
    assert env.failed(run_id) == failed
    assert env.fact() == good


def test_a_key_outside_its_dimension_fails():
    env = Env()
    env.store.sql(f"DELETE FROM {GOLD}.dim_school WHERE school_id = '100004'")
    env.store.sql(f"DELETE FROM {GOLD}.dim_barangay WHERE barangay_psgc_code = '{CITY}-UNKNOWN'")
    run_id, error = env.run()
    assert error
    assert env.failed(run_id) == {"school_in_dimension", "barangay_in_dimension"}


def test_a_map_from_a_run_that_did_not_succeed_fails():
    env = Env(map_run_status="failed")
    run_id, error = env.run()
    assert error and "Gold gate failed for fact_school_enrollment" in error
    assert env.failed(run_id) == {"upstream_run_deped_school_psgc_map"}


CANDIDATE = f"{GOLD}.fact_school_enrollment_candidate"
ROW = "school_id = '100001' AND school_year = '2023-24'"


@pytest.mark.parametrize("tamper, failed", [
    # learner_count and its audit sum changed together: only the recount from Silver sees it.
    (f"UPDATE {CANDIDATE} SET learner_count = learner_count + 1, published_cell_sum = published_cell_sum + 1 "
     f"WHERE {ROW} AND education_level_code = 'ES'", {"learner_count_matches_silver"}),
    # Moved to another valid city and barangay.
    (f"UPDATE {CANDIDATE} SET city_mun_psgc_code = '{OTHER_CITY}', barangay_psgc_code = '{OTHER_BARANGAY}' WHERE {ROW}",
     {"city_matches_map", "barangay_matches_map"}),
    # A reviewed match turned into a valid-looking unmatched row on the UNKNOWN members.
    (f"UPDATE {CANDIDATE} SET psgc_match_status = 'unmatched', city_mun_psgc_code = 'UNKNOWN', "
     f"barangay_psgc_code = 'UNKNOWN' WHERE {ROW}", {"match_status_matches_map", "city_matches_map", "barangay_matches_map"}),
    (f"UPDATE {CANDIDATE} SET sector = 'Private' WHERE {ROW}", {"sector_matches_silver"}),
    (f"UPDATE {CANDIDATE} SET annex_status = 'Annex' WHERE {ROW}", {"annex_status_matches_silver"}),
    # SHS not offered and every cell blank: offered with a NULL count still follows the rule on its own.
    (f"UPDATE {CANDIDATE} SET is_offered = TRUE, learner_count = NULL WHERE {ROW} AND education_level_code = 'SHS'",
     {"is_offered_matches_silver", "learner_count_matches_silver"}),
    (f"UPDATE {CANDIDATE} SET school_id = '100009' WHERE {ROW} AND education_level_code = 'ES'",
     {"rows_match_silver", "school_in_dimension"}),
])
def test_a_build_error_that_still_looks_valid_fails_against_silver_and_the_map(tamper, failed):
    env = Env()
    run_id, error = env.run(tamper)
    assert error and "Gold gate failed for fact_school_enrollment" in error
    assert env.failed(run_id) == failed
