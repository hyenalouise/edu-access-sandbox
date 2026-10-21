# Failure recovery and downstream rerun, local

## Scope

- Issue: #101
- Environment: local DuckDB only
- Data: made-up test deliveries, no repository or production data
- Command: `python -m pytest tests/test_local_job.py::test_a_gate_code_bug_is_fixed_and_recovered_by_rerun tests/test_local_job.py::test_a_second_run_changes_nothing tests/test_local_job.py::test_a_failing_gate_fails_its_task_and_an_independent_source_still_runs tests/test_local_job.py::test_a_failed_lane_stops_only_the_tasks_that_read_it tests/test_silver_hdx.py::test_a_rerun_builds_the_same_rows tests/test_gold_fact_school_enrollment.py::test_rerun_gives_the_same_table -q`
- Commit: the commit that adds this version of the record, on top of `dd5441e` (the first version of the rehearsal)

## Rehearsed failure

The local job test deliberately injects a made-up code bug into the DepEd enrollment Bronze gate after first publishing a good complete job build.

1. **Detect:** `90_validate_deped_enrollment_raw` returns failed and the whole local job exits nonzero.
2. **Diagnose:** `data_quality_results` records `made_up_code_bug` as FAIL for the enrollment lane and identifies the run, source, table, expected state, actual state, and code revision.
3. **Impact:** the failed lane's Silver task and every downstream task that depends on it, such as `10_build_fact_school_enrollment`, are `upstream_failed`, while an independent lane (`90_validate_psa_psgc_clean`) still succeeds. Every published Silver, Integration, Gold, and Analytics table (38 in the made-up job) is unchanged, comparing every column except `run_id`, `code_revision`, and the `*_at_utc` timestamps.
4. **Recover:** the gate is restored to its reviewed implementation, as a new commit (code revision `eeee…`), and the job is started as a new run (`job-run-3`), not a repair of the failed one (D-020). It runs against the same isolated database. No control row, raw row, or published table is manually edited.
5. **Verify:** the new run succeeds with zero FAIL results, every check it records carries the fixed commit as `code_revision`, and all 38 published tables equal the initial good run.

This behavior is asserted by `test_a_gate_code_bug_is_fixed_and_recovered_by_rerun`.

## Same-input rerun at Silver and Gold

The recovered run in `test_a_gate_code_bug_is_fixed_and_recovered_by_rerun` is a same-input rerun of the whole job: its Bronze deliveries all skip, and it rebuilds every enabled Silver, Integration, Gold, and Analytics table, whose contents equal the first run's.

`test_a_second_run_changes_nothing` runs the complete enabled job twice against the same made-up deliveries and database. The second run succeeds, all eight Bronze deliveries are recorded as `skip`, and Bronze remains at three enrollment rows. It checks task statuses and Bronze, not Silver or Gold contents.

The layer-specific deterministic rebuild tests add direct checks of published contents:

- Silver: `tests/test_silver_hdx.py::test_a_rerun_builds_the_same_rows` rebuilds from the same current Bronze inputs and compares the published rows after both runs.
- Gold enrollment: `tests/test_gold_fact_school_enrollment.py::test_rerun_gives_the_same_table` rebuilds and validates the fact twice, then compares the full published table.
- Gold: `dim_barangay`, `dim_city_municipality`, `dim_city_poverty`, `fact_city_population`, and `fact_city_school_age_population` have the same kind of rerun test in their `tests/test_gold_*.py` modules. The other Gold tables and Analytics are covered by the whole-job comparison above.

On Databricks `dev`, the whole job ran twice from source to Gold at `7542cc0` with identical gate results: [2026-10-20 Gold on dev](2026-10-20-gold-databricks-dev.md).

## Result

- Focused result at `dd5441e` (first version of the rehearsal, four tests): 4 passed in 118.61 seconds.
- Focused result with the whole-job comparison (six tests above): 6 passed in 223.19 seconds.

- Observed: the failure is detected by a gate and contained to its dependency path.
- Observed: recovery uses the same idempotent job path, without manual table edits.
- Observed: the same current input produces the same published Silver, Integration, Gold, and Analytics content on rerun.
- Not tested here: Databricks-specific capacity timeout behavior or a `prod` recovery. The repository has no `prod` target until #99 is completed.
