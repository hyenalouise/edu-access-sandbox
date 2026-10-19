-- Analytics build for AP2, classroom pressure (metric specification, D-047): one row per regular city or
-- municipality and school year in the classroom fact (the years DepEd facilities covers), every LGU kept
-- even with no public school.
-- Scope: active public schools. Each school's all-level learners and whole-school instructional rooms are
-- summed to the LGU, over the same schools only:
--   usable school          instructional_classrooms_total above 0 and a complete all-level total
--   learners_per_room      learners of usable schools / their rooms ("learners per reported
--                          instructional room"; source DepEd School Facilities (NSBI), not DepEd's
--                          classroom-learner ratio)
--   school_coverage_pct    usable schools / active public schools
--   learner_coverage_pct   learners of usable schools / learners of active schools with a complete total;
--                          the priority rule's coverage gate for AP2 (D-057)
-- Schools with blank rooms, zero rooms, no facilities row, or an incomplete total stay out of both sums and
-- are counted beside the ratio. A ratio with no usable school is NULL with its reason, never 0.
--
-- Writes ap2_classroom_pressure_candidate; the gate publishes it only if no check fails.
--
-- Parameters, supplied by the job (or src/job/local_run.py):
--   :run_id, :code_revision, :environment

DECLARE OR REPLACE VARIABLE analytics_run_id STRING;
SET VARIABLE analytics_run_id = :run_id;
DECLARE OR REPLACE VARIABLE analytics_code_revision STRING;
SET VARIABLE analytics_code_revision = COALESCE(NULLIF(:code_revision, ''), 'UNSET');
DECLARE OR REPLACE VARIABLE analytics_environment STRING;
SET VARIABLE analytics_environment = COALESCE(NULLIF(:environment, ''), 'UNSET');
DECLARE OR REPLACE VARIABLE analytics_built_at_utc TIMESTAMP;
SET VARIABLE analytics_built_at_utc = current_timestamp();

-- The run starts; the gate records how it ended (D-020).
MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (SELECT session.analytics_run_id AS run_id) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'analytics_build' AND t.source_id = 'ap2_classroom_pressure'
WHEN MATCHED THEN UPDATE SET
  status = 'running', started_at_utc = session.analytics_built_at_utc, finished_at_utc = NULL,
  failure_stage = NULL, error_message = NULL, code_revision = session.analytics_code_revision, job_run_id = s.run_id
WHEN NOT MATCHED THEN INSERT (run_id, pipeline_name, source_id, environment, status, started_at_utc, code_revision, job_run_id)
  VALUES (s.run_id, 'analytics_build', 'ap2_classroom_pressure', session.analytics_environment, 'running',
          session.analytics_built_at_utc, session.analytics_code_revision, s.run_id);

CREATE SCHEMA IF NOT EXISTS edu_access.`06-analytics`;
ALTER SCHEMA edu_access.`06-analytics` OWNER TO `reached-hq`;

CREATE OR REPLACE TABLE edu_access.`06-analytics`.ap2_classroom_pressure_candidate USING DELTA AS
WITH school AS (
  SELECT school_id, school_year,
         MAX(city_mun_psgc_code) AS city_mun_psgc_code,
         COALESCE(bool_or(is_offered AND learner_count > 0), FALSE) AS is_active,
         CASE WHEN COALESCE(COUNT_IF(is_offered AND learner_count IS NULL), 0) = 0 THEN SUM(learner_count) END AS total_learners
  FROM edu_access.`05-gold`.fact_school_enrollment
  WHERE sector = 'Public'
  GROUP BY school_id, school_year
),
rooms AS (
  SELECT s.city_mun_psgc_code, s.school_year, s.total_learners,
         r.instructional_classrooms_total AS rooms,
         CASE WHEN s.total_learners IS NULL THEN 'incomplete_enrollment'
              WHEN r.school_id IS NULL THEN 'no_facilities_row'
              WHEN r.instructional_classrooms_total IS NULL THEN 'rooms_blank'
              WHEN r.instructional_classrooms_total = 0 THEN 'rooms_zero'
              ELSE 'usable' END AS room_state
  FROM school AS s
  LEFT JOIN edu_access.`05-gold`.fact_school_classroom_capacity AS r
    ON r.school_id = s.school_id AND r.school_year = s.school_year
  WHERE s.is_active
),
agg AS (
  SELECT city_mun_psgc_code, school_year,
         COUNT(*) AS active_public_schools,
         COALESCE(COUNT_IF(room_state = 'usable'), 0) AS usable_schools,
         COALESCE(COUNT_IF(room_state = 'rooms_blank'), 0) AS rooms_blank_schools,
         COALESCE(COUNT_IF(room_state = 'rooms_zero'), 0) AS rooms_zero_schools,
         COALESCE(COUNT_IF(room_state = 'no_facilities_row'), 0) AS no_facilities_row_schools,
         COALESCE(COUNT_IF(room_state = 'incomplete_enrollment'), 0) AS incomplete_enrollment_schools,
         SUM(CASE WHEN room_state = 'usable' THEN total_learners END) AS learners_in_ratio,
         SUM(CASE WHEN room_state = 'usable' THEN rooms END) AS rooms_in_ratio,
         SUM(total_learners) AS public_learners,
         SUM(CASE WHEN room_state IN ('rooms_blank', 'rooms_zero', 'no_facilities_row') THEN total_learners END) AS learners_without_usable_rooms
  FROM rooms
  GROUP BY city_mun_psgc_code, school_year
),
base AS (
  SELECT d.city_mun_psgc_code, d.city_mun_name, d.lgu_type, d.city_class, d.income_class,
         d.province_name, d.region_name, y.school_year,
         COALESCE(a.active_public_schools, 0) AS active_public_schools,
         COALESCE(a.usable_schools, 0) AS usable_schools,
         COALESCE(a.rooms_blank_schools, 0) AS rooms_blank_schools,
         COALESCE(a.rooms_zero_schools, 0) AS rooms_zero_schools,
         COALESCE(a.no_facilities_row_schools, 0) AS no_facilities_row_schools,
         COALESCE(a.incomplete_enrollment_schools, 0) AS incomplete_enrollment_schools,
         COALESCE(a.learners_in_ratio, 0) AS learners_in_ratio,
         COALESCE(a.rooms_in_ratio, 0) AS rooms_in_ratio,
         COALESCE(a.public_learners, 0) AS public_learners,
         COALESCE(a.learners_without_usable_rooms, 0) AS learners_without_usable_rooms
  FROM edu_access.`05-gold`.dim_city_municipality AS d
  CROSS JOIN (SELECT DISTINCT school_year FROM edu_access.`05-gold`.fact_school_classroom_capacity) AS y
  LEFT JOIN agg AS a ON a.city_mun_psgc_code = d.city_mun_psgc_code AND a.school_year = y.school_year
  WHERE d.member_type = 'regular'
)
SELECT base.*,
       CAST(learners_in_ratio AS DOUBLE) / NULLIF(rooms_in_ratio, 0) AS learners_per_room,
       CASE WHEN active_public_schools = 0 THEN 'no active public school'
            WHEN usable_schools = 0 THEN 'no school with a usable room count' END AS ratio_null_reason,
       100.0 * usable_schools / NULLIF(active_public_schools, 0) AS school_coverage_pct,
       100.0 * learners_in_ratio / NULLIF(public_learners, 0) AS learner_coverage_pct
FROM base;

ALTER TABLE edu_access.`06-analytics`.ap2_classroom_pressure_candidate OWNER TO `reached-hq`;
