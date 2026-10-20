-- LGU priority table under the priority rule D-057, from the published AP1 to AP3 outputs, with AP4 as context.
-- grain: one regular city or municipality, SY 2023-24.
-- tier (D-057): Critical when all three measures are high (90th percentile within LGU type), Elevated with two,
-- Targeted with one (naming the measure), Monitor with none, and Data review when any measure is not assessed.
-- a count of high measures is not a weighted score. order within a tier: affected learners (the AP1 public enrollment
-- total), highest first, then the lowest of the three percentiles, highest first. the same rule run nationally gives
-- the national tier, and an LGU that is Critical both ways is Stable. the tier always comes from the within-type rank.
-- AP4, poverty and Similar LGUs are context and never change a tier. the result is relative pressure, not a shortage.

CREATE SCHEMA IF NOT EXISTS edu_access.`06-analytics`;
ALTER SCHEMA edu_access.`06-analytics` OWNER TO `reached-hq`;

CREATE OR REPLACE TABLE edu_access.`06-analytics`.lgu_priority_matrix_candidate USING DELTA AS
WITH joined AS (
  SELECT
    l.city_mun_psgc_code, l.city_mun_name, l.lgu_type, l.province_psgc_code, l.province_name,
    l.region_psgc_code, l.region_name,
    CAST('2023-24' AS STRING) AS school_year,
    a.learners_per_public_school AS ap1_learners_per_public_school,
    a.coverage_pct AS ap1_coverage_pct,
    a.is_assessed AS ap1_assessed,
    a.within_type_percentile AS ap1_percentile,
    a.national_percentile AS ap1_national_percentile,
    a.is_high AS ap1_high,
    a.is_high_nationally AS ap1_high_nationally,
    a.public_school_enrollment AS affected_learners,
    a.school_age_population_per_public_school AS ap1_school_age_population_per_public_school,
    b.learners_per_classroom AS ap2_learners_per_classroom,
    b.learner_coverage_pct AS ap2_learner_coverage_pct,
    b.is_assessed AS ap2_assessed,
    b.within_type_percentile AS ap2_percentile,
    b.national_percentile AS ap2_national_percentile,
    b.is_high AS ap2_high,
    b.is_high_nationally AS ap2_high_nationally,
    b.outlier_school_count AS ap2_outlier_school_count,
    c.es_learners_per_teacher AS ap3_es_learners_per_teacher,
    c.jhs_learners_per_teacher AS ap3_jhs_learners_per_teacher,
    c.shs_learners_per_teacher AS ap3_shs_learners_per_teacher,
    c.highest_level AS ap3_highest_level,
    c.is_assessed AS ap3_assessed,
    c.is_assessed_nationally AS ap3_assessed_nationally,
    c.within_type_percentile AS ap3_percentile,
    c.national_percentile AS ap3_national_percentile,
    c.is_high AS ap3_high,
    c.is_high_nationally AS ap3_high_nationally,
    COALESCE(c.es_outlier_school_count, 0) + COALESCE(c.jhs_outlier_school_count, 0)
      + COALESCE(c.shs_outlier_school_count, 0) AS ap3_outlier_school_level_count,
    d.ap4_gap_2020, d.ap4_gap_2024, d.ap4_gap_rate_2020_pct, d.ap4_gap_rate_2024_pct, d.ap4_gap_change,
    d.ap4_enrollment_trend, d.ap4_enrollment_change_pct
  FROM edu_access.`05-gold`.dim_city_municipality AS l
  LEFT JOIN edu_access.`06-analytics`.ap1_school_provision AS a USING (city_mun_psgc_code)
  LEFT JOIN edu_access.`06-analytics`.ap2_classroom_pressure AS b USING (city_mun_psgc_code)
  LEFT JOIN edu_access.`06-analytics`.ap3_teacher_pressure AS c USING (city_mun_psgc_code)
  -- AP4 has one row per city and school year: read one row per city, the census-year gaps and the trend.
  LEFT JOIN (
    SELECT city_mun_psgc_code,
           MAX(CASE WHEN school_year = '2020-21' THEN population_enrollment_gap END) AS ap4_gap_2020,
           MAX(CASE WHEN school_year = '2024-25' THEN population_enrollment_gap END) AS ap4_gap_2024,
           MAX(CASE WHEN school_year = '2020-21' THEN 100 * gap_share END) AS ap4_gap_rate_2020_pct,
           MAX(CASE WHEN school_year = '2024-25' THEN 100 * gap_share END) AS ap4_gap_rate_2024_pct,
           CASE WHEN BOOL_AND(is_2020_2024_geography_comparable)
                THEN MAX(CASE WHEN school_year = '2024-25' THEN population_enrollment_gap END)
                   - MAX(CASE WHEN school_year = '2020-21' THEN population_enrollment_gap END) END AS ap4_gap_change,
           MAX(enrollment_trend) AS ap4_enrollment_trend,
           MAX(enrollment_change_pct_first_to_latest) AS ap4_enrollment_change_pct
    FROM edu_access.`06-analytics`.ap4_enrollment_trend
    WHERE member_type = 'regular'
    GROUP BY city_mun_psgc_code
  ) AS d USING (city_mun_psgc_code)
  WHERE l.member_type = 'regular'
), counted AS (
  SELECT *,
         COALESCE(ap1_assessed AND ap2_assessed AND ap3_assessed, FALSE) AS all_assessed,
         COALESCE(ap1_assessed AND ap2_assessed AND ap3_assessed_nationally, FALSE) AS all_assessed_nationally,
         CAST(COALESCE(ap1_high, FALSE) AS INT) + CAST(COALESCE(ap2_high, FALSE) AS INT)
           + CAST(COALESCE(ap3_high, FALSE) AS INT) AS high_measure_count,
         CAST(COALESCE(ap1_high_nationally, FALSE) AS INT) + CAST(COALESCE(ap2_high_nationally, FALSE) AS INT)
           + CAST(COALESCE(ap3_high_nationally, FALSE) AS INT) AS high_measure_count_nationally,
         LEAST(ap1_percentile, ap2_percentile, ap3_percentile) AS lowest_percentile,
         NULLIF(CONCAT_WS(', ',
           CASE WHEN ap1_high THEN 'AP1 learners per public school' END,
           CASE WHEN ap2_high THEN 'AP2 learners per classroom' END,
           CASE WHEN ap3_high THEN CONCAT('AP3 learners per teacher (', ap3_highest_level, ')') END), '') AS high_measures
  FROM joined
), tiered AS (
  SELECT *,
         CASE WHEN NOT all_assessed THEN 'data_review' ELSE CAST(high_measure_count AS STRING) END AS tier_code,
         CASE WHEN NOT all_assessed THEN 'Data review'
              WHEN high_measure_count = 3 THEN 'Critical'
              WHEN high_measure_count = 2 THEN 'Elevated'
              WHEN high_measure_count = 1 THEN 'Targeted'
              ELSE 'Monitor' END AS tier,
         CASE WHEN NOT all_assessed_nationally THEN 'Data review'
              WHEN high_measure_count_nationally = 3 THEN 'Critical'
              WHEN high_measure_count_nationally = 2 THEN 'Elevated'
              WHEN high_measure_count_nationally = 1 THEN 'Targeted'
              ELSE 'Monitor' END AS national_tier
  FROM counted
)
SELECT *,
       tier = 'Critical' AND national_tier = 'Critical' AS is_stable,
       CASE tier
         WHEN 'Critical' THEN 'High on all three measures compared with LGUs of the same type: relative pressure, not a shortage'
         WHEN 'Elevated' THEN 'High on two of the three measures compared with LGUs of the same type'
         WHEN 'Targeted' THEN CONCAT('High on one measure compared with LGUs of the same type: ', high_measures)
         WHEN 'Monitor' THEN 'No measure at the 90th percentile within LGU type'
         ELSE 'At least one measure could not be assessed (coverage below 90% or no data), and the measures it could compute are still shown'
       END AS tier_meaning,
       ROW_NUMBER() OVER (PARTITION BY tier
         ORDER BY affected_learners DESC NULLS LAST, lowest_percentile DESC NULLS LAST, city_mun_psgc_code) AS order_in_tier,
       'D-057' AS rule_version,
       :code_revision AS code_revision
FROM tiered;

COMMENT ON TABLE edu_access.`06-analytics`.lgu_priority_matrix_candidate IS 'Unpublished priority table. Do not read: use lgu_priority_matrix.';
ALTER TABLE edu_access.`06-analytics`.lgu_priority_matrix_candidate OWNER TO `reached-hq`;
