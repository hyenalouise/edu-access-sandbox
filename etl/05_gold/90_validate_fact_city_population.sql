-- Gold gate for fact_city_population: one 2024 row per regular city or municipality, valid statuses, and
-- the total reconciled to PSGC Silver.

DECLARE OR REPLACE VARIABLE gold_gate_started_at_utc TIMESTAMP;
SET VARIABLE gold_gate_started_at_utc = current_timestamp();

INSERT INTO edu_access.`01-control`.data_quality_results
  (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, CAST(NULL AS STRING), 'fact_city_population', 'gold', 'edu_access.05-gold.fact_city_population_candidate',
       check_name, status, expected, actual, current_timestamp(), :code_revision
FROM (
WITH c AS (SELECT * FROM edu_access.`05-gold`.fact_city_population_candidate),
d AS (SELECT city_mun_psgc_code FROM edu_access.`05-gold`.dim_city_municipality WHERE member_type = 'regular'),
s AS (
  SELECT
    (SELECT COUNT(*) FROM d) AS regular_cities,
    (SELECT SUM(population) FROM edu_access.`03-silver`.psa_psgc_clean WHERE is_master_reference AND geographic_level IN ('City', 'Mun')) AS silver_population,
    (SELECT COUNT(*) FROM c LEFT JOIN d ON d.city_mun_psgc_code = c.city_mun_psgc_code WHERE d.city_mun_psgc_code IS NULL) AS not_regular,
    COUNT(*) AS rows_built,
    COUNT(DISTINCT city_mun_psgc_code || '/' || CAST(reference_year AS STRING)) AS keys_built,
    COALESCE(COUNT_IF(estimate_status NOT IN ('available', 'missing', 'provisional', 'excluded') OR estimate_status IS NULL), 0) AS bad_status,
    COALESCE(COUNT_IF((estimate_status = 'available') <> (population IS NOT NULL)
             OR (estimate_status = 'available') <> (status_reason IS NULL)), 0) AS status_mismatch,
    COALESCE(COUNT_IF(estimate_status <> 'available'), 0) AS not_available,
    COALESCE(COUNT_IF(population = 0), 0) AS zero_population,
    SUM(population) AS gold_population
  FROM c
)
SELECT 'one_row_per_regular_city' AS check_name,
       CASE WHEN rows_built = regular_cities AND keys_built = rows_built AND not_regular = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
       CAST(regular_cities AS STRING) AS expected, CAST(rows_built AS STRING) AS actual FROM s
UNION ALL SELECT 'estimate_status_valid', CASE WHEN bad_status = 0 AND status_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END,
                 '0', CAST(bad_status + status_mismatch AS STRING) FROM s
UNION ALL SELECT 'population_reconciles', CASE WHEN gold_population = silver_population THEN 'PASS' ELSE 'FAIL' END,
                 CAST(silver_population AS STRING), CAST(gold_population AS STRING) FROM s
UNION ALL SELECT 'population_not_available', CASE WHEN not_available = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(not_available AS STRING) FROM s
UNION ALL SELECT 'population_zero', CASE WHEN zero_population = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(zero_population AS STRING) FROM s
) AS results;

MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (SELECT :run_id AS run_id, COUNT_IF(status = 'FAIL') AS fails FROM edu_access.`01-control`.data_quality_results
       WHERE run_id = :run_id AND source_id = 'fact_city_population' AND layer = 'gold'
         AND checked_at_utc >= session.gold_gate_started_at_utc) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'gold_build' AND t.source_id = 'fact_city_population'
WHEN MATCHED AND s.fails > 0 THEN UPDATE SET status = 'failed', finished_at_utc = current_timestamp(),
  failure_stage = 'gate', error_message = CAST(s.fails AS STRING) || ' FAIL result(s) in data_quality_results';

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Gold gate failed for fact_city_population: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s)') END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'fact_city_population' AND layer = 'gold' AND status = 'FAIL'
  AND checked_at_utc >= session.gold_gate_started_at_utc;

CREATE OR REPLACE TABLE edu_access.`05-gold`.fact_city_population USING DELTA AS SELECT * FROM edu_access.`05-gold`.fact_city_population_candidate;
ALTER TABLE edu_access.`05-gold`.fact_city_population OWNER TO `reached-hq`;

MERGE INTO edu_access.`01-control`.pipeline_runs AS t USING (SELECT :run_id AS run_id) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'gold_build' AND t.source_id = 'fact_city_population'
WHEN MATCHED THEN UPDATE SET status = 'succeeded', finished_at_utc = current_timestamp(), failure_stage = NULL, error_message = NULL;
