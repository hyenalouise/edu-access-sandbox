DECLARE OR REPLACE VARIABLE gold_gate_started_at_utc TIMESTAMP;
SET VARIABLE gold_gate_started_at_utc = current_timestamp();

CREATE OR REPLACE TEMPORARY VIEW dim_school_gate_summary AS
WITH source_schools AS (
  SELECT DISTINCT school_id FROM edu_access.`03-silver`.deped_enrollment_clean
), latest_names AS (
  SELECT school_id, school_name
  FROM (
    SELECT school_id, school_name, ROW_NUMBER() OVER (PARTITION BY school_id ORDER BY school_year DESC) AS name_rank
    FROM edu_access.`03-silver`.deped_enrollment_clean
    WHERE school_name IS NOT NULL
  ) WHERE name_rank = 1
), dimension AS (
  SELECT * FROM edu_access.`05-gold`.dim_school_candidate
)
SELECT
  (SELECT COUNT(*) FROM source_schools) AS source_rows,
  (SELECT COUNT(*) FROM dimension) AS dimension_rows,
  (SELECT COUNT(*) - COUNT(DISTINCT school_id) FROM dimension) AS duplicate_keys,
  (SELECT COUNT_IF(school_id IS NULL) FROM dimension) AS null_keys,
  (SELECT COUNT_IF(school_name IS NULL) FROM dimension) AS missing_names,
  (SELECT COUNT(*) FROM dimension AS d LEFT JOIN latest_names AS n ON n.school_id = d.school_id WHERE d.school_name IS DISTINCT FROM n.school_name) AS wrong_latest_names;

INSERT INTO edu_access.`01-control`.data_quality_results (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, NULL, 'dim_school', 'gold', 'edu_access.05-gold.dim_school', check_name, status, expected, actual, current_timestamp(), :code_revision
FROM (
  SELECT 'rows_reconcile' AS check_name, CASE WHEN dimension_rows = source_rows THEN 'PASS' ELSE 'FAIL' END AS status, CAST(source_rows AS STRING) AS expected, CAST(dimension_rows AS STRING) AS actual FROM dim_school_gate_summary
  UNION ALL SELECT 'key_unique', CASE WHEN duplicate_keys = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(duplicate_keys AS STRING) FROM dim_school_gate_summary
  UNION ALL SELECT 'key_not_null', CASE WHEN null_keys = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(null_keys AS STRING) FROM dim_school_gate_summary
  UNION ALL SELECT 'latest_name_preserved', CASE WHEN wrong_latest_names = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(wrong_latest_names AS STRING) FROM dim_school_gate_summary
  UNION ALL SELECT 'school_name_available', CASE WHEN missing_names = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(missing_names AS STRING) FROM dim_school_gate_summary
) AS results;

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Gold gate failed for dim_school: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s)') END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'dim_school' AND layer = 'gold' AND status = 'FAIL' AND checked_at_utc >= session.gold_gate_started_at_utc;

CREATE OR REPLACE TABLE edu_access.`05-gold`.dim_school USING DELTA AS
SELECT * FROM edu_access.`05-gold`.dim_school_candidate;

ALTER TABLE edu_access.`05-gold`.dim_school OWNER TO `reached-hq`;
