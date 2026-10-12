-- Silver gate for psa_psgc. Generated from config/ingestion/psa_psgc.json
-- and config/mappings/psa_psgc.json by src/silver/psa_psgc.py:
--   python -m src.silver.cli gate --source psa_psgc > etl/03_silver/90_validate_psa_psgc_clean.sql
-- Do not edit by hand; tests/test_silver_psgc.py fails if it differs.
--
-- The job task after the Silver build. It checks the candidate tables the build wrote, one row
-- per check in data_quality_results: the whole build, then each current batch (one per quarter).
-- On any FAIL it records the run 'failed' and stops the task before publishing, so the Silver
-- tables keep the last build that passed and nothing downstream runs. Otherwise it copies the
-- candidates to the Silver tables and records the run 'succeeded'. PASS: as expected. WARN:
-- recorded, the build is published (quarantined rows). FAIL: the candidate cannot be trusted,
-- including any repeated PSGC code (D-019). Results hold counts, never row values.
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
SELECT :run_id, batch_id, 'psa_psgc', 'silver', table_name, check_name, status, expected, actual,
       current_timestamp(), :code_revision
FROM (
WITH cur AS (
  SELECT batch_id, school_year AS publication_period FROM edu_access.`01-control`.current_batches WHERE source_id = 'psa_psgc'
),
bronze AS (
  SELECT r.* FROM edu_access.`02-bronze`.psa_psgc_raw AS r JOIN cur ON r.batch_id = cur.batch_id
),
clean AS (SELECT * FROM edu_access.`03-silver`.psa_psgc_clean_candidate),
quarantined AS (SELECT * FROM edu_access.`03-silver`.psa_psgc_quarantine_candidate),
-- The codes Silver publishes, per batch: a parent must be one of them.
regions AS (SELECT batch_id, psgc_code FROM clean WHERE geographic_level = 'Reg'),
codes AS (SELECT batch_id, psgc_code FROM clean),
bronze_batches AS (
  SELECT
    b.batch_id,
    COUNT(*) AS bronze_rows,
    COUNT_IF(TRIM(regexp_replace(translate(b.`name`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`name` OR TRIM(regexp_replace(translate(b.`old_names`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`old_names` OR TRIM(regexp_replace(translate(b.`column_j_footnote`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`column_j_footnote`) AS whitespace_rows,
    COUNT_IF(b.`population` IN ('#N/A')) AS marker_rows,
    COUNT_IF(b.`population` = '') AS blank_population_rows,
    COUNT_IF(NULLIF(TRIM(regexp_replace(translate(b.`income_classification`, chr(9) || chr(160), '  '), ' +', ' ')), '') IN ('2nd*', '3rd*', '4th*')) AS starred_rows,
    SUM(CASE WHEN NULLIF(TRIM(regexp_replace(translate(b.`urban_rural`, chr(9) || chr(160), '  '), ' +', ' ')), '') IN ('-') THEN 1 ELSE 0 END + CASE WHEN NULLIF(TRIM(regexp_replace(translate(b.`income_classification`, chr(9) || chr(160), '  '), ' +', ' ')), '') IN ('-') THEN 1 ELSE 0 END) AS placeholder_cells
  FROM bronze AS b
  GROUP BY b.batch_id
),
-- Each clean row beside its Bronze row and its parents.
clean_batches AS (
  SELECT
    c.batch_id,
    COUNT(*) AS clean_rows,
    COUNT(DISTINCT c.psgc_code) AS clean_codes,
    COUNT_IF(c.psgc_code IS NULL OR NOT regexp_like(c.psgc_code, '^[0-9]{10}$')) AS invalid_codes,
    COUNT_IF(b.source_row_number IS NULL OR NOT (c.psgc_code IS NOT DISTINCT FROM b.`psgc_code`)) AS mismatched_psgc_code,
    COUNT_IF(b.source_row_number IS NULL OR NOT (c.name IS NOT DISTINCT FROM NULLIF(TRIM(regexp_replace(translate(b.name, chr(9) || chr(160), '  '), ' +', ' ')), ''))) AS mismatched_name,
    COUNT_IF(b.source_row_number IS NULL OR NOT (c.old_names IS NOT DISTINCT FROM NULLIF(TRIM(regexp_replace(translate(b.old_names, chr(9) || chr(160), '  '), ' +', ' ')), ''))) AS mismatched_old_names,
    COUNT_IF(b.source_row_number IS NULL OR NOT (c.population_footnote IS NOT DISTINCT FROM NULLIF(TRIM(regexp_replace(translate(b.column_j_footnote, chr(9) || chr(160), '  '), ' +', ' ')), ''))) AS mismatched_population_footnote,
    COUNT_IF(b.source_row_number IS NULL OR NOT (c.correspondence_code IS NOT DISTINCT FROM NULLIF(b.`correspondence_code`, ''))) AS mismatched_correspondence_code,
    COUNT_IF(b.source_row_number IS NULL OR NOT (c.publication_period IS NOT DISTINCT FROM b.publication_period)) AS mismatched_publication_period,
    COUNT_IF(b.source_row_number IS NULL OR NOT (c.publication_date IS NOT DISTINCT FROM CAST(b.publication_date AS DATE))) AS mismatched_publication_date,
    COUNT_IF(b.source_row_number IS NULL OR NOT (c.is_master_reference IS NOT DISTINCT FROM COALESCE(b.publication_period = '2026-Q2', FALSE))) AS mismatched_is_master_reference,
    COUNT_IF(b.source_row_number IS NULL OR NOT (c.geographic_level IS NOT DISTINCT FROM CASE NULLIF(TRIM(regexp_replace(translate(b.`geographic_level`, chr(9) || chr(160), '  '), ' +', ' ')), '') WHEN 'Reg' THEN 'Reg' WHEN 'Prov' THEN 'Prov' WHEN 'City' THEN 'City' WHEN 'Mun' THEN 'Mun' WHEN 'SubMun' THEN 'SubMun' WHEN 'Bgy' THEN 'Bgy' ELSE NULL END)) AS mismatched_geographic_level,
    COUNT_IF(b.source_row_number IS NULL OR NOT (c.city_class IS NOT DISTINCT FROM CASE NULLIF(TRIM(regexp_replace(translate(b.`city_class`, chr(9) || chr(160), '  '), ' +', ' ')), '') WHEN 'HUC' THEN 'HUC' WHEN 'ICC' THEN 'ICC' WHEN 'CC' THEN 'CC' ELSE NULL END)) AS mismatched_city_class,
    COUNT_IF(b.source_row_number IS NULL OR NOT (c.urban_rural IS NOT DISTINCT FROM CASE NULLIF(TRIM(regexp_replace(translate(b.`urban_rural`, chr(9) || chr(160), '  '), ' +', ' ')), '') WHEN 'U' THEN 'U' WHEN 'R' THEN 'R' WHEN '-' THEN NULL ELSE NULL END)) AS mismatched_urban_rural,
    COUNT_IF(b.source_row_number IS NULL OR NOT (c.status IS NOT DISTINCT FROM CASE NULLIF(TRIM(regexp_replace(translate(b.`status`, chr(9) || chr(160), '  '), ' +', ' ')), '') WHEN 'Capital' THEN 'Capital' WHEN 'Pob.' THEN 'Pob.' ELSE NULL END)) AS mismatched_status,
    COUNT_IF(b.source_row_number IS NULL OR NOT (c.urban_rural_null_reason IS NOT DISTINCT FROM CASE NULLIF(TRIM(regexp_replace(translate(b.`urban_rural`, chr(9) || chr(160), '  '), ' +', ' ')), '') WHEN '-' THEN 'unknown' ELSE NULL END)) AS mismatched_urban_rural_null_reason,
    COUNT_IF(b.source_row_number IS NULL OR NOT (c.income_class IS NOT DISTINCT FROM CASE NULLIF(TRIM(regexp_replace(translate(b.`income_classification`, chr(9) || chr(160), '  '), ' +', ' ')), '') WHEN '1st' THEN '1st' WHEN '2nd' THEN '2nd' WHEN '3rd' THEN '3rd' WHEN '4th' THEN '4th' WHEN '5th' THEN '5th' WHEN '2nd*' THEN '2nd' WHEN '3rd*' THEN '3rd' WHEN '4th*' THEN '4th' WHEN '-' THEN NULL ELSE NULL END)) AS mismatched_income_class,
    COUNT_IF(b.source_row_number IS NULL OR NOT (c.income_class_retained_after_downgrade IS NOT DISTINCT FROM CASE NULLIF(TRIM(regexp_replace(translate(b.`income_classification`, chr(9) || chr(160), '  '), ' +', ' ')), '') WHEN '1st' THEN FALSE WHEN '2nd' THEN FALSE WHEN '3rd' THEN FALSE WHEN '4th' THEN FALSE WHEN '5th' THEN FALSE WHEN '2nd*' THEN TRUE WHEN '3rd*' THEN TRUE WHEN '4th*' THEN TRUE ELSE NULL END)) AS mismatched_income_class_retained_after_downgrade,
    COUNT_IF(b.source_row_number IS NULL OR NOT (c.income_class_null_reason IS NOT DISTINCT FROM CASE NULLIF(TRIM(regexp_replace(translate(b.`income_classification`, chr(9) || chr(160), '  '), ' +', ' ')), '') WHEN '-' THEN 'not_classified' ELSE NULL END)) AS mismatched_income_class_null_reason,
    COUNT_IF(b.source_row_number IS NULL OR NOT (c.population IS NOT DISTINCT FROM CASE WHEN regexp_like(b.`population`, '^[0-9]{1,9}$') THEN CAST(b.`population` AS INT) END)) AS mismatched_population,
    COUNT_IF(b.source_row_number IS NULL OR NOT (c.population_null_reason IS NOT DISTINCT FROM CASE b.`population` WHEN '#N/A' THEN 'publisher_na' WHEN '' THEN 'blank' ELSE NULL END)) AS mismatched_population_null_reason,
    COUNT_IF((NULLIF(TRIM(regexp_replace(translate(b.`geographic_level`, chr(9) || chr(160), '  '), ' +', ' ')), '') IS NOT NULL AND NULLIF(TRIM(regexp_replace(translate(b.`geographic_level`, chr(9) || chr(160), '  '), ' +', ' ')), '') NOT IN ('Reg', 'Prov', 'City', 'Mun', 'SubMun', 'Bgy'))) AS unmapped_geographic_level,
    COUNT_IF((NULLIF(TRIM(regexp_replace(translate(b.`city_class`, chr(9) || chr(160), '  '), ' +', ' ')), '') IS NOT NULL AND NULLIF(TRIM(regexp_replace(translate(b.`city_class`, chr(9) || chr(160), '  '), ' +', ' ')), '') NOT IN ('HUC', 'ICC', 'CC'))) AS unmapped_city_class,
    COUNT_IF((NULLIF(TRIM(regexp_replace(translate(b.`urban_rural`, chr(9) || chr(160), '  '), ' +', ' ')), '') IS NOT NULL AND NULLIF(TRIM(regexp_replace(translate(b.`urban_rural`, chr(9) || chr(160), '  '), ' +', ' ')), '') NOT IN ('U', 'R', '-'))) AS unmapped_urban_rural,
    COUNT_IF((NULLIF(TRIM(regexp_replace(translate(b.`status`, chr(9) || chr(160), '  '), ' +', ' ')), '') IS NOT NULL AND NULLIF(TRIM(regexp_replace(translate(b.`status`, chr(9) || chr(160), '  '), ' +', ' ')), '') NOT IN ('Capital', 'Pob.'))) AS unmapped_status,
    COUNT_IF((NULLIF(TRIM(regexp_replace(translate(b.`income_classification`, chr(9) || chr(160), '  '), ' +', ' ')), '') IS NOT NULL AND NULLIF(TRIM(regexp_replace(translate(b.`income_classification`, chr(9) || chr(160), '  '), ' +', ' ')), '') NOT IN ('1st', '2nd', '3rd', '4th', '5th', '2nd*', '3rd*', '4th*', '-'))) AS unmapped_income_classification,
    COUNT_IF(reg.psgc_code IS NULL) AS missing_region,
    COUNT_IF(c.province_code IS NOT NULL AND prov.psgc_code IS NULL) AS missing_province,
    COUNT_IF(c.geographic_level IN ('City', 'Mun')
        AND c.province_code IS NULL AND COALESCE(c.city_class, '') <> 'HUC'
        AND c.psgc_code NOT IN ('1381701000')) AS unexplained_no_province,
    COUNT_IF((c.geographic_level = 'Bgy' OR c.city_municipality_code IS NOT NULL)
        AND cm.psgc_code IS NULL) AS missing_city_municipality,
    COUNT_IF(c.level_blank IS DISTINCT FROM (NULLIF(TRIM(regexp_replace(translate(b.geographic_level, chr(9) || chr(160), '  '), ' +', ' ')), '') IS NULL)
        OR c.population_is_zero IS DISTINCT FROM COALESCE(c.population = 0, FALSE)
        OR c.has_population_footnote IS DISTINCT FROM (c.population_footnote IS NOT NULL)) AS inconsistent_flags,
    COUNT_IF(c.level_blank) AS flagged_level_blank,
    COUNT_IF(c.population_is_zero) AS flagged_population_is_zero,
    COUNT_IF(c.has_population_footnote) AS flagged_has_population_footnote
  FROM clean AS c
  LEFT JOIN bronze AS b ON b.source_sha256 = c.source_sha256 AND b.source_row_number = c.source_row_number
  LEFT JOIN regions AS reg ON reg.batch_id = c.batch_id AND reg.psgc_code = c.region_code
  LEFT JOIN codes AS prov ON prov.batch_id = c.batch_id AND prov.psgc_code = c.province_code
  LEFT JOIN codes AS cm ON cm.batch_id = c.batch_id AND cm.psgc_code = c.city_municipality_code
  GROUP BY c.batch_id
),
quarantine_batches AS (
  SELECT
    q.batch_id,
    COUNT(*) AS quarantined_rows,
    COUNT_IF(array_contains(q.quarantine_reasons, 'psgc_code_blank')) AS reason_psgc_code_blank,
    COUNT_IF(array_contains(q.quarantine_reasons, 'psgc_code_malformed')) AS reason_psgc_code_malformed,
    COUNT_IF(array_contains(q.quarantine_reasons, 'psgc_code_duplicated')) AS reason_psgc_code_duplicated,
    COUNT_IF(array_contains(q.quarantine_reasons, 'correspondence_code_malformed')) AS reason_correspondence_code_malformed,
    COUNT_IF(array_contains(q.quarantine_reasons, 'population_uncastable')) AS reason_population_uncastable
  FROM quarantined AS q
  GROUP BY q.batch_id
),
batches AS (
  SELECT
    cur.batch_id,
    COALESCE(bronze_rows, 0) AS bronze_rows,
    COALESCE(whitespace_rows, 0) AS whitespace_rows,
    COALESCE(marker_rows, 0) AS marker_rows,
    COALESCE(blank_population_rows, 0) AS blank_population_rows,
    COALESCE(starred_rows, 0) AS starred_rows,
    COALESCE(placeholder_cells, 0) AS placeholder_cells,
    COALESCE(clean_rows, 0) AS clean_rows,
    COALESCE(clean_codes, 0) AS clean_codes,
    COALESCE(invalid_codes, 0) AS invalid_codes,
    COALESCE(mismatched_psgc_code, 0) AS mismatched_psgc_code,
    COALESCE(mismatched_name, 0) AS mismatched_name,
    COALESCE(mismatched_old_names, 0) AS mismatched_old_names,
    COALESCE(mismatched_population_footnote, 0) AS mismatched_population_footnote,
    COALESCE(mismatched_correspondence_code, 0) AS mismatched_correspondence_code,
    COALESCE(mismatched_publication_period, 0) AS mismatched_publication_period,
    COALESCE(mismatched_publication_date, 0) AS mismatched_publication_date,
    COALESCE(mismatched_is_master_reference, 0) AS mismatched_is_master_reference,
    COALESCE(mismatched_geographic_level, 0) AS mismatched_geographic_level,
    COALESCE(mismatched_city_class, 0) AS mismatched_city_class,
    COALESCE(mismatched_urban_rural, 0) AS mismatched_urban_rural,
    COALESCE(mismatched_status, 0) AS mismatched_status,
    COALESCE(mismatched_urban_rural_null_reason, 0) AS mismatched_urban_rural_null_reason,
    COALESCE(mismatched_income_class, 0) AS mismatched_income_class,
    COALESCE(mismatched_income_class_retained_after_downgrade, 0) AS mismatched_income_class_retained_after_downgrade,
    COALESCE(mismatched_income_class_null_reason, 0) AS mismatched_income_class_null_reason,
    COALESCE(mismatched_population, 0) AS mismatched_population,
    COALESCE(mismatched_population_null_reason, 0) AS mismatched_population_null_reason,
    COALESCE(unmapped_geographic_level, 0) AS unmapped_geographic_level,
    COALESCE(unmapped_city_class, 0) AS unmapped_city_class,
    COALESCE(unmapped_urban_rural, 0) AS unmapped_urban_rural,
    COALESCE(unmapped_status, 0) AS unmapped_status,
    COALESCE(unmapped_income_classification, 0) AS unmapped_income_classification,
    COALESCE(missing_region, 0) AS missing_region,
    COALESCE(missing_province, 0) AS missing_province,
    COALESCE(unexplained_no_province, 0) AS unexplained_no_province,
    COALESCE(missing_city_municipality, 0) AS missing_city_municipality,
    COALESCE(inconsistent_flags, 0) AS inconsistent_flags,
    COALESCE(flagged_level_blank, 0) AS flagged_level_blank,
    COALESCE(flagged_population_is_zero, 0) AS flagged_population_is_zero,
    COALESCE(flagged_has_population_footnote, 0) AS flagged_has_population_footnote,
    COALESCE(quarantined_rows, 0) AS quarantined_rows,
    COALESCE(reason_psgc_code_blank, 0) AS reason_psgc_code_blank,
    COALESCE(reason_psgc_code_malformed, 0) AS reason_psgc_code_malformed,
    COALESCE(reason_psgc_code_duplicated, 0) AS reason_psgc_code_duplicated,
    COALESCE(reason_correspondence_code_malformed, 0) AS reason_correspondence_code_malformed,
    COALESCE(reason_population_uncastable, 0) AS reason_population_uncastable
  FROM cur
  LEFT JOIN bronze_batches AS bb ON bb.batch_id = cur.batch_id
  LEFT JOIN clean_batches AS cb ON cb.batch_id = cur.batch_id
  LEFT JOIN quarantine_batches AS qb ON qb.batch_id = cur.batch_id
),
found AS (
  SELECT COUNT(*) AS current_batches,
         COUNT_IF(publication_period = '2026-Q2') AS master_batches
  FROM cur
),
silver_rows AS (
  SELECT publication_period, batch_id, delivery_version, schema_version, source_sha256, source_row_number, run_id, cleaned_at_utc, code_revision FROM clean
  UNION ALL SELECT publication_period, batch_id, delivery_version, schema_version, source_sha256, source_row_number, run_id, cleaned_at_utc, code_revision FROM quarantined
),
whole AS (
  SELECT
    COUNT_IF(publication_period IS NULL OR batch_id IS NULL OR delivery_version IS NULL OR schema_version IS NULL OR source_sha256 IS NULL OR source_row_number IS NULL OR run_id IS NULL OR cleaned_at_utc IS NULL OR code_revision IS NULL) AS missing_lineage,
    COUNT_IF(run_id <> :run_id) AS other_run_rows,
    COUNT(DISTINCT cleaned_at_utc) AS timestamps
  FROM silver_rows
),
unresolved AS (
  SELECT COUNT(*) AS unresolved_rows
  FROM silver_rows AS s
  LEFT JOIN bronze AS b ON b.source_sha256 = s.source_sha256 AND b.source_row_number = s.source_row_number
    AND b.batch_id = s.batch_id
  WHERE b.source_row_number IS NULL
)
  -- The whole build
  SELECT CAST(NULL AS STRING) AS batch_id, 'edu_access.03-silver.psa_psgc_clean_candidate' AS table_name, 'current_batches_present' AS check_name,
         CASE WHEN current_batches > 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         'at least 1' AS expected, CAST(current_batches AS STRING) AS actual FROM found
  UNION ALL SELECT CAST(NULL AS STRING) AS batch_id, 'edu_access.03-silver.psa_psgc_clean_candidate' AS table_name, 'master_reference_current' AS check_name,
         CASE WHEN master_batches = 1 THEN 'PASS' ELSE 'FAIL' END AS status,
         '1 current batch of ' || '2026-Q2' AS expected, CAST(master_batches AS STRING) AS actual FROM found
  UNION ALL SELECT CAST(NULL AS STRING) AS batch_id, 'edu_access.03-silver.psa_psgc_clean_candidate' AS table_name, 'lineage_complete' AS check_name,
         CASE WHEN missing_lineage = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(missing_lineage AS STRING) AS actual FROM whole
  UNION ALL SELECT CAST(NULL AS STRING) AS batch_id, 'edu_access.03-silver.psa_psgc_clean_candidate' AS table_name, 'rows_resolve_to_current_bronze' AS check_name,
         CASE WHEN unresolved_rows = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(unresolved_rows AS STRING) AS actual FROM unresolved
  UNION ALL SELECT CAST(NULL AS STRING) AS batch_id, 'edu_access.03-silver.psa_psgc_clean_candidate' AS table_name, 'rows_built_by_this_run' AS check_name,
         CASE WHEN other_run_rows = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(other_run_rows AS STRING) AS actual FROM whole
  UNION ALL SELECT CAST(NULL AS STRING) AS batch_id, 'edu_access.03-silver.psa_psgc_clean_candidate' AS table_name, 'one_timestamp_per_run' AS check_name,
         CASE WHEN timestamps = 1 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(1 AS STRING) AS expected, CAST(timestamps AS STRING) AS actual FROM whole
  -- Each current batch: reconciliation, keys, values against Bronze, labels, parents
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_psgc_clean_candidate' AS table_name, 'rows_reconcile' AS check_name,
         CASE WHEN clean_rows + quarantined_rows = bronze_rows THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(bronze_rows AS STRING) AS expected, CAST(clean_rows + quarantined_rows AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_psgc_clean_candidate' AS table_name, 'psgc_code_unique' AS check_name,
         CASE WHEN clean_rows - clean_codes = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(clean_rows - clean_codes AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_psgc_clean_candidate' AS table_name, 'psgc_code_valid' AS check_name,
         CASE WHEN invalid_codes = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(invalid_codes AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_psgc_quarantine_candidate' AS table_name, 'psgc_code_duplicates_absent' AS check_name,
         CASE WHEN reason_psgc_code_duplicated = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(reason_psgc_code_duplicated AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_psgc_clean_candidate' AS table_name, 'psgc_code_matches_bronze' AS check_name,
         CASE WHEN mismatched_psgc_code = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(mismatched_psgc_code AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_psgc_clean_candidate' AS table_name, 'name_matches_bronze' AS check_name,
         CASE WHEN mismatched_name = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(mismatched_name AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_psgc_clean_candidate' AS table_name, 'old_names_matches_bronze' AS check_name,
         CASE WHEN mismatched_old_names = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(mismatched_old_names AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_psgc_clean_candidate' AS table_name, 'population_footnote_matches_bronze' AS check_name,
         CASE WHEN mismatched_population_footnote = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(mismatched_population_footnote AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_psgc_clean_candidate' AS table_name, 'correspondence_code_matches_bronze' AS check_name,
         CASE WHEN mismatched_correspondence_code = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(mismatched_correspondence_code AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_psgc_clean_candidate' AS table_name, 'publication_period_matches_bronze' AS check_name,
         CASE WHEN mismatched_publication_period = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(mismatched_publication_period AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_psgc_clean_candidate' AS table_name, 'publication_date_matches_bronze' AS check_name,
         CASE WHEN mismatched_publication_date = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(mismatched_publication_date AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_psgc_clean_candidate' AS table_name, 'is_master_reference_matches_bronze' AS check_name,
         CASE WHEN mismatched_is_master_reference = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(mismatched_is_master_reference AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_psgc_clean_candidate' AS table_name, 'geographic_level_matches_bronze' AS check_name,
         CASE WHEN mismatched_geographic_level = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(mismatched_geographic_level AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_psgc_clean_candidate' AS table_name, 'city_class_matches_bronze' AS check_name,
         CASE WHEN mismatched_city_class = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(mismatched_city_class AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_psgc_clean_candidate' AS table_name, 'urban_rural_matches_bronze' AS check_name,
         CASE WHEN mismatched_urban_rural = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(mismatched_urban_rural AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_psgc_clean_candidate' AS table_name, 'status_matches_bronze' AS check_name,
         CASE WHEN mismatched_status = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(mismatched_status AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_psgc_clean_candidate' AS table_name, 'urban_rural_null_reason_matches_bronze' AS check_name,
         CASE WHEN mismatched_urban_rural_null_reason = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(mismatched_urban_rural_null_reason AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_psgc_clean_candidate' AS table_name, 'income_class_matches_bronze' AS check_name,
         CASE WHEN mismatched_income_class = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(mismatched_income_class AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_psgc_clean_candidate' AS table_name, 'income_class_retained_after_downgrade_matches_bronze' AS check_name,
         CASE WHEN mismatched_income_class_retained_after_downgrade = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(mismatched_income_class_retained_after_downgrade AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_psgc_clean_candidate' AS table_name, 'income_class_null_reason_matches_bronze' AS check_name,
         CASE WHEN mismatched_income_class_null_reason = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(mismatched_income_class_null_reason AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_psgc_clean_candidate' AS table_name, 'population_matches_bronze' AS check_name,
         CASE WHEN mismatched_population = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(mismatched_population AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_psgc_clean_candidate' AS table_name, 'population_null_reason_matches_bronze' AS check_name,
         CASE WHEN mismatched_population_null_reason = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(mismatched_population_null_reason AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_psgc_clean_candidate' AS table_name, 'labels_mapped_geographic_level' AS check_name,
         CASE WHEN unmapped_geographic_level = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(unmapped_geographic_level AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_psgc_clean_candidate' AS table_name, 'labels_mapped_city_class' AS check_name,
         CASE WHEN unmapped_city_class = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(unmapped_city_class AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_psgc_clean_candidate' AS table_name, 'labels_mapped_urban_rural' AS check_name,
         CASE WHEN unmapped_urban_rural = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(unmapped_urban_rural AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_psgc_clean_candidate' AS table_name, 'labels_mapped_status' AS check_name,
         CASE WHEN unmapped_status = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(unmapped_status AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_psgc_clean_candidate' AS table_name, 'labels_mapped_income_classification' AS check_name,
         CASE WHEN unmapped_income_classification = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(unmapped_income_classification AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_psgc_clean_candidate' AS table_name, 'region_code_exists' AS check_name,
         CASE WHEN missing_region = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(missing_region AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_psgc_clean_candidate' AS table_name, 'province_code_exists' AS check_name,
         CASE WHEN missing_province = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(missing_province AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_psgc_clean_candidate' AS table_name, 'province_code_missing_only_where_listed' AS check_name,
         CASE WHEN unexplained_no_province = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(unexplained_no_province AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_psgc_clean_candidate' AS table_name, 'city_municipality_code_exists' AS check_name,
         CASE WHEN missing_city_municipality = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(missing_city_municipality AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_psgc_clean_candidate' AS table_name, 'flags_consistent' AS check_name,
         CASE WHEN inconsistent_flags = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(inconsistent_flags AS STRING) AS actual FROM batches
  -- Each current batch: quarantine (WARN above 0, FAIL above 1% of its rows)
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_psgc_quarantine_candidate' AS table_name, 'quarantine_rate' AS check_name,
         CASE WHEN quarantined_rows = 0 THEN 'PASS' WHEN quarantined_rows * 100 > bronze_rows * 1 THEN 'FAIL' ELSE 'WARN' END AS status,
         '0 (FAIL above 1% of ' || CAST(bronze_rows AS STRING) || ')' AS expected, CAST(quarantined_rows AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_psgc_quarantine_candidate' AS table_name, 'quarantine_reason_psgc_code_blank' AS check_name,
         CASE WHEN reason_psgc_code_blank = 0 THEN 'PASS' ELSE 'WARN' END AS status,
         '0' AS expected, CAST(reason_psgc_code_blank AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_psgc_quarantine_candidate' AS table_name, 'quarantine_reason_psgc_code_malformed' AS check_name,
         CASE WHEN reason_psgc_code_malformed = 0 THEN 'PASS' ELSE 'WARN' END AS status,
         '0' AS expected, CAST(reason_psgc_code_malformed AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_psgc_quarantine_candidate' AS table_name, 'quarantine_reason_psgc_code_duplicated' AS check_name,
         CASE WHEN reason_psgc_code_duplicated = 0 THEN 'PASS' ELSE 'WARN' END AS status,
         '0' AS expected, CAST(reason_psgc_code_duplicated AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_psgc_quarantine_candidate' AS table_name, 'quarantine_reason_correspondence_code_malformed' AS check_name,
         CASE WHEN reason_correspondence_code_malformed = 0 THEN 'PASS' ELSE 'WARN' END AS status,
         '0' AS expected, CAST(reason_correspondence_code_malformed AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_psgc_quarantine_candidate' AS table_name, 'quarantine_reason_population_uncastable' AS check_name,
         CASE WHEN reason_population_uncastable = 0 THEN 'PASS' ELSE 'WARN' END AS status,
         '0' AS expected, CAST(reason_population_uncastable AS STRING) AS actual FROM batches
  -- Each current batch: rows flagged and rows each rule changed (records, always PASS)
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_psgc_clean_candidate' AS table_name, 'flag_level_blank' AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(flagged_level_blank AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_psgc_clean_candidate' AS table_name, 'flag_population_is_zero' AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(flagged_population_is_zero AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_psgc_clean_candidate' AS table_name, 'flag_has_population_footnote' AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(flagged_has_population_footnote AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_psgc_clean_candidate' AS table_name, 'rule_text_whitespace_normalized' AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(whitespace_rows AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_psgc_clean_candidate' AS table_name, 'rule_population_marker_to_null' AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(marker_rows AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_psgc_clean_candidate' AS table_name, 'rule_population_blank_to_null' AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(blank_population_rows AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_psgc_clean_candidate' AS table_name, 'rule_income_class_star_split' AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(starred_rows AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_psgc_clean_candidate' AS table_name, 'rule_placeholder_to_null' AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(placeholder_cells AS STRING) AS actual FROM batches
) AS results;

-- A failed build: record it before stopping. The Silver tables are not touched.
MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (
  SELECT :run_id AS run_id, COUNT_IF(status = 'FAIL') AS fails
  FROM edu_access.`01-control`.data_quality_results
  WHERE run_id = :run_id AND source_id = 'psa_psgc' AND layer = 'silver'
    AND checked_at_utc >= session.silver_gate_started_at_utc
) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'silver_build' AND t.source_id = 'psa_psgc'
WHEN MATCHED AND s.fails > 0 THEN UPDATE SET
  status = 'failed', finished_at_utc = current_timestamp(), failure_stage = 'gate',
  error_message = CAST(s.fails AS STRING) || ' FAIL result(s) in data_quality_results';

-- Stop here, before publishing, if anything failed in this execution.
SELECT CASE WHEN COUNT(*) > 0
            THEN raise_error('Silver gate failed for psa_psgc: ' || CAST(COUNT(*) AS STRING)
                             || ' FAIL result(s) in data_quality_results for run ' || :run_id)
       END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'psa_psgc' AND layer = 'silver' AND status = 'FAIL'
  AND checked_at_utc >= session.silver_gate_started_at_utc;

-- Every check passed: publish. Quarantine first, then clean, the table Gold reads. Each copy is
-- one atomic Delta commit, but the pair is not, so the run is 'succeeded' only after both. If the
-- task dies in between, the run stays 'running', and Gold trusts a Silver table only when the
-- run_id its rows carry is a succeeded silver_build run (D-025).
CREATE OR REPLACE TABLE edu_access.`03-silver`.psa_psgc_quarantine USING DELTA AS
SELECT * FROM edu_access.`03-silver`.psa_psgc_quarantine_candidate;

ALTER TABLE edu_access.`03-silver`.psa_psgc_quarantine OWNER TO `reached-hq`;

CREATE OR REPLACE TABLE edu_access.`03-silver`.psa_psgc_clean USING DELTA AS
SELECT * FROM edu_access.`03-silver`.psa_psgc_clean_candidate;

ALTER TABLE edu_access.`03-silver`.psa_psgc_clean OWNER TO `reached-hq`;

-- Published: the run succeeded.
MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (SELECT :run_id AS run_id) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'silver_build' AND t.source_id = 'psa_psgc'
WHEN MATCHED THEN UPDATE SET
  status = 'succeeded', finished_at_utc = current_timestamp(), failure_stage = NULL, error_message = NULL;
