-- Gold build for fact_school_enrollment (D-047, D-048, D-050, docs/architecture/data-model.md).
--
-- One row per school, school year and education level (ES, JHS, SHS), key (school_id, school_year,
-- education_level_code): three rows for every deped_enrollment_clean row, overseas schools included, so
-- no enrolment row is lost. Each row carries that school year's geography, so a school that moves is
-- counted where it was that year (D-048).
--
-- Reads published tables only: deped_enrollment_clean and deped_school_psgc_map (D-049). Writes
-- fact_school_enrollment_candidate: the data model's columns plus three audit columns (applicable_cells,
-- null_cells, published_cell_sum) that the gate reads and does not publish. The gate (the next task)
-- checks it and publishes fact_school_enrollment only if no check fails, so a FAIL keeps the last good
-- build. It rebuilds on every run.
--
-- Rules:
--   - Levels and their count columns are the metric specification's ("Enrollment by level", D-047): ES is
--     Kindergarten, Grades 1-6 and ES non-graded (16 cells); JHS is Grades 7-10 and JHS non-graded (10);
--     SHS is the eight Grade 11 and 12 strands (32), plus the unique-strand cells from SY 2024-25 (4) and
--     the Strengthened SHS cells from SY 2025-26 (4). A cell before the year DepEd started it is not
--     applicable, so it is never read as missing.
--   - learner_count ("Enrollment aggregation and missingness"): 0 when the level is not offered; the sum
--     of the applicable cells when it is offered and every cell is published (a published 0 counts as 0);
--     NULL when it is offered and any cell is blank, never a partial sum; NULL when the offering flag is
--     blank, which the gate fails. The offering is never inferred from the counts.
--   - Geography comes from the map's two rows for the school year (city_mun and bgy). A matched city or
--     municipality keeps its PSGC code; an unmatched or ambiguous one takes the UNKNOWN member and an
--     excluded one (Philippine Schools Overseas, Special Geographic Area schools under D-031) the EXCLUDED
--     member of dim_city_municipality. A matched barangay keeps its code; a matched city or municipality
--     with no single barangay takes its own '<code>-UNKNOWN' member of dim_barangay, and an unknown or
--     excluded city takes the UNKNOWN or EXCLUDED barangay. psgc_match_status is the city or municipality
--     status, kept even where a technical member stands in for the code.
--   - sector and annex_status are Silver's, as published.

-- Sandbox: the run starts in pipeline_runs as gold_build, like Silver and Integration; the gate records how it ended.
DECLARE OR REPLACE VARIABLE gold_run_id STRING;
SET VARIABLE gold_run_id = :run_id;
DECLARE OR REPLACE VARIABLE gold_code_revision STRING;
SET VARIABLE gold_code_revision = COALESCE(NULLIF(:code_revision, ''), 'UNSET');
DECLARE OR REPLACE VARIABLE gold_environment STRING;
SET VARIABLE gold_environment = COALESCE(NULLIF(:environment, ''), 'UNSET');
DECLARE OR REPLACE VARIABLE gold_built_at_utc TIMESTAMP;
SET VARIABLE gold_built_at_utc = current_timestamp();

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
WITH enrollment AS (
  SELECT e.*,
    CAST(substr(e.school_year, 1, 4) AS INT) >= 2024 AS from_2024_25,
    CAST(substr(e.school_year, 1, 4) AS INT) >= 2025 AS from_2025_26
  FROM edu_access.`03-silver`.deped_enrollment_clean AS e
),
levels AS (
  SELECT school_id, school_year, sector, annex_status, 'ES' AS education_level_code, offers_es AS is_offered,
    16 AS applicable_cells,
      CAST(kinder_male IS NULL AS INT) + CAST(kinder_female IS NULL AS INT) +
      CAST(g1_male IS NULL AS INT) + CAST(g1_female IS NULL AS INT) + CAST(g2_male IS NULL AS INT) +
      CAST(g2_female IS NULL AS INT) + CAST(g3_male IS NULL AS INT) + CAST(g3_female IS NULL AS INT) +
      CAST(g4_male IS NULL AS INT) + CAST(g4_female IS NULL AS INT) + CAST(g5_male IS NULL AS INT) +
      CAST(g5_female IS NULL AS INT) + CAST(g6_male IS NULL AS INT) + CAST(g6_female IS NULL AS INT) +
      CAST(esng_male IS NULL AS INT) + CAST(esng_female IS NULL AS INT) AS null_cells,
      COALESCE(kinder_male, 0) + COALESCE(kinder_female, 0) + COALESCE(g1_male, 0) +
      COALESCE(g1_female, 0) + COALESCE(g2_male, 0) + COALESCE(g2_female, 0) + COALESCE(g3_male, 0) +
      COALESCE(g3_female, 0) + COALESCE(g4_male, 0) + COALESCE(g4_female, 0) + COALESCE(g5_male, 0) +
      COALESCE(g5_female, 0) + COALESCE(g6_male, 0) + COALESCE(g6_female, 0) + COALESCE(esng_male, 0) +
      COALESCE(esng_female, 0) AS published_cell_sum
  FROM enrollment
  UNION ALL
  SELECT school_id, school_year, sector, annex_status, 'JHS', offers_jhs,
    10,
      CAST(g7_male IS NULL AS INT) + CAST(g7_female IS NULL AS INT) + CAST(g8_male IS NULL AS INT) +
      CAST(g8_female IS NULL AS INT) + CAST(g9_male IS NULL AS INT) + CAST(g9_female IS NULL AS INT) +
      CAST(g10_male IS NULL AS INT) + CAST(g10_female IS NULL AS INT) +
      CAST(jhsng_male IS NULL AS INT) + CAST(jhsng_female IS NULL AS INT),
      COALESCE(g7_male, 0) + COALESCE(g7_female, 0) + COALESCE(g8_male, 0) + COALESCE(g8_female, 0) +
      COALESCE(g9_male, 0) + COALESCE(g9_female, 0) + COALESCE(g10_male, 0) + COALESCE(g10_female, 0) +
      COALESCE(jhsng_male, 0) + COALESCE(jhsng_female, 0)
  FROM enrollment
  UNION ALL
  SELECT school_id, school_year, sector, annex_status, 'SHS', offers_shs,
    32 + CASE WHEN from_2024_25 THEN 4 ELSE 0 END + CASE WHEN from_2025_26 THEN 4 ELSE 0 END,
      CAST(g11_abm_male IS NULL AS INT) + CAST(g11_abm_female IS NULL AS INT) +
      CAST(g11_arts_male IS NULL AS INT) + CAST(g11_arts_female IS NULL AS INT) +
      CAST(g11_gas_male IS NULL AS INT) + CAST(g11_gas_female IS NULL AS INT) +
      CAST(g11_humss_male IS NULL AS INT) + CAST(g11_humss_female IS NULL AS INT) +
      CAST(g11_maritime_male IS NULL AS INT) + CAST(g11_maritime_female IS NULL AS INT) +
      CAST(g11_sports_male IS NULL AS INT) + CAST(g11_sports_female IS NULL AS INT) +
      CAST(g11_stem_male IS NULL AS INT) + CAST(g11_stem_female IS NULL AS INT) +
      CAST(g11_tvl_male IS NULL AS INT) + CAST(g11_tvl_female IS NULL AS INT) +
      CAST(g12_abm_male IS NULL AS INT) + CAST(g12_abm_female IS NULL AS INT) +
      CAST(g12_arts_male IS NULL AS INT) + CAST(g12_arts_female IS NULL AS INT) +
      CAST(g12_gas_male IS NULL AS INT) + CAST(g12_gas_female IS NULL AS INT) +
      CAST(g12_humss_male IS NULL AS INT) + CAST(g12_humss_female IS NULL AS INT) +
      CAST(g12_maritime_male IS NULL AS INT) + CAST(g12_maritime_female IS NULL AS INT) +
      CAST(g12_sports_male IS NULL AS INT) + CAST(g12_sports_female IS NULL AS INT) +
      CAST(g12_stem_male IS NULL AS INT) + CAST(g12_stem_female IS NULL AS INT) +
      CAST(g12_tvl_male IS NULL AS INT) + CAST(g12_tvl_female IS NULL AS INT) +
      CAST(g11_unique_male IS NULL AND from_2024_25 AS INT) +
      CAST(g11_unique_female IS NULL AND from_2024_25 AS INT) +
      CAST(g12_unique_male IS NULL AND from_2024_25 AS INT) +
      CAST(g12_unique_female IS NULL AND from_2024_25 AS INT) +
      CAST(g11_sshs_acad_male IS NULL AND from_2025_26 AS INT) +
      CAST(g11_sshs_acad_female IS NULL AND from_2025_26 AS INT) +
      CAST(g11_sshs_techpro_male IS NULL AND from_2025_26 AS INT) +
      CAST(g11_sshs_techpro_female IS NULL AND from_2025_26 AS INT),
      COALESCE(g11_abm_male, 0) + COALESCE(g11_abm_female, 0) + COALESCE(g11_arts_male, 0) +
      COALESCE(g11_arts_female, 0) + COALESCE(g11_gas_male, 0) + COALESCE(g11_gas_female, 0) +
      COALESCE(g11_humss_male, 0) + COALESCE(g11_humss_female, 0) + COALESCE(g11_maritime_male, 0) +
      COALESCE(g11_maritime_female, 0) + COALESCE(g11_sports_male, 0) +
      COALESCE(g11_sports_female, 0) + COALESCE(g11_stem_male, 0) + COALESCE(g11_stem_female, 0) +
      COALESCE(g11_tvl_male, 0) + COALESCE(g11_tvl_female, 0) + COALESCE(g12_abm_male, 0) +
      COALESCE(g12_abm_female, 0) + COALESCE(g12_arts_male, 0) + COALESCE(g12_arts_female, 0) +
      COALESCE(g12_gas_male, 0) + COALESCE(g12_gas_female, 0) + COALESCE(g12_humss_male, 0) +
      COALESCE(g12_humss_female, 0) + COALESCE(g12_maritime_male, 0) +
      COALESCE(g12_maritime_female, 0) + COALESCE(g12_sports_male, 0) +
      COALESCE(g12_sports_female, 0) + COALESCE(g12_stem_male, 0) + COALESCE(g12_stem_female, 0) +
      COALESCE(g12_tvl_male, 0) + COALESCE(g12_tvl_female, 0) +
      CASE WHEN from_2024_25 THEN COALESCE(g11_unique_male, 0) ELSE 0 END +
      CASE WHEN from_2024_25 THEN COALESCE(g11_unique_female, 0) ELSE 0 END +
      CASE WHEN from_2024_25 THEN COALESCE(g12_unique_male, 0) ELSE 0 END +
      CASE WHEN from_2024_25 THEN COALESCE(g12_unique_female, 0) ELSE 0 END +
      CASE WHEN from_2025_26 THEN COALESCE(g11_sshs_acad_male, 0) ELSE 0 END +
      CASE WHEN from_2025_26 THEN COALESCE(g11_sshs_acad_female, 0) ELSE 0 END +
      CASE WHEN from_2025_26 THEN COALESCE(g11_sshs_techpro_male, 0) ELSE 0 END +
      CASE WHEN from_2025_26 THEN COALESCE(g11_sshs_techpro_female, 0) ELSE 0 END
  FROM enrollment
),
city AS (
  SELECT school_year, school_id, psgc_code, match_status
  FROM edu_access.`04-integration`.deped_school_psgc_map
  WHERE geographic_level = 'city_mun'
),
barangay AS (
  SELECT school_year, school_id, psgc_code, match_status
  FROM edu_access.`04-integration`.deped_school_psgc_map
  WHERE geographic_level = 'bgy'
),
geography AS (
  SELECT
    c.school_year,
    c.school_id,
    c.match_status AS psgc_match_status,
    CASE c.match_status
      WHEN 'matched' THEN c.psgc_code
      WHEN 'excluded' THEN 'EXCLUDED'
      WHEN 'unmatched' THEN 'UNKNOWN'
      WHEN 'ambiguous' THEN 'UNKNOWN'
    END AS city_mun_psgc_code,
    CASE
      WHEN c.match_status = 'matched' AND b.match_status = 'matched' THEN b.psgc_code
      WHEN c.match_status = 'matched' THEN c.psgc_code || '-UNKNOWN'
      WHEN c.match_status = 'excluded' THEN 'EXCLUDED'
      WHEN c.match_status IN ('unmatched', 'ambiguous') THEN 'UNKNOWN'
    END AS barangay_psgc_code
  FROM city AS c
  LEFT JOIN barangay AS b ON b.school_year = c.school_year AND b.school_id = c.school_id
)
SELECT
  l.school_id,
  l.school_year,
  l.education_level_code,
  g.city_mun_psgc_code,
  g.barangay_psgc_code,
  g.psgc_match_status,
  l.sector,
  l.annex_status,
  l.is_offered,
  CAST(CASE
    WHEN l.is_offered IS NULL THEN NULL
    WHEN NOT l.is_offered THEN 0
    WHEN l.null_cells = 0 THEN l.published_cell_sum
  END AS BIGINT) AS learner_count,
  l.applicable_cells,
  l.null_cells,
  CAST(l.published_cell_sum AS BIGINT) AS published_cell_sum
FROM levels AS l
LEFT JOIN geography AS g ON g.school_year = l.school_year AND g.school_id = l.school_id;

COMMENT ON TABLE edu_access.`05-gold`.fact_school_enrollment_candidate IS 'Unpublished build for the Gold gate, which may have failed. Do not read: use fact_school_enrollment.';
ALTER TABLE edu_access.`05-gold`.fact_school_enrollment_candidate OWNER TO `reached-hq`;
