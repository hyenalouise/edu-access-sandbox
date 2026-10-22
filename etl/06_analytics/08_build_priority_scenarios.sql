-- the planning priority and its AP2 and AP3 evidence in both D-065 scenarios, for the planner dashboard.
-- grain: one regular city or municipality and scenario, SY 2023-24. scenario 'published' repeats lgu_priority_matrix,
-- ap2_classroom_pressure and ap3_teacher_pressure exactly; 'without suspected outliers' takes the same columns from
-- lgu_priority_sensitivity's scenario B. Columns keep the names the published tables use (AP2 and AP3 table columns
-- with an ap2_ or ap3_ prefix where the matrix has no column of that meaning), so the dashboard reads one scenario row
-- in place of the published values and needs no rule of its own. Nothing here changes a published table.

CREATE SCHEMA IF NOT EXISTS edu_access.`06-analytics`;
ALTER SCHEMA edu_access.`06-analytics` OWNER TO `reached-hq`;

CREATE OR REPLACE TABLE edu_access.`06-analytics`.lgu_priority_scenarios_candidate USING DELTA AS
WITH published AS (
  SELECT m.city_mun_psgc_code, 'published' AS scenario,
         m.priority_category, m.priority_order, m.classroom_pressure_flag, m.teacher_pressure_flag,
         m.current_pressure_count, m.priority_affected_learners,
         m.ap2_learners_per_reported_room, m.ap2_learner_coverage_pct, m.ap2_assessed, m.ap2_affected_school_count,
         m.ap2_affected_learners, m.ap2_affected_learner_share_pct,
         a2.ratio_school_count AS ap2_ratio_school_count, a2.eligible_learners AS ap2_eligible_learners,
         a2.reported_instructional_classrooms AS ap2_reported_instructional_classrooms,
         a2.not_assessed_reason AS ap2_not_assessed_reason, a2.benchmark_status AS ap2_benchmark_status,
         m.ap3_es_learners_per_teacher, m.ap3_jhs_learners_per_teacher, m.ap3_shs_learners_per_teacher,
         m.ap3_assessed, m.ap3_pressured_level_count, m.ap3_affected_learners,
         a3.es_eligible_learners AS ap3_es_eligible_learners, a3.es_teacher_count AS ap3_es_teacher_count,
         a3.es_learner_coverage_pct AS ap3_es_learner_coverage_pct, a3.es_passes_gate AS ap3_es_passes_gate,
         a3.es_benchmark_status AS ap3_es_benchmark_status,
         a3.jhs_eligible_learners AS ap3_jhs_eligible_learners, a3.jhs_teacher_count AS ap3_jhs_teacher_count,
         a3.jhs_learner_coverage_pct AS ap3_jhs_learner_coverage_pct, a3.jhs_passes_gate AS ap3_jhs_passes_gate,
         a3.jhs_benchmark_status AS ap3_jhs_benchmark_status,
         a3.shs_eligible_learners AS ap3_shs_eligible_learners, a3.shs_teacher_count AS ap3_shs_teacher_count,
         a3.shs_learner_coverage_pct AS ap3_shs_learner_coverage_pct, a3.shs_passes_gate AS ap3_shs_passes_gate,
         a3.shs_benchmark_status AS ap3_shs_benchmark_status,
         a3.not_assessed_reason AS ap3_not_assessed_reason, a3.benchmark_status AS ap3_benchmark_status,
         s.outlier_school_count, s.outlier_sensitivity_status, s.coverage_gate_changed
  FROM edu_access.`06-analytics`.lgu_priority_matrix AS m
  JOIN edu_access.`06-analytics`.ap2_classroom_pressure AS a2 ON a2.city_mun_psgc_code = m.city_mun_psgc_code
  JOIN edu_access.`06-analytics`.ap3_teacher_pressure AS a3 ON a3.city_mun_psgc_code = m.city_mun_psgc_code
  JOIN edu_access.`06-analytics`.lgu_priority_sensitivity AS s ON s.city_mun_psgc_code = m.city_mun_psgc_code
), without_outliers AS (
  -- scenario B: an AP2 or AP3 status follows the same wording as the published table, from the recalculated figures
  SELECT s.city_mun_psgc_code, 'without suspected outliers' AS scenario,
         s.priority_category_without_suspected_outliers, s.priority_order_without_suspected_outliers,
         s.classroom_pressure_flag_without_suspected_outliers, s.teacher_pressure_flag_without_suspected_outliers,
         s.current_pressure_count_without_suspected_outliers, s.priority_affected_learners_without_suspected_outliers,
         s.ap2_learners_per_reported_room_without_suspected_outliers, s.ap2_learner_coverage_pct_without_suspected_outliers,
         s.ap2_assessed_without_suspected_outliers, s.ap2_affected_school_count_without_suspected_outliers,
         s.ap2_affected_learners_without_suspected_outliers, s.ap2_affected_learner_share_pct_without_suspected_outliers,
         s.ap2_ratio_school_count_without_suspected_outliers, s.ap2_eligible_learners_without_suspected_outliers,
         s.ap2_reported_rooms_without_suspected_outliers,
         CASE WHEN s.ap2_assessed_without_suspected_outliers THEN NULL
              WHEN a2.not_assessed_reason IS NOT NULL THEN a2.not_assessed_reason
              WHEN s.ap2_learners_per_reported_room_without_suspected_outliers IS NULL THEN 'no usable classroom denominator'
              ELSE 'learner coverage below 90%' END,
         CASE WHEN NOT s.ap2_assessed_without_suspected_outliers THEN 'not assessed'
              WHEN s.ap2_affected_school_count_without_suspected_outliers > 0 THEN 'reported congestion identified'
              ELSE 'no reported congestion identified' END,
         s.ap3_es_learners_per_teacher_without_suspected_outliers, s.ap3_jhs_learners_per_teacher_without_suspected_outliers,
         s.ap3_shs_learners_per_teacher_without_suspected_outliers, s.ap3_assessed_without_suspected_outliers,
         s.ap3_pressured_level_count_without_suspected_outliers, s.ap3_affected_learners_without_suspected_outliers,
         s.ap3_es_eligible_learners_without_suspected_outliers, s.ap3_es_teacher_count_without_suspected_outliers,
         s.ap3_es_learner_coverage_pct_without_suspected_outliers, s.ap3_es_passes_gate_without_suspected_outliers,
         CASE WHEN a3.es_offered_school_count = 0 THEN 'not applicable'
              WHEN NOT s.ap3_es_passes_gate_without_suspected_outliers THEN 'not assessed'
              WHEN s.ap3_es_learners_per_teacher_without_suspected_outliers > 35 THEN 'above historical study reference'
              ELSE 'at or below historical study reference' END,
         s.ap3_jhs_eligible_learners_without_suspected_outliers, s.ap3_jhs_teacher_count_without_suspected_outliers,
         s.ap3_jhs_learner_coverage_pct_without_suspected_outliers, s.ap3_jhs_passes_gate_without_suspected_outliers,
         CASE WHEN a3.jhs_offered_school_count = 0 THEN 'not applicable'
              WHEN NOT s.ap3_jhs_passes_gate_without_suspected_outliers THEN 'not assessed'
              WHEN s.ap3_jhs_learners_per_teacher_without_suspected_outliers > 36 THEN 'above derived deployment comparison'
              ELSE 'at or below derived deployment comparison' END,
         s.ap3_shs_eligible_learners_without_suspected_outliers, s.ap3_shs_teacher_count_without_suspected_outliers,
         s.ap3_shs_learner_coverage_pct_without_suspected_outliers, s.ap3_shs_passes_gate_without_suspected_outliers,
         CASE WHEN a3.shs_offered_school_count = 0 THEN 'not applicable'
              WHEN NOT s.ap3_shs_passes_gate_without_suspected_outliers THEN 'not assessed'
              WHEN s.ap3_shs_learners_per_teacher_without_suspected_outliers > 80.0 / 3 THEN 'above derived deployment comparison'
              ELSE 'at or below derived deployment comparison' END,
         CASE WHEN s.ap3_assessed_without_suspected_outliers THEN NULL
              WHEN a3.not_assessed_reason IS NOT NULL THEN a3.not_assessed_reason
              ELSE 'an offered level is below 90% learner coverage' END,
         CASE WHEN a3.es_offered_school_count = 0 AND a3.jhs_offered_school_count = 0 AND a3.shs_offered_school_count = 0
              THEN 'not assessed'
              WHEN s.teacher_pressure_flag_without_suspected_outliers = 1 THEN 'pressure signal identified'
              WHEN NOT s.ap3_assessed_without_suspected_outliers THEN 'not fully assessed'
              ELSE 'no pressure signal identified' END,
         s.outlier_school_count, s.outlier_sensitivity_status, s.coverage_gate_changed
  FROM edu_access.`06-analytics`.lgu_priority_sensitivity AS s
  JOIN edu_access.`06-analytics`.ap2_classroom_pressure AS a2 ON a2.city_mun_psgc_code = s.city_mun_psgc_code
  JOIN edu_access.`06-analytics`.ap3_teacher_pressure AS a3 ON a3.city_mun_psgc_code = s.city_mun_psgc_code
)
SELECT *, 'D-065' AS rule_version, :code_revision AS code_revision FROM published
UNION ALL
SELECT *, 'D-065', :code_revision FROM without_outliers;

COMMENT ON TABLE edu_access.`06-analytics`.lgu_priority_scenarios_candidate IS 'Unpublished scenario build. Do not read: use lgu_priority_scenarios.';
ALTER TABLE edu_access.`06-analytics`.lgu_priority_scenarios_candidate OWNER TO `reached-hq`;
