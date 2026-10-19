DECLARE OR REPLACE VARIABLE gold_gate_started_at_utc TIMESTAMP;
SET VARIABLE gold_gate_started_at_utc = current_timestamp();

CREATE OR REPLACE TEMPORARY VIEW fact_school_classroom_capacity_gate_summary AS
WITH source AS (
  SELECT * FROM edu_access.`03-silver`.deped_facilities_clean WHERE sector = 'Public'
), expected AS (
  SELECT
    school_id,
    school_year,
    CASE WHEN es_classrooms_instructional IS NULL AND jhs_classrooms_instructional IS NULL AND shs_classrooms_instructional IS NULL THEN NULL ELSE COALESCE(es_classrooms_instructional, 0) + COALESCE(jhs_classrooms_instructional, 0) + COALESCE(shs_classrooms_instructional, 0) END AS instructional_classrooms_total,
    CASE WHEN es_temporary_learning_spaces IS NULL AND hs_temporary_learning_spaces IS NULL THEN NULL ELSE COALESCE(es_temporary_learning_spaces, 0) + COALESCE(hs_temporary_learning_spaces, 0) END AS temporary_learning_spaces,
    CASE WHEN es_classes_using_temporary_learning_spaces IS NULL AND hs_classes_using_temporary_learning_spaces IS NULL THEN NULL ELSE COALESCE(es_classes_using_temporary_learning_spaces, 0) + COALESCE(hs_classes_using_temporary_learning_spaces, 0) END AS classes_using_temporary_learning_spaces,
    CASE WHEN es_makeshift_rooms IS NULL AND hs_makeshift_rooms IS NULL THEN NULL ELSE COALESCE(es_makeshift_rooms, 0) + COALESCE(hs_makeshift_rooms, 0) END AS makeshift_rooms,
    CASE WHEN es_classes_using_makeshift_rooms IS NULL AND hs_classes_using_makeshift_rooms IS NULL THEN NULL ELSE COALESCE(es_classes_using_makeshift_rooms, 0) + COALESCE(hs_classes_using_makeshift_rooms, 0) END AS classes_using_makeshift_rooms
  FROM source
), fact AS (
  SELECT * FROM edu_access.`05-gold`.fact_school_classroom_capacity_candidate
)
SELECT
  (SELECT COUNT(*) FROM source) AS source_rows,
  (SELECT COUNT(*) FROM fact) AS fact_rows,
  (SELECT COUNT(*) - COUNT(DISTINCT (school_id, school_year)) FROM fact) AS duplicate_keys,
  (SELECT COUNT_IF(school_id IS NULL OR school_year IS NULL) FROM fact) AS null_keys,
  (SELECT COUNT(*) FROM fact AS f LEFT JOIN edu_access.`05-gold`.dim_school AS d ON d.school_id = f.school_id WHERE d.school_id IS NULL) AS missing_school_keys,
  (SELECT COUNT(*) FROM fact AS f LEFT JOIN edu_access.`05-gold`.dim_school_year AS d ON d.school_year = f.school_year WHERE d.school_year IS NULL) AS missing_school_year_keys,
  (SELECT COUNT(*) FROM fact AS f JOIN expected AS e USING (school_id, school_year) WHERE f.instructional_classrooms_total IS DISTINCT FROM e.instructional_classrooms_total OR f.temporary_learning_spaces IS DISTINCT FROM e.temporary_learning_spaces OR f.classes_using_temporary_learning_spaces IS DISTINCT FROM e.classes_using_temporary_learning_spaces OR f.makeshift_rooms IS DISTINCT FROM e.makeshift_rooms OR f.classes_using_makeshift_rooms IS DISTINCT FROM e.classes_using_makeshift_rooms) AS wrong_derived_values,
  (SELECT COUNT(*) FROM fact AS f LEFT JOIN edu_access.`03-silver`.deped_enrollment_clean AS e ON e.school_id = f.school_id AND e.school_year = f.school_year) AS enrollment_join_rows,
  (SELECT COUNT(*) FROM fact AS f LEFT JOIN edu_access.`03-silver`.deped_enrollment_clean AS e ON e.school_id = f.school_id AND e.school_year = f.school_year WHERE e.school_id IS NULL) AS missing_enrollment_rows,
  (SELECT COUNT_IF(instructional_classrooms_total < 0 OR temporary_learning_spaces < 0 OR classes_using_temporary_learning_spaces < 0 OR makeshift_rooms < 0 OR classes_using_makeshift_rooms < 0) FROM fact) AS negative_measures,
  (SELECT COUNT_IF(instructional_classrooms_total = 0) FROM fact) AS zero_denominators,
  (SELECT COUNT_IF(offers_es IS TRUE AND es_classrooms_instructional IS NULL)
      + COUNT_IF(offers_jhs IS TRUE AND jhs_classrooms_instructional IS NULL)
      + COUNT_IF(offers_shs IS TRUE AND shs_classrooms_instructional IS NULL) FROM source) AS offered_levels_without_rooms,
  (SELECT COUNT_IF((CAST(es_classrooms_instructional IS NOT NULL AS INT) + CAST(jhs_classrooms_instructional IS NOT NULL AS INT) + CAST(shs_classrooms_instructional IS NOT NULL AS INT)) BETWEEN 1 AND 2) FROM source) AS partially_reported_denominators;

INSERT INTO edu_access.`01-control`.data_quality_results (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, NULL, 'fact_school_classroom_capacity', 'gold', 'edu_access.05-gold.fact_school_classroom_capacity', check_name, status, expected, actual, current_timestamp(), :code_revision
FROM (
  SELECT 'rows_reconcile' AS check_name, CASE WHEN fact_rows = source_rows THEN 'PASS' ELSE 'FAIL' END AS status, CAST(source_rows AS STRING) AS expected, CAST(fact_rows AS STRING) AS actual FROM fact_school_classroom_capacity_gate_summary
  UNION ALL SELECT 'grain_unique', CASE WHEN duplicate_keys = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(duplicate_keys AS STRING) FROM fact_school_classroom_capacity_gate_summary
  UNION ALL SELECT 'key_not_null', CASE WHEN null_keys = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(null_keys AS STRING) FROM fact_school_classroom_capacity_gate_summary
  UNION ALL SELECT 'school_fk_resolves', CASE WHEN missing_school_keys = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(missing_school_keys AS STRING) FROM fact_school_classroom_capacity_gate_summary
  UNION ALL SELECT 'school_year_fk_resolves', CASE WHEN missing_school_year_keys = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(missing_school_year_keys AS STRING) FROM fact_school_classroom_capacity_gate_summary
  UNION ALL SELECT 'derived_values_reconcile', CASE WHEN wrong_derived_values = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(wrong_derived_values AS STRING) FROM fact_school_classroom_capacity_gate_summary
  UNION ALL SELECT 'enrollment_join_adds_no_rows', CASE WHEN enrollment_join_rows = fact_rows THEN 'PASS' ELSE 'FAIL' END, CAST(fact_rows AS STRING), CAST(enrollment_join_rows AS STRING) FROM fact_school_classroom_capacity_gate_summary
  UNION ALL SELECT 'every_capacity_school_has_enrollment', CASE WHEN missing_enrollment_rows = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(missing_enrollment_rows AS STRING) FROM fact_school_classroom_capacity_gate_summary
  UNION ALL SELECT 'measures_nonnegative', CASE WHEN negative_measures = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(negative_measures AS STRING) FROM fact_school_classroom_capacity_gate_summary
  UNION ALL SELECT 'zero_room_denominators', CASE WHEN zero_denominators = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(zero_denominators AS STRING) FROM fact_school_classroom_capacity_gate_summary
  UNION ALL SELECT 'offered_levels_without_room_data', CASE WHEN offered_levels_without_rooms = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(offered_levels_without_rooms AS STRING) FROM fact_school_classroom_capacity_gate_summary
  UNION ALL SELECT 'partial_room_reporting', CASE WHEN partially_reported_denominators = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(partially_reported_denominators AS STRING) FROM fact_school_classroom_capacity_gate_summary
) AS results;

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Gold gate failed for fact_school_classroom_capacity: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s)') END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'fact_school_classroom_capacity' AND layer = 'gold' AND status = 'FAIL' AND checked_at_utc >= session.gold_gate_started_at_utc;

CREATE OR REPLACE TABLE edu_access.`05-gold`.fact_school_classroom_capacity USING DELTA AS
SELECT * FROM edu_access.`05-gold`.fact_school_classroom_capacity_candidate;

ALTER TABLE edu_access.`05-gold`.fact_school_classroom_capacity OWNER TO `reached-hq`;
