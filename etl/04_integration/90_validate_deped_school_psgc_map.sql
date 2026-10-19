-- Integration gate for deped_enrollment. Generated from config/mappings/integration/deped_school_psgc.json by src/integration/deped_school_psgc.py:
--   python -m src.integration.deped_school_psgc gate > etl/04_integration/90_validate_deped_school_psgc_map.sql
-- Do not edit by hand; tests/test_integration_deped_school_psgc.py fails if it differs.
DECLARE OR REPLACE VARIABLE integration_gate_started_at_utc TIMESTAMP;
SET VARIABLE integration_gate_started_at_utc = current_timestamp();

INSERT INTO edu_access.`01-control`.data_quality_results
  (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, CAST(NULL AS STRING), 'deped_enrollment', 'integration', 'edu_access.04-integration.deped_school_psgc_map_candidate',
       check_name, status, expected, actual, current_timestamp(), :code_revision
FROM (
WITH e AS (SELECT school_year, school_id FROM edu_access.`03-silver`.deped_enrollment_clean),
p AS (SELECT psgc_code, geographic_level, city_municipality_code, publication_period FROM edu_access.`03-silver`.psa_psgc_clean WHERE is_master_reference),
m AS (SELECT * FROM edu_access.`04-integration`.deped_school_psgc_map_candidate),
profile AS (SELECT * FROM (VALUES ('2020-21', 'city_mun', '60877', '28', '16', '36'), ('2020-21', 'bgy', '60693', '153', '75', '36'), ('2023-24', 'city_mun', '60108', '12', '4', '43'), ('2023-24', 'bgy', '60050', '56', '18', '43'), ('2024-25', 'city_mun', '60060', '1', '5', '63'), ('2024-25', 'bgy', '60040', '13', '13', '63'), ('2025-26', 'city_mun', '60122', '3', '14', '65'), ('2025-26', 'bgy', '60039', '71', '29', '65')) AS v(school_year, geographic_level, matched, ambiguous, unmatched, excluded)),
overrides AS (SELECT * FROM (VALUES ('NCR FOURTH DISTRICT', 'TAGUIG CITY', 'SIGNAL VILLAGE')) AS v(province, municipality, barangay)),
expected_keys AS (
  SELECT e.school_year, e.school_id, l.geographic_level
  FROM e CROSS JOIN (VALUES ('city_mun'), ('bgy')) AS l(geographic_level)
),
key_membership AS (
  SELECT COUNT_IF(m.school_id IS NULL) AS missing_keys, COUNT_IF(x.school_id IS NULL) AS extra_keys
  FROM expected_keys AS x FULL OUTER JOIN m
    ON m.school_year = x.school_year AND m.school_id = x.school_id AND m.geographic_level = x.geographic_level
),
stats AS (
  SELECT
    (SELECT COUNT(*) FROM e) AS enrollment_rows,
    (SELECT COUNT(*) FROM p) AS psgc_rows,
    (SELECT COUNT(DISTINCT publication_period) FROM p) AS psgc_periods,
    (SELECT MIN(publication_period) FROM p) AS psgc_period,
    COUNT(*) AS map_rows,
    COUNT(DISTINCT m.school_year || '/' || m.school_id || '/' || m.geographic_level) AS map_keys,
    COUNT_IF(m.geographic_level = 'city_mun') AS city_rows,
    COUNT_IF(m.geographic_level = 'bgy') AS bgy_rows,
    COUNT_IF(m.geographic_level NOT IN ('city_mun', 'bgy')) AS bad_level,
    COUNT_IF(m.match_status NOT IN ('matched', 'unmatched', 'ambiguous', 'excluded') OR m.match_status IS NULL) AS bad_status,
    COUNT_IF((m.match_status = 'matched' AND (m.psgc_code IS NULL OR m.match_method NOT IN ('code', 'code_name_differs', 'code_region_moved', 'rollup', 'name_exact', 'name_old', 'name_normalized', 'reviewed_alias')))
             OR (m.match_status <> 'matched' AND (m.psgc_code IS NOT NULL OR m.match_method IS NOT NULL))) AS bad_combination,
    COUNT_IF(m.match_status = 'matched' AND p.psgc_code IS NULL) AS matched_without_psgc,
    COALESCE(COUNT_IF((m.geographic_level = 'city_mun' AND p.geographic_level NOT IN ('City', 'Mun'))
             OR (m.geographic_level = 'bgy' AND p.geographic_level <> 'Bgy')), 0) AS wrong_psgc_level,
    COUNT_IF(m.source_row_ref IS NULL OR m.source_reference_date IS NULL OR m.batch_id IS NULL OR m.source_sha256 IS NULL OR m.source_row_number IS NULL
             OR m.run_id IS NULL OR m.built_at_utc IS NULL OR m.code_revision IS NULL
             OR (m.psgc_code IS NOT NULL AND m.psgc_batch_id IS NULL)) AS missing_lineage,
    COUNT_IF(m.run_id <> :run_id OR m.run_id IS NULL) AS other_run_rows,
    COUNT_IF(m.match_status = 'unmatched') AS unmatched_rows,
    COUNT_IF(m.match_status = 'ambiguous') AS ambiguous_rows,
    COUNT_IF(m.match_status = 'excluded') AS excluded_rows,
    COUNT_IF(m.review_status = 'pending') AS pending_rows,
    COUNT_IF(m.reason = 'reviewed override: no unit') AS override_no_unit_rows,
    (SELECT COUNT(*) FROM overrides AS o WHERE NOT EXISTS (SELECT 1 FROM edu_access.`03-silver`.deped_enrollment_clean AS x WHERE x.province = o.province
       AND x.municipality = o.municipality AND x.barangay = o.barangay)) AS overrides_without_school
  FROM m LEFT JOIN p ON p.psgc_code = m.psgc_code
),
level_counts AS (
  SELECT school_year, geographic_level,
         CAST(COUNT_IF(match_status = 'matched') AS STRING) || '/' || CAST(COUNT_IF(match_status = 'ambiguous') AS STRING) || '/'
           || CAST(COUNT_IF(match_status = 'unmatched') AS STRING) || '/' || CAST(COUNT_IF(match_status = 'excluded') AS STRING) AS counts,
         100.0 * COUNT_IF(match_status = 'matched') / NULLIF(COUNT_IF(match_status <> 'excluded'), 0) AS match_rate
  FROM m GROUP BY school_year, geographic_level
),
hierarchy AS (
  SELECT COUNT_IF(NOT (b.psgc_code IS NULL OR c.psgc_code IS NULL OR pb.city_municipality_code = c.psgc_code
                       OR (pb.city_municipality_code LIKE '13806%' AND c.psgc_code = '1380600000'))) AS bad_parent
  FROM m AS b JOIN m AS c ON c.school_year = b.school_year AND c.school_id = b.school_id
    AND b.geographic_level = 'bgy' AND c.geographic_level = 'city_mun'
  LEFT JOIN p AS pb ON pb.psgc_code = b.psgc_code
),
-- An EMISD code with no master PSGC unit is read as no code; count them so a new PSGC edition is noticed.
unknown_codes AS (
  SELECT COUNT(*) AS code_not_in_psgc_rows
  FROM m LEFT JOIN p AS pc ON pc.psgc_code = m.code_candidate
  WHERE m.code_candidate IS NOT NULL AND pc.psgc_code IS NULL
),
s AS (SELECT * FROM stats CROSS JOIN hierarchy CROSS JOIN key_membership CROSS JOIN unknown_codes),
checks AS (
  SELECT 'inputs_present' AS check_name, CASE WHEN enrollment_rows > 0 AND psgc_rows > 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         'enrollment and master PSGC rows' AS expected, CAST(enrollment_rows AS STRING) || ' / ' || CAST(psgc_rows AS STRING) AS actual FROM s
  UNION ALL SELECT 'rows_reconcile', CASE WHEN map_rows = enrollment_rows * 2 THEN 'PASS' ELSE 'FAIL' END, CAST(enrollment_rows * 2 AS STRING), CAST(map_rows AS STRING) FROM s
  UNION ALL SELECT 'one_row_per_school_year_level', CASE WHEN map_keys = map_rows THEN 'PASS' ELSE 'FAIL' END, CAST(map_rows AS STRING), CAST(map_keys AS STRING) FROM s
  UNION ALL SELECT 'both_levels_present', CASE WHEN city_rows = enrollment_rows AND bgy_rows = enrollment_rows AND bad_level = 0 THEN 'PASS' ELSE 'FAIL' END,
                   CAST(enrollment_rows AS STRING) || ' / ' || CAST(enrollment_rows AS STRING) || ' / 0',
                   CAST(city_rows AS STRING) || ' / ' || CAST(bgy_rows AS STRING) || ' / ' || CAST(bad_level AS STRING) FROM s
  UNION ALL SELECT 'source_keys_match', CASE WHEN missing_keys = 0 AND extra_keys = 0 THEN 'PASS' ELSE 'FAIL' END,
                   '0 missing / 0 extra', CAST(missing_keys AS STRING) || ' missing / ' || CAST(extra_keys AS STRING) || ' extra' FROM s
  UNION ALL SELECT 'status_valid', CASE WHEN bad_status = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_status AS STRING) FROM s
  UNION ALL SELECT 'status_combination_valid', CASE WHEN bad_combination = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_combination AS STRING) FROM s
  UNION ALL SELECT 'matched_has_psgc_unit', CASE WHEN matched_without_psgc = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(matched_without_psgc AS STRING) FROM s
  UNION ALL SELECT 'psgc_level_valid', CASE WHEN wrong_psgc_level = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(wrong_psgc_level AS STRING) FROM s
  UNION ALL SELECT 'barangay_inside_city', CASE WHEN bad_parent = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_parent AS STRING) FROM s
  UNION ALL SELECT 'one_psgc_version', CASE WHEN psgc_periods = 1 THEN 'PASS' ELSE 'FAIL' END, '1', CAST(psgc_periods AS STRING) FROM s
  UNION ALL SELECT 'master_psgc_version', CASE WHEN psgc_period = '2026-Q2' THEN 'PASS' ELSE 'FAIL' END,
                   '2026-Q2', COALESCE(psgc_period, 'none') FROM s
  UNION ALL SELECT 'lineage_complete', CASE WHEN missing_lineage = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(missing_lineage AS STRING) FROM s
  UNION ALL SELECT 'rows_built_by_this_run', CASE WHEN other_run_rows = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(other_run_rows AS STRING) FROM s
  UNION ALL SELECT 'unmatched', CASE WHEN unmatched_rows = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(unmatched_rows AS STRING) FROM s
  UNION ALL SELECT 'ambiguous', CASE WHEN ambiguous_rows = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(ambiguous_rows AS STRING) FROM s
  UNION ALL SELECT 'excluded', CASE WHEN excluded_rows = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(excluded_rows AS STRING) FROM s
  UNION ALL SELECT 'review_pending', CASE WHEN pending_rows = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(pending_rows AS STRING) FROM s
  UNION ALL SELECT 'code_not_in_psgc', CASE WHEN code_not_in_psgc_rows = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(code_not_in_psgc_rows AS STRING) FROM s
  UNION ALL SELECT 'override_without_unit', CASE WHEN override_no_unit_rows = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(override_no_unit_rows AS STRING) FROM s
  UNION ALL SELECT 'override_without_school', CASE WHEN overrides_without_school = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(overrides_without_school AS STRING) FROM s
),
-- matched / (rows - excluded) per school year and level; below the rules file's floor the map is not published.
rates AS (
  SELECT 'match_rate_' || school_year || '_' || geographic_level AS check_name,
         CASE WHEN COALESCE(match_rate, 0) >= 99.0 THEN 'PASS' ELSE 'FAIL' END AS status,
         '>= 99.0' AS expected, CAST(ROUND(match_rate, 2) AS STRING) AS actual
  FROM level_counts
),
-- matched/ambiguous/unmatched/excluded against the reviewed counts: drift must be reviewed before publication.
profiled AS (
  SELECT 'profiled_' || COALESCE(c.school_year, f.school_year) || '_' || COALESCE(c.geographic_level, f.geographic_level) AS check_name,
         CASE WHEN c.counts = f.matched || '/' || f.ambiguous || '/' || f.unmatched || '/' || f.excluded THEN 'PASS' ELSE 'FAIL' END AS status,
         COALESCE(f.matched || '/' || f.ambiguous || '/' || f.unmatched || '/' || f.excluded, 'not profiled') AS expected,
         COALESCE(c.counts, 'no rows') AS actual
  FROM level_counts AS c FULL OUTER JOIN profile AS f ON f.school_year = c.school_year AND f.geographic_level = c.geographic_level
  WHERE EXISTS (SELECT 1 FROM profile)
)
SELECT * FROM checks UNION ALL SELECT * FROM rates UNION ALL SELECT * FROM profiled
) AS results;

MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (SELECT :run_id AS run_id, COUNT_IF(status = 'FAIL') AS fails FROM edu_access.`01-control`.data_quality_results
       WHERE run_id = :run_id AND source_id = 'deped_enrollment' AND layer = 'integration'
         AND checked_at_utc >= session.integration_gate_started_at_utc) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'integration_build' AND t.source_id = 'deped_enrollment'
WHEN MATCHED AND s.fails > 0 THEN UPDATE SET status = 'failed', finished_at_utc = current_timestamp(),
  failure_stage = 'gate', error_message = CAST(s.fails AS STRING) || ' FAIL result(s) in data_quality_results';

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Integration gate failed for deped_enrollment: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s)') END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'deped_enrollment' AND layer = 'integration' AND status = 'FAIL'
  AND checked_at_utc >= session.integration_gate_started_at_utc;

CREATE OR REPLACE TABLE edu_access.`04-integration`.deped_school_psgc_map USING DELTA AS SELECT * FROM edu_access.`04-integration`.deped_school_psgc_map_candidate;
ALTER TABLE edu_access.`04-integration`.deped_school_psgc_map OWNER TO `reached-hq`;

MERGE INTO edu_access.`01-control`.pipeline_runs AS t USING (SELECT :run_id AS run_id) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'integration_build' AND t.source_id = 'deped_enrollment'
WHEN MATCHED THEN UPDATE SET status = 'succeeded', finished_at_utc = current_timestamp(), failure_stage = NULL, error_message = NULL;
