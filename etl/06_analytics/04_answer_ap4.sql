-- Analytics build for AP4, school-age population and enrollment (metric specification): one row per
-- regular city or municipality and census period, each pairing a census with the school year that starts
-- in the same year: 2020 with SY 2020-21, 2024 with SY 2024-25. No other year has an AP4 value, and
-- population is never interpolated.
--   school_age_population   PSA total population, ages 5-17, male + female
--   enrollment_all_sectors  learners in public, private and SUC/LUC schools located in the LGU (Philippine
--                           Schools Overseas are in no LGU); schools whose all-level total is incomplete are
--                           left out and counted
--   population_enrollment_gap = population - enrollment; negative is kept (a school hub)
--   gap_share = gap / population; public_school_share = public enrollment / all-sector enrollment
--   enrollment_school_coverage_pct = schools with complete all-level enrollment / schools in scope
-- AP4 is context only. Its gap and coverage never enter the LGU priority tier.
--   gap_change_2020_2024 on the 2024 row, flagged where the city's geography is not comparable
-- Population is where people live and enrollment is where the school is: the gap is not an out-of-school
-- count or an enrollment rate.
--
-- Writes ap4_population_enrollment_gap_candidate; the gate publishes it only if no check fails.
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
ON t.run_id = s.run_id AND t.pipeline_name = 'analytics_build' AND t.source_id = 'ap4_population_enrollment_gap'
WHEN MATCHED THEN UPDATE SET
  status = 'running', started_at_utc = session.analytics_built_at_utc, finished_at_utc = NULL,
  failure_stage = NULL, error_message = NULL, code_revision = session.analytics_code_revision, job_run_id = s.run_id
WHEN NOT MATCHED THEN INSERT (run_id, pipeline_name, source_id, environment, status, started_at_utc, code_revision, job_run_id)
  VALUES (s.run_id, 'analytics_build', 'ap4_population_enrollment_gap', session.analytics_environment, 'running',
          session.analytics_built_at_utc, session.analytics_code_revision, s.run_id);

CREATE SCHEMA IF NOT EXISTS edu_access.`06-analytics`;
ALTER SCHEMA edu_access.`06-analytics` OWNER TO `reached-hq`;

CREATE OR REPLACE TABLE edu_access.`06-analytics`.ap4_population_enrollment_gap_candidate USING DELTA AS
WITH periods AS (
  SELECT * FROM (VALUES (2020, '2020-21'), (2024, '2024-25')) AS v(reference_year, school_year)
),
school AS (
  SELECT school_id, school_year,
         MAX(city_mun_psgc_code) AS city_mun_psgc_code,
         MAX(sector) AS sector,
         CASE WHEN COALESCE(COUNT_IF(is_offered AND learner_count IS NULL), 0) = 0 THEN SUM(learner_count) END AS total_learners
  FROM edu_access.`05-gold`.fact_school_enrollment
  WHERE sector IN ('Public', 'Private', 'SUC/LUC')
  GROUP BY school_id, school_year
),
enrolled AS (
  SELECT city_mun_psgc_code, school_year,
         SUM(total_learners) AS enrollment_all_sectors,
         SUM(CASE WHEN sector = 'Public' THEN total_learners END) AS public_enrollment,
         COUNT(*) AS schools_in_scope,
         COALESCE(COUNT_IF(total_learners IS NOT NULL), 0) AS complete_total_schools,
         COALESCE(COUNT_IF(total_learners IS NULL), 0) AS incomplete_total_schools
  FROM school
  GROUP BY city_mun_psgc_code, school_year
),
population AS (
  SELECT city_mun_psgc_code, reference_year,
         SUM(population) AS school_age_population,
         COALESCE(bool_and(is_2020_2024_geography_comparable), FALSE) AS is_comparable
  FROM edu_access.`05-gold`.fact_city_school_age_population
  WHERE age BETWEEN 5 AND 17 AND sex IN ('male', 'female')
  GROUP BY city_mun_psgc_code, reference_year
),
base AS (
  SELECT d.city_mun_psgc_code, d.city_mun_name, d.lgu_type, d.city_class, d.income_class,
         d.province_name, d.region_name, p.reference_year, p.school_year,
         pop.school_age_population,
         COALESCE(e.enrollment_all_sectors, 0) AS enrollment_all_sectors,
         COALESCE(e.public_enrollment, 0) AS public_enrollment,
         COALESCE(e.schools_in_scope, 0) AS schools_in_scope,
         COALESCE(e.complete_total_schools, 0) AS complete_total_schools,
         COALESCE(e.incomplete_total_schools, 0) AS incomplete_total_schools,
         COALESCE(pop.is_comparable, FALSE) AS is_2020_2024_geography_comparable
  FROM edu_access.`05-gold`.dim_city_municipality AS d
  CROSS JOIN periods AS p
  LEFT JOIN enrolled AS e ON e.city_mun_psgc_code = d.city_mun_psgc_code AND e.school_year = p.school_year
  LEFT JOIN population AS pop ON pop.city_mun_psgc_code = d.city_mun_psgc_code AND pop.reference_year = p.reference_year
  WHERE d.member_type = 'regular'
),
gaps AS (
  SELECT base.*,
         school_age_population - enrollment_all_sectors AS population_enrollment_gap,
         CAST(school_age_population - enrollment_all_sectors AS DOUBLE) / NULLIF(school_age_population, 0) AS gap_share,
         CAST(public_enrollment AS DOUBLE) / NULLIF(enrollment_all_sectors, 0) AS public_school_share,
         100.0 * complete_total_schools / NULLIF(schools_in_scope, 0) AS enrollment_school_coverage_pct,
         CASE WHEN school_age_population IS NULL THEN 'no PSA school-age population for this census' END AS gap_null_reason
  FROM base
)
SELECT g.*,
       CASE WHEN g.reference_year = 2024 THEN g.population_enrollment_gap - g20.population_enrollment_gap END AS gap_change_2020_2024
FROM gaps AS g
LEFT JOIN gaps AS g20 ON g20.city_mun_psgc_code = g.city_mun_psgc_code AND g20.reference_year = 2020;

ALTER TABLE edu_access.`06-analytics`.ap4_population_enrollment_gap_candidate OWNER TO `reached-hq`;
