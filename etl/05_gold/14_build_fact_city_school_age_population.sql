-- Gold build for fact_city_school_age_population (D-048): PSA single-year-age population, 2020 and 2024,
-- by city or municipality, age (5-24 as published) and sex, from the census workbooks' Total Population
-- sheets (D-029). Only male and female rows are stored; the published both-sexes row is checked against
-- them in the gate and never stored, so Analytics cannot double count it.
-- The city comes from the reviewed name-to-PSGC map (D-055). The 2020 Special Geographic Area clusters
-- are PSA groupings with no PSGC unit; they go to the EXCLUDED member, summed, with their map status.
-- is_2020_2024_geography_comparable is false where the city itself changed between the censuses: Makati
-- and Taguig (the EMBO barangays) and the Special Geographic Area municipalities, which did not exist in
-- 2020. Province and region moves (Negros Island Region, Sulu, Maguindanao) leave a city comparable.
--
-- Writes fact_city_school_age_population_candidate; the gate publishes it only if no check fails.
--
-- Parameters, supplied by the job (or src/job/local_run.py):
--   :run_id, :code_revision, :environment

DECLARE OR REPLACE VARIABLE gold_run_id STRING;
SET VARIABLE gold_run_id = :run_id;
DECLARE OR REPLACE VARIABLE gold_code_revision STRING;
SET VARIABLE gold_code_revision = COALESCE(NULLIF(:code_revision, ''), 'UNSET');
DECLARE OR REPLACE VARIABLE gold_environment STRING;
SET VARIABLE gold_environment = COALESCE(NULLIF(:environment, ''), 'UNSET');
DECLARE OR REPLACE VARIABLE gold_built_at_utc TIMESTAMP;
SET VARIABLE gold_built_at_utc = current_timestamp();

-- The run starts; the gate records how it ended (D-020).
MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (SELECT session.gold_run_id AS run_id) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'gold_build' AND t.source_id = 'fact_city_school_age_population'
WHEN MATCHED THEN UPDATE SET
  status = 'running', started_at_utc = session.gold_built_at_utc, finished_at_utc = NULL,
  failure_stage = NULL, error_message = NULL, code_revision = session.gold_code_revision, job_run_id = s.run_id
WHEN NOT MATCHED THEN INSERT (run_id, pipeline_name, source_id, environment, status, started_at_utc, code_revision, job_run_id)
  VALUES (s.run_id, 'gold_build', 'fact_city_school_age_population', session.gold_environment, 'running',
          session.gold_built_at_utc, session.gold_code_revision, s.run_id);

CREATE SCHEMA IF NOT EXISTS edu_access.`05-gold`;
ALTER SCHEMA edu_access.`05-gold` OWNER TO `reached-hq`;

CREATE OR REPLACE TABLE edu_access.`05-gold`.fact_city_school_age_population_candidate USING DELTA AS
WITH pop AS (
  SELECT x.census_year, x.age, x.sex, x.population,
         CASE WHEN m.match_status = 'matched' THEN m.psgc_code ELSE 'EXCLUDED' END AS city_mun_psgc_code,
         m.match_status
  FROM edu_access.`03-silver`.psa_school_age_population_clean AS x
  JOIN edu_access.`04-integration`.psa_school_age_population_psgc_map AS m
    ON m.census_year = x.census_year AND m.place_name = x.place_name AND m.parent_name = x.parent_name
  WHERE x.level = 'city_municipality' AND x.population_concept = 'total' AND x.sex IN ('male', 'female')
)
SELECT p.city_mun_psgc_code,
       p.census_year AS reference_year,
       p.age,
       p.sex,
       SUM(CAST(p.population AS BIGINT)) AS population,
       MIN(p.match_status) AS psgc_match_status,
       COALESCE(NOT (d.member_type <> 'regular' OR d.is_sga
                     OR p.city_mun_psgc_code IN ('1380300000', '1381500000')), FALSE) AS is_2020_2024_geography_comparable
FROM pop AS p
LEFT JOIN edu_access.`05-gold`.dim_city_municipality AS d ON d.city_mun_psgc_code = p.city_mun_psgc_code
GROUP BY p.city_mun_psgc_code, p.census_year, p.age, p.sex, d.member_type, d.is_sga;

ALTER TABLE edu_access.`05-gold`.fact_city_school_age_population_candidate OWNER TO `reached-hq`;
