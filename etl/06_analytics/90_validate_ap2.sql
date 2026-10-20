-- ap2 publication gate; a failure leaves the last valid output unchanged.
-- the one-row summary is written once to a table named for this run and dropped after the checks are recorded:
-- read many times as a temporary view, the same pattern made Databricks SQL fail with INTERNAL_ERROR (c64e949, #202).
-- FAIL: rows, keys or LGUs that differ from dim_city_municipality, school counts, learners, rooms or outlier counts
-- that differ from a recount from Gold, wrong ratio or coverage arithmetic, an assessment that does not follow the
-- 90% learner-coverage gate, a percentile that differs from PERCENT_RANK over the assessed LGUs, or a wrong high flag.
-- WARN: active public schools and learners not placed in a city or municipality.
DECLARE OR REPLACE VARIABLE analytics_gate_started_at_utc TIMESTAMP;
SET VARIABLE analytics_gate_started_at_utc = current_timestamp();
DECLARE OR REPLACE VARIABLE analytics_gate_summary STRING;
SET VARIABLE analytics_gate_summary = '`edu_access`.`06-analytics`.`ap2_classroom_pressure_gate_summary_r_' || sha2(:run_id, 256) || '`';
DECLARE OR REPLACE VARIABLE analytics_gate_owner_sql STRING;

CREATE OR REPLACE TABLE IDENTIFIER(session.analytics_gate_summary) USING DELTA COMMENT 'Internal unpublished one-row summary for one ap2_classroom_pressure gate. The gate drops it once its checks are recorded in data_quality_results.' AS
WITH c AS (
  SELECT * FROM edu_access.`06-analytics`.ap2_classroom_pressure_candidate
), regular AS (
  SELECT * FROM edu_access.`05-gold`.dim_city_municipality WHERE member_type = 'regular'
), enrollment AS (
  SELECT school_id, city_mun_psgc_code, MIN(psgc_match_status) AS psgc_match_status,
         MAX(CASE WHEN is_offered AND learner_count > 0 THEN 1 ELSE 0 END) AS active,
         COUNT_IF(is_offered AND learner_count IS NULL) AS incomplete,
         COUNT_IF(is_offered) > 0 AND COUNT_IF(is_offered AND learner_count IS NOT NULL) = 0 AS blank,
         SUM(CASE WHEN is_offered AND learner_count IS NOT NULL THEN learner_count ELSE 0 END) AS learners
  FROM edu_access.`05-gold`.fact_school_enrollment
  WHERE school_year = '2023-24' AND sector = 'Public'
  GROUP BY school_id, city_mun_psgc_code
), schools AS (
  SELECT e.*, r.lgu_type, k.instructional_classrooms_total AS rooms,
         e.active = 1 AND e.incomplete = 0 AND k.instructional_classrooms_total > 0 AS in_ratio
  FROM enrollment e
  JOIN regular r USING (city_mun_psgc_code)
  LEFT JOIN edu_access.`05-gold`.fact_school_classroom_capacity k
    ON k.school_id = e.school_id AND k.school_year = '2023-24'
  WHERE e.psgc_match_status = 'matched'
), fences AS (
  SELECT lgu_type,
         PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY CAST(learners AS DOUBLE) / rooms) AS q1,
         PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY CAST(learners AS DOUBLE) / rooms) AS q3
  FROM schools WHERE in_ratio GROUP BY lgu_type
), expected AS (
  SELECT s.city_mun_psgc_code,
         COUNT_IF(s.active = 1) AS active_schools,
         COUNT_IF(s.in_ratio) AS ratio_schools,
         COUNT_IF(s.active = 1 AND s.incomplete > 0) AS incomplete_schools,
         COUNT_IF(s.blank) AS blank_schools,
         SUM(CASE WHEN s.active = 1 AND s.incomplete = 0 THEN s.learners ELSE 0 END) AS enrollment,
         SUM(CASE WHEN s.in_ratio THEN s.learners ELSE 0 END) AS eligible_learners,
         SUM(CASE WHEN s.in_ratio THEN s.rooms ELSE 0 END) AS rooms,
         COUNT_IF(s.in_ratio AND CAST(s.learners AS DOUBLE) / s.rooms > f.q3 + 3 * (f.q3 - f.q1)) AS outlier_schools
  FROM schools s LEFT JOIN fences f USING (lgu_type)
  GROUP BY s.city_mun_psgc_code
), ranks AS (
  SELECT city_mun_psgc_code,
         PERCENT_RANK() OVER (PARTITION BY lgu_type ORDER BY learners_per_classroom) AS type_pct,
         PERCENT_RANK() OVER (ORDER BY learners_per_classroom) AS national_pct
  FROM c WHERE is_assessed
)
SELECT
  (SELECT COUNT(*) FROM c) AS rows, (SELECT COUNT(*) FROM regular) AS expected_rows,
  (SELECT COUNT(*) - COUNT(DISTINCT city_mun_psgc_code) FROM c) AS duplicate_keys,
  (SELECT COUNT(*) FROM c FULL OUTER JOIN regular USING (city_mun_psgc_code)
    WHERE c.city_mun_psgc_code IS NULL OR regular.city_mun_psgc_code IS NULL) AS lgu_mismatch,
  (SELECT COUNT(*) FROM c LEFT JOIN expected e USING (city_mun_psgc_code)
    WHERE c.active_public_school_count IS DISTINCT FROM COALESCE(e.active_schools, 0)
       OR c.ratio_school_count IS DISTINCT FROM COALESCE(e.ratio_schools, 0)
       OR c.incomplete_enrollment_school_count IS DISTINCT FROM COALESCE(e.incomplete_schools, 0)
       OR c.blank_enrollment_school_count IS DISTINCT FROM COALESCE(e.blank_schools, 0)
       OR c.public_school_enrollment IS DISTINCT FROM CAST(COALESCE(e.enrollment, 0) AS BIGINT)
       OR c.eligible_learners IS DISTINCT FROM CAST(COALESCE(e.eligible_learners, 0) AS BIGINT)
       OR c.reported_instructional_classrooms IS DISTINCT FROM CAST(COALESCE(e.rooms, 0) AS BIGINT)
       OR c.outlier_school_count IS DISTINCT FROM COALESCE(e.outlier_schools, 0)
       OR c.outlier_flag IS DISTINCT FROM (c.outlier_school_count > 0)) AS gold_mismatch,
  (SELECT COALESCE(COUNT_IF(
       (reported_instructional_classrooms = 0 AND learners_per_classroom IS NOT NULL)
    OR (reported_instructional_classrooms > 0
      AND ABS(learners_per_classroom - eligible_learners * 1.0 / reported_instructional_classrooms) > 1e-9)
    OR (public_school_enrollment > 0
      AND ABS(learner_coverage_pct - 100.0 * eligible_learners / public_school_enrollment) > 1e-9)
    OR (active_public_school_count + blank_enrollment_school_count > 0
      AND ABS(school_coverage_pct - 100.0 * ratio_school_count
        / (active_public_school_count + blank_enrollment_school_count)) > 1e-9)), 0) FROM c) AS arithmetic_mismatch,
  (SELECT COALESCE(COUNT_IF(is_assessed IS DISTINCT FROM (not_assessed_reason IS NULL)
    OR is_assessed IS DISTINCT FROM COALESCE(active_public_school_count > 0 AND learners_per_classroom IS NOT NULL
      AND learner_coverage_pct >= 90, FALSE)), 0) FROM c) AS assessment_mismatch,
  (SELECT COUNT(*) FROM c LEFT JOIN ranks r USING (city_mun_psgc_code)
    WHERE (c.within_type_percentile IS NULL) <> (r.type_pct IS NULL)
       OR (c.national_percentile IS NULL) <> (r.national_pct IS NULL)
       OR ABS(c.within_type_percentile - r.type_pct) > 1e-9
       OR ABS(c.national_percentile - r.national_pct) > 1e-9) AS percentile_mismatch,
  (SELECT COALESCE(COUNT_IF(is_high IS DISTINCT FROM COALESCE(within_type_percentile >= 0.9, FALSE)
    OR is_high_nationally IS DISTINCT FROM COALESCE(national_percentile >= 0.9, FALSE)), 0) FROM c) AS high_mismatch,
  (SELECT COUNT(*) FROM enrollment WHERE active = 1 AND psgc_match_status <> 'matched') AS unplaced_active_schools,
  (SELECT COALESCE(SUM(learners), 0) FROM enrollment WHERE active = 1 AND psgc_match_status <> 'matched')
    AS unplaced_public_learners,
  (SELECT COALESCE(COUNT_IF(is_high), 0) FROM c) AS high_lgus,
  (SELECT COALESCE(SUM(outlier_school_count), 0) FROM c) AS outlier_schools;
SET VARIABLE analytics_gate_owner_sql = 'ALTER TABLE ' || session.analytics_gate_summary || ' OWNER TO `reached-hq`';
EXECUTE IMMEDIATE analytics_gate_owner_sql;

INSERT INTO edu_access.`01-control`.data_quality_results
  (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, NULL, 'ap2_classroom_pressure', 'analytics', 'edu_access.06-analytics.ap2_classroom_pressure_candidate',
       check_name, status, expected, actual, current_timestamp(), :code_revision
FROM (
  SELECT 'rows_match_regular_lgus' AS check_name, CASE WHEN rows = expected_rows THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(expected_rows AS STRING) AS expected, CAST(rows AS STRING) AS actual FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'key_unique', CASE WHEN duplicate_keys = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(duplicate_keys AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'lgu_membership_reconciles', CASE WHEN lgu_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(lgu_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'schools_learners_rooms_reconcile', CASE WHEN gold_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(gold_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'ratio_and_coverage_arithmetic', CASE WHEN arithmetic_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(arithmetic_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'coverage_gate_valid', CASE WHEN assessment_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(assessment_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'percentile_is_percent_rank', CASE WHEN percentile_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(percentile_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'high_at_90th_percentile', CASE WHEN high_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(high_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'unplaced_active_public_schools', CASE WHEN unplaced_active_schools = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(unplaced_active_schools AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'unplaced_public_learners', CASE WHEN unplaced_public_learners = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(unplaced_public_learners AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'lgus_high', 'PASS', CAST(NULL AS STRING), CAST(high_lgus AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'outlier_schools', 'PASS', CAST(NULL AS STRING), CAST(outlier_schools AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
) AS checks;

-- Every check is recorded, so the summary is no longer needed, whether the gate passes or fails.
DROP TABLE IF EXISTS IDENTIFIER(session.analytics_gate_summary);

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Analytics gate failed for ap2_classroom_pressure: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s)') ELSE 1 END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'ap2_classroom_pressure' AND layer = 'analytics' AND status = 'FAIL'
  AND checked_at_utc >= session.analytics_gate_started_at_utc;

CREATE OR REPLACE TABLE edu_access.`06-analytics`.ap2_classroom_pressure USING DELTA AS
SELECT * FROM edu_access.`06-analytics`.ap2_classroom_pressure_candidate;
COMMENT ON TABLE edu_access.`06-analytics`.ap2_classroom_pressure IS 'AP2 learners per reported instructional room by regular LGU, SY 2023-24, ranked within LGU type (D-057).';
ALTER TABLE edu_access.`06-analytics`.ap2_classroom_pressure OWNER TO `reached-hq`;
