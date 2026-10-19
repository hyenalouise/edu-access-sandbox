-- ap1 publication gate; a failure leaves the last valid output unchanged.
-- the one-row summary is written once to a table named for this run and dropped after the checks are recorded:
-- read many times as a temporary view, the same pattern made Databricks SQL fail with INTERNAL_ERROR (c64e949, #202).
-- WARN: active public schools, learners and school-age population that are not placed in a city or municipality
-- (UNKNOWN or EXCLUDED), so what the matched-only measure leaves out is counted every run.
DECLARE OR REPLACE VARIABLE analytics_gate_started_at_utc TIMESTAMP;
SET VARIABLE analytics_gate_started_at_utc = current_timestamp();
DECLARE OR REPLACE VARIABLE analytics_gate_summary STRING;
SET VARIABLE analytics_gate_summary = '`edu_access`.`06-analytics`.`ap1_school_provision_gate_summary_r_' || sha2(:run_id, 256) || '`';
DECLARE OR REPLACE VARIABLE analytics_gate_owner_sql STRING;

CREATE OR REPLACE TABLE IDENTIFIER(session.analytics_gate_summary) USING DELTA COMMENT 'Internal unpublished one-row summary for one ap1_school_provision gate. The gate drops it once its checks are recorded in data_quality_results.' AS
WITH c AS (
  SELECT * FROM edu_access.`06-analytics`.ap1_school_provision_candidate
), regular AS (
  SELECT * FROM edu_access.`05-gold`.dim_city_municipality WHERE member_type = 'regular'
), expected_population AS (
  SELECT city_mun_psgc_code, CAST(SUM(population) AS BIGINT) AS school_age_population
  FROM edu_access.`05-gold`.fact_city_school_age_population
  WHERE reference_year = 2024 AND sex IN ('male', 'female') AND age BETWEEN 5 AND 17
    AND psgc_match_status = 'matched'
  GROUP BY city_mun_psgc_code
), school_rows AS (
  SELECT school_id, city_mun_psgc_code, MIN(psgc_match_status) AS psgc_match_status,
         MAX(CASE WHEN is_offered AND learner_count > 0 THEN 1 ELSE 0 END) AS active,
         COUNT_IF(is_offered AND learner_count IS NULL) AS incomplete,
         SUM(CASE WHEN is_offered AND learner_count IS NOT NULL THEN learner_count ELSE 0 END) AS learners
  FROM edu_access.`05-gold`.fact_school_enrollment
  WHERE school_year = '2024-25' AND sector = 'Public'
  GROUP BY school_id, city_mun_psgc_code
), expected_schools AS (
  SELECT city_mun_psgc_code, COUNT_IF(active = 1) AS active_public_school_count,
         COUNT_IF(active = 1 AND incomplete = 0) AS complete_enrollment_school_count
  FROM school_rows WHERE psgc_match_status = 'matched' GROUP BY city_mun_psgc_code
), type_refs AS (
  SELECT lgu_type, CAST(SUM(school_age_population) AS DOUBLE) / NULLIF(SUM(active_public_school_count), 0) AS ratio
  FROM c WHERE input_issue_reason IS NULL GROUP BY lgu_type
)
SELECT
  (SELECT COUNT(*) FROM c) AS rows,
  (SELECT COUNT(*) FROM regular) AS expected_rows,
  (SELECT COUNT(*) - COUNT(DISTINCT city_mun_psgc_code) FROM c) AS duplicate_keys,
  (SELECT COUNT_IF(city_mun_psgc_code IS NULL OR lgu_type IS NULL OR classification IS NULL) FROM c) AS null_required,
  (SELECT COUNT(*) FROM c FULL OUTER JOIN regular USING (city_mun_psgc_code)
    WHERE c.city_mun_psgc_code IS NULL OR regular.city_mun_psgc_code IS NULL) AS lgu_mismatch,
  (SELECT COUNT(*) FROM c LEFT JOIN expected_population p USING (city_mun_psgc_code)
    WHERE c.school_age_population IS DISTINCT FROM p.school_age_population) AS population_mismatch,
  (SELECT COUNT(*) FROM c LEFT JOIN expected_schools s USING (city_mun_psgc_code)
    WHERE c.active_public_school_count IS DISTINCT FROM COALESCE(s.active_public_school_count, 0)
       OR c.complete_enrollment_school_count IS DISTINCT FROM COALESCE(s.complete_enrollment_school_count, 0)) AS school_mismatch,
  (SELECT COUNT_IF((input_issue_reason IS NULL) <> COALESCE(school_age_population IS NOT NULL
    AND active_public_school_count > 0 AND coverage_pct >= 90, FALSE)) FROM c) AS input_issue_mismatch,
  (SELECT COUNT(*) FROM c LEFT JOIN type_refs r USING (lgu_type)
    WHERE (c.national_same_type_ratio IS NULL) <> (r.ratio IS NULL)
       OR (c.national_same_type_ratio IS NOT NULL AND r.ratio IS NOT NULL
           AND ABS(c.national_same_type_ratio - r.ratio) > 1e-9)) AS pooled_reference_mismatch,
  (SELECT COUNT_IF((active_public_school_count = 0 AND school_age_population_per_public_school IS NOT NULL)
    OR (active_public_school_count > 0 AND school_age_population IS NOT NULL
      AND ABS(school_age_population_per_public_school - school_age_population * 1.0 / active_public_school_count) > 1e-9)) FROM c)
    AS ratio_mismatch,
  (SELECT COUNT_IF((coverage_pct IS NOT NULL AND (coverage_pct < 0 OR coverage_pct > 100))
    OR (coverage_pct < 90 AND classification <> 'Data Review')
    OR (outlier_flag AND classification <> 'Data Review')
    OR (quality_issue_reason IS DISTINCT FROM input_issue_reason)
    OR (quality_issue_reason IS NOT NULL AND classification <> 'Data Review')
    OR (quality_issue_reason IS NULL AND NOT outlier_flag AND relative_pressure > 1 AND classification <> 'Above Reference')
    OR (quality_issue_reason IS NULL AND NOT outlier_flag AND relative_pressure <= 1 AND classification <> 'At or Below Reference')) FROM c)
    AS classification_mismatch,
  (SELECT COUNT(*) FROM school_rows WHERE active = 1 AND psgc_match_status <> 'matched') AS unplaced_active_schools,
  (SELECT COALESCE(SUM(CASE WHEN active = 1 THEN learners END), 0) FROM school_rows WHERE psgc_match_status <> 'matched')
    AS unplaced_public_learners,
  (SELECT COALESCE(SUM(population), 0) FROM edu_access.`05-gold`.fact_city_school_age_population
    WHERE reference_year = 2024 AND sex IN ('male', 'female') AND age BETWEEN 5 AND 17
      AND psgc_match_status <> 'matched') AS unplaced_school_age_population;
SET VARIABLE analytics_gate_owner_sql = 'ALTER TABLE ' || session.analytics_gate_summary || ' OWNER TO `reached-hq`';
EXECUTE IMMEDIATE analytics_gate_owner_sql;

INSERT INTO edu_access.`01-control`.data_quality_results
  (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, NULL, 'ap1_school_provision', 'analytics', 'edu_access.06-analytics.ap1_school_provision_candidate',
       check_name, status, expected, actual, current_timestamp(), :code_revision
FROM (
  SELECT 'rows_match_regular_lgus' AS check_name, CASE WHEN rows = expected_rows THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(expected_rows AS STRING) AS expected, CAST(rows AS STRING) AS actual FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'key_unique', CASE WHEN duplicate_keys = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(duplicate_keys AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'required_values_present', CASE WHEN null_required = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(null_required AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'lgu_membership_reconciles', CASE WHEN lgu_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(lgu_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'population_reconciles', CASE WHEN population_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(population_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'schools_reconcile', CASE WHEN school_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(school_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'input_issue_valid', CASE WHEN input_issue_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(input_issue_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'same_type_reference_pools_clean_lgus', CASE WHEN pooled_reference_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(pooled_reference_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'ratio_arithmetic', CASE WHEN ratio_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(ratio_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'classification_valid', CASE WHEN classification_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(classification_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'unplaced_active_public_schools', CASE WHEN unplaced_active_schools = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(unplaced_active_schools AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'unplaced_public_learners', CASE WHEN unplaced_public_learners = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(unplaced_public_learners AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'unplaced_school_age_population', CASE WHEN unplaced_school_age_population = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(unplaced_school_age_population AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
) AS checks;

-- Every check is recorded, so the summary is no longer needed, whether the gate passes or fails.
DROP TABLE IF EXISTS IDENTIFIER(session.analytics_gate_summary);

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Analytics gate failed for ap1_school_provision: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s)') ELSE 1 END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'ap1_school_provision' AND layer = 'analytics' AND status = 'FAIL'
  AND checked_at_utc >= session.analytics_gate_started_at_utc;

CREATE OR REPLACE TABLE edu_access.`06-analytics`.ap1_school_provision USING DELTA AS
SELECT * FROM edu_access.`06-analytics`.ap1_school_provision_candidate;
COMMENT ON TABLE edu_access.`06-analytics`.ap1_school_provision IS 'AP1 school-age population per active public school by regular LGU.';
ALTER TABLE edu_access.`06-analytics`.ap1_school_provision OWNER TO `reached-hq`;
