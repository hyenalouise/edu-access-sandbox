"""The data-quality dashboard (#97): its committed JSON, its datasets, and its quality-attribute catalog.

Each dataset's SQL is run as committed, on DuckDB, against made-up control rows (as
tests/test_alerts.py does for the alerts) and against the rows a whole local job run writes.
What this cannot show: that Databricks renders the widgets. That is checked in the workspace.
"""

import json
import re
from datetime import datetime, timedelta

import pytest
import yaml

from factories.deped_deliveries import REPO_ROOT
from src.dashboard import data_quality
from src.ingestion.store import DuckDBStore, to_duckdb
from src.job.local_run import run_job
from test_local_job import REVISION, deliver, repo  # noqa: F401  (repo is that file's fake-repository fixture)

CONTROL = "edu_access.`01-control`"
T0 = datetime(2026, 10, 13, 1, 0)
WIDGET_VERSIONS = {"counter": 2, "table": 2, "bar": 3, "filter-multi-select": 2, "filter-date-range-picker": 2,
                   "custom-vega-viz": 1, "heatmap": 3, "line": 3}
LAYERS = ["control", "bronze", "silver", "integration", "gold", "analytics"]
CORE = ["Completeness", "Uniqueness", "Validity", "Accuracy", "Consistency", "Timeliness"]


@pytest.fixture(scope="module")
def board():
    return json.loads((REPO_ROOT / data_quality.PATH).read_text(encoding="utf-8"))


@pytest.fixture
def store():
    s = DuckDBStore()
    for name in ("01_create_pipeline_runs", "02_create_ingestion_batches", "04_create_data_quality_results",
                 "05_create_current_batches"):
        s.run_file(REPO_ROOT / "etl" / "01_control" / f"{name}.sql")
    yield s
    s.close()


def dataset_sql(board, name, start="2000-01-01", end="2100-01-01"):
    """The dataset's SQL as Databricks gets it, with the date range bound and one DuckDB spelling."""
    dataset = next(d for d in board["datasets"] if d["name"] == name)
    sql = "".join(dataset["queryLines"])
    for keyword in ("history_range", "trend_week"):
        sql = sql.replace(f":{keyword}.min", f"DATE '{start}'").replace(f":{keyword}.max", f"DATE '{end}'")
    return sql.replace("explode(sequence(", "unnest(generate_series(").replace("timestampdiff(SECOND, ", "datediff('second', ")


def rows(store, board, name, **dates):
    return store.records(dataset_sql(board, name, **dates))


def result(store, run_id, check_name, status, minutes, source_id="deped_enrollment", layer="bronze",
           table_name="edu_access.02-bronze.deped_enrollment_raw", batch_id="b1", actual="a"):
    store.sql(
        f"INSERT INTO {CONTROL}.data_quality_results (run_id, batch_id, source_id, layer, table_name, check_name, "
        "status, expected, actual, checked_at_utc, code_revision) "
        "VALUES (:run_id, :batch_id, :source_id, :layer, :table_name, :check_name, :status, 'e', :actual, :at, 'r')",
        {"run_id": run_id, "batch_id": batch_id, "source_id": source_id, "layer": layer, "table_name": table_name,
         "check_name": check_name, "status": status, "actual": actual, "at": T0 + timedelta(minutes=minutes)})


def batch(store, batch_id, status="succeeded", version=1, school_year="2023-24", source_id="deped_enrollment"):
    store.sql(
        f"INSERT INTO {CONTROL}.ingestion_batches (batch_id, source_id, school_year, delivery_version, status, "
        "archive_path, archive_name, archive_sha256, attempt_count, first_run_id, last_run_id, "
        "first_attempt_at_utc, last_attempt_at_utc, succeeded_at_utc, environment, code_revision) "
        "VALUES (:b, :s, :y, :v, :status, 'p', 'n', :b, 1, 'r', 'r', :at, :at, :ok, 'dev', 'r')",
        {"b": batch_id, "s": source_id, "y": school_year, "v": version, "status": status, "at": T0,
         "ok": T0 if status == "succeeded" else None})


def run(store, run_id, source_id, status, minutes, job_run_id=None, pipeline_name="bronze_ingest",
        finished=True, failure_stage=None, error_message=None):
    store.sql(
        f"INSERT INTO {CONTROL}.pipeline_runs (run_id, pipeline_name, source_id, environment, status, "
        "started_at_utc, finished_at_utc, failure_stage, error_message, code_revision, job_run_id) "
        "VALUES (:r, :p, :s, 'dev', :status, :start, :end, :stage, :error, 'r', :job)",
        {"r": run_id, "p": pipeline_name, "s": source_id, "status": status, "start": T0 + timedelta(minutes=minutes),
         "end": T0 + timedelta(minutes=minutes + 5) if finished else None, "stage": failure_stage,
         "error": error_message, "job": job_run_id})


def totals(store, board):
    """The overview counters, computed the way the widgets do: SUM over the current dataset."""
    sql = dataset_sql(board, "ds_current")
    return store.records(
        f"SELECT SUM(is_result) AS checks, SUM(is_pass) AS pass, SUM(is_warn) AS warn, SUM(is_fail) AS fail, "
        f"SUM(is_test_pass) * 1.0 / NULLIF(SUM(is_test), 0) AS pass_rate FROM ({sql}) AS d")[0]


# ---------------------------------------------------------------- the committed file

def test_committed_dashboard_is_generated_from_the_catalog():
    committed = (REPO_ROOT / data_quality.PATH).read_text(encoding="utf-8")
    assert committed == data_quality.render(REPO_ROOT), (
        f"Regenerate it: python -m src.dashboard.data_quality > {data_quality.PATH}")


def test_dashboard_reads_only_the_control_tables(board):
    """Gold is not built; the dashboard must not depend on any data table, only on 01-control."""
    allowed = {"data_quality_results", "pipeline_runs", "ingestion_batches", "current_batches"}
    for dataset in board["datasets"]:
        sql = "".join(dataset["queryLines"])
        objects = re.findall(r"edu_access\.(\S+?)\.(\w+)", sql.replace("`01-control`", "01-control"))
        assert objects, dataset["name"]
        for schema, table in objects:
            # Text inside string literals (a table_name value) is not a read; the FROM/JOIN names are.
            if f"edu_access.`{schema}`.{table}" not in sql:
                continue
            assert schema == "01-control" and table in allowed, f"{dataset['name']} reads {schema}.{table}"
        for line in dataset["queryLines"]:
            assert line.endswith("\n"), f"{dataset['name']}: query lines are joined verbatim"


def widgets(board):
    for page in board["pages"]:
        for item in page["layout"]:
            yield page, item["widget"], item["position"]


def test_every_widget_binds_to_fields_its_dataset_has(board):
    names = {d["name"] for d in board["datasets"]}
    for page, widget, position in widgets(board):
        assert re.fullmatch(r"[A-Za-z0-9_-]{1,60}", widget["name"])
        assert 0 <= position["x"] and position["x"] + position["width"] <= 12, widget["name"]
        if "multilineTextboxSpec" in widget:
            continue
        spec = widget["spec"]
        assert spec["version"] == WIDGET_VERSIONS[spec["widgetType"]], widget["name"]
        assert spec["frame"]["showTitle"] is True, widget["name"]
        queries = {q["name"]: q["query"] for q in widget["queries"]}
        assert all(q["datasetName"] in names for q in queries.values()), widget["name"]
        if spec["widgetType"].startswith("filter-"):
            for field in spec["encodings"]["fields"]:
                query = queries[field["queryName"]]
                bound = {f["name"] for f in query.get("fields", [])} | {p["keyword"] for p in query.get("parameters", [])}
                assert field.get("fieldName", field.get("parameterName")) in bound, widget["name"]
            continue
        selected = {f["name"] for f in queries["main_query"]["fields"]}
        encodings = spec["encodings"]
        if spec["widgetType"] == "custom-vega-viz":
            used = {f["fieldName"] for f in encodings["fields"]}
            assert spec["data"]["queryName"] == "main_query"
            assert json.loads(spec["jsonSpec"]["spec"])["data"] == {"name": "databricks_query"}
        elif "columns" in encodings:
            used = {c["fieldName"] for c in encodings["columns"]}
        else:
            used = {e["fieldName"] for e in encodings.values() if "fieldName" in e}
        assert used == selected, f"{widget['name']}: encodings must name exactly the selected fields"


def test_no_two_widgets_overlap_and_the_overview_has_at_most_six_graphs(board):
    for page in board["pages"]:
        cells = {}
        for item in page["layout"]:
            p = item["position"]
            for x in range(p["x"], p["x"] + p["width"]):
                for y in range(p["y"], p["y"] + p["height"]):
                    assert (x, y) not in cells, f"{page['name']}: {item['widget']['name']} overlaps {cells[(x, y)]}"
                    cells[(x, y)] = item["widget"]["name"]
    overview = next(p for p in board["pages"] if p["name"] == "overview")
    graphs = [i["widget"]["name"] for i in overview["layout"]
              if i["widget"].get("spec", {}).get("widgetType") in ("bar", "line", "heatmap", "table")]
    assert len(graphs) <= 6, graphs


def test_every_widget_field_is_a_dataset_column(store, board):
    """A widget expression that names a column the dataset does not return breaks on Databricks only."""
    def returned(name):
        cursor = store.con.execute(to_duckdb(f"SELECT * FROM ({dataset_sql(board, name)}) AS x LIMIT 0"))
        return {c[0] for c in cursor.description}

    columns = {d["name"]: returned(d["name"]) | {c["displayName"] for c in d.get("columns", [])}
               for d in board["datasets"]}
    for _, widget, _ in widgets(board):
        for query in (q["query"] for q in widget.get("queries", [])):
            for field in query.get("fields", []):
                for column in re.findall(r"`([^`*]+)`", field["expression"]):
                    assert column in columns[query["datasetName"]], f"{widget['name']}: {column}"
            for f in query.get("filters", []):
                for column in re.findall(r"`([^`]+)`", f["expression"]):
                    assert column in columns[query["datasetName"]], f"{widget['name']}: {column}"


def test_the_bundle_deploys_the_committed_file_without_a_schedule():
    """No scheduled refresh during development (D-008): the dashboard refreshes only when it is opened."""
    bundle = yaml.safe_load((REPO_ROOT / "databricks.yml").read_text(encoding="utf-8"))
    resource = bundle["resources"]["dashboards"]["data_quality"]
    assert resource["file_path"] == data_quality.PATH
    assert resource["warehouse_id"] == "${var.warehouse_id}"
    assert "schedule" not in resource and "schedules" not in resource


def test_one_donut_per_core_attribute(board):
    """Six donuts in one row, title only (the definitions are in the Definitions box, 0ef532f)."""
    donuts = [(w, p) for _, w, p in widgets(board) if w.get("spec", {}).get("widgetType") == "custom-vega-viz"]
    assert [w["spec"]["frame"]["title"] for w, _ in donuts] == CORE
    assert sum(p["width"] for _, p in donuts) == 12 and len({p["y"] for _, p in donuts}) == 1
    for widget, _ in donuts:
        query = widget["queries"][0]["query"]
        assert query["filters"] == [{"expression": f"`quality_attribute` = '{widget['spec']['frame']['title']}'"}]
        assert "description" not in widget["spec"]["frame"]
    definitions = next(w for _, w, _ in widgets(board) if w["name"] == "definitions")
    text = "".join(definitions["multilineTextboxSpec"]["lines"])
    assert all(f"**{name}**:" in text for name in CORE), "each core attribute's definition is listed"


def test_a_donut_with_no_tests_is_no_checks_not_zero(store, board):
    """The donut query aggregates with no GROUP BY: one row, NULL when the attribute has no test."""
    result(store, "run-1", "rows_reconcile", "FAIL", 0)
    result(store, "run-1", "key_unique", "PASS", 0)
    result(store, "run-1", "rule_blank_text_to_null", "PASS", 0)       # a recorded count, not a test
    sql = dataset_sql(board, "ds_current")
    def rate(attribute):
        return store.query(f"SELECT SUM(is_test_pass), SUM(is_test) FROM ({sql}) AS d "
                           f"WHERE quality_attribute = '{attribute}'")[0]
    assert rate("Uniqueness") == (1, 1)
    assert rate("Timeliness") == (None, None)                           # the donut says "No checks"


# ---------------------------------------------------------------- the quality-attribute catalog

def classified(store, board, names):
    for i, name in enumerate(names):
        result(store, "run-1", name, "PASS", 0, batch_id=f"b{i}")
    return {r["check_name"]: r for r in rows(store, board, "ds_current")}


def literal_check_names():
    """Every check name written as a literal by a gate under etl/ or by the Bronze checks in src/ingestion."""
    names = set()
    for path in (REPO_ROOT / "etl").rglob("90_*.sql"):
        sql = path.read_text(encoding="utf-8")
        names |= set(re.findall(r"'([a-z][a-z0-9_]+)'\s+AS\s+check_name", sql))
        names |= set(re.findall(r"SELECT\s+:run_id,\s*[^,]+,\s*[^,]+,\s*'\w+',\s*'[^']+',\s*'([a-z0-9_]+)'", sql))
        names |= set(re.findall(r"SELECT\s+'([a-z][a-z0-9_]+)',\s*(?:'[A-Z]+'|CASE)", sql))
        # SELECT batch_id, '<table>', '<check>', status ... (e.g. the personnel quarantine reasons)
        names |= set(re.findall(r"SELECT\s+[a-z_.]+,\s*'[^']*',\s*'([a-z][a-z0-9_]+)',\s*(?:'[A-Z]+'|CASE)", sql))
    for path in (REPO_ROOT / "src" / "ingestion").glob("*.py"):
        code = path.read_text(encoding="utf-8")
        names |= set(re.findall(r'(?:add|profiled)\(\s*"([a-z][a-z0-9_]+)"', code))
        names |= set(re.findall(r'\(\s*"([a-z][a-z0-9_]+)",\s*[a-z_]+ ==', code))
    return sorted(names)


def built_check_names():
    """A sample of every check name a gate builds in SQL as '<base>_' || school_year ... or '<base>/' || ...,
    with a qualifier of the same shape, so the base must be listed (or covered by a family)."""
    names = set()
    for path in (REPO_ROOT / "etl").rglob("90_*.sql"):
        for base, sep in re.findall(r"'([a-z][a-z0-9_]*?)([_/])'\s*\|\|", path.read_text(encoding="utf-8")):
            names.add(base + ("/2023-24/ES" if sep == "/" else "_2023-24_city_mun"))
    return sorted(names)


def test_every_check_name_built_in_sql_is_in_the_catalog(store, board):
    """profiled_<school year>_<level> went unclassified until this test existed (review on #191)."""
    names = built_check_names()
    assert "profiled_2023-24_city_mun" in names and "learners/2023-24/ES" in names
    found = classified(store, board, names)
    missing = sorted(n for n, r in found.items() if r["classification_basis"].startswith("not in"))
    assert not missing, f"Add the base names of these to {data_quality.CONFIG}: {missing}"


def test_every_literal_check_name_is_in_the_catalog(store, board):
    names = literal_check_names()
    assert len(names) > 150
    found = classified(store, board, names)
    missing = sorted(n for n, r in found.items() if r["classification_basis"].startswith("not in"))
    assert not missing, f"Add these to {data_quality.CONFIG}: {missing}"


def test_names_resolve_exactly_then_by_qualifier_then_by_family(store, board):
    found = classified(store, board, [
        "rows_reconcile", "rows_reconcile_2018", "key_unique_household", "household_not_above_total",
        "2024 Total Pop: no_pipeline_duplicates", "labels_mapped_sector", "rule_blank_text_to_null",
        "method_valid", "silver_lane_succeeded", "a_check_nobody_listed", "match_rate_2023-24_bgy",
        "learners/2023-24/ES", "upstream_run_psa_psgc_clean", "rule_codes_in_psgc"])
    got = {n: (r["quality_attribute"], r["check_kind"], r["classification_basis"]) for n, r in found.items()}
    assert got["rows_reconcile"] == ("Reconciliation", "test", "listed")
    assert got["rows_reconcile_2018"] == ("Reconciliation", "test", "listed, with a year or concept qualifier")
    assert got["key_unique_household"][0] == "Uniqueness"
    assert got["household_not_above_total"][:2] == ("Consistency", "test")           # exact wins over qualifier
    assert got["2024 Total Pop: no_pipeline_duplicates"][0] == "Uniqueness"         # sheet prefix removed
    assert got["labels_mapped_sector"] == ("Validity", "test", "name family labels_mapped_")
    assert got["rule_blank_text_to_null"][:2] == ("Recorded count", "record")
    assert got["method_valid"][0] == "Validity"                                     # exact wins over method_
    assert got["silver_lane_succeeded"][0] == "Unclassified"
    assert got["silver_lane_succeeded"][2].startswith("deliberately unclassified: ")
    assert got["match_rate_2023-24_bgy"][:2] == ("Referential integrity", "test")    # school year and level
    assert got["learners/2023-24/ES"][:2] == ("Recorded count", "record")
    assert got["upstream_run_psa_psgc_clean"] == ("Lineage", "test", "name family upstream_run_")
    assert got["rule_codes_in_psgc"][0] == "Referential integrity"                  # exact wins over rule_
    assert got["a_check_nobody_listed"] == ("Unclassified", "test", f"not in {data_quality.CONFIG}")


def test_catalog_rejects_overlapping_families_and_repeats(tmp_path):
    config = yaml.safe_load((REPO_ROOT / data_quality.CONFIG).read_text(encoding="utf-8"))
    (tmp_path / "config").mkdir()
    for change, message in [
        (lambda c: c["families"].update({"labels_": {"attribute": "Validity", "basis": "x"}}), "overlap"),
        (lambda c: c["checks"]["Validity"].append("rows_reconcile"), "more than once"),
        (lambda c: c["checks"].update({"Freshness": ["x"]}), "not an attribute"),
    ]:
        broken = json.loads(json.dumps(config))
        change(broken)
        (tmp_path / data_quality.CONFIG).write_text(yaml.safe_dump(broken), encoding="utf-8")
        with pytest.raises(data_quality.CatalogError, match=message):
            data_quality.load_catalog(tmp_path)


# ---------------------------------------------------------------- current versus history

def test_no_results_is_no_data_not_zero_failures(store, board):
    assert rows(store, board, "ds_current") == []
    assert totals(store, board) == {"checks": None, "pass": None, "warn": None, "fail": None, "pass_rate": None}


def test_a_check_rerun_counts_once_in_current_and_every_time_in_history(store, board):
    result(store, "run-1", "rows_reconcile", "FAIL", 0)
    result(store, "run-2", "rows_reconcile", "PASS", 60)
    result(store, "run-3", "rows_reconcile", "PASS", 120)
    assert totals(store, board) == {"checks": 1, "pass": 1, "warn": 0, "fail": 0, "pass_rate": 1.0}
    assert [r["status"] for r in rows(store, board, "ds_history")].count("PASS") == 2
    assert len(rows(store, board, "ds_history")) == 3


def test_a_partial_later_run_does_not_hide_an_earlier_fail(store, board):
    """Unlike the quality_failures alert (latest run only), current keeps each check's own newest result."""
    result(store, "run-1", "rows_reconcile", "FAIL", 0, source_id="psa_psgc")
    result(store, "run-2", "rows_reconcile", "PASS", 60, source_id="deped_enrollment")
    current = {(r["source_id"], r["status"]) for r in rows(store, board, "ds_current")}
    assert current == {("psa_psgc", "FAIL"), ("deped_enrollment", "PASS")}


def test_results_of_a_superseded_delivery_leave_current_but_a_failed_one_stays(store, board):
    batch(store, "old", version=1)
    batch(store, "new", version=2)
    batch(store, "broken", status="failed", school_year="2024-25")
    for batch_id in ("old", "new", "broken"):
        result(store, "run-1", "row_count_matches_approved", "FAIL" if batch_id == "broken" else "PASS", 0,
               batch_id=batch_id)
    current = {r["batch_id"]: (r["batch_state"], r["batch_period"]) for r in rows(store, board, "ds_current")}
    assert current == {"new": ("current delivery", "2023-24"), "broken": ("batch failed", "2024-25")}
    assert len(rows(store, board, "ds_history")) == 3


def test_rows_one_gate_wrote_together_are_all_kept(store, board):
    result(store, "run-1", "rows_reconcile", "FAIL", 0, batch_id=None, actual="x")
    result(store, "run-1", "rows_reconcile", "WARN", 0, batch_id=None, actual="y")
    assert sorted(r["status"] for r in rows(store, board, "ds_current")) == ["FAIL", "WARN"]


def test_pass_rate_leaves_recorded_counts_out(store, board):
    result(store, "run-1", "rows_reconcile", "FAIL", 0)
    result(store, "run-1", "rule_blank_text_to_null", "PASS", 0)
    result(store, "run-1", "match_rate_percent", "PASS", 0)
    assert totals(store, board) == {"checks": 3, "pass": 2, "warn": 0, "fail": 1, "pass_rate": 0.0}


def test_runs_roll_bronze_loads_up_to_their_job_run_without_counting_results_twice(store, board):
    run(store, "uuid-1", "deped_enrollment", "succeeded", 0, job_run_id="job-1")
    run(store, "uuid-2", "psa_psgc", "failed", 1, job_run_id="job-1", failure_stage="validate",
        error_message="row count")
    run(store, "job-1", "deped_enrollment", "succeeded", 10, job_run_id="job-1", pipeline_name="silver_build")
    run(store, "manual-1", "psa_psgc", "running", 100, finished=False)
    for check in ("rows_reconcile", "lineage_complete"):
        result(store, "job-1", check, "PASS", 5)
    result(store, "uuid-1", "row_count_matches_approved", "PASS", 0)   # a load's batch check: its own run_id
    result(store, "job-1", "row_count_matches_approved", "FAIL", 5, source_id="psa_psgc", batch_id="b2")
    result(store, "orphan-run", "rows_reconcile", "PASS", 200)
    got = {r["run_id"]: r for r in rows(store, board, "ds_runs")}
    assert set(got) == {"job-1", "manual-1", "orphan-run"}
    job = got["job-1"]
    assert (job["run_status"], job["steps"], job["failed_steps"], job["pass_results"], job["fail_results"]) == (
        "failed", 3, 1, 3, 1)
    assert job["steps_not_succeeded"] == "bronze_ingest psa_psgc" and job["failure_stages"] == "validate"
    assert job["duration_minutes"] == 15
    assert got["manual-1"]["run_status"] == "running or interrupted" and got["manual-1"]["run_finished_at_utc"] is None
    assert got["orphan-run"]["run_status"] == "no pipeline_runs row"
    assert {r["run_recency"]: r["run_id"] for r in got.values()}[1] == "orphan-run"


def test_a_gold_fail_fails_the_run_even_when_every_recorded_step_succeeded(store, board):
    """Gold and Analytics gates write no pipeline_runs row, so a FAIL they record must still fail the run
    (review on #191). A repaired run keeps its run_id: a later PASS of the same check replaces the FAIL."""
    run(store, "job-1", "deped_enrollment", "succeeded", 0, job_run_id="job-1", pipeline_name="silver_build")
    result(store, "job-1", "key_unique", "FAIL", 5, layer="gold", source_id="dim_school",
           table_name="edu_access.05-gold.dim_school", batch_id=None)
    job = {r["run_id"]: r for r in rows(store, board, "ds_runs")}["job-1"]
    assert (job["step_status"], job["run_status"], job["fail_results"]) == ("succeeded", "failed", 1)
    result(store, "job-1", "key_unique", "PASS", 30, layer="gold", source_id="dim_school",
           table_name="edu_access.05-gold.dim_school", batch_id=None)
    job = {r["run_id"]: r for r in rows(store, board, "ds_runs")}["job-1"]
    assert (job["run_status"], job["fail_results"], job["pass_results"]) == ("succeeded", 0, 1)


def test_job_runs_are_not_date_filtered(board):
    """The latest run must not disappear when it is older than the date range (review on #191)."""
    date_filter = next(w for _, w, _ in widgets(board) if w["name"] == "g_dates")
    assert {q["query"]["datasetName"] for q in date_filter["queries"]} == {"ds_history"}


def test_freshness_shows_what_the_stale_sources_alert_emails(store, board):
    alert = yaml.safe_load((REPO_ROOT / "databricks.yml").read_text(encoding="utf-8"))["resources"]["alerts"]
    result(store, "run-1", "source_fresh", "WARN", 0, layer="control", source_id="psa_psgc", batch_id=None)
    result(store, "run-1", "source_fresh", "PASS", 0, layer="control", source_id="deped_enrollment", batch_id=None)
    result(store, "run-2", "rows_reconcile", "PASS", 60)        # a later run that skipped freshness
    emailed = {r["source_id"] for r in store.records(alert["stale_sources"]["query_text"])}
    shown = {r["source_id"] for r in rows(store, board, "ds_freshness") if r["is_stale"] == 1}
    assert emailed == shown == {"psa_psgc"}


# ---------------------------------------------------------------- on what a whole local job run writes

def test_every_check_a_local_job_run_writes_is_classified_and_every_dataset_runs(repo, tmp_path, board):
    """The made-up deliveries of tests/test_local_job.py, run through every task: the check names the
    gates really write (including the ones Bronze builds from each source's config) must all be listed."""
    landing = tmp_path / "landing"
    deliver(repo, landing)
    db = tmp_path / "job.duckdb"
    run_job(repo, landing, db, REVISION, run_id="job-run-1", log=lambda *_: None)
    run_job(repo, landing, db, REVISION, run_id="job-run-2", log=lambda *_: None)
    store = DuckDBStore(db)
    try:
        current = rows(store, board, "ds_current")
        unlisted = sorted({r["check_name"] for r in current if r["classification_basis"].startswith("not in")})
        assert not unlisted, f"Add these to {data_quality.CONFIG}: {unlisted}"
        recorded = store.query(f"SELECT COUNT(*) FROM {CONTROL}.data_quality_results")[0][0]
        assert len(rows(store, board, "ds_history")) == recorded            # history: every event
        assert len(current) < recorded                                       # current: each check once
        assert {r["layer"] for r in current} == set(LAYERS)                    # Gold is built now
        # The Gold widgets have rows: every Gold table and Analytics output, its upstream builds, and
        # a match rate from each PSGC map.
        gold = {r["table_name"].split(".")[-1].removesuffix("_candidate") for r in current
                if r["layer"] in ("gold", "analytics")}
        assert {"dim_school", "fact_school_enrollment", "lgu_priority_matrix"} <= gold and len(gold) == 18   # 7 dimensions (dim_school_location, #217), 6 facts, 5 Analytics tables
        assert all(r["layer"] == "gold" for r in current if r["check_name"].startswith("upstream_run_"))
        assert {r["table_name"].split(".")[-1].removesuffix("_candidate") for r in current
                if r["check_name"].startswith("match_rate")} == {
            "deped_school_psgc_map", "psa_poverty_psgc_map", "hdx_adm3_psgc_map", "psa_school_age_population_psgc_map"}
        assert {r["run_id"] for r in rows(store, board, "ds_runs")} >= {"job-run-1", "job-run-2"}
        assert rows(store, board, "ds_freshness")
    finally:
        store.close()



def test_the_trend_is_its_own_last_seven_days(board):
    trend = next(d for d in board["datasets"] if d["name"] == "ds_trend")
    assert trend["parameters"][0]["defaultSelection"]["range"]["min"] == {"value": "now-6d/d"}
    date_filter = next(w for _, w, _ in widgets(board) if w["name"] == "g_dates")
    assert "ds_trend" not in {q["query"]["datasetName"] for q in date_filter["queries"]}


def test_the_daily_trend_has_a_zero_for_every_day_nothing_ran(store, board):
    """A line needs a point per day: days and statuses with no result are 0, not missing."""
    result(store, "run-1", "rows_reconcile", "WARN", 0)                      # 2026-10-13 only
    result(store, "run-0", "rows_reconcile", "FAIL", -60 * 24 * 30, layer="staging")  # outside the week
    trend = rows(store, board, "ds_trend", start="2026-10-12", end="2026-10-14")
    got = {}
    for r in trend:                                                          # summed over layers, as the line is
        key = (str(r["checked_on_utc"])[:10], r["status"])
        got[key] = got.get(key, 0) + r["result_events"]
    assert len(got) == 9                                                     # 3 days x 3 statuses
    assert got[("2026-10-13", "WARN")] == 1
    assert sum(got.values()) == 1
    # Every pipeline layer has its zeros for the layer filter; a layer the week did not record is not read.
    assert {r["layer"] for r in trend} == set(LAYERS)


def test_a_date_range_keeps_its_whole_last_day(store, board):
    """The range filters the timestamp itself (so Delta can skip older files); its last day stays whole."""
    for minutes, run_id in ((-61, "day-before"), (0, "first-day"), (60 * 24 + 22 * 60 + 59, "last-day-23:59"),
                            (60 * 24 * 2 - 59, "day-after")):
        result(store, run_id, "rows_reconcile", "PASS", minutes)          # T0 is 2026-10-13 01:00
    history = {r["run_id"] for r in rows(store, board, "ds_history", start="2026-10-13", end="2026-10-14")}
    assert history == {"first-day", "last-day-23:59"}
    trend = rows(store, board, "ds_trend", start="2026-10-13", end="2026-10-14")
    assert sum(r["result_events"] for r in trend) == 2
