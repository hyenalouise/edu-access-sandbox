"""The LGU planner dashboard: its JSON matches the generator, and its pages, filters and layout follow the plan."""

import json
import re
from pathlib import Path

import yaml

from src.dashboard import planner

ROOT = Path(__file__).parents[1]
DASHBOARD = ROOT / "dashboards" / "reached_planner.lvdash.json"
PAGES = ["overview", "lgu_profile", "school_action", "data_and_method"]


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


def test_no_page_has_more_than_four_kpis():
    for page in load()["pages"][:4]:
        counters = [w for w in widgets(page) if w.get("spec", {}).get("widgetType") == "counter"
                    and w["spec"]["frame"]["title"] not in ("Selected city or municipality", "Selected school")]  # headings, not KPIs
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


def test_the_bundle_deploys_this_dashboard():
    bundle = yaml.safe_load((ROOT / "databricks.yml").read_text(encoding="utf-8"))
    dashboard = bundle["resources"]["dashboards"]["reached_planner"]
    assert dashboard["file_path"] == "./dashboards/reached_planner.lvdash.json"
    assert dashboard["warehouse_id"] == "${var.warehouse_id}"
