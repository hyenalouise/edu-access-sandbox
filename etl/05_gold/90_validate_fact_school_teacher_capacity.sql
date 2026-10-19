-- Gold gate for fact_school_teacher_capacity: three rows per personnel Silver row, every key in its
-- dimension, funding subtotals within teacher_count, and partly reported rows counted for review.

DECLARE OR REPLACE VARIABLE gold_gate_started_at_utc TIMESTAMP;
SET VARIABLE gold_gate_started_at_utc = current_timestamp();

INSERT INTO edu_access.`01-control`.data_quality_results
  (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, CAST(NULL AS STRING), 'fact_school_teacher_capacity', 'gold', 'edu_access.05-gold.fact_school_teacher_capacity_candidate',
       check_name, status, expected, actual, current_timestamp(), :code_revision
FROM (
WITH c AS (SELECT * FROM edu_access.`05-gold`.fact_school_teacher_capacity_candidate),
mix AS (
SELECT school_id, school_year, 'ES' AS education_level_code,
       COALESCE(es_teacher_i, es_teacher_ii, es_teacher_iii, es_master_teacher_i, es_master_teacher_ii, es_master_teacher_iii, es_master_teacher_iv, es_head_teacher_i, es_head_teacher_ii, es_head_teacher_iii, es_head_teacher_iv, es_head_teacher_v, es_head_teacher_vi, es_sped_sned_teacher_i, es_sped_sned_teacher_ii, es_sped_sned_teacher_iii, es_sped_sned_teacher_iv, es_sped_sned_teacher_v, kinder_teachers_sef_province, es_teachers_sef_province, kinder_teachers_sef_municipality_city, es_teachers_sef_municipality_city, kinder_teachers_lgu_funding, es_teachers_lgu_funding, kinder_teachers_other_funding, es_teachers_other_funding) IS NOT NULL AND (es_teacher_i IS NULL OR es_teacher_ii IS NULL OR es_teacher_iii IS NULL OR es_master_teacher_i IS NULL OR es_master_teacher_ii IS NULL OR es_master_teacher_iii IS NULL OR es_master_teacher_iv IS NULL OR es_head_teacher_i IS NULL OR es_head_teacher_ii IS NULL OR es_head_teacher_iii IS NULL OR es_head_teacher_iv IS NULL OR es_head_teacher_v IS NULL OR es_head_teacher_vi IS NULL OR es_sped_sned_teacher_i IS NULL OR es_sped_sned_teacher_ii IS NULL OR es_sped_sned_teacher_iii IS NULL OR es_sped_sned_teacher_iv IS NULL OR es_sped_sned_teacher_v IS NULL OR kinder_teachers_sef_province IS NULL OR es_teachers_sef_province IS NULL OR kinder_teachers_sef_municipality_city IS NULL OR es_teachers_sef_municipality_city IS NULL OR kinder_teachers_lgu_funding IS NULL OR es_teachers_lgu_funding IS NULL OR kinder_teachers_other_funding IS NULL OR es_teachers_other_funding IS NULL) AS is_partial
FROM edu_access.`03-silver`.deped_personnel_clean
UNION ALL
SELECT school_id, school_year, 'JHS' AS education_level_code,
       COALESCE(jhs_teacher_i, jhs_teacher_ii, jhs_teacher_iii, jhs_master_teacher_i, jhs_master_teacher_ii, jhs_master_teacher_iii, jhs_master_teacher_iv, jhs_head_teacher_i, jhs_head_teacher_ii, jhs_head_teacher_iii, jhs_head_teacher_iv, jhs_head_teacher_v, jhs_head_teacher_vi, jhs_sped_teacher_i, jhs_sped_teacher_ii, jhs_sped_teacher_iii, jhs_sped_teacher_iv, jhs_sped_teacher_v, jhs_special_science_teacher_i, jhs_instructor_i, jhs_instructor_ii, jhs_instructor_iii, jhs_teachers_sef_province, jhs_teachers_sef_municipality_city, jhs_teachers_lgu_funding, jhs_teachers_other_funding) IS NOT NULL AND (jhs_teacher_i IS NULL OR jhs_teacher_ii IS NULL OR jhs_teacher_iii IS NULL OR jhs_master_teacher_i IS NULL OR jhs_master_teacher_ii IS NULL OR jhs_master_teacher_iii IS NULL OR jhs_master_teacher_iv IS NULL OR jhs_head_teacher_i IS NULL OR jhs_head_teacher_ii IS NULL OR jhs_head_teacher_iii IS NULL OR jhs_head_teacher_iv IS NULL OR jhs_head_teacher_v IS NULL OR jhs_head_teacher_vi IS NULL OR jhs_sped_teacher_i IS NULL OR jhs_sped_teacher_ii IS NULL OR jhs_sped_teacher_iii IS NULL OR jhs_sped_teacher_iv IS NULL OR jhs_sped_teacher_v IS NULL OR jhs_special_science_teacher_i IS NULL OR jhs_instructor_i IS NULL OR jhs_instructor_ii IS NULL OR jhs_instructor_iii IS NULL OR jhs_teachers_sef_province IS NULL OR jhs_teachers_sef_municipality_city IS NULL OR jhs_teachers_lgu_funding IS NULL OR jhs_teachers_other_funding IS NULL) AS is_partial
FROM edu_access.`03-silver`.deped_personnel_clean
UNION ALL
SELECT school_id, school_year, 'SHS' AS education_level_code,
       COALESCE(shs_teacher_i, shs_teacher_ii, shs_teacher_iii, shs_master_teacher_i, shs_master_teacher_ii, shs_master_teacher_iii, shs_master_teacher_iv, shs_head_teacher_i, shs_head_teacher_ii, shs_head_teacher_iii, shs_head_teacher_iv, shs_head_teacher_v, shs_head_teacher_vi, shs_special_science_teacher_i, shs_teachers_sef_province, shs_teachers_sef_municipality_city, shs_teachers_lgu_funding, shs_teachers_other_funding) IS NOT NULL AND (shs_teacher_i IS NULL OR shs_teacher_ii IS NULL OR shs_teacher_iii IS NULL OR shs_master_teacher_i IS NULL OR shs_master_teacher_ii IS NULL OR shs_master_teacher_iii IS NULL OR shs_master_teacher_iv IS NULL OR shs_head_teacher_i IS NULL OR shs_head_teacher_ii IS NULL OR shs_head_teacher_iii IS NULL OR shs_head_teacher_iv IS NULL OR shs_head_teacher_v IS NULL OR shs_head_teacher_vi IS NULL OR shs_special_science_teacher_i IS NULL OR shs_teachers_sef_province IS NULL OR shs_teachers_sef_municipality_city IS NULL OR shs_teachers_lgu_funding IS NULL OR shs_teachers_other_funding IS NULL) AS is_partial
FROM edu_access.`03-silver`.deped_personnel_clean
),
s AS (
  SELECT
    (SELECT COUNT(*) FROM edu_access.`03-silver`.deped_personnel_clean) AS silver_rows,
    (SELECT COALESCE(COUNT_IF(is_partial), 0) FROM mix) AS partial_rows,
    COUNT(*) AS rows_built,
    COUNT(DISTINCT c.school_id || '/' || c.school_year || '/' || c.education_level_code) AS keys_built,
    COALESCE(COUNT_IF(ds.school_id IS NULL), 0) AS no_school,
    COALESCE(COUNT_IF(dy.school_year IS NULL), 0) AS no_year,
    COALESCE(COUNT_IF(dl.education_level_code IS NULL), 0) AS no_level,
    COALESCE(COUNT_IF(c.teacher_count < 0), 0) AS negative_counts,
    COALESCE(COUNT_IF(COALESCE(c.sef_provincial_teacher_count, 0) + COALESCE(c.sef_city_municipal_teacher_count, 0)
             + COALESCE(c.lgu_funded_teacher_count, 0) + COALESCE(c.other_funded_teacher_count, 0) > COALESCE(c.teacher_count, 0)), 0) AS funding_above_total,
    COALESCE(COUNT_IF(c.teacher_count IS NULL), 0) AS null_totals,
    SUM(c.teacher_count) AS teachers
  FROM c
  LEFT JOIN edu_access.`05-gold`.dim_school AS ds ON ds.school_id = c.school_id
  LEFT JOIN edu_access.`05-gold`.dim_school_year AS dy ON dy.school_year = c.school_year
  LEFT JOIN edu_access.`05-gold`.dim_education_level AS dl ON dl.education_level_code = c.education_level_code
)
SELECT 'rows_reconcile' AS check_name, CASE WHEN rows_built = silver_rows * 3 THEN 'PASS' ELSE 'FAIL' END AS status,
       CAST(silver_rows * 3 AS STRING) AS expected, CAST(rows_built AS STRING) AS actual FROM s
UNION ALL SELECT 'one_row_per_school_year_level', CASE WHEN keys_built = rows_built THEN 'PASS' ELSE 'FAIL' END,
                 CAST(rows_built AS STRING), CAST(keys_built AS STRING) FROM s
UNION ALL SELECT 'school_in_dim_school', CASE WHEN no_school = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(no_school AS STRING) FROM s
UNION ALL SELECT 'school_year_in_dim', CASE WHEN no_year = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(no_year AS STRING) FROM s
UNION ALL SELECT 'level_in_dim', CASE WHEN no_level = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(no_level AS STRING) FROM s
UNION ALL SELECT 'no_negative_counts', CASE WHEN negative_counts = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(negative_counts AS STRING) FROM s
UNION ALL SELECT 'funding_within_total', CASE WHEN funding_above_total = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(funding_above_total AS STRING) FROM s
UNION ALL SELECT 'teacher_count_missing', CASE WHEN null_totals = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(null_totals AS STRING) FROM s
UNION ALL SELECT 'partly_reported_rows', CASE WHEN partial_rows = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(partial_rows AS STRING) FROM s
UNION ALL SELECT 'teachers_total', 'PASS', 'count', CAST(teachers AS STRING) FROM s
) AS results;

MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (SELECT :run_id AS run_id, COUNT_IF(status = 'FAIL') AS fails FROM edu_access.`01-control`.data_quality_results
       WHERE run_id = :run_id AND source_id = 'fact_school_teacher_capacity' AND layer = 'gold'
         AND checked_at_utc >= session.gold_gate_started_at_utc) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'gold_build' AND t.source_id = 'fact_school_teacher_capacity'
WHEN MATCHED AND s.fails > 0 THEN UPDATE SET status = 'failed', finished_at_utc = current_timestamp(),
  failure_stage = 'gate', error_message = CAST(s.fails AS STRING) || ' FAIL result(s) in data_quality_results';

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Gold gate failed for fact_school_teacher_capacity: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s)') END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'fact_school_teacher_capacity' AND layer = 'gold' AND status = 'FAIL'
  AND checked_at_utc >= session.gold_gate_started_at_utc;

CREATE OR REPLACE TABLE edu_access.`05-gold`.fact_school_teacher_capacity USING DELTA AS SELECT * FROM edu_access.`05-gold`.fact_school_teacher_capacity_candidate;
ALTER TABLE edu_access.`05-gold`.fact_school_teacher_capacity OWNER TO `reached-hq`;

MERGE INTO edu_access.`01-control`.pipeline_runs AS t USING (SELECT :run_id AS run_id) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'gold_build' AND t.source_id = 'fact_school_teacher_capacity'
WHEN MATCHED THEN UPDATE SET status = 'succeeded', finished_at_utc = current_timestamp(), failure_stage = NULL, error_message = NULL;
