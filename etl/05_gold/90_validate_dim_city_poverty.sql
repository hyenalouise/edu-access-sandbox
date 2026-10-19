-- Gold gate for dim_city_poverty (D-046). Checks dim_city_poverty_candidate against the published
-- dim_city_municipality and psa_poverty_psgc_map it was built from, writes every result to
-- data_quality_results (layer 'gold'), stops on any FAIL, and only then publishes dim_city_poverty. A
-- FAIL keeps the last good build and stops nothing else: no other Gold task waits for this one.
--
-- FAIL (D-046; every one, because both sources are pinned, PSGC 2Q 2026 and PSA 2023, so a changed
-- count means the join drifted): a repeated or NULL key; a row that is not a regular member, or a
-- regular member with no row; a row count or status count other than the pinned 1,642 and
-- 1,597 / 1 / 44; a status or reason outside D-046; a Manila reason on any member other than the City
-- of Manila with its 14 district rows; a partial_estimate row; any value on a row that is
-- not estimated, or a missing one on a row that is; cv_over_20 that does not follow poverty_cv; an
-- estimate that differs from its map row; an estimate year other than 2023; a 2023 map row at city or
-- municipality level that is not matched, or matched to no regular member, so its estimate would be
-- lost; and a map run that did not succeed.
-- A pull request that changes the PSGC or PSA pin updates the pins line below in the same pull
-- request (D-046).
-- Counts only (PASS): CV above 20, lower limit not above 0, Manila district rows kept out.

DECLARE OR REPLACE VARIABLE gold_gate_started_at_utc TIMESTAMP;
SET VARIABLE gold_gate_started_at_utc = current_timestamp();

CREATE OR REPLACE TEMPORARY VIEW dim_city_poverty_gate_summary AS
WITH pins AS (
  -- D-046's reconciled counts for PSGC 2Q 2026 and PSA 2023.
  SELECT 1642 AS pin_rows, 1597 AS pin_estimated, 1 AS pin_no_estimate, 44 AS pin_not_in_source, 1 AS pin_manila_reason
),
regular AS (
  SELECT city_mun_psgc_code, city_mun_name, city_class
  FROM edu_access.`05-gold`.dim_city_municipality WHERE member_type = 'regular'
),
map_2023 AS (
  SELECT * FROM edu_access.`04-integration`.psa_poverty_psgc_map WHERE estimate_year = 2023
),
city_rows AS (
  -- PSA rows the map placed at city or municipality level, plus every row it could not place: an
  -- unmatched or ambiguous row may be a city or municipality, so none may stay out of Gold unseen.
  SELECT * FROM map_2023 WHERE geographic_level = 'city_mun' OR match_status <> 'matched'
),
dimension AS (
  SELECT * FROM edu_access.`05-gold`.dim_city_poverty_candidate
),
-- The build gives the Manila reason by a rule, not a code. This proves the one row that has it is the
-- City of Manila: the PSGC highly urbanized city of that name, with D-046's 14 matched 2023 district rows.
manila_districts AS (
  SELECT substr(psgc_code, 1, 5) || '00000' AS city_mun_psgc_code, COUNT(*) AS district_rows
  FROM map_2023
  WHERE match_status = 'matched' AND geographic_level = 'sub_mun'
  GROUP BY 1
)
SELECT
  pins.*,
  (SELECT COUNT(*) FROM dimension) AS dimension_rows,
  (SELECT COUNT(*) FROM regular) AS regular_members,
  (SELECT COUNT(*) - COUNT(DISTINCT city_mun_psgc_code) FROM dimension) AS duplicate_keys,
  (SELECT COUNT_IF(city_mun_psgc_code IS NULL) FROM dimension) AS null_keys,
  (SELECT COUNT(*) FROM dimension AS d LEFT JOIN regular AS r ON r.city_mun_psgc_code = d.city_mun_psgc_code
    WHERE r.city_mun_psgc_code IS NULL) AS rows_not_regular,
  (SELECT COUNT(*) FROM regular AS r LEFT JOIN dimension AS d ON d.city_mun_psgc_code = r.city_mun_psgc_code
    WHERE d.city_mun_psgc_code IS NULL) AS regular_without_row,
  (SELECT COUNT_IF(poverty_status = 'estimated') FROM dimension) AS estimated,
  (SELECT COUNT_IF(poverty_status = 'no_estimate') FROM dimension) AS no_estimate,
  (SELECT COUNT_IF(poverty_status = 'not_in_source') FROM dimension) AS not_in_source,
  (SELECT COUNT_IF(poverty_status = 'partial_estimate') FROM dimension) AS partial_estimate,
  (SELECT COUNT_IF(poverty_status IS NULL OR poverty_status NOT IN ('estimated', 'no_estimate', 'not_in_source'))
    FROM dimension) AS bad_status,
  (SELECT COUNT_IF(NOT COALESCE(
      (poverty_status = 'estimated' AND status_reason IS NULL)
      OR (poverty_status = 'no_estimate' AND status_reason = 'PSA published no 2023 estimate')
      OR (poverty_status = 'not_in_source' AND status_reason IN (
            'City of Manila not in the PSA estimates' || chr(59) || ' its 14 district estimates are not combined',
            'not in the PSA city and municipal estimates')),
      FALSE)) FROM dimension) AS bad_reason,
  (SELECT COUNT_IF(status_reason = 'City of Manila not in the PSA estimates' || chr(59) || ' its 14 district estimates are not combined')
    FROM dimension) AS manila_reason_rows,
  (SELECT COUNT(*) FROM dimension AS d
      JOIN regular AS r ON r.city_mun_psgc_code = d.city_mun_psgc_code
      JOIN manila_districts AS m ON m.city_mun_psgc_code = d.city_mun_psgc_code
    WHERE d.status_reason = 'City of Manila not in the PSA estimates' || chr(59) || ' its 14 district estimates are not combined'
      AND r.city_mun_name = 'City of Manila' AND r.city_class = 'HUC' AND m.district_rows = 14) AS manila_reason_on_manila,
  (SELECT COUNT_IF(poverty_status <> 'estimated' AND (poverty_incidence IS NOT NULL OR poverty_ci90_lower IS NOT NULL
      OR poverty_ci90_upper IS NOT NULL OR poverty_cv IS NOT NULL OR cv_over_20 IS NOT NULL)) FROM dimension) AS values_without_estimate,
  (SELECT COUNT_IF(poverty_status = 'estimated' AND (poverty_incidence IS NULL OR poverty_ci90_lower IS NULL
      OR poverty_ci90_upper IS NULL OR poverty_cv IS NULL OR cv_over_20 IS NULL)) FROM dimension) AS estimate_incomplete,
  (SELECT COUNT_IF(cv_over_20 IS DISTINCT FROM (poverty_cv > 20)) FROM dimension) AS cv_flag_inconsistent,
  (SELECT COUNT_IF(estimate_year IS DISTINCT FROM 2023) FROM dimension) AS wrong_estimate_year,
  (SELECT COUNT(*) FROM dimension AS d JOIN map_2023 AS m
      ON m.psgc_code = d.city_mun_psgc_code AND m.match_status = 'matched' AND m.geographic_level = 'city_mun'
    WHERE d.poverty_status IS DISTINCT FROM m.estimate_status
       OR d.poverty_incidence IS DISTINCT FROM m.poverty_incidence
       OR d.poverty_ci90_lower IS DISTINCT FROM m.ci90_lower_limit
       OR d.poverty_ci90_upper IS DISTINCT FROM m.ci90_upper_limit
       OR d.poverty_cv IS DISTINCT FROM m.coefficient_of_variation) AS values_differ_from_map,
  (SELECT COUNT(*) FROM city_rows) AS map_city_rows,
  (SELECT COUNT_IF(match_status <> 'matched') FROM city_rows) AS map_rows_not_matched,
  (SELECT COUNT(*) FROM city_rows AS m LEFT JOIN regular AS r ON r.city_mun_psgc_code = m.psgc_code
    WHERE m.match_status = 'matched' AND r.city_mun_psgc_code IS NULL) AS map_rows_outside_dimension,
  (SELECT COUNT_IF(geographic_level = 'sub_mun') FROM map_2023) AS district_rows_kept_out,
  (SELECT COUNT_IF(cv_over_20) FROM dimension) AS cv_over_20_rows,
  (SELECT COUNT_IF(poverty_ci90_lower <= 0) FROM dimension) AS lower_limit_not_positive
FROM pins;

INSERT INTO edu_access.`01-control`.data_quality_results (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, NULL, 'dim_city_poverty', 'gold', 'edu_access.05-gold.dim_city_poverty', check_name, status, expected, actual, current_timestamp(), :code_revision
FROM (
  SELECT 'key_unique' AS check_name, CASE WHEN duplicate_keys = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '0' AS expected, CAST(duplicate_keys AS STRING) AS actual FROM dim_city_poverty_gate_summary
  UNION ALL SELECT 'key_not_null', CASE WHEN null_keys = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(null_keys AS STRING) FROM dim_city_poverty_gate_summary
  UNION ALL SELECT 'rows_are_regular_members', CASE WHEN rows_not_regular = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(rows_not_regular AS STRING) FROM dim_city_poverty_gate_summary
  UNION ALL SELECT 'regular_members_present', CASE WHEN regular_without_row = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(regular_without_row AS STRING) FROM dim_city_poverty_gate_summary
  UNION ALL SELECT 'rows_match_pin', CASE WHEN dimension_rows = pin_rows THEN 'PASS' ELSE 'FAIL' END, CAST(pin_rows AS STRING), CAST(dimension_rows AS STRING) FROM dim_city_poverty_gate_summary
  UNION ALL SELECT 'estimated_match_pin', CASE WHEN estimated = pin_estimated THEN 'PASS' ELSE 'FAIL' END, CAST(pin_estimated AS STRING), CAST(estimated AS STRING) FROM dim_city_poverty_gate_summary
  UNION ALL SELECT 'no_estimate_match_pin', CASE WHEN no_estimate = pin_no_estimate THEN 'PASS' ELSE 'FAIL' END, CAST(pin_no_estimate AS STRING), CAST(no_estimate AS STRING) FROM dim_city_poverty_gate_summary
  UNION ALL SELECT 'not_in_source_match_pin', CASE WHEN not_in_source = pin_not_in_source THEN 'PASS' ELSE 'FAIL' END, CAST(pin_not_in_source AS STRING), CAST(not_in_source AS STRING) FROM dim_city_poverty_gate_summary
  UNION ALL SELECT 'manila_reason_match_pin', CASE WHEN manila_reason_rows = pin_manila_reason THEN 'PASS' ELSE 'FAIL' END, CAST(pin_manila_reason AS STRING), CAST(manila_reason_rows AS STRING) FROM dim_city_poverty_gate_summary
  UNION ALL SELECT 'manila_reason_on_city_of_manila', CASE WHEN manila_reason_on_manila = pin_manila_reason THEN 'PASS' ELSE 'FAIL' END, CAST(pin_manila_reason AS STRING), CAST(manila_reason_on_manila AS STRING) FROM dim_city_poverty_gate_summary
  UNION ALL SELECT 'poverty_status_allowed', CASE WHEN bad_status = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_status AS STRING) FROM dim_city_poverty_gate_summary
  UNION ALL SELECT 'no_partial_estimate', CASE WHEN partial_estimate = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(partial_estimate AS STRING) FROM dim_city_poverty_gate_summary
  UNION ALL SELECT 'status_reason_allowed', CASE WHEN bad_reason = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_reason AS STRING) FROM dim_city_poverty_gate_summary
  UNION ALL SELECT 'no_value_without_estimate', CASE WHEN values_without_estimate = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(values_without_estimate AS STRING) FROM dim_city_poverty_gate_summary
  UNION ALL SELECT 'estimate_complete', CASE WHEN estimate_incomplete = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(estimate_incomplete AS STRING) FROM dim_city_poverty_gate_summary
  UNION ALL SELECT 'cv_over_20_follows_cv', CASE WHEN cv_flag_inconsistent = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(cv_flag_inconsistent AS STRING) FROM dim_city_poverty_gate_summary
  UNION ALL SELECT 'estimate_year_2023', CASE WHEN wrong_estimate_year = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(wrong_estimate_year AS STRING) FROM dim_city_poverty_gate_summary
  UNION ALL SELECT 'values_equal_map', CASE WHEN values_differ_from_map = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(values_differ_from_map AS STRING) FROM dim_city_poverty_gate_summary
  UNION ALL SELECT 'map_rows_matched', CASE WHEN map_rows_not_matched = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(map_rows_not_matched AS STRING) FROM dim_city_poverty_gate_summary
  UNION ALL SELECT 'map_rows_in_dimension', CASE WHEN map_rows_outside_dimension = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(map_rows_outside_dimension AS STRING) FROM dim_city_poverty_gate_summary
  UNION ALL SELECT 'map_rows_carried', CASE WHEN map_city_rows = estimated + no_estimate + partial_estimate THEN 'PASS' ELSE 'FAIL' END,
                   CAST(map_city_rows AS STRING), CAST(estimated + no_estimate + partial_estimate AS STRING) FROM dim_city_poverty_gate_summary
  UNION ALL SELECT 'regular_members', 'PASS', CAST(NULL AS STRING), CAST(regular_members AS STRING) FROM dim_city_poverty_gate_summary
  UNION ALL SELECT 'district_rows_kept_out', 'PASS', CAST(NULL AS STRING), CAST(district_rows_kept_out AS STRING) FROM dim_city_poverty_gate_summary
  UNION ALL SELECT 'cv_over_20_rows', 'PASS', CAST(NULL AS STRING), CAST(cv_over_20_rows AS STRING) FROM dim_city_poverty_gate_summary
  UNION ALL SELECT 'lower_limit_not_positive', 'PASS', CAST(NULL AS STRING), CAST(lower_limit_not_positive AS STRING) FROM dim_city_poverty_gate_summary
) AS results;

-- Integrity rule 1 of the metric specification: one result per distinct upstream run_id read, PASS only
-- when that run's integration_build for the source succeeded in pipeline_runs (D-025), so the Gold
-- build is traceable to the map rows it read and never trusts a run that did not publish.
INSERT INTO edu_access.`01-control`.data_quality_results (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, NULL, 'dim_city_poverty', 'gold', 'edu_access.05-gold.dim_city_poverty', 'upstream_run_' || u.input_table,
       CASE WHEN p.run_id IS NULL THEN 'FAIL' ELSE 'PASS' END, 'succeeded ' || u.pipeline_name, u.upstream_run_id,
       current_timestamp(), :code_revision
FROM (
  SELECT DISTINCT 'psa_poverty_psgc_map' AS input_table, 'integration_build' AS pipeline_name, 'psa_poverty_stat' AS source_id, run_id AS upstream_run_id
  FROM edu_access.`04-integration`.psa_poverty_psgc_map WHERE estimate_year = 2023
) AS u
LEFT JOIN (
  SELECT DISTINCT run_id, pipeline_name, source_id
  FROM edu_access.`01-control`.pipeline_runs
  WHERE status = 'succeeded'
) AS p ON p.run_id = u.upstream_run_id AND p.pipeline_name = u.pipeline_name AND p.source_id = u.source_id;

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Gold gate failed for dim_city_poverty: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s) in data_quality_results for run ' || :run_id) END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'dim_city_poverty' AND layer = 'gold' AND status = 'FAIL'
  AND checked_at_utc >= session.gold_gate_started_at_utc;

-- Every check passed: publish.
CREATE OR REPLACE TABLE edu_access.`05-gold`.dim_city_poverty USING DELTA AS
SELECT * FROM edu_access.`05-gold`.dim_city_poverty_candidate;

COMMENT ON TABLE edu_access.`05-gold`.dim_city_poverty IS 'PSA 2023 poverty estimate and its status for each regular PSGC city or municipality, as context only (D-046).';
ALTER TABLE edu_access.`05-gold`.dim_city_poverty OWNER TO `reached-hq`;
