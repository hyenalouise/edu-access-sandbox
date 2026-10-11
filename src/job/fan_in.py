"""The source-lane fan-in, `90_validate_control`, generated from the job (D-039).

`90_validate_control` runs after every source lane's Silver gate has finished,
passed or not (`run_if: ALL_DONE`), so it always records the whole job run. It
checks the Silver lanes that are switched on: for each, the lane passes when its
`silver_build` run in this job run succeeded. On any FAIL the task stops, so the
Integration tasks, which start only from it, do not run.

Which lanes it checks comes from two reviewed files, never typed by hand:
`databricks.yml` (the Silver gates the fan-in waits for, and which are switched
on) and `config/tables.yml` (which source each Silver gate belongs to). A Silver
pull request that switches its tasks on must regenerate the file; a test fails
until it does.

    python -m src.job.fan_in > etl/01_control/90_validate_control.sql
"""

import inspect
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(inspect.currentframe().f_code.co_filename).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.job.local_run import load_job  # noqa: E402

TASK = "90_validate_control"
PATH = "etl/01_control/90_validate_control.sql"
CONTROL = "edu_access.`01-control`"
CHECK = "silver_lane_succeeded"


class FanInError(Exception):
    pass


def silver_gates(repo_root=REPO_ROOT):
    """{Silver gate task key: source_id}, from the table registry."""
    registry = yaml.safe_load((Path(repo_root) / "config" / "tables.yml").read_text(encoding="utf-8"))
    return {Path(e["silver"]["validate_file"]).stem: e["source_id"]
            for e in registry["source_tables"] if e.get("silver", {}).get("validate_file")}


def silver_lanes(repo_root=REPO_ROOT, job=None):
    """[(source_id, Silver gate)] the fan-in checks: the Silver gates it waits for that are switched on."""
    if job is None:
        _, job = load_job(repo_root)
    tasks = {t["task_key"]: t for t in job["tasks"]}
    gates = silver_gates(repo_root)
    waits_for = [d["task_key"] for d in tasks[TASK].get("depends_on", [])]
    strays = [k for k in waits_for if k not in gates]
    if strays:
        raise FanInError(f"{TASK} waits for {strays}, which are not Silver gates in config/tables.yml.")
    missing = sorted(k for k in gates if k in tasks and k not in waits_for)
    if missing:
        raise FanInError(f"{TASK} must wait for every Silver gate in the job; it does not wait for {missing}.")
    lanes = [(gates[k], k) for k in waits_for if not tasks[k].get("disabled")]
    if not lanes:
        raise FanInError(f"{TASK} has no Silver lane switched on to check.")
    return lanes


def control_sql(lanes):
    values = ", ".join(f"('{source}')" for source, _ in lanes)
    listed = [f"--   {source} ({gate})" for source, gate in lanes]
    return "\n".join([
        "-- Source-lane fan-in. Generated from databricks.yml and config/tables.yml:",
        f"--   python -m src.job.fan_in > {PATH}",
        "-- Do not edit by hand; tests/test_fan_in.py fails if it differs.",
        "--",
        "-- Runs after every source lane's Silver gate has finished, passed or not (run_if: ALL_DONE), so it",
        "-- always records the whole job run: one result per Silver lane in data_quality_results",
        "-- (layer 'control'). A lane passes when its silver_build run in this job run succeeded. A failed or",
        "-- unfinished run fails, and so does a missing one: when a lane's Bronze gate failed, its Silver never",
        "-- ran. On any FAIL the task stops, so Integration, which starts only from this task, does not run",
        "-- (D-039). Lanes checked, the Silver gates this task waits for that are switched on:",
        *listed,
        "--",
        "-- Parameters, supplied by the job (or src/job/local_run.py):",
        "--   :run_id         the job run",
        "--   :code_revision  the commit that ran, from the job parameter; never a literal",
        "",
        "-- Only this execution's results decide: a repaired job run keeps its run_id.",
        "DECLARE OR REPLACE VARIABLE control_started_at_utc TIMESTAMP;",
        "SET VARIABLE control_started_at_utc = current_timestamp();",
        "",
        f"INSERT INTO {CONTROL}.data_quality_results",
        "  (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)",
        f"SELECT :run_id, CAST(NULL AS STRING), l.source_id, 'control', 'edu_access.01-control.pipeline_runs', '{CHECK}',",
        "       CASE WHEN r.status = 'succeeded' THEN 'PASS' ELSE 'FAIL' END,",
        "       'succeeded', COALESCE(r.status, 'not run'), current_timestamp(), :code_revision",
        f"FROM (VALUES {values}) AS l(source_id)",
        f"LEFT JOIN {CONTROL}.pipeline_runs AS r",
        "  ON r.source_id = l.source_id AND r.pipeline_name = 'silver_build' AND r.run_id = :run_id;",
        "",
        "-- Stop here if any lane did not succeed in this execution.",
        "SELECT CASE WHEN COUNT(*) > 0",
        "            THEN raise_error('Source-lane fan-in failed: ' || CAST(COUNT(*) AS STRING)",
        "                             || ' Silver lane(s) did not succeed in run ' || :run_id)",
        "       END",
        f"FROM {CONTROL}.data_quality_results",
        "WHERE run_id = :run_id AND layer = 'control' AND status = 'FAIL'",
        "  AND checked_at_utc >= session.control_started_at_utc;",
        "",
    ])


def main():
    try:
        sys.stdout.write(control_sql(silver_lanes()))
    except FanInError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
