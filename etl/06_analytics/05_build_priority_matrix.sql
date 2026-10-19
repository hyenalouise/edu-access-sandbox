-- final dashboard-ready LGU priority matrix under the methodology that supersedes D-057.
-- grain: one regular city or municipality. AP4 lifts a priority only when its trend is Complete.

CREATE SCHEMA IF NOT EXISTS edu_access.`06-analytics`;
ALTER SCHEMA edu_access.`06-analytics` OWNER TO `reached-hq`;

CREATE OR REPLACE TABLE edu_access.`06-analytics`.lgu_priority_matrix_candidate USING DELTA AS
WITH joined AS (
  SELECT
    l.city_mun_psgc_code, l.city_mun_name, l.lgu_type, l.province_psgc_code, l.province_name,
    l.region_psgc_code, l.region_name,
    a.school_year AS ap1_school_year,
    a.population_reference_year AS ap1_population_reference_year,
    a.school_age_population_per_public_school AS ap1_ratio,
    a.national_same_type_ratio AS ap1_national_same_type_ratio,
    a.relative_pressure AS ap1_relative_pressure,
    a.coverage_pct AS ap1_coverage_pct,
    a.outlier_flag AS ap1_outlier_flag,
    a.quality_issue_reason AS ap1_quality_issue_reason,
    a.classification AS ap1_classification,
    b.school_year AS ap2_school_year,
    b.learners_per_classroom AS ap2_ratio,
    b.national_same_type_ratio AS ap2_national_same_type_ratio,
    b.relative_pressure AS ap2_relative_pressure,
    b.school_coverage_pct AS ap2_school_coverage_pct,
    b.learner_coverage_pct AS ap2_learner_coverage_pct,
    b.outlier_flag AS ap2_outlier_flag,
    b.outlier_school_count AS ap2_outlier_school_count,
    b.relative_pressure_without_outliers AS ap2_relative_pressure_without_outliers,
    b.quality_issue_reason AS ap2_quality_issue_reason,
    b.classification AS ap2_classification,
    c.school_year AS ap3_school_year,
    c.learners_per_teacher AS ap3_ratio,
    c.national_same_type_ratio AS ap3_national_same_type_ratio,
    c.relative_pressure AS ap3_relative_pressure,
    c.school_coverage_pct AS ap3_school_coverage_pct,
    c.learner_coverage_pct AS ap3_learner_coverage_pct,
    c.outlier_flag AS ap3_outlier_flag,
    c.outlier_school_level_count AS ap3_outlier_school_level_count,
    c.relative_pressure_without_outliers AS ap3_relative_pressure_without_outliers,
    c.quality_issue_reason AS ap3_quality_issue_reason,
    c.classification AS ap3_classification,
    d.enrollment_2020_21, d.enrollment_2021_22, d.enrollment_2022_23,
    d.enrollment_2023_24, d.enrollment_2024_25, d.enrollment_2025_26,
    d.absolute_change AS enrollment_absolute_change,
    d.pct_change AS enrollment_pct_change,
    d.trend_direction AS enrollment_trend,
    d.trend_status AS enrollment_trend_status
  FROM edu_access.`05-gold`.dim_city_municipality AS l
  LEFT JOIN edu_access.`06-analytics`.ap1_school_provision AS a USING (city_mun_psgc_code)
  LEFT JOIN edu_access.`06-analytics`.ap2_classroom_pressure AS b USING (city_mun_psgc_code)
  LEFT JOIN edu_access.`06-analytics`.ap3_teacher_pressure AS c USING (city_mun_psgc_code)
  LEFT JOIN edu_access.`06-analytics`.ap4_enrollment_trend AS d USING (city_mun_psgc_code)
  WHERE l.member_type = 'regular'
), flags AS (
  SELECT *,
         COALESCE(ap1_classification = 'Above Reference', FALSE) AS ap1_pressure_flag,
         COALESCE(ap2_classification = 'Above Reference', FALSE) AS ap2_pressure_flag,
         COALESCE(ap3_classification = 'Above Reference', FALSE) AS ap3_pressure_flag,
         COALESCE(enrollment_trend = 'Growing' AND enrollment_trend_status = 'Complete', FALSE) AS growing_enrollment_flag
  FROM joined
), counted AS (
  SELECT *,
         CAST(ap1_pressure_flag AS INT) + CAST(ap2_pressure_flag AS INT) + CAST(ap3_pressure_flag AS INT)
           AS current_pressure_count
  FROM flags
)
SELECT *,
       CASE
         WHEN ap1_classification IS NULL OR ap2_classification IS NULL OR ap3_classification IS NULL
           OR ap1_classification = 'Data Review' OR ap2_classification = 'Data Review'
           OR ap3_classification = 'Data Review' THEN 'Data Review'
         WHEN current_pressure_count >= 2 AND growing_enrollment_flag THEN 'Priority 1'
         WHEN current_pressure_count >= 2 THEN 'Priority 2'
         WHEN current_pressure_count = 1 AND growing_enrollment_flag THEN 'Priority 3'
         WHEN current_pressure_count = 1 THEN 'Monitor'
         WHEN current_pressure_count = 0 AND growing_enrollment_flag THEN 'Monitor'
         ELSE 'Lower Priority'
       END AS priority,
       :code_revision AS code_revision
FROM counted;

COMMENT ON TABLE edu_access.`06-analytics`.lgu_priority_matrix_candidate IS 'Unpublished priority matrix. Do not read: use lgu_priority_matrix.';
ALTER TABLE edu_access.`06-analytics`.lgu_priority_matrix_candidate OWNER TO `reached-hq`;

