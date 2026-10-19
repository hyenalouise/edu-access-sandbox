-- Gold gate for fact_city_school_age_population. Checks the candidate against the published Silver
-- table, its PSGC map and dim_city_municipality, writes every result to data_quality_results (layer
-- 'gold'), stops on any FAIL, and only then publishes the fact. A FAIL keeps the last good build.
--
-- FAIL: a repeated or NULL key; a key that is not in dim_city_municipality; a sex other than male or
-- female; a NULL or negative population; any fact row that differs, in any column, from the row
-- expected from its Silver male or female cells (cells_match_silver: catches a swapped sex, population
-- moved between cities, a wrong status or a wrong comparability flag); a year's population that differs
-- from Silver's; a city, year and age whose male plus female differs from the published 'both' row; a
-- city, year and sex without every age Silver publishes; a matched row on a technical member or an
-- unmatched row on a real code; and a comparability flag set on a code that is not in both years.
-- WARN: population on EXCLUDED (today the 8 2020 Special Geographic Area clusters, D-055) or UNKNOWN,
-- and regular cities or municipalities without 2024 rows.
-- Counts only (PASS): rows and population per year, rows not comparable.

DECLARE OR REPLACE VARIABLE gold_gate_started_at_utc TIMESTAMP;
SET VARIABLE gold_gate_started_at_utc = current_timestamp();
DECLARE OR REPLACE VARIABLE gold_gate_summary STRING;
SET VARIABLE gold_gate_summary = '`edu_access`.`05-gold`.`fact_city_school_age_population_gate_summary_r_' || sha2(:run_id, 256) || '`';
DECLARE OR REPLACE VARIABLE gold_gate_owner_sql STRING;

-- Every fact row as Silver says it should be: one per code, year, age and sex, male or female. The
-- territory-change list is the build's (keep the two in step; a test compares them).
CREATE OR REPLACE TEMPORARY VIEW fact_city_school_age_population_expected AS
WITH silver AS (
  SELECT s.*, m.match_status,
         CASE WHEN m.match_status = 'matched' THEN m.psgc_code
              WHEN m.review_status = 'reviewed' THEN 'EXCLUDED'
              ELSE 'UNKNOWN' END AS city_mun_psgc_code
  FROM edu_access.`03-silver`.psa_school_age_population_clean AS s
  JOIN edu_access.`04-integration`.psa_school_age_population_psgc_map AS m
    ON m.census_year = s.census_year AND m.batch_id = s.batch_id AND m.place_row_number = s.place_row_number
  WHERE s.level = 'city_municipality' AND s.population_concept = 'total'
),
territory_changes AS (
  SELECT psgc_code FROM (VALUES
    ('1380300000'), ('1381500000'), ('1204702000'), ('1204703000'),
    ('1204709000'), ('1204711000'), ('1204712000'), ('1204717000')
  ) AS v(psgc_code)
),
silver_years_per_code AS (
  SELECT city_mun_psgc_code, COUNT(DISTINCT census_year) AS years
  FROM silver WHERE city_mun_psgc_code NOT IN ('UNKNOWN', 'EXCLUDED') GROUP BY city_mun_psgc_code
)
SELECT
    s.city_mun_psgc_code,
    CAST(s.census_year AS INT) AS reference_year,
    CAST(s.age AS INT) AS age,
    s.sex,
    CAST(SUM(s.population) AS BIGINT) AS population,
    MIN(s.match_status) AS psgc_match_status,
    COALESCE(MAX(y.years), 0) = 2 AND MAX(t.psgc_code) IS NULL AS is_2020_2024_geography_comparable
  FROM silver AS s
  LEFT JOIN silver_years_per_code AS y ON y.city_mun_psgc_code = s.city_mun_psgc_code
  LEFT JOIN territory_changes AS t ON t.psgc_code = s.city_mun_psgc_code
  WHERE s.sex IN ('male', 'female')
  GROUP BY s.city_mun_psgc_code, s.census_year, s.age, s.sex;

DECLARE OR REPLACE VARIABLE gold_fact_csap_cells_not_matching BIGINT;
SET VARIABLE gold_fact_csap_cells_not_matching = (
  (SELECT COUNT(*) FROM (
     SELECT city_mun_psgc_code, reference_year, age, sex, population, psgc_match_status, is_2020_2024_geography_comparable
     FROM edu_access.`05-gold`.fact_city_school_age_population_candidate
     EXCEPT ALL SELECT * FROM fact_city_school_age_population_expected) AS x)
  + (SELECT COUNT(*) FROM (
     SELECT * FROM fact_city_school_age_population_expected
     EXCEPT ALL
     SELECT city_mun_psgc_code, reference_year, age, sex, population, psgc_match_status, is_2020_2024_geography_comparable
     FROM edu_access.`05-gold`.fact_city_school_age_population_candidate) AS x));

-- The full-row comparison is computed once, above, because the summary is read once per result row.
-- The one-row summary the checks read is written to a table first. Read 21 times as a temporary view, it
-- made Databricks SQL's optimizer fail with INTERNAL_ERROR (dev run, 2026-10-20), as the DepEd PSGC gate did
-- (c64e949). The table is this run's own (its name holds a hash of run_id) and is dropped once the checks
-- are recorded, whether the gate passes or fails.
CREATE OR REPLACE TABLE IDENTIFIER(session.gold_gate_summary) USING DELTA COMMENT 'Internal unpublished one-row summary for one fact_city_school_age_population gate. The gate drops it once its checks are recorded in data_quality_results.' AS
WITH silver AS (
  SELECT s.*, m.match_status,
         CASE WHEN m.match_status = 'matched' THEN m.psgc_code
              WHEN m.review_status = 'reviewed' THEN 'EXCLUDED'
              ELSE 'UNKNOWN' END AS city_mun_psgc_code
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
  session.gold_fact_csap_cells_not_matching AS cells_not_matching_silver,
  (SELECT COUNT(*) FROM silver_city_rows AS c LEFT JOIN silver_mapped_rows AS m ON m.census_year = c.census_year
    WHERE m.n IS DISTINCT FROM c.n) AS years_with_unmapped_places,
  (SELECT COUNT(*) FROM silver_by_year AS s FULL OUTER JOIN fact_by_year AS f ON f.reference_year = s.census_year
    WHERE s.population IS DISTINCT FROM f.population) AS years_not_reconciled,
  (SELECT COUNT(*) FROM silver_both AS s FULL OUTER JOIN fact_both AS f
    ON f.city_mun_psgc_code = s.city_mun_psgc_code AND f.reference_year = s.census_year AND f.age = s.age
    WHERE s.population IS DISTINCT FROM f.population) AS cells_not_matching_both,
  (SELECT COUNT(*) FROM fact_ages AS f JOIN silver_ages AS s ON s.census_year = f.reference_year
    WHERE f.ages <> s.ages) AS cells_missing_ages,
  (SELECT COUNT_IF((city_mun_psgc_code IN ('UNKNOWN', 'EXCLUDED')) = (psgc_match_status = 'matched') OR psgc_match_status IS NULL) FROM fact) AS status_code_mismatch,
  (SELECT COUNT(*) FROM fact AS f JOIN years_per_code AS y ON y.city_mun_psgc_code = f.city_mun_psgc_code
    WHERE f.is_2020_2024_geography_comparable AND (y.years <> 2 OR f.city_mun_psgc_code IN ('UNKNOWN', 'EXCLUDED'))) AS comparable_without_both_years,
  (SELECT COUNT_IF(is_2020_2024_geography_comparable IS NULL) FROM fact) AS comparable_null,
  (SELECT COALESCE(SUM(population), 0) FROM fact WHERE city_mun_psgc_code = 'UNKNOWN') AS unknown_population,
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
SET VARIABLE gold_gate_owner_sql = 'ALTER TABLE ' || session.gold_gate_summary || ' OWNER TO `reached-hq`';
EXECUTE IMMEDIATE gold_gate_owner_sql;

INSERT INTO edu_access.`01-control`.data_quality_results (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, NULL, 'fact_city_school_age_population', 'gold', 'edu_access.05-gold.fact_city_school_age_population', check_name, status, expected, actual, current_timestamp(), :code_revision
FROM (
  SELECT 'key_unique' AS check_name, CASE WHEN duplicate_keys = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '0' AS expected, CAST(duplicate_keys AS STRING) AS actual FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'key_not_null', CASE WHEN null_keys = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(null_keys AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'city_in_dim_city_municipality', CASE WHEN keys_not_in_dim = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(keys_not_in_dim AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'sex_male_or_female', CASE WHEN bad_sex = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_sex AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'population_not_null_or_negative', CASE WHEN bad_population = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_population AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'cells_match_silver', CASE WHEN cells_not_matching_silver = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(cells_not_matching_silver AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'every_place_mapped', CASE WHEN years_with_unmapped_places = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(years_with_unmapped_places AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'population_reconciles_by_year', CASE WHEN years_not_reconciled = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(years_not_reconciled AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'male_plus_female_is_published_total', CASE WHEN cells_not_matching_both = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(cells_not_matching_both AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'every_age_present', CASE WHEN cells_missing_ages = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(cells_missing_ages AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'match_status_fits_code', CASE WHEN status_code_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(status_code_mismatch AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'comparable_only_with_both_years', CASE WHEN comparable_without_both_years = 0 AND comparable_null = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(comparable_without_both_years + comparable_null AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'unknown_member_population', CASE WHEN unknown_population = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(unknown_population AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'excluded_member_population', CASE WHEN excluded_population = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(excluded_population AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'regular_without_2024', CASE WHEN regular_without_2024 = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(regular_without_2024 AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'rows_2020', 'PASS', CAST(NULL AS STRING), CAST(rows_2020 AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'rows_2024', 'PASS', CAST(NULL AS STRING), CAST(rows_2024 AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'population_2020', 'PASS', CAST(NULL AS STRING), CAST(population_2020 AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'population_2024', 'PASS', CAST(NULL AS STRING), CAST(population_2024 AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'rows_not_comparable', 'PASS', CAST(NULL AS STRING), CAST(rows_not_comparable AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'codes_not_comparable', 'PASS', CAST(NULL AS STRING), CAST(codes_not_comparable AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
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

-- Every check is recorded, so the summary is no longer needed, whether the gate passes or fails.
DROP TABLE IF EXISTS IDENTIFIER(session.gold_gate_summary);

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Gold gate failed for fact_city_school_age_population: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s) in data_quality_results for run ' || :run_id) END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'fact_city_school_age_population' AND layer = 'gold' AND status = 'FAIL'
  AND checked_at_utc >= session.gold_gate_started_at_utc;

-- Every check passed: publish.
CREATE OR REPLACE TABLE edu_access.`05-gold`.fact_city_school_age_population USING DELTA AS
SELECT * FROM edu_access.`05-gold`.fact_city_school_age_population_candidate;

COMMENT ON TABLE edu_access.`05-gold`.fact_city_school_age_population IS 'PSA 2020 and 2024 census population by city or municipality, single year of age (5 to 24) and sex, male and female only (D-048).';
ALTER TABLE edu_access.`05-gold`.fact_city_school_age_population OWNER TO `reached-hq`;
