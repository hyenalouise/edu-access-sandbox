-- outlier school list publication gate (D-057); a failure leaves the last valid output unchanged.
-- FAIL: duplicate keys, a row at or below its fence, an unknown measure or level, or a count per LGU (and per level
-- for AP3) that differs from the outlier counts the AP2 and AP3 outputs publish. Counts only (PASS): flagged schools.
DECLARE OR REPLACE VARIABLE analytics_gate_started_at_utc TIMESTAMP;
SET VARIABLE analytics_gate_started_at_utc = current_timestamp();
DECLARE OR REPLACE VARIABLE analytics_gate_summary STRING;
SET VARIABLE analytics_gate_summary = '`edu_access`.`06-analytics`.`lgu_priority_outlier_schools_gate_summary_r_' || sha2(:run_id, 256) || '`';
DECLARE OR REPLACE VARIABLE analytics_gate_owner_sql STRING;

CREATE OR REPLACE TABLE IDENTIFIER(session.analytics_gate_summary) USING DELTA COMMENT 'Internal unpublished one-row summary for one lgu_priority_outlier_schools gate. The gate drops it once its checks are recorded in data_quality_results.' AS
WITH c AS (
  SELECT * FROM edu_access.`06-analytics`.lgu_priority_outlier_schools_candidate
), listed AS (
  SELECT city_mun_psgc_code, measure, education_level_code, COUNT(*) AS schools
  FROM c GROUP BY city_mun_psgc_code, measure, education_level_code
), published AS (
  SELECT city_mun_psgc_code, 'AP2' AS measure, 'ALL' AS education_level_code, outlier_school_count AS schools
  FROM edu_access.`06-analytics`.ap2_classroom_pressure
  UNION ALL SELECT city_mun_psgc_code, 'AP3', 'ES', es_outlier_school_count FROM edu_access.`06-analytics`.ap3_teacher_pressure
  UNION ALL SELECT city_mun_psgc_code, 'AP3', 'JHS', jhs_outlier_school_count FROM edu_access.`06-analytics`.ap3_teacher_pressure
  UNION ALL SELECT city_mun_psgc_code, 'AP3', 'SHS', shs_outlier_school_count FROM edu_access.`06-analytics`.ap3_teacher_pressure
)
SELECT
  (SELECT COUNT(*) FROM c) AS rows,
  (SELECT COUNT(*) - COUNT(DISTINCT school_id || '|' || measure || '|' || education_level_code) FROM c) AS duplicate_keys,
  (SELECT COALESCE(COUNT_IF(NOT (school_ratio > upper_fence) OR upper_fence IS NULL), 0) FROM c) AS not_above_fence,
  (SELECT COALESCE(COUNT_IF(NOT ((measure = 'AP2' AND education_level_code = 'ALL')
                                 OR (measure = 'AP3' AND education_level_code IN ('ES', 'JHS', 'SHS')))), 0) FROM c) AS bad_measure,
  (SELECT COUNT(*) FROM published AS p
     LEFT JOIN listed AS l USING (city_mun_psgc_code, measure, education_level_code)
     WHERE COALESCE(p.schools, 0) <> COALESCE(l.schools, 0)) AS count_mismatch,
  (SELECT COUNT(*) FROM listed AS l
     LEFT JOIN published AS p USING (city_mun_psgc_code, measure, education_level_code)
     WHERE p.city_mun_psgc_code IS NULL) AS unpublished_lgu,
  (SELECT COALESCE(COUNT_IF(measure = 'AP2'), 0) FROM c) AS room_outliers,
  (SELECT COALESCE(COUNT_IF(measure = 'AP3'), 0) FROM c) AS teacher_outliers;
SET VARIABLE analytics_gate_owner_sql = 'ALTER TABLE ' || session.analytics_gate_summary || ' OWNER TO `reached-hq`';
EXECUTE IMMEDIATE analytics_gate_owner_sql;

INSERT INTO edu_access.`01-control`.data_quality_results
  (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, NULL, 'lgu_priority_outlier_schools', 'analytics', 'edu_access.06-analytics.lgu_priority_outlier_schools_candidate',
       check_name, status, expected, actual, current_timestamp(), :code_revision
FROM (
  SELECT 'key_unique' AS check_name, CASE WHEN duplicate_keys = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         '0' AS expected, CAST(duplicate_keys AS STRING) AS actual FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'every_row_above_its_fence', CASE WHEN not_above_fence = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(not_above_fence AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'measure_and_level_valid', CASE WHEN bad_measure = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_measure AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'counts_match_ap2_and_ap3', CASE WHEN count_mismatch = 0 AND unpublished_lgu = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(count_mismatch + unpublished_lgu AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'room_outlier_schools', 'PASS', CAST(NULL AS STRING), CAST(room_outliers AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'teacher_outlier_school_levels', 'PASS', CAST(NULL AS STRING), CAST(teacher_outliers AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
) AS checks;

-- Every check is recorded, so the summary is no longer needed, whether the gate passes or fails.
DROP TABLE IF EXISTS IDENTIFIER(session.analytics_gate_summary);

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Analytics gate failed for lgu_priority_outlier_schools: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s)') ELSE 1 END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'lgu_priority_outlier_schools' AND layer = 'analytics' AND status = 'FAIL'
  AND checked_at_utc >= session.analytics_gate_started_at_utc;

CREATE OR REPLACE TABLE edu_access.`06-analytics`.lgu_priority_outlier_schools USING DELTA AS
SELECT * FROM edu_access.`06-analytics`.lgu_priority_outlier_schools_candidate;
COMMENT ON TABLE edu_access.`06-analytics`.lgu_priority_outlier_schools IS 'D-057 outlier school list: public schools (AP2) and school levels (AP3) above Q3 + 3 x IQR within LGU type, SY 2023-24. Flagged schools stay in every published total.';
ALTER TABLE edu_access.`06-analytics`.lgu_priority_outlier_schools OWNER TO `reached-hq`;
