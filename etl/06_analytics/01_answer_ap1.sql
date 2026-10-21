-- ap1 descriptive school-provision context.
-- grain: one regular city or municipality for SY 2023-24.
-- measures: learners per public school and 2024 school-age population (5-17) per active public school.
-- neither measure is a new-school need or priority score: establishment needs distance, demand and feasibility data.
-- coverage gate: at least 90% of active public schools have complete all-level enrollment. a school that
-- offers a level but has every offered count blank is not active, but it is missing data, so it joins the denominator.

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
         COUNT_IF(is_offered) > 0 AND COUNT_IF(is_offered AND learner_count IS NOT NULL) = 0 AS is_blank,
         MAX(CASE WHEN annex_status = 'Annex/Extension School' THEN 1 ELSE 0 END) AS is_annex,
         SUM(CASE WHEN is_offered AND learner_count IS NOT NULL THEN learner_count ELSE 0 END) AS complete_level_learners
  FROM edu_access.`05-gold`.fact_school_enrollment
  WHERE school_year = '2023-24' AND sector = 'Public' AND psgc_match_status = 'matched'
  GROUP BY school_id, city_mun_psgc_code
), schools AS (
  SELECT city_mun_psgc_code,
         COUNT_IF(is_active = 1) AS active_public_school_count,
         COUNT_IF(is_active = 1 AND is_annex = 1) AS annex_school_count,
         COUNT_IF(is_active = 1 AND incomplete_offered_levels = 0) AS complete_enrollment_school_count,
         COUNT_IF(is_active = 1 AND incomplete_offered_levels > 0) AS incomplete_enrollment_school_count,
         COUNT_IF(is_blank) AS blank_enrollment_school_count,
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
  SELECT l.*, CAST('2023-24' AS STRING) AS school_year, CAST(2024 AS INT) AS population_reference_year,
         COALESCE(s.active_public_school_count, 0) AS active_public_school_count,
         COALESCE(s.annex_school_count, 0) AS annex_school_count,
         COALESCE(s.complete_enrollment_school_count, 0) AS complete_enrollment_school_count,
         COALESCE(s.incomplete_enrollment_school_count, 0) AS incomplete_enrollment_school_count,
         COALESCE(s.blank_enrollment_school_count, 0) AS blank_enrollment_school_count,
         CAST(COALESCE(s.public_school_enrollment, 0) AS BIGINT) AS public_school_enrollment,
         p.school_age_population
  FROM lgus AS l
  LEFT JOIN schools AS s USING (city_mun_psgc_code)
  LEFT JOIN population AS p USING (city_mun_psgc_code)
), ratios AS (
  SELECT *,
         CAST(public_school_enrollment AS DOUBLE) / NULLIF(complete_enrollment_school_count, 0)
           AS learners_per_public_school,
         CAST(school_age_population AS DOUBLE) / NULLIF(active_public_school_count, 0)
           AS school_age_population_per_public_school,
         CAST(100.0 * complete_enrollment_school_count
           / NULLIF(active_public_school_count + blank_enrollment_school_count, 0) AS DOUBLE) AS coverage_pct
  FROM metrics
), gated AS (
  SELECT *,
         CASE WHEN active_public_school_count = 0 THEN 'no active public school'
              WHEN learners_per_public_school IS NULL THEN 'no school with complete enrollment'
              WHEN coverage_pct < 90 THEN 'coverage below 90%'
         END AS not_assessed_reason
  FROM ratios
)
SELECT g.*,
       g.not_assessed_reason IS NULL AS is_assessed,
       'descriptive learners per public school, not a school-establishment or priority measure' AS measure_label,
       :code_revision AS code_revision
FROM gated AS g;

COMMENT ON TABLE edu_access.`06-analytics`.ap1_school_provision_candidate IS 'Unpublished AP1 build. Do not read: use ap1_school_provision.';
ALTER TABLE edu_access.`06-analytics`.ap1_school_provision_candidate OWNER TO `reached-hq`;
