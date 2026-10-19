-- Gold build for dim_city_municipality (D-048): one row per PSGC 2Q 2026 city or municipality (the 1,642
-- regular members), plus two technical members so no fact needs a NULL geography key:
--   UNKNOWN   member_type 'unknown': a school whose city could not be matched (unmatched or ambiguous)
--   EXCLUDED  member_type 'excluded': kept outside city analysis on purpose (Philippine Schools Overseas,
--             schools the school map excludes, and the 2020 Special Geographic Area census clusters)
-- The province is the PSGC province above the unit; highly urbanized cities and the NCR units have none,
-- and Isabela City's parent is PSGC's 'City of Isabela (Not a Province)' container. land_area_sqkm is
-- HDX's area for the matched ADM3 feature (D-042); the 8 Special Geographic Area municipalities have no
-- HDX feature and keep NULL. is_sga marks the units under PSGC's Special Geographic Area (1999900000).
--
-- Writes dim_city_municipality_candidate; the gate publishes it only if no check fails.
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
ON t.run_id = s.run_id AND t.pipeline_name = 'gold_build' AND t.source_id = 'dim_city_municipality'
WHEN MATCHED THEN UPDATE SET
  status = 'running', started_at_utc = session.gold_built_at_utc, finished_at_utc = NULL,
  failure_stage = NULL, error_message = NULL, code_revision = session.gold_code_revision, job_run_id = s.run_id
WHEN NOT MATCHED THEN INSERT (run_id, pipeline_name, source_id, environment, status, started_at_utc, code_revision, job_run_id)
  VALUES (s.run_id, 'gold_build', 'dim_city_municipality', session.gold_environment, 'running',
          session.gold_built_at_utc, session.gold_code_revision, s.run_id);

CREATE SCHEMA IF NOT EXISTS edu_access.`05-gold`;
ALTER SCHEMA edu_access.`05-gold` OWNER TO `reached-hq`;

CREATE OR REPLACE TABLE edu_access.`05-gold`.dim_city_municipality_candidate USING DELTA AS
WITH p AS (
  SELECT * FROM edu_access.`03-silver`.psa_psgc_clean WHERE is_master_reference
),
area AS (
  SELECT m.psgc_code, h.area_sqkm
  FROM edu_access.`04-integration`.hdx_adm3_psgc_map AS m
  JOIN edu_access.`03-silver`.hdx_adm3_clean AS h ON h.adm3_pcode = m.adm3_pcode
  WHERE m.match_status = 'matched'
)
SELECT u.psgc_code AS city_mun_psgc_code,
       u.name AS city_mun_name,
       u.province_code AS province_psgc_code,
       pr.name AS province_name,
       u.region_code AS region_psgc_code,
       rg.name AS region_name,
       CASE u.geographic_level WHEN 'City' THEN 'City' ELSE 'Municipality' END AS lgu_type,
       u.city_class,
       u.income_class,
       u.income_class_retained_after_downgrade AS income_class_retained,
       CAST(a.area_sqkm AS DECIMAL(18,4)) AS land_area_sqkm,
       CASE WHEN a.area_sqkm IS NOT NULL THEN 'HDX COD-AB ADM3 area_sqkm' END AS land_area_source,
       COALESCE(u.province_code = '1999900000', FALSE) AS is_sga,
       'regular' AS member_type,
       u.publication_period AS source_psgc_quarter
FROM p AS u
LEFT JOIN p AS pr ON pr.psgc_code = u.province_code
LEFT JOIN p AS rg ON rg.psgc_code = u.region_code
LEFT JOIN area AS a ON a.psgc_code = u.psgc_code
WHERE u.geographic_level IN ('City', 'Mun')
UNION ALL
SELECT t.code, t.name, CAST(NULL AS STRING), CAST(NULL AS STRING), CAST(NULL AS STRING), CAST(NULL AS STRING),
       CAST(NULL AS STRING), CAST(NULL AS STRING), CAST(NULL AS STRING), CAST(NULL AS BOOLEAN),
       CAST(NULL AS DECIMAL(18,4)), CAST(NULL AS STRING), FALSE, t.member_type,
       (SELECT MIN(publication_period) FROM edu_access.`03-silver`.psa_psgc_clean WHERE is_master_reference)
FROM (VALUES
  ('UNKNOWN', 'Unknown city or municipality', 'unknown'),
  ('EXCLUDED', 'Excluded from city analysis', 'excluded')
) AS t(code, name, member_type);

ALTER TABLE edu_access.`05-gold`.dim_city_municipality_candidate OWNER TO `reached-hq`;
