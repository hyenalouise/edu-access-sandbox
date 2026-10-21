-- Gold gate for dim_school_location (#217). Checks dim_school_location_candidate against the published
-- deped_school_boundary_map it was built from and dim_school, writes every result to data_quality_results
-- (layer 'gold'), stops on any FAIL, and only then publishes dim_school_location. A FAIL keeps the last good
-- build and stops nothing else: no other task waits for this one.
--
-- FAIL: a repeated or NULL key; a row count other than the map's SY 2023-24 rows; a school not in dim_school;
-- a longitude, latitude, coordinate_flag or boundary_status that differs from the map; a boundary_status outside
-- the five values; a map run that did not succeed. The boundary test itself, and the count of schools per status,
-- are the Integration gate's (90_validate_deped_school_boundary_map.sql).

DECLARE OR REPLACE VARIABLE gold_gate_started_at_utc TIMESTAMP;
SET VARIABLE gold_gate_started_at_utc = current_timestamp();
DECLARE OR REPLACE VARIABLE gold_gate_summary STRING;
SET VARIABLE gold_gate_summary = '`edu_access`.`05-gold`.`dim_school_location_gate_summary_r_' || sha2(:run_id, 256) || '`';
DECLARE OR REPLACE VARIABLE gold_gate_owner_sql STRING;

-- The one-row summary the checks read is written to a table, once, as the other Gold gates do (read many
-- times as a temporary view, Databricks SQL's optimizer failed; dim_barangay, 2026-10-20). The table is this
-- run's own (its name holds a hash of run_id) and is dropped once the checks are recorded.
-- COUNT_IF is wrapped in COALESCE: over no rows DuckDB returns NULL, Databricks 0.
CREATE OR REPLACE TABLE IDENTIFIER(session.gold_gate_summary) USING DELTA COMMENT 'Internal unpublished one-row summary for one dim_school_location gate. The gate drops it once its checks are recorded in data_quality_results.' AS
WITH dimension AS (
  SELECT * FROM edu_access.`05-gold`.dim_school_location_candidate
),
map AS (
  SELECT school_id, longitude, latitude, coordinate_flag, boundary_status
  FROM edu_access.`04-integration`.deped_school_boundary_map WHERE school_year = '2023-24'
)
SELECT
  (SELECT COUNT(*) FROM dimension) AS dimension_rows,
  (SELECT COUNT(*) FROM map) AS source_rows,
  (SELECT COUNT(*) - COUNT(DISTINCT school_id) FROM dimension) AS duplicate_keys,
  (SELECT COALESCE(COUNT_IF(school_id IS NULL), 0) FROM dimension) AS null_keys,
  (SELECT COUNT(*) FROM dimension AS d LEFT JOIN edu_access.`05-gold`.dim_school AS s ON s.school_id = d.school_id
    WHERE s.school_id IS NULL) AS schools_not_in_dim_school,
  (SELECT COUNT(*) FROM map AS m LEFT JOIN dimension AS d ON d.school_id = m.school_id
    WHERE d.school_id IS NULL OR d.longitude IS DISTINCT FROM m.longitude OR d.latitude IS DISTINCT FROM m.latitude
       OR d.coordinate_flag IS DISTINCT FROM m.coordinate_flag OR d.boundary_status IS DISTINCT FROM m.boundary_status) AS rows_not_matching_source,
  (SELECT COALESCE(COUNT_IF(boundary_status IS NULL OR boundary_status NOT IN ('inside', 'outside', 'no_usable_point', 'no_matched_city', 'no_boundary')), 0)
    FROM dimension) AS bad_boundary_status;
SET VARIABLE gold_gate_owner_sql = 'ALTER TABLE ' || session.gold_gate_summary || ' OWNER TO `reached-hq`';
EXECUTE IMMEDIATE gold_gate_owner_sql;

INSERT INTO edu_access.`01-control`.data_quality_results (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, NULL, 'dim_school_location', 'gold', 'edu_access.05-gold.dim_school_location', check_name, status, expected, actual, current_timestamp(), :code_revision
FROM (
  SELECT 'rows_reconcile' AS check_name, CASE WHEN dimension_rows = source_rows THEN 'PASS' ELSE 'FAIL' END AS status, CAST(source_rows AS STRING) AS expected, CAST(dimension_rows AS STRING) AS actual FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'key_unique', CASE WHEN duplicate_keys = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(duplicate_keys AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'key_not_null', CASE WHEN null_keys = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(null_keys AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'school_in_dim_school', CASE WHEN schools_not_in_dim_school = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(schools_not_in_dim_school AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'values_match_source', CASE WHEN rows_not_matching_source = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(rows_not_matching_source AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'boundary_status_allowed', CASE WHEN bad_boundary_status = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_boundary_status AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
) AS results;

-- Integrity rule 1 of the metric specification: one result per distinct upstream run_id read, PASS only
-- when that run succeeded in pipeline_runs (D-025), so the build never trusts a map that did not publish.
INSERT INTO edu_access.`01-control`.data_quality_results (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, NULL, 'dim_school_location', 'gold', 'edu_access.05-gold.dim_school_location', 'upstream_run_' || u.input_table,
       CASE WHEN p.run_id IS NULL THEN 'FAIL' ELSE 'PASS' END, 'succeeded ' || u.pipeline_name, u.upstream_run_id,
       current_timestamp(), :code_revision
FROM (
  SELECT DISTINCT 'deped_school_boundary_map' AS input_table, 'integration_build' AS pipeline_name, 'deped_psgc_coordinates' AS source_id, run_id AS upstream_run_id
  FROM edu_access.`04-integration`.deped_school_boundary_map WHERE school_year = '2023-24'
) AS u
LEFT JOIN (
  SELECT DISTINCT run_id, pipeline_name, source_id
  FROM edu_access.`01-control`.pipeline_runs
  WHERE status = 'succeeded'
) AS p ON p.run_id = u.upstream_run_id AND p.pipeline_name = u.pipeline_name AND p.source_id = u.source_id;

-- Every check is recorded, so the summary is no longer needed, whether the gate passes or fails.
DROP TABLE IF EXISTS IDENTIFIER(session.gold_gate_summary);

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Gold gate failed for dim_school_location: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s) in data_quality_results for run ' || :run_id) END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'dim_school_location' AND layer = 'gold' AND status = 'FAIL'
  AND checked_at_utc >= session.gold_gate_started_at_utc;

-- Every check passed: publish.
CREATE OR REPLACE TABLE edu_access.`05-gold`.dim_school_location USING DELTA AS
SELECT * FROM edu_access.`05-gold`.dim_school_location_candidate;

COMMENT ON TABLE edu_access.`05-gold`.dim_school_location IS 'One public school with a published location (SY 2023-24, NSBI as of 2025-07-07): its point, coordinate_flag, and boundary_status (S-1 at city level, from deped_school_boundary_map). Joins dim_school on school_id and carries no PSGC code (#217).';
ALTER TABLE edu_access.`05-gold`.dim_school_location OWNER TO `reached-hq`;
