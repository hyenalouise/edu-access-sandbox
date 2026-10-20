-- priority checks publication gate (D-057); a failure leaves the last valid output unchanged.
-- FAIL: rows or keys that differ from lgu_priority_matrix, a tier that differs from it, an assessed measure with no
-- same-type median or relative pressure, a relative pressure that does not recompute from the published ratio and an
-- independently computed median, a lower high line that removes a Critical LGU, or a check tier that is not a D-057
-- tier. Counts only (PASS): Critical LGUs under each check, how many stay Critical, and tier changes without outlier
-- schools, including LGUs with none of their own (the others' outliers move the percentiles they are ranked against).
DECLARE OR REPLACE VARIABLE analytics_gate_started_at_utc TIMESTAMP;
SET VARIABLE analytics_gate_started_at_utc = current_timestamp();
DECLARE OR REPLACE VARIABLE analytics_gate_summary STRING;
SET VARIABLE analytics_gate_summary = '`edu_access`.`06-analytics`.`lgu_priority_checks_gate_summary_r_' || sha2(:run_id, 256) || '`';
DECLARE OR REPLACE VARIABLE analytics_gate_owner_sql STRING;

CREATE OR REPLACE TABLE IDENTIFIER(session.analytics_gate_summary) USING DELTA COMMENT 'Internal unpublished one-row summary for one lgu_priority_checks gate. The gate drops it once its checks are recorded in data_quality_results.' AS
WITH c AS (
  SELECT * FROM edu_access.`06-analytics`.lgu_priority_checks_candidate
), m AS (
  SELECT * FROM edu_access.`06-analytics`.lgu_priority_matrix
), a1 AS (
  SELECT * FROM edu_access.`06-analytics`.ap1_school_provision
), a2 AS (
  SELECT * FROM edu_access.`06-analytics`.ap2_classroom_pressure
), a3 AS (
  SELECT * FROM edu_access.`06-analytics`.ap3_teacher_pressure
), med1 AS (
  SELECT lgu_type, PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY learners_per_public_school) AS v FROM a1 WHERE is_assessed GROUP BY lgu_type
), med2 AS (
  SELECT lgu_type, PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY learners_per_classroom) AS v FROM a2 WHERE is_assessed GROUP BY lgu_type
), expected AS (
  SELECT a1.city_mun_psgc_code, a1.is_assessed AS ap1_assessed, a2.is_assessed AS ap2_assessed,
         CASE WHEN a1.is_assessed THEN a1.learners_per_public_school / NULLIF(x1.v, 0) END AS ap1_rp,
         CASE WHEN a2.is_assessed THEN a2.learners_per_classroom / NULLIF(x2.v, 0) END AS ap2_rp
  FROM a1
  JOIN a2 USING (city_mun_psgc_code)
  LEFT JOIN med1 AS x1 ON x1.lgu_type = a1.lgu_type
  LEFT JOIN med2 AS x2 ON x2.lgu_type = a2.lgu_type
), outlier_lgus AS (
  SELECT DISTINCT city_mun_psgc_code FROM edu_access.`06-analytics`.lgu_priority_outlier_schools
)
SELECT
  (SELECT COUNT(*) FROM c) AS rows, (SELECT COUNT(*) FROM m) AS expected_rows,
  (SELECT COUNT(*) - COUNT(DISTINCT city_mun_psgc_code) FROM c) AS duplicate_keys,
  (SELECT COUNT(*) FROM c FULL OUTER JOIN m USING (city_mun_psgc_code)
    WHERE c.city_mun_psgc_code IS NULL OR m.city_mun_psgc_code IS NULL OR c.tier IS DISTINCT FROM m.tier) AS tier_mismatch,
  (SELECT COUNT(*) FROM c JOIN expected AS e USING (city_mun_psgc_code)
    WHERE (e.ap1_assessed AND (c.ap1_relative_pressure IS NULL OR c.ap1_same_type_median IS NULL))
       OR (e.ap2_assessed AND (c.ap2_relative_pressure IS NULL OR c.ap2_same_type_median IS NULL))) AS missing_comparison,
  (SELECT COUNT(*) FROM c JOIN a3 USING (city_mun_psgc_code)
    WHERE a3.highest_level IS NOT NULL AND (c.ap3_relative_pressure IS NULL OR c.ap3_level IS DISTINCT FROM a3.highest_level)) AS missing_ap3_comparison,
  (SELECT COUNT(*) FROM c JOIN expected AS e USING (city_mun_psgc_code)
    WHERE ABS(COALESCE(c.ap1_relative_pressure, 0) - COALESCE(e.ap1_rp, 0)) > 0.000000001
       OR ABS(COALESCE(c.ap2_relative_pressure, 0) - COALESCE(e.ap2_rp, 0)) > 0.000000001) AS bad_relative_pressure,
  (SELECT COALESCE(COUNT_IF(tier = 'Critical' AND (tier_at_line_085 <> 'Critical' OR tier_at_line_080 <> 'Critical')), 0) FROM c)
    AS lower_line_drops_critical,
  (SELECT COUNT(*) FROM c
    WHERE COALESCE(tier_at_line_085, '') NOT IN ('Critical', 'Elevated', 'Targeted', 'Monitor', 'Data review')
       OR COALESCE(tier_at_line_080, '') NOT IN ('Critical', 'Elevated', 'Targeted', 'Monitor', 'Data review')
       OR COALESCE(tier_at_gate_95, '') NOT IN ('Critical', 'Elevated', 'Targeted', 'Monitor', 'Data review')
       OR COALESCE(tier_without_outliers, '') NOT IN ('Critical', 'Elevated', 'Targeted', 'Monitor', 'Data review')
       OR outliers_change_tier IS DISTINCT FROM (tier_without_outliers IS DISTINCT FROM tier)) AS bad_scenario_tier,
  (SELECT COUNT(*) FROM c LEFT JOIN outlier_lgus AS o USING (city_mun_psgc_code)
    WHERE o.city_mun_psgc_code IS NULL AND c.outliers_change_tier) AS moved_by_others_outliers,
  (SELECT COALESCE(COUNT_IF(tier = 'Critical'), 0) FROM c) AS critical,
  (SELECT COALESCE(COUNT_IF(tier_at_line_085 = 'Critical'), 0) FROM c) AS critical_085,
  (SELECT COALESCE(COUNT_IF(tier_at_line_080 = 'Critical'), 0) FROM c) AS critical_080,
  (SELECT COALESCE(COUNT_IF(tier_at_gate_95 = 'Critical'), 0) FROM c) AS critical_gate_95,
  (SELECT COALESCE(COUNT_IF(tier = 'Critical' AND tier_at_gate_95 = 'Critical'), 0) FROM c) AS kept_gate_95,
  (SELECT COALESCE(COUNT_IF(tier_without_outliers = 'Critical'), 0) FROM c) AS critical_without_outliers,
  (SELECT COALESCE(COUNT_IF(tier = 'Critical' AND tier_without_outliers = 'Critical'), 0) FROM c) AS kept_without_outliers,
  (SELECT COALESCE(COUNT_IF(outliers_change_tier), 0) FROM c) AS outliers_change_tier;
SET VARIABLE analytics_gate_owner_sql = 'ALTER TABLE ' || session.analytics_gate_summary || ' OWNER TO `reached-hq`';
EXECUTE IMMEDIATE analytics_gate_owner_sql;

INSERT INTO edu_access.`01-control`.data_quality_results
  (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, NULL, 'lgu_priority_checks', 'analytics', 'edu_access.06-analytics.lgu_priority_checks_candidate',
       check_name, status, expected, actual, current_timestamp(), :code_revision
FROM (
  SELECT 'rows_match_priority_matrix' AS check_name, CASE WHEN rows = expected_rows THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(expected_rows AS STRING) AS expected, CAST(rows AS STRING) AS actual FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'key_unique', CASE WHEN duplicate_keys = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(duplicate_keys AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'tier_matches_priority_matrix', CASE WHEN tier_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(tier_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'assessed_measures_have_a_comparison', CASE WHEN missing_comparison = 0 AND missing_ap3_comparison = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(missing_comparison + missing_ap3_comparison AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'relative_pressure_recalculates', CASE WHEN bad_relative_pressure = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_relative_pressure AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'lower_line_keeps_critical', CASE WHEN lower_line_drops_critical = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(lower_line_drops_critical AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'scenario_tiers_valid', CASE WHEN bad_scenario_tier = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_scenario_tier AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'lgus_critical', 'PASS', CAST(NULL AS STRING), CAST(critical AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'lgus_critical_at_line_085', 'PASS', CAST(NULL AS STRING), CAST(critical_085 AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'lgus_critical_at_line_080', 'PASS', CAST(NULL AS STRING), CAST(critical_080 AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'lgus_critical_at_gate_95', 'PASS', CAST(NULL AS STRING), CAST(critical_gate_95 AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'critical_kept_at_gate_95', 'PASS', CAST(NULL AS STRING), CAST(kept_gate_95 AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'lgus_critical_without_outliers', 'PASS', CAST(NULL AS STRING), CAST(critical_without_outliers AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'critical_kept_without_outliers', 'PASS', CAST(NULL AS STRING), CAST(kept_without_outliers AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'lgus_tier_changes_without_outliers', 'PASS', CAST(NULL AS STRING), CAST(outliers_change_tier AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'lgus_moved_by_other_lgus_outliers', 'PASS', CAST(NULL AS STRING), CAST(moved_by_others_outliers AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
) AS checks;

-- Every check is recorded, so the summary is no longer needed, whether the gate passes or fails.
DROP TABLE IF EXISTS IDENTIFIER(session.analytics_gate_summary);

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Analytics gate failed for lgu_priority_checks: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s)') ELSE 1 END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'lgu_priority_checks' AND layer = 'analytics' AND status = 'FAIL'
  AND checked_at_utc >= session.analytics_gate_started_at_utc;

CREATE OR REPLACE TABLE edu_access.`06-analytics`.lgu_priority_checks USING DELTA AS
SELECT * FROM edu_access.`06-analytics`.lgu_priority_checks_candidate;
COMMENT ON TABLE edu_access.`06-analytics`.lgu_priority_checks IS 'D-057 checks beside the ranking (0.85 and 0.80 lines, 95% gate, without outlier schools) and the same-type median and relative pressure of AP1 to AP3. Never changes a tier.';
ALTER TABLE edu_access.`06-analytics`.lgu_priority_checks OWNER TO `reached-hq`;
