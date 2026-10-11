-- Silver gate for deped_facilities. Generated from config/ingestion/deped_facilities.json
-- and config/mappings/deped_facilities.json:
--   python -m src.silver.cli gate --source deped_facilities > etl/03_silver/90_validate_deped_facilities_clean.sql
-- Do not edit by hand; tests/test_silver.py fails if it differs.
--
-- The job task after the Silver build. It checks the candidate tables the build wrote, one row
-- per check in data_quality_results. On any FAIL it records the run 'failed' and stops the task
-- before publishing, so the Silver tables keep the last build that passed and nothing downstream runs.
-- Otherwise it copies the candidates to the Silver tables and records the run 'succeeded'.
-- PASS: as expected. WARN: recorded, the build is published (quarantined rows, or a scope change).
-- FAIL: the candidate cannot be trusted and is not published. Results hold counts, never row values.
--
-- Parameters, supplied by the job (or src/job/local_run.py):
--   :run_id         the job run that built the tables
--   :code_revision  the commit that ran, from the job parameter; never a literal

-- Only this execution's results decide: a repaired job run keeps its run_id, and the
-- results of an earlier attempt must not fail it again.
DECLARE OR REPLACE VARIABLE silver_gate_started_at_utc TIMESTAMP;
SET VARIABLE silver_gate_started_at_utc = current_timestamp();

INSERT INTO edu_access.`01-control`.data_quality_results
  (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, batch_id, 'deped_facilities', 'silver', table_name, check_name, status, expected, actual,
       current_timestamp(), :code_revision
FROM (
WITH cur AS (
  SELECT batch_id, school_year FROM edu_access.`01-control`.current_batches WHERE source_id = 'deped_facilities'
),
bronze AS (
  SELECT r.* FROM edu_access.`02-bronze`.deped_facilities_raw AS r JOIN cur ON r.batch_id = cur.batch_id
),
clean AS (SELECT * FROM edu_access.`03-silver`.deped_facilities_clean_candidate),
quarantined AS (SELECT * FROM edu_access.`03-silver`.deped_facilities_quarantine_candidate),
-- Current Bronze rows, each marked if Silver set it aside.
b AS (
  SELECT bronze.*, q.source_row_number IS NOT NULL AS in_quarantine
  FROM bronze
  LEFT JOIN quarantined AS q
    ON bronze.source_sha256 = q.source_sha256 AND bronze.source_row_number = q.source_row_number
),
-- A quarantined row has no clean value, so its labels are checked against the reviewed mapping here:
-- a row set aside for another reason must not let an unmapped label through.
bronze_years AS (
  SELECT
    b.school_year,
    COUNT(*) AS bronze_rows,
    SUM(CASE WHEN b.in_quarantine THEN 0 ELSE
        COALESCE(CASE WHEN regexp_like(b.`es_classrooms_instructional`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`es_classrooms_instructional` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`jhs_classrooms_instructional`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`jhs_classrooms_instructional` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`shs_classrooms_instructional`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`shs_classrooms_instructional` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`es_classrooms_non_instructional`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`es_classrooms_non_instructional` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`jhs_classrooms_non_instructional`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`jhs_classrooms_non_instructional` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`shs_classrooms_non_instructional`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`shs_classrooms_non_instructional` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`buildings_good_condition`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`buildings_good_condition` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`buildings_needs_minor_repair`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`buildings_needs_minor_repair` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`buildings_needs_major_repair`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`buildings_needs_major_repair` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`buildings_for_completion`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`buildings_for_completion` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`buildings_ongoing_construction`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`buildings_ongoing_construction` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`buildings_for_condemnation`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`buildings_for_condemnation` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`buildings_for_demolition`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`buildings_for_demolition` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`es_temporary_learning_spaces`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`es_temporary_learning_spaces` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`hs_temporary_learning_spaces`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`hs_temporary_learning_spaces` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`es_classes_using_temporary_learning_spaces`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`es_classes_using_temporary_learning_spaces` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`hs_classes_using_temporary_learning_spaces`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`hs_classes_using_temporary_learning_spaces` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`es_makeshift_rooms`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`es_makeshift_rooms` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`hs_makeshift_rooms`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`hs_makeshift_rooms` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`es_classes_using_makeshift_rooms`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`es_classes_using_makeshift_rooms` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`hs_classes_using_makeshift_rooms`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`hs_classes_using_makeshift_rooms` AS BIGINT) END, 0)
      END) AS kept_counts,
    SUM(CASE WHEN b.in_quarantine THEN 0 ELSE
        CASE WHEN b.`es_classrooms_instructional` IS NULL OR b.`es_classrooms_instructional` = '' THEN 1 ELSE 0 END + CASE WHEN b.`jhs_classrooms_instructional` IS NULL OR b.`jhs_classrooms_instructional` = '' THEN 1 ELSE 0 END + CASE WHEN b.`shs_classrooms_instructional` IS NULL OR b.`shs_classrooms_instructional` = '' THEN 1 ELSE 0 END + CASE WHEN b.`es_classrooms_non_instructional` IS NULL OR b.`es_classrooms_non_instructional` = '' THEN 1 ELSE 0 END + CASE WHEN b.`jhs_classrooms_non_instructional` IS NULL OR b.`jhs_classrooms_non_instructional` = '' THEN 1 ELSE 0 END + CASE WHEN b.`shs_classrooms_non_instructional` IS NULL OR b.`shs_classrooms_non_instructional` = '' THEN 1 ELSE 0 END + CASE WHEN b.`buildings_good_condition` IS NULL OR b.`buildings_good_condition` = '' THEN 1 ELSE 0 END + CASE WHEN b.`buildings_needs_minor_repair` IS NULL OR b.`buildings_needs_minor_repair` = '' THEN 1 ELSE 0 END + CASE WHEN b.`buildings_needs_major_repair` IS NULL OR b.`buildings_needs_major_repair` = '' THEN 1 ELSE 0 END + CASE WHEN b.`buildings_for_completion` IS NULL OR b.`buildings_for_completion` = '' THEN 1 ELSE 0 END + CASE WHEN b.`buildings_ongoing_construction` IS NULL OR b.`buildings_ongoing_construction` = '' THEN 1 ELSE 0 END + CASE WHEN b.`buildings_for_condemnation` IS NULL OR b.`buildings_for_condemnation` = '' THEN 1 ELSE 0 END + CASE WHEN b.`buildings_for_demolition` IS NULL OR b.`buildings_for_demolition` = '' THEN 1 ELSE 0 END + CASE WHEN b.`es_temporary_learning_spaces` IS NULL OR b.`es_temporary_learning_spaces` = '' THEN 1 ELSE 0 END + CASE WHEN b.`hs_temporary_learning_spaces` IS NULL OR b.`hs_temporary_learning_spaces` = '' THEN 1 ELSE 0 END + CASE WHEN b.`es_classes_using_temporary_learning_spaces` IS NULL OR b.`es_classes_using_temporary_learning_spaces` = '' THEN 1 ELSE 0 END + CASE WHEN b.`hs_classes_using_temporary_learning_spaces` IS NULL OR b.`hs_classes_using_temporary_learning_spaces` = '' THEN 1 ELSE 0 END + CASE WHEN b.`es_makeshift_rooms` IS NULL OR b.`es_makeshift_rooms` = '' THEN 1 ELSE 0 END + CASE WHEN b.`hs_makeshift_rooms` IS NULL OR b.`hs_makeshift_rooms` = '' THEN 1 ELSE 0 END + CASE WHEN b.`es_classes_using_makeshift_rooms` IS NULL OR b.`es_classes_using_makeshift_rooms` = '' THEN 1 ELSE 0 END + CASE WHEN b.`hs_classes_using_makeshift_rooms` IS NULL OR b.`hs_classes_using_makeshift_rooms` = '' THEN 1 ELSE 0 END
      END) AS kept_missing_counts,
    SUM(CASE WHEN b.in_quarantine THEN 0 ELSE
        CASE WHEN TRIM(regexp_replace(translate(b.`offers_es`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`offers_jhs`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`offers_shs`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`es_has_covered_court`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`hs_has_covered_court`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`es_has_gymnasium`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`hs_has_gymnasium`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`es_has_gate_entrance`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`hs_has_gate_entrance`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`es_has_gate_exit`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`hs_has_gate_exit`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`es_has_perimeter_fence_permanent`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`hs_has_perimeter_fence_permanent`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`es_has_flood_marker`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`hs_has_flood_marker`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`es_has_perimeter_fence_temporary`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`hs_has_perimeter_fence_temporary`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`es_has_playground`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`hs_has_playground`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`es_has_garden`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`hs_has_garden`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`es_has_solar_panel`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`hs_has_solar_panel`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`es_has_bike_rack`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`hs_has_bike_rack`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`es_has_paved_pathway`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`hs_has_paved_pathway`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`es_has_pathway_roofing`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`hs_has_pathway_roofing`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`es_has_road_paved`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`hs_has_road_paved`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`es_has_road_unpaved`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`hs_has_road_unpaved`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`es_has_road_levelled`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`hs_has_road_levelled`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`es_has_road_rough`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`hs_has_road_rough`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`es_has_road_under_construction`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`hs_has_road_under_construction`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`es_accessible_private_4wheel`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`hs_accessible_private_4wheel`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`es_accessible_private_motorcycle`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`hs_accessible_private_motorcycle`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`es_accessible_boat`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`hs_accessible_boat`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`es_accessible_uv_express`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`hs_accessible_uv_express`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`es_accessible_pedicab`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`hs_accessible_pedicab`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`es_accessible_tricycle`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`hs_accessible_tricycle`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`es_accessible_jeepney`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`hs_accessible_jeepney`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`es_accessible_habalhabal`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`hs_accessible_habalhabal`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`es_accessible_train`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`hs_accessible_train`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`es_accessible_bus`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`hs_accessible_bus`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`es_accessible_bicycle`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`hs_accessible_bicycle`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`es_accessible_walking_hiking`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END + CASE WHEN TRIM(regexp_replace(translate(b.`hs_accessible_walking_hiking`, chr(9) || chr(160), '  '), ' +', ' ')) IN ('True') THEN 1 ELSE 0 END
      END) AS kept_true_values,
    SUM(CASE WHEN b.in_quarantine THEN 0 ELSE
        CASE WHEN b.`offers_es` IS NULL OR TRIM(regexp_replace(translate(b.`offers_es`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`offers_jhs` IS NULL OR TRIM(regexp_replace(translate(b.`offers_jhs`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`offers_shs` IS NULL OR TRIM(regexp_replace(translate(b.`offers_shs`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`es_has_covered_court` IS NULL OR TRIM(regexp_replace(translate(b.`es_has_covered_court`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`hs_has_covered_court` IS NULL OR TRIM(regexp_replace(translate(b.`hs_has_covered_court`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`es_has_gymnasium` IS NULL OR TRIM(regexp_replace(translate(b.`es_has_gymnasium`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`hs_has_gymnasium` IS NULL OR TRIM(regexp_replace(translate(b.`hs_has_gymnasium`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`es_has_gate_entrance` IS NULL OR TRIM(regexp_replace(translate(b.`es_has_gate_entrance`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`hs_has_gate_entrance` IS NULL OR TRIM(regexp_replace(translate(b.`hs_has_gate_entrance`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`es_has_gate_exit` IS NULL OR TRIM(regexp_replace(translate(b.`es_has_gate_exit`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`hs_has_gate_exit` IS NULL OR TRIM(regexp_replace(translate(b.`hs_has_gate_exit`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`es_has_perimeter_fence_permanent` IS NULL OR TRIM(regexp_replace(translate(b.`es_has_perimeter_fence_permanent`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`hs_has_perimeter_fence_permanent` IS NULL OR TRIM(regexp_replace(translate(b.`hs_has_perimeter_fence_permanent`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`es_has_flood_marker` IS NULL OR TRIM(regexp_replace(translate(b.`es_has_flood_marker`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`hs_has_flood_marker` IS NULL OR TRIM(regexp_replace(translate(b.`hs_has_flood_marker`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`es_has_perimeter_fence_temporary` IS NULL OR TRIM(regexp_replace(translate(b.`es_has_perimeter_fence_temporary`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`hs_has_perimeter_fence_temporary` IS NULL OR TRIM(regexp_replace(translate(b.`hs_has_perimeter_fence_temporary`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`es_has_playground` IS NULL OR TRIM(regexp_replace(translate(b.`es_has_playground`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`hs_has_playground` IS NULL OR TRIM(regexp_replace(translate(b.`hs_has_playground`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`es_has_garden` IS NULL OR TRIM(regexp_replace(translate(b.`es_has_garden`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`hs_has_garden` IS NULL OR TRIM(regexp_replace(translate(b.`hs_has_garden`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`es_has_solar_panel` IS NULL OR TRIM(regexp_replace(translate(b.`es_has_solar_panel`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`hs_has_solar_panel` IS NULL OR TRIM(regexp_replace(translate(b.`hs_has_solar_panel`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`es_has_bike_rack` IS NULL OR TRIM(regexp_replace(translate(b.`es_has_bike_rack`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`hs_has_bike_rack` IS NULL OR TRIM(regexp_replace(translate(b.`hs_has_bike_rack`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`es_has_paved_pathway` IS NULL OR TRIM(regexp_replace(translate(b.`es_has_paved_pathway`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`hs_has_paved_pathway` IS NULL OR TRIM(regexp_replace(translate(b.`hs_has_paved_pathway`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`es_has_pathway_roofing` IS NULL OR TRIM(regexp_replace(translate(b.`es_has_pathway_roofing`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`hs_has_pathway_roofing` IS NULL OR TRIM(regexp_replace(translate(b.`hs_has_pathway_roofing`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`es_has_road_paved` IS NULL OR TRIM(regexp_replace(translate(b.`es_has_road_paved`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`hs_has_road_paved` IS NULL OR TRIM(regexp_replace(translate(b.`hs_has_road_paved`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`es_has_road_unpaved` IS NULL OR TRIM(regexp_replace(translate(b.`es_has_road_unpaved`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`hs_has_road_unpaved` IS NULL OR TRIM(regexp_replace(translate(b.`hs_has_road_unpaved`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`es_has_road_levelled` IS NULL OR TRIM(regexp_replace(translate(b.`es_has_road_levelled`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`hs_has_road_levelled` IS NULL OR TRIM(regexp_replace(translate(b.`hs_has_road_levelled`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`es_has_road_rough` IS NULL OR TRIM(regexp_replace(translate(b.`es_has_road_rough`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`hs_has_road_rough` IS NULL OR TRIM(regexp_replace(translate(b.`hs_has_road_rough`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`es_has_road_under_construction` IS NULL OR TRIM(regexp_replace(translate(b.`es_has_road_under_construction`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`hs_has_road_under_construction` IS NULL OR TRIM(regexp_replace(translate(b.`hs_has_road_under_construction`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`es_accessible_private_4wheel` IS NULL OR TRIM(regexp_replace(translate(b.`es_accessible_private_4wheel`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`hs_accessible_private_4wheel` IS NULL OR TRIM(regexp_replace(translate(b.`hs_accessible_private_4wheel`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`es_accessible_private_motorcycle` IS NULL OR TRIM(regexp_replace(translate(b.`es_accessible_private_motorcycle`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`hs_accessible_private_motorcycle` IS NULL OR TRIM(regexp_replace(translate(b.`hs_accessible_private_motorcycle`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`es_accessible_boat` IS NULL OR TRIM(regexp_replace(translate(b.`es_accessible_boat`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`hs_accessible_boat` IS NULL OR TRIM(regexp_replace(translate(b.`hs_accessible_boat`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`es_accessible_uv_express` IS NULL OR TRIM(regexp_replace(translate(b.`es_accessible_uv_express`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`hs_accessible_uv_express` IS NULL OR TRIM(regexp_replace(translate(b.`hs_accessible_uv_express`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`es_accessible_pedicab` IS NULL OR TRIM(regexp_replace(translate(b.`es_accessible_pedicab`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`hs_accessible_pedicab` IS NULL OR TRIM(regexp_replace(translate(b.`hs_accessible_pedicab`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`es_accessible_tricycle` IS NULL OR TRIM(regexp_replace(translate(b.`es_accessible_tricycle`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`hs_accessible_tricycle` IS NULL OR TRIM(regexp_replace(translate(b.`hs_accessible_tricycle`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`es_accessible_jeepney` IS NULL OR TRIM(regexp_replace(translate(b.`es_accessible_jeepney`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`hs_accessible_jeepney` IS NULL OR TRIM(regexp_replace(translate(b.`hs_accessible_jeepney`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`es_accessible_habalhabal` IS NULL OR TRIM(regexp_replace(translate(b.`es_accessible_habalhabal`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`hs_accessible_habalhabal` IS NULL OR TRIM(regexp_replace(translate(b.`hs_accessible_habalhabal`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`es_accessible_train` IS NULL OR TRIM(regexp_replace(translate(b.`es_accessible_train`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`hs_accessible_train` IS NULL OR TRIM(regexp_replace(translate(b.`hs_accessible_train`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`es_accessible_bus` IS NULL OR TRIM(regexp_replace(translate(b.`es_accessible_bus`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`hs_accessible_bus` IS NULL OR TRIM(regexp_replace(translate(b.`hs_accessible_bus`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`es_accessible_bicycle` IS NULL OR TRIM(regexp_replace(translate(b.`es_accessible_bicycle`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`hs_accessible_bicycle` IS NULL OR TRIM(regexp_replace(translate(b.`hs_accessible_bicycle`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`es_accessible_walking_hiking` IS NULL OR TRIM(regexp_replace(translate(b.`es_accessible_walking_hiking`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END + CASE WHEN b.`hs_accessible_walking_hiking` IS NULL OR TRIM(regexp_replace(translate(b.`hs_accessible_walking_hiking`, chr(9) || chr(160), '  '), ' +', ' ')) = '' THEN 1 ELSE 0 END
      END) AS kept_blank_booleans,
    COUNT_IF(
        TRIM(regexp_replace(translate(b.`sector`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`sector`
        OR TRIM(regexp_replace(translate(b.`school_management`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`school_management`
        OR TRIM(regexp_replace(translate(b.`offers_es`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`offers_es`
        OR TRIM(regexp_replace(translate(b.`offers_jhs`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`offers_jhs`
        OR TRIM(regexp_replace(translate(b.`offers_shs`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`offers_shs`
        OR TRIM(regexp_replace(translate(b.`es_has_covered_court`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`es_has_covered_court`
        OR TRIM(regexp_replace(translate(b.`hs_has_covered_court`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`hs_has_covered_court`
        OR TRIM(regexp_replace(translate(b.`es_has_gymnasium`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`es_has_gymnasium`
        OR TRIM(regexp_replace(translate(b.`hs_has_gymnasium`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`hs_has_gymnasium`
        OR TRIM(regexp_replace(translate(b.`es_has_gate_entrance`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`es_has_gate_entrance`
        OR TRIM(regexp_replace(translate(b.`hs_has_gate_entrance`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`hs_has_gate_entrance`
        OR TRIM(regexp_replace(translate(b.`es_has_gate_exit`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`es_has_gate_exit`
        OR TRIM(regexp_replace(translate(b.`hs_has_gate_exit`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`hs_has_gate_exit`
        OR TRIM(regexp_replace(translate(b.`es_has_perimeter_fence_permanent`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`es_has_perimeter_fence_permanent`
        OR TRIM(regexp_replace(translate(b.`hs_has_perimeter_fence_permanent`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`hs_has_perimeter_fence_permanent`
        OR TRIM(regexp_replace(translate(b.`es_has_flood_marker`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`es_has_flood_marker`
        OR TRIM(regexp_replace(translate(b.`hs_has_flood_marker`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`hs_has_flood_marker`
        OR TRIM(regexp_replace(translate(b.`es_has_perimeter_fence_temporary`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`es_has_perimeter_fence_temporary`
        OR TRIM(regexp_replace(translate(b.`hs_has_perimeter_fence_temporary`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`hs_has_perimeter_fence_temporary`
        OR TRIM(regexp_replace(translate(b.`es_has_playground`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`es_has_playground`
        OR TRIM(regexp_replace(translate(b.`hs_has_playground`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`hs_has_playground`
        OR TRIM(regexp_replace(translate(b.`es_has_garden`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`es_has_garden`
        OR TRIM(regexp_replace(translate(b.`hs_has_garden`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`hs_has_garden`
        OR TRIM(regexp_replace(translate(b.`es_has_solar_panel`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`es_has_solar_panel`
        OR TRIM(regexp_replace(translate(b.`hs_has_solar_panel`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`hs_has_solar_panel`
        OR TRIM(regexp_replace(translate(b.`es_has_bike_rack`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`es_has_bike_rack`
        OR TRIM(regexp_replace(translate(b.`hs_has_bike_rack`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`hs_has_bike_rack`
        OR TRIM(regexp_replace(translate(b.`es_has_paved_pathway`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`es_has_paved_pathway`
        OR TRIM(regexp_replace(translate(b.`hs_has_paved_pathway`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`hs_has_paved_pathway`
        OR TRIM(regexp_replace(translate(b.`es_has_pathway_roofing`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`es_has_pathway_roofing`
        OR TRIM(regexp_replace(translate(b.`hs_has_pathway_roofing`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`hs_has_pathway_roofing`
        OR TRIM(regexp_replace(translate(b.`es_has_road_paved`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`es_has_road_paved`
        OR TRIM(regexp_replace(translate(b.`hs_has_road_paved`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`hs_has_road_paved`
        OR TRIM(regexp_replace(translate(b.`es_has_road_unpaved`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`es_has_road_unpaved`
        OR TRIM(regexp_replace(translate(b.`hs_has_road_unpaved`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`hs_has_road_unpaved`
        OR TRIM(regexp_replace(translate(b.`es_has_road_levelled`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`es_has_road_levelled`
        OR TRIM(regexp_replace(translate(b.`hs_has_road_levelled`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`hs_has_road_levelled`
        OR TRIM(regexp_replace(translate(b.`es_has_road_rough`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`es_has_road_rough`
        OR TRIM(regexp_replace(translate(b.`hs_has_road_rough`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`hs_has_road_rough`
        OR TRIM(regexp_replace(translate(b.`es_has_road_under_construction`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`es_has_road_under_construction`
        OR TRIM(regexp_replace(translate(b.`hs_has_road_under_construction`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`hs_has_road_under_construction`
        OR TRIM(regexp_replace(translate(b.`es_accessible_private_4wheel`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`es_accessible_private_4wheel`
        OR TRIM(regexp_replace(translate(b.`hs_accessible_private_4wheel`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`hs_accessible_private_4wheel`
        OR TRIM(regexp_replace(translate(b.`es_accessible_private_motorcycle`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`es_accessible_private_motorcycle`
        OR TRIM(regexp_replace(translate(b.`hs_accessible_private_motorcycle`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`hs_accessible_private_motorcycle`
        OR TRIM(regexp_replace(translate(b.`es_accessible_boat`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`es_accessible_boat`
        OR TRIM(regexp_replace(translate(b.`hs_accessible_boat`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`hs_accessible_boat`
        OR TRIM(regexp_replace(translate(b.`es_accessible_uv_express`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`es_accessible_uv_express`
        OR TRIM(regexp_replace(translate(b.`hs_accessible_uv_express`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`hs_accessible_uv_express`
        OR TRIM(regexp_replace(translate(b.`es_accessible_pedicab`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`es_accessible_pedicab`
        OR TRIM(regexp_replace(translate(b.`hs_accessible_pedicab`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`hs_accessible_pedicab`
        OR TRIM(regexp_replace(translate(b.`es_accessible_tricycle`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`es_accessible_tricycle`
        OR TRIM(regexp_replace(translate(b.`hs_accessible_tricycle`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`hs_accessible_tricycle`
        OR TRIM(regexp_replace(translate(b.`es_accessible_jeepney`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`es_accessible_jeepney`
        OR TRIM(regexp_replace(translate(b.`hs_accessible_jeepney`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`hs_accessible_jeepney`
        OR TRIM(regexp_replace(translate(b.`es_accessible_habalhabal`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`es_accessible_habalhabal`
        OR TRIM(regexp_replace(translate(b.`hs_accessible_habalhabal`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`hs_accessible_habalhabal`
        OR TRIM(regexp_replace(translate(b.`es_accessible_train`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`es_accessible_train`
        OR TRIM(regexp_replace(translate(b.`hs_accessible_train`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`hs_accessible_train`
        OR TRIM(regexp_replace(translate(b.`es_accessible_bus`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`es_accessible_bus`
        OR TRIM(regexp_replace(translate(b.`hs_accessible_bus`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`hs_accessible_bus`
        OR TRIM(regexp_replace(translate(b.`es_accessible_bicycle`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`es_accessible_bicycle`
        OR TRIM(regexp_replace(translate(b.`hs_accessible_bicycle`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`hs_accessible_bicycle`
        OR TRIM(regexp_replace(translate(b.`es_accessible_walking_hiking`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`es_accessible_walking_hiking`
        OR TRIM(regexp_replace(translate(b.`hs_accessible_walking_hiking`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`hs_accessible_walking_hiking`
      ) AS whitespace_rows,
    COUNT_IF(
        b.`es_classrooms_instructional` = ''
        OR b.`jhs_classrooms_instructional` = ''
        OR b.`shs_classrooms_instructional` = ''
        OR b.`es_classrooms_non_instructional` = ''
        OR b.`jhs_classrooms_non_instructional` = ''
        OR b.`shs_classrooms_non_instructional` = ''
        OR b.`buildings_good_condition` = ''
        OR b.`buildings_needs_minor_repair` = ''
        OR b.`buildings_needs_major_repair` = ''
        OR b.`buildings_for_completion` = ''
        OR b.`buildings_ongoing_construction` = ''
        OR b.`buildings_for_condemnation` = ''
        OR b.`buildings_for_demolition` = ''
        OR b.`es_temporary_learning_spaces` = ''
        OR b.`hs_temporary_learning_spaces` = ''
        OR b.`es_classes_using_temporary_learning_spaces` = ''
        OR b.`hs_classes_using_temporary_learning_spaces` = ''
        OR b.`es_makeshift_rooms` = ''
        OR b.`hs_makeshift_rooms` = ''
        OR b.`es_classes_using_makeshift_rooms` = ''
        OR b.`hs_classes_using_makeshift_rooms` = ''
      ) AS blank_count_rows,
    COUNT_IF(
        b.`offers_es` = ''
        OR b.`offers_jhs` = ''
        OR b.`offers_shs` = ''
        OR b.`es_has_covered_court` = ''
        OR b.`hs_has_covered_court` = ''
        OR b.`es_has_gymnasium` = ''
        OR b.`hs_has_gymnasium` = ''
        OR b.`es_has_gate_entrance` = ''
        OR b.`hs_has_gate_entrance` = ''
        OR b.`es_has_gate_exit` = ''
        OR b.`hs_has_gate_exit` = ''
        OR b.`es_has_perimeter_fence_permanent` = ''
        OR b.`hs_has_perimeter_fence_permanent` = ''
        OR b.`es_has_flood_marker` = ''
        OR b.`hs_has_flood_marker` = ''
        OR b.`es_has_perimeter_fence_temporary` = ''
        OR b.`hs_has_perimeter_fence_temporary` = ''
        OR b.`es_has_playground` = ''
        OR b.`hs_has_playground` = ''
        OR b.`es_has_garden` = ''
        OR b.`hs_has_garden` = ''
        OR b.`es_has_solar_panel` = ''
        OR b.`hs_has_solar_panel` = ''
        OR b.`es_has_bike_rack` = ''
        OR b.`hs_has_bike_rack` = ''
        OR b.`es_has_paved_pathway` = ''
        OR b.`hs_has_paved_pathway` = ''
        OR b.`es_has_pathway_roofing` = ''
        OR b.`hs_has_pathway_roofing` = ''
        OR b.`es_has_road_paved` = ''
        OR b.`hs_has_road_paved` = ''
        OR b.`es_has_road_unpaved` = ''
        OR b.`hs_has_road_unpaved` = ''
        OR b.`es_has_road_levelled` = ''
        OR b.`hs_has_road_levelled` = ''
        OR b.`es_has_road_rough` = ''
        OR b.`hs_has_road_rough` = ''
        OR b.`es_has_road_under_construction` = ''
        OR b.`hs_has_road_under_construction` = ''
        OR b.`es_accessible_private_4wheel` = ''
        OR b.`hs_accessible_private_4wheel` = ''
        OR b.`es_accessible_private_motorcycle` = ''
        OR b.`hs_accessible_private_motorcycle` = ''
        OR b.`es_accessible_boat` = ''
        OR b.`hs_accessible_boat` = ''
        OR b.`es_accessible_uv_express` = ''
        OR b.`hs_accessible_uv_express` = ''
        OR b.`es_accessible_pedicab` = ''
        OR b.`hs_accessible_pedicab` = ''
        OR b.`es_accessible_tricycle` = ''
        OR b.`hs_accessible_tricycle` = ''
        OR b.`es_accessible_jeepney` = ''
        OR b.`hs_accessible_jeepney` = ''
        OR b.`es_accessible_habalhabal` = ''
        OR b.`hs_accessible_habalhabal` = ''
        OR b.`es_accessible_train` = ''
        OR b.`hs_accessible_train` = ''
        OR b.`es_accessible_bus` = ''
        OR b.`hs_accessible_bus` = ''
        OR b.`es_accessible_bicycle` = ''
        OR b.`hs_accessible_bicycle` = ''
        OR b.`es_accessible_walking_hiking` = ''
        OR b.`hs_accessible_walking_hiking` = ''
      ) AS blank_boolean_rows,
    COUNT_IF(b.in_quarantine AND (TRIM(regexp_replace(translate(b.`sector`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`sector`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('Public', 'Private', 'SUC/LUC', 'PSO'))) AS quarantined_unmapped_sector,
    COUNT_IF(b.in_quarantine AND (TRIM(regexp_replace(translate(b.`school_management`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`school_management`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('DepEd', 'Non-Sectarian', 'Sectarian', 'SUC', 'LUC', 'DOST', 'Other GA', 'International School', 'PSO'))) AS quarantined_unmapped_school_management,
    COUNT_IF(b.in_quarantine AND (TRIM(regexp_replace(translate(b.`offers_es`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`offers_es`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))) AS quarantined_unmapped_offers_es,
    COUNT_IF(b.in_quarantine AND (TRIM(regexp_replace(translate(b.`offers_jhs`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`offers_jhs`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))) AS quarantined_unmapped_offers_jhs,
    COUNT_IF(b.in_quarantine AND (TRIM(regexp_replace(translate(b.`offers_shs`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`offers_shs`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))) AS quarantined_unmapped_offers_shs,
    COUNT_IF(b.in_quarantine AND (
        (TRIM(regexp_replace(translate(b.`es_has_covered_court`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`es_has_covered_court`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`hs_has_covered_court`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`hs_has_covered_court`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`es_has_gymnasium`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`es_has_gymnasium`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`hs_has_gymnasium`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`hs_has_gymnasium`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`es_has_gate_entrance`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`es_has_gate_entrance`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`hs_has_gate_entrance`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`hs_has_gate_entrance`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`es_has_gate_exit`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`es_has_gate_exit`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`hs_has_gate_exit`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`hs_has_gate_exit`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`es_has_perimeter_fence_permanent`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`es_has_perimeter_fence_permanent`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`hs_has_perimeter_fence_permanent`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`hs_has_perimeter_fence_permanent`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`es_has_flood_marker`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`es_has_flood_marker`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`hs_has_flood_marker`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`hs_has_flood_marker`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`es_has_perimeter_fence_temporary`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`es_has_perimeter_fence_temporary`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`hs_has_perimeter_fence_temporary`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`hs_has_perimeter_fence_temporary`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`es_has_playground`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`es_has_playground`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`hs_has_playground`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`hs_has_playground`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`es_has_garden`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`es_has_garden`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`hs_has_garden`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`hs_has_garden`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`es_has_solar_panel`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`es_has_solar_panel`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`hs_has_solar_panel`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`hs_has_solar_panel`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`es_has_bike_rack`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`es_has_bike_rack`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`hs_has_bike_rack`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`hs_has_bike_rack`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`es_has_paved_pathway`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`es_has_paved_pathway`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`hs_has_paved_pathway`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`hs_has_paved_pathway`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`es_has_pathway_roofing`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`es_has_pathway_roofing`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`hs_has_pathway_roofing`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`hs_has_pathway_roofing`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`es_has_road_paved`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`es_has_road_paved`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`hs_has_road_paved`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`hs_has_road_paved`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`es_has_road_unpaved`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`es_has_road_unpaved`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`hs_has_road_unpaved`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`hs_has_road_unpaved`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`es_has_road_levelled`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`es_has_road_levelled`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`hs_has_road_levelled`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`hs_has_road_levelled`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`es_has_road_rough`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`es_has_road_rough`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`hs_has_road_rough`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`hs_has_road_rough`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`es_has_road_under_construction`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`es_has_road_under_construction`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`hs_has_road_under_construction`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`hs_has_road_under_construction`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`es_accessible_private_4wheel`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`es_accessible_private_4wheel`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`hs_accessible_private_4wheel`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`hs_accessible_private_4wheel`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`es_accessible_private_motorcycle`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`es_accessible_private_motorcycle`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`hs_accessible_private_motorcycle`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`hs_accessible_private_motorcycle`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`es_accessible_boat`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`es_accessible_boat`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`hs_accessible_boat`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`hs_accessible_boat`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`es_accessible_uv_express`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`es_accessible_uv_express`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`hs_accessible_uv_express`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`hs_accessible_uv_express`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`es_accessible_pedicab`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`es_accessible_pedicab`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`hs_accessible_pedicab`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`hs_accessible_pedicab`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`es_accessible_tricycle`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`es_accessible_tricycle`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`hs_accessible_tricycle`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`hs_accessible_tricycle`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`es_accessible_jeepney`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`es_accessible_jeepney`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`hs_accessible_jeepney`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`hs_accessible_jeepney`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`es_accessible_habalhabal`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`es_accessible_habalhabal`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`hs_accessible_habalhabal`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`hs_accessible_habalhabal`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`es_accessible_train`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`es_accessible_train`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`hs_accessible_train`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`hs_accessible_train`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`es_accessible_bus`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`es_accessible_bus`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`hs_accessible_bus`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`hs_accessible_bus`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`es_accessible_bicycle`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`es_accessible_bicycle`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`hs_accessible_bicycle`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`hs_accessible_bicycle`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`es_accessible_walking_hiking`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`es_accessible_walking_hiking`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
        OR (TRIM(regexp_replace(translate(b.`hs_accessible_walking_hiking`, chr(9) || chr(160), '  '), ' +', ' ')) <> '' AND TRIM(regexp_replace(translate(b.`hs_accessible_walking_hiking`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'False'))
      )) AS quarantined_unmapped_facility_booleans
  FROM b GROUP BY b.school_year
),
clean_years AS (
  SELECT
    c.school_year,
    COUNT(*) AS clean_rows,
    COUNT(DISTINCT c.school_id) AS clean_ids,
    COUNT_IF(c.school_id IS NULL OR NOT regexp_like(c.school_id, '^[0-9]{6}$')) AS invalid_ids,
    COUNT_IF(
        c.es_classrooms_instructional < 0
        OR c.jhs_classrooms_instructional < 0
        OR c.shs_classrooms_instructional < 0
        OR c.es_classrooms_non_instructional < 0
        OR c.jhs_classrooms_non_instructional < 0
        OR c.shs_classrooms_non_instructional < 0
        OR c.buildings_good_condition < 0
        OR c.buildings_needs_minor_repair < 0
        OR c.buildings_needs_major_repair < 0
        OR c.buildings_for_completion < 0
        OR c.buildings_ongoing_construction < 0
        OR c.buildings_for_condemnation < 0
        OR c.buildings_for_demolition < 0
        OR c.es_temporary_learning_spaces < 0
        OR c.hs_temporary_learning_spaces < 0
        OR c.es_classes_using_temporary_learning_spaces < 0
        OR c.hs_classes_using_temporary_learning_spaces < 0
        OR c.es_makeshift_rooms < 0
        OR c.hs_makeshift_rooms < 0
        OR c.es_classes_using_makeshift_rooms < 0
        OR c.hs_classes_using_makeshift_rooms < 0
      ) AS negative_rows,
    COUNT_IF(
        c.es_classrooms_instructional > 1000
        OR c.jhs_classrooms_instructional > 1000
        OR c.shs_classrooms_instructional > 1000
        OR c.es_classrooms_non_instructional > 1000
        OR c.jhs_classrooms_non_instructional > 1000
        OR c.shs_classrooms_non_instructional > 1000
        OR c.buildings_good_condition > 200
        OR c.buildings_needs_minor_repair > 200
        OR c.buildings_needs_major_repair > 200
        OR c.buildings_for_completion > 200
        OR c.buildings_ongoing_construction > 200
        OR c.buildings_for_condemnation > 200
        OR c.buildings_for_demolition > 200
        OR c.es_temporary_learning_spaces > 1000
        OR c.hs_temporary_learning_spaces > 1000
        OR c.es_classes_using_temporary_learning_spaces > 1000
        OR c.hs_classes_using_temporary_learning_spaces > 1000
        OR c.es_makeshift_rooms > 1000
        OR c.hs_makeshift_rooms > 1000
        OR c.es_classes_using_makeshift_rooms > 1000
        OR c.hs_classes_using_makeshift_rooms > 1000
      ) AS implausible_rows,
    SUM(
        COALESCE(CAST(c.es_classrooms_instructional AS BIGINT), 0) + COALESCE(CAST(c.jhs_classrooms_instructional AS BIGINT), 0) + COALESCE(CAST(c.shs_classrooms_instructional AS BIGINT), 0) + COALESCE(CAST(c.es_classrooms_non_instructional AS BIGINT), 0) + COALESCE(CAST(c.jhs_classrooms_non_instructional AS BIGINT), 0) + COALESCE(CAST(c.shs_classrooms_non_instructional AS BIGINT), 0) + COALESCE(CAST(c.buildings_good_condition AS BIGINT), 0) + COALESCE(CAST(c.buildings_needs_minor_repair AS BIGINT), 0) + COALESCE(CAST(c.buildings_needs_major_repair AS BIGINT), 0) + COALESCE(CAST(c.buildings_for_completion AS BIGINT), 0) + COALESCE(CAST(c.buildings_ongoing_construction AS BIGINT), 0) + COALESCE(CAST(c.buildings_for_condemnation AS BIGINT), 0) + COALESCE(CAST(c.buildings_for_demolition AS BIGINT), 0) + COALESCE(CAST(c.es_temporary_learning_spaces AS BIGINT), 0) + COALESCE(CAST(c.hs_temporary_learning_spaces AS BIGINT), 0) + COALESCE(CAST(c.es_classes_using_temporary_learning_spaces AS BIGINT), 0) + COALESCE(CAST(c.hs_classes_using_temporary_learning_spaces AS BIGINT), 0) + COALESCE(CAST(c.es_makeshift_rooms AS BIGINT), 0) + COALESCE(CAST(c.hs_makeshift_rooms AS BIGINT), 0) + COALESCE(CAST(c.es_classes_using_makeshift_rooms AS BIGINT), 0) + COALESCE(CAST(c.hs_classes_using_makeshift_rooms AS BIGINT), 0)
      ) AS clean_counts,
    SUM(
        CASE WHEN c.es_classrooms_instructional IS NULL THEN 1 ELSE 0 END + CASE WHEN c.jhs_classrooms_instructional IS NULL THEN 1 ELSE 0 END + CASE WHEN c.shs_classrooms_instructional IS NULL THEN 1 ELSE 0 END + CASE WHEN c.es_classrooms_non_instructional IS NULL THEN 1 ELSE 0 END + CASE WHEN c.jhs_classrooms_non_instructional IS NULL THEN 1 ELSE 0 END + CASE WHEN c.shs_classrooms_non_instructional IS NULL THEN 1 ELSE 0 END + CASE WHEN c.buildings_good_condition IS NULL THEN 1 ELSE 0 END + CASE WHEN c.buildings_needs_minor_repair IS NULL THEN 1 ELSE 0 END + CASE WHEN c.buildings_needs_major_repair IS NULL THEN 1 ELSE 0 END + CASE WHEN c.buildings_for_completion IS NULL THEN 1 ELSE 0 END + CASE WHEN c.buildings_ongoing_construction IS NULL THEN 1 ELSE 0 END + CASE WHEN c.buildings_for_condemnation IS NULL THEN 1 ELSE 0 END + CASE WHEN c.buildings_for_demolition IS NULL THEN 1 ELSE 0 END + CASE WHEN c.es_temporary_learning_spaces IS NULL THEN 1 ELSE 0 END + CASE WHEN c.hs_temporary_learning_spaces IS NULL THEN 1 ELSE 0 END + CASE WHEN c.es_classes_using_temporary_learning_spaces IS NULL THEN 1 ELSE 0 END + CASE WHEN c.hs_classes_using_temporary_learning_spaces IS NULL THEN 1 ELSE 0 END + CASE WHEN c.es_makeshift_rooms IS NULL THEN 1 ELSE 0 END + CASE WHEN c.hs_makeshift_rooms IS NULL THEN 1 ELSE 0 END + CASE WHEN c.es_classes_using_makeshift_rooms IS NULL THEN 1 ELSE 0 END + CASE WHEN c.hs_classes_using_makeshift_rooms IS NULL THEN 1 ELSE 0 END
      ) AS clean_missing_counts,
    SUM(
        CASE WHEN c.offers_es THEN 1 ELSE 0 END + CASE WHEN c.offers_jhs THEN 1 ELSE 0 END + CASE WHEN c.offers_shs THEN 1 ELSE 0 END + CASE WHEN c.es_has_covered_court THEN 1 ELSE 0 END + CASE WHEN c.hs_has_covered_court THEN 1 ELSE 0 END + CASE WHEN c.es_has_gymnasium THEN 1 ELSE 0 END + CASE WHEN c.hs_has_gymnasium THEN 1 ELSE 0 END + CASE WHEN c.es_has_gate_entrance THEN 1 ELSE 0 END + CASE WHEN c.hs_has_gate_entrance THEN 1 ELSE 0 END + CASE WHEN c.es_has_gate_exit THEN 1 ELSE 0 END + CASE WHEN c.hs_has_gate_exit THEN 1 ELSE 0 END + CASE WHEN c.es_has_perimeter_fence_permanent THEN 1 ELSE 0 END + CASE WHEN c.hs_has_perimeter_fence_permanent THEN 1 ELSE 0 END + CASE WHEN c.es_has_flood_marker THEN 1 ELSE 0 END + CASE WHEN c.hs_has_flood_marker THEN 1 ELSE 0 END + CASE WHEN c.es_has_perimeter_fence_temporary THEN 1 ELSE 0 END + CASE WHEN c.hs_has_perimeter_fence_temporary THEN 1 ELSE 0 END + CASE WHEN c.es_has_playground THEN 1 ELSE 0 END + CASE WHEN c.hs_has_playground THEN 1 ELSE 0 END + CASE WHEN c.es_has_garden THEN 1 ELSE 0 END + CASE WHEN c.hs_has_garden THEN 1 ELSE 0 END + CASE WHEN c.es_has_solar_panel THEN 1 ELSE 0 END + CASE WHEN c.hs_has_solar_panel THEN 1 ELSE 0 END + CASE WHEN c.es_has_bike_rack THEN 1 ELSE 0 END + CASE WHEN c.hs_has_bike_rack THEN 1 ELSE 0 END + CASE WHEN c.es_has_paved_pathway THEN 1 ELSE 0 END + CASE WHEN c.hs_has_paved_pathway THEN 1 ELSE 0 END + CASE WHEN c.es_has_pathway_roofing THEN 1 ELSE 0 END + CASE WHEN c.hs_has_pathway_roofing THEN 1 ELSE 0 END + CASE WHEN c.es_has_road_paved THEN 1 ELSE 0 END + CASE WHEN c.hs_has_road_paved THEN 1 ELSE 0 END + CASE WHEN c.es_has_road_unpaved THEN 1 ELSE 0 END + CASE WHEN c.hs_has_road_unpaved THEN 1 ELSE 0 END + CASE WHEN c.es_has_road_levelled THEN 1 ELSE 0 END + CASE WHEN c.hs_has_road_levelled THEN 1 ELSE 0 END + CASE WHEN c.es_has_road_rough THEN 1 ELSE 0 END + CASE WHEN c.hs_has_road_rough THEN 1 ELSE 0 END + CASE WHEN c.es_has_road_under_construction THEN 1 ELSE 0 END + CASE WHEN c.hs_has_road_under_construction THEN 1 ELSE 0 END + CASE WHEN c.es_accessible_private_4wheel THEN 1 ELSE 0 END + CASE WHEN c.hs_accessible_private_4wheel THEN 1 ELSE 0 END + CASE WHEN c.es_accessible_private_motorcycle THEN 1 ELSE 0 END + CASE WHEN c.hs_accessible_private_motorcycle THEN 1 ELSE 0 END + CASE WHEN c.es_accessible_boat THEN 1 ELSE 0 END + CASE WHEN c.hs_accessible_boat THEN 1 ELSE 0 END + CASE WHEN c.es_accessible_uv_express THEN 1 ELSE 0 END + CASE WHEN c.hs_accessible_uv_express THEN 1 ELSE 0 END + CASE WHEN c.es_accessible_pedicab THEN 1 ELSE 0 END + CASE WHEN c.hs_accessible_pedicab THEN 1 ELSE 0 END + CASE WHEN c.es_accessible_tricycle THEN 1 ELSE 0 END + CASE WHEN c.hs_accessible_tricycle THEN 1 ELSE 0 END + CASE WHEN c.es_accessible_jeepney THEN 1 ELSE 0 END + CASE WHEN c.hs_accessible_jeepney THEN 1 ELSE 0 END + CASE WHEN c.es_accessible_habalhabal THEN 1 ELSE 0 END + CASE WHEN c.hs_accessible_habalhabal THEN 1 ELSE 0 END + CASE WHEN c.es_accessible_train THEN 1 ELSE 0 END + CASE WHEN c.hs_accessible_train THEN 1 ELSE 0 END + CASE WHEN c.es_accessible_bus THEN 1 ELSE 0 END + CASE WHEN c.hs_accessible_bus THEN 1 ELSE 0 END + CASE WHEN c.es_accessible_bicycle THEN 1 ELSE 0 END + CASE WHEN c.hs_accessible_bicycle THEN 1 ELSE 0 END + CASE WHEN c.es_accessible_walking_hiking THEN 1 ELSE 0 END + CASE WHEN c.hs_accessible_walking_hiking THEN 1 ELSE 0 END
      ) AS clean_true_values,
    SUM(
        CASE WHEN c.offers_es IS NULL THEN 1 ELSE 0 END + CASE WHEN c.offers_jhs IS NULL THEN 1 ELSE 0 END + CASE WHEN c.offers_shs IS NULL THEN 1 ELSE 0 END + CASE WHEN c.es_has_covered_court IS NULL THEN 1 ELSE 0 END + CASE WHEN c.hs_has_covered_court IS NULL THEN 1 ELSE 0 END + CASE WHEN c.es_has_gymnasium IS NULL THEN 1 ELSE 0 END + CASE WHEN c.hs_has_gymnasium IS NULL THEN 1 ELSE 0 END + CASE WHEN c.es_has_gate_entrance IS NULL THEN 1 ELSE 0 END + CASE WHEN c.hs_has_gate_entrance IS NULL THEN 1 ELSE 0 END + CASE WHEN c.es_has_gate_exit IS NULL THEN 1 ELSE 0 END + CASE WHEN c.hs_has_gate_exit IS NULL THEN 1 ELSE 0 END + CASE WHEN c.es_has_perimeter_fence_permanent IS NULL THEN 1 ELSE 0 END + CASE WHEN c.hs_has_perimeter_fence_permanent IS NULL THEN 1 ELSE 0 END + CASE WHEN c.es_has_flood_marker IS NULL THEN 1 ELSE 0 END + CASE WHEN c.hs_has_flood_marker IS NULL THEN 1 ELSE 0 END + CASE WHEN c.es_has_perimeter_fence_temporary IS NULL THEN 1 ELSE 0 END + CASE WHEN c.hs_has_perimeter_fence_temporary IS NULL THEN 1 ELSE 0 END + CASE WHEN c.es_has_playground IS NULL THEN 1 ELSE 0 END + CASE WHEN c.hs_has_playground IS NULL THEN 1 ELSE 0 END + CASE WHEN c.es_has_garden IS NULL THEN 1 ELSE 0 END + CASE WHEN c.hs_has_garden IS NULL THEN 1 ELSE 0 END + CASE WHEN c.es_has_solar_panel IS NULL THEN 1 ELSE 0 END + CASE WHEN c.hs_has_solar_panel IS NULL THEN 1 ELSE 0 END + CASE WHEN c.es_has_bike_rack IS NULL THEN 1 ELSE 0 END + CASE WHEN c.hs_has_bike_rack IS NULL THEN 1 ELSE 0 END + CASE WHEN c.es_has_paved_pathway IS NULL THEN 1 ELSE 0 END + CASE WHEN c.hs_has_paved_pathway IS NULL THEN 1 ELSE 0 END + CASE WHEN c.es_has_pathway_roofing IS NULL THEN 1 ELSE 0 END + CASE WHEN c.hs_has_pathway_roofing IS NULL THEN 1 ELSE 0 END + CASE WHEN c.es_has_road_paved IS NULL THEN 1 ELSE 0 END + CASE WHEN c.hs_has_road_paved IS NULL THEN 1 ELSE 0 END + CASE WHEN c.es_has_road_unpaved IS NULL THEN 1 ELSE 0 END + CASE WHEN c.hs_has_road_unpaved IS NULL THEN 1 ELSE 0 END + CASE WHEN c.es_has_road_levelled IS NULL THEN 1 ELSE 0 END + CASE WHEN c.hs_has_road_levelled IS NULL THEN 1 ELSE 0 END + CASE WHEN c.es_has_road_rough IS NULL THEN 1 ELSE 0 END + CASE WHEN c.hs_has_road_rough IS NULL THEN 1 ELSE 0 END + CASE WHEN c.es_has_road_under_construction IS NULL THEN 1 ELSE 0 END + CASE WHEN c.hs_has_road_under_construction IS NULL THEN 1 ELSE 0 END + CASE WHEN c.es_accessible_private_4wheel IS NULL THEN 1 ELSE 0 END + CASE WHEN c.hs_accessible_private_4wheel IS NULL THEN 1 ELSE 0 END + CASE WHEN c.es_accessible_private_motorcycle IS NULL THEN 1 ELSE 0 END + CASE WHEN c.hs_accessible_private_motorcycle IS NULL THEN 1 ELSE 0 END + CASE WHEN c.es_accessible_boat IS NULL THEN 1 ELSE 0 END + CASE WHEN c.hs_accessible_boat IS NULL THEN 1 ELSE 0 END + CASE WHEN c.es_accessible_uv_express IS NULL THEN 1 ELSE 0 END + CASE WHEN c.hs_accessible_uv_express IS NULL THEN 1 ELSE 0 END + CASE WHEN c.es_accessible_pedicab IS NULL THEN 1 ELSE 0 END + CASE WHEN c.hs_accessible_pedicab IS NULL THEN 1 ELSE 0 END + CASE WHEN c.es_accessible_tricycle IS NULL THEN 1 ELSE 0 END + CASE WHEN c.hs_accessible_tricycle IS NULL THEN 1 ELSE 0 END + CASE WHEN c.es_accessible_jeepney IS NULL THEN 1 ELSE 0 END + CASE WHEN c.hs_accessible_jeepney IS NULL THEN 1 ELSE 0 END + CASE WHEN c.es_accessible_habalhabal IS NULL THEN 1 ELSE 0 END + CASE WHEN c.hs_accessible_habalhabal IS NULL THEN 1 ELSE 0 END + CASE WHEN c.es_accessible_train IS NULL THEN 1 ELSE 0 END + CASE WHEN c.hs_accessible_train IS NULL THEN 1 ELSE 0 END + CASE WHEN c.es_accessible_bus IS NULL THEN 1 ELSE 0 END + CASE WHEN c.hs_accessible_bus IS NULL THEN 1 ELSE 0 END + CASE WHEN c.es_accessible_bicycle IS NULL THEN 1 ELSE 0 END + CASE WHEN c.hs_accessible_bicycle IS NULL THEN 1 ELSE 0 END + CASE WHEN c.es_accessible_walking_hiking IS NULL THEN 1 ELSE 0 END + CASE WHEN c.hs_accessible_walking_hiking IS NULL THEN 1 ELSE 0 END
      ) AS clean_blank_booleans,
    COUNT_IF(c.sector IS DISTINCT FROM 'Public' AND c.has_facility_data) AS non_public_facility_rows,
    COUNT_IF(
        (COALESCE(c.offers_es, FALSE) = FALSE AND (c.es_classrooms_instructional IS NOT NULL OR c.es_classrooms_non_instructional IS NOT NULL OR c.es_temporary_learning_spaces IS NOT NULL OR c.es_classes_using_temporary_learning_spaces IS NOT NULL OR c.es_makeshift_rooms IS NOT NULL OR c.es_classes_using_makeshift_rooms IS NOT NULL OR c.es_has_covered_court IS NOT NULL OR c.es_has_gymnasium IS NOT NULL OR c.es_has_gate_entrance IS NOT NULL OR c.es_has_gate_exit IS NOT NULL OR c.es_has_perimeter_fence_permanent IS NOT NULL OR c.es_has_flood_marker IS NOT NULL OR c.es_has_perimeter_fence_temporary IS NOT NULL OR c.es_has_playground IS NOT NULL OR c.es_has_garden IS NOT NULL OR c.es_has_solar_panel IS NOT NULL OR c.es_has_bike_rack IS NOT NULL OR c.es_has_paved_pathway IS NOT NULL OR c.es_has_pathway_roofing IS NOT NULL OR c.es_has_road_paved IS NOT NULL OR c.es_has_road_unpaved IS NOT NULL OR c.es_has_road_levelled IS NOT NULL OR c.es_has_road_rough IS NOT NULL OR c.es_has_road_under_construction IS NOT NULL OR c.es_accessible_private_4wheel IS NOT NULL OR c.es_accessible_private_motorcycle IS NOT NULL OR c.es_accessible_boat IS NOT NULL OR c.es_accessible_uv_express IS NOT NULL OR c.es_accessible_pedicab IS NOT NULL OR c.es_accessible_tricycle IS NOT NULL OR c.es_accessible_jeepney IS NOT NULL OR c.es_accessible_habalhabal IS NOT NULL OR c.es_accessible_train IS NOT NULL OR c.es_accessible_bus IS NOT NULL OR c.es_accessible_bicycle IS NOT NULL OR c.es_accessible_walking_hiking IS NOT NULL))
        OR (COALESCE(c.offers_jhs, FALSE) = FALSE AND (c.jhs_classrooms_instructional IS NOT NULL OR c.jhs_classrooms_non_instructional IS NOT NULL))
        OR (COALESCE(c.offers_shs, FALSE) = FALSE AND (c.shs_classrooms_instructional IS NOT NULL OR c.shs_classrooms_non_instructional IS NOT NULL))
        OR (COALESCE(c.offers_jhs OR c.offers_shs, FALSE) = FALSE AND (c.hs_temporary_learning_spaces IS NOT NULL OR c.hs_classes_using_temporary_learning_spaces IS NOT NULL OR c.hs_makeshift_rooms IS NOT NULL OR c.hs_classes_using_makeshift_rooms IS NOT NULL OR c.hs_has_covered_court IS NOT NULL OR c.hs_has_gymnasium IS NOT NULL OR c.hs_has_gate_entrance IS NOT NULL OR c.hs_has_gate_exit IS NOT NULL OR c.hs_has_perimeter_fence_permanent IS NOT NULL OR c.hs_has_flood_marker IS NOT NULL OR c.hs_has_perimeter_fence_temporary IS NOT NULL OR c.hs_has_playground IS NOT NULL OR c.hs_has_garden IS NOT NULL OR c.hs_has_solar_panel IS NOT NULL OR c.hs_has_bike_rack IS NOT NULL OR c.hs_has_paved_pathway IS NOT NULL OR c.hs_has_pathway_roofing IS NOT NULL OR c.hs_has_road_paved IS NOT NULL OR c.hs_has_road_unpaved IS NOT NULL OR c.hs_has_road_levelled IS NOT NULL OR c.hs_has_road_rough IS NOT NULL OR c.hs_has_road_under_construction IS NOT NULL OR c.hs_accessible_private_4wheel IS NOT NULL OR c.hs_accessible_private_motorcycle IS NOT NULL OR c.hs_accessible_boat IS NOT NULL OR c.hs_accessible_uv_express IS NOT NULL OR c.hs_accessible_pedicab IS NOT NULL OR c.hs_accessible_tricycle IS NOT NULL OR c.hs_accessible_jeepney IS NOT NULL OR c.hs_accessible_habalhabal IS NOT NULL OR c.hs_accessible_train IS NOT NULL OR c.hs_accessible_bus IS NOT NULL OR c.hs_accessible_bicycle IS NOT NULL OR c.hs_accessible_walking_hiking IS NOT NULL))
      ) AS outside_level_rows,
    COUNT_IF(c.is_overseas) AS overseas_rows,
    COUNT_IF(c.has_facility_data) AS facility_data_rows,
    COUNT_IF(c.sector = 'Public' AND NOT c.has_facility_data) AS public_without_data_rows,
    COUNT_IF(c.es_classrooms_missing) AS classrooms_missing_rows
  FROM clean AS c GROUP BY c.school_year
),
-- Each clean row beside its Bronze row: is every published label mapped?
matched_years AS (
  SELECT
    c.school_year,
    COUNT_IF(c.sector IS NULL AND TRIM(regexp_replace(translate(b.`sector`, chr(9) || chr(160), '  '), ' +', ' ')) <> '') AS unmapped_sector,
    COUNT_IF(c.school_management IS NULL AND TRIM(regexp_replace(translate(b.`school_management`, chr(9) || chr(160), '  '), ' +', ' ')) <> '') AS unmapped_school_management,
    COUNT_IF(c.offers_es IS NULL AND TRIM(regexp_replace(translate(b.`offers_es`, chr(9) || chr(160), '  '), ' +', ' ')) <> '') AS unmapped_offers_es,
    COUNT_IF(c.offers_jhs IS NULL AND TRIM(regexp_replace(translate(b.`offers_jhs`, chr(9) || chr(160), '  '), ' +', ' ')) <> '') AS unmapped_offers_jhs,
    COUNT_IF(c.offers_shs IS NULL AND TRIM(regexp_replace(translate(b.`offers_shs`, chr(9) || chr(160), '  '), ' +', ' ')) <> '') AS unmapped_offers_shs,
    COUNT_IF(
        (c.es_has_covered_court IS NULL AND TRIM(regexp_replace(translate(b.`es_has_covered_court`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.hs_has_covered_court IS NULL AND TRIM(regexp_replace(translate(b.`hs_has_covered_court`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.es_has_gymnasium IS NULL AND TRIM(regexp_replace(translate(b.`es_has_gymnasium`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.hs_has_gymnasium IS NULL AND TRIM(regexp_replace(translate(b.`hs_has_gymnasium`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.es_has_gate_entrance IS NULL AND TRIM(regexp_replace(translate(b.`es_has_gate_entrance`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.hs_has_gate_entrance IS NULL AND TRIM(regexp_replace(translate(b.`hs_has_gate_entrance`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.es_has_gate_exit IS NULL AND TRIM(regexp_replace(translate(b.`es_has_gate_exit`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.hs_has_gate_exit IS NULL AND TRIM(regexp_replace(translate(b.`hs_has_gate_exit`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.es_has_perimeter_fence_permanent IS NULL AND TRIM(regexp_replace(translate(b.`es_has_perimeter_fence_permanent`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.hs_has_perimeter_fence_permanent IS NULL AND TRIM(regexp_replace(translate(b.`hs_has_perimeter_fence_permanent`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.es_has_flood_marker IS NULL AND TRIM(regexp_replace(translate(b.`es_has_flood_marker`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.hs_has_flood_marker IS NULL AND TRIM(regexp_replace(translate(b.`hs_has_flood_marker`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.es_has_perimeter_fence_temporary IS NULL AND TRIM(regexp_replace(translate(b.`es_has_perimeter_fence_temporary`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.hs_has_perimeter_fence_temporary IS NULL AND TRIM(regexp_replace(translate(b.`hs_has_perimeter_fence_temporary`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.es_has_playground IS NULL AND TRIM(regexp_replace(translate(b.`es_has_playground`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.hs_has_playground IS NULL AND TRIM(regexp_replace(translate(b.`hs_has_playground`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.es_has_garden IS NULL AND TRIM(regexp_replace(translate(b.`es_has_garden`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.hs_has_garden IS NULL AND TRIM(regexp_replace(translate(b.`hs_has_garden`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.es_has_solar_panel IS NULL AND TRIM(regexp_replace(translate(b.`es_has_solar_panel`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.hs_has_solar_panel IS NULL AND TRIM(regexp_replace(translate(b.`hs_has_solar_panel`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.es_has_bike_rack IS NULL AND TRIM(regexp_replace(translate(b.`es_has_bike_rack`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.hs_has_bike_rack IS NULL AND TRIM(regexp_replace(translate(b.`hs_has_bike_rack`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.es_has_paved_pathway IS NULL AND TRIM(regexp_replace(translate(b.`es_has_paved_pathway`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.hs_has_paved_pathway IS NULL AND TRIM(regexp_replace(translate(b.`hs_has_paved_pathway`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.es_has_pathway_roofing IS NULL AND TRIM(regexp_replace(translate(b.`es_has_pathway_roofing`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.hs_has_pathway_roofing IS NULL AND TRIM(regexp_replace(translate(b.`hs_has_pathway_roofing`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.es_has_road_paved IS NULL AND TRIM(regexp_replace(translate(b.`es_has_road_paved`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.hs_has_road_paved IS NULL AND TRIM(regexp_replace(translate(b.`hs_has_road_paved`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.es_has_road_unpaved IS NULL AND TRIM(regexp_replace(translate(b.`es_has_road_unpaved`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.hs_has_road_unpaved IS NULL AND TRIM(regexp_replace(translate(b.`hs_has_road_unpaved`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.es_has_road_levelled IS NULL AND TRIM(regexp_replace(translate(b.`es_has_road_levelled`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.hs_has_road_levelled IS NULL AND TRIM(regexp_replace(translate(b.`hs_has_road_levelled`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.es_has_road_rough IS NULL AND TRIM(regexp_replace(translate(b.`es_has_road_rough`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.hs_has_road_rough IS NULL AND TRIM(regexp_replace(translate(b.`hs_has_road_rough`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.es_has_road_under_construction IS NULL AND TRIM(regexp_replace(translate(b.`es_has_road_under_construction`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.hs_has_road_under_construction IS NULL AND TRIM(regexp_replace(translate(b.`hs_has_road_under_construction`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.es_accessible_private_4wheel IS NULL AND TRIM(regexp_replace(translate(b.`es_accessible_private_4wheel`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.hs_accessible_private_4wheel IS NULL AND TRIM(regexp_replace(translate(b.`hs_accessible_private_4wheel`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.es_accessible_private_motorcycle IS NULL AND TRIM(regexp_replace(translate(b.`es_accessible_private_motorcycle`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.hs_accessible_private_motorcycle IS NULL AND TRIM(regexp_replace(translate(b.`hs_accessible_private_motorcycle`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.es_accessible_boat IS NULL AND TRIM(regexp_replace(translate(b.`es_accessible_boat`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.hs_accessible_boat IS NULL AND TRIM(regexp_replace(translate(b.`hs_accessible_boat`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.es_accessible_uv_express IS NULL AND TRIM(regexp_replace(translate(b.`es_accessible_uv_express`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.hs_accessible_uv_express IS NULL AND TRIM(regexp_replace(translate(b.`hs_accessible_uv_express`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.es_accessible_pedicab IS NULL AND TRIM(regexp_replace(translate(b.`es_accessible_pedicab`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.hs_accessible_pedicab IS NULL AND TRIM(regexp_replace(translate(b.`hs_accessible_pedicab`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.es_accessible_tricycle IS NULL AND TRIM(regexp_replace(translate(b.`es_accessible_tricycle`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.hs_accessible_tricycle IS NULL AND TRIM(regexp_replace(translate(b.`hs_accessible_tricycle`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.es_accessible_jeepney IS NULL AND TRIM(regexp_replace(translate(b.`es_accessible_jeepney`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.hs_accessible_jeepney IS NULL AND TRIM(regexp_replace(translate(b.`hs_accessible_jeepney`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.es_accessible_habalhabal IS NULL AND TRIM(regexp_replace(translate(b.`es_accessible_habalhabal`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.hs_accessible_habalhabal IS NULL AND TRIM(regexp_replace(translate(b.`hs_accessible_habalhabal`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.es_accessible_train IS NULL AND TRIM(regexp_replace(translate(b.`es_accessible_train`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.hs_accessible_train IS NULL AND TRIM(regexp_replace(translate(b.`hs_accessible_train`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.es_accessible_bus IS NULL AND TRIM(regexp_replace(translate(b.`es_accessible_bus`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.hs_accessible_bus IS NULL AND TRIM(regexp_replace(translate(b.`hs_accessible_bus`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.es_accessible_bicycle IS NULL AND TRIM(regexp_replace(translate(b.`es_accessible_bicycle`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.hs_accessible_bicycle IS NULL AND TRIM(regexp_replace(translate(b.`hs_accessible_bicycle`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.es_accessible_walking_hiking IS NULL AND TRIM(regexp_replace(translate(b.`es_accessible_walking_hiking`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.hs_accessible_walking_hiking IS NULL AND TRIM(regexp_replace(translate(b.`hs_accessible_walking_hiking`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
      ) AS unmapped_facility_booleans,
    COUNT_IF(
        TRIM(regexp_replace(translate(b.`sector`, chr(9) || chr(160), '  '), ' +', ' ')) <> c.sector
        OR TRIM(regexp_replace(translate(b.`school_management`, chr(9) || chr(160), '  '), ' +', ' ')) <> c.school_management
      ) AS relabelled_rows
  FROM clean AS c
  JOIN b ON c.source_sha256 = b.source_sha256 AND c.source_row_number = b.source_row_number
  GROUP BY c.school_year
),
quarantine_years AS (
  SELECT
    q.school_year,
    COUNT(*) AS quarantined_rows,
    COUNT_IF(array_contains(q.quarantine_reasons, 'school_id_blank')) AS reason_school_id_blank,
    COUNT_IF(array_contains(q.quarantine_reasons, 'school_id_malformed')) AS reason_school_id_malformed,
    COUNT_IF(array_contains(q.quarantine_reasons, 'school_id_duplicated')) AS reason_school_id_duplicated,
    COUNT_IF(array_contains(q.quarantine_reasons, 'count_negative')) AS reason_count_negative,
    COUNT_IF(array_contains(q.quarantine_reasons, 'count_uncastable')) AS reason_count_uncastable,
    COUNT_IF(array_contains(q.quarantine_reasons, 'count_above_plausible_max')) AS reason_count_above_plausible_max
  FROM quarantined AS q GROUP BY q.school_year
),
years AS (
  SELECT
    y.school_year,
    y.batch_id,
    COALESCE(bronze_rows, 0) AS bronze_rows,
    COALESCE(clean_rows, 0) AS clean_rows,
    COALESCE(clean_ids, 0) AS clean_ids,
    COALESCE(quarantined_rows, 0) AS quarantined_rows,
    COALESCE(kept_counts, 0) AS kept_counts,
    COALESCE(clean_counts, 0) AS clean_counts,
    COALESCE(kept_missing_counts, 0) AS kept_missing_counts,
    COALESCE(clean_missing_counts, 0) AS clean_missing_counts,
    COALESCE(kept_true_values, 0) AS kept_true_values,
    COALESCE(clean_true_values, 0) AS clean_true_values,
    COALESCE(kept_blank_booleans, 0) AS kept_blank_booleans,
    COALESCE(clean_blank_booleans, 0) AS clean_blank_booleans,
    COALESCE(whitespace_rows, 0) AS whitespace_rows,
    COALESCE(blank_count_rows, 0) AS blank_count_rows,
    COALESCE(blank_boolean_rows, 0) AS blank_boolean_rows,
    COALESCE(invalid_ids, 0) AS invalid_ids,
    COALESCE(negative_rows, 0) AS negative_rows,
    COALESCE(implausible_rows, 0) AS implausible_rows,
    COALESCE(non_public_facility_rows, 0) AS non_public_facility_rows,
    COALESCE(outside_level_rows, 0) AS outside_level_rows,
    COALESCE(overseas_rows, 0) AS overseas_rows,
    COALESCE(facility_data_rows, 0) AS facility_data_rows,
    COALESCE(public_without_data_rows, 0) AS public_without_data_rows,
    COALESCE(classrooms_missing_rows, 0) AS classrooms_missing_rows,
    COALESCE(relabelled_rows, 0) AS relabelled_rows,
    COALESCE(reason_school_id_blank, 0) AS reason_school_id_blank,
    COALESCE(reason_school_id_malformed, 0) AS reason_school_id_malformed,
    COALESCE(reason_school_id_duplicated, 0) AS reason_school_id_duplicated,
    COALESCE(reason_count_negative, 0) AS reason_count_negative,
    COALESCE(reason_count_uncastable, 0) AS reason_count_uncastable,
    COALESCE(reason_count_above_plausible_max, 0) AS reason_count_above_plausible_max,
    COALESCE(unmapped_sector, 0) + COALESCE(quarantined_unmapped_sector, 0) AS unmapped_sector,
    COALESCE(unmapped_school_management, 0) + COALESCE(quarantined_unmapped_school_management, 0) AS unmapped_school_management,
    COALESCE(unmapped_offers_es, 0) + COALESCE(quarantined_unmapped_offers_es, 0) AS unmapped_offers_es,
    COALESCE(unmapped_offers_jhs, 0) + COALESCE(quarantined_unmapped_offers_jhs, 0) AS unmapped_offers_jhs,
    COALESCE(unmapped_offers_shs, 0) + COALESCE(quarantined_unmapped_offers_shs, 0) AS unmapped_offers_shs,
    COALESCE(unmapped_facility_booleans, 0) + COALESCE(quarantined_unmapped_facility_booleans, 0) AS unmapped_facility_booleans
  FROM cur AS y
  LEFT JOIN bronze_years ON bronze_years.school_year = y.school_year
  LEFT JOIN clean_years ON clean_years.school_year = y.school_year
  LEFT JOIN matched_years ON matched_years.school_year = y.school_year
  LEFT JOIN quarantine_years ON quarantine_years.school_year = y.school_year
),
found AS (SELECT COUNT(*) AS current_batches FROM cur),
silver_rows AS (
  SELECT school_year, batch_id, delivery_version, schema_version, source_sha256, source_row_number, run_id, cleaned_at_utc, code_revision FROM clean
  UNION ALL SELECT school_year, batch_id, delivery_version, schema_version, source_sha256, source_row_number, run_id, cleaned_at_utc, code_revision FROM quarantined
),
whole AS (
  SELECT
    COUNT_IF(school_year IS NULL OR batch_id IS NULL OR delivery_version IS NULL OR schema_version IS NULL OR source_sha256 IS NULL OR source_row_number IS NULL OR run_id IS NULL OR cleaned_at_utc IS NULL OR code_revision IS NULL) AS missing_lineage,
    COUNT_IF(run_id IS NULL OR run_id <> :run_id) AS other_run_rows,
    COUNT(DISTINCT cleaned_at_utc) AS timestamps
  FROM silver_rows
),
-- Silver rows whose Bronze row is not in a current batch (an old version, or gone).
unresolved AS (
  SELECT COUNT(*) AS unresolved_rows
  FROM silver_rows AS s
  LEFT JOIN bronze ON s.source_sha256 = bronze.source_sha256 AND s.source_row_number = bronze.source_row_number
  WHERE bronze.source_row_number IS NULL
),
checks AS (
  -- The whole table, both tables together
  SELECT CAST(NULL AS STRING) AS batch_id, 'edu_access.03-silver.deped_facilities_clean_candidate' AS table_name, 'current_batches_present' AS check_name,
         CASE WHEN current_batches > 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         'at least 1' AS expected, CAST(current_batches AS STRING) AS actual FROM found
  UNION ALL SELECT CAST(NULL AS STRING) AS batch_id, 'edu_access.03-silver.deped_facilities_clean_candidate' AS table_name, 'lineage_complete' AS check_name,
         CASE WHEN missing_lineage = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(missing_lineage AS STRING) AS actual FROM whole
  UNION ALL SELECT CAST(NULL AS STRING) AS batch_id, 'edu_access.03-silver.deped_facilities_clean_candidate' AS table_name, 'rows_resolve_to_current_bronze' AS check_name,
         CASE WHEN unresolved_rows = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(unresolved_rows AS STRING) AS actual FROM unresolved
  UNION ALL SELECT CAST(NULL AS STRING) AS batch_id, 'edu_access.03-silver.deped_facilities_clean_candidate' AS table_name, 'rows_built_by_this_run' AS check_name,
         CASE WHEN other_run_rows = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(other_run_rows AS STRING) AS actual FROM whole
  UNION ALL SELECT CAST(NULL AS STRING) AS batch_id, 'edu_access.03-silver.deped_facilities_clean_candidate' AS table_name, 'one_timestamp_per_run' AS check_name,
         CASE WHEN timestamps = 1 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(1 AS STRING) AS expected, CAST(timestamps AS STRING) AS actual FROM whole
  -- Each school year: reconciliation, keys, ranges, NULLs
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_facilities_clean_candidate' AS table_name, 'rows_reconcile' AS check_name,
         CASE WHEN clean_rows + quarantined_rows = bronze_rows THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(bronze_rows AS STRING) AS expected, CAST(clean_rows + quarantined_rows AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_facilities_clean_candidate' AS table_name, 'school_id_unique' AS check_name,
         CASE WHEN clean_rows - clean_ids = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(clean_rows - clean_ids AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_facilities_clean_candidate' AS table_name, 'school_id_valid' AS check_name,
         CASE WHEN invalid_ids = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(invalid_ids AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_facilities_clean_candidate' AS table_name, 'counts_non_negative' AS check_name,
         CASE WHEN negative_rows = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(negative_rows AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_facilities_clean_candidate' AS table_name, 'counts_within_plausible_max' AS check_name,
         CASE WHEN implausible_rows = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(implausible_rows AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_facilities_clean_candidate' AS table_name, 'counts_reconcile' AS check_name,
         CASE WHEN clean_counts = kept_counts THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(kept_counts AS STRING) AS expected, CAST(clean_counts AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_facilities_clean_candidate' AS table_name, 'missing_counts_stay_null' AS check_name,
         CASE WHEN clean_missing_counts = kept_missing_counts THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(kept_missing_counts AS STRING) AS expected, CAST(clean_missing_counts AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_facilities_clean_candidate' AS table_name, 'true_values_reconcile' AS check_name,
         CASE WHEN clean_true_values = kept_true_values THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(kept_true_values AS STRING) AS expected, CAST(clean_true_values AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_facilities_clean_candidate' AS table_name, 'missing_booleans_stay_null' AS check_name,
         CASE WHEN clean_blank_booleans = kept_blank_booleans THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(kept_blank_booleans AS STRING) AS expected, CAST(clean_blank_booleans AS STRING) AS actual FROM years
  -- Each school year: every label is in the reviewed mapping
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_facilities_clean_candidate' AS table_name, 'labels_mapped_sector' AS check_name,
         CASE WHEN unmapped_sector = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(unmapped_sector AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_facilities_clean_candidate' AS table_name, 'labels_mapped_school_management' AS check_name,
         CASE WHEN unmapped_school_management = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(unmapped_school_management AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_facilities_clean_candidate' AS table_name, 'labels_mapped_offers_es' AS check_name,
         CASE WHEN unmapped_offers_es = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(unmapped_offers_es AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_facilities_clean_candidate' AS table_name, 'labels_mapped_offers_jhs' AS check_name,
         CASE WHEN unmapped_offers_jhs = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(unmapped_offers_jhs AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_facilities_clean_candidate' AS table_name, 'labels_mapped_offers_shs' AS check_name,
         CASE WHEN unmapped_offers_shs = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(unmapped_offers_shs AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_facilities_clean_candidate' AS table_name, 'labels_mapped_facility_booleans' AS check_name,
         CASE WHEN unmapped_facility_booleans = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(unmapped_facility_booleans AS STRING) AS actual FROM years
  -- Each school year: scope the planners rely on (WARN: published, but Gold's reading may need review)
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_facilities_clean_candidate' AS table_name, 'facility_data_public_only' AS check_name,
         CASE WHEN non_public_facility_rows = 0 THEN 'PASS' ELSE 'WARN' END AS status,
         '0' AS expected, CAST(non_public_facility_rows AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_facilities_clean_candidate' AS table_name, 'facility_values_within_offered_levels' AS check_name,
         CASE WHEN outside_level_rows = 0 THEN 'PASS' ELSE 'WARN' END AS status,
         '0' AS expected, CAST(outside_level_rows AS STRING) AS actual FROM years
  -- Each school year: quarantine (WARN above 0, FAIL above 1% of the year's Bronze rows)
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_facilities_quarantine_candidate' AS table_name, 'quarantine_rate' AS check_name,
         CASE WHEN quarantined_rows = 0 THEN 'PASS' WHEN quarantined_rows * 100 > bronze_rows THEN 'FAIL' ELSE 'WARN' END AS status,
         '0 (FAIL above 1% of ' || CAST(bronze_rows AS STRING) || ')' AS expected, CAST(quarantined_rows AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_facilities_quarantine_candidate' AS table_name, 'quarantine_reason_school_id_blank' AS check_name,
         CASE WHEN reason_school_id_blank = 0 THEN 'PASS' ELSE 'WARN' END AS status,
         '0' AS expected, CAST(reason_school_id_blank AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_facilities_quarantine_candidate' AS table_name, 'quarantine_reason_school_id_malformed' AS check_name,
         CASE WHEN reason_school_id_malformed = 0 THEN 'PASS' ELSE 'WARN' END AS status,
         '0' AS expected, CAST(reason_school_id_malformed AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_facilities_quarantine_candidate' AS table_name, 'quarantine_reason_school_id_duplicated' AS check_name,
         CASE WHEN reason_school_id_duplicated = 0 THEN 'PASS' ELSE 'WARN' END AS status,
         '0' AS expected, CAST(reason_school_id_duplicated AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_facilities_quarantine_candidate' AS table_name, 'quarantine_reason_count_negative' AS check_name,
         CASE WHEN reason_count_negative = 0 THEN 'PASS' ELSE 'WARN' END AS status,
         '0' AS expected, CAST(reason_count_negative AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_facilities_quarantine_candidate' AS table_name, 'quarantine_reason_count_uncastable' AS check_name,
         CASE WHEN reason_count_uncastable = 0 THEN 'PASS' ELSE 'WARN' END AS status,
         '0' AS expected, CAST(reason_count_uncastable AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_facilities_quarantine_candidate' AS table_name, 'quarantine_reason_count_above_plausible_max' AS check_name,
         CASE WHEN reason_count_above_plausible_max = 0 THEN 'PASS' ELSE 'WARN' END AS status,
         '0' AS expected, CAST(reason_count_above_plausible_max AS STRING) AS actual FROM years
  -- Each school year: how many rows each cleaning rule changed or flagged (records, always PASS)
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_facilities_clean_candidate' AS table_name, 'rule_whitespace_normalized' AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(whitespace_rows AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_facilities_clean_candidate' AS table_name, 'rule_blank_counts_to_null' AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(blank_count_rows AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_facilities_clean_candidate' AS table_name, 'rule_blank_booleans_to_null' AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(blank_boolean_rows AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_facilities_clean_candidate' AS table_name, 'rule_labels_standardized' AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(relabelled_rows AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_facilities_clean_candidate' AS table_name, 'flag_is_overseas' AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(overseas_rows AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_facilities_clean_candidate' AS table_name, 'flag_has_facility_data' AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(facility_data_rows AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_facilities_clean_candidate' AS table_name, 'flag_public_without_facility_data' AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(public_without_data_rows AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_facilities_clean_candidate' AS table_name, 'flag_es_classrooms_missing' AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(classrooms_missing_rows AS STRING) AS actual FROM years
)
SELECT * FROM checks
) AS results;

-- A failed build: record it before stopping. The Silver tables are not touched.
MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (
  SELECT :run_id AS run_id, COUNT_IF(status = 'FAIL') AS fails
  FROM edu_access.`01-control`.data_quality_results
  WHERE run_id = :run_id AND source_id = 'deped_facilities' AND layer = 'silver'
    AND checked_at_utc >= session.silver_gate_started_at_utc
) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'silver_build' AND t.source_id = 'deped_facilities'
WHEN MATCHED AND s.fails > 0 THEN UPDATE SET
  status = 'failed', finished_at_utc = current_timestamp(), failure_stage = 'gate',
  error_message = CAST(s.fails AS STRING) || ' FAIL result(s) in data_quality_results';

-- Stop here, before publishing, if anything failed in this execution.
SELECT CASE WHEN COUNT(*) > 0
            THEN raise_error('Silver gate failed for deped_facilities: ' || CAST(COUNT(*) AS STRING)
                             || ' FAIL result(s) in data_quality_results for run ' || :run_id)
       END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'deped_facilities' AND layer = 'silver' AND status = 'FAIL'
  AND checked_at_utc >= session.silver_gate_started_at_utc;

-- Every check passed: publish. Quarantine first, then clean, the table Gold reads. Each copy is
-- one atomic Delta commit, but the pair is not, so the run is 'succeeded' only after both. If the
-- task dies in between, the run stays 'running', and Gold trusts a Silver table only when the
-- run_id its rows carry is a succeeded silver_build run (D-025).
CREATE OR REPLACE TABLE edu_access.`03-silver`.deped_facilities_quarantine USING DELTA AS
SELECT * FROM edu_access.`03-silver`.deped_facilities_quarantine_candidate;

ALTER TABLE edu_access.`03-silver`.deped_facilities_quarantine OWNER TO `reached-hq`;

CREATE OR REPLACE TABLE edu_access.`03-silver`.deped_facilities_clean USING DELTA AS
SELECT * FROM edu_access.`03-silver`.deped_facilities_clean_candidate;

ALTER TABLE edu_access.`03-silver`.deped_facilities_clean OWNER TO `reached-hq`;

-- Published: the run succeeded.
MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (SELECT :run_id AS run_id) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'silver_build' AND t.source_id = 'deped_facilities'
WHEN MATCHED THEN UPDATE SET
  status = 'succeeded', finished_at_utc = current_timestamp(), failure_stage = NULL, error_message = NULL;
