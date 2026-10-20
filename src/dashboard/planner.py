"""The ReachED LGU planner dashboard: Overview, LGU Profile, School Action, Data and Method.

Run `python -m src.dashboard.planner` to rewrite dashboards/reached_planner.lvdash.json from this file.

The tier, percentiles, coverage gate and checks come from the Analytics tables (D-057); the dashboard only filters,
labels and arranges them. Global filters (Region, Province, LGU type) and the selection filters (City or
municipality, Barangay) are query parameters applied after those values are read, so a filter narrows what is shown
and never changes a percentile, reference or tier. School-level views read Gold, with the outlier fences from
lgu_priority_outlier_schools.
"""
import json
import sys
from pathlib import Path

from src.dashboard.widgets import (Builder, Page, bar, chart, choropleth, heatmap, kpi, line, num, param_filter, pct,
                                   quant, ref_line, scatter, table, text)

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "dashboards" / "reached_planner.lvdash.json"

A = "edu_access.`06-analytics`"
G = "edu_access.`05-gold`"
ALL_REGIONS, ALL_PROVINCES, ALL_TYPES = "All regions", "All provinces", "All LGU types"
ALL_TIERS, ALL_COVERAGE = "All tiers", "All LGUs"
TOP_LGU = "(Top LGU in the filters)"
ALL_BARANGAYS = "All barangays"
ALL_LEVELS, ALL_SCHOOLS, FIRST_SCHOOL = "All levels", "All schools", "(First school to check)"
ALL_MEASURES = "All measures"
SCHOOL_YEARS = ["SY 2020-21", "SY 2021-22", "SY 2022-23", "SY 2023-24", "SY 2024-25", "SY 2025-26"]
SCENARIOS = ["Without outlier schools", "95% coverage gate", "High line at 0.85", "High line at 0.80", "Ranked nationally"]

TIERS = ["Critical", "Elevated", "Targeted", "Monitor", "Data review"]
TIER_COLORS = [{"value": "Critical", "color": "#712B13"}, {"value": "Elevated", "color": "#D85A30"},
               {"value": "Targeted", "color": "#F0997B"}, {"value": "Monitor", "color": "#D9DEE3"},
               {"value": "Data review", "color": "#8A96A3"}]
MEASURES = ["Schools (AP1)", "Classrooms (AP2)", "Teachers (AP3)"]
STATUS_ORDER = ["Above the outlier fence", "Missing report", "Zero rooms or teachers", "No figures to check"]
STATUS_COLORS = [{"value": "Selected school", "color": "#712B13"}, {"value": "Figures to check", "color": "#E3A008"},
                 {"value": "Other schools", "color": "#A9B4BF"}]

# ------------------------------------------------------------------------------------------ shared SQL

LGU = f"""lgu AS (
  SELECT d.city_mun_psgc_code, d.city_mun_name,
         d.city_mun_name || ', ' || COALESCE(d.province_name, d.region_name) AS lgu_label,
         COALESCE(d.province_name, 'Independent cities (no province)') AS province_label,
         d.region_name,
         CASE WHEN lower(d.lgu_type) = 'city' THEN 'City' ELSE 'Municipality' END AS lgu_type_label,
         CASE WHEN lower(d.lgu_type) = 'city' THEN 'cities' ELSE 'municipalities' END AS type_plural
  FROM {G}.dim_city_municipality AS d
  WHERE d.member_type = 'regular'
)"""


def geo(prefix=""):
    return (f"(:region = '{ALL_REGIONS}' OR {prefix}region_name = :region)"
            f" AND (:province = '{ALL_PROVINCES}' OR {prefix}province_label = :province)"
            f" AND (:lgu_type = '{ALL_TYPES}' OR {prefix}lgu_type_label = :lgu_type)")


GEO, GEO_L, GEO_PRI = geo(), geo("l."), geo("pri.")
TYPE_ONLY = f"(:lgu_type = '{ALL_TYPES}' OR lgu_type_label = :lgu_type)"
TIER_SORT = ("CASE {c} WHEN 'Critical' THEN 4 WHEN 'Elevated' THEN 3 WHEN 'Targeted' THEN 2 WHEN 'Monitor' THEN 1 "
             "ELSE 0 END")


def r1(expr):
    return f"COALESCE(format_number({expr}, 1), 'n/a')"


def r2(expr):
    return f"COALESCE(CAST(ROUND({expr}, 2) AS STRING), 'n/a')"


def cov(expr):
    return f"COALESCE(format_number({expr}, 0) || '%', 'n/a')"


def r0(expr):
    return f"COALESCE(format_number({expr}, 0), 'n/a')"


# Every LGU's published D-057 row with its checks and plain-language labels.
PRI_CTE = f"""pri AS (
  SELECT l.lgu_label, l.province_label, l.lgu_type_label, l.type_plural, m.*,
         {TIER_SORT.format(c='m.tier')} AS tier_sort,
         {TIER_SORT.format(c='m.tier')} AS tier_level,
         ROW_NUMBER() OVER (ORDER BY {TIER_SORT.format(c='m.tier')} DESC, m.order_in_tier) AS national_rank,
         COALESCE(NULLIF(concat_ws(' + ', CASE WHEN m.ap1_high THEN 'Schools' END,
                                          CASE WHEN m.ap2_high THEN 'Classrooms' END,
                                          CASE WHEN m.ap3_high THEN 'Teachers' END), ''), 'None') AS high_areas,
         CAST(m.high_measure_count AS STRING) || ' of 3' AS high_count_label,
         CASE WHEN m.tier = 'Data review'
              THEN concat_ws('; ', 'schools: ' || a1.not_assessed_reason, 'classrooms: ' || a2.not_assessed_reason,
                             'teachers: ' || a3.not_assessed_reason) END AS data_review_reason,
         CASE WHEN m.is_stable THEN 'Stable' ELSE '' END AS stability,
         k.ap1_same_type_median, k.ap1_relative_pressure, k.ap2_same_type_median, k.ap2_relative_pressure,
         k.ap3_level, k.ap3_same_type_median, k.ap3_relative_pressure,
         k.tier_at_line_085, k.tier_at_line_080, k.tier_at_gate_95, k.tier_without_outliers, k.outliers_change_tier,
         NULLIF(LEAST(CASE WHEN a3.es_offered_school_count > 0 THEN COALESCE(a3.es_learner_coverage_pct, 0) ELSE 999 END,
                      CASE WHEN a3.jhs_offered_school_count > 0 THEN COALESCE(a3.jhs_learner_coverage_pct, 0) ELSE 999 END,
                      CASE WHEN a3.shs_offered_school_count > 0 THEN COALESCE(a3.shs_learner_coverage_pct, 0) ELSE 999 END),
                999) AS ap3_coverage_pct,
         CASE a3.highest_level WHEN 'ES' THEN m.ap3_es_learners_per_teacher WHEN 'JHS' THEN m.ap3_jhs_learners_per_teacher
              WHEN 'SHS' THEN m.ap3_shs_learners_per_teacher END AS ap3_value
  FROM {A}.lgu_priority_matrix AS m
  JOIN lgu AS l ON l.city_mun_psgc_code = m.city_mun_psgc_code
  LEFT JOIN {A}.lgu_priority_checks AS k ON k.city_mun_psgc_code = m.city_mun_psgc_code
  LEFT JOIN {A}.ap1_school_provision AS a1 ON a1.city_mun_psgc_code = m.city_mun_psgc_code
  LEFT JOIN {A}.ap2_classroom_pressure AS a2 ON a2.city_mun_psgc_code = m.city_mun_psgc_code
  LEFT JOIN {A}.ap3_teacher_pressure AS a3 ON a3.city_mun_psgc_code = m.city_mun_psgc_code
)"""
PRI = f"""{LGU},
{PRI_CTE}"""

OV_FILTER = (f"{GEO} AND (:tier = '{ALL_TIERS}' OR tier = :tier)"
             f" AND (:coverage = '{ALL_COVERAGE}' OR (:coverage = 'Assessed' AND tier <> 'Data review')"
             f" OR (:coverage = 'Data review' AND tier = 'Data review'))")

# ============================================================ 1 Overview
GEOM = "st_setsrid(st_simplify(st_geomfromgeojson(h.geometry), 0.003), 4326)"
OV_LGU = f"""SELECT b.*, {GEOM} AS boundary
FROM (
  WITH {PRI}
  SELECT ROW_NUMBER() OVER (ORDER BY tier_sort DESC, order_in_tier) AS rank_in_view, national_rank,
         city_mun_psgc_code, lgu_label, lgu_type_label, province_label, region_name, tier, tier_level, tier_meaning,
         high_areas, high_count_label, data_review_reason, stability, affected_learners, ap3_highest_level,
         NULLIF(LEAST(COALESCE(ap1_coverage_pct, 0), COALESCE(ap2_learner_coverage_pct, 0), COALESCE(ap3_coverage_pct, 999)), 999)
           AS lowest_coverage_pct,
         100.0 * ap1_percentile AS ap1_pct, 100.0 * ap2_percentile AS ap2_pct, 100.0 * ap3_percentile AS ap3_pct
  FROM pri
  WHERE {OV_FILTER}
) AS b
LEFT JOIN edu_access.`04-integration`.hdx_adm3_psgc_map AS m
  ON m.psgc_code = b.city_mun_psgc_code AND m.match_status = 'matched'
LEFT JOIN edu_access.`03-silver`.hdx_adm3_clean AS h ON h.adm3_pcode = m.adm3_pcode
ORDER BY b.rank_in_view"""

OV_KPI = f"""WITH {PRI}
SELECT COUNT(*) AS lgus,
       COUNT_IF(tier IN ('Critical', 'Elevated')) AS priority_lgus,
       COUNT_IF(tier = 'Critical') AS critical_lgus,
       COUNT_IF(tier = 'Data review') AS data_review_lgus,
       SUM(affected_learners) AS public_learners,
       SUM(CASE WHEN tier IN ('Critical', 'Elevated') THEN affected_learners ELSE 0 END) AS priority_learners,
       SUM(CASE WHEN tier IN ('Critical', 'Elevated') THEN affected_learners ELSE 0 END)
         / NULLIF(CAST(SUM(affected_learners) AS DOUBLE), 0) AS priority_learner_share,
       COALESCE(CAST(ROUND(100.0 * SUM(CASE WHEN tier IN ('Critical', 'Elevated') THEN affected_learners ELSE 0 END)
         / NULLIF(SUM(affected_learners), 0), 1) AS STRING) || '%', 'n/a') AS share_txt
FROM pri
WHERE {OV_FILTER}"""

DRIVER_ORDER = ["Schools + Classrooms + Teachers", "Classrooms + Teachers", "Schools + Teachers", "Schools + Classrooms",
                "Teachers", "Classrooms", "Schools"]
OV_DRIVERS = f"""WITH {PRI}
SELECT city_mun_psgc_code, high_areas, tier, affected_learners
FROM pri
WHERE tier IN ('Critical', 'Elevated', 'Targeted') AND {OV_FILTER}"""

RP_GROUPS = ["High-pressure LGUs", "Other assessed LGUs"]
OV_RP = f"""WITH {PRI},
u AS (
  SELECT '{MEASURES[0]}' AS measure, ap1_high AS high, ap1_relative_pressure AS rp FROM pri WHERE ap1_assessed AND {GEO}
  UNION ALL SELECT '{MEASURES[1]}', ap2_high, ap2_relative_pressure FROM pri WHERE ap2_assessed AND {GEO}
  UNION ALL SELECT '{MEASURES[2]}', ap3_high, ap3_relative_pressure FROM pri WHERE ap3_assessed AND {GEO}
)
SELECT measure, CASE WHEN high THEN '{RP_GROUPS[0]}' ELSE '{RP_GROUPS[1]}' END AS lgu_group,
       MEDIAN(rp) AS typical_relative_pressure, COUNT(*) AS lgus
FROM u
WHERE rp IS NOT NULL
GROUP BY ALL"""

# ============================================================ 2 LGU Profile
SEL = f"""sel AS (
  SELECT l.city_mun_psgc_code, l.lgu_label
  FROM lgu AS l
  JOIN {A}.lgu_priority_matrix AS p ON p.city_mun_psgc_code = l.city_mun_psgc_code
  WHERE {GEO_L}
  ORDER BY CASE WHEN l.lgu_label = :lgu THEN 0 ELSE 1 END, {TIER_SORT.format(c='p.tier')} DESC, p.order_in_tier
  LIMIT 1
)"""

PR_CARD = f"""WITH {PRI},
{SEL}
SELECT p.lgu_label, p.city_mun_name, p.lgu_type_label, p.province_label, p.region_name, p.tier, p.tier_meaning,
       CASE WHEN p.province_label = 'Independent cities (no province)' THEN p.region_name
            ELSE p.province_label || ', ' || p.region_name END AS province_region,
       p.national_rank, (SELECT COUNT(*) FROM {A}.lgu_priority_matrix) AS places_ranked,
       p.lgu_type_label || ' · '
         || CASE WHEN p.province_label = 'Independent cities (no province)' THEN p.region_name ELSE p.province_label END
         || ' · ' || p.tier || ' · rank ' || format_number(p.national_rank, 0) || ' of '
         || format_number((SELECT COUNT(*) FROM {A}.lgu_priority_matrix), 0)
         || CASE WHEN p.is_stable THEN ' · Stable' ELSE '' END
         || CASE WHEN :lgu <> '{TOP_LGU}' AND p.lgu_label <> :lgu THEN ' · top place in the filters' ELSE '' END AS details,
       p.high_count_label, p.high_areas, p.affected_learners, p.stability,
       CASE WHEN :lgu <> '{TOP_LGU}' AND p.lgu_label <> :lgu
            THEN '(Your selection is outside the filters, so this shows the top LGU in them.)' ELSE '' END AS notice
FROM pri AS p
JOIN sel ON sel.city_mun_psgc_code = p.city_mun_psgc_code"""

PR_WHY = f"""WITH {PRI},
{SEL},
p AS (SELECT pri.* FROM pri JOIN sel USING (city_mun_psgc_code))
SELECT '{MEASURES[0]}' AS measure, 1 AS ord, ap1_relative_pressure AS relative_pressure,
       CASE WHEN NOT ap1_assessed THEN 'Not assessed' WHEN ap1_high THEN 'High' ELSE 'Not high' END AS status
FROM p
UNION ALL SELECT '{MEASURES[1]}', 2, ap2_relative_pressure,
       CASE WHEN NOT ap2_assessed THEN 'Not assessed' WHEN ap2_high THEN 'High' ELSE 'Not high' END FROM p
UNION ALL SELECT '{MEASURES[2]}', 3, ap3_relative_pressure,
       CASE WHEN NOT ap3_assessed THEN 'Not assessed' WHEN ap3_high THEN 'High' ELSE 'Not high' END FROM p"""

PR_RELIABILITY = f"""WITH {PRI},
{SEL},
p AS (SELECT pri.* FROM pri JOIN sel USING (city_mun_psgc_code))
SELECT 1 AS ord, '{MEASURES[0]}' AS measure, {r1('ap1_learners_per_public_school')} AS value,
       {r1('ap1_same_type_median')} AS typical, {r0('100 * ap1_percentile')} AS percentile,
       {cov('ap1_coverage_pct')} AS coverage,
       CASE WHEN ap1_assessed THEN 'Assessed' ELSE 'Not assessed' END AS assessed,
       'No outlier rule' AS unusual_schools
FROM p
UNION ALL SELECT 2, '{MEASURES[1]}', {r1('ap2_learners_per_classroom')}, {r1('ap2_same_type_median')},
       {r0('100 * ap2_percentile')}, {cov('ap2_learner_coverage_pct')},
       CASE WHEN ap2_assessed THEN 'Assessed' ELSE 'Not assessed' END,
       'Schools above the fence: ' || format_number(COALESCE(ap2_outlier_school_count, 0), 0)
FROM p
UNION ALL SELECT 3, '{MEASURES[2]} · ' || COALESCE(ap3_level, 'no level'), {r1('ap3_value')}, {r1('ap3_same_type_median')},
       {r0('100 * ap3_percentile')}, {cov('ap3_coverage_pct')},
       CASE WHEN ap3_assessed THEN 'Assessed' ELSE 'Not assessed' END,
       'School levels above the fence: ' || format_number(COALESCE(ap3_outlier_school_level_count, 0), 0)
FROM p
UNION ALL SELECT 4, 'Tier without the flagged schools', COALESCE(tier_without_outliers, 'n/a'), tier, '', '',
       CASE WHEN outliers_change_tier THEN 'Changes' ELSE 'Holds' END, ''
FROM p"""

LEVEL_LABEL = "CASE {c} WHEN 'ES' THEN 'Elementary' WHEN 'JHS' THEN 'Junior high' ELSE 'Senior high' END"
PR_TEACHERS = f"""WITH {PRI},
{SEL},
active AS (
  SELECT e.school_id, MAX(CASE WHEN e.is_offered AND e.learner_count > 0 THEN 1 ELSE 0 END) AS is_active
  FROM {G}.fact_school_enrollment AS e JOIN sel ON sel.city_mun_psgc_code = e.city_mun_psgc_code
  WHERE e.school_year = '2023-24' AND e.sector = 'Public' AND e.psgc_match_status = 'matched'
  GROUP BY e.school_id
),
t AS (
  SELECT t.education_level_code,
         SUM(COALESCE(t.teacher_count, 0)) AS teachers,
         SUM(COALESCE(t.sef_provincial_teacher_count, 0) + COALESCE(t.sef_city_municipal_teacher_count, 0)
             + COALESCE(t.lgu_funded_teacher_count, 0) + COALESCE(t.other_funded_teacher_count, 0)) AS locally_funded
  FROM {G}.fact_school_teacher_capacity AS t
  JOIN active AS a ON a.school_id = t.school_id AND a.is_active = 1
  WHERE t.school_year = '2023-24'
  GROUP BY t.education_level_code
),
p AS (SELECT pri.* FROM pri JOIN sel USING (city_mun_psgc_code)),
labelled AS (
  SELECT t.*, {LEVEL_LABEL.format(c='t.education_level_code')} || ' · ' ||
         {r1("CASE t.education_level_code WHEN 'ES' THEN p.ap3_es_learners_per_teacher WHEN 'JHS' THEN p.ap3_jhs_learners_per_teacher ELSE p.ap3_shs_learners_per_teacher END")}
         || ' learners per teacher' AS level_label,
         CASE t.education_level_code WHEN 'ES' THEN 1 WHEN 'JHS' THEN 2 ELSE 3 END AS ord
  FROM t CROSS JOIN p
)
SELECT level_label, ord, 'DepEd-funded' AS funding, GREATEST(teachers - locally_funded, 0) AS teachers FROM labelled
UNION ALL SELECT level_label, ord, 'Locally funded (SEF, LGU, other)', locally_funded FROM labelled"""

PR_ENROLLMENT = f"""WITH {LGU},
{SEL},
y AS (SELECT a.* FROM {A}.ap4_enrollment_trend AS a JOIN sel USING (city_mun_psgc_code))
SELECT 'SY ' || school_year AS school_year_label, 'All sectors' AS scope, enrollment_all_sectors AS learners FROM y
UNION ALL SELECT 'SY ' || school_year, 'Public schools', public_school_enrollment FROM y"""

CENSUS_SERIES = ["Children aged 5-17", "Enrolled, all sectors", "Difference (children minus enrolled)"]
PR_CENSUS = f"""WITH {LGU},
{SEL},
c AS (
  SELECT CAST(a.census_year AS STRING) || ' · SY ' || a.school_year
           || CASE WHEN a.is_2020_2024_geography_comparable THEN '' ELSE ' (boundaries changed)' END AS period, a.*
  FROM {A}.ap4_enrollment_trend AS a JOIN sel USING (city_mun_psgc_code)
  WHERE a.census_year IS NOT NULL
)
SELECT period, '{CENSUS_SERIES[0]}' AS series, school_age_population AS people FROM c
UNION ALL SELECT period, '{CENSUS_SERIES[1]}', enrollment_all_sectors FROM c
UNION ALL SELECT period, '{CENSUS_SERIES[2]}', population_enrollment_gap FROM c"""


def school_base(level_param=True):
    """Active and blank-count public schools in the selected LGU, SY 2023-24, with the reasons to verify each."""
    level = (f"CASE WHEN :level = '{ALL_LEVELS}' THEN NULL ELSE :level END") if level_param else "CAST(NULL AS STRING)"
    return f"""{LGU},
{SEL},
lvl AS (SELECT {level} AS level_code),
checks AS (SELECT k.outliers_change_tier FROM {A}.lgu_priority_checks AS k JOIN sel USING (city_mun_psgc_code)),
e AS (
  SELECT e.* FROM {G}.fact_school_enrollment AS e JOIN sel ON sel.city_mun_psgc_code = e.city_mun_psgc_code
  WHERE e.sector = 'Public' AND e.psgc_match_status = 'matched'
),
sch AS (
  SELECT school_id, MAX(barangay_psgc_code) AS barangay_psgc_code, MAX(annex_status) AS annex_status,
         MAX(CASE WHEN is_offered AND learner_count > 0 THEN 1 ELSE 0 END) AS is_active,
         COUNT_IF(is_offered) > 0 AND COUNT_IF(is_offered AND learner_count IS NOT NULL) = 0 AS is_blank,
         COUNT_IF(is_offered AND learner_count IS NULL) AS incomplete_levels,
         SUM(CASE WHEN is_offered AND learner_count IS NOT NULL THEN learner_count ELSE 0 END) AS learners,
         MAX(CASE WHEN education_level_code = 'ES' AND is_offered THEN 1 ELSE 0 END) AS offers_es,
         MAX(CASE WHEN education_level_code = 'JHS' AND is_offered THEN 1 ELSE 0 END) AS offers_jhs,
         MAX(CASE WHEN education_level_code = 'SHS' AND is_offered THEN 1 ELSE 0 END) AS offers_shs,
         SUM(CASE WHEN education_level_code = 'ES' AND is_offered THEN learner_count END) AS es_learners,
         SUM(CASE WHEN education_level_code = 'JHS' AND is_offered THEN learner_count END) AS jhs_learners,
         SUM(CASE WHEN education_level_code = 'SHS' AND is_offered THEN learner_count END) AS shs_learners
  FROM e WHERE school_year = '2023-24' GROUP BY school_id
),
years AS (
  SELECT school_id,
         SUM(CASE WHEN school_year = '2020-21' AND is_offered THEN learner_count END) AS learners_2020,
         SUM(CASE WHEN school_year = '2025-26' AND is_offered THEN learner_count END) AS learners_2025,
         COUNT_IF(school_year IN ('2020-21', '2025-26') AND is_offered AND learner_count IS NULL) AS incomplete_ends
  FROM e GROUP BY school_id
),
t AS (
  SELECT school_id,
         MAX(CASE WHEN education_level_code = 'ES' THEN teacher_count END) AS es_teachers,
         MAX(CASE WHEN education_level_code = 'JHS' THEN teacher_count END) AS jhs_teachers,
         MAX(CASE WHEN education_level_code = 'SHS' THEN teacher_count END) AS shs_teachers,
         COUNT_IF(education_level_code = 'ES') AS es_rows, COUNT_IF(education_level_code = 'JHS') AS jhs_rows,
         COUNT_IF(education_level_code = 'SHS') AS shs_rows,
         SUM(COALESCE(sef_provincial_teacher_count, 0) + COALESCE(sef_city_municipal_teacher_count, 0)
             + COALESCE(lgu_funded_teacher_count, 0) + COALESCE(other_funded_teacher_count, 0)) AS locally_funded_teachers
  FROM {G}.fact_school_teacher_capacity WHERE school_year = '2023-24' GROUP BY school_id
),
o AS (
  SELECT school_id,
         MAX(CASE WHEN measure = 'AP2' THEN 'Learners per classroom ' || {r1('school_ratio')} || ' is above the outlier fence of '
                  || {r1('upper_fence')} END) AS room_fence_reason,
         MAX(CASE WHEN measure = 'AP3' AND education_level_code = 'ES' THEN 'Learners per teacher at Elementary '
                  || {r1('school_ratio')} || ' is above the fence of ' || {r1('upper_fence')} END) AS es_fence_reason,
         MAX(CASE WHEN measure = 'AP3' AND education_level_code = 'JHS' THEN 'Learners per teacher at Junior high '
                  || {r1('school_ratio')} || ' is above the fence of ' || {r1('upper_fence')} END) AS jhs_fence_reason,
         MAX(CASE WHEN measure = 'AP3' AND education_level_code = 'SHS' THEN 'Learners per teacher at Senior high '
                  || {r1('school_ratio')} || ' is above the fence of ' || {r1('upper_fence')} END) AS shs_fence_reason
  FROM {A}.lgu_priority_outlier_schools GROUP BY school_id
),
x AS (
  SELECT s.school_id, COALESCE(ds.school_name, s.school_id) AS school_name,
         COALESCE(b.barangay_name, 'Barangay not matched') AS barangay_name,
         CASE WHEN s.annex_status = 'Annex/Extension School' THEN 'Annex' ELSE 'Main' END AS school_kind,
         concat_ws(' + ', CASE WHEN s.offers_es = 1 THEN 'ES' END, CASE WHEN s.offers_jhs = 1 THEN 'JHS' END,
                          CASE WHEN s.offers_shs = 1 THEN 'SHS' END) AS levels_offered,
         s.offers_es, s.offers_jhs, s.offers_shs, s.es_learners, s.jhs_learners, s.shs_learners,
         CASE WHEN s.incomplete_levels = 0 THEN s.learners END AS learners,
         r.instructional_classrooms_total AS rooms,
         COALESCE(r.temporary_learning_spaces, 0) + COALESCE(r.makeshift_rooms, 0) AS temporary_or_makeshift_rooms,
         r.temporary_learning_spaces, r.makeshift_rooms,
         CASE WHEN s.incomplete_levels = 0 AND r.instructional_classrooms_total > 0
              THEN s.learners / CAST(r.instructional_classrooms_total AS DOUBLE) END AS learners_per_room,
         t.es_teachers, t.jhs_teachers, t.shs_teachers, COALESCE(t.locally_funded_teachers, 0) AS locally_funded_teachers,
         COALESCE(t.es_teachers, 0) + COALESCE(t.jhs_teachers, 0) + COALESCE(t.shs_teachers, 0) AS teachers,
         (CASE WHEN t.es_teachers > 0 THEN COALESCE(s.es_learners, 0) ELSE 0 END
          + CASE WHEN t.jhs_teachers > 0 THEN COALESCE(s.jhs_learners, 0) ELSE 0 END
          + CASE WHEN t.shs_teachers > 0 THEN COALESCE(s.shs_learners, 0) ELSE 0 END)
          / NULLIF(CAST(CASE WHEN t.es_teachers > 0 THEN t.es_teachers ELSE 0 END
                        + CASE WHEN t.jhs_teachers > 0 THEN t.jhs_teachers ELSE 0 END
                        + CASE WHEN t.shs_teachers > 0 THEN t.shs_teachers ELSE 0 END AS DOUBLE), 0) AS learners_per_teacher,
         CASE (SELECT level_code FROM lvl)
              WHEN 'ES' THEN s.es_learners / NULLIF(CAST(t.es_teachers AS DOUBLE), 0)
              WHEN 'JHS' THEN s.jhs_learners / NULLIF(CAST(t.jhs_teachers AS DOUBLE), 0)
              WHEN 'SHS' THEN s.shs_learners / NULLIF(CAST(t.shs_teachers AS DOUBLE), 0) END AS learners_per_teacher_at_level,
         CASE WHEN y.incomplete_ends = 0 AND y.learners_2020 > 0
              THEN (y.learners_2025 - y.learners_2020) / CAST(y.learners_2020 AS DOUBLE) END AS enrollment_change,
         CASE (SELECT level_code FROM lvl) WHEN 'ES' THEN s.offers_es WHEN 'JHS' THEN s.offers_jhs
              WHEN 'SHS' THEN s.offers_shs ELSE 1 END AS offers_level,
         concat_ws('; ',
           o.room_fence_reason, o.es_fence_reason, o.jhs_fence_reason, o.shs_fence_reason,
           CASE WHEN r.school_id IS NULL OR r.instructional_classrooms_total IS NULL THEN 'Classroom count not reported' END,
           CASE WHEN r.instructional_classrooms_total = 0 THEN '0 classrooms reported' END,
           CASE WHEN s.incomplete_levels > 0 THEN 'An offered level has no learner count' END,
           CASE WHEN s.offers_es = 1 AND (t.es_rows IS NULL OR t.es_rows = 0 OR t.es_teachers IS NULL) THEN 'Elementary offered but no teacher count' END,
           CASE WHEN s.offers_jhs = 1 AND (t.jhs_rows IS NULL OR t.jhs_rows = 0 OR t.jhs_teachers IS NULL) THEN 'Junior high offered but no teacher count' END,
           CASE WHEN s.offers_shs = 1 AND (t.shs_rows IS NULL OR t.shs_rows = 0 OR t.shs_teachers IS NULL) THEN 'Senior high offered but no teacher count' END,
           CASE WHEN s.annex_status <> 'Annex/Extension School' AND ((s.offers_es = 1 AND t.es_teachers = 0)
                  OR (s.offers_jhs = 1 AND t.jhs_teachers = 0) OR (s.offers_shs = 1 AND t.shs_teachers = 0))
                THEN '0 teachers reported at an offered level' END,
           CASE WHEN COALESCE(o.room_fence_reason, o.es_fence_reason, o.jhs_fence_reason, o.shs_fence_reason) IS NOT NULL
                     AND (SELECT outliers_change_tier FROM checks)
                THEN 'Leaving out the flagged schools changes this LGU''s tier' END) AS reasons,
         CASE WHEN COALESCE(o.room_fence_reason, o.es_fence_reason, o.jhs_fence_reason, o.shs_fence_reason) IS NOT NULL
                THEN '{STATUS_ORDER[0]}'
              WHEN r.school_id IS NULL OR r.instructional_classrooms_total IS NULL OR s.incomplete_levels > 0
                   OR (s.offers_es = 1 AND t.es_teachers IS NULL) OR (s.offers_jhs = 1 AND t.jhs_teachers IS NULL)
                   OR (s.offers_shs = 1 AND t.shs_teachers IS NULL) THEN '{STATUS_ORDER[1]}'
              WHEN r.instructional_classrooms_total = 0 OR (s.annex_status <> 'Annex/Extension School'
                   AND ((s.offers_es = 1 AND t.es_teachers = 0) OR (s.offers_jhs = 1 AND t.jhs_teachers = 0)
                        OR (s.offers_shs = 1 AND t.shs_teachers = 0))) THEN '{STATUS_ORDER[2]}'
              ELSE '{STATUS_ORDER[3]}' END AS status
  FROM sch AS s
  LEFT JOIN {G}.dim_school AS ds ON ds.school_id = s.school_id
  LEFT JOIN {G}.dim_barangay AS b ON b.barangay_psgc_code = s.barangay_psgc_code AND b.member_type = 'regular'
  LEFT JOIN {G}.fact_school_classroom_capacity AS r ON r.school_id = s.school_id AND r.school_year = '2023-24'
  LEFT JOIN t ON t.school_id = s.school_id
  LEFT JOIN o ON o.school_id = s.school_id
  LEFT JOIN years AS y ON y.school_id = s.school_id
  WHERE s.is_active = 1 OR s.is_blank
),
schools AS (
  SELECT x.*, status <> '{STATUS_ORDER[3]}' AS to_check,
         ROW_NUMBER() OVER (ORDER BY CASE WHEN status <> '{STATUS_ORDER[3]}' THEN 0 ELSE 1 END,
                                     learners_per_room DESC NULLS LAST, school_name) AS list_order
  FROM x
)"""


BARANGAY = f"(:barangay = '{ALL_BARANGAYS}' OR barangay_name = :barangay)"

PR_LOCAL_KPI = f"""WITH {school_base(level_param=False)},
br AS (
  SELECT b.barangay_name,
         MAX(CASE WHEN s.offers_es = 1 AND s.learners > 0 THEN 1 ELSE 0 END) AS has_public_es
  FROM {G}.dim_barangay AS b
  JOIN sel ON sel.city_mun_psgc_code = b.city_mun_psgc_code
  LEFT JOIN schools AS s ON s.barangay_name = b.barangay_name
  WHERE b.member_type = 'regular'
  GROUP BY b.barangay_name
)
SELECT (SELECT COUNT_IF(has_public_es = 0) FROM br) AS barangays_without_public_es,
       (SELECT COUNT(*) FROM br) AS regular_barangays,
       (SELECT COUNT_IF(to_check) FROM schools) AS schools_to_check,
       (SELECT COUNT(*) FROM schools) AS schools,
       (SELECT COUNT_IF(barangay_name = 'Barangay not matched') FROM schools) AS schools_without_barangay,
       CASE WHEN (SELECT COUNT_IF(barangay_name = 'Barangay not matched') FROM schools) > 0 THEN 'At most ' ELSE '' END
         AS bound_prefix"""

PR_BARANGAYS = f"""WITH {school_base(level_param=False)},
bs AS (
  SELECT barangay_name, COUNT(*) AS public_schools, MAX(CASE WHEN offers_es = 1 AND learners > 0 THEN 1 ELSE 0 END) AS has_es,
         SUM(learners) AS learners
  FROM schools GROUP BY barangay_name
)
SELECT b.barangay_name, COALESCE(b.urban_rural, 'n/a') AS urban_rural, COALESCE(bs.public_schools, 0) AS public_schools,
       CASE WHEN COALESCE(bs.has_es, 0) = 1 THEN 'Yes' ELSE 'No' END AS public_es,
       COALESCE(bs.learners, 0) AS learners,
       CASE WHEN COALESCE(bs.has_es, 0) = 1 THEN 1 ELSE 0 END AS es_sort
FROM {G}.dim_barangay AS b
JOIN sel ON sel.city_mun_psgc_code = b.city_mun_psgc_code
LEFT JOIN bs ON bs.barangay_name = b.barangay_name
WHERE b.member_type = 'regular' AND {BARANGAY.replace('barangay_name', 'b.barangay_name')}
ORDER BY es_sort, learners DESC, b.barangay_name"""

PR_TEASER = f"""WITH {school_base(level_param=False)}
SELECT school_name, barangay_name, learners_per_room, status, reasons
FROM schools
WHERE list_order <= 5 AND {BARANGAY}
ORDER BY list_order"""

# Deterministic insights: fixed rules over the same tables as the visuals, at most four, each suppressed when its
# data is missing. They state facts and never a cause.
PR_INSIGHTS = f"""WITH {school_base(level_param=False)},
{PRI_CTE},
p AS (SELECT pri.* FROM pri JOIN sel USING (city_mun_psgc_code)),
strongest AS (
  SELECT * FROM (
    SELECT measure, pctl, value_txt, rp_txt,
           ROW_NUMBER() OVER (ORDER BY pctl DESC) AS rn
    FROM (
      SELECT 'Schools: ' || {r0('ap1_learners_per_public_school')} || ' learners per public school' AS measure,
             ap1_percentile AS pctl, '' AS value_txt, {r2('ap1_relative_pressure')} AS rp_txt FROM p WHERE ap1_assessed
      UNION ALL SELECT 'Classrooms: ' || {r1('ap2_learners_per_classroom')} || ' learners per classroom', ap2_percentile, '',
             {r2('ap2_relative_pressure')} FROM p WHERE ap2_assessed
      UNION ALL SELECT 'Teachers: ' || {r1('ap3_value')} || ' learners per teacher at ' || {LEVEL_LABEL.format(c='ap3_level')},
             ap3_percentile, '', {r2('ap3_relative_pressure')} FROM p WHERE ap3_assessed AND ap3_level IS NOT NULL
    ) AS u
  ) AS ranked WHERE rn = 1
),
trend AS (
  SELECT MIN(a.school_year) AS first_year, MAX(a.school_year) AS last_year,
         MAX(CASE WHEN a.school_year = a.first_school_year THEN a.enrollment_all_sectors END) AS first_value,
         MAX(CASE WHEN a.school_year = a.latest_school_year THEN a.enrollment_all_sectors END) AS last_value,
         MAX(a.enrollment_change_pct_first_to_latest) AS change_pct,
         SUM(a.schools_incomplete) AS incomplete
  FROM {A}.ap4_enrollment_trend AS a JOIN sel USING (city_mun_psgc_code)
),
brgy AS (
  SELECT COUNT_IF(has_es = 0) AS without_es, COUNT(*) AS barangays FROM (
    SELECT b.barangay_name, MAX(CASE WHEN s.offers_es = 1 AND s.learners > 0 THEN 1 ELSE 0 END) AS has_es
    FROM {G}.dim_barangay AS b JOIN sel ON sel.city_mun_psgc_code = b.city_mun_psgc_code
    LEFT JOIN schools AS s ON s.barangay_name = b.barangay_name
    WHERE b.member_type = 'regular' GROUP BY b.barangay_name) AS z
),
teachers AS (SELECT SUM(teachers) AS teachers, SUM(locally_funded_teachers) AS local FROM schools),
rules AS (
  SELECT 1 AS ord, measure || ' is the strongest pressure, at the ' || {r0('100 * pctl')}
         || 'th percentile among ' || (SELECT type_plural FROM p) || ' (' || rp_txt || ' times the typical one).' AS insight
  FROM strongest
  UNION ALL
  SELECT 2, CASE WHEN tier = 'Data review' THEN 'Not given a tier yet: ' || data_review_reason || '.'
                 ELSE 'School figures above the outlier fence: '
                      || format_number(COALESCE(ap2_outlier_school_count, 0) + COALESCE(ap3_outlier_school_level_count, 0), 0)
                      || '. The tier '
                      || CASE WHEN outliers_change_tier THEN 'changes to ' || tier_without_outliers ELSE 'stays ' || tier END
                      || ' without them, so check them with the Schools Division Office.' END
  FROM p
  WHERE tier = 'Data review' OR COALESCE(ap2_outlier_school_count, 0) + COALESCE(ap3_outlier_school_level_count, 0) > 0
  UNION ALL
  SELECT 3, 'Enrollment in all sectors went from ' || format_number(first_value, 0) || ' in SY ' || first_year || ' to '
            || format_number(last_value, 0) || ' in SY ' || last_year || ' (' || CASE WHEN change_pct >= 0 THEN '+' ELSE '' END
            || {r1('100 * change_pct')} || '%). Context only: it does not set the tier.'
  FROM trend WHERE incomplete = 0 AND first_value IS NOT NULL AND last_value IS NOT NULL AND change_pct IS NOT NULL
  UNION ALL
  SELECT 4, format_number(without_es, 0) || ' of ' || format_number(barangays, 0) || ' barangays '
            || CASE WHEN without_es = 1 THEN 'has' ELSE 'have' END
            || ' no matched public elementary school. A nearby school may still serve them.'
  FROM brgy WHERE without_es > 0
  UNION ALL
  SELECT 5, format_number(local, 0) || ' of ' || format_number(teachers, 0)
            || ' public-school teachers are locally funded (SEF, LGU or other local funds), SY 2023-24.'
  FROM teachers WHERE teachers > 0
)
SELECT ROW_NUMBER() OVER (ORDER BY ord) AS insight_order, insight
FROM rules
WHERE insight IS NOT NULL
ORDER BY ord
LIMIT 4"""

# ============================================================ 3 School Action
SCHOOL_FILTERS = (f"{BARANGAY} AND offers_level = 1"
                  f" AND (:school_status = '{ALL_SCHOOLS}' OR (:school_status = 'Figures to check' AND to_check)"
                  f" OR status = :school_status)")
PICK = f"""pick AS (
  SELECT school_id FROM schools
  WHERE {BARANGAY} AND offers_level = 1
  ORDER BY CASE WHEN school_name || ' · ' || school_id = :school THEN 0 ELSE 1 END, list_order
  LIMIT 1
)"""

SA_SCHOOL = f"""WITH {school_base()},
{PICK}
SELECT s.school_name, s.school_id, s.barangay_name, s.school_kind, s.levels_offered, s.learners,
       s.learners_per_room, s.learners_per_teacher, COALESCE(s.learners_per_teacher_at_level, s.learners_per_teacher) AS teacher_ratio,
       CASE WHEN (SELECT level_code FROM lvl) IS NULL THEN 'all levels' ELSE {LEVEL_LABEL.format(c='(SELECT level_code FROM lvl)')} END AS level_txt,
       s.enrollment_change, s.temporary_or_makeshift_rooms, s.status,
       CASE WHEN s.to_check THEN 'Figures to check' ELSE 'No figures to check' END AS check_label,
       'ID ' || s.school_id || ' · ' || s.barangay_name || ' · ' || s.school_kind || ' · ' || s.levels_offered
         || ' · ' || COALESCE(format_number(s.learners, 0), 'n/a') || ' learners · '
         || CASE WHEN s.to_check THEN 'Figures to check' ELSE 'No figures to check' END
         || CASE WHEN :school <> '{FIRST_SCHOOL}' AND s.school_name || ' · ' || s.school_id <> :school
                 THEN ' · first school to check' ELSE '' END AS details,
       CASE WHEN :school <> '{FIRST_SCHOOL}' AND s.school_name || ' · ' || s.school_id <> :school
            THEN '(Your school is outside the filters, so this shows the first school to check.)' ELSE '' END AS notice
FROM schools AS s JOIN pick USING (school_id)"""

SA_PEERS = f"""WITH {school_base()},
{PICK}
SELECT s.school_name, s.learners, s.learners_per_room,
       COALESCE(s.learners_per_teacher_at_level, s.learners_per_teacher) AS teacher_ratio,
       CASE WHEN s.school_id = (SELECT school_id FROM pick) THEN 'Selected school'
            WHEN s.to_check THEN 'Figures to check' ELSE 'Other schools' END AS series
FROM schools AS s
WHERE s.offers_level = 1 AND s.learners_per_room IS NOT NULL
  AND COALESCE(s.learners_per_teacher_at_level, s.learners_per_teacher) IS NOT NULL"""

SA_TREND = f"""WITH {school_base()},
{PICK},
y AS (
  SELECT 'SY ' || e.school_year AS school_year_label, e.education_level_code, SUM(e.learner_count) AS learners
  FROM e JOIN pick USING (school_id)
  WHERE e.is_offered
  GROUP BY e.school_year, e.education_level_code
),
levels AS (SELECT COUNT(DISTINCT education_level_code) AS n FROM y)
-- the school's total first; each level only when the school offers more than one
SELECT school_year_label, 'All levels' AS series, SUM(learners) AS learners FROM y GROUP BY school_year_label
UNION ALL
SELECT school_year_label, {LEVEL_LABEL.format(c='education_level_code')}, learners FROM y
WHERE (SELECT n FROM levels) > 1"""

SA_ROOMS = f"""WITH {school_base()},
{PICK},
s AS (SELECT schools.* FROM schools JOIN pick USING (school_id)),
lv AS (
  SELECT 1 AS ord, 'Elementary' AS level, offers_es AS offered, es_learners AS learners, es_teachers AS teachers FROM s
  UNION ALL SELECT 2, 'Junior high', offers_jhs, jhs_learners, jhs_teachers FROM s
  UNION ALL SELECT 3, 'Senior high', offers_shs, shs_learners, shs_teachers FROM s
)
SELECT ord, level, learners, teachers, learners / NULLIF(CAST(teachers AS DOUBLE), 0) AS learners_per_teacher,
       CAST(NULL AS BIGINT) AS classrooms, CAST(NULL AS BIGINT) AS temporary_rooms, CAST(NULL AS BIGINT) AS makeshift_rooms
FROM lv WHERE offered = 1
UNION ALL
SELECT 4, 'All levels (rooms are shared)', learners, teachers, learners_per_teacher, rooms, temporary_learning_spaces, makeshift_rooms
FROM s
ORDER BY ord"""

SA_VERIFY = f"""WITH {school_base()},
{PICK},
s AS (SELECT schools.* FROM schools JOIN pick USING (school_id))
SELECT CASE WHEN to_check THEN status ELSE 'No figures to check' END AS status,
       CASE WHEN to_check THEN reasons ELSE 'Every figure is reported and within the outlier fences.' END AS reason,
       'Confirm with the school and the Schools Division Office before using this figure for planning.' AS next_step
FROM s"""

SA_LIST = f"""WITH {school_base()}
SELECT list_order, school_name, school_id, barangay_name, levels_offered, learners, learners_per_room,
       COALESCE(learners_per_teacher_at_level, learners_per_teacher) AS teacher_ratio, enrollment_change,
       temporary_or_makeshift_rooms, locally_funded_teachers, school_kind, status, reasons
FROM schools
WHERE {SCHOOL_FILTERS}
ORDER BY list_order"""

# ============================================================ 4 Data and Method
FRESHNESS = f"""WITH runs AS (
  SELECT MAX(finished_at_utc) AS last_run FROM edu_access.`01-control`.pipeline_runs WHERE status = 'succeeded'
),
years AS (
  SELECT MIN(CASE WHEN source_id = 'deped_enrollment' AND has_data THEN school_year END) AS first_enrollment,
         MAX(CASE WHEN source_id = 'deped_enrollment' AND has_data THEN school_year END) AS last_enrollment,
         MAX(CASE WHEN source_id IN ('deped_facilities', 'deped_personnel') AND has_data THEN school_year END) AS last_capacity
  FROM {G}.fact_school_year_source_availability
)
SELECT 'Data as of ' || COALESCE(CAST(CAST(runs.last_run AS DATE) AS STRING), 'n/a')
       || ' · classrooms and teachers SY ' || COALESCE(years.last_capacity, 'n/a')
       || ' · enrollment SY ' || COALESCE(years.first_enrollment, 'n/a') || ' to ' || COALESCE(years.last_enrollment, 'n/a')
         AS freshness
FROM runs CROSS JOIN years"""

DM_KPI = f"""WITH {PRI}
SELECT COUNT(*) AS lgus,
       COUNT_IF(tier <> 'Data review') AS assessed,
       COUNT_IF(tier = 'Data review') AS data_review,
       COUNT_IF(tier = 'Critical') AS critical,
       COUNT_IF(is_stable) AS stable,
       COUNT_IF(outliers_change_tier) AS outlier_changes
FROM pri
WHERE {GEO}"""

DM_REFS = f"""WITH {PRI}
SELECT measure, lgu_type_label, MAX(typical) AS typical_value, COUNT(*) AS lgus
FROM (
  SELECT '{MEASURES[0]} · learners per public school' AS measure, lgu_type_label, ap1_same_type_median AS typical FROM pri WHERE ap1_assessed
  UNION ALL SELECT '{MEASURES[1]} · learners per classroom', lgu_type_label, ap2_same_type_median FROM pri WHERE ap2_assessed
) AS r
WHERE {TYPE_ONLY}
GROUP BY measure, lgu_type_label"""

COVERAGE_BANDS = ["95-100% (assessed)", "90-95% (assessed)", "80-90%", "50-80%", "Under 50%", "No value"]
COVERAGE_MEASURES = ["Schools (AP1)", "Classrooms (AP2)", "Teachers, Elementary (AP3)", "Teachers, Junior high (AP3)",
                     "Teachers, Senior high (AP3)"]
DM_COVERAGE = f"""WITH {PRI},
c AS (
  SELECT '{COVERAGE_MEASURES[0]}' AS measure, ap1_coverage_pct AS coverage FROM pri WHERE {GEO}
  UNION ALL SELECT '{COVERAGE_MEASURES[1]}', ap2_learner_coverage_pct FROM pri WHERE {GEO}
  UNION ALL SELECT '{COVERAGE_MEASURES[2]}', a.es_learner_coverage_pct FROM pri JOIN {A}.ap3_teacher_pressure AS a USING (city_mun_psgc_code)
            WHERE a.es_offered_school_count > 0 AND {GEO_PRI}
  UNION ALL SELECT '{COVERAGE_MEASURES[3]}', a.jhs_learner_coverage_pct FROM pri JOIN {A}.ap3_teacher_pressure AS a USING (city_mun_psgc_code)
            WHERE a.jhs_offered_school_count > 0 AND {GEO_PRI}
  UNION ALL SELECT '{COVERAGE_MEASURES[4]}', a.shs_learner_coverage_pct FROM pri JOIN {A}.ap3_teacher_pressure AS a USING (city_mun_psgc_code)
            WHERE a.shs_offered_school_count > 0 AND {GEO_PRI}
)
SELECT measure,
       CASE WHEN coverage IS NULL THEN '{COVERAGE_BANDS[5]}' WHEN coverage < 50 THEN '{COVERAGE_BANDS[4]}'
            WHEN coverage < 80 THEN '{COVERAGE_BANDS[3]}' WHEN coverage < 90 THEN '{COVERAGE_BANDS[2]}'
            WHEN coverage < 95 THEN '{COVERAGE_BANDS[1]}' ELSE '{COVERAGE_BANDS[0]}' END AS coverage_band,
       COUNT(*) AS lgus
FROM c
WHERE (:measure = '{ALL_MEASURES}' OR measure = :measure OR (measure LIKE 'Teachers%' AND :measure = 'Teachers (AP3)'))
GROUP BY ALL"""

DM_REASONS = f"""WITH {PRI},
r AS (
  SELECT '{MEASURES[0]}' AS measure, a.not_assessed_reason AS reason FROM pri JOIN {A}.ap1_school_provision AS a USING (city_mun_psgc_code) WHERE {GEO_PRI}
  UNION ALL SELECT '{MEASURES[1]}', a.not_assessed_reason FROM pri JOIN {A}.ap2_classroom_pressure AS a USING (city_mun_psgc_code) WHERE {GEO_PRI}
  UNION ALL SELECT '{MEASURES[2]}', a.not_assessed_reason FROM pri JOIN {A}.ap3_teacher_pressure AS a USING (city_mun_psgc_code) WHERE {GEO_PRI}
)
SELECT measure, reason, COUNT(*) AS lgus
FROM r
WHERE reason IS NOT NULL AND (:measure = '{ALL_MEASURES}' OR measure = :measure)
GROUP BY measure, reason"""

HOLD_SERIES = ["Critical under this check", "Also Critical under the published rule"]
DM_HOLD = f"""WITH {PRI},
p AS (SELECT * FROM pri WHERE {TYPE_ONLY}),
c AS (
  SELECT 1 AS s, 'Published rule' AS check_name, tier = 'Critical' AS critical, tier FROM p
  UNION ALL SELECT 2, 'Ranked nationally', national_tier = 'Critical', tier FROM p
  UNION ALL SELECT 3, 'Without outlier schools', tier_without_outliers = 'Critical', tier FROM p
  UNION ALL SELECT 4, '95% coverage gate', tier_at_gate_95 = 'Critical', tier FROM p
  UNION ALL SELECT 5, 'High line at 0.85', tier_at_line_085 = 'Critical', tier FROM p
  UNION ALL SELECT 6, 'High line at 0.80', tier_at_line_080 = 'Critical', tier FROM p
),
k AS (
  SELECT s, check_name, COUNT_IF(critical) AS critical, COUNT_IF(critical AND tier = 'Critical') AS kept
  FROM c GROUP BY s, check_name
),
base AS (SELECT critical AS published FROM k WHERE s = 1)
SELECT CAST(k.s AS STRING) || ' ' || k.check_name || ' · ' || {r0('100.0 * k.kept / NULLIF(base.published, 0)')} || '% kept' AS check_label,
       '{HOLD_SERIES[0]}' AS series, k.critical AS lgus
FROM k CROSS JOIN base
UNION ALL
SELECT CAST(k.s AS STRING) || ' ' || k.check_name || ' · ' || {r0('100.0 * k.kept / NULLIF(base.published, 0)')} || '% kept',
       '{HOLD_SERIES[1]}', k.kept
FROM k CROSS JOIN base"""

DM_TRANSITION = f"""WITH {PRI}
SELECT tier AS published_tier,
       CASE :scenario WHEN '{SCENARIOS[0]}' THEN tier_without_outliers WHEN '{SCENARIOS[1]}' THEN tier_at_gate_95
                      WHEN '{SCENARIOS[2]}' THEN tier_at_line_085 WHEN '{SCENARIOS[3]}' THEN tier_at_line_080
                      ELSE national_tier END AS check_tier,
       COUNT(*) AS lgus
FROM pri
WHERE {TYPE_ONLY}
GROUP BY ALL"""

DM_OVERLAP = f"""WITH {PRI},
p AS (SELECT * FROM pri WHERE {TYPE_ONLY}),
pairs AS (
  SELECT lgu_type_label, 'Schools and classrooms' AS pair, ap1_percentile AS a, ap2_percentile AS b, ap1_high AS ha, ap2_high AS hb,
         ap1_assessed AND ap2_assessed AS both_assessed FROM p
  UNION ALL SELECT lgu_type_label, 'Schools and teachers', ap1_percentile, ap3_percentile, ap1_high, ap3_high,
         ap1_assessed AND ap3_assessed FROM p
  UNION ALL SELECT lgu_type_label, 'Classrooms and teachers', ap2_percentile, ap3_percentile, ap2_high, ap3_high,
         ap2_assessed AND ap3_assessed FROM p
)
SELECT pair, lgu_type_label, corr(a, b) AS rank_agreement,
       COUNT_IF(ha AND hb) / NULLIF(CAST(COUNT_IF(ha) AS DOUBLE), 0) AS shared_high,
       COUNT(*) AS lgus_compared
FROM pairs
WHERE both_assessed AND a IS NOT NULL AND b IS NOT NULL
GROUP BY pair, lgu_type_label"""

DM_SOURCES = f"""SELECT school_year,
       CASE source_id WHEN 'deped_enrollment' THEN 'Enrollment' WHEN 'deped_facilities' THEN 'Classrooms (facilities)'
            WHEN 'deped_personnel' THEN 'Teachers (personnel)' ELSE source_id END AS source,
       CASE WHEN has_data THEN 1 ELSE 0 END AS has_data
FROM {G}.fact_school_year_source_availability"""

DM_CHECKS = """SELECT layer, status, COUNT(*) AS checks
FROM (
  SELECT layer, table_name, check_name, status
  FROM edu_access.`01-control`.data_quality_results
  QUALIFY ROW_NUMBER() OVER (PARTITION BY layer, table_name, check_name ORDER BY checked_at_utc DESC) = 1
) AS latest
GROUP BY layer, status"""

# ------------------------------------------------------------------------------------------ filter options


def values(column, options):
    rows = ", ".join("('" + o.replace("'", "''") + "')" for o in options)
    return f"SELECT * FROM (VALUES {rows}) AS v({column})"


OPT_REGION = f"""SELECT region FROM (
  SELECT '{ALL_REGIONS}' AS region, 0 AS s
  UNION ALL SELECT DISTINCT region_name, 1 FROM {G}.dim_city_municipality WHERE member_type = 'regular'
) AS r ORDER BY s, region"""
OPT_PROVINCE = f"""SELECT province FROM (
  SELECT '{ALL_PROVINCES}' AS province, 0 AS s
  UNION ALL SELECT DISTINCT COALESCE(province_name, 'Independent cities (no province)'), 1
  FROM {G}.dim_city_municipality
  WHERE member_type = 'regular' AND (:region = '{ALL_REGIONS}' OR region_name = :region)
) AS p ORDER BY s, province"""
OPT_LGU = f"""WITH {LGU}
SELECT lgu_option FROM (
  SELECT '{TOP_LGU}' AS lgu_option, 0 AS s
  UNION ALL SELECT lgu_label, 1 FROM lgu WHERE {GEO}
) AS o ORDER BY s, lgu_option"""
OPT_BARANGAY = f"""WITH {LGU},
{SEL}
SELECT barangay_option FROM (
  SELECT '{ALL_BARANGAYS}' AS barangay_option, 0 AS s
  UNION ALL SELECT DISTINCT b.barangay_name, 1 FROM {G}.dim_barangay AS b
  JOIN sel ON sel.city_mun_psgc_code = b.city_mun_psgc_code WHERE b.member_type = 'regular'
) AS o ORDER BY s, barangay_option"""
OPT_SCHOOL = f"""WITH {school_base()}
SELECT school_option FROM (
  SELECT '{FIRST_SCHOOL}' AS school_option, 0 AS s
  UNION ALL SELECT school_name || ' · ' || school_id, 1 FROM schools WHERE {BARANGAY} AND offers_level = 1
) AS o ORDER BY s, school_option"""

DEFAULTS = {"region": ALL_REGIONS, "province": ALL_PROVINCES, "lgu_type": ALL_TYPES, "tier": ALL_TIERS,
            "coverage": ALL_COVERAGE, "lgu": TOP_LGU, "barangay": ALL_BARANGAYS, "level": ALL_LEVELS,
            "school_status": ALL_SCHOOLS, "school": FIRST_SCHOOL, "measure": ALL_MEASURES, "scenario": SCENARIOS[0]}
OPTION_FIELDS = {"region": ("opt_region", "region"), "province": ("opt_province", "province"),
                 "lgu_type": ("opt_type", "lgu_type_option"), "tier": ("opt_tier", "tier_option"),
                 "coverage": ("opt_coverage", "coverage_option"), "lgu": ("opt_lgu", "lgu_option"),
                 "barangay": ("opt_barangay", "barangay_option"), "level": ("opt_level", "level_option"),
                 "school_status": ("opt_status", "status_option"), "school": ("opt_school", "school_option"),
                 "measure": ("opt_measure", "measure_option"), "scenario": ("opt_scenario", "scenario_option")}

GEO_P = ["region", "province", "lgu_type"]
OV_P = GEO_P + ["tier", "coverage"]
LGU_P = GEO_P + ["lgu"]
SCHOOL_P = LGU_P + ["barangay", "level", "school"]


def datasets(b):
    b.dataset("ov_lgu", "Overview: LGUs and boundaries", OV_LGU, OV_P)
    b.dataset("ov_kpi", "Overview: KPIs", OV_KPI, OV_P)
    b.dataset("ov_drivers", "Overview: what drives the tier", OV_DRIVERS, OV_P)
    b.dataset("ov_relative", "Overview: typical relative pressure", OV_RP, GEO_P)
    b.dataset("pr_card", "LGU Profile: selected LGU", PR_CARD, LGU_P)
    b.dataset("pr_local", "LGU Profile: barangay and school counts", PR_LOCAL_KPI, LGU_P)
    b.dataset("pr_insights", "LGU Profile: what stands out", PR_INSIGHTS, LGU_P)
    b.dataset("pr_why", "LGU Profile: why this tier", PR_WHY, LGU_P)
    b.dataset("pr_reliability", "LGU Profile: result reliability", PR_RELIABILITY, LGU_P)
    b.dataset("pr_teachers", "LGU Profile: teachers by level", PR_TEACHERS, LGU_P)
    b.dataset("pr_enrollment", "LGU Profile: enrollment by school year", PR_ENROLLMENT, LGU_P)
    b.dataset("pr_census", "LGU Profile: school-age population (context)", PR_CENSUS, LGU_P)
    b.dataset("pr_barangays", "LGU Profile: barangay access", PR_BARANGAYS, LGU_P + ["barangay"])
    b.dataset("pr_teaser", "LGU Profile: schools to follow up", PR_TEASER, LGU_P + ["barangay"])
    b.dataset("sa_school", "School Action: selected school", SA_SCHOOL, SCHOOL_P)
    b.dataset("sa_peers", "School Action: schools in the LGU", SA_PEERS, SCHOOL_P)
    b.dataset("sa_trend", "School Action: enrollment by level", SA_TREND, SCHOOL_P)
    b.dataset("sa_rooms", "School Action: rooms and teachers", SA_ROOMS, SCHOOL_P)
    b.dataset("sa_verify", "School Action: figures to verify", SA_VERIFY, SCHOOL_P)
    b.dataset("sa_list", "School Action: action list", SA_LIST, LGU_P + ["barangay", "level", "school_status"])
    b.dataset("freshness", "Data freshness", FRESHNESS)
    b.dataset("dm_kpi", "Data and Method: KPIs", DM_KPI, GEO_P)
    b.dataset("dm_refs", "Data and Method: same-type medians", DM_REFS, ["lgu_type"])
    b.dataset("dm_coverage", "Data and Method: coverage bands", DM_COVERAGE, GEO_P + ["measure"])
    b.dataset("dm_reasons", "Data and Method: data review reasons", DM_REASONS, GEO_P + ["measure"])
    b.dataset("dm_hold", "Data and Method: does the Critical list hold", DM_HOLD, ["lgu_type"])
    b.dataset("dm_transition", "Data and Method: published tier against a check", DM_TRANSITION, ["lgu_type", "scenario"])
    b.dataset("dm_overlap", "Data and Method: measure overlap", DM_OVERLAP, ["lgu_type"])
    b.dataset("dm_sources", "Data and Method: source years", DM_SOURCES)
    b.dataset("dm_checks", "Data and Method: latest data quality checks", DM_CHECKS)
    b.dataset("opt_region", "Filter: region", OPT_REGION)
    b.dataset("opt_province", "Filter: province", OPT_PROVINCE, ["region"])
    b.dataset("opt_type", "Filter: LGU type", values("lgu_type_option", [ALL_TYPES, "City", "Municipality"]))
    b.dataset("opt_tier", "Filter: priority tier", values("tier_option", [ALL_TIERS] + TIERS))
    b.dataset("opt_coverage", "Filter: coverage status", values("coverage_option", [ALL_COVERAGE, "Assessed", "Data review"]))
    b.dataset("opt_lgu", "Filter: city or municipality", OPT_LGU, GEO_P)
    b.dataset("opt_barangay", "Filter: barangay", OPT_BARANGAY, LGU_P)
    b.dataset("opt_level", "Filter: education level", values("level_option", [ALL_LEVELS, "ES", "JHS", "SHS"]))
    b.dataset("opt_status", "Filter: school status",
              values("status_option", [ALL_SCHOOLS, "Figures to check"] + STATUS_ORDER))
    b.dataset("opt_school", "Filter: school", OPT_SCHOOL, LGU_P + ["barangay", "level"])
    b.dataset("opt_measure", "Filter: measure", values("measure_option", [ALL_MEASURES] + MEASURES))
    b.dataset("opt_scenario", "Filter: validation check", values("scenario_option", SCENARIOS))


# ------------------------------------------------------------------------------------------ pages


def overview(b):
    p = Page("overview", "Overview")
    targets = ["ov_lgu", "ov_kpi", "ov_drivers"]
    p.row([(text(b, "# Which cities and municipalities should be reviewed first?\n",
                 "Each place is compared with others of the same type on learners per public school, per classroom and "
                 "per teacher (SY 2023-24). High means at or above the 90th percentile. Select a place on the map to "
                 "narrow the list."), 6),
           (param_filter(b, "tier", "Priority tier", targets), 3),
           (param_filter(b, "coverage", "Coverage status", targets,
                         "Assessed places have every measure at 90% coverage or more."), 3)], 2)
    p.row([(kpi(b, "freshness", "Data freshness", "freshness", None,
                desc="Latest successful pipeline run and the school years it covers"), 12)], 2)
    p.row([(kpi(b, "ov_kpi", "Priority LGUs", "priority_lgus", num(), desc="Critical or Elevated: high on 2 or 3 measures"), 3),
           (kpi(b, "ov_kpi", "Public learners in priority LGUs", "priority_learners", num(1, True),
                "{{ @formatted }} ({{share_txt}})", "SY 2023-24 · share of public learners in view",
                extra=("share_txt",)), 3),
           (kpi(b, "ov_kpi", "Critical LGUs", "critical_lgus", num(), desc="High on all three measures"), 3),
           (kpi(b, "ov_kpi", "LGUs needing data review", "data_review_lgus", num(),
                desc="Under 90% coverage on a measure: no tier"), 3)], 3)
    p.row([(choropleth(b, "ov_lgu", "Where the priority places are", "tier_level", "Tier",
                       [("lgu_label", "City or municipality"), ("tier", "Tier"), ("high_areas", "High on")],
                       "#B4B2A9", "#712B13",
                       "Tier scale: 4 Critical, 3 Elevated, 2 Targeted, 1 Monitor, 0 data review (grey). The 8 Special "
                       "Geographic Area municipalities have no boundary and are not drawn; a missing area is not a low priority."), 7),
           (bar(b, "ov_drivers", "What drives each tier", "high_areas", "High on", "count", "city_mun_psgc_code",
                "Cities and municipalities", color="tier", color_label="Tier", mappings=TIER_COLORS,
                color_order=TIERS[:3], order=DRIVER_ORDER,
                desc="Critical, Elevated and Targeted places by the measures that are high."), 5)], 9)
    p.row([(bar(b, "ov_relative", "How far above the typical place they are", "measure", "Measure", "max",
                "typical_relative_pressure", "Typical relative pressure", horizontal=False, color="lgu_group",
                color_label="Places", mappings=[{"value": RP_GROUPS[0], "color": "#712B13"},
                                                {"value": RP_GROUPS[1], "color": "#A9B4BF"}],
                order=MEASURES, color_order=RP_GROUPS, layout="group", fmt=num(2),
                desc="Relative pressure is a place's ratio divided by the median of its type, so 1.00 is the typical "
                     "place. The percentile decides who is high; this shows how far above the rest they are. Follows "
                     "Region, Province and LGU type only, so high places are always compared with the rest.",
                annotations=[ref_line("y", 1, "Typical place = 1.00")]), 12)], 6)
    p.row([(table(b, "ov_lgu", "Priority list", [
        ("rank_in_view", "Rank", None), ("lgu_label", "City or municipality", None), ("lgu_type_label", "Type", None),
        ("tier", "Tier", None), ("high_areas", "High on", None), ("ap1_pct", "Schools pct", num()),
        ("ap2_pct", "Classrooms pct", num()), ("ap3_pct", "Teachers pct", num()),
        ("ap3_highest_level", "Teacher level used", None), ("affected_learners", "Public learners", num()),
        ("lowest_coverage_pct", "Lowest coverage %", num()), ("stability", "Stability", None),
        ("data_review_reason", "Data review reason", None)],
        "Ranked by tier, then public learners, then the lowest of the three percentiles (D-057). pct is the "
        "within-type percentile (90 or more is high). Lowest coverage is the least complete of the three measures; under 90 "
        "means data review, not low pressure. Stable means Critical within type and nationally. Download "
        "from the table menu."), 12)], 10)
    p.row([(text(b, "**Next:** choose a place in *City or municipality* at the top, then open **LGU Profile**. "
                 "A tier is relative pressure compared with similar places, not a count of schools, classrooms or "
                 "teachers to add."), 12)], 1)
    return p


def lgu_profile(b):
    p = Page("lgu_profile", "LGU Profile")
    p.row([(text(b, "# Why is this place a priority, and where should the board look?\n",
                 "Choose the place in *City or municipality* and, for the barangay and school sections, a *Barangay* at "
                 "the top. Figures are SY 2023-24 unless a title says otherwise."), 12)], 2)
    p.row([(kpi(b, "pr_card", "Selected city or municipality", "city_mun_name", None,
                desc="Change it in City or municipality at the top"), 12)], 2)
    p.row([(kpi(b, "pr_card", "Place details", "details", None,
                desc="Type · province (or region) · tier · national rank · Stable if Critical both ways"), 12)], 2)
    p.row([(kpi(b, "pr_card", "High-pressure measures", "high_count_label", None,
                desc="At or above the 90th percentile of its type"), 3),
           (kpi(b, "pr_card", "Public learners", "affected_learners", num(), desc="SY 2023-24, complete school counts"), 3),
           (kpi(b, "pr_local", "Barangays without a public elementary school", "barangays_without_public_es", num(),
                "{{bound_prefix}}{{ @formatted }} of {{regular_barangays}}", "Matched public schools · a screening count",
                extra=("bound_prefix", "regular_barangays")), 3),
           (kpi(b, "pr_local", "Schools with figures to verify", "schools_to_check", num(),
                "{{ @formatted }} of {{schools}}", "Unusual, missing or zero · see School Action", extra=("schools",)), 3)], 3)
    p.row([(table(b, "pr_insights", "What stands out", [("insight", "Finding", None)],
                  "Up to four facts, each from a fixed rule over the same tables as the charts, and left out when its "
                  "data is incomplete. They describe the place; they do not explain why."), 12)], 4)
    p.row([(bar(b, "pr_why", "Why this tier", "measure", "Measure", "max", "relative_pressure",
                "Relative pressure (1.00 = typical place of its type)", color="status", color_label="Result",
                mappings=[{"value": "High", "color": "#712B13"}, {"value": "Not high", "color": "#A9B4BF"},
                          {"value": "Not assessed", "color": "#8A96A3"}],
                order=MEASURES, color_order=["High", "Not high", "Not assessed"], fmt=num(2),
                desc="High comes from the percentile; the bar shows how far the place is from the typical one.",
                annotations=[ref_line("x", 1, "Typical place")]), 6),
           (table(b, "pr_reliability", "How reliable the result is", [
               ("measure", "Measure", None), ("value", "This place", None), ("typical", "Typical place", None),
               ("percentile", "Percentile", None), ("coverage", "Coverage", None), ("assessed", "Status", None),
               ("unusual_schools", "Unusual figures", None)],
               "Coverage is the share of learners reported (schools for AP1, the lowest offered level for AP3); below 90% "
               "means not assessed. Schools above an outlier fence stay in every total; the last row "
               "shows whether the tier holds without them."), 6)], 7)
    p.row([(bar(b, "pr_teachers", "Teachers by level, and who funds them", "level_label", "Level", "sum", "teachers",
                "Teachers", color="funding", color_label="Funding", layout="stack",
                mappings=[{"value": "DepEd-funded", "color": "#5B6B7A"},
                          {"value": "Locally funded (SEF, LGU, other)", "color": "#C9A227"}],
                desc="Public-school teachers, SY 2023-24. Learners per teacher in each label is the AP3 ratio for the level; "
                     "locally funded positions are included in it."), 12)], 5)
    p.row([(line(b, "pr_enrollment", "Enrollment each school year · context only", "school_year_label", "School year",
                 "sum", "learners", "Learners", num(1, True), color="scope", color_label="Scope",
                 mappings=[{"value": "All sectors", "color": "#5B6B7A"}, {"value": "Public schools", "color": "#C9A227"}],
                 x_order=SCHOOL_YEARS,
                 desc="All sectors includes private and state or local college schools. Enrollment does not set the tier."), 6),
           (bar(b, "pr_census", "Children aged 5-17 and enrolled learners · context only", "period", "Census · school year",
                "sum", "people", "People", horizontal=False, color="series", color_label="Series", layout="group",
                mappings=[{"value": CENSUS_SERIES[0], "color": "#5B6B7A"}, {"value": CENSUS_SERIES[1], "color": "#A9B4BF"},
                          {"value": CENSUS_SERIES[2], "color": "#C9A227"}],
                color_order=CENSUS_SERIES, fmt=num(1, True),
                desc="Children are counted where they live and learners where their school is, so the difference is not "
                     "the number of children out of school. Below zero usually means local schools also serve nearby places."), 6)], 7)
    p.row([(table(b, "pr_barangays", "Barangay access", [
        ("barangay_name", "Barangay", None), ("urban_rural", "Urban or rural", None),
        ("public_schools", "Public schools", num()), ("public_es", "Public elementary", None),
        ("learners", "Public learners", num())],
        "Every regular PSGC barangay, those with no matched public elementary school first. A screening view, not a "
        "barangay priority ranking."), 12)], 8)
    p.row([(table(b, "pr_teaser", "Schools to follow up first", [
        ("school_name", "School", None), ("barangay_name", "Barangay", None), ("learners_per_room", "Learners per classroom", num(1)),
        ("status", "Status", None), ("reasons", "Why", None)],
        "The first five schools in the School Action list: figures to verify first, then the most crowded. Open "
        "School Action for every school and its details."), 12)], 5)
    return p


def school_action(b):
    p = Page("school_action", "School Action")
    targets = ["sa_school", "sa_peers", "sa_trend", "sa_rooms", "sa_verify", "sa_list", "opt_school"]
    p.row([(text(b, "# Which schools should we check, and why?\n",
                 "Public schools in the selected city or municipality, SY 2023-24. Pick a school to see its figures."), 6),
           (param_filter(b, "level", "Education level", targets), 2),
           (param_filter(b, "school_status", "School status", ["sa_list"]), 2),
           (param_filter(b, "school", "School", targets, "Defaults to the first school to check."), 2)], 2)
    p.row([(kpi(b, "sa_school", "Selected school", "school_name", None,
                desc="Change it in School above"), 12)], 2)
    p.row([(kpi(b, "sa_school", "School details", "details", None,
                desc="School ID · barangay · main or annex · levels · learners, SY 2023-24 · figures to check"), 12)], 2)
    p.row([(kpi(b, "sa_school", "Learners per reported room", "learners_per_room", num(1),
                desc="All levels · rooms include labs"), 3),
           (kpi(b, "sa_school", "Learners per teacher", "teacher_ratio", num(1), desc="At the education level chosen above"), 3),
           (kpi(b, "sa_school", "Enrollment change", "enrollment_change", pct(1), desc="SY 2020-21 to 2025-26, if complete"), 3),
           (kpi(b, "sa_school", "Temporary and makeshift rooms", "temporary_or_makeshift_rooms", num(),
                desc="SY 2023-24"), 3)], 3)
    p.row([(scatter(b, "sa_peers", "This school among schools in the same place", "learners_per_room",
                    "Learners per classroom", "teacher_ratio", "Learners per teacher", "series", "School",
                    STATUS_COLORS, [c["value"] for c in STATUS_COLORS], "learners", "Learners", "school_name",
                    "Each dot is a public school offering the chosen level. A school-level screen, not the LGU priority "
                    "rule; schools with no rooms or teachers reported cannot be placed."), 7),
           (table(b, "sa_verify", "Figures to verify", [("status", "Status", None), ("reason", "Exact reason", None),
                                                         ("next_step", "Next step", None)],
                  "A flag means verify, not incorrect. Flagged schools stay in every total."), 5)], 8)
    p.row([(line(b, "sa_trend", "Learners each school year", "school_year_label", "School year", "sum",
                 "learners", "Learners", num(), color="series", color_label="Series", x_order=SCHOOL_YEARS,
                 mappings=[{"value": "All levels", "color": "#712B13"}, {"value": "Elementary", "color": "#A9B4BF"},
                           {"value": "Junior high", "color": "#5B6B7A"}, {"value": "Senior high", "color": "#C9A227"}],
                 color_order=["All levels", "Elementary", "Junior high", "Senior high"],
                 desc="The school's total first; each level is added when the school offers more than one."), 6),
           (table(b, "sa_rooms", "Rooms and teachers", [
               ("level", "Level", None), ("learners", "Learners", num()), ("teachers", "Teachers", num()),
               ("learners_per_teacher", "Per teacher", num(1)), ("classrooms", "Classrooms", num()),
               ("temporary_rooms", "Temporary", num()), ("makeshift_rooms", "Makeshift", num())],
               "SY 2023-24. Classrooms are reported for the whole school, not by level."), 6)], 7)
    p.row([(table(b, "sa_list", "School action list", [
        ("list_order", "#", None), ("school_name", "School", None), ("barangay_name", "Barangay", None),
        ("levels_offered", "Levels", None), ("learners", "Learners", num()), ("learners_per_room", "Per classroom", num(1)),
        ("teacher_ratio", "Per teacher", num(1)), ("enrollment_change", "Enrollment change", pct(1)),
        ("status", "Status", None), ("reasons", "Reason", None)],
        "Figures to verify first, then the most crowded. The download adds school ID, main or annex, temporary or "
        "makeshift rooms and locally funded teachers."), 12)], 10)
    p.row([(text(b, "Confirm flagged figures with the Schools Division Office before using them for planning. The "
                 "dashboard identifies pressure and data requiring review; it does not prescribe how many classrooms, "
                 "teachers, or schools to add."), 12)], 1)
    return p


def data_and_method(b):
    p = Page("data_and_method", "Data and Method")
    p.row([(text(b, "# Can we rely on these results, and how were they produced?\n",
                 "Start with the summary and the rule; the checks behind them follow."), 6),
           (param_filter(b, "measure", "Measure", ["dm_coverage", "dm_reasons"]), 3),
           (param_filter(b, "scenario", "Validation check", ["dm_transition"]), 3)], 2)
    p.row([(kpi(b, "freshness", "Data freshness", "freshness", None,
                desc="Latest successful pipeline run and the school years it covers"), 12)], 2)
    p.row([(kpi(b, "dm_kpi", "Assessed LGUs", "assessed", num(), "{{ @formatted }} of {{lgus}}",
                "Every measure at 90% coverage or more", extra=("lgus",)), 3),
           (kpi(b, "dm_kpi", "LGUs requiring data review", "data_review", num(), desc="A measure below the coverage gate"), 3),
           (kpi(b, "dm_kpi", "Stable Critical results", "stable", num(), "{{ @formatted }} of {{critical}}",
                "Critical within type and nationally", extra=("critical",)), 3),
           (kpi(b, "dm_kpi", "Tier changes without flagged schools", "outlier_changes", num(),
                desc="Published tiers keep the flagged schools"), 3)], 3)
    p.row([(text(b, "## How the priority is determined\n\n",
                 "1. **Three measures, SY 2023-24:** learners per public school (AP1), learners per reported instructional "
                 "room (AP2) and learners per teacher by level (AP3).\n",
                 "2. **Coverage gate:** a measure counts only when at least 90% of schools (AP1) or learners (AP2, each AP3 "
                 "level) are reported. Otherwise the place is **Data review**.\n",
                 "3. **High:** at or above the 90th percentile among places of the same type (cities with cities, "
                 "municipalities with municipalities). AP3 uses the level with the highest percentile.\n",
                 "4. **Tier:** Critical (3 high), Elevated (2), Targeted (1), Monitor (0). A count, not a weighted score.\n",
                 "5. **Relative pressure** (ratio ÷ the median place of the same type) shows how far above the rest a "
                 "place is. It never sets the tier.\n",
                 "6. **Context only:** enrollment trends, school-age population and poverty never change a tier."), 7),
           (table(b, "dm_refs", "Typical place of each type", [
               ("measure", "Measure", None), ("lgu_type_label", "Type", None),
               ("typical_value", "Median", num(1)), ("lgus", "Places compared", num())],
               "The middle place among the assessed places of each type, SY 2023-24. Relative pressure divides by it. "
               "Teachers use the median of the level that sets each place's AP3, so it is shown per place in LGU "
               "Profile. Follows LGU type only."), 5)], 8)
    p.row([(bar(b, "dm_coverage", "Coverage by measure", "measure", "Measure", "sum", "lgus", "Cities and municipalities",
                color="coverage_band", color_label="Coverage", layout="stack", color_order=COVERAGE_BANDS,
                order=COVERAGE_MEASURES, desc="Below 90% a measure is not assessed and the place goes to data review."), 6),
           (bar(b, "dm_reasons", "Why places are not assessed", "reason", "Reason", "sum", "lgus", "Cities and municipalities",
                color="measure", color_label="Measure", color_order=MEASURES, layout="stack", sort_by="value",
                desc="A place can be counted under more than one measure."), 6)], 7)
    p.row([(bar(b, "dm_hold", "Does the Critical list hold?", "check_label", "Check", "sum", "lgus",
                "Critical places", color="series", color_label="Count", layout="group", color_order=HOLD_SERIES,
                sort_by="alphabetical",
                desc="D-057's checks. The rule is revisited if fewer than 80% stay Critical and at least 3 leave. "
                     "None of these change the published tier. Follows LGU type only."), 6),
           (heatmap(b, "dm_transition", "Published tier against the chosen check", "check_tier", "Tier under the check",
                    TIERS, "published_tier", "Published tier", TIERS, "sum", "lgus", "Places",
                    "Pick the check with Validation check above. The diagonal is agreement."), 6)], 7)
    p.row([(table(b, "dm_overlap", "Do the three measures repeat one signal?", [
        ("pair", "Measures", None), ("lgu_type_label", "Type", None), ("rank_agreement", "Rank agreement", num(2)),
        ("shared_high", "Also high", pct(0)), ("lgus_compared", "Places", num())],
        "Rank agreement is the Spearman correlation of the two within-type percentiles. Also high is the share of places "
        "high on the first measure that are also high on the second (about 10% if unrelated). Some overlap is expected "
        "because the measures share learners."), 6),
           (heatmap(b, "dm_sources", "Which school years each source covers", "school_year", "School year", None,
                    "source", "Source", None, "max", "has_data", "Has data (1 = yes)",
                    "Classrooms and teachers are available only for SY 2023-24, the year every tier uses."), 6)], 6)
    p.row([(bar(b, "dm_checks", "Latest automatic data checks", "layer", "Processing step", "sum", "checks", "Checks",
                horizontal=False, color="status", color_label="Result",
                mappings=[{"value": "PASS", "color": "#5B6B7A"}, {"value": "WARN", "color": "#E3A008"},
                          {"value": "FAIL", "color": "#A32D2D"}],
                order=["control", "bronze", "silver", "integration", "gold", "analytics"]), 6),
           (text(b, "## What this dashboard cannot tell you\n\n",
                 "- **How many resources to add.** A tier is relative pressure, not a shortage count.\n",
                 "- **Why a place is under pressure.** Enrollment, population and poverty are context only.\n",
                 "- **How far learners travel.** Enrollment is counted at the school.\n",
                 "- **Whether a reported value is correct.** Unusual figures are flagged for checking, never removed.\n",
                 "- **Classroom or teacher trends.** Only SY 2023-24 has comparable classroom and teacher data."), 6)], 6)
    return p


def build():
    b = Builder(DEFAULTS, OPTION_FIELDS)
    datasets(b)
    pages = [overview(b), lgu_profile(b), school_action(b), data_and_method(b)]
    global_page = Page("global_filters", "Global filters")
    all_targets = [d["name"] for d in b.datasets]
    for i, (keyword, title, desc) in enumerate([
            ("region", "Region", None), ("province", "Province", None), ("lgu_type", "LGU type", None),
            ("lgu", "City or municipality", "Used by LGU Profile and School Action. Defaults to the top place in the filters."),
            ("barangay", "Barangay", "Used by the barangay and school sections of LGU Profile and by School Action.")]):
        global_page.items.append({"widget": param_filter(b, keyword, title, all_targets, desc),
                                  "position": {"x": 0, "y": i * 2, "width": 12, "height": 2}})
    return {
        "datasets": b.datasets,
        "pages": [page.json() for page in pages] + [global_page.json("PAGE_TYPE_GLOBAL_FILTERS")],
        "uiSettings": {"theme": {
            "canvasBackgroundColor": {"light": "#F6F7F8", "dark": "#151B20"},
            "widgetBackgroundColor": {"light": "#FFFFFF", "dark": "#1E262C"},
            "widgetBorderColor": {"light": "#FFFFFF", "dark": "#1E262C"},
            "fontColor": {"light": "#14212B", "dark": "#E8ECF0"},
            "selectionColor": {"light": "#712B13", "dark": "#F0997B"},
            "visualizationColors": ["#712B13", "#5B6B7A", "#C9A227", "#D85A30", "#A9B4BF", "#8A96A3", "#2F6F8F"],
            "widgetHeaderAlignment": "LEFT", "widgetCornerRadius": 10}},
    }


def render():
    return json.dumps(build(), indent=2) + "\n"


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else OUTPUT
    target.write_text(render(), encoding="utf-8")
    print(f"wrote {target}")
