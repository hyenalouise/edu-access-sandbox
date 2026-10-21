-- D-061 publication gate for the lgu planning-priority matrix.
DECLARE OR REPLACE VARIABLE analytics_gate_started_at_utc TIMESTAMP;
SET VARIABLE analytics_gate_started_at_utc = current_timestamp();
DECLARE OR REPLACE VARIABLE analytics_gate_summary STRING;
SET VARIABLE analytics_gate_summary = '`edu_access`.`06-analytics`.`lgu_priority_matrix_gate_summary_r_' || sha2(:run_id, 256) || '`';
DECLARE OR REPLACE VARIABLE analytics_gate_owner_sql STRING;

CREATE OR REPLACE TABLE IDENTIFIER(session.analytics_gate_summary) USING DELTA COMMENT 'Internal unpublished one-row summary for one D-061 gate.' AS
WITH c AS (SELECT * FROM edu_access.`06-analytics`.lgu_priority_matrix_candidate),
regular AS (SELECT * FROM edu_access.`05-gold`.dim_city_municipality WHERE member_type = 'regular'),
expected_joined AS (
  SELECT l.city_mun_psgc_code, COALESCE(b.is_assessed, FALSE) AS ap2_assessed,
    COALESCE(c.is_assessed, FALSE) AS ap3_assessed,
    CAST(CASE WHEN b.is_assessed AND b.congested_school_count > 0 THEN 1 ELSE 0 END AS INT) AS classroom_pressure_flag,
    CAST(CASE WHEN (c.es_benchmark_status = 'above historical study reference'
      OR c.jhs_benchmark_status = 'above derived deployment comparison'
      OR c.shs_benchmark_status = 'above derived deployment comparison') THEN 1 ELSE 0 END AS INT) AS teacher_pressure_flag,
    COALESCE(b.learners_in_congested_schools, 0) AS ap2_affected_learners,
    CAST((CASE WHEN c.es_benchmark_status = 'above historical study reference' THEN c.es_eligible_learners ELSE 0 END)
      + (CASE WHEN c.jhs_benchmark_status = 'above derived deployment comparison' THEN c.jhs_eligible_learners ELSE 0 END)
      + (CASE WHEN c.shs_benchmark_status = 'above derived deployment comparison' THEN c.shs_eligible_learners ELSE 0 END) AS BIGINT)
      AS ap3_affected_learners,
    CAST((CASE WHEN c.es_benchmark_status = 'above historical study reference' THEN 1 ELSE 0 END)
      + (CASE WHEN c.jhs_benchmark_status = 'above derived deployment comparison' THEN 1 ELSE 0 END)
      + (CASE WHEN c.shs_benchmark_status = 'above derived deployment comparison' THEN 1 ELSE 0 END) AS INT)
      AS ap3_pressured_level_count,
    d.public_enrollment_change_first_to_latest AS ap4_public_enrollment_change,
    100 * d.public_enrollment_change_pct_first_to_latest AS ap4_public_enrollment_change_pct,
    CASE WHEN NOT COALESCE(d.is_2020_2024_geography_comparable, FALSE) THEN NULL
         WHEN d.public_enrollment_trend = 'increasing' THEN TRUE
         WHEN d.public_enrollment_trend IN ('decreasing', 'no change') THEN FALSE END AS growing_enrollment
  FROM regular AS l
  LEFT JOIN edu_access.`06-analytics`.ap2_classroom_pressure AS b USING (city_mun_psgc_code)
  LEFT JOIN edu_access.`06-analytics`.ap3_teacher_pressure AS c USING (city_mun_psgc_code)
  LEFT JOIN edu_access.`06-analytics`.ap4_enrollment_trend AS d
    ON d.city_mun_psgc_code = l.city_mun_psgc_code AND d.school_year = d.latest_school_year
), expected_inputs AS (
  -- every value the matrix copies from AP1 to AP4, read again from the published tables
  SELECT l.city_mun_psgc_code,
    a.learners_per_public_school AS ap1_learners_per_public_school, a.coverage_pct AS ap1_coverage_pct,
    a.is_assessed AS ap1_assessed, a.public_school_enrollment AS ap1_public_school_enrollment,
    a.school_age_population_per_public_school AS ap1_school_age_population_per_public_school,
    b.learners_per_classroom AS ap2_learners_per_reported_room, b.learner_coverage_pct AS ap2_learner_coverage_pct,
    b.is_assessed AS ap2_assessed, b.congested_school_count AS ap2_affected_school_count,
    b.learners_in_congested_schools AS ap2_affected_learners,
    b.congested_learner_share_pct AS ap2_affected_learner_share_pct, b.benchmark_status AS ap2_screen_status,
    c.es_learners_per_teacher AS ap3_es_learners_per_teacher, c.jhs_learners_per_teacher AS ap3_jhs_learners_per_teacher,
    c.shs_learners_per_teacher AS ap3_shs_learners_per_teacher, c.is_assessed AS ap3_assessed,
    c.benchmark_status AS ap3_review_status,
    d.public_enrollment_first_school_year AS ap4_public_enrollment_first,
    d.public_enrollment_latest_school_year AS ap4_public_enrollment_latest,
    d.public_enrollment_trend AS ap4_public_enrollment_trend,
    d.public_enrollment_endpoints_complete AS ap4_public_enrollment_endpoints_complete,
    d.is_2020_2024_geography_comparable AS ap4_geography_comparable,
    g.population_enrollment_gap AS ap4_gap_2024, 100 * g.gap_share AS ap4_gap_rate_2024_pct,
    CASE WHEN d.city_mun_psgc_code IS NULL THEN 'no AP4 enrollment row'
         WHEN COALESCE(d.is_2020_2024_geography_comparable, FALSE) AND d.public_enrollment_trend IS NOT NULL THEN NULL
         WHEN NOT COALESCE(d.is_2020_2024_geography_comparable, FALSE) AND g.school_age_population IS NULL
           THEN 'no 2024 census population row'
         WHEN NOT COALESCE(d.is_2020_2024_geography_comparable, FALSE) THEN 'boundary changed 2020-2024'
         WHEN NOT COALESCE(d.public_enrollment_endpoints_complete, FALSE)
           THEN 'public enrollment incomplete in first or latest school year'
         ELSE 'no public enrollment in first school year' END AS growth_not_assessed_reason
  FROM regular AS l
  LEFT JOIN edu_access.`06-analytics`.ap1_school_provision AS a USING (city_mun_psgc_code)
  LEFT JOIN edu_access.`06-analytics`.ap2_classroom_pressure AS b USING (city_mun_psgc_code)
  LEFT JOIN edu_access.`06-analytics`.ap3_teacher_pressure AS c USING (city_mun_psgc_code)
  LEFT JOIN edu_access.`06-analytics`.ap4_enrollment_trend AS d
    ON d.city_mun_psgc_code = l.city_mun_psgc_code AND d.school_year = d.latest_school_year
  LEFT JOIN edu_access.`06-analytics`.ap4_enrollment_trend AS g
    ON g.city_mun_psgc_code = l.city_mun_psgc_code AND g.school_year = '2024-25'
), expected_grouped AS (
  SELECT *, classroom_pressure_flag + teacher_pressure_flag AS current_pressure_count,
    GREATEST(ap2_affected_learners, ap3_affected_learners) AS priority_affected_learners,
    CASE WHEN classroom_pressure_flag + teacher_pressure_flag = 0
           AND (growing_enrollment IS NULL OR NOT ap2_assessed OR NOT ap3_assessed) THEN 'Data review'
         WHEN classroom_pressure_flag + teacher_pressure_flag = 2 AND COALESCE(growing_enrollment, FALSE) THEN 'Priority 1'
         WHEN classroom_pressure_flag + teacher_pressure_flag = 2
           OR (classroom_pressure_flag + teacher_pressure_flag = 1 AND COALESCE(growing_enrollment, FALSE)) THEN 'Priority 2'
         WHEN classroom_pressure_flag + teacher_pressure_flag = 1 THEN 'Priority 3'
         WHEN growing_enrollment THEN 'Monitor' ELSE 'No current pressure identified' END AS priority_category
  FROM expected_joined
), expected AS (
  SELECT *, ROW_NUMBER() OVER (
    ORDER BY CASE priority_category WHEN 'Priority 1' THEN 1 WHEN 'Priority 2' THEN 2 WHEN 'Priority 3' THEN 3
                                    WHEN 'Monitor' THEN 4 WHEN 'No current pressure identified' THEN 5 ELSE 6 END,
      current_pressure_count DESC, priority_affected_learners DESC, ap2_affected_learners DESC,
      ap3_pressured_level_count DESC, ap4_public_enrollment_change DESC,
      ap4_public_enrollment_change_pct DESC, city_mun_psgc_code) AS priority_order
  FROM expected_grouped
)
SELECT
  (SELECT COUNT(*) FROM c) AS rows, (SELECT COUNT(*) FROM regular) AS expected_rows,
  (SELECT COUNT(*) - COUNT(DISTINCT city_mun_psgc_code) FROM c) AS duplicate_keys,
  (SELECT COUNT(*) FROM c FULL OUTER JOIN regular USING (city_mun_psgc_code)
    WHERE c.city_mun_psgc_code IS NULL OR regular.city_mun_psgc_code IS NULL) AS lgu_mismatch,
  (SELECT COUNT_IF(current_pressure_count <> classroom_pressure_flag + teacher_pressure_flag
      OR classroom_pressure_flag NOT IN (0, 1) OR teacher_pressure_flag NOT IN (0, 1)
      OR priority_affected_learners <> GREATEST(COALESCE(ap2_affected_learners, 0), COALESCE(ap3_affected_learners, 0))
      OR priority_category IS DISTINCT FROM
        CASE WHEN current_pressure_count = 0
               AND (growing_enrollment IS NULL
                    OR NOT COALESCE(ap2_assessed, FALSE) OR NOT COALESCE(ap3_assessed, FALSE)) THEN 'Data review'
             WHEN current_pressure_count = 2 AND COALESCE(growing_enrollment, FALSE) THEN 'Priority 1'
             WHEN current_pressure_count = 2
               OR (current_pressure_count = 1 AND COALESCE(growing_enrollment, FALSE)) THEN 'Priority 2'
             WHEN current_pressure_count = 1 THEN 'Priority 3'
             WHEN growing_enrollment THEN 'Monitor'
             ELSE 'No current pressure identified' END
      OR rule_version <> 'D-061') FROM c) AS rule_mismatch,
  (SELECT COUNT(*) FROM c JOIN expected AS e USING (city_mun_psgc_code)
    WHERE c.classroom_pressure_flag IS DISTINCT FROM e.classroom_pressure_flag
       OR c.teacher_pressure_flag IS DISTINCT FROM e.teacher_pressure_flag
       OR c.growing_enrollment IS DISTINCT FROM e.growing_enrollment
       OR c.current_pressure_count IS DISTINCT FROM e.current_pressure_count
       OR c.priority_affected_learners IS DISTINCT FROM e.priority_affected_learners
       OR c.ap3_pressured_level_count IS DISTINCT FROM e.ap3_pressured_level_count
       OR c.ap3_affected_learners IS DISTINCT FROM e.ap3_affected_learners
       OR c.ap4_public_enrollment_change IS DISTINCT FROM e.ap4_public_enrollment_change
       OR c.ap4_public_enrollment_change_pct IS DISTINCT FROM e.ap4_public_enrollment_change_pct
       OR c.priority_category IS DISTINCT FROM e.priority_category) AS source_reconciliation_mismatch,
  (SELECT COUNT(*) FROM c JOIN expected_inputs AS e USING (city_mun_psgc_code)
    WHERE c.ap1_learners_per_public_school IS DISTINCT FROM e.ap1_learners_per_public_school
       OR c.ap1_coverage_pct IS DISTINCT FROM e.ap1_coverage_pct OR c.ap1_assessed IS DISTINCT FROM e.ap1_assessed
       OR c.ap1_public_school_enrollment IS DISTINCT FROM e.ap1_public_school_enrollment
       OR c.ap1_school_age_population_per_public_school IS DISTINCT FROM e.ap1_school_age_population_per_public_school
       OR c.ap2_learners_per_reported_room IS DISTINCT FROM e.ap2_learners_per_reported_room
       OR c.ap2_learner_coverage_pct IS DISTINCT FROM e.ap2_learner_coverage_pct
       OR c.ap2_assessed IS DISTINCT FROM e.ap2_assessed
       OR c.ap2_affected_school_count IS DISTINCT FROM e.ap2_affected_school_count
       OR c.ap2_affected_learners IS DISTINCT FROM e.ap2_affected_learners
       OR c.ap2_affected_learner_share_pct IS DISTINCT FROM e.ap2_affected_learner_share_pct
       OR c.ap2_screen_status IS DISTINCT FROM e.ap2_screen_status
       OR c.ap3_es_learners_per_teacher IS DISTINCT FROM e.ap3_es_learners_per_teacher
       OR c.ap3_jhs_learners_per_teacher IS DISTINCT FROM e.ap3_jhs_learners_per_teacher
       OR c.ap3_shs_learners_per_teacher IS DISTINCT FROM e.ap3_shs_learners_per_teacher
       OR c.ap3_assessed IS DISTINCT FROM e.ap3_assessed OR c.ap3_review_status IS DISTINCT FROM e.ap3_review_status
       OR c.ap4_public_enrollment_first IS DISTINCT FROM e.ap4_public_enrollment_first
       OR c.ap4_public_enrollment_latest IS DISTINCT FROM e.ap4_public_enrollment_latest
       OR c.ap4_public_enrollment_trend IS DISTINCT FROM e.ap4_public_enrollment_trend
       OR c.ap4_public_enrollment_endpoints_complete IS DISTINCT FROM e.ap4_public_enrollment_endpoints_complete
       OR c.ap4_geography_comparable IS DISTINCT FROM e.ap4_geography_comparable
       OR c.ap4_gap_2024 IS DISTINCT FROM e.ap4_gap_2024 OR c.ap4_gap_rate_2024_pct IS DISTINCT FROM e.ap4_gap_rate_2024_pct
       OR c.growth_not_assessed_reason IS DISTINCT FROM e.growth_not_assessed_reason) AS input_mismatch,
  (SELECT COUNT(*) FROM c JOIN expected AS e USING (city_mun_psgc_code)
    WHERE c.priority_order IS DISTINCT FROM e.priority_order) AS ordering_mismatch,
  (SELECT COUNT(*) - COUNT(DISTINCT priority_order) FROM c) AS duplicate_orders,
  (SELECT COUNT_IF(priority_category = 'Data review') FROM c) AS data_review_lgus,
  (SELECT COUNT_IF(priority_category = 'Priority 1') FROM c) AS priority_1_lgus;
SET VARIABLE analytics_gate_owner_sql = 'ALTER TABLE ' || session.analytics_gate_summary || ' OWNER TO `reached-hq`';
EXECUTE IMMEDIATE analytics_gate_owner_sql;

INSERT INTO edu_access.`01-control`.data_quality_results
  (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, NULL, 'lgu_priority_matrix', 'analytics', 'edu_access.06-analytics.lgu_priority_matrix_candidate',
       check_name, status, expected, actual, current_timestamp(), :code_revision
FROM (
  SELECT 'rows_match_regular_lgus' AS check_name, CASE WHEN rows = expected_rows THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(expected_rows AS STRING) AS expected, CAST(rows AS STRING) AS actual FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'key_unique', CASE WHEN duplicate_keys = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(duplicate_keys AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'lgu_membership_reconciles', CASE WHEN lgu_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(lgu_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'priority_rule_follows_d061', CASE WHEN rule_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(rule_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'inputs_match_ap_outputs', CASE WHEN input_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(input_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'priority_inputs_reconcile_to_ap2_ap3_ap4', CASE WHEN source_reconciliation_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(source_reconciliation_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'priority_order_recomputed', CASE WHEN ordering_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(ordering_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'priority_order_unique', CASE WHEN duplicate_orders = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(duplicate_orders AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'data_review_lgus', 'PASS', NULL, CAST(data_review_lgus AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'priority_1_lgus', 'PASS', NULL, CAST(priority_1_lgus AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
) AS checks;

DROP TABLE IF EXISTS IDENTIFIER(session.analytics_gate_summary);

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Analytics gate failed for lgu_priority_matrix: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s)') ELSE 1 END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'lgu_priority_matrix' AND layer = 'analytics' AND status = 'FAIL'
  AND checked_at_utc >= session.analytics_gate_started_at_utc;

CREATE OR REPLACE TABLE edu_access.`06-analytics`.lgu_priority_matrix USING DELTA AS
SELECT * FROM edu_access.`06-analytics`.lgu_priority_matrix_candidate;
COMMENT ON TABLE edu_access.`06-analytics`.lgu_priority_matrix IS 'LGU planning-priority categories from separate AP2 and AP3 pressure flags and AP4 public-enrollment growth under D-061.';
ALTER TABLE edu_access.`06-analytics`.lgu_priority_matrix OWNER TO `reached-hq`;
