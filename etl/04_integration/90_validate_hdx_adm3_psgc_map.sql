-- Integration gate for hdx_boundaries. Generated from config/integration/hdx_adm3_psgc.json by src/integration/hdx_adm3_psgc.py:
--   python -m src.integration.hdx_adm3_psgc gate > etl/04_integration/90_validate_hdx_adm3_psgc_map.sql
-- Do not edit by hand; tests/test_integration_hdx.py fails if it differs.
--
-- The job task after the build. It checks hdx_adm3_psgc_map_candidate, one row per check in
-- data_quality_results (layer 'integration'). On any FAIL it records the run 'failed' and stops
-- before publishing, so hdx_adm3_psgc_map keeps the last map that passed. Otherwise it copies
-- the candidate to the map table and records the run 'succeeded'. WARN (pending reviews, unmatched,
-- ambiguous, an override whose P-code is not in the HDX release it was reviewed for, PSGC cities and municipalities
-- no feature matched, counted per HDX release) is recorded and the map is
-- published. Results hold counts, never row values.

DECLARE OR REPLACE VARIABLE integration_gate_started_at_utc TIMESTAMP;
SET VARIABLE integration_gate_started_at_utc = current_timestamp();

INSERT INTO edu_access.`01-control`.data_quality_results
  (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, CAST(NULL AS STRING), 'hdx_boundaries', 'integration', 'edu_access.04-integration.hdx_adm3_psgc_map_candidate', check_name, status, expected, actual,
       current_timestamp(), :code_revision
FROM (
WITH hdx AS (SELECT adm3_pcode, adm2_pcode, valid_on, rpad(substr(adm2_pcode, 3), 10, '0') AS prov10 FROM edu_access.`03-silver`.hdx_adm3_clean),
psgc AS (SELECT * FROM edu_access.`03-silver`.psa_psgc_clean WHERE is_master_reference),
units AS (SELECT psgc_code, name, correspondence_code FROM psgc WHERE geographic_level IN ('City', 'Mun')),
province AS (
  SELECT h.adm3_pcode, h.valid_on, substr(COALESCE(MIN(p1.psgc_code), MIN(p2.psgc_code)), 1, 5) AS prov5
  FROM hdx AS h
  LEFT JOIN psgc AS p1 ON p1.psgc_code = h.prov10
  LEFT JOIN psgc AS p2 ON substr(h.prov10, 3, 1) = '0' AND p2.correspondence_code = substr(h.prov10, 1, 2) || substr(h.prov10, 4, 2) || substr(h.prov10, 6, 2) || substr(h.prov10, 8, 3)
  GROUP BY h.adm3_pcode, h.valid_on
),
overrides AS (SELECT * FROM (VALUES ('PH0907226', DATE '2025-02-13', '0907226000', 'code_renamed', 'renamed LGU: COD-AB Bacungan (Leon T. Postigo) is PSGC Leon T. Postigo, Zamboanga del Norte'), ('PH1004217', DATE '2025-02-13', '1004217000', 'code_renamed', 'renamed LGU: COD-AB Don Victoriano Chiongbian (Don Mariano Marcos) is PSGC Don Victoriano, Misamis Occidental'), ('PH1102324', DATE '2025-02-13', '1102324000', 'code_renamed', 'renamed LGU: COD-AB San Isidro is PSGC Sawata, Davao del Norte'), ('PH1705323', DATE '2025-02-13', '1705323000', 'code_renamed', 'renamed LGU: COD-AB Rizal (Marcos) is PSGC Dr. Jose P. Rizal, Palawan'), ('PH1909901', DATE '2025-02-13', CAST(NULL AS STRING), CAST(NULL AS STRING), 'Special Geographic Area unit (SGA - Carmen): no PSGC equivalent until a spatial check (D-031)'), ('PH1909902', DATE '2025-02-13', CAST(NULL AS STRING), CAST(NULL AS STRING), 'Special Geographic Area unit (SGA - Kabacan): no PSGC equivalent until a spatial check (D-031)'), ('PH1909903', DATE '2025-02-13', CAST(NULL AS STRING), CAST(NULL AS STRING), 'Special Geographic Area unit (SGA - Midsayap I): no PSGC equivalent until a spatial check (D-031)'), ('PH1909904', DATE '2025-02-13', CAST(NULL AS STRING), CAST(NULL AS STRING), 'Special Geographic Area unit (SGA - Midsayap II): no PSGC equivalent until a spatial check (D-031)'), ('PH1909905', DATE '2025-02-13', CAST(NULL AS STRING), CAST(NULL AS STRING), 'Special Geographic Area unit (SGA - Pigkawayan): no PSGC equivalent until a spatial check (D-031)'), ('PH1909906', DATE '2025-02-13', CAST(NULL AS STRING), CAST(NULL AS STRING), 'Special Geographic Area unit (SGA - Pikit I): no PSGC equivalent until a spatial check (D-031)'), ('PH1909907', DATE '2025-02-13', CAST(NULL AS STRING), CAST(NULL AS STRING), 'Special Geographic Area unit (SGA - Pikit II): no PSGC equivalent until a spatial check (D-031)'), ('PH1909908', DATE '2025-02-13', CAST(NULL AS STRING), CAST(NULL AS STRING), 'Special Geographic Area unit (SGA - Pikit III): no PSGC equivalent until a spatial check (D-031)')) AS v(adm3_pcode, source_reference_date, psgc_code, match_method, reason)),
totals AS (
  SELECT (SELECT COUNT(*) FROM hdx) AS hdx_rows, (SELECT COUNT(*) FROM units) AS psgc_units,
         (SELECT COUNT(*) FROM overrides AS o JOIN hdx AS h ON h.adm3_pcode = o.adm3_pcode AND h.valid_on = o.source_reference_date) AS overrides_present,
         (SELECT COUNT(*) FROM overrides AS o LEFT JOIN hdx AS h ON h.adm3_pcode = o.adm3_pcode AND h.valid_on = o.source_reference_date
          WHERE h.adm3_pcode IS NULL) AS overrides_missing,
         (SELECT COUNT(DISTINCT publication_period) FROM psgc) AS master_periods,
         -- Per HDX release: each (release, PSGC unit) pair with no matched feature in that release.
         (SELECT COUNT(*) FROM (SELECT DISTINCT valid_on FROM hdx) AS r CROSS JOIN units AS u
          LEFT JOIN (SELECT DISTINCT source_reference_date, psgc_code FROM edu_access.`04-integration`.hdx_adm3_psgc_map_candidate WHERE match_status = 'matched') AS mm
            ON mm.psgc_code = u.psgc_code AND mm.source_reference_date = r.valid_on
          WHERE mm.psgc_code IS NULL) AS units_without_feature
),
agg AS (
  SELECT
    COUNT(*) AS map_rows,
    COUNT(DISTINCT m.source_row_ref) AS map_features,
    COUNT_IF(m.match_status = 'matched') AS matched_rows,
    COUNT(DISTINCT CASE WHEN m.match_status = 'matched' THEN m.psgc_code || '/' || CAST(m.source_reference_date AS STRING) END) AS matched_codes,
    COUNT_IF(m.match_status = 'matched' AND (m.psgc_code IS NULL OR u.psgc_code IS NULL)) AS matched_without_unit,
    COUNT_IF(m.match_status <> 'matched' AND m.psgc_code IS NOT NULL) AS unmatched_with_code,
    COUNT_IF(m.match_status IS NULL OR m.match_status NOT IN ('matched', 'unmatched', 'ambiguous')) AS bad_status,
    COUNT_IF((m.match_status = 'matched' AND (m.match_method IS NULL OR m.match_method NOT IN ('code', 'code_renamed', 'code_region_moved', 'correspondence_code', 'name_exact', 'name_old', 'name_normalized', 'reviewed_alias', 'spatial'))) OR (m.match_status = 'ambiguous' AND m.match_method IS NOT NULL)) AS bad_method,
    COUNT_IF(m.review_status IS NULL OR m.review_status NOT IN ('rule', 'reviewed', 'pending')) AS bad_review,
    COUNT_IF(NOT COALESCE((m.match_status = 'matched' AND m.review_status IN ('rule', 'reviewed') AND m.match_method IS NOT NULL AND m.psgc_code IS NOT NULL) OR (m.match_status = 'ambiguous' AND m.review_status = 'pending' AND m.match_method IS NULL AND m.psgc_code IS NULL) OR (m.match_status = 'unmatched' AND m.review_status IN ('pending', 'reviewed') AND m.match_method IS NULL AND m.psgc_code IS NULL), FALSE)) AS bad_combination,
    COUNT_IF(m.match_status = 'matched' AND (m.psgc_name IS NULL OR u.name IS NULL OR m.psgc_name <> u.name)) AS psgc_name_mismatch,
    COUNT_IF(COALESCE(m.match_method IN ('name_exact', 'name_old', 'name_normalized') AND (pr.prov5 IS NULL OR substr(m.psgc_code, 1, 5) <> pr.prov5), FALSE)) AS name_province_mismatch,
    COUNT_IF(m.match_method = 'code' AND m.review_status = 'rule' AND m.psgc_code <> m.code_candidate) AS code_mismatch,
    COUNT_IF(m.match_method = 'correspondence_code' AND m.review_status = 'rule' AND (u.correspondence_code IS NULL OR u.correspondence_code <> substr(m.code_candidate, 1, 2) || substr(m.code_candidate, 4, 2) || substr(m.code_candidate, 6, 2) || substr(m.code_candidate, 8, 3))) AS correspondence_mismatch,
    COUNT_IF(m.match_method = 'code_region_moved' AND m.review_status = 'rule' AND (m.code_candidate NOT LIKE '19%' OR m.psgc_code <> '09' || substr(m.code_candidate, 3))) AS region_mismatch,
    COUNT_IF(m.review_status = 'reviewed') AS overrides_used,
    COUNT_IF(m.source_row_ref IS NULL OR m.batch_id IS NULL OR m.source_sha256 IS NULL OR m.source_row_number IS NULL OR m.run_id IS NULL OR m.built_at_utc IS NULL OR m.code_revision IS NULL OR (m.psgc_code IS NOT NULL AND m.psgc_batch_id IS NULL)) AS missing_lineage,
    COUNT_IF(m.run_id IS NULL OR m.run_id <> :run_id) AS other_run_rows,
    COUNT_IF(m.review_status = 'pending') AS pending_rows,
    COUNT_IF(m.match_status = 'unmatched') AS unmatched_rows,
    COUNT_IF(m.match_status = 'ambiguous') AS ambiguous_rows,
    COUNT_IF(m.match_status = 'matched' AND m.match_method = 'code') AS method_code,
    COUNT_IF(m.match_status = 'matched' AND m.match_method = 'code_renamed') AS method_code_renamed,
    COUNT_IF(m.match_status = 'matched' AND m.match_method = 'code_region_moved') AS method_code_region_moved,
    COUNT_IF(m.match_status = 'matched' AND m.match_method = 'correspondence_code') AS method_correspondence_code,
    COUNT_IF(m.match_status = 'matched' AND m.match_method = 'name_exact') AS method_name_exact,
    COUNT_IF(m.match_status = 'matched' AND m.match_method = 'name_old') AS method_name_old,
    COUNT_IF(m.match_status = 'matched' AND m.match_method = 'name_normalized') AS method_name_normalized,
    COUNT_IF(m.match_status = 'matched' AND m.match_method = 'reviewed_alias') AS method_reviewed_alias,
    COUNT_IF(m.match_status = 'matched' AND m.match_method = 'spatial') AS method_spatial
  FROM edu_access.`04-integration`.hdx_adm3_psgc_map_candidate AS m
  LEFT JOIN units AS u ON u.psgc_code = m.psgc_code
  LEFT JOIN province AS pr ON pr.adm3_pcode = m.adm3_pcode AND pr.valid_on = m.source_reference_date
),
stats AS (SELECT * FROM agg CROSS JOIN totals),
checks AS (
  SELECT 'inputs_present' AS check_name, CASE WHEN hdx_rows > 0 AND psgc_units > 0 THEN 'PASS' ELSE 'FAIL' END AS status, 'HDX rows and PSGC units' AS expected, CAST(CAST(hdx_rows AS STRING) || ' / ' || CAST(psgc_units AS STRING) AS STRING) AS actual FROM stats
  UNION ALL SELECT 'rows_reconcile' AS check_name, CASE WHEN map_rows = hdx_rows THEN 'PASS' ELSE 'FAIL' END AS status, CAST(hdx_rows AS STRING) AS expected, CAST(map_rows AS STRING) AS actual FROM stats
  UNION ALL SELECT 'one_row_per_feature' AS check_name, CASE WHEN map_features = map_rows THEN 'PASS' ELSE 'FAIL' END AS status, CAST(map_rows AS STRING) AS expected, CAST(map_features AS STRING) AS actual FROM stats
  UNION ALL SELECT 'psgc_code_taken_once' AS check_name, CASE WHEN matched_codes = matched_rows THEN 'PASS' ELSE 'FAIL' END AS status, CAST(matched_rows AS STRING) AS expected, CAST(matched_codes AS STRING) AS actual FROM stats
  UNION ALL SELECT 'matched_has_psgc_unit' AS check_name, CASE WHEN matched_without_unit = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '0' AS expected, CAST(matched_without_unit AS STRING) AS actual FROM stats
  UNION ALL SELECT 'unmatched_has_no_psgc' AS check_name, CASE WHEN unmatched_with_code = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '0' AS expected, CAST(unmatched_with_code AS STRING) AS actual FROM stats
  UNION ALL SELECT 'status_valid' AS check_name, CASE WHEN bad_status = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '0' AS expected, CAST(bad_status AS STRING) AS actual FROM stats
  UNION ALL SELECT 'method_valid' AS check_name, CASE WHEN bad_method = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '0' AS expected, CAST(bad_method AS STRING) AS actual FROM stats
  UNION ALL SELECT 'review_status_valid' AS check_name, CASE WHEN bad_review = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '0' AS expected, CAST(bad_review AS STRING) AS actual FROM stats
  UNION ALL SELECT 'status_combination_valid' AS check_name, CASE WHEN bad_combination = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '0' AS expected, CAST(bad_combination AS STRING) AS actual FROM stats
  UNION ALL SELECT 'psgc_name_matches_unit' AS check_name, CASE WHEN psgc_name_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '0' AS expected, CAST(psgc_name_mismatch AS STRING) AS actual FROM stats
  UNION ALL SELECT 'name_match_inside_province' AS check_name, CASE WHEN name_province_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '0' AS expected, CAST(name_province_mismatch AS STRING) AS actual FROM stats
  UNION ALL SELECT 'code_is_the_pcode' AS check_name, CASE WHEN code_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '0' AS expected, CAST(code_mismatch AS STRING) AS actual FROM stats
  UNION ALL SELECT 'correspondence_is_the_old_code' AS check_name, CASE WHEN correspondence_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '0' AS expected, CAST(correspondence_mismatch AS STRING) AS actual FROM stats
  UNION ALL SELECT 'region_moved_is_sulu' AS check_name, CASE WHEN region_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '0' AS expected, CAST(region_mismatch AS STRING) AS actual FROM stats
  UNION ALL SELECT 'overrides_applied' AS check_name, CASE WHEN overrides_used = overrides_present THEN 'PASS' ELSE 'FAIL' END AS status, CAST(overrides_present AS STRING) AS expected, CAST(overrides_used AS STRING) AS actual FROM stats
  UNION ALL SELECT 'one_psgc_version' AS check_name, CASE WHEN master_periods = 1 THEN 'PASS' ELSE 'FAIL' END AS status, CAST(1 AS STRING) AS expected, CAST(master_periods AS STRING) AS actual FROM stats
  UNION ALL SELECT 'lineage_complete' AS check_name, CASE WHEN missing_lineage = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '0' AS expected, CAST(missing_lineage AS STRING) AS actual FROM stats
  UNION ALL SELECT 'rows_built_by_this_run' AS check_name, CASE WHEN other_run_rows = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '0' AS expected, CAST(other_run_rows AS STRING) AS actual FROM stats
  UNION ALL SELECT 'review_pending' AS check_name, CASE WHEN pending_rows = 0 THEN 'PASS' ELSE 'WARN' END AS status, '0' AS expected, CAST(pending_rows AS STRING) AS actual FROM stats
  UNION ALL SELECT 'unmatched' AS check_name, CASE WHEN unmatched_rows = 0 THEN 'PASS' ELSE 'WARN' END AS status, '0' AS expected, CAST(unmatched_rows AS STRING) AS actual FROM stats
  UNION ALL SELECT 'ambiguous' AS check_name, CASE WHEN ambiguous_rows = 0 THEN 'PASS' ELSE 'WARN' END AS status, '0' AS expected, CAST(ambiguous_rows AS STRING) AS actual FROM stats
  UNION ALL SELECT 'override_feature_missing' AS check_name, CASE WHEN overrides_missing = 0 THEN 'PASS' ELSE 'WARN' END AS status, '0' AS expected, CAST(overrides_missing AS STRING) AS actual FROM stats
  UNION ALL SELECT 'psgc_units_without_feature' AS check_name, CASE WHEN units_without_feature = 0 THEN 'PASS' ELSE 'WARN' END AS status, '0' AS expected, CAST(units_without_feature AS STRING) AS actual FROM stats
  UNION ALL SELECT 'method_code' AS check_name, 'PASS' AS status, CAST(NULL AS STRING) AS expected, CAST(method_code AS STRING) AS actual FROM stats
  UNION ALL SELECT 'method_code_renamed' AS check_name, 'PASS' AS status, CAST(NULL AS STRING) AS expected, CAST(method_code_renamed AS STRING) AS actual FROM stats
  UNION ALL SELECT 'method_code_region_moved' AS check_name, 'PASS' AS status, CAST(NULL AS STRING) AS expected, CAST(method_code_region_moved AS STRING) AS actual FROM stats
  UNION ALL SELECT 'method_correspondence_code' AS check_name, 'PASS' AS status, CAST(NULL AS STRING) AS expected, CAST(method_correspondence_code AS STRING) AS actual FROM stats
  UNION ALL SELECT 'method_name_exact' AS check_name, 'PASS' AS status, CAST(NULL AS STRING) AS expected, CAST(method_name_exact AS STRING) AS actual FROM stats
  UNION ALL SELECT 'method_name_old' AS check_name, 'PASS' AS status, CAST(NULL AS STRING) AS expected, CAST(method_name_old AS STRING) AS actual FROM stats
  UNION ALL SELECT 'method_name_normalized' AS check_name, 'PASS' AS status, CAST(NULL AS STRING) AS expected, CAST(method_name_normalized AS STRING) AS actual FROM stats
  UNION ALL SELECT 'method_reviewed_alias' AS check_name, 'PASS' AS status, CAST(NULL AS STRING) AS expected, CAST(method_reviewed_alias AS STRING) AS actual FROM stats
  UNION ALL SELECT 'method_spatial' AS check_name, 'PASS' AS status, CAST(NULL AS STRING) AS expected, CAST(method_spatial AS STRING) AS actual FROM stats
  UNION ALL SELECT 'match_rate_percent' AS check_name, 'PASS' AS status, CAST(NULL AS STRING) AS expected, CAST(CASE WHEN map_rows = 0 THEN 0 ELSE ROUND(100.0 * matched_rows / map_rows, 2) END AS STRING) AS actual FROM stats
)
SELECT * FROM checks
) AS results;

-- A failed build: record it before stopping. The map table is not touched.
MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (
  SELECT :run_id AS run_id, COUNT_IF(status = 'FAIL') AS fails
  FROM edu_access.`01-control`.data_quality_results
  WHERE run_id = :run_id AND source_id = 'hdx_boundaries' AND layer = 'integration'
    AND checked_at_utc >= session.integration_gate_started_at_utc
) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'integration_build' AND t.source_id = 'hdx_boundaries'
WHEN MATCHED AND s.fails > 0 THEN UPDATE SET
  status = 'failed', finished_at_utc = current_timestamp(), failure_stage = 'gate',
  error_message = CAST(s.fails AS STRING) || ' FAIL result(s) in data_quality_results';

SELECT CASE WHEN COUNT(*) > 0
            THEN raise_error('Integration gate failed for hdx_boundaries: ' || CAST(COUNT(*) AS STRING)
                             || ' FAIL result(s) in data_quality_results for run ' || :run_id)
       END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'hdx_boundaries' AND layer = 'integration' AND status = 'FAIL'
  AND checked_at_utc >= session.integration_gate_started_at_utc;

-- Every check passed: publish, then record the run 'succeeded'.
CREATE OR REPLACE TABLE edu_access.`04-integration`.hdx_adm3_psgc_map USING DELTA AS
SELECT * FROM edu_access.`04-integration`.hdx_adm3_psgc_map_candidate;

ALTER TABLE edu_access.`04-integration`.hdx_adm3_psgc_map OWNER TO `reached-hq`;

MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (SELECT :run_id AS run_id) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'integration_build' AND t.source_id = 'hdx_boundaries'
WHEN MATCHED THEN UPDATE SET
  status = 'succeeded', finished_at_utc = current_timestamp(), failure_stage = NULL, error_message = NULL;
