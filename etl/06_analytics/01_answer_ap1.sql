-- Analytics build for AP1, school-provision context (metric specification, D-047): one row per regular
-- city or municipality and enrollment school year, every LGU kept even with no public school.
-- Scope: public schools, including annexes; overseas and excluded schools are not in any LGU.
--   active school             at least one offered level has a complete learner_count above 0
--   all-level total           ES + JHS + SHS when every offered level is complete, otherwise NULL
--   learners_per_public_school  learners of active schools with a complete total / those schools
--   ap1_coverage_pct          share of active public schools whose all-level total is complete; the
--                             priority rule's coverage gate for AP1 (D-057)
--   population_per_public_school  Population 2024 / all active public schools, for every school year
--   barangays_without_public_es   regular PSGC barangays with no active public school that offers ES and
--                             is matched to the barangay; "at most" when the LGU has schools matched to
--                             the city but not a barangay (barangay_count_is_upper_bound)
-- A ratio with no usable denominator is NULL with its reason, never 0.
--
-- Writes ap1_school_provision_candidate; the gate publishes it only if no check fails.
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
ON t.run_id = s.run_id AND t.pipeline_name = 'analytics_build' AND t.source_id = 'ap1_school_provision'
WHEN MATCHED THEN UPDATE SET
  status = 'running', started_at_utc = session.analytics_built_at_utc, finished_at_utc = NULL,
  failure_stage = NULL, error_message = NULL, code_revision = session.analytics_code_revision, job_run_id = s.run_id
WHEN NOT MATCHED THEN INSERT (run_id, pipeline_name, source_id, environment, status, started_at_utc, code_revision, job_run_id)
  VALUES (s.run_id, 'analytics_build', 'ap1_school_provision', session.analytics_environment, 'running',
          session.analytics_built_at_utc, session.analytics_code_revision, s.run_id);

CREATE SCHEMA IF NOT EXISTS edu_access.`06-analytics`;
ALTER SCHEMA edu_access.`06-analytics` OWNER TO `reached-hq`;

CREATE OR REPLACE TABLE edu_access.`06-analytics`.ap1_school_provision_candidate USING DELTA AS
WITH school AS (
  SELECT school_id, school_year,
         MAX(city_mun_psgc_code) AS city_mun_psgc_code,
         MAX(barangay_psgc_code) AS barangay_psgc_code,
         MAX(annex_status) AS annex_status,
         COALESCE(bool_or(is_offered AND learner_count > 0), FALSE) AS is_active,
         COALESCE(bool_or(education_level_code = 'ES' AND is_offered), FALSE) AS offers_es,
         CASE WHEN COALESCE(COUNT_IF(is_offered AND learner_count IS NULL), 0) = 0 THEN SUM(learner_count) END AS total_learners,
         SUM(learner_count) AS complete_level_learners
  FROM edu_access.`05-gold`.fact_school_enrollment
  WHERE sector = 'Public'
  GROUP BY school_id, school_year
),
agg AS (
  SELECT city_mun_psgc_code, school_year,
         COALESCE(COUNT_IF(is_active), 0) AS active_public_schools,
         COALESCE(COUNT_IF(is_active AND annex_status = 'Annex/Extension School'), 0) AS active_annexes,
         COALESCE(COUNT_IF(NOT is_active), 0) AS inactive_public_schools,
         COALESCE(COUNT_IF(is_active AND total_learners IS NOT NULL), 0) AS complete_total_schools,
         COALESCE(COUNT_IF(is_active AND total_learners IS NULL), 0) AS incomplete_total_schools,
         SUM(CASE WHEN is_active AND total_learners IS NOT NULL THEN total_learners END) AS public_learners,
         SUM(CASE WHEN is_active AND total_learners IS NULL THEN complete_level_learners END) AS incomplete_school_learners_audit,
         COALESCE(COUNT_IF(is_active AND barangay_psgc_code LIKE 'UNK-%'), 0) AS schools_without_barangay_match
  FROM school
  GROUP BY city_mun_psgc_code, school_year
),
served AS (
  SELECT DISTINCT school_year, barangay_psgc_code FROM school WHERE is_active AND offers_es
),
barangays AS (
  SELECT b.city_mun_psgc_code, y.school_year,
         COUNT(*) AS regular_barangays,
         COALESCE(COUNT_IF(s.barangay_psgc_code IS NULL), 0) AS barangays_without_public_es
  FROM edu_access.`05-gold`.dim_barangay AS b
  CROSS JOIN edu_access.`05-gold`.dim_school_year AS y
  LEFT JOIN served AS s ON s.barangay_psgc_code = b.barangay_psgc_code AND s.school_year = y.school_year
  WHERE b.member_type = 'regular'
  GROUP BY b.city_mun_psgc_code, y.school_year
),
base AS (
  SELECT d.city_mun_psgc_code, d.city_mun_name, d.lgu_type, d.city_class, d.income_class,
         d.province_name, d.region_name, y.school_year,
         COALESCE(a.active_public_schools, 0) AS active_public_schools,
         COALESCE(a.active_annexes, 0) AS active_annexes,
         COALESCE(a.inactive_public_schools, 0) AS inactive_public_schools,
         COALESCE(a.complete_total_schools, 0) AS complete_total_schools,
         COALESCE(a.incomplete_total_schools, 0) AS incomplete_total_schools,
         COALESCE(a.public_learners, 0) AS public_learners,
         a.incomplete_school_learners_audit,
         COALESCE(a.schools_without_barangay_match, 0) AS schools_without_barangay_match,
         p.population AS population_2024,
         p.estimate_status AS population_status,
         COALESCE(b.regular_barangays, 0) AS regular_barangays,
         COALESCE(b.barangays_without_public_es, 0) AS barangays_without_public_es
  FROM edu_access.`05-gold`.dim_city_municipality AS d
  CROSS JOIN edu_access.`05-gold`.dim_school_year AS y
  LEFT JOIN agg AS a ON a.city_mun_psgc_code = d.city_mun_psgc_code AND a.school_year = y.school_year
  LEFT JOIN edu_access.`05-gold`.fact_city_population AS p
    ON p.city_mun_psgc_code = d.city_mun_psgc_code AND p.reference_year = 2024
  LEFT JOIN barangays AS b ON b.city_mun_psgc_code = d.city_mun_psgc_code AND b.school_year = y.school_year
  WHERE d.member_type = 'regular'
)
SELECT base.*,
       CAST(public_learners AS DOUBLE) / NULLIF(complete_total_schools, 0) AS learners_per_public_school,
       CASE WHEN active_public_schools = 0 THEN 'no active public school'
            WHEN complete_total_schools = 0 THEN 'no active public school with complete enrollment' END AS learners_per_school_null_reason,
       100.0 * complete_total_schools / NULLIF(active_public_schools, 0) AS ap1_coverage_pct,
       CASE WHEN population_status = 'available' THEN CAST(population_2024 AS DOUBLE) / NULLIF(active_public_schools, 0) END AS population_per_public_school,
       CASE WHEN population_status IS DISTINCT FROM 'available' THEN 'Population 2024 not available'
            WHEN active_public_schools = 0 THEN 'no active public school' END AS population_per_school_null_reason,
       100.0 * barangays_without_public_es / NULLIF(regular_barangays, 0) AS barangays_without_public_es_pct,
       schools_without_barangay_match > 0 AS barangay_count_is_upper_bound
FROM base;

ALTER TABLE edu_access.`06-analytics`.ap1_school_provision_candidate OWNER TO `reached-hq`;
