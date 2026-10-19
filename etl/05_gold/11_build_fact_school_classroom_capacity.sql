-- Gold build for fact_school_classroom_capacity (D-048, D-047): one row per facilities Silver school and
-- school year, all sectors (Analytics applies the AP scope). Rooms are whole-school because integrated
-- schools share them across levels.
--   instructional_classrooms_total  the ES, JHS and SHS instructional-room counts that are not blank,
--                                   summed; NULL when all three are blank, never 0
--   the four supporting measures     ES plus combined HS as published; NULL only when both are blank
-- None of the supporting measures is substituted into the instructional-room total.
--
-- Writes fact_school_classroom_capacity_candidate; the gate publishes it only if no check fails.
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
ON t.run_id = s.run_id AND t.pipeline_name = 'gold_build' AND t.source_id = 'fact_school_classroom_capacity'
WHEN MATCHED THEN UPDATE SET
  status = 'running', started_at_utc = session.gold_built_at_utc, finished_at_utc = NULL,
  failure_stage = NULL, error_message = NULL, code_revision = session.gold_code_revision, job_run_id = s.run_id
WHEN NOT MATCHED THEN INSERT (run_id, pipeline_name, source_id, environment, status, started_at_utc, code_revision, job_run_id)
  VALUES (s.run_id, 'gold_build', 'fact_school_classroom_capacity', session.gold_environment, 'running',
          session.gold_built_at_utc, session.gold_code_revision, s.run_id);

CREATE SCHEMA IF NOT EXISTS edu_access.`05-gold`;
ALTER SCHEMA edu_access.`05-gold` OWNER TO `reached-hq`;

CREATE OR REPLACE TABLE edu_access.`05-gold`.fact_school_classroom_capacity_candidate USING DELTA AS
SELECT school_id, school_year,
       CASE WHEN COALESCE(es_classrooms_instructional, jhs_classrooms_instructional, shs_classrooms_instructional) IS NULL THEN CAST(NULL AS INT)
            ELSE COALESCE(es_classrooms_instructional, 0) + COALESCE(jhs_classrooms_instructional, 0) + COALESCE(shs_classrooms_instructional, 0)
       END AS instructional_classrooms_total,
       CASE WHEN COALESCE(es_temporary_learning_spaces, hs_temporary_learning_spaces) IS NULL THEN CAST(NULL AS INT)
            ELSE COALESCE(es_temporary_learning_spaces, 0) + COALESCE(hs_temporary_learning_spaces, 0)
       END AS temporary_learning_spaces,
       CASE WHEN COALESCE(es_classes_using_temporary_learning_spaces, hs_classes_using_temporary_learning_spaces) IS NULL THEN CAST(NULL AS INT)
            ELSE COALESCE(es_classes_using_temporary_learning_spaces, 0) + COALESCE(hs_classes_using_temporary_learning_spaces, 0)
       END AS classes_using_temporary_learning_spaces,
       CASE WHEN COALESCE(es_makeshift_rooms, hs_makeshift_rooms) IS NULL THEN CAST(NULL AS INT)
            ELSE COALESCE(es_makeshift_rooms, 0) + COALESCE(hs_makeshift_rooms, 0)
       END AS makeshift_rooms,
       CASE WHEN COALESCE(es_classes_using_makeshift_rooms, hs_classes_using_makeshift_rooms) IS NULL THEN CAST(NULL AS INT)
            ELSE COALESCE(es_classes_using_makeshift_rooms, 0) + COALESCE(hs_classes_using_makeshift_rooms, 0)
       END AS classes_using_makeshift_rooms
FROM edu_access.`03-silver`.deped_facilities_clean;

ALTER TABLE edu_access.`05-gold`.fact_school_classroom_capacity_candidate OWNER TO `reached-hq`;
