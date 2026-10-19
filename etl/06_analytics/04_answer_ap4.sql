-- ap4 enrollment direction under the methodology that supersedes D-057.
-- grain: one regular city or municipality across SY 2020-21 through SY 2025-26.
-- growth needs more than +5% and decline less than -5%, anything within the band is Stable. the trend is Data Review
-- when the national matched-learner share moves more than 2 points between the endpoints.

CREATE SCHEMA IF NOT EXISTS edu_access.`06-analytics`;
ALTER SCHEMA edu_access.`06-analytics` OWNER TO `reached-hq`;

CREATE OR REPLACE TABLE edu_access.`06-analytics`.ap4_enrollment_trend_candidate USING DELTA AS
WITH lgus AS (
  SELECT city_mun_psgc_code, city_mun_name, lgu_type, province_psgc_code, province_name,
         region_psgc_code, region_name
  FROM edu_access.`05-gold`.dim_city_municipality
  WHERE member_type = 'regular'
), years AS (
  SELECT * FROM VALUES ('2020-21'), ('2021-22'), ('2022-23'), ('2023-24'), ('2024-25'), ('2025-26')
    AS v(school_year)
), availability AS (
  SELECT school_year, TRUE AS has_data
  FROM edu_access.`05-gold`.fact_school_enrollment
  GROUP BY school_year
), school_totals AS (
  SELECT school_id, school_year, city_mun_psgc_code, MIN(psgc_match_status) AS psgc_match_status,
         CASE WHEN COUNT_IF(is_offered IS NULL OR (is_offered AND learner_count IS NULL)) > 0 THEN NULL
              ELSE SUM(CASE WHEN is_offered THEN learner_count ELSE 0 END) END AS school_learners
  FROM edu_access.`05-gold`.fact_school_enrollment
  WHERE school_year IN ('2020-21', '2021-22', '2022-23', '2023-24', '2024-25', '2025-26')
    AND sector IN ('Public', 'Private', 'SUC/LUC')
  GROUP BY school_id, school_year, city_mun_psgc_code
), matched_share AS (
  -- learners at schools placed in a city or municipality, out of all complete schools that year; a large move
  -- between the endpoints means part of any change could be matching, not enrollment.
  SELECT school_year,
         CAST(100.0 * SUM(CASE WHEN psgc_match_status = 'matched' THEN school_learners ELSE 0 END)
           / NULLIF(SUM(school_learners), 0) AS DOUBLE) AS matched_learner_share_pct
  FROM school_totals
  GROUP BY school_year
), enrollment AS (
  SELECT city_mun_psgc_code, school_year, CAST(COALESCE(SUM(school_learners), 0) AS BIGINT) AS enrollment,
         COUNT(*) AS school_count, COUNT_IF(school_learners IS NOT NULL) AS complete_school_count,
         COUNT_IF(school_learners IS NULL) AS incomplete_school_count
  FROM school_totals
  WHERE psgc_match_status = 'matched'
  GROUP BY city_mun_psgc_code, school_year
), grid AS (
  SELECT l.city_mun_psgc_code, l.city_mun_name, l.lgu_type, l.province_psgc_code, l.province_name,
         l.region_psgc_code, l.region_name, y.school_year,
         COALESCE(a.has_data, FALSE) AS source_available,
         CASE WHEN COALESCE(a.has_data, FALSE) THEN COALESCE(e.enrollment, 0) END AS enrollment,
         CASE WHEN COALESCE(a.has_data, FALSE) THEN COALESCE(e.school_count, 0) END AS school_count,
         CASE WHEN COALESCE(a.has_data, FALSE) THEN COALESCE(e.complete_school_count, 0) END AS complete_school_count,
         CASE WHEN COALESCE(a.has_data, FALSE) THEN COALESCE(e.incomplete_school_count, 0) END AS incomplete_school_count
  FROM lgus AS l
  CROSS JOIN years AS y
  LEFT JOIN availability AS a USING (school_year)
  LEFT JOIN enrollment AS e ON e.city_mun_psgc_code = l.city_mun_psgc_code AND e.school_year = y.school_year
), pivoted AS (
  SELECT city_mun_psgc_code, MAX(city_mun_name) AS city_mun_name, MAX(lgu_type) AS lgu_type,
         MAX(province_psgc_code) AS province_psgc_code, MAX(province_name) AS province_name,
         MAX(region_psgc_code) AS region_psgc_code, MAX(region_name) AS region_name,
         MAX(CASE WHEN school_year = '2020-21' THEN enrollment END) AS enrollment_2020_21,
         MAX(CASE WHEN school_year = '2021-22' THEN enrollment END) AS enrollment_2021_22,
         MAX(CASE WHEN school_year = '2022-23' THEN enrollment END) AS enrollment_2022_23,
         MAX(CASE WHEN school_year = '2023-24' THEN enrollment END) AS enrollment_2023_24,
         MAX(CASE WHEN school_year = '2024-25' THEN enrollment END) AS enrollment_2024_25,
         MAX(CASE WHEN school_year = '2025-26' THEN enrollment END) AS enrollment_2025_26,
         COUNT_IF(source_available) AS available_year_count,
         SUM(COALESCE(incomplete_school_count, 0)) AS incomplete_school_year_rows,
         CAST(100.0 * SUM(COALESCE(complete_school_count, 0))
           / NULLIF(SUM(COALESCE(school_count, 0)), 0) AS DOUBLE) AS complete_school_coverage_pct
  FROM grid
  GROUP BY city_mun_psgc_code
), changes AS (
  SELECT p.*,
         (SELECT matched_learner_share_pct FROM matched_share WHERE school_year = '2020-21')
           AS matched_learner_share_2020_21_pct,
         (SELECT matched_learner_share_pct FROM matched_share WHERE school_year = '2025-26')
           AS matched_learner_share_2025_26_pct,
         CASE WHEN available_year_count = 6 THEN enrollment_2025_26 - enrollment_2020_21 END AS absolute_change,
         CASE WHEN available_year_count = 6 THEN
           CAST(enrollment_2025_26 - enrollment_2020_21 AS DOUBLE) / NULLIF(enrollment_2020_21, 0) END AS pct_change
  FROM pivoted AS p
)
SELECT *,
       matched_learner_share_2025_26_pct - matched_learner_share_2020_21_pct AS matched_learner_share_change_pts,
       CAST(0.05 AS DOUBLE) AS stable_band,
       CASE WHEN available_year_count < 6 THEN NULL
            WHEN enrollment_2020_21 IS NULL OR enrollment_2020_21 = 0 THEN NULL
            WHEN pct_change > 0.05 THEN 'Growing'
            WHEN pct_change < -0.05 THEN 'Declining'
            ELSE 'Stable' END AS trend_direction,
       CASE WHEN available_year_count < 6 THEN 'Data Review: one or more enrollment years unavailable'
            WHEN enrollment_2020_21 IS NULL OR enrollment_2020_21 = 0 THEN 'Data Review: starting enrollment is null or zero'
            WHEN incomplete_school_year_rows > 0 THEN 'Data Review: one or more school totals are incomplete'
            WHEN matched_learner_share_2025_26_pct IS NULL OR matched_learner_share_2020_21_pct IS NULL
              OR ABS(matched_learner_share_2025_26_pct - matched_learner_share_2020_21_pct) > 2
              THEN 'Data Review: matched-learner share moved more than 2 points'
            ELSE 'Complete' END AS trend_status,
       :code_revision AS code_revision
FROM changes;

COMMENT ON TABLE edu_access.`06-analytics`.ap4_enrollment_trend_candidate IS 'Unpublished AP4 build. Do not read: use ap4_enrollment_trend.';
ALTER TABLE edu_access.`06-analytics`.ap4_enrollment_trend_candidate OWNER TO `reached-hq`;

