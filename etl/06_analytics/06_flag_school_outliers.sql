-- suspected extreme school ratios for the outlier sensitivity check (D-065).
-- grain: one public school and measure in that measure's ratio, SY 2023-24: the classroom ratio (learners per reported
-- instructional room, AP2's denominator-usable schools) and the teacher ratio by level (learners per included
-- teaching position, AP3's teacher-usable school levels; zero-teacher annexes have no ratio and are never flagged).
-- fence: Tukey's outer fence, Q1 - 3 * IQR and Q3 + 3 * IQR (NIST/SEMATECH e-Handbook 7.1.6), from the quartiles of
-- the same ratio among comparable schools: within LGU type for the classroom ratio, within LGU type and level for the
-- teacher ratio. A group of fewer than 10 schools has no fence and flags nothing.
-- a classroom ratio is suspected only above the upper fence, because only high ratios can create the school-level
-- screen; a teacher ratio is suspected above the upper or below the lower fence, because AP3 pools every school in
-- the LGU and excluding only high schools would bias the sensitivity result toward no pressure.
-- a flag is a quality result: the school stays in every published measure. Nothing here is deleted or corrected.

CREATE SCHEMA IF NOT EXISTS edu_access.`06-analytics`;
ALTER SCHEMA edu_access.`06-analytics` OWNER TO `reached-hq`;

CREATE OR REPLACE TABLE edu_access.`06-analytics`.school_outlier_flags_candidate USING DELTA AS
WITH lgus AS (
  SELECT city_mun_psgc_code, lgu_type
  FROM edu_access.`05-gold`.dim_city_municipality
  WHERE member_type = 'regular'
), enrollment AS (
  SELECT school_id, city_mun_psgc_code,
         MAX(CASE WHEN is_offered AND learner_count > 0 THEN 1 ELSE 0 END) AS is_active,
         COUNT_IF(is_offered AND learner_count IS NULL) AS incomplete_levels,
         COUNT_IF(is_offered) > 0 AND COUNT_IF(is_offered AND learner_count IS NOT NULL) = 0 AS is_blank,
         SUM(CASE WHEN is_offered AND learner_count IS NOT NULL THEN learner_count ELSE 0 END) AS complete_level_learners
  FROM edu_access.`05-gold`.fact_school_enrollment
  WHERE school_year = '2023-24' AND sector = 'Public' AND psgc_match_status = 'matched'
  GROUP BY school_id, city_mun_psgc_code
), classroom AS (
  -- AP2's ratio population: active, complete enrollment, more than zero reported rooms
  SELECT e.school_id, e.city_mun_psgc_code, l.lgu_type, 'classroom' AS measure, 'ALL' AS education_level_code,
         CAST(e.complete_level_learners AS BIGINT) AS learners, CAST(c.instructional_classrooms_total AS BIGINT) AS denominator,
         CAST(e.complete_level_learners AS DOUBLE) / c.instructional_classrooms_total AS ratio
  FROM enrollment AS e
  JOIN lgus AS l ON l.city_mun_psgc_code = e.city_mun_psgc_code
  JOIN edu_access.`05-gold`.fact_school_classroom_capacity AS c
    ON c.school_id = e.school_id AND c.school_year = '2023-24'
  WHERE e.is_active = 1 AND e.incomplete_levels = 0 AND c.instructional_classrooms_total > 0
), teacher AS (
  -- AP3's ratio population: an offered level with a learner count and more than zero included teachers
  SELECT f.school_id, f.city_mun_psgc_code, l.lgu_type, 'teacher' AS measure, f.education_level_code,
         CAST(f.learner_count AS BIGINT) AS learners, CAST(t.teacher_count AS BIGINT) AS denominator,
         CAST(f.learner_count AS DOUBLE) / t.teacher_count AS ratio
  FROM edu_access.`05-gold`.fact_school_enrollment AS f
  JOIN enrollment AS e ON e.school_id = f.school_id AND (e.is_active = 1 OR e.is_blank)
  JOIN lgus AS l ON l.city_mun_psgc_code = f.city_mun_psgc_code
  JOIN edu_access.`05-gold`.fact_school_teacher_capacity AS t
    ON t.school_id = f.school_id AND t.school_year = f.school_year AND t.education_level_code = f.education_level_code
  WHERE f.school_year = '2023-24' AND f.sector = 'Public' AND f.psgc_match_status = 'matched' AND f.is_offered
    AND f.learner_count IS NOT NULL AND t.teacher_count > 0
), ratios AS (
  SELECT * FROM classroom
  UNION ALL
  SELECT * FROM teacher
), quartiles AS (
  SELECT measure, education_level_code, lgu_type, COUNT(*) AS fence_group_size,
         percentile_cont(0.25) WITHIN GROUP (ORDER BY ratio) AS q1,
         percentile_cont(0.75) WITHIN GROUP (ORDER BY ratio) AS q3
  FROM ratios
  GROUP BY measure, education_level_code, lgu_type
), fences AS (
  SELECT measure, education_level_code, lgu_type, fence_group_size, q1, q3, q3 - q1 AS iqr,
         CASE WHEN fence_group_size >= 10 THEN q1 - 3 * (q3 - q1) END AS lower_outer_fence,
         CASE WHEN fence_group_size >= 10 THEN q3 + 3 * (q3 - q1) END AS upper_outer_fence
  FROM quartiles
)
SELECT r.school_id, r.city_mun_psgc_code, r.lgu_type, CAST('2023-24' AS STRING) AS school_year,
       r.measure, r.education_level_code, r.learners, r.denominator, r.ratio,
       f.fence_group_size, f.q1, f.q3, f.iqr, f.lower_outer_fence, f.upper_outer_fence,
       COALESCE(r.ratio > f.upper_outer_fence, FALSE) AS is_above_upper_fence,
       COALESCE(r.ratio < f.lower_outer_fence, FALSE) AS is_below_lower_fence,
       CASE WHEN r.measure = 'classroom' THEN COALESCE(r.ratio > f.upper_outer_fence, FALSE)
            ELSE COALESCE(r.ratio > f.upper_outer_fence OR r.ratio < f.lower_outer_fence, FALSE) END AS is_suspected_outlier,
       :code_revision AS code_revision
FROM ratios AS r
JOIN fences AS f
  ON f.measure = r.measure AND f.education_level_code = r.education_level_code AND f.lgu_type = r.lgu_type;

COMMENT ON TABLE edu_access.`06-analytics`.school_outlier_flags_candidate IS 'Unpublished outlier-flag build. Do not read: use school_outlier_flags.';
ALTER TABLE edu_access.`06-analytics`.school_outlier_flags_candidate OWNER TO `reached-hq`;
