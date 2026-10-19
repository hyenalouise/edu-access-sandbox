-- ap2 classroom pressure under the same-type ratio methodology that supersedes D-057.
-- grain: one regular city or municipality for SY 2023-24.
-- the same-type reference pools only LGUs with no input issue; flagged outlier schools stay in every total.

CREATE SCHEMA IF NOT EXISTS edu_access.`06-analytics`;
ALTER SCHEMA edu_access.`06-analytics` OWNER TO `reached-hq`;

CREATE OR REPLACE TABLE edu_access.`06-analytics`.ap2_classroom_pressure_candidate USING DELTA AS
WITH lgus AS (
  SELECT city_mun_psgc_code, city_mun_name, lgu_type, province_psgc_code, province_name,
         region_psgc_code, region_name
  FROM edu_access.`05-gold`.dim_city_municipality
  WHERE member_type = 'regular'
), enrollment AS (
  SELECT school_id, city_mun_psgc_code,
         MAX(CASE WHEN is_offered AND learner_count > 0 THEN 1 ELSE 0 END) AS is_active,
         COUNT_IF(is_offered AND learner_count IS NULL) AS incomplete_levels,
         SUM(CASE WHEN is_offered AND learner_count IS NOT NULL THEN learner_count ELSE 0 END) AS complete_level_learners
  FROM edu_access.`05-gold`.fact_school_enrollment
  WHERE school_year = '2023-24' AND sector = 'Public' AND psgc_match_status = 'matched'
  GROUP BY school_id, city_mun_psgc_code
), schools AS (
  SELECT e.*, c.instructional_classrooms_total,
         e.incomplete_levels = 0 AS enrollment_complete,
         e.is_active = 1 AND e.incomplete_levels = 0 AND c.instructional_classrooms_total > 0 AS in_ratio,
         CASE WHEN e.incomplete_levels = 0 THEN e.complete_level_learners END AS total_learners
  FROM enrollment AS e
  LEFT JOIN edu_access.`05-gold`.fact_school_classroom_capacity AS c
    ON c.school_id = e.school_id AND c.school_year = '2023-24'
), school_ratios AS (
  SELECT s.*, l.lgu_type,
         CAST(total_learners AS DOUBLE) / NULLIF(instructional_classrooms_total, 0) AS school_ratio
  FROM schools AS s
  JOIN lgus AS l USING (city_mun_psgc_code)
  WHERE in_ratio
), fences AS (
  SELECT lgu_type,
         PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY school_ratio) AS q1,
         PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY school_ratio) AS q3
  FROM school_ratios
  GROUP BY lgu_type
), flagged AS (
  SELECT sr.school_id, sr.city_mun_psgc_code, sr.school_ratio > f.q3 + 3 * (f.q3 - f.q1) AS is_outlier
  FROM school_ratios AS sr
  JOIN fences AS f USING (lgu_type)
), metrics AS (
  SELECT l.*, CAST('2023-24' AS STRING) AS school_year,
         COALESCE(COUNT_IF(s.is_active = 1), 0) AS active_public_school_count,
         COUNT_IF(s.is_active = 1 AND s.instructional_classrooms_total > 0) AS usable_room_school_count,
         COALESCE(COUNT_IF(s.is_active = 1 AND s.in_ratio), 0) AS ratio_school_count,
         COALESCE(COUNT_IF(s.is_active = 1 AND NOT s.enrollment_complete), 0) AS incomplete_enrollment_school_count,
         CAST(COALESCE(SUM(CASE WHEN s.is_active = 1 AND s.enrollment_complete THEN s.total_learners ELSE 0 END), 0) AS BIGINT)
           AS public_school_enrollment,
         CAST(COALESCE(SUM(CASE WHEN s.in_ratio THEN s.total_learners ELSE 0 END), 0) AS BIGINT) AS eligible_learners,
         CAST(COALESCE(SUM(CASE WHEN s.in_ratio THEN s.instructional_classrooms_total ELSE 0 END), 0) AS BIGINT)
           AS reported_instructional_classrooms,
         COUNT_IF(s.is_active = 1 AND s.instructional_classrooms_total IS NULL) AS missing_room_school_count,
         COUNT_IF(s.is_active = 1 AND s.instructional_classrooms_total = 0) AS zero_room_school_count,
         COALESCE(COUNT_IF(o.is_outlier), 0) AS outlier_school_count,
         CAST(COALESCE(SUM(CASE WHEN s.in_ratio AND NOT o.is_outlier THEN s.total_learners ELSE 0 END), 0) AS BIGINT)
           AS eligible_learners_without_outliers,
         CAST(COALESCE(SUM(CASE WHEN s.in_ratio AND NOT o.is_outlier THEN s.instructional_classrooms_total ELSE 0 END), 0) AS BIGINT)
           AS reported_instructional_classrooms_without_outliers
  FROM lgus AS l
  LEFT JOIN schools AS s USING (city_mun_psgc_code)
  LEFT JOIN flagged AS o ON o.school_id = s.school_id AND o.city_mun_psgc_code = s.city_mun_psgc_code
  GROUP BY l.city_mun_psgc_code, l.city_mun_name, l.lgu_type, l.province_psgc_code, l.province_name,
           l.region_psgc_code, l.region_name
), ratios AS (
  SELECT *,
         outlier_school_count > 0 AS outlier_flag,
         CAST(eligible_learners AS DOUBLE) / NULLIF(reported_instructional_classrooms, 0) AS learners_per_classroom,
         CAST(eligible_learners_without_outliers AS DOUBLE) / NULLIF(reported_instructional_classrooms_without_outliers, 0)
           AS learners_per_classroom_without_outliers,
         -- a school counts as covered only with both a complete enrollment total and a usable room count: an active
         -- school with a blank offered level adds nothing to either learner sum, so only this count can show it is missing.
         CAST(100.0 * ratio_school_count / NULLIF(active_public_school_count, 0) AS DOUBLE) AS school_coverage_pct,
         CAST(100.0 * eligible_learners / NULLIF(public_school_enrollment, 0) AS DOUBLE) AS learner_coverage_pct
  FROM metrics
), assessed AS (
  -- input problems are found before the reference, so an LGU that fails them never moves the line others are judged against.
  SELECT *,
         CASE WHEN active_public_school_count = 0 THEN 'no active public school'
              WHEN learners_per_classroom IS NULL THEN 'no usable classroom denominator'
              WHEN school_coverage_pct < 90 OR learner_coverage_pct < 90 THEN 'coverage below 90%'
         END AS input_issue_reason
  FROM ratios
), type_references AS (
  SELECT lgu_type,
         CAST(SUM(eligible_learners) AS DOUBLE) / NULLIF(SUM(reported_instructional_classrooms), 0)
           AS national_same_type_ratio,
         COUNT(*) AS reference_lgu_count
  FROM assessed
  WHERE input_issue_reason IS NULL
  GROUP BY lgu_type
), compared AS (
  SELECT a.*, n.national_same_type_ratio, COALESCE(n.reference_lgu_count, 0) AS reference_lgu_count,
         a.learners_per_classroom / NULLIF(n.national_same_type_ratio, 0) AS relative_pressure,
         a.learners_per_classroom_without_outliers / NULLIF(n.national_same_type_ratio, 0) AS relative_pressure_without_outliers
  FROM assessed AS a
  LEFT JOIN type_references AS n USING (lgu_type)
), outliers_checked AS (
  -- outliers stay in the totals; they decide Data Review only when leaving them out moves the LGU across the reference.
  SELECT *,
         COALESCE(outlier_flag AND (relative_pressure_without_outliers IS NULL
           OR (relative_pressure > 1.0) <> (relative_pressure_without_outliers > 1.0)), FALSE) AS outlier_changes_classification
  FROM compared
), classified AS (
  SELECT *,
         COALESCE(input_issue_reason,
           CASE WHEN outlier_changes_classification THEN 'school-level outlier changes the classification' END)
           AS quality_issue_reason
  FROM outliers_checked
)
SELECT *,
       CASE WHEN quality_issue_reason IS NOT NULL THEN 'Data Review'
            WHEN relative_pressure > 1.0 THEN 'Above Reference'
            ELSE 'At or Below Reference' END AS classification,
       CAST(45 AS DOUBLE) AS contextual_45_to_1_reference,
       'context only because NSBI instructional rooms are not confirmed compatible with the statutory denominator' AS contextual_reference_note,
       'project-defined same-type pooled ratio' AS comparison_method,
       :code_revision AS code_revision
FROM classified;

COMMENT ON TABLE edu_access.`06-analytics`.ap2_classroom_pressure_candidate IS 'Unpublished AP2 build. Do not read: use ap2_classroom_pressure.';
ALTER TABLE edu_access.`06-analytics`.ap2_classroom_pressure_candidate OWNER TO `reached-hq`;

