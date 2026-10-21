-- Silver gate for deped_psgc_coordinates. Generated from config/ingestion/deped_psgc_coordinates.json
-- and config/mappings/deped_psgc_coordinates.json:
--   python -m src.silver.cli gate --source deped_psgc_coordinates > etl/03_silver/90_validate_deped_psgc_coordinates_clean.sql
-- Do not edit by hand; tests/test_silver.py fails if it differs.
-- Records every rule count, stops before publishing on FAIL, then publishes quarantine before clean.

DECLARE OR REPLACE VARIABLE silver_gate_started_at_utc TIMESTAMP;
SET VARIABLE silver_gate_started_at_utc = current_timestamp();

-- Materialize the aggregates once so every check reads the same one-row result.
CREATE OR REPLACE TABLE edu_access.`03-silver`.deped_psgc_coordinates_gate_summary_candidate USING DELTA AS
WITH cur AS (
  SELECT batch_id FROM edu_access.`01-control`.current_batches WHERE source_id = 'deped_psgc_coordinates'
), bronze AS (
  SELECT b.* FROM edu_access.`02-bronze`.deped_psgc_coordinates_raw AS b JOIN cur ON b.batch_id = cur.batch_id
), unit AS (
  SELECT * FROM bronze WHERE source_row_kind = 'unit'
), expected_padded AS (
  -- Every value recomputed from its Bronze row with the build's own expressions.
  SELECT
    r.school_year,
    r.school_id AS school_id,
    CASE WHEN regexp_like(r.psgc_region, '^[0-9]{9,10}$') THEN lpad(r.psgc_region, 10, '0') END AS region_padded,
    CASE WHEN regexp_like(r.psgc_province, '^[0-9]{9,10}$') THEN lpad(r.psgc_province, 10, '0') END AS province_padded,
    CASE WHEN regexp_like(r.psgc_city_municipality, '^[0-9]{9,10}$') THEN lpad(r.psgc_city_municipality, 10, '0') END AS city_municipality_padded,
    CASE WHEN regexp_like(r.psgc_barangay, '^[0-9]{9,10}$') THEN lpad(r.psgc_barangay, 10, '0') END AS barangay_padded,
    CASE WHEN r.psgc_city_municipality IS NULL THEN 'not_in_workbook' WHEN r.psgc_city_municipality = '#N/A' THEN 'source_na' WHEN r.psgc_city_municipality = '' THEN 'not_in_workbook' ELSE 'unrecognized' END AS city_reason_if_null,
    CASE WHEN r.psgc_barangay IS NULL THEN 'not_in_workbook' WHEN r.psgc_barangay = '#N/A' THEN 'source_na' WHEN r.psgc_barangay = '' THEN 'not_in_workbook' ELSE 'unrecognized' END AS barangay_reason_if_null,
    CASE WHEN regexp_like(r.longitude, '^-?[0-9]+([.][0-9]+)?([eE]-?[0-9]+)?$') THEN TRY_CAST(r.longitude AS DOUBLE) END AS longitude,
    CASE WHEN regexp_like(r.latitude, '^-?[0-9]+([.][0-9]+)?([eE]-?[0-9]+)?$') THEN TRY_CAST(r.latitude AS DOUBLE) END AS latitude,
    r.batch_id,
    r.source_sha256,
    r.source_row_number
  FROM unit AS r
), expected_recoded AS (
  SELECT c.*, COALESCE(substr(c.province_padded, 1, 5) = '19066', FALSE) AS psgc_recoded FROM expected_padded AS c
), expected AS (
  SELECT
    c.school_year,
    c.school_id,
    CASE WHEN c.psgc_recoded AND c.region_padded = '1900000000' THEN '0900000000' ELSE c.region_padded END AS psgc_region,
    CASE WHEN c.psgc_recoded AND substr(c.province_padded, 1, 5) = '19066' THEN concat('09066', substr(c.province_padded, 6)) ELSE c.province_padded END AS psgc_province,
    CASE WHEN c.psgc_recoded AND substr(c.city_municipality_padded, 1, 5) = '19066' THEN concat('09066', substr(c.city_municipality_padded, 6)) ELSE c.city_municipality_padded END AS psgc_city_municipality,
    CASE WHEN c.psgc_recoded AND substr(c.barangay_padded, 1, 5) = '19066' THEN concat('09066', substr(c.barangay_padded, 6)) ELSE c.barangay_padded END AS psgc_barangay,
    c.psgc_recoded,
    CASE WHEN c.city_municipality_padded IS NULL THEN c.city_reason_if_null WHEN c.barangay_padded IS NULL THEN c.barangay_reason_if_null END AS psgc_null_reason,
    COALESCE(substr(c.barangay_padded, 1, 7) <> substr(c.city_municipality_padded, 1, 7), FALSE) AS barangay_outside_city,
    c.longitude,
    c.latitude,
    CASE WHEN c.longitude IS NULL OR c.latitude IS NULL THEN 'missing' WHEN c.longitude = 0 AND c.latitude = 0 THEN 'zero' WHEN NOT (c.longitude BETWEEN 116 AND 127 AND c.latitude BETWEEN 4 AND 21.5) THEN 'outside_philippines' END AS coordinate_flag,
    c.batch_id,
    c.source_sha256,
    c.source_row_number
  FROM expected_recoded AS c
), c AS (
  SELECT * FROM edu_access.`03-silver`.deped_psgc_coordinates_clean_candidate
), q AS (
  SELECT * FROM edu_access.`03-silver`.deped_psgc_coordinates_quarantine_candidate
), s AS (
  SELECT batch_id, source_sha256, source_row_number FROM c UNION ALL SELECT batch_id, source_sha256, source_row_number FROM q
), counts AS (
  SELECT
    (SELECT COUNT(*) FROM cur) AS current_batches,
    (SELECT COUNT(*) FROM s LEFT JOIN unit AS u ON u.batch_id = s.batch_id AND u.source_sha256 = s.source_sha256 AND u.source_row_number = s.source_row_number WHERE u.source_row_number IS NULL) + (SELECT COUNT(*) - COUNT(DISTINCT (source_sha256, source_row_number)) FROM s) AS unresolved_rows,
    (SELECT COUNT(*) FROM c JOIN expected AS e ON e.source_sha256 = c.source_sha256 AND e.source_row_number = c.source_row_number WHERE c.school_year IS DISTINCT FROM e.school_year OR c.school_id IS DISTINCT FROM e.school_id OR c.psgc_region IS DISTINCT FROM e.psgc_region OR c.psgc_province IS DISTINCT FROM e.psgc_province OR c.psgc_city_municipality IS DISTINCT FROM e.psgc_city_municipality OR c.psgc_barangay IS DISTINCT FROM e.psgc_barangay OR c.psgc_recoded IS DISTINCT FROM e.psgc_recoded OR c.psgc_null_reason IS DISTINCT FROM e.psgc_null_reason OR c.barangay_outside_city IS DISTINCT FROM e.barangay_outside_city OR c.longitude IS DISTINCT FROM e.longitude OR c.latitude IS DISTINCT FROM e.latitude OR c.coordinate_flag IS DISTINCT FROM e.coordinate_flag) AS value_mismatches,
    (SELECT COUNT(*) FROM c JOIN unit AS b ON b.source_sha256 = c.source_sha256 AND b.source_row_number = c.source_row_number WHERE c.longitude IS DISTINCT FROM CASE WHEN regexp_like(b.longitude, '^-?[0-9]+([.][0-9]+)?([eE]-?[0-9]+)?$') THEN TRY_CAST(b.longitude AS DOUBLE) END OR c.latitude IS DISTINCT FROM CASE WHEN regexp_like(b.latitude, '^-?[0-9]+([.][0-9]+)?([eE]-?[0-9]+)?$') THEN TRY_CAST(b.latitude AS DOUBLE) END) AS coordinate_mismatches,
    (SELECT COALESCE(COUNT_IF((u.psgc_region IS NOT NULL AND u.psgc_region NOT IN ('#N/A', '') AND NOT regexp_like(u.psgc_region, '^[0-9]{9,10}$')) OR (u.psgc_province IS NOT NULL AND u.psgc_province NOT IN ('#N/A', '') AND NOT regexp_like(u.psgc_province, '^[0-9]{9,10}$'))), 0) FROM unit AS u) AS unrecognized_region_province,
    (SELECT COALESCE(COUNT_IF(source_row_kind = 'unit'), 0) FROM bronze) AS bronze_unit_rows,
    (SELECT COALESCE(COUNT_IF(source_row_kind <> 'unit'), 0) FROM bronze) AS bronze_other_rows,
    (SELECT COUNT(*) FROM c) AS clean_rows,
    (SELECT COUNT(*) FROM q) AS quarantine_rows,
    (SELECT COUNT(*) - COUNT(DISTINCT (school_year, school_id)) FROM c) AS duplicate_clean_ids,
    (SELECT COALESCE(COUNT_IF(NOT regexp_like(school_id, '^[0-9]{6}$')), 0) FROM c) AS malformed_clean_ids,
    (SELECT COALESCE(COUNT_IF((psgc_region IS NOT NULL AND NOT regexp_like(psgc_region, '^[0-9]{10}$')) OR (psgc_province IS NOT NULL AND NOT regexp_like(psgc_province, '^[0-9]{10}$')) OR (psgc_city_municipality IS NOT NULL AND NOT regexp_like(psgc_city_municipality, '^[0-9]{10}$')) OR (psgc_barangay IS NOT NULL AND NOT regexp_like(psgc_barangay, '^[0-9]{10}$'))), 0) FROM c) AS codes_not_ten_digits,
    (SELECT COALESCE(COUNT_IF(CASE WHEN psgc_city_municipality IS NULL THEN psgc_null_reason END = 'unrecognized' OR CASE WHEN psgc_barangay IS NULL THEN psgc_null_reason END = 'unrecognized'), 0) FROM c) AS unrecognized_code_values,
    (SELECT COALESCE(COUNT_IF((psgc_city_municipality IS NULL OR psgc_barangay IS NULL) <> (psgc_null_reason IS NOT NULL)), 0) FROM c) AS null_reason_mismatches,
    (SELECT COALESCE(COUNT_IF(CASE WHEN regexp_like(u.psgc_city_municipality, '^[0-9]{9,10}$') THEN lpad(u.psgc_city_municipality, 10, '0') END IS NULL AND CASE WHEN regexp_like(u.psgc_barangay, '^[0-9]{9,10}$') THEN lpad(u.psgc_barangay, 10, '0') END IS NULL AND CASE WHEN u.psgc_city_municipality IS NULL THEN 'not_in_workbook' WHEN u.psgc_city_municipality = '#N/A' THEN 'source_na' WHEN u.psgc_city_municipality = '' THEN 'not_in_workbook' ELSE 'unrecognized' END <> CASE WHEN u.psgc_barangay IS NULL THEN 'not_in_workbook' WHEN u.psgc_barangay = '#N/A' THEN 'source_na' WHEN u.psgc_barangay = '' THEN 'not_in_workbook' ELSE 'unrecognized' END), 0) FROM unit AS u) AS null_reasons_differ,
    (SELECT COALESCE(COUNT_IF((psgc_region IS NULL) <> (psgc_city_municipality IS NULL) OR (psgc_province IS NULL) <> (psgc_city_municipality IS NULL)), 0) FROM c) AS levels_not_null_together,
    (SELECT COALESCE(COUNT_IF((longitude IS NULL) <> (latitude IS NULL)), 0) FROM c) AS coordinates_not_in_pairs,
    (SELECT COALESCE(COUNT_IF(source_row_kind = 'unit' AND ((b.longitude NOT IN ('#N/A', '') AND NOT regexp_like(b.longitude, '^-?[0-9]+([.][0-9]+)?([eE]-?[0-9]+)?$')) OR (b.latitude NOT IN ('#N/A', '') AND NOT regexp_like(b.latitude, '^-?[0-9]+([.][0-9]+)?([eE]-?[0-9]+)?$')))), 0) FROM bronze AS b) AS unrecognized_coordinates,
    (SELECT COALESCE(COUNT_IF(x.batch_id IS NULL OR x.delivery_version IS NULL OR x.schema_version IS NULL OR x.source_sha256 IS NULL OR x.source_row_number IS NULL OR x.run_id IS NULL OR x.cleaned_at_utc IS NULL OR x.code_revision IS NULL), 0) FROM c AS x) + (SELECT COALESCE(COUNT_IF(x.batch_id IS NULL OR x.delivery_version IS NULL OR x.schema_version IS NULL OR x.source_sha256 IS NULL OR x.source_row_number IS NULL OR x.run_id IS NULL OR x.cleaned_at_utc IS NULL OR x.code_revision IS NULL), 0) FROM q AS x) AS missing_lineage,
    (SELECT COALESCE(COUNT_IF(run_id <> :run_id), 0) FROM c) + (SELECT COALESCE(COUNT_IF(run_id <> :run_id), 0) FROM q) AS other_run_rows,
    (SELECT COALESCE(COUNT_IF(source_row_kind = 'unit' AND regexp_like(b.psgc_barangay, '^[0-9]{9,10}$') AND length(b.psgc_barangay) < 10), 0) FROM bronze AS b) AS barangay_codes_padded,
    (SELECT COALESCE(COUNT_IF(CASE WHEN psgc_city_municipality IS NULL THEN psgc_null_reason END = 'source_na'), 0) FROM c) AS city_source_na,
    (SELECT COALESCE(COUNT_IF(CASE WHEN psgc_city_municipality IS NULL THEN psgc_null_reason END = 'not_in_workbook'), 0) FROM c) AS city_not_in_workbook,
    (SELECT COALESCE(COUNT_IF(CASE WHEN psgc_barangay IS NULL THEN psgc_null_reason END = 'source_na'), 0) FROM c) AS barangay_source_na,
    (SELECT COALESCE(COUNT_IF(CASE WHEN psgc_barangay IS NULL THEN psgc_null_reason END = 'not_in_workbook'), 0) FROM c) AS barangay_not_in_workbook,
    (SELECT COALESCE(COUNT_IF(psgc_recoded), 0) FROM c) AS recoded,
    (SELECT COALESCE(COUNT_IF(barangay_outside_city), 0) FROM c) AS barangay_outside_city,
    (SELECT COALESCE(COUNT_IF(coordinate_flag = 'missing'), 0) FROM c) AS coordinate_missing,
    (SELECT COALESCE(COUNT_IF(coordinate_flag = 'zero'), 0) FROM c) AS coordinate_zero,
    (SELECT COALESCE(COUNT_IF(coordinate_flag = 'outside_philippines'), 0) FROM c) AS coordinate_outside_philippines,
    (SELECT COALESCE(COUNT_IF(array_contains(quarantine_reasons, 'school_id_malformed')), 0) FROM q) AS quarantine_school_id_malformed,
    (SELECT COALESCE(COUNT_IF(array_contains(quarantine_reasons, 'school_id_duplicated')), 0) FROM q) AS quarantine_school_id_duplicated,
    (SELECT COALESCE(COUNT_IF(array_contains(quarantine_reasons, 'school_id_identical_copy')), 0) FROM q) AS quarantine_school_id_identical_copy,
    (SELECT COALESCE(COUNT_IF(array_contains(quarantine_reasons, 'school_year_out_of_scope')), 0) FROM q) AS quarantine_school_year_out_of_scope,
    (SELECT COALESCE(COUNT_IF(array_contains(quarantine_reasons, 'sector_not_public')), 0) FROM q) AS quarantine_sector_not_public,
    (SELECT COUNT(*) FROM c JOIN unit AS b ON b.source_sha256 = c.source_sha256 AND b.source_row_number = c.source_row_number WHERE (b.school_year IS NULL OR b.school_year NOT IN ('2023-24')) OR (b.sector IS NULL OR b.sector NOT IN ('Public'))) AS out_of_scope_clean_rows
)
-- One row even when no batch is current, so current_batch_present can FAIL and nothing is published.
SELECT (SELECT MIN(batch_id) FROM cur) AS batch_id, counts.* FROM counts;

ALTER TABLE edu_access.`03-silver`.deped_psgc_coordinates_gate_summary_candidate OWNER TO `reached-hq`;

INSERT INTO edu_access.`01-control`.data_quality_results (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, batch_id, 'deped_psgc_coordinates', 'silver', table_name, check_name, status, expected, actual, current_timestamp(), :code_revision FROM (
SELECT batch_id, 'edu_access.03-silver.deped_psgc_coordinates_clean_candidate' AS table_name, 'current_batch_present' AS check_name, CASE WHEN current_batches > 0 THEN 'PASS' ELSE 'FAIL' END AS status, '> 0' AS expected, CAST(current_batches AS STRING) AS actual FROM edu_access.`03-silver`.deped_psgc_coordinates_gate_summary_candidate
  UNION ALL SELECT batch_id, 'edu_access.03-silver.deped_psgc_coordinates_clean_candidate' AS table_name, 'rows_reconcile' AS check_name, CASE WHEN clean_rows + quarantine_rows = bronze_unit_rows THEN 'PASS' ELSE 'FAIL' END AS status, '= bronze_unit_rows' AS expected, CAST(clean_rows + quarantine_rows AS STRING) AS actual FROM edu_access.`03-silver`.deped_psgc_coordinates_gate_summary_candidate
  UNION ALL SELECT batch_id, 'edu_access.03-silver.deped_psgc_coordinates_clean_candidate' AS table_name, 'rows_resolve_to_current_bronze' AS check_name, CASE WHEN unresolved_rows = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '= 0' AS expected, CAST(unresolved_rows AS STRING) AS actual FROM edu_access.`03-silver`.deped_psgc_coordinates_gate_summary_candidate
  UNION ALL SELECT batch_id, 'edu_access.03-silver.deped_psgc_coordinates_clean_candidate' AS table_name, 'values_reconcile' AS check_name, CASE WHEN value_mismatches = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '= 0' AS expected, CAST(value_mismatches AS STRING) AS actual FROM edu_access.`03-silver`.deped_psgc_coordinates_gate_summary_candidate
  UNION ALL SELECT batch_id, 'edu_access.03-silver.deped_psgc_coordinates_clean_candidate' AS table_name, 'coordinates_reconcile' AS check_name, CASE WHEN coordinate_mismatches = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '= 0' AS expected, CAST(coordinate_mismatches AS STRING) AS actual FROM edu_access.`03-silver`.deped_psgc_coordinates_gate_summary_candidate
  UNION ALL SELECT batch_id, 'edu_access.03-silver.deped_psgc_coordinates_clean_candidate' AS table_name, 'school_id_unique' AS check_name, CASE WHEN duplicate_clean_ids = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '= 0' AS expected, CAST(duplicate_clean_ids AS STRING) AS actual FROM edu_access.`03-silver`.deped_psgc_coordinates_gate_summary_candidate
  UNION ALL SELECT batch_id, 'edu_access.03-silver.deped_psgc_coordinates_clean_candidate' AS table_name, 'school_id_format' AS check_name, CASE WHEN malformed_clean_ids = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '= 0' AS expected, CAST(malformed_clean_ids AS STRING) AS actual FROM edu_access.`03-silver`.deped_psgc_coordinates_gate_summary_candidate
  UNION ALL SELECT batch_id, 'edu_access.03-silver.deped_psgc_coordinates_clean_candidate' AS table_name, 'codes_ten_digits' AS check_name, CASE WHEN codes_not_ten_digits = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '= 0' AS expected, CAST(codes_not_ten_digits AS STRING) AS actual FROM edu_access.`03-silver`.deped_psgc_coordinates_gate_summary_candidate
  UNION ALL SELECT batch_id, 'edu_access.03-silver.deped_psgc_coordinates_clean_candidate' AS table_name, 'code_values_recognized' AS check_name, CASE WHEN unrecognized_code_values = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '= 0' AS expected, CAST(unrecognized_code_values AS STRING) AS actual FROM edu_access.`03-silver`.deped_psgc_coordinates_gate_summary_candidate
  UNION ALL SELECT batch_id, 'edu_access.03-silver.deped_psgc_coordinates_clean_candidate' AS table_name, 'region_province_values_recognized' AS check_name, CASE WHEN unrecognized_region_province = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '= 0' AS expected, CAST(unrecognized_region_province AS STRING) AS actual FROM edu_access.`03-silver`.deped_psgc_coordinates_gate_summary_candidate
  UNION ALL SELECT batch_id, 'edu_access.03-silver.deped_psgc_coordinates_clean_candidate' AS table_name, 'null_reason_matches_code' AS check_name, CASE WHEN null_reason_mismatches = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '= 0' AS expected, CAST(null_reason_mismatches AS STRING) AS actual FROM edu_access.`03-silver`.deped_psgc_coordinates_gate_summary_candidate
  UNION ALL SELECT batch_id, 'edu_access.03-silver.deped_psgc_coordinates_clean_candidate' AS table_name, 'null_reasons_agree' AS check_name, CASE WHEN null_reasons_differ = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '= 0' AS expected, CAST(null_reasons_differ AS STRING) AS actual FROM edu_access.`03-silver`.deped_psgc_coordinates_gate_summary_candidate
  UNION ALL SELECT batch_id, 'edu_access.03-silver.deped_psgc_coordinates_clean_candidate' AS table_name, 'levels_null_together' AS check_name, CASE WHEN levels_not_null_together = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '= 0' AS expected, CAST(levels_not_null_together AS STRING) AS actual FROM edu_access.`03-silver`.deped_psgc_coordinates_gate_summary_candidate
  UNION ALL SELECT batch_id, 'edu_access.03-silver.deped_psgc_coordinates_clean_candidate' AS table_name, 'coordinates_in_pairs' AS check_name, CASE WHEN coordinates_not_in_pairs = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '= 0' AS expected, CAST(coordinates_not_in_pairs AS STRING) AS actual FROM edu_access.`03-silver`.deped_psgc_coordinates_gate_summary_candidate
  UNION ALL SELECT batch_id, 'edu_access.03-silver.deped_psgc_coordinates_clean_candidate' AS table_name, 'coordinate_values_recognized' AS check_name, CASE WHEN unrecognized_coordinates = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '= 0' AS expected, CAST(unrecognized_coordinates AS STRING) AS actual FROM edu_access.`03-silver`.deped_psgc_coordinates_gate_summary_candidate
  UNION ALL SELECT batch_id, 'edu_access.03-silver.deped_psgc_coordinates_clean_candidate' AS table_name, 'lineage_complete' AS check_name, CASE WHEN missing_lineage = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '= 0' AS expected, CAST(missing_lineage AS STRING) AS actual FROM edu_access.`03-silver`.deped_psgc_coordinates_gate_summary_candidate
  UNION ALL SELECT batch_id, 'edu_access.03-silver.deped_psgc_coordinates_clean_candidate' AS table_name, 'rows_built_by_this_run' AS check_name, CASE WHEN other_run_rows = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '= 0' AS expected, CAST(other_run_rows AS STRING) AS actual FROM edu_access.`03-silver`.deped_psgc_coordinates_gate_summary_candidate
  UNION ALL SELECT batch_id, 'edu_access.03-silver.deped_psgc_coordinates_clean_candidate' AS table_name, 'rows_in_scope' AS check_name, CASE WHEN out_of_scope_clean_rows = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '= 0' AS expected, CAST(out_of_scope_clean_rows AS STRING) AS actual FROM edu_access.`03-silver`.deped_psgc_coordinates_gate_summary_candidate
  UNION ALL SELECT batch_id, 'edu_access.03-silver.deped_psgc_coordinates_clean_candidate' AS table_name, 'profiled_bronze_unit_rows' AS check_name, CASE WHEN bronze_unit_rows = 47818 THEN 'PASS' ELSE 'WARN' END AS status, '47818' AS expected, CAST(bronze_unit_rows AS STRING) AS actual FROM edu_access.`03-silver`.deped_psgc_coordinates_gate_summary_candidate
  UNION ALL SELECT batch_id, 'edu_access.03-silver.deped_psgc_coordinates_clean_candidate' AS table_name, 'profiled_bronze_other_rows' AS check_name, CASE WHEN bronze_other_rows = 0 THEN 'PASS' ELSE 'WARN' END AS status, '0' AS expected, CAST(bronze_other_rows AS STRING) AS actual FROM edu_access.`03-silver`.deped_psgc_coordinates_gate_summary_candidate
  UNION ALL SELECT batch_id, 'edu_access.03-silver.deped_psgc_coordinates_clean_candidate' AS table_name, 'profiled_barangay_codes_padded' AS check_name, CASE WHEN barangay_codes_padded = 28811 THEN 'PASS' ELSE 'WARN' END AS status, '28811' AS expected, CAST(barangay_codes_padded AS STRING) AS actual FROM edu_access.`03-silver`.deped_psgc_coordinates_gate_summary_candidate
  UNION ALL SELECT batch_id, 'edu_access.03-silver.deped_psgc_coordinates_clean_candidate' AS table_name, 'profiled_city_source_na' AS check_name, CASE WHEN city_source_na = 204 THEN 'PASS' ELSE 'WARN' END AS status, '204' AS expected, CAST(city_source_na AS STRING) AS actual FROM edu_access.`03-silver`.deped_psgc_coordinates_gate_summary_candidate
  UNION ALL SELECT batch_id, 'edu_access.03-silver.deped_psgc_coordinates_clean_candidate' AS table_name, 'profiled_city_not_in_workbook' AS check_name, CASE WHEN city_not_in_workbook = 0 THEN 'PASS' ELSE 'WARN' END AS status, '0' AS expected, CAST(city_not_in_workbook AS STRING) AS actual FROM edu_access.`03-silver`.deped_psgc_coordinates_gate_summary_candidate
  UNION ALL SELECT batch_id, 'edu_access.03-silver.deped_psgc_coordinates_clean_candidate' AS table_name, 'profiled_barangay_source_na' AS check_name, CASE WHEN barangay_source_na = 204 THEN 'PASS' ELSE 'WARN' END AS status, '204' AS expected, CAST(barangay_source_na AS STRING) AS actual FROM edu_access.`03-silver`.deped_psgc_coordinates_gate_summary_candidate
  UNION ALL SELECT batch_id, 'edu_access.03-silver.deped_psgc_coordinates_clean_candidate' AS table_name, 'profiled_barangay_not_in_workbook' AS check_name, CASE WHEN barangay_not_in_workbook = 0 THEN 'PASS' ELSE 'WARN' END AS status, '0' AS expected, CAST(barangay_not_in_workbook AS STRING) AS actual FROM edu_access.`03-silver`.deped_psgc_coordinates_gate_summary_candidate
  UNION ALL SELECT batch_id, 'edu_access.03-silver.deped_psgc_coordinates_clean_candidate' AS table_name, 'profiled_recoded' AS check_name, CASE WHEN recoded = 446 THEN 'PASS' ELSE 'WARN' END AS status, '446' AS expected, CAST(recoded AS STRING) AS actual FROM edu_access.`03-silver`.deped_psgc_coordinates_gate_summary_candidate
  UNION ALL SELECT batch_id, 'edu_access.03-silver.deped_psgc_coordinates_clean_candidate' AS table_name, 'profiled_barangay_outside_city' AS check_name, CASE WHEN barangay_outside_city = 2 THEN 'PASS' ELSE 'WARN' END AS status, '2' AS expected, CAST(barangay_outside_city AS STRING) AS actual FROM edu_access.`03-silver`.deped_psgc_coordinates_gate_summary_candidate
  UNION ALL SELECT batch_id, 'edu_access.03-silver.deped_psgc_coordinates_clean_candidate' AS table_name, 'profiled_coordinate_missing' AS check_name, CASE WHEN coordinate_missing = 679 THEN 'PASS' ELSE 'WARN' END AS status, '679' AS expected, CAST(coordinate_missing AS STRING) AS actual FROM edu_access.`03-silver`.deped_psgc_coordinates_gate_summary_candidate
  UNION ALL SELECT batch_id, 'edu_access.03-silver.deped_psgc_coordinates_clean_candidate' AS table_name, 'profiled_coordinate_zero' AS check_name, CASE WHEN coordinate_zero = 5 THEN 'PASS' ELSE 'WARN' END AS status, '5' AS expected, CAST(coordinate_zero AS STRING) AS actual FROM edu_access.`03-silver`.deped_psgc_coordinates_gate_summary_candidate
  UNION ALL SELECT batch_id, 'edu_access.03-silver.deped_psgc_coordinates_clean_candidate' AS table_name, 'profiled_coordinate_outside_philippines' AS check_name, CASE WHEN coordinate_outside_philippines = 54 THEN 'PASS' ELSE 'WARN' END AS status, '54' AS expected, CAST(coordinate_outside_philippines AS STRING) AS actual FROM edu_access.`03-silver`.deped_psgc_coordinates_gate_summary_candidate
  UNION ALL SELECT batch_id, 'edu_access.03-silver.deped_psgc_coordinates_quarantine_candidate' AS table_name, 'profiled_quarantine_school_id_malformed' AS check_name, CASE WHEN quarantine_school_id_malformed = 0 THEN 'PASS' ELSE 'WARN' END AS status, '0' AS expected, CAST(quarantine_school_id_malformed AS STRING) AS actual FROM edu_access.`03-silver`.deped_psgc_coordinates_gate_summary_candidate
  UNION ALL SELECT batch_id, 'edu_access.03-silver.deped_psgc_coordinates_quarantine_candidate' AS table_name, 'profiled_quarantine_school_id_duplicated' AS check_name, CASE WHEN quarantine_school_id_duplicated = 0 THEN 'PASS' ELSE 'WARN' END AS status, '0' AS expected, CAST(quarantine_school_id_duplicated AS STRING) AS actual FROM edu_access.`03-silver`.deped_psgc_coordinates_gate_summary_candidate
  UNION ALL SELECT batch_id, 'edu_access.03-silver.deped_psgc_coordinates_quarantine_candidate' AS table_name, 'profiled_quarantine_school_id_identical_copy' AS check_name, CASE WHEN quarantine_school_id_identical_copy = 0 THEN 'PASS' ELSE 'WARN' END AS status, '0' AS expected, CAST(quarantine_school_id_identical_copy AS STRING) AS actual FROM edu_access.`03-silver`.deped_psgc_coordinates_gate_summary_candidate
  UNION ALL SELECT batch_id, 'edu_access.03-silver.deped_psgc_coordinates_quarantine_candidate' AS table_name, 'profiled_quarantine_school_year_out_of_scope' AS check_name, CASE WHEN quarantine_school_year_out_of_scope = 0 THEN 'PASS' ELSE 'WARN' END AS status, '0' AS expected, CAST(quarantine_school_year_out_of_scope AS STRING) AS actual FROM edu_access.`03-silver`.deped_psgc_coordinates_gate_summary_candidate
  UNION ALL SELECT batch_id, 'edu_access.03-silver.deped_psgc_coordinates_quarantine_candidate' AS table_name, 'profiled_quarantine_sector_not_public' AS check_name, CASE WHEN quarantine_sector_not_public = 0 THEN 'PASS' ELSE 'WARN' END AS status, '0' AS expected, CAST(quarantine_sector_not_public AS STRING) AS actual FROM edu_access.`03-silver`.deped_psgc_coordinates_gate_summary_candidate
  UNION ALL SELECT batch_id, 'edu_access.03-silver.deped_psgc_coordinates_quarantine_candidate', 'quarantine_rate', CASE WHEN quarantine_rows = 0 THEN 'PASS' WHEN quarantine_rows * 100 > bronze_unit_rows * 1 THEN 'FAIL' ELSE 'WARN' END, '0 (FAIL above 1% of ' || CAST(bronze_unit_rows AS STRING) || ')', CAST(quarantine_rows AS STRING) FROM edu_access.`03-silver`.deped_psgc_coordinates_gate_summary_candidate
) AS results;

MERGE INTO edu_access.`01-control`.pipeline_runs AS t USING (SELECT :run_id AS run_id, COUNT_IF(status = 'FAIL') AS fails FROM edu_access.`01-control`.data_quality_results WHERE run_id = :run_id AND source_id = 'deped_psgc_coordinates' AND layer = 'silver' AND checked_at_utc >= session.silver_gate_started_at_utc) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'silver_build' AND t.source_id = 'deped_psgc_coordinates' WHEN MATCHED AND s.fails > 0 THEN UPDATE SET status = 'failed', finished_at_utc = current_timestamp(), failure_stage = 'gate', error_message = CAST(s.fails AS STRING) || ' FAIL result(s) in data_quality_results';

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Silver gate failed for deped_psgc_coordinates: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s)') END FROM edu_access.`01-control`.data_quality_results WHERE run_id = :run_id AND source_id = 'deped_psgc_coordinates' AND layer = 'silver' AND status = 'FAIL' AND checked_at_utc >= session.silver_gate_started_at_utc;

CREATE OR REPLACE TABLE edu_access.`03-silver`.deped_psgc_coordinates_quarantine USING DELTA AS SELECT * FROM edu_access.`03-silver`.deped_psgc_coordinates_quarantine_candidate;
ALTER TABLE edu_access.`03-silver`.deped_psgc_coordinates_quarantine OWNER TO `reached-hq`;

CREATE OR REPLACE TABLE edu_access.`03-silver`.deped_psgc_coordinates_clean USING DELTA AS SELECT * FROM edu_access.`03-silver`.deped_psgc_coordinates_clean_candidate;
ALTER TABLE edu_access.`03-silver`.deped_psgc_coordinates_clean OWNER TO `reached-hq`;

MERGE INTO edu_access.`01-control`.pipeline_runs AS t USING (SELECT :run_id AS run_id) AS s ON t.run_id = s.run_id AND t.pipeline_name = 'silver_build' AND t.source_id = 'deped_psgc_coordinates' WHEN MATCHED THEN UPDATE SET status = 'succeeded', finished_at_utc = current_timestamp(), failure_stage = NULL, error_message = NULL;

DROP TABLE IF EXISTS edu_access.`03-silver`.deped_psgc_coordinates_gate_summary_candidate;
