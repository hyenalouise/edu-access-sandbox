-- Analytics gate for AP2: one row per regular LGU and facilities school year, the ratio equal to its sums,
-- the school states adding up to the active schools, coverage within 0 to 100, and rooms reconciled to the
-- classroom fact for the schools in LGUs.

DECLARE OR REPLACE VARIABLE analytics_gate_started_at_utc TIMESTAMP;
SET VARIABLE analytics_gate_started_at_utc = current_timestamp();

INSERT INTO edu_access.`01-control`.data_quality_results
  (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, CAST(NULL AS STRING), 'ap2_classroom_pressure', 'analytics', 'edu_access.06-analytics.ap2_classroom_pressure_candidate',
       check_name, status, expected, actual, current_timestamp(), :code_revision
FROM (
WITH c AS (SELECT * FROM edu_access.`06-analytics`.ap2_classroom_pressure_candidate),
s AS (
  SELECT
    (SELECT COUNT(*) FROM edu_access.`05-gold`.dim_city_municipality WHERE member_type = 'regular')
      * (SELECT COUNT(DISTINCT school_year) FROM edu_access.`05-gold`.fact_school_classroom_capacity) AS expected_rows,
    COUNT(*) AS rows_built,
    COUNT(DISTINCT city_mun_psgc_code || '/' || school_year) AS keys_built,
    COALESCE(COUNT_IF(ABS(learners_per_room - CAST(learners_in_ratio AS DOUBLE) / NULLIF(rooms_in_ratio, 0)) > 1e-9
             OR (learners_per_room IS NULL) <> (rooms_in_ratio = 0)), 0) AS bad_ratio,
    COALESCE(COUNT_IF((learners_per_room IS NULL) <> (ratio_null_reason IS NOT NULL)), 0) AS reason_mismatch,
    COALESCE(COUNT_IF(usable_schools + rooms_blank_schools + rooms_zero_schools + no_facilities_row_schools
             + incomplete_enrollment_schools <> active_public_schools), 0) AS state_mismatch,
    COALESCE(COUNT_IF(school_coverage_pct < 0 OR school_coverage_pct > 100 OR learner_coverage_pct < 0 OR learner_coverage_pct > 100), 0) AS pct_out_of_range,
    COALESCE(COUNT_IF(learners_in_ratio + learners_without_usable_rooms <> public_learners), 0) AS learner_split_mismatch,
    COALESCE(COUNT_IF(learner_coverage_pct < 90), 0) AS below_gate,
    COALESCE(COUNT_IF(learners_per_room IS NOT NULL), 0) AS lgus_with_ratio,
    SUM(rooms_blank_schools) AS rooms_blank,
    SUM(rooms_zero_schools) AS rooms_zero
  FROM c
)
SELECT 'one_row_per_lgu_and_year' AS check_name,
       CASE WHEN rows_built = expected_rows AND keys_built = rows_built THEN 'PASS' ELSE 'FAIL' END AS status,
       CAST(expected_rows AS STRING) AS expected, CAST(rows_built AS STRING) AS actual FROM s
UNION ALL SELECT 'ratio_from_sums', CASE WHEN bad_ratio = 0 AND reason_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END,
                 '0', CAST(bad_ratio + reason_mismatch AS STRING) FROM s
UNION ALL SELECT 'school_states_add_up', CASE WHEN state_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(state_mismatch AS STRING) FROM s
UNION ALL SELECT 'learner_states_add_up', CASE WHEN learner_split_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(learner_split_mismatch AS STRING) FROM s
UNION ALL SELECT 'percentages_in_range', CASE WHEN pct_out_of_range = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(pct_out_of_range AS STRING) FROM s
UNION ALL SELECT 'lgus_with_ratio', 'PASS', 'count', CAST(lgus_with_ratio AS STRING) FROM s
UNION ALL SELECT 'schools_rooms_blank', CASE WHEN rooms_blank = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(rooms_blank AS STRING) FROM s
UNION ALL SELECT 'schools_rooms_zero', CASE WHEN rooms_zero = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(rooms_zero AS STRING) FROM s
UNION ALL SELECT 'lgu_years_below_90pct_coverage', CASE WHEN below_gate = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(below_gate AS STRING) FROM s
) AS results;

MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (SELECT :run_id AS run_id, COUNT_IF(status = 'FAIL') AS fails FROM edu_access.`01-control`.data_quality_results
       WHERE run_id = :run_id AND source_id = 'ap2_classroom_pressure' AND layer = 'analytics'
         AND checked_at_utc >= session.analytics_gate_started_at_utc) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'analytics_build' AND t.source_id = 'ap2_classroom_pressure'
WHEN MATCHED AND s.fails > 0 THEN UPDATE SET status = 'failed', finished_at_utc = current_timestamp(),
  failure_stage = 'gate', error_message = CAST(s.fails AS STRING) || ' FAIL result(s) in data_quality_results';

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Analytics gate failed for ap2_classroom_pressure: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s)') END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'ap2_classroom_pressure' AND layer = 'analytics' AND status = 'FAIL'
  AND checked_at_utc >= session.analytics_gate_started_at_utc;

CREATE OR REPLACE TABLE edu_access.`06-analytics`.ap2_classroom_pressure USING DELTA AS SELECT * FROM edu_access.`06-analytics`.ap2_classroom_pressure_candidate;
ALTER TABLE edu_access.`06-analytics`.ap2_classroom_pressure OWNER TO `reached-hq`;

MERGE INTO edu_access.`01-control`.pipeline_runs AS t USING (SELECT :run_id AS run_id) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'analytics_build' AND t.source_id = 'ap2_classroom_pressure'
WHEN MATCHED THEN UPDATE SET status = 'succeeded', finished_at_utc = current_timestamp(), failure_stage = NULL, error_message = NULL;
