-- Analytics gate for AP4: two rows per regular LGU (2020, 2024), the gap equal to population minus
-- enrollment, population reconciled to the Gold fact for regular cities, and the national 2024 totals
-- reported beside the metric specification's figures (27,569,038 residents aged 5-17; 26,375,327 learners).

DECLARE OR REPLACE VARIABLE analytics_gate_started_at_utc TIMESTAMP;
SET VARIABLE analytics_gate_started_at_utc = current_timestamp();

INSERT INTO edu_access.`01-control`.data_quality_results
  (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, CAST(NULL AS STRING), 'ap4_population_enrollment_gap', 'analytics', 'edu_access.06-analytics.ap4_population_enrollment_gap_candidate',
       check_name, status, expected, actual, current_timestamp(), :code_revision
FROM (
WITH c AS (SELECT * FROM edu_access.`06-analytics`.ap4_population_enrollment_gap_candidate),
fact AS (
  SELECT f.reference_year, SUM(f.population) AS population
  FROM edu_access.`05-gold`.fact_city_school_age_population AS f
  JOIN edu_access.`05-gold`.dim_city_municipality AS d ON d.city_mun_psgc_code = f.city_mun_psgc_code AND d.member_type = 'regular'
  WHERE f.age BETWEEN 5 AND 17
  GROUP BY f.reference_year
),
totals AS (
  SELECT reference_year, SUM(school_age_population) AS population, SUM(enrollment_all_sectors) AS enrollment
  FROM c GROUP BY reference_year
),
s AS (
  SELECT
    (SELECT COUNT(*) FROM edu_access.`05-gold`.dim_city_municipality WHERE member_type = 'regular') * 2 AS expected_rows,
    COUNT(*) AS rows_built,
    COUNT(DISTINCT city_mun_psgc_code || '/' || CAST(reference_year AS STRING)) AS keys_built,
    COALESCE(COUNT_IF(population_enrollment_gap IS DISTINCT FROM school_age_population - enrollment_all_sectors), 0) AS bad_gap,
    COALESCE(COUNT_IF(public_enrollment > enrollment_all_sectors), 0) AS public_above_total,
    COALESCE(COUNT_IF(school_age_population IS NULL), 0) AS no_population,
    COALESCE(COUNT_IF(population_enrollment_gap < 0), 0) AS negative_gap,
    COALESCE(COUNT_IF(reference_year = 2024 AND NOT is_2020_2024_geography_comparable), 0) AS not_comparable
  FROM c
)
SELECT 'two_rows_per_lgu' AS check_name,
       CASE WHEN rows_built = expected_rows AND keys_built = rows_built THEN 'PASS' ELSE 'FAIL' END AS status,
       CAST(expected_rows AS STRING) AS expected, CAST(rows_built AS STRING) AS actual FROM s
UNION ALL SELECT 'gap_is_population_minus_enrollment', CASE WHEN bad_gap = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_gap AS STRING) FROM s
UNION ALL SELECT 'public_within_all_sectors', CASE WHEN public_above_total = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(public_above_total AS STRING) FROM s
UNION ALL SELECT 'population_reconciles_' || CAST(t.reference_year AS STRING),
                 CASE WHEN t.population = f.population THEN 'PASS' ELSE 'FAIL' END,
                 CAST(f.population AS STRING), CAST(t.population AS STRING)
FROM totals AS t JOIN fact AS f ON f.reference_year = t.reference_year
UNION ALL SELECT 'national_totals_' || CAST(reference_year AS STRING), 'PASS', 'population / enrollment',
                 CAST(population AS STRING) || ' / ' || CAST(enrollment AS STRING) FROM totals
UNION ALL SELECT 'lgu_periods_without_population', CASE WHEN no_population = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(no_population AS STRING) FROM s
UNION ALL SELECT 'negative_gaps_kept', 'PASS', 'count', CAST(negative_gap AS STRING) FROM s
UNION ALL SELECT 'lgus_not_comparable_2020_2024', 'PASS', 'count', CAST(not_comparable AS STRING) FROM s
) AS results;

MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (SELECT :run_id AS run_id, COUNT_IF(status = 'FAIL') AS fails FROM edu_access.`01-control`.data_quality_results
       WHERE run_id = :run_id AND source_id = 'ap4_population_enrollment_gap' AND layer = 'analytics'
         AND checked_at_utc >= session.analytics_gate_started_at_utc) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'analytics_build' AND t.source_id = 'ap4_population_enrollment_gap'
WHEN MATCHED AND s.fails > 0 THEN UPDATE SET status = 'failed', finished_at_utc = current_timestamp(),
  failure_stage = 'gate', error_message = CAST(s.fails AS STRING) || ' FAIL result(s) in data_quality_results';

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Analytics gate failed for ap4_population_enrollment_gap: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s)') END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'ap4_population_enrollment_gap' AND layer = 'analytics' AND status = 'FAIL'
  AND checked_at_utc >= session.analytics_gate_started_at_utc;

CREATE OR REPLACE TABLE edu_access.`06-analytics`.ap4_population_enrollment_gap USING DELTA AS SELECT * FROM edu_access.`06-analytics`.ap4_population_enrollment_gap_candidate;
ALTER TABLE edu_access.`06-analytics`.ap4_population_enrollment_gap OWNER TO `reached-hq`;

MERGE INTO edu_access.`01-control`.pipeline_runs AS t USING (SELECT :run_id AS run_id) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'analytics_build' AND t.source_id = 'ap4_population_enrollment_gap'
WHEN MATCHED THEN UPDATE SET status = 'succeeded', finished_at_utc = current_timestamp(), failure_stage = NULL, error_message = NULL;
