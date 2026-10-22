"""Suspected extreme school ratios and the outlier sensitivity of the planning priority (D-065)."""

import statistics

import pytest

from test_analytics_priority import ANALYTICS, STEPS, add_public_school, run_all, store  # noqa: F401  (store is that file's made-up Gold fixture)

OUTLIER_STEPS = STEPS + [
    ("06_flag_school_outliers.sql", "90_validate_school_outlier_flags.sql"),
    ("07_build_priority_sensitivity.sql", "90_validate_priority_sensitivity.sql"),
    ("08_build_priority_scenarios.sql", "90_validate_priority_scenarios.sql"),
]


def add_ordinary_schools(store, step=8, codes=("M1", "M2"), count=12):
    """Twelve municipal schools, each with 4 rooms and 4 teachers, from 25 learners per room upward in steps of step/4,
    so the municipal groups reach the 10 schools a fence needs. The fixture's two cities stay below it, with no fence."""
    for i in range(count):
        add_public_school(store, f"N{i}", codes[i % len(codes)], 100 + i * step, 4, 4)


def flags(store, measure="classroom"):
    return {r[0]: r[1:] for r in store.query(f"""
        SELECT school_id, is_suspected_outlier, is_above_upper_fence, is_below_lower_fence, lgu_type,
               fence_group_size, q1, q3, lower_outer_fence, upper_outer_fence
        FROM {ANALYTICS}.school_outlier_flags WHERE measure = '{measure}'""")}


def sensitivity(store, code):
    columns = ["priority_category", "priority_category_without_suspected_outliers", "classroom_pressure_flag",
               "classroom_pressure_flag_without_suspected_outliers", "priority_affected_learners",
               "priority_affected_learners_without_suspected_outliers", "ap2_learner_coverage_pct_without_suspected_outliers",
               "outlier_school_count", "outlier_sensitivity_status"]
    row = store.query(f"SELECT {', '.join(columns)} FROM {ANALYTICS}.lgu_priority_sensitivity "
                      f"WHERE city_mun_psgc_code = '{code}'")[0]
    return dict(zip(columns, row))


def test_the_fence_is_tukeys_outer_fence_within_lgu_type(store):
    add_ordinary_schools(store)
    add_public_school(store, "X", "M2", 400, 1, 4)  # 400 learners in one room
    run_all(store, OUTLIER_STEPS)
    rooms = flags(store)
    municipal = sorted(r for r in [120 / 6, 180 / 9] + [(100 + i * 8) / 4 for i in range(12)] + [400.0])
    q1, _, q3 = statistics.quantiles(municipal, n=4, method="inclusive")  # linear interpolation, as percentile_cont
    assert rooms["X"][5:7] == (pytest.approx(q1), pytest.approx(q3))
    assert rooms["X"][8] == pytest.approx(q3 + 3 * (q3 - q1))
    assert [school for school, row in rooms.items() if row[0]] == ["X"]
    # the city group has three schools, short of the ten a fence needs: no fence and no flag
    assert rooms["S3"][3:5] == ("City", 3) and rooms["S3"][7:9] == (None, None) and not rooms["S3"][0]


def test_a_classroom_ratio_is_suspected_only_when_high_and_a_teacher_ratio_either_way(store):
    # with ordinary schools close together, L (4 learners, 4 rooms, 4 teachers: 1 per room and per teacher) is below
    # both lower fences. Only the teacher ratio is suspected, because AP3 pools every school in the LGU and a low one
    # moves the LGU ratio as much as a high one
    add_ordinary_schools(store, step=1)
    add_public_school(store, "L", "M1", 4, 4, 4)
    run_all(store, OUTLIER_STEPS)
    assert flags(store)["L"][:3] == (False, False, True)
    assert flags(store, "teacher")["L"][:3] == (True, False, True)


def test_scenario_b_drops_the_whole_school_and_flags_a_category_that_rests_on_it(store):
    # X makes Town Two's only congested school. Without it the classroom flag goes, and so many learners leave the
    # ratio that classroom coverage falls below 90%: the category moves, so the LGU is priority-sensitive
    add_ordinary_schools(store)
    add_public_school(store, "X", "M2", 400, 1, 4)
    run_all(store, OUTLIER_STEPS)
    town_two = sensitivity(store, "M2")
    assert (town_two["classroom_pressure_flag"], town_two["classroom_pressure_flag_without_suspected_outliers"]) == (1, 0)
    assert town_two["ap2_learner_coverage_pct_without_suspected_outliers"] < 90
    assert town_two["priority_category"] != town_two["priority_category_without_suspected_outliers"] == "Data review"
    assert (town_two["outlier_school_count"], town_two["outlier_sensitivity_status"]) == (1, "Priority-sensitive")


def test_a_result_that_holds_without_the_outlier_is_only_magnitude_sensitive(store):
    # Town One has a congested school within the fence (C: 200 learners, 4 rooms, 50 per room) and an extreme one
    # (X: 120 learners in one room). Without X the classroom flag and the category stay, coverage stays above 90%, and
    # only the affected learners fall, by more than 10%
    add_ordinary_schools(store)
    add_public_school(store, "C", "M1", 200, 4, 8)
    add_public_school(store, "X", "M1", 120, 1, 4)
    run_all(store, OUTLIER_STEPS)
    assert flags(store)["X"][0] and not flags(store)["C"][0]
    town_one = sensitivity(store, "M1")
    assert town_one["priority_category"] == town_one["priority_category_without_suspected_outliers"]
    assert town_one["classroom_pressure_flag"] == town_one["classroom_pressure_flag_without_suspected_outliers"] == 1
    assert (town_one["priority_affected_learners"], town_one["priority_affected_learners_without_suspected_outliers"]) == (320, 200)
    assert town_one["outlier_sensitivity_status"] == "Magnitude-sensitive"


def test_an_lgu_with_nothing_to_exclude_is_the_published_result(store):
    add_ordinary_schools(store)
    add_public_school(store, "X", "M2", 400, 1, 4)
    run_all(store, OUTLIER_STEPS)
    rows = store.query(f"""SELECT city_mun_psgc_code, outlier_sensitivity_status,
        priority_category = priority_category_without_suspected_outliers,
        priority_affected_learners = priority_affected_learners_without_suspected_outliers
        FROM {ANALYTICS}.lgu_priority_sensitivity WHERE city_mun_psgc_code <> 'M2' ORDER BY 1""")
    assert rows == [(code, "No suspected outliers", True, True) for code in ("C1", "C2", "M1")]


def test_the_published_matrix_is_never_changed(store):
    # the same Gold, with and without the two outlier steps, publishes the same matrix
    add_ordinary_schools(store)
    add_public_school(store, "X", "M2", 400, 1, 4)
    run_all(store)
    before = store.query(f"SELECT * FROM {ANALYTICS}.lgu_priority_matrix ORDER BY city_mun_psgc_code")
    run_all(store, OUTLIER_STEPS[-3:])
    assert store.query(f"SELECT * FROM {ANALYTICS}.lgu_priority_matrix ORDER BY city_mun_psgc_code") == before
    assert store.query(f"""SELECT COUNT(*) FROM {ANALYTICS}.lgu_priority_sensitivity AS s
        JOIN {ANALYTICS}.lgu_priority_matrix AS m USING (city_mun_psgc_code)
        WHERE s.priority_category <> m.priority_category OR s.priority_order <> m.priority_order""") == [(0,)]


@pytest.mark.parametrize("table", ["school_outlier_flags", "lgu_priority_sensitivity", "lgu_priority_scenarios"])
def test_the_analytics_dictionary_lists_every_column(store, table):
    from test_analytics_priority import documented_columns
    add_ordinary_schools(store)
    run_all(store, OUTLIER_STEPS)
    columns = {c[0] for c in store.query(
        f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table}'")}
    documented = documented_columns(table)
    assert len(documented) == len(set(documented)), f"a column of {table} is listed twice"
    assert set(documented) == columns, f"update docs/data/analytics-outputs.md for {table}"
