-- Gold build for fact_city_population (D-048): one row per regular city or municipality for reference
-- year 2024, the 2024 Census of Population count that the PSGC 2Q 2026 master publishes. AP1 labels it
-- "Population 2024" for every enrollment school year.
--   estimate_status  'available' when PSGC publishes a count, 'missing' when it does not
--   status_reason    NULL when available; otherwise PSGC's published marker ('#N/A' or blank)
-- The technical members have no row.
--
-- Writes fact_city_population_candidate; the gate publishes it only if no check fails.
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
ON t.run_id = s.run_id AND t.pipeline_name = 'gold_build' AND t.source_id = 'fact_city_population'
WHEN MATCHED THEN UPDATE SET
  status = 'running', started_at_utc = session.gold_built_at_utc, finished_at_utc = NULL,
  failure_stage = NULL, error_message = NULL, code_revision = session.gold_code_revision, job_run_id = s.run_id
WHEN NOT MATCHED THEN INSERT (run_id, pipeline_name, source_id, environment, status, started_at_utc, code_revision, job_run_id)
  VALUES (s.run_id, 'gold_build', 'fact_city_population', session.gold_environment, 'running',
          session.gold_built_at_utc, session.gold_code_revision, s.run_id);

CREATE SCHEMA IF NOT EXISTS edu_access.`05-gold`;
ALTER SCHEMA edu_access.`05-gold` OWNER TO `reached-hq`;

CREATE OR REPLACE TABLE edu_access.`05-gold`.fact_city_population_candidate USING DELTA AS
SELECT d.city_mun_psgc_code,
       2024 AS reference_year,
       CAST(p.population AS BIGINT) AS population,
       CASE WHEN p.population IS NOT NULL THEN 'available' ELSE 'missing' END AS estimate_status,
       CASE WHEN p.population IS NOT NULL THEN CAST(NULL AS STRING)
            WHEN p.population_null_reason = 'publisher_na' THEN 'PSGC publishes #N/A'
            ELSE 'PSGC publishes no population' END AS status_reason
FROM edu_access.`05-gold`.dim_city_municipality AS d
JOIN edu_access.`03-silver`.psa_psgc_clean AS p ON p.psgc_code = d.city_mun_psgc_code AND p.is_master_reference
WHERE d.member_type = 'regular';

ALTER TABLE edu_access.`05-gold`.fact_city_population_candidate OWNER TO `reached-hq`;
