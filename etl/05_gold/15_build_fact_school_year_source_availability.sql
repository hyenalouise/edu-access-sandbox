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
ON t.run_id = s.run_id AND t.pipeline_name = 'gold_build' AND t.source_id = 'fact_school_year_source_availability'
WHEN MATCHED THEN UPDATE SET
  status = 'running', started_at_utc = session.gold_built_at_utc, finished_at_utc = NULL,
  failure_stage = NULL, error_message = NULL, code_revision = session.gold_code_revision, job_run_id = s.run_id
WHEN NOT MATCHED THEN INSERT (run_id, pipeline_name, source_id, environment, status, started_at_utc, code_revision, job_run_id)
  VALUES (s.run_id, 'gold_build', 'fact_school_year_source_availability', session.gold_environment, 'running',
          session.gold_built_at_utc, session.gold_code_revision, s.run_id);

CREATE OR REPLACE TABLE edu_access.`05-gold`.fact_school_year_source_availability_candidate USING DELTA AS
WITH years AS (
  SELECT school_year FROM edu_access.`05-gold`.dim_school_year
), sources AS (
  SELECT * FROM VALUES ('deped_enrollment'), ('deped_facilities'), ('deped_personnel') AS s(source_id)
), available AS (
  SELECT school_year, 'deped_enrollment' AS source_id FROM edu_access.`03-silver`.deped_enrollment_clean GROUP BY school_year
  UNION ALL
  SELECT school_year, 'deped_facilities' AS source_id FROM edu_access.`03-silver`.deped_facilities_clean GROUP BY school_year
  UNION ALL
  SELECT school_year, 'deped_personnel' AS source_id FROM edu_access.`03-silver`.deped_personnel_clean GROUP BY school_year
)
SELECT y.school_year, s.source_id, a.school_year IS NOT NULL AS has_data
FROM years AS y
CROSS JOIN sources AS s
LEFT JOIN available AS a ON a.school_year = y.school_year AND a.source_id = s.source_id;

ALTER TABLE edu_access.`05-gold`.fact_school_year_source_availability_candidate OWNER TO `reached-hq`;
