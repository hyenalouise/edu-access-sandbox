-- Gold gate for dim_city_municipality: every PSGC 2Q 2026 city and municipality once, the two technical
-- members once each, valid classifications, and land area for every unit HDX matched.

DECLARE OR REPLACE VARIABLE gold_gate_started_at_utc TIMESTAMP;
SET VARIABLE gold_gate_started_at_utc = current_timestamp();

INSERT INTO edu_access.`01-control`.data_quality_results
  (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, CAST(NULL AS STRING), 'dim_city_municipality', 'gold', 'edu_access.05-gold.dim_city_municipality_candidate',
       check_name, status, expected, actual, current_timestamp(), :code_revision
FROM (
WITH c AS (SELECT * FROM edu_access.`05-gold`.dim_city_municipality_candidate),
p AS (SELECT * FROM edu_access.`03-silver`.psa_psgc_clean WHERE is_master_reference),
s AS (
  SELECT
    (SELECT COUNT(*) FROM p WHERE geographic_level IN ('City', 'Mun')) AS psgc_units,
    (SELECT COUNT(*) FROM edu_access.`04-integration`.hdx_adm3_psgc_map WHERE match_status = 'matched') AS hdx_matched,
    (SELECT COUNT(DISTINCT publication_period) FROM p) AS psgc_periods,
    COUNT(*) AS rows_built,
    COUNT(DISTINCT city_mun_psgc_code) AS keys_built,
    COALESCE(COUNT_IF(city_mun_psgc_code IS NULL OR city_mun_name IS NULL), 0) AS null_keys,
    COALESCE(COUNT_IF(member_type = 'regular'), 0) AS regular_rows,
    COALESCE(COUNT_IF(member_type = 'unknown' AND city_mun_psgc_code = 'UNKNOWN'), 0) AS unknown_rows,
    COALESCE(COUNT_IF(member_type = 'excluded' AND city_mun_psgc_code = 'EXCLUDED'), 0) AS excluded_rows,
    COALESCE(COUNT_IF(member_type NOT IN ('regular', 'unknown', 'excluded') OR member_type IS NULL), 0) AS bad_member_type,
    COALESCE(COUNT_IF(member_type = 'regular' AND (lgu_type NOT IN ('City', 'Municipality') OR lgu_type IS NULL)), 0) AS bad_lgu_type,
    COALESCE(COUNT_IF(member_type = 'regular' AND NOT ((lgu_type = 'City' AND COALESCE(city_class IN ('HUC', 'ICC', 'CC'), FALSE))
                                              OR (lgu_type = 'Municipality' AND city_class IS NULL))), 0) AS bad_city_class,
    COALESCE(COUNT_IF(member_type = 'regular' AND (region_psgc_code IS NULL OR region_name IS NULL)), 0) AS no_region,
    COALESCE(COUNT_IF(member_type = 'regular' AND province_psgc_code IS NOT NULL AND province_name IS NULL), 0) AS province_unnamed,
    COALESCE(COUNT_IF(member_type = 'regular' AND land_area_sqkm IS NOT NULL), 0) AS with_area,
    COALESCE(COUNT_IF(member_type = 'regular' AND land_area_sqkm IS NULL), 0) AS without_area,
    COALESCE(COUNT_IF(land_area_sqkm <= 0), 0) AS bad_area,
    COALESCE(COUNT_IF(is_sga), 0) AS sga_rows
  FROM c
)
SELECT 'rows_present' AS check_name, CASE WHEN rows_built > 0 THEN 'PASS' ELSE 'FAIL' END AS status,
       '> 0' AS expected, CAST(rows_built AS STRING) AS actual FROM s
UNION ALL SELECT 'one_row_per_code', CASE WHEN keys_built = rows_built AND null_keys = 0 THEN 'PASS' ELSE 'FAIL' END,
                 CAST(rows_built AS STRING) || ' / 0 null', CAST(keys_built AS STRING) || ' / ' || CAST(null_keys AS STRING) || ' null' FROM s
UNION ALL SELECT 'every_psgc_unit_present', CASE WHEN regular_rows = psgc_units THEN 'PASS' ELSE 'FAIL' END,
                 CAST(psgc_units AS STRING), CAST(regular_rows AS STRING) FROM s
UNION ALL SELECT 'technical_members', CASE WHEN unknown_rows = 1 AND excluded_rows = 1 AND rows_built = regular_rows + 2 THEN 'PASS' ELSE 'FAIL' END,
                 '1 unknown / 1 excluded', CAST(unknown_rows AS STRING) || ' unknown / ' || CAST(excluded_rows AS STRING) || ' excluded' FROM s
UNION ALL SELECT 'member_type_valid', CASE WHEN bad_member_type = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_member_type AS STRING) FROM s
UNION ALL SELECT 'lgu_type_valid', CASE WHEN bad_lgu_type = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_lgu_type AS STRING) FROM s
UNION ALL SELECT 'city_class_matches_type', CASE WHEN bad_city_class = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_city_class AS STRING) FROM s
UNION ALL SELECT 'region_present', CASE WHEN no_region = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(no_region AS STRING) FROM s
UNION ALL SELECT 'province_named', CASE WHEN province_unnamed = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(province_unnamed AS STRING) FROM s
UNION ALL SELECT 'one_psgc_version', CASE WHEN psgc_periods = 1 THEN 'PASS' ELSE 'FAIL' END, '1', CAST(psgc_periods AS STRING) FROM s
UNION ALL SELECT 'land_area_for_every_hdx_match', CASE WHEN with_area = hdx_matched THEN 'PASS' ELSE 'FAIL' END,
                 CAST(hdx_matched AS STRING), CAST(with_area AS STRING) FROM s
UNION ALL SELECT 'land_area_positive', CASE WHEN bad_area = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_area AS STRING) FROM s
UNION ALL SELECT 'land_area_missing', CASE WHEN without_area = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(without_area AS STRING) FROM s
UNION ALL SELECT 'special_geographic_area_units', 'PASS', 'count', CAST(sga_rows AS STRING) FROM s
) AS results;

MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (SELECT :run_id AS run_id, COUNT_IF(status = 'FAIL') AS fails FROM edu_access.`01-control`.data_quality_results
       WHERE run_id = :run_id AND source_id = 'dim_city_municipality' AND layer = 'gold'
         AND checked_at_utc >= session.gold_gate_started_at_utc) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'gold_build' AND t.source_id = 'dim_city_municipality'
WHEN MATCHED AND s.fails > 0 THEN UPDATE SET status = 'failed', finished_at_utc = current_timestamp(),
  failure_stage = 'gate', error_message = CAST(s.fails AS STRING) || ' FAIL result(s) in data_quality_results';

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Gold gate failed for dim_city_municipality: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s)') END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'dim_city_municipality' AND layer = 'gold' AND status = 'FAIL'
  AND checked_at_utc >= session.gold_gate_started_at_utc;

CREATE OR REPLACE TABLE edu_access.`05-gold`.dim_city_municipality USING DELTA AS SELECT * FROM edu_access.`05-gold`.dim_city_municipality_candidate;
ALTER TABLE edu_access.`05-gold`.dim_city_municipality OWNER TO `reached-hq`;

MERGE INTO edu_access.`01-control`.pipeline_runs AS t USING (SELECT :run_id AS run_id) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'gold_build' AND t.source_id = 'dim_city_municipality'
WHEN MATCHED THEN UPDATE SET status = 'succeeded', finished_at_utc = current_timestamp(), failure_stage = NULL, error_message = NULL;
