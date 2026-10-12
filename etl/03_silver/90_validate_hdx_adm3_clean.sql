-- Silver gate for hdx_boundaries. Generated from config/ingestion/hdx_boundaries.json
-- and config/mappings/hdx_boundaries.json by src/silver/hdx_boundaries.py:
--   python -m src.silver.cli gate --source hdx_boundaries > etl/03_silver/90_validate_hdx_adm3_clean.sql
-- Do not edit by hand; tests/test_silver_hdx.py fails if it differs.
--
-- The job task after the Silver build. It checks the candidate tables the build wrote, one row
-- per check in data_quality_results: the whole build, then each current batch. On any FAIL it
-- records the run 'failed' and stops the task before publishing, so the Silver tables keep the
-- last build that passed and nothing downstream runs. Otherwise it copies the candidates to the
-- Silver tables and records the run 'succeeded'. PASS: as expected. WARN: recorded, the build is
-- published (invalid shapes, centres outside their shape, broken code chains, quarantined rows).
-- FAIL: the candidate cannot be trusted. Results hold counts, never row values.
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
SELECT :run_id, batch_id, 'hdx_boundaries', 'silver', table_name, check_name, status, expected, actual,
       current_timestamp(), :code_revision
FROM (
WITH cur AS (
  SELECT batch_id FROM edu_access.`01-control`.current_batches WHERE source_id = 'hdx_boundaries'
),
bronze AS (
  SELECT r.* FROM edu_access.`02-bronze`.hdx_adm3_raw AS r JOIN cur ON r.batch_id = cur.batch_id
),
clean AS (SELECT * FROM edu_access.`03-silver`.hdx_adm3_clean_candidate),
quarantined AS (SELECT * FROM edu_access.`03-silver`.hdx_adm3_quarantine_candidate),
-- Current Bronze features, each marked if Silver set it aside.
b AS (
  SELECT bronze.*, q.source_row_number IS NOT NULL AS in_quarantine
  FROM bronze
  LEFT JOIN quarantined AS q
    ON bronze.source_sha256 = q.source_sha256 AND bronze.source_row_number = q.source_row_number
),
-- A quarantined row has no clean value, so its labels are checked against the reviewed rules here:
-- a row set aside for another reason must not let an unmapped label through.
bronze_batches AS (
  SELECT
    b.batch_id,
    COUNT(*) AS bronze_rows,
    COUNT_IF(
        TRIM(regexp_replace(translate(b.`adm3_name`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`adm3_name`
        OR TRIM(regexp_replace(translate(b.`adm3_name1`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`adm3_name1`
        OR TRIM(regexp_replace(translate(b.`adm3_name2`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`adm3_name2`
        OR TRIM(regexp_replace(translate(b.`adm3_name3`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`adm3_name3`
        OR TRIM(regexp_replace(translate(b.`adm2_name`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`adm2_name`
        OR TRIM(regexp_replace(translate(b.`adm2_name1`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`adm2_name1`
        OR TRIM(regexp_replace(translate(b.`adm2_name2`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`adm2_name2`
        OR TRIM(regexp_replace(translate(b.`adm2_name3`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`adm2_name3`
        OR TRIM(regexp_replace(translate(b.`adm1_name`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`adm1_name`
        OR TRIM(regexp_replace(translate(b.`adm1_name1`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`adm1_name1`
        OR TRIM(regexp_replace(translate(b.`adm1_name2`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`adm1_name2`
        OR TRIM(regexp_replace(translate(b.`adm1_name3`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`adm1_name3`
        OR TRIM(regexp_replace(translate(b.`adm0_name`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`adm0_name`
        OR TRIM(regexp_replace(translate(b.`adm0_name1`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`adm0_name1`
        OR TRIM(regexp_replace(translate(b.`adm0_name2`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`adm0_name2`
        OR TRIM(regexp_replace(translate(b.`adm0_name3`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`adm0_name3`
        OR TRIM(regexp_replace(translate(b.`version`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`version`
        OR TRIM(regexp_replace(translate(b.`lang`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`lang`
        OR TRIM(regexp_replace(translate(b.`lang1`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`lang1`
        OR TRIM(regexp_replace(translate(b.`lang2`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`lang2`
        OR TRIM(regexp_replace(translate(b.`lang3`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`lang3`
        OR TRIM(regexp_replace(translate(b.`adm3_ref_name`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`adm3_ref_name`
      ) AS whitespace_rows,
    COUNT_IF(
        TRIM(regexp_replace(translate(b.`adm3_name`, chr(9) || chr(160), '  '), ' +', ' ')) = ''
        OR TRIM(regexp_replace(translate(b.`adm3_name1`, chr(9) || chr(160), '  '), ' +', ' ')) = ''
        OR TRIM(regexp_replace(translate(b.`adm3_name2`, chr(9) || chr(160), '  '), ' +', ' ')) = ''
        OR TRIM(regexp_replace(translate(b.`adm3_name3`, chr(9) || chr(160), '  '), ' +', ' ')) = ''
        OR TRIM(regexp_replace(translate(b.`adm2_name`, chr(9) || chr(160), '  '), ' +', ' ')) = ''
        OR TRIM(regexp_replace(translate(b.`adm2_name1`, chr(9) || chr(160), '  '), ' +', ' ')) = ''
        OR TRIM(regexp_replace(translate(b.`adm2_name2`, chr(9) || chr(160), '  '), ' +', ' ')) = ''
        OR TRIM(regexp_replace(translate(b.`adm2_name3`, chr(9) || chr(160), '  '), ' +', ' ')) = ''
        OR TRIM(regexp_replace(translate(b.`adm1_name`, chr(9) || chr(160), '  '), ' +', ' ')) = ''
        OR TRIM(regexp_replace(translate(b.`adm1_name1`, chr(9) || chr(160), '  '), ' +', ' ')) = ''
        OR TRIM(regexp_replace(translate(b.`adm1_name2`, chr(9) || chr(160), '  '), ' +', ' ')) = ''
        OR TRIM(regexp_replace(translate(b.`adm1_name3`, chr(9) || chr(160), '  '), ' +', ' ')) = ''
        OR TRIM(regexp_replace(translate(b.`adm0_name`, chr(9) || chr(160), '  '), ' +', ' ')) = ''
        OR TRIM(regexp_replace(translate(b.`adm0_name1`, chr(9) || chr(160), '  '), ' +', ' ')) = ''
        OR TRIM(regexp_replace(translate(b.`adm0_name2`, chr(9) || chr(160), '  '), ' +', ' ')) = ''
        OR TRIM(regexp_replace(translate(b.`adm0_name3`, chr(9) || chr(160), '  '), ' +', ' ')) = ''
        OR TRIM(regexp_replace(translate(b.`version`, chr(9) || chr(160), '  '), ' +', ' ')) = ''
        OR TRIM(regexp_replace(translate(b.`lang`, chr(9) || chr(160), '  '), ' +', ' ')) = ''
        OR TRIM(regexp_replace(translate(b.`lang1`, chr(9) || chr(160), '  '), ' +', ' ')) = ''
        OR TRIM(regexp_replace(translate(b.`lang2`, chr(9) || chr(160), '  '), ' +', ' ')) = ''
        OR TRIM(regexp_replace(translate(b.`lang3`, chr(9) || chr(160), '  '), ' +', ' ')) = ''
        OR TRIM(regexp_replace(translate(b.`adm3_ref_name`, chr(9) || chr(160), '  '), ' +', ' ')) = ''
      ) AS blank_text_rows,
    COUNT_IF(b.in_quarantine AND TRIM(regexp_replace(translate(b.`adm1_name`, chr(9) || chr(160), '  '), ' +', ' ')) <> ''
        AND TRIM(regexp_replace(translate(b.`adm1_name`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('Bangsamoro Autonomous Region In Muslim Mindanao (BARMM)', 'Cordillera Administrative Region (CAR)', 'Mimaropa Region', 'National Capital Region (NCR)', 'Region I (Ilocos Region)', 'Region II (Cagayan Valley)', 'Region III (Central Luzon)', 'Region IV-A (Calabarzon)', 'Region IX (Zamboanga Peninsula)', 'Region V (Bicol Region)', 'Region VI (Western Visayas)', 'Region VII (Central Visayas)', 'Region VIII (Eastern Visayas)', 'Region X (Northern Mindanao)', 'Region XI (Davao Region)', 'Region XII (Soccsksargen)', 'Region XIII (Caraga)')) AS quarantined_unmapped_adm1_name,
    COUNT_IF(b.in_quarantine AND TRIM(regexp_replace(translate(b.`adm0_name`, chr(9) || chr(160), '  '), ' +', ' ')) <> ''
        AND TRIM(regexp_replace(translate(b.`adm0_name`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('Philippines')) AS quarantined_unmapped_adm0_name,
    COUNT_IF(b.in_quarantine AND TRIM(regexp_replace(translate(b.`version`, chr(9) || chr(160), '  '), ' +', ' ')) <> ''
        AND TRIM(regexp_replace(translate(b.`version`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('v03')) AS quarantined_unmapped_version,
    COUNT_IF(b.in_quarantine AND TRIM(regexp_replace(translate(b.`lang`, chr(9) || chr(160), '  '), ' +', ' ')) <> ''
        AND TRIM(regexp_replace(translate(b.`lang`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('en')) AS quarantined_unmapped_lang
  FROM b GROUP BY b.batch_id
),
-- Each clean row beside its Bronze feature, the geometry parsed again: the build is checked, not trusted.
g AS (
  SELECT c.source_sha256, c.source_row_number, try_to_geometry(c.geometry) AS geo FROM clean AS c
),
clean_batches AS (
  SELECT
    c.batch_id,
    COUNT(*) AS clean_rows,
    COUNT(DISTINCT c.adm3_pcode) AS clean_ids,
    COUNT_IF(c.adm3_pcode IS NULL OR NOT regexp_like(c.adm3_pcode, '^PH[0-9]{7}$')) AS invalid_ids,
    COUNT_IF(b.source_row_number IS NULL
        OR c.adm3_pcode IS DISTINCT FROM b.`adm3_pcode`
        OR c.adm2_pcode IS DISTINCT FROM b.`adm2_pcode`
        OR c.adm1_pcode IS DISTINCT FROM b.`adm1_pcode`
        OR c.adm0_pcode IS DISTINCT FROM b.`adm0_pcode`
      ) AS changed_codes,
    COUNT_IF(b.source_row_number IS NULL OR c.geometry IS DISTINCT FROM b.`geometry`) AS changed_geometry,
    COUNT_IF(
        (c.adm3_name IS NULL AND TRIM(regexp_replace(translate(b.`adm3_name`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.adm3_name1 IS NULL AND TRIM(regexp_replace(translate(b.`adm3_name1`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.adm3_name2 IS NULL AND TRIM(regexp_replace(translate(b.`adm3_name2`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.adm3_name3 IS NULL AND TRIM(regexp_replace(translate(b.`adm3_name3`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.adm2_name IS NULL AND TRIM(regexp_replace(translate(b.`adm2_name`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.adm2_name1 IS NULL AND TRIM(regexp_replace(translate(b.`adm2_name1`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.adm2_name2 IS NULL AND TRIM(regexp_replace(translate(b.`adm2_name2`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.adm2_name3 IS NULL AND TRIM(regexp_replace(translate(b.`adm2_name3`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.adm2_pcode IS NULL AND NOT (b.`adm2_pcode` IS NULL OR b.`adm2_pcode` = ''))
        OR (c.adm1_name1 IS NULL AND TRIM(regexp_replace(translate(b.`adm1_name1`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.adm1_name2 IS NULL AND TRIM(regexp_replace(translate(b.`adm1_name2`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.adm1_name3 IS NULL AND TRIM(regexp_replace(translate(b.`adm1_name3`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.adm1_pcode IS NULL AND NOT (b.`adm1_pcode` IS NULL OR b.`adm1_pcode` = ''))
        OR (c.adm0_name1 IS NULL AND TRIM(regexp_replace(translate(b.`adm0_name1`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.adm0_name2 IS NULL AND TRIM(regexp_replace(translate(b.`adm0_name2`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.adm0_name3 IS NULL AND TRIM(regexp_replace(translate(b.`adm0_name3`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.adm0_pcode IS NULL AND NOT (b.`adm0_pcode` IS NULL OR b.`adm0_pcode` = ''))
        OR (c.valid_on IS NULL AND NOT (b.`valid_on` IS NULL OR b.`valid_on` = ''))
        OR (c.valid_to IS NULL AND NOT (b.`valid_to` IS NULL OR b.`valid_to` = ''))
        OR (c.area_sqkm IS NULL AND NOT (b.`area_sqkm` IS NULL OR b.`area_sqkm` = ''))
        OR (c.lang1 IS NULL AND TRIM(regexp_replace(translate(b.`lang1`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.lang2 IS NULL AND TRIM(regexp_replace(translate(b.`lang2`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.lang3 IS NULL AND TRIM(regexp_replace(translate(b.`lang3`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.adm3_ref_name IS NULL AND TRIM(regexp_replace(translate(b.`adm3_ref_name`, chr(9) || chr(160), '  '), ' +', ' ')) <> '')
        OR (c.center_lat IS NULL AND NOT (b.`center_lat` IS NULL OR b.`center_lat` = ''))
        OR (c.center_lon IS NULL AND NOT (b.`center_lon` IS NULL OR b.`center_lon` = ''))
      ) AS lost_values,
    COUNT_IF(c.valid_on IS NULL OR c.valid_on <> TRY_CAST(b.school_year AS DATE)) AS off_reference_rows,
    COUNT_IF(g.geo IS NULL) AS unparsed_rows,
    COUNT_IF(g.geo IS NOT NULL AND upper(replace(CAST(st_geometrytype(g.geo) AS STRING), 'ST_', '')) NOT IN ('POLYGON', 'MULTIPOLYGON')) AS wrong_type_rows,
    COUNT_IF(g.geo IS NOT NULL AND st_isempty(g.geo)) AS empty_rows,
    COUNT_IF(c.area_sqkm <= 0) AS not_positive_area_sqkm,
    COUNT_IF(
        c.hierarchy_consistent IS DISTINCT FROM COALESCE(regexp_like(c.adm2_pcode, '^PH[0-9]{5}$')
        AND regexp_like(c.adm1_pcode, '^PH[0-9]{2}$')
        AND regexp_like(c.adm0_pcode, '^PH$')
        AND substr(c.adm3_pcode, 1, length(c.adm2_pcode)) = c.adm2_pcode
        AND substr(c.adm2_pcode, 1, length(c.adm1_pcode)) = c.adm1_pcode, FALSE)
        OR c.geometry_is_valid IS DISTINCT FROM COALESCE(st_isvalid(g.geo), FALSE)
        OR c.center_inside_geometry IS DISTINCT FROM COALESCE(st_contains(g.geo, try_to_geometry(concat('{"type": "Point", "coordinates": [', b.`center_lon`, ', ', b.`center_lat`, ']}'))), FALSE)
      ) AS inconsistent_flags,
    COUNT_IF(c.adm1_name IS NULL AND TRIM(regexp_replace(translate(b.`adm1_name`, chr(9) || chr(160), '  '), ' +', ' ')) <> '') AS unmapped_adm1_name,
    COUNT_IF(c.adm0_name IS NULL AND TRIM(regexp_replace(translate(b.`adm0_name`, chr(9) || chr(160), '  '), ' +', ' ')) <> '') AS unmapped_adm0_name,
    COUNT_IF(c.version IS NULL AND TRIM(regexp_replace(translate(b.`version`, chr(9) || chr(160), '  '), ' +', ' ')) <> '') AS unmapped_version,
    COUNT_IF(c.lang IS NULL AND TRIM(regexp_replace(translate(b.`lang`, chr(9) || chr(160), '  '), ' +', ' ')) <> '') AS unmapped_lang,
    COUNT_IF(NOT c.geometry_is_valid) AS invalid_geometry_rows,
    COUNT_IF(NOT c.center_inside_geometry) AS center_outside_rows,
    COUNT_IF(NOT c.hierarchy_consistent) AS hierarchy_broken_rows
  FROM clean AS c
  LEFT JOIN b ON b.source_sha256 = c.source_sha256 AND b.source_row_number = c.source_row_number
  LEFT JOIN g ON g.source_sha256 = c.source_sha256 AND g.source_row_number = c.source_row_number
  GROUP BY c.batch_id
),
quarantine_batches AS (
  SELECT
    q.batch_id,
    COUNT(*) AS quarantined_rows,
    COUNT_IF(array_contains(q.quarantine_reasons, 'adm3_pcode_blank')) AS reason_adm3_pcode_blank,
    COUNT_IF(array_contains(q.quarantine_reasons, 'adm3_pcode_malformed')) AS reason_adm3_pcode_malformed,
    COUNT_IF(array_contains(q.quarantine_reasons, 'adm3_pcode_duplicated')) AS reason_adm3_pcode_duplicated,
    COUNT_IF(array_contains(q.quarantine_reasons, 'valid_on_uncastable')) AS reason_valid_on_uncastable,
    COUNT_IF(array_contains(q.quarantine_reasons, 'valid_to_uncastable')) AS reason_valid_to_uncastable,
    COUNT_IF(array_contains(q.quarantine_reasons, 'area_uncastable')) AS reason_area_uncastable,
    COUNT_IF(array_contains(q.quarantine_reasons, 'area_not_positive')) AS reason_area_not_positive,
    COUNT_IF(array_contains(q.quarantine_reasons, 'center_uncastable')) AS reason_center_uncastable,
    COUNT_IF(array_contains(q.quarantine_reasons, 'geometry_unparseable')) AS reason_geometry_unparseable,
    COUNT_IF(array_contains(q.quarantine_reasons, 'geometry_empty')) AS reason_geometry_empty,
    COUNT_IF(array_contains(q.quarantine_reasons, 'geometry_wrong_type')) AS reason_geometry_wrong_type
  FROM quarantined AS q GROUP BY q.batch_id
),
batches AS (
  SELECT
    y.batch_id,
    COALESCE(bronze_rows, 0) AS bronze_rows,
    COALESCE(whitespace_rows, 0) AS whitespace_rows,
    COALESCE(blank_text_rows, 0) AS blank_text_rows,
    COALESCE(clean_rows, 0) AS clean_rows,
    COALESCE(clean_ids, 0) AS clean_ids,
    COALESCE(invalid_ids, 0) AS invalid_ids,
    COALESCE(changed_codes, 0) AS changed_codes,
    COALESCE(changed_geometry, 0) AS changed_geometry,
    COALESCE(lost_values, 0) AS lost_values,
    COALESCE(off_reference_rows, 0) AS off_reference_rows,
    COALESCE(unparsed_rows, 0) AS unparsed_rows,
    COALESCE(wrong_type_rows, 0) AS wrong_type_rows,
    COALESCE(empty_rows, 0) AS empty_rows,
    COALESCE(not_positive_area_sqkm, 0) AS not_positive_area_sqkm,
    COALESCE(inconsistent_flags, 0) AS inconsistent_flags,
    COALESCE(invalid_geometry_rows, 0) AS invalid_geometry_rows,
    COALESCE(center_outside_rows, 0) AS center_outside_rows,
    COALESCE(hierarchy_broken_rows, 0) AS hierarchy_broken_rows,
    COALESCE(quarantined_rows, 0) AS quarantined_rows,
    COALESCE(reason_adm3_pcode_blank, 0) AS reason_adm3_pcode_blank,
    COALESCE(reason_adm3_pcode_malformed, 0) AS reason_adm3_pcode_malformed,
    COALESCE(reason_adm3_pcode_duplicated, 0) AS reason_adm3_pcode_duplicated,
    COALESCE(reason_valid_on_uncastable, 0) AS reason_valid_on_uncastable,
    COALESCE(reason_valid_to_uncastable, 0) AS reason_valid_to_uncastable,
    COALESCE(reason_area_uncastable, 0) AS reason_area_uncastable,
    COALESCE(reason_area_not_positive, 0) AS reason_area_not_positive,
    COALESCE(reason_center_uncastable, 0) AS reason_center_uncastable,
    COALESCE(reason_geometry_unparseable, 0) AS reason_geometry_unparseable,
    COALESCE(reason_geometry_empty, 0) AS reason_geometry_empty,
    COALESCE(reason_geometry_wrong_type, 0) AS reason_geometry_wrong_type,
    COALESCE(unmapped_adm1_name, 0) + COALESCE(quarantined_unmapped_adm1_name, 0) AS unmapped_adm1_name,
    COALESCE(unmapped_adm0_name, 0) + COALESCE(quarantined_unmapped_adm0_name, 0) AS unmapped_adm0_name,
    COALESCE(unmapped_version, 0) + COALESCE(quarantined_unmapped_version, 0) AS unmapped_version,
    COALESCE(unmapped_lang, 0) + COALESCE(quarantined_unmapped_lang, 0) AS unmapped_lang
  FROM cur AS y
  LEFT JOIN bronze_batches ON bronze_batches.batch_id = y.batch_id
  LEFT JOIN clean_batches ON clean_batches.batch_id = y.batch_id
  LEFT JOIN quarantine_batches ON quarantine_batches.batch_id = y.batch_id
),
found AS (SELECT COUNT(*) AS current_batches FROM cur),
silver_rows AS (
  SELECT batch_id, delivery_version, schema_version, source_sha256, source_row_number, run_id, cleaned_at_utc, code_revision FROM clean
  UNION ALL SELECT batch_id, delivery_version, schema_version, source_sha256, source_row_number, run_id, cleaned_at_utc, code_revision FROM quarantined
),
whole AS (
  SELECT
    COUNT_IF(batch_id IS NULL OR delivery_version IS NULL OR schema_version IS NULL OR source_sha256 IS NULL OR source_row_number IS NULL OR run_id IS NULL OR cleaned_at_utc IS NULL OR code_revision IS NULL) AS missing_lineage,
    COUNT_IF(run_id IS NULL OR run_id <> :run_id) AS other_run_rows,
    COUNT(DISTINCT cleaned_at_utc) AS timestamps
  FROM silver_rows
),
-- Silver rows whose Bronze feature is not in a current batch (an old version, or gone).
unresolved AS (
  SELECT COUNT(*) AS unresolved_rows
  FROM silver_rows AS s
  LEFT JOIN bronze ON s.source_sha256 = bronze.source_sha256 AND s.source_row_number = bronze.source_row_number
  WHERE bronze.source_row_number IS NULL
),
checks AS (
  -- The whole build
  SELECT CAST(NULL AS STRING) AS batch_id, 'edu_access.03-silver.hdx_adm3_clean_candidate' AS table_name, 'current_batches_present' AS check_name,
         CASE WHEN current_batches > 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         'at least 1' AS expected, CAST(current_batches AS STRING) AS actual FROM found
  UNION ALL SELECT CAST(NULL AS STRING) AS batch_id, 'edu_access.03-silver.hdx_adm3_clean_candidate' AS table_name, 'lineage_complete' AS check_name,
         CASE WHEN missing_lineage = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(missing_lineage AS STRING) AS actual FROM whole
  UNION ALL SELECT CAST(NULL AS STRING) AS batch_id, 'edu_access.03-silver.hdx_adm3_clean_candidate' AS table_name, 'rows_resolve_to_current_bronze' AS check_name,
         CASE WHEN unresolved_rows = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(unresolved_rows AS STRING) AS actual FROM unresolved
  UNION ALL SELECT CAST(NULL AS STRING) AS batch_id, 'edu_access.03-silver.hdx_adm3_clean_candidate' AS table_name, 'rows_built_by_this_run' AS check_name,
         CASE WHEN other_run_rows = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(other_run_rows AS STRING) AS actual FROM whole
  UNION ALL SELECT CAST(NULL AS STRING) AS batch_id, 'edu_access.03-silver.hdx_adm3_clean_candidate' AS table_name, 'one_timestamp_per_run' AS check_name,
         CASE WHEN timestamps = 1 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(1 AS STRING) AS expected, CAST(timestamps AS STRING) AS actual FROM whole
  -- Each current batch: reconciliation, the key, published values kept, geometry
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.hdx_adm3_clean_candidate' AS table_name, 'rows_reconcile' AS check_name,
         CASE WHEN clean_rows + quarantined_rows = bronze_rows THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(bronze_rows AS STRING) AS expected, CAST(clean_rows + quarantined_rows AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.hdx_adm3_clean_candidate' AS table_name, 'adm3_pcode_unique' AS check_name,
         CASE WHEN clean_rows - clean_ids = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(clean_rows - clean_ids AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.hdx_adm3_clean_candidate' AS table_name, 'adm3_pcode_valid' AS check_name,
         CASE WHEN invalid_ids = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(invalid_ids AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.hdx_adm3_clean_candidate' AS table_name, 'codes_as_published' AS check_name,
         CASE WHEN changed_codes = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(changed_codes AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.hdx_adm3_clean_candidate' AS table_name, 'geometry_as_published' AS check_name,
         CASE WHEN changed_geometry = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(changed_geometry AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.hdx_adm3_clean_candidate' AS table_name, 'values_kept' AS check_name,
         CASE WHEN lost_values = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(lost_values AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.hdx_adm3_clean_candidate' AS table_name, 'valid_on_is_reference_date' AS check_name,
         CASE WHEN off_reference_rows = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(off_reference_rows AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.hdx_adm3_clean_candidate' AS table_name, 'geometry_parsed' AS check_name,
         CASE WHEN unparsed_rows = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(unparsed_rows AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.hdx_adm3_clean_candidate' AS table_name, 'geometry_type_allowed' AS check_name,
         CASE WHEN wrong_type_rows = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(wrong_type_rows AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.hdx_adm3_clean_candidate' AS table_name, 'geometry_not_empty' AS check_name,
         CASE WHEN empty_rows = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(empty_rows AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.hdx_adm3_clean_candidate' AS table_name, 'area_positive' AS check_name,
         CASE WHEN not_positive_area_sqkm = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(not_positive_area_sqkm AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.hdx_adm3_clean_candidate' AS table_name, 'flags_consistent' AS check_name,
         CASE WHEN inconsistent_flags = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(inconsistent_flags AS STRING) AS actual FROM batches
  -- Each current batch: every label is in the reviewed rules
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.hdx_adm3_clean_candidate' AS table_name, 'labels_mapped_adm1_name' AS check_name,
         CASE WHEN unmapped_adm1_name = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(unmapped_adm1_name AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.hdx_adm3_clean_candidate' AS table_name, 'labels_mapped_adm0_name' AS check_name,
         CASE WHEN unmapped_adm0_name = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(unmapped_adm0_name AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.hdx_adm3_clean_candidate' AS table_name, 'labels_mapped_version' AS check_name,
         CASE WHEN unmapped_version = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(unmapped_version AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.hdx_adm3_clean_candidate' AS table_name, 'labels_mapped_lang' AS check_name,
         CASE WHEN unmapped_lang = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(unmapped_lang AS STRING) AS actual FROM batches
  -- Each current batch: flagged, never repaired (WARN)
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.hdx_adm3_clean_candidate' AS table_name, 'geometry_valid' AS check_name,
         CASE WHEN invalid_geometry_rows = 0 THEN 'PASS' ELSE 'WARN' END AS status,
         '0' AS expected, CAST(invalid_geometry_rows AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.hdx_adm3_clean_candidate' AS table_name, 'center_inside_geometry' AS check_name,
         CASE WHEN center_outside_rows = 0 THEN 'PASS' ELSE 'WARN' END AS status,
         '0' AS expected, CAST(center_outside_rows AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.hdx_adm3_clean_candidate' AS table_name, 'hierarchy_consistent' AS check_name,
         CASE WHEN hierarchy_broken_rows = 0 THEN 'PASS' ELSE 'WARN' END AS status,
         '0' AS expected, CAST(hierarchy_broken_rows AS STRING) AS actual FROM batches
  -- Each current batch: quarantine (WARN above 0, FAIL above 1% of the batch's Bronze rows)
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.hdx_adm3_quarantine_candidate' AS table_name, 'quarantine_rate' AS check_name,
         CASE WHEN quarantined_rows = 0 THEN 'PASS' WHEN quarantined_rows * 100 > bronze_rows * 1 THEN 'FAIL' ELSE 'WARN' END AS status,
         '0 (FAIL above 1% of ' || CAST(bronze_rows AS STRING) || ')' AS expected, CAST(quarantined_rows AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.hdx_adm3_quarantine_candidate' AS table_name, 'quarantine_reason_adm3_pcode_blank' AS check_name,
         CASE WHEN reason_adm3_pcode_blank = 0 THEN 'PASS' ELSE 'WARN' END AS status,
         '0' AS expected, CAST(reason_adm3_pcode_blank AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.hdx_adm3_quarantine_candidate' AS table_name, 'quarantine_reason_adm3_pcode_malformed' AS check_name,
         CASE WHEN reason_adm3_pcode_malformed = 0 THEN 'PASS' ELSE 'WARN' END AS status,
         '0' AS expected, CAST(reason_adm3_pcode_malformed AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.hdx_adm3_quarantine_candidate' AS table_name, 'quarantine_reason_adm3_pcode_duplicated' AS check_name,
         CASE WHEN reason_adm3_pcode_duplicated = 0 THEN 'PASS' ELSE 'WARN' END AS status,
         '0' AS expected, CAST(reason_adm3_pcode_duplicated AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.hdx_adm3_quarantine_candidate' AS table_name, 'quarantine_reason_valid_on_uncastable' AS check_name,
         CASE WHEN reason_valid_on_uncastable = 0 THEN 'PASS' ELSE 'WARN' END AS status,
         '0' AS expected, CAST(reason_valid_on_uncastable AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.hdx_adm3_quarantine_candidate' AS table_name, 'quarantine_reason_valid_to_uncastable' AS check_name,
         CASE WHEN reason_valid_to_uncastable = 0 THEN 'PASS' ELSE 'WARN' END AS status,
         '0' AS expected, CAST(reason_valid_to_uncastable AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.hdx_adm3_quarantine_candidate' AS table_name, 'quarantine_reason_area_uncastable' AS check_name,
         CASE WHEN reason_area_uncastable = 0 THEN 'PASS' ELSE 'WARN' END AS status,
         '0' AS expected, CAST(reason_area_uncastable AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.hdx_adm3_quarantine_candidate' AS table_name, 'quarantine_reason_area_not_positive' AS check_name,
         CASE WHEN reason_area_not_positive = 0 THEN 'PASS' ELSE 'WARN' END AS status,
         '0' AS expected, CAST(reason_area_not_positive AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.hdx_adm3_quarantine_candidate' AS table_name, 'quarantine_reason_center_uncastable' AS check_name,
         CASE WHEN reason_center_uncastable = 0 THEN 'PASS' ELSE 'WARN' END AS status,
         '0' AS expected, CAST(reason_center_uncastable AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.hdx_adm3_quarantine_candidate' AS table_name, 'quarantine_reason_geometry_unparseable' AS check_name,
         CASE WHEN reason_geometry_unparseable = 0 THEN 'PASS' ELSE 'WARN' END AS status,
         '0' AS expected, CAST(reason_geometry_unparseable AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.hdx_adm3_quarantine_candidate' AS table_name, 'quarantine_reason_geometry_empty' AS check_name,
         CASE WHEN reason_geometry_empty = 0 THEN 'PASS' ELSE 'WARN' END AS status,
         '0' AS expected, CAST(reason_geometry_empty AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.hdx_adm3_quarantine_candidate' AS table_name, 'quarantine_reason_geometry_wrong_type' AS check_name,
         CASE WHEN reason_geometry_wrong_type = 0 THEN 'PASS' ELSE 'WARN' END AS status,
         '0' AS expected, CAST(reason_geometry_wrong_type AS STRING) AS actual FROM batches
  -- Each current batch: how many rows each text rule changed (records, always PASS)
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.hdx_adm3_clean_candidate' AS table_name, 'rule_whitespace_normalized' AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(whitespace_rows AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.hdx_adm3_clean_candidate' AS table_name, 'rule_blank_text_to_null' AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(blank_text_rows AS STRING) AS actual FROM batches
)
SELECT * FROM checks
) AS results;

-- A failed build: record it before stopping. The Silver tables are not touched.
MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (
  SELECT :run_id AS run_id, COUNT_IF(status = 'FAIL') AS fails
  FROM edu_access.`01-control`.data_quality_results
  WHERE run_id = :run_id AND source_id = 'hdx_boundaries' AND layer = 'silver'
    AND checked_at_utc >= session.silver_gate_started_at_utc
) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'silver_build' AND t.source_id = 'hdx_boundaries'
WHEN MATCHED AND s.fails > 0 THEN UPDATE SET
  status = 'failed', finished_at_utc = current_timestamp(), failure_stage = 'gate',
  error_message = CAST(s.fails AS STRING) || ' FAIL result(s) in data_quality_results';

-- Stop here, before publishing, if anything failed in this execution.
SELECT CASE WHEN COUNT(*) > 0
            THEN raise_error('Silver gate failed for hdx_boundaries: ' || CAST(COUNT(*) AS STRING)
                             || ' FAIL result(s) in data_quality_results for run ' || :run_id)
       END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'hdx_boundaries' AND layer = 'silver' AND status = 'FAIL'
  AND checked_at_utc >= session.silver_gate_started_at_utc;

-- Every check passed: publish. Quarantine first, then clean, the table Gold reads. Each copy is
-- one atomic Delta commit, but the pair is not, so the run is 'succeeded' only after both. If the
-- task dies in between, the run stays 'running', and Gold trusts a Silver table only when the
-- run_id its rows carry is a succeeded silver_build run (D-025).
CREATE OR REPLACE TABLE edu_access.`03-silver`.hdx_adm3_quarantine USING DELTA AS
SELECT * FROM edu_access.`03-silver`.hdx_adm3_quarantine_candidate;

ALTER TABLE edu_access.`03-silver`.hdx_adm3_quarantine OWNER TO `reached-hq`;

CREATE OR REPLACE TABLE edu_access.`03-silver`.hdx_adm3_clean USING DELTA AS
SELECT * FROM edu_access.`03-silver`.hdx_adm3_clean_candidate;

ALTER TABLE edu_access.`03-silver`.hdx_adm3_clean OWNER TO `reached-hq`;

-- Published: the run succeeded.
MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (SELECT :run_id AS run_id) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'silver_build' AND t.source_id = 'hdx_boundaries'
WHEN MATCHED THEN UPDATE SET
  status = 'succeeded', finished_at_utc = current_timestamp(), failure_stage = NULL, error_message = NULL;
