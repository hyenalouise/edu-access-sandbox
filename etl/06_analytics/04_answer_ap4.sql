-- Analytics output for AP4 (#147): enrollment by city or municipality and school year and whether it goes up
-- or down, with the school-age population gap on the census school years. Implements the AP4 contract of
-- docs/business/metric-specification.md and the team's BP and AP metrics (D-042). AP4 is context under D-057
-- and never changes a priority tier.
--
-- Grain: one row per city or municipality member and school year, key (city_mun_psgc_code,
-- school_year), for every school year in fact_school_enrollment (SY 2020-21 to 2025-26 today).
--
-- Reads published Gold only: fact_school_enrollment and fact_city_school_age_population. Writes
-- ap4_enrollment_trend_candidate; the gate (the next task) checks it and publishes ap4_enrollment_trend
-- only if no check fails, so a FAIL keeps the last good output.
--
-- The answer: enrolled learners each school year, and whether they go up or down.
--   - enrollment_all_sectors: learners in Public, Private and SUC/LUC schools located in the city or
--     municipality that school year; Philippine Schools Overseas excluded. A school counts with its
--     all-level total: ES + JHS + SHS when every offered level has a learner_count, otherwise NULL
--     ("Enrollment aggregation and missingness"). NULL totals are left out of the sums and counted in
--     schools_incomplete, never read as 0. A member with no school that year has 0.
--   - enrollment_change_from_previous_year: against the member's row for the school year just before;
--     NULL for the first school year, and when the school year before is not in the data, so a missing
--     year never turns into a several-year change.
--   - The trend: enrollment_change_first_to_latest compares the first school year in the data with the
--     latest (SY 2020-21 and 2025-26 today). enrollment_trend is 'increasing', 'decreasing' or
--     'no change' by the sign of that change, with no threshold; NULL for the technical members.
--     Percent changes are NULL when the base is 0.
--   - Geography is each school year's own (D-048): a school that moves is counted where it was that year.
--
-- Context only: school-age population against enrollment, where a census matches the school year.
--   - Census years pair with the school year that starts in the same year: the 2020 Census of
--     Population and Housing (May 1, 2020) with SY 2020-21, the 2024 Census of Population (July 1,
--     2024) with SY 2024-25. Other school years have no population: census_context says why.
--     Nothing is interpolated or extrapolated.
--   - school_age_population: ages 5 to 17, male plus female rows (never the published both-sexes total).
--   - population_enrollment_gap = school_age_population - enrollment_all_sectors, kept when negative;
--     gap_share = gap / school_age_population. An arithmetic difference, not an out-of-school count.
--   - is_2020_2024_geography_comparable is the population fact's flag (territory changes and units that
--     exist in one census only are FALSE); technical members and units without population are FALSE.
--
-- Every member with population or enrollment gets a row for every school year, the UNKNOWN and EXCLUDED
-- technical members included (member_type), so the rows add up to the national totals and unplaced
-- schools and people stay visible. Dashboards filter member_type = 'regular'.

CREATE SCHEMA IF NOT EXISTS edu_access.`06-analytics`;
ALTER SCHEMA edu_access.`06-analytics` OWNER TO `reached-hq`;

CREATE OR REPLACE TABLE edu_access.`06-analytics`.ap4_enrollment_trend_candidate USING DELTA AS
WITH school_years AS (
  SELECT DISTINCT school_year, CAST(substr(school_year, 1, 4) AS INT) AS school_year_start
  FROM edu_access.`05-gold`.fact_school_enrollment
),
bounds AS (
  SELECT MIN(school_year) AS first_school_year, MAX(school_year) AS latest_school_year FROM school_years
),
censuses AS (
  SELECT * FROM (VALUES
    (2020, DATE '2020-05-01', '2020 Census of Population and Housing (CPH), PSA Total Population'),
    (2024, DATE '2024-07-01', '2024 Census of Population (POPCEN), PSA Total Population')
  ) AS v(census_year, population_reference_date, population_source)
),
-- One all-level total per school and school year: NULL when any offered level has no learner_count.
school_totals AS (
  SELECT
    e.school_year,
    e.school_id,
    e.city_mun_psgc_code,
    e.sector,
    CASE WHEN COUNT_IF(e.is_offered IS NULL OR (e.is_offered AND e.learner_count IS NULL)) > 0 THEN NULL
         ELSE SUM(CASE WHEN e.is_offered THEN e.learner_count ELSE 0 END) END AS school_learners
  FROM edu_access.`05-gold`.fact_school_enrollment AS e
  WHERE e.sector IN ('Public', 'Private', 'SUC/LUC')
  GROUP BY e.school_year, e.school_id, e.city_mun_psgc_code, e.sector
),
enrollment AS (
  SELECT
    school_year,
    city_mun_psgc_code,
    CAST(COALESCE(SUM(school_learners), 0) AS BIGINT) AS enrollment_all_sectors,
    CAST(COALESCE(SUM(CASE WHEN sector = 'Public' THEN school_learners END), 0) AS BIGINT) AS public_school_enrollment,
    COUNT(school_learners) AS schools_counted,
    COUNT_IF(school_learners IS NULL) AS schools_incomplete
  FROM school_totals
  GROUP BY school_year, city_mun_psgc_code
),
population AS (
  SELECT
    f.reference_year AS census_year,
    f.city_mun_psgc_code,
    CAST(SUM(f.population) AS BIGINT) AS school_age_population,
    BOOL_AND(f.is_2020_2024_geography_comparable) AS is_2020_2024_geography_comparable
  FROM edu_access.`05-gold`.fact_city_school_age_population AS f
  JOIN censuses AS c ON c.census_year = f.reference_year
  WHERE f.sex IN ('male', 'female') AND f.age BETWEEN 5 AND 17
  GROUP BY f.reference_year, f.city_mun_psgc_code
),
comparability AS (
  SELECT city_mun_psgc_code, BOOL_AND(is_2020_2024_geography_comparable) AS is_2020_2024_geography_comparable
  FROM population GROUP BY city_mun_psgc_code
),
members AS (
  SELECT city_mun_psgc_code FROM population
  UNION
  SELECT city_mun_psgc_code FROM enrollment
),
grid AS (
  SELECT
    m.city_mun_psgc_code,
    CASE m.city_mun_psgc_code WHEN 'UNKNOWN' THEN 'unknown' WHEN 'EXCLUDED' THEN 'excluded' ELSE 'regular' END AS member_type,
    y.school_year,
    y.school_year_start,
    COALESCE(e.enrollment_all_sectors, 0) AS enrollment_all_sectors,
    COALESCE(e.public_school_enrollment, 0) AS public_school_enrollment,
    COALESCE(e.schools_counted, 0) AS schools_counted,
    COALESCE(e.schools_incomplete, 0) AS schools_incomplete
  FROM members AS m
  CROSS JOIN school_years AS y
  LEFT JOIN enrollment AS e ON e.city_mun_psgc_code = m.city_mun_psgc_code AND e.school_year = y.school_year
),
trend AS (
  SELECT
    g.*,
    CASE WHEN LAG(g.school_year_start) OVER (PARTITION BY g.city_mun_psgc_code ORDER BY g.school_year_start) = g.school_year_start - 1
         THEN LAG(g.enrollment_all_sectors) OVER (PARTITION BY g.city_mun_psgc_code ORDER BY g.school_year_start) END
      AS previous_enrollment,
    f.enrollment_all_sectors AS enrollment_first_school_year,
    l.enrollment_all_sectors AS enrollment_latest_school_year
  FROM grid AS g
  CROSS JOIN bounds AS b
  JOIN grid AS f ON f.city_mun_psgc_code = g.city_mun_psgc_code AND f.school_year = b.first_school_year
  JOIN grid AS l ON l.city_mun_psgc_code = g.city_mun_psgc_code AND l.school_year = b.latest_school_year
)
SELECT
  t.city_mun_psgc_code,
  t.member_type,
  t.school_year,
  CAST(t.school_year_start AS INT) AS school_year_start,
  t.enrollment_all_sectors,
  t.public_school_enrollment,
  CAST(t.public_school_enrollment AS DOUBLE) / NULLIF(t.enrollment_all_sectors, 0) AS public_school_share,
  t.schools_counted,
  t.schools_incomplete,
  t.enrollment_all_sectors - t.previous_enrollment AS enrollment_change_from_previous_year,
  CAST(t.enrollment_all_sectors - t.previous_enrollment AS DOUBLE) / NULLIF(t.previous_enrollment, 0) AS enrollment_change_pct_from_previous_year,
  b.first_school_year,
  b.latest_school_year,
  t.enrollment_first_school_year,
  t.enrollment_latest_school_year,
  t.enrollment_latest_school_year - t.enrollment_first_school_year AS enrollment_change_first_to_latest,
  CAST(t.enrollment_latest_school_year - t.enrollment_first_school_year AS DOUBLE) / NULLIF(t.enrollment_first_school_year, 0)
    AS enrollment_change_pct_first_to_latest,
  CASE WHEN t.member_type <> 'regular' THEN NULL
       WHEN t.enrollment_latest_school_year > t.enrollment_first_school_year THEN 'increasing'
       WHEN t.enrollment_latest_school_year < t.enrollment_first_school_year THEN 'decreasing'
       ELSE 'no change' END AS enrollment_trend,
  c.census_year,
  c.population_source,
  c.population_reference_date,
  CASE WHEN c.census_year IS NOT NULL THEN 5 END AS age_min,
  CASE WHEN c.census_year IS NOT NULL THEN 17 END AS age_max,
  p.school_age_population,
  p.school_age_population - t.enrollment_all_sectors AS population_enrollment_gap,
  CAST(p.school_age_population - t.enrollment_all_sectors AS DOUBLE) / NULLIF(p.school_age_population, 0) AS gap_share,
  CASE WHEN c.census_year IS NULL THEN 'not available: no census in this school year'
       WHEN p.school_age_population IS NULL THEN 'not available: no census population for this member'
       ELSE 'available' END AS census_context,
  COALESCE(t.member_type = 'regular' AND k.is_2020_2024_geography_comparable, FALSE) AS is_2020_2024_geography_comparable,
  'Public, Private and SUC/LUC schools, Philippine Schools Overseas excluded' AS enrollment_scope,
  'Enrollment counts learners where the school is, by the geography of each school year. The trend compares the '
    || 'first and latest school years. The census context is an arithmetic difference between residents aged '
    || '5 to 17 and enrolled learners, not an out-of-school count or an enrollment rate, and a negative gap '
    || 'usually marks a school hub.' AS interpretation_note
FROM trend AS t
CROSS JOIN bounds AS b
LEFT JOIN censuses AS c ON c.census_year = t.school_year_start
LEFT JOIN population AS p ON p.city_mun_psgc_code = t.city_mun_psgc_code AND p.census_year = c.census_year
LEFT JOIN comparability AS k ON k.city_mun_psgc_code = t.city_mun_psgc_code;

COMMENT ON TABLE edu_access.`06-analytics`.ap4_enrollment_trend_candidate IS 'Unpublished build for the Analytics gate, which may have failed. Do not read: use ap4_enrollment_trend.';
ALTER TABLE edu_access.`06-analytics`.ap4_enrollment_trend_candidate OWNER TO `reached-hq`;
