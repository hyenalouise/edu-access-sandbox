-- D-065 publication gate for the two planning-priority scenarios the planner dashboard reads.
DECLARE OR REPLACE VARIABLE analytics_gate_started_at_utc TIMESTAMP;
SET VARIABLE analytics_gate_started_at_utc = current_timestamp();
DECLARE OR REPLACE VARIABLE analytics_gate_summary STRING;
SET VARIABLE analytics_gate_summary = '`edu_access`.`06-analytics`.`lgu_priority_scenarios_gate_summary_r_' || sha2(:run_id, 256) || '`';
DECLARE OR REPLACE VARIABLE analytics_gate_owner_sql STRING;

CREATE OR REPLACE TABLE IDENTIFIER(session.analytics_gate_summary) USING DELTA COMMENT 'Internal unpublished one-row summary for one D-065 gate.' AS
WITH c AS (SELECT * FROM edu_access.`06-analytics`.lgu_priority_scenarios_candidate),
a AS (SELECT * FROM c WHERE scenario = 'published'),
b AS (SELECT * FROM c WHERE scenario = 'without suspected outliers'),
m AS (SELECT * FROM edu_access.`06-analytics`.lgu_priority_matrix),
s AS (SELECT * FROM edu_access.`06-analytics`.lgu_priority_sensitivity),
regular AS (SELECT city_mun_psgc_code FROM edu_access.`05-gold`.dim_city_municipality WHERE member_type = 'regular')
SELECT
  (SELECT COUNT(*) FROM c) AS rows,
  2 * (SELECT COUNT(*) FROM regular) AS expected_rows,
  (SELECT COUNT(*) - COUNT(DISTINCT city_mun_psgc_code || '|' || scenario) FROM c) AS duplicate_keys,
  (SELECT COUNT(*) FROM c WHERE scenario NOT IN ('published', 'without suspected outliers')) AS unknown_scenarios,
  (SELECT COUNT(*) FROM regular AS r FULL OUTER JOIN b USING (city_mun_psgc_code)
    WHERE r.city_mun_psgc_code IS NULL OR b.city_mun_psgc_code IS NULL) AS lgu_mismatch,
  -- the published scenario is the published matrix, AP2 and AP3
  (SELECT COUNT(*) FROM a JOIN m USING (city_mun_psgc_code)
     JOIN edu_access.`06-analytics`.ap2_classroom_pressure AS a2 USING (city_mun_psgc_code)
     JOIN edu_access.`06-analytics`.ap3_teacher_pressure AS a3 USING (city_mun_psgc_code)
    WHERE a.priority_category IS DISTINCT FROM m.priority_category OR a.priority_order IS DISTINCT FROM m.priority_order
       OR a.priority_affected_learners IS DISTINCT FROM m.priority_affected_learners
       OR a.ap2_affected_learners IS DISTINCT FROM a2.learners_in_congested_schools
       OR a.ap2_ratio_school_count IS DISTINCT FROM a2.ratio_school_count
       OR a.ap2_learners_per_reported_room IS DISTINCT FROM a2.learners_per_classroom
       OR a.ap3_es_learners_per_teacher IS DISTINCT FROM a3.es_learners_per_teacher
       OR a.ap3_jhs_learners_per_teacher IS DISTINCT FROM a3.jhs_learners_per_teacher
       OR a.ap3_shs_learners_per_teacher IS DISTINCT FROM a3.shs_learners_per_teacher
       OR a.ap3_es_benchmark_status IS DISTINCT FROM a3.es_benchmark_status
       OR a.ap3_benchmark_status IS DISTINCT FROM a3.benchmark_status) AS published_mismatch,
  -- the other scenario is lgu_priority_sensitivity's scenario B
  (SELECT COUNT(*) FROM b JOIN s USING (city_mun_psgc_code)
    WHERE b.priority_category IS DISTINCT FROM s.priority_category_without_suspected_outliers
       OR b.priority_order IS DISTINCT FROM s.priority_order_without_suspected_outliers
       OR b.classroom_pressure_flag IS DISTINCT FROM s.classroom_pressure_flag_without_suspected_outliers
       OR b.teacher_pressure_flag IS DISTINCT FROM s.teacher_pressure_flag_without_suspected_outliers
       OR b.priority_affected_learners IS DISTINCT FROM s.priority_affected_learners_without_suspected_outliers
       OR b.outlier_sensitivity_status IS DISTINCT FROM s.outlier_sensitivity_status
       OR b.coverage_gate_changed IS DISTINCT FROM s.coverage_gate_changed
       OR b.ap2_ratio_school_count IS DISTINCT FROM s.ap2_ratio_school_count_without_suspected_outliers
       OR b.ap3_es_learners_per_teacher IS DISTINCT FROM s.ap3_es_learners_per_teacher_without_suspected_outliers
       OR b.ap3_jhs_learners_per_teacher IS DISTINCT FROM s.ap3_jhs_learners_per_teacher_without_suspected_outliers
       OR b.ap3_shs_learners_per_teacher IS DISTINCT FROM s.ap3_shs_learners_per_teacher_without_suspected_outliers)
    AS scenario_b_mismatch,
  -- an LGU with no suspected outlier has the same figures in both scenarios
  (SELECT COUNT(*) FROM a JOIN b USING (city_mun_psgc_code)
    WHERE a.outlier_school_count = 0
      AND (a.priority_category IS DISTINCT FROM b.priority_category
           OR a.priority_affected_learners IS DISTINCT FROM b.priority_affected_learners
           OR a.ap2_eligible_learners IS DISTINCT FROM b.ap2_eligible_learners
           OR a.ap2_reported_instructional_classrooms IS DISTINCT FROM b.ap2_reported_instructional_classrooms
           OR a.ap2_affected_school_count IS DISTINCT FROM b.ap2_affected_school_count
           OR a.ap2_not_assessed_reason IS DISTINCT FROM b.ap2_not_assessed_reason
           OR a.ap2_benchmark_status IS DISTINCT FROM b.ap2_benchmark_status
           OR a.ap3_es_teacher_count IS DISTINCT FROM b.ap3_es_teacher_count
           OR a.ap3_jhs_teacher_count IS DISTINCT FROM b.ap3_jhs_teacher_count
           OR a.ap3_shs_teacher_count IS DISTINCT FROM b.ap3_shs_teacher_count
           OR a.ap3_es_benchmark_status IS DISTINCT FROM b.ap3_es_benchmark_status
           OR a.ap3_jhs_benchmark_status IS DISTINCT FROM b.ap3_jhs_benchmark_status
           OR a.ap3_shs_benchmark_status IS DISTINCT FROM b.ap3_shs_benchmark_status
           OR a.ap3_not_assessed_reason IS DISTINCT FROM b.ap3_not_assessed_reason
           OR a.ap3_benchmark_status IS DISTINCT FROM b.ap3_benchmark_status)) AS unflagged_scenarios_differ;
SET VARIABLE analytics_gate_owner_sql = 'ALTER TABLE ' || session.analytics_gate_summary || ' OWNER TO `reached-hq`';
EXECUTE IMMEDIATE analytics_gate_owner_sql;

INSERT INTO edu_access.`01-control`.data_quality_results
  (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, NULL, 'lgu_priority_scenarios', 'analytics', 'edu_access.06-analytics.lgu_priority_scenarios_candidate',
       check_name, status, expected, actual, current_timestamp(), :code_revision
FROM (
  SELECT 'rows_match_regular_lgus_per_scenario' AS check_name, CASE WHEN rows = expected_rows THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(expected_rows AS STRING) AS expected, CAST(rows AS STRING) AS actual FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'key_unique', CASE WHEN duplicate_keys = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(duplicate_keys AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'scenario_allowed', CASE WHEN unknown_scenarios = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(unknown_scenarios AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'lgu_membership_reconciles', CASE WHEN lgu_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(lgu_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'published_scenario_matches_published_tables', CASE WHEN published_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(published_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'scenario_b_matches_sensitivity', CASE WHEN scenario_b_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(scenario_b_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'unflagged_lgu_scenarios_identical', CASE WHEN unflagged_scenarios_differ = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(unflagged_scenarios_differ AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
) AS checks;

DROP TABLE IF EXISTS IDENTIFIER(session.analytics_gate_summary);

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Analytics gate failed for lgu_priority_scenarios: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s)') ELSE 1 END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'lgu_priority_scenarios' AND layer = 'analytics' AND status = 'FAIL'
  AND checked_at_utc >= session.analytics_gate_started_at_utc;

CREATE OR REPLACE TABLE edu_access.`06-analytics`.lgu_priority_scenarios USING DELTA AS
SELECT * FROM edu_access.`06-analytics`.lgu_priority_scenarios_candidate;
COMMENT ON TABLE edu_access.`06-analytics`.lgu_priority_scenarios IS 'The D-061 planning priority and its AP2 and AP3 evidence, published and without suspected extreme schools (D-065), one row per LGU and scenario, for the planner dashboard.';
ALTER TABLE edu_access.`06-analytics`.lgu_priority_scenarios OWNER TO `reached-hq`;
