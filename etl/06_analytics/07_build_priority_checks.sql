-- the checks D-057 reports beside the ranking, and the same-type comparison the dashboard shows beside each measure.
-- grain: one regular city or municipality, SY 2023-24. nothing here changes the published tier.
-- comparison: the national same-type median of each measure, over the LGUs of the same type that pass the measure's
-- coverage gate, and relative pressure = the LGU's ratio / that median (1.00 is the typical LGU of its type). AP3 uses
-- the level that sets the AP3 percentile. relative pressure shows size; the within-type percentile sets "high".
-- checks (D-057): the tier with the high line at 0.85 and 0.80, with a 95% coverage gate, and without the outlier
-- schools in lgu_priority_outlier_schools (AP2 and AP3 ratios recomputed without them; AP1 has no outlier rule).

CREATE SCHEMA IF NOT EXISTS edu_access.`06-analytics`;
ALTER SCHEMA edu_access.`06-analytics` OWNER TO `reached-hq`;

CREATE OR REPLACE TABLE edu_access.`06-analytics`.lgu_priority_checks_candidate USING DELTA AS
WITH m AS (
  SELECT city_mun_psgc_code, lgu_type, tier, tier_code FROM edu_access.`06-analytics`.lgu_priority_matrix
), a1 AS (
  SELECT * FROM edu_access.`06-analytics`.ap1_school_provision
), a2 AS (
  SELECT * FROM edu_access.`06-analytics`.ap2_classroom_pressure
), a3 AS (
  SELECT * FROM edu_access.`06-analytics`.ap3_teacher_pressure
), lv AS (
  -- AP3 levels side by side become one row per LGU and level.
  SELECT city_mun_psgc_code, lgu_type, 'ES' AS lvl, 1 AS ord, COALESCE(es_offered_school_count, 0) > 0 AS offered,
         es_learners_per_teacher AS ratio, es_learner_coverage_pct AS coverage, COALESCE(es_passes_gate, FALSE) AS passes,
         es_eligible_learners AS eligible, es_teacher_count AS teachers, es_public_school_enrollment AS enrollment
  FROM a3
  UNION ALL SELECT city_mun_psgc_code, lgu_type, 'JHS', 2, COALESCE(jhs_offered_school_count, 0) > 0, jhs_learners_per_teacher,
         jhs_learner_coverage_pct, COALESCE(jhs_passes_gate, FALSE), jhs_eligible_learners, jhs_teacher_count, jhs_public_school_enrollment
  FROM a3
  UNION ALL SELECT city_mun_psgc_code, lgu_type, 'SHS', 3, COALESCE(shs_offered_school_count, 0) > 0, shs_learners_per_teacher,
         shs_learner_coverage_pct, COALESCE(shs_passes_gate, FALSE), shs_eligible_learners, shs_teacher_count, shs_public_school_enrollment
  FROM a3

-- ---------------------------------------------------------------- same-type medians and relative pressure
), med1 AS (
  SELECT lgu_type, PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY learners_per_public_school) AS median_ratio
  FROM a1 WHERE is_assessed GROUP BY lgu_type
), med2 AS (
  SELECT lgu_type, PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY learners_per_classroom) AS median_ratio
  FROM a2 WHERE is_assessed GROUP BY lgu_type
), med3 AS (
  SELECT lgu_type, lvl, PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ratio) AS median_ratio
  FROM lv WHERE passes GROUP BY lgu_type, lvl
), comparison AS (
  SELECT m.city_mun_psgc_code,
         x1.median_ratio AS ap1_same_type_median,
         a1.learners_per_public_school / NULLIF(x1.median_ratio, 0) AS ap1_relative_pressure,
         x2.median_ratio AS ap2_same_type_median,
         a2.learners_per_classroom / NULLIF(x2.median_ratio, 0) AS ap2_relative_pressure,
         a3.highest_level AS ap3_level,
         x3.median_ratio AS ap3_same_type_median,
         l3.ratio / NULLIF(x3.median_ratio, 0) AS ap3_relative_pressure
  FROM m
  LEFT JOIN a1 USING (city_mun_psgc_code)
  LEFT JOIN a2 USING (city_mun_psgc_code)
  LEFT JOIN a3 USING (city_mun_psgc_code)
  LEFT JOIN med1 AS x1 ON x1.lgu_type = m.lgu_type AND a1.is_assessed
  LEFT JOIN med2 AS x2 ON x2.lgu_type = m.lgu_type AND a2.is_assessed
  LEFT JOIN lv AS l3 ON l3.city_mun_psgc_code = m.city_mun_psgc_code AND l3.lvl = a3.highest_level AND l3.passes
  LEFT JOIN med3 AS x3 ON x3.lgu_type = m.lgu_type AND x3.lvl = a3.highest_level

-- ---------------------------------------------------------------- lower high lines (0.85 and 0.80)
), lines AS (
  SELECT m.city_mun_psgc_code, x.line,
         COALESCE(a1.is_assessed, FALSE) AS ap1_assessed, COALESCE(a1.within_type_percentile >= x.line, FALSE) AS ap1_high,
         COALESCE(a2.is_assessed, FALSE) AS ap2_assessed, COALESCE(a2.within_type_percentile >= x.line, FALSE) AS ap2_high,
         COALESCE(a3.within_type_percentile >= x.line
                  OR (a3.offered_level_count > 0 AND a3.passing_level_count = a3.offered_level_count), FALSE) AS ap3_assessed,
         COALESCE(a3.within_type_percentile >= x.line, FALSE) AS ap3_high
  FROM m
  CROSS JOIN (SELECT 0.85 AS line UNION ALL SELECT 0.80) AS x
  LEFT JOIN a1 USING (city_mun_psgc_code)
  LEFT JOIN a2 USING (city_mun_psgc_code)
  LEFT JOIN a3 USING (city_mun_psgc_code)

-- ---------------------------------------------------------------- a 95% coverage gate
), g1 AS (
  SELECT city_mun_psgc_code, lgu_type, learners_per_public_school AS ratio FROM a1 WHERE is_assessed AND coverage_pct >= 95
), g1r AS (
  SELECT city_mun_psgc_code, PERCENT_RANK() OVER (PARTITION BY lgu_type ORDER BY ratio) >= 0.9 AS high FROM g1
), g2 AS (
  SELECT city_mun_psgc_code, lgu_type, learners_per_classroom AS ratio FROM a2 WHERE is_assessed AND learner_coverage_pct >= 95
), g2r AS (
  SELECT city_mun_psgc_code, PERCENT_RANK() OVER (PARTITION BY lgu_type ORDER BY ratio) >= 0.9 AS high FROM g2
), g3l AS (
  SELECT city_mun_psgc_code, lgu_type, lvl, ord, offered,
         offered AND ratio IS NOT NULL AND coverage >= 95 AND passes AS passes95, ratio
  FROM lv
), g3p AS (
  SELECT city_mun_psgc_code, lgu_type, lvl, ord,
         PERCENT_RANK() OVER (PARTITION BY lgu_type, lvl ORDER BY ratio) AS pct
  FROM g3l WHERE passes95
), g3b AS (
  SELECT city_mun_psgc_code, lgu_type, pct
  FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY city_mun_psgc_code ORDER BY pct DESC, ord) AS rn FROM g3p) AS t
  WHERE rn = 1
), g3r AS (
  SELECT city_mun_psgc_code, PERCENT_RANK() OVER (PARTITION BY lgu_type ORDER BY pct) >= 0.9 AS high FROM g3b
), g3c AS (
  SELECT city_mun_psgc_code, COUNT_IF(offered) AS offered_levels, COUNT_IF(passes95) AS passing_levels
  FROM g3l GROUP BY city_mun_psgc_code
), gate95 AS (
  SELECT m.city_mun_psgc_code, CAST(95 AS INT) AS gate,
         r1.city_mun_psgc_code IS NOT NULL AS ap1_assessed, COALESCE(r1.high, FALSE) AS ap1_high,
         r2.city_mun_psgc_code IS NOT NULL AS ap2_assessed, COALESCE(r2.high, FALSE) AS ap2_high,
         COALESCE(r3.high OR (c3.offered_levels > 0 AND c3.passing_levels = c3.offered_levels), FALSE) AS ap3_assessed,
         COALESCE(r3.high, FALSE) AS ap3_high
  FROM m
  LEFT JOIN g1r AS r1 USING (city_mun_psgc_code)
  LEFT JOIN g2r AS r2 USING (city_mun_psgc_code)
  LEFT JOIN g3r AS r3 USING (city_mun_psgc_code)
  LEFT JOIN g3c AS c3 USING (city_mun_psgc_code)

-- ---------------------------------------------------------------- without the outlier schools
), o2 AS (
  SELECT city_mun_psgc_code, SUM(learners) AS learners, SUM(denominator) AS rooms
  FROM edu_access.`06-analytics`.lgu_priority_outlier_schools WHERE measure = 'AP2' GROUP BY city_mun_psgc_code
), w2 AS (
  -- the flagged schools leave the ratio and both sides of learner coverage.
  SELECT a2.city_mun_psgc_code, a2.lgu_type,
         CAST(a2.eligible_learners - COALESCE(o2.learners, 0) AS DOUBLE)
           / NULLIF(a2.reported_instructional_classrooms - COALESCE(o2.rooms, 0), 0) AS ratio,
         100.0 * (a2.eligible_learners - COALESCE(o2.learners, 0))
           / NULLIF(a2.public_school_enrollment - COALESCE(o2.learners, 0), 0) AS coverage,
         a2.active_public_school_count
  FROM a2 LEFT JOIN o2 USING (city_mun_psgc_code)
), w2r AS (
  SELECT city_mun_psgc_code, PERCENT_RANK() OVER (PARTITION BY lgu_type ORDER BY ratio) >= 0.9 AS high
  FROM w2 WHERE active_public_school_count > 0 AND ratio IS NOT NULL AND coverage >= 90
), o3 AS (
  SELECT city_mun_psgc_code, education_level_code AS lvl, SUM(learners) AS learners, SUM(denominator) AS teachers
  FROM edu_access.`06-analytics`.lgu_priority_outlier_schools WHERE measure = 'AP3' GROUP BY city_mun_psgc_code, education_level_code
), w3l AS (
  SELECT l.city_mun_psgc_code, l.lgu_type, l.lvl, l.ord, l.offered,
         CAST(l.eligible - COALESCE(o.learners, 0) AS DOUBLE) / NULLIF(l.teachers - COALESCE(o.teachers, 0), 0) AS ratio,
         100.0 * (l.eligible - COALESCE(o.learners, 0)) / NULLIF(l.enrollment - COALESCE(o.learners, 0), 0) AS coverage
  FROM lv AS l LEFT JOIN o3 AS o USING (city_mun_psgc_code, lvl)
), w3g AS (
  SELECT *, COALESCE(offered AND ratio IS NOT NULL AND coverage >= 90, FALSE) AS passes FROM w3l
), w3p AS (
  SELECT city_mun_psgc_code, lgu_type, ord, PERCENT_RANK() OVER (PARTITION BY lgu_type, lvl ORDER BY ratio) AS pct
  FROM w3g WHERE passes
), w3b AS (
  SELECT city_mun_psgc_code, lgu_type, pct
  FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY city_mun_psgc_code ORDER BY pct DESC, ord) AS rn FROM w3p) AS t
  WHERE rn = 1
), w3r AS (
  SELECT city_mun_psgc_code, PERCENT_RANK() OVER (PARTITION BY lgu_type ORDER BY pct) >= 0.9 AS high FROM w3b
), w3c AS (
  SELECT city_mun_psgc_code, COUNT_IF(offered) AS offered_levels, COUNT_IF(passes) AS passing_levels
  FROM w3g GROUP BY city_mun_psgc_code
), no_outliers AS (
  SELECT m.city_mun_psgc_code,
         COALESCE(a1.is_assessed, FALSE) AS ap1_assessed, COALESCE(a1.is_high, FALSE) AS ap1_high,
         r2.city_mun_psgc_code IS NOT NULL AS ap2_assessed, COALESCE(r2.high, FALSE) AS ap2_high,
         COALESCE(r3.high OR (c3.offered_levels > 0 AND c3.passing_levels = c3.offered_levels), FALSE) AS ap3_assessed,
         COALESCE(r3.high, FALSE) AS ap3_high
  FROM m
  LEFT JOIN a1 USING (city_mun_psgc_code)
  LEFT JOIN w2r AS r2 USING (city_mun_psgc_code)
  LEFT JOIN w3r AS r3 USING (city_mun_psgc_code)
  LEFT JOIN w3c AS c3 USING (city_mun_psgc_code)

-- ---------------------------------------------------------------- tiers, by the D-057 count of high measures
), tiered AS (
  SELECT city_mun_psgc_code, 'line_085' AS scenario,
         CASE WHEN NOT (ap1_assessed AND ap2_assessed AND ap3_assessed) THEN 'Data review'
              ELSE CASE CAST(ap1_high AS INT) + CAST(ap2_high AS INT) + CAST(ap3_high AS INT)
                   WHEN 3 THEN 'Critical' WHEN 2 THEN 'Elevated' WHEN 1 THEN 'Targeted' ELSE 'Monitor' END END AS tier
  FROM lines WHERE line = 0.85
  UNION ALL
  SELECT city_mun_psgc_code, 'line_080',
         CASE WHEN NOT (ap1_assessed AND ap2_assessed AND ap3_assessed) THEN 'Data review'
              ELSE CASE CAST(ap1_high AS INT) + CAST(ap2_high AS INT) + CAST(ap3_high AS INT)
                   WHEN 3 THEN 'Critical' WHEN 2 THEN 'Elevated' WHEN 1 THEN 'Targeted' ELSE 'Monitor' END END
  FROM lines WHERE line = 0.80
  UNION ALL
  SELECT city_mun_psgc_code, 'gate_95',
         CASE WHEN NOT (ap1_assessed AND ap2_assessed AND ap3_assessed) THEN 'Data review'
              ELSE CASE CAST(ap1_high AS INT) + CAST(ap2_high AS INT) + CAST(ap3_high AS INT)
                   WHEN 3 THEN 'Critical' WHEN 2 THEN 'Elevated' WHEN 1 THEN 'Targeted' ELSE 'Monitor' END END
  FROM gate95
  UNION ALL
  SELECT city_mun_psgc_code, 'no_outliers',
         CASE WHEN NOT (ap1_assessed AND ap2_assessed AND ap3_assessed) THEN 'Data review'
              ELSE CASE CAST(ap1_high AS INT) + CAST(ap2_high AS INT) + CAST(ap3_high AS INT)
                   WHEN 3 THEN 'Critical' WHEN 2 THEN 'Elevated' WHEN 1 THEN 'Targeted' ELSE 'Monitor' END END
  FROM no_outliers
)
SELECT m.city_mun_psgc_code, m.lgu_type, CAST('2023-24' AS STRING) AS school_year, m.tier,
       c.ap1_same_type_median, c.ap1_relative_pressure,
       c.ap2_same_type_median, c.ap2_relative_pressure,
       c.ap3_level, c.ap3_same_type_median, c.ap3_relative_pressure,
       MAX(CASE WHEN t.scenario = 'line_085' THEN t.tier END) AS tier_at_line_085,
       MAX(CASE WHEN t.scenario = 'line_080' THEN t.tier END) AS tier_at_line_080,
       MAX(CASE WHEN t.scenario = 'gate_95' THEN t.tier END) AS tier_at_gate_95,
       MAX(CASE WHEN t.scenario = 'no_outliers' THEN t.tier END) AS tier_without_outliers,
       MAX(CASE WHEN t.scenario = 'no_outliers' THEN t.tier END) IS DISTINCT FROM m.tier AS outliers_change_tier,
       'D-057' AS rule_version,
       :code_revision AS code_revision
FROM m
JOIN comparison AS c USING (city_mun_psgc_code)
LEFT JOIN tiered AS t USING (city_mun_psgc_code)
GROUP BY m.city_mun_psgc_code, m.lgu_type, m.tier, c.ap1_same_type_median, c.ap1_relative_pressure,
         c.ap2_same_type_median, c.ap2_relative_pressure, c.ap3_level, c.ap3_same_type_median, c.ap3_relative_pressure;

COMMENT ON TABLE edu_access.`06-analytics`.lgu_priority_checks_candidate IS 'Unpublished priority checks. Do not read: use lgu_priority_checks.';
ALTER TABLE edu_access.`06-analytics`.lgu_priority_checks_candidate OWNER TO `reached-hq`;
