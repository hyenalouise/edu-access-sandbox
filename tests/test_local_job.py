"""The job in databricks.yml, run locally task by task on made-up deliveries.

What CI can show about the job before Databricks runs it: every task's command
or SQL file works in the order the job runs them, and run_if stops or continues
the right tasks. Databricks-only behavior is listed in docs/operations/ingestion.md.
"""

import json
import shutil

import pytest

from factories.deped_deliveries import REPO_ROOT, approve, empty_config, fake_repo, make_delivery, write_config
from factories import psa_workbooks, psgc_workbooks
from src.ingestion.control import ADDED_COLUMNS
from src.ingestion.store import DuckDBStore
from src.job import local_run
from src.job.local_run import in_order, job_parameters, load_job, python_argv, run_job

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
    # always has one made-up workbook approved for it.
    psa = psa_workbooks.empty_config()
    workbook = psa_workbooks.write_workbook(tmp_path / "landing" / "psa" / "original" / psa_workbooks.WORKBOOK)
    psa_workbooks.approve(psa, workbook)
    write_config(root, psa)
    write_config(root, psgc_workbooks.empty_config())   # enabled lanes with no approved delivery yet
    write_config(root, empty_config("hdx_boundaries"))                  # ← new
    (tmp_path / "landing" / "admin_boundaries").mkdir(parents=True)     # ← new
    shutil.copy(REPO_ROOT / "databricks.yml", root / "databricks.yml")
    return root


def deliver(repo, landing, source_id="deped_enrollment", school_year="2023-24"):
    """A made-up delivery in the landing folder, approved in the fake repository's contract."""
    config = json.loads((repo / "config" / "ingestion" / f"{source_id}.json").read_text(encoding="utf-8"))
    path = make_delivery(landing / "deped" / "original", school_year, source_id=source_id)
    approve(config, path, school_year)
    write_config(repo, config)


def statuses(results):
    return {r.task_key: r.status for r in results}


def test_every_task_runs_in_order_and_succeeds(repo, tmp_path):
    landing = tmp_path / "landing"
    deliver(repo, landing)
    db = tmp_path / "job.duckdb"
    results = run_job(repo, landing, db, REVISION, run_id="job-run-1", log=lambda *_: None)
    assert set(statuses(results).values()) == {"succeeded", "disabled"}
    _, job = load_job(repo)
    assert [r.task_key for r in results] == [t["task_key"] for t in in_order(job["tasks"])]
    store = DuckDBStore(db)
    assert store.query(f"SELECT COUNT(*) FROM {BRONZE}") == [(3,)]
    assert store.query(f"SELECT COUNT(*) FROM {CONTROL}.data_quality_results WHERE status = 'FAIL'") == [(0,)]
    assert store.query("SELECT COUNT(*), MIN(run_id) FROM edu_access.\"03-silver\".deped_enrollment_clean") == [(3, "job-run-1")]
    assert store.query(f"SELECT source_id, status FROM {CONTROL}.pipeline_runs WHERE pipeline_name = 'silver_build' "
                       "ORDER BY 1") == [("deped_enrollment", "succeeded"), ("deped_facilities", "succeeded"),
                                         ("psa_poverty_stat", "succeeded")]
    assert store.query("SELECT COUNT(*), MIN(run_id) FROM edu_access.\"03-silver\".deped_facilities_clean") == [(3, "job-run-1")]
    assert store.query("SELECT COUNT(*), MIN(run_id) FROM edu_access.\"03-silver\".psa_poverty_stat_clean") == [(18, "job-run-1")]
    assert store.query(f"SELECT source_id, status FROM {CONTROL}.data_quality_results "
                       "WHERE run_id = 'job-run-1' AND layer = 'control' ORDER BY 1") == [
        ("deped_enrollment", "PASS"), ("psa_poverty_stat", "PASS")]          # one result per Silver lane switched on
    linked = store.query(f"""
        SELECT r.source_id, COUNT(q.check_name) FROM {CONTROL}.pipeline_runs AS r
        JOIN {CONTROL}.data_quality_results AS q ON q.run_id = r.job_run_id AND q.source_id = r.source_id
        WHERE r.job_run_id = 'job-run-1' AND q.layer = 'bronze' GROUP BY 1 ORDER BY 1""")
    assert [source for source, checks in linked if checks > 0] == [
        "deped_enrollment", "deped_facilities", "deped_personnel", "hdx_boundaries", "psa_poverty_stat", "psa_psgc"]
    store.close()


def test_a_second_run_changes_nothing(repo, tmp_path):
    landing = tmp_path / "landing"
    deliver(repo, landing)
    db = tmp_path / "job.duckdb"
    run_job(repo, landing, db, REVISION, log=lambda *_: None)
    results = run_job(repo, landing, db, REVISION, log=lambda *_: None)
    assert set(statuses(results).values()) == {"succeeded", "disabled"}
    store = DuckDBStore(db)
    assert store.query(f"SELECT COUNT(*) FROM {BRONZE}") == [(3,)]
    assert store.query(f"SELECT action, COUNT(*) FROM {CONTROL}.ingestion_batch_attempts GROUP BY 1 ORDER BY 1") \
        == [("load", 3), ("skip", 3)]                       # DepEd enrollment and facilities, PSA Poverty Stat
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
    assert set(results.values()) == {"succeeded", "disabled"}
    store = DuckDBStore(db)
    assert store.query(f"SELECT pipeline_name, COUNT(*) FROM {CONTROL}.pipeline_runs WHERE job_run_id = 'job-run-1' "
                       "GROUP BY 1 ORDER BY 1") == [("bronze_ingest", 6), ("silver_build", 3)]   # one filter, both layers
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
    store = DuckDBStore(db)
    assert store.query(f"SELECT check_name FROM {CONTROL}.data_quality_results WHERE run_id = 'job-run-2' "
                       "AND status = 'FAIL' ORDER BY 1") == [
        ("no_pipeline_duplicates",), ("rows_have_a_known_batch",), ("silver_lane_succeeded",),
        ("succeeded_batches_reconcile",)]
    assert store.query(f"SELECT source_id, status, actual FROM {CONTROL}.data_quality_results "
                       "WHERE run_id = 'job-run-2' AND layer = 'control' ORDER BY 1") == [
        ("deped_enrollment", "FAIL", "not run"), ("psa_poverty_stat", "PASS", "succeeded")]
    store.close()


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
