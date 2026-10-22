-- outlier sensitivity of the D-061 planning priority (D-065).
-- grain: one regular city or municipality, SY 2023-24.
-- scenario A is the published result in lgu_priority_matrix, with every otherwise valid school. It stays primary.
-- scenario B recalculates the same AP2 and AP3 measures without the schools school_outlier_flags marks as suspected
-- extreme for that ratio, taking each excluded school out of both the numerator and the denominator. Learner coverage
-- keeps every enrolled learner in its denominator, so excluding schools can lower coverage below the 90% gate. Growth
-- (AP4) is not a school ratio and is the same in both scenarios. The D-061 rule and ordering are then applied again.
-- the status names what changes, most serious first: Priority-sensitive (the category), Classification-sensitive (a
-- pressure flag), Coverage-sensitive (a coverage gate no longer passes), Magnitude-sensitive (affected learners change
-- by more than 10%), Stable (nothing that matters changes), or No suspected outliers. The ranking position is not a
-- status, because one LGU changing moves every LGU below it.
-- scenario B also publishes the recalculated AP2 and AP3 figures (pooled ratios, counts, coverage and gates), so the
-- planner dashboard can show every measure without the flagged schools when a user chooses to exclude them.

CREATE SCHEMA IF NOT EXISTS edu_access.`06-analytics`;
ALTER SCHEMA edu_access.`06-analytics` OWNER TO `reached-hq`;

CREATE OR REPLACE TABLE edu_access.`06-analytics`.lgu_priority_sensitivity_candidate USING DELTA AS
WITH flags AS (
  SELECT * FROM edu_access.`06-analytics`.school_outlier_flags
), outlier_schools AS (
  -- learners in the flagged ratios, each school once: its total for a classroom flag, else its flagged levels
  SELECT city_mun_psgc_code, school_id,
         COALESCE(MAX(CASE WHEN measure = 'classroom' AND is_suspected_outlier THEN learners END),
                  SUM(CASE WHEN measure = 'teacher' AND is_suspected_outlier THEN learners END)) AS learners
  FROM flags
  GROUP BY city_mun_psgc_code, school_id
  HAVING COUNT_IF(is_suspected_outlier) > 0
), outlier_counts AS (
  SELECT f.city_mun_psgc_code,
         COUNT(DISTINCT CASE WHEN f.is_suspected_outlier THEN f.school_id END) AS outlier_school_count,
         COUNT_IF(f.is_suspected_outlier AND f.measure = 'classroom') AS classroom_outlier_school_count,
         COUNT_IF(f.is_suspected_outlier AND f.measure = 'teacher') AS teacher_outlier_level_count,
         MAX(o.learner_total) AS outlier_learner_count
  FROM flags AS f
  LEFT JOIN (SELECT city_mun_psgc_code, SUM(learners) AS learner_total FROM outlier_schools GROUP BY city_mun_psgc_code) AS o
    USING (city_mun_psgc_code)
  GROUP BY f.city_mun_psgc_code
), classroom_b AS (
  SELECT city_mun_psgc_code,
         COUNT_IF(NOT is_suspected_outlier) AS ratio_school_count,
         SUM(CASE WHEN NOT is_suspected_outlier THEN learners ELSE 0 END) AS eligible_learners,
         SUM(CASE WHEN NOT is_suspected_outlier THEN denominator ELSE 0 END) AS reported_rooms,
         COUNT_IF(NOT is_suspected_outlier AND ratio >= 50) AS congested_school_count,
         SUM(CASE WHEN NOT is_suspected_outlier AND ratio >= 50 THEN learners ELSE 0 END) AS learners_in_congested_schools
  FROM flags WHERE measure = 'classroom'
  GROUP BY city_mun_psgc_code
), ap2_b AS (
  SELECT a.city_mun_psgc_code,
         CAST(100.0 * COALESCE(c.eligible_learners, 0) / NULLIF(a.public_school_enrollment, 0) AS DOUBLE) AS learner_coverage_pct,
         COALESCE(a.active_public_school_count > 0 AND COALESCE(c.eligible_learners, 0) > 0
                  AND 100.0 * COALESCE(c.eligible_learners, 0) / NULLIF(a.public_school_enrollment, 0) >= 90, FALSE) AS assessed,
         COALESCE(c.ratio_school_count, 0) AS ratio_school_count,
         CAST(COALESCE(c.eligible_learners, 0) AS BIGINT) AS eligible_learners,
         CAST(COALESCE(c.reported_rooms, 0) AS BIGINT) AS reported_rooms,
         CAST(c.eligible_learners AS DOUBLE) / NULLIF(c.reported_rooms, 0) AS learners_per_reported_room,
         COALESCE(c.congested_school_count, 0) AS congested_school_count,
         CAST(COALESCE(c.learners_in_congested_schools, 0) AS BIGINT) AS affected_learners,
         CAST(100.0 * COALESCE(c.learners_in_congested_schools, 0) / NULLIF(a.public_school_enrollment, 0) AS DOUBLE)
           AS affected_learner_share_pct
  FROM edu_access.`06-analytics`.ap2_classroom_pressure AS a
  LEFT JOIN classroom_b AS c USING (city_mun_psgc_code)
), teacher_b AS (
  SELECT city_mun_psgc_code, education_level_code,
         SUM(CASE WHEN NOT is_suspected_outlier THEN learners ELSE 0 END) AS usable_learners,
         SUM(CASE WHEN NOT is_suspected_outlier THEN denominator ELSE 0 END) AS teacher_count
  FROM flags WHERE measure = 'teacher'
  GROUP BY city_mun_psgc_code, education_level_code
), levels AS (
  -- AP3's published level figures; zero-teacher annexes keep their learners in both scenarios
  SELECT city_mun_psgc_code, 'ES' AS education_level_code, es_offered_school_count AS offered_school_count,
         es_public_school_enrollment AS public_school_enrollment, es_zero_teacher_annex_learners AS zero_teacher_annex_learners,
         es_learner_coverage_pct AS learner_coverage_pct, es_benchmark_max_learners_per_teacher AS reference
  FROM edu_access.`06-analytics`.ap3_teacher_pressure
  UNION ALL SELECT city_mun_psgc_code, 'JHS', jhs_offered_school_count, jhs_public_school_enrollment,
         jhs_zero_teacher_annex_learners, jhs_learner_coverage_pct, jhs_benchmark_max_learners_per_teacher
  FROM edu_access.`06-analytics`.ap3_teacher_pressure
  UNION ALL SELECT city_mun_psgc_code, 'SHS', shs_offered_school_count, shs_public_school_enrollment,
         shs_zero_teacher_annex_learners, shs_learner_coverage_pct, shs_benchmark_max_learners_per_teacher
  FROM edu_access.`06-analytics`.ap3_teacher_pressure
), levels_b AS (
  SELECT l.*,
         COALESCE(t.usable_learners, 0) + COALESCE(l.zero_teacher_annex_learners, 0) AS eligible_learners,
         COALESCE(t.teacher_count, 0) AS teacher_count,
         CAST(COALESCE(t.usable_learners, 0) + COALESCE(l.zero_teacher_annex_learners, 0) AS DOUBLE)
           / NULLIF(COALESCE(t.teacher_count, 0), 0) AS learners_per_teacher,
         CAST(100.0 * (COALESCE(t.usable_learners, 0) + COALESCE(l.zero_teacher_annex_learners, 0))
           / NULLIF(l.public_school_enrollment, 0) AS DOUBLE) AS learner_coverage_pct_b
  FROM levels AS l
  LEFT JOIN teacher_b AS t USING (city_mun_psgc_code, education_level_code)
), levels_gated AS (
  SELECT *,
         COALESCE(offered_school_count > 0 AND learners_per_teacher IS NOT NULL AND learner_coverage_pct_b >= 90, FALSE)
           AS passes_gate
  FROM levels_b
), ap3_b AS (
  SELECT city_mun_psgc_code,
         COUNT_IF(offered_school_count > 0) > 0
           AND COUNT_IF(offered_school_count > 0 AND NOT passes_gate) = 0 AS assessed,
         COUNT_IF(passes_gate AND learners_per_teacher > reference) AS pressured_level_count,
         CAST(COALESCE(SUM(CASE WHEN passes_gate AND learners_per_teacher > reference THEN eligible_learners END), 0) AS BIGINT)
           AS affected_learners,
         CAST(MAX(CASE WHEN education_level_code = 'ES' THEN eligible_learners END) AS BIGINT) AS es_eligible_learners,
         CAST(MAX(CASE WHEN education_level_code = 'ES' THEN teacher_count END) AS BIGINT) AS es_teacher_count,
         MAX(CASE WHEN education_level_code = 'ES' THEN learners_per_teacher END) AS es_learners_per_teacher,
         MAX(CASE WHEN education_level_code = 'ES' THEN learner_coverage_pct_b END) AS es_learner_coverage_pct,
         COALESCE(MAX(CASE WHEN education_level_code = 'ES' THEN passes_gate END), FALSE) AS es_passes_gate,
         CAST(MAX(CASE WHEN education_level_code = 'JHS' THEN eligible_learners END) AS BIGINT) AS jhs_eligible_learners,
         CAST(MAX(CASE WHEN education_level_code = 'JHS' THEN teacher_count END) AS BIGINT) AS jhs_teacher_count,
         MAX(CASE WHEN education_level_code = 'JHS' THEN learners_per_teacher END) AS jhs_learners_per_teacher,
         MAX(CASE WHEN education_level_code = 'JHS' THEN learner_coverage_pct_b END) AS jhs_learner_coverage_pct,
         COALESCE(MAX(CASE WHEN education_level_code = 'JHS' THEN passes_gate END), FALSE) AS jhs_passes_gate,
         CAST(MAX(CASE WHEN education_level_code = 'SHS' THEN eligible_learners END) AS BIGINT) AS shs_eligible_learners,
         CAST(MAX(CASE WHEN education_level_code = 'SHS' THEN teacher_count END) AS BIGINT) AS shs_teacher_count,
         MAX(CASE WHEN education_level_code = 'SHS' THEN learners_per_teacher END) AS shs_learners_per_teacher,
         MAX(CASE WHEN education_level_code = 'SHS' THEN learner_coverage_pct_b END) AS shs_learner_coverage_pct,
         COALESCE(MAX(CASE WHEN education_level_code = 'SHS' THEN passes_gate END), FALSE) AS shs_passes_gate,
         MIN(CASE WHEN offered_school_count > 0 THEN learner_coverage_pct END) AS lowest_learner_coverage_pct,
         MIN(CASE WHEN offered_school_count > 0 THEN learner_coverage_pct_b END) AS lowest_learner_coverage_pct_b
  FROM levels_gated
  GROUP BY city_mun_psgc_code
), joined AS (
  SELECT m.city_mun_psgc_code, m.city_mun_name, m.lgu_type, m.province_name, m.region_name, m.school_year,
         m.priority_category, m.priority_order, m.classroom_pressure_flag, m.teacher_pressure_flag,
         m.priority_affected_learners, m.growing_enrollment, m.ap2_assessed, m.ap3_assessed, m.ap2_learner_coverage_pct,
         m.ap4_public_enrollment_change, m.ap4_public_enrollment_change_pct,
         COALESCE(o.outlier_school_count, 0) AS outlier_school_count,
         CAST(COALESCE(o.outlier_learner_count, 0) AS BIGINT) AS outlier_learner_count,
         COALESCE(o.classroom_outlier_school_count, 0) AS classroom_outlier_school_count,
         COALESCE(o.teacher_outlier_level_count, 0) AS teacher_outlier_level_count,
         t.lowest_learner_coverage_pct AS ap3_lowest_learner_coverage_pct,
         c.learner_coverage_pct AS ap2_learner_coverage_pct_without_suspected_outliers,
         t.lowest_learner_coverage_pct_b AS ap3_lowest_learner_coverage_pct_without_suspected_outliers,
         COALESCE(c.assessed, FALSE) AS ap2_assessed_without_suspected_outliers,
         COALESCE(t.assessed, FALSE) AS ap3_assessed_without_suspected_outliers,
         c.affected_learners AS ap2_affected_learners_b, t.affected_learners AS ap3_affected_learners_b,
         c.ratio_school_count AS ap2_ratio_school_count_without_suspected_outliers,
         c.eligible_learners AS ap2_eligible_learners_without_suspected_outliers,
         c.reported_rooms AS ap2_reported_rooms_without_suspected_outliers,
         c.learners_per_reported_room AS ap2_learners_per_reported_room_without_suspected_outliers,
         c.congested_school_count AS ap2_affected_school_count_without_suspected_outliers,
         c.affected_learner_share_pct AS ap2_affected_learner_share_pct_without_suspected_outliers,
         t.es_eligible_learners AS ap3_es_eligible_learners_without_suspected_outliers,
         t.es_teacher_count AS ap3_es_teacher_count_without_suspected_outliers,
         t.es_learners_per_teacher AS ap3_es_learners_per_teacher_without_suspected_outliers,
         t.es_learner_coverage_pct AS ap3_es_learner_coverage_pct_without_suspected_outliers,
         COALESCE(t.es_passes_gate, FALSE) AS ap3_es_passes_gate_without_suspected_outliers,
         t.jhs_eligible_learners AS ap3_jhs_eligible_learners_without_suspected_outliers,
         t.jhs_teacher_count AS ap3_jhs_teacher_count_without_suspected_outliers,
         t.jhs_learners_per_teacher AS ap3_jhs_learners_per_teacher_without_suspected_outliers,
         t.jhs_learner_coverage_pct AS ap3_jhs_learner_coverage_pct_without_suspected_outliers,
         COALESCE(t.jhs_passes_gate, FALSE) AS ap3_jhs_passes_gate_without_suspected_outliers,
         t.shs_eligible_learners AS ap3_shs_eligible_learners_without_suspected_outliers,
         t.shs_teacher_count AS ap3_shs_teacher_count_without_suspected_outliers,
         t.shs_learners_per_teacher AS ap3_shs_learners_per_teacher_without_suspected_outliers,
         t.shs_learner_coverage_pct AS ap3_shs_learner_coverage_pct_without_suspected_outliers,
         COALESCE(t.shs_passes_gate, FALSE) AS ap3_shs_passes_gate_without_suspected_outliers,
         COALESCE(t.pressured_level_count, 0) AS ap3_pressured_level_count_b,
         CAST(CASE WHEN c.assessed AND c.congested_school_count > 0 THEN 1 ELSE 0 END AS INT)
           AS classroom_pressure_flag_without_suspected_outliers,
         CAST(CASE WHEN COALESCE(t.pressured_level_count, 0) > 0 THEN 1 ELSE 0 END AS INT)
           AS teacher_pressure_flag_without_suspected_outliers
  FROM edu_access.`06-analytics`.lgu_priority_matrix AS m
  LEFT JOIN outlier_counts AS o USING (city_mun_psgc_code)
  LEFT JOIN ap2_b AS c USING (city_mun_psgc_code)
  LEFT JOIN ap3_b AS t USING (city_mun_psgc_code)
), scenario_b AS (
  SELECT *,
         classroom_pressure_flag_without_suspected_outliers + teacher_pressure_flag_without_suspected_outliers
           AS current_pressure_count_b,
         GREATEST(COALESCE(ap2_affected_learners_b, 0), COALESCE(ap3_affected_learners_b, 0))
           AS priority_affected_learners_without_suspected_outliers,
         -- the D-061 rule, applied to the scenario B flags and coverage
         CASE WHEN classroom_pressure_flag_without_suspected_outliers + teacher_pressure_flag_without_suspected_outliers = 0
                AND (growing_enrollment IS NULL OR NOT ap2_assessed_without_suspected_outliers
                     OR NOT ap3_assessed_without_suspected_outliers) THEN 'Data review'
              WHEN classroom_pressure_flag_without_suspected_outliers + teacher_pressure_flag_without_suspected_outliers = 2
                AND COALESCE(growing_enrollment, FALSE) THEN 'Priority 1'
              WHEN classroom_pressure_flag_without_suspected_outliers + teacher_pressure_flag_without_suspected_outliers = 2
                OR (classroom_pressure_flag_without_suspected_outliers + teacher_pressure_flag_without_suspected_outliers = 1
                    AND COALESCE(growing_enrollment, FALSE)) THEN 'Priority 2'
              WHEN classroom_pressure_flag_without_suspected_outliers + teacher_pressure_flag_without_suspected_outliers = 1
                THEN 'Priority 3'
              WHEN growing_enrollment THEN 'Monitor'
              ELSE 'No current pressure identified' END AS priority_category_without_suspected_outliers
  FROM joined
), compared AS (
  SELECT *,
         ROW_NUMBER() OVER (
           ORDER BY CASE priority_category_without_suspected_outliers WHEN 'Priority 1' THEN 1 WHEN 'Priority 2' THEN 2
                         WHEN 'Priority 3' THEN 3 WHEN 'Monitor' THEN 4 WHEN 'No current pressure identified' THEN 5
                         ELSE 6 END,
             current_pressure_count_b DESC, priority_affected_learners_without_suspected_outliers DESC,
             ap2_affected_learners_b DESC, ap3_pressured_level_count_b DESC, ap4_public_enrollment_change DESC,
             ap4_public_enrollment_change_pct DESC, city_mun_psgc_code
         ) AS priority_order_without_suspected_outliers,
         classroom_pressure_flag <> classroom_pressure_flag_without_suspected_outliers AS classroom_flag_changed,
         teacher_pressure_flag <> teacher_pressure_flag_without_suspected_outliers AS teacher_flag_changed,
         priority_category <> priority_category_without_suspected_outliers AS priority_category_changed,
         (COALESCE(ap2_assessed, FALSE) AND NOT ap2_assessed_without_suspected_outliers)
           OR (COALESCE(ap3_assessed, FALSE) AND NOT ap3_assessed_without_suspected_outliers) AS coverage_gate_changed,
         CASE WHEN priority_affected_learners > 0
              THEN abs(priority_affected_learners_without_suspected_outliers - priority_affected_learners)
                   > 0.10 * priority_affected_learners
              ELSE priority_affected_learners_without_suspected_outliers > 0 END AS affected_learners_changed
  FROM scenario_b
)
SELECT city_mun_psgc_code, city_mun_name, lgu_type, province_name, region_name, school_year,
       outlier_school_count, outlier_learner_count, classroom_outlier_school_count, teacher_outlier_level_count,
       priority_category, priority_category_without_suspected_outliers,
       priority_order, priority_order_without_suspected_outliers,
       classroom_pressure_flag, classroom_pressure_flag_without_suspected_outliers,
       teacher_pressure_flag, teacher_pressure_flag_without_suspected_outliers,
       priority_affected_learners, priority_affected_learners_without_suspected_outliers,
       ap2_learner_coverage_pct, ap2_learner_coverage_pct_without_suspected_outliers,
       ap3_lowest_learner_coverage_pct, ap3_lowest_learner_coverage_pct_without_suspected_outliers,
       ap2_assessed_without_suspected_outliers, ap3_assessed_without_suspected_outliers,
       ap2_ratio_school_count_without_suspected_outliers,
       ap2_eligible_learners_without_suspected_outliers,
       ap2_reported_rooms_without_suspected_outliers,
       ap2_learners_per_reported_room_without_suspected_outliers,
       ap2_affected_school_count_without_suspected_outliers,
       CAST(COALESCE(ap2_affected_learners_b, 0) AS BIGINT) AS ap2_affected_learners_without_suspected_outliers,
       ap2_affected_learner_share_pct_without_suspected_outliers,
       ap3_es_eligible_learners_without_suspected_outliers,
       ap3_es_teacher_count_without_suspected_outliers,
       ap3_es_learners_per_teacher_without_suspected_outliers,
       ap3_es_learner_coverage_pct_without_suspected_outliers,
       ap3_es_passes_gate_without_suspected_outliers,
       ap3_jhs_eligible_learners_without_suspected_outliers,
       ap3_jhs_teacher_count_without_suspected_outliers,
       ap3_jhs_learners_per_teacher_without_suspected_outliers,
       ap3_jhs_learner_coverage_pct_without_suspected_outliers,
       ap3_jhs_passes_gate_without_suspected_outliers,
       ap3_shs_eligible_learners_without_suspected_outliers,
       ap3_shs_teacher_count_without_suspected_outliers,
       ap3_shs_learners_per_teacher_without_suspected_outliers,
       ap3_shs_learner_coverage_pct_without_suspected_outliers,
       ap3_shs_passes_gate_without_suspected_outliers,
       ap3_pressured_level_count_b AS ap3_pressured_level_count_without_suspected_outliers,
       CAST(COALESCE(ap3_affected_learners_b, 0) AS BIGINT) AS ap3_affected_learners_without_suspected_outliers,
       current_pressure_count_b AS current_pressure_count_without_suspected_outliers,
       classroom_flag_changed, teacher_flag_changed, priority_category_changed, coverage_gate_changed,
       affected_learners_changed,
       CASE WHEN outlier_school_count = 0 THEN 'No suspected outliers'
            WHEN priority_category_changed THEN 'Priority-sensitive'
            WHEN classroom_flag_changed OR teacher_flag_changed THEN 'Classification-sensitive'
            WHEN coverage_gate_changed THEN 'Coverage-sensitive'
            WHEN affected_learners_changed THEN 'Magnitude-sensitive'
            ELSE 'Stable' END AS outlier_sensitivity_status,
       'D-065' AS rule_version,
       :code_revision AS code_revision
FROM compared;

COMMENT ON TABLE edu_access.`06-analytics`.lgu_priority_sensitivity_candidate IS 'Unpublished outlier-sensitivity build. Do not read: use lgu_priority_sensitivity.';
ALTER TABLE edu_access.`06-analytics`.lgu_priority_sensitivity_candidate OWNER TO `reached-hq`;
