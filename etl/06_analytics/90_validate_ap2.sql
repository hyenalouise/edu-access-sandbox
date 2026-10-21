-- AP2 publication gate; a failure leaves the last valid output unchanged.
-- Recomputes the school-level illustrative screen and LGU affected-learner aggregation independently from Gold.
-- the one-row summary is written once to a table named for this run and dropped after the checks are recorded:
-- read many times as a temporary view, the same pattern made Databricks SQL fail with INTERNAL_ERROR (c64e949, #202).
-- FAIL: rows, keys or LGUs that differ from dim_city_municipality, school counts, learners or rooms that differ
-- from a recount from Gold, wrong ratio or coverage arithmetic, an assessment that does not follow the 90%
-- learner-coverage gate, or a school screen, affected-learner count, share or status that does not follow D-060.
-- WARN: active public schools and learners not placed in a city or municipality.
DECLARE OR REPLACE VARIABLE analytics_gate_started_at_utc TIMESTAMP;
SET VARIABLE analytics_gate_started_at_utc = current_timestamp();
DECLARE OR REPLACE VARIABLE analytics_gate_summary STRING;
SET VARIABLE analytics_gate_summary = '`edu_access`.`06-analytics`.`ap2_classroom_pressure_gate_summary_r_' || sha2(:run_id, 256) || '`';
DECLARE OR REPLACE VARIABLE analytics_gate_owner_sql STRING;

CREATE OR REPLACE TABLE IDENTIFIER(session.analytics_gate_summary) USING DELTA COMMENT 'Internal unpublished one-row summary for one ap2 gate.' AS
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
  SELECT e.*, k.instructional_classrooms_total AS rooms,
         e.active = 1 AND e.incomplete = 0 AND k.instructional_classrooms_total > 0 AS in_ratio
  FROM enrollment e
  JOIN regular r USING (city_mun_psgc_code)
  LEFT JOIN edu_access.`05-gold`.fact_school_classroom_capacity k
    ON k.school_id = e.school_id AND k.school_year = '2023-24'
  WHERE e.psgc_match_status = 'matched'
), expected AS (
  SELECT city_mun_psgc_code,
         COUNT_IF(active = 1) AS active_schools,
         COUNT_IF(active = 1 AND rooms > 0) AS usable_room_schools,
         COUNT_IF(in_ratio) AS ratio_schools,
         COUNT_IF(active = 1 AND incomplete > 0) AS incomplete_schools,
         COUNT_IF(blank) AS blank_schools,
         COUNT_IF(active = 1 AND rooms IS NULL) AS missing_room_schools,
         COUNT_IF(active = 1 AND rooms = 0) AS zero_room_schools,
         SUM(CASE WHEN active = 1 AND incomplete = 0 THEN learners ELSE 0 END) AS enrollment,
         SUM(CASE WHEN in_ratio THEN learners ELSE 0 END) AS eligible_learners,
         SUM(CASE WHEN in_ratio THEN rooms ELSE 0 END) AS rooms,
         COUNT_IF(in_ratio AND CAST(learners AS DOUBLE) / rooms >= 50) AS congested_schools,
         SUM(CASE WHEN in_ratio AND CAST(learners AS DOUBLE) / rooms >= 50 THEN learners ELSE 0 END)
           AS congested_learners
  FROM schools GROUP BY city_mun_psgc_code
)
SELECT
  (SELECT COUNT(*) FROM c) AS rows, (SELECT COUNT(*) FROM regular) AS expected_rows,
  (SELECT COUNT(*) - COUNT(DISTINCT city_mun_psgc_code) FROM c) AS duplicate_keys,
  (SELECT COUNT(*) FROM c FULL OUTER JOIN regular USING (city_mun_psgc_code)
    WHERE c.city_mun_psgc_code IS NULL OR regular.city_mun_psgc_code IS NULL) AS lgu_mismatch,
  (SELECT COUNT(*) FROM c LEFT JOIN expected e USING (city_mun_psgc_code)
    WHERE c.active_public_school_count IS DISTINCT FROM COALESCE(e.active_schools, 0)
       OR c.usable_room_school_count IS DISTINCT FROM COALESCE(e.usable_room_schools, 0)
       OR c.ratio_school_count IS DISTINCT FROM COALESCE(e.ratio_schools, 0)
       OR c.incomplete_enrollment_school_count IS DISTINCT FROM COALESCE(e.incomplete_schools, 0)
       OR c.blank_enrollment_school_count IS DISTINCT FROM COALESCE(e.blank_schools, 0)
       OR c.missing_room_school_count IS DISTINCT FROM COALESCE(e.missing_room_schools, 0)
       OR c.zero_room_school_count IS DISTINCT FROM COALESCE(e.zero_room_schools, 0)
       OR c.public_school_enrollment IS DISTINCT FROM CAST(COALESCE(e.enrollment, 0) AS BIGINT)
       OR c.eligible_learners IS DISTINCT FROM CAST(COALESCE(e.eligible_learners, 0) AS BIGINT)
       OR c.reported_instructional_classrooms IS DISTINCT FROM CAST(COALESCE(e.rooms, 0) AS BIGINT)
       OR c.congested_school_count IS DISTINCT FROM COALESCE(e.congested_schools, 0)
       OR c.learners_in_congested_schools IS DISTINCT FROM CAST(COALESCE(e.congested_learners, 0) AS BIGINT))
    AS gold_mismatch,
  (SELECT COALESCE(COUNT_IF(
       (reported_instructional_classrooms = 0 AND learners_per_classroom IS NOT NULL)
    OR (reported_instructional_classrooms > 0
      AND ABS(learners_per_classroom - eligible_learners * 1.0 / reported_instructional_classrooms) > 1e-9)
    OR (eligible_learners > 0
      AND ABS(congested_learner_share_pct - 100.0 * learners_in_congested_schools / public_school_enrollment) > 1e-9)
    OR (public_school_enrollment > 0
      AND ABS(learner_coverage_pct - 100.0 * eligible_learners / public_school_enrollment) > 1e-9)
    OR (active_public_school_count + blank_enrollment_school_count > 0
      AND ABS(school_coverage_pct - 100.0 * ratio_school_count
        / (active_public_school_count + blank_enrollment_school_count)) > 1e-9)), 0) FROM c) AS arithmetic_mismatch,
  (SELECT COALESCE(COUNT_IF(is_assessed IS DISTINCT FROM (not_assessed_reason IS NULL)
    OR is_assessed IS DISTINCT FROM COALESCE(active_public_school_count > 0 AND learners_per_classroom IS NOT NULL
      AND learner_coverage_pct >= 90, FALSE)), 0) FROM c) AS assessment_mismatch,
  (SELECT COALESCE(COUNT_IF(congestion_benchmark IS DISTINCT FROM 50.0
    OR benchmark_status IS DISTINCT FROM CASE WHEN NOT is_assessed THEN 'not assessed'
      WHEN congested_school_count > 0 THEN 'reported congestion identified'
      ELSE 'no reported congestion identified' END), 0) FROM c) AS benchmark_mismatch,
  (SELECT COUNT(*) FROM enrollment WHERE active = 1 AND psgc_match_status <> 'matched') AS unplaced_active_schools,
  (SELECT COALESCE(SUM(learners), 0) FROM enrollment WHERE active = 1 AND psgc_match_status <> 'matched')
    AS unplaced_public_learners,
  (SELECT COALESCE(SUM(congested_school_count), 0) FROM c) AS screened_congested_schools,
  (SELECT COALESCE(SUM(learners_in_congested_schools), 0) FROM c) AS screened_affected_learners;
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
  UNION ALL SELECT 'congestion_screen_valid', CASE WHEN benchmark_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(benchmark_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'unplaced_active_public_schools', CASE WHEN unplaced_active_schools = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(unplaced_active_schools AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'unplaced_public_learners', CASE WHEN unplaced_public_learners = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(unplaced_public_learners AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'screened_congested_schools', 'PASS', CAST(NULL AS STRING), CAST(screened_congested_schools AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'screened_affected_learners', 'PASS', CAST(NULL AS STRING), CAST(screened_affected_learners AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
) AS checks;

DROP TABLE IF EXISTS IDENTIFIER(session.analytics_gate_summary);

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Analytics gate failed for ap2_classroom_pressure: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s)') ELSE 1 END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'ap2_classroom_pressure' AND layer = 'analytics' AND status = 'FAIL'
  AND checked_at_utc >= session.analytics_gate_started_at_utc;

CREATE OR REPLACE TABLE edu_access.`06-analytics`.ap2_classroom_pressure USING DELTA AS
SELECT * FROM edu_access.`06-analytics`.ap2_classroom_pressure_candidate;
COMMENT ON TABLE edu_access.`06-analytics`.ap2_classroom_pressure IS 'AP2 PIDS-style illustrative school congestion screen aggregated to affected learners by regular LGU, SY 2023-24, not an official shortage.';
ALTER TABLE edu_access.`06-analytics`.ap2_classroom_pressure OWNER TO `reached-hq`;
