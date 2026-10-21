-- LGU evidence table under D-060, from the published AP1 to AP3 outputs, with AP4 as context.
-- grain: one regular city or municipality, SY 2023-24.
-- there is no composite score, percentile tier, or overall LGU rank.
-- the only ranked queue in this version is the classroom-screening queue: LGUs with school-level reported-room
-- congestion are ordered by affected learners, then affected schools, then the descriptive pooled room ratio.
-- DENSE_RANK uses only those substantive measures, so exact ties receive the same rank. AP1 is access context and
-- AP3 is teacher-pressure review context; neither is allowed to decide a resource allocation.

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
    a.public_school_enrollment AS ap1_public_school_enrollment,
    a.school_age_population_per_public_school AS ap1_school_age_population_per_public_school,
    b.learners_per_classroom AS ap2_learners_per_reported_room,
    b.learner_coverage_pct AS ap2_learner_coverage_pct,
    b.is_assessed AS ap2_assessed,
    b.congested_school_count AS ap2_screened_congested_school_count,
    b.learners_in_congested_schools AS ap2_affected_learners,
    b.congested_learner_share_pct AS ap2_affected_learner_share_pct,
    b.benchmark_status AS ap2_screen_status,
    c.es_learners_per_teacher AS ap3_es_learners_per_teacher,
    c.jhs_learners_per_teacher AS ap3_jhs_learners_per_teacher,
    c.shs_learners_per_teacher AS ap3_shs_learners_per_teacher,
    c.is_assessed AS ap3_fully_assessed,
    c.benchmark_status AS ap3_review_status,
    d.ap4_gap_2020, d.ap4_gap_2024, d.ap4_gap_rate_2020_pct, d.ap4_gap_rate_2024_pct, d.ap4_gap_change,
    d.ap4_enrollment_trend, d.ap4_enrollment_change_pct
  FROM edu_access.`05-gold`.dim_city_municipality AS l
  LEFT JOIN edu_access.`06-analytics`.ap1_school_provision AS a USING (city_mun_psgc_code)
  LEFT JOIN edu_access.`06-analytics`.ap2_classroom_pressure AS b USING (city_mun_psgc_code)
  LEFT JOIN edu_access.`06-analytics`.ap3_teacher_pressure AS c USING (city_mun_psgc_code)
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
), classroom_ranked AS (
  SELECT city_mun_psgc_code,
         DENSE_RANK() OVER (ORDER BY ap2_affected_learners DESC,
           ap2_screened_congested_school_count DESC,
           ap2_learners_per_reported_room DESC) AS classroom_priority_rank
  FROM joined
  WHERE ap2_assessed AND ap2_affected_learners > 0
)
SELECT j.*,
       CASE WHEN NOT COALESCE(j.ap2_assessed, FALSE) THEN 'data_review'
            WHEN j.ap2_affected_learners > 0 THEN 'reported_congestion_screen'
            ELSE 'no_reported_congestion_screen' END AS classroom_priority_group,
       r.classroom_priority_rank,
       CASE WHEN NOT COALESCE(j.ap2_assessed, FALSE)
              THEN 'Classroom data do not pass the coverage gate, no classroom priority is assigned'
            WHEN j.ap2_affected_learners > 0
              THEN 'PIDS-style illustrative school screen, ordered by affected learners, affected schools, then pooled reported-room ratio'
            ELSE 'No school crosses the illustrative reported-room screen, this is not proof of classroom adequacy'
       END AS classroom_priority_basis,
       'D-060' AS rule_version,
       :code_revision AS code_revision
FROM joined AS j
LEFT JOIN classroom_ranked AS r USING (city_mun_psgc_code);

COMMENT ON TABLE edu_access.`06-analytics`.lgu_priority_matrix_candidate IS 'Unpublished LGU evidence and classroom-screening queue under D-060. Do not read: use lgu_priority_matrix.';
ALTER TABLE edu_access.`06-analytics`.lgu_priority_matrix_candidate OWNER TO `reached-hq`;
