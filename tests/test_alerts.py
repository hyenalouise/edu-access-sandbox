"""The SQL alerts in databricks.yml: which control rows each one reports (D-043).

Each alert's query_text is run as committed, on DuckDB, against made-up
data_quality_results rows. An alert triggers when its query returns any row, so
what the query returns is what the team is told.
"""

from datetime import datetime, timedelta

import pytest
import yaml

from factories.deped_deliveries import REPO_ROOT
from src.ingestion.store import DuckDBStore

CONTROL = "edu_access.`01-control`"
DEPLOYER = "${workspace.current_user.userName}"
T0 = datetime(2026, 10, 13, 1, 0)


@pytest.fixture(scope="module")
def alerts():
    bundle = yaml.safe_load((REPO_ROOT / "databricks.yml").read_text(encoding="utf-8"))
    return bundle["resources"]["alerts"]


@pytest.fixture
def store():
    s = DuckDBStore()
    for name in ("01_create_pipeline_runs", "04_create_data_quality_results"):
        s.run_file(REPO_ROOT / "etl" / "01_control" / f"{name}.sql")
    yield s
    s.close()


def result(store, run_id, check_name, status, minutes, source_id="deped_enrollment", layer="bronze",
           table_name="edu_access.02-bronze.deped_enrollment_raw", batch_id="b1"):
    store.sql(
        f"INSERT INTO {CONTROL}.data_quality_results (run_id, batch_id, source_id, layer, table_name, check_name, "
        "status, expected, actual, checked_at_utc, code_revision) "
        "VALUES (:run_id, :batch_id, :source_id, :layer, :table_name, :check_name, :status, 'e', 'a', :at, 'r')",
        {"run_id": run_id, "batch_id": batch_id, "source_id": source_id, "layer": layer, "table_name": table_name,
         "check_name": check_name, "status": status, "at": T0 + timedelta(minutes=minutes)})


def reported(store, alerts, key):
    return store.records(alerts[key]["query_text"])


def test_both_alerts_exist_and_email_the_deployer(alerts):
    assert set(alerts) == {"quality_failures", "stale_sources"}
    for key, alert in alerts.items():
        assert alert["warehouse_id"] == "${var.warehouse_id}"
        notification = alert["evaluation"]["notification"]
        assert notification["subscriptions"] == [{"user_email": DEPLOYER}], f"{key}: must email the deployer"
        assert notification["notify_on_ok"] is True, f"{key}: say when it is fixed, too"
        assert alert["evaluation"]["empty_result_state"] == "OK"
        assert alert["schedule"]["quartz_cron_schedule"] == "${var.alert_schedule}"
        assert "{{QUERY_RESULT_TABLE}}" in alert["custom_description"], f"{key}: the email must list the rows"


def test_each_alert_counts_a_column_its_query_returns(store, alerts):
    """A misspelled source column makes the alert error on Databricks instead of triggering."""
    result(store, "run-1", "rows_reconcile", "FAIL", 0)
    result(store, "run-1", "source_fresh", "WARN", 1, layer="control")
    for key, alert in alerts.items():
        evaluation = alert["evaluation"]
        assert evaluation["source"]["aggregation"] == "COUNT"
        assert evaluation["comparison_operator"] == "GREATER_THAN"
        assert evaluation["threshold"]["value"]["double_value"] == 0
        rows = reported(store, alerts, key)
        assert rows and evaluation["source"]["name"] in rows[0], f"{key}: returns no {evaluation['source']['name']}"


def test_quality_failures_reports_the_fails_of_the_latest_run_only(store, alerts):
    result(store, "run-1", "rows_reconcile", "FAIL", 0)
    result(store, "run-2", "rows_reconcile", "PASS", 60)
    result(store, "run-2", "no_duplicates", "WARN", 60)
    assert reported(store, alerts, "quality_failures") == []
    result(store, "run-3", "rows_reconcile", "FAIL", 120)
    result(store, "run-3", "silver_lane_succeeded", "FAIL", 121, layer="control", source_id="psa_psgc",
           table_name="edu_access.01-control.pipeline_runs", batch_id=None)
    rows = reported(store, alerts, "quality_failures")
    assert [(r["run_id"], r["layer"], r["check_name"]) for r in rows] == [
        ("run-3", "bronze", "rows_reconcile"), ("run-3", "control", "silver_lane_succeeded")]


def test_a_check_rerun_in_a_repaired_run_replaces_its_fail(store, alerts):
    """A repaired job run keeps its run_id; the gate's rerun writes a new, later result."""
    result(store, "run-1", "rows_reconcile", "FAIL", 0)
    result(store, "run-1", "rows_reconcile", "PASS", 30)
    assert reported(store, alerts, "quality_failures") == []


def test_fails_written_together_are_all_reported(store, alerts):
    """One gate statement stamps its rows with the same time; RANK keeps every one."""
    for batch in ("b1", "b2"):
        result(store, "run-1", "rows_reconcile", "FAIL", 0, batch_id=batch)
    result(store, "run-1", "rows_reconcile", "FAIL", 0, batch_id="b1", table_name="edu_access.02-bronze.other_raw")
    assert len(reported(store, alerts, "quality_failures")) == 3


def test_stale_sources_reports_the_warns_of_the_latest_freshness_check(store, alerts):
    result(store, "run-1", "source_fresh", "WARN", 0, layer="control", source_id="psa_psgc")
    result(store, "run-1", "source_fresh", "PASS", 0, layer="control", source_id="deped_enrollment")
    rows = reported(store, alerts, "stale_sources")
    assert [(r["run_id"], r["source_id"]) for r in rows] == [("run-1", "psa_psgc")]
    result(store, "run-2", "source_fresh", "PASS", 60, layer="control", source_id="psa_psgc")
    result(store, "run-2", "source_fresh", "PASS", 60, layer="control", source_id="deped_enrollment")
    assert reported(store, alerts, "stale_sources") == []


def test_a_later_run_that_skipped_the_freshness_check_does_not_hide_a_stale_source(store, alerts):
    result(store, "run-1", "source_fresh", "WARN", 0, layer="control", source_id="psa_psgc")
    result(store, "run-2", "rows_reconcile", "PASS", 60)
    assert [r["source_id"] for r in reported(store, alerts, "stale_sources")] == ["psa_psgc"]


def test_stale_sources_ignores_other_warns(store, alerts):
    result(store, "run-1", "source_fresh", "PASS", 0, layer="control")
    result(store, "run-1", "no_duplicates", "WARN", 0)
    assert reported(store, alerts, "stale_sources") == []
