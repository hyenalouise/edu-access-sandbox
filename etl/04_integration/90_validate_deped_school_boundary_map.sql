-- Integration gate for deped_psgc_coordinates (#217): the public-school boundary map.
--
-- The job task after the build. It checks deped_school_boundary_map_candidate against its inputs, one row per
-- check in data_quality_results (layer 'integration'). On any FAIL it records the run 'failed' and stops before
-- publishing, so deped_school_boundary_map keeps the last map that passed. Otherwise it copies the candidate to
-- the map table and records the run 'succeeded'.
-- FAIL: a Silver row missing, repeated or added; a point, flag or lineage value that differs from Silver; a city
-- other than the school map's matched city for that school year; a boundary_status outside the five values, or
-- one that does not follow its inputs (no_usable_point exactly when coordinate_flag is set; no_matched_city
-- exactly when an unflagged school has no matched city; inside or outside only when that city has a boundary,
-- no_boundary only when it has none); an adm3_pcode on a row that is not inside, or one that is not a boundary
-- of its city in the release used; a release other than the latest; a missing reason or lineage value.
-- WARN: schools whose point is outside their city's boundary (likely misplaced, profile S-1).
-- Counts only (PASS): schools per status, and the share inside among the schools tested.
-- The point-in-boundary result itself is not recomputed here, to run the spatial work once per refresh;
-- tests/test_integration_school_boundary.py checks it on known shapes. Results hold counts, never row values.

DECLARE OR REPLACE VARIABLE integration_gate_started_at_utc TIMESTAMP;
SET VARIABLE integration_gate_started_at_utc = current_timestamp();

INSERT INTO edu_access.`01-control`.data_quality_results
  (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, CAST(NULL AS STRING), 'deped_psgc_coordinates', 'integration', 'edu_access.04-integration.deped_school_boundary_map_candidate',
       check_name, status, expected, actual, current_timestamp(), :code_revision
FROM (
WITH loc AS (SELECT * FROM edu_access.`03-silver`.deped_psgc_coordinates_clean),
m AS (SELECT * FROM edu_access.`04-integration`.deped_school_boundary_map_candidate),
city AS (
  SELECT school_year, school_id, psgc_code AS city_mun_psgc_code
  FROM edu_access.`04-integration`.deped_school_psgc_map
  WHERE geographic_level = 'city_mun' AND match_status = 'matched'
),
hdx_release AS (SELECT MAX(source_reference_date) AS source_reference_date FROM edu_access.`04-integration`.hdx_adm3_psgc_map),
boundary AS (
  SELECT m2.psgc_code AS city_mun_psgc_code, m2.adm3_pcode
  FROM edu_access.`04-integration`.hdx_adm3_psgc_map AS m2
  JOIN hdx_release AS r ON r.source_reference_date = m2.source_reference_date
  JOIN edu_access.`03-silver`.hdx_adm3_clean AS h ON h.adm3_pcode = m2.adm3_pcode AND h.valid_on = m2.source_reference_date
  WHERE m2.match_status = 'matched' AND h.geometry_is_valid
),
bounded_city AS (SELECT DISTINCT city_mun_psgc_code FROM boundary),
inputs AS (
  SELECT m.*, c.city_mun_psgc_code AS expected_city, bc.city_mun_psgc_code IS NOT NULL AS has_boundary,
         b.adm3_pcode IS NOT NULL AS adm3_in_city
  FROM m
  LEFT JOIN city AS c ON c.school_year = m.school_year AND c.school_id = m.school_id
  LEFT JOIN bounded_city AS bc ON bc.city_mun_psgc_code = c.city_mun_psgc_code
  LEFT JOIN boundary AS b ON b.adm3_pcode = m.adm3_pcode AND b.city_mun_psgc_code = c.city_mun_psgc_code
),
stats AS (
  SELECT
    (SELECT COUNT(*) FROM loc) AS loc_rows,
    (SELECT COUNT(*) FROM m) AS map_rows,
    (SELECT COUNT(DISTINCT source_row_ref) FROM m) AS map_refs,
    (SELECT COALESCE(COUNT_IF(source_row_ref IS DISTINCT FROM school_year || '/' || school_id), 0) FROM m) AS bad_ref,
    (SELECT COUNT(*) FROM loc LEFT JOIN m ON m.school_year = loc.school_year AND m.school_id = loc.school_id
      WHERE m.school_id IS NULL) AS missing_rows,
    (SELECT COUNT(*) FROM m JOIN loc ON loc.school_year = m.school_year AND loc.school_id = m.school_id
      WHERE m.longitude IS DISTINCT FROM loc.longitude OR m.latitude IS DISTINCT FROM loc.latitude
         OR m.coordinate_flag IS DISTINCT FROM loc.coordinate_flag OR m.batch_id IS DISTINCT FROM loc.batch_id
         OR m.source_sha256 IS DISTINCT FROM loc.source_sha256 OR m.source_row_number IS DISTINCT FROM loc.source_row_number) AS changed_rows,
    (SELECT COALESCE(COUNT_IF(city_mun_psgc_code IS DISTINCT FROM expected_city), 0) FROM inputs) AS city_mismatches,
    (SELECT COALESCE(COUNT_IF(boundary_status IS NULL OR boundary_status NOT IN ('inside', 'outside', 'no_usable_point', 'no_matched_city', 'no_boundary')), 0) FROM m) AS bad_status,
    (SELECT COALESCE(COUNT_IF((coordinate_flag IS NOT NULL) <> (boundary_status = 'no_usable_point')
                              OR (coordinate_flag IS NULL AND (expected_city IS NULL) <> (boundary_status = 'no_matched_city'))
                              OR (coordinate_flag IS NULL AND expected_city IS NOT NULL
                                  AND (boundary_status IN ('inside', 'outside')) <> has_boundary)), 0) FROM inputs) AS status_mismatches,
    (SELECT COALESCE(COUNT_IF((adm3_pcode IS NOT NULL) <> (boundary_status = 'inside')
                              OR (adm3_pcode IS NOT NULL AND NOT adm3_in_city)), 0) FROM inputs) AS adm3_mismatches,
    (SELECT COALESCE(COUNT_IF(hdx_release IS DISTINCT FROM (SELECT source_reference_date FROM hdx_release)), 0) FROM m) AS other_release_rows,
    (SELECT COALESCE(COUNT_IF(source_id IS DISTINCT FROM 'deped_psgc_coordinates' OR reason IS NULL OR batch_id IS NULL OR source_sha256 IS NULL
                              OR source_row_number IS NULL OR run_id IS NULL OR built_at_utc IS NULL OR code_revision IS NULL), 0) FROM m) AS missing_lineage,
    (SELECT COALESCE(COUNT_IF(run_id IS NULL OR run_id <> :run_id), 0) FROM m) AS other_run_rows,
    (SELECT COALESCE(COUNT_IF(boundary_status = 'inside'), 0) FROM m) AS status_inside,
    (SELECT COALESCE(COUNT_IF(boundary_status = 'outside'), 0) FROM m) AS status_outside,
    (SELECT COALESCE(COUNT_IF(boundary_status = 'no_usable_point'), 0) FROM m) AS status_no_usable_point,
    (SELECT COALESCE(COUNT_IF(boundary_status = 'no_matched_city'), 0) FROM m) AS status_no_matched_city,
    (SELECT COALESCE(COUNT_IF(boundary_status = 'no_boundary'), 0) FROM m) AS status_no_boundary
),
checks AS (
  SELECT 'inputs_present' AS check_name, CASE WHEN loc_rows > 0 THEN 'PASS' ELSE 'FAIL' END AS status, '> 0 location rows' AS expected, CAST(loc_rows AS STRING) AS actual FROM stats
  UNION ALL SELECT 'rows_reconcile', CASE WHEN map_rows = loc_rows THEN 'PASS' ELSE 'FAIL' END, CAST(loc_rows AS STRING), CAST(map_rows AS STRING) FROM stats
  UNION ALL SELECT 'source_rows_not_dropped', CASE WHEN missing_rows = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(missing_rows AS STRING) FROM stats
  UNION ALL SELECT 'one_row_per_source_row', CASE WHEN map_refs = map_rows AND bad_ref = 0 THEN 'PASS' ELSE 'FAIL' END, CAST(map_rows AS STRING), CAST(map_refs - bad_ref AS STRING) FROM stats
  UNION ALL SELECT 'locations_unchanged', CASE WHEN changed_rows = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(changed_rows AS STRING) FROM stats
  UNION ALL SELECT 'city_matches_school_map', CASE WHEN city_mismatches = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(city_mismatches AS STRING) FROM stats
  UNION ALL SELECT 'boundary_status_allowed', CASE WHEN bad_status = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_status AS STRING) FROM stats
  UNION ALL SELECT 'boundary_status_follows_inputs', CASE WHEN status_mismatches = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(status_mismatches AS STRING) FROM stats
  UNION ALL SELECT 'boundary_feature_in_city', CASE WHEN adm3_mismatches = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(adm3_mismatches AS STRING) FROM stats
  UNION ALL SELECT 'hdx_release_is_latest', CASE WHEN other_release_rows = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(other_release_rows AS STRING) FROM stats
  UNION ALL SELECT 'lineage_complete', CASE WHEN missing_lineage = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(missing_lineage AS STRING) FROM stats
  UNION ALL SELECT 'rows_built_by_this_run', CASE WHEN other_run_rows = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(other_run_rows AS STRING) FROM stats
  UNION ALL SELECT 'schools_outside_boundary', CASE WHEN status_outside = 1997 THEN 'PASS' ELSE 'WARN' END, '1997 (profiled baseline)', CAST(status_outside AS STRING) FROM stats
  UNION ALL SELECT 'schools_inside_boundary', 'PASS', CAST(NULL AS STRING), CAST(status_inside AS STRING) FROM stats
  UNION ALL SELECT 'schools_no_usable_point', 'PASS', CAST(NULL AS STRING), CAST(status_no_usable_point AS STRING) FROM stats
  UNION ALL SELECT 'schools_no_matched_city', 'PASS', CAST(NULL AS STRING), CAST(status_no_matched_city AS STRING) FROM stats
  UNION ALL SELECT 'schools_no_boundary', 'PASS', CAST(NULL AS STRING), CAST(status_no_boundary AS STRING) FROM stats
  UNION ALL SELECT 'inside_rate_percent', 'PASS', CAST(NULL AS STRING),
                   CAST(CASE WHEN status_inside + status_outside = 0 THEN 0 ELSE ROUND(100.0 * status_inside / (status_inside + status_outside), 2) END AS STRING) FROM stats
)
SELECT * FROM checks
) AS results;

-- A failed build: record it before stopping. The map table is not touched.
MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (
  SELECT :run_id AS run_id, COUNT_IF(status = 'FAIL') AS fails
  FROM edu_access.`01-control`.data_quality_results
  WHERE run_id = :run_id AND source_id = 'deped_psgc_coordinates' AND layer = 'integration'
    AND checked_at_utc >= session.integration_gate_started_at_utc
) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'integration_build' AND t.source_id = 'deped_psgc_coordinates'
WHEN MATCHED AND s.fails > 0 THEN UPDATE SET
  status = 'failed', finished_at_utc = current_timestamp(), failure_stage = 'gate',
  error_message = CAST(s.fails AS STRING) || ' FAIL result(s) in data_quality_results';

SELECT CASE WHEN COUNT(*) > 0
            THEN raise_error('Integration gate failed for deped_psgc_coordinates: ' || CAST(COUNT(*) AS STRING)
                             || ' FAIL result(s) in data_quality_results for run ' || :run_id)
       END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'deped_psgc_coordinates' AND layer = 'integration' AND status = 'FAIL'
  AND checked_at_utc >= session.integration_gate_started_at_utc;

-- Every check passed: publish, then record the run 'succeeded'.
CREATE OR REPLACE TABLE edu_access.`04-integration`.deped_school_boundary_map USING DELTA AS
SELECT * FROM edu_access.`04-integration`.deped_school_boundary_map_candidate;

ALTER TABLE edu_access.`04-integration`.deped_school_boundary_map OWNER TO `reached-hq`;

MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (SELECT :run_id AS run_id) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'integration_build' AND t.source_id = 'deped_psgc_coordinates'
WHEN MATCHED THEN UPDATE SET
  status = 'succeeded', finished_at_utc = current_timestamp(), failure_stage = NULL, error_message = NULL;
