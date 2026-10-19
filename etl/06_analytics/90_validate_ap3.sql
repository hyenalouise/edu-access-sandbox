-- Analytics gate for AP3: one row per regular LGU, personnel school year and level, the ratio equal to its
-- sums, school and learner states adding up, funding within the teacher total, and coverage within 0 to 100.

DECLARE OR REPLACE VARIABLE analytics_gate_started_at_utc TIMESTAMP;
SET VARIABLE analytics_gate_started_at_utc = current_timestamp();

INSERT INTO edu_access.`01-control`.data_quality_results
  (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, CAST(NULL AS STRING), 'ap3_teacher_pressure', 'analytics', 'edu_access.06-analytics.ap3_teacher_pressure_candidate',
       check_name, status, expected, actual, current_timestamp(), :code_revision
FROM (
WITH c AS (SELECT * FROM edu_access.`06-analytics`.ap3_teacher_pressure_candidate),
s AS (
  SELECT
    (SELECT COUNT(*) FROM edu_access.`05-gold`.dim_city_municipality WHERE member_type = 'regular')
      * (SELECT COUNT(DISTINCT school_year) FROM edu_access.`05-gold`.fact_school_teacher_capacity) * 3 AS expected_rows,
    COUNT(*) AS rows_built,
    COUNT(DISTINCT city_mun_psgc_code || '/' || school_year || '/' || education_level_code) AS keys_built,
    COALESCE(COUNT_IF(ABS(learners_per_teacher - CAST(learners_in_ratio AS DOUBLE) / NULLIF(teachers_in_ratio, 0)) > 1e-9
             OR (learners_per_teacher IS NULL) <> (teachers_in_ratio = 0)), 0) AS bad_ratio,
    COALESCE(COUNT_IF((learners_per_teacher IS NULL) <> (ratio_null_reason IS NOT NULL)), 0) AS reason_mismatch,
    COALESCE(COUNT_IF(usable_schools + zero_teacher_annex_schools + zero_teacher_schools + teachers_blank_schools
             + no_personnel_row_schools + incomplete_enrollment_schools <> schools_in_scope), 0) AS state_mismatch,
    COALESCE(COUNT_IF(learners_in_ratio + learners_without_teachers <> level_learners), 0) AS learner_split_mismatch,
    COALESCE(COUNT_IF(sef_provincial_teachers + sef_city_municipal_teachers + lgu_funded_teachers + other_funded_teachers > teachers_in_ratio), 0) AS funding_above_total,
    COALESCE(COUNT_IF(school_coverage_pct < 0 OR school_coverage_pct > 100 OR learner_coverage_pct < 0 OR learner_coverage_pct > 100), 0) AS pct_out_of_range,
    COALESCE(COUNT_IF(learner_coverage_pct < 90), 0) AS below_gate,
    SUM(zero_teacher_annex_schools) AS zero_teacher_annexes,
    SUM(zero_teacher_annex_learners) AS zero_teacher_annex_learners,
    SUM(zero_teacher_schools) AS zero_teacher_schools,
    SUM(teachers_in_ratio) AS teachers
  FROM c
)
SELECT 'one_row_per_lgu_year_and_level' AS check_name,
       CASE WHEN rows_built = expected_rows AND keys_built = rows_built THEN 'PASS' ELSE 'FAIL' END AS status,
       CAST(expected_rows AS STRING) AS expected, CAST(rows_built AS STRING) AS actual FROM s
UNION ALL SELECT 'ratio_from_sums', CASE WHEN bad_ratio = 0 AND reason_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END,
                 '0', CAST(bad_ratio + reason_mismatch AS STRING) FROM s
UNION ALL SELECT 'school_states_add_up', CASE WHEN state_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(state_mismatch AS STRING) FROM s
UNION ALL SELECT 'learner_states_add_up', CASE WHEN learner_split_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(learner_split_mismatch AS STRING) FROM s
UNION ALL SELECT 'funding_within_teachers', CASE WHEN funding_above_total = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(funding_above_total AS STRING) FROM s
UNION ALL SELECT 'percentages_in_range', CASE WHEN pct_out_of_range = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(pct_out_of_range AS STRING) FROM s
UNION ALL SELECT 'teachers_in_lgu_ratios', 'PASS', 'count', CAST(teachers AS STRING) FROM s
UNION ALL SELECT 'zero_teacher_annexes_kept', 'PASS', 'schools / learners',
                 CAST(zero_teacher_annexes AS STRING) || ' / ' || CAST(zero_teacher_annex_learners AS STRING) FROM s
UNION ALL SELECT 'zero_teacher_schools', CASE WHEN zero_teacher_schools = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(zero_teacher_schools AS STRING) FROM s
UNION ALL SELECT 'lgu_levels_below_90pct_coverage', CASE WHEN below_gate = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(below_gate AS STRING) FROM s
) AS results;

MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (SELECT :run_id AS run_id, COUNT_IF(status = 'FAIL') AS fails FROM edu_access.`01-control`.data_quality_results
       WHERE run_id = :run_id AND source_id = 'ap3_teacher_pressure' AND layer = 'analytics'
         AND checked_at_utc >= session.analytics_gate_started_at_utc) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'analytics_build' AND t.source_id = 'ap3_teacher_pressure'
WHEN MATCHED AND s.fails > 0 THEN UPDATE SET status = 'failed', finished_at_utc = current_timestamp(),
  failure_stage = 'gate', error_message = CAST(s.fails AS STRING) || ' FAIL result(s) in data_quality_results';

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Analytics gate failed for ap3_teacher_pressure: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s)') END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'ap3_teacher_pressure' AND layer = 'analytics' AND status = 'FAIL'
  AND checked_at_utc >= session.analytics_gate_started_at_utc;

CREATE OR REPLACE TABLE edu_access.`06-analytics`.ap3_teacher_pressure USING DELTA AS SELECT * FROM edu_access.`06-analytics`.ap3_teacher_pressure_candidate;
ALTER TABLE edu_access.`06-analytics`.ap3_teacher_pressure OWNER TO `reached-hq`;

MERGE INTO edu_access.`01-control`.pipeline_runs AS t USING (SELECT :run_id AS run_id) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'analytics_build' AND t.source_id = 'ap3_teacher_pressure'
WHEN MATCHED THEN UPDATE SET status = 'succeeded', finished_at_utc = current_timestamp(), failure_stage = NULL, error_message = NULL;
