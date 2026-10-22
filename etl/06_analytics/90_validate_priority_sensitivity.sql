-- D-065 publication gate for the outlier sensitivity of the planning priority.
DECLARE OR REPLACE VARIABLE analytics_gate_started_at_utc TIMESTAMP;
SET VARIABLE analytics_gate_started_at_utc = current_timestamp();
DECLARE OR REPLACE VARIABLE analytics_gate_summary STRING;
SET VARIABLE analytics_gate_summary = '`edu_access`.`06-analytics`.`lgu_priority_sensitivity_gate_summary_r_' || sha2(:run_id, 256) || '`';
DECLARE OR REPLACE VARIABLE analytics_gate_owner_sql STRING;

CREATE OR REPLACE TABLE IDENTIFIER(session.analytics_gate_summary) USING DELTA COMMENT 'Internal unpublished one-row summary for one D-065 gate.' AS
WITH c AS (SELECT * FROM edu_access.`06-analytics`.lgu_priority_sensitivity_candidate),
m AS (SELECT * FROM edu_access.`06-analytics`.lgu_priority_matrix),
regular AS (SELECT city_mun_psgc_code FROM edu_access.`05-gold`.dim_city_municipality WHERE member_type = 'regular'),
flagged AS (
  SELECT city_mun_psgc_code, COUNT(DISTINCT school_id) AS n
  FROM edu_access.`06-analytics`.school_outlier_flags WHERE is_suspected_outlier GROUP BY city_mun_psgc_code
)
SELECT
  (SELECT COUNT(*) FROM c) AS rows,
  (SELECT COUNT(*) FROM regular) AS expected_rows,
  (SELECT COUNT(*) - COUNT(DISTINCT city_mun_psgc_code) FROM c) AS duplicate_keys,
  (SELECT COUNT(*) FROM regular AS r FULL OUTER JOIN c USING (city_mun_psgc_code)
    WHERE r.city_mun_psgc_code IS NULL OR c.city_mun_psgc_code IS NULL) AS lgu_mismatch,
  -- scenario A is the published matrix, unchanged
  (SELECT COUNT(*) FROM c JOIN m USING (city_mun_psgc_code)
    WHERE c.priority_category IS DISTINCT FROM m.priority_category OR c.priority_order IS DISTINCT FROM m.priority_order
       OR c.classroom_pressure_flag IS DISTINCT FROM m.classroom_pressure_flag
       OR c.teacher_pressure_flag IS DISTINCT FROM m.teacher_pressure_flag
       OR c.priority_affected_learners IS DISTINCT FROM m.priority_affected_learners) AS scenario_a_mismatch,
  (SELECT COUNT(*) FROM c LEFT JOIN flagged AS f USING (city_mun_psgc_code)
    WHERE c.outlier_school_count IS DISTINCT FROM COALESCE(f.n, 0)) AS outlier_count_mismatch,
  -- with nothing to exclude, scenario B must reproduce scenario A exactly
  (SELECT COUNT(*) FROM c WHERE outlier_school_count = 0
     AND (priority_category_without_suspected_outliers IS DISTINCT FROM priority_category
          OR classroom_pressure_flag_without_suspected_outliers IS DISTINCT FROM classroom_pressure_flag
          OR teacher_pressure_flag_without_suspected_outliers IS DISTINCT FROM teacher_pressure_flag
          OR priority_affected_learners_without_suspected_outliers IS DISTINCT FROM priority_affected_learners
          OR coverage_gate_changed)) AS unflagged_lgu_changed,
  -- and its recalculated AP2 and AP3 figures are the published ones
  (SELECT COUNT(*) FROM c
     JOIN edu_access.`06-analytics`.ap2_classroom_pressure AS a2 USING (city_mun_psgc_code)
     JOIN edu_access.`06-analytics`.ap3_teacher_pressure AS a3 USING (city_mun_psgc_code)
   WHERE c.outlier_school_count = 0
     AND (c.ap2_ratio_school_count_without_suspected_outliers IS DISTINCT FROM a2.ratio_school_count
          OR c.ap2_eligible_learners_without_suspected_outliers IS DISTINCT FROM a2.eligible_learners
          OR c.ap2_reported_rooms_without_suspected_outliers IS DISTINCT FROM a2.reported_instructional_classrooms
          OR c.ap2_affected_school_count_without_suspected_outliers IS DISTINCT FROM a2.congested_school_count
          OR c.ap2_affected_learners_without_suspected_outliers IS DISTINCT FROM a2.learners_in_congested_schools
          OR c.ap3_es_eligible_learners_without_suspected_outliers IS DISTINCT FROM COALESCE(a3.es_eligible_learners, 0)
          OR c.ap3_es_teacher_count_without_suspected_outliers IS DISTINCT FROM COALESCE(a3.es_teacher_count, 0)
          OR c.ap3_es_passes_gate_without_suspected_outliers IS DISTINCT FROM COALESCE(a3.es_passes_gate, FALSE)
          OR c.ap3_jhs_eligible_learners_without_suspected_outliers IS DISTINCT FROM COALESCE(a3.jhs_eligible_learners, 0)
          OR c.ap3_jhs_teacher_count_without_suspected_outliers IS DISTINCT FROM COALESCE(a3.jhs_teacher_count, 0)
          OR c.ap3_jhs_passes_gate_without_suspected_outliers IS DISTINCT FROM COALESCE(a3.jhs_passes_gate, FALSE)
          OR c.ap3_shs_eligible_learners_without_suspected_outliers IS DISTINCT FROM COALESCE(a3.shs_eligible_learners, 0)
          OR c.ap3_shs_teacher_count_without_suspected_outliers IS DISTINCT FROM COALESCE(a3.shs_teacher_count, 0)
          OR c.ap3_shs_passes_gate_without_suspected_outliers IS DISTINCT FROM COALESCE(a3.shs_passes_gate, FALSE))) AS unflagged_measures_changed,
  (SELECT COUNT(*) FROM c
    WHERE classroom_flag_changed IS DISTINCT FROM (classroom_pressure_flag <> classroom_pressure_flag_without_suspected_outliers)
       OR teacher_flag_changed IS DISTINCT FROM (teacher_pressure_flag <> teacher_pressure_flag_without_suspected_outliers)
       OR priority_category_changed IS DISTINCT FROM (priority_category <> priority_category_without_suspected_outliers)
       OR outlier_sensitivity_status IS DISTINCT FROM
          CASE WHEN outlier_school_count = 0 THEN 'No suspected outliers'
               WHEN priority_category_changed THEN 'Priority-sensitive'
               WHEN classroom_flag_changed OR teacher_flag_changed THEN 'Classification-sensitive'
               WHEN coverage_gate_changed THEN 'Coverage-sensitive'
               WHEN affected_learners_changed THEN 'Magnitude-sensitive'
               ELSE 'Stable' END
       OR rule_version <> 'D-065') AS status_mismatch,
  COALESCE((SELECT COUNT_IF(priority_category_without_suspected_outliers NOT IN
                   ('Priority 1', 'Priority 2', 'Priority 3', 'Monitor', 'No current pressure identified', 'Data review'))
   FROM c), 0) AS invalid_categories,
  (SELECT COUNT(*) - COUNT(DISTINCT priority_order_without_suspected_outliers) FROM c) AS duplicate_orders,
  COALESCE((SELECT COUNT_IF(outlier_school_count > 0) FROM c), 0) AS lgus_with_outliers,
  COALESCE((SELECT COUNT_IF(outlier_sensitivity_status = 'Priority-sensitive') FROM c), 0) AS priority_sensitive_lgus,
  COALESCE((SELECT COUNT_IF(outlier_sensitivity_status = 'Classification-sensitive') FROM c), 0) AS classification_sensitive_lgus,
  COALESCE((SELECT COUNT_IF(outlier_sensitivity_status = 'Coverage-sensitive') FROM c), 0) AS coverage_sensitive_lgus,
  COALESCE((SELECT COUNT_IF(outlier_sensitivity_status = 'Magnitude-sensitive') FROM c), 0) AS magnitude_sensitive_lgus;
SET VARIABLE analytics_gate_owner_sql = 'ALTER TABLE ' || session.analytics_gate_summary || ' OWNER TO `reached-hq`';
EXECUTE IMMEDIATE analytics_gate_owner_sql;

INSERT INTO edu_access.`01-control`.data_quality_results
  (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, NULL, 'lgu_priority_sensitivity', 'analytics', 'edu_access.06-analytics.lgu_priority_sensitivity_candidate',
       check_name, status, expected, actual, current_timestamp(), :code_revision
FROM (
  SELECT 'rows_match_regular_lgus' AS check_name, CASE WHEN rows = expected_rows THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(expected_rows AS STRING) AS expected, CAST(rows AS STRING) AS actual FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'key_unique', CASE WHEN duplicate_keys = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(duplicate_keys AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'lgu_membership_reconciles', CASE WHEN lgu_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(lgu_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'scenario_a_matches_priority_matrix', CASE WHEN scenario_a_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(scenario_a_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'outlier_counts_match_flags', CASE WHEN outlier_count_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(outlier_count_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'unflagged_lgus_unchanged', CASE WHEN unflagged_lgu_changed = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(unflagged_lgu_changed AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'unflagged_lgu_measures_unchanged', CASE WHEN unflagged_measures_changed = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(unflagged_measures_changed AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'sensitivity_status_follows_d065', CASE WHEN status_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(status_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'scenario_b_category_allowed', CASE WHEN invalid_categories = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(invalid_categories AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'scenario_b_order_unique', CASE WHEN duplicate_orders = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(duplicate_orders AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  -- counts, never a failure; a priority-sensitive LGU is a warning, because its category rests on extreme figures
  UNION ALL SELECT 'lgus_with_outliers', 'PASS', NULL, CAST(lgus_with_outliers AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'priority_sensitive_lgus', CASE WHEN priority_sensitive_lgus = 0 THEN 'PASS' ELSE 'WARN' END, NULL, CAST(priority_sensitive_lgus AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'classification_sensitive_lgus', 'PASS', NULL, CAST(classification_sensitive_lgus AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'coverage_sensitive_lgus', 'PASS', NULL, CAST(coverage_sensitive_lgus AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'magnitude_sensitive_lgus', 'PASS', NULL, CAST(magnitude_sensitive_lgus AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
) AS checks;

DROP TABLE IF EXISTS IDENTIFIER(session.analytics_gate_summary);

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Analytics gate failed for lgu_priority_sensitivity: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s)') ELSE 1 END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'lgu_priority_sensitivity' AND layer = 'analytics' AND status = 'FAIL'
  AND checked_at_utc >= session.analytics_gate_started_at_utc;

CREATE OR REPLACE TABLE edu_access.`06-analytics`.lgu_priority_sensitivity USING DELTA AS
SELECT * FROM edu_access.`06-analytics`.lgu_priority_sensitivity_candidate;
COMMENT ON TABLE edu_access.`06-analytics`.lgu_priority_sensitivity IS 'The D-061 planning priority with every valid school (published) and without suspected extreme schools, with an outlier-sensitivity status under D-065.';
ALTER TABLE edu_access.`06-analytics`.lgu_priority_sensitivity OWNER TO `reached-hq`;
