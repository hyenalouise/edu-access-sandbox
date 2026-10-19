-- Gold gate for fact_school_enrollment. Checks fact_school_enrollment_candidate against
-- deped_enrollment_clean, deped_school_psgc_map and the five dimensions it points to, writes every result
-- to data_quality_results (layer 'gold'), stops on any FAIL, and only then publishes the data model's
-- columns as fact_school_enrollment. A FAIL keeps the last good build.
--
-- FAIL: a repeated or NULL key; a row count other than three per Silver row; a NULL geography key or
-- match status (a school year with no map row); a match status outside matched, unmatched, ambiguous and
-- excluded, or a geography member that does not follow it; a key that resolves to no dimension member; a
-- barangay outside the row's city or municipality; a matched row on a technical member; a blank offering
-- flag, or a level not offered with a positive count (metric specification rules 1 and 4), in total and
-- by school year and level; a published SHS cell before the school year DepEd started it (it would be left
-- out of learner_count); a learner_count that does not follow the rule; a sector outside DepEd's list;
-- a row that differs from the expected fact recomputed from Silver and the map (a key on one side only,
-- or a different sector, annex_status, is_offered, learner_count, match status, city or barangay); and
-- an upstream run that did not succeed.
-- WARN: schools whose city or municipality is unmatched or ambiguous, matched schools with no single
-- barangay, and, by school year and level, offered levels with some or all cells blank.
-- Counts (PASS): excluded schools, and by school year and level the complete offered rows, the learners
-- and the published cells of partial rows (an audit value, never a learner_count).

DECLARE OR REPLACE VARIABLE gold_gate_started_at_utc TIMESTAMP;
SET VARIABLE gold_gate_started_at_utc = current_timestamp();

-- The expected fact, recomputed from Silver and the map without the build's audit columns, so an error
-- the build makes in both learner_count and its audit columns, or in a carried field, still fails. Plain
-- addition is NULL when any cell is NULL, so an offered level with a blank applicable cell expects NULL.
CREATE OR REPLACE TEMPORARY VIEW fact_school_enrollment_gate_expected AS
WITH silver AS (
  SELECT *, CAST(substr(school_year, 1, 4) AS INT) AS year_start
  FROM edu_access.`03-silver`.deped_enrollment_clean
),
levels AS (
  SELECT school_id, school_year, 'ES' AS education_level_code, sector, annex_status, offers_es AS is_offered,
    kinder_male + kinder_female + g1_male + g1_female + g2_male + g2_female + g3_male + g3_female + g4_male +
    g4_female + g5_male + g5_female + g6_male + g6_female + esng_male + esng_female AS cell_total
  FROM silver
  UNION ALL
  SELECT school_id, school_year, 'JHS', sector, annex_status, offers_jhs,
    g7_male + g7_female + g8_male + g8_female + g9_male + g9_female + g10_male + g10_female + jhsng_male +
    jhsng_female
  FROM silver
  UNION ALL
  SELECT school_id, school_year, 'SHS', sector, annex_status, offers_shs,
    g11_abm_male + g11_abm_female + g11_arts_male + g11_arts_female + g11_gas_male + g11_gas_female +
    g11_humss_male + g11_humss_female + g11_maritime_male + g11_maritime_female + g11_sports_male +
    g11_sports_female + g11_stem_male + g11_stem_female + g11_tvl_male + g11_tvl_female + g12_abm_male +
    g12_abm_female + g12_arts_male + g12_arts_female + g12_gas_male + g12_gas_female + g12_humss_male +
    g12_humss_female + g12_maritime_male + g12_maritime_female + g12_sports_male + g12_sports_female +
    g12_stem_male + g12_stem_female + g12_tvl_male + g12_tvl_female
    + CASE WHEN year_start >= 2024
      THEN g11_unique_male + g11_unique_female + g12_unique_male + g12_unique_female ELSE 0 END
    + CASE WHEN year_start >= 2025
      THEN g11_sshs_acad_male + g11_sshs_acad_female + g11_sshs_techpro_male + g11_sshs_techpro_female ELSE 0 END
  FROM silver
)
SELECT
  l.school_id, l.school_year, l.education_level_code, l.sector, l.annex_status, l.is_offered,
  CASE WHEN l.is_offered IS NULL THEN NULL WHEN NOT l.is_offered THEN 0 ELSE l.cell_total END AS learner_count,
  c.match_status AS map_city_status,
  c.psgc_code AS map_city_code,
  b.match_status AS map_barangay_status,
  b.psgc_code AS map_barangay_code
FROM levels AS l
LEFT JOIN edu_access.`04-integration`.deped_school_psgc_map AS c
  ON c.school_year = l.school_year AND c.school_id = l.school_id AND c.geographic_level = 'city_mun'
LEFT JOIN edu_access.`04-integration`.deped_school_psgc_map AS b
  ON b.school_year = l.school_year AND b.school_id = l.school_id AND b.geographic_level = 'bgy';

-- Computed once into a table, as the Silver gates do: the checks below read it many times.
CREATE OR REPLACE TABLE edu_access.`05-gold`.fact_school_enrollment_gate_summary_candidate USING DELTA AS
WITH fact AS (
  SELECT * FROM edu_access.`05-gold`.fact_school_enrollment_candidate
),
-- One row per school and school year: geography is the same on its three level rows.
school_years AS (
  SELECT * FROM fact WHERE education_level_code = 'ES'
),
-- Each fact row beside its expected row, in one join on the key; a row on one side only counts once.
reconciliation AS (
  SELECT
    COUNT_IF(e.school_id IS NULL OR f.school_id IS NULL) AS rows_not_matching_silver,
    COUNT_IF(f.school_id IS NOT NULL AND e.school_id IS NOT NULL AND f.sector IS DISTINCT FROM e.sector) AS sector_differs,
    COUNT_IF(f.school_id IS NOT NULL AND e.school_id IS NOT NULL
      AND f.annex_status IS DISTINCT FROM e.annex_status) AS annex_status_differs,
    COUNT_IF(f.school_id IS NOT NULL AND e.school_id IS NOT NULL
      AND f.is_offered IS DISTINCT FROM e.is_offered) AS is_offered_differs,
    COUNT_IF(f.school_id IS NOT NULL AND e.school_id IS NOT NULL
      AND f.learner_count IS DISTINCT FROM e.learner_count) AS learner_count_differs,
    COUNT_IF(f.school_id IS NOT NULL AND e.school_id IS NOT NULL
      AND f.psgc_match_status IS DISTINCT FROM e.map_city_status) AS match_status_differs,
    COUNT_IF(f.school_id IS NOT NULL AND e.map_city_status = 'matched'
      AND f.city_mun_psgc_code IS DISTINCT FROM e.map_city_code) AS city_differs,
    COUNT_IF(f.school_id IS NOT NULL AND e.map_city_status = 'matched' AND f.barangay_psgc_code IS DISTINCT FROM
      CASE WHEN e.map_barangay_status = 'matched' THEN e.map_barangay_code ELSE e.map_city_code || '-UNKNOWN' END)
      AS barangay_differs
  FROM fact AS f
  FULL OUTER JOIN fact_school_enrollment_gate_expected AS e
    ON e.school_id = f.school_id AND e.school_year = f.school_year AND e.education_level_code = f.education_level_code
)
SELECT
  r.*,
  (SELECT COUNT(*) FROM edu_access.`03-silver`.deped_enrollment_clean) AS silver_rows,
  (SELECT COUNT(*) FROM fact) AS fact_rows,
  (SELECT COUNT(*) FROM (SELECT school_id, school_year, education_level_code FROM fact
    GROUP BY school_id, school_year, education_level_code HAVING COUNT(*) > 1) AS x) AS duplicate_keys,
  (SELECT COUNT_IF(school_id IS NULL OR school_year IS NULL OR education_level_code IS NULL) FROM fact) AS null_keys,
  (SELECT COUNT_IF(city_mun_psgc_code IS NULL OR barangay_psgc_code IS NULL OR psgc_match_status IS NULL) FROM fact) AS null_geography,
  (SELECT COUNT_IF(psgc_match_status NOT IN ('matched', 'unmatched', 'ambiguous', 'excluded')) FROM fact) AS bad_match_status,
  (SELECT COUNT_IF(NOT COALESCE(
      (psgc_match_status = 'matched' AND city_mun_psgc_code NOT IN ('UNKNOWN', 'EXCLUDED'))
      OR (psgc_match_status IN ('unmatched', 'ambiguous') AND city_mun_psgc_code = 'UNKNOWN' AND barangay_psgc_code = 'UNKNOWN')
      OR (psgc_match_status = 'excluded' AND city_mun_psgc_code = 'EXCLUDED' AND barangay_psgc_code = 'EXCLUDED'),
      FALSE)) FROM fact) AS member_not_following_status,
  (SELECT COUNT(*) FROM fact AS f LEFT JOIN edu_access.`05-gold`.dim_school AS d ON d.school_id = f.school_id
    WHERE d.school_id IS NULL) AS school_unresolved,
  (SELECT COUNT(*) FROM fact AS f LEFT JOIN edu_access.`05-gold`.dim_school_year AS d ON d.school_year = f.school_year
    WHERE d.school_year IS NULL) AS school_year_unresolved,
  (SELECT COUNT(*) FROM fact AS f LEFT JOIN edu_access.`05-gold`.dim_education_level AS d
      ON d.education_level_code = f.education_level_code
    WHERE d.education_level_code IS NULL) AS education_level_unresolved,
  (SELECT COUNT(*) FROM fact AS f LEFT JOIN edu_access.`05-gold`.dim_city_municipality AS d
      ON d.city_mun_psgc_code = f.city_mun_psgc_code
    WHERE d.city_mun_psgc_code IS NULL) AS city_unresolved,
  (SELECT COUNT(*) FROM fact AS f LEFT JOIN edu_access.`05-gold`.dim_barangay AS d
      ON d.barangay_psgc_code = f.barangay_psgc_code
    WHERE d.barangay_psgc_code IS NULL) AS barangay_unresolved,
  (SELECT COUNT(*) FROM fact AS f JOIN edu_access.`05-gold`.dim_barangay AS d
      ON d.barangay_psgc_code = f.barangay_psgc_code
    WHERE d.city_mun_psgc_code IS DISTINCT FROM f.city_mun_psgc_code) AS barangay_outside_city,
  (SELECT COUNT(*) FROM fact AS f JOIN edu_access.`05-gold`.dim_city_municipality AS d
      ON d.city_mun_psgc_code = f.city_mun_psgc_code
    WHERE f.psgc_match_status = 'matched' AND d.member_type <> 'regular') AS matched_on_technical_member,
  (SELECT COUNT_IF(is_offered IS NULL) FROM fact) AS offering_flag_blank,
  (SELECT COUNT_IF(NOT is_offered AND published_cell_sum > 0) FROM fact) AS not_offered_with_learners,
  (SELECT COUNT_IF(learner_count IS DISTINCT FROM CASE
      WHEN is_offered IS NULL THEN NULL
      WHEN NOT is_offered THEN 0
      WHEN null_cells = 0 THEN published_cell_sum END) FROM fact) AS learner_count_off_rule,
  -- Unique-strand cells start in SY 2024-25 and Strengthened SHS cells in SY 2025-26; the build does not
  -- count them before then, so a published one there must stop the gate rather than be left out.
  (SELECT COUNT_IF(
      (CAST(substr(school_year, 1, 4) AS INT) < 2024
        AND COALESCE(g11_unique_male, g11_unique_female, g12_unique_male, g12_unique_female) IS NOT NULL)
      OR (CAST(substr(school_year, 1, 4) AS INT) < 2025
        AND COALESCE(g11_sshs_acad_male, g11_sshs_acad_female, g11_sshs_techpro_male, g11_sshs_techpro_female) IS NOT NULL))
    FROM edu_access.`03-silver`.deped_enrollment_clean) AS cells_before_start,
  (SELECT COUNT_IF(sector IS NULL OR sector NOT IN ('Public', 'Private', 'SUC/LUC', 'PSO')) FROM fact) AS bad_sector,
  (SELECT COUNT_IF(psgc_match_status IN ('unmatched', 'ambiguous')) FROM school_years) AS schools_city_unknown,
  (SELECT COUNT_IF(psgc_match_status = 'matched' AND barangay_psgc_code LIKE '%-UNKNOWN') FROM school_years) AS schools_barangay_unknown,
  (SELECT COUNT_IF(psgc_match_status = 'excluded') FROM school_years) AS schools_excluded
FROM reconciliation AS r;

ALTER TABLE edu_access.`05-gold`.fact_school_enrollment_gate_summary_candidate OWNER TO `reached-hq`;

CREATE OR REPLACE TEMPORARY VIEW fact_school_enrollment_gate_levels AS
SELECT
  school_year,
  education_level_code,
  COUNT_IF(is_offered AND null_cells = 0) AS offered_complete,
  COUNT_IF(is_offered AND null_cells > 0 AND null_cells < applicable_cells) AS offered_partial,
  COUNT_IF(is_offered AND null_cells = applicable_cells) AS offered_all_blank,
  COUNT_IF(NOT is_offered AND published_cell_sum > 0) AS not_offered_positive,
  COUNT_IF(is_offered IS NULL) AS offering_flag_blank,
  SUM(learner_count) AS learners,
  SUM(CASE WHEN is_offered AND null_cells > 0 THEN published_cell_sum ELSE 0 END) AS partial_published_cells
FROM edu_access.`05-gold`.fact_school_enrollment_candidate
GROUP BY school_year, education_level_code;

INSERT INTO edu_access.`01-control`.data_quality_results (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, NULL, 'fact_school_enrollment', 'gold', 'edu_access.05-gold.fact_school_enrollment', check_name, status, expected, actual, current_timestamp(), :code_revision
FROM (
  SELECT 'key_unique' AS check_name, CASE WHEN duplicate_keys = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '0' AS expected, CAST(duplicate_keys AS STRING) AS actual FROM edu_access.`05-gold`.fact_school_enrollment_gate_summary_candidate
  UNION ALL SELECT 'key_not_null', CASE WHEN null_keys = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(null_keys AS STRING) FROM edu_access.`05-gold`.fact_school_enrollment_gate_summary_candidate
  UNION ALL SELECT 'rows_reconcile', CASE WHEN fact_rows = 3 * silver_rows THEN 'PASS' ELSE 'FAIL' END, CAST(3 * silver_rows AS STRING), CAST(fact_rows AS STRING) FROM edu_access.`05-gold`.fact_school_enrollment_gate_summary_candidate
  UNION ALL SELECT 'geography_not_null', CASE WHEN null_geography = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(null_geography AS STRING) FROM edu_access.`05-gold`.fact_school_enrollment_gate_summary_candidate
  UNION ALL SELECT 'match_status_allowed', CASE WHEN bad_match_status = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_match_status AS STRING) FROM edu_access.`05-gold`.fact_school_enrollment_gate_summary_candidate
  UNION ALL SELECT 'member_follows_status', CASE WHEN member_not_following_status = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(member_not_following_status AS STRING) FROM edu_access.`05-gold`.fact_school_enrollment_gate_summary_candidate
  UNION ALL SELECT 'school_in_dimension', CASE WHEN school_unresolved = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(school_unresolved AS STRING) FROM edu_access.`05-gold`.fact_school_enrollment_gate_summary_candidate
  UNION ALL SELECT 'school_year_in_dimension', CASE WHEN school_year_unresolved = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(school_year_unresolved AS STRING) FROM edu_access.`05-gold`.fact_school_enrollment_gate_summary_candidate
  UNION ALL SELECT 'education_level_in_dimension', CASE WHEN education_level_unresolved = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(education_level_unresolved AS STRING) FROM edu_access.`05-gold`.fact_school_enrollment_gate_summary_candidate
  UNION ALL SELECT 'city_in_dimension', CASE WHEN city_unresolved = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(city_unresolved AS STRING) FROM edu_access.`05-gold`.fact_school_enrollment_gate_summary_candidate
  UNION ALL SELECT 'barangay_in_dimension', CASE WHEN barangay_unresolved = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(barangay_unresolved AS STRING) FROM edu_access.`05-gold`.fact_school_enrollment_gate_summary_candidate
  UNION ALL SELECT 'barangay_in_city', CASE WHEN barangay_outside_city = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(barangay_outside_city AS STRING) FROM edu_access.`05-gold`.fact_school_enrollment_gate_summary_candidate
  UNION ALL SELECT 'matched_on_regular_member', CASE WHEN matched_on_technical_member = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(matched_on_technical_member AS STRING) FROM edu_access.`05-gold`.fact_school_enrollment_gate_summary_candidate
  UNION ALL SELECT 'offering_flag_published', CASE WHEN offering_flag_blank = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(offering_flag_blank AS STRING) FROM edu_access.`05-gold`.fact_school_enrollment_gate_summary_candidate
  UNION ALL SELECT 'not_offered_without_learners', CASE WHEN not_offered_with_learners = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(not_offered_with_learners AS STRING) FROM edu_access.`05-gold`.fact_school_enrollment_gate_summary_candidate
  UNION ALL SELECT 'learner_count_follows_rule', CASE WHEN learner_count_off_rule = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(learner_count_off_rule AS STRING) FROM edu_access.`05-gold`.fact_school_enrollment_gate_summary_candidate
  UNION ALL SELECT 'cells_before_start_blank', CASE WHEN cells_before_start = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(cells_before_start AS STRING) FROM edu_access.`05-gold`.fact_school_enrollment_gate_summary_candidate
  UNION ALL SELECT 'rows_match_silver', CASE WHEN rows_not_matching_silver = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(rows_not_matching_silver AS STRING) FROM edu_access.`05-gold`.fact_school_enrollment_gate_summary_candidate
  UNION ALL SELECT 'sector_matches_silver', CASE WHEN sector_differs = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(sector_differs AS STRING) FROM edu_access.`05-gold`.fact_school_enrollment_gate_summary_candidate
  UNION ALL SELECT 'annex_status_matches_silver', CASE WHEN annex_status_differs = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(annex_status_differs AS STRING) FROM edu_access.`05-gold`.fact_school_enrollment_gate_summary_candidate
  UNION ALL SELECT 'is_offered_matches_silver', CASE WHEN is_offered_differs = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(is_offered_differs AS STRING) FROM edu_access.`05-gold`.fact_school_enrollment_gate_summary_candidate
  UNION ALL SELECT 'learner_count_matches_silver', CASE WHEN learner_count_differs = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(learner_count_differs AS STRING) FROM edu_access.`05-gold`.fact_school_enrollment_gate_summary_candidate
  UNION ALL SELECT 'match_status_matches_map', CASE WHEN match_status_differs = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(match_status_differs AS STRING) FROM edu_access.`05-gold`.fact_school_enrollment_gate_summary_candidate
  UNION ALL SELECT 'city_matches_map', CASE WHEN city_differs = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(city_differs AS STRING) FROM edu_access.`05-gold`.fact_school_enrollment_gate_summary_candidate
  UNION ALL SELECT 'barangay_matches_map', CASE WHEN barangay_differs = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(barangay_differs AS STRING) FROM edu_access.`05-gold`.fact_school_enrollment_gate_summary_candidate
  UNION ALL SELECT 'sector_allowed', CASE WHEN bad_sector = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_sector AS STRING) FROM edu_access.`05-gold`.fact_school_enrollment_gate_summary_candidate
  UNION ALL SELECT 'schools_city_unknown', CASE WHEN schools_city_unknown = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(schools_city_unknown AS STRING) FROM edu_access.`05-gold`.fact_school_enrollment_gate_summary_candidate
  UNION ALL SELECT 'schools_barangay_unknown', CASE WHEN schools_barangay_unknown = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(schools_barangay_unknown AS STRING) FROM edu_access.`05-gold`.fact_school_enrollment_gate_summary_candidate
  UNION ALL SELECT 'schools_excluded', 'PASS', CAST(NULL AS STRING), CAST(schools_excluded AS STRING) FROM edu_access.`05-gold`.fact_school_enrollment_gate_summary_candidate
  -- By school year and level (metric specification, "Enrollment aggregation and missingness").
  UNION ALL SELECT 'offered_complete/' || school_year || '/' || education_level_code, 'PASS', CAST(NULL AS STRING), CAST(offered_complete AS STRING) FROM fact_school_enrollment_gate_levels
  UNION ALL SELECT 'offered_partial/' || school_year || '/' || education_level_code, CASE WHEN offered_partial = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(offered_partial AS STRING) FROM fact_school_enrollment_gate_levels
  UNION ALL SELECT 'offered_all_blank/' || school_year || '/' || education_level_code, CASE WHEN offered_all_blank = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(offered_all_blank AS STRING) FROM fact_school_enrollment_gate_levels
  UNION ALL SELECT 'not_offered_positive/' || school_year || '/' || education_level_code, CASE WHEN not_offered_positive = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(not_offered_positive AS STRING) FROM fact_school_enrollment_gate_levels
  UNION ALL SELECT 'offering_flag_blank/' || school_year || '/' || education_level_code, CASE WHEN offering_flag_blank = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(offering_flag_blank AS STRING) FROM fact_school_enrollment_gate_levels
  UNION ALL SELECT 'learners/' || school_year || '/' || education_level_code, 'PASS', CAST(NULL AS STRING), CAST(learners AS STRING) FROM fact_school_enrollment_gate_levels
  UNION ALL SELECT 'partial_published_cells/' || school_year || '/' || education_level_code, 'PASS', CAST(NULL AS STRING), CAST(partial_published_cells AS STRING) FROM fact_school_enrollment_gate_levels
) AS results;

-- Integrity rule 1 of the metric specification: one result per distinct upstream run_id read, PASS only
-- when that run's silver_build or integration_build for the source succeeded in pipeline_runs (D-025), so
-- the Gold build is traceable to the Silver and Integration rows it read and never trusts a run that did
-- not publish.
INSERT INTO edu_access.`01-control`.data_quality_results (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, NULL, 'fact_school_enrollment', 'gold', 'edu_access.05-gold.fact_school_enrollment', 'upstream_run_' || u.input_table,
       CASE WHEN p.run_id IS NULL THEN 'FAIL' ELSE 'PASS' END, 'succeeded ' || u.pipeline_name, u.upstream_run_id,
       current_timestamp(), :code_revision
FROM (
  SELECT DISTINCT 'deped_enrollment_clean' AS input_table, 'silver_build' AS pipeline_name, 'deped_enrollment' AS source_id, run_id AS upstream_run_id
  FROM edu_access.`03-silver`.deped_enrollment_clean
  UNION ALL
  SELECT DISTINCT 'deped_school_psgc_map' AS input_table, 'integration_build' AS pipeline_name, 'deped_enrollment' AS source_id, run_id AS upstream_run_id
  FROM edu_access.`04-integration`.deped_school_psgc_map
) AS u
LEFT JOIN (
  SELECT DISTINCT run_id, pipeline_name, source_id
  FROM edu_access.`01-control`.pipeline_runs
  WHERE status = 'succeeded'
) AS p ON p.run_id = u.upstream_run_id AND p.pipeline_name = u.pipeline_name AND p.source_id = u.source_id;

-- Sandbox: a failing gate marks its gold_build run failed before it stops.
MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (SELECT :run_id AS run_id, COUNT_IF(status = 'FAIL') AS fails FROM edu_access.`01-control`.data_quality_results
       WHERE run_id = :run_id AND source_id = 'fact_school_enrollment' AND layer = 'gold'
         AND checked_at_utc >= session.gold_gate_started_at_utc) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'gold_build' AND t.source_id = 'fact_school_enrollment'
WHEN MATCHED AND s.fails > 0 THEN UPDATE SET status = 'failed', finished_at_utc = current_timestamp(),
  failure_stage = 'gate', error_message = CAST(s.fails AS STRING) || ' FAIL result(s) in data_quality_results';

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Gold gate failed for fact_school_enrollment: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s) in data_quality_results for run ' || :run_id) END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'fact_school_enrollment' AND layer = 'gold' AND status = 'FAIL'
  AND checked_at_utc >= session.gold_gate_started_at_utc;

-- Every check passed: publish the data model's columns, without the audit columns.
CREATE OR REPLACE TABLE edu_access.`05-gold`.fact_school_enrollment USING DELTA AS
SELECT school_id, school_year, education_level_code, city_mun_psgc_code, barangay_psgc_code, psgc_match_status,
       sector, annex_status, is_offered, learner_count
FROM edu_access.`05-gold`.fact_school_enrollment_candidate;

COMMENT ON TABLE edu_access.`05-gold`.fact_school_enrollment IS 'Learners by school, school year and education level, with the geography and PSGC match status of that school year (D-048).';
ALTER TABLE edu_access.`05-gold`.fact_school_enrollment OWNER TO `reached-hq`;

-- Sandbox: the gate passed and the table is published.
MERGE INTO edu_access.`01-control`.pipeline_runs AS t USING (SELECT :run_id AS run_id) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'gold_build' AND t.source_id = 'fact_school_enrollment'
WHEN MATCHED THEN UPDATE SET status = 'succeeded', finished_at_utc = current_timestamp(), failure_stage = NULL, error_message = NULL;
