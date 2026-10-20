"""AP1 to AP4 under the BP and AP metrics, and the LGU priority table under D-057."""

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


STEPS = [
    ("01_answer_ap1.sql", "90_validate_ap1.sql"),
    ("02_answer_ap2.sql", "90_validate_ap2.sql"),
    ("03_answer_ap3.sql", "90_validate_ap3.sql"),
    ("04_answer_ap4.sql", "90_validate_ap4.sql"),
    ("05_build_priority_matrix.sql", "90_validate_priority_matrix.sql"),
]


def run_all(store, steps=STEPS):
    for build, gate in steps:
        run(store, build)
        run(store, gate)


def matrix(store):
    return {r[0]: r[1:] for r in store.query(f"""SELECT city_mun_psgc_code, high_measure_count, tier, tier_code,
        national_tier, is_stable, order_in_tier FROM {ANALYTICS}.lgu_priority_matrix""")}


def test_d057_tiers_from_the_count_of_high_measures(store):
    run_all(store)
    rows = matrix(store)
    # each type has two LGUs, so the higher ratio is at percentile 1.0 (high) and the lower at 0.0
    assert rows["C2"] == (3, "Critical", "3", "Critical", True, 1)
    assert rows["M1"][:3] == (2, "Elevated", "2")
    assert rows["M2"][:3] == (1, "Targeted", "1")
    assert rows["C1"][:3] == (0, "Monitor", "0")
    assert store.query(f"""SELECT high_measures FROM {ANALYTICS}.lgu_priority_matrix
        WHERE city_mun_psgc_code = 'M2'""") == [("AP1 learners per public school",)]
    assert store.query(f"""SELECT high_measures FROM {ANALYTICS}.lgu_priority_matrix
        WHERE city_mun_psgc_code = 'C1'""") == [(None,)]


def test_ap1_ranks_learners_per_school_and_keeps_population_as_context(store):
    run_all(store, STEPS[:1])
    c2 = store.query(f"""SELECT learners_per_public_school, school_age_population_per_public_school,
        within_type_percentile, is_high FROM {ANALYTICS}.ap1_school_provision WHERE city_mun_psgc_code = 'C2'""")[0]
    assert c2 == (330.0, pytest.approx(1976.0), 1.0, True)


def test_a_failed_coverage_gate_sends_the_lgu_to_data_review(store):
    # S6 offers ES in City One but its count is blank: not active, but it lowers AP1 coverage to 2/3
    store.sql(f"""INSERT INTO {GOLD}.fact_school_enrollment VALUES
        ('S6','2023-24','ES','C1','Public','matched','Mother School',TRUE,NULL),
        ('S6','2023-24','JHS','C1','Public','matched','Mother School',FALSE,0),
        ('S6','2023-24','SHS','C1','Public','matched','Mother School',FALSE,0)""")
    run_all(store)
    assert store.query(f"""SELECT blank_enrollment_school_count, coverage_pct, is_assessed, not_assessed_reason,
        within_type_percentile FROM {ANALYTICS}.ap1_school_provision WHERE city_mun_psgc_code = 'C1'""") == [
        (1, pytest.approx(200 / 3), False, "coverage below 90%", None)]
    assert matrix(store)["C1"][1:3] == ("Data review", "data_review")


def test_ap2_gates_on_learner_coverage(store):
    # S1 loses its room count: City One keeps half its learners in the ratio, below the 90% gate
    store.sql(f"DELETE FROM {GOLD}.fact_school_classroom_capacity WHERE school_id = 'S1'")
    run_all(store, STEPS[:2])
    assert store.query(f"""SELECT learner_coverage_pct, is_assessed, not_assessed_reason
        FROM {ANALYTICS}.ap2_classroom_pressure WHERE city_mun_psgc_code = 'C1'""") == [
        (50.0, False, "learner coverage below 90%")]
    # City Two is now the only assessed city, so it ranks alone at 0.0
    assert store.query(f"""SELECT within_type_percentile FROM {ANALYTICS}.ap2_classroom_pressure
        WHERE city_mun_psgc_code = 'C2'""") == [(0.0,)]


def test_ap3_publishes_each_level_and_names_the_highest(store):
    # City One gains a JHS level with the highest JHS ratio among cities
    store.sql(f"""UPDATE {GOLD}.fact_school_enrollment SET is_offered = TRUE, learner_count = 200
        WHERE school_id = 'S1' AND school_year = '2023-24' AND education_level_code = 'JHS'""")
    store.sql(f"""UPDATE {GOLD}.fact_school_enrollment SET is_offered = TRUE, learner_count = 100
        WHERE school_id = 'S3' AND school_year = '2023-24' AND education_level_code = 'JHS'""")
    store.sql(f"""INSERT INTO {GOLD}.fact_school_teacher_capacity VALUES
        ('S1','2023-24','JHS',4), ('S3','2023-24','JHS',4)""")
    run_all(store, STEPS[:3])
    rows = {r[0]: r[1:] for r in store.query(f"""SELECT city_mun_psgc_code, es_learners_per_teacher,
        jhs_learners_per_teacher, jhs_within_type_percentile, highest_level, within_type_percentile, is_high, is_assessed
        FROM {ANALYTICS}.ap3_teacher_pressure WHERE lgu_type = 'City'""")}
    assert rows["C1"] == (26.0, 50.0, 1.0, "JHS", 0.0, False, True)
    # City Two: ES 1.0 and JHS 0.0, so ES is named. Both cities' highest level is 1.0: a tie ranks both at 0.0
    assert rows["C2"] == (33.0, 25.0, 0.0, "ES", 0.0, False, True)


def test_ap3_is_not_assessed_when_a_level_fails_and_none_is_high(store):
    # City One offers JHS with no teacher row: JHS learner coverage is 0%, and ES alone is not high
    store.sql(f"""UPDATE {GOLD}.fact_school_enrollment SET is_offered = TRUE, learner_count = 50
        WHERE school_id = 'S1' AND school_year = '2023-24' AND education_level_code = 'JHS'""")
    run_all(store, STEPS[:3])
    assert store.query(f"""SELECT jhs_passes_gate, is_high, is_assessed, not_assessed_reason
        FROM {ANALYTICS}.ap3_teacher_pressure WHERE city_mun_psgc_code = 'C1'""") == [
        (False, False, False, "a level below 90% learner coverage and no level high")]


def test_ap4_gives_the_gap_at_both_censuses_and_never_changes_a_tier(store):
    for code, population in [("C1", 900), ("C2", 1800), ("M1", 800), ("M2", 1000)]:
        for age in range(5, 18):
            value = population // 26
            store.sql(f"INSERT INTO {GOLD}.fact_city_school_age_population VALUES "
                      f"('{code}',2020,{age},'male',{value},'matched',TRUE),"
                      f"('{code}',2020,{age},'female',{value},'matched',TRUE)")
    store.sql(f"""UPDATE {GOLD}.fact_city_school_age_population SET is_2020_2024_geography_comparable = FALSE
        WHERE city_mun_psgc_code = 'M2'""")
    run_all(store)
    rows = {(r[0], r[1]): r[2:] for r in store.query(f"""SELECT city_mun_psgc_code, school_year, school_age_population,
        enrollment_all_sectors, population_enrollment_gap, census_context FROM {ANALYTICS}.ap4_enrollment_trend""")}
    # City One: 2020 population 34 x 26 = 884 against SY 2020-21 enrollment 200; 2024: 988 against 280
    assert rows[("C1", "2020-21")] == (884, 200, 684, "available")
    assert rows[("C1", "2024-25")] == (988, 280, 708, "available")
    assert rows[("C1", "2023-24")] == (None, 260, None, "not available: no census in this school year")
    gaps = {r[0]: r[1:] for r in store.query(f"""SELECT city_mun_psgc_code, ap4_gap_2020, ap4_gap_2024, ap4_gap_change,
        ap4_enrollment_trend FROM {ANALYTICS}.lgu_priority_matrix""")}
    assert gaps["C1"] == (684, 708, 24, "increasing")
    assert gaps["M2"][2] is None                      # geography not comparable: no change in gap
    assert matrix(store)["C2"][1] == "Critical"     # AP4 never changes a tier


def test_no_d058_logic_remains():
    sql = "\n".join((ROOT / "etl/06_analytics" / name).read_text(encoding="utf-8")
                    for name in ["01_answer_ap1.sql", "02_answer_ap2.sql", "03_answer_ap3.sql",
                                 "04_answer_ap4.sql", "05_build_priority_matrix.sql"])
    assert "PERCENT_RANK" in sql
    for gone in ["national_same_type_ratio", "relative_pressure", "Priority 1", "Lower Priority", "D-058"]:
        assert gone not in sql


def test_priority_gate_rejects_a_wrong_tier(store):
    run_all(store)
    before = store.query(f"SELECT * FROM {ANALYTICS}.lgu_priority_matrix ORDER BY city_mun_psgc_code")
    store.sql(f"UPDATE {ANALYTICS}.lgu_priority_matrix_candidate SET tier = 'Critical', tier_code = '3'")
    with pytest.raises(Exception, match="Analytics gate failed"):
        run(store, "90_validate_priority_matrix.sql")
    assert store.query(f"SELECT * FROM {ANALYTICS}.lgu_priority_matrix ORDER BY city_mun_psgc_code") == before


def test_ap3_gate_rejects_a_wrong_level_percentile(store):
    run_all(store, STEPS[:2])
    run(store, "03_answer_ap3.sql")
    store.sql(f"UPDATE {ANALYTICS}.ap3_teacher_pressure_candidate SET es_within_type_percentile = 0.5")
    with pytest.raises(Exception, match="Analytics gate failed"):
        run(store, "90_validate_ap3.sql")


def test_gates_record_tier_counts_and_drop_their_summaries(store):
    run_all(store)
    tiers = store.query("""SELECT SUM(CAST(actual AS BIGINT)) FROM edu_access."01-control".data_quality_results
        WHERE source_id = 'lgu_priority_matrix' AND check_name IN
        ('lgus_critical', 'lgus_elevated', 'lgus_targeted', 'lgus_monitor', 'lgus_data_review')""")
    assert tiers == [(4,)]
    leftovers = "SELECT table_name FROM information_schema.tables WHERE table_name LIKE '%gate_summary_r_%'"
    assert store.query(leftovers) == []


def add_public_school(store, school_id, code, learners, rooms, teachers=None):
    store.sql(f"""INSERT INTO {GOLD}.fact_school_enrollment VALUES
        ('{school_id}','2023-24','ES','{code}','Public','matched','Mother School',TRUE,{learners}),
        ('{school_id}','2023-24','JHS','{code}','Public','matched','Mother School',FALSE,0),
        ('{school_id}','2023-24','SHS','{code}','Public','matched','Mother School',FALSE,0)""")
    store.sql(f"INSERT INTO {GOLD}.fact_school_classroom_capacity VALUES ('{school_id}','2023-24',{rooms})")
    if teachers is not None:
        store.sql(f"INSERT INTO {GOLD}.fact_school_teacher_capacity VALUES ('{school_id}','2023-24','ES',{teachers})")


def test_an_outlier_school_is_counted_but_never_changes_a_result(store):
    # Town Two gains five ordinary schools and Town One one extreme school (60 learners in 1 room) above the fence
    for n in range(5):
        add_public_school(store, f"T{n}", "M2", 210, 9, 9)
    add_public_school(store, "X1", "M1", 60, 1, 1)
    run_all(store, STEPS[:2])
    assert store.query(f"""SELECT outlier_school_count, outlier_flag, is_assessed, within_type_percentile, is_high
        FROM {ANALYTICS}.ap2_classroom_pressure WHERE city_mun_psgc_code = 'M1'""") == [(1, True, True, 1.0, True)]


def test_critical_within_type_but_not_nationally_is_not_stable(store):
    # Town Two's rooms drop to 5 (42 learners per room): it now leads AP2 nationally, above City Two's 33
    store.sql(f"UPDATE {GOLD}.fact_school_classroom_capacity SET instructional_classrooms_total = 5 WHERE school_id = 'S5'")
    run_all(store)
    c2 = matrix(store)["C2"]
    assert c2[1:5] == ("Critical", "3", "Elevated", False)


def test_a_measure_is_high_at_exactly_the_90th_percentile(store):
    # eleven municipalities: nine new ones at 10 to 18 learners per room, then Town Two (23.3) and Town One (25)
    for n in range(9):
        code = f"N{n}"
        store.sql(f"""INSERT INTO {GOLD}.dim_city_municipality VALUES
            ('{code}','Town {code}','Municipality','P','Province','R','Region','regular')""")
        add_public_school(store, f"Q{n}", code, 100 + 10 * n, 10)
    run_all(store, STEPS[1:2])
    rows = {r[0]: r[1:] for r in store.query(f"""SELECT city_mun_psgc_code, within_type_percentile, is_high
        FROM {ANALYTICS}.ap2_classroom_pressure WHERE lgu_type = 'Municipality'""")}
    assert rows["M2"] == (0.9, True)          # rank 10 of 11: (10 - 1) / (11 - 1)
    assert rows["N8"] == (pytest.approx(0.8), False)
    assert rows["M1"] == (1.0, True)


def test_ap3_gate_rejects_a_wrong_national_assessment(store):
    run_all(store, STEPS[:2])
    run(store, "03_answer_ap3.sql")
    store.sql(f"""UPDATE {ANALYTICS}.ap3_teacher_pressure_candidate SET is_assessed_nationally = FALSE
        WHERE city_mun_psgc_code = 'C2'""")
    with pytest.raises(Exception, match="Analytics gate failed"):
        run(store, "90_validate_ap3.sql")


def test_ap3_keeps_a_school_whose_offered_counts_are_all_blank(store):
    # review on #210: S7 offers JHS in City One with a blank count. It is not active, but the JHS level must stay
    # offered and incomplete, so AP3 is not assessed and City One is Data review, never Monitor.
    store.sql(f"""INSERT INTO {GOLD}.fact_school_enrollment VALUES
        ('S7','2023-24','ES','C1','Public','matched','Mother School',FALSE,0),
        ('S7','2023-24','JHS','C1','Public','matched','Mother School',TRUE,NULL),
        ('S7','2023-24','SHS','C1','Public','matched','Mother School',FALSE,0)""")
    store.sql(f"INSERT INTO {GOLD}.fact_school_teacher_capacity VALUES ('S7','2023-24','JHS',3)")
    run_all(store)
    assert store.query(f"""SELECT jhs_offered_school_count, jhs_incomplete_school_count, jhs_passes_gate,
        offered_level_count, passing_level_count, is_assessed FROM {ANALYTICS}.ap3_teacher_pressure
        WHERE city_mun_psgc_code = 'C1'""") == [(1, 1, False, 2, 1, False)]
    assert matrix(store)["C1"][1:3] == ("Data review", "data_review")


def test_ap2_publishes_no_45_to_1_line(store):
    # review on #210: RA 7880's 45:1 does not apply to the NSBI room count (D-045), so no column may invite a target line
    run_all(store, STEPS[1:2])
    columns = [c[0] for c in store.query(f"""SELECT column_name FROM information_schema.columns
        WHERE table_name = 'ap2_classroom_pressure'""")]
    assert "learners_per_classroom" in columns
    assert not [c for c in columns if "45" in c]
