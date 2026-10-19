-- ap3 publication gate; a failure leaves the last valid output unchanged.
-- the one-row summary is written once to a table named for this run and dropped after the checks are recorded:
-- read many times as a temporary view, the same pattern made Databricks SQL fail with INTERNAL_ERROR (c64e949, #202).
-- WARN: active public schools and learners that are not placed in a city or municipality (UNKNOWN or EXCLUDED).
DECLARE OR REPLACE VARIABLE analytics_gate_started_at_utc TIMESTAMP;
SET VARIABLE analytics_gate_started_at_utc = current_timestamp();
DECLARE OR REPLACE VARIABLE analytics_gate_summary STRING;
SET VARIABLE analytics_gate_summary = '`edu_access`.`06-analytics`.`ap3_teacher_pressure_gate_summary_r_' || sha2(:run_id, 256) || '`';
DECLARE OR REPLACE VARIABLE analytics_gate_owner_sql STRING;

CREATE OR REPLACE TABLE IDENTIFIER(session.analytics_gate_summary) USING DELTA COMMENT 'Internal unpublished one-row summary for one ap3_teacher_pressure gate. The gate drops it once its checks are recorded in data_quality_results.' AS
WITH c AS (
  SELECT * FROM edu_access.`06-analytics`.ap3_teacher_pressure_candidate
), regular AS (
  SELECT * FROM edu_access.`05-gold`.dim_city_municipality WHERE member_type = 'regular'
), schools AS (
  SELECT school_id, MIN(psgc_match_status) AS psgc_match_status,
         MAX(CASE WHEN is_offered AND learner_count > 0 THEN 1 ELSE 0 END) AS active,
         SUM(CASE WHEN is_offered AND learner_count IS NOT NULL THEN learner_count ELSE 0 END) AS learners
  FROM edu_access.`05-gold`.fact_school_enrollment
  WHERE school_year = '2023-24' AND sector = 'Public'
  GROUP BY school_id
), rows AS (
  SELECT e.city_mun_psgc_code, r.lgu_type, e.school_id, e.education_level_code, e.learner_count, t.teacher_count,
         COALESCE(t.teacher_count > 0, FALSE) AS usable,
         COALESCE(e.annex_status = 'Annex/Extension School' AND t.teacher_count = 0, FALSE) AS zero_annex
  FROM edu_access.`05-gold`.fact_school_enrollment e
  JOIN schools a ON a.school_id = e.school_id AND a.active = 1
  JOIN regular r ON r.city_mun_psgc_code = e.city_mun_psgc_code
  LEFT JOIN edu_access.`05-gold`.fact_school_teacher_capacity t
    ON t.school_id = e.school_id AND t.school_year = e.school_year AND t.education_level_code = e.education_level_code
  WHERE e.school_year = '2023-24' AND e.sector = 'Public' AND e.psgc_match_status = 'matched' AND e.is_offered
), level_ratios AS (
  SELECT lgu_type, city_mun_psgc_code, CAST(learner_count AS DOUBLE) / teacher_count AS school_ratio
  FROM rows WHERE usable AND learner_count IS NOT NULL
), fences AS (
  SELECT lgu_type,
         PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY school_ratio) AS q1,
         PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY school_ratio) AS q3
  FROM level_ratios GROUP BY lgu_type
), outliers AS (
  SELECT l.city_mun_psgc_code, COUNT_IF(l.school_ratio > f.q3 + 3 * (f.q3 - f.q1)) AS outlier_levels
  FROM level_ratios l JOIN fences f USING (lgu_type)
  GROUP BY l.city_mun_psgc_code
), expected AS (
  SELECT city_mun_psgc_code,
         CAST(COALESCE(SUM(CASE WHEN usable OR zero_annex THEN learner_count ELSE 0 END), 0) AS BIGINT) AS eligible_learners,
         CAST(COALESCE(SUM(CASE WHEN usable AND learner_count IS NOT NULL THEN teacher_count ELSE 0 END), 0) AS BIGINT)
           AS teachers
  FROM rows GROUP BY city_mun_psgc_code
), type_refs AS (
  SELECT lgu_type, CAST(SUM(eligible_learners) AS DOUBLE) / NULLIF(SUM(approved_teacher_count), 0) AS ratio
  FROM c WHERE input_issue_reason IS NULL GROUP BY lgu_type
), outlier_rule AS (
  SELECT *,
         COALESCE(outlier_flag AND (relative_pressure_without_outliers IS NULL
           OR (relative_pressure > 1.0) <> (relative_pressure_without_outliers > 1.0)), FALSE) AS expected_changes
  FROM c
)
SELECT
  (SELECT COUNT(*) FROM c) AS rows, (SELECT COUNT(*) FROM regular) AS expected_rows,
  (SELECT COUNT(*) - COUNT(DISTINCT city_mun_psgc_code) FROM c) AS duplicate_keys,
  (SELECT COUNT(*) FROM c FULL OUTER JOIN regular USING (city_mun_psgc_code)
    WHERE c.city_mun_psgc_code IS NULL OR regular.city_mun_psgc_code IS NULL) AS lgu_mismatch,
  (SELECT COUNT(*) FROM c LEFT JOIN expected e USING (city_mun_psgc_code)
    WHERE c.eligible_learners IS DISTINCT FROM COALESCE(e.eligible_learners, 0)
       OR c.approved_teacher_count IS DISTINCT FROM COALESCE(e.teachers, 0)) AS gold_mismatch,
  (SELECT COUNT(*) FROM c LEFT JOIN outliers o USING (city_mun_psgc_code)
    WHERE c.outlier_school_level_count IS DISTINCT FROM COALESCE(o.outlier_levels, 0)
       OR c.outlier_flag IS DISTINCT FROM (c.outlier_school_level_count > 0)) AS outlier_count_mismatch,
  (SELECT COUNT_IF((input_issue_reason IS NULL) <> COALESCE(offered_school_level_count > 0
    AND learners_per_teacher IS NOT NULL AND incomplete_enrollment_school_level_count = 0
    AND school_coverage_pct >= 90 AND learner_coverage_pct >= 90, FALSE)) FROM c) AS input_issue_mismatch,
  (SELECT COUNT(*) FROM c LEFT JOIN type_refs r USING (lgu_type)
    WHERE (c.national_same_type_ratio IS NULL) <> (r.ratio IS NULL)
       OR (c.national_same_type_ratio IS NOT NULL AND r.ratio IS NOT NULL
           AND ABS(c.national_same_type_ratio - r.ratio) > 1e-9)) AS pooled_reference_mismatch,
  (SELECT COUNT_IF((approved_teacher_count = 0 AND learners_per_teacher IS NOT NULL)
    OR (approved_teacher_count > 0
      AND ABS(learners_per_teacher - eligible_learners * 1.0 / approved_teacher_count) > 1e-9)
    OR (approved_teacher_count_without_outliers = 0 AND learners_per_teacher_without_outliers IS NOT NULL)
    OR (approved_teacher_count_without_outliers > 0
      AND ABS(learners_per_teacher_without_outliers
        - eligible_learners_without_outliers * 1.0 / approved_teacher_count_without_outliers) > 1e-9)
    OR eligible_learners_without_outliers > eligible_learners
    OR approved_teacher_count_without_outliers > approved_teacher_count) FROM c) AS ratio_mismatch,
  (SELECT COUNT_IF(outlier_changes_classification IS DISTINCT FROM expected_changes
    OR quality_issue_reason IS DISTINCT FROM COALESCE(input_issue_reason,
      CASE WHEN expected_changes THEN 'school-level outlier changes the classification' END)) FROM outlier_rule)
    AS outlier_rule_mismatch,
  (SELECT COUNT_IF((school_coverage_pct IS NOT NULL AND (school_coverage_pct < 0 OR school_coverage_pct > 100))
    OR (learner_coverage_pct IS NOT NULL AND (learner_coverage_pct < 0 OR learner_coverage_pct > 100))
    OR ((school_coverage_pct < 90 OR learner_coverage_pct < 90) AND classification <> 'Data Review')
    OR (quality_issue_reason IS NOT NULL AND classification <> 'Data Review')
    OR (quality_issue_reason IS NULL AND relative_pressure > 1 AND classification <> 'Above Reference')
    OR (quality_issue_reason IS NULL AND relative_pressure <= 1 AND classification <> 'At or Below Reference')) FROM c)
    AS classification_mismatch,
  (SELECT COUNT(*) FROM schools WHERE active = 1 AND psgc_match_status <> 'matched') AS unplaced_active_schools,
  (SELECT COALESCE(SUM(learners), 0) FROM schools WHERE active = 1 AND psgc_match_status <> 'matched')
    AS unplaced_public_learners;
SET VARIABLE analytics_gate_owner_sql = 'ALTER TABLE ' || session.analytics_gate_summary || ' OWNER TO `reached-hq`';
EXECUTE IMMEDIATE analytics_gate_owner_sql;

INSERT INTO edu_access.`01-control`.data_quality_results
  (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, NULL, 'ap3_teacher_pressure', 'analytics', 'edu_access.06-analytics.ap3_teacher_pressure_candidate',
       check_name, status, expected, actual, current_timestamp(), :code_revision
FROM (
  SELECT 'rows_match_regular_lgus' AS check_name, CASE WHEN rows = expected_rows THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(expected_rows AS STRING) AS expected, CAST(rows AS STRING) AS actual FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'key_unique', CASE WHEN duplicate_keys = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(duplicate_keys AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'lgu_membership_reconciles', CASE WHEN lgu_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(lgu_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'numerator_denominator_reconcile', CASE WHEN gold_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(gold_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'outlier_school_levels_reconcile', CASE WHEN outlier_count_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(outlier_count_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'input_issue_valid', CASE WHEN input_issue_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(input_issue_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'same_type_reference_pools_clean_lgus', CASE WHEN pooled_reference_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(pooled_reference_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'ratio_arithmetic', CASE WHEN ratio_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(ratio_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'outlier_review_rule', CASE WHEN outlier_rule_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(outlier_rule_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'classification_valid', CASE WHEN classification_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(classification_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'unplaced_active_public_schools', CASE WHEN unplaced_active_schools = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(unplaced_active_schools AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'unplaced_public_learners', CASE WHEN unplaced_public_learners = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(unplaced_public_learners AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
) AS checks;

-- Every check is recorded, so the summary is no longer needed, whether the gate passes or fails.
DROP TABLE IF EXISTS IDENTIFIER(session.analytics_gate_summary);

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Analytics gate failed for ap3_teacher_pressure: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s)') ELSE 1 END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'ap3_teacher_pressure' AND layer = 'analytics' AND status = 'FAIL'
  AND checked_at_utc >= session.analytics_gate_started_at_utc;

CREATE OR REPLACE TABLE edu_access.`06-analytics`.ap3_teacher_pressure USING DELTA AS
SELECT * FROM edu_access.`06-analytics`.ap3_teacher_pressure_candidate;
COMMENT ON TABLE edu_access.`06-analytics`.ap3_teacher_pressure IS 'AP3 pooled teacher pressure by regular LGU, with same-type reference and quality gate.';
ALTER TABLE edu_access.`06-analytics`.ap3_teacher_pressure OWNER TO `reached-hq`;
