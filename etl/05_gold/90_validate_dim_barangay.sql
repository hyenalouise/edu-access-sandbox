-- Gold gate for dim_barangay. Checks dim_barangay_candidate against psa_psgc_clean, writes every result
-- to data_quality_results (layer 'gold'), stops on any FAIL, and only then publishes dim_barangay. A
-- FAIL keeps the last good build.
--
-- FAIL: any row that differs, in any column, from the row expected from PSGC (values_match_source:
-- catches a changed name or urban_rural, and a barangay moved to another valid city or municipality;
-- its expected parent is the published City or Mun row, or for a Manila district the City row at the
-- district's province position, and nothing else), a repeated or NULL key, a regular member that is not a Bgy row of the one master quarter (or
-- one missing), a parent that is not a PSGC City or Mun of that quarter, a city or municipality without
-- exactly one unknown-barangay member, technical members other than UNKNOWN and EXCLUDED under the same
-- city codes, and an urban_rural value other than U, R or NULL.
-- WARN: regular barangays without urban_rural (PSGC '-').
-- Counts only (PASS): barangays rolled up from a Manila district, barangays per member type.

DECLARE OR REPLACE VARIABLE gold_gate_started_at_utc TIMESTAMP;
SET VARIABLE gold_gate_started_at_utc = current_timestamp();
DECLARE OR REPLACE VARIABLE gold_gate_summary STRING;
SET VARIABLE gold_gate_summary = '`edu_access`.`05-gold`.`dim_barangay_gate_summary_r_' || sha2(:run_id, 256) || '`';
DECLARE OR REPLACE VARIABLE gold_gate_owner_sql STRING;

-- Every row as PSGC says it should be, built once for the full-row comparison. A barangay whose
-- published parent is neither a City or Mun row nor a SubMun under a City row gets a NULL parent here,
-- so it can never match a built row.
CREATE OR REPLACE TEMPORARY VIEW dim_barangay_expected AS
WITH psgc AS (
  SELECT * FROM edu_access.`03-silver`.psa_psgc_clean WHERE is_master_reference
)
  SELECT
    b.psgc_code AS barangay_psgc_code, b.name AS barangay_name,
    CASE WHEN parent.geographic_level IN ('City', 'Mun') THEN parent.psgc_code
         WHEN parent.geographic_level = 'SubMun' AND city.geographic_level = 'City' THEN city.psgc_code
    END AS city_mun_psgc_code,
    b.urban_rural, 'regular' AS member_type
  FROM psgc AS b
  LEFT JOIN psgc AS parent ON parent.psgc_code = b.city_municipality_code
  LEFT JOIN psgc AS city ON city.psgc_code = substr(parent.psgc_code, 1, 5) || '00000'
  WHERE b.geographic_level = 'Bgy'
  UNION ALL
  SELECT u.psgc_code || '-UNKNOWN', 'Unknown barangay in ' || u.name, u.psgc_code, CAST(NULL AS STRING), 'unknown'
  FROM psgc AS u WHERE u.geographic_level IN ('City', 'Mun')
  UNION ALL
  SELECT v.code, v.label, v.code, CAST(NULL AS STRING), v.member_type
  FROM (VALUES ('UNKNOWN', 'Unknown barangay', 'unknown'), ('EXCLUDED', 'Excluded from barangay analysis', 'excluded'))
    AS v(code, label, member_type);

DECLARE OR REPLACE VARIABLE gold_dim_barangay_rows_not_matching BIGINT;
SET VARIABLE gold_dim_barangay_rows_not_matching = (
  (SELECT COUNT(*) FROM (SELECT barangay_psgc_code, barangay_name, city_mun_psgc_code, urban_rural, member_type FROM edu_access.`05-gold`.dim_barangay_candidate EXCEPT ALL SELECT * FROM dim_barangay_expected) AS x)
  + (SELECT COUNT(*) FROM (SELECT * FROM dim_barangay_expected EXCEPT ALL SELECT barangay_psgc_code, barangay_name, city_mun_psgc_code, urban_rural, member_type FROM edu_access.`05-gold`.dim_barangay_candidate) AS x));

-- The full-row comparison is computed once, above, because the summary is read once per result row.
-- The one-row summary the checks read is written to a table first. Read 15 times as a temporary view, it
-- made Databricks SQL's optimizer fail with INTERNAL_ERROR (dev run, 2026-10-20), as the DepEd PSGC gate did
-- (c64e949). The table is this run's own (its name holds a hash of run_id) and is dropped once the checks
-- are recorded, whether the gate passes or fails.
CREATE OR REPLACE TABLE IDENTIFIER(session.gold_gate_summary) USING DELTA COMMENT 'Internal unpublished one-row summary for one dim_barangay gate. The gate drops it once its checks are recorded in data_quality_results.' AS
WITH psgc AS (
  SELECT * FROM edu_access.`03-silver`.psa_psgc_clean WHERE is_master_reference
),
source_barangays AS (
  SELECT psgc_code, city_municipality_code FROM psgc WHERE geographic_level = 'Bgy'
),
source_units AS (
  SELECT psgc_code FROM psgc WHERE geographic_level IN ('City', 'Mun')
),
dimension AS (
  SELECT * FROM edu_access.`05-gold`.dim_barangay_candidate
),
regular AS (
  SELECT * FROM dimension WHERE member_type = 'regular'
),
unknown_per_unit AS (
  SELECT u.psgc_code, COUNT(d.barangay_psgc_code) AS members
  FROM source_units AS u
  LEFT JOIN dimension AS d
    ON d.city_mun_psgc_code = u.psgc_code AND d.member_type = 'unknown' AND d.barangay_psgc_code = u.psgc_code || '-UNKNOWN'
  GROUP BY u.psgc_code
)
SELECT
  session.gold_dim_barangay_rows_not_matching AS rows_not_matching_source,
  (SELECT COUNT(*) FROM source_barangays) AS source_barangays,
  (SELECT COUNT(*) FROM regular) AS regular_rows,
  (SELECT COUNT(*) - COUNT(DISTINCT barangay_psgc_code) FROM dimension) AS duplicate_keys,
  (SELECT COUNT_IF(barangay_psgc_code IS NULL) FROM dimension) AS null_keys,
  (SELECT COUNT(*) FROM regular AS d LEFT JOIN source_barangays AS s ON s.psgc_code = d.barangay_psgc_code
    WHERE s.psgc_code IS NULL) AS regular_not_in_psgc,
  (SELECT COUNT(*) FROM source_barangays AS s LEFT JOIN regular AS d ON d.barangay_psgc_code = s.psgc_code
    WHERE d.barangay_psgc_code IS NULL) AS psgc_barangays_missing,
  (SELECT COUNT(DISTINCT publication_period) FROM psgc) AS master_periods,
  (SELECT COUNT(*) FROM dimension AS d LEFT JOIN source_units AS u ON u.psgc_code = d.city_mun_psgc_code
    WHERE (d.member_type = 'regular' OR d.barangay_psgc_code LIKE '%-UNKNOWN') AND u.psgc_code IS NULL) AS parent_not_city_mun,
  (SELECT COUNT_IF(members <> 1) FROM unknown_per_unit) AS units_without_one_unknown,
  (SELECT COUNT(*) FROM dimension WHERE barangay_psgc_code LIKE '%-UNKNOWN') AS unknown_barangay_rows,
  (SELECT COUNT(*) FROM source_units) AS source_units,
  (SELECT COUNT(*) FROM dimension WHERE member_type <> 'regular' AND barangay_psgc_code NOT LIKE '%-UNKNOWN') AS technical_rows,
  (SELECT COUNT_IF((barangay_psgc_code = 'UNKNOWN' AND city_mun_psgc_code = 'UNKNOWN' AND member_type = 'unknown')
                OR (barangay_psgc_code = 'EXCLUDED' AND city_mun_psgc_code = 'EXCLUDED' AND member_type = 'excluded')) FROM dimension) AS expected_technical_rows,
  (SELECT COUNT_IF(member_type NOT IN ('regular', 'unknown', 'excluded') OR member_type IS NULL) FROM dimension) AS bad_member_type,
  (SELECT COUNT_IF(urban_rural IS NOT NULL AND urban_rural NOT IN ('U', 'R')) FROM dimension) AS bad_urban_rural,
  (SELECT COUNT_IF(member_type <> 'regular' AND urban_rural IS NOT NULL) FROM dimension) AS technical_with_urban_rural,
  (SELECT COUNT_IF(urban_rural IS NULL) FROM regular) AS regular_without_urban_rural,
  (SELECT COUNT(*) FROM regular AS d JOIN source_barangays AS s ON s.psgc_code = d.barangay_psgc_code
    WHERE s.city_municipality_code <> d.city_mun_psgc_code) AS rolled_up_from_district;
SET VARIABLE gold_gate_owner_sql = 'ALTER TABLE ' || session.gold_gate_summary || ' OWNER TO `reached-hq`';
EXECUTE IMMEDIATE gold_gate_owner_sql;

INSERT INTO edu_access.`01-control`.data_quality_results (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, NULL, 'dim_barangay', 'gold', 'edu_access.05-gold.dim_barangay', check_name, status, expected, actual, current_timestamp(), :code_revision
FROM (
  SELECT 'values_match_source' AS check_name, CASE WHEN rows_not_matching_source = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '0' AS expected, CAST(rows_not_matching_source AS STRING) AS actual FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'key_unique', CASE WHEN duplicate_keys = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(duplicate_keys AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'key_not_null', CASE WHEN null_keys = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(null_keys AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'regular_rows_reconcile', CASE WHEN regular_rows = source_barangays THEN 'PASS' ELSE 'FAIL' END, CAST(source_barangays AS STRING), CAST(regular_rows AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'regular_in_psgc_master', CASE WHEN regular_not_in_psgc = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(regular_not_in_psgc AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'psgc_barangays_present', CASE WHEN psgc_barangays_missing = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(psgc_barangays_missing AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'one_psgc_version', CASE WHEN master_periods = 1 THEN 'PASS' ELSE 'FAIL' END, '1', CAST(master_periods AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'parent_is_city_or_municipality', CASE WHEN parent_not_city_mun = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(parent_not_city_mun AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'one_unknown_barangay_per_city_mun', CASE WHEN units_without_one_unknown = 0 AND unknown_barangay_rows = source_units THEN 'PASS' ELSE 'FAIL' END, CAST(source_units AS STRING), CAST(unknown_barangay_rows AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'technical_members', CASE WHEN technical_rows = 2 AND expected_technical_rows = 2 THEN 'PASS' ELSE 'FAIL' END, '2', CAST(technical_rows AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'member_type_allowed', CASE WHEN bad_member_type = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_member_type AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'urban_rural_allowed', CASE WHEN bad_urban_rural = 0 AND technical_with_urban_rural = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_urban_rural + technical_with_urban_rural AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'regular_without_urban_rural', CASE WHEN regular_without_urban_rural = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(regular_without_urban_rural AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'regular_barangays', 'PASS', CAST(NULL AS STRING), CAST(regular_rows AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
  UNION ALL SELECT 'rolled_up_from_district', 'PASS', CAST(NULL AS STRING), CAST(rolled_up_from_district AS STRING) FROM IDENTIFIER(session.gold_gate_summary)
) AS results;

-- Integrity rule 1 of the metric specification: one result per distinct upstream run_id read, PASS only
-- when that run's silver_build for the source succeeded in pipeline_runs (D-025), so the Gold build is
-- traceable to the Silver and Integration rows it read and never trusts a run that did not publish.
INSERT INTO edu_access.`01-control`.data_quality_results (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, NULL, 'dim_barangay', 'gold', 'edu_access.05-gold.dim_barangay', 'upstream_run_' || u.input_table,
       CASE WHEN p.run_id IS NULL THEN 'FAIL' ELSE 'PASS' END, 'succeeded ' || u.pipeline_name, u.upstream_run_id,
       current_timestamp(), :code_revision
FROM (
  SELECT DISTINCT 'psa_psgc_clean' AS input_table, 'silver_build' AS pipeline_name, 'psa_psgc' AS source_id, run_id AS upstream_run_id
  FROM edu_access.`03-silver`.psa_psgc_clean WHERE is_master_reference
) AS u
LEFT JOIN (
  SELECT DISTINCT run_id, pipeline_name, source_id
  FROM edu_access.`01-control`.pipeline_runs
  WHERE status = 'succeeded'
) AS p ON p.run_id = u.upstream_run_id AND p.pipeline_name = u.pipeline_name AND p.source_id = u.source_id;

-- Every check is recorded, so the summary is no longer needed, whether the gate passes or fails.
DROP TABLE IF EXISTS IDENTIFIER(session.gold_gate_summary);

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Gold gate failed for dim_barangay: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s) in data_quality_results for run ' || :run_id) END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'dim_barangay' AND layer = 'gold' AND status = 'FAIL'
  AND checked_at_utc >= session.gold_gate_started_at_utc;

-- Every check passed: publish.
CREATE OR REPLACE TABLE edu_access.`05-gold`.dim_barangay USING DELTA AS
SELECT * FROM edu_access.`05-gold`.dim_barangay_candidate;

COMMENT ON TABLE edu_access.`05-gold`.dim_barangay IS 'One PSGC barangay of the master quarter, one unknown barangay per city or municipality, plus the UNKNOWN and EXCLUDED technical members (D-048).';
ALTER TABLE edu_access.`05-gold`.dim_barangay OWNER TO `reached-hq`;
