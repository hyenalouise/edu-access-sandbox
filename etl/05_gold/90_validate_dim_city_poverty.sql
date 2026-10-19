-- Gold gate for dim_city_poverty, the checks D-046 lists: one row per regular city, the pinned status
-- counts (1,597 / 1 / 44 for PSGC 2Q 2026 and PSA 2023), only the listed reasons, and no value where
-- the status is not 'estimated'. Each is FAIL because both sources are pinned. The counts are pinned to
-- the PSGC 2Q 2026 master, so they apply when it has its 1,642 cities and municipalities; on any other
-- master (the test fixtures) the check is a WARN that says so.

DECLARE OR REPLACE VARIABLE gold_gate_started_at_utc TIMESTAMP;
SET VARIABLE gold_gate_started_at_utc = current_timestamp();

INSERT INTO edu_access.`01-control`.data_quality_results
  (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, CAST(NULL AS STRING), 'dim_city_poverty', 'gold', 'edu_access.05-gold.dim_city_poverty_candidate',
       check_name, status, expected, actual, current_timestamp(), :code_revision
FROM (
WITH c AS (SELECT * FROM edu_access.`05-gold`.dim_city_poverty_candidate),
d AS (SELECT city_mun_psgc_code FROM edu_access.`05-gold`.dim_city_municipality WHERE member_type = 'regular'),
s AS (
  SELECT
    (SELECT COUNT(*) FROM d) AS regular_cities,
    (SELECT COUNT(*) FROM c LEFT JOIN d ON d.city_mun_psgc_code = c.city_mun_psgc_code WHERE d.city_mun_psgc_code IS NULL) AS not_regular,
    COUNT(*) AS rows_built,
    COUNT(DISTINCT city_mun_psgc_code) AS keys_built,
    COALESCE(COUNT_IF(poverty_status = 'estimated'), 0) AS estimated,
    COALESCE(COUNT_IF(poverty_status = 'no_estimate'), 0) AS no_estimate,
    COALESCE(COUNT_IF(poverty_status = 'not_in_source'), 0) AS not_in_source,
    COALESCE(COUNT_IF(estimate_year <> 2023 OR estimate_year IS NULL), 0) AS bad_year,
    COALESCE(COUNT_IF(NOT ((poverty_status = 'estimated' AND status_reason IS NULL)
               OR (poverty_status = 'no_estimate' AND status_reason = 'PSA published no 2023 estimate')
               OR (poverty_status = 'not_in_source' AND status_reason IN (
                     'City of Manila not in the PSA estimates' || chr(59) || ' its 14 district estimates are not combined',
                     'not in the PSA city and municipal estimates')))), 0) AS bad_reason,
    COALESCE(COUNT_IF(poverty_status <> 'estimated' AND (poverty_incidence IS NOT NULL OR poverty_ci90_lower IS NOT NULL
             OR poverty_ci90_upper IS NOT NULL OR poverty_cv IS NOT NULL)), 0) AS value_without_estimate,
    COALESCE(COUNT_IF(poverty_status = 'estimated' AND (poverty_incidence IS NULL OR poverty_ci90_lower IS NULL OR poverty_ci90_upper IS NULL)), 0) AS estimate_incomplete,
    COALESCE(COUNT_IF(cv_over_20), 0) AS less_precise
  FROM c
)
SELECT 'one_row_per_regular_city' AS check_name,
       CASE WHEN rows_built = regular_cities AND keys_built = rows_built AND not_regular = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
       CAST(regular_cities AS STRING) AS expected, CAST(rows_built AS STRING) AS actual FROM s
UNION ALL SELECT 'status_counts', CASE WHEN estimated = 1597 AND no_estimate = 1 AND not_in_source = 44 THEN 'PASS'
                                         WHEN regular_cities = 1642 THEN 'FAIL' ELSE 'WARN' END,
                 '1597 / 1 / 44', CAST(estimated AS STRING) || ' / ' || CAST(no_estimate AS STRING) || ' / ' || CAST(not_in_source AS STRING) FROM s
UNION ALL SELECT 'estimate_year_2023', CASE WHEN bad_year = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_year AS STRING) FROM s
UNION ALL SELECT 'status_reason_listed', CASE WHEN bad_reason = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_reason AS STRING) FROM s
UNION ALL SELECT 'no_value_without_estimate', CASE WHEN value_without_estimate = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(value_without_estimate AS STRING) FROM s
UNION ALL SELECT 'estimate_complete', CASE WHEN estimate_incomplete = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(estimate_incomplete AS STRING) FROM s
UNION ALL SELECT 'less_precise_cv_over_20', 'PASS', 'count', CAST(less_precise AS STRING) FROM s
) AS results;

MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (SELECT :run_id AS run_id, COUNT_IF(status = 'FAIL') AS fails FROM edu_access.`01-control`.data_quality_results
       WHERE run_id = :run_id AND source_id = 'dim_city_poverty' AND layer = 'gold'
         AND checked_at_utc >= session.gold_gate_started_at_utc) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'gold_build' AND t.source_id = 'dim_city_poverty'
WHEN MATCHED AND s.fails > 0 THEN UPDATE SET status = 'failed', finished_at_utc = current_timestamp(),
  failure_stage = 'gate', error_message = CAST(s.fails AS STRING) || ' FAIL result(s) in data_quality_results';

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Gold gate failed for dim_city_poverty: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s)') END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'dim_city_poverty' AND layer = 'gold' AND status = 'FAIL'
  AND checked_at_utc >= session.gold_gate_started_at_utc;

CREATE OR REPLACE TABLE edu_access.`05-gold`.dim_city_poverty USING DELTA AS SELECT * FROM edu_access.`05-gold`.dim_city_poverty_candidate;
ALTER TABLE edu_access.`05-gold`.dim_city_poverty OWNER TO `reached-hq`;

MERGE INTO edu_access.`01-control`.pipeline_runs AS t USING (SELECT :run_id AS run_id) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'gold_build' AND t.source_id = 'dim_city_poverty'
WHEN MATCHED THEN UPDATE SET status = 'succeeded', finished_at_utc = current_timestamp(), failure_stage = NULL, error_message = NULL;
