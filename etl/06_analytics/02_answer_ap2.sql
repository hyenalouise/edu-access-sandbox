-- ap2 classroom pressure under the BP and AP metrics and the priority rule D-057.
-- grain: one regular city or municipality for SY 2023-24.
-- measure: enrollment in denominator-usable schools / reported instructional rooms in the same schools (D-047).
-- coverage gate (D-057): learner coverage, the share of learners in schools with a usable room count, at least 90%.
-- school coverage is shown beside it, with incomplete and blank-enrollment schools in its denominator.
-- outlier schools (above Q3 + 3 x IQR within LGU type) are counted and stay in every total, they never change a result.
-- no 45:1 value is published: RA 7880's statutory line does not apply to this NSBI room count, which includes rooms
-- the law excludes (D-045), so a column beside the ratio would invite a reference line.
-- percentiles: PERCENT_RANK within LGU type and nationally, among LGUs that pass the gate.

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
         COUNT_IF(is_offered) > 0 AND COUNT_IF(is_offered AND learner_count IS NOT NULL) = 0 AS is_blank,
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
  SELECT s.school_id, s.city_mun_psgc_code, l.lgu_type,
         CAST(s.total_learners AS DOUBLE) / s.instructional_classrooms_total AS school_ratio
  FROM schools AS s
  JOIN lgus AS l USING (city_mun_psgc_code)
  WHERE s.in_ratio
), fences AS (
  SELECT lgu_type,
         PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY school_ratio) AS q1,
         PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY school_ratio) AS q3
  FROM school_ratios
  GROUP BY lgu_type
), outliers AS (
  SELECT r.city_mun_psgc_code, COUNT_IF(r.school_ratio > f.q3 + 3 * (f.q3 - f.q1)) AS outlier_school_count
  FROM school_ratios AS r
  JOIN fences AS f USING (lgu_type)
  GROUP BY r.city_mun_psgc_code
), metrics AS (
  SELECT l.*, CAST('2023-24' AS STRING) AS school_year,
         COALESCE(COUNT_IF(s.is_active = 1), 0) AS active_public_school_count,
         COALESCE(COUNT_IF(s.is_active = 1 AND s.instructional_classrooms_total > 0), 0) AS usable_room_school_count,
         COALESCE(COUNT_IF(s.in_ratio), 0) AS ratio_school_count,
         COALESCE(COUNT_IF(s.is_active = 1 AND NOT s.enrollment_complete), 0) AS incomplete_enrollment_school_count,
         COALESCE(COUNT_IF(s.is_blank), 0) AS blank_enrollment_school_count,
         COALESCE(COUNT_IF(s.is_active = 1 AND s.instructional_classrooms_total IS NULL), 0) AS missing_room_school_count,
         COALESCE(COUNT_IF(s.is_active = 1 AND s.instructional_classrooms_total = 0), 0) AS zero_room_school_count,
         CAST(COALESCE(SUM(CASE WHEN s.is_active = 1 AND s.enrollment_complete THEN s.total_learners ELSE 0 END), 0) AS BIGINT)
           AS public_school_enrollment,
         CAST(COALESCE(SUM(CASE WHEN s.in_ratio THEN s.total_learners ELSE 0 END), 0) AS BIGINT) AS eligible_learners,
         CAST(COALESCE(SUM(CASE WHEN s.in_ratio THEN s.instructional_classrooms_total ELSE 0 END), 0) AS BIGINT)
           AS reported_instructional_classrooms
  FROM lgus AS l
  LEFT JOIN schools AS s USING (city_mun_psgc_code)
  GROUP BY l.city_mun_psgc_code, l.city_mun_name, l.lgu_type, l.province_psgc_code, l.province_name,
           l.region_psgc_code, l.region_name
), ratios AS (
  SELECT m.*,
         COALESCE(o.outlier_school_count, 0) AS outlier_school_count,
         COALESCE(o.outlier_school_count, 0) > 0 AS outlier_flag,
         CAST(m.eligible_learners AS DOUBLE) / NULLIF(m.reported_instructional_classrooms, 0) AS learners_per_classroom,
         CAST(100.0 * m.ratio_school_count
           / NULLIF(m.active_public_school_count + m.blank_enrollment_school_count, 0) AS DOUBLE) AS school_coverage_pct,
         CAST(100.0 * m.eligible_learners / NULLIF(m.public_school_enrollment, 0) AS DOUBLE) AS learner_coverage_pct
  FROM metrics AS m
  LEFT JOIN outliers AS o USING (city_mun_psgc_code)
), gated AS (
  SELECT *,
         CASE WHEN active_public_school_count = 0 THEN 'no active public school'
              WHEN learners_per_classroom IS NULL THEN 'no usable classroom denominator'
              WHEN learner_coverage_pct < 90 THEN 'learner coverage below 90%'
         END AS not_assessed_reason
  FROM ratios
), ranked AS (
  SELECT city_mun_psgc_code,
         PERCENT_RANK() OVER (PARTITION BY lgu_type ORDER BY learners_per_classroom) AS within_type_percentile,
         PERCENT_RANK() OVER (ORDER BY learners_per_classroom) AS national_percentile
  FROM gated
  WHERE not_assessed_reason IS NULL
)
SELECT g.*,
       g.not_assessed_reason IS NULL AS is_assessed,
       r.within_type_percentile,
       r.national_percentile,
       COALESCE(r.within_type_percentile >= 0.9, FALSE) AS is_high,
       COALESCE(r.national_percentile >= 0.9, FALSE) AS is_high_nationally,
       'learners per reported instructional room, source DepEd School Facilities (NSBI), not the DepEd classroom-learner ratio' AS measure_label,
       :code_revision AS code_revision
FROM gated AS g
LEFT JOIN ranked AS r USING (city_mun_psgc_code);

COMMENT ON TABLE edu_access.`06-analytics`.ap2_classroom_pressure_candidate IS 'Unpublished AP2 build. Do not read: use ap2_classroom_pressure.';
ALTER TABLE edu_access.`06-analytics`.ap2_classroom_pressure_candidate OWNER TO `reached-hq`;
