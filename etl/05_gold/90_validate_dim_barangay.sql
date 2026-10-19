-- Gold gate for dim_barangay: every PSGC barangay once, one unknown member per regular city, and every
-- barangay under a city or municipality in dim_city_municipality.

DECLARE OR REPLACE VARIABLE gold_gate_started_at_utc TIMESTAMP;
SET VARIABLE gold_gate_started_at_utc = current_timestamp();

INSERT INTO edu_access.`01-control`.data_quality_results
  (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, CAST(NULL AS STRING), 'dim_barangay', 'gold', 'edu_access.05-gold.dim_barangay_candidate',
       check_name, status, expected, actual, current_timestamp(), :code_revision
FROM (
WITH c AS (SELECT * FROM edu_access.`05-gold`.dim_barangay_candidate),
cities AS (SELECT * FROM edu_access.`05-gold`.dim_city_municipality),
s AS (
  SELECT
    (SELECT COUNT(*) FROM edu_access.`03-silver`.psa_psgc_clean WHERE is_master_reference AND geographic_level = 'Bgy') AS psgc_barangays,
    (SELECT COUNT(*) FROM cities WHERE member_type = 'regular') AS regular_cities,
    COUNT(*) AS rows_built,
    COUNT(DISTINCT c.barangay_psgc_code) AS keys_built,
    COALESCE(COUNT_IF(c.barangay_psgc_code IS NULL OR c.barangay_name IS NULL OR c.city_mun_psgc_code IS NULL), 0) AS null_fields,
    COALESCE(COUNT_IF(c.member_type = 'regular'), 0) AS regular_rows,
    COALESCE(COUNT_IF(c.member_type = 'unknown' AND c.barangay_psgc_code LIKE 'UNK-%'), 0) AS city_unknown_rows,
    COALESCE(COUNT_IF(c.member_type = 'unknown' AND c.barangay_psgc_code = 'UNKNOWN' AND c.city_mun_psgc_code = 'UNKNOWN'), 0) AS global_unknown_rows,
    COALESCE(COUNT_IF(c.member_type = 'excluded' AND c.barangay_psgc_code = 'EXCLUDED' AND c.city_mun_psgc_code = 'EXCLUDED'), 0) AS excluded_rows,
    COALESCE(COUNT_IF(c.member_type NOT IN ('regular', 'unknown', 'excluded') OR c.member_type IS NULL), 0) AS bad_member_type,
    COALESCE(COUNT_IF(d.city_mun_psgc_code IS NULL), 0) AS city_not_in_dim,
    COALESCE(COUNT_IF(c.member_type = 'regular' AND d.member_type <> 'regular'), 0) AS regular_under_technical,
    COALESCE(COUNT_IF(c.member_type = 'regular' AND (c.urban_rural NOT IN ('U', 'R') OR c.urban_rural IS NULL)), 0) AS urban_rural_unknown
  FROM c LEFT JOIN cities AS d ON d.city_mun_psgc_code = c.city_mun_psgc_code
)
SELECT 'rows_present' AS check_name, CASE WHEN rows_built > 0 THEN 'PASS' ELSE 'FAIL' END AS status,
       '> 0' AS expected, CAST(rows_built AS STRING) AS actual FROM s
UNION ALL SELECT 'one_row_per_code', CASE WHEN keys_built = rows_built THEN 'PASS' ELSE 'FAIL' END,
                 CAST(rows_built AS STRING), CAST(keys_built AS STRING) FROM s
UNION ALL SELECT 'no_null_fields', CASE WHEN null_fields = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(null_fields AS STRING) FROM s
UNION ALL SELECT 'every_psgc_barangay_present', CASE WHEN regular_rows = psgc_barangays THEN 'PASS' ELSE 'FAIL' END,
                 CAST(psgc_barangays AS STRING), CAST(regular_rows AS STRING) FROM s
UNION ALL SELECT 'one_unknown_per_city', CASE WHEN city_unknown_rows = regular_cities THEN 'PASS' ELSE 'FAIL' END,
                 CAST(regular_cities AS STRING), CAST(city_unknown_rows AS STRING) FROM s
UNION ALL SELECT 'technical_members', CASE WHEN global_unknown_rows = 1 AND excluded_rows = 1
                   AND rows_built = regular_rows + city_unknown_rows + 2 THEN 'PASS' ELSE 'FAIL' END,
                 '1 unknown / 1 excluded', CAST(global_unknown_rows AS STRING) || ' unknown / ' || CAST(excluded_rows AS STRING) || ' excluded' FROM s
UNION ALL SELECT 'member_type_valid', CASE WHEN bad_member_type = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_member_type AS STRING) FROM s
UNION ALL SELECT 'city_in_dim_city_municipality', CASE WHEN city_not_in_dim = 0 AND regular_under_technical = 0 THEN 'PASS' ELSE 'FAIL' END,
                 '0', CAST(city_not_in_dim + regular_under_technical AS STRING) FROM s
UNION ALL SELECT 'urban_rural_unknown', CASE WHEN urban_rural_unknown = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(urban_rural_unknown AS STRING) FROM s
) AS results;

MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (SELECT :run_id AS run_id, COUNT_IF(status = 'FAIL') AS fails FROM edu_access.`01-control`.data_quality_results
       WHERE run_id = :run_id AND source_id = 'dim_barangay' AND layer = 'gold'
         AND checked_at_utc >= session.gold_gate_started_at_utc) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'gold_build' AND t.source_id = 'dim_barangay'
WHEN MATCHED AND s.fails > 0 THEN UPDATE SET status = 'failed', finished_at_utc = current_timestamp(),
  failure_stage = 'gate', error_message = CAST(s.fails AS STRING) || ' FAIL result(s) in data_quality_results';

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Gold gate failed for dim_barangay: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s)') END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'dim_barangay' AND layer = 'gold' AND status = 'FAIL'
  AND checked_at_utc >= session.gold_gate_started_at_utc;

CREATE OR REPLACE TABLE edu_access.`05-gold`.dim_barangay USING DELTA AS SELECT * FROM edu_access.`05-gold`.dim_barangay_candidate;
ALTER TABLE edu_access.`05-gold`.dim_barangay OWNER TO `reached-hq`;

MERGE INTO edu_access.`01-control`.pipeline_runs AS t USING (SELECT :run_id AS run_id) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'gold_build' AND t.source_id = 'dim_barangay'
WHEN MATCHED THEN UPDATE SET status = 'succeeded', finished_at_utc = current_timestamp(), failure_stage = NULL, error_message = NULL;
