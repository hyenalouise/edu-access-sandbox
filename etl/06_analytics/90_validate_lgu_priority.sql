-- Analytics gate for the LGU priority table: one row per regular LGU, a tier that agrees with its measure
-- statuses, percentiles within 0 to 1, a gapless priority order, and the checks D-057 reports beside the
-- ranking: the tier counts, the flag rate per measure and type (about 10% expected), Stable, how many
-- LGUs join Critical at a lower line or leave it at a 95% gate, the LGUs whose tier changes without the
-- outlier schools, and the overlap of the measures by type (Spearman rank correlation, and the share of
-- LGUs high on one measure also high on another, 10% if unrelated). The revisit trigger (fewer than 80% of
-- Critical LGUs kept and at least 3 leave) is a WARN, at the 95% gate and without outliers.
-- The outlier school list has its own rows: one row per school, measure and level, each above its fence.

DECLARE OR REPLACE VARIABLE analytics_gate_started_at_utc TIMESTAMP;
SET VARIABLE analytics_gate_started_at_utc = current_timestamp();

INSERT INTO edu_access.`01-control`.data_quality_results
  (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, CAST(NULL AS STRING), 'lgu_priority', 'analytics', 'edu_access.06-analytics.lgu_priority_candidate',
       check_name, status, expected, actual, current_timestamp(), :code_revision
FROM (
WITH c AS (SELECT * FROM edu_access.`06-analytics`.lgu_priority_candidate),
s AS (
  SELECT
    (SELECT COUNT(*) FROM edu_access.`05-gold`.dim_city_municipality WHERE member_type = 'regular') AS regular_lgus,
    COUNT(*) AS rows_built,
    COUNT(DISTINCT city_mun_psgc_code) AS keys_built,
    COALESCE(COUNT_IF(tier_code NOT IN ('3', '2', '1', '0', 'data_review') OR tier_code IS NULL), 0) AS bad_tier,
    COALESCE(COUNT_IF(tier_code <> 'data_review' AND tier_code <> CAST(high_measure_count AS STRING)), 0) AS tier_not_count,
    COALESCE(COUNT_IF((tier_code = 'data_review') <> (ap1_status = 'not_assessed' OR ap2_status = 'not_assessed' OR ap3_status = 'not_assessed')), 0) AS review_mismatch,
    COALESCE(COUNT_IF(ap1_percentile < 0 OR ap1_percentile > 1 OR ap2_percentile < 0 OR ap2_percentile > 1 OR ap3_percentile < 0 OR ap3_percentile > 1), 0) AS pct_out_of_range,
    COALESCE(COUNT_IF(is_stable AND tier_code <> '3'), 0) AS bad_stable,
    COUNT(DISTINCT priority_rank) AS ranks, MIN(priority_rank) AS min_rank, MAX(priority_rank) AS max_rank,
    COALESCE(COUNT_IF(tier_code = '3'), 0) AS critical, COALESCE(COUNT_IF(tier_code = '2'), 0) AS elevated, COALESCE(COUNT_IF(tier_code = '1'), 0) AS targeted,
    COALESCE(COUNT_IF(tier_code = '0'), 0) AS monitor, COALESCE(COUNT_IF(tier_code = 'data_review'), 0) AS data_review,
    COALESCE(COUNT_IF(is_stable), 0) AS stable,
    COALESCE(COUNT_IF(critical_at_line_085 AND tier_code <> '3'), 0) AS join_085,
    COALESCE(COUNT_IF(critical_at_line_080 AND tier_code <> '3'), 0) AS join_080,
    COALESCE(COUNT_IF(tier_code = '3' AND NOT critical_at_line_085), 0) AS leave_085,
    COALESCE(COUNT_IF(tier_code = '3' AND critical_at_gate_95), 0) AS kept_95,
    COALESCE(COUNT_IF(tier_code = '3' AND NOT critical_at_gate_95), 0) AS leave_95,
    COALESCE(COUNT_IF(critical_at_gate_95 AND tier_code <> '3'), 0) AS join_95,
    COALESCE(COUNT_IF(tier_code_without_outliers IS NULL), 0) AS missing_wo,
    COALESCE(COUNT_IF(tier_code <> tier_code_without_outliers), 0) AS changed_wo,
    COALESCE(COUNT_IF(tier_code <> 'data_review' AND tier_code_without_outliers <> 'data_review'
                      AND tier_code_without_outliers > tier_code), 0) AS up_wo,
    COALESCE(COUNT_IF(tier_code <> 'data_review' AND tier_code_without_outliers <> 'data_review'
                      AND tier_code_without_outliers < tier_code), 0) AS down_wo,
    COALESCE(COUNT_IF(tier_code <> tier_code_without_outliers
                      AND (tier_code = 'data_review' OR tier_code_without_outliers = 'data_review')), 0) AS review_wo,
    COALESCE(COUNT_IF(tier_code = '3' AND tier_code_without_outliers = '3'), 0) AS kept_wo,
    COALESCE(COUNT_IF(tier_code = '3' AND tier_code_without_outliers <> '3'), 0) AS leave_wo,
    COALESCE(COUNT_IF(tier_code <> '3' AND tier_code_without_outliers = '3'), 0) AS join_wo
  FROM c
),
flag_rate AS (
  SELECT lgu_type,
         100.0 * COALESCE(COUNT_IF(ap1_status = 'high'), 0) / NULLIF(COALESCE(COUNT_IF(ap1_status <> 'not_assessed'), 0), 0) AS ap1_rate,
         100.0 * COALESCE(COUNT_IF(ap2_status = 'high'), 0) / NULLIF(COALESCE(COUNT_IF(ap2_status <> 'not_assessed'), 0), 0) AS ap2_rate,
         100.0 * COALESCE(COUNT_IF(ap3_status = 'high'), 0) / NULLIF(COALESCE(COUNT_IF(ap3_status <> 'not_assessed'), 0), 0) AS ap3_rate
  FROM c GROUP BY lgu_type
),
-- Overlap: each pair of measures over the LGUs assessed on both. Spearman is the correlation of average
-- ranks. The percentiles rank like the ratios within type (AP3 by its re-ranked percentile).
pairs AS (
  SELECT lgu_type, 'ap1_ap2' AS pair, ap1_percentile AS x, ap2_percentile AS y, ap1_status = 'high' AS x_high, ap2_status = 'high' AS y_high
  FROM c WHERE ap1_status <> 'not_assessed' AND ap2_status <> 'not_assessed'
  UNION ALL
  SELECT lgu_type, 'ap1_ap3', ap1_percentile, ap3_percentile, ap1_status = 'high', ap3_status = 'high'
  FROM c WHERE ap1_status <> 'not_assessed' AND ap3_status <> 'not_assessed'
  UNION ALL
  SELECT lgu_type, 'ap2_ap3', ap2_percentile, ap3_percentile, ap2_status = 'high', ap3_status = 'high'
  FROM c WHERE ap2_status <> 'not_assessed' AND ap3_status <> 'not_assessed'
),
ranked AS (
  SELECT pairs.*,
         CAST(RANK() OVER (PARTITION BY lgu_type, pair ORDER BY x) + COUNT(*) OVER (PARTITION BY lgu_type, pair) + 1
              - RANK() OVER (PARTITION BY lgu_type, pair ORDER BY x DESC) AS DOUBLE) / 2 AS rx,
         CAST(RANK() OVER (PARTITION BY lgu_type, pair ORDER BY y) + COUNT(*) OVER (PARTITION BY lgu_type, pair) + 1
              - RANK() OVER (PARTITION BY lgu_type, pair ORDER BY y DESC) AS DOUBLE) / 2 AS ry
  FROM pairs
),
overlap AS (
  SELECT lgu_type, pair, COUNT(*) AS lgus, corr(rx, ry) AS spearman,
         COALESCE(COUNT_IF(x_high), 0) AS x_high, COALESCE(COUNT_IF(y_high), 0) AS y_high,
         COALESCE(COUNT_IF(x_high AND y_high), 0) AS both_high
  FROM ranked GROUP BY lgu_type, pair
)
SELECT 'one_row_per_regular_lgu' AS check_name,
       CASE WHEN rows_built = regular_lgus AND keys_built = rows_built THEN 'PASS' ELSE 'FAIL' END AS status,
       CAST(regular_lgus AS STRING) AS expected, CAST(rows_built AS STRING) AS actual FROM s
UNION ALL SELECT 'tier_code_valid', CASE WHEN bad_tier = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_tier AS STRING) FROM s
UNION ALL SELECT 'tier_is_count_of_high_measures', CASE WHEN tier_not_count = 0 AND review_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END,
                 '0', CAST(tier_not_count + review_mismatch AS STRING) FROM s
UNION ALL SELECT 'percentiles_in_range', CASE WHEN pct_out_of_range = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(pct_out_of_range AS STRING) FROM s
UNION ALL SELECT 'stable_only_if_critical', CASE WHEN bad_stable = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_stable AS STRING) FROM s
UNION ALL SELECT 'priority_rank_gapless', CASE WHEN ranks = rows_built AND min_rank = 1 AND max_rank = rows_built THEN 'PASS' ELSE 'FAIL' END,
                 '1..' || CAST(rows_built AS STRING), CAST(min_rank AS STRING) || '..' || CAST(max_rank AS STRING) FROM s
UNION ALL SELECT 'tier_counts', 'PASS', 'critical / elevated / targeted / monitor / data review',
                 CAST(critical AS STRING) || ' / ' || CAST(elevated AS STRING) || ' / ' || CAST(targeted AS STRING) || ' / '
                   || CAST(monitor AS STRING) || ' / ' || CAST(data_review AS STRING) FROM s
UNION ALL SELECT 'stable_critical', 'PASS', 'count', CAST(stable AS STRING) FROM s
UNION ALL SELECT 'line_085_and_080_join_critical', 'PASS', 'join at 0.85 / 0.80', CAST(join_085 AS STRING) || ' / ' || CAST(join_080 AS STRING) FROM s
UNION ALL SELECT 'lower_line_only_adds', CASE WHEN leave_085 = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(leave_085 AS STRING) FROM s
UNION ALL SELECT 'gate_95_critical_kept', 'PASS', 'kept / left / joined',
                 CAST(kept_95 AS STRING) || ' / ' || CAST(leave_95 AS STRING) || ' / ' || CAST(join_95 AS STRING) FROM s
UNION ALL SELECT 'revisit_trigger_gate_95',
                 CASE WHEN critical > 0 AND 100.0 * kept_95 / critical < 80 AND leave_95 >= 3 THEN 'WARN' ELSE 'PASS' END,
                 'keep >= 80% or fewer than 3 leave', CAST(kept_95 AS STRING) || ' of ' || CAST(critical AS STRING) || ' kept' FROM s
UNION ALL SELECT 'tier_without_outliers_built', CASE WHEN missing_wo = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(missing_wo AS STRING) FROM s
UNION ALL SELECT 'outlier_tier_changes', 'PASS', 'changed: up / down / to or from data review',
                 CAST(changed_wo AS STRING) || ': ' || CAST(up_wo AS STRING) || ' / ' || CAST(down_wo AS STRING) || ' / ' || CAST(review_wo AS STRING) FROM s
UNION ALL SELECT 'outlier_critical_kept', 'PASS', 'kept / left / joined',
                 CAST(kept_wo AS STRING) || ' / ' || CAST(leave_wo AS STRING) || ' / ' || CAST(join_wo AS STRING) FROM s
UNION ALL SELECT 'revisit_trigger_outliers',
                 CASE WHEN critical > 0 AND 100.0 * kept_wo / critical < 80 AND leave_wo >= 3 THEN 'WARN' ELSE 'PASS' END,
                 'keep >= 80% or fewer than 3 leave', CAST(kept_wo AS STRING) || ' of ' || CAST(critical AS STRING) || ' kept' FROM s
UNION ALL SELECT 'flag_rate_' || lower(lgu_type), 'PASS', 'about 10% each: AP1 / AP2 / AP3',
                 CAST(ROUND(ap1_rate, 1) AS STRING) || ' / ' || CAST(ROUND(ap2_rate, 1) AS STRING) || ' / ' || CAST(ROUND(ap3_rate, 1) AS STRING)
FROM flag_rate
UNION ALL SELECT 'overlap_' || lower(lgu_type) || '_' || pair, 'PASS',
                 'Spearman / high on first also high on second / the reverse (10% if unrelated), over n LGUs',
                 COALESCE(CAST(ROUND(spearman, 2) AS STRING), 'none') || ' / '
                   || COALESCE(CAST(ROUND(100.0 * both_high / NULLIF(x_high, 0), 1) AS STRING) || '%', 'none') || ' / '
                   || COALESCE(CAST(ROUND(100.0 * both_high / NULLIF(y_high, 0), 1) AS STRING) || '%', 'none')
                   || ', n = ' || CAST(lgus AS STRING)
FROM overlap
) AS results;

INSERT INTO edu_access.`01-control`.data_quality_results
  (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, CAST(NULL AS STRING), 'lgu_priority', 'analytics', 'edu_access.06-analytics.lgu_priority_outlier_schools_candidate',
       check_name, status, expected, actual, current_timestamp(), :code_revision
FROM (
WITH o AS (SELECT * FROM edu_access.`06-analytics`.lgu_priority_outlier_schools_candidate),
s AS (
  SELECT COUNT(*) AS rows_built,
         COUNT(DISTINCT school_id || '|' || measure || '|' || education_level_code) AS keys_built,
         COALESCE(COUNT_IF(NOT ratio > upper_fence OR ratio IS NULL OR upper_fence IS NULL), 0) AS not_above_fence,
         COALESCE(COUNT_IF(run_id IS NULL OR run_id <> :run_id), 0) AS other_run
  FROM o
),
flagged AS (
  SELECT lgu_type, measure, education_level_code, COUNT(*) AS schools, MAX(schools_scored) AS schools_scored, MAX(upper_fence) AS upper_fence
  FROM o GROUP BY lgu_type, measure, education_level_code
)
SELECT 'one_row_per_school_measure_level' AS check_name,
       CASE WHEN keys_built = rows_built THEN 'PASS' ELSE 'FAIL' END AS status,
       CAST(rows_built AS STRING) AS expected, CAST(keys_built AS STRING) AS actual FROM s
UNION ALL SELECT 'flagged_above_fence', CASE WHEN not_above_fence = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(not_above_fence AS STRING) FROM s
UNION ALL SELECT 'saved_with_this_run', CASE WHEN other_run = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(other_run AS STRING) FROM s
UNION ALL SELECT 'outlier_schools_' || lower(lgu_type) || '_' || lower(measure) || CASE WHEN measure = 'AP3' THEN '_' || lower(education_level_code) ELSE '' END,
                 'PASS', 'flagged of scored (share), fence',
                 CAST(schools AS STRING) || ' of ' || CAST(schools_scored AS STRING) || ' ('
                   || CAST(ROUND(100.0 * schools / NULLIF(schools_scored, 0), 1) AS STRING) || '%), above '
                   || CAST(ROUND(upper_fence, 1) AS STRING)
FROM flagged
) AS results;

MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (SELECT :run_id AS run_id, COUNT_IF(status = 'FAIL') AS fails FROM edu_access.`01-control`.data_quality_results
       WHERE run_id = :run_id AND source_id = 'lgu_priority' AND layer = 'analytics'
         AND checked_at_utc >= session.analytics_gate_started_at_utc) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'analytics_build' AND t.source_id = 'lgu_priority'
WHEN MATCHED AND s.fails > 0 THEN UPDATE SET status = 'failed', finished_at_utc = current_timestamp(),
  failure_stage = 'gate', error_message = CAST(s.fails AS STRING) || ' FAIL result(s) in data_quality_results';

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Analytics gate failed for lgu_priority: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s)') END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'lgu_priority' AND layer = 'analytics' AND status = 'FAIL'
  AND checked_at_utc >= session.analytics_gate_started_at_utc;

CREATE OR REPLACE TABLE edu_access.`06-analytics`.lgu_priority_outlier_schools USING DELTA AS
SELECT * FROM edu_access.`06-analytics`.lgu_priority_outlier_schools_candidate;
ALTER TABLE edu_access.`06-analytics`.lgu_priority_outlier_schools OWNER TO `reached-hq`;
CREATE OR REPLACE TABLE edu_access.`06-analytics`.lgu_priority USING DELTA AS SELECT * FROM edu_access.`06-analytics`.lgu_priority_candidate;
ALTER TABLE edu_access.`06-analytics`.lgu_priority OWNER TO `reached-hq`;

MERGE INTO edu_access.`01-control`.pipeline_runs AS t USING (SELECT :run_id AS run_id) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'analytics_build' AND t.source_id = 'lgu_priority'
WHEN MATCHED THEN UPDATE SET status = 'succeeded', finished_at_utc = current_timestamp(), failure_stage = NULL, error_message = NULL;
