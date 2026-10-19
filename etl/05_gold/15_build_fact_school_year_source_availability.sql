-- Gold build for fact_school_year_source_availability (D-051): one row per school year in dim_school_year
-- and each DepEd source (enrollment, facilities, personnel). has_data is true when that source's Silver
-- table has rows for the school year, so the dashboard can say "not available" for a source's missing
-- years. It does not say that every school or level has a usable value: fact coverage still applies.
--
-- Writes fact_school_year_source_availability_candidate; the gate publishes it only if no check fails.
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
ON t.run_id = s.run_id AND t.pipeline_name = 'gold_build' AND t.source_id = 'fact_school_year_source_availability'
WHEN MATCHED THEN UPDATE SET
  status = 'running', started_at_utc = session.gold_built_at_utc, finished_at_utc = NULL,
  failure_stage = NULL, error_message = NULL, code_revision = session.gold_code_revision, job_run_id = s.run_id
WHEN NOT MATCHED THEN INSERT (run_id, pipeline_name, source_id, environment, status, started_at_utc, code_revision, job_run_id)
  VALUES (s.run_id, 'gold_build', 'fact_school_year_source_availability', session.gold_environment, 'running',
          session.gold_built_at_utc, session.gold_code_revision, s.run_id);

CREATE SCHEMA IF NOT EXISTS edu_access.`05-gold`;
ALTER SCHEMA edu_access.`05-gold` OWNER TO `reached-hq`;

CREATE OR REPLACE TABLE edu_access.`05-gold`.fact_school_year_source_availability_candidate USING DELTA AS
WITH present AS (
  SELECT DISTINCT school_year, 'deped_enrollment' AS source_id FROM edu_access.`03-silver`.deped_enrollment_clean
  UNION ALL
  SELECT DISTINCT school_year, 'deped_facilities' FROM edu_access.`03-silver`.deped_facilities_clean
  UNION ALL
  SELECT DISTINCT school_year, 'deped_personnel' FROM edu_access.`03-silver`.deped_personnel_clean
)
SELECT y.school_year, src.source_id, p.source_id IS NOT NULL AS has_data
FROM edu_access.`05-gold`.dim_school_year AS y
CROSS JOIN (VALUES ('deped_enrollment'), ('deped_facilities'), ('deped_personnel')) AS src(source_id)
LEFT JOIN present AS p ON p.school_year = y.school_year AND p.source_id = src.source_id;

ALTER TABLE edu_access.`05-gold`.fact_school_year_source_availability_candidate OWNER TO `reached-hq`;
