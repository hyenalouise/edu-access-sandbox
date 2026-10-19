-- Gold build for fact_school_enrollment (D-048, D-047): one row per school, school year and education level
-- (ES, JHS, SHS) for every enrollment Silver row, all sectors (Analytics applies the AP scope).
-- learner_count follows the metric specification's enrollment rules:
--   not offered                          0 (the gate fails if a cell is positive anyway)
--   offered, every applicable cell set   the sum of the cells; a recorded zero counts as zero
--   offered, any applicable cell blank   NULL, never a partial sum
--   offering flag NULL                   NULL, and the gate fails
-- Applicable cells are the level's columns in the metric specification. The g11/g12 'unique' strand counts
-- apply from SY 2024-25 and the g11 SSHS counts from SY 2025-26 (DepEd's published start years); a column
-- is never treated as inapplicable because it happens to be blank.
-- Geography is the school map's (D-049) for that school year: a matched city and barangay keep their PSGC
-- codes; a matched city with no matched barangay uses the city's UNK-<code> barangay; an unmatched or
-- ambiguous city uses UNKNOWN, and an excluded one EXCLUDED (dim_city_municipality, dim_barangay).
-- psgc_match_status is the city-level map status, kept even where a technical member is used.
--
-- Writes fact_school_enrollment_candidate; the gate publishes it only if no check fails.
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
ON t.run_id = s.run_id AND t.pipeline_name = 'gold_build' AND t.source_id = 'fact_school_enrollment'
WHEN MATCHED THEN UPDATE SET
  status = 'running', started_at_utc = session.gold_built_at_utc, finished_at_utc = NULL,
  failure_stage = NULL, error_message = NULL, code_revision = session.gold_code_revision, job_run_id = s.run_id
WHEN NOT MATCHED THEN INSERT (run_id, pipeline_name, source_id, environment, status, started_at_utc, code_revision, job_run_id)
  VALUES (s.run_id, 'gold_build', 'fact_school_enrollment', session.gold_environment, 'running',
          session.gold_built_at_utc, session.gold_code_revision, s.run_id);

CREATE SCHEMA IF NOT EXISTS edu_access.`05-gold`;
ALTER SCHEMA edu_access.`05-gold` OWNER TO `reached-hq`;

CREATE OR REPLACE TABLE edu_access.`05-gold`.fact_school_enrollment_candidate USING DELTA AS
WITH levels AS (
SELECT school_year, school_id, 'ES' AS education_level_code, offers_es AS is_offered,
       CASE WHEN offers_es IS NULL THEN CAST(NULL AS BIGINT)
            WHEN NOT offers_es THEN CAST(0 AS BIGINT)
            ELSE CAST(kinder_male AS BIGINT) + CAST(kinder_female AS BIGINT) + CAST(g1_male AS BIGINT) + CAST(g1_female AS BIGINT) +
          CAST(g2_male AS BIGINT) + CAST(g2_female AS BIGINT) + CAST(g3_male AS BIGINT) + CAST(g3_female AS BIGINT) +
          CAST(g4_male AS BIGINT) + CAST(g4_female AS BIGINT) + CAST(g5_male AS BIGINT) + CAST(g5_female AS BIGINT) +
          CAST(g6_male AS BIGINT) + CAST(g6_female AS BIGINT) + CAST(esng_male AS BIGINT) + CAST(esng_female AS BIGINT)
       END AS learner_count
FROM edu_access.`03-silver`.deped_enrollment_clean
UNION ALL
SELECT school_year, school_id, 'JHS' AS education_level_code, offers_jhs AS is_offered,
       CASE WHEN offers_jhs IS NULL THEN CAST(NULL AS BIGINT)
            WHEN NOT offers_jhs THEN CAST(0 AS BIGINT)
            ELSE CAST(g7_male AS BIGINT) + CAST(g7_female AS BIGINT) + CAST(g8_male AS BIGINT) + CAST(g8_female AS BIGINT) +
          CAST(g9_male AS BIGINT) + CAST(g9_female AS BIGINT) + CAST(g10_male AS BIGINT) + CAST(g10_female AS BIGINT) +
          CAST(jhsng_male AS BIGINT) + CAST(jhsng_female AS BIGINT)
       END AS learner_count
FROM edu_access.`03-silver`.deped_enrollment_clean
UNION ALL
SELECT school_year, school_id, 'SHS' AS education_level_code, offers_shs AS is_offered,
       CASE WHEN offers_shs IS NULL THEN CAST(NULL AS BIGINT)
            WHEN NOT offers_shs THEN CAST(0 AS BIGINT)
            ELSE CAST(g11_abm_male AS BIGINT) + CAST(g11_abm_female AS BIGINT) + CAST(g11_arts_male AS BIGINT) + CAST(g11_arts_female AS BIGINT) +
          CAST(g11_gas_male AS BIGINT) + CAST(g11_gas_female AS BIGINT) + CAST(g11_humss_male AS BIGINT) + CAST(g11_humss_female AS BIGINT) +
          CAST(g11_maritime_male AS BIGINT) + CAST(g11_maritime_female AS BIGINT) + CAST(g11_sports_male AS BIGINT) + CAST(g11_sports_female AS BIGINT) +
          CAST(g11_stem_male AS BIGINT) + CAST(g11_stem_female AS BIGINT) + CAST(g11_tvl_male AS BIGINT) + CAST(g11_tvl_female AS BIGINT) +
          CAST(g12_abm_male AS BIGINT) + CAST(g12_abm_female AS BIGINT) + CAST(g12_arts_male AS BIGINT) + CAST(g12_arts_female AS BIGINT) +
          CAST(g12_gas_male AS BIGINT) + CAST(g12_gas_female AS BIGINT) + CAST(g12_humss_male AS BIGINT) + CAST(g12_humss_female AS BIGINT) +
          CAST(g12_maritime_male AS BIGINT) + CAST(g12_maritime_female AS BIGINT) + CAST(g12_sports_male AS BIGINT) + CAST(g12_sports_female AS BIGINT) +
          CAST(g12_stem_male AS BIGINT) + CAST(g12_stem_female AS BIGINT) + CAST(g12_tvl_male AS BIGINT) + CAST(g12_tvl_female AS BIGINT)
          + CASE WHEN school_year >= '2024-25' THEN CAST(g11_unique_male AS BIGINT) + CAST(g11_unique_female AS BIGINT) + CAST(g12_unique_male AS BIGINT) + CAST(g12_unique_female AS BIGINT) ELSE 0 END
          + CASE WHEN school_year >= '2025-26' THEN CAST(g11_sshs_acad_male AS BIGINT) + CAST(g11_sshs_acad_female AS BIGINT) + CAST(g11_sshs_techpro_male AS BIGINT) + CAST(g11_sshs_techpro_female AS BIGINT) ELSE 0 END
       END AS learner_count
FROM edu_access.`03-silver`.deped_enrollment_clean
),
geo AS (
  SELECT e.school_year, e.school_id, e.sector, e.annex_status,
         c.match_status AS psgc_match_status,
         CASE WHEN c.match_status = 'matched' THEN c.psgc_code
              WHEN c.match_status = 'excluded' THEN 'EXCLUDED'
              ELSE 'UNKNOWN' END AS city_mun_psgc_code,
         CASE WHEN c.match_status = 'excluded' THEN 'EXCLUDED'
              WHEN c.match_status IS DISTINCT FROM 'matched' THEN 'UNKNOWN'
              WHEN b.match_status = 'matched' THEN b.psgc_code
              ELSE 'UNK-' || c.psgc_code END AS barangay_psgc_code
  FROM edu_access.`03-silver`.deped_enrollment_clean AS e
  LEFT JOIN edu_access.`04-integration`.deped_school_psgc_map AS c
    ON c.school_year = e.school_year AND c.school_id = e.school_id AND c.geographic_level = 'city_mun'
  LEFT JOIN edu_access.`04-integration`.deped_school_psgc_map AS b
    ON b.school_year = e.school_year AND b.school_id = e.school_id AND b.geographic_level = 'bgy'
)
SELECT l.school_id, l.school_year, l.education_level_code,
       g.city_mun_psgc_code, g.barangay_psgc_code, g.psgc_match_status,
       g.sector, g.annex_status, l.is_offered, l.learner_count
FROM levels AS l
JOIN geo AS g ON g.school_year = l.school_year AND g.school_id = l.school_id;

ALTER TABLE edu_access.`05-gold`.fact_school_enrollment_candidate OWNER TO `reached-hq`;
