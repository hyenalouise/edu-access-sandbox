-- priority-matrix publication gate; a failure leaves the last valid output unchanged.
-- the one-row summary is written once to a table named for this run and dropped after the checks are recorded:
-- read many times as a temporary view, the same pattern made Databricks SQL fail with INTERNAL_ERROR (c64e949, #202).
-- Counts only (PASS): LGUs per priority, so every run records how many land in each tier.
DECLARE OR REPLACE VARIABLE analytics_gate_started_at_utc TIMESTAMP;
SET VARIABLE analytics_gate_started_at_utc = current_timestamp();
DECLARE OR REPLACE VARIABLE analytics_gate_summary STRING;
SET VARIABLE analytics_gate_summary = '`edu_access`.`06-analytics`.`lgu_priority_matrix_gate_summary_r_' || sha2(:run_id, 256) || '`';
DECLARE OR REPLACE VARIABLE analytics_gate_owner_sql STRING;

CREATE OR REPLACE TABLE IDENTIFIER(session.analytics_gate_summary) USING DELTA COMMENT 'Internal unpublished one-row summary for one lgu_priority_matrix gate. The gate drops it once its checks are recorded in data_quality_results.' AS
WITH c AS (SELECT * FROM edu_access.`06-analytics`.lgu_priority_matrix_candidate),
regular AS (SELECT * FROM edu_access.`05-gold`.dim_city_municipality WHERE member_type = 'regular')
SELECT
  (SELECT COUNT(*) FROM c) AS rows, (SELECT COUNT(*) FROM regular) AS expected_rows,
  (SELECT COUNT(*) - COUNT(DISTINCT city_mun_psgc_code) FROM c) AS duplicate_keys,
  (SELECT COUNT(*) FROM c FULL OUTER JOIN regular USING (city_mun_psgc_code)
    WHERE c.city_mun_psgc_code IS NULL OR regular.city_mun_psgc_code IS NULL) AS lgu_mismatch,
  (SELECT COUNT_IF(ap1_classification IS NULL OR ap2_classification IS NULL OR ap3_classification IS NULL
    OR enrollment_trend_status IS NULL) FROM c) AS missing_ap_outputs,
  (SELECT COUNT_IF(current_pressure_count NOT BETWEEN 0 AND 3) FROM c) AS invalid_pressure_count,
  (SELECT COUNT_IF(ap1_pressure_flag IS DISTINCT FROM (ap1_classification = 'Above Reference')
    OR ap2_pressure_flag IS DISTINCT FROM (ap2_classification = 'Above Reference')
    OR ap3_pressure_flag IS DISTINCT FROM (ap3_classification = 'Above Reference')) FROM c) AS flag_mismatch,
  (SELECT COUNT_IF(growing_enrollment_flag IS DISTINCT FROM COALESCE(enrollment_trend = 'Growing' AND enrollment_trend_status = 'Complete', FALSE)) FROM c)
    AS growth_flag_mismatch,
  (SELECT COUNT_IF(current_pressure_count <>
    CAST(ap1_pressure_flag AS INT) + CAST(ap2_pressure_flag AS INT) + CAST(ap3_pressure_flag AS INT)) FROM c)
    AS count_mismatch,
  (SELECT COUNT_IF(priority IS DISTINCT FROM CASE
      WHEN ap1_classification IS NULL OR ap2_classification IS NULL OR ap3_classification IS NULL
        OR ap1_classification = 'Data Review' OR ap2_classification = 'Data Review'
        OR ap3_classification = 'Data Review' THEN 'Data Review'
      WHEN current_pressure_count >= 2 AND growing_enrollment_flag THEN 'Priority 1'
      WHEN current_pressure_count >= 2 THEN 'Priority 2'
      WHEN current_pressure_count = 1 AND growing_enrollment_flag THEN 'Priority 3'
      WHEN current_pressure_count = 1 THEN 'Monitor'
      WHEN current_pressure_count = 0 AND growing_enrollment_flag THEN 'Monitor'
      ELSE 'Lower Priority' END) FROM c) AS priority_mismatch,
  (SELECT COUNT_IF((ap1_classification = 'Data Review' OR ap2_classification = 'Data Review'
    OR ap3_classification = 'Data Review') AND priority <> 'Data Review') FROM c) AS data_review_not_overriding,
  (SELECT COUNT_IF(priority = 'Priority 1') FROM c) AS priority_1,
  (SELECT COUNT_IF(priority = 'Priority 2') FROM c) AS priority_2,
  (SELECT COUNT_IF(priority = 'Priority 3') FROM c) AS priority_3,
  (SELECT COUNT_IF(priority = 'Monitor') FROM c) AS monitor,
  (SELECT COUNT_IF(priority = 'Lower Priority') FROM c) AS lower_priority,
  (SELECT COUNT_IF(priority = 'Data Review') FROM c) AS data_review;
SET VARIABLE analytics_gate_owner_sql = 'ALTER TABLE ' || session.analytics_gate_summary || ' OWNER TO `reached-hq`';
EXECUTE IMMEDIATE analytics_gate_owner_sql;



INSERT INTO edu_access.`01-control`.data_quality_results
  (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, NULL, 'lgu_priority_matrix', 'analytics', 'edu_access.06-analytics.lgu_priority_matrix_candidate',
       check_name, status, expected, actual, current_timestamp(), :code_revision
FROM (
  SELECT 'rows_match_regular_lgus' AS check_name, CASE WHEN rows = expected_rows THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(expected_rows AS STRING) AS expected, CAST(rows AS STRING) AS actual FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'key_unique', CASE WHEN duplicate_keys = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(duplicate_keys AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'lgu_membership_reconciles', CASE WHEN lgu_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(lgu_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'all_ap_outputs_joined', CASE WHEN missing_ap_outputs = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(missing_ap_outputs AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'pressure_count_valid', CASE WHEN invalid_pressure_count = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(invalid_pressure_count AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'pressure_flags_match', CASE WHEN flag_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(flag_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'growth_flag_needs_complete_trend', CASE WHEN growth_flag_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(growth_flag_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'pressure_count_matches', CASE WHEN count_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(count_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'priority_logic_matches', CASE WHEN priority_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(priority_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'data_review_overrides', CASE WHEN data_review_not_overriding = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(data_review_not_overriding AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'lgus_priority_1', 'PASS', CAST(NULL AS STRING), CAST(priority_1 AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'lgus_priority_2', 'PASS', CAST(NULL AS STRING), CAST(priority_2 AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'lgus_priority_3', 'PASS', CAST(NULL AS STRING), CAST(priority_3 AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'lgus_monitor', 'PASS', CAST(NULL AS STRING), CAST(monitor AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'lgus_lower_priority', 'PASS', CAST(NULL AS STRING), CAST(lower_priority AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'lgus_data_review', 'PASS', CAST(NULL AS STRING), CAST(data_review AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
) AS checks;

-- Every check is recorded, so the summary is no longer needed, whether the gate passes or fails.
DROP TABLE IF EXISTS IDENTIFIER(session.analytics_gate_summary);

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Analytics gate failed for lgu_priority_matrix: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s)') ELSE 1 END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'lgu_priority_matrix' AND layer = 'analytics' AND status = 'FAIL'
  AND checked_at_utc >= session.analytics_gate_started_at_utc;

CREATE OR REPLACE TABLE edu_access.`06-analytics`.lgu_priority_matrix USING DELTA AS
SELECT * FROM edu_access.`06-analytics`.lgu_priority_matrix_candidate;
COMMENT ON TABLE edu_access.`06-analytics`.lgu_priority_matrix IS 'Dashboard-ready LGU priority matrix from validated AP1 to AP4 outputs.';
ALTER TABLE edu_access.`06-analytics`.lgu_priority_matrix OWNER TO `reached-hq`;

