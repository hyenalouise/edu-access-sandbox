-- ap1 school provision under the same-type ratio methodology that supersedes D-057.
-- grain: one regular city or municipality for SY 2024-25 schools against the 2024 census (AP2 and AP3 use SY 2023-24).
-- the same-type reference pools only LGUs with no input issue.

CREATE SCHEMA IF NOT EXISTS edu_access.`06-analytics`;
ALTER SCHEMA edu_access.`06-analytics` OWNER TO `reached-hq`;

CREATE OR REPLACE TABLE edu_access.`06-analytics`.ap1_school_provision_candidate USING DELTA AS
WITH lgus AS (
  SELECT city_mun_psgc_code, city_mun_name, lgu_type, province_psgc_code, province_name,
         region_psgc_code, region_name
  FROM edu_access.`05-gold`.dim_city_municipality
  WHERE member_type = 'regular'
), school_rows AS (
  SELECT school_id, city_mun_psgc_code,
         MAX(CASE WHEN is_offered AND learner_count > 0 THEN 1 ELSE 0 END) AS is_active,
         COUNT_IF(is_offered AND learner_count IS NULL) AS incomplete_offered_levels,
         SUM(CASE WHEN is_offered AND learner_count IS NOT NULL THEN learner_count ELSE 0 END) AS complete_level_learners
  FROM edu_access.`05-gold`.fact_school_enrollment
  WHERE school_year = '2024-25' AND sector = 'Public' AND psgc_match_status = 'matched'
  GROUP BY school_id, city_mun_psgc_code
), schools AS (
  SELECT city_mun_psgc_code,
         COUNT_IF(is_active = 1) AS active_public_school_count,
         COUNT_IF(is_active = 1 AND incomplete_offered_levels = 0) AS complete_enrollment_school_count,
         COUNT_IF(is_active = 1 AND incomplete_offered_levels > 0) AS incomplete_enrollment_school_count,
         SUM(CASE WHEN is_active = 1 AND incomplete_offered_levels = 0 THEN complete_level_learners ELSE 0 END)
           AS public_school_enrollment
  FROM school_rows
  GROUP BY city_mun_psgc_code
), population AS (
  SELECT city_mun_psgc_code, CAST(SUM(population) AS BIGINT) AS school_age_population
  FROM edu_access.`05-gold`.fact_city_school_age_population
  WHERE reference_year = 2024 AND sex IN ('male', 'female') AND age BETWEEN 5 AND 17
    AND psgc_match_status = 'matched'
  GROUP BY city_mun_psgc_code
), metrics AS (
  SELECT l.*, CAST('2024-25' AS STRING) AS school_year, CAST(2024 AS INT) AS population_reference_year,
         p.school_age_population,
         COALESCE(s.active_public_school_count, 0) AS active_public_school_count,
         COALESCE(s.complete_enrollment_school_count, 0) AS complete_enrollment_school_count,
         COALESCE(s.incomplete_enrollment_school_count, 0) AS incomplete_enrollment_school_count,
         CAST(COALESCE(s.public_school_enrollment, 0) AS BIGINT) AS public_school_enrollment,
         CAST(p.school_age_population AS DOUBLE) / NULLIF(s.active_public_school_count, 0)
           AS school_age_population_per_public_school,
         CAST(s.public_school_enrollment AS DOUBLE) / NULLIF(s.complete_enrollment_school_count, 0)
           AS learners_per_public_school,
         CAST(100.0 * s.complete_enrollment_school_count / NULLIF(s.active_public_school_count, 0) AS DOUBLE)
           AS coverage_pct
  FROM lgus AS l
  LEFT JOIN schools AS s USING (city_mun_psgc_code)
  LEFT JOIN population AS p USING (city_mun_psgc_code)
), assessed AS (
  -- input problems are found before the reference, so an LGU that fails them never moves the line others are judged against.
  SELECT *,
         CASE WHEN school_age_population IS NULL THEN 'missing 2024 school-age population'
              WHEN active_public_school_count = 0 THEN 'no active public school'
              WHEN coverage_pct IS NULL OR coverage_pct < 90 THEN 'coverage below 90%'
         END AS input_issue_reason
  FROM metrics
), type_references AS (
  SELECT lgu_type,
         CAST(SUM(school_age_population) AS DOUBLE) / NULLIF(SUM(active_public_school_count), 0)
           AS national_same_type_ratio,
         COUNT(*) AS reference_lgu_count
  FROM assessed
  WHERE input_issue_reason IS NULL
  GROUP BY lgu_type
), classified AS (
  SELECT a.*, r.national_same_type_ratio, COALESCE(r.reference_lgu_count, 0) AS reference_lgu_count,
         a.school_age_population_per_public_school / NULLIF(r.national_same_type_ratio, 0) AS relative_pressure,
         FALSE AS outlier_flag,
         a.input_issue_reason AS quality_issue_reason
  FROM assessed AS a
  LEFT JOIN type_references AS r USING (lgu_type)
)
SELECT *,
       CASE WHEN quality_issue_reason IS NOT NULL OR outlier_flag THEN 'Data Review'
            WHEN relative_pressure > 1.0 THEN 'Above Reference'
            ELSE 'At or Below Reference' END AS classification,
       'project-defined same-type pooled ratio' AS comparison_method,
       :code_revision AS code_revision
FROM classified;

COMMENT ON TABLE edu_access.`06-analytics`.ap1_school_provision_candidate IS 'Unpublished AP1 build. Do not read: use ap1_school_provision.';
ALTER TABLE edu_access.`06-analytics`.ap1_school_provision_candidate OWNER TO `reached-hq`;

