-- Gold gate for dim_school_year: checks the candidate, records every result in data_quality_results,
-- and publishes the candidate only when no check FAILs, so a failed build keeps the last good table.

DECLARE OR REPLACE VARIABLE gold_gate_started_at_utc TIMESTAMP;
SET VARIABLE gold_gate_started_at_utc = current_timestamp();

INSERT INTO edu_access.`01-control`.data_quality_results
  (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, CAST(NULL AS STRING), 'dim_school_year', 'gold', 'edu_access.05-gold.dim_school_year_candidate',
       check_name, status, expected, actual, current_timestamp(), :code_revision
FROM (
WITH c AS (SELECT * FROM edu_access.`05-gold`.dim_school_year_candidate),
s AS (
  SELECT
    (SELECT COUNT(DISTINCT school_year) FROM edu_access.`03-silver`.deped_enrollment_clean) AS silver_years,
    COUNT(*) AS rows_built,
    COUNT(DISTINCT school_year) AS keys_built,
    COALESCE(COUNT_IF(school_year IS NULL OR start_year IS NULL OR end_year IS NULL), 0) AS null_fields,
    COALESCE(COUNT_IF(NOT regexp_like(school_year, '^[0-9]{4}-[0-9]{2}$')), 0) AS bad_format,
    COALESCE(COUNT_IF(substr(CAST(end_year AS STRING), 3, 2) <> substr(school_year, 6, 2)), 0) AS bad_end_year
  FROM c
)
SELECT 'rows_present' AS check_name, CASE WHEN rows_built > 0 THEN 'PASS' ELSE 'FAIL' END AS status,
       '> 0' AS expected, CAST(rows_built AS STRING) AS actual FROM s
UNION ALL SELECT 'one_row_per_school_year', CASE WHEN keys_built = rows_built THEN 'PASS' ELSE 'FAIL' END,
                 CAST(rows_built AS STRING), CAST(keys_built AS STRING) FROM s
UNION ALL SELECT 'every_silver_year_present', CASE WHEN keys_built = silver_years THEN 'PASS' ELSE 'FAIL' END,
                 CAST(silver_years AS STRING), CAST(keys_built AS STRING) FROM s
UNION ALL SELECT 'no_null_fields', CASE WHEN null_fields = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(null_fields AS STRING) FROM s
UNION ALL SELECT 'school_year_format', CASE WHEN bad_format = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_format AS STRING) FROM s
UNION ALL SELECT 'end_year_matches_label', CASE WHEN bad_end_year = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_end_year AS STRING) FROM s
) AS results;

MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (SELECT :run_id AS run_id, COUNT_IF(status = 'FAIL') AS fails FROM edu_access.`01-control`.data_quality_results
       WHERE run_id = :run_id AND source_id = 'dim_school_year' AND layer = 'gold'
         AND checked_at_utc >= session.gold_gate_started_at_utc) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'gold_build' AND t.source_id = 'dim_school_year'
WHEN MATCHED AND s.fails > 0 THEN UPDATE SET status = 'failed', finished_at_utc = current_timestamp(),
  failure_stage = 'gate', error_message = CAST(s.fails AS STRING) || ' FAIL result(s) in data_quality_results';

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Gold gate failed for dim_school_year: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s)') END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'dim_school_year' AND layer = 'gold' AND status = 'FAIL'
  AND checked_at_utc >= session.gold_gate_started_at_utc;

CREATE OR REPLACE TABLE edu_access.`05-gold`.dim_school_year USING DELTA AS SELECT * FROM edu_access.`05-gold`.dim_school_year_candidate;
ALTER TABLE edu_access.`05-gold`.dim_school_year OWNER TO `reached-hq`;

MERGE INTO edu_access.`01-control`.pipeline_runs AS t USING (SELECT :run_id AS run_id) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'gold_build' AND t.source_id = 'dim_school_year'
WHEN MATCHED THEN UPDATE SET status = 'succeeded', finished_at_utc = current_timestamp(), failure_stage = NULL, error_message = NULL;
