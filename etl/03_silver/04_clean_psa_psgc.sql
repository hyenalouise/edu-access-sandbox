-- Silver build for psa_psgc. Generated from config/ingestion/psa_psgc.json
-- and config/mappings/psa_psgc.json by src/silver/psa_psgc.py:
--   python -m src.silver.cli sql --source psa_psgc > etl/03_silver/04_clean_psa_psgc.sql
-- Do not edit by hand; tests/test_silver_psgc.py fails if it differs.
--
-- Rebuilds the two candidate tables from the current Bronze batches only (01-control.current_batches:
-- the latest succeeded delivery version of each publication quarter). Bronze is read, never changed.
-- Every current Bronze row ends in exactly one of the two tables:
--   psa_psgc_clean_candidate       one row per PSGC code per quarter, typed;
--   psa_psgc_quarantine_candidate  rows that cannot be trusted, with their reasons.
-- The Silver tables are never written here: the gate (the next task) checks the candidates and
-- publishes them only if no check fails (D-025). It rebuilds on every run.
--
-- Parameters, supplied by the job (or src/job/local_run.py):
--   :run_id         the job run; every row built here, and the gate's results, carry it
--   :code_revision  the commit that ran, from the job parameter; never a literal
--   :environment    the deploy target: local, dev, or prod

-- One run stamp for the whole file, so both tables carry the same run and the same time.
DECLARE OR REPLACE VARIABLE silver_run_id STRING;
SET VARIABLE silver_run_id = :run_id;
DECLARE OR REPLACE VARIABLE silver_code_revision STRING;
SET VARIABLE silver_code_revision = COALESCE(NULLIF(:code_revision, ''), 'UNSET');
DECLARE OR REPLACE VARIABLE silver_environment STRING;
SET VARIABLE silver_environment = COALESCE(NULLIF(:environment, ''), 'UNSET');
DECLARE OR REPLACE VARIABLE silver_cleaned_at_utc TIMESTAMP;
SET VARIABLE silver_cleaned_at_utc = current_timestamp();

-- The run starts. Its row stays 'running' until the gate records how it ended, so a
-- build that dies is never mistaken for a good one. run_id and job_run_id are both the job run,
-- so one filter on job_run_id finds a job run's Bronze loads and Silver builds (D-020).
MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (SELECT session.silver_run_id AS run_id) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'silver_build' AND t.source_id = 'psa_psgc'
WHEN MATCHED THEN UPDATE SET
  status = 'running', started_at_utc = session.silver_cleaned_at_utc, finished_at_utc = NULL,
  failure_stage = NULL, error_message = NULL, code_revision = session.silver_code_revision, job_run_id = s.run_id
WHEN NOT MATCHED THEN INSERT (run_id, pipeline_name, source_id, environment, status, started_at_utc, code_revision, job_run_id)
  VALUES (s.run_id, 'silver_build', 'psa_psgc', session.silver_environment, 'running',
          session.silver_cleaned_at_utc, session.silver_code_revision, s.run_id);

CREATE SCHEMA IF NOT EXISTS edu_access.`03-silver`;
ALTER SCHEMA edu_access.`03-silver` OWNER TO `reached-hq`;

-- Every current row once, typed, with the reasons it would be quarantined. Labels and free text are
-- read with whitespace normalized and blank as NULL (D-022, D-023); codes are read exactly as
-- published. concat_ws never returns NULL, so quarantine_reasons = '' and <> '' split the rows.
CREATE OR REPLACE TEMPORARY VIEW psa_psgc_classified AS
WITH bronze AS (
  SELECT r.*
  FROM edu_access.`02-bronze`.psa_psgc_raw AS r
  JOIN edu_access.`01-control`.current_batches AS c ON r.batch_id = c.batch_id
  WHERE c.source_id = 'psa_psgc'
),
normalized AS (
  SELECT
    r.*,
    NULLIF(TRIM(regexp_replace(translate(r.`name`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS n_name,
    NULLIF(TRIM(regexp_replace(translate(r.`old_names`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS n_old_names,
    NULLIF(TRIM(regexp_replace(translate(r.`column_j_footnote`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS n_column_j_footnote,
    NULLIF(TRIM(regexp_replace(translate(r.`geographic_level`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS n_geographic_level,
    NULLIF(TRIM(regexp_replace(translate(r.`city_class`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS n_city_class,
    NULLIF(TRIM(regexp_replace(translate(r.`urban_rural`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS n_urban_rural,
    NULLIF(TRIM(regexp_replace(translate(r.`status`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS n_status,
    NULLIF(TRIM(regexp_replace(translate(r.`income_classification`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS n_income_classification,
    NULLIF(r.`correspondence_code`, '') AS n_correspondence,
    COUNT(*) OVER (PARTITION BY r.batch_id, r.`psgc_code`) AS code_rows
  FROM bronze AS r
),
-- The codes of each delivery, once each: a code at the province position is a province, or one of
-- the blank-level containers (City of Isabela, Special Geographic Area), when it is a Prov or
-- blank-level row of the same delivery (O-10).
positions AS (
  SELECT batch_id, `psgc_code` AS psgc_code,
         MAX(CASE WHEN n_geographic_level = 'Prov' OR n_geographic_level IS NULL THEN 1 ELSE 0 END) AS is_province_position
  FROM normalized
  WHERE regexp_like(`psgc_code`, '^[0-9]{10}$')
  GROUP BY batch_id, `psgc_code`
)
SELECT
  n.publication_period,
  CAST(n.publication_date AS DATE) AS publication_date,
  COALESCE(n.publication_period = '2026-Q2', FALSE) AS is_master_reference,
  n.`psgc_code` AS psgc_code,
  n.n_name AS name,
  n.n_correspondence AS correspondence_code,
  CASE n.n_geographic_level WHEN 'Reg' THEN 'Reg' WHEN 'Prov' THEN 'Prov' WHEN 'City' THEN 'City' WHEN 'Mun' THEN 'Mun' WHEN 'SubMun' THEN 'SubMun' WHEN 'Bgy' THEN 'Bgy' ELSE NULL END AS geographic_level,
  CASE WHEN regexp_like(n.`psgc_code`, '^[0-9]{10}$') THEN substr(n.`psgc_code`, 1, 2) || '00000000' END AS region_code,
  CASE WHEN p.is_province_position = 1 THEN p.psgc_code END AS province_code,
  CASE WHEN regexp_like(n.`psgc_code`, '^[0-9]{10}$') AND n.n_geographic_level = 'Bgy' THEN substr(n.`psgc_code`, 1, 7) || '000' END AS city_municipality_code,
  n.n_old_names AS old_names,
  CASE n.n_city_class WHEN 'HUC' THEN 'HUC' WHEN 'ICC' THEN 'ICC' WHEN 'CC' THEN 'CC' ELSE NULL END AS city_class,
  CASE n.n_income_classification WHEN '1st' THEN '1st' WHEN '2nd' THEN '2nd' WHEN '3rd' THEN '3rd' WHEN '4th' THEN '4th' WHEN '5th' THEN '5th' WHEN '2nd*' THEN '2nd' WHEN '3rd*' THEN '3rd' WHEN '4th*' THEN '4th' WHEN '-' THEN NULL ELSE NULL END AS income_class,
  CASE n.n_income_classification WHEN '1st' THEN FALSE WHEN '2nd' THEN FALSE WHEN '3rd' THEN FALSE WHEN '4th' THEN FALSE WHEN '5th' THEN FALSE WHEN '2nd*' THEN TRUE WHEN '3rd*' THEN TRUE WHEN '4th*' THEN TRUE ELSE NULL END AS income_class_retained_after_downgrade,
  CASE n.n_income_classification WHEN '-' THEN 'not_classified' ELSE NULL END AS income_class_null_reason,
  CASE n.n_urban_rural WHEN 'U' THEN 'U' WHEN 'R' THEN 'R' WHEN '-' THEN NULL ELSE NULL END AS urban_rural,
  CASE n.n_urban_rural WHEN '-' THEN 'unknown' ELSE NULL END AS urban_rural_null_reason,
  CASE WHEN regexp_like(n.`population`, '^[0-9]{1,9}$') THEN CAST(n.`population` AS INT) END AS population,
  CASE n.`population` WHEN '#N/A' THEN 'publisher_na' WHEN '' THEN 'blank' ELSE NULL END AS population_null_reason,
  n.n_column_j_footnote AS population_footnote,
  CASE n.n_status WHEN 'Capital' THEN 'Capital' WHEN 'Pob.' THEN 'Pob.' ELSE NULL END AS status,
  (n.n_geographic_level IS NULL) AS level_blank,
  COALESCE(CASE WHEN regexp_like(n.`population`, '^[0-9]{1,9}$') THEN CAST(n.`population` AS INT) END = 0, FALSE) AS population_is_zero,
  (n.n_column_j_footnote IS NOT NULL) AS has_population_footnote,
  concat_ws(',',
      CASE WHEN n.`psgc_code` IS NULL OR n.`psgc_code` = '' THEN 'psgc_code_blank'
           WHEN NOT regexp_like(n.`psgc_code`, '^[0-9]{10}$') THEN 'psgc_code_malformed' END,
      CASE WHEN regexp_like(n.`psgc_code`, '^[0-9]{10}$') AND n.code_rows > 1 THEN 'psgc_code_duplicated' END,
      CASE WHEN n.n_correspondence IS NOT NULL AND NOT regexp_like(n.n_correspondence, '^[0-9]{9}$') THEN 'correspondence_code_malformed' END,
      CASE WHEN (n.`population` <> '' AND NOT regexp_like(n.`population`, '^[0-9]{1,9}$') AND n.`population` NOT IN ('#N/A')) THEN 'population_uncastable' END
    ) AS quarantine_reasons,
  n.batch_id,
  n.delivery_version,
  n.schema_version,
  n.source_sha256,
  n.source_row_number,
  session.silver_run_id AS run_id,
  session.silver_cleaned_at_utc AS cleaned_at_utc,
  session.silver_code_revision AS code_revision
FROM normalized AS n
-- positions holds valid codes only; a row with a malformed code is quarantined, so its match never
-- reaches the clean table. (A pattern test in this join made it a slow nested loop on DuckDB.)
LEFT JOIN positions AS p
  ON p.batch_id = n.batch_id AND p.psgc_code = substr(n.`psgc_code`, 1, 5) || '00000';

-- One row per PSGC code per quarter, with the Bronze row it came from.
CREATE OR REPLACE TABLE edu_access.`03-silver`.psa_psgc_clean_candidate USING DELTA AS
SELECT
  publication_period,
  publication_date,
  is_master_reference,
  psgc_code,
  name,
  correspondence_code,
  geographic_level,
  region_code,
  province_code,
  city_municipality_code,
  old_names,
  city_class,
  income_class,
  income_class_retained_after_downgrade,
  income_class_null_reason,
  urban_rural,
  urban_rural_null_reason,
  population,
  population_null_reason,
  population_footnote,
  status,
  level_blank,
  population_is_zero,
  has_population_footnote,
  batch_id,
  delivery_version,
  schema_version,
  source_sha256,
  source_row_number,
  run_id,
  cleaned_at_utc,
  code_revision
FROM psa_psgc_classified
WHERE quarantine_reasons = '';

COMMENT ON TABLE edu_access.`03-silver`.psa_psgc_clean_candidate IS 'Unpublished build for the Silver gate, which may have failed. Do not read: use psa_psgc_clean, trusted by the run its rows carry (D-025).';
ALTER TABLE edu_access.`03-silver`.psa_psgc_clean_candidate OWNER TO `reached-hq`;

-- Rows set aside, never deleted: the Bronze row, and why.
CREATE OR REPLACE TABLE edu_access.`03-silver`.psa_psgc_quarantine_candidate USING DELTA AS
SELECT
  publication_period,
  psgc_code,
  name,
  split(quarantine_reasons, ',') AS quarantine_reasons,
  batch_id,
  delivery_version,
  schema_version,
  source_sha256,
  source_row_number,
  run_id,
  cleaned_at_utc,
  code_revision
FROM psa_psgc_classified
WHERE quarantine_reasons <> '';

COMMENT ON TABLE edu_access.`03-silver`.psa_psgc_quarantine_candidate IS 'Unpublished build for the Silver gate, which may have failed. Do not read: use psa_psgc_quarantine, trusted by the run its rows carry (D-025).';
ALTER TABLE edu_access.`03-silver`.psa_psgc_quarantine_candidate OWNER TO `reached-hq`;
