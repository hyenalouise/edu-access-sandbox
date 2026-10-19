-- Analytics build for AP3, teacher pressure by level (metric specification, D-047): one row per regular
-- city or municipality, school year in the teacher fact (the years DepEd personnel covers) and education
-- level, every LGU kept. Project-defined: DepEd publishes no mother-school ID, so annexes cannot be added to
-- their mother school as DepEd's teacher-learner ratio does.
-- Scope at a level: active public schools that offer the level.
--   usable school         teacher_count above 0 and a complete learner_count at the level
--   zero-teacher annex    an annex reporting 0 teachers at every level keeps its learners in the numerator
--                         (not in the denominator, not in school coverage): 48 annexes, 21,114 learners in
--                         SY 2023-24 in the metric specification. An annex with teachers at another level
--                         only is a zero-teacher school at this level, like any other school.
--   learners_per_teacher  (learners of usable schools + zero-teacher annexes) / teachers of usable schools
--   school_coverage_pct   usable schools / schools in scope
--   learner_coverage_pct  learners in the ratio / complete learners in scope; the priority rule's
--                         coverage gate for each AP3 level (D-057)
-- Other zero-teacher schools, blank teacher counts, schools with no personnel row and incomplete learner
-- counts are counted beside the ratio. The funding split is over usable schools and is part of
-- teachers_in_ratio, never added to it. A ratio with no usable school is NULL with its reason, never 0.
--
-- Writes ap3_teacher_pressure_candidate; the gate publishes it only if no check fails.
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
ON t.run_id = s.run_id AND t.pipeline_name = 'analytics_build' AND t.source_id = 'ap3_teacher_pressure'
WHEN MATCHED THEN UPDATE SET
  status = 'running', started_at_utc = session.analytics_built_at_utc, finished_at_utc = NULL,
  failure_stage = NULL, error_message = NULL, code_revision = session.analytics_code_revision, job_run_id = s.run_id
WHEN NOT MATCHED THEN INSERT (run_id, pipeline_name, source_id, environment, status, started_at_utc, code_revision, job_run_id)
  VALUES (s.run_id, 'analytics_build', 'ap3_teacher_pressure', session.analytics_environment, 'running',
          session.analytics_built_at_utc, session.analytics_code_revision, s.run_id);

CREATE SCHEMA IF NOT EXISTS edu_access.`06-analytics`;
ALTER SCHEMA edu_access.`06-analytics` OWNER TO `reached-hq`;

CREATE OR REPLACE TABLE edu_access.`06-analytics`.ap3_teacher_pressure_candidate USING DELTA AS
WITH school_teachers AS (
  SELECT school_id, school_year, SUM(teacher_count) AS teachers
  FROM edu_access.`05-gold`.fact_school_teacher_capacity
  GROUP BY school_id, school_year
),
active AS (
  SELECT school_id, school_year
  FROM edu_access.`05-gold`.fact_school_enrollment
  WHERE sector = 'Public'
  GROUP BY school_id, school_year
  HAVING COALESCE(bool_or(is_offered AND learner_count > 0), FALSE)
),
scope AS (
  SELECT e.city_mun_psgc_code, e.school_year, e.education_level_code, e.learner_count,
         t.teacher_count, t.sef_provincial_teacher_count, t.sef_city_municipal_teacher_count,
         t.lgu_funded_teacher_count, t.other_funded_teacher_count,
         CASE WHEN e.learner_count IS NULL THEN 'incomplete_enrollment'
              WHEN t.school_id IS NULL THEN 'no_personnel_row'
              WHEN t.teacher_count IS NULL THEN 'teachers_blank'
              WHEN t.teacher_count > 0 THEN 'usable'
              WHEN e.annex_status = 'Annex/Extension School' AND st.teachers = 0 THEN 'zero_teacher_annex'
              ELSE 'zero_teacher' END AS teacher_state
  FROM edu_access.`05-gold`.fact_school_enrollment AS e
  JOIN active AS a ON a.school_id = e.school_id AND a.school_year = e.school_year
  LEFT JOIN edu_access.`05-gold`.fact_school_teacher_capacity AS t
    ON t.school_id = e.school_id AND t.school_year = e.school_year AND t.education_level_code = e.education_level_code
  LEFT JOIN school_teachers AS st ON st.school_id = e.school_id AND st.school_year = e.school_year
  WHERE e.sector = 'Public' AND e.is_offered
),
agg AS (
  SELECT city_mun_psgc_code, school_year, education_level_code,
         COUNT(*) AS schools_in_scope,
         COALESCE(COUNT_IF(teacher_state = 'usable'), 0) AS usable_schools,
         COALESCE(COUNT_IF(teacher_state = 'zero_teacher_annex'), 0) AS zero_teacher_annex_schools,
         COALESCE(COUNT_IF(teacher_state = 'zero_teacher'), 0) AS zero_teacher_schools,
         COALESCE(COUNT_IF(teacher_state = 'teachers_blank'), 0) AS teachers_blank_schools,
         COALESCE(COUNT_IF(teacher_state = 'no_personnel_row'), 0) AS no_personnel_row_schools,
         COALESCE(COUNT_IF(teacher_state = 'incomplete_enrollment'), 0) AS incomplete_enrollment_schools,
         SUM(learner_count) AS level_learners,
         SUM(CASE WHEN teacher_state IN ('usable', 'zero_teacher_annex') THEN learner_count END) AS learners_in_ratio,
         SUM(CASE WHEN teacher_state = 'zero_teacher_annex' THEN learner_count END) AS zero_teacher_annex_learners,
         SUM(CASE WHEN teacher_state IN ('zero_teacher', 'teachers_blank', 'no_personnel_row') THEN learner_count END) AS learners_without_teachers,
         SUM(CASE WHEN teacher_state = 'usable' THEN teacher_count END) AS teachers_in_ratio,
         SUM(CASE WHEN teacher_state = 'usable' THEN sef_provincial_teacher_count END) AS sef_provincial_teachers,
         SUM(CASE WHEN teacher_state = 'usable' THEN sef_city_municipal_teacher_count END) AS sef_city_municipal_teachers,
         SUM(CASE WHEN teacher_state = 'usable' THEN lgu_funded_teacher_count END) AS lgu_funded_teachers,
         SUM(CASE WHEN teacher_state = 'usable' THEN other_funded_teacher_count END) AS other_funded_teachers
  FROM scope
  GROUP BY city_mun_psgc_code, school_year, education_level_code
),
base AS (
  SELECT d.city_mun_psgc_code, d.city_mun_name, d.lgu_type, d.city_class, d.income_class,
         d.province_name, d.region_name, y.school_year, l.education_level_code,
         COALESCE(a.schools_in_scope, 0) AS schools_in_scope,
         COALESCE(a.usable_schools, 0) AS usable_schools,
         COALESCE(a.zero_teacher_annex_schools, 0) AS zero_teacher_annex_schools,
         COALESCE(a.zero_teacher_schools, 0) AS zero_teacher_schools,
         COALESCE(a.teachers_blank_schools, 0) AS teachers_blank_schools,
         COALESCE(a.no_personnel_row_schools, 0) AS no_personnel_row_schools,
         COALESCE(a.incomplete_enrollment_schools, 0) AS incomplete_enrollment_schools,
         COALESCE(a.level_learners, 0) AS level_learners,
         COALESCE(a.learners_in_ratio, 0) AS learners_in_ratio,
         COALESCE(a.zero_teacher_annex_learners, 0) AS zero_teacher_annex_learners,
         COALESCE(a.learners_without_teachers, 0) AS learners_without_teachers,
         COALESCE(a.teachers_in_ratio, 0) AS teachers_in_ratio,
         COALESCE(a.sef_provincial_teachers, 0) AS sef_provincial_teachers,
         COALESCE(a.sef_city_municipal_teachers, 0) AS sef_city_municipal_teachers,
         COALESCE(a.lgu_funded_teachers, 0) AS lgu_funded_teachers,
         COALESCE(a.other_funded_teachers, 0) AS other_funded_teachers
  FROM edu_access.`05-gold`.dim_city_municipality AS d
  CROSS JOIN (SELECT DISTINCT school_year FROM edu_access.`05-gold`.fact_school_teacher_capacity) AS y
  CROSS JOIN edu_access.`05-gold`.dim_education_level AS l
  LEFT JOIN agg AS a ON a.city_mun_psgc_code = d.city_mun_psgc_code AND a.school_year = y.school_year
    AND a.education_level_code = l.education_level_code
  WHERE d.member_type = 'regular'
)
SELECT base.*,
       CAST(learners_in_ratio AS DOUBLE) / NULLIF(teachers_in_ratio, 0) AS learners_per_teacher,
       CASE WHEN schools_in_scope = 0 THEN 'no active public school offers the level'
            WHEN usable_schools = 0 THEN 'no school with teachers at the level' END AS ratio_null_reason,
       100.0 * usable_schools / NULLIF(schools_in_scope, 0) AS school_coverage_pct,
       100.0 * learners_in_ratio / NULLIF(level_learners, 0) AS learner_coverage_pct
FROM base;

ALTER TABLE edu_access.`06-analytics`.ap3_teacher_pressure_candidate OWNER TO `reached-hq`;
