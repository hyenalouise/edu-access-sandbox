-- Silver build for deped_psgc_coordinates. Generated from config/ingestion/deped_psgc_coordinates.json
-- and config/mappings/deped_psgc_coordinates.json:
--   python -m src.silver.cli sql --source deped_psgc_coordinates > etl/03_silver/09_clean_deped_psgc_coordinates.sql
-- Do not edit by hand; tests/test_silver.py fails if it differs.
-- Builds unpublished candidate tables. The gate publishes them only after every FAIL check is zero.

DECLARE OR REPLACE VARIABLE silver_run_id STRING;
SET VARIABLE silver_run_id = :run_id;
DECLARE OR REPLACE VARIABLE silver_code_revision STRING;
SET VARIABLE silver_code_revision = COALESCE(NULLIF(:code_revision, ''), 'UNSET');
DECLARE OR REPLACE VARIABLE silver_environment STRING;
SET VARIABLE silver_environment = COALESCE(NULLIF(:environment, ''), 'UNSET');
DECLARE OR REPLACE VARIABLE silver_cleaned_at_utc TIMESTAMP;
SET VARIABLE silver_cleaned_at_utc = current_timestamp();

MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (SELECT session.silver_run_id AS run_id) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'silver_build' AND t.source_id = 'deped_psgc_coordinates'
WHEN MATCHED THEN UPDATE SET status = 'running', started_at_utc = session.silver_cleaned_at_utc, finished_at_utc = NULL, failure_stage = NULL, error_message = NULL, code_revision = session.silver_code_revision, job_run_id = s.run_id
WHEN NOT MATCHED THEN INSERT (run_id, pipeline_name, source_id, environment, status, started_at_utc, code_revision, job_run_id)
  VALUES (s.run_id, 'silver_build', 'deped_psgc_coordinates', session.silver_environment, 'running', session.silver_cleaned_at_utc, session.silver_code_revision, s.run_id);

CREATE SCHEMA IF NOT EXISTS edu_access.`03-silver`;
ALTER SCHEMA edu_access.`03-silver` OWNER TO `reached-hq`;

-- Only rows of kind unit are schools; blank and no_identifier rows stay in Bronze (D-049).
CREATE OR REPLACE TEMPORARY VIEW deped_psgc_coordinates_classified AS
WITH bronze AS (
  SELECT r.* FROM edu_access.`02-bronze`.deped_psgc_coordinates_raw AS r JOIN edu_access.`01-control`.current_batches AS b ON r.batch_id = b.batch_id
  WHERE b.source_id = 'deped_psgc_coordinates' AND r.source_row_kind = 'unit'
), ids AS (
  -- How many rows share a school_id, and how many different versions of the row there are.
  SELECT r.school_year, r.school_id, COUNT(*) AS id_rows, COUNT(DISTINCT md5(concat_ws('|', COALESCE(r.region, ''), COALESCE(r.division, ''), COALESCE(r.district, ''), COALESCE(r.school_id, ''), COALESCE(r.school_name, ''), COALESCE(r.street_address, ''), COALESCE(r.province, ''), COALESCE(r.municipality, ''), COALESCE(r.legislative_district, ''), COALESCE(r.barangay, ''), COALESCE(r.sector, ''), COALESCE(r.school_subclassification, ''), COALESCE(r.school_type, ''), COALESCE(r.curricular_offering_classification, ''), COALESCE(r.implementing_unit, ''), COALESCE(r.urp, ''), COALESCE(r.modified_coc, ''), COALESCE(r.psgc_region, ''), COALESCE(r.psgc_region_name, ''), COALESCE(r.psgc_province, ''), COALESCE(r.psgc_province_name, ''), COALESCE(r.psgc_city_municipality, ''), COALESCE(r.psgc_city_municipality_name, ''), COALESCE(r.psgc_barangay, ''), COALESCE(r.psgc_barangay_name, ''), COALESCE(r.urban_rural, ''), COALESCE(r.income_class, ''), COALESCE(r.income_class_long, ''), COALESCE(r.longitude, ''), COALESCE(r.latitude, ''), COALESCE(r.k_male, ''), COALESCE(r.k_female, ''), COALESCE(r.g1_male, ''), COALESCE(r.g1_female, ''), COALESCE(r.g2_male, ''), COALESCE(r.g2_female, ''), COALESCE(r.g3_male, ''), COALESCE(r.g3_female, ''), COALESCE(r.g4_male, ''), COALESCE(r.g4_female, ''), COALESCE(r.g5_male, ''), COALESCE(r.g5_female, ''), COALESCE(r.g6_male, ''), COALESCE(r.g6_female, ''), COALESCE(r.elem_ng_male, ''), COALESCE(r.elem_ng_female, ''), COALESCE(r.g7_male, ''), COALESCE(r.g7_female, ''), COALESCE(r.g8_male, ''), COALESCE(r.g8_female, ''), COALESCE(r.g9_male, ''), COALESCE(r.g9_female, ''), COALESCE(r.g10_male, ''), COALESCE(r.g10_female, ''), COALESCE(r.jhs_ng_male, ''), COALESCE(r.jhs_ng_female, ''), COALESCE(r.g11_acad_abm_male, ''), COALESCE(r.g11_acad_abm_female, ''), COALESCE(r.g11_acad_humss_male, ''), COALESCE(r.g11_acad_humss_female, ''), COALESCE(r.g11_acad_stem_male, ''), COALESCE(r.g11_acad_stem_female, ''), COALESCE(r.g11_acad_gas_male, ''), COALESCE(r.g11_acad_gas_female, ''), COALESCE(r.g11_acad_pbm_male, ''), COALESCE(r.g11_acad_pbm_female, ''), COALESCE(r.g11_tvl_male, ''), COALESCE(r.g11_tvl_female, ''), COALESCE(r.g11_sports_male, ''), COALESCE(r.g11_sports_female, ''), COALESCE(r.g11_arts_male, ''), COALESCE(r.g11_arts_female, ''), COALESCE(r.g12_acad_abm_male, ''), COALESCE(r.g12_acad_abm_female, ''), COALESCE(r.g12_acad_humss_male, ''), COALESCE(r.g12_acad_humss_female, ''), COALESCE(r.g12_acad_stem_male, ''), COALESCE(r.g12_acad_stem_female, ''), COALESCE(r.g12_acad_gas_male, ''), COALESCE(r.g12_acad_gas_female, ''), COALESCE(r.g12_acad_pbm_male, ''), COALESCE(r.g12_acad_pbm_female, ''), COALESCE(r.g12_tvl_male, ''), COALESCE(r.g12_tvl_female, ''), COALESCE(r.g12_sports_male, ''), COALESCE(r.g12_sports_female, ''), COALESCE(r.g12_arts_male, ''), COALESCE(r.g12_arts_female, '')))) AS id_versions
  FROM bronze AS r GROUP BY r.school_year, r.school_id
), coded AS (
  SELECT
    r.school_year,
    r.school_id AS school_id,
    CASE WHEN regexp_like(r.psgc_region, '^[0-9]{9,10}$') THEN lpad(r.psgc_region, 10, '0') END AS region_padded,
    CASE WHEN regexp_like(r.psgc_province, '^[0-9]{9,10}$') THEN lpad(r.psgc_province, 10, '0') END AS province_padded,
    CASE WHEN regexp_like(r.psgc_city_municipality, '^[0-9]{9,10}$') THEN lpad(r.psgc_city_municipality, 10, '0') END AS city_municipality_padded,
    CASE WHEN regexp_like(r.psgc_barangay, '^[0-9]{9,10}$') THEN lpad(r.psgc_barangay, 10, '0') END AS barangay_padded,
    CASE WHEN r.psgc_city_municipality IS NULL THEN 'not_in_workbook' WHEN r.psgc_city_municipality = '#N/A' THEN 'source_na' WHEN r.psgc_city_municipality = '' THEN 'not_in_workbook' ELSE 'unrecognized' END AS city_reason_if_null,
    CASE WHEN r.psgc_barangay IS NULL THEN 'not_in_workbook' WHEN r.psgc_barangay = '#N/A' THEN 'source_na' WHEN r.psgc_barangay = '' THEN 'not_in_workbook' ELSE 'unrecognized' END AS barangay_reason_if_null,
    CASE WHEN regexp_like(r.longitude, '^-?[0-9]+([.][0-9]+)?([eE]-?[0-9]+)?$') THEN TRY_CAST(r.longitude AS DOUBLE) END AS longitude,
    CASE WHEN regexp_like(r.latitude, '^-?[0-9]+([.][0-9]+)?([eE]-?[0-9]+)?$') THEN TRY_CAST(r.latitude AS DOUBLE) END AS latitude,
    g.id_rows,
    g.id_versions,
    ROW_NUMBER() OVER (PARTITION BY r.school_year, r.school_id ORDER BY r.source_row_number) AS id_copy,
    r.batch_id,
    r.delivery_version,
    r.schema_version,
    r.source_sha256,
    r.source_row_number,
    r.school_year AS scope_school_year,
    r.sector AS scope_sector
  FROM bronze AS r JOIN ids AS g ON g.school_year = r.school_year AND g.school_id = r.school_id
), recoded AS (
  SELECT c.*, COALESCE(substr(c.province_padded, 1, 5) = '19066', FALSE) AS psgc_recoded FROM coded AS c
)
SELECT
  c.school_year,
  c.school_id,
  CASE WHEN c.psgc_recoded AND c.region_padded = '1900000000' THEN '0900000000' ELSE c.region_padded END AS psgc_region,
  CASE WHEN c.psgc_recoded AND substr(c.province_padded, 1, 5) = '19066' THEN concat('09066', substr(c.province_padded, 6)) ELSE c.province_padded END AS psgc_province,
  CASE WHEN c.psgc_recoded AND substr(c.city_municipality_padded, 1, 5) = '19066' THEN concat('09066', substr(c.city_municipality_padded, 6)) ELSE c.city_municipality_padded END AS psgc_city_municipality,
  CASE WHEN c.psgc_recoded AND substr(c.barangay_padded, 1, 5) = '19066' THEN concat('09066', substr(c.barangay_padded, 6)) ELSE c.barangay_padded END AS psgc_barangay,
  c.psgc_recoded,
  CASE WHEN c.city_municipality_padded IS NULL THEN c.city_reason_if_null WHEN c.barangay_padded IS NULL THEN c.barangay_reason_if_null END AS psgc_null_reason,
  COALESCE(substr(c.barangay_padded, 1, 7) <> substr(c.city_municipality_padded, 1, 7), FALSE) AS barangay_outside_city,
  c.longitude,
  c.latitude,
  CASE WHEN c.longitude IS NULL OR c.latitude IS NULL THEN 'missing' WHEN c.longitude = 0 AND c.latitude = 0 THEN 'zero' WHEN NOT (c.longitude BETWEEN 116 AND 127 AND c.latitude BETWEEN 4 AND 21.5) THEN 'outside_philippines' END AS coordinate_flag,
  concat_ws(',',
      CASE WHEN NOT regexp_like(c.school_id, '^[0-9]{6}$') THEN 'school_id_malformed' END,
      CASE WHEN c.id_rows > 1 AND c.id_versions > 1 THEN 'school_id_duplicated' END,
      CASE WHEN c.id_rows > 1 AND c.id_versions = 1 AND c.id_copy > 1 THEN 'school_id_identical_copy' END,
      CASE WHEN (c.scope_school_year IS NULL OR c.scope_school_year NOT IN ('2023-24')) THEN 'school_year_out_of_scope' END,
      CASE WHEN (c.scope_sector IS NULL OR c.scope_sector NOT IN ('Public')) THEN 'sector_not_public' END
    ) AS quarantine_reasons,
  c.batch_id,
  c.delivery_version,
  c.schema_version,
  c.source_sha256,
  c.source_row_number
FROM recoded AS c;

CREATE OR REPLACE TABLE edu_access.`03-silver`.deped_psgc_coordinates_clean_candidate USING DELTA AS
SELECT
  school_year,
  school_id,
  psgc_region,
  psgc_province,
  psgc_city_municipality,
  psgc_barangay,
  psgc_recoded,
  psgc_null_reason,
  barangay_outside_city,
  longitude,
  latitude,
  coordinate_flag,
  batch_id,
  delivery_version,
  schema_version,
  source_sha256,
  source_row_number,
  session.silver_run_id AS run_id,
  session.silver_cleaned_at_utc AS cleaned_at_utc,
  session.silver_code_revision AS code_revision
FROM deped_psgc_coordinates_classified WHERE quarantine_reasons = '';

COMMENT ON TABLE edu_access.`03-silver`.deped_psgc_coordinates_clean_candidate IS 'Unpublished build for the Silver gate, which may have failed. Do not read: use deped_psgc_coordinates_clean, trusted by the run its rows carry (D-025).';
ALTER TABLE edu_access.`03-silver`.deped_psgc_coordinates_clean_candidate OWNER TO `reached-hq`;

CREATE OR REPLACE TABLE edu_access.`03-silver`.deped_psgc_coordinates_quarantine_candidate USING DELTA AS
SELECT
  school_year,
  school_id,
  split(quarantine_reasons, ',') AS quarantine_reasons,
  batch_id,
  delivery_version,
  schema_version,
  source_sha256,
  source_row_number,
  session.silver_run_id AS run_id,
  session.silver_cleaned_at_utc AS cleaned_at_utc,
  session.silver_code_revision AS code_revision
FROM deped_psgc_coordinates_classified WHERE quarantine_reasons <> '';

COMMENT ON TABLE edu_access.`03-silver`.deped_psgc_coordinates_quarantine_candidate IS 'Unpublished build for the Silver gate, which may have failed. Do not read: use deped_psgc_coordinates_quarantine, trusted by the run its rows carry (D-025).';
ALTER TABLE edu_access.`03-silver`.deped_psgc_coordinates_quarantine_candidate OWNER TO `reached-hq`;
