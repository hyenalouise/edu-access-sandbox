-- Gold build for dim_barangay (D-048): one row per PSGC 2Q 2026 barangay, plus technical members:
--   UNK-<city code>  member_type 'unknown', one per regular city or municipality: a school matched to the
--                    city but not to one of its barangays still rolls up to that city
--   UNKNOWN          member_type 'unknown', under city UNKNOWN: the city itself is not matched
--   EXCLUDED         member_type 'excluded', under city EXCLUDED
-- A barangay's city is its PSGC parent; Manila's barangays sit under its 14 sub-municipalities, which roll
-- up to the City of Manila by their first five digits (as the school map does).
--
-- Writes dim_barangay_candidate; the gate publishes it only if no check fails.
--
-- Parameters, supplied by the job (or src/job/local_run.py):
--   :run_id, :code_revision, :environment

DECLARE OR REPLACE VARIABLE gold_run_id STRING;
SET VARIABLE gold_run_id = :run_id;
DECLARE OR REPLACE VARIABLE gold_code_revision STRING;
SET VARIABLE gold_code_revision = COALESCE(NULLIF(:code_revision, ''), 'UNSET');
DECLARE OR REPLACE VARIABLE gold_environment STRING;
SET VARIABLE gold_environment = COALESCE(NULLIF(:environment, ''), 'UNSET');
DECLARE OR REPLACE VARIABLE gold_built_at_utc TIMESTAMP;
SET VARIABLE gold_built_at_utc = current_timestamp();

-- The run starts; the gate records how it ended (D-020).
MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (SELECT session.gold_run_id AS run_id) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'gold_build' AND t.source_id = 'dim_barangay'
WHEN MATCHED THEN UPDATE SET
  status = 'running', started_at_utc = session.gold_built_at_utc, finished_at_utc = NULL,
  failure_stage = NULL, error_message = NULL, code_revision = session.gold_code_revision, job_run_id = s.run_id
WHEN NOT MATCHED THEN INSERT (run_id, pipeline_name, source_id, environment, status, started_at_utc, code_revision, job_run_id)
  VALUES (s.run_id, 'gold_build', 'dim_barangay', session.gold_environment, 'running',
          session.gold_built_at_utc, session.gold_code_revision, s.run_id);

CREATE SCHEMA IF NOT EXISTS edu_access.`05-gold`;
ALTER SCHEMA edu_access.`05-gold` OWNER TO `reached-hq`;

CREATE OR REPLACE TABLE edu_access.`05-gold`.dim_barangay_candidate USING DELTA AS
WITH p AS (
  SELECT * FROM edu_access.`03-silver`.psa_psgc_clean WHERE is_master_reference
)
SELECT b.psgc_code AS barangay_psgc_code,
       b.name AS barangay_name,
       CASE WHEN parent.geographic_level = 'SubMun' THEN substr(b.city_municipality_code, 1, 5) || '00000'
            ELSE b.city_municipality_code END AS city_mun_psgc_code,
       b.urban_rural,
       'regular' AS member_type
FROM p AS b
LEFT JOIN p AS parent ON parent.psgc_code = b.city_municipality_code
WHERE b.geographic_level = 'Bgy'
UNION ALL
SELECT 'UNK-' || psgc_code, 'Unknown barangay', psgc_code, CAST(NULL AS STRING), 'unknown'
FROM p WHERE geographic_level IN ('City', 'Mun')
UNION ALL
SELECT t.code, t.name, t.city, CAST(NULL AS STRING), t.member_type
FROM (VALUES
  ('UNKNOWN', 'Unknown barangay', 'UNKNOWN', 'unknown'),
  ('EXCLUDED', 'Excluded from city analysis', 'EXCLUDED', 'excluded')
) AS t(code, name, city, member_type);

ALTER TABLE edu_access.`05-gold`.dim_barangay_candidate OWNER TO `reached-hq`;
