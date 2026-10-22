"""The Education Access Review Dashboard: its JSON matches the generator, its pages, filters and layout follow the plan,
its wording stays in plain language, and it shows the planning priorities as the Analytics tables publish them."""

import json
import re
from pathlib import Path

import yaml

from src.dashboard import planner
from test_analytics_priority import GOLD, add_public_school, run_all, store  # noqa: F401  (store is that file's made-up Gold fixture)

ROOT = Path(__file__).parents[1]
DASHBOARD = ROOT / "dashboards" / "reached_planner.lvdash.json"
PAGES = ["overview", "lgu_profile", "school_action", "data_and_method"]
INTERNAL_CODE = re.compile(r"\bD-0\d\d\b|\bAP ?[1-4]\b")


def load():
    return json.loads(DASHBOARD.read_text(encoding="utf-8"))


def widgets(page):
    return [item["widget"] for item in page["layout"]]


def test_the_committed_json_is_what_the_generator_writes():
    assert DASHBOARD.read_text(encoding="utf-8") == planner.render(), \
        "Run `python -m src.dashboard.planner` and commit the result"


def test_four_views_in_order_then_the_global_filters():
    pages = load()["pages"]
    assert [p["name"] for p in pages] == PAGES + ["global_filters"]
    assert [p["pageType"] for p in pages] == ["PAGE_TYPE_CANVAS"] * 4 + ["PAGE_TYPE_GLOBAL_FILTERS"]


def kpis(page):
    """Counters that show their title: headings (the selected place or school) and notes (scope, facts) hide it."""
    return [w for w in widgets(page) if w.get("spec", {}).get("widgetType") == "counter"
            and w["name"].startswith("kpi_") and w["spec"]["frame"]["showTitle"]]


def test_every_page_has_exactly_four_kpis():
    for page in load()["pages"][:4]:
        counters = kpis(page)
        assert len(counters) == 4, page["name"]
        for counter in counters:  # a counter shows its value large: no sentences in the template
            template = counter["spec"]["encodings"]["value"].get("formatTemplate", "")
            assert len(re.sub(r"{{[^}]*}}", "", template)) <= 12, (page["name"], template)


def test_layout_stays_on_the_grid_without_overlaps():
    for page in load()["pages"]:
        cells = set()
        for item in page["layout"]:
            pos = item["position"]
            assert pos["x"] >= 0 and pos["x"] + pos["width"] <= 12, (page["name"], item["widget"]["name"])
            for x in range(pos["x"], pos["x"] + pos["width"]):
                for y in range(pos["y"], pos["y"] + pos["height"]):
                    assert (x, y) not in cells, (page["name"], item["widget"]["name"])
                    cells.add((x, y))


def test_every_query_reads_a_dataset_and_every_filter_targets_a_real_parameter():
    dashboard = load()
    params = {d["name"]: {p["keyword"] for p in d["parameters"]} for d in dashboard["datasets"]}
    names = [w["name"] for p in dashboard["pages"] for w in widgets(p)]
    assert len(names) == len(set(names))
    for page in dashboard["pages"]:
        for widget in widgets(page):
            for q in widget.get("queries", []):
                dataset = q["query"]["datasetName"]
                assert dataset in params, (widget["name"], dataset)
                for parameter in q["query"].get("parameters", []):
                    assert parameter["keyword"] in params[dataset], (widget["name"], dataset, parameter)


def test_every_dataset_parameter_is_used_and_set_by_a_filter():
    dashboard = load()
    bound = {(q["query"]["datasetName"], p["keyword"]) for page in dashboard["pages"] for w in widgets(page)
             for q in w.get("queries", []) for p in q["query"].get("parameters", [])}
    for dataset in dashboard["datasets"]:
        sql = "".join(dataset["queryLines"])
        for parameter in dataset["parameters"]:
            assert re.search(rf":{parameter['keyword']}\b", sql), (dataset["name"], parameter["keyword"])
            assert (dataset["name"], parameter["keyword"]) in bound, (dataset["name"], parameter["keyword"])


def test_every_dataset_is_drawn_or_feeds_a_filter():
    dashboard = load()
    used = {q["query"]["datasetName"] for page in dashboard["pages"] for w in widgets(page)
            for q in w.get("queries", []) if "fields" in q["query"]}
    assert {d["name"] for d in dashboard["datasets"]} == used


def test_tables_are_fully_qualified_and_read_only_gold_analytics_and_control():
    for dataset in load()["datasets"]:
        sql = "".join(dataset["queryLines"])
        for schema in re.findall(r"edu_access\.`([^`]+)`", sql):
            assert schema in {"01-control", "03-silver", "04-integration", "05-gold", "06-analytics"}, (dataset["name"], schema)
        assert not re.search(r"\bai_query\b", sql), dataset["name"]


def test_wording_never_states_a_need_or_shortage_as_a_finding():
    text = DASHBOARD.read_text(encoding="utf-8").lower()
    for phrase in ("deficit", "under-capacity", "shortfall", "classroom shortage of", "need to build"):
        assert phrase not in text
    assert "out-of-school count" not in text


def test_kpis_show_a_short_value_never_an_abbreviated_count():
    # review of the 2026-10-21 deploy: KPI values were cut off, and 1,380 showed as 1.38K
    for page in load()["pages"][:4]:
        for counter in kpis(page):
            value = counter["spec"]["encodings"]["value"]
            assert "format" not in value and "formatTemplate" not in value, (page["name"], value["displayName"])


def test_legends_axes_and_filters_use_the_review_status():
    dashboard = load()
    orders = re.findall(r'"orderedValues": (\[[^\]]*\])', json.dumps([w for p in dashboard["pages"] for w in widgets(p)]))
    orders = [json.loads(o) for o in orders]
    assert planner.QUEUE in orders and not any(set(o) & set(planner.STATUS_LABELS[:4]) for o in orders)
    options = "".join(next(d for d in dashboard["datasets"] if d["name"] == "opt_queue")["queryLines"])
    assert all(f"('{q}')" in options for q in planner.QUEUE)


def test_kpis_use_the_production_language():
    titles = {w["spec"]["frame"]["title"] for p in load()["pages"][:4] for w in kpis(p)}
    assert {"LGUs requiring immediate joint review", "LGUs with a current pressure signal", "LGUs requiring data review",
            "Verification items"} <= titles
    assert not titles & {"Priority 1 LGUs", "LGUs with any pressure", "Data review LGUs", "Figures to verify"}


def test_no_table_cell_is_coloured():
    # badges were tried on 2026-10-22 and were unreadable: tables stay plain
    for page in load()["pages"]:
        for widget in widgets(page):
            if widget.get("spec", {}).get("widgetType") == "table":
                assert not any("style" in c for c in widget["spec"]["encodings"]["columns"]), widget["name"]


def test_population_charts_are_bars_in_the_order_the_sql_gives():
    # bubbles were tried on 2026-10-22 and were hard to read; both population charts are bars, largest first
    dashboard = load()
    datasets = {d["name"]: "".join(d["queryLines"]) for d in dashboard["datasets"]}
    for name in ("ov_region_pairs", "pr_peers"):
        chart = next(w for p in dashboard["pages"] for w in widgets(p) if w.get("queries")
                     and w["queries"][0]["query"]["datasetName"] == name)
        assert chart["spec"]["widgetType"] == "bar" and chart["queries"][0]["query"]["disaggregated"]
        assert chart["spec"]["encodings"]["y"]["scale"]["sort"] == {"by": "natural-order"}
    assert "ORDER BY size_order DESC" in datasets["ov_region_pairs"]
    assert "ORDER BY children_per_school DESC" in datasets["pr_peers"] and ":barangay" not in datasets["pr_peers"]
    assert not any(w.get("spec", {}).get("widgetType") == "scatter" for p in dashboard["pages"][:2] for w in widgets(p))


def test_the_selected_lgu_is_ranked_among_its_comparison_area(store):
    add_public_school(store, "X1", "M1", 300, 4, 10)
    run_all(store)
    rows = _rows(store, "pr_peers", lgu="Town One, Province")
    assert [r["series"] for r in rows].count(planner.PEER_SERIES[0]) == 1
    assert [r["children_per_school"] for r in rows] == sorted((r["children_per_school"] for r in rows), reverse=True)
    note = _rows(store, "pr_peer_note", lgu="Town One, Province")[0]["peer_line"]
    assert note.startswith("Town One: ") and "school-age children per public school" in note
    pairs = _rows(store, "ov_region_pairs")
    assert [r["series"] for r in pairs] == planner.REGION_SERIES


def test_no_chart_legend_says_verification_needed():
    # the review on 2026-10-22: schools are coloured by levels offered or school status, never by a data-check flag
    for page in load()["pages"]:
        for widget in widgets(page):
            color = widget.get("spec", {}).get("encodings", {}).get("color", {})
            values = [m["value"] for m in color.get("scale", {}).get("mappings", [])]
            assert planner.VERIFY[0] not in values, widget["name"]


def test_no_title_renders_markdown():
    # review of the 2026-10-21 export: asterisks in chart titles rendered literally
    for page in load()["pages"]:
        for widget in widgets(page):
            title = widget.get("spec", {}).get("frame", {}).get("title", "")
            assert not re.search(r"[*#_`]", title), (page["name"], title)


def test_no_internal_rule_or_measure_code_outside_the_technical_metadata():
    dashboard = load()
    for page in dashboard["pages"]:
        for widget in widgets(page):
            shown = json.dumps({k: v for k, v in widget.items() if k != "queries"})
            if page["name"] == "data_and_method" and "Technical metadata" in shown:
                continue
            assert not INTERNAL_CODE.search(shown), (page["name"], widget["name"], INTERNAL_CODE.search(shown).group())
    for dataset in dashboard["datasets"]:  # text the SQL writes into a cell: its string literals, comments aside,
        sql = re.sub(r"--[^\n]*", "", "".join(dataset["queryLines"]))  # and a published value it maps to plain words
        sql = re.sub(r"WHEN\s+'(?:''|[^'])*'\s+THEN", "WHEN THEN", sql)
        for literal in re.findall(r"'((?:''|[^'])*)'", sql):
            assert not INTERNAL_CODE.search(literal), (dataset["name"], literal)


def test_missing_values_are_never_written_as_null_or_na():
    for dataset in load()["datasets"]:
        sql = "".join(dataset["queryLines"])
        assert "'n/a'" not in sql and "'null'" not in sql.lower(), dataset["name"]


def test_every_planning_status_has_a_plain_label_and_basis():
    # review status (Priority 1 to 3, ...) names every legend, axis and filter; the planning status reads beside it
    assert len(planner.QUEUE) == len(planner.STATUS_LABELS) == len(planner.STATUS_BASIS)
    text = DASHBOARD.read_text(encoding="utf-8")
    for label, basis in zip(planner.STATUS_LABELS, planner.STATUS_BASIS):
        assert label in text and basis in text


def test_the_map_colours_each_lgu_by_its_priority_category():
    # the reference map: one boundary per LGU from geo_first(boundary), a Review status legend in the published
    # order, and City or municipality, Review status and Learners in screened schools in the tooltip
    maps = [w for p in load()["pages"] for w in widgets(p) if w.get("spec", {}).get("widgetType") == "choropleth-map"]
    assert len(maps) == 1
    encodings, query = maps[0]["spec"]["encodings"], maps[0]["queries"][0]["query"]
    assert encodings["region"] == {"regionType": "custom", "fieldName": "geo_first(boundary)"}
    assert {f["name"]: f["expression"] for f in query["fields"]}["geo_first(boundary)"] == "ST_ASGEOJSON(FIRST(`boundary`))"
    assert not query["disaggregated"]
    color = encodings["color"]
    assert (color["fieldName"], color["displayName"]) == ("queue_status", "Review status")
    assert color["scale"]["sort"]["orderedValues"] == planner.QUEUE
    assert [m["value"] for m in color["scale"]["mappings"]] == planner.QUEUE
    assert [e["displayName"] for e in encodings["extra"]] == [
        "City or municipality", "Review status", "Learners in screened schools"]


def test_tables_show_counts_written_with_separators():
    # review of the 2026-10-22 export: table counts showed as 171855; every table cell is text from the SQL instead
    for page in load()["pages"]:
        for widget in widgets(page):
            if widget.get("spec", {}).get("widgetType") == "table":
                for column in widget["spec"]["encodings"]["columns"]:
                    assert "format" not in column, (page["name"], column["displayName"])


def test_reasons_are_complete_capitalised_labels():
    assert all(label[0].isupper() for label in planner.REASONS.values())
    assert planner.REASONS["boundary changed 2020-2024"] == "Geographic boundaries changed"


def test_region_rows_keep_the_order_the_sql_gives_them():
    # sorted by the share of Priority 1 and 2 LGUs: the chart draws the rows unaggregated, in natural order
    chart = next(w for p in load()["pages"] for w in widgets(p) if w.get("queries")
                 and w["queries"][0]["query"]["datasetName"] == "ov_region")
    assert chart["queries"][0]["query"]["disaggregated"]
    assert chart["spec"]["encodings"]["y"]["scale"]["sort"] == {"by": "natural-order"}
    sql = "".join(next(d for d in load()["datasets"] if d["name"] == "ov_region")["queryLines"])
    assert "ORDER BY high_share DESC" in sql


def test_barangay_and_measure_filters_sit_with_what_they_change():
    pages = {p["name"]: p for p in load()["pages"]}

    def targets(page, title):
        widget = next(w for w in widgets(pages[page]) if w.get("spec", {}).get("widgetType") == "filter-single-select"
                      and w["spec"]["frame"]["title"] == title)
        return {q["query"]["datasetName"] for q in widget["queries"] if "parameters" in q["query"]}

    assert targets("lgu_profile", "Barangay") == {"pr_barangays", "pr_map", "pr_map_note"}
    assert targets("school_action", "Barangay") == {"sa_list"}
    assert targets("school_action", "School status") == {"sa_list"}
    assert targets("data_and_method", "Measure") == {"dm_coverage", "dm_reasons"}


def test_the_school_map_plots_only_locations_inside_the_lgu_boundary():
    sql = "".join(next(d for d in load()["datasets"] if d["name"] == "pr_map")["queryLines"])
    assert "boundary_status = 'inside'" in sql


def test_the_bundle_deploys_this_dashboard():
    bundle = yaml.safe_load((ROOT / "databricks.yml").read_text(encoding="utf-8"))
    dashboard = bundle["resources"]["dashboards"]["reached_planner"]
    assert dashboard["file_path"] == "dashboards/reached_planner.lvdash.json"
    assert dashboard["warehouse_id"] == "${var.warehouse_id}"


def add_school_detail(store, barangays):
    """The school-level columns School Action and the barangay list read, which the AP fixture leaves out.

    barangays maps a barangay PSGC code to (name, its city or municipality, the school IDs in it)."""
    store.sql(f"ALTER TABLE {GOLD}.fact_school_enrollment ADD COLUMN barangay_psgc_code STRING")
    store.sql(f"ALTER TABLE {GOLD}.fact_school_classroom_capacity ADD COLUMN temporary_learning_spaces BIGINT")
    store.sql(f"ALTER TABLE {GOLD}.fact_school_classroom_capacity ADD COLUMN makeshift_rooms BIGINT")
    for column in ("sef_provincial", "sef_city_municipal", "lgu_funded", "other_funded"):
        store.sql(f"ALTER TABLE {GOLD}.fact_school_teacher_capacity ADD COLUMN {column}_teacher_count BIGINT")
    store.sql(f"CREATE TABLE {GOLD}.dim_school (school_id STRING, school_name STRING)")
    store.sql(f"""CREATE TABLE {GOLD}.dim_barangay (barangay_psgc_code STRING, barangay_name STRING,
        city_mun_psgc_code STRING, urban_rural STRING, member_type STRING)""")
    for code, (name, lgu, school_ids) in barangays.items():
        store.sql(f"INSERT INTO {GOLD}.dim_barangay VALUES ('{code}','{name}','{lgu}','Rural','regular')")
        for school_id in school_ids:
            store.sql(f"UPDATE {GOLD}.fact_school_enrollment SET barangay_psgc_code = '{code}' WHERE school_id = '{school_id}'")


def _rows(store, name, **chosen):
    """Run one planner dataset on DuckDB with its default filter values, or the ones chosen."""
    dataset = next(d for d in planner.build()["datasets"] if d["name"] == name)
    sql = "".join(dataset["queryLines"])
    params = {p["keyword"]: p["defaultSelection"]["values"]["values"][0]["value"] for p in dataset["parameters"]} | chosen
    return store.records(sql, {k: v for k, v in params.items() if re.search(rf":{k}\b", sql)})


def test_the_planner_shows_the_priority_as_published(store):
    # Town One gains a school with 300 learners in 4 reported rooms (75 per room), above the screen of 50
    add_public_school(store, "X1", "M1", 300, 4, 10)
    run_all(store)
    kpi = _rows(store, "ov_kpi")[0]
    assert (kpi["any_pressure"], kpi["schools_above"], kpi["learners_above"], kpi["data_review"]) == (1, 1, 300, 0)
    # Town One has classroom pressure and growing enrollment, so the matrix publishes Priority 2: high-priority review
    card = _rows(store, "pr_card", lgu="Town One, Province")[0]
    assert card["city_mun_name"] == "Town One" and card["queue_status"] == planner.QUEUE[1]
    assert card["status_label"] == planner.STATUS_LABELS[1]
    assert card["status_line"].startswith("Priority 2 · High-priority review: ")
    assert "National review order: 1 of " in card["details"]
    assert (card["classroom_kpi"], card["teacher_kpi"], card["enrollment_kpi"], card["readiness_kpi"]) == (
        "1 of 2", "0 of 1", "+41.7%", "100%")
    assert (kpi["joint_kpi"], kpi["any_kpi"], kpi["learners_kpi"], kpi["data_review_kpi"]) == (
        "0 of 4", "1 of 4", "300 (24.0%)", "0 of 4")  # every count out of the same total
    screen = _rows(store, "pr_evidence", lgu="Town One, Province")[0]
    assert screen["this_lgu"] == "1 of 2 schools, 300 learners" and screen["status"] == "Signal present"
    decision = _rows(store, "pr_decision", lgu="Town One, Province")
    assert [(r["signal"], r["result"]) for r in decision] == [
        ("Classroom pressure", "Yes"), ("Teacher pressure", "No"), ("Enrollment growing", "Yes"),
        ("Review status", planner.QUEUE[1])]
    queue = {r["lgu_label"]: r for r in _rows(store, "ov_lgu")}
    assert queue["Town One, Province"]["pressure_signals"] == "Classroom"
    assert queue["Town One, Province"]["status_basis"] == planner.STATUS_BASIS[1]
    assert {r["share_band"] for r in _rows(store, "dm_share")} <= set(planner.SHARE_BANDS)
    # the review-status filter and every legend use Priority 1 to 3, Monitor, No current pressure, Data review
    assert [r["lgu_label"] for r in _rows(store, "ov_lgu", queue=planner.QUEUE[1])] == ["Town One, Province"]


def test_a_level_above_its_reference_shows_even_when_another_level_is_not_fully_assessed(store):
    # review on #224: City One's JHS is above its reference while its SHS has no teacher count. AP3 publishes
    # "pressure signal identified", so the planner says the teacher signal is present, not "Not assessed"
    store.sql(f"""UPDATE {GOLD}.fact_school_enrollment SET is_offered = TRUE, learner_count = 200
        WHERE school_id = 'S1' AND school_year = '2023-24' AND education_level_code = 'JHS'""")
    store.sql(f"INSERT INTO {GOLD}.fact_school_teacher_capacity VALUES ('S1','2023-24','JHS',4)")
    store.sql(f"""UPDATE {GOLD}.fact_school_enrollment SET is_offered = TRUE, learner_count = 50
        WHERE school_id = 'S2' AND school_year = '2023-24' AND education_level_code = 'SHS'""")
    run_all(store)
    signal = {r["city_mun_psgc_code"]: r["teacher_signal"] for r in _rows(store, "ov_lgu")}
    assert signal["C1"] == planner.SIGNALS[0]


def test_a_chosen_level_without_a_teacher_count_shows_no_ratio(store):
    # review on #224: X1 offers JHS with no JHS teacher count. With JHS chosen it has no ratio, not the all-level one
    add_public_school(store, "X1", "M1", 300, 4, 10)
    store.sql(f"""UPDATE {GOLD}.fact_school_enrollment SET is_offered = TRUE, learner_count = 40
        WHERE school_id = 'X1' AND education_level_code = 'JHS'""")
    run_all(store)
    add_school_detail(store, {"B1": ("Poblacion", "M1", ["X1", "S4"])})
    ratio = {level: {r["school_id"]: r["teacher_ratio"] for r in _rows(store, "sa_list", level=level, lgu="Town One, Province")}
             for level in (planner.ALL_LEVELS, "Elementary", "Junior high")}
    assert ratio[planner.ALL_LEVELS]["X1"] == ratio["Elementary"]["X1"] == 30  # 300 ES learners over 10 ES teachers
    assert ratio["Junior high"]["X1"] is None
    shown = {r["school_id"]: r for r in _rows(store, "sa_list", level="Junior high", lgu="Town One, Province")}
    assert shown["X1"]["per_teacher_txt"] == "Not assessable"  # a word, never null
    # the bullet chart gives every level its own row and writes no number in a label
    bullets = _rows(store, "sa_bullet", level="Junior high", lgu="Town One, Province", school="X1 · X1")
    assert [(r["figure"], r["share_of_reference"], r["status"]) for r in bullets] == [
        ("Learners per reported room", 1.7, planner.LEVEL_STATUS[0]),
        ("Learners per elementary teacher", 30 / 35, planner.LEVEL_STATUS[1]),
        ("Learners per junior high teacher", None, planner.LEVEL_STATUS[2]),
        ("Learners per senior high teacher", 0, planner.NOT_OFFERED)]
    # the comparison scatter leaves it out at JHS rather than plotting the all-level ratio
    assert "X1" in {r["school_name"] for r in _rows(store, "sa_peers", level=planner.ALL_LEVELS, lgu="Town One, Province")}
    assert "X1" not in {r["school_name"] for r in _rows(store, "sa_peers", level="Junior high", lgu="Town One, Province")}
    school = _rows(store, "sa_school", level="Elementary", lgu="Town One, Province", school="X1 · X1")[0]
    assert school["teacher_kpi"] == "30.0 vs 35"


def test_every_listed_school_says_why_and_what_to_verify(store):
    # X1 is above the classroom screen; S4 has no flag. Both get a reason, and X1's verify panel names its figure
    add_public_school(store, "X1", "M1", 300, 4, 10)
    run_all(store)
    add_school_detail(store, {"B1": ("Poblacion", "M1", ["X1", "S4"])})
    rows = {r["school_id"]: r for r in _rows(store, "sa_list", lgu="Town One, Province")}
    assert all(r["why_listed"] and r["next_step"] for r in rows.values())
    assert rows["X1"]["why_listed"] == "Above classroom screen" and rows["X1"]["verification_status"] == planner.VERIFY[0]
    assert rows["S4"]["why_listed"] == "Included by classroom-pressure order"
    school = _rows(store, "sa_school", lgu="Town One, Province")[0]
    assert school["school_id"] == "X1" and school["verify_kpi"] == "1 verification item"
    assert (school["room_kpi"], school["teacher_kpi"], school["change_kpi"]) == ("75.0", "30.0", "Incomplete")
    assert school["verify_header"] == "Verify reported room count and enrollment"
    assert [r["item"] for r in _rows(store, "sa_verify", lgu="Town One, Province")] == ["Classroom pressure"]


def test_a_barangay_has_public_es_from_its_own_es_learners_matched_by_psgc_code(store):
    # review on #224: X1 has ES learners but no JHS count, so its all-level learners are unknown; it still gives
    # its barangay a public elementary school. Two barangays share a name and are told apart by PSGC code
    add_public_school(store, "X1", "M1", 300, 4, 10)
    store.sql(f"""UPDATE {GOLD}.fact_school_enrollment SET is_offered = TRUE, learner_count = NULL
        WHERE school_id = 'X1' AND education_level_code = 'JHS'""")
    run_all(store)
    add_school_detail(store, {"B1": ("Poblacion", "M1", ["X1"]), "B2": ("Poblacion", "M1", []),
                              "B3": ("San Roque", "M1", ["S4"])})
    rows = _rows(store, "pr_barangays", lgu="Town One, Province")
    assert sorted((r["barangay_name"], r["public_schools"], r["public_es"]) for r in rows) == [
        ("Poblacion", 0, "No"), ("Poblacion", 1, "Yes"), ("San Roque", 1, "Yes")]


def test_no_retired_tier_or_check_table_is_read():
    text = DASHBOARD.read_text(encoding="utf-8")
    for retired in ("lgu_priority_checks", "lgu_priority_outlier_schools", "order_in_tier", "is_stable", "_percentile"):
        assert retired not in text, retired
