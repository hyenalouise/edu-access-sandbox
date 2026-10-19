-- Gold gate for fact_school_year_source_availability: exactly one row per school year and approved DepEd
-- source, no unknown source, has_data reconciled to the Silver source periods, and no Silver year missing
-- from dim_school_year.

DECLARE OR REPLACE VARIABLE gold_gate_started_at_utc TIMESTAMP;
SET VARIABLE gold_gate_started_at_utc = current_timestamp();

INSERT INTO edu_access.`01-control`.data_quality_results
  (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, CAST(NULL AS STRING), 'fact_school_year_source_availability', 'gold', 'edu_access.05-gold.fact_school_year_source_availability_candidate',
       check_name, status, expected, actual, current_timestamp(), :code_revision
FROM (
WITH c AS (SELECT * FROM edu_access.`05-gold`.fact_school_year_source_availability_candidate),
present AS (
  SELECT DISTINCT school_year, 'deped_enrollment' AS source_id FROM edu_access.`03-silver`.deped_enrollment_clean
  UNION ALL
  SELECT DISTINCT school_year, 'deped_facilities' FROM edu_access.`03-silver`.deped_facilities_clean
  UNION ALL
  SELECT DISTINCT school_year, 'deped_personnel' FROM edu_access.`03-silver`.deped_personnel_clean
),
s AS (
  SELECT
    (SELECT COUNT(*) FROM edu_access.`05-gold`.dim_school_year) AS years,
    (SELECT COUNT(*) FROM present AS p LEFT JOIN edu_access.`05-gold`.dim_school_year AS y ON y.school_year = p.school_year
     WHERE y.school_year IS NULL) AS silver_year_not_in_dim,
    (SELECT COUNT(*) FROM c LEFT JOIN present AS p ON p.school_year = c.school_year AND p.source_id = c.source_id
     WHERE c.has_data IS DISTINCT FROM (p.source_id IS NOT NULL)) AS has_data_mismatch,
    COUNT(*) AS rows_built,
    COUNT(DISTINCT school_year || '/' || source_id) AS keys_built,
    COALESCE(COUNT_IF(source_id NOT IN ('deped_enrollment', 'deped_facilities', 'deped_personnel') OR source_id IS NULL), 0) AS unknown_sources,
    COALESCE(COUNT_IF(has_data), 0) AS with_data
  FROM c
)
SELECT 'one_row_per_year_and_source' AS check_name,
       CASE WHEN rows_built = years * 3 AND keys_built = rows_built THEN 'PASS' ELSE 'FAIL' END AS status,
       CAST(years * 3 AS STRING) AS expected, CAST(rows_built AS STRING) AS actual FROM s
UNION ALL SELECT 'approved_sources_only', CASE WHEN unknown_sources = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(unknown_sources AS STRING) FROM s
UNION ALL SELECT 'has_data_reconciles', CASE WHEN has_data_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(has_data_mismatch AS STRING) FROM s
UNION ALL SELECT 'silver_years_in_dim', CASE WHEN silver_year_not_in_dim = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(silver_year_not_in_dim AS STRING) FROM s
UNION ALL SELECT 'year_source_pairs_with_data', 'PASS', 'count', CAST(with_data AS STRING) FROM s
) AS results;

MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (SELECT :run_id AS run_id, COUNT_IF(status = 'FAIL') AS fails FROM edu_access.`01-control`.data_quality_results
       WHERE run_id = :run_id AND source_id = 'fact_school_year_source_availability' AND layer = 'gold'
         AND checked_at_utc >= session.gold_gate_started_at_utc) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'gold_build' AND t.source_id = 'fact_school_year_source_availability'
WHEN MATCHED AND s.fails > 0 THEN UPDATE SET status = 'failed', finished_at_utc = current_timestamp(),
  failure_stage = 'gate', error_message = CAST(s.fails AS STRING) || ' FAIL result(s) in data_quality_results';

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Gold gate failed for fact_school_year_source_availability: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s)') END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'fact_school_year_source_availability' AND layer = 'gold' AND status = 'FAIL'
  AND checked_at_utc >= session.gold_gate_started_at_utc;

CREATE OR REPLACE TABLE edu_access.`05-gold`.fact_school_year_source_availability USING DELTA AS SELECT * FROM edu_access.`05-gold`.fact_school_year_source_availability_candidate;
ALTER TABLE edu_access.`05-gold`.fact_school_year_source_availability OWNER TO `reached-hq`;

MERGE INTO edu_access.`01-control`.pipeline_runs AS t USING (SELECT :run_id AS run_id) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'gold_build' AND t.source_id = 'fact_school_year_source_availability'
WHEN MATCHED THEN UPDATE SET status = 'succeeded', finished_at_utc = current_timestamp(), failure_stage = NULL, error_message = NULL;
