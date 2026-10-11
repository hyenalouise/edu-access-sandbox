-- Source-lane fan-in. Generated from databricks.yml and config/tables.yml:
--   python -m src.job.fan_in > etl/01_control/90_validate_control.sql
-- Do not edit by hand; tests/test_fan_in.py fails if it differs.
--
-- Runs after every source lane's Silver gate has finished, passed or not (run_if: ALL_DONE), so it
-- always records the whole job run: one result per Silver lane in data_quality_results
-- (layer 'control'). A lane passes when its silver_build run in this job run succeeded. A failed or
-- unfinished run fails, and so does a missing one: when a lane's Bronze gate failed, its Silver never
-- ran. On any FAIL the task stops, so Integration, which starts only from this task, does not run
-- (D-039). Lanes checked, the Silver gates this task waits for that are switched on:
--   deped_enrollment (90_validate_deped_enrollment_clean)
--   deped_facilities (90_validate_deped_facilities_clean)
--   psa_poverty_stat (90_validate_psa_poverty_stat_clean)
--
-- Parameters, supplied by the job (or src/job/local_run.py):
--   :run_id         the job run
--   :code_revision  the commit that ran, from the job parameter; never a literal

-- Only this execution's results decide: a repaired job run keeps its run_id.
DECLARE OR REPLACE VARIABLE control_started_at_utc TIMESTAMP;
SET VARIABLE control_started_at_utc = current_timestamp();

INSERT INTO edu_access.`01-control`.data_quality_results
  (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, CAST(NULL AS STRING), l.source_id, 'control', 'edu_access.01-control.pipeline_runs', 'silver_lane_succeeded',
       CASE WHEN r.status = 'succeeded' THEN 'PASS' ELSE 'FAIL' END,
       'succeeded', COALESCE(r.status, 'not run'), current_timestamp(), :code_revision
FROM (VALUES ('deped_enrollment'), ('deped_facilities'), ('psa_poverty_stat')) AS l(source_id)
LEFT JOIN edu_access.`01-control`.pipeline_runs AS r
  ON r.source_id = l.source_id AND r.pipeline_name = 'silver_build' AND r.run_id = :run_id;

-- Stop here if any lane did not succeed in this execution.
SELECT CASE WHEN COUNT(*) > 0
            THEN raise_error('Source-lane fan-in failed: ' || CAST(COUNT(*) AS STRING)
                             || ' Silver lane(s) did not succeed in run ' || :run_id)
       END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND layer = 'control' AND status = 'FAIL'
  AND checked_at_utc >= session.control_started_at_utc;
