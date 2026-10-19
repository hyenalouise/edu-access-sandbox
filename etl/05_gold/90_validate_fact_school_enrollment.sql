-- Gold gate for fact_school_enrollment: the grain, every foreign key, the geography rules, and the
-- enrollment-state counts the metric specification asks for, by school year and level: offered and
-- complete, offered and partly published, offered and all blank, not offered but with a positive cell
-- (FAIL), and a NULL offering flag (FAIL). The published-cell sum on partial rows is an audit value only.

DECLARE OR REPLACE VARIABLE gold_gate_started_at_utc TIMESTAMP;
SET VARIABLE gold_gate_started_at_utc = current_timestamp();

INSERT INTO edu_access.`01-control`.data_quality_results
  (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, CAST(NULL AS STRING), 'fact_school_enrollment', 'gold', 'edu_access.05-gold.fact_school_enrollment_candidate',
       check_name, status, expected, actual, current_timestamp(), :code_revision
FROM (
WITH c AS (SELECT * FROM edu_access.`05-gold`.fact_school_enrollment_candidate),
cells AS (
SELECT school_year, school_id, 'ES' AS education_level_code,
       COALESCE(kinder_male, kinder_female, g1_male, g1_female, g2_male, g2_female, g3_male, g3_female,
          g4_male, g4_female, g5_male, g5_female, g6_male, g6_female, esng_male, esng_female) IS NOT NULL AS any_published,
       COALESCE(kinder_male, 0) + COALESCE(kinder_female, 0) + COALESCE(g1_male, 0) + COALESCE(g1_female, 0) + COALESCE(g2_male, 0) + COALESCE(g2_female, 0) +
          COALESCE(g3_male, 0) + COALESCE(g3_female, 0) + COALESCE(g4_male, 0) + COALESCE(g4_female, 0) + COALESCE(g5_male, 0) + COALESCE(g5_female, 0) +
          COALESCE(g6_male, 0) + COALESCE(g6_female, 0) + COALESCE(esng_male, 0) + COALESCE(esng_female, 0) AS published_sum
FROM edu_access.`03-silver`.deped_enrollment_clean
UNION ALL
SELECT school_year, school_id, 'JHS' AS education_level_code,
       COALESCE(g7_male, g7_female, g8_male, g8_female, g9_male, g9_female, g10_male, g10_female,
          jhsng_male, jhsng_female) IS NOT NULL AS any_published,
       COALESCE(g7_male, 0) + COALESCE(g7_female, 0) + COALESCE(g8_male, 0) + COALESCE(g8_female, 0) + COALESCE(g9_male, 0) + COALESCE(g9_female, 0) +
          COALESCE(g10_male, 0) + COALESCE(g10_female, 0) + COALESCE(jhsng_male, 0) + COALESCE(jhsng_female, 0) AS published_sum
FROM edu_access.`03-silver`.deped_enrollment_clean
UNION ALL
SELECT school_year, school_id, 'SHS' AS education_level_code,
       (COALESCE(g11_abm_male, g11_abm_female, g11_arts_male, g11_arts_female, g11_gas_male, g11_gas_female, g11_humss_male, g11_humss_female,
          g11_maritime_male, g11_maritime_female, g11_sports_male, g11_sports_female, g11_stem_male, g11_stem_female, g11_tvl_male, g11_tvl_female,
          g12_abm_male, g12_abm_female, g12_arts_male, g12_arts_female, g12_gas_male, g12_gas_female, g12_humss_male, g12_humss_female,
          g12_maritime_male, g12_maritime_female, g12_sports_male, g12_sports_female, g12_stem_male, g12_stem_female, g12_tvl_male, g12_tvl_female) IS NOT NULL
           OR (school_year >= '2024-25' AND COALESCE(g11_unique_male, g11_unique_female, g12_unique_male, g12_unique_female) IS NOT NULL)
           OR (school_year >= '2025-26' AND COALESCE(g11_sshs_acad_male, g11_sshs_acad_female, g11_sshs_techpro_male, g11_sshs_techpro_female) IS NOT NULL)) AS any_published,
       COALESCE(g11_abm_male, 0) + COALESCE(g11_abm_female, 0) + COALESCE(g11_arts_male, 0) + COALESCE(g11_arts_female, 0) + COALESCE(g11_gas_male, 0) + COALESCE(g11_gas_female, 0) +
          COALESCE(g11_humss_male, 0) + COALESCE(g11_humss_female, 0) + COALESCE(g11_maritime_male, 0) + COALESCE(g11_maritime_female, 0) + COALESCE(g11_sports_male, 0) + COALESCE(g11_sports_female, 0) +
          COALESCE(g11_stem_male, 0) + COALESCE(g11_stem_female, 0) + COALESCE(g11_tvl_male, 0) + COALESCE(g11_tvl_female, 0) + COALESCE(g12_abm_male, 0) + COALESCE(g12_abm_female, 0) +
          COALESCE(g12_arts_male, 0) + COALESCE(g12_arts_female, 0) + COALESCE(g12_gas_male, 0) + COALESCE(g12_gas_female, 0) + COALESCE(g12_humss_male, 0) + COALESCE(g12_humss_female, 0) +
          COALESCE(g12_maritime_male, 0) + COALESCE(g12_maritime_female, 0) + COALESCE(g12_sports_male, 0) + COALESCE(g12_sports_female, 0) + COALESCE(g12_stem_male, 0) + COALESCE(g12_stem_female, 0) +
          COALESCE(g12_tvl_male, 0) + COALESCE(g12_tvl_female, 0)
          + CASE WHEN school_year >= '2024-25' THEN COALESCE(g11_unique_male, 0) + COALESCE(g11_unique_female, 0) + COALESCE(g12_unique_male, 0) + COALESCE(g12_unique_female, 0) ELSE 0 END
          + CASE WHEN school_year >= '2025-26' THEN COALESCE(g11_sshs_acad_male, 0) + COALESCE(g11_sshs_acad_female, 0) + COALESCE(g11_sshs_techpro_male, 0) + COALESCE(g11_sshs_techpro_female, 0) ELSE 0 END AS published_sum
FROM edu_access.`03-silver`.deped_enrollment_clean
),
states AS (
  SELECT c.school_year, c.education_level_code,
         COALESCE(COUNT_IF(c.is_offered AND c.learner_count IS NOT NULL), 0) AS complete_rows,
         COALESCE(COUNT_IF(c.is_offered AND c.learner_count IS NULL AND x.any_published), 0) AS partial_rows,
         COALESCE(COUNT_IF(c.is_offered AND c.learner_count IS NULL AND NOT x.any_published), 0) AS blank_rows,
         COALESCE(COUNT_IF(NOT c.is_offered AND x.published_sum > 0), 0) AS conflict_rows,
         COALESCE(COUNT_IF(c.is_offered IS NULL), 0) AS null_flag_rows,
         SUM(CASE WHEN c.is_offered AND c.learner_count IS NULL THEN x.published_sum ELSE 0 END) AS partial_cell_sum
  FROM c JOIN cells AS x
    ON x.school_year = c.school_year AND x.school_id = c.school_id AND x.education_level_code = c.education_level_code
  GROUP BY c.school_year, c.education_level_code
),
s AS (
  SELECT
    (SELECT COUNT(*) FROM edu_access.`03-silver`.deped_enrollment_clean) AS silver_rows,
    COUNT(*) AS rows_built,
    COUNT(DISTINCT c.school_id || '/' || c.school_year || '/' || c.education_level_code) AS keys_built,
    COALESCE(COUNT_IF(ds.school_id IS NULL), 0) AS no_school,
    COALESCE(COUNT_IF(dy.school_year IS NULL), 0) AS no_year,
    COALESCE(COUNT_IF(dl.education_level_code IS NULL), 0) AS no_level,
    COALESCE(COUNT_IF(dc.city_mun_psgc_code IS NULL), 0) AS no_city,
    COALESCE(COUNT_IF(db.barangay_psgc_code IS NULL), 0) AS no_barangay,
    COALESCE(COUNT_IF(db.city_mun_psgc_code IS DISTINCT FROM c.city_mun_psgc_code), 0) AS barangay_outside_city,
    COALESCE(COUNT_IF(c.psgc_match_status NOT IN ('matched', 'unmatched', 'ambiguous', 'excluded') OR c.psgc_match_status IS NULL), 0) AS bad_status,
    COALESCE(COUNT_IF((c.psgc_match_status = 'matched') <> (dc.member_type = 'regular')), 0) AS status_member_mismatch,
    COALESCE(COUNT_IF(c.learner_count < 0), 0) AS negative_counts,
    COALESCE(COUNT_IF(NOT c.is_offered AND c.learner_count <> 0), 0) AS not_offered_nonzero,
    COALESCE(COUNT_IF(c.education_level_code = 'ES' AND c.city_mun_psgc_code = 'UNKNOWN'), 0) AS unknown_city_schools,
    COALESCE(COUNT_IF(c.education_level_code = 'ES' AND c.city_mun_psgc_code = 'EXCLUDED'), 0) AS excluded_city_schools,
    COALESCE(COUNT_IF(c.education_level_code = 'ES' AND c.barangay_psgc_code LIKE '%-UNKNOWN'), 0) AS unknown_barangay_schools
  FROM c
  LEFT JOIN edu_access.`05-gold`.dim_school AS ds ON ds.school_id = c.school_id
  LEFT JOIN edu_access.`05-gold`.dim_school_year AS dy ON dy.school_year = c.school_year
  LEFT JOIN edu_access.`05-gold`.dim_education_level AS dl ON dl.education_level_code = c.education_level_code
  LEFT JOIN edu_access.`05-gold`.dim_city_municipality AS dc ON dc.city_mun_psgc_code = c.city_mun_psgc_code
  LEFT JOIN edu_access.`05-gold`.dim_barangay AS db ON db.barangay_psgc_code = c.barangay_psgc_code
),
checks AS (
  SELECT 'rows_reconcile' AS check_name, CASE WHEN rows_built = silver_rows * 3 THEN 'PASS' ELSE 'FAIL' END AS status,
         CAST(silver_rows * 3 AS STRING) AS expected, CAST(rows_built AS STRING) AS actual FROM s
  UNION ALL SELECT 'one_row_per_school_year_level', CASE WHEN keys_built = rows_built THEN 'PASS' ELSE 'FAIL' END,
                   CAST(rows_built AS STRING), CAST(keys_built AS STRING) FROM s
  UNION ALL SELECT 'school_in_dim_school', CASE WHEN no_school = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(no_school AS STRING) FROM s
  UNION ALL SELECT 'school_year_in_dim', CASE WHEN no_year = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(no_year AS STRING) FROM s
  UNION ALL SELECT 'level_in_dim', CASE WHEN no_level = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(no_level AS STRING) FROM s
  UNION ALL SELECT 'city_in_dim', CASE WHEN no_city = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(no_city AS STRING) FROM s
  UNION ALL SELECT 'barangay_in_dim', CASE WHEN no_barangay = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(no_barangay AS STRING) FROM s
  UNION ALL SELECT 'barangay_inside_city', CASE WHEN barangay_outside_city = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(barangay_outside_city AS STRING) FROM s
  UNION ALL SELECT 'match_status_valid', CASE WHEN bad_status = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_status AS STRING) FROM s
  UNION ALL SELECT 'matched_means_regular_city', CASE WHEN status_member_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(status_member_mismatch AS STRING) FROM s
  UNION ALL SELECT 'no_negative_counts', CASE WHEN negative_counts = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(negative_counts AS STRING) FROM s
  UNION ALL SELECT 'not_offered_is_zero', CASE WHEN not_offered_nonzero = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(not_offered_nonzero AS STRING) FROM s
  UNION ALL SELECT 'schools_in_unknown_city', CASE WHEN unknown_city_schools = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(unknown_city_schools AS STRING) FROM s
  UNION ALL SELECT 'schools_excluded', CASE WHEN excluded_city_schools = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(excluded_city_schools AS STRING) FROM s
  UNION ALL SELECT 'schools_in_unknown_barangay', CASE WHEN unknown_barangay_schools = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(unknown_barangay_schools AS STRING) FROM s
),
by_level AS (
  SELECT 'offering_conflict_' || school_year || '_' || education_level_code AS check_name,
         CASE WHEN conflict_rows = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '0' AS expected, CAST(conflict_rows AS STRING) AS actual
  FROM states
  UNION ALL
  SELECT 'offering_flag_null_' || school_year || '_' || education_level_code,
         CASE WHEN null_flag_rows = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(null_flag_rows AS STRING)
  FROM states
  UNION ALL
  SELECT 'enrollment_states_' || school_year || '_' || education_level_code,
         CASE WHEN partial_rows + blank_rows = 0 THEN 'PASS' ELSE 'WARN' END,
         'complete / partial / blank / partial cell sum',
         CAST(complete_rows AS STRING) || ' / ' || CAST(partial_rows AS STRING) || ' / ' || CAST(blank_rows AS STRING)
           || ' / ' || CAST(partial_cell_sum AS STRING)
  FROM states
)
SELECT * FROM checks UNION ALL SELECT * FROM by_level
) AS results;

MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (SELECT :run_id AS run_id, COUNT_IF(status = 'FAIL') AS fails FROM edu_access.`01-control`.data_quality_results
       WHERE run_id = :run_id AND source_id = 'fact_school_enrollment' AND layer = 'gold'
         AND checked_at_utc >= session.gold_gate_started_at_utc) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'gold_build' AND t.source_id = 'fact_school_enrollment'
WHEN MATCHED AND s.fails > 0 THEN UPDATE SET status = 'failed', finished_at_utc = current_timestamp(),
  failure_stage = 'gate', error_message = CAST(s.fails AS STRING) || ' FAIL result(s) in data_quality_results';

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Gold gate failed for fact_school_enrollment: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s)') END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'fact_school_enrollment' AND layer = 'gold' AND status = 'FAIL'
  AND checked_at_utc >= session.gold_gate_started_at_utc;

CREATE OR REPLACE TABLE edu_access.`05-gold`.fact_school_enrollment USING DELTA AS SELECT * FROM edu_access.`05-gold`.fact_school_enrollment_candidate;
ALTER TABLE edu_access.`05-gold`.fact_school_enrollment OWNER TO `reached-hq`;

MERGE INTO edu_access.`01-control`.pipeline_runs AS t USING (SELECT :run_id AS run_id) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'gold_build' AND t.source_id = 'fact_school_enrollment'
WHEN MATCHED THEN UPDATE SET status = 'succeeded', finished_at_utc = current_timestamp(), failure_stage = NULL, error_message = NULL;
