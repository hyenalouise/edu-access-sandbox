-- Gold build for dim_city_poverty (D-046): one row per regular city or municipality of
-- dim_city_municipality (1,642) with PSA's 2023 poverty estimate, carried unchanged from the poverty map
-- (D-054), and its status. Context only: never a ranking, flag, tier or score input.
--   estimated      PSA published a 2023 value
--   no_estimate    in the PSA file, values blank (Kalayaan)
--   not_in_source  no PSA city or municipal row; the City of Manila is one, because its 14 district
--                  estimates are not combined
-- The technical members have no row.
--
-- Writes dim_city_poverty_candidate; the gate publishes it only if no check fails.
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
ON t.run_id = s.run_id AND t.pipeline_name = 'gold_build' AND t.source_id = 'dim_city_poverty'
WHEN MATCHED THEN UPDATE SET
  status = 'running', started_at_utc = session.gold_built_at_utc, finished_at_utc = NULL,
  failure_stage = NULL, error_message = NULL, code_revision = session.gold_code_revision, job_run_id = s.run_id
WHEN NOT MATCHED THEN INSERT (run_id, pipeline_name, source_id, environment, status, started_at_utc, code_revision, job_run_id)
  VALUES (s.run_id, 'gold_build', 'dim_city_poverty', session.gold_environment, 'running',
          session.gold_built_at_utc, session.gold_code_revision, s.run_id);

CREATE SCHEMA IF NOT EXISTS edu_access.`05-gold`;
ALTER SCHEMA edu_access.`05-gold` OWNER TO `reached-hq`;

CREATE OR REPLACE TABLE edu_access.`05-gold`.dim_city_poverty_candidate USING DELTA AS
WITH pov AS (
  SELECT psgc_code, poverty_incidence, ci90_lower_limit, ci90_upper_limit, coefficient_of_variation,
         cv_over_20, estimate_status
  FROM edu_access.`04-integration`.psa_poverty_psgc_map
  WHERE estimate_year = 2023 AND match_status = 'matched' AND geographic_level = 'city_mun'
)
SELECT d.city_mun_psgc_code,
       2023 AS estimate_year,
       p.poverty_incidence,
       p.ci90_lower_limit AS poverty_ci90_lower,
       p.ci90_upper_limit AS poverty_ci90_upper,
       p.coefficient_of_variation AS poverty_cv,
       p.cv_over_20,
       CASE WHEN p.psgc_code IS NULL THEN 'not_in_source'
            WHEN p.poverty_incidence IS NULL THEN 'no_estimate'
            ELSE 'estimated' END AS poverty_status,
       CASE WHEN p.psgc_code IS NULL AND d.city_mun_psgc_code = '1380600000'
              THEN 'City of Manila not in the PSA estimates' || chr(59) || ' its 14 district estimates are not combined'
            WHEN p.psgc_code IS NULL THEN 'not in the PSA city and municipal estimates'
            WHEN p.poverty_incidence IS NULL THEN 'PSA published no 2023 estimate' END AS status_reason
FROM edu_access.`05-gold`.dim_city_municipality AS d
LEFT JOIN pov AS p ON p.psgc_code = d.city_mun_psgc_code
WHERE d.member_type = 'regular';

ALTER TABLE edu_access.`05-gold`.dim_city_poverty_candidate OWNER TO `reached-hq`;
