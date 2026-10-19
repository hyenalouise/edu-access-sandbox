"""Revised AP1 to AP4 outputs and the downstream LGU priority matrix."""

from pathlib import Path

import pytest

from src.ingestion.store import DuckDBStore


ROOT = Path(__file__).parents[1]
GOLD = "edu_access.`05-gold`"
ANALYTICS = "edu_access.`06-analytics`"


@pytest.fixture()
def store(tmp_path):
    value = DuckDBStore(tmp_path / "analytics.duckdb")
    value.sql("CREATE SCHEMA IF NOT EXISTS edu_access.`01-control`")
    value.sql("CREATE SCHEMA IF NOT EXISTS edu_access.`05-gold`")
    value.run_file(ROOT / "etl/01_control/04_create_data_quality_results.sql")
    value.sql(f"""CREATE TABLE {GOLD}.dim_city_municipality (
        city_mun_psgc_code STRING, city_mun_name STRING, lgu_type STRING,
        province_psgc_code STRING, province_name STRING, region_psgc_code STRING,
        region_name STRING, member_type STRING)""")
    value.sql(f"""INSERT INTO {GOLD}.dim_city_municipality VALUES
        ('C1','City One','City','P','Province','R','Region','regular'),
        ('C2','City Two','City','P','Province','R','Region','regular'),
        ('M1','Town One','Municipality','P','Province','R','Region','regular'),
        ('M2','Town Two','Municipality','P','Province','R','Region','regular')""")
    value.sql(f"""CREATE TABLE {GOLD}.fact_school_enrollment (
        school_id STRING, school_year STRING, education_level_code STRING,
        city_mun_psgc_code STRING, sector STRING, psgc_match_status STRING,
        annex_status STRING, is_offered BOOLEAN, learner_count BIGINT)""")
    years = ["2020-21", "2021-22", "2022-23", "2023-24", "2024-25", "2025-26"]
    schools = [("S1", "C1", 100), ("S2", "C1", 100), ("S3", "C2", 300),
               ("S4", "M1", 120), ("S5", "M2", 180)]
    for year_index, year in enumerate(years):
        for school_id, code, base in schools:
            learners = base + year_index * 10
            value.sql(f"""INSERT INTO {GOLD}.fact_school_enrollment VALUES
                ('{school_id}','{year}','ES','{code}','Public','matched','Mother School',TRUE,{learners}),
                ('{school_id}','{year}','JHS','{code}','Public','matched','Mother School',FALSE,0),
                ('{school_id}','{year}','SHS','{code}','Public','matched','Mother School',FALSE,0)""")
    value.sql(f"""CREATE TABLE {GOLD}.fact_city_school_age_population (
        city_mun_psgc_code STRING, reference_year INT, age INT, sex STRING,
        population BIGINT, psgc_match_status STRING, is_2020_2024_geography_comparable BOOLEAN)""")
    for code, population in [("C1", 1000), ("C2", 2000), ("M1", 900), ("M2", 1100)]:
        for age in range(5, 18):
            male = population // 26
            female = population // 26
            value.sql(f"INSERT INTO {GOLD}.fact_city_school_age_population VALUES "
                      f"('{code}',2024,{age},'male',{male},'matched',TRUE),"
                      f"('{code}',2024,{age},'female',{female},'matched',TRUE)")
    value.sql(f"""CREATE TABLE {GOLD}.fact_school_classroom_capacity (
        school_id STRING, school_year STRING, instructional_classrooms_total BIGINT)""")
    value.sql(f"""INSERT INTO {GOLD}.fact_school_classroom_capacity VALUES
        ('S1','2023-24',5),('S2','2023-24',5),('S3','2023-24',10),
        ('S4','2023-24',6),('S5','2023-24',9)""")
    value.sql(f"""CREATE TABLE {GOLD}.fact_school_teacher_capacity (
        school_id STRING, school_year STRING, education_level_code STRING, teacher_count BIGINT)""")
    value.sql(f"""INSERT INTO {GOLD}.fact_school_teacher_capacity VALUES
        ('S1','2023-24','ES',5),('S2','2023-24','ES',5),('S3','2023-24','ES',10),
        ('S4','2023-24','ES',6),('S5','2023-24','ES',9)""")
    value.sql(f"""CREATE TABLE {GOLD}.fact_school_year_source_availability (
        school_year STRING, source_id STRING, has_data BOOLEAN)""")
    for year in years:
        value.sql(f"INSERT INTO {GOLD}.fact_school_year_source_availability VALUES "
                  f"('{year}','deped_enrollment',TRUE)")
    yield value
    value.close()


def run(store, file_name):
    store.run_file(ROOT / "etl/06_analytics" / file_name, {
        "run_id": "priority-test", "code_revision": "a" * 40, "environment": "local"})


def test_revised_outputs_and_priority_matrix(store):
    for build, gate in [
        ("01_answer_ap1.sql", "90_validate_ap1.sql"),
        ("02_answer_ap2.sql", "90_validate_ap2.sql"),
        ("03_answer_ap3.sql", "90_validate_ap3.sql"),
        ("04_answer_ap4.sql", "90_validate_ap4.sql"),
        ("05_build_priority_matrix.sql", "90_validate_priority_matrix.sql"),
    ]:
        run(store, build)
        run(store, gate)

    assert store.query(f"SELECT COUNT(*) FROM {ANALYTICS}.lgu_priority_matrix") == [(4,)]
    c2 = store.query(f"""SELECT ap1_classification, ap1_national_same_type_ratio,
        current_pressure_count, enrollment_trend, priority
        FROM {ANALYTICS}.lgu_priority_matrix WHERE city_mun_psgc_code = 'C2'""")[0]
    assert c2[0] == "Above Reference"
    assert c2[1] == pytest.approx((988 + 1976) / 3)
    assert c2[2] in (0, 1, 2, 3)
    assert c2[3] == "Growing"
    assert c2[4] in ("Priority 1", "Priority 3", "Monitor")


def test_no_percentile_priority_logic():
    sql = "\n".join((ROOT / "etl/06_analytics" / name).read_text(encoding="utf-8")
                    for name in ["01_answer_ap1.sql", "02_answer_ap2.sql", "03_answer_ap3.sql",
                                 "04_answer_ap4.sql", "05_build_priority_matrix.sql"])
    assert "PERCENT_RANK" not in sql.upper()
    assert "national_same_type_ratio" in sql
    assert "Data Review" in sql
    assert "PERCENTILE_CONT" in sql  # retained only for the school-level outlier review fence


def test_priority_gate_rejects_wrong_priority(store):
    test_revised_outputs_and_priority_matrix(store)
    before = store.query(f"SELECT * FROM {ANALYTICS}.lgu_priority_matrix ORDER BY city_mun_psgc_code")
    store.sql(f"UPDATE {ANALYTICS}.lgu_priority_matrix_candidate SET priority = 'Priority 1'")
    with pytest.raises(Exception, match="Analytics gate failed"):
        run(store, "90_validate_priority_matrix.sql")
    assert store.query(f"SELECT * FROM {ANALYTICS}.lgu_priority_matrix ORDER BY city_mun_psgc_code") == before


STEPS = [
    ("01_answer_ap1.sql", "90_validate_ap1.sql"),
    ("02_answer_ap2.sql", "90_validate_ap2.sql"),
    ("03_answer_ap3.sql", "90_validate_ap3.sql"),
    ("04_answer_ap4.sql", "90_validate_ap4.sql"),
    ("05_build_priority_matrix.sql", "90_validate_priority_matrix.sql"),
]


def run_all(store):
    for build, gate in STEPS:
        run(store, build)
        run(store, gate)


def add_public_school(store, school_id, code, year, learners, rooms):
    store.sql(f"""INSERT INTO {GOLD}.fact_school_enrollment VALUES
        ('{school_id}','{year}','ES','{code}','Public','matched','Mother School',TRUE,{learners}),
        ('{school_id}','{year}','JHS','{code}','Public','matched','Mother School',FALSE,0),
        ('{school_id}','{year}','SHS','{code}','Public','matched','Mother School',FALSE,0)""")
    store.sql(f"INSERT INTO {GOLD}.fact_school_classroom_capacity VALUES ('{school_id}','{year}',{rooms})")


def test_reference_pools_only_lgus_without_an_input_issue(store):
    # S1 loses its room count, so City One's room coverage is 50% and it must not move the city line.
    store.sql(f"DELETE FROM {GOLD}.fact_school_classroom_capacity WHERE school_id = 'S1'")
    run_all(store)
    rows = dict(store.query(f"""SELECT city_mun_psgc_code, national_same_type_ratio
        FROM {ANALYTICS}.ap2_classroom_pressure WHERE lgu_type = 'City'"""))
    assert rows["C2"] == pytest.approx(330 / 10)
    assert store.query(f"""SELECT input_issue_reason, classification FROM {ANALYTICS}.ap2_classroom_pressure
        WHERE city_mun_psgc_code = 'C1'""") == [("coverage below 90%", "Data Review")]


@pytest.mark.parametrize("learners, rooms, expected", [
    (60, 1, "Above Reference"),   # without the outlier, Town One is still above the line
    (600, 10, "Data Review"),     # without the outlier, Town One drops below the line
])
def test_an_outlier_school_decides_data_review_only_when_it_flips_the_result(store, learners, rooms, expected):
    for n in range(5):
        add_public_school(store, f"T{n}", "M2", "2023-24", 210, 9)
    add_public_school(store, "X1", "M1", "2023-24", learners, rooms)
    run_all(store)
    flag, count, classification = store.query(f"""SELECT outlier_flag, outlier_school_count, classification
        FROM {ANALYTICS}.ap2_classroom_pressure WHERE city_mun_psgc_code = 'M1'""")[0]
    assert flag and count == 1
    assert classification == expected


def test_ap4_applies_the_stable_band(store):
    # Town Two moves from 180 to 185 learners (+2.8%), inside the ±5% band; City One grows by 50%.
    store.sql(f"""UPDATE {GOLD}.fact_school_enrollment SET learner_count = 185
        WHERE school_id = 'S5' AND school_year = '2025-26' AND education_level_code = 'ES'""")
    run_all(store)
    rows = {r[0]: r[1:] for r in store.query(f"""SELECT city_mun_psgc_code, enrollment_2020_21, enrollment_2025_26,
        trend_direction, trend_status FROM {ANALYTICS}.ap4_enrollment_trend""")}
    assert rows["C1"] == (200, 300, "Growing", "Complete")
    assert rows["M2"] == (180, 185, "Stable", "Complete")
    assert store.query(f"""SELECT growing_enrollment_flag FROM {ANALYTICS}.lgu_priority_matrix
        WHERE city_mun_psgc_code = 'C1'""") == [(True,)]


def test_growth_needs_a_complete_trend(store):
    # a large unplaced school in the latest year moves the matched-learner share by more than 2 points
    store.sql(f"""INSERT INTO {GOLD}.fact_school_enrollment VALUES
        ('U1','2025-26','ES','UNKNOWN','Private','unmatched','Mother School',TRUE,500)""")
    run_all(store)
    assert store.query(f"""SELECT DISTINCT enrollment_trend, enrollment_trend_status, growing_enrollment_flag
        FROM {ANALYTICS}.lgu_priority_matrix""") == [
        ("Growing", "Data Review: matched-learner share moved more than 2 points", False)]


def test_gates_record_tier_counts_and_drop_their_summaries(store):
    run_all(store)
    tiers = store.query("""SELECT SUM(CAST(actual AS BIGINT)) FROM edu_access."01-control".data_quality_results
        WHERE source_id = 'lgu_priority_matrix' AND check_name LIKE 'lgus_%'""")
    assert tiers == [(4,)]
    leftovers = "SELECT table_name FROM information_schema.tables WHERE table_name LIKE '%gate_summary_r_%'"
    assert store.query(leftovers) == []
    run(store, "02_answer_ap2.sql")
    store.sql(f"UPDATE {ANALYTICS}.ap2_classroom_pressure_candidate SET outlier_changes_classification = TRUE")
    with pytest.raises(Exception, match="Analytics gate failed"):
        run(store, "90_validate_ap2.sql")
    assert store.query(leftovers) == []


def test_ap2_counts_a_school_with_blank_enrollment_as_not_covered(store):
    # S1 is active (ES has learners) but its offered JHS count is blank: it must lower City One's school coverage,
    # not vanish from both learner sums and leave coverage at 100% (review on #203).
    store.sql(f"""UPDATE {GOLD}.fact_school_enrollment SET is_offered = TRUE, learner_count = NULL
        WHERE school_id = 'S1' AND school_year = '2023-24' AND education_level_code = 'JHS'""")
    run_all(store)
    assert store.query(f"""SELECT active_public_school_count, incomplete_enrollment_school_count, school_coverage_pct,
        input_issue_reason, classification FROM {ANALYTICS}.ap2_classroom_pressure WHERE city_mun_psgc_code = 'C1'""") == [
        (2, 1, 50.0, "coverage below 90%", "Data Review")]
    # City One is left out of the city reference, which is now City Two's own ratio
    assert store.query(f"""SELECT national_same_type_ratio FROM {ANALYTICS}.ap2_classroom_pressure
        WHERE city_mun_psgc_code = 'C2'""") == [(pytest.approx(33.0),)]


def test_ap2_gate_rejects_coverage_that_hides_blank_enrollment(store):
    store.sql(f"""UPDATE {GOLD}.fact_school_enrollment SET is_offered = TRUE, learner_count = NULL
        WHERE school_id = 'S1' AND school_year = '2023-24' AND education_level_code = 'JHS'""")
    for build, gate in STEPS[:1]:
        run(store, build)
        run(store, gate)
    run(store, "02_answer_ap2.sql")
    store.sql(f"""UPDATE {ANALYTICS}.ap2_classroom_pressure_candidate
        SET school_coverage_pct = 100.0, ratio_school_count = active_public_school_count""")
    with pytest.raises(Exception, match="Analytics gate failed"):
        run(store, "90_validate_ap2.sql")
