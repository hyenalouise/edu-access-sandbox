-- D-065 publication gate for the suspected extreme school ratios.
DECLARE OR REPLACE VARIABLE analytics_gate_started_at_utc TIMESTAMP;
SET VARIABLE analytics_gate_started_at_utc = current_timestamp();
DECLARE OR REPLACE VARIABLE analytics_gate_summary STRING;
SET VARIABLE analytics_gate_summary = '`edu_access`.`06-analytics`.`school_outlier_flags_gate_summary_r_' || sha2(:run_id, 256) || '`';
DECLARE OR REPLACE VARIABLE analytics_gate_owner_sql STRING;

CREATE OR REPLACE TABLE IDENTIFIER(session.analytics_gate_summary) USING DELTA COMMENT 'Internal unpublished one-row summary for one D-065 gate.' AS
WITH c AS (SELECT * FROM edu_access.`06-analytics`.school_outlier_flags_candidate),
regular AS (SELECT city_mun_psgc_code FROM edu_access.`05-gold`.dim_city_municipality WHERE member_type = 'regular'),
enrollment AS (
  SELECT school_id, city_mun_psgc_code,
         MAX(CASE WHEN is_offered AND learner_count > 0 THEN 1 ELSE 0 END) AS is_active,
         COUNT_IF(is_offered AND learner_count IS NULL) AS incomplete_levels,
         COUNT_IF(is_offered) > 0 AND COUNT_IF(is_offered AND learner_count IS NOT NULL) = 0 AS is_blank
  FROM edu_access.`05-gold`.fact_school_enrollment
  WHERE school_year = '2023-24' AND sector = 'Public' AND psgc_match_status = 'matched'
  GROUP BY school_id, city_mun_psgc_code
),
-- the two ratio populations, counted again from Gold
expected_classroom AS (
  SELECT COUNT(*) AS n FROM enrollment AS e
  JOIN regular AS r ON r.city_mun_psgc_code = e.city_mun_psgc_code
  JOIN edu_access.`05-gold`.fact_school_classroom_capacity AS k ON k.school_id = e.school_id AND k.school_year = '2023-24'
  WHERE e.is_active = 1 AND e.incomplete_levels = 0 AND k.instructional_classrooms_total > 0
),
expected_teacher AS (
  SELECT COUNT(*) AS n FROM edu_access.`05-gold`.fact_school_enrollment AS f
  JOIN enrollment AS e ON e.school_id = f.school_id AND (e.is_active = 1 OR e.is_blank)
  JOIN regular AS r ON r.city_mun_psgc_code = f.city_mun_psgc_code
  JOIN edu_access.`05-gold`.fact_school_teacher_capacity AS t
    ON t.school_id = f.school_id AND t.school_year = f.school_year AND t.education_level_code = f.education_level_code
  WHERE f.school_year = '2023-24' AND f.sector = 'Public' AND f.psgc_match_status = 'matched' AND f.is_offered
    AND f.learner_count IS NOT NULL AND t.teacher_count > 0
),
-- quartiles and fences recomputed from the candidate's own ratios
groups AS (
  SELECT measure, education_level_code, lgu_type, COUNT(*) AS n,
         percentile_cont(0.25) WITHIN GROUP (ORDER BY ratio) AS q1,
         percentile_cont(0.75) WITHIN GROUP (ORDER BY ratio) AS q3
  FROM c GROUP BY measure, education_level_code, lgu_type
)
SELECT
  (SELECT COUNT(*) FROM c) AS rows,
  (SELECT n FROM expected_classroom) + (SELECT n FROM expected_teacher) AS expected_rows,
  (SELECT COUNT(*) - COUNT(DISTINCT school_id || '|' || measure || '|' || education_level_code) FROM c) AS duplicate_keys,
  COALESCE((SELECT COUNT_IF(measure NOT IN ('classroom', 'teacher')
                   OR (measure = 'classroom' AND education_level_code <> 'ALL')
                   OR (measure = 'teacher' AND education_level_code NOT IN ('ES', 'JHS', 'SHS'))
                   OR denominator <= 0 OR learners IS NULL
                   OR abs(ratio - CAST(learners AS DOUBLE) / denominator) > 1e-9) FROM c), 0) AS invalid_rows,
  (SELECT COUNT(*) FROM c JOIN groups AS g USING (measure, education_level_code, lgu_type)
    WHERE c.fence_group_size <> g.n OR abs(c.q1 - g.q1) > 1e-9 OR abs(c.q3 - g.q3) > 1e-9
       OR (g.n >= 10 AND (abs(c.upper_outer_fence - (g.q3 + 3 * (g.q3 - g.q1))) > 1e-9
                          OR abs(c.lower_outer_fence - (g.q1 - 3 * (g.q3 - g.q1))) > 1e-9))
       OR (g.n < 10 AND (c.upper_outer_fence IS NOT NULL OR c.lower_outer_fence IS NOT NULL))) AS fence_mismatch,
  COALESCE((SELECT COUNT_IF(is_above_upper_fence IS DISTINCT FROM COALESCE(ratio > upper_outer_fence, FALSE)
                   OR is_below_lower_fence IS DISTINCT FROM COALESCE(ratio < lower_outer_fence, FALSE)
                   OR is_suspected_outlier IS DISTINCT FROM
                      CASE WHEN measure = 'classroom' THEN is_above_upper_fence
                           ELSE is_above_upper_fence OR is_below_lower_fence END) FROM c), 0) AS flag_mismatch,
  (SELECT COUNT(DISTINCT school_id) FROM c WHERE is_suspected_outlier) AS outlier_schools,
  COALESCE((SELECT COUNT_IF(is_suspected_outlier AND measure = 'classroom') FROM c), 0) AS classroom_outlier_schools,
  COALESCE((SELECT COUNT_IF(is_suspected_outlier AND measure = 'teacher') FROM c), 0) AS outlier_school_levels;
SET VARIABLE analytics_gate_owner_sql = 'ALTER TABLE ' || session.analytics_gate_summary || ' OWNER TO `reached-hq`';
EXECUTE IMMEDIATE analytics_gate_owner_sql;

INSERT INTO edu_access.`01-control`.data_quality_results
  (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, NULL, 'school_outlier_flags', 'analytics', 'edu_access.06-analytics.school_outlier_flags_candidate',
       check_name, status, expected, actual, current_timestamp(), :code_revision
FROM (
  SELECT 'rows_match_ratio_schools' AS check_name, CASE WHEN rows = expected_rows THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(expected_rows AS STRING) AS expected, CAST(rows AS STRING) AS actual FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'key_unique', CASE WHEN duplicate_keys = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(duplicate_keys AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'ratio_rows_valid', CASE WHEN invalid_rows = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(invalid_rows AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'outer_fences_recomputed', CASE WHEN fence_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(fence_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'outlier_flags_follow_fences', CASE WHEN flag_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(flag_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  -- counts, never a failure: an unusual ratio is not an error (D-065)
  UNION ALL SELECT 'outlier_schools', CASE WHEN outlier_schools = 0 THEN 'PASS' ELSE 'WARN' END, NULL, CAST(outlier_schools AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'classroom_outlier_schools', 'PASS', NULL, CAST(classroom_outlier_schools AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'outlier_school_levels', 'PASS', NULL, CAST(outlier_school_levels AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
) AS checks;

DROP TABLE IF EXISTS IDENTIFIER(session.analytics_gate_summary);

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Analytics gate failed for school_outlier_flags: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s)') ELSE 1 END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'school_outlier_flags' AND layer = 'analytics' AND status = 'FAIL'
  AND checked_at_utc >= session.analytics_gate_started_at_utc;

CREATE OR REPLACE TABLE edu_access.`06-analytics`.school_outlier_flags USING DELTA AS
SELECT * FROM edu_access.`06-analytics`.school_outlier_flags_candidate;
COMMENT ON TABLE edu_access.`06-analytics`.school_outlier_flags IS 'Every public school ratio in AP2 and AP3 with its Tukey outer fences and suspected-outlier flag under D-065, a quality result and never a correction.';
ALTER TABLE edu_access.`06-analytics`.school_outlier_flags OWNER TO `reached-hq`;
