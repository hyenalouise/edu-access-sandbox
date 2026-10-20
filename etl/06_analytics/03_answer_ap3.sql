-- ap3 descriptive teacher-pressure screening.
-- grain: one regular city or municipality for SY 2023-24, with ES, JHS and SHS side by side.
-- measure, by level: complete enrollment for the level at denominator-usable schools (plus annexes that report 0
-- teachers) / included teaching positions for the same level (D-047).
-- coverage gate, by level: learner coverage at least 90%.
-- references are context only: ES 35 is historical World Bank study context based on older DepEd service standards;
-- JHS 36 and SHS 80/3 are derived unit conversions from current class-size and teacher-to-class planning parameters.
-- none is a current official pupil-teacher cutoff, teacher requirement, shortage, staffing entitlement, or rank.

CREATE SCHEMA IF NOT EXISTS edu_access.`06-analytics`;
ALTER SCHEMA edu_access.`06-analytics` OWNER TO `reached-hq`;

CREATE OR REPLACE TABLE edu_access.`06-analytics`.ap3_teacher_pressure_candidate USING DELTA AS
WITH lgus AS (
  SELECT city_mun_psgc_code, city_mun_name, lgu_type, province_psgc_code, province_name,
         region_psgc_code, region_name
  FROM edu_access.`05-gold`.dim_city_municipality
  WHERE member_type = 'regular'
), levels AS (
  SELECT * FROM VALUES ('ES', 1), ('JHS', 2), ('SHS', 3) AS v(education_level_code, level_order)
), active AS (
  -- a school that offers a level but has every offered count blank is not active, but it is missing data, not a
  -- closed school: its blank levels stay in so the level counts as incomplete and is never read as not offered.
  SELECT school_id, MAX(CASE WHEN is_offered AND learner_count > 0 THEN 1 ELSE 0 END) AS is_active,
         COUNT_IF(is_offered) > 0 AND COUNT_IF(is_offered AND learner_count IS NOT NULL) = 0 AS is_blank
  FROM edu_access.`05-gold`.fact_school_enrollment
  WHERE school_year = '2023-24' AND sector = 'Public' AND psgc_match_status = 'matched'
  GROUP BY school_id
), school_levels AS (
  SELECT e.school_id, e.city_mun_psgc_code, l.lgu_type, e.education_level_code, e.learner_count, t.teacher_count,
         COALESCE(t.teacher_count > 0, FALSE) AND e.learner_count IS NOT NULL AS teacher_usable,
         COALESCE(e.annex_status = 'Annex/Extension School' AND t.teacher_count = 0, FALSE)
           AND e.learner_count IS NOT NULL AS zero_teacher_annex
  FROM edu_access.`05-gold`.fact_school_enrollment AS e
  JOIN active AS a ON a.school_id = e.school_id AND (a.is_active = 1 OR a.is_blank)
  JOIN lgus AS l ON l.city_mun_psgc_code = e.city_mun_psgc_code
  LEFT JOIN edu_access.`05-gold`.fact_school_teacher_capacity AS t
    ON t.school_id = e.school_id AND t.school_year = e.school_year AND t.education_level_code = e.education_level_code
  WHERE e.school_year = '2023-24' AND e.sector = 'Public' AND e.psgc_match_status = 'matched' AND e.is_offered
), level_metrics AS (
  SELECT l.city_mun_psgc_code, l.lgu_type, v.education_level_code, v.level_order,
         COUNT(s.school_id) AS offered_school_count,
         COALESCE(COUNT_IF(s.school_id IS NOT NULL AND s.learner_count IS NULL), 0) AS incomplete_school_count,
         COALESCE(COUNT_IF(s.teacher_usable), 0) AS usable_teacher_school_count,
         COALESCE(COUNT_IF(s.zero_teacher_annex), 0) AS zero_teacher_annex_school_count,
         CAST(COALESCE(SUM(CASE WHEN s.zero_teacher_annex THEN s.learner_count END), 0) AS BIGINT) AS zero_teacher_annex_learners,
         CAST(COALESCE(SUM(s.learner_count), 0) AS BIGINT) AS public_school_enrollment,
         CAST(COALESCE(SUM(CASE WHEN s.teacher_usable OR s.zero_teacher_annex THEN s.learner_count END), 0) AS BIGINT)
           AS eligible_learners,
         CAST(COALESCE(SUM(CASE WHEN s.teacher_usable THEN s.teacher_count END), 0) AS BIGINT) AS teacher_count
  FROM lgus AS l
  CROSS JOIN levels AS v
  LEFT JOIN school_levels AS s
    ON s.city_mun_psgc_code = l.city_mun_psgc_code AND s.education_level_code = v.education_level_code
  GROUP BY l.city_mun_psgc_code, l.lgu_type, v.education_level_code, v.level_order
), level_ratios AS (
  SELECT *,
         offered_school_count > 0 AS is_offered,
         CAST(eligible_learners AS DOUBLE) / NULLIF(teacher_count, 0) AS learners_per_teacher,
         CAST(100.0 * usable_teacher_school_count / NULLIF(offered_school_count, 0) AS DOUBLE) AS school_coverage_pct,
         CAST(100.0 * eligible_learners / NULLIF(public_school_enrollment, 0) AS DOUBLE) AS learner_coverage_pct
  FROM level_metrics
), level_gated AS (
  SELECT *,
         COALESCE(is_offered AND learners_per_teacher IS NOT NULL AND learner_coverage_pct >= 90, FALSE) AS passes_gate
  FROM level_ratios
), level_all AS (
  SELECT * FROM level_gated
), lgu_levels AS (
  SELECT l.city_mun_psgc_code, l.city_mun_name, l.lgu_type, l.province_psgc_code, l.province_name,
         l.region_psgc_code, l.region_name, CAST('2023-24' AS STRING) AS school_year,
         COALESCE(COUNT_IF(a.is_offered), 0) AS offered_level_count,
         COALESCE(COUNT_IF(a.is_offered AND a.passes_gate), 0) AS passing_level_count,
         MAX(CASE WHEN a.education_level_code = 'ES' THEN a.offered_school_count END) AS es_offered_school_count,
         MAX(CASE WHEN a.education_level_code = 'ES' THEN a.incomplete_school_count END) AS es_incomplete_school_count,
         MAX(CASE WHEN a.education_level_code = 'ES' THEN a.usable_teacher_school_count END) AS es_usable_teacher_school_count,
         MAX(CASE WHEN a.education_level_code = 'ES' THEN a.zero_teacher_annex_school_count END) AS es_zero_teacher_annex_school_count,
         MAX(CASE WHEN a.education_level_code = 'ES' THEN a.zero_teacher_annex_learners END) AS es_zero_teacher_annex_learners,
         MAX(CASE WHEN a.education_level_code = 'ES' THEN a.public_school_enrollment END) AS es_public_school_enrollment,
         MAX(CASE WHEN a.education_level_code = 'ES' THEN a.eligible_learners END) AS es_eligible_learners,
         MAX(CASE WHEN a.education_level_code = 'ES' THEN a.teacher_count END) AS es_teacher_count,
         MAX(CASE WHEN a.education_level_code = 'ES' THEN a.learners_per_teacher END) AS es_learners_per_teacher,
         MAX(CASE WHEN a.education_level_code = 'ES' THEN a.school_coverage_pct END) AS es_school_coverage_pct,
         MAX(CASE WHEN a.education_level_code = 'ES' THEN a.learner_coverage_pct END) AS es_learner_coverage_pct,
         MAX(CASE WHEN a.education_level_code = 'ES' THEN a.passes_gate END) AS es_passes_gate,
         MAX(CASE WHEN a.education_level_code = 'JHS' THEN a.offered_school_count END) AS jhs_offered_school_count,
         MAX(CASE WHEN a.education_level_code = 'JHS' THEN a.incomplete_school_count END) AS jhs_incomplete_school_count,
         MAX(CASE WHEN a.education_level_code = 'JHS' THEN a.usable_teacher_school_count END) AS jhs_usable_teacher_school_count,
         MAX(CASE WHEN a.education_level_code = 'JHS' THEN a.zero_teacher_annex_school_count END) AS jhs_zero_teacher_annex_school_count,
         MAX(CASE WHEN a.education_level_code = 'JHS' THEN a.zero_teacher_annex_learners END) AS jhs_zero_teacher_annex_learners,
         MAX(CASE WHEN a.education_level_code = 'JHS' THEN a.public_school_enrollment END) AS jhs_public_school_enrollment,
         MAX(CASE WHEN a.education_level_code = 'JHS' THEN a.eligible_learners END) AS jhs_eligible_learners,
         MAX(CASE WHEN a.education_level_code = 'JHS' THEN a.teacher_count END) AS jhs_teacher_count,
         MAX(CASE WHEN a.education_level_code = 'JHS' THEN a.learners_per_teacher END) AS jhs_learners_per_teacher,
         MAX(CASE WHEN a.education_level_code = 'JHS' THEN a.school_coverage_pct END) AS jhs_school_coverage_pct,
         MAX(CASE WHEN a.education_level_code = 'JHS' THEN a.learner_coverage_pct END) AS jhs_learner_coverage_pct,
         MAX(CASE WHEN a.education_level_code = 'JHS' THEN a.passes_gate END) AS jhs_passes_gate,
         MAX(CASE WHEN a.education_level_code = 'SHS' THEN a.offered_school_count END) AS shs_offered_school_count,
         MAX(CASE WHEN a.education_level_code = 'SHS' THEN a.incomplete_school_count END) AS shs_incomplete_school_count,
         MAX(CASE WHEN a.education_level_code = 'SHS' THEN a.usable_teacher_school_count END) AS shs_usable_teacher_school_count,
         MAX(CASE WHEN a.education_level_code = 'SHS' THEN a.zero_teacher_annex_school_count END) AS shs_zero_teacher_annex_school_count,
         MAX(CASE WHEN a.education_level_code = 'SHS' THEN a.zero_teacher_annex_learners END) AS shs_zero_teacher_annex_learners,
         MAX(CASE WHEN a.education_level_code = 'SHS' THEN a.public_school_enrollment END) AS shs_public_school_enrollment,
         MAX(CASE WHEN a.education_level_code = 'SHS' THEN a.eligible_learners END) AS shs_eligible_learners,
         MAX(CASE WHEN a.education_level_code = 'SHS' THEN a.teacher_count END) AS shs_teacher_count,
         MAX(CASE WHEN a.education_level_code = 'SHS' THEN a.learners_per_teacher END) AS shs_learners_per_teacher,
         MAX(CASE WHEN a.education_level_code = 'SHS' THEN a.school_coverage_pct END) AS shs_school_coverage_pct,
         MAX(CASE WHEN a.education_level_code = 'SHS' THEN a.learner_coverage_pct END) AS shs_learner_coverage_pct,
         MAX(CASE WHEN a.education_level_code = 'SHS' THEN a.passes_gate END) AS shs_passes_gate
  FROM lgus AS l
  JOIN level_all AS a ON a.city_mun_psgc_code = l.city_mun_psgc_code
  GROUP BY l.city_mun_psgc_code, l.city_mun_name, l.lgu_type, l.province_psgc_code, l.province_name,
           l.region_psgc_code, l.region_name
)
SELECT c.*,
       c.offered_level_count > 0 AND c.passing_level_count = c.offered_level_count AS is_assessed,
       CASE WHEN c.offered_level_count > 0 AND c.passing_level_count = c.offered_level_count THEN NULL
            WHEN c.offered_level_count = 0 THEN 'no active public school level'
            ELSE 'an offered level is below 90% learner coverage' END AS not_assessed_reason,
       CAST(35.0 AS DOUBLE) AS es_benchmark_max_learners_per_teacher,
       CASE WHEN c.es_offered_school_count = 0 THEN 'not applicable'
            WHEN NOT c.es_passes_gate THEN 'not assessed'
            WHEN c.es_learners_per_teacher > 35 THEN 'above historical study reference'
            ELSE 'at or below historical study reference' END AS es_benchmark_status,
       CAST(36.0 AS DOUBLE) AS jhs_benchmark_max_learners_per_teacher,
       CASE WHEN c.jhs_offered_school_count = 0 THEN 'not applicable'
            WHEN NOT c.jhs_passes_gate THEN 'not assessed'
            WHEN c.jhs_learners_per_teacher > 36 THEN 'above derived deployment comparison'
            ELSE 'at or below derived deployment comparison' END AS jhs_benchmark_status,
       CAST(80.0 / 3 AS DOUBLE) AS shs_benchmark_max_learners_per_teacher,
       CASE WHEN c.shs_offered_school_count = 0 THEN 'not applicable'
            WHEN NOT c.shs_passes_gate THEN 'not assessed'
            WHEN c.shs_learners_per_teacher > 80.0 / 3 THEN 'above derived deployment comparison'
            ELSE 'at or below derived deployment comparison' END AS shs_benchmark_status,
       CASE WHEN c.es_offered_school_count = 0 AND c.jhs_offered_school_count = 0
              AND c.shs_offered_school_count = 0 THEN 'not assessed'
            WHEN (c.es_passes_gate AND c.es_learners_per_teacher > 35)
              OR (c.jhs_passes_gate AND c.jhs_learners_per_teacher > 36)
              OR (c.shs_passes_gate AND c.shs_learners_per_teacher > 80.0 / 3) THEN 'pressure signal identified'
            WHEN (c.es_offered_school_count > 0 AND NOT c.es_passes_gate)
              OR (c.jhs_offered_school_count > 0 AND NOT c.jhs_passes_gate)
              OR (c.shs_offered_school_count > 0 AND NOT c.shs_passes_gate) THEN 'not fully assessed'
            ELSE 'no pressure signal identified' END AS benchmark_status,
       'descriptive learners per reported teaching personnel, references do not estimate teacher shortage' AS measure_label,
       :code_revision AS code_revision
FROM lgu_levels AS c;

COMMENT ON TABLE edu_access.`06-analytics`.ap3_teacher_pressure_candidate IS 'Unpublished AP3 build. Do not read: use ap3_teacher_pressure.';
ALTER TABLE edu_access.`06-analytics`.ap3_teacher_pressure_candidate OWNER TO `reached-hq`;
