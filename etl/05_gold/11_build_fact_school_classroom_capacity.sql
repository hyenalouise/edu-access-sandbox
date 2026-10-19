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
ON t.run_id = s.run_id AND t.pipeline_name = 'gold_build' AND t.source_id = 'fact_school_classroom_capacity'
WHEN MATCHED THEN UPDATE SET
  status = 'running', started_at_utc = session.gold_built_at_utc, finished_at_utc = NULL,
  failure_stage = NULL, error_message = NULL, code_revision = session.gold_code_revision, job_run_id = s.run_id
WHEN NOT MATCHED THEN INSERT (run_id, pipeline_name, source_id, environment, status, started_at_utc, code_revision, job_run_id)
  VALUES (s.run_id, 'gold_build', 'fact_school_classroom_capacity', session.gold_environment, 'running',
          session.gold_built_at_utc, session.gold_code_revision, s.run_id);

CREATE OR REPLACE TABLE edu_access.`05-gold`.fact_school_classroom_capacity_candidate USING DELTA AS
SELECT
  school_id,
  school_year,
  CASE
    WHEN es_classrooms_instructional IS NULL AND jhs_classrooms_instructional IS NULL AND shs_classrooms_instructional IS NULL THEN NULL
    ELSE COALESCE(es_classrooms_instructional, 0) + COALESCE(jhs_classrooms_instructional, 0) + COALESCE(shs_classrooms_instructional, 0)
  END AS instructional_classrooms_total,
  CASE
    WHEN es_temporary_learning_spaces IS NULL AND hs_temporary_learning_spaces IS NULL THEN NULL
    ELSE COALESCE(es_temporary_learning_spaces, 0) + COALESCE(hs_temporary_learning_spaces, 0)
  END AS temporary_learning_spaces,
  CASE
    WHEN es_classes_using_temporary_learning_spaces IS NULL AND hs_classes_using_temporary_learning_spaces IS NULL THEN NULL
    ELSE COALESCE(es_classes_using_temporary_learning_spaces, 0) + COALESCE(hs_classes_using_temporary_learning_spaces, 0)
  END AS classes_using_temporary_learning_spaces,
  CASE
    WHEN es_makeshift_rooms IS NULL AND hs_makeshift_rooms IS NULL THEN NULL
    ELSE COALESCE(es_makeshift_rooms, 0) + COALESCE(hs_makeshift_rooms, 0)
  END AS makeshift_rooms,
  CASE
    WHEN es_classes_using_makeshift_rooms IS NULL AND hs_classes_using_makeshift_rooms IS NULL THEN NULL
    ELSE COALESCE(es_classes_using_makeshift_rooms, 0) + COALESCE(hs_classes_using_makeshift_rooms, 0)
  END AS classes_using_makeshift_rooms
FROM edu_access.`03-silver`.deped_facilities_clean
WHERE sector = 'Public';

ALTER TABLE edu_access.`05-gold`.fact_school_classroom_capacity_candidate OWNER TO `reached-hq`;
