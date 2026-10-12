"""The source-lane fan-in, 90_validate_control: generated from the job, checking every Silver lane that is on.

The committed SQL must equal what src/job/fan_in.py writes from databricks.yml and
config/tables.yml, so a Silver lane switched on in the job is always checked, and
none can drop out unnoticed (D-039). How the task behaves in a run is tested in
tests/test_local_job.py.
"""

import copy

import pytest

from factories.deped_deliveries import REPO_ROOT
from src.job import fan_in
from src.job.local_run import load_job


def job():
    return copy.deepcopy(load_job(REPO_ROOT)[1])


def task(job, key):
    return next(t for t in job["tasks"] if t["task_key"] == key)


def test_committed_fan_in_matches_the_generator():
    path = REPO_ROOT / fan_in.PATH
    assert path.read_text(encoding="utf-8") == fan_in.control_sql(fan_in.silver_lanes(REPO_ROOT)), (
        f"Regenerate: python -m src.job.fan_in > {fan_in.PATH}")


def test_the_lanes_are_exactly_the_silver_gates_switched_on():
    j = job()
    gates = fan_in.silver_gates(REPO_ROOT)
    on = {gates[t["task_key"]] for t in j["tasks"] if t["task_key"] in gates and not t.get("disabled")}
    assert {source for source, _ in fan_in.silver_lanes(REPO_ROOT, j)} == on
    assert on, "no Silver lane is switched on"


def test_switching_a_silver_lane_on_adds_it():
    j = job()
    gates = fan_in.silver_gates(REPO_ROOT)
    gate = next(iter(gates))
    task(j, gate)["disabled"] = True
    assert gates[gate] not in {source for source, _ in fan_in.silver_lanes(REPO_ROOT, j)}
    task(j, gate)["disabled"] = False
    assert gates[gate] in {source for source, _ in fan_in.silver_lanes(REPO_ROOT, j)}


@pytest.mark.parametrize("break_it, message", [
    (lambda j: task(j, "90_validate_control")["depends_on"].append({"task_key": "05_create_current_batches"}),
     "not Silver gates"),
    (lambda j: task(j, "90_validate_control")["depends_on"].pop(0), "must wait for every Silver gate"),
])
def test_the_generator_refuses_a_fan_in_that_misses_or_adds_a_lane(break_it, message):
    j = job()
    break_it(j)
    with pytest.raises(fan_in.FanInError, match=message):
        fan_in.silver_lanes(REPO_ROOT, j)


def test_the_fan_in_only_records_and_stops():
    sql = fan_in.control_sql(fan_in.silver_lanes(REPO_ROOT))
    assert "raise_error(" in sql and "CREATE OR REPLACE" not in sql and "MERGE" not in sql
    assert sql.index("INSERT INTO") < sql.index("raise_error(")
