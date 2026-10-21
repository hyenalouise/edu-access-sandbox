"""AP1 to AP4 evidence and the separate classroom-screening queue under D-060."""

import re
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


def add_public_school(store, school_id, code, learners, rooms, teachers=None):
    store.sql(f"""INSERT INTO {GOLD}.fact_school_enrollment VALUES
        ('{school_id}','2023-24','ES','{code}','Public','matched','Mother School',TRUE,{learners}),
        ('{school_id}','2023-24','JHS','{code}','Public','matched','Mother School',FALSE,0),
        ('{school_id}','2023-24','SHS','{code}','Public','matched','Mother School',FALSE,0)""")
    store.sql(f"INSERT INTO {GOLD}.fact_school_classroom_capacity VALUES ('{school_id}','2023-24',{rooms})")
    if teachers is not None:
        store.sql(f"INSERT INTO {GOLD}.fact_school_teacher_capacity VALUES ('{school_id}','2023-24','ES',{teachers})")


def test_no_percentile_or_composite_tier_is_published(store):
    run_all(store)
    for table in ["ap1_school_provision", "ap2_classroom_pressure", "ap3_teacher_pressure", "lgu_priority_matrix"]:
        columns = {c[0] for c in store.query(
            f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table}'")}
        assert not {c for c in columns if "percentile" in c or c in {"is_high", "tier", "national_tier"}}


def test_ap1_is_descriptive_only(store):
    run_all(store, STEPS[:1])
    assert store.query(f"""SELECT learners_per_public_school, school_age_population_per_public_school, is_assessed
        FROM {ANALYTICS}.ap1_school_provision WHERE city_mun_psgc_code = 'C2'""") == [
        (330.0, pytest.approx(1976.0), True)]


def test_ap2_flags_schools_then_aggregates_affected_learners(store):
    add_public_school(store, "X1", "M1", 60, 1)
    run_all(store, STEPS[:2])
    assert store.query(f"""SELECT congested_school_count, learners_in_congested_schools,
        congested_learner_share_pct, benchmark_status FROM {ANALYTICS}.ap2_classroom_pressure
        WHERE city_mun_psgc_code = 'M1'""") == [
        (1, 60, pytest.approx(60 / 210 * 100), "reported congestion identified")]


def test_ap2_threshold_is_inclusive_at_50(store):
    store.sql(f"""UPDATE {GOLD}.fact_school_enrollment SET learner_count = 100
        WHERE school_id = 'S1' AND school_year = '2023-24' AND education_level_code = 'ES'""")
    store.sql(f"UPDATE {GOLD}.fact_school_classroom_capacity SET instructional_classrooms_total = 2 WHERE school_id = 'S1'")
    run_all(store, STEPS[1:2])
    assert store.query(f"""SELECT congested_school_count, learners_in_congested_schools
        FROM {ANALYTICS}.ap2_classroom_pressure WHERE city_mun_psgc_code = 'C1'""") == [(1, 100)]


def test_ap2_coverage_failure_goes_to_classroom_data_review(store):
    # S1 loses its room count: City One keeps half its learners in the ratio, below the 90% gate
    store.sql(f"DELETE FROM {GOLD}.fact_school_classroom_capacity WHERE school_id = 'S1'")
    run_all(store)
    assert store.query(f"""SELECT learner_coverage_pct, is_assessed, not_assessed_reason
        FROM {ANALYTICS}.ap2_classroom_pressure WHERE city_mun_psgc_code = 'C1'""") == [
        (50.0, False, "learner coverage below 90%")]
    assert store.query(f"""SELECT ap2_assessed, classroom_priority_group, classroom_priority_rank
        FROM {ANALYTICS}.lgu_priority_matrix WHERE city_mun_psgc_code = 'C1'""") == [
        (False, "data_review", None)]


def test_classroom_queue_orders_by_affected_learners_and_preserves_ties(store):
    add_public_school(store, "X1", "M1", 60, 1)
    add_public_school(store, "X2", "M2", 60, 1)
    store.sql(f"""UPDATE {GOLD}.fact_school_classroom_capacity SET instructional_classrooms_total = 8
        WHERE school_id = 'S5'""")
    run_all(store)
    rows = {r[0]: r[1:] for r in store.query(f"""SELECT city_mun_psgc_code, ap2_affected_learners,
        ap2_screened_congested_school_count, classroom_priority_rank FROM {ANALYTICS}.lgu_priority_matrix
        WHERE classroom_priority_group = 'reported_congestion_screen'""")}
    assert rows["M1"] == (60, 1, 1)
    assert rows["M2"] == (60, 1, 1)


def test_ap3_pressure_signal_precedes_incomplete_level(store):
    store.sql(f"""UPDATE {GOLD}.fact_school_enrollment SET is_offered = TRUE, learner_count = 200
        WHERE school_id = 'S1' AND school_year = '2023-24' AND education_level_code = 'JHS'""")
    store.sql(f"INSERT INTO {GOLD}.fact_school_teacher_capacity VALUES ('S1','2023-24','JHS',4)")
    store.sql(f"""UPDATE {GOLD}.fact_school_enrollment SET is_offered = TRUE, learner_count = 50
        WHERE school_id = 'S2' AND school_year = '2023-24' AND education_level_code = 'SHS'""")
    run_all(store, STEPS[:3])
    assert store.query(f"""SELECT is_assessed, jhs_benchmark_status, shs_benchmark_status, benchmark_status
        FROM {ANALYTICS}.ap3_teacher_pressure WHERE city_mun_psgc_code = 'C1'""") == [
        (False, "above derived deployment comparison", "not assessed", "pressure signal identified")]


def test_teacher_context_never_assigns_a_teacher_priority_rank(store):
    run_all(store)
    columns = {c[0] for c in store.query(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'lgu_priority_matrix'")}
    assert "ap3_review_status" in columns
    assert not {c for c in columns if "teacher_priority" in c}


def test_ap4_gives_the_gap_at_both_censuses_and_never_enters_the_classroom_queue(store):
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
        ap4_enrollment_trend, classroom_priority_group, classroom_priority_rank FROM {ANALYTICS}.lgu_priority_matrix""")}
    assert gaps["C1"][:4] == (684, 708, 24, "increasing")
    assert gaps["M2"][2] is None                      # geography not comparable: no change in gap
    # AP4 is context: a large gap never puts an LGU in the classroom queue (no school here reaches 50 per room)
    assert {g[4:] for g in gaps.values()} == {("no_reported_congestion_screen", None)}


def test_ap3_keeps_a_school_whose_offered_counts_are_all_blank(store):
    # review on #210: S7 offers JHS in City One with a blank count. It is not active, but the JHS level must stay
    # offered and incomplete, so AP3 is not fully assessed instead of reading as no pressure.
    store.sql(f"""INSERT INTO {GOLD}.fact_school_enrollment VALUES
        ('S7','2023-24','ES','C1','Public','matched','Mother School',FALSE,0),
        ('S7','2023-24','JHS','C1','Public','matched','Mother School',TRUE,NULL),
        ('S7','2023-24','SHS','C1','Public','matched','Mother School',FALSE,0)""")
    store.sql(f"INSERT INTO {GOLD}.fact_school_teacher_capacity VALUES ('S7','2023-24','JHS',3)")
    run_all(store)
    assert store.query(f"""SELECT jhs_offered_school_count, jhs_incomplete_school_count, jhs_passes_gate,
        offered_level_count, passing_level_count, is_assessed, benchmark_status FROM {ANALYTICS}.ap3_teacher_pressure
        WHERE city_mun_psgc_code = 'C1'""") == [(1, 1, False, 2, 1, False, "not fully assessed")]
    assert store.query(f"""SELECT ap3_fully_assessed, ap3_review_status FROM {ANALYTICS}.lgu_priority_matrix
        WHERE city_mun_psgc_code = 'C1'""") == [(False, "not fully assessed")]


def test_ap2_publishes_no_45_to_1_line(store):
    # review on #210: RA 7880's 45:1 does not apply to the NSBI room count (D-045), so no column may invite a target line
    run_all(store, STEPS[1:2])
    columns = [c[0] for c in store.query(f"""SELECT column_name FROM information_schema.columns
        WHERE table_name = 'ap2_classroom_pressure'""")]
    assert "learners_per_classroom" in columns
    assert not [c for c in columns if "45" in c]


def test_no_d057_or_d058_logic_remains():
    sql = "\n".join((ROOT / "etl/06_analytics" / name).read_text(encoding="utf-8")
                    for name in ["01_answer_ap1.sql", "02_answer_ap2.sql", "03_answer_ap3.sql",
                                 "04_answer_ap4.sql", "05_build_priority_matrix.sql"])
    for gone in ["PERCENT_RANK", "national_same_type_ratio", "relative_pressure", "Priority 1", "Lower Priority",
                 "Critical", "D-057", "D-058"]:
        assert gone not in sql


def test_priority_gate_rejects_a_wrong_classroom_rank(store):
    add_public_school(store, "X1", "M1", 60, 1)
    run_all(store)
    before = store.query(f"SELECT * FROM {ANALYTICS}.lgu_priority_matrix ORDER BY city_mun_psgc_code")
    store.sql(f"""UPDATE {ANALYTICS}.lgu_priority_matrix_candidate SET classroom_priority_rank = 99
        WHERE city_mun_psgc_code = 'M1'""")
    with pytest.raises(Exception, match="Analytics gate failed"):
        run(store, "90_validate_priority_matrix.sql")
    assert store.query(f"SELECT * FROM {ANALYTICS}.lgu_priority_matrix ORDER BY city_mun_psgc_code") == before


def test_ap3_gate_rejects_a_wrong_reference_status(store):
    run_all(store, STEPS[:2])
    run(store, "03_answer_ap3.sql")
    store.sql(f"""UPDATE {ANALYTICS}.ap3_teacher_pressure_candidate
        SET es_benchmark_status = 'official shortage' WHERE city_mun_psgc_code = 'C2'""")
    with pytest.raises(Exception, match="Analytics gate failed"):
        run(store, "90_validate_ap3.sql")


def test_gate_summaries_are_dropped(store):
    run_all(store)
    leftovers = "SELECT table_name FROM information_schema.tables WHERE table_name LIKE '%gate_summary_r_%'"
    assert store.query(leftovers) == []


def test_benchmark_registry_matches_published_values(store):
    import json

    registry = json.loads((ROOT / "config/analytics_benchmarks.json").read_text(encoding="utf-8"))
    run_all(store, STEPS[:3])
    assert store.query(f"SELECT DISTINCT congestion_benchmark FROM {ANALYTICS}.ap2_classroom_pressure") == [
        (registry["ap2"]["threshold"],)]
    assert store.query(f"""SELECT DISTINCT es_benchmark_max_learners_per_teacher,
        jhs_benchmark_max_learners_per_teacher, shs_benchmark_max_learners_per_teacher
        FROM {ANALYTICS}.ap3_teacher_pressure""") == [
        (registry["ap3"]["es_max_learners_per_teacher"], registry["ap3"]["jhs_max_learners_per_teacher"],
         pytest.approx(registry["ap3"]["shs_max_learners_per_teacher"]))]


def documented_columns(table):
    """Columns listed for a table in docs/data/analytics-outputs.md, <level>_ expanded to es_, jhs_ and shs_."""
    text = (ROOT / "docs/data/analytics-outputs.md").read_text(encoding="utf-8")
    sections = dict(re.findall(r"^## `?([a-z_0-9]+|LGU columns)`?\n(.*?)(?=^## |\Z)", text, flags=re.M | re.S))
    def listed(section):
        names = []
        for name in re.findall(r"^\| `([a-z_0-9<>]+)` \|", section, flags=re.M):
            names += [name.replace("<level>", level) for level in ("es", "jhs", "shs")] if "<level>" in name else [name]
        return names
    body = sections[table]
    return (listed(sections["LGU columns"]) if "[LGU columns]" in body else []) + listed(body)


@pytest.mark.parametrize("table", ["ap1_school_provision", "ap2_classroom_pressure", "ap3_teacher_pressure",
                                   "ap4_enrollment_trend", "lgu_priority_matrix"])
def test_the_analytics_dictionary_lists_every_column(store, table):
    run_all(store)
    columns = {c[0] for c in store.query(
        f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table}'")}
    documented = documented_columns(table)
    assert len(documented) == len(set(documented)), f"a column of {table} is listed twice"
    assert set(documented) == columns, f"update docs/data/analytics-outputs.md for {table}"
