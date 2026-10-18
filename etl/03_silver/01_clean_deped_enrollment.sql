-- Silver build for deped_enrollment. Generated from config/ingestion/deped_enrollment.json
-- and config/mappings/deped_enrollment.json:
--   python -m src.silver.cli sql --source deped_enrollment > etl/03_silver/01_clean_deped_enrollment.sql
-- Do not edit by hand; tests/test_silver.py fails if it differs.
--
-- Rebuilds the two candidate tables from the current Bronze batches only (01-control.current_batches:
-- the latest succeeded delivery version of each school year). Bronze is read, never changed.
-- Every current Bronze row ends in exactly one of the two tables:
--   deped_enrollment_clean_candidate       one row per school per school year, typed and standardized;
--   deped_enrollment_quarantine_candidate  rows that cannot be trusted, with their reasons.
-- The Silver tables (deped_enrollment_clean, deped_enrollment_quarantine) are never written here:
-- the gate (the next task) checks the candidates and publishes them only if every check passes,
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
ON t.run_id = s.run_id AND t.pipeline_name = 'silver_build' AND t.source_id = 'deped_enrollment'
WHEN MATCHED THEN UPDATE SET
  status = 'running', started_at_utc = session.silver_cleaned_at_utc, finished_at_utc = NULL,
  failure_stage = NULL, error_message = NULL, code_revision = session.silver_code_revision, job_run_id = s.run_id
WHEN NOT MATCHED THEN INSERT (run_id, pipeline_name, source_id, environment, status, started_at_utc, code_revision, job_run_id)
  VALUES (s.run_id, 'silver_build', 'deped_enrollment', session.silver_environment, 'running',
          session.silver_cleaned_at_utc, session.silver_code_revision, s.run_id);

CREATE SCHEMA IF NOT EXISTS edu_access.`03-silver`;
ALTER SCHEMA edu_access.`03-silver` OWNER TO `reached-hq`;

-- Every current Bronze row once, cleaned, with the reasons it would be quarantined.
-- A reason is decided with explicit NULL handling, and concat_ws never returns NULL, so
-- quarantine_reasons = '' and <> '' split the rows without losing any.
CREATE OR REPLACE TEMPORARY VIEW deped_enrollment_classified AS
WITH bronze AS (
  SELECT r.*
  FROM edu_access.`02-bronze`.deped_enrollment_raw AS r
  JOIN edu_access.`01-control`.current_batches AS c ON r.batch_id = c.batch_id
  WHERE c.source_id = 'deped_enrollment'
),
-- Text: character repair (free text only), whitespace normalized, blank to NULL. Counts stay as published here.
normalized AS (
  SELECT
    r.school_year,
    r.`school_id`,
    COUNT(*) OVER (PARTITION BY r.school_year, r.`school_id`) AS school_id_rows,
    length(r.`barangay`) AS barangay_published_length,
    NULLIF(TRIM(regexp_replace(translate(replace(replace(r.`school_name`, 'Ã‘', 'Ñ'), 'Ã±', 'ñ'), chr(9) || chr(160), '  '), ' +', ' ')), '') AS school_name,
    NULLIF(TRIM(regexp_replace(translate(r.`region`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS region,
    NULLIF(TRIM(regexp_replace(translate(replace(replace(r.`division`, 'Ã‘', 'Ñ'), 'Ã±', 'ñ'), chr(9) || chr(160), '  '), ' +', ' ')), '') AS division,
    NULLIF(TRIM(regexp_replace(translate(replace(replace(r.`province`, 'Ã‘', 'Ñ'), 'Ã±', 'ñ'), chr(9) || chr(160), '  '), ' +', ' ')), '') AS province,
    NULLIF(TRIM(regexp_replace(translate(replace(replace(r.`school_district`, 'Ã‘', 'Ñ'), 'Ã±', 'ñ'), chr(9) || chr(160), '  '), ' +', ' ')), '') AS school_district,
    NULLIF(TRIM(regexp_replace(translate(r.`legislative_district`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS legislative_district,
    NULLIF(TRIM(regexp_replace(translate(replace(replace(r.`municipality`, 'Ã‘', 'Ñ'), 'Ã±', 'ñ'), chr(9) || chr(160), '  '), ' +', ' ')), '') AS municipality,
    NULLIF(TRIM(regexp_replace(translate(replace(replace(r.`barangay`, 'Ã‘', 'Ñ'), 'Ã±', 'ñ'), chr(9) || chr(160), '  '), ' +', ' ')), '') AS barangay,
    NULLIF(TRIM(regexp_replace(translate(replace(replace(r.`street_address`, 'Ã‘', 'Ñ'), 'Ã±', 'ñ'), chr(9) || chr(160), '  '), ' +', ' ')), '') AS street_address,
    NULLIF(TRIM(regexp_replace(translate(r.`sector`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS sector,
    NULLIF(TRIM(regexp_replace(translate(r.`school_management`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS school_management,
    NULLIF(TRIM(regexp_replace(translate(r.`annex_status`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS annex_status,
    NULLIF(TRIM(regexp_replace(translate(r.`offers_es`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS offers_es,
    NULLIF(TRIM(regexp_replace(translate(r.`offers_jhs`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS offers_jhs,
    NULLIF(TRIM(regexp_replace(translate(r.`offers_shs`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS offers_shs,
    NULLIF(TRIM(regexp_replace(translate(r.`Modified Curricular Offering Classification`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS modified_curricular_offering_classification,
    r.`kinder_male` AS kinder_male,
    r.`kinder_female` AS kinder_female,
    r.`g1_male` AS g1_male,
    r.`g1_female` AS g1_female,
    r.`g2_male` AS g2_male,
    r.`g2_female` AS g2_female,
    r.`g3_male` AS g3_male,
    r.`g3_female` AS g3_female,
    r.`g4_male` AS g4_male,
    r.`g4_female` AS g4_female,
    r.`g5_male` AS g5_male,
    r.`g5_female` AS g5_female,
    r.`g6_male` AS g6_male,
    r.`g6_female` AS g6_female,
    r.`esng_male` AS esng_male,
    r.`esng_female` AS esng_female,
    r.`g7_male` AS g7_male,
    r.`g7_female` AS g7_female,
    r.`g8_male` AS g8_male,
    r.`g8_female` AS g8_female,
    r.`g9_male` AS g9_male,
    r.`g9_female` AS g9_female,
    r.`g10_male` AS g10_male,
    r.`g10_female` AS g10_female,
    r.`jhsng_male` AS jhsng_male,
    r.`jhsng_female` AS jhsng_female,
    r.`g11_abm_male` AS g11_abm_male,
    r.`g11_abm_female` AS g11_abm_female,
    r.`g11_arts_male` AS g11_arts_male,
    r.`g11_arts_female` AS g11_arts_female,
    r.`g11_gas_male` AS g11_gas_male,
    r.`g11_gas_female` AS g11_gas_female,
    r.`g11_humss_male` AS g11_humss_male,
    r.`g11_humss_female` AS g11_humss_female,
    r.`g11_maritime_male` AS g11_maritime_male,
    r.`g11_maritime_female` AS g11_maritime_female,
    r.`g11_sports_male` AS g11_sports_male,
    r.`g11_sports_female` AS g11_sports_female,
    r.`g11_stem_male` AS g11_stem_male,
    r.`g11_stem_female` AS g11_stem_female,
    r.`g11_tvl_male` AS g11_tvl_male,
    r.`g11_tvl_female` AS g11_tvl_female,
    r.`g11_unique_male` AS g11_unique_male,
    r.`g11_unique_female` AS g11_unique_female,
    r.`g12_abm_male` AS g12_abm_male,
    r.`g12_abm_female` AS g12_abm_female,
    r.`g12_arts_male` AS g12_arts_male,
    r.`g12_arts_female` AS g12_arts_female,
    r.`g12_gas_male` AS g12_gas_male,
    r.`g12_gas_female` AS g12_gas_female,
    r.`g12_humss_male` AS g12_humss_male,
    r.`g12_humss_female` AS g12_humss_female,
    r.`g12_maritime_male` AS g12_maritime_male,
    r.`g12_maritime_female` AS g12_maritime_female,
    r.`g12_sports_male` AS g12_sports_male,
    r.`g12_sports_female` AS g12_sports_female,
    r.`g12_stem_male` AS g12_stem_male,
    r.`g12_stem_female` AS g12_stem_female,
    r.`g12_tvl_male` AS g12_tvl_male,
    r.`g12_tvl_female` AS g12_tvl_female,
    r.`g12_unique_male` AS g12_unique_male,
    r.`g12_unique_female` AS g12_unique_female,
    r.`g11_sshs_acad_male` AS g11_sshs_acad_male,
    r.`g11_sshs_acad_female` AS g11_sshs_acad_female,
    r.`g11_sshs_techpro_male` AS g11_sshs_techpro_male,
    r.`g11_sshs_techpro_female` AS g11_sshs_techpro_female,
    r.batch_id,
    r.delivery_version,
    r.schema_version,
    r.source_sha256,
    r.source_row_number
  FROM bronze AS r
),
-- Labels mapped to the standard set (unmapped: NULL, and the gate fails), booleans, placeholders,
-- counts typed only when they are whole numbers (TRY_CAST alone accepts '5.0' in DuckDB).
typed AS (
  SELECT
    n.school_year,
    n.school_id,
    n.school_name,
    CASE n.region
      WHEN 'NCR' THEN 'NCR'
      WHEN 'CAR' THEN 'CAR'
      WHEN 'Region I' THEN 'Region I'
      WHEN 'Region II' THEN 'Region II'
      WHEN 'Region III' THEN 'Region III'
      WHEN 'Region IV-A' THEN 'Region IV-A'
      WHEN 'MIMAROPA' THEN 'MIMAROPA'
      WHEN 'Region V' THEN 'Region V'
      WHEN 'Region VI' THEN 'Region VI'
      WHEN 'NIR' THEN 'NIR'
      WHEN 'Region VII' THEN 'Region VII'
      WHEN 'Region VIII' THEN 'Region VIII'
      WHEN 'Region IX' THEN 'Region IX'
      WHEN 'Region X' THEN 'Region X'
      WHEN 'Region XI' THEN 'Region XI'
      WHEN 'Region XII' THEN 'Region XII'
      WHEN 'CARAGA' THEN 'CARAGA'
      WHEN 'BARMM' THEN 'BARMM'
      WHEN 'PSO' THEN 'PSO'
    END AS region,
    n.division,
    n.province,
    n.school_district,
    CASE n.legislative_district
      WHEN '1st District' THEN '1st District'
      WHEN '2nd District' THEN '2nd District'
      WHEN '3rd District' THEN '3rd District'
      WHEN '4th District' THEN '4th District'
      WHEN '5th District' THEN '5th District'
      WHEN '6th District' THEN '6th District'
      WHEN '7th District' THEN '7th District'
      WHEN 'Lone District' THEN 'Lone District'
      WHEN 'No Legislative District' THEN 'No Legislative District'
      WHEN 'PSO' THEN 'PSO'
    END AS legislative_district,
    n.municipality,
    n.barangay,
    CASE WHEN n.street_address IN ('-', 'n/a', 'N/A') THEN NULL ELSE n.street_address END AS street_address,
    CASE n.sector
      WHEN 'Public' THEN 'Public'
      WHEN 'Private' THEN 'Private'
      WHEN 'SUC/LUC' THEN 'SUC/LUC'
      WHEN 'SUCsLUCs' THEN 'SUC/LUC'
      WHEN 'PSO' THEN 'PSO'
    END AS sector,
    CASE n.school_management
      WHEN 'DepEd' THEN 'DepEd'
      WHEN 'DepED Managed' THEN 'DepEd'
      WHEN 'Non-Sectarian' THEN 'Non-Sectarian'
      WHEN 'Sectarian' THEN 'Sectarian'
      WHEN 'SUC' THEN 'SUC'
      WHEN 'SUC Managed' THEN 'SUC'
      WHEN 'LUC' THEN 'LUC'
      WHEN 'Local Government' THEN 'Local Government'
      WHEN 'DOST' THEN 'DOST'
      WHEN 'DOST Managed' THEN 'DOST'
      WHEN 'Other GA' THEN 'Other GA'
      WHEN 'Other GA Managed' THEN 'Other GA'
      WHEN 'International School' THEN 'International School'
      WHEN 'Local International School' THEN 'International School'
      WHEN 'PSO' THEN 'PSO'
      WHEN 'SCHOOL ABROAD' THEN 'PSO'
    END AS school_management,
    CASE n.annex_status
      WHEN 'Standalone School' THEN 'Standalone School'
      WHEN 'School with no Annexes' THEN 'Standalone School'
      WHEN 'Mother School' THEN 'Mother School'
      WHEN 'Mother school' THEN 'Mother School'
      WHEN 'Annex/Extension School' THEN 'Annex/Extension School'
      WHEN 'Annex or Extension school(s)' THEN 'Annex/Extension School'
      WHEN 'Mobile School/Center' THEN 'Mobile School/Center'
      WHEN 'Mobile School(s)/Center(s)' THEN 'Mobile School/Center'
    END AS annex_status,
    CASE WHEN n.offers_es IN ('True', 'Yes') THEN TRUE WHEN n.offers_es IN ('False', 'No') THEN FALSE END AS offers_es,
    CASE WHEN n.offers_jhs IN ('True', 'Yes') THEN TRUE WHEN n.offers_jhs IN ('False', 'No') THEN FALSE END AS offers_jhs,
    CASE WHEN n.offers_shs IN ('True', 'Yes') THEN TRUE WHEN n.offers_shs IN ('False', 'No') THEN FALSE END AS offers_shs,
    CASE n.modified_curricular_offering_classification
      WHEN 'Purely ES' THEN 'Purely ES'
      WHEN 'Purely JHS' THEN 'Purely JHS'
      WHEN 'Purely SHS' THEN 'Purely SHS'
      WHEN 'ES and JHS' THEN 'ES and JHS'
      WHEN 'ES with SHS' THEN 'ES with SHS'
      WHEN 'JHS with SHS' THEN 'JHS with SHS'
      WHEN 'All Offering' THEN 'All Offering'
    END AS modified_curricular_offering_classification,
    CASE WHEN regexp_like(n.kinder_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.kinder_male AS INT) END AS kinder_male,
    CASE WHEN regexp_like(n.kinder_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.kinder_female AS INT) END AS kinder_female,
    CASE WHEN regexp_like(n.g1_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g1_male AS INT) END AS g1_male,
    CASE WHEN regexp_like(n.g1_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g1_female AS INT) END AS g1_female,
    CASE WHEN regexp_like(n.g2_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g2_male AS INT) END AS g2_male,
    CASE WHEN regexp_like(n.g2_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g2_female AS INT) END AS g2_female,
    CASE WHEN regexp_like(n.g3_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g3_male AS INT) END AS g3_male,
    CASE WHEN regexp_like(n.g3_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g3_female AS INT) END AS g3_female,
    CASE WHEN regexp_like(n.g4_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g4_male AS INT) END AS g4_male,
    CASE WHEN regexp_like(n.g4_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g4_female AS INT) END AS g4_female,
    CASE WHEN regexp_like(n.g5_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g5_male AS INT) END AS g5_male,
    CASE WHEN regexp_like(n.g5_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g5_female AS INT) END AS g5_female,
    CASE WHEN regexp_like(n.g6_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g6_male AS INT) END AS g6_male,
    CASE WHEN regexp_like(n.g6_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g6_female AS INT) END AS g6_female,
    CASE WHEN regexp_like(n.esng_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.esng_male AS INT) END AS esng_male,
    CASE WHEN regexp_like(n.esng_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.esng_female AS INT) END AS esng_female,
    CASE WHEN regexp_like(n.g7_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g7_male AS INT) END AS g7_male,
    CASE WHEN regexp_like(n.g7_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g7_female AS INT) END AS g7_female,
    CASE WHEN regexp_like(n.g8_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g8_male AS INT) END AS g8_male,
    CASE WHEN regexp_like(n.g8_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g8_female AS INT) END AS g8_female,
    CASE WHEN regexp_like(n.g9_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g9_male AS INT) END AS g9_male,
    CASE WHEN regexp_like(n.g9_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g9_female AS INT) END AS g9_female,
    CASE WHEN regexp_like(n.g10_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g10_male AS INT) END AS g10_male,
    CASE WHEN regexp_like(n.g10_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g10_female AS INT) END AS g10_female,
    CASE WHEN regexp_like(n.jhsng_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.jhsng_male AS INT) END AS jhsng_male,
    CASE WHEN regexp_like(n.jhsng_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.jhsng_female AS INT) END AS jhsng_female,
    CASE WHEN regexp_like(n.g11_abm_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g11_abm_male AS INT) END AS g11_abm_male,
    CASE WHEN regexp_like(n.g11_abm_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g11_abm_female AS INT) END AS g11_abm_female,
    CASE WHEN regexp_like(n.g11_arts_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g11_arts_male AS INT) END AS g11_arts_male,
    CASE WHEN regexp_like(n.g11_arts_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g11_arts_female AS INT) END AS g11_arts_female,
    CASE WHEN regexp_like(n.g11_gas_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g11_gas_male AS INT) END AS g11_gas_male,
    CASE WHEN regexp_like(n.g11_gas_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g11_gas_female AS INT) END AS g11_gas_female,
    CASE WHEN regexp_like(n.g11_humss_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g11_humss_male AS INT) END AS g11_humss_male,
    CASE WHEN regexp_like(n.g11_humss_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g11_humss_female AS INT) END AS g11_humss_female,
    CASE WHEN regexp_like(n.g11_maritime_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g11_maritime_male AS INT) END AS g11_maritime_male,
    CASE WHEN regexp_like(n.g11_maritime_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g11_maritime_female AS INT) END AS g11_maritime_female,
    CASE WHEN regexp_like(n.g11_sports_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g11_sports_male AS INT) END AS g11_sports_male,
    CASE WHEN regexp_like(n.g11_sports_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g11_sports_female AS INT) END AS g11_sports_female,
    CASE WHEN regexp_like(n.g11_stem_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g11_stem_male AS INT) END AS g11_stem_male,
    CASE WHEN regexp_like(n.g11_stem_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g11_stem_female AS INT) END AS g11_stem_female,
    CASE WHEN regexp_like(n.g11_tvl_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g11_tvl_male AS INT) END AS g11_tvl_male,
    CASE WHEN regexp_like(n.g11_tvl_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g11_tvl_female AS INT) END AS g11_tvl_female,
    CASE WHEN regexp_like(n.g11_unique_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g11_unique_male AS INT) END AS g11_unique_male,
    CASE WHEN regexp_like(n.g11_unique_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g11_unique_female AS INT) END AS g11_unique_female,
    CASE WHEN regexp_like(n.g12_abm_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g12_abm_male AS INT) END AS g12_abm_male,
    CASE WHEN regexp_like(n.g12_abm_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g12_abm_female AS INT) END AS g12_abm_female,
    CASE WHEN regexp_like(n.g12_arts_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g12_arts_male AS INT) END AS g12_arts_male,
    CASE WHEN regexp_like(n.g12_arts_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g12_arts_female AS INT) END AS g12_arts_female,
    CASE WHEN regexp_like(n.g12_gas_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g12_gas_male AS INT) END AS g12_gas_male,
    CASE WHEN regexp_like(n.g12_gas_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g12_gas_female AS INT) END AS g12_gas_female,
    CASE WHEN regexp_like(n.g12_humss_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g12_humss_male AS INT) END AS g12_humss_male,
    CASE WHEN regexp_like(n.g12_humss_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g12_humss_female AS INT) END AS g12_humss_female,
    CASE WHEN regexp_like(n.g12_maritime_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g12_maritime_male AS INT) END AS g12_maritime_male,
    CASE WHEN regexp_like(n.g12_maritime_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g12_maritime_female AS INT) END AS g12_maritime_female,
    CASE WHEN regexp_like(n.g12_sports_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g12_sports_male AS INT) END AS g12_sports_male,
    CASE WHEN regexp_like(n.g12_sports_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g12_sports_female AS INT) END AS g12_sports_female,
    CASE WHEN regexp_like(n.g12_stem_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g12_stem_male AS INT) END AS g12_stem_male,
    CASE WHEN regexp_like(n.g12_stem_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g12_stem_female AS INT) END AS g12_stem_female,
    CASE WHEN regexp_like(n.g12_tvl_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g12_tvl_male AS INT) END AS g12_tvl_male,
    CASE WHEN regexp_like(n.g12_tvl_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g12_tvl_female AS INT) END AS g12_tvl_female,
    CASE WHEN regexp_like(n.g12_unique_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g12_unique_male AS INT) END AS g12_unique_male,
    CASE WHEN regexp_like(n.g12_unique_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g12_unique_female AS INT) END AS g12_unique_female,
    CASE WHEN regexp_like(n.g11_sshs_acad_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g11_sshs_acad_male AS INT) END AS g11_sshs_acad_male,
    CASE WHEN regexp_like(n.g11_sshs_acad_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g11_sshs_acad_female AS INT) END AS g11_sshs_acad_female,
    CASE WHEN regexp_like(n.g11_sshs_techpro_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g11_sshs_techpro_male AS INT) END AS g11_sshs_techpro_male,
    CASE WHEN regexp_like(n.g11_sshs_techpro_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g11_sshs_techpro_female AS INT) END AS g11_sshs_techpro_female,
    COALESCE(n.barangay_published_length = 40, FALSE) AS barangay_possibly_truncated,
    concat_ws(',',
      CASE WHEN n.school_id IS NULL OR n.school_id = '' THEN 'school_id_blank'
           WHEN NOT regexp_like(n.school_id, '^[0-9]{6}$') THEN 'school_id_malformed' END,
      CASE WHEN n.school_id <> '' AND n.school_id_rows > 1 THEN 'school_id_duplicated' END,
      CASE WHEN regexp_like(n.kinder_male, '^-[0-9]+$')
         OR regexp_like(n.kinder_female, '^-[0-9]+$')
         OR regexp_like(n.g1_male, '^-[0-9]+$')
         OR regexp_like(n.g1_female, '^-[0-9]+$')
         OR regexp_like(n.g2_male, '^-[0-9]+$')
         OR regexp_like(n.g2_female, '^-[0-9]+$')
         OR regexp_like(n.g3_male, '^-[0-9]+$')
         OR regexp_like(n.g3_female, '^-[0-9]+$')
         OR regexp_like(n.g4_male, '^-[0-9]+$')
         OR regexp_like(n.g4_female, '^-[0-9]+$')
         OR regexp_like(n.g5_male, '^-[0-9]+$')
         OR regexp_like(n.g5_female, '^-[0-9]+$')
         OR regexp_like(n.g6_male, '^-[0-9]+$')
         OR regexp_like(n.g6_female, '^-[0-9]+$')
         OR regexp_like(n.esng_male, '^-[0-9]+$')
         OR regexp_like(n.esng_female, '^-[0-9]+$')
         OR regexp_like(n.g7_male, '^-[0-9]+$')
         OR regexp_like(n.g7_female, '^-[0-9]+$')
         OR regexp_like(n.g8_male, '^-[0-9]+$')
         OR regexp_like(n.g8_female, '^-[0-9]+$')
         OR regexp_like(n.g9_male, '^-[0-9]+$')
         OR regexp_like(n.g9_female, '^-[0-9]+$')
         OR regexp_like(n.g10_male, '^-[0-9]+$')
         OR regexp_like(n.g10_female, '^-[0-9]+$')
         OR regexp_like(n.jhsng_male, '^-[0-9]+$')
         OR regexp_like(n.jhsng_female, '^-[0-9]+$')
         OR regexp_like(n.g11_abm_male, '^-[0-9]+$')
         OR regexp_like(n.g11_abm_female, '^-[0-9]+$')
         OR regexp_like(n.g11_arts_male, '^-[0-9]+$')
         OR regexp_like(n.g11_arts_female, '^-[0-9]+$')
         OR regexp_like(n.g11_gas_male, '^-[0-9]+$')
         OR regexp_like(n.g11_gas_female, '^-[0-9]+$')
         OR regexp_like(n.g11_humss_male, '^-[0-9]+$')
         OR regexp_like(n.g11_humss_female, '^-[0-9]+$')
         OR regexp_like(n.g11_maritime_male, '^-[0-9]+$')
         OR regexp_like(n.g11_maritime_female, '^-[0-9]+$')
         OR regexp_like(n.g11_sports_male, '^-[0-9]+$')
         OR regexp_like(n.g11_sports_female, '^-[0-9]+$')
         OR regexp_like(n.g11_stem_male, '^-[0-9]+$')
         OR regexp_like(n.g11_stem_female, '^-[0-9]+$')
         OR regexp_like(n.g11_tvl_male, '^-[0-9]+$')
         OR regexp_like(n.g11_tvl_female, '^-[0-9]+$')
         OR regexp_like(n.g11_unique_male, '^-[0-9]+$')
         OR regexp_like(n.g11_unique_female, '^-[0-9]+$')
         OR regexp_like(n.g12_abm_male, '^-[0-9]+$')
         OR regexp_like(n.g12_abm_female, '^-[0-9]+$')
         OR regexp_like(n.g12_arts_male, '^-[0-9]+$')
         OR regexp_like(n.g12_arts_female, '^-[0-9]+$')
         OR regexp_like(n.g12_gas_male, '^-[0-9]+$')
         OR regexp_like(n.g12_gas_female, '^-[0-9]+$')
         OR regexp_like(n.g12_humss_male, '^-[0-9]+$')
         OR regexp_like(n.g12_humss_female, '^-[0-9]+$')
         OR regexp_like(n.g12_maritime_male, '^-[0-9]+$')
         OR regexp_like(n.g12_maritime_female, '^-[0-9]+$')
         OR regexp_like(n.g12_sports_male, '^-[0-9]+$')
         OR regexp_like(n.g12_sports_female, '^-[0-9]+$')
         OR regexp_like(n.g12_stem_male, '^-[0-9]+$')
         OR regexp_like(n.g12_stem_female, '^-[0-9]+$')
         OR regexp_like(n.g12_tvl_male, '^-[0-9]+$')
         OR regexp_like(n.g12_tvl_female, '^-[0-9]+$')
         OR regexp_like(n.g12_unique_male, '^-[0-9]+$')
         OR regexp_like(n.g12_unique_female, '^-[0-9]+$')
         OR regexp_like(n.g11_sshs_acad_male, '^-[0-9]+$')
         OR regexp_like(n.g11_sshs_acad_female, '^-[0-9]+$')
         OR regexp_like(n.g11_sshs_techpro_male, '^-[0-9]+$')
         OR regexp_like(n.g11_sshs_techpro_female, '^-[0-9]+$')
      THEN 'count_negative' END,
      CASE WHEN (n.kinder_male <> '' AND NOT regexp_like(n.kinder_male, '^[0-9]{1,9}$') AND NOT regexp_like(n.kinder_male, '^-[0-9]+$'))
         OR (n.kinder_female <> '' AND NOT regexp_like(n.kinder_female, '^[0-9]{1,9}$') AND NOT regexp_like(n.kinder_female, '^-[0-9]+$'))
         OR (n.g1_male <> '' AND NOT regexp_like(n.g1_male, '^[0-9]{1,9}$') AND NOT regexp_like(n.g1_male, '^-[0-9]+$'))
         OR (n.g1_female <> '' AND NOT regexp_like(n.g1_female, '^[0-9]{1,9}$') AND NOT regexp_like(n.g1_female, '^-[0-9]+$'))
         OR (n.g2_male <> '' AND NOT regexp_like(n.g2_male, '^[0-9]{1,9}$') AND NOT regexp_like(n.g2_male, '^-[0-9]+$'))
         OR (n.g2_female <> '' AND NOT regexp_like(n.g2_female, '^[0-9]{1,9}$') AND NOT regexp_like(n.g2_female, '^-[0-9]+$'))
         OR (n.g3_male <> '' AND NOT regexp_like(n.g3_male, '^[0-9]{1,9}$') AND NOT regexp_like(n.g3_male, '^-[0-9]+$'))
         OR (n.g3_female <> '' AND NOT regexp_like(n.g3_female, '^[0-9]{1,9}$') AND NOT regexp_like(n.g3_female, '^-[0-9]+$'))
         OR (n.g4_male <> '' AND NOT regexp_like(n.g4_male, '^[0-9]{1,9}$') AND NOT regexp_like(n.g4_male, '^-[0-9]+$'))
         OR (n.g4_female <> '' AND NOT regexp_like(n.g4_female, '^[0-9]{1,9}$') AND NOT regexp_like(n.g4_female, '^-[0-9]+$'))
         OR (n.g5_male <> '' AND NOT regexp_like(n.g5_male, '^[0-9]{1,9}$') AND NOT regexp_like(n.g5_male, '^-[0-9]+$'))
         OR (n.g5_female <> '' AND NOT regexp_like(n.g5_female, '^[0-9]{1,9}$') AND NOT regexp_like(n.g5_female, '^-[0-9]+$'))
         OR (n.g6_male <> '' AND NOT regexp_like(n.g6_male, '^[0-9]{1,9}$') AND NOT regexp_like(n.g6_male, '^-[0-9]+$'))
         OR (n.g6_female <> '' AND NOT regexp_like(n.g6_female, '^[0-9]{1,9}$') AND NOT regexp_like(n.g6_female, '^-[0-9]+$'))
         OR (n.esng_male <> '' AND NOT regexp_like(n.esng_male, '^[0-9]{1,9}$') AND NOT regexp_like(n.esng_male, '^-[0-9]+$'))
         OR (n.esng_female <> '' AND NOT regexp_like(n.esng_female, '^[0-9]{1,9}$') AND NOT regexp_like(n.esng_female, '^-[0-9]+$'))
         OR (n.g7_male <> '' AND NOT regexp_like(n.g7_male, '^[0-9]{1,9}$') AND NOT regexp_like(n.g7_male, '^-[0-9]+$'))
         OR (n.g7_female <> '' AND NOT regexp_like(n.g7_female, '^[0-9]{1,9}$') AND NOT regexp_like(n.g7_female, '^-[0-9]+$'))
         OR (n.g8_male <> '' AND NOT regexp_like(n.g8_male, '^[0-9]{1,9}$') AND NOT regexp_like(n.g8_male, '^-[0-9]+$'))
         OR (n.g8_female <> '' AND NOT regexp_like(n.g8_female, '^[0-9]{1,9}$') AND NOT regexp_like(n.g8_female, '^-[0-9]+$'))
         OR (n.g9_male <> '' AND NOT regexp_like(n.g9_male, '^[0-9]{1,9}$') AND NOT regexp_like(n.g9_male, '^-[0-9]+$'))
         OR (n.g9_female <> '' AND NOT regexp_like(n.g9_female, '^[0-9]{1,9}$') AND NOT regexp_like(n.g9_female, '^-[0-9]+$'))
         OR (n.g10_male <> '' AND NOT regexp_like(n.g10_male, '^[0-9]{1,9}$') AND NOT regexp_like(n.g10_male, '^-[0-9]+$'))
         OR (n.g10_female <> '' AND NOT regexp_like(n.g10_female, '^[0-9]{1,9}$') AND NOT regexp_like(n.g10_female, '^-[0-9]+$'))
         OR (n.jhsng_male <> '' AND NOT regexp_like(n.jhsng_male, '^[0-9]{1,9}$') AND NOT regexp_like(n.jhsng_male, '^-[0-9]+$'))
         OR (n.jhsng_female <> '' AND NOT regexp_like(n.jhsng_female, '^[0-9]{1,9}$') AND NOT regexp_like(n.jhsng_female, '^-[0-9]+$'))
         OR (n.g11_abm_male <> '' AND NOT regexp_like(n.g11_abm_male, '^[0-9]{1,9}$') AND NOT regexp_like(n.g11_abm_male, '^-[0-9]+$'))
         OR (n.g11_abm_female <> '' AND NOT regexp_like(n.g11_abm_female, '^[0-9]{1,9}$') AND NOT regexp_like(n.g11_abm_female, '^-[0-9]+$'))
         OR (n.g11_arts_male <> '' AND NOT regexp_like(n.g11_arts_male, '^[0-9]{1,9}$') AND NOT regexp_like(n.g11_arts_male, '^-[0-9]+$'))
         OR (n.g11_arts_female <> '' AND NOT regexp_like(n.g11_arts_female, '^[0-9]{1,9}$') AND NOT regexp_like(n.g11_arts_female, '^-[0-9]+$'))
         OR (n.g11_gas_male <> '' AND NOT regexp_like(n.g11_gas_male, '^[0-9]{1,9}$') AND NOT regexp_like(n.g11_gas_male, '^-[0-9]+$'))
         OR (n.g11_gas_female <> '' AND NOT regexp_like(n.g11_gas_female, '^[0-9]{1,9}$') AND NOT regexp_like(n.g11_gas_female, '^-[0-9]+$'))
         OR (n.g11_humss_male <> '' AND NOT regexp_like(n.g11_humss_male, '^[0-9]{1,9}$') AND NOT regexp_like(n.g11_humss_male, '^-[0-9]+$'))
         OR (n.g11_humss_female <> '' AND NOT regexp_like(n.g11_humss_female, '^[0-9]{1,9}$') AND NOT regexp_like(n.g11_humss_female, '^-[0-9]+$'))
         OR (n.g11_maritime_male <> '' AND NOT regexp_like(n.g11_maritime_male, '^[0-9]{1,9}$') AND NOT regexp_like(n.g11_maritime_male, '^-[0-9]+$'))
         OR (n.g11_maritime_female <> '' AND NOT regexp_like(n.g11_maritime_female, '^[0-9]{1,9}$') AND NOT regexp_like(n.g11_maritime_female, '^-[0-9]+$'))
         OR (n.g11_sports_male <> '' AND NOT regexp_like(n.g11_sports_male, '^[0-9]{1,9}$') AND NOT regexp_like(n.g11_sports_male, '^-[0-9]+$'))
         OR (n.g11_sports_female <> '' AND NOT regexp_like(n.g11_sports_female, '^[0-9]{1,9}$') AND NOT regexp_like(n.g11_sports_female, '^-[0-9]+$'))
         OR (n.g11_stem_male <> '' AND NOT regexp_like(n.g11_stem_male, '^[0-9]{1,9}$') AND NOT regexp_like(n.g11_stem_male, '^-[0-9]+$'))
         OR (n.g11_stem_female <> '' AND NOT regexp_like(n.g11_stem_female, '^[0-9]{1,9}$') AND NOT regexp_like(n.g11_stem_female, '^-[0-9]+$'))
         OR (n.g11_tvl_male <> '' AND NOT regexp_like(n.g11_tvl_male, '^[0-9]{1,9}$') AND NOT regexp_like(n.g11_tvl_male, '^-[0-9]+$'))
         OR (n.g11_tvl_female <> '' AND NOT regexp_like(n.g11_tvl_female, '^[0-9]{1,9}$') AND NOT regexp_like(n.g11_tvl_female, '^-[0-9]+$'))
         OR (n.g11_unique_male <> '' AND NOT regexp_like(n.g11_unique_male, '^[0-9]{1,9}$') AND NOT regexp_like(n.g11_unique_male, '^-[0-9]+$'))
         OR (n.g11_unique_female <> '' AND NOT regexp_like(n.g11_unique_female, '^[0-9]{1,9}$') AND NOT regexp_like(n.g11_unique_female, '^-[0-9]+$'))
         OR (n.g12_abm_male <> '' AND NOT regexp_like(n.g12_abm_male, '^[0-9]{1,9}$') AND NOT regexp_like(n.g12_abm_male, '^-[0-9]+$'))
         OR (n.g12_abm_female <> '' AND NOT regexp_like(n.g12_abm_female, '^[0-9]{1,9}$') AND NOT regexp_like(n.g12_abm_female, '^-[0-9]+$'))
         OR (n.g12_arts_male <> '' AND NOT regexp_like(n.g12_arts_male, '^[0-9]{1,9}$') AND NOT regexp_like(n.g12_arts_male, '^-[0-9]+$'))
         OR (n.g12_arts_female <> '' AND NOT regexp_like(n.g12_arts_female, '^[0-9]{1,9}$') AND NOT regexp_like(n.g12_arts_female, '^-[0-9]+$'))
         OR (n.g12_gas_male <> '' AND NOT regexp_like(n.g12_gas_male, '^[0-9]{1,9}$') AND NOT regexp_like(n.g12_gas_male, '^-[0-9]+$'))
         OR (n.g12_gas_female <> '' AND NOT regexp_like(n.g12_gas_female, '^[0-9]{1,9}$') AND NOT regexp_like(n.g12_gas_female, '^-[0-9]+$'))
         OR (n.g12_humss_male <> '' AND NOT regexp_like(n.g12_humss_male, '^[0-9]{1,9}$') AND NOT regexp_like(n.g12_humss_male, '^-[0-9]+$'))
         OR (n.g12_humss_female <> '' AND NOT regexp_like(n.g12_humss_female, '^[0-9]{1,9}$') AND NOT regexp_like(n.g12_humss_female, '^-[0-9]+$'))
         OR (n.g12_maritime_male <> '' AND NOT regexp_like(n.g12_maritime_male, '^[0-9]{1,9}$') AND NOT regexp_like(n.g12_maritime_male, '^-[0-9]+$'))
         OR (n.g12_maritime_female <> '' AND NOT regexp_like(n.g12_maritime_female, '^[0-9]{1,9}$') AND NOT regexp_like(n.g12_maritime_female, '^-[0-9]+$'))
         OR (n.g12_sports_male <> '' AND NOT regexp_like(n.g12_sports_male, '^[0-9]{1,9}$') AND NOT regexp_like(n.g12_sports_male, '^-[0-9]+$'))
         OR (n.g12_sports_female <> '' AND NOT regexp_like(n.g12_sports_female, '^[0-9]{1,9}$') AND NOT regexp_like(n.g12_sports_female, '^-[0-9]+$'))
         OR (n.g12_stem_male <> '' AND NOT regexp_like(n.g12_stem_male, '^[0-9]{1,9}$') AND NOT regexp_like(n.g12_stem_male, '^-[0-9]+$'))
         OR (n.g12_stem_female <> '' AND NOT regexp_like(n.g12_stem_female, '^[0-9]{1,9}$') AND NOT regexp_like(n.g12_stem_female, '^-[0-9]+$'))
         OR (n.g12_tvl_male <> '' AND NOT regexp_like(n.g12_tvl_male, '^[0-9]{1,9}$') AND NOT regexp_like(n.g12_tvl_male, '^-[0-9]+$'))
         OR (n.g12_tvl_female <> '' AND NOT regexp_like(n.g12_tvl_female, '^[0-9]{1,9}$') AND NOT regexp_like(n.g12_tvl_female, '^-[0-9]+$'))
         OR (n.g12_unique_male <> '' AND NOT regexp_like(n.g12_unique_male, '^[0-9]{1,9}$') AND NOT regexp_like(n.g12_unique_male, '^-[0-9]+$'))
         OR (n.g12_unique_female <> '' AND NOT regexp_like(n.g12_unique_female, '^[0-9]{1,9}$') AND NOT regexp_like(n.g12_unique_female, '^-[0-9]+$'))
         OR (n.g11_sshs_acad_male <> '' AND NOT regexp_like(n.g11_sshs_acad_male, '^[0-9]{1,9}$') AND NOT regexp_like(n.g11_sshs_acad_male, '^-[0-9]+$'))
         OR (n.g11_sshs_acad_female <> '' AND NOT regexp_like(n.g11_sshs_acad_female, '^[0-9]{1,9}$') AND NOT regexp_like(n.g11_sshs_acad_female, '^-[0-9]+$'))
         OR (n.g11_sshs_techpro_male <> '' AND NOT regexp_like(n.g11_sshs_techpro_male, '^[0-9]{1,9}$') AND NOT regexp_like(n.g11_sshs_techpro_male, '^-[0-9]+$'))
         OR (n.g11_sshs_techpro_female <> '' AND NOT regexp_like(n.g11_sshs_techpro_female, '^[0-9]{1,9}$') AND NOT regexp_like(n.g11_sshs_techpro_female, '^-[0-9]+$'))
      THEN 'count_uncastable' END,
      CASE WHEN CASE WHEN regexp_like(n.kinder_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.kinder_male AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.kinder_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.kinder_female AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g1_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g1_male AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g1_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g1_female AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g2_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g2_male AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g2_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g2_female AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g3_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g3_male AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g3_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g3_female AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g4_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g4_male AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g4_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g4_female AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g5_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g5_male AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g5_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g5_female AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g6_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g6_male AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g6_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g6_female AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.esng_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.esng_male AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.esng_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.esng_female AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g7_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g7_male AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g7_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g7_female AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g8_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g8_male AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g8_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g8_female AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g9_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g9_male AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g9_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g9_female AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g10_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g10_male AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g10_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g10_female AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.jhsng_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.jhsng_male AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.jhsng_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.jhsng_female AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g11_abm_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g11_abm_male AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g11_abm_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g11_abm_female AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g11_arts_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g11_arts_male AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g11_arts_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g11_arts_female AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g11_gas_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g11_gas_male AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g11_gas_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g11_gas_female AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g11_humss_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g11_humss_male AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g11_humss_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g11_humss_female AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g11_maritime_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g11_maritime_male AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g11_maritime_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g11_maritime_female AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g11_sports_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g11_sports_male AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g11_sports_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g11_sports_female AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g11_stem_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g11_stem_male AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g11_stem_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g11_stem_female AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g11_tvl_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g11_tvl_male AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g11_tvl_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g11_tvl_female AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g11_unique_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g11_unique_male AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g11_unique_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g11_unique_female AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g12_abm_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g12_abm_male AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g12_abm_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g12_abm_female AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g12_arts_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g12_arts_male AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g12_arts_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g12_arts_female AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g12_gas_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g12_gas_male AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g12_gas_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g12_gas_female AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g12_humss_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g12_humss_male AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g12_humss_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g12_humss_female AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g12_maritime_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g12_maritime_male AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g12_maritime_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g12_maritime_female AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g12_sports_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g12_sports_male AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g12_sports_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g12_sports_female AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g12_stem_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g12_stem_male AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g12_stem_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g12_stem_female AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g12_tvl_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g12_tvl_male AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g12_tvl_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g12_tvl_female AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g12_unique_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g12_unique_male AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g12_unique_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g12_unique_female AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g11_sshs_acad_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g11_sshs_acad_male AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g11_sshs_acad_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g11_sshs_acad_female AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g11_sshs_techpro_male, '^[0-9]{1,9}$') THEN TRY_CAST(n.g11_sshs_techpro_male AS BIGINT) END > 10000
         OR CASE WHEN regexp_like(n.g11_sshs_techpro_female, '^[0-9]{1,9}$') THEN TRY_CAST(n.g11_sshs_techpro_female AS BIGINT) END > 10000
      THEN 'count_above_plausible_max' END
    ) AS quarantine_reasons,
    n.batch_id,
    n.delivery_version,
    n.schema_version,
    n.source_sha256,
    n.source_row_number
  FROM normalized AS n
)
SELECT
  t.school_year,
  t.school_id,
  t.school_name,
  t.region,
  t.division,
  t.province,
  t.school_district,
  t.legislative_district,
  t.municipality,
  t.barangay,
  t.street_address,
  t.sector,
  t.school_management,
  t.annex_status,
  t.offers_es,
  t.offers_jhs,
  t.offers_shs,
  t.modified_curricular_offering_classification,
  t.kinder_male,
  t.kinder_female,
  t.g1_male,
  t.g1_female,
  t.g2_male,
  t.g2_female,
  t.g3_male,
  t.g3_female,
  t.g4_male,
  t.g4_female,
  t.g5_male,
  t.g5_female,
  t.g6_male,
  t.g6_female,
  t.esng_male,
  t.esng_female,
  t.g7_male,
  t.g7_female,
  t.g8_male,
  t.g8_female,
  t.g9_male,
  t.g9_female,
  t.g10_male,
  t.g10_female,
  t.jhsng_male,
  t.jhsng_female,
  t.g11_abm_male,
  t.g11_abm_female,
  t.g11_arts_male,
  t.g11_arts_female,
  t.g11_gas_male,
  t.g11_gas_female,
  t.g11_humss_male,
  t.g11_humss_female,
  t.g11_maritime_male,
  t.g11_maritime_female,
  t.g11_sports_male,
  t.g11_sports_female,
  t.g11_stem_male,
  t.g11_stem_female,
  t.g11_tvl_male,
  t.g11_tvl_female,
  t.g11_unique_male,
  t.g11_unique_female,
  t.g12_abm_male,
  t.g12_abm_female,
  t.g12_arts_male,
  t.g12_arts_female,
  t.g12_gas_male,
  t.g12_gas_female,
  t.g12_humss_male,
  t.g12_humss_female,
  t.g12_maritime_male,
  t.g12_maritime_female,
  t.g12_sports_male,
  t.g12_sports_female,
  t.g12_stem_male,
  t.g12_stem_female,
  t.g12_tvl_male,
  t.g12_tvl_female,
  t.g12_unique_male,
  t.g12_unique_female,
  t.g11_sshs_acad_male,
  t.g11_sshs_acad_female,
  t.g11_sshs_techpro_male,
  t.g11_sshs_techpro_female,
  COALESCE(t.sector = 'PSO' OR t.region = 'PSO' OR t.school_management = 'PSO', FALSE) AS is_overseas,
  CASE WHEN COALESCE(
            t.kinder_male,
            t.kinder_female,
            t.g1_male,
            t.g1_female,
            t.g2_male,
            t.g2_female,
            t.g3_male,
            t.g3_female,
            t.g4_male,
            t.g4_female,
            t.g5_male,
            t.g5_female,
            t.g6_male,
            t.g6_female,
            t.esng_male,
            t.esng_female,
            t.g7_male,
            t.g7_female,
            t.g8_male,
            t.g8_female,
            t.g9_male,
            t.g9_female,
            t.g10_male,
            t.g10_female,
            t.jhsng_male,
            t.jhsng_female,
            t.g11_abm_male,
            t.g11_abm_female,
            t.g11_arts_male,
            t.g11_arts_female,
            t.g11_gas_male,
            t.g11_gas_female,
            t.g11_humss_male,
            t.g11_humss_female,
            t.g11_maritime_male,
            t.g11_maritime_female,
            t.g11_sports_male,
            t.g11_sports_female,
            t.g11_stem_male,
            t.g11_stem_female,
            t.g11_tvl_male,
            t.g11_tvl_female,
            t.g11_unique_male,
            t.g11_unique_female,
            t.g12_abm_male,
            t.g12_abm_female,
            t.g12_arts_male,
            t.g12_arts_female,
            t.g12_gas_male,
            t.g12_gas_female,
            t.g12_humss_male,
            t.g12_humss_female,
            t.g12_maritime_male,
            t.g12_maritime_female,
            t.g12_sports_male,
            t.g12_sports_female,
            t.g12_stem_male,
            t.g12_stem_female,
            t.g12_tvl_male,
            t.g12_tvl_female,
            t.g12_unique_male,
            t.g12_unique_female,
            t.g11_sshs_acad_male,
            t.g11_sshs_acad_female,
            t.g11_sshs_techpro_male,
            t.g11_sshs_techpro_female
         ) IS NULL THEN 'no_counts'
       WHEN COALESCE(CAST(t.kinder_male AS BIGINT), 0)
            + COALESCE(CAST(t.kinder_female AS BIGINT), 0)
            + COALESCE(CAST(t.g1_male AS BIGINT), 0)
            + COALESCE(CAST(t.g1_female AS BIGINT), 0)
            + COALESCE(CAST(t.g2_male AS BIGINT), 0)
            + COALESCE(CAST(t.g2_female AS BIGINT), 0)
            + COALESCE(CAST(t.g3_male AS BIGINT), 0)
            + COALESCE(CAST(t.g3_female AS BIGINT), 0)
            + COALESCE(CAST(t.g4_male AS BIGINT), 0)
            + COALESCE(CAST(t.g4_female AS BIGINT), 0)
            + COALESCE(CAST(t.g5_male AS BIGINT), 0)
            + COALESCE(CAST(t.g5_female AS BIGINT), 0)
            + COALESCE(CAST(t.g6_male AS BIGINT), 0)
            + COALESCE(CAST(t.g6_female AS BIGINT), 0)
            + COALESCE(CAST(t.esng_male AS BIGINT), 0)
            + COALESCE(CAST(t.esng_female AS BIGINT), 0)
            + COALESCE(CAST(t.g7_male AS BIGINT), 0)
            + COALESCE(CAST(t.g7_female AS BIGINT), 0)
            + COALESCE(CAST(t.g8_male AS BIGINT), 0)
            + COALESCE(CAST(t.g8_female AS BIGINT), 0)
            + COALESCE(CAST(t.g9_male AS BIGINT), 0)
            + COALESCE(CAST(t.g9_female AS BIGINT), 0)
            + COALESCE(CAST(t.g10_male AS BIGINT), 0)
            + COALESCE(CAST(t.g10_female AS BIGINT), 0)
            + COALESCE(CAST(t.jhsng_male AS BIGINT), 0)
            + COALESCE(CAST(t.jhsng_female AS BIGINT), 0)
            + COALESCE(CAST(t.g11_abm_male AS BIGINT), 0)
            + COALESCE(CAST(t.g11_abm_female AS BIGINT), 0)
            + COALESCE(CAST(t.g11_arts_male AS BIGINT), 0)
            + COALESCE(CAST(t.g11_arts_female AS BIGINT), 0)
            + COALESCE(CAST(t.g11_gas_male AS BIGINT), 0)
            + COALESCE(CAST(t.g11_gas_female AS BIGINT), 0)
            + COALESCE(CAST(t.g11_humss_male AS BIGINT), 0)
            + COALESCE(CAST(t.g11_humss_female AS BIGINT), 0)
            + COALESCE(CAST(t.g11_maritime_male AS BIGINT), 0)
            + COALESCE(CAST(t.g11_maritime_female AS BIGINT), 0)
            + COALESCE(CAST(t.g11_sports_male AS BIGINT), 0)
            + COALESCE(CAST(t.g11_sports_female AS BIGINT), 0)
            + COALESCE(CAST(t.g11_stem_male AS BIGINT), 0)
            + COALESCE(CAST(t.g11_stem_female AS BIGINT), 0)
            + COALESCE(CAST(t.g11_tvl_male AS BIGINT), 0)
            + COALESCE(CAST(t.g11_tvl_female AS BIGINT), 0)
            + COALESCE(CAST(t.g11_unique_male AS BIGINT), 0)
            + COALESCE(CAST(t.g11_unique_female AS BIGINT), 0)
            + COALESCE(CAST(t.g12_abm_male AS BIGINT), 0)
            + COALESCE(CAST(t.g12_abm_female AS BIGINT), 0)
            + COALESCE(CAST(t.g12_arts_male AS BIGINT), 0)
            + COALESCE(CAST(t.g12_arts_female AS BIGINT), 0)
            + COALESCE(CAST(t.g12_gas_male AS BIGINT), 0)
            + COALESCE(CAST(t.g12_gas_female AS BIGINT), 0)
            + COALESCE(CAST(t.g12_humss_male AS BIGINT), 0)
            + COALESCE(CAST(t.g12_humss_female AS BIGINT), 0)
            + COALESCE(CAST(t.g12_maritime_male AS BIGINT), 0)
            + COALESCE(CAST(t.g12_maritime_female AS BIGINT), 0)
            + COALESCE(CAST(t.g12_sports_male AS BIGINT), 0)
            + COALESCE(CAST(t.g12_sports_female AS BIGINT), 0)
            + COALESCE(CAST(t.g12_stem_male AS BIGINT), 0)
            + COALESCE(CAST(t.g12_stem_female AS BIGINT), 0)
            + COALESCE(CAST(t.g12_tvl_male AS BIGINT), 0)
            + COALESCE(CAST(t.g12_tvl_female AS BIGINT), 0)
            + COALESCE(CAST(t.g12_unique_male AS BIGINT), 0)
            + COALESCE(CAST(t.g12_unique_female AS BIGINT), 0)
            + COALESCE(CAST(t.g11_sshs_acad_male AS BIGINT), 0)
            + COALESCE(CAST(t.g11_sshs_acad_female AS BIGINT), 0)
            + COALESCE(CAST(t.g11_sshs_techpro_male AS BIGINT), 0)
            + COALESCE(CAST(t.g11_sshs_techpro_female AS BIGINT), 0) = 0 THEN 'all_zero'
       ELSE 'has_learners' END AS enrollment_status,
  t.barangay_possibly_truncated,
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

-- One row per school per school year, with the Bronze row it came from.
CREATE OR REPLACE TABLE edu_access.`03-silver`.deped_enrollment_clean_candidate USING DELTA AS
SELECT
  school_year,
  school_id,
  school_name,
  region,
  division,
  province,
  school_district,
  legislative_district,
  municipality,
  barangay,
  street_address,
  sector,
  school_management,
  annex_status,
  offers_es,
  offers_jhs,
  offers_shs,
  modified_curricular_offering_classification,
  kinder_male,
  kinder_female,
  g1_male,
  g1_female,
  g2_male,
  g2_female,
  g3_male,
  g3_female,
  g4_male,
  g4_female,
  g5_male,
  g5_female,
  g6_male,
  g6_female,
  esng_male,
  esng_female,
  g7_male,
  g7_female,
  g8_male,
  g8_female,
  g9_male,
  g9_female,
  g10_male,
  g10_female,
  jhsng_male,
  jhsng_female,
  g11_abm_male,
  g11_abm_female,
  g11_arts_male,
  g11_arts_female,
  g11_gas_male,
  g11_gas_female,
  g11_humss_male,
  g11_humss_female,
  g11_maritime_male,
  g11_maritime_female,
  g11_sports_male,
  g11_sports_female,
  g11_stem_male,
  g11_stem_female,
  g11_tvl_male,
  g11_tvl_female,
  g11_unique_male,
  g11_unique_female,
  g12_abm_male,
  g12_abm_female,
  g12_arts_male,
  g12_arts_female,
  g12_gas_male,
  g12_gas_female,
  g12_humss_male,
  g12_humss_female,
  g12_maritime_male,
  g12_maritime_female,
  g12_sports_male,
  g12_sports_female,
  g12_stem_male,
  g12_stem_female,
  g12_tvl_male,
  g12_tvl_female,
  g12_unique_male,
  g12_unique_female,
  g11_sshs_acad_male,
  g11_sshs_acad_female,
  g11_sshs_techpro_male,
  g11_sshs_techpro_female,
  is_overseas,
  enrollment_status,
  barangay_possibly_truncated,
  batch_id,
  delivery_version,
  schema_version,
  source_sha256,
  source_row_number,
  run_id,
  cleaned_at_utc,
  code_revision
FROM deped_enrollment_classified
WHERE quarantine_reasons = '';

COMMENT ON TABLE edu_access.`03-silver`.deped_enrollment_clean_candidate IS 'Unpublished build for the Silver gate, which may have failed. Do not read: use deped_enrollment_clean, trusted by the run its rows carry (D-025).';
ALTER TABLE edu_access.`03-silver`.deped_enrollment_clean_candidate OWNER TO `reached-hq`;

-- Rows set aside, never deleted: the Bronze row, and why.
CREATE OR REPLACE TABLE edu_access.`03-silver`.deped_enrollment_quarantine_candidate USING DELTA AS
SELECT
  school_year,
  school_id,
  split(quarantine_reasons, ',') AS quarantine_reasons,
  batch_id,
  delivery_version,
  schema_version,
  source_sha256,
  source_row_number,
  run_id,
  cleaned_at_utc,
  code_revision
FROM deped_enrollment_classified
WHERE quarantine_reasons <> '';

COMMENT ON TABLE edu_access.`03-silver`.deped_enrollment_quarantine_candidate IS 'Unpublished build for the Silver gate, which may have failed. Do not read: use deped_enrollment_quarantine, trusted by the run its rows carry (D-025).';
ALTER TABLE edu_access.`03-silver`.deped_enrollment_quarantine_candidate OWNER TO `reached-hq`;
