-- lgu planning-priority matrix under D-061.
-- AP2 and AP3 provide separate current-pressure flags. AP4 supplies public-school enrollment growth.
-- AP1 and the population-enrollment gap remain context and never change the priority category.
-- A published pressure signal always counts: AP3's teacher flag comes from any level above its reference (that
-- level passed its own coverage gate), even when another offered level is incomplete. Unassessed growth never
-- raises a category, so an LGU with a known pressure is placed as if it were not growing. Data review is used only
-- when no measure shows pressure and a coverage gate failed or growth cannot be assessed. Growth is not assessed
-- where the 2020-to-2024 geography is not comparable (boundary changes such as Makati/Taguig and the SGA).

CREATE SCHEMA IF NOT EXISTS edu_access.`06-analytics`;
ALTER SCHEMA edu_access.`06-analytics` OWNER TO `reached-hq`;

CREATE OR REPLACE TABLE edu_access.`06-analytics`.lgu_priority_matrix_candidate USING DELTA AS
WITH joined AS (
  SELECT
    l.city_mun_psgc_code, l.city_mun_name, l.lgu_type, l.province_psgc_code, l.province_name,
    l.region_psgc_code, l.region_name, CAST('2023-24' AS STRING) AS school_year,
    a.learners_per_public_school AS ap1_learners_per_public_school, a.coverage_pct AS ap1_coverage_pct,
    a.is_assessed AS ap1_assessed, a.public_school_enrollment AS ap1_public_school_enrollment,
    a.school_age_population_per_public_school AS ap1_school_age_population_per_public_school,
    b.learners_per_classroom AS ap2_learners_per_reported_room, b.learner_coverage_pct AS ap2_learner_coverage_pct,
    b.is_assessed AS ap2_assessed, b.congested_school_count AS ap2_affected_school_count,
    b.learners_in_congested_schools AS ap2_affected_learners,
    b.congested_learner_share_pct AS ap2_affected_learner_share_pct, b.benchmark_status AS ap2_screen_status,
    c.es_learners_per_teacher AS ap3_es_learners_per_teacher,
    c.jhs_learners_per_teacher AS ap3_jhs_learners_per_teacher,
    c.shs_learners_per_teacher AS ap3_shs_learners_per_teacher, c.is_assessed AS ap3_assessed,
    c.benchmark_status AS ap3_review_status,
    CAST((CASE WHEN c.es_benchmark_status = 'above historical study reference' THEN 1 ELSE 0 END)
      + (CASE WHEN c.jhs_benchmark_status = 'above derived deployment comparison' THEN 1 ELSE 0 END)
      + (CASE WHEN c.shs_benchmark_status = 'above derived deployment comparison' THEN 1 ELSE 0 END) AS INT)
      AS ap3_pressured_level_count,
    CAST((CASE WHEN c.es_benchmark_status = 'above historical study reference' THEN c.es_eligible_learners ELSE 0 END)
      + (CASE WHEN c.jhs_benchmark_status = 'above derived deployment comparison' THEN c.jhs_eligible_learners ELSE 0 END)
      + (CASE WHEN c.shs_benchmark_status = 'above derived deployment comparison' THEN c.shs_eligible_learners ELSE 0 END) AS BIGINT)
      AS ap3_affected_learners,
    d.public_enrollment_first_school_year AS ap4_public_enrollment_first,
    d.public_enrollment_latest_school_year AS ap4_public_enrollment_latest,
    d.public_enrollment_change_first_to_latest AS ap4_public_enrollment_change,
    100 * d.public_enrollment_change_pct_first_to_latest AS ap4_public_enrollment_change_pct,
    d.public_enrollment_trend AS ap4_public_enrollment_trend,
    d.public_enrollment_endpoints_complete AS ap4_public_enrollment_endpoints_complete,
    d.is_2020_2024_geography_comparable AS ap4_geography_comparable,
    g.population_enrollment_gap AS ap4_gap_2024, 100 * g.gap_share AS ap4_gap_rate_2024_pct,
    -- why growth is not assessed; NULL exactly when growing_enrollment is assessed
    CASE WHEN d.city_mun_psgc_code IS NULL THEN 'no AP4 enrollment row'
         WHEN COALESCE(d.is_2020_2024_geography_comparable, FALSE) AND d.public_enrollment_trend IS NOT NULL THEN NULL
         WHEN NOT COALESCE(d.is_2020_2024_geography_comparable, FALSE) AND g.school_age_population IS NULL
           THEN 'no 2024 census population row'
         WHEN NOT COALESCE(d.is_2020_2024_geography_comparable, FALSE) THEN 'boundary changed 2020-2024'
         WHEN NOT COALESCE(d.public_enrollment_endpoints_complete, FALSE)
           THEN 'public enrollment incomplete in first or latest school year'
         ELSE 'no public enrollment in first school year' END AS growth_not_assessed_reason
  FROM edu_access.`05-gold`.dim_city_municipality AS l
  LEFT JOIN edu_access.`06-analytics`.ap1_school_provision AS a USING (city_mun_psgc_code)
  LEFT JOIN edu_access.`06-analytics`.ap2_classroom_pressure AS b USING (city_mun_psgc_code)
  LEFT JOIN edu_access.`06-analytics`.ap3_teacher_pressure AS c USING (city_mun_psgc_code)
  LEFT JOIN edu_access.`06-analytics`.ap4_enrollment_trend AS d
    ON d.city_mun_psgc_code = l.city_mun_psgc_code AND d.school_year = d.latest_school_year
  LEFT JOIN edu_access.`06-analytics`.ap4_enrollment_trend AS g
    ON g.city_mun_psgc_code = l.city_mun_psgc_code AND g.school_year = '2024-25'
  WHERE l.member_type = 'regular'
), classified AS (
  SELECT *,
    CAST(CASE WHEN ap2_assessed AND ap2_affected_school_count > 0 THEN 1 ELSE 0 END AS INT) AS classroom_pressure_flag,
    CAST(CASE WHEN ap3_pressured_level_count > 0 THEN 1 ELSE 0 END AS INT) AS teacher_pressure_flag,
    CASE WHEN NOT COALESCE(ap4_geography_comparable, FALSE) THEN NULL
         WHEN ap4_public_enrollment_trend = 'increasing' THEN TRUE
         WHEN ap4_public_enrollment_trend IN ('decreasing', 'no change') THEN FALSE END AS growing_enrollment
  FROM joined
), grouped AS (
  SELECT *, classroom_pressure_flag + teacher_pressure_flag AS current_pressure_count,
    GREATEST(COALESCE(ap2_affected_learners, 0), COALESCE(ap3_affected_learners, 0)) AS priority_affected_learners,
    CASE WHEN classroom_pressure_flag + teacher_pressure_flag = 0
           AND (growing_enrollment IS NULL OR NOT COALESCE(ap2_assessed, FALSE) OR NOT COALESCE(ap3_assessed, FALSE))
           THEN 'Data review'
         WHEN classroom_pressure_flag + teacher_pressure_flag = 2 AND COALESCE(growing_enrollment, FALSE) THEN 'Priority 1'
         WHEN classroom_pressure_flag + teacher_pressure_flag = 2
           OR (classroom_pressure_flag + teacher_pressure_flag = 1 AND COALESCE(growing_enrollment, FALSE)) THEN 'Priority 2'
         WHEN classroom_pressure_flag + teacher_pressure_flag = 1 THEN 'Priority 3'
         WHEN growing_enrollment THEN 'Monitor'
         ELSE 'No current pressure identified' END AS priority_category
  FROM classified
)
SELECT *, ROW_NUMBER() OVER (
    ORDER BY CASE priority_category WHEN 'Priority 1' THEN 1 WHEN 'Priority 2' THEN 2 WHEN 'Priority 3' THEN 3
                                    WHEN 'Monitor' THEN 4 WHEN 'No current pressure identified' THEN 5 ELSE 6 END,
      current_pressure_count DESC, priority_affected_learners DESC, ap2_affected_learners DESC,
      ap3_pressured_level_count DESC, ap4_public_enrollment_change DESC,
      ap4_public_enrollment_change_pct DESC, city_mun_psgc_code
  ) AS priority_order,
  'D-061' AS rule_version, :code_revision AS code_revision
FROM grouped;

COMMENT ON TABLE edu_access.`06-analytics`.lgu_priority_matrix_candidate IS 'Unpublished AP2 and AP3 pressure and AP4 public-enrollment priority build under D-061.';
ALTER TABLE edu_access.`06-analytics`.lgu_priority_matrix_candidate OWNER TO `reached-hq`;
