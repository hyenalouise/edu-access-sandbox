-- ap3 publication gate; a failure leaves the last valid output unchanged.
-- the one-row summary is written once to a table named for this run and dropped after the checks are recorded:
-- read many times as a temporary view, the same pattern made Databricks SQL fail with INTERNAL_ERROR (c64e949, #202).
-- FAIL: rows, keys or LGUs that differ from dim_city_municipality, any level's schools, learners, teachers or
-- outlier counts that differ from a recount from Gold, wrong ratio or coverage arithmetic, a level gate that does not
-- follow the 90% learner-coverage rule, a level percentile, highest level or re-ranked percentile that differs from
-- D-057's two-step PERCENT_RANK, or an assessment or high flag that does not follow it.
-- WARN: active public schools and learners not placed in a city or municipality.
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
         COUNT_IF(is_offered) > 0 AND COUNT_IF(is_offered AND learner_count IS NOT NULL) = 0 AS blank,
         SUM(CASE WHEN is_offered AND learner_count IS NOT NULL THEN learner_count ELSE 0 END) AS learners
  FROM edu_access.`05-gold`.fact_school_enrollment
  WHERE school_year = '2023-24' AND sector = 'Public'
  GROUP BY school_id
), rows AS (
  SELECT e.city_mun_psgc_code, r.lgu_type, e.school_id, e.education_level_code, e.learner_count, t.teacher_count,
         COALESCE(t.teacher_count > 0, FALSE) AND e.learner_count IS NOT NULL AS usable,
         COALESCE(e.annex_status = 'Annex/Extension School' AND t.teacher_count = 0, FALSE)
           AND e.learner_count IS NOT NULL AS zero_annex
  FROM edu_access.`05-gold`.fact_school_enrollment e
  JOIN schools a ON a.school_id = e.school_id AND (a.active = 1 OR a.blank)
  JOIN regular r ON r.city_mun_psgc_code = e.city_mun_psgc_code
  LEFT JOIN edu_access.`05-gold`.fact_school_teacher_capacity t
    ON t.school_id = e.school_id AND t.school_year = e.school_year AND t.education_level_code = e.education_level_code
  WHERE e.school_year = '2023-24' AND e.sector = 'Public' AND e.psgc_match_status = 'matched' AND e.is_offered
), fences AS (
  SELECT lgu_type, education_level_code,
         PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY CAST(learner_count AS DOUBLE) / teacher_count) AS q1,
         PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY CAST(learner_count AS DOUBLE) / teacher_count) AS q3
  FROM rows WHERE usable GROUP BY lgu_type, education_level_code
), expected AS (
  SELECT r.city_mun_psgc_code, r.education_level_code,
         COUNT(*) AS offered, COUNT_IF(r.learner_count IS NULL) AS incomplete,
         COUNT_IF(r.usable) AS usable_schools, COUNT_IF(r.zero_annex) AS zero_annex_schools,
         SUM(r.learner_count) AS enrollment,
         SUM(CASE WHEN r.usable OR r.zero_annex THEN r.learner_count END) AS eligible,
         SUM(CASE WHEN r.usable THEN r.teacher_count END) AS teachers,
         COUNT_IF(r.usable AND CAST(r.learner_count AS DOUBLE) / r.teacher_count > f.q3 + 3 * (f.q3 - f.q1)) AS outliers
  FROM rows r LEFT JOIN fences f USING (lgu_type, education_level_code)
  GROUP BY r.city_mun_psgc_code, r.education_level_code
), actual AS (
  SELECT city_mun_psgc_code, lgu_type, 'ES' AS education_level_code, 1 AS level_order,
         es_offered_school_count AS offered, es_incomplete_school_count AS incomplete,
         es_usable_teacher_school_count AS usable_schools, es_zero_teacher_annex_school_count AS zero_annex_schools,
         es_public_school_enrollment AS enrollment, es_eligible_learners AS eligible, es_teacher_count AS teachers,
         es_outlier_school_count AS outliers, es_learners_per_teacher AS ratio, es_school_coverage_pct AS school_cov,
         es_learner_coverage_pct AS learner_cov, es_passes_gate AS passes, es_within_type_percentile AS type_pct,
         es_national_percentile AS national_pct
  FROM c
  UNION ALL
  SELECT city_mun_psgc_code, lgu_type, 'JHS', 2, jhs_offered_school_count, jhs_incomplete_school_count,
         jhs_usable_teacher_school_count, jhs_zero_teacher_annex_school_count, jhs_public_school_enrollment,
         jhs_eligible_learners, jhs_teacher_count, jhs_outlier_school_count, jhs_learners_per_teacher,
         jhs_school_coverage_pct, jhs_learner_coverage_pct, jhs_passes_gate, jhs_within_type_percentile, jhs_national_percentile
  FROM c
  UNION ALL
  SELECT city_mun_psgc_code, lgu_type, 'SHS', 3, shs_offered_school_count, shs_incomplete_school_count,
         shs_usable_teacher_school_count, shs_zero_teacher_annex_school_count, shs_public_school_enrollment,
         shs_eligible_learners, shs_teacher_count, shs_outlier_school_count, shs_learners_per_teacher,
         shs_school_coverage_pct, shs_learner_coverage_pct, shs_passes_gate, shs_within_type_percentile, shs_national_percentile
  FROM c
), level_ranks AS (
  SELECT city_mun_psgc_code, education_level_code,
         PERCENT_RANK() OVER (PARTITION BY lgu_type, education_level_code ORDER BY ratio) AS type_pct,
         PERCENT_RANK() OVER (PARTITION BY education_level_code ORDER BY ratio) AS national_pct
  FROM actual WHERE passes
), best AS (
  SELECT city_mun_psgc_code,
         MAX(CASE WHEN type_order = 1 THEN education_level_code END) AS level,
         MAX(CASE WHEN type_order = 1 THEN type_pct END) AS level_pct,
         MAX(CASE WHEN national_order = 1 THEN education_level_code END) AS national_level,
         MAX(CASE WHEN national_order = 1 THEN national_pct END) AS national_level_pct
  FROM (
    SELECT a.city_mun_psgc_code, a.education_level_code, a.type_pct, a.national_pct,
           ROW_NUMBER() OVER (PARTITION BY a.city_mun_psgc_code ORDER BY a.type_pct DESC, a.level_order) AS type_order,
           ROW_NUMBER() OVER (PARTITION BY a.city_mun_psgc_code ORDER BY a.national_pct DESC, a.level_order) AS national_order
    FROM actual a WHERE a.passes
  ) AS p
  GROUP BY city_mun_psgc_code
), reranks AS (
  SELECT b.city_mun_psgc_code, b.level, b.level_pct, b.national_level, b.national_level_pct,
         PERCENT_RANK() OVER (PARTITION BY r.lgu_type ORDER BY b.level_pct) AS type_pct,
         PERCENT_RANK() OVER (ORDER BY b.national_level_pct) AS national_pct
  FROM best b JOIN regular r USING (city_mun_psgc_code)
)
SELECT
  (SELECT COUNT(*) FROM c) AS rows, (SELECT COUNT(*) FROM regular) AS expected_rows,
  (SELECT COUNT(*) - COUNT(DISTINCT city_mun_psgc_code) FROM c) AS duplicate_keys,
  (SELECT COUNT(*) FROM c FULL OUTER JOIN regular USING (city_mun_psgc_code)
    WHERE c.city_mun_psgc_code IS NULL OR regular.city_mun_psgc_code IS NULL) AS lgu_mismatch,
  (SELECT COUNT(*) FROM actual a
    LEFT JOIN expected e ON e.city_mun_psgc_code = a.city_mun_psgc_code AND e.education_level_code = a.education_level_code
    WHERE a.offered IS DISTINCT FROM COALESCE(e.offered, 0)
       OR a.incomplete IS DISTINCT FROM COALESCE(e.incomplete, 0)
       OR a.usable_schools IS DISTINCT FROM COALESCE(e.usable_schools, 0)
       OR a.zero_annex_schools IS DISTINCT FROM COALESCE(e.zero_annex_schools, 0)
       OR a.enrollment IS DISTINCT FROM CAST(COALESCE(e.enrollment, 0) AS BIGINT)
       OR a.eligible IS DISTINCT FROM CAST(COALESCE(e.eligible, 0) AS BIGINT)
       OR a.teachers IS DISTINCT FROM CAST(COALESCE(e.teachers, 0) AS BIGINT)
       OR a.outliers IS DISTINCT FROM COALESCE(e.outliers, 0)) AS gold_mismatch,
  (SELECT COALESCE(COUNT_IF((teachers = 0 AND ratio IS NOT NULL)
    OR (teachers > 0 AND ABS(ratio - eligible * 1.0 / teachers) > 1e-9)
    OR (offered > 0 AND ABS(school_cov - 100.0 * usable_schools / offered) > 1e-9)
    OR (enrollment > 0 AND ABS(learner_cov - 100.0 * eligible / enrollment) > 1e-9)), 0) FROM actual) AS arithmetic_mismatch,
  (SELECT COALESCE(COUNT_IF(passes IS DISTINCT FROM COALESCE(offered > 0 AND ratio IS NOT NULL AND learner_cov >= 90, FALSE)), 0)
    FROM actual) AS level_gate_mismatch,
  (SELECT COUNT(*) FROM actual a LEFT JOIN level_ranks r USING (city_mun_psgc_code, education_level_code)
    WHERE (a.type_pct IS NULL) <> (r.type_pct IS NULL) OR (a.national_pct IS NULL) <> (r.national_pct IS NULL)
       OR ABS(a.type_pct - r.type_pct) > 1e-9 OR ABS(a.national_pct - r.national_pct) > 1e-9) AS level_percentile_mismatch,
  (SELECT COUNT(*) FROM c LEFT JOIN reranks r USING (city_mun_psgc_code)
    WHERE c.highest_level IS DISTINCT FROM r.level
       OR c.highest_level_percentile IS DISTINCT FROM r.level_pct
       OR c.highest_level_nationally IS DISTINCT FROM r.national_level
       OR c.highest_level_national_percentile IS DISTINCT FROM r.national_level_pct
       OR (c.within_type_percentile IS NULL) <> (r.type_pct IS NULL)
       OR (c.national_percentile IS NULL) <> (r.national_pct IS NULL)
       OR ABS(c.within_type_percentile - r.type_pct) > 1e-9
       OR ABS(c.national_percentile - r.national_pct) > 1e-9) AS rerank_mismatch,
  (SELECT COALESCE(COUNT_IF(is_high IS DISTINCT FROM COALESCE(within_type_percentile >= 0.9, FALSE)
    OR is_high_nationally IS DISTINCT FROM COALESCE(national_percentile >= 0.9, FALSE)
    OR is_assessed IS DISTINCT FROM (is_high OR (offered_level_count > 0 AND passing_level_count = offered_level_count))
    OR is_assessed IS DISTINCT FROM (not_assessed_reason IS NULL)
    OR is_assessed_nationally IS DISTINCT FROM
      (is_high_nationally OR (offered_level_count > 0 AND passing_level_count = offered_level_count))
    OR offered_level_count IS DISTINCT FROM CAST(COALESCE(es_offered_school_count > 0, FALSE) AS INT)
      + CAST(COALESCE(jhs_offered_school_count > 0, FALSE) AS INT) + CAST(COALESCE(shs_offered_school_count > 0, FALSE) AS INT)
    OR passing_level_count IS DISTINCT FROM CAST(COALESCE(es_passes_gate, FALSE) AS INT)
      + CAST(COALESCE(jhs_passes_gate, FALSE) AS INT) + CAST(COALESCE(shs_passes_gate, FALSE) AS INT)), 0) FROM c)
    AS assessment_mismatch,
  (SELECT COUNT(*) FROM schools WHERE active = 1 AND psgc_match_status <> 'matched') AS unplaced_active_schools,
  (SELECT COALESCE(SUM(learners), 0) FROM schools WHERE active = 1 AND psgc_match_status <> 'matched')
    AS unplaced_public_learners,
  (SELECT COALESCE(COUNT_IF(is_high), 0) FROM c) AS high_lgus,
  (SELECT COALESCE(SUM(outliers), 0) FROM actual) AS outlier_school_levels;
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
  UNION ALL SELECT 'levels_reconcile_with_gold', CASE WHEN gold_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(gold_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'ratio_and_coverage_arithmetic', CASE WHEN arithmetic_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(arithmetic_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'level_coverage_gate_valid', CASE WHEN level_gate_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(level_gate_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'level_percentile_is_percent_rank', CASE WHEN level_percentile_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(level_percentile_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'highest_level_reranked', CASE WHEN rerank_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(rerank_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'assessment_and_high_valid', CASE WHEN assessment_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(assessment_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'unplaced_active_public_schools', CASE WHEN unplaced_active_schools = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(unplaced_active_schools AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'unplaced_public_learners', CASE WHEN unplaced_public_learners = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(unplaced_public_learners AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'lgus_high', 'PASS', CAST(NULL AS STRING), CAST(high_lgus AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'outlier_school_levels', 'PASS', CAST(NULL AS STRING), CAST(outlier_school_levels AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
) AS checks;

-- Every check is recorded, so the summary is no longer needed, whether the gate passes or fails.
DROP TABLE IF EXISTS IDENTIFIER(session.analytics_gate_summary);

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Analytics gate failed for ap3_teacher_pressure: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s)') ELSE 1 END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'ap3_teacher_pressure' AND layer = 'analytics' AND status = 'FAIL'
  AND checked_at_utc >= session.analytics_gate_started_at_utc;

CREATE OR REPLACE TABLE edu_access.`06-analytics`.ap3_teacher_pressure USING DELTA AS
SELECT * FROM edu_access.`06-analytics`.ap3_teacher_pressure_candidate;
COMMENT ON TABLE edu_access.`06-analytics`.ap3_teacher_pressure IS 'AP3 learners per teacher by level (ES, JHS, SHS) by regular LGU, SY 2023-24, re-ranked within LGU type (D-057).';
ALTER TABLE edu_access.`06-analytics`.ap3_teacher_pressure OWNER TO `reached-hq`;
