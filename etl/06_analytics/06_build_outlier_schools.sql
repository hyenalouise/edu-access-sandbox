-- the D-057 outlier school list, saved with the run: every public school (AP2) and school level (AP3) above
-- Q3 + 3 x IQR of its school-level ratio within LGU type, SY 2023-24.
-- grain: one school, measure and education level ('ALL' for AP2, which combines levels).
-- the fences repeat the AP2 and AP3 builds exactly, and the gate checks that the counts match their outlier counts.
-- flagged schools stay in every published total; this list only names them, for the outlier check and for
-- follow-up with the Schools Division Office.

CREATE SCHEMA IF NOT EXISTS edu_access.`06-analytics`;
ALTER SCHEMA edu_access.`06-analytics` OWNER TO `reached-hq`;

CREATE OR REPLACE TABLE edu_access.`06-analytics`.lgu_priority_outlier_schools_candidate USING DELTA AS
WITH lgus AS (
  SELECT city_mun_psgc_code, lgu_type
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
), room_ratios AS (
  -- AP2: schools in the ratio (active, complete enrollment, rooms above 0), all levels combined.
  SELECT e.school_id, e.city_mun_psgc_code, l.lgu_type,
         CAST(e.complete_level_learners AS BIGINT) AS learners,
         CAST(c.instructional_classrooms_total AS BIGINT) AS denominator,
         CAST(e.complete_level_learners AS DOUBLE) / c.instructional_classrooms_total AS school_ratio
  FROM enrollment AS e
  JOIN lgus AS l USING (city_mun_psgc_code)
  JOIN edu_access.`05-gold`.fact_school_classroom_capacity AS c
    ON c.school_id = e.school_id AND c.school_year = '2023-24'
  WHERE e.is_active = 1 AND e.incomplete_levels = 0 AND c.instructional_classrooms_total > 0
), room_fences AS (
  SELECT lgu_type,
         PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY school_ratio) AS q1,
         PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY school_ratio) AS q3
  FROM room_ratios
  GROUP BY lgu_type
), active AS (
  SELECT school_id, MAX(CASE WHEN is_offered AND learner_count > 0 THEN 1 ELSE 0 END) AS is_active,
         COUNT_IF(is_offered) > 0 AND COUNT_IF(is_offered AND learner_count IS NOT NULL) = 0 AS is_blank
  FROM edu_access.`05-gold`.fact_school_enrollment
  WHERE school_year = '2023-24' AND sector = 'Public' AND psgc_match_status = 'matched'
  GROUP BY school_id
), teacher_ratios AS (
  -- AP3: school levels with a usable teacher count (above 0) and a complete learner count.
  SELECT e.school_id, e.city_mun_psgc_code, l.lgu_type, e.education_level_code,
         CAST(e.learner_count AS BIGINT) AS learners,
         CAST(t.teacher_count AS BIGINT) AS denominator,
         CAST(e.learner_count AS DOUBLE) / t.teacher_count AS school_ratio
  FROM edu_access.`05-gold`.fact_school_enrollment AS e
  JOIN active AS a ON a.school_id = e.school_id AND (a.is_active = 1 OR a.is_blank)
  JOIN lgus AS l ON l.city_mun_psgc_code = e.city_mun_psgc_code
  JOIN edu_access.`05-gold`.fact_school_teacher_capacity AS t
    ON t.school_id = e.school_id AND t.school_year = e.school_year AND t.education_level_code = e.education_level_code
  WHERE e.school_year = '2023-24' AND e.sector = 'Public' AND e.psgc_match_status = 'matched' AND e.is_offered
    AND e.learner_count IS NOT NULL AND t.teacher_count > 0
), teacher_fences AS (
  SELECT lgu_type, education_level_code,
         PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY school_ratio) AS q1,
         PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY school_ratio) AS q3
  FROM teacher_ratios
  GROUP BY lgu_type, education_level_code
)
SELECT r.school_id, r.city_mun_psgc_code, r.lgu_type, CAST('2023-24' AS STRING) AS school_year,
       'AP2' AS measure, 'ALL' AS education_level_code, r.learners, r.denominator, r.school_ratio,
       f.q1, f.q3, f.q3 + 3 * (f.q3 - f.q1) AS upper_fence,
       'learners per reported instructional room' AS ratio_label, :code_revision AS code_revision
FROM room_ratios AS r
JOIN room_fences AS f USING (lgu_type)
WHERE r.school_ratio > f.q3 + 3 * (f.q3 - f.q1)
UNION ALL
SELECT r.school_id, r.city_mun_psgc_code, r.lgu_type, CAST('2023-24' AS STRING),
       'AP3', r.education_level_code, r.learners, r.denominator, r.school_ratio,
       f.q1, f.q3, f.q3 + 3 * (f.q3 - f.q1),
       'learners per teacher at the level', :code_revision
FROM teacher_ratios AS r
JOIN teacher_fences AS f USING (lgu_type, education_level_code)
WHERE r.school_ratio > f.q3 + 3 * (f.q3 - f.q1);

COMMENT ON TABLE edu_access.`06-analytics`.lgu_priority_outlier_schools_candidate IS 'Unpublished outlier school list. Do not read: use lgu_priority_outlier_schools.';
ALTER TABLE edu_access.`06-analytics`.lgu_priority_outlier_schools_candidate OWNER TO `reached-hq`;
