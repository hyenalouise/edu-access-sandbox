-- Gold build for fact_city_population (D-048, docs/architecture/data-model.md).
--
-- One row per regular member of dim_city_municipality and reference year, key (city_mun_psgc_code,
-- reference_year): the total population PSGC publishes for each city and municipality. AP1 reads it as
-- "Population 2024" for every enrollment school year (metric specification). The UNKNOWN and EXCLUDED
-- technical members get no row: a population belongs to a place.
--
-- Reads published tables only: dim_city_municipality and psa_psgc_clean (D-033, D-035). Writes
-- fact_city_population_candidate; the gate (the next task) checks it and publishes fact_city_population
-- only if no check fails, so a FAIL keeps the last good build. It rebuilds on every run.
--
-- Rules:
--   - reference_year is 2024: the master quarter's only population column is "2024 Population"
--     (D-012, D-033), so every row is 2024. A new census year is a new column, and a new rule here.
--   - population is Silver's as published: a 0 stays 0 and NULL stays NULL (D-035).
--   - estimate_status is 'available' with a population, or 'missing' without one, its reason from
--     Silver's population_null_reason, or 'Not a City or Mun row of the PSGC master quarter' for a member
--     PSGC lacks (the gate fails it). The model's other two values, 'provisional' and 'excluded', have
--     no rule yet, so no row takes them, and the gate fails one until a rule is approved.

CREATE SCHEMA IF NOT EXISTS edu_access.`05-gold`;
ALTER SCHEMA edu_access.`05-gold` OWNER TO `reached-hq`;

CREATE OR REPLACE TABLE edu_access.`05-gold`.fact_city_population_candidate USING DELTA AS
WITH regular AS (
  SELECT city_mun_psgc_code
  FROM edu_access.`05-gold`.dim_city_municipality
  WHERE member_type = 'regular'
),
psgc AS (
  SELECT psgc_code, population, population_null_reason
  FROM edu_access.`03-silver`.psa_psgc_clean
  WHERE is_master_reference AND geographic_level IN ('City', 'Mun')
)
SELECT
  r.city_mun_psgc_code,
  CAST(2024 AS INT) AS reference_year,
  CAST(p.population AS BIGINT) AS population,
  CASE WHEN p.population IS NOT NULL THEN 'available' ELSE 'missing' END AS estimate_status,
  CASE
    WHEN p.population IS NOT NULL THEN NULL
    WHEN p.population_null_reason = 'publisher_na' THEN 'PSGC publishes #N/A as the 2024 population'
    WHEN p.population_null_reason = 'blank' THEN 'PSGC publishes no 2024 population'
    WHEN p.psgc_code IS NULL THEN 'Not a City or Mun row of the PSGC master quarter'
  END AS status_reason
FROM regular AS r
LEFT JOIN psgc AS p ON p.psgc_code = r.city_mun_psgc_code;

COMMENT ON TABLE edu_access.`05-gold`.fact_city_population_candidate IS 'Unpublished build for the Gold gate, which may have failed. Do not read: use fact_city_population.';
ALTER TABLE edu_access.`05-gold`.fact_city_population_candidate OWNER TO `reached-hq`;
