-- Gold gate for dim_school: one row per enrollment school, each named from its latest school year.

DECLARE OR REPLACE VARIABLE gold_gate_started_at_utc TIMESTAMP;
SET VARIABLE gold_gate_started_at_utc = current_timestamp();

INSERT INTO edu_access.`01-control`.data_quality_results
  (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, CAST(NULL AS STRING), 'dim_school', 'gold', 'edu_access.05-gold.dim_school_candidate',
       check_name, status, expected, actual, current_timestamp(), :code_revision
FROM (
WITH c AS (SELECT * FROM edu_access.`05-gold`.dim_school_candidate),
latest AS (
  SELECT school_id, school_name FROM (
    SELECT school_id, school_name, ROW_NUMBER() OVER (PARTITION BY school_id ORDER BY school_year DESC) AS newest
    FROM edu_access.`03-silver`.deped_enrollment_clean) AS e
  WHERE newest = 1
),
s AS (
  SELECT
    (SELECT COUNT(*) FROM latest) AS silver_schools,
    (SELECT COUNT(*) FROM c) AS rows_built,
    (SELECT COUNT(DISTINCT school_id) FROM c) AS keys_built,
    (SELECT COALESCE(COUNT_IF(school_id IS NULL), 0) FROM c) AS null_ids,
    (SELECT COALESCE(COUNT_IF(school_name IS NULL), 0) FROM c) AS null_names,
    (SELECT COUNT(*) FROM c LEFT JOIN latest AS l ON l.school_id = c.school_id
     WHERE l.school_id IS NULL OR c.school_name IS DISTINCT FROM l.school_name) AS name_mismatch
)
SELECT 'rows_present' AS check_name, CASE WHEN rows_built > 0 THEN 'PASS' ELSE 'FAIL' END AS status,
       '> 0' AS expected, CAST(rows_built AS STRING) AS actual FROM s
UNION ALL SELECT 'one_row_per_school', CASE WHEN keys_built = rows_built AND null_ids = 0 THEN 'PASS' ELSE 'FAIL' END,
                 CAST(rows_built AS STRING) || ' / 0 null', CAST(keys_built AS STRING) || ' / ' || CAST(null_ids AS STRING) || ' null' FROM s
UNION ALL SELECT 'every_enrollment_school_present', CASE WHEN rows_built = silver_schools THEN 'PASS' ELSE 'FAIL' END,
                 CAST(silver_schools AS STRING), CAST(rows_built AS STRING) FROM s
UNION ALL SELECT 'name_from_latest_year', CASE WHEN name_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(name_mismatch AS STRING) FROM s
UNION ALL SELECT 'school_name_blank', CASE WHEN null_names = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(null_names AS STRING) FROM s
) AS results;

MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (SELECT :run_id AS run_id, COUNT_IF(status = 'FAIL') AS fails FROM edu_access.`01-control`.data_quality_results
       WHERE run_id = :run_id AND source_id = 'dim_school' AND layer = 'gold'
         AND checked_at_utc >= session.gold_gate_started_at_utc) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'gold_build' AND t.source_id = 'dim_school'
WHEN MATCHED AND s.fails > 0 THEN UPDATE SET status = 'failed', finished_at_utc = current_timestamp(),
  failure_stage = 'gate', error_message = CAST(s.fails AS STRING) || ' FAIL result(s) in data_quality_results';

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Gold gate failed for dim_school: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s)') END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'dim_school' AND layer = 'gold' AND status = 'FAIL'
  AND checked_at_utc >= session.gold_gate_started_at_utc;

CREATE OR REPLACE TABLE edu_access.`05-gold`.dim_school USING DELTA AS SELECT * FROM edu_access.`05-gold`.dim_school_candidate;
ALTER TABLE edu_access.`05-gold`.dim_school OWNER TO `reached-hq`;

MERGE INTO edu_access.`01-control`.pipeline_runs AS t USING (SELECT :run_id AS run_id) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'gold_build' AND t.source_id = 'dim_school'
WHEN MATCHED THEN UPDATE SET status = 'succeeded', finished_at_utc = current_timestamp(), failure_stage = NULL, error_message = NULL;
