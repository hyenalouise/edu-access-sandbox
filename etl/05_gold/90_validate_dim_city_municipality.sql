-- Gold gate for dim_city_municipality. Checks dim_city_municipality_candidate against the published
-- PSGC and HDX tables it was built from, writes every result to data_quality_results (layer 'gold'),
-- stops on any FAIL, and only then publishes dim_city_municipality. A FAIL keeps the last good build.
--
-- FAIL: a repeated or NULL key, a regular member that is not a City or Mun row of the one master
-- quarter (or one missing), technical members other than exactly UNKNOWN and EXCLUDED, a region or
-- province code without its name, a class that does not fit the LGU type, land area that is not
-- positive or has no source, a unit matched by two HDX features of the latest release, and a
-- Special Geographic Area member outside its blank-level container.
-- WARN: regular members without land area (today the 8 Special Geographic Area municipalities,
-- D-052) and cities without a city class.
-- Counts only (PASS): cities, municipalities, members without a province, SGA members.

DECLARE OR REPLACE VARIABLE gold_gate_started_at_utc TIMESTAMP;
SET VARIABLE gold_gate_started_at_utc = current_timestamp();

CREATE OR REPLACE TEMPORARY VIEW dim_city_municipality_gate_summary AS
WITH psgc AS (
  SELECT * FROM edu_access.`03-silver`.psa_psgc_clean WHERE is_master_reference
),
source_units AS (
  SELECT psgc_code FROM psgc WHERE geographic_level IN ('City', 'Mun')
),
hdx_latest AS (
  SELECT psgc_code
  FROM edu_access.`04-integration`.hdx_adm3_psgc_map
  WHERE match_status = 'matched'
    AND source_reference_date = (SELECT MAX(source_reference_date) FROM edu_access.`04-integration`.hdx_adm3_psgc_map)
),
dimension AS (
  SELECT * FROM edu_access.`05-gold`.dim_city_municipality_candidate
),
regular AS (
  SELECT * FROM dimension WHERE member_type = 'regular'
)
SELECT
  (SELECT COUNT(*) FROM source_units) AS source_units,
  (SELECT COUNT(*) FROM regular) AS regular_rows,
  (SELECT COUNT(*) - COUNT(DISTINCT city_mun_psgc_code) FROM dimension) AS duplicate_keys,
  (SELECT COUNT_IF(city_mun_psgc_code IS NULL) FROM dimension) AS null_keys,
  (SELECT COUNT(*) FROM regular AS d LEFT JOIN source_units AS s ON s.psgc_code = d.city_mun_psgc_code
    WHERE s.psgc_code IS NULL) AS regular_not_in_psgc,
  (SELECT COUNT(*) FROM source_units AS s LEFT JOIN regular AS d ON d.city_mun_psgc_code = s.psgc_code
    WHERE d.city_mun_psgc_code IS NULL) AS psgc_units_missing,
  (SELECT COUNT(DISTINCT publication_period) FROM psgc) AS master_periods,
  (SELECT COUNT(*) FROM dimension AS d
    WHERE d.source_psgc_quarter IS DISTINCT FROM (SELECT MAX(publication_period) FROM psgc)) AS wrong_quarter,
  (SELECT COUNT_IF(member_type NOT IN ('regular', 'unknown', 'excluded') OR member_type IS NULL) FROM dimension) AS bad_member_type,
  (SELECT COUNT(*) FROM dimension WHERE member_type <> 'regular') AS technical_rows,
  (SELECT COUNT_IF((city_mun_psgc_code = 'UNKNOWN' AND member_type = 'unknown')
                OR (city_mun_psgc_code = 'EXCLUDED' AND member_type = 'excluded')) FROM dimension) AS expected_technical_rows,
  (SELECT COUNT_IF(region_psgc_code IS NULL OR region_name IS NULL) FROM regular) AS region_unresolved,
  (SELECT COUNT_IF(province_psgc_code IS NOT NULL AND province_name IS NULL) FROM regular) AS province_unresolved,
  (SELECT COUNT_IF(lgu_type IS NULL OR lgu_type NOT IN ('city', 'municipality')) FROM regular) AS bad_lgu_type,
  (SELECT COUNT_IF(lgu_type = 'municipality' AND city_class IS NOT NULL) FROM regular) AS municipality_with_city_class,
  (SELECT COUNT_IF(lgu_type = 'city' AND city_class IS NULL) FROM regular) AS city_without_class,
  (SELECT COUNT_IF(income_class IS NOT NULL AND income_class NOT IN ('1st', '2nd', '3rd', '4th', '5th')) FROM regular) AS bad_income_class,
  (SELECT COUNT_IF(land_area_sqkm IS NOT NULL AND land_area_sqkm <= 0) FROM dimension) AS land_area_not_positive,
  (SELECT COUNT_IF((land_area_sqkm IS NULL) <> (land_area_source IS NULL)) FROM dimension) AS land_area_source_mismatch,
  (SELECT COUNT(*) FROM (SELECT psgc_code FROM hdx_latest GROUP BY psgc_code HAVING COUNT(*) > 1) AS x) AS units_with_two_features,
  (SELECT COUNT_IF(land_area_sqkm IS NULL) FROM regular) AS regular_without_land_area,
  (SELECT COUNT(*) FROM regular AS d LEFT JOIN psgc AS p ON p.psgc_code = d.province_psgc_code
    WHERE d.is_sga AND NOT COALESCE(p.level_blank, FALSE)) AS sga_outside_container,
  (SELECT COUNT_IF(lgu_type = 'city') FROM regular) AS cities,
  (SELECT COUNT_IF(lgu_type = 'municipality') FROM regular) AS municipalities,
  (SELECT COUNT_IF(province_psgc_code IS NULL) FROM regular) AS regular_without_province,
  (SELECT COUNT_IF(is_sga) FROM regular) AS sga_members;

INSERT INTO edu_access.`01-control`.data_quality_results (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, NULL, 'dim_city_municipality', 'gold', 'edu_access.05-gold.dim_city_municipality', check_name, status, expected, actual, current_timestamp(), :code_revision
FROM (
  SELECT 'key_unique' AS check_name, CASE WHEN duplicate_keys = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '0' AS expected, CAST(duplicate_keys AS STRING) AS actual FROM dim_city_municipality_gate_summary
  UNION ALL SELECT 'key_not_null', CASE WHEN null_keys = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(null_keys AS STRING) FROM dim_city_municipality_gate_summary
  UNION ALL SELECT 'regular_rows_reconcile', CASE WHEN regular_rows = source_units THEN 'PASS' ELSE 'FAIL' END, CAST(source_units AS STRING), CAST(regular_rows AS STRING) FROM dim_city_municipality_gate_summary
  UNION ALL SELECT 'regular_in_psgc_master', CASE WHEN regular_not_in_psgc = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(regular_not_in_psgc AS STRING) FROM dim_city_municipality_gate_summary
  UNION ALL SELECT 'psgc_units_present', CASE WHEN psgc_units_missing = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(psgc_units_missing AS STRING) FROM dim_city_municipality_gate_summary
  UNION ALL SELECT 'one_psgc_version', CASE WHEN master_periods = 1 THEN 'PASS' ELSE 'FAIL' END, '1', CAST(master_periods AS STRING) FROM dim_city_municipality_gate_summary
  UNION ALL SELECT 'source_quarter_is_master', CASE WHEN wrong_quarter = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(wrong_quarter AS STRING) FROM dim_city_municipality_gate_summary
  UNION ALL SELECT 'member_type_allowed', CASE WHEN bad_member_type = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_member_type AS STRING) FROM dim_city_municipality_gate_summary
  UNION ALL SELECT 'technical_members', CASE WHEN technical_rows = 2 AND expected_technical_rows = 2 THEN 'PASS' ELSE 'FAIL' END, '2', CAST(technical_rows AS STRING) FROM dim_city_municipality_gate_summary
  UNION ALL SELECT 'region_resolved', CASE WHEN region_unresolved = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(region_unresolved AS STRING) FROM dim_city_municipality_gate_summary
  UNION ALL SELECT 'province_name_resolved', CASE WHEN province_unresolved = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(province_unresolved AS STRING) FROM dim_city_municipality_gate_summary
  UNION ALL SELECT 'lgu_type_allowed', CASE WHEN bad_lgu_type = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_lgu_type AS STRING) FROM dim_city_municipality_gate_summary
  UNION ALL SELECT 'municipality_without_city_class', CASE WHEN municipality_with_city_class = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(municipality_with_city_class AS STRING) FROM dim_city_municipality_gate_summary
  UNION ALL SELECT 'income_class_allowed', CASE WHEN bad_income_class = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_income_class AS STRING) FROM dim_city_municipality_gate_summary
  UNION ALL SELECT 'land_area_positive', CASE WHEN land_area_not_positive = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(land_area_not_positive AS STRING) FROM dim_city_municipality_gate_summary
  UNION ALL SELECT 'land_area_has_source', CASE WHEN land_area_source_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(land_area_source_mismatch AS STRING) FROM dim_city_municipality_gate_summary
  UNION ALL SELECT 'land_area_one_feature', CASE WHEN units_with_two_features = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(units_with_two_features AS STRING) FROM dim_city_municipality_gate_summary
  UNION ALL SELECT 'sga_inside_container', CASE WHEN sga_outside_container = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(sga_outside_container AS STRING) FROM dim_city_municipality_gate_summary
  UNION ALL SELECT 'regular_without_land_area', CASE WHEN regular_without_land_area = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(regular_without_land_area AS STRING) FROM dim_city_municipality_gate_summary
  UNION ALL SELECT 'city_without_class', CASE WHEN city_without_class = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(city_without_class AS STRING) FROM dim_city_municipality_gate_summary
  UNION ALL SELECT 'cities', 'PASS', CAST(NULL AS STRING), CAST(cities AS STRING) FROM dim_city_municipality_gate_summary
  UNION ALL SELECT 'municipalities', 'PASS', CAST(NULL AS STRING), CAST(municipalities AS STRING) FROM dim_city_municipality_gate_summary
  UNION ALL SELECT 'regular_without_province', 'PASS', CAST(NULL AS STRING), CAST(regular_without_province AS STRING) FROM dim_city_municipality_gate_summary
  UNION ALL SELECT 'sga_members', 'PASS', CAST(NULL AS STRING), CAST(sga_members AS STRING) FROM dim_city_municipality_gate_summary
) AS results;

-- Integrity rule 1 of the metric specification: one result per distinct upstream run_id read, PASS only
-- when that run's silver_build or integration_build for the source succeeded in pipeline_runs (D-025), so the Gold build is
-- traceable to the Silver and Integration rows it read and never trusts a run that did not publish.
INSERT INTO edu_access.`01-control`.data_quality_results (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, NULL, 'dim_city_municipality', 'gold', 'edu_access.05-gold.dim_city_municipality', 'upstream_run_' || u.input_table,
       CASE WHEN p.run_id IS NULL THEN 'FAIL' ELSE 'PASS' END, 'succeeded ' || u.pipeline_name, u.upstream_run_id,
       current_timestamp(), :code_revision
FROM (
  SELECT DISTINCT 'psa_psgc_clean' AS input_table, 'silver_build' AS pipeline_name, 'psa_psgc' AS source_id, run_id AS upstream_run_id
  FROM edu_access.`03-silver`.psa_psgc_clean WHERE is_master_reference
  UNION ALL
  SELECT DISTINCT 'hdx_adm3_clean' AS input_table, 'silver_build' AS pipeline_name, 'hdx_boundaries' AS source_id, run_id AS upstream_run_id
  FROM edu_access.`03-silver`.hdx_adm3_clean WHERE valid_on = (SELECT MAX(source_reference_date) FROM edu_access.`04-integration`.hdx_adm3_psgc_map)
  UNION ALL
  SELECT DISTINCT 'hdx_adm3_psgc_map' AS input_table, 'integration_build' AS pipeline_name, 'hdx_boundaries' AS source_id, run_id AS upstream_run_id
  FROM edu_access.`04-integration`.hdx_adm3_psgc_map WHERE source_reference_date = (SELECT MAX(source_reference_date) FROM edu_access.`04-integration`.hdx_adm3_psgc_map)
) AS u
LEFT JOIN (
  SELECT DISTINCT run_id, pipeline_name, source_id
  FROM edu_access.`01-control`.pipeline_runs
  WHERE status = 'succeeded'
) AS p ON p.run_id = u.upstream_run_id AND p.pipeline_name = u.pipeline_name AND p.source_id = u.source_id;

-- Sandbox: a failing gate marks its gold_build run failed before it stops.
MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (SELECT :run_id AS run_id, COUNT_IF(status = 'FAIL') AS fails FROM edu_access.`01-control`.data_quality_results
       WHERE run_id = :run_id AND source_id = 'dim_city_municipality' AND layer = 'gold'
         AND checked_at_utc >= session.gold_gate_started_at_utc) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'gold_build' AND t.source_id = 'dim_city_municipality'
WHEN MATCHED AND s.fails > 0 THEN UPDATE SET status = 'failed', finished_at_utc = current_timestamp(),
  failure_stage = 'gate', error_message = CAST(s.fails AS STRING) || ' FAIL result(s) in data_quality_results';

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Gold gate failed for dim_city_municipality: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s) in data_quality_results for run ' || :run_id) END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'dim_city_municipality' AND layer = 'gold' AND status = 'FAIL'
  AND checked_at_utc >= session.gold_gate_started_at_utc;

-- Every check passed: publish.
CREATE OR REPLACE TABLE edu_access.`05-gold`.dim_city_municipality USING DELTA AS
SELECT * FROM edu_access.`05-gold`.dim_city_municipality_candidate;

COMMENT ON TABLE edu_access.`05-gold`.dim_city_municipality IS 'One PSGC city or municipality of the master quarter, plus the UNKNOWN and EXCLUDED technical members (D-048).';
ALTER TABLE edu_access.`05-gold`.dim_city_municipality OWNER TO `reached-hq`;

-- Sandbox: the gate passed and the table is published.
MERGE INTO edu_access.`01-control`.pipeline_runs AS t USING (SELECT :run_id AS run_id) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'gold_build' AND t.source_id = 'dim_city_municipality'
WHEN MATCHED THEN UPDATE SET status = 'succeeded', finished_at_utc = current_timestamp(), failure_stage = NULL, error_message = NULL;
