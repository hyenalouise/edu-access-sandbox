-- Silver build for psa_poverty_stat. Generated from config/ingestion/psa_poverty_stat.json
-- and config/mappings/psa_poverty_stat.json by src/silver/psa_poverty_stat.py:
--   python -m src.silver.cli sql --source psa_poverty_stat > etl/03_silver/05_clean_psa_poverty_stat.sql
-- Do not edit by hand; tests/test_silver_psa.py fails if it differs.
--
-- Rebuilds the two candidate tables from the current Bronze batches only (01-control.current_batches:
-- the latest succeeded delivery version of each logical dataset). Bronze is read, never changed.
-- Each current Bronze 'unit' row becomes one candidate per estimate year its delivery covers
-- (2018, 2021, 2023 in the contract), and every candidate ends in exactly one of the two tables:
--   psa_poverty_stat_clean_candidate       one row per unit per estimate year, typed;
--   psa_poverty_stat_quarantine_candidate  candidates that cannot be trusted, with their reasons.
-- Title, header, region banner, blank and footer rows stay in Bronze; banners only give each unit its
-- region label. The Silver tables are never written here: the gate (the next task) checks the
-- candidates and publishes them only if no check fails (D-025). It rebuilds on every run.
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
ON t.run_id = s.run_id AND t.pipeline_name = 'silver_build' AND t.source_id = 'psa_poverty_stat'
WHEN MATCHED THEN UPDATE SET
  status = 'running', started_at_utc = session.silver_cleaned_at_utc, finished_at_utc = NULL,
  failure_stage = NULL, error_message = NULL, code_revision = session.silver_code_revision, job_run_id = s.run_id
WHEN NOT MATCHED THEN INSERT (run_id, pipeline_name, source_id, environment, status, started_at_utc, code_revision, job_run_id)
  VALUES (s.run_id, 'silver_build', 'psa_poverty_stat', session.silver_environment, 'running',
          session.silver_cleaned_at_utc, session.silver_code_revision, s.run_id);

CREATE SCHEMA IF NOT EXISTS edu_access.`03-silver`;
ALTER SCHEMA edu_access.`03-silver` OWNER TO `reached-hq`;

-- Every candidate once, typed, with the reasons it would be quarantined. A reason is decided with
-- explicit NULL handling, and concat_ws never returns NULL, so quarantine_reasons = '' and <> ''
-- split the candidates without losing any.
CREATE OR REPLACE TEMPORARY VIEW psa_poverty_stat_classified AS
WITH bronze AS (
  SELECT r.*
  FROM edu_access.`02-bronze`.psa_poverty_stat_raw AS r
  JOIN edu_access.`01-control`.current_batches AS c ON r.batch_id = c.batch_id
  WHERE c.source_id = 'psa_poverty_stat'
),
-- Region context: number the banner rows in Excel row order within each batch and sheet, so every
-- unit gets the banner above it, and nothing is carried from one delivery to another.
ordered AS (
  SELECT r.*,
         SUM(CASE WHEN r.source_row_kind = 'region_banner' THEN 1 ELSE 0 END) OVER (
           PARTITION BY r.batch_id, r.source_sheet ORDER BY r.source_row_number
           ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS banner_seq
  FROM bronze AS r
  WHERE r.source_row_kind IN ('unit', 'region_banner')
),
banners AS (
  SELECT batch_id, source_sheet, banner_seq, NULLIF(TRIM(regexp_replace(translate(o.`Region/Province`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS region
  FROM ordered AS o WHERE o.source_row_kind = 'region_banner'
),
units AS (
  SELECT o.*, b.region
  FROM ordered AS o
  LEFT JOIN banners AS b
    ON b.batch_id = o.batch_id AND b.source_sheet = o.source_sheet AND b.banner_seq = o.banner_seq
  WHERE o.source_row_kind = 'unit'
),
-- Unpivot: one candidate per unit and estimate year the delivery covers, the year's five measures
-- still as the published text.
candidates AS (
  SELECT
    '2018' AS estimate_year,
    u.`PSGC ID` AS psgc_id_published,
    u.region,
    NULLIF(TRIM(regexp_replace(translate(u.`Municipality/City`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS municipality,
    u.`Poverty Incidence 2018` AS poverty_incidence_published,
    u.`Coefficient of Variation 2018` AS coefficient_of_variation_published,
    u.`Standard Error 2018` AS standard_error_published,
    u.`90% Confidence Interval Lower Limit 2018` AS ci90_lower_limit_published,
    u.`90% Confidence Interval Upper Limit 2018` AS ci90_upper_limit_published,
    u.logical_dataset,
    u.estimate_years_covered,
    u.batch_id,
    u.delivery_version,
    u.schema_version,
    u.source_sha256,
    u.source_row_number
  FROM units AS u
  WHERE array_contains(split(u.estimate_years_covered, ','), '2018')
  UNION ALL
  SELECT
    '2021' AS estimate_year,
    u.`PSGC ID` AS psgc_id_published,
    u.region,
    NULLIF(TRIM(regexp_replace(translate(u.`Municipality/City`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS municipality,
    u.`Poverty Incidence 2021` AS poverty_incidence_published,
    u.`Coefficient of Variation 2021` AS coefficient_of_variation_published,
    u.`Standard Error 2021` AS standard_error_published,
    u.`90% Confidence Interval Lower Limit 2021` AS ci90_lower_limit_published,
    u.`90% Confidence Interval Upper Limit 2021` AS ci90_upper_limit_published,
    u.logical_dataset,
    u.estimate_years_covered,
    u.batch_id,
    u.delivery_version,
    u.schema_version,
    u.source_sha256,
    u.source_row_number
  FROM units AS u
  WHERE array_contains(split(u.estimate_years_covered, ','), '2021')
  UNION ALL
  SELECT
    '2023' AS estimate_year,
    u.`PSGC ID` AS psgc_id_published,
    u.region,
    NULLIF(TRIM(regexp_replace(translate(u.`Municipality/City`, chr(9) || chr(160), '  '), ' +', ' ')), '') AS municipality,
    u.`Poverty Incidence 2023` AS poverty_incidence_published,
    u.`Coefficient of Variation 2023` AS coefficient_of_variation_published,
    u.`Standard Error 2023` AS standard_error_published,
    u.`90% Confidence Interval Lower Limit 2023` AS ci90_lower_limit_published,
    u.`90% Confidence Interval Upper Limit 2023` AS ci90_upper_limit_published,
    u.logical_dataset,
    u.estimate_years_covered,
    u.batch_id,
    u.delivery_version,
    u.schema_version,
    u.source_sha256,
    u.source_row_number
  FROM units AS u
  WHERE array_contains(split(u.estimate_years_covered, ','), '2023')
),
-- The padded ID (O-2). A malformed ID gets no padded form, so it can never match another row.
keyed AS (
  SELECT
    c.*,
    CASE WHEN regexp_like(c.psgc_id_published, '^[0-9]{5,6}$') THEN lpad(c.psgc_id_published, 6, '0') END AS psgc_id
  FROM candidates AS c
),
-- Measures typed only when they are numbers (DOUBLE, no rounding); the key counted per year.
typed AS (
  SELECT
    k.estimate_year,
    k.psgc_id,
    k.psgc_id || '000' AS correspondence_code,
    k.region,
    k.municipality,
    CASE WHEN regexp_like(k.poverty_incidence_published, '^-?[0-9]+([.][0-9]+)?([eE][-+]?[0-9]{1,3})?$') THEN TRY_CAST(k.poverty_incidence_published AS DOUBLE) END AS poverty_incidence,
    CASE WHEN regexp_like(k.coefficient_of_variation_published, '^-?[0-9]+([.][0-9]+)?([eE][-+]?[0-9]{1,3})?$') THEN TRY_CAST(k.coefficient_of_variation_published AS DOUBLE) END AS coefficient_of_variation,
    CASE WHEN regexp_like(k.standard_error_published, '^-?[0-9]+([.][0-9]+)?([eE][-+]?[0-9]{1,3})?$') THEN TRY_CAST(k.standard_error_published AS DOUBLE) END AS standard_error,
    CASE WHEN regexp_like(k.ci90_lower_limit_published, '^-?[0-9]+([.][0-9]+)?([eE][-+]?[0-9]{1,3})?$') THEN TRY_CAST(k.ci90_lower_limit_published AS DOUBLE) END AS ci90_lower_limit,
    CASE WHEN regexp_like(k.ci90_upper_limit_published, '^-?[0-9]+([.][0-9]+)?([eE][-+]?[0-9]{1,3})?$') THEN TRY_CAST(k.ci90_upper_limit_published AS DOUBLE) END AS ci90_upper_limit,
    COUNT(*) OVER (PARTITION BY k.estimate_year, k.psgc_id) AS key_rows,
    COALESCE(
      (k.poverty_incidence_published <> '' AND (NOT regexp_like(k.poverty_incidence_published, '^-?[0-9]+([.][0-9]+)?([eE][-+]?[0-9]{1,3})?$') OR TRY_CAST(k.poverty_incidence_published AS DOUBLE) IS NULL))
      OR (k.coefficient_of_variation_published <> '' AND (NOT regexp_like(k.coefficient_of_variation_published, '^-?[0-9]+([.][0-9]+)?([eE][-+]?[0-9]{1,3})?$') OR TRY_CAST(k.coefficient_of_variation_published AS DOUBLE) IS NULL))
      OR (k.standard_error_published <> '' AND (NOT regexp_like(k.standard_error_published, '^-?[0-9]+([.][0-9]+)?([eE][-+]?[0-9]{1,3})?$') OR TRY_CAST(k.standard_error_published AS DOUBLE) IS NULL))
      OR (k.ci90_lower_limit_published <> '' AND (NOT regexp_like(k.ci90_lower_limit_published, '^-?[0-9]+([.][0-9]+)?([eE][-+]?[0-9]{1,3})?$') OR TRY_CAST(k.ci90_lower_limit_published AS DOUBLE) IS NULL))
      OR (k.ci90_upper_limit_published <> '' AND (NOT regexp_like(k.ci90_upper_limit_published, '^-?[0-9]+([.][0-9]+)?([eE][-+]?[0-9]{1,3})?$') OR TRY_CAST(k.ci90_upper_limit_published AS DOUBLE) IS NULL)),
      FALSE) AS any_uncastable,
    (k.psgc_id_published IS NULL OR k.psgc_id_published = '') AS id_blank,
    k.logical_dataset,
    k.estimate_years_covered,
    k.batch_id,
    k.delivery_version,
    k.schema_version,
    k.source_sha256,
    k.source_row_number
  FROM keyed AS k
)
SELECT
  CAST(t.estimate_year AS INT) AS estimate_year,
  t.psgc_id,
  t.correspondence_code,
  t.region,
  t.municipality,
  t.poverty_incidence,
  t.coefficient_of_variation,
  t.standard_error,
  t.ci90_lower_limit,
  t.ci90_upper_limit,
  CASE WHEN t.poverty_incidence IS NOT NULL AND t.coefficient_of_variation IS NOT NULL AND t.standard_error IS NOT NULL AND t.ci90_lower_limit IS NOT NULL AND t.ci90_upper_limit IS NOT NULL THEN 'estimated'
         WHEN t.poverty_incidence IS NULL AND t.coefficient_of_variation IS NULL AND t.standard_error IS NULL AND t.ci90_lower_limit IS NULL AND t.ci90_upper_limit IS NULL THEN 'no_estimate'
         ELSE 'partial_estimate' END AS estimate_status,
  COALESCE(t.coefficient_of_variation > 20, FALSE) AS cv_over_20,
  COALESCE(abs(t.standard_error - t.poverty_incidence * t.coefficient_of_variation / 100) > 0.05, FALSE) AS se_cv_inconsistent,
  COALESCE(t.ci90_lower_limit <= 0, FALSE) AS lower_limit_not_positive,
  concat_ws(',',
      CASE WHEN t.id_blank THEN 'psgc_id_blank'
           WHEN t.psgc_id IS NULL THEN 'psgc_id_malformed' END,
      CASE WHEN t.psgc_id IS NOT NULL AND t.key_rows > 1 THEN 'psgc_id_duplicated' END,
      CASE WHEN t.any_uncastable THEN 'measure_uncastable' END,
      CASE WHEN COALESCE(t.poverty_incidence < 0 OR t.poverty_incidence > 100, FALSE) THEN 'incidence_out_of_range' END,
      CASE WHEN COALESCE(t.coefficient_of_variation < 0, FALSE) THEN 'cv_negative' END,
      CASE WHEN COALESCE(t.standard_error < 0, FALSE) THEN 'se_negative' END,
      CASE WHEN COALESCE(t.ci90_lower_limit > t.ci90_upper_limit, FALSE) OR COALESCE(t.poverty_incidence < t.ci90_lower_limit, FALSE) OR COALESCE(t.poverty_incidence > t.ci90_upper_limit, FALSE) THEN 'ci_inconsistent' END
    ) AS quarantine_reasons,
  t.logical_dataset,
  t.estimate_years_covered,
  t.batch_id,
  t.delivery_version,
  t.schema_version,
  t.source_sha256,
  t.source_row_number,
  session.silver_run_id AS run_id,
  session.silver_cleaned_at_utc AS cleaned_at_utc,
  session.silver_code_revision AS code_revision
FROM typed AS t;

-- One row per unit per estimate year, with the Bronze row it came from.
CREATE OR REPLACE TABLE edu_access.`03-silver`.psa_poverty_stat_clean_candidate USING DELTA AS
SELECT
  estimate_year,
  psgc_id,
  correspondence_code,
  region,
  municipality,
  poverty_incidence,
  coefficient_of_variation,
  standard_error,
  ci90_lower_limit,
  ci90_upper_limit,
  estimate_status,
  cv_over_20,
  se_cv_inconsistent,
  lower_limit_not_positive,
  logical_dataset,
  estimate_years_covered,
  batch_id,
  delivery_version,
  schema_version,
  source_sha256,
  source_row_number,
  run_id,
  cleaned_at_utc,
  code_revision
FROM psa_poverty_stat_classified
WHERE quarantine_reasons = '';

COMMENT ON TABLE edu_access.`03-silver`.psa_poverty_stat_clean_candidate IS 'Unpublished build for the Silver gate, which may have failed. Do not read: use psa_poverty_stat_clean, trusted by the run its rows carry (D-025).';
ALTER TABLE edu_access.`03-silver`.psa_poverty_stat_clean_candidate OWNER TO `reached-hq`;

-- Candidates set aside, never deleted: the Bronze row, and why.
CREATE OR REPLACE TABLE edu_access.`03-silver`.psa_poverty_stat_quarantine_candidate USING DELTA AS
SELECT
  estimate_year,
  psgc_id,
  region,
  split(quarantine_reasons, ',') AS quarantine_reasons,
  logical_dataset,
  estimate_years_covered,
  batch_id,
  delivery_version,
  schema_version,
  source_sha256,
  source_row_number,
  run_id,
  cleaned_at_utc,
  code_revision
FROM psa_poverty_stat_classified
WHERE quarantine_reasons <> '';

COMMENT ON TABLE edu_access.`03-silver`.psa_poverty_stat_quarantine_candidate IS 'Unpublished build for the Silver gate, which may have failed. Do not read: use psa_poverty_stat_quarantine, trusted by the run its rows carry (D-025).';
ALTER TABLE edu_access.`03-silver`.psa_poverty_stat_quarantine_candidate OWNER TO `reached-hq`;
