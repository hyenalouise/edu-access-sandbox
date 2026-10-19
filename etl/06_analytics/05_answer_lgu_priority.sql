-- Analytics build for the LGU priority table (D-057, metric specification "Priority rule"): one row per
-- regular city or municipality for SY 2023-24, the one shared answer for the priority slide, the dashboard
-- and Genie. Labelled "relative capacity pressure", never a shortage or a number of resources needed.
-- 1. Coverage gate: a measure is assessed only at 90% coverage or more (AP1: active public schools with a
--    complete all-level total; AP2 and each AP3 level: learner coverage).
-- 2. Percentile: PERCENT_RANK() within LGU type among the LGUs that pass the measure's gate. AP3 ranks each
--    level, then re-ranks each LGU's highest passing level percentile among LGUs with a passing level.
-- 3. High: percentile 0.90 or above. AP3 is not high only when every offered level passes and it is still
--    not high; otherwise it is not assessed (also when the school year has no personnel data).
-- 4. Tier: the count of high measures when all three are assessed: Critical (3), Elevated (2), Targeted
--    (1), Monitor (0); otherwise Data review. tier_code is 3, 2, 1, 0 or data_review.
-- 5. Order within a tier: affected learners (AP1 public learners) first, then the lowest of the three
--    percentiles, both highest first.
-- 6. Stable: Critical both within type and nationally (the same steps without the type partition).
-- Checks beside the ranking, never changing a tier: Critical at a 0.85 and a 0.80 line, and at a 95% gate.
-- The outlier, flag-rate and overlap checks of D-057 are not built yet.
--
-- Writes lgu_priority_candidate; the gate publishes it only if no check fails.
--
-- Parameters, supplied by the job (or src/job/local_run.py):
--   :run_id, :code_revision, :environment

DECLARE OR REPLACE VARIABLE analytics_run_id STRING;
SET VARIABLE analytics_run_id = :run_id;
DECLARE OR REPLACE VARIABLE analytics_code_revision STRING;
SET VARIABLE analytics_code_revision = COALESCE(NULLIF(:code_revision, ''), 'UNSET');
DECLARE OR REPLACE VARIABLE analytics_environment STRING;
SET VARIABLE analytics_environment = COALESCE(NULLIF(:environment, ''), 'UNSET');
DECLARE OR REPLACE VARIABLE analytics_built_at_utc TIMESTAMP;
SET VARIABLE analytics_built_at_utc = current_timestamp();

-- The run starts; the gate records how it ended (D-020).
MERGE INTO edu_access.`01-control`.pipeline_runs AS t
USING (SELECT session.analytics_run_id AS run_id) AS s
ON t.run_id = s.run_id AND t.pipeline_name = 'analytics_build' AND t.source_id = 'lgu_priority'
WHEN MATCHED THEN UPDATE SET
  status = 'running', started_at_utc = session.analytics_built_at_utc, finished_at_utc = NULL,
  failure_stage = NULL, error_message = NULL, code_revision = session.analytics_code_revision, job_run_id = s.run_id
WHEN NOT MATCHED THEN INSERT (run_id, pipeline_name, source_id, environment, status, started_at_utc, code_revision, job_run_id)
  VALUES (s.run_id, 'analytics_build', 'lgu_priority', session.analytics_environment, 'running',
          session.analytics_built_at_utc, session.analytics_code_revision, s.run_id);

CREATE SCHEMA IF NOT EXISTS edu_access.`06-analytics`;
ALTER SCHEMA edu_access.`06-analytics` OWNER TO `reached-hq`;

CREATE OR REPLACE TABLE edu_access.`06-analytics`.lgu_priority_candidate USING DELTA AS
WITH scenarios AS (
  SELECT * FROM (VALUES ('main', 90.0, TRUE), ('national', 90.0, FALSE), ('gate_95', 95.0, TRUE)) AS v(scenario, gate_pct, by_type)
),
lines AS (
  SELECT * FROM (VALUES (0.90), (0.85), (0.80)) AS v(line)
),
ap12 AS (
  SELECT a1.city_mun_psgc_code, a1.city_mun_name, a1.lgu_type, a1.city_class, a1.income_class,
         a1.province_name, a1.region_name, a1.school_year,
         a1.public_learners AS affected_learners,
         a1.learners_per_public_school AS ap1_value, a1.ap1_coverage_pct,
         a2.learners_per_room AS ap2_value, a2.learner_coverage_pct AS ap2_coverage_pct
  FROM edu_access.`06-analytics`.ap1_school_provision AS a1
  LEFT JOIN edu_access.`06-analytics`.ap2_classroom_pressure AS a2
    ON a2.city_mun_psgc_code = a1.city_mun_psgc_code AND a2.school_year = a1.school_year
  WHERE a1.school_year = '2023-24'
),
m12 AS (
  SELECT s.scenario, x.city_mun_psgc_code, x.ap1_value, x.ap2_value,
         CASE WHEN s.by_type THEN x.lgu_type ELSE 'all' END AS part,
         COALESCE(x.ap1_value IS NOT NULL AND x.ap1_coverage_pct >= s.gate_pct, FALSE) AS ap1_ok,
         COALESCE(x.ap2_value IS NOT NULL AND x.ap2_coverage_pct >= s.gate_pct, FALSE) AS ap2_ok
  FROM ap12 AS x CROSS JOIN scenarios AS s
),
r12 AS (
  SELECT m12.*,
         CASE WHEN ap1_ok THEN PERCENT_RANK() OVER (PARTITION BY scenario, part, ap1_ok ORDER BY ap1_value) END AS ap1_pct,
         CASE WHEN ap2_ok THEN PERCENT_RANK() OVER (PARTITION BY scenario, part, ap2_ok ORDER BY ap2_value) END AS ap2_pct
  FROM m12
),
lvl AS (
  SELECT s.scenario, t.city_mun_psgc_code, t.education_level_code, t.learners_per_teacher,
         CASE WHEN s.by_type THEN t.lgu_type ELSE 'all' END AS part,
         t.schools_in_scope > 0 AS offered,
         COALESCE(t.schools_in_scope > 0 AND t.learners_per_teacher IS NOT NULL
                  AND t.learner_coverage_pct >= s.gate_pct, FALSE) AS level_ok
  FROM edu_access.`06-analytics`.ap3_teacher_pressure AS t CROSS JOIN scenarios AS s
  WHERE t.school_year = '2023-24'
),
rl AS (
  SELECT lvl.*,
         CASE WHEN level_ok THEN PERCENT_RANK() OVER (PARTITION BY scenario, part, education_level_code, level_ok
                                                      ORDER BY learners_per_teacher) END AS level_pct
  FROM lvl
),
a3 AS (
  SELECT scenario, city_mun_psgc_code, MAX(part) AS part,
         COALESCE(COUNT_IF(offered), 0) AS levels_offered,
         COALESCE(COUNT_IF(level_ok), 0) AS levels_assessed,
         MAX(level_pct) AS top_level_pct,
         MAX_BY(CASE WHEN level_ok THEN education_level_code END, COALESCE(level_pct, -1.0)) AS top_level
  FROM rl
  GROUP BY scenario, city_mun_psgc_code
),
r3 AS (
  SELECT a3.*,
         CASE WHEN levels_assessed > 0 THEN PERCENT_RANK() OVER (PARTITION BY scenario, part, levels_assessed > 0
                                                                 ORDER BY top_level_pct) END AS ap3_pct
  FROM a3
),
tiers AS (
  SELECT r.scenario, l.line, r.city_mun_psgc_code, r.ap1_pct, r.ap2_pct, t.ap3_pct, t.top_level,
         CASE WHEN NOT r.ap1_ok THEN 'not_assessed' WHEN r.ap1_pct >= l.line THEN 'high' ELSE 'not_high' END AS ap1_status,
         CASE WHEN NOT r.ap2_ok THEN 'not_assessed' WHEN r.ap2_pct >= l.line THEN 'high' ELSE 'not_high' END AS ap2_status,
         CASE WHEN t.levels_assessed > 0 AND t.ap3_pct >= l.line THEN 'high'
              WHEN t.levels_offered > 0 AND t.levels_assessed = t.levels_offered THEN 'not_high'
              ELSE 'not_assessed' END AS ap3_status
  FROM r12 AS r
  LEFT JOIN r3 AS t ON t.scenario = r.scenario AND t.city_mun_psgc_code = r.city_mun_psgc_code
  CROSS JOIN lines AS l
),
tiered AS (
  SELECT tiers.*,
         CASE WHEN ap1_status = 'not_assessed' OR ap2_status = 'not_assessed' OR ap3_status = 'not_assessed' THEN 'data_review'
              ELSE CAST((CASE WHEN ap1_status = 'high' THEN 1 ELSE 0 END) + (CASE WHEN ap2_status = 'high' THEN 1 ELSE 0 END)
                        + (CASE WHEN ap3_status = 'high' THEN 1 ELSE 0 END) AS STRING) END AS tier_code
  FROM tiers
),
levels AS (
  SELECT city_mun_psgc_code,
         MAX(CASE WHEN education_level_code = 'ES' THEN learners_per_teacher END) AS ap3_es_learners_per_teacher,
         MAX(CASE WHEN education_level_code = 'JHS' THEN learners_per_teacher END) AS ap3_jhs_learners_per_teacher,
         MAX(CASE WHEN education_level_code = 'SHS' THEN learners_per_teacher END) AS ap3_shs_learners_per_teacher,
         MAX(CASE WHEN education_level_code = 'ES' THEN learner_coverage_pct END) AS ap3_es_coverage_pct,
         MAX(CASE WHEN education_level_code = 'JHS' THEN learner_coverage_pct END) AS ap3_jhs_coverage_pct,
         MAX(CASE WHEN education_level_code = 'SHS' THEN learner_coverage_pct END) AS ap3_shs_coverage_pct
  FROM edu_access.`06-analytics`.ap3_teacher_pressure
  WHERE school_year = '2023-24'
  GROUP BY city_mun_psgc_code
),
main AS (
  SELECT x.city_mun_psgc_code, x.city_mun_name, x.lgu_type, x.city_class, x.income_class,
         x.province_name, x.region_name, x.school_year,
         x.ap1_value AS ap1_learners_per_public_school, x.ap1_coverage_pct, m.ap1_pct AS ap1_percentile, m.ap1_status,
         x.ap2_value AS ap2_learners_per_room, x.ap2_coverage_pct, m.ap2_pct AS ap2_percentile, m.ap2_status,
         lv.ap3_es_learners_per_teacher, lv.ap3_jhs_learners_per_teacher, lv.ap3_shs_learners_per_teacher,
         lv.ap3_es_coverage_pct, lv.ap3_jhs_coverage_pct, lv.ap3_shs_coverage_pct,
         m.top_level AS ap3_highest_level, m.ap3_pct AS ap3_percentile, m.ap3_status,
         (CASE WHEN m.ap1_status = 'high' THEN 1 ELSE 0 END) + (CASE WHEN m.ap2_status = 'high' THEN 1 ELSE 0 END)
           + (CASE WHEN m.ap3_status = 'high' THEN 1 ELSE 0 END) AS high_measure_count,
         concat_ws(', ', CASE WHEN m.ap1_status = 'high' THEN 'AP1 learners per school' END,
                         CASE WHEN m.ap2_status = 'high' THEN 'AP2 learners per room' END,
                         CASE WHEN m.ap3_status = 'high' THEN 'AP3 learners per teacher (' || m.top_level || ')' END) AS high_measures,
         m.tier_code,
         CASE m.tier_code WHEN '3' THEN 'Critical' WHEN '2' THEN 'Elevated' WHEN '1' THEN 'Targeted'
                          WHEN '0' THEN 'Monitor' ELSE 'Data review' END AS tier_label,
         CASE m.tier_code WHEN '3' THEN 4 WHEN '2' THEN 3 WHEN '1' THEN 2 WHEN '0' THEN 1 ELSE 0 END AS tier_sort,
         x.affected_learners,
         LEAST(m.ap1_pct, m.ap2_pct, m.ap3_pct) AS lowest_percentile,
         n.tier_code AS national_tier_code,
         m.tier_code = '3' AND n.tier_code = '3' AS is_stable,
         c85.tier_code = '3' AS critical_at_line_085,
         c80.tier_code = '3' AS critical_at_line_080,
         g95.tier_code = '3' AS critical_at_gate_95
  FROM ap12 AS x
  JOIN tiered AS m ON m.city_mun_psgc_code = x.city_mun_psgc_code AND m.scenario = 'main' AND m.line = 0.90
  JOIN tiered AS n ON n.city_mun_psgc_code = x.city_mun_psgc_code AND n.scenario = 'national' AND n.line = 0.90
  JOIN tiered AS c85 ON c85.city_mun_psgc_code = x.city_mun_psgc_code AND c85.scenario = 'main' AND c85.line = 0.85
  JOIN tiered AS c80 ON c80.city_mun_psgc_code = x.city_mun_psgc_code AND c80.scenario = 'main' AND c80.line = 0.80
  JOIN tiered AS g95 ON g95.city_mun_psgc_code = x.city_mun_psgc_code AND g95.scenario = 'gate_95' AND g95.line = 0.90
  LEFT JOIN levels AS lv ON lv.city_mun_psgc_code = x.city_mun_psgc_code
)
SELECT main.*,
       ROW_NUMBER() OVER (ORDER BY tier_sort DESC, affected_learners DESC, lowest_percentile DESC, city_mun_psgc_code) AS priority_rank,
       ROW_NUMBER() OVER (PARTITION BY tier_code ORDER BY affected_learners DESC, lowest_percentile DESC, city_mun_psgc_code) AS rank_within_tier,
       'D-057' AS rule_version,
       'relative capacity pressure' AS result_label
FROM main;

ALTER TABLE edu_access.`06-analytics`.lgu_priority_candidate OWNER TO `reached-hq`;
