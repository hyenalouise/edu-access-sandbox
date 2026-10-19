DECLARE OR REPLACE VARIABLE gold_gate_started_at_utc TIMESTAMP;
SET VARIABLE gold_gate_started_at_utc = current_timestamp();

CREATE OR REPLACE TEMPORARY VIEW dim_education_level_gate_summary AS
SELECT
  COUNT(*) AS dimension_rows,
  COUNT(*) - COUNT(DISTINCT education_level_code) AS duplicate_keys,
  COUNT_IF(education_level_code IS NULL OR education_level_name IS NULL) AS null_required_values,
  COUNT_IF((education_level_code = 'ES' AND education_level_name <> 'Elementary School')
    OR (education_level_code = 'JHS' AND education_level_name <> 'Junior High School')
    OR (education_level_code = 'SHS' AND education_level_name <> 'Senior High School')
    OR education_level_code NOT IN ('ES', 'JHS', 'SHS')) AS invalid_members
FROM edu_access.`05-gold`.dim_education_level_candidate;

INSERT INTO edu_access.`01-control`.data_quality_results (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, NULL, 'dim_education_level', 'gold', 'edu_access.05-gold.dim_education_level', check_name, status, expected, actual, current_timestamp(), :code_revision
FROM (
  SELECT 'three_members' AS check_name, CASE WHEN dimension_rows = 3 THEN 'PASS' ELSE 'FAIL' END AS status, '3' AS expected, CAST(dimension_rows AS STRING) AS actual FROM dim_education_level_gate_summary
  UNION ALL SELECT 'key_unique', CASE WHEN duplicate_keys = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(duplicate_keys AS STRING) FROM dim_education_level_gate_summary
  UNION ALL SELECT 'required_values_not_null', CASE WHEN null_required_values = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(null_required_values AS STRING) FROM dim_education_level_gate_summary
  UNION ALL SELECT 'members_match_contract', CASE WHEN invalid_members = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(invalid_members AS STRING) FROM dim_education_level_gate_summary
) AS results;

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Gold gate failed for dim_education_level: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s)') END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'dim_education_level' AND layer = 'gold' AND status = 'FAIL' AND checked_at_utc >= session.gold_gate_started_at_utc;

CREATE OR REPLACE TABLE edu_access.`05-gold`.dim_education_level USING DELTA AS
SELECT * FROM edu_access.`05-gold`.dim_education_level_candidate;

ALTER TABLE edu_access.`05-gold`.dim_education_level OWNER TO `reached-hq`;
