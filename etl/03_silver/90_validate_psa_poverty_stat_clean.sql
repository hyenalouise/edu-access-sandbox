-- Silver gate for psa_poverty_stat. Generated from config/ingestion/psa_poverty_stat.json
-- and config/mappings/psa_poverty_stat.json by src/silver/psa_poverty_stat.py:
--   python -m src.silver.cli gate --source psa_poverty_stat > etl/03_silver/90_validate_psa_poverty_stat_clean.sql
-- Do not edit by hand; tests/test_silver_psa.py fails if it differs.
--
-- The job task after the Silver build. It checks the candidate tables the build wrote, one row
-- per check in data_quality_results: the whole build, each current batch, and each batch and
-- estimate year (check names end in the year). On any FAIL it records the run 'failed' and stops
-- the task before publishing, so the Silver tables keep the last build that passed and nothing
-- downstream runs. Otherwise it copies the candidates to the Silver tables and records the run
-- 'succeeded'. PASS: as expected. WARN: recorded, the build is published (statistical flags,
-- quarantined rows). FAIL: the candidate cannot be trusted. Results hold counts, never row values.
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
SELECT :run_id, batch_id, 'psa_poverty_stat', 'silver', table_name, check_name, status, expected, actual,
       current_timestamp(), :code_revision
FROM (
WITH cur AS (
  SELECT batch_id, estimate_years_covered FROM edu_access.`01-control`.current_batches WHERE source_id = 'psa_poverty_stat'
),
bronze AS (
  SELECT r.* FROM edu_access.`02-bronze`.psa_poverty_stat_raw AS r JOIN cur ON r.batch_id = cur.batch_id
),
clean AS (SELECT * FROM edu_access.`03-silver`.psa_poverty_stat_clean_candidate),
quarantined AS (SELECT * FROM edu_access.`03-silver`.psa_poverty_stat_quarantine_candidate),
known_years AS (SELECT * FROM (VALUES ('2018'), ('2021'), ('2023')) AS v(estimate_year)),
-- Every batch and estimate year the current batches cover: the grid every year check is written for.
grid AS (
  SELECT cur.batch_id, y.estimate_year FROM cur
  JOIN known_years AS y ON array_contains(split(cur.estimate_years_covered, ','), y.estimate_year)
),
-- Each Bronze unit row once per estimate year its batch covers, marked if Silver set it aside.
bronze_units AS (
  SELECT
    u.batch_id,
    y.estimate_year,
    COUNT(*) AS unit_rows,
    COUNT_IF(length(u.`PSGC ID`) < 6) AS padded_ids,
    COUNT_IF(
        TRIM(regexp_replace(translate(u.`Municipality/City`, chr(9) || chr(160), '  '), ' +', ' ')) <> u.`Municipality/City`
      ) AS whitespace_rows,
    SUM(CASE WHEN q.source_row_number IS NULL THEN
        CASE WHEN (CASE y.estimate_year WHEN '2018' THEN u.`Poverty Incidence 2018` WHEN '2021' THEN u.`Poverty Incidence 2021` WHEN '2023' THEN u.`Poverty Incidence 2023` END IS NULL OR CASE y.estimate_year WHEN '2018' THEN u.`Poverty Incidence 2018` WHEN '2021' THEN u.`Poverty Incidence 2021` WHEN '2023' THEN u.`Poverty Incidence 2023` END = '') THEN 1 ELSE 0 END + CASE WHEN (CASE y.estimate_year WHEN '2018' THEN u.`Coefficient of Variation 2018` WHEN '2021' THEN u.`Coefficient of Variation 2021` WHEN '2023' THEN u.`Coefficient of Variation 2023` END IS NULL OR CASE y.estimate_year WHEN '2018' THEN u.`Coefficient of Variation 2018` WHEN '2021' THEN u.`Coefficient of Variation 2021` WHEN '2023' THEN u.`Coefficient of Variation 2023` END = '') THEN 1 ELSE 0 END + CASE WHEN (CASE y.estimate_year WHEN '2018' THEN u.`Standard Error 2018` WHEN '2021' THEN u.`Standard Error 2021` WHEN '2023' THEN u.`Standard Error 2023` END IS NULL OR CASE y.estimate_year WHEN '2018' THEN u.`Standard Error 2018` WHEN '2021' THEN u.`Standard Error 2021` WHEN '2023' THEN u.`Standard Error 2023` END = '') THEN 1 ELSE 0 END + CASE WHEN (CASE y.estimate_year WHEN '2018' THEN u.`90% Confidence Interval Lower Limit 2018` WHEN '2021' THEN u.`90% Confidence Interval Lower Limit 2021` WHEN '2023' THEN u.`90% Confidence Interval Lower Limit 2023` END IS NULL OR CASE y.estimate_year WHEN '2018' THEN u.`90% Confidence Interval Lower Limit 2018` WHEN '2021' THEN u.`90% Confidence Interval Lower Limit 2021` WHEN '2023' THEN u.`90% Confidence Interval Lower Limit 2023` END = '') THEN 1 ELSE 0 END + CASE WHEN (CASE y.estimate_year WHEN '2018' THEN u.`90% Confidence Interval Upper Limit 2018` WHEN '2021' THEN u.`90% Confidence Interval Upper Limit 2021` WHEN '2023' THEN u.`90% Confidence Interval Upper Limit 2023` END IS NULL OR CASE y.estimate_year WHEN '2018' THEN u.`90% Confidence Interval Upper Limit 2018` WHEN '2021' THEN u.`90% Confidence Interval Upper Limit 2021` WHEN '2023' THEN u.`90% Confidence Interval Upper Limit 2023` END = '') THEN 1 ELSE 0 END
      ELSE 0 END) AS kept_blank_cells
  FROM bronze AS u
  JOIN cur ON u.batch_id = cur.batch_id
  JOIN known_years AS y ON array_contains(split(cur.estimate_years_covered, ','), y.estimate_year)
  LEFT JOIN quarantined AS q
    ON q.source_sha256 = u.source_sha256 AND q.source_row_number = u.source_row_number
   AND CAST(q.estimate_year AS STRING) = y.estimate_year
  WHERE u.source_row_kind = 'unit'
  GROUP BY u.batch_id, y.estimate_year
),
-- Each clean row beside its Bronze row: every value is the published cell, typed.
clean_years AS (
  SELECT
    c.batch_id,
    CAST(c.estimate_year AS STRING) AS estimate_year,
    COUNT(*) AS clean_rows,
    COUNT(DISTINCT c.psgc_id) AS clean_ids,
    COUNT_IF(c.psgc_id IS NULL OR NOT regexp_like(c.psgc_id, '^[0-9]{6}$')
        OR b.source_row_number IS NULL OR c.psgc_id <> lpad(b.`PSGC ID`, 6, '0')
        OR c.correspondence_code IS NULL OR c.correspondence_code <> c.psgc_id || '000') AS invalid_ids,
    COUNT_IF(NOT array_contains(split(c.estimate_years_covered, ','), CAST(c.estimate_year AS STRING))) AS uncovered_rows,
    COUNT_IF(b.source_row_number IS NULL OR NOT (c.poverty_incidence IS NOT DISTINCT FROM CASE WHEN regexp_like(CASE CAST(c.estimate_year AS STRING) WHEN '2018' THEN b.`Poverty Incidence 2018` WHEN '2021' THEN b.`Poverty Incidence 2021` WHEN '2023' THEN b.`Poverty Incidence 2023` END, '^-?[0-9]+([.][0-9]+)?([eE][-+]?[0-9]{1,3})?$') THEN TRY_CAST(CASE CAST(c.estimate_year AS STRING) WHEN '2018' THEN b.`Poverty Incidence 2018` WHEN '2021' THEN b.`Poverty Incidence 2021` WHEN '2023' THEN b.`Poverty Incidence 2023` END AS DOUBLE) END)) AS mismatched_poverty_incidence,
    COUNT_IF(b.source_row_number IS NULL OR NOT (c.coefficient_of_variation IS NOT DISTINCT FROM CASE WHEN regexp_like(CASE CAST(c.estimate_year AS STRING) WHEN '2018' THEN b.`Coefficient of Variation 2018` WHEN '2021' THEN b.`Coefficient of Variation 2021` WHEN '2023' THEN b.`Coefficient of Variation 2023` END, '^-?[0-9]+([.][0-9]+)?([eE][-+]?[0-9]{1,3})?$') THEN TRY_CAST(CASE CAST(c.estimate_year AS STRING) WHEN '2018' THEN b.`Coefficient of Variation 2018` WHEN '2021' THEN b.`Coefficient of Variation 2021` WHEN '2023' THEN b.`Coefficient of Variation 2023` END AS DOUBLE) END)) AS mismatched_coefficient_of_variation,
    COUNT_IF(b.source_row_number IS NULL OR NOT (c.standard_error IS NOT DISTINCT FROM CASE WHEN regexp_like(CASE CAST(c.estimate_year AS STRING) WHEN '2018' THEN b.`Standard Error 2018` WHEN '2021' THEN b.`Standard Error 2021` WHEN '2023' THEN b.`Standard Error 2023` END, '^-?[0-9]+([.][0-9]+)?([eE][-+]?[0-9]{1,3})?$') THEN TRY_CAST(CASE CAST(c.estimate_year AS STRING) WHEN '2018' THEN b.`Standard Error 2018` WHEN '2021' THEN b.`Standard Error 2021` WHEN '2023' THEN b.`Standard Error 2023` END AS DOUBLE) END)) AS mismatched_standard_error,
    COUNT_IF(b.source_row_number IS NULL OR NOT (c.ci90_lower_limit IS NOT DISTINCT FROM CASE WHEN regexp_like(CASE CAST(c.estimate_year AS STRING) WHEN '2018' THEN b.`90% Confidence Interval Lower Limit 2018` WHEN '2021' THEN b.`90% Confidence Interval Lower Limit 2021` WHEN '2023' THEN b.`90% Confidence Interval Lower Limit 2023` END, '^-?[0-9]+([.][0-9]+)?([eE][-+]?[0-9]{1,3})?$') THEN TRY_CAST(CASE CAST(c.estimate_year AS STRING) WHEN '2018' THEN b.`90% Confidence Interval Lower Limit 2018` WHEN '2021' THEN b.`90% Confidence Interval Lower Limit 2021` WHEN '2023' THEN b.`90% Confidence Interval Lower Limit 2023` END AS DOUBLE) END)) AS mismatched_ci90_lower_limit,
    COUNT_IF(b.source_row_number IS NULL OR NOT (c.ci90_upper_limit IS NOT DISTINCT FROM CASE WHEN regexp_like(CASE CAST(c.estimate_year AS STRING) WHEN '2018' THEN b.`90% Confidence Interval Upper Limit 2018` WHEN '2021' THEN b.`90% Confidence Interval Upper Limit 2021` WHEN '2023' THEN b.`90% Confidence Interval Upper Limit 2023` END, '^-?[0-9]+([.][0-9]+)?([eE][-+]?[0-9]{1,3})?$') THEN TRY_CAST(CASE CAST(c.estimate_year AS STRING) WHEN '2018' THEN b.`90% Confidence Interval Upper Limit 2018` WHEN '2021' THEN b.`90% Confidence Interval Upper Limit 2021` WHEN '2023' THEN b.`90% Confidence Interval Upper Limit 2023` END AS DOUBLE) END)) AS mismatched_ci90_upper_limit,
    SUM(CASE WHEN c.poverty_incidence IS NULL THEN 1 ELSE 0 END + CASE WHEN c.coefficient_of_variation IS NULL THEN 1 ELSE 0 END + CASE WHEN c.standard_error IS NULL THEN 1 ELSE 0 END + CASE WHEN c.ci90_lower_limit IS NULL THEN 1 ELSE 0 END + CASE WHEN c.ci90_upper_limit IS NULL THEN 1 ELSE 0 END) AS clean_null_cells,
    COUNT_IF(c.estimate_status IS NULL OR c.estimate_status NOT IN ('estimated', 'no_estimate', 'partial_estimate')
        OR c.estimate_status <> CASE WHEN c.poverty_incidence IS NOT NULL AND c.coefficient_of_variation IS NOT NULL AND c.standard_error IS NOT NULL AND c.ci90_lower_limit IS NOT NULL AND c.ci90_upper_limit IS NOT NULL THEN 'estimated'
         WHEN c.poverty_incidence IS NULL AND c.coefficient_of_variation IS NULL AND c.standard_error IS NULL AND c.ci90_lower_limit IS NULL AND c.ci90_upper_limit IS NULL THEN 'no_estimate'
         ELSE 'partial_estimate' END) AS invalid_status_rows,
    COUNT_IF(COALESCE(c.poverty_incidence < 0 OR c.poverty_incidence > 100, FALSE)) AS incidence_out_of_bounds,
    COUNT_IF(COALESCE(c.coefficient_of_variation < 0, FALSE)) AS negative_cv,
    COUNT_IF(COALESCE(c.standard_error < 0, FALSE)) AS negative_se,
    COUNT_IF(COALESCE(c.ci90_lower_limit > c.ci90_upper_limit, FALSE) OR COALESCE(c.poverty_incidence < c.ci90_lower_limit, FALSE) OR COALESCE(c.poverty_incidence > c.ci90_upper_limit, FALSE)) AS ci_problems,
    COUNT_IF(
        c.cv_over_20 IS NULL OR c.cv_over_20 <> (COALESCE(c.coefficient_of_variation > 20, FALSE))
        OR c.se_cv_inconsistent IS NULL OR c.se_cv_inconsistent <> (COALESCE(abs(c.standard_error - c.poverty_incidence * c.coefficient_of_variation / 100) > 0.05, FALSE))
        OR c.lower_limit_not_positive IS NULL OR c.lower_limit_not_positive <> (COALESCE(c.ci90_lower_limit <= 0, FALSE))
      ) AS inconsistent_flags,
    COUNT_IF(c.region IS NULL) AS no_banner_rows,
    COUNT_IF(c.cv_over_20) AS flagged_cv_over_20,
    COUNT_IF(c.se_cv_inconsistent) AS flagged_se_cv_inconsistent,
    COUNT_IF(c.lower_limit_not_positive) AS flagged_lower_limit_not_positive,
    COUNT_IF(c.estimate_status = 'partial_estimate') AS partial_rows,
    COUNT_IF(c.estimate_status = 'no_estimate' AND c.poverty_incidence IS NULL AND c.coefficient_of_variation IS NULL AND c.standard_error IS NULL AND c.ci90_lower_limit IS NULL AND c.ci90_upper_limit IS NULL) AS no_estimate_rows
  FROM clean AS c
  LEFT JOIN bronze AS b ON b.source_sha256 = c.source_sha256 AND b.source_row_number = c.source_row_number
  GROUP BY c.batch_id, c.estimate_year
),
quarantine_years AS (
  SELECT
    q.batch_id,
    CAST(q.estimate_year AS STRING) AS estimate_year,
    COUNT(*) AS quarantined_rows,
    COUNT_IF(array_contains(q.quarantine_reasons, 'psgc_id_blank')) AS reason_psgc_id_blank,
    COUNT_IF(array_contains(q.quarantine_reasons, 'psgc_id_malformed')) AS reason_psgc_id_malformed,
    COUNT_IF(array_contains(q.quarantine_reasons, 'psgc_id_duplicated')) AS reason_psgc_id_duplicated,
    COUNT_IF(array_contains(q.quarantine_reasons, 'measure_uncastable')) AS reason_measure_uncastable,
    COUNT_IF(array_contains(q.quarantine_reasons, 'incidence_out_of_range')) AS reason_incidence_out_of_range,
    COUNT_IF(array_contains(q.quarantine_reasons, 'cv_negative')) AS reason_cv_negative,
    COUNT_IF(array_contains(q.quarantine_reasons, 'se_negative')) AS reason_se_negative,
    COUNT_IF(array_contains(q.quarantine_reasons, 'ci_inconsistent')) AS reason_ci_inconsistent
  FROM quarantined AS q GROUP BY q.batch_id, q.estimate_year
),
years AS (
  SELECT
    g.batch_id,
    g.estimate_year,
    COALESCE(unit_rows, 0) AS unit_rows,
    COALESCE(padded_ids, 0) AS padded_ids,
    COALESCE(whitespace_rows, 0) AS whitespace_rows,
    COALESCE(kept_blank_cells, 0) AS kept_blank_cells,
    COALESCE(clean_rows, 0) AS clean_rows,
    COALESCE(clean_ids, 0) AS clean_ids,
    COALESCE(invalid_ids, 0) AS invalid_ids,
    COALESCE(uncovered_rows, 0) AS uncovered_rows,
    COALESCE(mismatched_poverty_incidence, 0) AS mismatched_poverty_incidence,
    COALESCE(mismatched_coefficient_of_variation, 0) AS mismatched_coefficient_of_variation,
    COALESCE(mismatched_standard_error, 0) AS mismatched_standard_error,
    COALESCE(mismatched_ci90_lower_limit, 0) AS mismatched_ci90_lower_limit,
    COALESCE(mismatched_ci90_upper_limit, 0) AS mismatched_ci90_upper_limit,
    COALESCE(clean_null_cells, 0) AS clean_null_cells,
    COALESCE(invalid_status_rows, 0) AS invalid_status_rows,
    COALESCE(incidence_out_of_bounds, 0) AS incidence_out_of_bounds,
    COALESCE(negative_cv, 0) AS negative_cv,
    COALESCE(negative_se, 0) AS negative_se,
    COALESCE(ci_problems, 0) AS ci_problems,
    COALESCE(inconsistent_flags, 0) AS inconsistent_flags,
    COALESCE(no_banner_rows, 0) AS no_banner_rows,
    COALESCE(flagged_cv_over_20, 0) AS flagged_cv_over_20,
    COALESCE(flagged_se_cv_inconsistent, 0) AS flagged_se_cv_inconsistent,
    COALESCE(flagged_lower_limit_not_positive, 0) AS flagged_lower_limit_not_positive,
    COALESCE(partial_rows, 0) AS partial_rows,
    COALESCE(no_estimate_rows, 0) AS no_estimate_rows,
    COALESCE(quarantined_rows, 0) AS quarantined_rows,
    COALESCE(reason_psgc_id_blank, 0) AS reason_psgc_id_blank,
    COALESCE(reason_psgc_id_malformed, 0) AS reason_psgc_id_malformed,
    COALESCE(reason_psgc_id_duplicated, 0) AS reason_psgc_id_duplicated,
    COALESCE(reason_measure_uncastable, 0) AS reason_measure_uncastable,
    COALESCE(reason_incidence_out_of_range, 0) AS reason_incidence_out_of_range,
    COALESCE(reason_cv_negative, 0) AS reason_cv_negative,
    COALESCE(reason_se_negative, 0) AS reason_se_negative,
    COALESCE(reason_ci_inconsistent, 0) AS reason_ci_inconsistent
  FROM grid AS g
  LEFT JOIN bronze_units AS bu ON bu.batch_id = g.batch_id AND bu.estimate_year = g.estimate_year
  LEFT JOIN clean_years AS cy ON cy.batch_id = g.batch_id AND cy.estimate_year = g.estimate_year
  LEFT JOIN quarantine_years AS qy ON qy.batch_id = g.batch_id AND qy.estimate_year = g.estimate_year
),
-- Each current batch: its Bronze rows by kind. Structural rows stay in Bronze, never as estimates.
batches AS (
  SELECT cur.batch_id,
         COUNT(r.source_row_number) AS bronze_rows,
         COUNT_IF(r.source_row_kind = 'unit') AS unit_rows,
         COUNT_IF(r.source_row_kind IN ('title', 'header', 'region_banner', 'blank', 'footer')) AS structural_rows,
         COUNT_IF(r.source_row_kind = 'title') AS title_rows,
         COUNT_IF(r.source_row_kind = 'header') AS header_rows,
         COUNT_IF(r.source_row_kind = 'region_banner') AS region_banner_rows,
         COUNT_IF(r.source_row_kind = 'blank') AS blank_rows,
         COUNT_IF(r.source_row_kind = 'footer') AS footer_rows,
         COUNT_IF(r.source_row_kind IS NULL OR r.source_row_kind NOT IN ('unit', 'title', 'header', 'region_banner', 'blank', 'footer')) AS other_rows
  FROM cur LEFT JOIN bronze AS r ON r.batch_id = cur.batch_id
  GROUP BY cur.batch_id
),
-- A batch covering a year the contract's columns do not hold could not be unpivoted.
found AS (
  SELECT COUNT(*) AS current_batches,
         COUNT_IF((CASE WHEN array_contains(split(estimate_years_covered, ','), '2018') THEN 1 ELSE 0 END + CASE WHEN array_contains(split(estimate_years_covered, ','), '2021') THEN 1 ELSE 0 END + CASE WHEN array_contains(split(estimate_years_covered, ','), '2023') THEN 1 ELSE 0 END) <> length(estimate_years_covered) - length(replace(estimate_years_covered, ',', '')) + 1)
           AS unknown_year_batches
  FROM cur
),
silver_rows AS (
  SELECT estimate_year, logical_dataset, estimate_years_covered, batch_id, delivery_version, schema_version, source_sha256, source_row_number, run_id, cleaned_at_utc, code_revision FROM clean
  UNION ALL SELECT estimate_year, logical_dataset, estimate_years_covered, batch_id, delivery_version, schema_version, source_sha256, source_row_number, run_id, cleaned_at_utc, code_revision FROM quarantined
),
whole AS (
  SELECT
    COUNT_IF(estimate_year IS NULL OR logical_dataset IS NULL OR estimate_years_covered IS NULL OR batch_id IS NULL OR delivery_version IS NULL OR schema_version IS NULL OR source_sha256 IS NULL OR source_row_number IS NULL OR run_id IS NULL OR cleaned_at_utc IS NULL OR code_revision IS NULL) AS missing_lineage,
    COUNT_IF(run_id IS NULL OR run_id <> :run_id) AS other_run_rows,
    COUNT(DISTINCT cleaned_at_utc) AS timestamps
  FROM silver_rows
),
-- Silver rows whose Bronze row is not a unit row of a current batch (an old version, a banner, or gone).
unresolved AS (
  SELECT COUNT(*) AS unresolved_rows
  FROM silver_rows AS s
  LEFT JOIN bronze ON s.source_sha256 = bronze.source_sha256 AND s.source_row_number = bronze.source_row_number
    AND s.batch_id = bronze.batch_id AND bronze.source_row_kind = 'unit'
  WHERE bronze.source_row_number IS NULL
),
checks AS (
  -- The whole build
  SELECT CAST(NULL AS STRING) AS batch_id, 'edu_access.03-silver.psa_poverty_stat_clean_candidate' AS table_name, 'current_batches_present' AS check_name,
         CASE WHEN current_batches > 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         'at least 1' AS expected, CAST(current_batches AS STRING) AS actual FROM found
  UNION ALL SELECT CAST(NULL AS STRING) AS batch_id, 'edu_access.03-silver.psa_poverty_stat_clean_candidate' AS table_name, 'estimate_years_known' AS check_name,
         CASE WHEN unknown_year_batches = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(unknown_year_batches AS STRING) AS actual FROM found
  UNION ALL SELECT CAST(NULL AS STRING) AS batch_id, 'edu_access.03-silver.psa_poverty_stat_clean_candidate' AS table_name, 'lineage_complete' AS check_name,
         CASE WHEN missing_lineage = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(missing_lineage AS STRING) AS actual FROM whole
  UNION ALL SELECT CAST(NULL AS STRING) AS batch_id, 'edu_access.03-silver.psa_poverty_stat_clean_candidate' AS table_name, 'rows_resolve_to_current_bronze_units' AS check_name,
         CASE WHEN unresolved_rows = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(unresolved_rows AS STRING) AS actual FROM unresolved
  UNION ALL SELECT CAST(NULL AS STRING) AS batch_id, 'edu_access.03-silver.psa_poverty_stat_clean_candidate' AS table_name, 'rows_built_by_this_run' AS check_name,
         CASE WHEN other_run_rows = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(other_run_rows AS STRING) AS actual FROM whole
  UNION ALL SELECT CAST(NULL AS STRING) AS batch_id, 'edu_access.03-silver.psa_poverty_stat_clean_candidate' AS table_name, 'one_timestamp_per_run' AS check_name,
         CASE WHEN timestamps = 1 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(1 AS STRING) AS expected, CAST(timestamps AS STRING) AS actual FROM whole
  -- Each current batch: every Bronze row is a unit or a known structural row
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_poverty_stat_clean_candidate' AS table_name, 'bronze_rows_accounted' AS check_name,
         CASE WHEN other_rows = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(bronze_rows AS STRING) AS expected, CAST(unit_rows + structural_rows AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_poverty_stat_clean_candidate' AS table_name, 'rule_structural_rows_not_estimates' AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(structural_rows AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_poverty_stat_clean_candidate' AS table_name, 'rows_kind_title' AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(title_rows AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_poverty_stat_clean_candidate' AS table_name, 'rows_kind_header' AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(header_rows AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_poverty_stat_clean_candidate' AS table_name, 'rows_kind_region_banner' AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(region_banner_rows AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_poverty_stat_clean_candidate' AS table_name, 'rows_kind_blank' AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(blank_rows AS STRING) AS actual FROM batches
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_poverty_stat_clean_candidate' AS table_name, 'rows_kind_footer' AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(footer_rows AS STRING) AS actual FROM batches
  -- Each batch and estimate year: reconciliation, keys, values against Bronze, ranges, NULLs
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_poverty_stat_clean_candidate' AS table_name, 'rows_reconcile_' || estimate_year AS check_name,
         CASE WHEN clean_rows + quarantined_rows = unit_rows THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(unit_rows AS STRING) AS expected, CAST(clean_rows + quarantined_rows AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_poverty_stat_clean_candidate' AS table_name, 'psgc_id_unique_' || estimate_year AS check_name,
         CASE WHEN clean_rows - clean_ids = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(clean_rows - clean_ids AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_poverty_stat_clean_candidate' AS table_name, 'psgc_id_valid_' || estimate_year AS check_name,
         CASE WHEN invalid_ids = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(invalid_ids AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_poverty_stat_clean_candidate' AS table_name, 'estimate_year_covered_' || estimate_year AS check_name,
         CASE WHEN uncovered_rows = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(uncovered_rows AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_poverty_stat_clean_candidate' AS table_name, 'poverty_incidence_matches_bronze_' || estimate_year AS check_name,
         CASE WHEN mismatched_poverty_incidence = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(mismatched_poverty_incidence AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_poverty_stat_clean_candidate' AS table_name, 'coefficient_of_variation_matches_bronze_' || estimate_year AS check_name,
         CASE WHEN mismatched_coefficient_of_variation = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(mismatched_coefficient_of_variation AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_poverty_stat_clean_candidate' AS table_name, 'standard_error_matches_bronze_' || estimate_year AS check_name,
         CASE WHEN mismatched_standard_error = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(mismatched_standard_error AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_poverty_stat_clean_candidate' AS table_name, 'ci90_lower_limit_matches_bronze_' || estimate_year AS check_name,
         CASE WHEN mismatched_ci90_lower_limit = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(mismatched_ci90_lower_limit AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_poverty_stat_clean_candidate' AS table_name, 'ci90_upper_limit_matches_bronze_' || estimate_year AS check_name,
         CASE WHEN mismatched_ci90_upper_limit = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(mismatched_ci90_upper_limit AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_poverty_stat_clean_candidate' AS table_name, 'missing_measures_stay_null_' || estimate_year AS check_name,
         CASE WHEN clean_null_cells = kept_blank_cells THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(kept_blank_cells AS STRING) AS expected, CAST(clean_null_cells AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_poverty_stat_clean_candidate' AS table_name, 'estimate_status_valid_' || estimate_year AS check_name,
         CASE WHEN invalid_status_rows = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(invalid_status_rows AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_poverty_stat_clean_candidate' AS table_name, 'poverty_incidence_within_bounds_' || estimate_year AS check_name,
         CASE WHEN incidence_out_of_bounds = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(incidence_out_of_bounds AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_poverty_stat_clean_candidate' AS table_name, 'cv_non_negative_' || estimate_year AS check_name,
         CASE WHEN negative_cv = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(negative_cv AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_poverty_stat_clean_candidate' AS table_name, 'se_non_negative_' || estimate_year AS check_name,
         CASE WHEN negative_se = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(negative_se AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_poverty_stat_clean_candidate' AS table_name, 'ci_contains_estimate_' || estimate_year AS check_name,
         CASE WHEN ci_problems = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(ci_problems AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_poverty_stat_clean_candidate' AS table_name, 'flags_consistent_' || estimate_year AS check_name,
         CASE WHEN inconsistent_flags = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(inconsistent_flags AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_poverty_stat_clean_candidate' AS table_name, 'region_banner_assigned_' || estimate_year AS check_name,
         CASE WHEN no_banner_rows = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(no_banner_rows AS STRING) AS actual FROM years
  -- Each batch and estimate year: quarantine (WARN above 0, FAIL above 1% of the units)
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_poverty_stat_quarantine_candidate' AS table_name, 'quarantine_rate_' || estimate_year AS check_name,
         CASE WHEN quarantined_rows = 0 THEN 'PASS' WHEN quarantined_rows * 100 > unit_rows * 1 THEN 'FAIL' ELSE 'WARN' END AS status,
         '0 (FAIL above 1% of ' || CAST(unit_rows AS STRING) || ')' AS expected, CAST(quarantined_rows AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_poverty_stat_quarantine_candidate' AS table_name, 'quarantine_reason_psgc_id_blank_' || estimate_year AS check_name,
         CASE WHEN reason_psgc_id_blank = 0 THEN 'PASS' ELSE 'WARN' END AS status,
         '0' AS expected, CAST(reason_psgc_id_blank AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_poverty_stat_quarantine_candidate' AS table_name, 'quarantine_reason_psgc_id_malformed_' || estimate_year AS check_name,
         CASE WHEN reason_psgc_id_malformed = 0 THEN 'PASS' ELSE 'WARN' END AS status,
         '0' AS expected, CAST(reason_psgc_id_malformed AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_poverty_stat_quarantine_candidate' AS table_name, 'quarantine_reason_psgc_id_duplicated_' || estimate_year AS check_name,
         CASE WHEN reason_psgc_id_duplicated = 0 THEN 'PASS' ELSE 'WARN' END AS status,
         '0' AS expected, CAST(reason_psgc_id_duplicated AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_poverty_stat_quarantine_candidate' AS table_name, 'quarantine_reason_measure_uncastable_' || estimate_year AS check_name,
         CASE WHEN reason_measure_uncastable = 0 THEN 'PASS' ELSE 'WARN' END AS status,
         '0' AS expected, CAST(reason_measure_uncastable AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_poverty_stat_quarantine_candidate' AS table_name, 'quarantine_reason_incidence_out_of_range_' || estimate_year AS check_name,
         CASE WHEN reason_incidence_out_of_range = 0 THEN 'PASS' ELSE 'WARN' END AS status,
         '0' AS expected, CAST(reason_incidence_out_of_range AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_poverty_stat_quarantine_candidate' AS table_name, 'quarantine_reason_cv_negative_' || estimate_year AS check_name,
         CASE WHEN reason_cv_negative = 0 THEN 'PASS' ELSE 'WARN' END AS status,
         '0' AS expected, CAST(reason_cv_negative AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_poverty_stat_quarantine_candidate' AS table_name, 'quarantine_reason_se_negative_' || estimate_year AS check_name,
         CASE WHEN reason_se_negative = 0 THEN 'PASS' ELSE 'WARN' END AS status,
         '0' AS expected, CAST(reason_se_negative AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_poverty_stat_quarantine_candidate' AS table_name, 'quarantine_reason_ci_inconsistent_' || estimate_year AS check_name,
         CASE WHEN reason_ci_inconsistent = 0 THEN 'PASS' ELSE 'WARN' END AS status,
         '0' AS expected, CAST(reason_ci_inconsistent AS STRING) AS actual FROM years
  -- Each batch and estimate year: statistical warnings, flagged on the row and never corrected (WARN)
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_poverty_stat_clean_candidate' AS table_name, 'flag_cv_over_20_' || estimate_year AS check_name,
         CASE WHEN flagged_cv_over_20 = 0 THEN 'PASS' ELSE 'WARN' END AS status,
         '0' AS expected, CAST(flagged_cv_over_20 AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_poverty_stat_clean_candidate' AS table_name, 'flag_se_cv_inconsistent_' || estimate_year AS check_name,
         CASE WHEN flagged_se_cv_inconsistent = 0 THEN 'PASS' ELSE 'WARN' END AS status,
         '0' AS expected, CAST(flagged_se_cv_inconsistent AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_poverty_stat_clean_candidate' AS table_name, 'flag_lower_limit_not_positive_' || estimate_year AS check_name,
         CASE WHEN flagged_lower_limit_not_positive = 0 THEN 'PASS' ELSE 'WARN' END AS status,
         '0' AS expected, CAST(flagged_lower_limit_not_positive AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_poverty_stat_clean_candidate' AS table_name, 'flag_partial_estimate_' || estimate_year AS check_name,
         CASE WHEN partial_rows = 0 THEN 'PASS' ELSE 'WARN' END AS status,
         '0' AS expected, CAST(partial_rows AS STRING) AS actual FROM years
  -- Each batch and estimate year: how many rows each rule changed or marked (records, always PASS)
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_poverty_stat_clean_candidate' AS table_name, 'rule_no_estimate_' || estimate_year AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(no_estimate_rows AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_poverty_stat_clean_candidate' AS table_name, 'rule_psgc_id_padded_' || estimate_year AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(padded_ids AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_poverty_stat_clean_candidate' AS table_name, 'rule_text_whitespace_normalized_' || estimate_year AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(whitespace_rows AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.psa_poverty_stat_clean_candidate' AS table_name, 'rule_blank_measures_to_null_' || estimate_year AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(kept_blank_cells AS STRING) AS actual FROM years
)
SELECT * FROM checks
) AS results;

-- A failed build: record it before stopping. The Silver tables are not touched.
MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (
  SELECT :run_id AS run_id, COUNT_IF(status = 'FAIL') AS fails
  FROM edu_access.`01-control`.data_quality_results
  WHERE run_id = :run_id AND source_id = 'psa_poverty_stat' AND layer = 'silver'
    AND checked_at_utc >= session.silver_gate_started_at_utc
) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'silver_build' AND t.source_id = 'psa_poverty_stat'
WHEN MATCHED AND s.fails > 0 THEN UPDATE SET
  status = 'failed', finished_at_utc = current_timestamp(), failure_stage = 'gate',
  error_message = CAST(s.fails AS STRING) || ' FAIL result(s) in data_quality_results';

-- Stop here, before publishing, if anything failed in this execution.
SELECT CASE WHEN COUNT(*) > 0
            THEN raise_error('Silver gate failed for psa_poverty_stat: ' || CAST(COUNT(*) AS STRING)
                             || ' FAIL result(s) in data_quality_results for run ' || :run_id)
       END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'psa_poverty_stat' AND layer = 'silver' AND status = 'FAIL'
  AND checked_at_utc >= session.silver_gate_started_at_utc;

-- Every check passed: publish. Quarantine first, then clean, the table Gold reads. Each copy is
-- one atomic Delta commit, but the pair is not, so the run is 'succeeded' only after both. If the
-- task dies in between, the run stays 'running', and Gold trusts a Silver table only when the
-- run_id its rows carry is a succeeded silver_build run (D-025).
CREATE OR REPLACE TABLE edu_access.`03-silver`.psa_poverty_stat_quarantine USING DELTA AS
SELECT * FROM edu_access.`03-silver`.psa_poverty_stat_quarantine_candidate;

ALTER TABLE edu_access.`03-silver`.psa_poverty_stat_quarantine OWNER TO `reached-hq`;

CREATE OR REPLACE TABLE edu_access.`03-silver`.psa_poverty_stat_clean USING DELTA AS
SELECT * FROM edu_access.`03-silver`.psa_poverty_stat_clean_candidate;

ALTER TABLE edu_access.`03-silver`.psa_poverty_stat_clean OWNER TO `reached-hq`;

-- Published: the run succeeded.
MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (SELECT :run_id AS run_id) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'silver_build' AND t.source_id = 'psa_poverty_stat'
WHEN MATCHED THEN UPDATE SET
  status = 'succeeded', finished_at_utc = current_timestamp(), failure_stage = NULL, error_message = NULL;
