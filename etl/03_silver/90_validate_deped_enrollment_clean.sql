-- Silver gate for deped_enrollment. Generated from config/ingestion/deped_enrollment.json
-- and config/mappings/deped_enrollment.json:
--   python -m src.silver.cli gate --source deped_enrollment > etl/03_silver/90_validate_deped_enrollment_clean.sql
-- Do not edit by hand; tests/test_silver.py fails if it differs.
--
-- The job task after the Silver build. It checks the candidate tables the build wrote, one row
-- per check in data_quality_results. On any FAIL it records the run 'failed' and stops the task
-- before publishing, so the Silver tables keep the last build that passed and nothing downstream
-- runs. Otherwise it copies the candidates to the Silver tables and records the run 'succeeded'.
-- PASS: as expected. WARN: recorded, the build is published (quarantined rows exist).
-- FAIL: the candidate cannot be trusted and is not published. Results hold counts, never row values.
--
-- Parameters, supplied by the job (or src/job/local_run.py):
--   :run_id         the job run that built the tables
--   :code_revision  the commit that ran, from the job parameter; never a literal

-- Only this execution's results decide: a repaired job run keeps its run_id, and the
-- results of an earlier attempt must not fail it again.
DECLARE OR REPLACE VARIABLE silver_gate_started_at_utc TIMESTAMP;
SET VARIABLE silver_gate_started_at_utc = current_timestamp();

INSERT INTO edu_access.`01-control`.data_quality_results
  (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, batch_id, 'deped_enrollment', 'silver', table_name, check_name, status, expected, actual,
       current_timestamp(), :code_revision
FROM (
WITH cur AS (
  SELECT batch_id, school_year FROM edu_access.`01-control`.current_batches WHERE source_id = 'deped_enrollment'
),
bronze AS (
  SELECT r.* FROM edu_access.`02-bronze`.deped_enrollment_raw AS r JOIN cur ON r.batch_id = cur.batch_id
),
clean AS (SELECT * FROM edu_access.`03-silver`.deped_enrollment_clean_candidate),
quarantined AS (SELECT * FROM edu_access.`03-silver`.deped_enrollment_quarantine_candidate),
-- Current Bronze rows, each marked if Silver set it aside.
b AS (
  SELECT bronze.*, q.source_row_number IS NOT NULL AS in_quarantine
  FROM bronze
  LEFT JOIN quarantined AS q
    ON bronze.source_sha256 = q.source_sha256 AND bronze.source_row_number = q.source_row_number
),
-- A quarantined row has no clean value, so its labels are checked against the reviewed mapping here:
-- a row set aside for another reason must not let an unmapped label through.
bronze_years AS (
  SELECT
    b.school_year,
    COUNT(*) AS bronze_rows,
    COUNT_IF(NOT b.in_quarantine) AS kept_rows,
    SUM(CASE WHEN b.in_quarantine THEN 0 ELSE
        COALESCE(CASE WHEN regexp_like(b.`kinder_male`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`kinder_male` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`kinder_female`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`kinder_female` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g1_male`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g1_male` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g1_female`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g1_female` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g2_male`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g2_male` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g2_female`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g2_female` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g3_male`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g3_male` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g3_female`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g3_female` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g4_male`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g4_male` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g4_female`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g4_female` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g5_male`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g5_male` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g5_female`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g5_female` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g6_male`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g6_male` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g6_female`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g6_female` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`esng_male`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`esng_male` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`esng_female`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`esng_female` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g7_male`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g7_male` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g7_female`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g7_female` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g8_male`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g8_male` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g8_female`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g8_female` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g9_male`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g9_male` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g9_female`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g9_female` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g10_male`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g10_male` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g10_female`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g10_female` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`jhsng_male`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`jhsng_male` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`jhsng_female`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`jhsng_female` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g11_abm_male`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g11_abm_male` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g11_abm_female`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g11_abm_female` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g11_arts_male`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g11_arts_male` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g11_arts_female`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g11_arts_female` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g11_gas_male`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g11_gas_male` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g11_gas_female`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g11_gas_female` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g11_humss_male`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g11_humss_male` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g11_humss_female`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g11_humss_female` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g11_maritime_male`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g11_maritime_male` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g11_maritime_female`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g11_maritime_female` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g11_sports_male`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g11_sports_male` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g11_sports_female`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g11_sports_female` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g11_stem_male`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g11_stem_male` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g11_stem_female`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g11_stem_female` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g11_tvl_male`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g11_tvl_male` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g11_tvl_female`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g11_tvl_female` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g11_unique_male`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g11_unique_male` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g11_unique_female`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g11_unique_female` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g12_abm_male`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g12_abm_male` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g12_abm_female`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g12_abm_female` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g12_arts_male`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g12_arts_male` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g12_arts_female`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g12_arts_female` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g12_gas_male`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g12_gas_male` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g12_gas_female`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g12_gas_female` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g12_humss_male`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g12_humss_male` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g12_humss_female`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g12_humss_female` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g12_maritime_male`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g12_maritime_male` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g12_maritime_female`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g12_maritime_female` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g12_sports_male`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g12_sports_male` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g12_sports_female`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g12_sports_female` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g12_stem_male`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g12_stem_male` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g12_stem_female`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g12_stem_female` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g12_tvl_male`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g12_tvl_male` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g12_tvl_female`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g12_tvl_female` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g12_unique_male`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g12_unique_male` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g12_unique_female`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g12_unique_female` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g11_sshs_acad_male`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g11_sshs_acad_male` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g11_sshs_acad_female`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g11_sshs_acad_female` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g11_sshs_techpro_male`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g11_sshs_techpro_male` AS BIGINT) END, 0) + COALESCE(CASE WHEN regexp_like(b.`g11_sshs_techpro_female`, '^[0-9]{1,9}$') THEN TRY_CAST(b.`g11_sshs_techpro_female` AS BIGINT) END, 0)
      END) AS kept_learners,
    SUM(CASE WHEN b.in_quarantine THEN 0 ELSE
        CASE WHEN b.`kinder_male` IS NULL OR b.`kinder_male` = '' THEN 1 ELSE 0 END + CASE WHEN b.`kinder_female` IS NULL OR b.`kinder_female` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g1_male` IS NULL OR b.`g1_male` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g1_female` IS NULL OR b.`g1_female` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g2_male` IS NULL OR b.`g2_male` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g2_female` IS NULL OR b.`g2_female` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g3_male` IS NULL OR b.`g3_male` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g3_female` IS NULL OR b.`g3_female` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g4_male` IS NULL OR b.`g4_male` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g4_female` IS NULL OR b.`g4_female` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g5_male` IS NULL OR b.`g5_male` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g5_female` IS NULL OR b.`g5_female` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g6_male` IS NULL OR b.`g6_male` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g6_female` IS NULL OR b.`g6_female` = '' THEN 1 ELSE 0 END + CASE WHEN b.`esng_male` IS NULL OR b.`esng_male` = '' THEN 1 ELSE 0 END + CASE WHEN b.`esng_female` IS NULL OR b.`esng_female` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g7_male` IS NULL OR b.`g7_male` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g7_female` IS NULL OR b.`g7_female` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g8_male` IS NULL OR b.`g8_male` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g8_female` IS NULL OR b.`g8_female` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g9_male` IS NULL OR b.`g9_male` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g9_female` IS NULL OR b.`g9_female` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g10_male` IS NULL OR b.`g10_male` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g10_female` IS NULL OR b.`g10_female` = '' THEN 1 ELSE 0 END + CASE WHEN b.`jhsng_male` IS NULL OR b.`jhsng_male` = '' THEN 1 ELSE 0 END + CASE WHEN b.`jhsng_female` IS NULL OR b.`jhsng_female` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g11_abm_male` IS NULL OR b.`g11_abm_male` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g11_abm_female` IS NULL OR b.`g11_abm_female` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g11_arts_male` IS NULL OR b.`g11_arts_male` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g11_arts_female` IS NULL OR b.`g11_arts_female` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g11_gas_male` IS NULL OR b.`g11_gas_male` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g11_gas_female` IS NULL OR b.`g11_gas_female` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g11_humss_male` IS NULL OR b.`g11_humss_male` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g11_humss_female` IS NULL OR b.`g11_humss_female` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g11_maritime_male` IS NULL OR b.`g11_maritime_male` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g11_maritime_female` IS NULL OR b.`g11_maritime_female` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g11_sports_male` IS NULL OR b.`g11_sports_male` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g11_sports_female` IS NULL OR b.`g11_sports_female` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g11_stem_male` IS NULL OR b.`g11_stem_male` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g11_stem_female` IS NULL OR b.`g11_stem_female` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g11_tvl_male` IS NULL OR b.`g11_tvl_male` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g11_tvl_female` IS NULL OR b.`g11_tvl_female` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g11_unique_male` IS NULL OR b.`g11_unique_male` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g11_unique_female` IS NULL OR b.`g11_unique_female` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g12_abm_male` IS NULL OR b.`g12_abm_male` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g12_abm_female` IS NULL OR b.`g12_abm_female` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g12_arts_male` IS NULL OR b.`g12_arts_male` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g12_arts_female` IS NULL OR b.`g12_arts_female` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g12_gas_male` IS NULL OR b.`g12_gas_male` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g12_gas_female` IS NULL OR b.`g12_gas_female` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g12_humss_male` IS NULL OR b.`g12_humss_male` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g12_humss_female` IS NULL OR b.`g12_humss_female` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g12_maritime_male` IS NULL OR b.`g12_maritime_male` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g12_maritime_female` IS NULL OR b.`g12_maritime_female` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g12_sports_male` IS NULL OR b.`g12_sports_male` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g12_sports_female` IS NULL OR b.`g12_sports_female` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g12_stem_male` IS NULL OR b.`g12_stem_male` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g12_stem_female` IS NULL OR b.`g12_stem_female` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g12_tvl_male` IS NULL OR b.`g12_tvl_male` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g12_tvl_female` IS NULL OR b.`g12_tvl_female` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g12_unique_male` IS NULL OR b.`g12_unique_male` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g12_unique_female` IS NULL OR b.`g12_unique_female` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g11_sshs_acad_male` IS NULL OR b.`g11_sshs_acad_male` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g11_sshs_acad_female` IS NULL OR b.`g11_sshs_acad_female` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g11_sshs_techpro_male` IS NULL OR b.`g11_sshs_techpro_male` = '' THEN 1 ELSE 0 END + CASE WHEN b.`g11_sshs_techpro_female` IS NULL OR b.`g11_sshs_techpro_female` = '' THEN 1 ELSE 0 END
      END) AS kept_missing_counts,
    COUNT_IF(
        TRIM(regexp_replace(translate(b.`school_name`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`school_name`
        OR TRIM(regexp_replace(translate(b.`region`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`region`
        OR TRIM(regexp_replace(translate(b.`division`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`division`
        OR TRIM(regexp_replace(translate(b.`province`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`province`
        OR TRIM(regexp_replace(translate(b.`school_district`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`school_district`
        OR TRIM(regexp_replace(translate(b.`legislative_district`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`legislative_district`
        OR TRIM(regexp_replace(translate(b.`municipality`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`municipality`
        OR TRIM(regexp_replace(translate(b.`barangay`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`barangay`
        OR TRIM(regexp_replace(translate(b.`street_address`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`street_address`
        OR TRIM(regexp_replace(translate(b.`sector`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`sector`
        OR TRIM(regexp_replace(translate(b.`school_management`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`school_management`
        OR TRIM(regexp_replace(translate(b.`annex_status`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`annex_status`
        OR TRIM(regexp_replace(translate(b.`offers_es`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`offers_es`
        OR TRIM(regexp_replace(translate(b.`offers_jhs`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`offers_jhs`
        OR TRIM(regexp_replace(translate(b.`offers_shs`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`offers_shs`
        OR TRIM(regexp_replace(translate(b.`Modified Curricular Offering Classification`, chr(9) || chr(160), '  '), ' +', ' ')) <> b.`Modified Curricular Offering Classification`
      ) AS whitespace_rows,
    COUNT_IF(
        replace(replace(b.`school_name`, 'Ã‘', 'Ñ'), 'Ã±', 'ñ') <> b.`school_name`
        OR replace(replace(b.`division`, 'Ã‘', 'Ñ'), 'Ã±', 'ñ') <> b.`division`
        OR replace(replace(b.`province`, 'Ã‘', 'Ñ'), 'Ã±', 'ñ') <> b.`province`
        OR replace(replace(b.`school_district`, 'Ã‘', 'Ñ'), 'Ã±', 'ñ') <> b.`school_district`
        OR replace(replace(b.`municipality`, 'Ã‘', 'Ñ'), 'Ã±', 'ñ') <> b.`municipality`
        OR replace(replace(b.`barangay`, 'Ã‘', 'Ñ'), 'Ã±', 'ñ') <> b.`barangay`
        OR replace(replace(b.`street_address`, 'Ã‘', 'Ñ'), 'Ã±', 'ñ') <> b.`street_address`
      ) AS repaired_rows,
    COUNT_IF(
        TRIM(regexp_replace(translate(b.`school_name`, chr(9) || chr(160), '  '), ' +', ' ')) = ''
        OR TRIM(regexp_replace(translate(b.`region`, chr(9) || chr(160), '  '), ' +', ' ')) = ''
        OR TRIM(regexp_replace(translate(b.`division`, chr(9) || chr(160), '  '), ' +', ' ')) = ''
        OR TRIM(regexp_replace(translate(b.`province`, chr(9) || chr(160), '  '), ' +', ' ')) = ''
        OR TRIM(regexp_replace(translate(b.`school_district`, chr(9) || chr(160), '  '), ' +', ' ')) = ''
        OR TRIM(regexp_replace(translate(b.`legislative_district`, chr(9) || chr(160), '  '), ' +', ' ')) = ''
        OR TRIM(regexp_replace(translate(b.`municipality`, chr(9) || chr(160), '  '), ' +', ' ')) = ''
        OR TRIM(regexp_replace(translate(b.`barangay`, chr(9) || chr(160), '  '), ' +', ' ')) = ''
        OR TRIM(regexp_replace(translate(b.`street_address`, chr(9) || chr(160), '  '), ' +', ' ')) = ''
        OR TRIM(regexp_replace(translate(b.`sector`, chr(9) || chr(160), '  '), ' +', ' ')) = ''
        OR TRIM(regexp_replace(translate(b.`school_management`, chr(9) || chr(160), '  '), ' +', ' ')) = ''
        OR TRIM(regexp_replace(translate(b.`annex_status`, chr(9) || chr(160), '  '), ' +', ' ')) = ''
        OR TRIM(regexp_replace(translate(b.`offers_es`, chr(9) || chr(160), '  '), ' +', ' ')) = ''
        OR TRIM(regexp_replace(translate(b.`offers_jhs`, chr(9) || chr(160), '  '), ' +', ' ')) = ''
        OR TRIM(regexp_replace(translate(b.`offers_shs`, chr(9) || chr(160), '  '), ' +', ' ')) = ''
        OR TRIM(regexp_replace(translate(b.`Modified Curricular Offering Classification`, chr(9) || chr(160), '  '), ' +', ' ')) = ''
      ) AS blank_text_rows,
    COUNT_IF(
        TRIM(regexp_replace(translate(replace(replace(b.`street_address`, 'Ã‘', 'Ñ'), 'Ã±', 'ñ'), chr(9) || chr(160), '  '), ' +', ' ')) IN ('-', 'n/a', 'N/A')
      ) AS placeholder_rows,
    COUNT_IF(
        b.`kinder_male` = ''
        OR b.`kinder_female` = ''
        OR b.`g1_male` = ''
        OR b.`g1_female` = ''
        OR b.`g2_male` = ''
        OR b.`g2_female` = ''
        OR b.`g3_male` = ''
        OR b.`g3_female` = ''
        OR b.`g4_male` = ''
        OR b.`g4_female` = ''
        OR b.`g5_male` = ''
        OR b.`g5_female` = ''
        OR b.`g6_male` = ''
        OR b.`g6_female` = ''
        OR b.`esng_male` = ''
        OR b.`esng_female` = ''
        OR b.`g7_male` = ''
        OR b.`g7_female` = ''
        OR b.`g8_male` = ''
        OR b.`g8_female` = ''
        OR b.`g9_male` = ''
        OR b.`g9_female` = ''
        OR b.`g10_male` = ''
        OR b.`g10_female` = ''
        OR b.`jhsng_male` = ''
        OR b.`jhsng_female` = ''
        OR b.`g11_abm_male` = ''
        OR b.`g11_abm_female` = ''
        OR b.`g11_arts_male` = ''
        OR b.`g11_arts_female` = ''
        OR b.`g11_gas_male` = ''
        OR b.`g11_gas_female` = ''
        OR b.`g11_humss_male` = ''
        OR b.`g11_humss_female` = ''
        OR b.`g11_maritime_male` = ''
        OR b.`g11_maritime_female` = ''
        OR b.`g11_sports_male` = ''
        OR b.`g11_sports_female` = ''
        OR b.`g11_stem_male` = ''
        OR b.`g11_stem_female` = ''
        OR b.`g11_tvl_male` = ''
        OR b.`g11_tvl_female` = ''
        OR b.`g11_unique_male` = ''
        OR b.`g11_unique_female` = ''
        OR b.`g12_abm_male` = ''
        OR b.`g12_abm_female` = ''
        OR b.`g12_arts_male` = ''
        OR b.`g12_arts_female` = ''
        OR b.`g12_gas_male` = ''
        OR b.`g12_gas_female` = ''
        OR b.`g12_humss_male` = ''
        OR b.`g12_humss_female` = ''
        OR b.`g12_maritime_male` = ''
        OR b.`g12_maritime_female` = ''
        OR b.`g12_sports_male` = ''
        OR b.`g12_sports_female` = ''
        OR b.`g12_stem_male` = ''
        OR b.`g12_stem_female` = ''
        OR b.`g12_tvl_male` = ''
        OR b.`g12_tvl_female` = ''
        OR b.`g12_unique_male` = ''
        OR b.`g12_unique_female` = ''
        OR b.`g11_sshs_acad_male` = ''
        OR b.`g11_sshs_acad_female` = ''
        OR b.`g11_sshs_techpro_male` = ''
        OR b.`g11_sshs_techpro_female` = ''
      ) AS blank_count_rows,
    COUNT_IF(b.schema_version = 'v1') AS absent_column_rows,
    COUNT_IF(b.in_quarantine AND TRIM(regexp_replace(translate(b.`region`, chr(9) || chr(160), '  '), ' +', ' ')) <> ''
        AND TRIM(regexp_replace(translate(b.`region`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('NCR', 'CAR', 'Region I', 'Region II', 'Region III', 'Region IV-A', 'MIMAROPA', 'Region V', 'Region VI', 'NIR', 'Region VII', 'Region VIII', 'Region IX', 'Region X', 'Region XI', 'Region XII', 'CARAGA', 'BARMM', 'PSO')) AS quarantined_unmapped_region,
    COUNT_IF(b.in_quarantine AND TRIM(regexp_replace(translate(b.`legislative_district`, chr(9) || chr(160), '  '), ' +', ' ')) <> ''
        AND TRIM(regexp_replace(translate(b.`legislative_district`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('1st District', '2nd District', '3rd District', '4th District', '5th District', '6th District', '7th District', 'Lone District', 'No Legislative District', 'PSO')) AS quarantined_unmapped_legislative_district,
    COUNT_IF(b.in_quarantine AND TRIM(regexp_replace(translate(b.`sector`, chr(9) || chr(160), '  '), ' +', ' ')) <> ''
        AND TRIM(regexp_replace(translate(b.`sector`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('Public', 'Private', 'SUC/LUC', 'SUCsLUCs', 'PSO')) AS quarantined_unmapped_sector,
    COUNT_IF(b.in_quarantine AND TRIM(regexp_replace(translate(b.`school_management`, chr(9) || chr(160), '  '), ' +', ' ')) <> ''
        AND TRIM(regexp_replace(translate(b.`school_management`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('DepEd', 'DepED Managed', 'Non-Sectarian', 'Sectarian', 'SUC', 'SUC Managed', 'LUC', 'Local Government', 'DOST', 'DOST Managed', 'Other GA', 'Other GA Managed', 'International School', 'Local International School', 'PSO', 'SCHOOL ABROAD')) AS quarantined_unmapped_school_management,
    COUNT_IF(b.in_quarantine AND TRIM(regexp_replace(translate(b.`annex_status`, chr(9) || chr(160), '  '), ' +', ' ')) <> ''
        AND TRIM(regexp_replace(translate(b.`annex_status`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('Standalone School', 'School with no Annexes', 'Mother School', 'Mother school', 'Annex/Extension School', 'Annex or Extension school(s)', 'Mobile School/Center', 'Mobile School(s)/Center(s)')) AS quarantined_unmapped_annex_status,
    COUNT_IF(b.in_quarantine AND TRIM(regexp_replace(translate(b.`offers_es`, chr(9) || chr(160), '  '), ' +', ' ')) <> ''
        AND TRIM(regexp_replace(translate(b.`offers_es`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'Yes', 'False', 'No')) AS quarantined_unmapped_offers_es,
    COUNT_IF(b.in_quarantine AND TRIM(regexp_replace(translate(b.`offers_jhs`, chr(9) || chr(160), '  '), ' +', ' ')) <> ''
        AND TRIM(regexp_replace(translate(b.`offers_jhs`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'Yes', 'False', 'No')) AS quarantined_unmapped_offers_jhs,
    COUNT_IF(b.in_quarantine AND TRIM(regexp_replace(translate(b.`offers_shs`, chr(9) || chr(160), '  '), ' +', ' ')) <> ''
        AND TRIM(regexp_replace(translate(b.`offers_shs`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('True', 'Yes', 'False', 'No')) AS quarantined_unmapped_offers_shs,
    COUNT_IF(b.in_quarantine AND TRIM(regexp_replace(translate(b.`Modified Curricular Offering Classification`, chr(9) || chr(160), '  '), ' +', ' ')) <> ''
        AND TRIM(regexp_replace(translate(b.`Modified Curricular Offering Classification`, chr(9) || chr(160), '  '), ' +', ' ')) NOT IN ('Purely ES', 'Purely JHS', 'Purely SHS', 'ES and JHS', 'ES with SHS', 'JHS with SHS', 'All Offering')) AS quarantined_unmapped_modified_curricular_offering_classification
  FROM b GROUP BY b.school_year
),
clean_years AS (
  SELECT
    c.school_year,
    COUNT(*) AS clean_rows,
    COUNT(DISTINCT c.school_id) AS clean_ids,
    COUNT_IF(c.school_id IS NULL OR NOT regexp_like(c.school_id, '^[0-9]{6}$')) AS invalid_ids,
    COUNT_IF(
        c.kinder_male < 0
        OR c.kinder_female < 0
        OR c.g1_male < 0
        OR c.g1_female < 0
        OR c.g2_male < 0
        OR c.g2_female < 0
        OR c.g3_male < 0
        OR c.g3_female < 0
        OR c.g4_male < 0
        OR c.g4_female < 0
        OR c.g5_male < 0
        OR c.g5_female < 0
        OR c.g6_male < 0
        OR c.g6_female < 0
        OR c.esng_male < 0
        OR c.esng_female < 0
        OR c.g7_male < 0
        OR c.g7_female < 0
        OR c.g8_male < 0
        OR c.g8_female < 0
        OR c.g9_male < 0
        OR c.g9_female < 0
        OR c.g10_male < 0
        OR c.g10_female < 0
        OR c.jhsng_male < 0
        OR c.jhsng_female < 0
        OR c.g11_abm_male < 0
        OR c.g11_abm_female < 0
        OR c.g11_arts_male < 0
        OR c.g11_arts_female < 0
        OR c.g11_gas_male < 0
        OR c.g11_gas_female < 0
        OR c.g11_humss_male < 0
        OR c.g11_humss_female < 0
        OR c.g11_maritime_male < 0
        OR c.g11_maritime_female < 0
        OR c.g11_sports_male < 0
        OR c.g11_sports_female < 0
        OR c.g11_stem_male < 0
        OR c.g11_stem_female < 0
        OR c.g11_tvl_male < 0
        OR c.g11_tvl_female < 0
        OR c.g11_unique_male < 0
        OR c.g11_unique_female < 0
        OR c.g12_abm_male < 0
        OR c.g12_abm_female < 0
        OR c.g12_arts_male < 0
        OR c.g12_arts_female < 0
        OR c.g12_gas_male < 0
        OR c.g12_gas_female < 0
        OR c.g12_humss_male < 0
        OR c.g12_humss_female < 0
        OR c.g12_maritime_male < 0
        OR c.g12_maritime_female < 0
        OR c.g12_sports_male < 0
        OR c.g12_sports_female < 0
        OR c.g12_stem_male < 0
        OR c.g12_stem_female < 0
        OR c.g12_tvl_male < 0
        OR c.g12_tvl_female < 0
        OR c.g12_unique_male < 0
        OR c.g12_unique_female < 0
        OR c.g11_sshs_acad_male < 0
        OR c.g11_sshs_acad_female < 0
        OR c.g11_sshs_techpro_male < 0
        OR c.g11_sshs_techpro_female < 0
      ) AS negative_rows,
    COUNT_IF(
        c.kinder_male > 10000
        OR c.kinder_female > 10000
        OR c.g1_male > 10000
        OR c.g1_female > 10000
        OR c.g2_male > 10000
        OR c.g2_female > 10000
        OR c.g3_male > 10000
        OR c.g3_female > 10000
        OR c.g4_male > 10000
        OR c.g4_female > 10000
        OR c.g5_male > 10000
        OR c.g5_female > 10000
        OR c.g6_male > 10000
        OR c.g6_female > 10000
        OR c.esng_male > 10000
        OR c.esng_female > 10000
        OR c.g7_male > 10000
        OR c.g7_female > 10000
        OR c.g8_male > 10000
        OR c.g8_female > 10000
        OR c.g9_male > 10000
        OR c.g9_female > 10000
        OR c.g10_male > 10000
        OR c.g10_female > 10000
        OR c.jhsng_male > 10000
        OR c.jhsng_female > 10000
        OR c.g11_abm_male > 10000
        OR c.g11_abm_female > 10000
        OR c.g11_arts_male > 10000
        OR c.g11_arts_female > 10000
        OR c.g11_gas_male > 10000
        OR c.g11_gas_female > 10000
        OR c.g11_humss_male > 10000
        OR c.g11_humss_female > 10000
        OR c.g11_maritime_male > 10000
        OR c.g11_maritime_female > 10000
        OR c.g11_sports_male > 10000
        OR c.g11_sports_female > 10000
        OR c.g11_stem_male > 10000
        OR c.g11_stem_female > 10000
        OR c.g11_tvl_male > 10000
        OR c.g11_tvl_female > 10000
        OR c.g11_unique_male > 10000
        OR c.g11_unique_female > 10000
        OR c.g12_abm_male > 10000
        OR c.g12_abm_female > 10000
        OR c.g12_arts_male > 10000
        OR c.g12_arts_female > 10000
        OR c.g12_gas_male > 10000
        OR c.g12_gas_female > 10000
        OR c.g12_humss_male > 10000
        OR c.g12_humss_female > 10000
        OR c.g12_maritime_male > 10000
        OR c.g12_maritime_female > 10000
        OR c.g12_sports_male > 10000
        OR c.g12_sports_female > 10000
        OR c.g12_stem_male > 10000
        OR c.g12_stem_female > 10000
        OR c.g12_tvl_male > 10000
        OR c.g12_tvl_female > 10000
        OR c.g12_unique_male > 10000
        OR c.g12_unique_female > 10000
        OR c.g11_sshs_acad_male > 10000
        OR c.g11_sshs_acad_female > 10000
        OR c.g11_sshs_techpro_male > 10000
        OR c.g11_sshs_techpro_female > 10000
      ) AS implausible_rows,
    SUM(
        COALESCE(CAST(c.kinder_male AS BIGINT), 0) + COALESCE(CAST(c.kinder_female AS BIGINT), 0) + COALESCE(CAST(c.g1_male AS BIGINT), 0) + COALESCE(CAST(c.g1_female AS BIGINT), 0) + COALESCE(CAST(c.g2_male AS BIGINT), 0) + COALESCE(CAST(c.g2_female AS BIGINT), 0) + COALESCE(CAST(c.g3_male AS BIGINT), 0) + COALESCE(CAST(c.g3_female AS BIGINT), 0) + COALESCE(CAST(c.g4_male AS BIGINT), 0) + COALESCE(CAST(c.g4_female AS BIGINT), 0) + COALESCE(CAST(c.g5_male AS BIGINT), 0) + COALESCE(CAST(c.g5_female AS BIGINT), 0) + COALESCE(CAST(c.g6_male AS BIGINT), 0) + COALESCE(CAST(c.g6_female AS BIGINT), 0) + COALESCE(CAST(c.esng_male AS BIGINT), 0) + COALESCE(CAST(c.esng_female AS BIGINT), 0) + COALESCE(CAST(c.g7_male AS BIGINT), 0) + COALESCE(CAST(c.g7_female AS BIGINT), 0) + COALESCE(CAST(c.g8_male AS BIGINT), 0) + COALESCE(CAST(c.g8_female AS BIGINT), 0) + COALESCE(CAST(c.g9_male AS BIGINT), 0) + COALESCE(CAST(c.g9_female AS BIGINT), 0) + COALESCE(CAST(c.g10_male AS BIGINT), 0) + COALESCE(CAST(c.g10_female AS BIGINT), 0) + COALESCE(CAST(c.jhsng_male AS BIGINT), 0) + COALESCE(CAST(c.jhsng_female AS BIGINT), 0) + COALESCE(CAST(c.g11_abm_male AS BIGINT), 0) + COALESCE(CAST(c.g11_abm_female AS BIGINT), 0) + COALESCE(CAST(c.g11_arts_male AS BIGINT), 0) + COALESCE(CAST(c.g11_arts_female AS BIGINT), 0) + COALESCE(CAST(c.g11_gas_male AS BIGINT), 0) + COALESCE(CAST(c.g11_gas_female AS BIGINT), 0) + COALESCE(CAST(c.g11_humss_male AS BIGINT), 0) + COALESCE(CAST(c.g11_humss_female AS BIGINT), 0) + COALESCE(CAST(c.g11_maritime_male AS BIGINT), 0) + COALESCE(CAST(c.g11_maritime_female AS BIGINT), 0) + COALESCE(CAST(c.g11_sports_male AS BIGINT), 0) + COALESCE(CAST(c.g11_sports_female AS BIGINT), 0) + COALESCE(CAST(c.g11_stem_male AS BIGINT), 0) + COALESCE(CAST(c.g11_stem_female AS BIGINT), 0) + COALESCE(CAST(c.g11_tvl_male AS BIGINT), 0) + COALESCE(CAST(c.g11_tvl_female AS BIGINT), 0) + COALESCE(CAST(c.g11_unique_male AS BIGINT), 0) + COALESCE(CAST(c.g11_unique_female AS BIGINT), 0) + COALESCE(CAST(c.g12_abm_male AS BIGINT), 0) + COALESCE(CAST(c.g12_abm_female AS BIGINT), 0) + COALESCE(CAST(c.g12_arts_male AS BIGINT), 0) + COALESCE(CAST(c.g12_arts_female AS BIGINT), 0) + COALESCE(CAST(c.g12_gas_male AS BIGINT), 0) + COALESCE(CAST(c.g12_gas_female AS BIGINT), 0) + COALESCE(CAST(c.g12_humss_male AS BIGINT), 0) + COALESCE(CAST(c.g12_humss_female AS BIGINT), 0) + COALESCE(CAST(c.g12_maritime_male AS BIGINT), 0) + COALESCE(CAST(c.g12_maritime_female AS BIGINT), 0) + COALESCE(CAST(c.g12_sports_male AS BIGINT), 0) + COALESCE(CAST(c.g12_sports_female AS BIGINT), 0) + COALESCE(CAST(c.g12_stem_male AS BIGINT), 0) + COALESCE(CAST(c.g12_stem_female AS BIGINT), 0) + COALESCE(CAST(c.g12_tvl_male AS BIGINT), 0) + COALESCE(CAST(c.g12_tvl_female AS BIGINT), 0) + COALESCE(CAST(c.g12_unique_male AS BIGINT), 0) + COALESCE(CAST(c.g12_unique_female AS BIGINT), 0) + COALESCE(CAST(c.g11_sshs_acad_male AS BIGINT), 0) + COALESCE(CAST(c.g11_sshs_acad_female AS BIGINT), 0) + COALESCE(CAST(c.g11_sshs_techpro_male AS BIGINT), 0) + COALESCE(CAST(c.g11_sshs_techpro_female AS BIGINT), 0)
      ) AS clean_learners,
    SUM(
        CASE WHEN c.kinder_male IS NULL THEN 1 ELSE 0 END + CASE WHEN c.kinder_female IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g1_male IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g1_female IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g2_male IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g2_female IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g3_male IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g3_female IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g4_male IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g4_female IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g5_male IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g5_female IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g6_male IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g6_female IS NULL THEN 1 ELSE 0 END + CASE WHEN c.esng_male IS NULL THEN 1 ELSE 0 END + CASE WHEN c.esng_female IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g7_male IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g7_female IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g8_male IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g8_female IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g9_male IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g9_female IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g10_male IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g10_female IS NULL THEN 1 ELSE 0 END + CASE WHEN c.jhsng_male IS NULL THEN 1 ELSE 0 END + CASE WHEN c.jhsng_female IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g11_abm_male IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g11_abm_female IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g11_arts_male IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g11_arts_female IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g11_gas_male IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g11_gas_female IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g11_humss_male IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g11_humss_female IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g11_maritime_male IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g11_maritime_female IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g11_sports_male IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g11_sports_female IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g11_stem_male IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g11_stem_female IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g11_tvl_male IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g11_tvl_female IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g11_unique_male IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g11_unique_female IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g12_abm_male IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g12_abm_female IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g12_arts_male IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g12_arts_female IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g12_gas_male IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g12_gas_female IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g12_humss_male IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g12_humss_female IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g12_maritime_male IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g12_maritime_female IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g12_sports_male IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g12_sports_female IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g12_stem_male IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g12_stem_female IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g12_tvl_male IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g12_tvl_female IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g12_unique_male IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g12_unique_female IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g11_sshs_acad_male IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g11_sshs_acad_female IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g11_sshs_techpro_male IS NULL THEN 1 ELSE 0 END + CASE WHEN c.g11_sshs_techpro_female IS NULL THEN 1 ELSE 0 END
      ) AS clean_missing_counts,
    COUNT_IF(
        (c.schema_version = 'v1' AND (c.modified_curricular_offering_classification IS NOT NULL OR c.g11_sshs_acad_male IS NOT NULL OR c.g11_sshs_acad_female IS NOT NULL OR c.g11_sshs_techpro_male IS NOT NULL OR c.g11_sshs_techpro_female IS NOT NULL))
      ) AS absent_filled_rows,
    COUNT_IF(c.is_overseas) AS overseas_rows,
    COUNT_IF(c.enrollment_status = 'all_zero') AS all_zero_rows,
    COUNT_IF(c.enrollment_status = 'no_counts') AS no_counts_rows,
    COUNT_IF(c.enrollment_status IS NULL OR c.enrollment_status NOT IN ('has_learners', 'all_zero', 'no_counts')) AS invalid_status_rows,
    COUNT_IF(c.barangay_possibly_truncated) AS truncated_rows,
    COUNT_IF(c.barangay IS NULL) AS barangay_null_rows
  FROM clean AS c GROUP BY c.school_year
),
-- Each clean row beside its Bronze row: is every published label mapped?
matched_years AS (
  SELECT
    c.school_year,
    COUNT_IF(c.region IS NULL AND TRIM(regexp_replace(translate(b.`region`, chr(9) || chr(160), '  '), ' +', ' ')) <> '') AS unmapped_region,
    COUNT_IF(c.legislative_district IS NULL AND TRIM(regexp_replace(translate(b.`legislative_district`, chr(9) || chr(160), '  '), ' +', ' ')) <> '') AS unmapped_legislative_district,
    COUNT_IF(c.sector IS NULL AND TRIM(regexp_replace(translate(b.`sector`, chr(9) || chr(160), '  '), ' +', ' ')) <> '') AS unmapped_sector,
    COUNT_IF(c.school_management IS NULL AND TRIM(regexp_replace(translate(b.`school_management`, chr(9) || chr(160), '  '), ' +', ' ')) <> '') AS unmapped_school_management,
    COUNT_IF(c.annex_status IS NULL AND TRIM(regexp_replace(translate(b.`annex_status`, chr(9) || chr(160), '  '), ' +', ' ')) <> '') AS unmapped_annex_status,
    COUNT_IF(c.offers_es IS NULL AND TRIM(regexp_replace(translate(b.`offers_es`, chr(9) || chr(160), '  '), ' +', ' ')) <> '') AS unmapped_offers_es,
    COUNT_IF(c.offers_jhs IS NULL AND TRIM(regexp_replace(translate(b.`offers_jhs`, chr(9) || chr(160), '  '), ' +', ' ')) <> '') AS unmapped_offers_jhs,
    COUNT_IF(c.offers_shs IS NULL AND TRIM(regexp_replace(translate(b.`offers_shs`, chr(9) || chr(160), '  '), ' +', ' ')) <> '') AS unmapped_offers_shs,
    COUNT_IF(c.modified_curricular_offering_classification IS NULL AND TRIM(regexp_replace(translate(b.`Modified Curricular Offering Classification`, chr(9) || chr(160), '  '), ' +', ' ')) <> '') AS unmapped_modified_curricular_offering_classification,
    COUNT_IF(
        TRIM(regexp_replace(translate(b.`region`, chr(9) || chr(160), '  '), ' +', ' ')) <> c.region
        OR TRIM(regexp_replace(translate(b.`legislative_district`, chr(9) || chr(160), '  '), ' +', ' ')) <> c.legislative_district
        OR TRIM(regexp_replace(translate(b.`sector`, chr(9) || chr(160), '  '), ' +', ' ')) <> c.sector
        OR TRIM(regexp_replace(translate(b.`school_management`, chr(9) || chr(160), '  '), ' +', ' ')) <> c.school_management
        OR TRIM(regexp_replace(translate(b.`annex_status`, chr(9) || chr(160), '  '), ' +', ' ')) <> c.annex_status
        OR TRIM(regexp_replace(translate(b.`Modified Curricular Offering Classification`, chr(9) || chr(160), '  '), ' +', ' ')) <> c.modified_curricular_offering_classification
      ) AS relabelled_rows
  FROM clean AS c
  JOIN b ON c.source_sha256 = b.source_sha256 AND c.source_row_number = b.source_row_number
  GROUP BY c.school_year
),
quarantine_years AS (
  SELECT
    q.school_year,
    COUNT(*) AS quarantined_rows,
    COUNT_IF(array_contains(q.quarantine_reasons, 'school_id_blank')) AS reason_school_id_blank,
    COUNT_IF(array_contains(q.quarantine_reasons, 'school_id_malformed')) AS reason_school_id_malformed,
    COUNT_IF(array_contains(q.quarantine_reasons, 'school_id_duplicated')) AS reason_school_id_duplicated,
    COUNT_IF(array_contains(q.quarantine_reasons, 'count_negative')) AS reason_count_negative,
    COUNT_IF(array_contains(q.quarantine_reasons, 'count_uncastable')) AS reason_count_uncastable,
    COUNT_IF(array_contains(q.quarantine_reasons, 'count_above_plausible_max')) AS reason_count_above_plausible_max
  FROM quarantined AS q GROUP BY q.school_year
),
years AS (
  SELECT
    y.school_year,
    y.batch_id,
    COALESCE(bronze_rows, 0) AS bronze_rows,
    COALESCE(kept_rows, 0) AS kept_rows,
    COALESCE(kept_learners, 0) AS kept_learners,
    COALESCE(kept_missing_counts, 0) AS kept_missing_counts,
    COALESCE(clean_rows, 0) AS clean_rows,
    COALESCE(clean_ids, 0) AS clean_ids,
    COALESCE(clean_learners, 0) AS clean_learners,
    COALESCE(clean_missing_counts, 0) AS clean_missing_counts,
    COALESCE(quarantined_rows, 0) AS quarantined_rows,
    COALESCE(whitespace_rows, 0) AS whitespace_rows,
    COALESCE(repaired_rows, 0) AS repaired_rows,
    COALESCE(blank_text_rows, 0) AS blank_text_rows,
    COALESCE(placeholder_rows, 0) AS placeholder_rows,
    COALESCE(blank_count_rows, 0) AS blank_count_rows,
    COALESCE(absent_column_rows, 0) AS absent_column_rows,
    COALESCE(invalid_ids, 0) AS invalid_ids,
    COALESCE(negative_rows, 0) AS negative_rows,
    COALESCE(implausible_rows, 0) AS implausible_rows,
    COALESCE(absent_filled_rows, 0) AS absent_filled_rows,
    COALESCE(overseas_rows, 0) AS overseas_rows,
    COALESCE(all_zero_rows, 0) AS all_zero_rows,
    COALESCE(no_counts_rows, 0) AS no_counts_rows,
    COALESCE(invalid_status_rows, 0) AS invalid_status_rows,
    COALESCE(truncated_rows, 0) AS truncated_rows,
    COALESCE(barangay_null_rows, 0) AS barangay_null_rows,
    COALESCE(relabelled_rows, 0) AS relabelled_rows,
    COALESCE(reason_school_id_blank, 0) AS reason_school_id_blank,
    COALESCE(reason_school_id_malformed, 0) AS reason_school_id_malformed,
    COALESCE(reason_school_id_duplicated, 0) AS reason_school_id_duplicated,
    COALESCE(reason_count_negative, 0) AS reason_count_negative,
    COALESCE(reason_count_uncastable, 0) AS reason_count_uncastable,
    COALESCE(reason_count_above_plausible_max, 0) AS reason_count_above_plausible_max,
    COALESCE(unmapped_region, 0) + COALESCE(quarantined_unmapped_region, 0) AS unmapped_region,
    COALESCE(unmapped_legislative_district, 0) + COALESCE(quarantined_unmapped_legislative_district, 0) AS unmapped_legislative_district,
    COALESCE(unmapped_sector, 0) + COALESCE(quarantined_unmapped_sector, 0) AS unmapped_sector,
    COALESCE(unmapped_school_management, 0) + COALESCE(quarantined_unmapped_school_management, 0) AS unmapped_school_management,
    COALESCE(unmapped_annex_status, 0) + COALESCE(quarantined_unmapped_annex_status, 0) AS unmapped_annex_status,
    COALESCE(unmapped_offers_es, 0) + COALESCE(quarantined_unmapped_offers_es, 0) AS unmapped_offers_es,
    COALESCE(unmapped_offers_jhs, 0) + COALESCE(quarantined_unmapped_offers_jhs, 0) AS unmapped_offers_jhs,
    COALESCE(unmapped_offers_shs, 0) + COALESCE(quarantined_unmapped_offers_shs, 0) AS unmapped_offers_shs,
    COALESCE(unmapped_modified_curricular_offering_classification, 0) + COALESCE(quarantined_unmapped_modified_curricular_offering_classification, 0) AS unmapped_modified_curricular_offering_classification
  FROM cur AS y
  LEFT JOIN bronze_years ON bronze_years.school_year = y.school_year
  LEFT JOIN clean_years ON clean_years.school_year = y.school_year
  LEFT JOIN matched_years ON matched_years.school_year = y.school_year
  LEFT JOIN quarantine_years ON quarantine_years.school_year = y.school_year
),
found AS (SELECT COUNT(*) AS current_batches FROM cur),
silver_rows AS (
  SELECT school_year, batch_id, delivery_version, schema_version, source_sha256, source_row_number, run_id, cleaned_at_utc, code_revision FROM clean
  UNION ALL SELECT school_year, batch_id, delivery_version, schema_version, source_sha256, source_row_number, run_id, cleaned_at_utc, code_revision FROM quarantined
),
whole AS (
  SELECT
    COUNT_IF(school_year IS NULL OR batch_id IS NULL OR delivery_version IS NULL OR schema_version IS NULL OR source_sha256 IS NULL OR source_row_number IS NULL OR run_id IS NULL OR cleaned_at_utc IS NULL OR code_revision IS NULL) AS missing_lineage,
    COUNT_IF(run_id IS NULL OR run_id <> :run_id) AS other_run_rows,
    COUNT(DISTINCT cleaned_at_utc) AS timestamps
  FROM silver_rows
),
-- Silver rows whose Bronze row is not in a current batch (an old version, or gone).
unresolved AS (
  SELECT COUNT(*) AS unresolved_rows
  FROM silver_rows AS s
  LEFT JOIN bronze ON s.source_sha256 = bronze.source_sha256 AND s.source_row_number = bronze.source_row_number
  WHERE bronze.source_row_number IS NULL
),
checks AS (
  -- The whole table, both tables together
  SELECT CAST(NULL AS STRING) AS batch_id, 'edu_access.03-silver.deped_enrollment_clean_candidate' AS table_name, 'current_batches_present' AS check_name,
         CASE WHEN current_batches > 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         'at least 1' AS expected, CAST(current_batches AS STRING) AS actual FROM found
  UNION ALL SELECT CAST(NULL AS STRING) AS batch_id, 'edu_access.03-silver.deped_enrollment_clean_candidate' AS table_name, 'lineage_complete' AS check_name,
         CASE WHEN missing_lineage = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(missing_lineage AS STRING) AS actual FROM whole
  UNION ALL SELECT CAST(NULL AS STRING) AS batch_id, 'edu_access.03-silver.deped_enrollment_clean_candidate' AS table_name, 'rows_resolve_to_current_bronze' AS check_name,
         CASE WHEN unresolved_rows = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(unresolved_rows AS STRING) AS actual FROM unresolved
  UNION ALL SELECT CAST(NULL AS STRING) AS batch_id, 'edu_access.03-silver.deped_enrollment_clean_candidate' AS table_name, 'rows_built_by_this_run' AS check_name,
         CASE WHEN other_run_rows = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(other_run_rows AS STRING) AS actual FROM whole
  UNION ALL SELECT CAST(NULL AS STRING) AS batch_id, 'edu_access.03-silver.deped_enrollment_clean_candidate' AS table_name, 'one_timestamp_per_run' AS check_name,
         CASE WHEN timestamps = 1 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(1 AS STRING) AS expected, CAST(timestamps AS STRING) AS actual FROM whole
  -- Each school year: reconciliation, keys, ranges, NULLs
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_enrollment_clean_candidate' AS table_name, 'rows_reconcile' AS check_name,
         CASE WHEN clean_rows + quarantined_rows = bronze_rows THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(bronze_rows AS STRING) AS expected, CAST(clean_rows + quarantined_rows AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_enrollment_clean_candidate' AS table_name, 'school_id_unique' AS check_name,
         CASE WHEN clean_rows - clean_ids = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(clean_rows - clean_ids AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_enrollment_clean_candidate' AS table_name, 'school_id_valid' AS check_name,
         CASE WHEN invalid_ids = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(invalid_ids AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_enrollment_clean_candidate' AS table_name, 'counts_non_negative' AS check_name,
         CASE WHEN negative_rows = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(negative_rows AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_enrollment_clean_candidate' AS table_name, 'counts_within_plausible_max' AS check_name,
         CASE WHEN implausible_rows = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(implausible_rows AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_enrollment_clean_candidate' AS table_name, 'learners_reconcile' AS check_name,
         CASE WHEN clean_learners = kept_learners THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(kept_learners AS STRING) AS expected, CAST(clean_learners AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_enrollment_clean_candidate' AS table_name, 'missing_counts_stay_null' AS check_name,
         CASE WHEN clean_missing_counts = kept_missing_counts THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(kept_missing_counts AS STRING) AS expected, CAST(clean_missing_counts AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_enrollment_clean_candidate' AS table_name, 'absent_columns_stay_null' AS check_name,
         CASE WHEN absent_filled_rows = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(absent_filled_rows AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_enrollment_clean_candidate' AS table_name, 'enrollment_status_valid' AS check_name,
         CASE WHEN invalid_status_rows = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(invalid_status_rows AS STRING) AS actual FROM years
  -- Each school year: every label is in the reviewed mapping
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_enrollment_clean_candidate' AS table_name, 'labels_mapped_region' AS check_name,
         CASE WHEN unmapped_region = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(unmapped_region AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_enrollment_clean_candidate' AS table_name, 'labels_mapped_legislative_district' AS check_name,
         CASE WHEN unmapped_legislative_district = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(unmapped_legislative_district AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_enrollment_clean_candidate' AS table_name, 'labels_mapped_sector' AS check_name,
         CASE WHEN unmapped_sector = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(unmapped_sector AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_enrollment_clean_candidate' AS table_name, 'labels_mapped_school_management' AS check_name,
         CASE WHEN unmapped_school_management = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(unmapped_school_management AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_enrollment_clean_candidate' AS table_name, 'labels_mapped_annex_status' AS check_name,
         CASE WHEN unmapped_annex_status = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(unmapped_annex_status AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_enrollment_clean_candidate' AS table_name, 'labels_mapped_offers_es' AS check_name,
         CASE WHEN unmapped_offers_es = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(unmapped_offers_es AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_enrollment_clean_candidate' AS table_name, 'labels_mapped_offers_jhs' AS check_name,
         CASE WHEN unmapped_offers_jhs = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(unmapped_offers_jhs AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_enrollment_clean_candidate' AS table_name, 'labels_mapped_offers_shs' AS check_name,
         CASE WHEN unmapped_offers_shs = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(unmapped_offers_shs AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_enrollment_clean_candidate' AS table_name, 'labels_mapped_modified_curricular_offering_classification' AS check_name,
         CASE WHEN unmapped_modified_curricular_offering_classification = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(0 AS STRING) AS expected, CAST(unmapped_modified_curricular_offering_classification AS STRING) AS actual FROM years
  -- Each school year: quarantine (WARN above 0, FAIL above 1% of the year's Bronze rows)
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_enrollment_quarantine_candidate' AS table_name, 'quarantine_rate' AS check_name,
         CASE WHEN quarantined_rows = 0 THEN 'PASS' WHEN quarantined_rows * 100 > bronze_rows THEN 'FAIL' ELSE 'WARN' END AS status,
         '0 (FAIL above 1% of ' || CAST(bronze_rows AS STRING) || ')' AS expected, CAST(quarantined_rows AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_enrollment_quarantine_candidate' AS table_name, 'quarantine_reason_school_id_blank' AS check_name,
         CASE WHEN reason_school_id_blank = 0 THEN 'PASS' ELSE 'WARN' END AS status,
         '0' AS expected, CAST(reason_school_id_blank AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_enrollment_quarantine_candidate' AS table_name, 'quarantine_reason_school_id_malformed' AS check_name,
         CASE WHEN reason_school_id_malformed = 0 THEN 'PASS' ELSE 'WARN' END AS status,
         '0' AS expected, CAST(reason_school_id_malformed AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_enrollment_quarantine_candidate' AS table_name, 'quarantine_reason_school_id_duplicated' AS check_name,
         CASE WHEN reason_school_id_duplicated = 0 THEN 'PASS' ELSE 'WARN' END AS status,
         '0' AS expected, CAST(reason_school_id_duplicated AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_enrollment_quarantine_candidate' AS table_name, 'quarantine_reason_count_negative' AS check_name,
         CASE WHEN reason_count_negative = 0 THEN 'PASS' ELSE 'WARN' END AS status,
         '0' AS expected, CAST(reason_count_negative AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_enrollment_quarantine_candidate' AS table_name, 'quarantine_reason_count_uncastable' AS check_name,
         CASE WHEN reason_count_uncastable = 0 THEN 'PASS' ELSE 'WARN' END AS status,
         '0' AS expected, CAST(reason_count_uncastable AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_enrollment_quarantine_candidate' AS table_name, 'quarantine_reason_count_above_plausible_max' AS check_name,
         CASE WHEN reason_count_above_plausible_max = 0 THEN 'PASS' ELSE 'WARN' END AS status,
         '0' AS expected, CAST(reason_count_above_plausible_max AS STRING) AS actual FROM years
  -- Each school year: how many rows each cleaning rule changed or flagged (records, always PASS)
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_enrollment_clean_candidate' AS table_name, 'rule_whitespace_normalized' AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(whitespace_rows AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_enrollment_clean_candidate' AS table_name, 'rule_characters_repaired' AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(repaired_rows AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_enrollment_clean_candidate' AS table_name, 'rule_blank_text_to_null' AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(blank_text_rows AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_enrollment_clean_candidate' AS table_name, 'rule_placeholder_to_null' AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(placeholder_rows AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_enrollment_clean_candidate' AS table_name, 'rule_blank_counts_to_null' AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(blank_count_rows AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_enrollment_clean_candidate' AS table_name, 'rule_absent_columns_null' AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(absent_column_rows AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_enrollment_clean_candidate' AS table_name, 'rule_labels_standardized' AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(relabelled_rows AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_enrollment_clean_candidate' AS table_name, 'flag_is_overseas' AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(overseas_rows AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_enrollment_clean_candidate' AS table_name, 'flag_enrollment_all_zero' AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(all_zero_rows AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_enrollment_clean_candidate' AS table_name, 'flag_enrollment_no_counts' AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(no_counts_rows AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_enrollment_clean_candidate' AS table_name, 'flag_barangay_possibly_truncated' AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(truncated_rows AS STRING) AS actual FROM years
  UNION ALL SELECT batch_id AS batch_id, 'edu_access.03-silver.deped_enrollment_clean_candidate' AS table_name, 'flag_barangay_blank' AS check_name,
         'PASS' AS status,
         CAST(NULL AS STRING) AS expected, CAST(barangay_null_rows AS STRING) AS actual FROM years
)
SELECT * FROM checks
) AS results;

-- A failed build: record it before stopping. The Silver tables are not touched.
MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (
  SELECT :run_id AS run_id, COUNT_IF(status = 'FAIL') AS fails
  FROM edu_access.`01-control`.data_quality_results
  WHERE run_id = :run_id AND source_id = 'deped_enrollment' AND layer = 'silver'
    AND checked_at_utc >= session.silver_gate_started_at_utc
) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'silver_build' AND t.source_id = 'deped_enrollment'
WHEN MATCHED AND s.fails > 0 THEN UPDATE SET
  status = 'failed', finished_at_utc = current_timestamp(), failure_stage = 'gate',
  error_message = CAST(s.fails AS STRING) || ' FAIL result(s) in data_quality_results';

-- Stop here, before publishing, if anything failed in this execution.
SELECT CASE WHEN COUNT(*) > 0
            THEN raise_error('Silver gate failed for deped_enrollment: ' || CAST(COUNT(*) AS STRING)
                             || ' FAIL result(s) in data_quality_results for run ' || :run_id)
       END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'deped_enrollment' AND layer = 'silver' AND status = 'FAIL'
  AND checked_at_utc >= session.silver_gate_started_at_utc;

-- Every check passed: publish. Quarantine first, then clean, the table Gold reads. Each copy is
-- one atomic Delta commit, but the pair is not, so the run is 'succeeded' only after both. If the
-- task dies in between, the run stays 'running', and Gold trusts a Silver table only when the
-- run_id its rows carry is a succeeded silver_build run (D-025).
CREATE OR REPLACE TABLE edu_access.`03-silver`.deped_enrollment_quarantine USING DELTA AS
SELECT * FROM edu_access.`03-silver`.deped_enrollment_quarantine_candidate;

ALTER TABLE edu_access.`03-silver`.deped_enrollment_quarantine OWNER TO `reached-hq`;

CREATE OR REPLACE TABLE edu_access.`03-silver`.deped_enrollment_clean USING DELTA AS
SELECT * FROM edu_access.`03-silver`.deped_enrollment_clean_candidate;

ALTER TABLE edu_access.`03-silver`.deped_enrollment_clean OWNER TO `reached-hq`;

-- Published: the run succeeded.
MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (SELECT :run_id AS run_id) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'silver_build' AND t.source_id = 'deped_enrollment'
WHEN MATCHED THEN UPDATE SET
  status = 'succeeded', finished_at_utc = current_timestamp(), failure_stage = NULL, error_message = NULL;
