-- Gold build for fact_school_teacher_capacity (D-048, D-047): one row per personnel Silver school, school
-- year and education level, all sectors (Analytics applies the AP scope). teacher_count is the sum of the
-- level's approved teaching fields in the metric specification: Teacher I-III, Master Teacher I-IV, Head
-- Teacher I-VI, SPED/SNED, Special Science, Instructors, and the four locally funded categories, with
-- Kindergarten's locally funded teachers under ES. Principals and non-teaching staff are left out.
-- Each funding column is a subset of teacher_count for the dashboard split, never added to it again.
-- A total is NULL only when every field in it is NULL; a recorded zero stays zero.
--
-- Writes fact_school_teacher_capacity_candidate; the gate publishes it only if no check fails.
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
ON t.run_id = s.run_id AND t.pipeline_name = 'gold_build' AND t.source_id = 'fact_school_teacher_capacity'
WHEN MATCHED THEN UPDATE SET
  status = 'running', started_at_utc = session.gold_built_at_utc, finished_at_utc = NULL,
  failure_stage = NULL, error_message = NULL, code_revision = session.gold_code_revision, job_run_id = s.run_id
WHEN NOT MATCHED THEN INSERT (run_id, pipeline_name, source_id, environment, status, started_at_utc, code_revision, job_run_id)
  VALUES (s.run_id, 'gold_build', 'fact_school_teacher_capacity', session.gold_environment, 'running',
          session.gold_built_at_utc, session.gold_code_revision, s.run_id);

CREATE SCHEMA IF NOT EXISTS edu_access.`05-gold`;
ALTER SCHEMA edu_access.`05-gold` OWNER TO `reached-hq`;

CREATE OR REPLACE TABLE edu_access.`05-gold`.fact_school_teacher_capacity_candidate USING DELTA AS
SELECT school_id, school_year, 'ES' AS education_level_code,
       CASE WHEN COALESCE(es_teacher_i, es_teacher_ii, es_teacher_iii, es_master_teacher_i, es_master_teacher_ii, es_master_teacher_iii, es_master_teacher_iv,
           es_head_teacher_i, es_head_teacher_ii, es_head_teacher_iii, es_head_teacher_iv, es_head_teacher_v, es_head_teacher_vi, es_sped_sned_teacher_i,
           es_sped_sned_teacher_ii, es_sped_sned_teacher_iii, es_sped_sned_teacher_iv, es_sped_sned_teacher_v, kinder_teachers_sef_province, es_teachers_sef_province, kinder_teachers_sef_municipality_city,
           es_teachers_sef_municipality_city, kinder_teachers_lgu_funding, es_teachers_lgu_funding, kinder_teachers_other_funding, es_teachers_other_funding) IS NULL THEN CAST(NULL AS INT)
     ELSE COALESCE(es_teacher_i, 0) + COALESCE(es_teacher_ii, 0) + COALESCE(es_teacher_iii, 0) + COALESCE(es_master_teacher_i, 0) + COALESCE(es_master_teacher_ii, 0) +
           COALESCE(es_master_teacher_iii, 0) + COALESCE(es_master_teacher_iv, 0) + COALESCE(es_head_teacher_i, 0) + COALESCE(es_head_teacher_ii, 0) + COALESCE(es_head_teacher_iii, 0) +
           COALESCE(es_head_teacher_iv, 0) + COALESCE(es_head_teacher_v, 0) + COALESCE(es_head_teacher_vi, 0) + COALESCE(es_sped_sned_teacher_i, 0) + COALESCE(es_sped_sned_teacher_ii, 0) +
           COALESCE(es_sped_sned_teacher_iii, 0) + COALESCE(es_sped_sned_teacher_iv, 0) + COALESCE(es_sped_sned_teacher_v, 0) + COALESCE(kinder_teachers_sef_province, 0) + COALESCE(es_teachers_sef_province, 0) +
           COALESCE(kinder_teachers_sef_municipality_city, 0) + COALESCE(es_teachers_sef_municipality_city, 0) + COALESCE(kinder_teachers_lgu_funding, 0) + COALESCE(es_teachers_lgu_funding, 0) + COALESCE(kinder_teachers_other_funding, 0) +
           COALESCE(es_teachers_other_funding, 0) END AS teacher_count,
       CASE WHEN COALESCE(kinder_teachers_sef_province, es_teachers_sef_province) IS NULL THEN CAST(NULL AS INT)
     ELSE COALESCE(kinder_teachers_sef_province, 0) + COALESCE(es_teachers_sef_province, 0) END AS sef_provincial_teacher_count,
       CASE WHEN COALESCE(kinder_teachers_sef_municipality_city, es_teachers_sef_municipality_city) IS NULL THEN CAST(NULL AS INT)
     ELSE COALESCE(kinder_teachers_sef_municipality_city, 0) + COALESCE(es_teachers_sef_municipality_city, 0) END AS sef_city_municipal_teacher_count,
       CASE WHEN COALESCE(kinder_teachers_lgu_funding, es_teachers_lgu_funding) IS NULL THEN CAST(NULL AS INT)
     ELSE COALESCE(kinder_teachers_lgu_funding, 0) + COALESCE(es_teachers_lgu_funding, 0) END AS lgu_funded_teacher_count,
       CASE WHEN COALESCE(kinder_teachers_other_funding, es_teachers_other_funding) IS NULL THEN CAST(NULL AS INT)
     ELSE COALESCE(kinder_teachers_other_funding, 0) + COALESCE(es_teachers_other_funding, 0) END AS other_funded_teacher_count
FROM edu_access.`03-silver`.deped_personnel_clean
UNION ALL
SELECT school_id, school_year, 'JHS' AS education_level_code,
       CASE WHEN COALESCE(jhs_teacher_i, jhs_teacher_ii, jhs_teacher_iii, jhs_master_teacher_i, jhs_master_teacher_ii, jhs_master_teacher_iii, jhs_master_teacher_iv,
           jhs_head_teacher_i, jhs_head_teacher_ii, jhs_head_teacher_iii, jhs_head_teacher_iv, jhs_head_teacher_v, jhs_head_teacher_vi, jhs_sped_teacher_i,
           jhs_sped_teacher_ii, jhs_sped_teacher_iii, jhs_sped_teacher_iv, jhs_sped_teacher_v, jhs_special_science_teacher_i, jhs_instructor_i, jhs_instructor_ii,
           jhs_instructor_iii, jhs_teachers_sef_province, jhs_teachers_sef_municipality_city, jhs_teachers_lgu_funding, jhs_teachers_other_funding) IS NULL THEN CAST(NULL AS INT)
     ELSE COALESCE(jhs_teacher_i, 0) + COALESCE(jhs_teacher_ii, 0) + COALESCE(jhs_teacher_iii, 0) + COALESCE(jhs_master_teacher_i, 0) + COALESCE(jhs_master_teacher_ii, 0) +
           COALESCE(jhs_master_teacher_iii, 0) + COALESCE(jhs_master_teacher_iv, 0) + COALESCE(jhs_head_teacher_i, 0) + COALESCE(jhs_head_teacher_ii, 0) + COALESCE(jhs_head_teacher_iii, 0) +
           COALESCE(jhs_head_teacher_iv, 0) + COALESCE(jhs_head_teacher_v, 0) + COALESCE(jhs_head_teacher_vi, 0) + COALESCE(jhs_sped_teacher_i, 0) + COALESCE(jhs_sped_teacher_ii, 0) +
           COALESCE(jhs_sped_teacher_iii, 0) + COALESCE(jhs_sped_teacher_iv, 0) + COALESCE(jhs_sped_teacher_v, 0) + COALESCE(jhs_special_science_teacher_i, 0) + COALESCE(jhs_instructor_i, 0) +
           COALESCE(jhs_instructor_ii, 0) + COALESCE(jhs_instructor_iii, 0) + COALESCE(jhs_teachers_sef_province, 0) + COALESCE(jhs_teachers_sef_municipality_city, 0) + COALESCE(jhs_teachers_lgu_funding, 0) +
           COALESCE(jhs_teachers_other_funding, 0) END AS teacher_count,
       CASE WHEN COALESCE(jhs_teachers_sef_province) IS NULL THEN CAST(NULL AS INT)
     ELSE COALESCE(jhs_teachers_sef_province, 0) END AS sef_provincial_teacher_count,
       CASE WHEN COALESCE(jhs_teachers_sef_municipality_city) IS NULL THEN CAST(NULL AS INT)
     ELSE COALESCE(jhs_teachers_sef_municipality_city, 0) END AS sef_city_municipal_teacher_count,
       CASE WHEN COALESCE(jhs_teachers_lgu_funding) IS NULL THEN CAST(NULL AS INT)
     ELSE COALESCE(jhs_teachers_lgu_funding, 0) END AS lgu_funded_teacher_count,
       CASE WHEN COALESCE(jhs_teachers_other_funding) IS NULL THEN CAST(NULL AS INT)
     ELSE COALESCE(jhs_teachers_other_funding, 0) END AS other_funded_teacher_count
FROM edu_access.`03-silver`.deped_personnel_clean
UNION ALL
SELECT school_id, school_year, 'SHS' AS education_level_code,
       CASE WHEN COALESCE(shs_teacher_i, shs_teacher_ii, shs_teacher_iii, shs_master_teacher_i, shs_master_teacher_ii, shs_master_teacher_iii, shs_master_teacher_iv,
           shs_head_teacher_i, shs_head_teacher_ii, shs_head_teacher_iii, shs_head_teacher_iv, shs_head_teacher_v, shs_head_teacher_vi, shs_special_science_teacher_i,
           shs_teachers_sef_province, shs_teachers_sef_municipality_city, shs_teachers_lgu_funding, shs_teachers_other_funding) IS NULL THEN CAST(NULL AS INT)
     ELSE COALESCE(shs_teacher_i, 0) + COALESCE(shs_teacher_ii, 0) + COALESCE(shs_teacher_iii, 0) + COALESCE(shs_master_teacher_i, 0) + COALESCE(shs_master_teacher_ii, 0) +
           COALESCE(shs_master_teacher_iii, 0) + COALESCE(shs_master_teacher_iv, 0) + COALESCE(shs_head_teacher_i, 0) + COALESCE(shs_head_teacher_ii, 0) + COALESCE(shs_head_teacher_iii, 0) +
           COALESCE(shs_head_teacher_iv, 0) + COALESCE(shs_head_teacher_v, 0) + COALESCE(shs_head_teacher_vi, 0) + COALESCE(shs_special_science_teacher_i, 0) + COALESCE(shs_teachers_sef_province, 0) +
           COALESCE(shs_teachers_sef_municipality_city, 0) + COALESCE(shs_teachers_lgu_funding, 0) + COALESCE(shs_teachers_other_funding, 0) END AS teacher_count,
       CASE WHEN COALESCE(shs_teachers_sef_province) IS NULL THEN CAST(NULL AS INT)
     ELSE COALESCE(shs_teachers_sef_province, 0) END AS sef_provincial_teacher_count,
       CASE WHEN COALESCE(shs_teachers_sef_municipality_city) IS NULL THEN CAST(NULL AS INT)
     ELSE COALESCE(shs_teachers_sef_municipality_city, 0) END AS sef_city_municipal_teacher_count,
       CASE WHEN COALESCE(shs_teachers_lgu_funding) IS NULL THEN CAST(NULL AS INT)
     ELSE COALESCE(shs_teachers_lgu_funding, 0) END AS lgu_funded_teacher_count,
       CASE WHEN COALESCE(shs_teachers_other_funding) IS NULL THEN CAST(NULL AS INT)
     ELSE COALESCE(shs_teachers_other_funding, 0) END AS other_funded_teacher_count
FROM edu_access.`03-silver`.deped_personnel_clean;

ALTER TABLE edu_access.`05-gold`.fact_school_teacher_capacity_candidate OWNER TO `reached-hq`;
