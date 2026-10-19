-- Gold build for dim_education_level (D-048, D-047): the three reporting levels. ES is Kindergarten,
-- Grades 1-6 and ES non-graded; JHS is Grades 7-10 and JHS non-graded; SHS is Grades 11-12, all strands.
-- Classroom capacity has no level key, so there is no ALL member.
--
-- Writes dim_education_level_candidate; the gate publishes it only if no check fails.
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
ON t.run_id = s.run_id AND t.pipeline_name = 'gold_build' AND t.source_id = 'dim_education_level'
WHEN MATCHED THEN UPDATE SET
  status = 'running', started_at_utc = session.gold_built_at_utc, finished_at_utc = NULL,
  failure_stage = NULL, error_message = NULL, code_revision = session.gold_code_revision, job_run_id = s.run_id
WHEN NOT MATCHED THEN INSERT (run_id, pipeline_name, source_id, environment, status, started_at_utc, code_revision, job_run_id)
  VALUES (s.run_id, 'gold_build', 'dim_education_level', session.gold_environment, 'running',
          session.gold_built_at_utc, session.gold_code_revision, s.run_id);

CREATE SCHEMA IF NOT EXISTS edu_access.`05-gold`;
ALTER SCHEMA edu_access.`05-gold` OWNER TO `reached-hq`;

CREATE OR REPLACE TABLE edu_access.`05-gold`.dim_education_level_candidate USING DELTA AS
SELECT education_level_code, education_level_name
FROM (VALUES
  ('ES', 'Elementary: Kindergarten, Grades 1-6 and non-graded'),
  ('JHS', 'Junior High School: Grades 7-10 and non-graded'),
  ('SHS', 'Senior High School: Grades 11-12')
) AS v(education_level_code, education_level_name);

ALTER TABLE edu_access.`05-gold`.dim_education_level_candidate OWNER TO `reached-hq`;
