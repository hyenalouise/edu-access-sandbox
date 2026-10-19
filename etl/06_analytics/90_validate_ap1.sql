-- Analytics gate for AP1: one row per regular LGU and school year, each ratio equal to its numerator over
-- its denominator, coverage within 0 to 100, and public learners reconciled to the enrollment fact, so a
-- school is neither dropped nor counted twice. Public schools outside any regular LGU (unknown or
-- excluded geography) are reported, not hidden.

DECLARE OR REPLACE VARIABLE analytics_gate_started_at_utc TIMESTAMP;
SET VARIABLE analytics_gate_started_at_utc = current_timestamp();

INSERT INTO edu_access.`01-control`.data_quality_results
  (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, CAST(NULL AS STRING), 'ap1_school_provision', 'analytics', 'edu_access.06-analytics.ap1_school_provision_candidate',
       check_name, status, expected, actual, current_timestamp(), :code_revision
FROM (
WITH c AS (SELECT * FROM edu_access.`06-analytics`.ap1_school_provision_candidate),
school AS (
  SELECT school_id, school_year, MAX(city_mun_psgc_code) AS city_mun_psgc_code,
         COALESCE(bool_or(is_offered AND learner_count > 0), FALSE) AS is_active,
         CASE WHEN COALESCE(COUNT_IF(is_offered AND learner_count IS NULL), 0) = 0 THEN SUM(learner_count) END AS total_learners
  FROM edu_access.`05-gold`.fact_school_enrollment
  WHERE sector = 'Public'
  GROUP BY school_id, school_year
),
fact AS (
  SELECT COALESCE(COUNT_IF(is_active), 0) AS active_schools,
         COALESCE(COUNT_IF(is_active AND city_mun_psgc_code IN ('UNKNOWN', 'EXCLUDED')), 0) AS outside_lgu_schools,
         SUM(CASE WHEN is_active AND total_learners IS NOT NULL THEN total_learners ELSE 0 END) AS learners,
         SUM(CASE WHEN is_active AND total_learners IS NOT NULL AND city_mun_psgc_code IN ('UNKNOWN', 'EXCLUDED') THEN total_learners ELSE 0 END) AS outside_lgu_learners
  FROM school
),
s AS (
  SELECT
    (SELECT COUNT(*) FROM edu_access.`05-gold`.dim_city_municipality WHERE member_type = 'regular')
      * (SELECT COUNT(*) FROM edu_access.`05-gold`.dim_school_year) AS expected_rows,
    COUNT(*) AS rows_built,
    COUNT(DISTINCT city_mun_psgc_code || '/' || school_year) AS keys_built,
    COALESCE(COUNT_IF(ABS(learners_per_public_school - CAST(public_learners AS DOUBLE) / NULLIF(complete_total_schools, 0)) > 1e-9
             OR (learners_per_public_school IS NULL) <> (complete_total_schools = 0)), 0) AS bad_learner_ratio,
    COALESCE(COUNT_IF((learners_per_public_school IS NULL) <> (learners_per_school_null_reason IS NOT NULL)), 0) AS reason_mismatch,
    COALESCE(COUNT_IF(ap1_coverage_pct < 0 OR ap1_coverage_pct > 100 OR barangays_without_public_es_pct < 0 OR barangays_without_public_es_pct > 100), 0) AS pct_out_of_range,
    COALESCE(COUNT_IF(complete_total_schools + incomplete_total_schools <> active_public_schools), 0) AS school_split_mismatch,
    COALESCE(COUNT_IF(barangays_without_public_es > regular_barangays), 0) AS barangay_overcount,
    SUM(active_public_schools) AS lgu_active_schools,
    SUM(public_learners) AS lgu_learners,
    COALESCE(COUNT_IF(population_per_public_school IS NULL AND active_public_schools > 0), 0) AS population_ratio_missing,
    COALESCE(COUNT_IF(ap1_coverage_pct < 90), 0) AS below_gate
  FROM c
)
SELECT 'one_row_per_lgu_and_year' AS check_name,
       CASE WHEN rows_built = expected_rows AND keys_built = rows_built THEN 'PASS' ELSE 'FAIL' END AS status,
       CAST(expected_rows AS STRING) AS expected, CAST(rows_built AS STRING) AS actual FROM s
UNION ALL SELECT 'learner_ratio_from_sums', CASE WHEN bad_learner_ratio = 0 AND reason_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END,
                 '0', CAST(bad_learner_ratio + reason_mismatch AS STRING) FROM s
UNION ALL SELECT 'percentages_in_range', CASE WHEN pct_out_of_range = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(pct_out_of_range AS STRING) FROM s
UNION ALL SELECT 'active_schools_split', CASE WHEN school_split_mismatch = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(school_split_mismatch AS STRING) FROM s
UNION ALL SELECT 'barangays_within_lgu_count', CASE WHEN barangay_overcount = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(barangay_overcount AS STRING) FROM s
UNION ALL SELECT 'active_schools_reconcile', CASE WHEN lgu_active_schools + f.outside_lgu_schools = f.active_schools THEN 'PASS' ELSE 'FAIL' END,
                 CAST(f.active_schools AS STRING), CAST(lgu_active_schools AS STRING) || ' + ' || CAST(f.outside_lgu_schools AS STRING) || ' outside an LGU'
FROM s CROSS JOIN fact AS f
UNION ALL SELECT 'learners_reconcile', CASE WHEN lgu_learners + f.outside_lgu_learners = f.learners THEN 'PASS' ELSE 'FAIL' END,
                 CAST(f.learners AS STRING), CAST(lgu_learners AS STRING) || ' + ' || CAST(f.outside_lgu_learners AS STRING) || ' outside an LGU'
FROM s CROSS JOIN fact AS f
UNION ALL SELECT 'public_schools_outside_an_lgu', CASE WHEN f.outside_lgu_schools = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(f.outside_lgu_schools AS STRING)
FROM fact AS f
UNION ALL SELECT 'population_ratio_missing', CASE WHEN population_ratio_missing = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(population_ratio_missing AS STRING) FROM s
UNION ALL SELECT 'lgu_years_below_90pct_coverage', CASE WHEN below_gate = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(below_gate AS STRING) FROM s
) AS results;

MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (SELECT :run_id AS run_id, COUNT_IF(status = 'FAIL') AS fails FROM edu_access.`01-control`.data_quality_results
       WHERE run_id = :run_id AND source_id = 'ap1_school_provision' AND layer = 'analytics'
         AND checked_at_utc >= session.analytics_gate_started_at_utc) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'analytics_build' AND t.source_id = 'ap1_school_provision'
WHEN MATCHED AND s.fails > 0 THEN UPDATE SET status = 'failed', finished_at_utc = current_timestamp(),
  failure_stage = 'gate', error_message = CAST(s.fails AS STRING) || ' FAIL result(s) in data_quality_results';

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Analytics gate failed for ap1_school_provision: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s)') END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'ap1_school_provision' AND layer = 'analytics' AND status = 'FAIL'
  AND checked_at_utc >= session.analytics_gate_started_at_utc;

CREATE OR REPLACE TABLE edu_access.`06-analytics`.ap1_school_provision USING DELTA AS SELECT * FROM edu_access.`06-analytics`.ap1_school_provision_candidate;
ALTER TABLE edu_access.`06-analytics`.ap1_school_provision OWNER TO `reached-hq`;

MERGE INTO edu_access.`01-control`.pipeline_runs AS t USING (SELECT :run_id AS run_id) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'analytics_build' AND t.source_id = 'ap1_school_provision'
WHEN MATCHED THEN UPDATE SET status = 'succeeded', finished_at_utc = current_timestamp(), failure_stage = NULL, error_message = NULL;
