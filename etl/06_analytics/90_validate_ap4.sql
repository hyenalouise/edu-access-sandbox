-- Analytics gate for AP4 (#147). Checks ap4_enrollment_trend_candidate against the published Gold
-- facts it reads, writes every result to data_quality_results (layer 'analytics'), stops on any FAIL,
-- and only then publishes ap4_enrollment_trend. A FAIL keeps the last good output.
--
-- FAIL: a repeated or NULL key; a school year missing for a member, or one not in fact_school_enrollment;
-- a school placed in two cities or municipalities in one school year; a school year's all-sector
-- enrollment, or a census year's school-age population (5 to 17, male and female), that differs from the
-- Gold facts (which count no Philippine School Overseas); census context on a school year without a
-- census (only aligned years are compared); a change, share, gap or trend label that is not the
-- arithmetic of its rows; a member_type that does not fit the code; a trend that differs between a
-- member's rows; and any row that differs, in any column, from the row expected from the Gold facts
-- (rows_match_gold).
-- WARN: schools left out because an offered level has no learner_count; learners in schools on the
-- UNKNOWN or EXCLUDED member; school-age population on EXCLUDED; regular rows in a census school year
-- without population.
-- Counts only (PASS): enrollment per school year (the national trend), rows, and members by trend.

DECLARE OR REPLACE VARIABLE analytics_gate_started_at_utc TIMESTAMP;
SET VARIABLE analytics_gate_started_at_utc = current_timestamp();
DECLARE OR REPLACE VARIABLE analytics_gate_summary STRING;
SET VARIABLE analytics_gate_summary = '`edu_access`.`06-analytics`.`ap4_enrollment_trend_gate_summary_r_' || sha2(:run_id, 256) || '`';
DECLARE OR REPLACE VARIABLE analytics_gate_owner_sql STRING;

-- Every row as the Gold facts say it should be, built once for the full-row comparison.
CREATE OR REPLACE TEMPORARY VIEW ap4_expected AS
WITH years AS (
  SELECT DISTINCT school_year FROM edu_access.`05-gold`.fact_school_enrollment
),
first_last AS (
  SELECT MIN(school_year) AS first_year, MAX(school_year) AS latest_year FROM years
),
schools AS (
  SELECT school_year, school_id, MIN(city_mun_psgc_code) AS city_mun_psgc_code, MIN(sector) AS sector,
         BOOL_AND(is_offered IS NOT NULL AND (NOT is_offered OR learner_count IS NOT NULL)) AS complete,
         SUM(CASE WHEN is_offered THEN learner_count ELSE 0 END) AS learners
  FROM edu_access.`05-gold`.fact_school_enrollment
  WHERE sector <> 'PSO'
  GROUP BY school_year, school_id
),
enrollment AS (
  SELECT school_year, city_mun_psgc_code,
         SUM(CASE WHEN complete THEN learners ELSE 0 END) AS enrollment_all_sectors,
         SUM(CASE WHEN complete AND sector = 'Public' THEN learners ELSE 0 END) AS public_school_enrollment,
         COUNT_IF(complete) AS schools_counted, COUNT_IF(NOT complete) AS schools_incomplete,
         COUNT_IF(sector = 'Public' AND complete) AS public_schools_counted,
         COUNT_IF(sector = 'Public' AND NOT complete) AS public_schools_incomplete
  FROM schools GROUP BY school_year, city_mun_psgc_code
),
population AS (
  SELECT reference_year, city_mun_psgc_code, SUM(population) AS school_age_population,
         BOOL_AND(is_2020_2024_geography_comparable) AS comparable
  FROM edu_access.`05-gold`.fact_city_school_age_population
  WHERE reference_year IN (2020, 2024) AND sex IN ('male', 'female') AND age >= 5 AND age <= 17
  GROUP BY reference_year, city_mun_psgc_code
),
members AS (
  SELECT city_mun_psgc_code FROM population
  UNION
  SELECT city_mun_psgc_code FROM enrollment
),
cells AS (
  SELECT m.city_mun_psgc_code, y.school_year,
         COALESCE(e.enrollment_all_sectors, 0) AS enrollment_all_sectors,
         COALESCE(e.public_school_enrollment, 0) AS public_school_enrollment,
         COALESCE(e.schools_counted, 0) AS schools_counted,
         COALESCE(e.schools_incomplete, 0) AS schools_incomplete,
         COALESCE(e.public_schools_counted, 0) AS public_schools_counted,
         COALESCE(e.public_schools_incomplete, 0) AS public_schools_incomplete
  FROM members AS m CROSS JOIN years AS y
  LEFT JOIN enrollment AS e ON e.city_mun_psgc_code = m.city_mun_psgc_code AND e.school_year = y.school_year
)
SELECT
  c.city_mun_psgc_code,
  c.school_year,
  CAST(c.enrollment_all_sectors AS BIGINT) AS enrollment_all_sectors,
  CAST(c.public_school_enrollment AS BIGINT) AS public_school_enrollment,
  c.schools_counted,
  c.schools_incomplete,
  c.public_schools_counted,
  c.public_schools_incomplete,
  CAST(f.enrollment_all_sectors AS BIGINT) AS enrollment_first_school_year,
  CAST(l.enrollment_all_sectors AS BIGINT) AS enrollment_latest_school_year,
  CASE WHEN c.city_mun_psgc_code IN ('UNKNOWN', 'EXCLUDED') THEN NULL
       WHEN l.enrollment_all_sectors > f.enrollment_all_sectors THEN 'increasing'
       WHEN l.enrollment_all_sectors < f.enrollment_all_sectors THEN 'decreasing'
       ELSE 'no change' END AS enrollment_trend,
  CAST(f.public_school_enrollment AS BIGINT) AS public_enrollment_first_school_year,
  CAST(l.public_school_enrollment AS BIGINT) AS public_enrollment_latest_school_year,
  f.public_schools_counted > 0 AND f.public_schools_incomplete = 0
    AND l.public_schools_counted > 0 AND l.public_schools_incomplete = 0 AS public_enrollment_endpoints_complete,
  CASE WHEN c.city_mun_psgc_code IN ('UNKNOWN', 'EXCLUDED') OR f.public_schools_counted = 0
         OR f.public_schools_incomplete > 0 OR l.public_schools_counted = 0 OR l.public_schools_incomplete > 0
         OR f.public_school_enrollment = 0 THEN NULL
       WHEN l.public_school_enrollment > f.public_school_enrollment THEN 'increasing'
       WHEN l.public_school_enrollment < f.public_school_enrollment THEN 'decreasing'
       ELSE 'no change' END AS public_enrollment_trend,
  CAST(p.school_age_population AS BIGINT) AS school_age_population,
  COALESCE(c.city_mun_psgc_code NOT IN ('UNKNOWN', 'EXCLUDED') AND k.comparable, FALSE) AS is_2020_2024_geography_comparable
FROM cells AS c
CROSS JOIN first_last AS b
JOIN cells AS f ON f.city_mun_psgc_code = c.city_mun_psgc_code AND f.school_year = b.first_year
JOIN cells AS l ON l.city_mun_psgc_code = c.city_mun_psgc_code AND l.school_year = b.latest_year
LEFT JOIN population AS p
  ON p.city_mun_psgc_code = c.city_mun_psgc_code AND p.reference_year = CAST(substr(c.school_year, 1, 4) AS INT)
LEFT JOIN (SELECT city_mun_psgc_code, BOOL_AND(comparable) AS comparable FROM population GROUP BY city_mun_psgc_code) AS k
  ON k.city_mun_psgc_code = c.city_mun_psgc_code;

DECLARE OR REPLACE VARIABLE analytics_ap4_rows_not_matching BIGINT;
SET VARIABLE analytics_ap4_rows_not_matching = (
  (SELECT COUNT(*) FROM (
     SELECT city_mun_psgc_code, school_year, enrollment_all_sectors, public_school_enrollment, schools_counted,
             schools_incomplete, public_schools_counted, public_schools_incomplete,
             enrollment_first_school_year, enrollment_latest_school_year, enrollment_trend,
             public_enrollment_first_school_year, public_enrollment_latest_school_year,
             public_enrollment_endpoints_complete, public_enrollment_trend,
            school_age_population, is_2020_2024_geography_comparable
     FROM edu_access.`06-analytics`.ap4_enrollment_trend_candidate
     EXCEPT ALL SELECT * FROM ap4_expected) AS x)
  + (SELECT COUNT(*) FROM (
     SELECT * FROM ap4_expected
     EXCEPT ALL
     SELECT city_mun_psgc_code, school_year, enrollment_all_sectors, public_school_enrollment, schools_counted,
             schools_incomplete, public_schools_counted, public_schools_incomplete,
             enrollment_first_school_year, enrollment_latest_school_year, enrollment_trend,
             public_enrollment_first_school_year, public_enrollment_latest_school_year,
             public_enrollment_endpoints_complete, public_enrollment_trend,
            school_age_population, is_2020_2024_geography_comparable
     FROM edu_access.`06-analytics`.ap4_enrollment_trend_candidate) AS x));

-- The full-row comparison is computed once, above, because the summary is read once per result row.
-- The one-row summary the checks read is written to a table first. Read 20 times as a temporary view, it
-- made Databricks SQL's optimizer fail with INTERNAL_ERROR (dev run, 2026-10-20), as the DepEd PSGC gate did
-- (c64e949). The table is this run's own (its name holds a hash of run_id) and is dropped once the checks
-- are recorded, whether the gate passes or fails.
CREATE OR REPLACE TABLE IDENTIFIER(session.analytics_gate_summary) USING DELTA COMMENT 'Internal unpublished one-row summary for one ap4 gate. The gate drops it once its checks are recorded in data_quality_results.' AS
WITH ap4 AS (
  SELECT * FROM edu_access.`06-analytics`.ap4_enrollment_trend_candidate
),
gold_years AS (
  SELECT DISTINCT school_year FROM edu_access.`05-gold`.fact_school_enrollment
),
school_places AS (
  SELECT school_year, school_id, COUNT(DISTINCT city_mun_psgc_code) AS places
  FROM edu_access.`05-gold`.fact_school_enrollment GROUP BY school_year, school_id
),
expected_by_year AS (
  SELECT school_year, SUM(enrollment_all_sectors) AS enrollment, SUM(school_age_population) AS population
  FROM ap4_expected GROUP BY school_year
),
ap4_by_year AS (
  SELECT school_year, SUM(enrollment_all_sectors) AS enrollment, SUM(school_age_population) AS population
  FROM ap4 GROUP BY school_year
),
member_years AS (
  SELECT city_mun_psgc_code, COUNT(DISTINCT school_year) AS years,
         COUNT(DISTINCT COALESCE(enrollment_trend, '-')) AS trends,
         COUNT(DISTINCT is_2020_2024_geography_comparable) AS flags
  FROM ap4 GROUP BY city_mun_psgc_code
),
previous AS (
  SELECT a.city_mun_psgc_code, a.school_year, a.enrollment_change_from_previous_year, a.enrollment_change_pct_from_previous_year,
         a.enrollment_all_sectors,
         CASE WHEN LAG(a.school_year_start) OVER (PARTITION BY a.city_mun_psgc_code ORDER BY a.school_year) = a.school_year_start - 1
              THEN LAG(a.enrollment_all_sectors) OVER (PARTITION BY a.city_mun_psgc_code ORDER BY a.school_year) END AS previous_enrollment
  FROM ap4 AS a
)
SELECT
  session.analytics_ap4_rows_not_matching AS rows_not_matching_gold,
  (SELECT COUNT(*) FROM ap4) - (SELECT COUNT(*) FROM (SELECT DISTINCT city_mun_psgc_code, school_year FROM ap4) AS k) AS duplicate_keys,
  (SELECT COUNT_IF(city_mun_psgc_code IS NULL OR school_year IS NULL) FROM ap4) AS null_keys,
  (SELECT COUNT(*) FROM member_years WHERE years <> (SELECT COUNT(*) FROM gold_years)) AS members_missing_years,
  (SELECT COUNT(*) FROM (SELECT DISTINCT school_year FROM ap4) AS a LEFT JOIN gold_years AS g ON g.school_year = a.school_year
    WHERE g.school_year IS NULL) AS years_not_in_gold,
  (SELECT COUNT_IF(places > 1) FROM school_places) AS schools_in_two_places,
  (SELECT COUNT(*) FROM expected_by_year AS x FULL OUTER JOIN ap4_by_year AS a ON a.school_year = x.school_year
    WHERE a.enrollment IS DISTINCT FROM x.enrollment) AS enrollment_years_not_reconciled,
  (SELECT COUNT(*) FROM expected_by_year AS x FULL OUTER JOIN ap4_by_year AS a ON a.school_year = x.school_year
    WHERE a.population IS DISTINCT FROM x.population) AS population_years_not_reconciled,
  (SELECT COUNT_IF(NOT ((census_year = 2020 AND school_year = '2020-21') OR (census_year = 2024 AND school_year = '2024-25'))
                   AND (census_year IS NOT NULL OR school_age_population IS NOT NULL OR population_enrollment_gap IS NOT NULL))
   + COUNT_IF(school_year = '2020-21' AND census_year IS DISTINCT FROM 2020)
   + COUNT_IF(school_year = '2024-25' AND census_year IS DISTINCT FROM 2024)
   FROM ap4) AS unaligned_context_rows,
  (SELECT COUNT_IF(public_school_share IS DISTINCT FROM CAST(public_school_enrollment AS DOUBLE) / NULLIF(enrollment_all_sectors, 0)
                OR public_school_enrollment > enrollment_all_sectors
                OR population_enrollment_gap IS DISTINCT FROM school_age_population - enrollment_all_sectors
                OR gap_share IS DISTINCT FROM CAST(population_enrollment_gap AS DOUBLE) / NULLIF(school_age_population, 0)
                OR enrollment_change_first_to_latest IS DISTINCT FROM enrollment_latest_school_year - enrollment_first_school_year
                OR enrollment_change_pct_first_to_latest IS DISTINCT FROM
                   CAST(enrollment_change_first_to_latest AS DOUBLE) / NULLIF(enrollment_first_school_year, 0)
                OR public_enrollment_change_first_to_latest IS DISTINCT FROM
                   public_enrollment_latest_school_year - public_enrollment_first_school_year
                OR public_enrollment_change_pct_first_to_latest IS DISTINCT FROM
                   CAST(public_enrollment_change_first_to_latest AS DOUBLE) / NULLIF(public_enrollment_first_school_year, 0)
                OR (census_year IS NOT NULL AND (age_min <> 5 OR age_max <> 17))) FROM ap4) AS arithmetic_errors,
  (SELECT COUNT_IF(enrollment_change_from_previous_year IS DISTINCT FROM enrollment_all_sectors - previous_enrollment
                OR enrollment_change_pct_from_previous_year IS DISTINCT FROM
                   CAST(enrollment_all_sectors - previous_enrollment AS DOUBLE) / NULLIF(previous_enrollment, 0)) FROM previous) AS change_errors,
  (SELECT COUNT_IF(member_type IS DISTINCT FROM CASE city_mun_psgc_code WHEN 'UNKNOWN' THEN 'unknown'
                                                      WHEN 'EXCLUDED' THEN 'excluded' ELSE 'regular' END) FROM ap4) AS bad_member_type,
  (SELECT COUNT_IF(trends > 1 OR flags > 1) FROM member_years) AS members_with_two_trends,
  (SELECT COALESCE(SUM(schools_incomplete), 0) FROM ap4) AS schools_incomplete,
  (SELECT COALESCE(SUM(enrollment_all_sectors), 0) FROM ap4 WHERE member_type <> 'regular') AS learners_on_technical_members,
  (SELECT COALESCE(SUM(school_age_population), 0) FROM ap4 WHERE member_type = 'excluded') AS population_on_excluded,
  (SELECT COUNT_IF(member_type = 'regular' AND census_year IS NOT NULL AND school_age_population IS NULL) FROM ap4) AS regular_census_rows_without_population,
  (SELECT COUNT(*) FROM ap4) AS total_rows,
  (SELECT COUNT(DISTINCT CASE WHEN member_type = 'regular' AND enrollment_trend = 'increasing' THEN city_mun_psgc_code END) FROM ap4) AS members_increasing,
  (SELECT COUNT(DISTINCT CASE WHEN member_type = 'regular' AND enrollment_trend = 'decreasing' THEN city_mun_psgc_code END) FROM ap4) AS members_decreasing,
  (SELECT COUNT(DISTINCT CASE WHEN member_type = 'regular' AND enrollment_trend = 'no change' THEN city_mun_psgc_code END) FROM ap4) AS members_no_change;
SET VARIABLE analytics_gate_owner_sql = 'ALTER TABLE ' || session.analytics_gate_summary || ' OWNER TO `reached-hq`';
EXECUTE IMMEDIATE analytics_gate_owner_sql;

INSERT INTO edu_access.`01-control`.data_quality_results (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, NULL, 'ap4_enrollment_trend', 'analytics', 'edu_access.06-analytics.ap4_enrollment_trend_candidate', check_name, status, expected, actual, current_timestamp(), :code_revision
FROM (
  SELECT 'rows_match_gold' AS check_name, CASE WHEN rows_not_matching_gold = 0 THEN 'PASS' ELSE 'FAIL' END AS status, '0' AS expected, CAST(rows_not_matching_gold AS STRING) AS actual FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'key_unique', CASE WHEN duplicate_keys = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(duplicate_keys AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'key_not_null', CASE WHEN null_keys = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(null_keys AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'every_school_year_per_member', CASE WHEN members_missing_years = 0 AND years_not_in_gold = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(members_missing_years + years_not_in_gold AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'one_place_per_school_year', CASE WHEN schools_in_two_places = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(schools_in_two_places AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'enrollment_reconciles_by_school_year', CASE WHEN enrollment_years_not_reconciled = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(enrollment_years_not_reconciled AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'population_reconciles_by_census_year', CASE WHEN population_years_not_reconciled = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(population_years_not_reconciled AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'census_context_only_on_aligned_years', CASE WHEN unaligned_context_rows = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(unaligned_context_rows AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'arithmetic_holds', CASE WHEN arithmetic_errors = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(arithmetic_errors AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'year_over_year_change_holds', CASE WHEN change_errors = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(change_errors AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'member_type_fits_code', CASE WHEN bad_member_type = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_member_type AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'one_trend_per_member', CASE WHEN members_with_two_trends = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(members_with_two_trends AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'schools_incomplete', CASE WHEN schools_incomplete = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(schools_incomplete AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'learners_on_technical_members', CASE WHEN learners_on_technical_members = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(learners_on_technical_members AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'population_on_excluded', CASE WHEN population_on_excluded = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(population_on_excluded AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'regular_census_rows_without_population', CASE WHEN regular_census_rows_without_population = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(regular_census_rows_without_population AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'rows', 'PASS', CAST(NULL AS STRING), CAST(total_rows AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'members_increasing', 'PASS', CAST(NULL AS STRING), CAST(members_increasing AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'members_decreasing', 'PASS', CAST(NULL AS STRING), CAST(members_decreasing AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'members_no_change', 'PASS', CAST(NULL AS STRING), CAST(members_no_change AS STRING) FROM IDENTIFIER(session.analytics_gate_summary)
  UNION ALL SELECT 'enrollment_' || school_year, 'PASS', CAST(NULL AS STRING), CAST(enrollment AS STRING) FROM (SELECT school_year, SUM(enrollment_all_sectors) AS enrollment FROM edu_access.`06-analytics`.ap4_enrollment_trend_candidate GROUP BY school_year) AS national
) AS results;

-- Every check is recorded, so the summary is no longer needed, whether the gate passes or fails.
DROP TABLE IF EXISTS IDENTIFIER(session.analytics_gate_summary);

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Analytics gate failed for ap4_enrollment_trend: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s) in data_quality_results for run ' || :run_id) END
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = :run_id AND source_id = 'ap4_enrollment_trend' AND layer = 'analytics' AND status = 'FAIL'
  AND checked_at_utc >= session.analytics_gate_started_at_utc;

-- Every check passed: publish.
CREATE OR REPLACE TABLE edu_access.`06-analytics`.ap4_enrollment_trend USING DELTA AS
SELECT * FROM edu_access.`06-analytics`.ap4_enrollment_trend_candidate;

COMMENT ON TABLE edu_access.`06-analytics`.ap4_enrollment_trend IS 'AP4: all-sector enrollment (PSO excluded) by city or municipality and school year, its year-over-year change and first-to-latest trend, with school-age population (5 to 17) and the gap as context on the 2020 and 2024 census school years only.';
ALTER TABLE edu_access.`06-analytics`.ap4_enrollment_trend OWNER TO `reached-hq`;
