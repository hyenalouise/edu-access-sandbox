-- Gold build for dim_school_year (D-048): one row per school year in enrollment Silver, the source that
-- defines which school years exist (D-051). Facilities and personnel years are in
-- fact_school_year_source_availability, so a failed facilities or personnel lane cannot stop this table.
--
-- Writes dim_school_year_candidate. The table itself is never written here: the gate checks the
-- candidate and publishes it only if no check fails (as D-025 does for Silver).
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
ON t.run_id = s.run_id AND t.pipeline_name = 'gold_build' AND t.source_id = 'dim_school_year'
WHEN MATCHED THEN UPDATE SET
  status = 'running', started_at_utc = session.gold_built_at_utc, finished_at_utc = NULL,
  failure_stage = NULL, error_message = NULL, code_revision = session.gold_code_revision, job_run_id = s.run_id
WHEN NOT MATCHED THEN INSERT (run_id, pipeline_name, source_id, environment, status, started_at_utc, code_revision, job_run_id)
  VALUES (s.run_id, 'gold_build', 'dim_school_year', session.gold_environment, 'running',
          session.gold_built_at_utc, session.gold_code_revision, s.run_id);

CREATE SCHEMA IF NOT EXISTS edu_access.`05-gold`;
ALTER SCHEMA edu_access.`05-gold` OWNER TO `reached-hq`;

-- school_year is published as 'YYYY-YY'; the gate checks that the end year matches the suffix.
CREATE OR REPLACE TABLE edu_access.`05-gold`.dim_school_year_candidate USING DELTA AS
SELECT school_year,
       CAST(substr(school_year, 1, 4) AS INT) AS start_year,
       CAST(substr(school_year, 1, 4) AS INT) + 1 AS end_year
FROM (SELECT DISTINCT school_year FROM edu_access.`03-silver`.deped_enrollment_clean) AS y;

ALTER TABLE edu_access.`05-gold`.dim_school_year_candidate OWNER TO `reached-hq`;
