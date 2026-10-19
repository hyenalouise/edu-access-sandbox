-- Gold gate for fact_city_school_age_population. Checks the candidate against the published Silver
-- table, its PSGC map and dim_city_municipality, writes every result to data_quality_results (layer
-- 'gold'), stops on any FAIL, and only then publishes the fact. A FAIL keeps the last good build.
--
-- FAIL: a repeated or NULL key; a key that is not in dim_city_municipality; a sex other than male or
-- female; a NULL or negative population; a year's population that differs from Silver's male and
-- female rows; a city, year and age whose male plus female differs from the published 'both' row; a
-- city, year and sex without every age Silver publishes; a matched row on EXCLUDED or an unmatched row
-- on a real code; and a comparability flag set on a code that is not in both census years.
-- WARN: population on the EXCLUDED member (today the 8 2020 Special Geographic Area clusters, D-055),
-- and regular cities or municipalities without 2024 rows.
-- Counts only (PASS): rows and population per year, rows not comparable.

DECLARE OR REPLACE VARIABLE gold_gate_started_at_utc TIMESTAMP;
SET VARIABLE gold_gate_started_at_utc = current_timestamp();

-- Sandbox: the one-row summary is a table, not a temporary view. Read 19 times as a view, it made Databricks
-- SQL's optimizer fail with INTERNAL_ERROR (sandbox run, 2026-10-19), as the DepEd PSGC gate did.
CREATE OR REPLACE TABLE edu_access.`05-gold`.fact_city_school_age_population_gate_summary USING DELTA AS
WITH silver AS (
  SELECT s.*, CASE WHEN m.match_status = 'matched' THEN m.psgc_code ELSE 'EXCLUDED' END AS city_mun_psgc_code
  FROM edu_access.`03-silver`.psa_school_age_population_clean AS s
  JOIN edu_access.`04-integration`.psa_school_age_population_psgc_map AS m
    ON m.census_year = s.census_year AND m.batch_id = s.batch_id AND m.place_row_number = s.place_row_number
  WHERE s.level = 'city_municipality' AND s.population_concept = 'total'
),
silver_city_rows AS (
  SELECT census_year, COUNT(*) AS n
  FROM edu_access.`03-silver`.psa_school_age_population_clean
  WHERE level = 'city_municipality' AND population_concept = 'total' AND sex IN ('male', 'female')
  GROUP BY census_year
),
silver_mapped_rows AS (
  SELECT census_year, COUNT(*) AS n FROM silver WHERE sex IN ('male', 'female') GROUP BY census_year
),
silver_by_year AS (
  SELECT census_year, SUM(population) AS population FROM silver WHERE sex IN ('male', 'female') GROUP BY census_year
),
silver_both AS (
  SELECT city_mun_psgc_code, census_year, age, SUM(population) AS population
  FROM silver WHERE sex = 'both' GROUP BY city_mun_psgc_code, census_year, age
),
silver_ages AS (
  SELECT census_year, COUNT(DISTINCT age) AS ages FROM silver GROUP BY census_year
),
fact AS (
  SELECT * FROM edu_access.`05-gold`.fact_city_school_age_population_candidate
),
fact_by_year AS (
  SELECT reference_year, COUNT(*) AS n, SUM(population) AS population FROM fact GROUP BY reference_year
),
fact_both AS (
  SELECT city_mun_psgc_code, reference_year, age, SUM(population) AS population
  FROM fact GROUP BY city_mun_psgc_code, reference_year, age
),
fact_ages AS (
  SELECT city_mun_psgc_code, reference_year, sex, COUNT(DISTINCT age) AS ages
  FROM fact GROUP BY city_mun_psgc_code, reference_year, sex
),
years_per_code AS (
  SELECT city_mun_psgc_code, COUNT(DISTINCT reference_year) AS years FROM fact GROUP BY city_mun_psgc_code
),
dim AS (
  SELECT * FROM edu_access.`05-gold`.dim_city_municipality
)
SELECT
  (SELECT COUNT(*) FROM fact) - (SELECT COUNT(*) FROM (SELECT DISTINCT city_mun_psgc_code, reference_year, age, sex FROM fact) AS k) AS duplicate_keys,
  (SELECT COUNT_IF(city_mun_psgc_code IS NULL OR reference_year IS NULL OR age IS NULL OR sex IS NULL) FROM fact) AS null_keys,
  (SELECT COUNT(*) FROM fact AS f LEFT JOIN dim AS d ON d.city_mun_psgc_code = f.city_mun_psgc_code
    WHERE d.city_mun_psgc_code IS NULL) AS keys_not_in_dim,
  (SELECT COUNT_IF(sex NOT IN ('male', 'female')) FROM fact) AS bad_sex,
  (SELECT COUNT_IF(population IS NULL OR population < 0) FROM fact) AS bad_population,
  (SELECT COUNT(*) FROM silver_city_rows AS c LEFT JOIN silver_mapped_rows AS m ON m.census_year = c.census_year
    WHERE m.n IS DISTINCT FROM c.n) AS years_with_unmapped_places,
  (SELECT COUNT(*) FROM silver_by_year AS s FULL OUTER JOIN fact_by_year AS f ON f.reference_year = s.census_year
    WHERE s.population IS DISTINCT FROM f.population) AS years_not_reconciled,
  (SELECT COUNT(*) FROM silver_both AS s FULL OUTER JOIN fact_both AS f
    ON f.city_mun_psgc_code = s.city_mun_psgc_code AND f.reference_year = s.census_year AND f.age = s.age
    WHERE s.population IS DISTINCT FROM f.population) AS cells_not_matching_both,
  (SELECT COUNT(*) FROM fact_ages AS f JOIN silver_ages AS s ON s.census_year = f.reference_year
    WHERE f.ages <> s.ages) AS cells_missing_ages,
  (SELECT COUNT_IF((city_mun_psgc_code = 'EXCLUDED') = (psgc_match_status = 'matched') OR psgc_match_status IS NULL) FROM fact) AS status_code_mismatch,
  (SELECT COUNT(*) FROM fact AS f JOIN years_per_code AS y ON y.city_mun_psgc_code = f.city_mun_psgc_code
    WHERE f.is_2020_2024_geography_comparable AND (y.years <> 2 OR f.city_mun_psgc_code = 'EXCLUDED')) AS comparable_without_both_years,
  (SELECT COUNT_IF(is_2020_2024_geography_comparable IS NULL) FROM fact) AS comparable_null,
  (SELECT COALESCE(SUM(population), 0) FROM fact WHERE city_mun_psgc_code = 'EXCLUDED') AS excluded_population,
  (SELECT COUNT(*) FROM dim AS d
    WHERE d.member_type = 'regular'
      AND NOT EXISTS (SELECT 1 FROM fact AS f WHERE f.city_mun_psgc_code = d.city_mun_psgc_code AND f.reference_year = 2024)) AS regular_without_2024,
  (SELECT COUNT_IF(reference_year = 2020) FROM fact) AS rows_2020,
  (SELECT COUNT_IF(reference_year = 2024) FROM fact) AS rows_2024,
  (SELECT COALESCE(SUM(CASE WHEN reference_year = 2020 THEN population END), 0) FROM fact) AS population_2020,
  (SELECT COALESCE(SUM(CASE WHEN reference_year = 2024 THEN population END), 0) FROM fact) AS population_2024,
  (SELECT COUNT_IF(NOT is_2020_2024_geography_comparable) FROM fact) AS rows_not_comparable,
  (SELECT COUNT(DISTINCT CASE WHEN NOT is_2020_2024_geography_comparable THEN city_mun_psgc_code END) FROM fact) AS codes_not_comparable;

ALTER TABLE edu_access.`05-gold`.fact_city_school_age_population_gate_summary OWNER TO `reached-hq`;

INSERT INTO edu_access.`01-control`.data_quality_results (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, NULL, 'fact_city_school_age_population', 'gold', 'edu_access.05-gold.fact_city_school_age_population', check_name, status, expected, actual, current_timestamp(), :code_revision
FROM (
  SELECT 'key_unique' AS check_name, CASE WHEN duplicate_keys = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '0' AS expected, CAST(duplicate_keys AS STRING) AS actual FROM edu_access.`05-gold`.fact_city_school_age_population_gate_summary
  UNION ALL SELECT 'key_not_null', CASE WHEN null_keys = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(null_keys AS STRING) FROM edu_access.`05-gold`.fact_city_school_age_population_gate_summary
  UNION ALL SELECT 'city_in_dim_city_municipality', CASE WHEN keys_not_in_dim = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(keys_not_in_dim AS STRING) FROM edu_access.`05-gold`.fact_city_school_age_population_gate_summary
  UNION ALL SELECT 'sex_male_or_female', CASE WHEN bad_sex = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_sex AS STRING) FROM edu_access.`05-gold`.fact_city_school_age_population_gate_summary
  UNION ALL SELECT 'population_not_null_or_negative', CASE WHEN bad_population = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_population AS STRING) FROM edu_access.`05-gold`.fact_city_school_age_population_gate_summary
  UNION ALL SELECT 'every_place_mapped', CASE WHEN years_with_unmapped_places = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(years_with_unmapped_places AS STRING) FROM edu_access.`05-gold`.fact_city_school_age_population_gate_summary
  UNION ALL SELECT 'population_reconciles_by_year', CASE WHEN years_not_reconciled = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(years_not_reconciled AS STRING) FROM edu_access.`05-gold`.fact_city_school_age_population_gate_summary
  UNION ALL SELECT 'male_plus_female_is_published_total', CASE WHEN cells_not_matching_both = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(cells_not_matching_both AS STRING) FROM edu_access.`05-gold`.fact_city_school_age_population_gate_summary
  UNION ALL SELECT 'every_age_present', CASE WHEN cells_missing_ages = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(cells_missing_ages AS STRING) FROM edu_access.`05-gold`.fact_city_school_age_population_gate_summary
  UNION ALL SELECT 'match_status_fits_code', CASE WHEN status_code_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(status_code_mismatch AS STRING) FROM edu_access.`05-gold`.fact_city_school_age_population_gate_summary
  UNION ALL SELECT 'comparable_only_with_both_years', CASE WHEN comparable_without_both_years = 0 AND comparable_null = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(comparable_without_both_years + comparable_null AS STRING) FROM edu_access.`05-gold`.fact_city_school_age_population_gate_summary
  UNION ALL SELECT 'excluded_member_population', CASE WHEN excluded_population = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(excluded_population AS STRING) FROM edu_access.`05-gold`.fact_city_school_age_population_gate_summary
  UNION ALL SELECT 'regular_without_2024', CASE WHEN regular_without_2024 = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(regular_without_2024 AS STRING) FROM edu_access.`05-gold`.fact_city_school_age_population_gate_summary
  UNION ALL SELECT 'rows_2020', 'PASS', CAST(NULL AS STRING), CAST(rows_2020 AS STRING) FROM edu_access.`05-gold`.fact_city_school_age_population_gate_summary
  UNION ALL SELECT 'rows_2024', 'PASS', CAST(NULL AS STRING), CAST(rows_2024 AS STRING) FROM edu_access.`05-gold`.fact_city_school_age_population_gate_summary
  UNION ALL SELECT 'population_2020', 'PASS', CAST(NULL AS STRING), CAST(population_2020 AS STRING) FROM edu_access.`05-gold`.fact_city_school_age_population_gate_summary
  UNION ALL SELECT 'population_2024', 'PASS', CAST(NULL AS STRING), CAST(population_2024 AS STRING) FROM edu_access.`05-gold`.fact_city_school_age_population_gate_summary
  UNION ALL SELECT 'rows_not_comparable', 'PASS', CAST(NULL AS STRING), CAST(rows_not_comparable AS STRING) FROM edu_access.`05-gold`.fact_city_school_age_population_gate_summary
  UNION ALL SELECT 'codes_not_comparable', 'PASS', CAST(NULL AS STRING), CAST(codes_not_comparable AS STRING) FROM edu_access.`05-gold`.fact_city_school_age_population_gate_summary
) AS results;

-- Integrity rule 1 of the metric specification: one result per distinct upstream run_id read, PASS only
-- when that run's silver_build or integration_build for the source succeeded in pipeline_runs (D-025), so the Gold build is
-- traceable to the Silver and Integration rows it read and never trusts a run that did not publish.
INSERT INTO edu_access.`01-control`.data_quality_results (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, NULL, 'fact_city_school_age_population', 'gold', 'edu_access.05-gold.fact_city_school_age_population', 'upstream_run_' || u.input_table,
       CASE WHEN p.run_id IS NULL THEN 'FAIL' ELSE 'PASS' END, 'succeeded ' || u.pipeline_name, u.upstream_run_id,
       current_timestamp(), :code_revision
FROM (
  SELECT DISTINCT 'psa_school_age_population_clean' AS input_table, 'silver_build' AS pipeline_name, 'psa_school_age_population' AS source_id, run_id AS upstream_run_id
  FROM edu_access.`03-silver`.psa_school_age_population_clean WHERE level = 'city_municipality' AND population_concept = 'total'
  UNION ALL
  SELECT DISTINCT 'psa_school_age_population_psgc_map' AS input_table, 'integration_build' AS pipeline_name, 'psa_school_age_population' AS source_id, run_id AS upstream_run_id
  FROM edu_access.`04-integration`.psa_school_age_population_psgc_map
) AS u
LEFT JOIN (
  SELECT DISTINCT run_id, pipeline_name, source_id
  FROM edu_access.`01-control`.pipeline_runs
  WHERE status = 'succeeded'
) AS p ON p.run_id = u.upstream_run_id AND p.pipeline_name = u.pipeline_name AND p.source_id = u.source_id;

-- Sandbox: a failing gate marks its gold_build run failed before it stops.
MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (SELECT :run_id AS run_id, COUNT_IF(status = 'FAIL') AS fails FROM edu_access.`01-control`.data_quality_results
       WHERE run_id = :run_id AND source_id = 'fact_city_school_age_population' AND layer = 'gold'
         AND checked_at_utc >= session.gold_gate_started_at_utc) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'gold_build' AND t.source_id = 'fact_city_school_age_population'
WHEN MATCHED AND s.fails > 0 THEN UPDATE SET status = 'failed', finished_at_utc = current_timestamp(),
  failure_stage = 'gate', error_message = CAST(s.fails AS STRING) || ' FAIL result(s) in data_quality_results';

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Gold gate failed for fact_city_school_age_population: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s) in data_quality_results for run ' || :run_id) END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'fact_city_school_age_population' AND layer = 'gold' AND status = 'FAIL'
  AND checked_at_utc >= session.gold_gate_started_at_utc;

-- Every check passed: publish.
CREATE OR REPLACE TABLE edu_access.`05-gold`.fact_city_school_age_population USING DELTA AS
SELECT * FROM edu_access.`05-gold`.fact_city_school_age_population_candidate;

COMMENT ON TABLE edu_access.`05-gold`.fact_city_school_age_population IS 'PSA 2020 and 2024 census population by city or municipality, single year of age (5 to 24) and sex, male and female only (D-048).';
ALTER TABLE edu_access.`05-gold`.fact_city_school_age_population OWNER TO `reached-hq`;

-- Sandbox: the gate passed and the table is published.
MERGE INTO edu_access.`01-control`.pipeline_runs AS t USING (SELECT :run_id AS run_id) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'gold_build' AND t.source_id = 'fact_city_school_age_population'
WHEN MATCHED THEN UPDATE SET status = 'succeeded', finished_at_utc = current_timestamp(), failure_stage = NULL, error_message = NULL;
