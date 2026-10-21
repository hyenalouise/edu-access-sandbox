-- AP3 publication gate; recomputes level totals, coverage, ratios and descriptive reference statuses from Gold.
-- the one-row summary is written once to a table named for this run and dropped after the checks are recorded:
-- read many times as a temporary view, the same pattern made Databricks SQL fail with INTERNAL_ERROR (c64e949, #202).
-- FAIL: rows, keys or LGUs that differ from dim_city_municipality, any level's schools, learners or teachers that
-- differ from a recount from Gold, wrong ratio or coverage arithmetic, a level gate that does not follow the 90%
-- learner-coverage rule, or an assessment, reference value or reference status that does not follow D-061.
-- WARN: active public schools and learners not placed in a city or municipality.
DECLARE OR REPLACE VARIABLE analytics_gate_started_at_utc TIMESTAMP;
SET VARIABLE analytics_gate_started_at_utc = current_timestamp();
DECLARE OR REPLACE VARIABLE analytics_gate_summary STRING;
SET VARIABLE analytics_gate_summary = '`edu_access`.`06-analytics`.`ap3_teacher_pressure_gate_summary_r_' || sha2(:run_id, 256) || '`';
DECLARE OR REPLACE VARIABLE analytics_gate_owner_sql STRING;

CREATE OR REPLACE TABLE IDENTIFIER(session.analytics_gate_summary) USING DELTA COMMENT 'Internal unpublished one-row summary for one ap3 gate.' AS
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
), source_rows AS (
  SELECT e.city_mun_psgc_code, e.school_id, e.education_level_code, e.learner_count, t.teacher_count,
         COALESCE(t.teacher_count > 0, FALSE) AND e.learner_count IS NOT NULL AS usable,
         COALESCE(e.annex_status = 'Annex/Extension School' AND t.teacher_count = 0, FALSE)
           AND e.learner_count IS NOT NULL AS zero_annex
  FROM edu_access.`05-gold`.fact_school_enrollment e
  JOIN schools a ON a.school_id = e.school_id AND (a.active = 1 OR a.blank)
  JOIN regular r ON r.city_mun_psgc_code = e.city_mun_psgc_code
  LEFT JOIN edu_access.`05-gold`.fact_school_teacher_capacity t
    ON t.school_id = e.school_id AND t.school_year = e.school_year AND t.education_level_code = e.education_level_code
  WHERE e.school_year = '2023-24' AND e.sector = 'Public' AND e.psgc_match_status = 'matched' AND e.is_offered
), expected AS (
  SELECT city_mun_psgc_code, education_level_code,
         COUNT(*) AS offered, COUNT_IF(learner_count IS NULL) AS incomplete,
         COUNT_IF(usable) AS usable_schools, COUNT_IF(zero_annex) AS zero_annex_schools,
         SUM(learner_count) AS enrollment,
         SUM(CASE WHEN usable OR zero_annex THEN learner_count END) AS eligible,
         SUM(CASE WHEN usable THEN teacher_count END) AS teachers
  FROM source_rows GROUP BY city_mun_psgc_code, education_level_code
), actual AS (
  SELECT city_mun_psgc_code, 'ES' AS education_level_code,
         es_offered_school_count AS offered, es_incomplete_school_count AS incomplete,
         es_usable_teacher_school_count AS usable_schools, es_zero_teacher_annex_school_count AS zero_annex_schools,
         es_public_school_enrollment AS enrollment, es_eligible_learners AS eligible, es_teacher_count AS teachers,
         es_learners_per_teacher AS ratio, es_school_coverage_pct AS school_cov,
         es_learner_coverage_pct AS learner_cov, es_passes_gate AS passes
  FROM c
  UNION ALL
  SELECT city_mun_psgc_code, 'JHS', jhs_offered_school_count, jhs_incomplete_school_count,
         jhs_usable_teacher_school_count, jhs_zero_teacher_annex_school_count, jhs_public_school_enrollment,
         jhs_eligible_learners, jhs_teacher_count, jhs_learners_per_teacher,
         jhs_school_coverage_pct, jhs_learner_coverage_pct, jhs_passes_gate
  FROM c
  UNION ALL
  SELECT city_mun_psgc_code, 'SHS', shs_offered_school_count, shs_incomplete_school_count,
         shs_usable_teacher_school_count, shs_zero_teacher_annex_school_count, shs_public_school_enrollment,
         shs_eligible_learners, shs_teacher_count, shs_learners_per_teacher,
         shs_school_coverage_pct, shs_learner_coverage_pct, shs_passes_gate
  FROM c
)
SELECT
  (SELECT COUNT(*) FROM c) AS rows, (SELECT COUNT(*) FROM regular) AS expected_rows,
  (SELECT COUNT(*) - COUNT(DISTINCT city_mun_psgc_code) FROM c) AS duplicate_keys,
  (SELECT COUNT(*) FROM c FULL OUTER JOIN regular USING (city_mun_psgc_code)
    WHERE c.city_mun_psgc_code IS NULL OR regular.city_mun_psgc_code IS NULL) AS lgu_mismatch,
  (SELECT COUNT(*) FROM actual a LEFT JOIN expected e
    ON e.city_mun_psgc_code = a.city_mun_psgc_code AND e.education_level_code = a.education_level_code
    WHERE a.offered IS DISTINCT FROM COALESCE(e.offered, 0)
       OR a.incomplete IS DISTINCT FROM COALESCE(e.incomplete, 0)
       OR a.usable_schools IS DISTINCT FROM COALESCE(e.usable_schools, 0)
       OR a.zero_annex_schools IS DISTINCT FROM COALESCE(e.zero_annex_schools, 0)
       OR a.enrollment IS DISTINCT FROM CAST(COALESCE(e.enrollment, 0) AS BIGINT)
       OR a.eligible IS DISTINCT FROM CAST(COALESCE(e.eligible, 0) AS BIGINT)
       OR a.teachers IS DISTINCT FROM CAST(COALESCE(e.teachers, 0) AS BIGINT)) AS gold_mismatch,
  (SELECT COALESCE(COUNT_IF((teachers = 0 AND ratio IS NOT NULL)
    OR (teachers > 0 AND ABS(ratio - eligible * 1.0 / teachers) > 1e-9)
    OR (offered > 0 AND ABS(school_cov - 100.0 * usable_schools / offered) > 1e-9)
    OR (enrollment > 0 AND ABS(learner_cov - 100.0 * eligible / enrollment) > 1e-9)), 0) FROM actual)
    AS arithmetic_mismatch,
  (SELECT COALESCE(COUNT_IF(passes IS DISTINCT FROM COALESCE(offered > 0 AND ratio IS NOT NULL
    AND learner_cov >= 90, FALSE)), 0) FROM actual) AS level_gate_mismatch,
  (SELECT COALESCE(COUNT_IF(
       is_assessed IS DISTINCT FROM (offered_level_count > 0 AND passing_level_count = offered_level_count)
    OR is_assessed IS DISTINCT FROM (not_assessed_reason IS NULL)
    OR offered_level_count IS DISTINCT FROM CAST(COALESCE(es_offered_school_count > 0, FALSE) AS INT)
      + CAST(COALESCE(jhs_offered_school_count > 0, FALSE) AS INT)
      + CAST(COALESCE(shs_offered_school_count > 0, FALSE) AS INT)
    OR passing_level_count IS DISTINCT FROM CAST(COALESCE(es_passes_gate, FALSE) AS INT)
      + CAST(COALESCE(jhs_passes_gate, FALSE) AS INT)
      + CAST(COALESCE(shs_passes_gate, FALSE) AS INT)), 0) FROM c) AS assessment_mismatch,
  (SELECT COALESCE(COUNT_IF(es_benchmark_max_learners_per_teacher IS DISTINCT FROM 35.0
    OR es_benchmark_status IS DISTINCT FROM CASE WHEN es_offered_school_count = 0 THEN 'not applicable'
      WHEN NOT es_passes_gate THEN 'not assessed' WHEN es_learners_per_teacher > 35
      THEN 'above historical study reference' ELSE 'at or below historical study reference' END
    OR jhs_benchmark_max_learners_per_teacher IS DISTINCT FROM 36.0
    OR jhs_benchmark_status IS DISTINCT FROM CASE WHEN jhs_offered_school_count = 0 THEN 'not applicable'
      WHEN NOT jhs_passes_gate THEN 'not assessed' WHEN jhs_learners_per_teacher > 36
      THEN 'above derived deployment comparison' ELSE 'at or below derived deployment comparison' END
    OR shs_benchmark_max_learners_per_teacher IS DISTINCT FROM 80.0 / 3
    OR shs_benchmark_status IS DISTINCT FROM CASE WHEN shs_offered_school_count = 0 THEN 'not applicable'
      WHEN NOT shs_passes_gate THEN 'not assessed' WHEN shs_learners_per_teacher > 80.0 / 3
      THEN 'above derived deployment comparison' ELSE 'at or below derived deployment comparison' END
    OR benchmark_status IS DISTINCT FROM CASE
      WHEN es_offered_school_count = 0 AND jhs_offered_school_count = 0 AND shs_offered_school_count = 0
        THEN 'not assessed'
      WHEN (es_passes_gate AND es_learners_per_teacher > 35)
        OR (jhs_passes_gate AND jhs_learners_per_teacher > 36)
        OR (shs_passes_gate AND shs_learners_per_teacher > 80.0 / 3) THEN 'pressure signal identified'
      WHEN (es_offered_school_count > 0 AND NOT es_passes_gate)
        OR (jhs_offered_school_count > 0 AND NOT jhs_passes_gate)
        OR (shs_offered_school_count > 0 AND NOT shs_passes_gate) THEN 'not fully assessed'
      ELSE 'no pressure signal identified' END), 0) FROM c) AS benchmark_mismatch,
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
  UNION ALL SELECT 'levels_reconcile_with_gold', CASE WHEN gold_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(gold_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'ratio_and_coverage_arithmetic', CASE WHEN arithmetic_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(arithmetic_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'level_coverage_gate_valid', CASE WHEN level_gate_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(level_gate_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'assessment_status_valid', CASE WHEN assessment_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(assessment_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'teacher_reference_context_valid', CASE WHEN benchmark_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(benchmark_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'unplaced_active_public_schools', CASE WHEN unplaced_active_schools = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(unplaced_active_schools AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'unplaced_public_learners', CASE WHEN unplaced_public_learners = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(unplaced_public_learners AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
) AS checks;

DROP TABLE IF EXISTS IDENTIFIER(session.analytics_gate_summary);

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Analytics gate failed for ap3_teacher_pressure: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s)') ELSE 1 END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'ap3_teacher_pressure' AND layer = 'analytics' AND status = 'FAIL'
  AND checked_at_utc >= session.analytics_gate_started_at_utc;

CREATE OR REPLACE TABLE edu_access.`06-analytics`.ap3_teacher_pressure USING DELTA AS
SELECT * FROM edu_access.`06-analytics`.ap3_teacher_pressure_candidate;
COMMENT ON TABLE edu_access.`06-analytics`.ap3_teacher_pressure IS 'AP3 descriptive learners per reported teaching personnel by level, with historical and derived comparison context, not an official teacher shortage or priority.';
ALTER TABLE edu_access.`06-analytics`.ap3_teacher_pressure OWNER TO `reached-hq`;
