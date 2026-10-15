"""The source freshness check, 90_validate_freshness: generated from the job, one result per loaded source.

The committed SQL must equal what src/job/freshness.py writes from databricks.yml and
config/freshness.yml, so every source the job loads has a reviewed limit and none can
drop out unnoticed (D-043). The SQL itself is run on DuckDB against made-up batches.
"""

import copy
from datetime import datetime, timezone

import pytest

from factories.deped_deliveries import REPO_ROOT
from src.ingestion.store import DuckDBStore
from src.job import freshness
from src.job.local_run import load_job

CONTROL = "edu_access.`01-control`"
REVISION = "f" * 40


def job():
    return copy.deepcopy(load_job(REPO_ROOT)[1])


def task(job, key):
    return next(t for t in job["tasks"] if t["task_key"] == key)


def test_committed_check_matches_the_generator():
    path = REPO_ROOT / freshness.PATH
    assert path.read_text(encoding="utf-8") == freshness.freshness_sql(freshness.limits(REPO_ROOT)), (
        f"Regenerate: python -m src.job.freshness > {freshness.PATH}")


def test_every_loaded_source_has_a_limit():
    j = job()
    assert [source for source, _, _ in freshness.limits(REPO_ROOT, j)] == freshness.loaded_sources(j)
    assert freshness.loaded_sources(j), "the job loads no source"


def test_a_switched_off_load_is_not_checked():
    j = job()
    load = next(t for t in j["tasks"] if t.get("spark_python_task", {}).get("parameters", [""])[0] == "ingest")
    load["disabled"] = True
    source = load["spark_python_task"]["parameters"][load["spark_python_task"]["parameters"].index("--source") + 1]
    assert source not in freshness.loaded_sources(j)


def enrollment_only_job():
    """The job with every Bronze load but enrollment's switched off."""
    j = job()
    for t in j["tasks"]:
        args = t.get("spark_python_task", {}).get("parameters", [])
        if args[:1] == ["ingest"] and args[args.index("--source") + 1] != "deped_enrollment":
            t["disabled"] = True
    return j


@pytest.mark.parametrize("config, message", [
    ("deped_enrollment: {max_age_days: 400, basis: Annual}\n"
     "osm_philippines: {max_age_days: 30, basis: Weekly}\n", "which the job does not load"),
    ("deped_enrollment: {max_age_days: 0, basis: Annual}\n", "positive whole number"),
    ("deped_enrollment: {max_age_days: 400.5, basis: Annual}\n", "positive whole number"),
    ("deped_enrollment: {max_age_days: 400}\n", "give the basis"),
    ("psa_psgc: {max_age_days: 120, basis: Quarterly}\n", "has no limit for"),
])
def test_the_generator_refuses_a_missing_stray_or_bad_limit(tmp_path, config, message):
    (tmp_path / "config").mkdir()
    indented = "".join(f"  {line}\n" for line in config.splitlines())
    (tmp_path / "config" / "freshness.yml").write_text("sources:\n" + indented, encoding="utf-8")
    with pytest.raises(freshness.FreshnessError, match=message):
        freshness.limits(tmp_path, enrollment_only_job())


def test_the_check_only_records():
    sql = freshness.freshness_sql(freshness.limits(REPO_ROOT))
    assert "raise_error(" not in sql and "CREATE OR REPLACE" not in sql and "MERGE" not in sql
    assert "'FAIL'" not in sql, "a stale source is a WARN, never a FAIL"


@pytest.fixture
def store():
    s = DuckDBStore()
    for name in ("01_create_pipeline_runs", "02_create_ingestion_batches", "03_create_ingestion_batch_attempts",
                 "04_create_data_quality_results", "05_create_current_batches"):
        s.run_file(REPO_ROOT / "etl" / "01_control" / f"{name}.sql")
    yield s
    s.close()


def add_batch(store, source_id, succeeded_at, status="succeeded", period="2024-25"):
    store.sql(
        f"INSERT INTO {CONTROL}.ingestion_batches (batch_id, source_id, school_year, delivery_version, status, "
        "archive_path, archive_name, archive_sha256, attempt_count, first_run_id, last_run_id, "
        "first_attempt_at_utc, last_attempt_at_utc, succeeded_at_utc, environment, code_revision) "
        "VALUES (:batch_id, :source_id, :period, 1, :status, 'a.zip', 'a.zip', :sha, 1, 'r0', 'r0', "
        ":at, :at, :succeeded, 'local', :revision)",
        {"batch_id": f"{source_id}__{period}", "source_id": source_id, "period": period, "status": status,
         "sha": f"{source_id}{period}", "at": succeeded_at,
         "succeeded": succeeded_at if status == "succeeded" else None, "revision": REVISION})


def check(store, as_of, rows=None):
    sql = freshness.freshness_sql(rows or [("deped_enrollment", 400, "Annual"), ("psa_psgc", 120, "Quarterly")])
    path = store._tmp.name + "/freshness.sql"
    with open(path, "w", encoding="utf-8") as f:
        f.write(sql)
    store.run_file(path, {"run_id": "run-1", "code_revision": REVISION, "freshness_as_of": as_of})
    return {r["source_id"]: r for r in store.records(
        f"SELECT source_id, layer, check_name, status, expected, actual, code_revision "
        f"FROM {CONTROL}.data_quality_results WHERE run_id = 'run-1'")}


def test_a_source_within_its_limit_passes_and_an_older_one_warns(store):
    add_batch(store, "deped_enrollment", datetime(2026, 10, 6, 3, 0))
    add_batch(store, "psa_psgc", datetime(2026, 6, 1, 3, 0), period="2026-Q2")
    results = check(store, "2026-10-13 00:00:00")
    assert results["deped_enrollment"]["status"] == "PASS"
    assert results["psa_psgc"]["status"] == "WARN"
    assert results["psa_psgc"]["expected"] == "succeeded within 120 days of 2026-10-13"
    assert results["psa_psgc"]["actual"] == "last succeeded 2026-06-01"
    assert {(r["layer"], r["check_name"], r["code_revision"]) for r in results.values()} == {
        ("control", "source_fresh", REVISION)}


def test_the_limit_is_inclusive_to_the_day(store):
    add_batch(store, "deped_enrollment", datetime(2025, 9, 8, 0, 0))  # exactly 400 days before
    add_batch(store, "psa_psgc", datetime(2026, 6, 15, 0, 0), period="2026-Q2")  # exactly 120 days before
    results = check(store, "2026-10-13 00:00:00")
    assert results["deped_enrollment"]["status"] == "PASS"
    assert results["psa_psgc"]["status"] == "PASS"


def test_a_source_with_no_succeeded_batch_warns(store):
    add_batch(store, "deped_enrollment", datetime(2026, 10, 6), status="failed")
    results = check(store, "2026-10-13 00:00:00")
    assert results["deped_enrollment"]["status"] == "WARN"
    assert results["deped_enrollment"]["actual"] == "no succeeded batch"


def test_the_latest_batch_decides(store):
    add_batch(store, "deped_enrollment", datetime(2024, 1, 1), period="2023-24")
    add_batch(store, "deped_enrollment", datetime(2026, 10, 6), period="2024-25")
    assert check(store, "2026-10-13 00:00:00")["deped_enrollment"]["status"] == "PASS"


def test_blank_checks_as_of_now(store):
    add_batch(store, "deped_enrollment", datetime.now(timezone.utc).replace(tzinfo=None))
    assert check(store, "")["deped_enrollment"]["status"] == "PASS"


def test_a_later_as_of_makes_every_source_stale(store):
    """How the stale-source alert is tested on Databricks without changing any data."""
    add_batch(store, "deped_enrollment", datetime(2026, 10, 6))
    add_batch(store, "psa_psgc", datetime(2026, 10, 6), period="2026-Q2")
    assert {r["status"] for r in check(store, "2030-01-01 00:00:00").values()} == {"WARN"}


def test_text_that_is_not_a_timestamp_fails(store):
    with pytest.raises(Exception, match="(?i)timestamp"):
        check(store, "next tuesday")
