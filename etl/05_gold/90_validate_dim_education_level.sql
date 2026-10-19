-- Gold gate for dim_education_level: exactly ES, JHS and SHS, each named.

DECLARE OR REPLACE VARIABLE gold_gate_started_at_utc TIMESTAMP;
SET VARIABLE gold_gate_started_at_utc = current_timestamp();

INSERT INTO edu_access.`01-control`.data_quality_results
  (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, CAST(NULL AS STRING), 'dim_education_level', 'gold', 'edu_access.05-gold.dim_education_level_candidate',
       check_name, status, expected, actual, current_timestamp(), :code_revision
FROM (
WITH c AS (SELECT * FROM edu_access.`05-gold`.dim_education_level_candidate),
s AS (
  SELECT COUNT(*) AS rows_built, COUNT(DISTINCT education_level_code) AS keys_built,
         COALESCE(COUNT_IF(education_level_code NOT IN ('ES', 'JHS', 'SHS') OR education_level_code IS NULL), 0) AS bad_codes,
         COALESCE(COUNT_IF(education_level_name IS NULL), 0) AS null_names
  FROM c
)
SELECT 'three_levels' AS check_name, CASE WHEN rows_built = 3 AND keys_built = 3 AND bad_codes = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
       '3 rows: ES, JHS, SHS' AS expected,
       CAST(rows_built AS STRING) || ' rows, ' || CAST(bad_codes AS STRING) || ' other codes' AS actual FROM s
UNION ALL SELECT 'every_level_named', CASE WHEN null_names = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(null_names AS STRING) FROM s
) AS results;

MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (SELECT :run_id AS run_id, COUNT_IF(status = 'FAIL') AS fails FROM edu_access.`01-control`.data_quality_results
       WHERE run_id = :run_id AND source_id = 'dim_education_level' AND layer = 'gold'
         AND checked_at_utc >= session.gold_gate_started_at_utc) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'gold_build' AND t.source_id = 'dim_education_level'
WHEN MATCHED AND s.fails > 0 THEN UPDATE SET status = 'failed', finished_at_utc = current_timestamp(),
  failure_stage = 'gate', error_message = CAST(s.fails AS STRING) || ' FAIL result(s) in data_quality_results';

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Gold gate failed for dim_education_level: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s)') END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'dim_education_level' AND layer = 'gold' AND status = 'FAIL'
  AND checked_at_utc >= session.gold_gate_started_at_utc;

CREATE OR REPLACE TABLE edu_access.`05-gold`.dim_education_level USING DELTA AS SELECT * FROM edu_access.`05-gold`.dim_education_level_candidate;
ALTER TABLE edu_access.`05-gold`.dim_education_level OWNER TO `reached-hq`;

MERGE INTO edu_access.`01-control`.pipeline_runs AS t USING (SELECT :run_id AS run_id) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'gold_build' AND t.source_id = 'dim_education_level'
WHEN MATCHED THEN UPDATE SET status = 'succeeded', finished_at_utc = current_timestamp(), failure_stage = NULL, error_message = NULL;
