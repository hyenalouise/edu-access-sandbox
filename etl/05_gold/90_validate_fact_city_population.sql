-- Gold gate for fact_city_population. Checks fact_city_population_candidate against the published
-- dim_city_municipality and psa_psgc_clean it was built from, writes every result to
-- data_quality_results (layer 'gold'), stops on any FAIL, and only then publishes fact_city_population.
-- A FAIL keeps the last good build.
--
-- FAIL: a repeated or NULL key; a key that is not a regular member of dim_city_municipality, or a
-- regular member with no row; a member that is not a City or Mun row of the master quarter; a reference
-- year other than 2024; a status the build has no rule for ('provisional' and 'excluded' stay in the
-- data model but fail until their rules are approved); a population that is negative, differs from
-- Silver, or is present on a row that is not 'available' (or absent on one that is); a status reason on
-- an available row or a missing one on any other; a status or reason other than the one Silver's
-- population and population_null_reason give; a fact total that differs from the total of every City
-- and Mun row of Silver's master quarter, member or not, so a city the dimension lacks fails here; more
-- than one master PSGC period; and a PSGC Silver run that did not succeed.
-- WARN: members without a population; the fact total differing from the region total (the two match
-- when every city and municipality has a population, profile O-4).
-- Counts only (PASS): members with a published 0, the fact total.

DECLARE OR REPLACE VARIABLE gold_gate_started_at_utc TIMESTAMP;
SET VARIABLE gold_gate_started_at_utc = current_timestamp();

CREATE OR REPLACE TEMPORARY VIEW fact_city_population_gate_summary AS
WITH psgc AS (
  SELECT * FROM edu_access.`03-silver`.psa_psgc_clean WHERE is_master_reference
),
units AS (
  SELECT psgc_code, population, population_null_reason FROM psgc WHERE geographic_level IN ('City', 'Mun')
),
regular AS (
  SELECT city_mun_psgc_code FROM edu_access.`05-gold`.dim_city_municipality WHERE member_type = 'regular'
),
fact AS (
  SELECT * FROM edu_access.`05-gold`.fact_city_population_candidate
)
SELECT
  (SELECT COUNT(*) FROM fact) AS fact_rows,
  (SELECT COUNT(*) FROM regular) AS regular_members,
  (SELECT COUNT(*) FROM (SELECT city_mun_psgc_code, reference_year FROM fact
    GROUP BY city_mun_psgc_code, reference_year HAVING COUNT(*) > 1) AS x) AS duplicate_keys,
  (SELECT COUNT_IF(city_mun_psgc_code IS NULL OR reference_year IS NULL) FROM fact) AS null_keys,
  (SELECT COUNT(*) FROM fact AS f LEFT JOIN regular AS r ON r.city_mun_psgc_code = f.city_mun_psgc_code
    WHERE r.city_mun_psgc_code IS NULL) AS keys_not_regular,
  (SELECT COUNT(*) FROM regular AS r LEFT JOIN fact AS f ON f.city_mun_psgc_code = r.city_mun_psgc_code
    WHERE f.city_mun_psgc_code IS NULL) AS regular_without_row,
  (SELECT COUNT(*) FROM regular AS r LEFT JOIN units AS u ON u.psgc_code = r.city_mun_psgc_code
    WHERE u.psgc_code IS NULL) AS regular_not_in_psgc,
  (SELECT COUNT_IF(reference_year IS DISTINCT FROM 2024) FROM fact) AS wrong_reference_year,
  (SELECT COUNT_IF(estimate_status IS NULL OR estimate_status NOT IN ('available', 'missing'))
    FROM fact) AS bad_status,
  (SELECT COUNT_IF((estimate_status = 'available') <> (population IS NOT NULL)) FROM fact) AS status_population_mismatch,
  (SELECT COUNT_IF((estimate_status = 'available') = (status_reason IS NOT NULL)) FROM fact) AS status_reason_mismatch,
  -- The build's rules, restated from Silver, so a swapped or made-up status or reason fails.
  (SELECT COUNT_IF(
     f.estimate_status IS DISTINCT FROM CASE WHEN u.population IS NOT NULL THEN 'available' ELSE 'missing' END
     OR f.status_reason IS DISTINCT FROM CASE
       WHEN u.population IS NOT NULL THEN NULL
       WHEN u.population_null_reason = 'publisher_na' THEN 'PSGC publishes #N/A as the 2024 population'
       WHEN u.population_null_reason = 'blank' THEN 'PSGC publishes no 2024 population'
       WHEN u.psgc_code IS NULL THEN 'Not a City or Mun row of the PSGC master quarter'
     END)
   FROM fact AS f LEFT JOIN units AS u ON u.psgc_code = f.city_mun_psgc_code) AS status_differs_from_psgc,
  (SELECT COUNT_IF(population < 0) FROM fact) AS negative_population,
  (SELECT COUNT(*) FROM fact AS f JOIN units AS u ON u.psgc_code = f.city_mun_psgc_code
    WHERE f.population IS DISTINCT FROM u.population) AS population_differs_from_psgc,
  (SELECT SUM(population) FROM fact) AS fact_total,
  (SELECT SUM(population) FROM units) AS psgc_total,
  (SELECT SUM(population) FROM psgc WHERE geographic_level = 'Reg') AS region_total,
  (SELECT COUNT(DISTINCT publication_period) FROM psgc) AS master_periods,
  (SELECT COUNT_IF(estimate_status <> 'available') FROM fact) AS not_available,
  (SELECT COUNT_IF(population = 0) FROM fact) AS zero_population;

INSERT INTO edu_access.`01-control`.data_quality_results (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, NULL, 'fact_city_population', 'gold', 'edu_access.05-gold.fact_city_population', check_name, status, expected, actual, current_timestamp(), :code_revision
FROM (
  SELECT 'key_unique' AS check_name, CASE WHEN duplicate_keys = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '0' AS expected, CAST(duplicate_keys AS STRING) AS actual FROM fact_city_population_gate_summary
  UNION ALL SELECT 'key_not_null', CASE WHEN null_keys = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(null_keys AS STRING) FROM fact_city_population_gate_summary
  UNION ALL SELECT 'keys_in_dimension', CASE WHEN keys_not_regular = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(keys_not_regular AS STRING) FROM fact_city_population_gate_summary
  UNION ALL SELECT 'regular_members_present', CASE WHEN regular_without_row = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(regular_without_row AS STRING) FROM fact_city_population_gate_summary
  UNION ALL SELECT 'rows_reconcile', CASE WHEN fact_rows = regular_members THEN 'PASS' ELSE 'FAIL' END, CAST(regular_members AS STRING), CAST(fact_rows AS STRING) FROM fact_city_population_gate_summary
  UNION ALL SELECT 'regular_in_psgc_master', CASE WHEN regular_not_in_psgc = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(regular_not_in_psgc AS STRING) FROM fact_city_population_gate_summary
  UNION ALL SELECT 'one_psgc_version', CASE WHEN master_periods = 1 THEN 'PASS' ELSE 'FAIL' END, '1', CAST(master_periods AS STRING) FROM fact_city_population_gate_summary
  UNION ALL SELECT 'reference_year_2024', CASE WHEN wrong_reference_year = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(wrong_reference_year AS STRING) FROM fact_city_population_gate_summary
  UNION ALL SELECT 'estimate_status_allowed', CASE WHEN bad_status = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_status AS STRING) FROM fact_city_population_gate_summary
  UNION ALL SELECT 'population_follows_status', CASE WHEN status_population_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(status_population_mismatch AS STRING) FROM fact_city_population_gate_summary
  UNION ALL SELECT 'status_reason_follows_status', CASE WHEN status_reason_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(status_reason_mismatch AS STRING) FROM fact_city_population_gate_summary
  UNION ALL SELECT 'status_and_reason_equal_psgc', CASE WHEN status_differs_from_psgc = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(status_differs_from_psgc AS STRING) FROM fact_city_population_gate_summary
  UNION ALL SELECT 'population_not_negative', CASE WHEN negative_population = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(negative_population AS STRING) FROM fact_city_population_gate_summary
  UNION ALL SELECT 'population_equals_psgc', CASE WHEN population_differs_from_psgc = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(population_differs_from_psgc AS STRING) FROM fact_city_population_gate_summary
  UNION ALL SELECT 'total_equals_psgc', CASE WHEN fact_total IS NOT DISTINCT FROM psgc_total THEN 'PASS' ELSE 'FAIL' END, CAST(psgc_total AS STRING), CAST(fact_total AS STRING) FROM fact_city_population_gate_summary
  UNION ALL SELECT 'members_without_population', CASE WHEN not_available = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(not_available AS STRING) FROM fact_city_population_gate_summary
  UNION ALL SELECT 'total_equals_regions', CASE WHEN fact_total IS NOT DISTINCT FROM region_total THEN 'PASS' ELSE 'WARN' END, CAST(region_total AS STRING), CAST(fact_total AS STRING) FROM fact_city_population_gate_summary
  UNION ALL SELECT 'members_with_zero_population', 'PASS', CAST(NULL AS STRING), CAST(zero_population AS STRING) FROM fact_city_population_gate_summary
  UNION ALL SELECT 'fact_total', 'PASS', CAST(NULL AS STRING), CAST(fact_total AS STRING) FROM fact_city_population_gate_summary
) AS results;

-- Integrity rule 1 of the metric specification: one result per distinct upstream run_id read, PASS only
-- when that run's silver_build for the source succeeded in pipeline_runs (D-025), so the Gold build is
-- traceable to the Silver rows it read and never trusts a run that did not publish.
INSERT INTO edu_access.`01-control`.data_quality_results (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, NULL, 'fact_city_population', 'gold', 'edu_access.05-gold.fact_city_population', 'upstream_run_' || u.input_table,
       CASE WHEN p.run_id IS NULL THEN 'FAIL' ELSE 'PASS' END, 'succeeded ' || u.pipeline_name, u.upstream_run_id,
       current_timestamp(), :code_revision
FROM (
  SELECT DISTINCT 'psa_psgc_clean' AS input_table, 'silver_build' AS pipeline_name, 'psa_psgc' AS source_id, run_id AS upstream_run_id
  FROM edu_access.`03-silver`.psa_psgc_clean WHERE is_master_reference
) AS u
LEFT JOIN (
  SELECT DISTINCT run_id, pipeline_name, source_id
  FROM edu_access.`01-control`.pipeline_runs
  WHERE status = 'succeeded'
) AS p ON p.run_id = u.upstream_run_id AND p.pipeline_name = u.pipeline_name AND p.source_id = u.source_id;

-- Sandbox: a failing gate marks its gold_build run failed before it stops.
MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (SELECT :run_id AS run_id, COUNT_IF(status = 'FAIL') AS fails FROM edu_access.`01-control`.data_quality_results
       WHERE run_id = :run_id AND source_id = 'fact_city_population' AND layer = 'gold'
         AND checked_at_utc >= session.gold_gate_started_at_utc) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'gold_build' AND t.source_id = 'fact_city_population'
WHEN MATCHED AND s.fails > 0 THEN UPDATE SET status = 'failed', finished_at_utc = current_timestamp(),
  failure_stage = 'gate', error_message = CAST(s.fails AS STRING) || ' FAIL result(s) in data_quality_results';

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Gold gate failed for fact_city_population: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s) in data_quality_results for run ' || :run_id) END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'fact_city_population' AND layer = 'gold' AND status = 'FAIL'
  AND checked_at_utc >= session.gold_gate_started_at_utc;

-- Every check passed: publish.
CREATE OR REPLACE TABLE edu_access.`05-gold`.fact_city_population USING DELTA AS
SELECT * FROM edu_access.`05-gold`.fact_city_population_candidate;

COMMENT ON TABLE edu_access.`05-gold`.fact_city_population IS 'PSGC 2024 total population of each regular city or municipality, with its availability status (D-048).';
ALTER TABLE edu_access.`05-gold`.fact_city_population OWNER TO `reached-hq`;

-- Sandbox: the gate passed and the table is published.
MERGE INTO edu_access.`01-control`.pipeline_runs AS t USING (SELECT :run_id AS run_id) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'gold_build' AND t.source_id = 'fact_city_population'
WHEN MATCHED THEN UPDATE SET status = 'succeeded', finished_at_utc = current_timestamp(), failure_stage = NULL, error_message = NULL;
