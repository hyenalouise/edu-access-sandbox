-- Silver build for hdx_boundaries. Generated from config/ingestion/hdx_boundaries.json
-- and config/mappings/hdx_boundaries.json by src/silver/hdx_boundaries.py:
--   python -m src.silver.cli sql --source hdx_boundaries > etl/03_silver/06_clean_hdx_adm3.sql
-- Do not edit by hand; tests/test_silver_hdx.py fails if it differs.
--
-- Rebuilds the two candidate tables from the current Bronze batches only (01-control.current_batches:
-- the latest succeeded delivery version of each reference date). Bronze is read, never changed.
-- Every current Bronze feature ends in exactly one of the two tables:
--   hdx_adm3_clean_candidate       one row per ADM3 unit, typed, geometry as published;
--   hdx_adm3_quarantine_candidate  features that cannot be trusted, with their reasons.
-- The Silver tables (hdx_adm3_clean, hdx_adm3_quarantine) are never written here:
-- the gate (the next task) checks the candidates and publishes them only if no check fails,
-- so a failed build never replaces the last good one. It rebuilds on every run (D-025).
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
ON t.run_id = s.run_id AND t.pipeline_name = 'silver_build' AND t.source_id = 'hdx_boundaries'
WHEN MATCHED THEN UPDATE SET
  status = 'running', started_at_utc = session.silver_cleaned_at_utc, finished_at_utc = NULL,
  failure_stage = NULL, error_message = NULL, code_revision = session.silver_code_revision, job_run_id = s.run_id
WHEN NOT MATCHED THEN INSERT (run_id, pipeline_name, source_id, environment, status, started_at_utc, code_revision, job_run_id)
  VALUES (s.run_id, 'silver_build', 'hdx_boundaries', session.silver_environment, 'running',
          session.silver_cleaned_at_utc, session.silver_code_revision, s.run_id);

CREATE SCHEMA IF NOT EXISTS edu_access.`03-silver`;
ALTER SCHEMA edu_access.`03-silver` OWNER TO `reached-hq`;

-- Every current Bronze feature once, typed, with the reasons it would be quarantined. A reason is
-- decided with explicit NULL handling, and concat_ws never returns NULL, so quarantine_reasons = ''
-- and <> '' split the features without losing any. The geometry is parsed once, here, and only
-- its checks are kept: Silver stores the published text.
CREATE OR REPLACE TEMPORARY VIEW hdx_boundaries_classified AS
WITH bronze AS (
  SELECT r.*
  FROM edu_access.`02-bronze`.hdx_adm3_raw AS r
  JOIN edu_access.`01-control`.current_batches AS c ON r.batch_id = c.batch_id
  WHERE c.source_id = 'hdx_boundaries'
),
-- Free text and labels: whitespace normalized, blank to NULL. Codes, numbers, dates and the
-- geometry stay as published here. The key is counted per reference date.
normalized AS (
  SELECT
    r.`adm3_pcode`,
    r.school_year,
    COUNT(*) OVER (PARTITION BY r.school_year, r.`adm3_pcode`) AS adm3_pcode_rows,
    NULLIF(TRIM(regexp_replace(translate(r.`adm3_name`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS adm3_name,
    NULLIF(TRIM(regexp_replace(translate(r.`adm3_name1`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS adm3_name1,
    NULLIF(TRIM(regexp_replace(translate(r.`adm3_name2`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS adm3_name2,
    NULLIF(TRIM(regexp_replace(translate(r.`adm3_name3`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS adm3_name3,
    NULLIF(TRIM(regexp_replace(translate(r.`adm2_name`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS adm2_name,
    NULLIF(TRIM(regexp_replace(translate(r.`adm2_name1`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS adm2_name1,
    NULLIF(TRIM(regexp_replace(translate(r.`adm2_name2`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS adm2_name2,
    NULLIF(TRIM(regexp_replace(translate(r.`adm2_name3`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS adm2_name3,
    r.`adm2_pcode` AS adm2_pcode,
    NULLIF(TRIM(regexp_replace(translate(r.`adm1_name`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS adm1_name,
    NULLIF(TRIM(regexp_replace(translate(r.`adm1_name1`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS adm1_name1,
    NULLIF(TRIM(regexp_replace(translate(r.`adm1_name2`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS adm1_name2,
    NULLIF(TRIM(regexp_replace(translate(r.`adm1_name3`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS adm1_name3,
    r.`adm1_pcode` AS adm1_pcode,
    NULLIF(TRIM(regexp_replace(translate(r.`adm0_name`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS adm0_name,
    NULLIF(TRIM(regexp_replace(translate(r.`adm0_name1`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS adm0_name1,
    NULLIF(TRIM(regexp_replace(translate(r.`adm0_name2`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS adm0_name2,
    NULLIF(TRIM(regexp_replace(translate(r.`adm0_name3`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS adm0_name3,
    r.`adm0_pcode` AS adm0_pcode,
    r.`valid_on` AS valid_on,
    r.`valid_to` AS valid_to,
    r.`area_sqkm` AS area_sqkm,
    NULLIF(TRIM(regexp_replace(translate(r.`version`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS version,
    NULLIF(TRIM(regexp_replace(translate(r.`lang`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS lang,
    NULLIF(TRIM(regexp_replace(translate(r.`lang1`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS lang1,
    NULLIF(TRIM(regexp_replace(translate(r.`lang2`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS lang2,
    NULLIF(TRIM(regexp_replace(translate(r.`lang3`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS lang3,
    NULLIF(TRIM(regexp_replace(translate(r.`adm3_ref_name`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS adm3_ref_name,
    r.`center_lat` AS center_lat,
    r.`center_lon` AS center_lon,
    r.`geometry` AS geometry,
    try_to_geometry(r.`geometry`) AS geo,
    r.batch_id,
    r.delivery_version,
    r.schema_version,
    r.source_sha256,
    r.source_row_number
  FROM bronze AS r
),
-- Labels mapped to the standard set (unmapped: NULL, and the gate fails); dates and decimals typed
-- only when the published text fits the type exactly, so no digit is rounded away (D-023).
typed AS (
  SELECT
    n.adm3_name,
    n.adm3_name1,
    n.adm3_name2,
    n.adm3_name3,
    n.adm3_pcode,
    n.adm2_name,
    n.adm2_name1,
    n.adm2_name2,
    n.adm2_name3,
    n.adm2_pcode,
    CASE n.adm1_name
      WHEN 'Bangsamoro Autonomous Region In Muslim Mindanao (BARMM)' THEN 'Bangsamoro Autonomous Region In Muslim Mindanao (BARMM)'
      WHEN 'Cordillera Administrative Region (CAR)' THEN 'Cordillera Administrative Region (CAR)'
      WHEN 'Mimaropa Region' THEN 'Mimaropa Region'
      WHEN 'National Capital Region (NCR)' THEN 'National Capital Region (NCR)'
      WHEN 'Region I (Ilocos Region)' THEN 'Region I (Ilocos Region)'
      WHEN 'Region II (Cagayan Valley)' THEN 'Region II (Cagayan Valley)'
      WHEN 'Region III (Central Luzon)' THEN 'Region III (Central Luzon)'
      WHEN 'Region IV-A (Calabarzon)' THEN 'Region IV-A (Calabarzon)'
      WHEN 'Region IX (Zamboanga Peninsula)' THEN 'Region IX (Zamboanga Peninsula)'
      WHEN 'Region V (Bicol Region)' THEN 'Region V (Bicol Region)'
      WHEN 'Region VI (Western Visayas)' THEN 'Region VI (Western Visayas)'
      WHEN 'Region VII (Central Visayas)' THEN 'Region VII (Central Visayas)'
      WHEN 'Region VIII (Eastern Visayas)' THEN 'Region VIII (Eastern Visayas)'
      WHEN 'Region X (Northern Mindanao)' THEN 'Region X (Northern Mindanao)'
      WHEN 'Region XI (Davao Region)' THEN 'Region XI (Davao Region)'
      WHEN 'Region XII (Soccsksargen)' THEN 'Region XII (Soccsksargen)'
      WHEN 'Region XIII (Caraga)' THEN 'Region XIII (Caraga)'
    END AS adm1_name,
    n.adm1_name1,
    n.adm1_name2,
    n.adm1_name3,
    n.adm1_pcode,
    CASE n.adm0_name
      WHEN 'Philippines' THEN 'Philippines'
    END AS adm0_name,
    n.adm0_name1,
    n.adm0_name2,
    n.adm0_name3,
    n.adm0_pcode,
    CASE WHEN regexp_like(n.valid_on, '^[0-9]{4}-[0-9]{2}-[0-9]{2}$') THEN TRY_CAST(n.valid_on AS DATE) END AS valid_on,
    CASE WHEN regexp_like(n.valid_to, '^[0-9]{4}-[0-9]{2}-[0-9]{2}$') THEN TRY_CAST(n.valid_to AS DATE) END AS valid_to,
    CASE WHEN regexp_like(n.area_sqkm, '^-?[0-9]{1,6}([.][0-9]{1,14})?$') THEN TRY_CAST(n.area_sqkm AS DECIMAL(20,14)) END AS area_sqkm,
    CASE n.version
      WHEN 'v03' THEN 'v03'
    END AS version,
    CASE n.lang
      WHEN 'en' THEN 'en'
    END AS lang,
    n.lang1,
    n.lang2,
    n.lang3,
    n.adm3_ref_name,
    CASE WHEN regexp_like(n.center_lat, '^-?[0-9]{1,4}([.][0-9]{1,14})?$') THEN TRY_CAST(n.center_lat AS DECIMAL(18,14)) END AS center_lat,
    CASE WHEN regexp_like(n.center_lon, '^-?[0-9]{1,4}([.][0-9]{1,14})?$') THEN TRY_CAST(n.center_lon AS DECIMAL(18,14)) END AS center_lon,
    n.geometry,
    COALESCE(regexp_like(n.adm2_pcode, '^PH[0-9]{5}$')
        AND regexp_like(n.adm1_pcode, '^PH[0-9]{2}$')
        AND regexp_like(n.adm0_pcode, '^PH$')
        AND substr(n.adm3_pcode, 1, length(n.adm2_pcode)) = n.adm2_pcode
        AND substr(n.adm2_pcode, 1, length(n.adm1_pcode)) = n.adm1_pcode, FALSE) AS hierarchy_consistent,
    COALESCE(st_isvalid(n.geo), FALSE) AS geometry_is_valid,
    COALESCE(st_contains(n.geo, try_to_geometry(concat('{"type": "Point", "coordinates": [', n.center_lon, ', ', n.center_lat, ']}'))), FALSE) AS center_inside_geometry,
    concat_ws(',',
      CASE WHEN n.adm3_pcode IS NULL OR n.adm3_pcode = '' THEN 'adm3_pcode_blank' END,
      CASE WHEN n.adm3_pcode <> '' AND NOT regexp_like(n.adm3_pcode, '^PH[0-9]{7}$') THEN 'adm3_pcode_malformed' END,
      CASE WHEN n.adm3_pcode <> '' AND n.adm3_pcode_rows > 1 THEN 'adm3_pcode_duplicated' END,
      CASE WHEN (NOT (n.valid_on IS NULL OR n.valid_on = '') AND CASE WHEN regexp_like(n.valid_on, '^[0-9]{4}-[0-9]{2}-[0-9]{2}$') THEN TRY_CAST(n.valid_on AS DATE) END IS NULL) THEN 'valid_on_uncastable' END,
      CASE WHEN (NOT (n.valid_to IS NULL OR n.valid_to = '') AND CASE WHEN regexp_like(n.valid_to, '^[0-9]{4}-[0-9]{2}-[0-9]{2}$') THEN TRY_CAST(n.valid_to AS DATE) END IS NULL) THEN 'valid_to_uncastable' END,
      CASE WHEN (NOT (n.area_sqkm IS NULL OR n.area_sqkm = '') AND CASE WHEN regexp_like(n.area_sqkm, '^-?[0-9]{1,6}([.][0-9]{1,14})?$') THEN TRY_CAST(n.area_sqkm AS DECIMAL(20,14)) END IS NULL) THEN 'area_uncastable' END,
      CASE WHEN CASE WHEN regexp_like(n.area_sqkm, '^-?[0-9]{1,6}([.][0-9]{1,14})?$') THEN TRY_CAST(n.area_sqkm AS DECIMAL(20,14)) END <= 0 THEN 'area_not_positive' END,
      CASE WHEN (NOT (n.center_lat IS NULL OR n.center_lat = '') AND CASE WHEN regexp_like(n.center_lat, '^-?[0-9]{1,4}([.][0-9]{1,14})?$') THEN TRY_CAST(n.center_lat AS DECIMAL(18,14)) END IS NULL)
            OR (NOT (n.center_lon IS NULL OR n.center_lon = '') AND CASE WHEN regexp_like(n.center_lon, '^-?[0-9]{1,4}([.][0-9]{1,14})?$') THEN TRY_CAST(n.center_lon AS DECIMAL(18,14)) END IS NULL) THEN 'center_uncastable' END,
      CASE WHEN n.geo IS NULL THEN 'geometry_unparseable' END,
      CASE WHEN n.geo IS NOT NULL AND st_isempty(n.geo) THEN 'geometry_empty' END,
      CASE WHEN n.geo IS NOT NULL AND NOT st_isempty(n.geo)
            AND upper(replace(CAST(st_geometrytype(n.geo) AS STRING), 'ST_', '')) NOT IN ('POLYGON', 'MULTIPOLYGON') THEN 'geometry_wrong_type' END
    ) AS quarantine_reasons,
    n.batch_id,
    n.delivery_version,
    n.schema_version,
    n.source_sha256,
    n.source_row_number
  FROM normalized AS n
)
SELECT
  t.adm3_name,
  t.adm3_name1,
  t.adm3_name2,
  t.adm3_name3,
  t.adm3_pcode,
  t.adm2_name,
  t.adm2_name1,
  t.adm2_name2,
  t.adm2_name3,
  t.adm2_pcode,
  t.adm1_name,
  t.adm1_name1,
  t.adm1_name2,
  t.adm1_name3,
  t.adm1_pcode,
  t.adm0_name,
  t.adm0_name1,
  t.adm0_name2,
  t.adm0_name3,
  t.adm0_pcode,
  t.valid_on,
  t.valid_to,
  t.area_sqkm,
  t.version,
  t.lang,
  t.lang1,
  t.lang2,
  t.lang3,
  t.adm3_ref_name,
  t.center_lat,
  t.center_lon,
  t.geometry,
  t.hierarchy_consistent,
  t.geometry_is_valid,
  t.center_inside_geometry,
  t.quarantine_reasons,
  t.batch_id,
  t.delivery_version,
  t.schema_version,
  t.source_sha256,
  t.source_row_number,
  session.silver_run_id AS run_id,
  session.silver_cleaned_at_utc AS cleaned_at_utc,
  session.silver_code_revision AS code_revision
FROM typed AS t;

-- One row per ADM3 unit, with the Bronze feature it came from.
CREATE OR REPLACE TABLE edu_access.`03-silver`.hdx_adm3_clean_candidate USING DELTA AS
SELECT
  adm3_name,
  adm3_name1,
  adm3_name2,
  adm3_name3,
  adm3_pcode,
  adm2_name,
  adm2_name1,
  adm2_name2,
  adm2_name3,
  adm2_pcode,
  adm1_name,
  adm1_name1,
  adm1_name2,
  adm1_name3,
  adm1_pcode,
  adm0_name,
  adm0_name1,
  adm0_name2,
  adm0_name3,
  adm0_pcode,
  valid_on,
  valid_to,
  area_sqkm,
  version,
  lang,
  lang1,
  lang2,
  lang3,
  adm3_ref_name,
  center_lat,
  center_lon,
  geometry,
  hierarchy_consistent,
  geometry_is_valid,
  center_inside_geometry,
  batch_id,
  delivery_version,
  schema_version,
  source_sha256,
  source_row_number,
  run_id,
  cleaned_at_utc,
  code_revision
FROM hdx_boundaries_classified
WHERE quarantine_reasons = '';

COMMENT ON TABLE edu_access.`03-silver`.hdx_adm3_clean_candidate IS 'Unpublished build for the Silver gate, which may have failed. Do not read: use hdx_adm3_clean, trusted by the run its rows carry (D-025).';
ALTER TABLE edu_access.`03-silver`.hdx_adm3_clean_candidate OWNER TO `reached-hq`;

-- Features set aside, never deleted: the Bronze feature, and why.
CREATE OR REPLACE TABLE edu_access.`03-silver`.hdx_adm3_quarantine_candidate USING DELTA AS
SELECT
  adm3_pcode,
  split(quarantine_reasons, ',') AS quarantine_reasons,
  batch_id,
  delivery_version,
  schema_version,
  source_sha256,
  source_row_number,
  run_id,
  cleaned_at_utc,
  code_revision
FROM hdx_boundaries_classified
WHERE quarantine_reasons <> '';

COMMENT ON TABLE edu_access.`03-silver`.hdx_adm3_quarantine_candidate IS 'Unpublished build for the Silver gate, which may have failed. Do not read: use hdx_adm3_quarantine, trusted by the run its rows carry (D-025).';
ALTER TABLE edu_access.`03-silver`.hdx_adm3_quarantine_candidate OWNER TO `reached-hq`;
