-- Integration gate for psa_poverty_stat (#92, D-054).
--
-- The job task after the build. It checks psa_poverty_psgc_map_candidate against its two inputs,
-- one row per check in data_quality_results (layer 'integration'). On any FAIL it records the run
-- 'failed' and stops before publishing, so psa_poverty_psgc_map keeps the last map that passed.
-- Otherwise it copies the candidate to the map table and records the run 'succeeded'.
-- FAIL: a Silver row missing, repeated or added; a PSGC unit taken twice in one estimate year; a
-- matched row whose unit, psgc_name, level or Correspondence Code does not hold against the master
-- PSGC quarter; a status, method or review status outside the contract or in a forbidden combination
-- (the map has no name rule, so a name method fails here); an estimate, flag or lineage value that
-- differs from its Silver row; more than one master PSGC period.
-- WARN: pending reviews, unmatched and ambiguous rows, matched rows whose PSA name differs from the
-- PSGC name (D-030 lists them for review), and PSGC cities and municipalities with no PSA row in an
-- estimate year (D-028), split by what PSGC says about them: highly urbanized cities, units with no
-- Correspondence Code, and the rest. Results hold counts, never row values.

DECLARE OR REPLACE VARIABLE integration_gate_started_at_utc TIMESTAMP;
SET VARIABLE integration_gate_started_at_utc = current_timestamp();

INSERT INTO edu_access.`01-control`.data_quality_results
  (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, CAST(NULL AS STRING), 'psa_poverty_stat', 'integration', 'edu_access.04-integration.psa_poverty_psgc_map_candidate', check_name, status, expected, actual,
       current_timestamp(), :code_revision
FROM (
WITH pv AS (SELECT * FROM edu_access.`03-silver`.psa_poverty_stat_clean),
master AS (SELECT * FROM edu_access.`03-silver`.psa_psgc_clean WHERE is_master_reference),
units AS (SELECT psgc_code, name, correspondence_code, geographic_level FROM master WHERE geographic_level IN ('City', 'Mun', 'SubMun')),
m AS (SELECT * FROM edu_access.`04-integration`.psa_poverty_psgc_map_candidate),
totals AS (
  SELECT (SELECT COUNT(*) FROM pv) AS pv_rows,
         (SELECT COUNT(*) FROM units) AS psgc_units,
         (SELECT COUNT(*) FROM pv LEFT JOIN m ON m.psgc_id = pv.psgc_id AND m.estimate_year = pv.estimate_year
          WHERE m.psgc_id IS NULL) AS missing_rows,
         (SELECT COUNT(DISTINCT publication_period) FROM edu_access.`03-silver`.psa_psgc_clean WHERE is_master_reference) AS master_periods,
         (SELECT MIN(publication_period) FROM master) AS master_period,
         (SELECT COUNT(*) FROM m WHERE m.psgc_version IS DISTINCT FROM (SELECT MIN(publication_period) FROM master)
             OR m.source_id IS DISTINCT FROM 'psa_poverty_stat') AS other_version_rows,
         -- Each map value against its own Silver row: no estimate, flag, place field or lineage rewritten.
         (SELECT COUNT(*) FROM m JOIN pv ON pv.psgc_id = m.psgc_id AND pv.estimate_year = m.estimate_year
          WHERE m.correspondence_code IS DISTINCT FROM pv.correspondence_code OR m.municipality IS DISTINCT FROM pv.municipality
             OR m.region IS DISTINCT FROM pv.region OR m.poverty_incidence IS DISTINCT FROM pv.poverty_incidence
             OR m.coefficient_of_variation IS DISTINCT FROM pv.coefficient_of_variation OR m.standard_error IS DISTINCT FROM pv.standard_error
             OR m.ci90_lower_limit IS DISTINCT FROM pv.ci90_lower_limit OR m.ci90_upper_limit IS DISTINCT FROM pv.ci90_upper_limit
             OR m.estimate_status IS DISTINCT FROM pv.estimate_status OR m.cv_over_20 IS DISTINCT FROM pv.cv_over_20
             OR m.se_cv_inconsistent IS DISTINCT FROM pv.se_cv_inconsistent OR m.lower_limit_not_positive IS DISTINCT FROM pv.lower_limit_not_positive
             OR m.logical_dataset IS DISTINCT FROM pv.logical_dataset OR m.estimate_years_covered IS DISTINCT FROM pv.estimate_years_covered
             OR m.delivery_version IS DISTINCT FROM pv.delivery_version OR m.batch_id IS DISTINCT FROM pv.batch_id
             OR m.source_sha256 IS DISTINCT FROM pv.source_sha256 OR m.source_row_number IS DISTINCT FROM pv.source_row_number) AS changed_rows
),
agg AS (
  SELECT
    COUNT(*) AS map_rows,
    COUNT(DISTINCT m.source_row_ref) AS map_refs,
    COUNT(DISTINCT m.psgc_id || '/' || CAST(m.estimate_year AS STRING)) AS map_keys,
    COUNT_IF(m.source_row_ref IS DISTINCT FROM m.psgc_id || '/' || CAST(m.estimate_year AS STRING)) AS bad_ref,
    COUNT_IF(m.match_status = 'matched') AS matched_rows,
    COUNT(DISTINCT CASE WHEN m.match_status = 'matched' THEN m.psgc_code || '/' || CAST(m.estimate_year AS STRING) END) AS matched_codes,
    COUNT_IF(m.match_status = 'matched' AND (m.psgc_code IS NULL OR u.psgc_code IS NULL)) AS matched_without_unit,
    COUNT_IF((m.psgc_code IS NOT NULL AND m.psgc_name IS DISTINCT FROM u.name) OR (m.psgc_code IS NULL AND m.psgc_name IS NOT NULL)) AS psgc_name_mismatch,
    COUNT_IF(m.geographic_level IS DISTINCT FROM CASE u.geographic_level WHEN 'City' THEN 'city_mun' WHEN 'Mun' THEN 'city_mun' WHEN 'SubMun' THEN 'sub_mun' END) AS level_mismatch,
    COUNT_IF(m.match_status <> 'matched' AND m.psgc_code IS NOT NULL) AS unmatched_with_code,
    COUNT_IF(m.match_status IS NULL OR m.match_status NOT IN ('matched', 'unmatched', 'ambiguous')) AS bad_status,
    COUNT_IF((m.match_status = 'matched' AND m.match_method IS DISTINCT FROM 'correspondence_code') OR (m.match_status <> 'matched' AND m.match_method IS NOT NULL)) AS bad_method,
    COUNT_IF(COALESCE(m.match_method IN ('name_exact', 'name_old', 'name_normalized', 'reviewed_alias'), FALSE)) AS name_rule_rows,
    COUNT_IF(m.review_status IS NULL OR m.review_status NOT IN ('rule', 'pending')) AS bad_review,
    COUNT_IF(NOT COALESCE((m.match_status = 'matched' AND m.review_status = 'rule' AND m.match_method IS NOT NULL AND m.psgc_code IS NOT NULL) OR (m.match_status IN ('ambiguous', 'unmatched') AND m.review_status = 'pending' AND m.match_method IS NULL AND m.psgc_code IS NULL), FALSE)) AS bad_combination,
    -- D-030 and D-034, read again: the six-digit ID plus 000 is the source code, and the unit carries it.
    COUNT_IF(m.match_status = 'matched' AND (NOT regexp_like(m.psgc_id, '^[0-9]{6}$') OR m.correspondence_code IS DISTINCT FROM m.psgc_id || '000'
             OR u.correspondence_code IS DISTINCT FROM m.correspondence_code)) AS correspondence_mismatch,
    COUNT_IF(m.names_agree IS DISTINCT FROM CASE WHEN m.match_status = 'matched' THEN upper(COALESCE(m.municipality, '')) = upper(u.name) END) AS bad_names_agree,
    COUNT_IF(m.source_row_ref IS NULL OR m.batch_id IS NULL OR m.source_sha256 IS NULL OR m.source_row_number IS NULL OR m.logical_dataset IS NULL OR m.delivery_version IS NULL OR m.run_id IS NULL OR m.built_at_utc IS NULL OR m.code_revision IS NULL OR (m.psgc_code IS NOT NULL AND (m.psgc_batch_id IS NULL OR m.psgc_source_row_number IS NULL))) AS missing_lineage,
    COUNT_IF(m.run_id IS NULL OR m.run_id <> :run_id) AS other_run_rows,
    COUNT_IF(m.review_status = 'pending') AS pending_rows,
    COUNT_IF(m.match_status = 'unmatched') AS unmatched_rows,
    COUNT_IF(m.match_status = 'ambiguous') AS ambiguous_rows,
    COUNT_IF(m.match_status = 'matched' AND NOT m.names_agree) AS names_differ_rows,
    COUNT_IF(m.match_status = 'matched' AND m.match_method = 'correspondence_code') AS method_correspondence_code
  FROM m
  LEFT JOIN units AS u ON u.psgc_code = m.psgc_code
),
stats AS (SELECT * FROM agg CROSS JOIN totals),
-- Coverage per estimate year, from the PSGC side: the cities and municipalities no row matched (D-028).
years AS (SELECT DISTINCT estimate_year FROM pv),
city_mun AS (SELECT psgc_code, city_class, correspondence_code FROM master WHERE geographic_level IN ('City', 'Mun')),
not_in_source AS (
  SELECT y.estimate_year, c.psgc_code, c.city_class, c.correspondence_code
  FROM years AS y CROSS JOIN city_mun AS c
  LEFT JOIN m ON m.psgc_code = c.psgc_code AND m.estimate_year = y.estimate_year AND m.match_status = 'matched'
  WHERE m.psgc_code IS NULL
),
coverage AS (
  SELECT y.estimate_year,
    (SELECT COUNT(*) FROM not_in_source AS n WHERE n.estimate_year = y.estimate_year) AS not_in_source,
    (SELECT COUNT(*) FROM not_in_source AS n WHERE n.estimate_year = y.estimate_year AND n.city_class = 'HUC') AS huc,
    (SELECT COUNT(*) FROM not_in_source AS n WHERE n.estimate_year = y.estimate_year AND n.correspondence_code IS NULL AND COALESCE(n.city_class, '') <> 'HUC') AS no_code,
    (SELECT COUNT(*) FROM not_in_source AS n WHERE n.estimate_year = y.estimate_year AND n.correspondence_code IS NOT NULL AND COALESCE(n.city_class, '') <> 'HUC') AS other,
    -- A city whose sub-municipalities have rows (Manila): PSGC rolls a sub-municipality up by its first 5 digits + 00000.
    (SELECT COUNT(DISTINCT n.psgc_code) FROM not_in_source AS n JOIN m ON m.estimate_year = n.estimate_year AND m.geographic_level = 'sub_mun'
       AND substr(m.psgc_code, 1, 5) || '00000' = n.psgc_code WHERE n.estimate_year = y.estimate_year) AS with_sub_mun,
    (SELECT COUNT(*) FROM m WHERE m.estimate_year = y.estimate_year AND m.geographic_level = 'sub_mun') AS sub_mun_rows,
    (SELECT COUNT(*) FROM m WHERE m.estimate_year = y.estimate_year AND m.estimate_status = 'no_estimate') AS no_estimate_rows
  FROM years AS y
),
checks AS (
  SELECT 'inputs_present' AS check_name, CASE WHEN pv_rows > 0 AND psgc_units > 0 THEN 'PASS' ELSE 'FAIL' END AS status, 'poverty rows and PSGC units' AS expected, CAST(CAST(pv_rows AS STRING) || ' / ' || CAST(psgc_units AS STRING) AS STRING) AS actual FROM stats
  UNION ALL SELECT 'rows_reconcile', CASE WHEN map_rows = pv_rows THEN 'PASS' ELSE 'FAIL' END, CAST(pv_rows AS STRING), CAST(map_rows AS STRING) FROM stats
  UNION ALL SELECT 'source_rows_not_dropped', CASE WHEN missing_rows = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(missing_rows AS STRING) FROM stats
  UNION ALL SELECT 'one_row_per_source_row', CASE WHEN map_keys = map_rows AND map_refs = map_rows AND bad_ref = 0 THEN 'PASS' ELSE 'FAIL' END, CAST(map_rows AS STRING), CAST(LEAST(map_keys, map_refs) - bad_ref AS STRING) FROM stats
  UNION ALL SELECT 'psgc_code_taken_once', CASE WHEN matched_codes = matched_rows THEN 'PASS' ELSE 'FAIL' END, CAST(matched_rows AS STRING), CAST(matched_codes AS STRING) FROM stats
  UNION ALL SELECT 'matched_has_psgc_unit', CASE WHEN matched_without_unit = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(matched_without_unit AS STRING) FROM stats
  UNION ALL SELECT 'psgc_name_matches_unit', CASE WHEN psgc_name_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(psgc_name_mismatch AS STRING) FROM stats
  UNION ALL SELECT 'geographic_level_matches_unit', CASE WHEN level_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(level_mismatch AS STRING) FROM stats
  UNION ALL SELECT 'unmatched_has_no_psgc', CASE WHEN unmatched_with_code = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(unmatched_with_code AS STRING) FROM stats
  UNION ALL SELECT 'status_valid', CASE WHEN bad_status = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_status AS STRING) FROM stats
  UNION ALL SELECT 'method_valid', CASE WHEN bad_method = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_method AS STRING) FROM stats
  UNION ALL SELECT 'no_name_rule_match', CASE WHEN name_rule_rows = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(name_rule_rows AS STRING) FROM stats
  UNION ALL SELECT 'review_status_valid', CASE WHEN bad_review = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_review AS STRING) FROM stats
  UNION ALL SELECT 'status_combination_valid', CASE WHEN bad_combination = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_combination AS STRING) FROM stats
  UNION ALL SELECT 'correspondence_is_the_old_code', CASE WHEN correspondence_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(correspondence_mismatch AS STRING) FROM stats
  UNION ALL SELECT 'names_agree_valid', CASE WHEN bad_names_agree = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_names_agree AS STRING) FROM stats
  UNION ALL SELECT 'estimates_unchanged', CASE WHEN changed_rows = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(changed_rows AS STRING) FROM stats
  UNION ALL SELECT 'one_psgc_version', CASE WHEN master_periods = 1 THEN 'PASS' ELSE 'FAIL' END, '1', CAST(master_periods AS STRING) FROM stats
  UNION ALL SELECT 'psgc_version_is_master', CASE WHEN other_version_rows = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(other_version_rows AS STRING) FROM stats
  UNION ALL SELECT 'lineage_complete', CASE WHEN missing_lineage = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(missing_lineage AS STRING) FROM stats
  UNION ALL SELECT 'rows_built_by_this_run', CASE WHEN other_run_rows = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(other_run_rows AS STRING) FROM stats
  UNION ALL SELECT 'review_pending', CASE WHEN pending_rows = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(pending_rows AS STRING) FROM stats
  UNION ALL SELECT 'unmatched', CASE WHEN unmatched_rows = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(unmatched_rows AS STRING) FROM stats
  UNION ALL SELECT 'ambiguous', CASE WHEN ambiguous_rows = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(ambiguous_rows AS STRING) FROM stats
  UNION ALL SELECT 'names_differ', CASE WHEN names_differ_rows = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(names_differ_rows AS STRING) FROM stats
  UNION ALL SELECT 'method_correspondence_code', 'PASS', CAST(NULL AS STRING), CAST(method_correspondence_code AS STRING) FROM stats
  UNION ALL SELECT 'match_rate_percent', 'PASS', CAST(NULL AS STRING), CAST(CASE WHEN map_rows = 0 THEN 0 ELSE ROUND(100.0 * matched_rows / map_rows, 2) END AS STRING) FROM stats
  UNION ALL SELECT 'psgc_units_not_in_source_' || CAST(estimate_year AS STRING), CASE WHEN not_in_source = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(not_in_source AS STRING) FROM coverage
  UNION ALL SELECT 'not_in_source_huc_' || CAST(estimate_year AS STRING), 'PASS', CAST(NULL AS STRING), CAST(huc AS STRING) FROM coverage
  UNION ALL SELECT 'not_in_source_without_correspondence_code_' || CAST(estimate_year AS STRING), 'PASS', CAST(NULL AS STRING), CAST(no_code AS STRING) FROM coverage
  UNION ALL SELECT 'not_in_source_other_' || CAST(estimate_year AS STRING), 'PASS', CAST(NULL AS STRING), CAST(other AS STRING) FROM coverage
  UNION ALL SELECT 'not_in_source_with_sub_municipality_rows_' || CAST(estimate_year AS STRING), 'PASS', CAST(NULL AS STRING), CAST(with_sub_mun AS STRING) FROM coverage
  UNION ALL SELECT 'sub_municipality_rows_' || CAST(estimate_year AS STRING), 'PASS', CAST(NULL AS STRING), CAST(sub_mun_rows AS STRING) FROM coverage
  UNION ALL SELECT 'no_estimate_rows_' || CAST(estimate_year AS STRING), 'PASS', CAST(NULL AS STRING), CAST(no_estimate_rows AS STRING) FROM coverage
)
SELECT * FROM checks
) AS results;

-- A failed build: record it before stopping. The map table is not touched.
MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (
  SELECT :run_id AS run_id, COUNT_IF(status = 'FAIL') AS fails
  FROM edu_access.`01-control`.data_quality_results
  WHERE run_id = :run_id AND source_id = 'psa_poverty_stat' AND layer = 'integration'
    AND checked_at_utc >= session.integration_gate_started_at_utc
) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'integration_build' AND t.source_id = 'psa_poverty_stat'
WHEN MATCHED AND s.fails > 0 THEN UPDATE SET
  status = 'failed', finished_at_utc = current_timestamp(), failure_stage = 'gate',
  error_message = CAST(s.fails AS STRING) || ' FAIL result(s) in data_quality_results';

SELECT CASE WHEN COUNT(*) > 0
            THEN raise_error('Integration gate failed for psa_poverty_stat: ' || CAST(COUNT(*) AS STRING)
                             || ' FAIL result(s) in data_quality_results for run ' || :run_id)
       END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'psa_poverty_stat' AND layer = 'integration' AND status = 'FAIL'
  AND checked_at_utc >= session.integration_gate_started_at_utc;

-- Every check passed: publish, then record the run 'succeeded'.
CREATE OR REPLACE TABLE edu_access.`04-integration`.psa_poverty_psgc_map USING DELTA AS
SELECT * FROM edu_access.`04-integration`.psa_poverty_psgc_map_candidate;

ALTER TABLE edu_access.`04-integration`.psa_poverty_psgc_map OWNER TO `reached-hq`;

MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (SELECT :run_id AS run_id) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'integration_build' AND t.source_id = 'psa_poverty_stat'
WHEN MATCHED THEN UPDATE SET
  status = 'succeeded', finished_at_utc = current_timestamp(), failure_stage = NULL, error_message = NULL;
