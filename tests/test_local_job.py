"""The job in databricks.yml, run locally task by task on made-up deliveries.

What CI can show about the job before Databricks runs it: every task's command
or SQL file works in the order the job runs them, and run_if stops or continues
the right tasks. Databricks-only behavior is listed in docs/operations/ingestion.md.
"""

import json
import shutil

import pytest

from factories.deped_deliveries import (REPO_ROOT, approve, columns, empty_config, fake_repo, make_delivery, make_rows,
                                        with_values, write_config)
from factories import census_workbooks, hdx_geojson, psa_workbooks, psgc_workbooks, report_workbooks
from src.ingestion.control import ADDED_COLUMNS
from src.ingestion.store import DuckDBStore
from src.job import local_run
from src.job.local_run import in_order, job_parameters, load_job, python_argv, run_job
from src.integration import deped_school_psgc
from src.integration import psa_school_age_population_psgc
from src.silver import psa_school_age_population

REVISION = "d" * 40
CONTROL = "edu_access.`01-control`"
BRONZE = "edu_access.`02-bronze`.deped_enrollment_raw"


@pytest.fixture
def repo(tmp_path):
    root = fake_repo(tmp_path / "repo", empty_config("deped_enrollment"))
    # Facilities runs through Silver too, and its gate fails a build with no current batch, so the job
    # always has one made-up delivery approved for it (the same school IDs as deliver()'s enrollment).
    facilities = empty_config("deped_facilities")
    approve(facilities, make_delivery(tmp_path / "landing" / "deped" / "original", "2023-24",
                                      source_id="deped_facilities"), "2023-24")
    write_config(root, facilities)
    write_config(root, empty_config("deped_personnel"))
    # PSA Poverty Stat runs through Silver, and its gate fails a build with no current batch, so the job
    # always has one made-up workbook approved for it. Its two units are the made-up PSGC's municipality
    # and city, so the poverty map places every row and dim_city_poverty (#174) can pass its gate.
    psa = psa_workbooks.empty_config()
    years = ("2018", "2021", "2023")
    poverty_rows = [psa_workbooks.banner("Test Region"),
                    psa_workbooks.unit("00101", "Bayan ng Halimbawa", years, seed=1),         # 0000101000, Mun
                    psa_workbooks.unit("200102", "Lungsod ng Halimbawa", years, blank=True)]  # 2000102000, City
    workbook = psa_workbooks.write_workbook(tmp_path / "landing" / "psa" / "original" / psa_workbooks.WORKBOOK,
                                            rows=poverty_rows)
    psa_workbooks.approve(psa, workbook, rows=poverty_rows)
    write_config(root, psa)
    # PSGC runs through Silver too (#88), so it also gets one made-up workbook.
    psgc = psgc_workbooks.empty_config()
    psgc_workbooks.approve(psgc, psgc_workbooks.make_workbook(tmp_path / "landing" / "psa" / "original"))
    write_config(root, psgc)
    # HDX boundaries run through Silver too, so the job always has one made-up GeoJSON file approved for it.
    hdx = empty_config("hdx_boundaries")
    features = [hdx_geojson.silver_feature(i) for i in range(1, 4)]
    hdx_geojson.approve(hdx, hdx_geojson.write_features(tmp_path / "landing" / "admin_boundaries", features), 3)
    write_config(root, hdx)
    # The EMISD crosswalk runs through Silver too (#163), and its gate fails a build with no current batch,
    # so the job always has one made-up workbook approved for it: two ordinary schools, nothing quarantined.
    emisd = report_workbooks.empty_config()
    workbook = report_workbooks.make_workbook(tmp_path / "landing" / "deped" / "original",
                                              rows={9: report_workbooks.school(100001), 10: report_workbooks.school(100002)})
    report_workbooks.approve(emisd, workbook, row_count=2, unit_rows=2, blank_rows=0, no_identifier_rows=0, last_row=10)
    write_config(root, emisd)
    # PSA school-age population runs through Silver too (#158): one made-up tree workbook per census year,
    # with its level counts pinned in the Silver rules and the gate regenerated, as a reviewer would.
    census = census_workbooks.empty_config()
    workbooks = []
    for year in ("2020", "2024"):
        path = census_workbooks.write_tree_workbook(tmp_path / "landing" / "psa" / "original", year)
        census_workbooks.approve_tree(census, path, year)
        workbooks.append((year, path))
    write_config(root, census)
    rules = root / "config" / "mappings" / "psa_school_age_population.json"
    rules.write_text(json.dumps(census_workbooks.pin_tree_levels(json.loads(rules.read_text(encoding="utf-8")),
                                                                 workbooks), indent=2), encoding="utf-8")
    (root / "etl" / "03_silver" / "90_validate_psa_school_age_population_clean.sql").write_text(
        psa_school_age_population.gate_sql(psa_school_age_population.load_spec(root)), encoding="utf-8")
    # Its PSGC map (#159) gets rules for this made-up geography, its SQL regenerated: the committed rules name
    # real PSGC codes, and a region or alias code missing from the master quarter fails the map's gate (#187).
    map_rules = root / "config" / "integration" / "psa_school_age_population_psgc.json"
    map_rules.parent.mkdir(parents=True, exist_ok=True)
    rules = json.loads((REPO_ROOT / psa_school_age_population_psgc.CONFIG).read_text(encoding="utf-8"))
    regions = {"2020": ("REGION I", "NATIONAL CAPITAL REGION", "REGION II"),
               "2024": ("REGION I - TEST REGION", "NATIONAL CAPITAL REGION", "REGION II")}
    rules.update(province_aliases=[], overrides=[], regions=[
        {"census_year": int(year), "region_name": name, "psgc_region_codes": ["2000000000"], "reason": "made up"}
        for year, names in regions.items() for name in names])
    map_rules.write_text(json.dumps(rules, indent=2), encoding="utf-8")
    spec = psa_school_age_population_psgc.load_spec(root)
    folder = root / "etl" / "04_integration"
    (folder / "05_map_psa_school_age_population_psgc.sql").write_text(psa_school_age_population_psgc.build_sql(spec), encoding="utf-8")
    (folder / "90_validate_psa_school_age_population_psgc_map.sql").write_text(
        psa_school_age_population_psgc.gate_sql(spec), encoding="utf-8")
    # The made-up schools are not in the made-up PSGC, so the DepEd map's floor and profiled counts are
    # set for this job and its gate regenerated, as a reviewer would for a new delivery.
    rules = root / "config" / "mappings" / "integration" / "deped_school_psgc.json"
    deped_rules = json.loads(rules.read_text(encoding="utf-8"))
    deped_rules["gate"] |= {"min_match_rate_pct": 0, "profiled_counts": {}}
    rules.write_text(json.dumps(deped_rules, indent=2), encoding="utf-8")
    (root / "etl" / "04_integration" / "90_validate_deped_school_psgc_map.sql").write_text(
        deped_school_psgc.gate_sql(deped_school_psgc.load_spec(root)), encoding="utf-8")
    # dim_city_poverty's gate pins D-046's real counts; for this made-up geography they are set to its two
    # places, one estimated and one with no estimate, as a pull request that changes the pin would.
    gate = root / "etl" / "05_gold" / "90_validate_dim_city_poverty.sql"
    pins = ("SELECT 1642 AS pin_rows, 1597 AS pin_estimated, 1 AS pin_no_estimate, 44 AS pin_not_in_source, "
            "1 AS pin_manila_reason")
    text = gate.read_text(encoding="utf-8")
    assert pins in text
    gate.write_text(text.replace(pins, "SELECT 2 AS pin_rows, 1 AS pin_estimated, 1 AS pin_no_estimate, "
                                       "0 AS pin_not_in_source, 0 AS pin_manila_reason"), encoding="utf-8")
    shutil.copy(REPO_ROOT / "databricks.yml", root / "databricks.yml")
    return root


def deliver(repo, landing, source_id="deped_enrollment", school_year="2023-24"):
    """A made-up delivery in the landing folder, approved in the fake repository's contract."""
    config = json.loads((repo / "config" / "ingestion" / f"{source_id}.json").read_text(encoding="utf-8"))
    header = columns("v1", source_id)
    rows = make_rows(header)
    if "offers_jhs" in header:
        # The factory's schools offer ES only but publish JHS and SHS learners, which the enrollment
        # fact's gate rightly fails (not_offered_without_learners): these schools offer every level.
        rows = [with_values(header, row, {"offers_jhs": "True", "offers_shs": "True"}) for row in rows]
    path = make_delivery(landing / "deped" / "original", school_year, rows=rows, source_id=source_id)
    approve(config, path, school_year)
    write_config(repo, config)


def statuses(results):
    return {r.task_key: r.status for r in results}


def test_every_task_runs_in_order_and_succeeds(repo, tmp_path):
    landing = tmp_path / "landing"
    deliver(repo, landing)
    db = tmp_path / "job.duckdb"
    results = run_job(repo, landing, db, REVISION, run_id="job-run-1", log=lambda *_: None)
    failed = [(result.task_key, result.status, result.detail) for result in results if result.status not in {"succeeded", "disabled"}]
    assert not failed, failed
    _, job = load_job(repo)
    assert [r.task_key for r in results] == [t["task_key"] for t in in_order(job["tasks"])]
    result_statuses = statuses(results)
    enabled_gold_tasks = [task["task_key"] for task in job["tasks"]
                          if task.get("sql_task", {}).get("file", {}).get("path", "").startswith("etl/05_gold/")
                          and not task.get("disabled")]
    assert enabled_gold_tasks
    assert {key: result_statuses[key] for key in enabled_gold_tasks} == {key: "succeeded" for key in enabled_gold_tasks}
    store = DuckDBStore(db)
    assert store.query(f"SELECT COUNT(*) FROM {BRONZE}") == [(3,)]
    assert store.query(f"SELECT COUNT(*) FROM {CONTROL}.data_quality_results WHERE status = 'FAIL'") == [(0,)]
    assert store.query("SELECT COUNT(*), MIN(run_id) FROM edu_access.\"03-silver\".deped_enrollment_clean") == [(3, "job-run-1")]
    assert store.query(f"SELECT source_id, status FROM {CONTROL}.pipeline_runs WHERE pipeline_name = 'silver_build' "
                       "ORDER BY 1") == [("deped_enrollment", "succeeded"), ("deped_enrollment_psgc", "succeeded"),
                                         ("deped_facilities", "succeeded"),
                                         ("deped_personnel", "succeeded"), ("hdx_boundaries", "succeeded"),
                                         ("psa_poverty_stat", "succeeded"), ("psa_psgc", "succeeded"),
                                         ("psa_school_age_population", "succeeded")]
    assert store.query("SELECT COUNT(*), MIN(run_id) FROM edu_access.\"03-silver\".deped_facilities_clean") == [(3, "job-run-1")]
    assert store.query("SELECT COUNT(*), MIN(run_id) FROM edu_access.\"03-silver\".psa_psgc_clean") == [
        (len(psgc_workbooks.UNITS), "job-run-1")]
    assert store.query("SELECT COUNT(*), MIN(run_id) FROM edu_access.\"03-silver\".psa_poverty_stat_clean") == [(6, "job-run-1")]
    assert store.query("SELECT COUNT(*), MIN(run_id) FROM edu_access.\"03-silver\".hdx_adm3_clean") == [(3, "job-run-1")]
    # Every enrollment school-year has a city/municipality row and a barangay row, even when the
    # made-up PSGC has no match. The map runs only after enrollment, EMISD, and PSGC Silver gates.
    assert store.query("SELECT COUNT(*), MIN(run_id) FROM edu_access.\"04-integration\".deped_school_psgc_map") == [(6, "job-run-1")]
    assert store.query(f"SELECT status FROM {CONTROL}.pipeline_runs WHERE pipeline_name = 'integration_build' "
                       "AND source_id = 'deped_enrollment'") == [("succeeded",)]
    # The HDX map runs after the HDX and PSGC Silver gates (D-051): every made-up HDX feature has one map row (#93, D-052).
    assert store.query("SELECT COUNT(*), MIN(run_id) FROM edu_access.\"04-integration\".hdx_adm3_psgc_map") == [(3, "job-run-1")]
    assert store.query("SELECT COUNT(*), MIN(run_id) FROM edu_access.\"04-integration\".psa_poverty_psgc_map") == [(6, "job-run-1")]
    assert store.query(f"SELECT status FROM {CONTROL}.pipeline_runs WHERE pipeline_name = 'integration_build' "
                       "AND source_id = 'hdx_boundaries'") == [("succeeded",)]
    # The school-age map runs after the school-age and PSGC Silver gates (D-051): one row per made-up census place (#159).
    places = store.query("SELECT COUNT(*) FROM (SELECT DISTINCT census_year, place_name, parent_name FROM "
                         "edu_access.\"03-silver\".psa_school_age_population_clean WHERE level = 'city_municipality')")
    assert store.query("SELECT COUNT(*), MIN(run_id) FROM edu_access.\"04-integration\".psa_school_age_population_psgc_map") == [
        (places[0][0], "job-run-1")]
    assert store.query(f"SELECT status FROM {CONTROL}.pipeline_runs WHERE pipeline_name = 'integration_build' "
                       "AND source_id = 'psa_school_age_population'") == [("succeeded",)]
    assert store.query(f"SELECT source_id, status FROM {CONTROL}.data_quality_results "
                       "WHERE run_id = 'job-run-1' AND check_name = 'silver_lane_succeeded' ORDER BY 1") == [
        ("deped_enrollment", "PASS"), ("deped_enrollment_psgc", "PASS"), ("deped_facilities", "PASS"),
        ("deped_personnel", "PASS"), ("hdx_boundaries", "PASS"), ("psa_poverty_stat", "PASS"),
        ("psa_psgc", "PASS"), ("psa_school_age_population", "PASS")]   # one per Silver lane on
    fresh = store.query(f"SELECT source_id, status, actual FROM {CONTROL}.data_quality_results "
                        "WHERE run_id = 'job-run-1' AND check_name = 'source_fresh' ORDER BY 1")
    # One per loaded source, after the fan-in. Every batch was just loaded, so each source with one is fresh;
    # the fake repository approves no personnel delivery, so that one has none.
    assert [(source, status) for source, status, _ in fresh] == [
        ("deped_enrollment", "PASS"), ("deped_enrollment_psgc", "PASS"), ("deped_facilities", "PASS"),
        ("deped_personnel", "WARN"), ("hdx_boundaries", "PASS"), ("psa_poverty_stat", "PASS"), ("psa_psgc", "PASS"),
        ("psa_school_age_population", "PASS")]
    assert all(actual.startswith("last succeeded ") for _, status, actual in fresh if status == "PASS")
    assert dict((s, a) for s, _, a in fresh)["deped_personnel"] == "no succeeded batch"
    assert store.query("SELECT COUNT(*), MIN(run_id) FROM edu_access.\"03-silver\".psa_school_age_population_clean") == [
        (4 * len(census_workbooks.TREE) * 60, "job-run-1")]
    linked = store.query(f"""
        SELECT r.source_id, COUNT(q.check_name) FROM {CONTROL}.pipeline_runs AS r
        JOIN {CONTROL}.data_quality_results AS q ON q.run_id = r.job_run_id AND q.source_id = r.source_id
        WHERE r.job_run_id = 'job-run-1' AND q.layer = 'bronze' GROUP BY 1 ORDER BY 1""")
    assert [source for source, checks in linked if checks > 0] == [
        "deped_enrollment", "deped_enrollment_psgc", "deped_facilities", "deped_personnel", "hdx_boundaries",
        "psa_poverty_stat", "psa_psgc", "psa_school_age_population"]
    store.close()


def test_a_second_run_changes_nothing(repo, tmp_path):
    landing = tmp_path / "landing"
    deliver(repo, landing)
    db = tmp_path / "job.duckdb"
    run_job(repo, landing, db, REVISION, log=lambda *_: None)
    results = run_job(repo, landing, db, REVISION, log=lambda *_: None)
    assert set(statuses(results).values()) == {"succeeded"}
    store = DuckDBStore(db)
    assert store.query(f"SELECT COUNT(*) FROM {BRONZE}") == [(3,)]
    assert store.query(f"SELECT action, COUNT(*) FROM {CONTROL}.ingestion_batch_attempts GROUP BY 1 ORDER BY 1") \
        == [("load", 8), ("skip", 8)]   # DepEd enrollment and facilities, PSA Poverty Stat, PSGC, HDX, EMISD, both censuses
    store.close()


def test_the_job_runs_on_control_tables_from_before_added_columns(repo, tmp_path):
    """Control tables created before D-018 and D-020 lack logical_dataset and job_run_id. The job
    adds them before replacing current_batches, which reads logical_dataset (#113 review)."""
    landing = tmp_path / "landing"
    deliver(repo, landing)
    db = tmp_path / "job.duckdb"
    store = DuckDBStore(db)
    for path in sorted((repo / "etl" / "01_control").glob("0[1-4]_*.sql")):
        store.run_file(path)
    for table, columns in ADDED_COLUMNS.items():
        for name, _ in columns:
            store.sql(f"ALTER TABLE {CONTROL}.{table} DROP COLUMN {name}")
    store.close()
    results = statuses(run_job(repo, landing, db, REVISION, run_id="job-run-1", log=lambda *_: None))
    assert results["add_control_columns"] == "succeeded"
    assert set(results.values()) == {"succeeded"}
    store = DuckDBStore(db)
    assert store.query(f"SELECT pipeline_name, COUNT(*) FROM {CONTROL}.pipeline_runs WHERE job_run_id = 'job-run-1' "
                       "GROUP BY 1 ORDER BY 1") == [("bronze_ingest", 8), ("integration_build", 4), ("silver_build", 8)]   # one filter, both layers; the DepEd school, HDX, poverty and school-age maps write their own runs
    store.close()


def test_python_tasks_get_local_values():
    _, job = load_job(REPO_ROOT)
    task = next(t for t in job["tasks"] if t.get("spark_python_task", {}).get("parameters", [None])[0] == "ingest")
    params = job_parameters(job, REVISION, "job-run-1")
    argv = python_argv(task, "/tmp/landing", "/tmp/x.duckdb", params)
    for flag, value in (("--backend", "duckdb"), ("--environment", "local"), ("--landing", "/tmp/landing"),
                        ("--code-revision", REVISION), ("--db", "/tmp/x.duckdb")):
        assert argv[argv.index(flag) + 1] == value
    assert "/Volumes/edu_access/00-source/raw" not in argv
    assert params["code_revision"] == REVISION


def test_a_failing_gate_fails_its_task_and_an_independent_source_still_runs(repo, tmp_path):
    landing = tmp_path / "landing"
    deliver(repo, landing)
    db = tmp_path / "job.duckdb"
    run_job(repo, landing, db, REVISION, log=lambda *_: None)
    store = DuckDBStore(db)
    store.sql(f"INSERT INTO {BRONZE} SELECT * REPLACE ('ghost' AS batch_id) FROM {BRONZE} LIMIT 1")
    store.close()
    results = statuses(run_job(repo, landing, db, REVISION, run_id="job-run-2", log=lambda *_: None))
    assert results["bronze_deped_enrollment"] == "succeeded"      # the load itself is fine
    assert results["90_validate_deped_enrollment_raw"] == "failed"
    assert results["01_clean_deped_enrollment"] == "upstream_failed"   # Silver never builds on a failed gate
    assert results["bronze_deped_facilities"] == "succeeded"      # independent root: enrollment cannot block it
    assert results["05_clean_psa_poverty_stat"] == "succeeded"    # another lane still runs to the end
    assert results["90_validate_control"] == "failed"             # the fan-in runs anyway, records, and stops
    assert results["90_validate_freshness"] == "succeeded"        # and freshness is still checked after it
    assert results["04_map_deped_annex_mother"] == "upstream_failed"   # the map reads enrollment (D-051)
    store = DuckDBStore(db)
    assert store.query(f"SELECT check_name FROM {CONTROL}.data_quality_results WHERE run_id = 'job-run-2' "
                       "AND status = 'FAIL' ORDER BY 1") == [
        ("no_pipeline_duplicates",), ("rows_have_a_known_batch",), ("silver_lane_succeeded",),
        ("succeeded_batches_reconcile",)]
    assert store.query(f"SELECT source_id, status, actual FROM {CONTROL}.data_quality_results "
                       "WHERE run_id = 'job-run-2' AND check_name = 'silver_lane_succeeded' ORDER BY 1") == [
        ("deped_enrollment", "FAIL", "not run"), ("deped_enrollment_psgc", "PASS", "succeeded"),
        ("deped_facilities", "PASS", "succeeded"), ("deped_personnel", "PASS", "succeeded"),
        ("hdx_boundaries", "PASS", "succeeded"), ("psa_poverty_stat", "PASS", "succeeded"),
        ("psa_psgc", "PASS", "succeeded"), ("psa_school_age_population", "PASS", "succeeded")]
    store.close()


def test_a_failed_lane_stops_only_the_tasks_that_read_it(repo, tmp_path):
    """The annex map reads enrollment only, so a failed poverty lane does not stop it; the fan-in
    still records the failed lane and fails the run (D-051)."""
    landing = tmp_path / "landing"
    deliver(repo, landing)
    db = tmp_path / "job.duckdb"
    run_job(repo, landing, db, REVISION, log=lambda *_: None)
    poverty = "edu_access.`02-bronze`.psa_poverty_stat_raw"
    store = DuckDBStore(db)
    store.sql(f"INSERT INTO {poverty} SELECT * REPLACE ('ghost' AS batch_id) FROM {poverty} LIMIT 1")
    store.close()
    results = statuses(run_job(repo, landing, db, REVISION, run_id="job-run-2", log=lambda *_: None))
    assert results["90_validate_psa_poverty_stat_raw"] == "failed"
    assert results["05_clean_psa_poverty_stat"] == "upstream_failed"
    assert results["90_validate_control"] == "failed"              # the run still shows the failed lane
    assert results["04_map_deped_annex_mother"] == "succeeded"       # but a map that does not read poverty runs
    assert results["90_validate_deped_annex_mother_map"] == "succeeded"


@pytest.mark.parametrize("error", [RuntimeError("made-up Python task crash"), RuntimeError()], ids=["message", "no-message"])
def test_a_crashed_python_task_fails_and_an_independent_source_still_runs(repo, tmp_path, monkeypatch, error):
    landing = tmp_path / "landing"
    deliver(repo, landing)
    real_run_python = local_run.run_python

    def crash_enrollment(task, *args):
        if task["task_key"] == "bronze_deped_enrollment":
            raise error
        return real_run_python(task, *args)

    monkeypatch.setattr(local_run, "run_python", crash_enrollment)
    results = statuses(run_job(repo, landing, tmp_path / "job.duckdb", REVISION, log=lambda *_: None))

    assert results["bronze_deped_enrollment"] == "failed"
    assert results["90_validate_deped_enrollment_raw"] == "upstream_failed"
    assert results["bronze_deped_facilities"] == "succeeded"


def test_every_dashboard_query_runs_on_the_job_output(repo, tmp_path):
    # the planner dashboard reads only what the job publishes: every dataset and every widget query must run on it
    import re
    from src.dashboard import planner
    landing = tmp_path / "landing"
    deliver(repo, landing)
    db = tmp_path / "job.duckdb"
    run_job(repo, landing, db, REVISION, run_id="job-run-1", log=lambda *_: None)
    store = DuckDBStore(db)
    dashboard = planner.build()
    datasets = {d["name"]: d for d in dashboard["datasets"]}
    geometry = ("st_setsrid(st_simplify(st_geomfromgeojson(h.geometry), 0.003), 4326)",
                "ST_Simplify(ST_GeomFromGeoJSON(h.geometry), 0.003)")

    def dataset_sql(name):
        dataset = datasets[name]
        sql = "".join(dataset["queryLines"]).replace(*geometry)
        params = {p["keyword"]: p["defaultSelection"]["values"]["values"][0]["value"] for p in dataset["parameters"]}
        return sql, {k: v for k, v in params.items() if re.search(rf":{k}\b", sql)}

    for name in datasets:
        sql, params = dataset_sql(name)
        store.query(sql, params)
    aggregate = re.compile(r"\b(SUM|COUNT|MAX|MIN|AVG|FIRST)\s*\(")
    for page in dashboard["pages"]:
        for item in page["layout"]:
            for q in item["widget"].get("queries", []):
                if "fields" not in q["query"]:
                    continue
                inner, params = dataset_sql(q["query"]["datasetName"])
                fields = q["query"]["fields"]
                groups = [f["expression"] for f in fields if not aggregate.search(f["expression"])]
                sql = (f"SELECT {', '.join(f['expression'] + ' AS ' + chr(96) + f['name'] + chr(96) for f in fields)} "
                       f"FROM ({inner}) AS t")
                if not q["query"]["disaggregated"] and groups and len(groups) < len(fields):
                    sql += " GROUP BY " + ", ".join(groups)
                store.query(sql, params)
    insights = store.query(*dataset_sql("pr_insights"))  # one row of four findings, at least one filled
    assert len(insights) == 1 and any(insights[0])
    answers = store.query(*dataset_sql("pr_answers"))
    assert len(answers) == 1 and any(answers[0])
    store.close()
