-- priority table publication gate (D-057); a failure leaves the last valid output unchanged.
-- the one-row summary is written once to a table named for this run and dropped after the checks are recorded:
-- read many times as a temporary view, the same pattern made Databricks SQL fail with INTERNAL_ERROR (c64e949, #202).
-- FAIL: rows, keys or LGUs that differ from dim_city_municipality, AP1 to AP3 values that differ from the published
-- outputs, a count of high measures, tier, tier code, national tier, Stable flag or order within a tier that does not
-- follow D-057. Counts only (PASS): LGUs per tier and Stable LGUs.
DECLARE OR REPLACE VARIABLE analytics_gate_started_at_utc TIMESTAMP;
SET VARIABLE analytics_gate_started_at_utc = current_timestamp();
DECLARE OR REPLACE VARIABLE analytics_gate_summary STRING;
SET VARIABLE analytics_gate_summary = '`edu_access`.`06-analytics`.`lgu_priority_matrix_gate_summary_r_' || sha2(:run_id, 256) || '`';
DECLARE OR REPLACE VARIABLE analytics_gate_owner_sql STRING;

CREATE OR REPLACE TABLE IDENTIFIER(session.analytics_gate_summary) USING DELTA COMMENT 'Internal unpublished one-row summary for one lgu_priority_matrix gate. The gate drops it once its checks are recorded in data_quality_results.' AS
WITH c AS (
  SELECT * FROM edu_access.`06-analytics`.lgu_priority_matrix_candidate
), regular AS (
  SELECT * FROM edu_access.`05-gold`.dim_city_municipality WHERE member_type = 'regular'
), expected AS (
  SELECT r.city_mun_psgc_code,
         COALESCE(a.is_assessed AND b.is_assessed AND t.is_assessed, FALSE) AS all_assessed,
         COALESCE(a.is_assessed AND b.is_assessed AND t.is_assessed_nationally, FALSE) AS all_assessed_nationally,
         CAST(COALESCE(a.is_high, FALSE) AS INT) + CAST(COALESCE(b.is_high, FALSE) AS INT)
           + CAST(COALESCE(t.is_high, FALSE) AS INT) AS high_count,
         CAST(COALESCE(a.is_high_nationally, FALSE) AS INT) + CAST(COALESCE(b.is_high_nationally, FALSE) AS INT)
           + CAST(COALESCE(t.is_high_nationally, FALSE) AS INT) AS national_high_count,
         a.public_school_enrollment AS affected_learners,
         a.within_type_percentile AS ap1_pct, b.within_type_percentile AS ap2_pct, t.within_type_percentile AS ap3_pct
  FROM regular r
  LEFT JOIN edu_access.`06-analytics`.ap1_school_provision a USING (city_mun_psgc_code)
  LEFT JOIN edu_access.`06-analytics`.ap2_classroom_pressure b USING (city_mun_psgc_code)
  LEFT JOIN edu_access.`06-analytics`.ap3_teacher_pressure t USING (city_mun_psgc_code)
), expected_tiers AS (
  SELECT *,
         CASE WHEN NOT all_assessed THEN 'Data review' WHEN high_count = 3 THEN 'Critical' WHEN high_count = 2 THEN 'Elevated'
              WHEN high_count = 1 THEN 'Targeted' ELSE 'Monitor' END AS tier,
         CASE WHEN NOT all_assessed THEN 'data_review' ELSE CAST(high_count AS STRING) END AS tier_code,
         CASE WHEN NOT all_assessed_nationally THEN 'Data review' WHEN national_high_count = 3 THEN 'Critical'
              WHEN national_high_count = 2 THEN 'Elevated' WHEN national_high_count = 1 THEN 'Targeted'
              ELSE 'Monitor' END AS national_tier,
         LEAST(ap1_pct, ap2_pct, ap3_pct) AS lowest_pct
  FROM expected
), expected_order AS (
  SELECT city_mun_psgc_code,
         ROW_NUMBER() OVER (PARTITION BY tier
           ORDER BY affected_learners DESC NULLS LAST, lowest_pct DESC NULLS LAST, city_mun_psgc_code) AS order_in_tier
  FROM expected_tiers
)
SELECT
  (SELECT COUNT(*) FROM c) AS rows, (SELECT COUNT(*) FROM regular) AS expected_rows,
  (SELECT COUNT(*) - COUNT(DISTINCT city_mun_psgc_code) FROM c) AS duplicate_keys,
  (SELECT COUNT(*) FROM c FULL OUTER JOIN regular USING (city_mun_psgc_code)
    WHERE c.city_mun_psgc_code IS NULL OR regular.city_mun_psgc_code IS NULL) AS lgu_mismatch,
  (SELECT COUNT(*) FROM c JOIN expected_tiers e USING (city_mun_psgc_code)
    WHERE c.all_assessed IS DISTINCT FROM e.all_assessed
       OR c.high_measure_count IS DISTINCT FROM e.high_count
       OR c.affected_learners IS DISTINCT FROM e.affected_learners
       OR c.ap1_percentile IS DISTINCT FROM e.ap1_pct
       OR c.ap2_percentile IS DISTINCT FROM e.ap2_pct
       OR c.ap3_percentile IS DISTINCT FROM e.ap3_pct) AS input_mismatch,
  (SELECT COUNT(*) FROM c JOIN expected_tiers e USING (city_mun_psgc_code)
    WHERE c.tier IS DISTINCT FROM e.tier OR c.tier_code IS DISTINCT FROM e.tier_code) AS tier_mismatch,
  (SELECT COUNT(*) FROM c JOIN expected_tiers e USING (city_mun_psgc_code)
    WHERE c.national_tier IS DISTINCT FROM e.national_tier
       OR c.is_stable IS DISTINCT FROM (e.tier = 'Critical' AND e.national_tier = 'Critical')) AS stable_mismatch,
  (SELECT COUNT(*) FROM c JOIN expected_order o USING (city_mun_psgc_code)
    WHERE c.order_in_tier IS DISTINCT FROM o.order_in_tier) AS order_mismatch,
  (SELECT COALESCE(COUNT_IF(tier = 'Targeted' AND high_measures IS NULL), 0) FROM c) AS targeted_without_measure,
  (SELECT COALESCE(COUNT_IF(tier = 'Critical'), 0) FROM c) AS critical,
  (SELECT COALESCE(COUNT_IF(tier = 'Elevated'), 0) FROM c) AS elevated,
  (SELECT COALESCE(COUNT_IF(tier = 'Targeted'), 0) FROM c) AS targeted,
  (SELECT COALESCE(COUNT_IF(tier = 'Monitor'), 0) FROM c) AS monitor,
  (SELECT COALESCE(COUNT_IF(tier = 'Data review'), 0) FROM c) AS data_review,
  (SELECT COALESCE(COUNT_IF(is_stable), 0) FROM c) AS stable;
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
  UNION ALL SELECT 'inputs_match_ap_outputs', CASE WHEN input_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(input_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'tier_follows_d057', CASE WHEN tier_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(tier_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'national_tier_and_stable', CASE WHEN stable_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(stable_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'order_within_tier', CASE WHEN order_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(order_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'targeted_names_its_measure', CASE WHEN targeted_without_measure = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(targeted_without_measure AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'lgus_critical', 'PASS', CAST(NULL AS STRING), CAST(critical AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'lgus_elevated', 'PASS', CAST(NULL AS STRING), CAST(elevated AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'lgus_targeted', 'PASS', CAST(NULL AS STRING), CAST(targeted AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'lgus_monitor', 'PASS', CAST(NULL AS STRING), CAST(monitor AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'lgus_data_review', 'PASS', CAST(NULL AS STRING), CAST(data_review AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'lgus_stable', 'PASS', CAST(NULL AS STRING), CAST(stable AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
) AS checks;

-- Every check is recorded, so the summary is no longer needed, whether the gate passes or fails.
DROP TABLE IF EXISTS IDENTIFIER(session.analytics_gate_summary);

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Analytics gate failed for lgu_priority_matrix: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s)') ELSE 1 END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'lgu_priority_matrix' AND layer = 'analytics' AND status = 'FAIL'
  AND checked_at_utc >= session.analytics_gate_started_at_utc;

CREATE OR REPLACE TABLE edu_access.`06-analytics`.lgu_priority_matrix USING DELTA AS
SELECT * FROM edu_access.`06-analytics`.lgu_priority_matrix_candidate;
COMMENT ON TABLE edu_access.`06-analytics`.lgu_priority_matrix IS 'LGU priority table under D-057: tier by the count of AP1 to AP3 measures at the 90th percentile within LGU type, order by affected learners, Stable flag, AP4 as context.';
ALTER TABLE edu_access.`06-analytics`.lgu_priority_matrix OWNER TO `reached-hq`;
