-- Gold gate for fact_school_classroom_capacity: one row per facilities Silver row, every key in its
-- dimension, and each school year's school set inside the enrollment fact (the room join must not add
-- rows to enrollment). Blank, zero and partly reported room counts are counted for review.

DECLARE OR REPLACE VARIABLE gold_gate_started_at_utc TIMESTAMP;
SET VARIABLE gold_gate_started_at_utc = current_timestamp();

INSERT INTO edu_access.`01-control`.data_quality_results
  (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, CAST(NULL AS STRING), 'fact_school_classroom_capacity', 'gold', 'edu_access.05-gold.fact_school_classroom_capacity_candidate',
       check_name, status, expected, actual, current_timestamp(), :code_revision
FROM (
WITH c AS (SELECT * FROM edu_access.`05-gold`.fact_school_classroom_capacity_candidate),
f AS (SELECT * FROM edu_access.`03-silver`.deped_facilities_clean),
enrolled AS (SELECT DISTINCT school_id, school_year FROM edu_access.`05-gold`.fact_school_enrollment),
s AS (
  SELECT
    (SELECT COUNT(*) FROM f) AS silver_rows,
    (SELECT COALESCE(COUNT_IF(COALESCE(es_classrooms_instructional, jhs_classrooms_instructional, shs_classrooms_instructional) IS NOT NULL
                     AND (es_classrooms_instructional IS NULL OR jhs_classrooms_instructional IS NULL OR shs_classrooms_instructional IS NULL)), 0)
     FROM f) AS partial_rooms,
    (SELECT SUM(COALESCE(es_classrooms_instructional, 0) + COALESCE(jhs_classrooms_instructional, 0) + COALESCE(shs_classrooms_instructional, 0)) FROM f) AS silver_rooms,
    COUNT(*) AS rows_built,
    COUNT(DISTINCT c.school_id || '/' || c.school_year) AS keys_built,
    COALESCE(COUNT_IF(ds.school_id IS NULL), 0) AS no_school,
    COALESCE(COUNT_IF(dy.school_year IS NULL), 0) AS no_year,
    COALESCE(COUNT_IF(en.school_id IS NULL), 0) AS not_in_enrollment,
    COALESCE(COUNT_IF(c.instructional_classrooms_total < 0 OR c.temporary_learning_spaces < 0 OR c.makeshift_rooms < 0
             OR c.classes_using_temporary_learning_spaces < 0 OR c.classes_using_makeshift_rooms < 0), 0) AS negative_counts,
    COALESCE(COUNT_IF(c.instructional_classrooms_total IS NULL), 0) AS blank_rooms,
    COALESCE(COUNT_IF(c.instructional_classrooms_total = 0), 0) AS zero_rooms,
    COALESCE(SUM(c.instructional_classrooms_total), 0) AS gold_rooms
  FROM c
  LEFT JOIN edu_access.`05-gold`.dim_school AS ds ON ds.school_id = c.school_id
  LEFT JOIN edu_access.`05-gold`.dim_school_year AS dy ON dy.school_year = c.school_year
  LEFT JOIN enrolled AS en ON en.school_id = c.school_id AND en.school_year = c.school_year
)
SELECT 'rows_reconcile' AS check_name, CASE WHEN rows_built = silver_rows THEN 'PASS' ELSE 'FAIL' END AS status,
       CAST(silver_rows AS STRING) AS expected, CAST(rows_built AS STRING) AS actual FROM s
UNION ALL SELECT 'one_row_per_school_year', CASE WHEN keys_built = rows_built THEN 'PASS' ELSE 'FAIL' END,
                 CAST(rows_built AS STRING), CAST(keys_built AS STRING) FROM s
UNION ALL SELECT 'school_in_dim_school', CASE WHEN no_school = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(no_school AS STRING) FROM s
UNION ALL SELECT 'school_year_in_dim', CASE WHEN no_year = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(no_year AS STRING) FROM s
UNION ALL SELECT 'school_year_in_enrollment', CASE WHEN not_in_enrollment = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(not_in_enrollment AS STRING) FROM s
UNION ALL SELECT 'no_negative_counts', CASE WHEN negative_counts = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(negative_counts AS STRING) FROM s
UNION ALL SELECT 'rooms_reconcile', CASE WHEN gold_rooms = silver_rooms THEN 'PASS' ELSE 'FAIL' END,
                 CAST(silver_rooms AS STRING), CAST(gold_rooms AS STRING) FROM s
UNION ALL SELECT 'rooms_blank', CASE WHEN blank_rooms = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(blank_rooms AS STRING) FROM s
UNION ALL SELECT 'rooms_zero', CASE WHEN zero_rooms = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(zero_rooms AS STRING) FROM s
UNION ALL SELECT 'rooms_partly_reported', CASE WHEN partial_rooms = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(partial_rooms AS STRING) FROM s
) AS results;

MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (SELECT :run_id AS run_id, COUNT_IF(status = 'FAIL') AS fails FROM edu_access.`01-control`.data_quality_results
       WHERE run_id = :run_id AND source_id = 'fact_school_classroom_capacity' AND layer = 'gold'
         AND checked_at_utc >= session.gold_gate_started_at_utc) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'gold_build' AND t.source_id = 'fact_school_classroom_capacity'
WHEN MATCHED AND s.fails > 0 THEN UPDATE SET status = 'failed', finished_at_utc = current_timestamp(),
  failure_stage = 'gate', error_message = CAST(s.fails AS STRING) || ' FAIL result(s) in data_quality_results';

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Gold gate failed for fact_school_classroom_capacity: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s)') END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'fact_school_classroom_capacity' AND layer = 'gold' AND status = 'FAIL'
  AND checked_at_utc >= session.gold_gate_started_at_utc;

CREATE OR REPLACE TABLE edu_access.`05-gold`.fact_school_classroom_capacity USING DELTA AS SELECT * FROM edu_access.`05-gold`.fact_school_classroom_capacity_candidate;
ALTER TABLE edu_access.`05-gold`.fact_school_classroom_capacity OWNER TO `reached-hq`;

MERGE INTO edu_access.`01-control`.pipeline_runs AS t USING (SELECT :run_id AS run_id) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'gold_build' AND t.source_id = 'fact_school_classroom_capacity'
WHEN MATCHED THEN UPDATE SET status = 'succeeded', finished_at_utc = current_timestamp(), failure_stage = NULL, error_message = NULL;
