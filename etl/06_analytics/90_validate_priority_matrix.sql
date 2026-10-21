-- D-060 LGU evidence-table publication gate; validates source reconciliation and the classroom queue.
-- the one-row summary is written once to a table named for this run and dropped after the checks are recorded:
-- read many times as a temporary view, the same pattern made Databricks SQL fail with INTERNAL_ERROR (c64e949, #202).
-- FAIL: rows, keys or LGUs that differ from dim_city_municipality, AP1 to AP3 values that differ from the published
-- outputs, or a classroom group, rank or rule version that does not follow D-060. Counts only (PASS): queued and
-- data-review LGUs.
DECLARE OR REPLACE VARIABLE analytics_gate_started_at_utc TIMESTAMP;
SET VARIABLE analytics_gate_started_at_utc = current_timestamp();
DECLARE OR REPLACE VARIABLE analytics_gate_summary STRING;
SET VARIABLE analytics_gate_summary = '`edu_access`.`06-analytics`.`lgu_priority_matrix_gate_summary_r_' || sha2(:run_id, 256) || '`';
DECLARE OR REPLACE VARIABLE analytics_gate_owner_sql STRING;

CREATE OR REPLACE TABLE IDENTIFIER(session.analytics_gate_summary) USING DELTA COMMENT 'Internal unpublished one-row summary for one D-060 gate.' AS
WITH c AS (
  SELECT * FROM edu_access.`06-analytics`.lgu_priority_matrix_candidate
), regular AS (
  SELECT * FROM edu_access.`05-gold`.dim_city_municipality WHERE member_type = 'regular'
), expected AS (
  SELECT r.city_mun_psgc_code,
         a.learners_per_public_school AS ap1_ratio, a.coverage_pct AS ap1_coverage, a.is_assessed AS ap1_assessed,
         b.learners_per_classroom AS ap2_ratio, b.learner_coverage_pct AS ap2_coverage,
         b.is_assessed AS ap2_assessed, b.congested_school_count AS affected_schools,
         b.learners_in_congested_schools AS affected_learners,
         b.congested_learner_share_pct AS affected_share, b.benchmark_status AS screen_status,
         t.es_learners_per_teacher AS es_ratio, t.jhs_learners_per_teacher AS jhs_ratio,
         t.shs_learners_per_teacher AS shs_ratio, t.is_assessed AS teacher_assessed,
         t.benchmark_status AS teacher_status
  FROM regular r
  LEFT JOIN edu_access.`06-analytics`.ap1_school_provision a USING (city_mun_psgc_code)
  LEFT JOIN edu_access.`06-analytics`.ap2_classroom_pressure b USING (city_mun_psgc_code)
  LEFT JOIN edu_access.`06-analytics`.ap3_teacher_pressure t USING (city_mun_psgc_code)
), expected_rank AS (
  SELECT city_mun_psgc_code,
         DENSE_RANK() OVER (ORDER BY affected_learners DESC, affected_schools DESC, ap2_ratio DESC) AS queue_rank
  FROM expected WHERE ap2_assessed AND affected_learners > 0
)
SELECT
  (SELECT COUNT(*) FROM c) AS rows, (SELECT COUNT(*) FROM regular) AS expected_rows,
  (SELECT COUNT(*) - COUNT(DISTINCT city_mun_psgc_code) FROM c) AS duplicate_keys,
  (SELECT COUNT(*) FROM c FULL OUTER JOIN regular USING (city_mun_psgc_code)
    WHERE c.city_mun_psgc_code IS NULL OR regular.city_mun_psgc_code IS NULL) AS lgu_mismatch,
  (SELECT COUNT(*) FROM c JOIN expected e USING (city_mun_psgc_code)
    WHERE c.ap1_learners_per_public_school IS DISTINCT FROM e.ap1_ratio
       OR c.ap1_coverage_pct IS DISTINCT FROM e.ap1_coverage
       OR c.ap1_assessed IS DISTINCT FROM e.ap1_assessed
       OR c.ap2_learners_per_reported_room IS DISTINCT FROM e.ap2_ratio
       OR c.ap2_learner_coverage_pct IS DISTINCT FROM e.ap2_coverage
       OR c.ap2_assessed IS DISTINCT FROM e.ap2_assessed
       OR c.ap2_screened_congested_school_count IS DISTINCT FROM e.affected_schools
       OR c.ap2_affected_learners IS DISTINCT FROM e.affected_learners
       OR c.ap2_affected_learner_share_pct IS DISTINCT FROM e.affected_share
       OR c.ap2_screen_status IS DISTINCT FROM e.screen_status
       OR c.ap3_es_learners_per_teacher IS DISTINCT FROM e.es_ratio
       OR c.ap3_jhs_learners_per_teacher IS DISTINCT FROM e.jhs_ratio
       OR c.ap3_shs_learners_per_teacher IS DISTINCT FROM e.shs_ratio
       OR c.ap3_fully_assessed IS DISTINCT FROM e.teacher_assessed
       OR c.ap3_review_status IS DISTINCT FROM e.teacher_status) AS input_mismatch,
  (SELECT COUNT(*) FROM c JOIN expected e USING (city_mun_psgc_code)
    LEFT JOIN expected_rank q USING (city_mun_psgc_code)
    WHERE c.classroom_priority_group IS DISTINCT FROM CASE WHEN NOT COALESCE(e.ap2_assessed, FALSE) THEN 'data_review'
            WHEN e.affected_learners > 0 THEN 'reported_congestion_screen'
            ELSE 'no_reported_congestion_screen' END
       OR c.classroom_priority_rank IS DISTINCT FROM q.queue_rank
       OR c.rule_version IS DISTINCT FROM 'D-060') AS queue_mismatch,
  (SELECT COALESCE(COUNT_IF(classroom_priority_group = 'reported_congestion_screen'), 0) FROM c) AS queued_lgus,
  (SELECT COALESCE(COUNT_IF(classroom_priority_group = 'data_review'), 0) FROM c) AS data_review_lgus;
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
  UNION ALL SELECT 'inputs_match_ap_outputs', CASE WHEN input_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(input_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'classroom_queue_follows_d060', CASE WHEN queue_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(queue_mismatch AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'classroom_queue_lgus', 'PASS', CAST(NULL AS STRING), CAST(queued_lgus AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'classroom_data_review_lgus', 'PASS', CAST(NULL AS STRING), CAST(data_review_lgus AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
) AS checks;

DROP TABLE IF EXISTS IDENTIFIER(session.analytics_gate_summary);

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Analytics gate failed for lgu_priority_matrix: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s)') ELSE 1 END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'lgu_priority_matrix' AND layer = 'analytics' AND status = 'FAIL'
  AND checked_at_utc >= session.analytics_gate_started_at_utc;

CREATE OR REPLACE TABLE edu_access.`06-analytics`.lgu_priority_matrix USING DELTA AS
SELECT * FROM edu_access.`06-analytics`.lgu_priority_matrix_candidate;
COMMENT ON TABLE edu_access.`06-analytics`.lgu_priority_matrix IS 'LGU evidence table under D-060 with a separate classroom-screening queue, no composite score or percentile tier.';
ALTER TABLE edu_access.`06-analytics`.lgu_priority_matrix OWNER TO `reached-hq`;
