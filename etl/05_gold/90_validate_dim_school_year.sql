DECLARE OR REPLACE VARIABLE gold_gate_started_at_utc TIMESTAMP;
SET VARIABLE gold_gate_started_at_utc = current_timestamp();

CREATE OR REPLACE TEMPORARY VIEW dim_school_year_gate_summary AS
WITH dimension AS (
  SELECT * FROM edu_access.`05-gold`.dim_school_year
)
SELECT
  (SELECT COUNT(DISTINCT school_year) FROM edu_access.`03-silver`.deped_enrollment_clean) AS source_years,
  (SELECT COUNT(*) FROM dimension) AS dimension_rows,
  (SELECT COUNT(*) - COUNT(DISTINCT school_year) FROM dimension) AS duplicate_keys,
  (SELECT COUNT_IF(school_year IS NULL) FROM dimension) AS null_keys,
  (SELECT COUNT_IF(NOT has_enrollment OR start_year IS NULL OR end_year <> start_year + 1 OR school_year <> CONCAT(CAST(start_year AS STRING), '-', RIGHT(CAST(end_year AS STRING), 2))) FROM dimension) AS invalid_year_rows,
  (SELECT COUNT(*) FROM dimension AS d WHERE d.has_facilities <> EXISTS (SELECT 1 FROM edu_access.`03-silver`.deped_facilities_clean AS f WHERE f.school_year = d.school_year)) AS wrong_facilities_flags,
  (SELECT COUNT(*) FROM dimension AS d WHERE d.has_personnel <> EXISTS (SELECT 1 FROM edu_access.`03-silver`.deped_personnel_clean AS p WHERE p.school_year = d.school_year)) AS wrong_personnel_flags;

INSERT INTO edu_access.`01-control`.data_quality_results (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, NULL, 'dim_school_year', 'gold', 'edu_access.05-gold.dim_school_year', check_name, status, expected, actual, current_timestamp(), :code_revision
FROM (
  SELECT 'rows_reconcile' AS check_name, CASE WHEN dimension_rows = source_years THEN 'PASS' ELSE 'FAIL' END AS status, CAST(source_years AS STRING) AS expected, CAST(dimension_rows AS STRING) AS actual FROM dim_school_year_gate_summary
  UNION ALL SELECT 'key_unique', CASE WHEN duplicate_keys = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(duplicate_keys AS STRING) FROM dim_school_year_gate_summary
  UNION ALL SELECT 'key_not_null', CASE WHEN null_keys = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(null_keys AS STRING) FROM dim_school_year_gate_summary
  UNION ALL SELECT 'school_year_consistent', CASE WHEN invalid_year_rows = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(invalid_year_rows AS STRING) FROM dim_school_year_gate_summary
  UNION ALL SELECT 'facilities_availability_correct', CASE WHEN wrong_facilities_flags = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(wrong_facilities_flags AS STRING) FROM dim_school_year_gate_summary
  UNION ALL SELECT 'personnel_availability_correct', CASE WHEN wrong_personnel_flags = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(wrong_personnel_flags AS STRING) FROM dim_school_year_gate_summary
) AS results;

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Gold gate failed for dim_school_year: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s)') END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'dim_school_year' AND layer = 'gold' AND status = 'FAIL' AND checked_at_utc >= session.gold_gate_started_at_utc;
