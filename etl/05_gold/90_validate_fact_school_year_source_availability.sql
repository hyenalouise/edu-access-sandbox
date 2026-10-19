DECLARE OR REPLACE VARIABLE gold_gate_started_at_utc TIMESTAMP;
SET VARIABLE gold_gate_started_at_utc = current_timestamp();

CREATE OR REPLACE TEMPORARY VIEW fact_school_year_source_availability_gate_summary AS
WITH fact AS (
  SELECT * FROM edu_access.`05-gold`.fact_school_year_source_availability_candidate
), expected AS (
  SELECT y.school_year, s.source_id,
    CASE s.source_id
      WHEN 'deped_enrollment' THEN EXISTS (SELECT 1 FROM edu_access.`03-silver`.deped_enrollment_clean AS e WHERE e.school_year = y.school_year)
      WHEN 'deped_facilities' THEN EXISTS (SELECT 1 FROM edu_access.`03-silver`.deped_facilities_clean AS f WHERE f.school_year = y.school_year)
      WHEN 'deped_personnel' THEN EXISTS (SELECT 1 FROM edu_access.`03-silver`.deped_personnel_clean AS p WHERE p.school_year = y.school_year)
    END AS has_data
  FROM edu_access.`05-gold`.dim_school_year AS y
  CROSS JOIN (SELECT * FROM VALUES ('deped_enrollment'), ('deped_facilities'), ('deped_personnel') AS s(source_id)) AS s
)
SELECT
  (SELECT COUNT(*) FROM expected) AS expected_rows,
  (SELECT COUNT(*) FROM fact) AS fact_rows,
  (SELECT COUNT(*) - COUNT(DISTINCT (school_year, source_id)) FROM fact) AS duplicate_keys,
  (SELECT COUNT_IF(school_year IS NULL OR source_id IS NULL OR has_data IS NULL) FROM fact) AS null_required_values,
  (SELECT COUNT_IF(source_id NOT IN ('deped_enrollment', 'deped_facilities', 'deped_personnel')) FROM fact) AS invalid_sources,
  (SELECT COUNT(*) FROM fact AS f LEFT JOIN edu_access.`05-gold`.dim_school_year AS y USING (school_year) WHERE y.school_year IS NULL) AS missing_school_year_keys,
  (SELECT COUNT(*) FROM expected AS e FULL OUTER JOIN fact AS f USING (school_year, source_id) WHERE f.school_year IS NULL OR e.school_year IS NULL OR f.has_data IS DISTINCT FROM e.has_data) AS mismatched_rows;

INSERT INTO edu_access.`01-control`.data_quality_results (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, NULL, 'fact_school_year_source_availability', 'gold', 'edu_access.05-gold.fact_school_year_source_availability', check_name, status, expected, actual, current_timestamp(), :code_revision
FROM (
  SELECT 'rows_reconcile' AS check_name, CASE WHEN fact_rows = expected_rows THEN 'PASS' ELSE 'FAIL' END AS status, CAST(expected_rows AS STRING) AS expected, CAST(fact_rows AS STRING) AS actual FROM fact_school_year_source_availability_gate_summary
  UNION ALL SELECT 'grain_unique', CASE WHEN duplicate_keys = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(duplicate_keys AS STRING) FROM fact_school_year_source_availability_gate_summary
  UNION ALL SELECT 'required_values_not_null', CASE WHEN null_required_values = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(null_required_values AS STRING) FROM fact_school_year_source_availability_gate_summary
  UNION ALL SELECT 'source_id_valid', CASE WHEN invalid_sources = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(invalid_sources AS STRING) FROM fact_school_year_source_availability_gate_summary
  UNION ALL SELECT 'school_year_fk_resolves', CASE WHEN missing_school_year_keys = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(missing_school_year_keys AS STRING) FROM fact_school_year_source_availability_gate_summary
  UNION ALL SELECT 'source_availability_reconciles', CASE WHEN mismatched_rows = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(mismatched_rows AS STRING) FROM fact_school_year_source_availability_gate_summary
) AS results;

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Gold gate failed for fact_school_year_source_availability: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s)') END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'fact_school_year_source_availability' AND layer = 'gold' AND status = 'FAIL' AND checked_at_utc >= session.gold_gate_started_at_utc;

CREATE OR REPLACE TABLE edu_access.`05-gold`.fact_school_year_source_availability USING DELTA AS
SELECT * FROM edu_access.`05-gold`.fact_school_year_source_availability_candidate;

ALTER TABLE edu_access.`05-gold`.fact_school_year_source_availability OWNER TO `reached-hq`;
