-- ap3 teacher pressure under the same-type ratio methodology that supersedes D-057.
-- grain: one regular city or municipality for SY 2023-24, with ES, JHS and SHS pooled.
-- the same-type reference pools only LGUs with no input issue; flagged outlier school levels stay in every total.

CREATE SCHEMA IF NOT EXISTS edu_access.`06-analytics`;
ALTER SCHEMA edu_access.`06-analytics` OWNER TO `reached-hq`;

CREATE OR REPLACE TABLE edu_access.`06-analytics`.ap3_teacher_pressure_candidate USING DELTA AS
WITH lgus AS (
  SELECT city_mun_psgc_code, city_mun_name, lgu_type, province_psgc_code, province_name,
         region_psgc_code, region_name
  FROM edu_access.`05-gold`.dim_city_municipality
  WHERE member_type = 'regular'
), active AS (
  SELECT school_id, MAX(CASE WHEN is_offered AND learner_count > 0 THEN 1 ELSE 0 END) AS is_active
  FROM edu_access.`05-gold`.fact_school_enrollment
  WHERE school_year = '2023-24' AND sector = 'Public' AND psgc_match_status = 'matched'
  GROUP BY school_id
), school_levels AS (
  SELECT e.school_id, e.city_mun_psgc_code, e.education_level_code, e.annex_status, e.learner_count,
         t.teacher_count, t.school_id IS NOT NULL AS has_teacher_row,
         COALESCE(t.teacher_count > 0, FALSE) AS teacher_usable,
         COALESCE(e.annex_status = 'Annex/Extension School' AND t.teacher_count = 0, FALSE) AS zero_teacher_annex
  FROM edu_access.`05-gold`.fact_school_enrollment AS e
  JOIN active AS a ON a.school_id = e.school_id AND a.is_active = 1
  JOIN lgus AS l ON l.city_mun_psgc_code = e.city_mun_psgc_code
  LEFT JOIN edu_access.`05-gold`.fact_school_teacher_capacity AS t
    ON t.school_id = e.school_id AND t.school_year = e.school_year
    AND t.education_level_code = e.education_level_code
  WHERE e.school_year = '2023-24' AND e.sector = 'Public' AND e.psgc_match_status = 'matched' AND e.is_offered
), school_ratios AS (
  SELECT s.*, l.lgu_type, CAST(s.learner_count AS DOUBLE) / NULLIF(s.teacher_count, 0) AS school_ratio
  FROM school_levels AS s
  JOIN lgus AS l USING (city_mun_psgc_code)
  WHERE s.learner_count IS NOT NULL AND s.teacher_usable
), fences AS (
  SELECT lgu_type,
         PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY school_ratio) AS q1,
         PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY school_ratio) AS q3
  FROM school_ratios
  GROUP BY lgu_type
), flagged AS (
  SELECT sr.school_id, sr.education_level_code, sr.city_mun_psgc_code,
         sr.school_ratio > f.q3 + 3 * (f.q3 - f.q1) AS is_outlier
  FROM school_ratios AS sr
  JOIN fences AS f USING (lgu_type)
), levels AS (
  SELECT s.*, COALESCE(o.is_outlier, FALSE) AS is_outlier
  FROM school_levels AS s
  LEFT JOIN flagged AS o ON o.school_id = s.school_id AND o.education_level_code = s.education_level_code
    AND o.city_mun_psgc_code = s.city_mun_psgc_code
), metrics AS (
  SELECT l.*, CAST('2023-24' AS STRING) AS school_year,
         COUNT(s.school_id) AS offered_school_level_count,
         COUNT_IF(s.learner_count IS NULL) AS incomplete_enrollment_school_level_count,
         COUNT_IF(s.teacher_usable) AS usable_teacher_school_level_count,
         COUNT_IF(NOT s.has_teacher_row OR s.teacher_count IS NULL) AS missing_teacher_school_level_count,
         COUNT_IF(s.teacher_count = 0) AS zero_teacher_school_level_count,
         COUNT_IF(s.zero_teacher_annex) AS zero_teacher_annex_school_level_count,
         CAST(COALESCE(SUM(s.learner_count), 0) AS BIGINT) AS public_school_enrollment,
         CAST(COALESCE(SUM(CASE WHEN s.teacher_usable OR s.zero_teacher_annex THEN s.learner_count ELSE 0 END), 0) AS BIGINT)
           AS eligible_learners,
         CAST(COALESCE(SUM(CASE WHEN s.teacher_usable AND s.learner_count IS NOT NULL THEN s.teacher_count ELSE 0 END), 0) AS BIGINT)
           AS approved_teacher_count,
         COALESCE(COUNT_IF(s.is_outlier), 0) AS outlier_school_level_count,
         CAST(COALESCE(SUM(CASE WHEN (s.teacher_usable OR s.zero_teacher_annex) AND NOT s.is_outlier
                                THEN s.learner_count ELSE 0 END), 0) AS BIGINT) AS eligible_learners_without_outliers,
         CAST(COALESCE(SUM(CASE WHEN s.teacher_usable AND s.learner_count IS NOT NULL AND NOT s.is_outlier
                                THEN s.teacher_count ELSE 0 END), 0) AS BIGINT) AS approved_teacher_count_without_outliers
  FROM lgus AS l
  LEFT JOIN levels AS s USING (city_mun_psgc_code)
  GROUP BY l.city_mun_psgc_code, l.city_mun_name, l.lgu_type, l.province_psgc_code, l.province_name,
           l.region_psgc_code, l.region_name
), ratios AS (
  SELECT *,
         outlier_school_level_count > 0 AS outlier_flag,
         CAST(eligible_learners AS DOUBLE) / NULLIF(approved_teacher_count, 0) AS learners_per_teacher,
         CAST(eligible_learners_without_outliers AS DOUBLE) / NULLIF(approved_teacher_count_without_outliers, 0)
           AS learners_per_teacher_without_outliers,
         CAST(100.0 * usable_teacher_school_level_count / NULLIF(offered_school_level_count, 0) AS DOUBLE)
           AS school_coverage_pct,
         CAST(100.0 * eligible_learners / NULLIF(public_school_enrollment, 0) AS DOUBLE) AS learner_coverage_pct
  FROM metrics
), assessed AS (
  -- input problems are found before the reference, so an LGU that fails them never moves the line others are judged against.
  SELECT *,
         CASE WHEN offered_school_level_count = 0 THEN 'no active public school level'
              WHEN learners_per_teacher IS NULL THEN 'no usable positive teacher denominator'
              WHEN incomplete_enrollment_school_level_count > 0 THEN 'incomplete enrollment'
              WHEN school_coverage_pct < 90 OR learner_coverage_pct < 90 THEN 'coverage below 90%'
         END AS input_issue_reason
  FROM ratios
), type_references AS (
  SELECT lgu_type,
         CAST(SUM(eligible_learners) AS DOUBLE) / NULLIF(SUM(approved_teacher_count), 0)
           AS national_same_type_ratio,
         COUNT(*) AS reference_lgu_count
  FROM assessed
  WHERE input_issue_reason IS NULL
  GROUP BY lgu_type
), compared AS (
  SELECT a.*, n.national_same_type_ratio, COALESCE(n.reference_lgu_count, 0) AS reference_lgu_count,
         a.learners_per_teacher / NULLIF(n.national_same_type_ratio, 0) AS relative_pressure,
         a.learners_per_teacher_without_outliers / NULLIF(n.national_same_type_ratio, 0) AS relative_pressure_without_outliers
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
       'project-defined same-type pooled ratio' AS comparison_method,
       :code_revision AS code_revision
FROM classified;

COMMENT ON TABLE edu_access.`06-analytics`.ap3_teacher_pressure_candidate IS 'Unpublished AP3 build. Do not read: use ap3_teacher_pressure.';
ALTER TABLE edu_access.`06-analytics`.ap3_teacher_pressure_candidate OWNER TO `reached-hq`;

