-- Gold gate for fact_city_school_age_population: the grain, male and female only, every city in its
-- dimension, both census years, totals reconciled to Silver, and the published both-sexes row equal to
-- male plus female.

DECLARE OR REPLACE VARIABLE gold_gate_started_at_utc TIMESTAMP;
SET VARIABLE gold_gate_started_at_utc = current_timestamp();

INSERT INTO edu_access.`01-control`.data_quality_results
  (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, CAST(NULL AS STRING), 'fact_city_school_age_population', 'gold', 'edu_access.05-gold.fact_city_school_age_population_candidate',
       check_name, status, expected, actual, current_timestamp(), :code_revision
FROM (
WITH c AS (SELECT * FROM edu_access.`05-gold`.fact_city_school_age_population_candidate),
x AS (SELECT * FROM edu_access.`03-silver`.psa_school_age_population_clean
      WHERE level = 'city_municipality' AND population_concept = 'total'),
both_sexes AS (
  SELECT COUNT(*) AS cells,
         COALESCE(COUNT_IF(b.population <> COALESCE(m.population, 0) + COALESCE(f.population, 0)), 0) AS mismatched
  FROM x AS b
  LEFT JOIN x AS m ON m.census_year = b.census_year AND m.place_name = b.place_name AND m.parent_name = b.parent_name
    AND m.age = b.age AND m.sex = 'male'
  LEFT JOIN x AS f ON f.census_year = b.census_year AND f.place_name = b.place_name AND f.parent_name = b.parent_name
    AND f.age = b.age AND f.sex = 'female'
  WHERE b.sex = 'both'
),
s AS (
  SELECT
    (SELECT SUM(CAST(population AS BIGINT)) FROM x WHERE sex IN ('male', 'female')) AS silver_population,
    COUNT(*) AS rows_built,
    COUNT(DISTINCT c.city_mun_psgc_code || '/' || CAST(c.reference_year AS STRING) || '/' || CAST(c.age AS STRING) || '/' || c.sex) AS keys_built,
    COALESCE(COUNT_IF(c.sex NOT IN ('male', 'female') OR c.sex IS NULL), 0) AS bad_sex,
    COALESCE(COUNT_IF(c.age < 5 OR c.age > 24 OR c.age IS NULL), 0) AS bad_age,
    COALESCE(COUNT_IF(d.city_mun_psgc_code IS NULL), 0) AS no_city,
    COALESCE(COUNT_IF(c.population < 0 OR c.population IS NULL), 0) AS bad_population,
    COALESCE(COUNT_IF(c.psgc_match_status NOT IN ('matched', 'unmatched', 'ambiguous', 'excluded') OR c.psgc_match_status IS NULL), 0) AS bad_status,
    COUNT(DISTINCT c.reference_year) AS years,
    COUNT(DISTINCT CASE WHEN c.reference_year = 2020 AND d.member_type = 'regular' THEN c.city_mun_psgc_code END) AS cities_2020,
    COUNT(DISTINCT CASE WHEN c.reference_year = 2024 AND d.member_type = 'regular' THEN c.city_mun_psgc_code END) AS cities_2024,
    COUNT(DISTINCT CASE WHEN NOT c.is_2020_2024_geography_comparable AND d.member_type = 'regular' THEN c.city_mun_psgc_code END) AS not_comparable,
    COALESCE(SUM(CASE WHEN c.city_mun_psgc_code = 'EXCLUDED' THEN c.population END), 0) AS excluded_population,
    SUM(c.population) AS gold_population
  FROM c LEFT JOIN edu_access.`05-gold`.dim_city_municipality AS d ON d.city_mun_psgc_code = c.city_mun_psgc_code
)
SELECT 'rows_present' AS check_name, CASE WHEN rows_built > 0 THEN 'PASS' ELSE 'FAIL' END AS status,
       '> 0' AS expected, CAST(rows_built AS STRING) AS actual FROM s
UNION ALL SELECT 'one_row_per_city_year_age_sex', CASE WHEN keys_built = rows_built THEN 'PASS' ELSE 'FAIL' END,
                 CAST(rows_built AS STRING), CAST(keys_built AS STRING) FROM s
UNION ALL SELECT 'male_and_female_only', CASE WHEN bad_sex = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_sex AS STRING) FROM s
UNION ALL SELECT 'age_5_to_24', CASE WHEN bad_age = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_age AS STRING) FROM s
UNION ALL SELECT 'city_in_dim', CASE WHEN no_city = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(no_city AS STRING) FROM s
UNION ALL SELECT 'population_valid', CASE WHEN bad_population = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_population AS STRING) FROM s
UNION ALL SELECT 'match_status_valid', CASE WHEN bad_status = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_status AS STRING) FROM s
UNION ALL SELECT 'both_census_years', CASE WHEN years = 2 THEN 'PASS' ELSE 'FAIL' END, '2', CAST(years AS STRING) FROM s
UNION ALL SELECT 'population_reconciles', CASE WHEN gold_population = silver_population THEN 'PASS' ELSE 'FAIL' END,
                 CAST(silver_population AS STRING), CAST(gold_population AS STRING) FROM s
UNION ALL SELECT 'both_sexes_equals_male_plus_female', CASE WHEN b.mismatched = 0 THEN 'PASS' ELSE 'FAIL' END,
                 '0 of ' || CAST(b.cells AS STRING), CAST(b.mismatched AS STRING) FROM both_sexes AS b
UNION ALL SELECT 'regular_cities_by_year', 'PASS', '2020 / 2024', CAST(cities_2020 AS STRING) || ' / ' || CAST(cities_2024 AS STRING) FROM s
UNION ALL SELECT 'excluded_population', CASE WHEN excluded_population = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(excluded_population AS STRING) FROM s
UNION ALL SELECT 'cities_not_comparable_2020_2024', 'PASS', 'count', CAST(not_comparable AS STRING) FROM s
) AS results;

MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (SELECT :run_id AS run_id, COUNT_IF(status = 'FAIL') AS fails FROM edu_access.`01-control`.data_quality_results
       WHERE run_id = :run_id AND source_id = 'fact_city_school_age_population' AND layer = 'gold'
         AND checked_at_utc >= session.gold_gate_started_at_utc) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'gold_build' AND t.source_id = 'fact_city_school_age_population'
WHEN MATCHED AND s.fails > 0 THEN UPDATE SET status = 'failed', finished_at_utc = current_timestamp(),
  failure_stage = 'gate', error_message = CAST(s.fails AS STRING) || ' FAIL result(s) in data_quality_results';

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Gold gate failed for fact_city_school_age_population: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s)') END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'fact_city_school_age_population' AND layer = 'gold' AND status = 'FAIL'
  AND checked_at_utc >= session.gold_gate_started_at_utc;

CREATE OR REPLACE TABLE edu_access.`05-gold`.fact_city_school_age_population USING DELTA AS SELECT * FROM edu_access.`05-gold`.fact_city_school_age_population_candidate;
ALTER TABLE edu_access.`05-gold`.fact_city_school_age_population OWNER TO `reached-hq`;

MERGE INTO edu_access.`01-control`.pipeline_runs AS t USING (SELECT :run_id AS run_id) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'gold_build' AND t.source_id = 'fact_city_school_age_population'
WHEN MATCHED THEN UPDATE SET status = 'succeeded', finished_at_utc = current_timestamp(), failure_stage = NULL, error_message = NULL;
