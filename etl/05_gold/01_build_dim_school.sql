-- Sandbox: the run starts in pipeline_runs as gold_build, like Silver and Integration; the gate records how it ended.
DECLARE OR REPLACE VARIABLE gold_run_id STRING;
SET VARIABLE gold_run_id = :run_id;
DECLARE OR REPLACE VARIABLE gold_code_revision STRING;
SET VARIABLE gold_code_revision = COALESCE(NULLIF(:code_revision, ''), 'UNSET');
DECLARE OR REPLACE VARIABLE gold_environment STRING;
SET VARIABLE gold_environment = COALESCE(NULLIF(:environment, ''), 'UNSET');
DECLARE OR REPLACE VARIABLE gold_built_at_utc TIMESTAMP;
SET VARIABLE gold_built_at_utc = current_timestamp();

MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (SELECT session.gold_run_id AS run_id) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'gold_build' AND t.source_id = 'dim_school'
WHEN MATCHED THEN UPDATE SET
  status = 'running', started_at_utc = session.gold_built_at_utc, finished_at_utc = NULL,
  failure_stage = NULL, error_message = NULL, code_revision = session.gold_code_revision, job_run_id = s.run_id
WHEN NOT MATCHED THEN INSERT (run_id, pipeline_name, source_id, environment, status, started_at_utc, code_revision, job_run_id)
  VALUES (s.run_id, 'gold_build', 'dim_school', session.gold_environment, 'running',
          session.gold_built_at_utc, session.gold_code_revision, s.run_id);

CREATE SCHEMA IF NOT EXISTS edu_access.`05-gold`;
ALTER SCHEMA edu_access.`05-gold` OWNER TO `reached-hq`;

CREATE OR REPLACE TABLE edu_access.`05-gold`.dim_school_candidate USING DELTA AS
WITH schools AS (
  SELECT DISTINCT school_id
  FROM edu_access.`03-silver`.deped_enrollment_clean
), ranked_names AS (
  SELECT school_id, school_name, ROW_NUMBER() OVER (PARTITION BY school_id ORDER BY school_year DESC) AS name_rank
  FROM edu_access.`03-silver`.deped_enrollment_clean
  WHERE school_name IS NOT NULL
)
SELECT s.school_id, n.school_name
FROM schools AS s
LEFT JOIN ranked_names AS n ON n.school_id = s.school_id AND n.name_rank = 1;

ALTER TABLE edu_access.`05-gold`.dim_school_candidate OWNER TO `reached-hq`;
