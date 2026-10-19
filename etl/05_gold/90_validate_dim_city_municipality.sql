-- Gold gate for dim_city_municipality. Checks dim_city_municipality_candidate against the published
-- PSGC and HDX tables it was built from, writes every result to data_quality_results (layer 'gold'),
-- stops on any FAIL, and only then publishes dim_city_municipality. A FAIL keeps the last good build.
--
-- FAIL: any row that differs, in any column, from the row expected from its PSGC and HDX source rows
-- (values_match_source: catches a changed name, parent, class, SGA flag or land area), a repeated or NULL key, a regular member that is not a City or Mun row of the one master
-- quarter (or one missing), technical members other than exactly UNKNOWN and EXCLUDED, a region or
-- province code without its name, a class that does not fit the LGU type, land area that is not
-- positive or has no source, a unit matched by two HDX features of the latest release, and a
-- Special Geographic Area member outside its blank-level container.
-- WARN: regular members without land area (today the 8 Special Geographic Area municipalities,
-- D-052) and cities without a city class.
-- Counts only (PASS): cities, municipalities, members without a province, SGA members.

DECLARE OR REPLACE VARIABLE gold_gate_started_at_utc TIMESTAMP;
SET VARIABLE gold_gate_started_at_utc = current_timestamp();
DECLARE OR REPLACE VARIABLE gold_gate_summary STRING;
SET VARIABLE gold_gate_summary = '`edu_access`.`05-gold`.`dim_city_municipality_gate_summary_r_' || sha2(:run_id, 256) || '`';
DECLARE OR REPLACE VARIABLE gold_gate_owner_sql STRING;

-- Every row as its source says it should be, column by column, built once for the full-row comparison.
CREATE OR REPLACE TEMPORARY VIEW dim_city_municipality_expected AS
WITH psgc AS (
  SELECT * FROM edu_access.`03-silver`.psa_psgc_clean WHERE is_master_reference
),
hdx_area AS (
  SELECT m.psgc_code, h.area_sqkm
  FROM edu_access.`04-integration`.hdx_adm3_psgc_map AS m
  JOIN edu_access.`03-silver`.hdx_adm3_clean AS h
    ON h.adm3_pcode = m.adm3_pcode AND h.valid_on = m.source_reference_date
  WHERE m.match_status = 'matched'
    AND m.source_reference_date = (SELECT MAX(source_reference_date) FROM edu_access.`04-integration`.hdx_adm3_psgc_map)
)
  SELECT
    c.psgc_code AS city_mun_psgc_code, c.name AS city_mun_name,
    c.province_code AS province_psgc_code, p.name AS province_name,
    c.region_code AS region_psgc_code, r.name AS region_name,
    CASE c.geographic_level WHEN 'City' THEN 'city' WHEN 'Mun' THEN 'municipality' END AS lgu_type,
    c.city_class, c.income_class, c.income_class_retained_after_downgrade AS income_class_retained,
    CAST(a.area_sqkm AS DECIMAL(18,4)) AS land_area_sqkm,
    CASE WHEN a.area_sqkm IS NOT NULL THEN 'hdx_boundaries' END AS land_area_source,
    COALESCE(p.level_blank AND p.psgc_code = '1999900000', FALSE) AS is_sga,
    'regular' AS member_type, c.publication_period AS source_psgc_quarter
  FROM psgc AS c
  LEFT JOIN psgc AS p ON p.psgc_code = c.province_code
  LEFT JOIN psgc AS r ON r.psgc_code = c.region_code AND r.geographic_level = 'Reg'
  LEFT JOIN hdx_area AS a ON a.psgc_code = c.psgc_code
  WHERE c.geographic_level IN ('City', 'Mun')
  UNION ALL
  SELECT v.code, v.label, CAST(NULL AS STRING), CAST(NULL AS STRING), CAST(NULL AS STRING), CAST(NULL AS STRING),
         CAST(NULL AS STRING), CAST(NULL AS STRING), CAST(NULL AS STRING), CAST(NULL AS BOOLEAN),
         CAST(NULL AS DECIMAL(18,4)), CAST(NULL AS STRING), FALSE, v.member_type, (SELECT MAX(publication_period) FROM psgc)
  FROM (VALUES
    ('UNKNOWN', 'Unknown city or municipality', 'unknown'),
    ('EXCLUDED', 'Excluded from city or municipality analysis', 'excluded')
  ) AS v(code, label, member_type);

DECLARE OR REPLACE VARIABLE gold_dim_city_rows_not_matching BIGINT;
SET VARIABLE gold_dim_city_rows_not_matching = (
  (SELECT COUNT(*) FROM (SELECT city_mun_psgc_code, city_mun_name, province_psgc_code, province_name, region_psgc_code, region_name, lgu_type, city_class, income_class, income_class_retained, land_area_sqkm, land_area_source, is_sga, member_type, source_psgc_quarter FROM edu_access.`05-gold`.dim_city_municipality_candidate EXCEPT ALL SELECT * FROM dim_city_municipality_expected) AS x)
  + (SELECT COUNT(*) FROM (SELECT * FROM dim_city_municipality_expected EXCEPT ALL SELECT city_mun_psgc_code, city_mun_name, province_psgc_code, province_name, region_psgc_code, region_name, lgu_type, city_class, income_class, income_class_retained, land_area_sqkm, land_area_source, is_sga, member_type, source_psgc_quarter FROM edu_access.`05-gold`.dim_city_municipality_candidate) AS x));

-- The full-row comparison is computed once, above, because the summary is read once per result row.
-- The one-row summary the checks read is written to a table first. Read 25 times as a temporary view, it
-- made Databricks SQL's optimizer fail with INTERNAL_ERROR (dev run, 2026-10-20), as the DepEd PSGC gate did
-- (c64e949). The table is this run's own (its name holds a hash of run_id) and is dropped once the checks
-- are recorded, whether the gate passes or fails.
CREATE OR REPLACE TABLE IDENTIFIER(session.gold_gate_summary) USING DELTA COMMENT 'Internal unpublished one-row summary for one dim_city_municipality gate. The gate drops it once its checks are recorded in data_quality_results.' AS
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
  session.gold_dim_city_rows_not_matching AS rows_not_matching_source,
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
SET VARIABLE gold_gate_owner_sql = 'ALTER TABLE ' || session.gold_gate_summary || ' OWNER TO `reached-hq`';
EXECUTE IMMEDIATE gold_gate_owner_sql;

INSERT INTO edu_access.`01-control`.data_quality_results (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, NULL, 'dim_city_municipality', 'gold', 'edu_access.05-gold.dim_city_municipality', check_name, status, expected, actual, current_timestamp(), :code_revision
FROM (
  SELECT 'values_match_source' AS check_name, CASE WHEN rows_not_matching_source = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '0' AS expected, CAST(rows_not_matching_source AS STRING) AS actual FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'key_unique', CASE WHEN duplicate_keys = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(duplicate_keys AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'key_not_null', CASE WHEN null_keys = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(null_keys AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'regular_rows_reconcile', CASE WHEN regular_rows = source_units THEN 'PASS' ELSE 'FAIL' END, CAST(source_units AS STRING), CAST(regular_rows AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'regular_in_psgc_master', CASE WHEN regular_not_in_psgc = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(regular_not_in_psgc AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'psgc_units_present', CASE WHEN psgc_units_missing = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(psgc_units_missing AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'one_psgc_version', CASE WHEN master_periods = 1 THEN 'PASS' ELSE 'FAIL' END, '1', CAST(master_periods AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'source_quarter_is_master', CASE WHEN wrong_quarter = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(wrong_quarter AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'member_type_allowed', CASE WHEN bad_member_type = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_member_type AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'technical_members', CASE WHEN technical_rows = 2 AND expected_technical_rows = 2 THEN 'PASS' ELSE 'FAIL' END, '2', CAST(technical_rows AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'region_resolved', CASE WHEN region_unresolved = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(region_unresolved AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'province_name_resolved', CASE WHEN province_unresolved = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(province_unresolved AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'lgu_type_allowed', CASE WHEN bad_lgu_type = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_lgu_type AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'municipality_without_city_class', CASE WHEN municipality_with_city_class = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(municipality_with_city_class AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'income_class_allowed', CASE WHEN bad_income_class = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_income_class AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'land_area_positive', CASE WHEN land_area_not_positive = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(land_area_not_positive AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'land_area_has_source', CASE WHEN land_area_source_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(land_area_source_mismatch AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'land_area_one_feature', CASE WHEN units_with_two_features = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(units_with_two_features AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'sga_inside_container', CASE WHEN sga_outside_container = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(sga_outside_container AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'regular_without_land_area', CASE WHEN regular_without_land_area = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(regular_without_land_area AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'city_without_class', CASE WHEN city_without_class = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(city_without_class AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'cities', 'PASS', CAST(NULL AS STRING), CAST(cities AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'municipalities', 'PASS', CAST(NULL AS STRING), CAST(municipalities AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'regular_without_province', 'PASS', CAST(NULL AS STRING), CAST(regular_without_province AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'sga_members', 'PASS', CAST(NULL AS STRING), CAST(sga_members AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
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

-- Every check is recorded, so the summary is no longer needed, whether the gate passes or fails.
DROP TABLE IF EXISTS IDENTIFIER(session.gold_gate_summary);

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Gold gate failed for dim_city_municipality: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s) in data_quality_results for run ' || :run_id) END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'dim_city_municipality' AND layer = 'gold' AND status = 'FAIL'
  AND checked_at_utc >= session.gold_gate_started_at_utc;

-- Every check passed: publish.
CREATE OR REPLACE TABLE edu_access.`05-gold`.dim_city_municipality USING DELTA AS
SELECT * FROM edu_access.`05-gold`.dim_city_municipality_candidate;

COMMENT ON TABLE edu_access.`05-gold`.dim_city_municipality IS 'One PSGC city or municipality of the master quarter, plus the UNKNOWN and EXCLUDED technical members (D-048).';
ALTER TABLE edu_access.`05-gold`.dim_city_municipality OWNER TO `reached-hq`;
