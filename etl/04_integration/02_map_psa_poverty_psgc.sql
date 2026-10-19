-- Integration build for psa_poverty_stat (#92, D-054).
--
-- Rebuilds psa_poverty_psgc_map_candidate: one row per row of the published psa_poverty_stat_clean
-- (psgc_id, estimate_year), matched to the master PSGC quarter in psa_psgc_clean by one rule only:
-- Silver's correspondence_code (the six-digit psgc_id followed by 000, D-034) equals PSGC's
-- correspondence_code (D-030). There is no name rule and no override: a row the code does not place
-- is kept as unmatched, one whose code names two or more PSGC units as ambiguous, both pending review.
-- Names are compared, never used to match: names_agree marks the rows whose PSA name differs from
-- the PSGC name, and the gate counts them for review (D-030).
-- The estimate, its CV, SE and 90% limits, its status and flags are copied unchanged from Silver, so
-- each estimate stays on its own row. Manila's 14 sub-municipalities match their own PSGC
-- sub-municipality codes (geographic_level 'sub_mun') and are never combined into a City of Manila
-- value (D-046). No row is dropped. The map table (psa_poverty_psgc_map) is never written here: the
-- gate checks the candidate and publishes it only if no check fails (as D-025 does for Silver).
--
-- Parameters, supplied by the job (or src/job/local_run.py):
--   :run_id, :code_revision, :environment

DECLARE OR REPLACE VARIABLE integration_run_id STRING;
SET VARIABLE integration_run_id = :run_id;
DECLARE OR REPLACE VARIABLE integration_code_revision STRING;
SET VARIABLE integration_code_revision = COALESCE(NULLIF(:code_revision, ''), 'UNSET');
DECLARE OR REPLACE VARIABLE integration_environment STRING;
SET VARIABLE integration_environment = COALESCE(NULLIF(:environment, ''), 'UNSET');
DECLARE OR REPLACE VARIABLE integration_built_at_utc TIMESTAMP;
SET VARIABLE integration_built_at_utc = current_timestamp();

-- The run starts; the gate records how it ended (D-020).
MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (SELECT session.integration_run_id AS run_id) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'integration_build' AND t.source_id = 'psa_poverty_stat'
WHEN MATCHED THEN UPDATE SET
  status = 'running', started_at_utc = session.integration_built_at_utc, finished_at_utc = NULL,
  failure_stage = NULL, error_message = NULL, code_revision = session.integration_code_revision, job_run_id = s.run_id
WHEN NOT MATCHED THEN INSERT (run_id, pipeline_name, source_id, environment, status, started_at_utc, code_revision, job_run_id)
  VALUES (s.run_id, 'integration_build', 'psa_poverty_stat', session.integration_environment, 'running',
          session.integration_built_at_utc, session.integration_code_revision, s.run_id);

CREATE SCHEMA IF NOT EXISTS edu_access.`04-integration`;
ALTER SCHEMA edu_access.`04-integration` OWNER TO `reached-hq`;

CREATE OR REPLACE TEMPORARY VIEW psa_poverty_psgc_matched AS
-- The master PSGC quarter, and the units a PSA small-area estimate can be for: cities, municipalities
-- and Manila's sub-municipalities (profile X-1). A unit without a Correspondence Code cannot be reached.
WITH psgc AS (
  SELECT psgc_code, name, correspondence_code, geographic_level, publication_period, batch_id, source_row_number
  FROM edu_access.`03-silver`.psa_psgc_clean WHERE is_master_reference
),
units AS (
  SELECT * FROM psgc WHERE geographic_level IN ('City', 'Mun', 'SubMun') AND correspondence_code IS NOT NULL
),
pv AS (SELECT * FROM edu_access.`03-silver`.psa_poverty_stat_clean),
-- How many units each row's code names. MIN is read only when exactly one does.
hits AS (
  SELECT pv.psgc_id, pv.estimate_year, COUNT(u.psgc_code) AS hits, MIN(u.psgc_code) AS psgc_code
  FROM pv LEFT JOIN units AS u ON u.correspondence_code = pv.correspondence_code
  GROUP BY pv.psgc_id, pv.estimate_year
),
decided AS (
  SELECT pv.*,
    CASE WHEN h.hits = 1 THEN h.psgc_code END AS matched_code,
    CASE WHEN h.hits = 1 THEN 'matched' WHEN h.hits > 1 THEN 'ambiguous' ELSE 'unmatched' END AS match_status,
    CASE WHEN h.hits = 1 THEN 'correspondence_code' END AS match_method,
    CASE WHEN h.hits = 1 THEN 'rule' ELSE 'pending' END AS review_status,
    h.hits
  FROM pv JOIN hits AS h ON h.psgc_id = pv.psgc_id AND h.estimate_year = pv.estimate_year
)
SELECT
  'psa_poverty_stat' AS source_id,
  d.psgc_id || '/' || CAST(d.estimate_year AS STRING) AS source_row_ref,
  d.psgc_id,
  d.correspondence_code,
  d.municipality,
  d.region,
  d.estimate_year,
  (SELECT MIN(publication_period) FROM psgc) AS psgc_version,
  d.matched_code AS psgc_code,
  p.name AS psgc_name,
  CASE p.geographic_level WHEN 'City' THEN 'city_mun' WHEN 'Mun' THEN 'city_mun' WHEN 'SubMun' THEN 'sub_mun' END AS geographic_level,
  d.match_status,
  d.match_method,
  d.review_status,
  CASE WHEN d.hits > 1 THEN CAST(d.hits AS STRING) || ' PSGC units share this Correspondence Code: not one-to-one (D-030), review'
       WHEN d.hits = 0 THEN 'no PSGC city, municipality or sub-municipality of the master quarter has this Correspondence Code'
       WHEN upper(COALESCE(d.municipality, '')) <> upper(p.name) THEN 'PSA name differs from the PSGC name: listed for review (D-030)'
       END AS reason,
  CASE WHEN d.matched_code IS NOT NULL THEN upper(COALESCE(d.municipality, '')) = upper(p.name) END AS names_agree,
  d.poverty_incidence,
  d.coefficient_of_variation,
  d.standard_error,
  d.ci90_lower_limit,
  d.ci90_upper_limit,
  d.estimate_status,
  d.cv_over_20,
  d.se_cv_inconsistent,
  d.lower_limit_not_positive,
  d.logical_dataset,
  d.estimate_years_covered,
  d.delivery_version,
  d.batch_id,
  d.source_sha256,
  d.source_row_number,
  p.batch_id AS psgc_batch_id,
  p.source_row_number AS psgc_source_row_number,
  session.integration_run_id AS run_id,
  session.integration_built_at_utc AS built_at_utc,
  session.integration_code_revision AS code_revision
FROM decided AS d
LEFT JOIN psgc AS p ON p.psgc_code = d.matched_code;

CREATE OR REPLACE TABLE edu_access.`04-integration`.psa_poverty_psgc_map_candidate USING DELTA AS
SELECT
  source_id,
  source_row_ref,
  psgc_id,
  correspondence_code,
  municipality,
  region,
  estimate_year,
  psgc_version,
  psgc_code,
  psgc_name,
  geographic_level,
  match_status,
  match_method,
  review_status,
  reason,
  names_agree,
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
  delivery_version,
  batch_id,
  source_sha256,
  source_row_number,
  psgc_batch_id,
  psgc_source_row_number,
  run_id,
  built_at_utc,
  code_revision
FROM psa_poverty_psgc_matched;

COMMENT ON TABLE edu_access.`04-integration`.psa_poverty_psgc_map_candidate IS 'Unpublished build for the Integration gate, which may have failed. Do not read: use psa_poverty_psgc_map.';
ALTER TABLE edu_access.`04-integration`.psa_poverty_psgc_map_candidate OWNER TO `reached-hq`;
