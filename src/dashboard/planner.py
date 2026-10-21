"""The ReachED LGU planner dashboard: Overview, LGU Profile, School Action, Data and Method.

Run `python -m src.dashboard.planner` to rewrite dashboards/reached_planner.lvdash.json from this file.

The classroom review queue, its rank, the school screen, the AP3 reference statuses and the coverage gate come from
the Analytics tables (D-060); the dashboard only filters, labels and arranges them. Global filters (Region, Province,
LGU type) and the selection filters (City or municipality, Barangay) are query parameters applied after those values
are read, so a filter narrows what is shown and never changes a status, reference or rank. School-level views read
Gold and apply the same illustrative 50-learner screen to each school's own reported rooms.
"""
import json
import sys
from pathlib import Path

from src.dashboard.widgets import (Builder, Page, bar, chart, choropleth, heatmap, kpi, line, note, num, param_filter,
                                   pct, quant, ref_line, scatter, table, text)

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "dashboards" / "reached_planner.lvdash.json"

A = "edu_access.`06-analytics`"
G = "edu_access.`05-gold`"
ALL_REGIONS, ALL_PROVINCES, ALL_TYPES = "All regions", "All provinces", "All LGU types"
ALL_QUEUE, ALL_COVERAGE = "All review statuses", "All LGUs"
TOP_LGU = "(Top LGU in the filters)"
ALL_BARANGAYS = "All barangays"
ALL_LEVELS, ALL_SCHOOLS, FIRST_SCHOOL = "All levels", "All schools", "(First school to check)"
ALL_MEASURES = "All measures"
SCHOOL_YEARS = ["SY 2020-21", "SY 2021-22", "SY 2022-23", "SY 2023-24", "SY 2024-25", "SY 2025-26"]

# D-060: lgu_priority_matrix.classroom_priority_group, in plain words, most urgent first
QUEUE = ["Classroom review queue", "No reported congestion", "Data review"]
QUEUE_COLORS = [{"value": QUEUE[0], "color": "#712B13"}, {"value": QUEUE[1], "color": "#D9DEE3"},
                {"value": QUEUE[2], "color": "#8A96A3"}]
SCREEN = 50  # the AP2 illustrative reported-room screen, config/analytics_benchmarks.json
MEASURES = ["Schools (AP1)", "Classrooms (AP2)", "Teachers (AP3)"]
TEACHER_STATUS = ["Above a reference", "At or below the references", "Not fully assessed"]
TEACHER_COLORS = [{"value": TEACHER_STATUS[0], "color": "#C9A227"}, {"value": TEACHER_STATUS[1], "color": "#A9B4BF"},
                  {"value": TEACHER_STATUS[2], "color": "#8A96A3"}]
STATUS_ORDER = [f"At or above {SCREEN} per reported room", "Missing report", "Zero rooms or teachers", "No figures to check"]
KPI_STYLE = {"fontStyle": "normal", "fontWeight": 800}  # the view's four KPIs; Overview's are 700
TITLE_STYLE = {"fontSize": 60, "fontStyle": "normal", "fontWeight": 800}  # the selected place or school
DETAIL_STYLE = {"fontSize": 16, "fontStyle": "normal", "fontWeight": 400}  # the line of details under it
SENTENCE_STYLE = {"fontStyle": "normal", "fontSize": 14, "fontWeight": 400}  # findings and answers on LGU Profile
KPI_CARD = {"fontColor": {"light": "#FFFFFF"}}  # every view's four KPI cards
LEGEND_BOTTOM = {"position": "bottom"}
FINDINGS = ["Classroom screen", "Reliability", "Enrollment context", "Barangay follow-up"]  # pr_insights rules 1 to 4
ANSWERS = [("Answer: AP1 schools", "AP1 · Enough public schools?", "Learners per public school · context only"),
           ("Answer: AP2 classrooms", "AP2 · Are classrooms crowded?",
            f"Schools at or above {SCREEN} learners per reported room"),
           ("Answer: AP3 teachers", "AP3 · Are there enough teachers?",
            "Learners per teacher by level · compared with the references, never ranked"),
           ("Answer: AP4 enrollment", "AP4 · Is enrollment growing?",
            "All sectors, SY 2020-21 to 2025-26 · context only")]
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
QUEUE_SORT = ("CASE {c} WHEN 'reported_congestion_screen' THEN 0 WHEN 'no_reported_congestion_screen' THEN 1 "
              "ELSE 2 END")


def r1(expr):
    return f"COALESCE(format_number({expr}, 1), 'n/a')"


def r2(expr):
    return f"COALESCE(CAST(ROUND({expr}, 2) AS STRING), 'n/a')"


def cov(expr):
    return f"COALESCE(format_number({expr}, 0) || '%', 'n/a')"


def r0(expr):
    return f"COALESCE(format_number({expr}, 0), 'n/a')"


# Every LGU's published D-060 row with plain-language labels.
PRI_CTE = f"""pri AS (
  SELECT l.lgu_label, l.province_label, l.lgu_type_label, l.type_plural, m.*,
         CASE m.classroom_priority_group WHEN 'reported_congestion_screen' THEN '{QUEUE[0]}'
              WHEN 'no_reported_congestion_screen' THEN '{QUEUE[1]}' ELSE '{QUEUE[2]}' END AS queue_status,
         {QUEUE_SORT.format(c='m.classroom_priority_group')} AS queue_sort,
         ROW_NUMBER() OVER (ORDER BY {QUEUE_SORT.format(c='m.classroom_priority_group')}, m.classroom_priority_rank NULLS LAST,
                                     m.ap2_affected_learners DESC, m.city_mun_psgc_code) AS national_order,
         CASE WHEN m.classroom_priority_group = 'data_review'
              THEN 'classrooms: ' || COALESCE(a2.not_assessed_reason, 'learner coverage below 90%') END AS data_review_reason,
         -- AP3's published status: a signal at one level stands even if another offered level is short of coverage
         CASE a3.benchmark_status WHEN 'pressure signal identified' THEN '{TEACHER_STATUS[0]}'
              WHEN 'no pressure signal identified' THEN '{TEACHER_STATUS[1]}'
              ELSE '{TEACHER_STATUS[2]}' END AS teacher_status,
         concat_ws(', ', CASE WHEN a3.es_benchmark_status LIKE 'above%' THEN 'ES' END,
                         CASE WHEN a3.jhs_benchmark_status LIKE 'above%' THEN 'JHS' END,
                         CASE WHEN a3.shs_benchmark_status LIKE 'above%' THEN 'SHS' END) AS teacher_levels_above,
         a1.active_public_school_count, a1.public_school_enrollment,
         a2.congested_school_count, a2.ratio_school_count, a2.missing_room_school_count, a2.zero_room_school_count,
         a2.reported_instructional_classrooms, a2.eligible_learners,
         a3.es_offered_school_count, a3.jhs_offered_school_count, a3.shs_offered_school_count,
         a3.es_teacher_count, a3.jhs_teacher_count, a3.shs_teacher_count,
         a3.es_benchmark_max_learners_per_teacher, a3.jhs_benchmark_max_learners_per_teacher,
         a3.shs_benchmark_max_learners_per_teacher,
         COALESCE(a3.es_zero_teacher_annex_school_count, 0) + COALESCE(a3.jhs_zero_teacher_annex_school_count, 0)
           + COALESCE(a3.shs_zero_teacher_annex_school_count, 0) AS zero_teacher_annex_schools,
         NULLIF(LEAST(CASE WHEN a3.es_offered_school_count > 0 THEN COALESCE(a3.es_learner_coverage_pct, 0) ELSE 999 END,
                      CASE WHEN a3.jhs_offered_school_count > 0 THEN COALESCE(a3.jhs_learner_coverage_pct, 0) ELSE 999 END,
                      CASE WHEN a3.shs_offered_school_count > 0 THEN COALESCE(a3.shs_learner_coverage_pct, 0) ELSE 999 END),
                999) AS ap3_coverage_pct
  FROM {A}.lgu_priority_matrix AS m
  JOIN lgu AS l ON l.city_mun_psgc_code = m.city_mun_psgc_code
  LEFT JOIN {A}.ap1_school_provision AS a1 ON a1.city_mun_psgc_code = m.city_mun_psgc_code
  LEFT JOIN {A}.ap2_classroom_pressure AS a2 ON a2.city_mun_psgc_code = m.city_mun_psgc_code
  LEFT JOIN {A}.ap3_teacher_pressure AS a3 ON a3.city_mun_psgc_code = m.city_mun_psgc_code
)"""
PRI = f"""{LGU},
{PRI_CTE}"""

OV_FILTER = (f"{GEO} AND (:queue = '{ALL_QUEUE}' OR queue_status = :queue)"
             f" AND (:coverage = '{ALL_COVERAGE}' OR (:coverage = 'Assessed' AND queue_status <> '{QUEUE[2]}')"
             f" OR (:coverage = 'Data review' AND queue_status = '{QUEUE[2]}'))")

# ============================================================ 1 Overview
GEOM = "st_setsrid(st_simplify(st_geomfromgeojson(h.geometry), 0.003), 4326)"
OV_LGU = f"""SELECT b.*,
       CASE WHEN instr(b.region_name, '(') > 0
            THEN substring(b.region_name, instr(b.region_name, '(') + 1,
                           instr(b.region_name, ')') - instr(b.region_name, '(') - 1)
            ELSE b.region_name END AS region_short,
       {GEOM} AS boundary
FROM (
  WITH {PRI}
  -- the list keeps the D-060 order: the review queue by its rank, then the rest
  SELECT ROW_NUMBER() OVER (ORDER BY queue_sort, classroom_priority_rank NULLS LAST, ap2_affected_learners DESC,
                                     city_mun_psgc_code) AS rank_in_view,
         classroom_priority_rank, city_mun_psgc_code, lgu_label, lgu_type_label, province_label, region_name,
         queue_status, congested_school_count, ap2_affected_learners, ap2_affected_learner_share_pct,
         ap2_learners_per_reported_room, teacher_status, teacher_levels_above, ap1_learners_per_public_school,
         ap4_enrollment_trend, data_review_reason, public_school_enrollment,
         NULLIF(LEAST(COALESCE(ap1_coverage_pct, 0), COALESCE(ap2_learner_coverage_pct, 0), COALESCE(ap3_coverage_pct, 999)), 999)
           AS lowest_coverage_pct
  FROM pri
  WHERE {OV_FILTER}
) AS b
LEFT JOIN edu_access.`04-integration`.hdx_adm3_psgc_map AS m
  ON m.psgc_code = b.city_mun_psgc_code AND m.match_status = 'matched'
LEFT JOIN edu_access.`03-silver`.hdx_adm3_clean AS h ON h.adm3_pcode = m.adm3_pcode
ORDER BY b.rank_in_view"""

OV_KPI = f"""WITH {PRI}
SELECT COUNT(*) AS lgus,
       COUNT_IF(queue_status = '{QUEUE[0]}') AS queue_lgus,
       COUNT_IF(queue_status = '{QUEUE[2]}') AS data_review_lgus,
       SUM(COALESCE(congested_school_count, 0)) AS screened_schools,
       SUM(COALESCE(ap2_affected_learners, 0)) AS screened_learners,
       COALESCE(CAST(ROUND(100.0 * SUM(COALESCE(ap2_affected_learners, 0))
         / NULLIF(SUM(public_school_enrollment), 0), 1) AS STRING) || '%', 'n/a') AS share_txt
FROM pri
WHERE {OV_FILTER}"""

# AP3 beside the queue: whether a level is above its reference (context; never ranks or moves a place).
OV_TEACHERS = f"""WITH {PRI}
SELECT city_mun_psgc_code, queue_status, teacher_status
FROM pri
WHERE {OV_FILTER}"""

DIRECTIONS = ["Increased", "No change", "Decreased", "Incomplete trend"]
DIRECTION_COLORS = [{"value": "Increased", "color": "#5B6B7A"}, {"value": "No change", "color": "#D9DEE3"},
                    {"value": "Decreased", "color": "#A32D2D"}, {"value": "Incomplete trend", "color": "#C9A227"}]
AP4_INCOMPLETE = f"""ap4_complete AS (
  SELECT city_mun_psgc_code, MAX(CASE WHEN schools_incomplete > 0 THEN 1 ELSE 0 END) AS incomplete,
         MIN(CASE WHEN is_2020_2024_geography_comparable THEN 1 ELSE 0 END) AS comparable
  FROM {A}.ap4_enrollment_trend WHERE member_type = 'regular' GROUP BY city_mun_psgc_code
)"""
# AP4 beside the queue: whether enrollment went up from SY 2020-21 to 2025-26 (context; never moves a place).
OV_DEMAND = f"""WITH {PRI},
{AP4_INCOMPLETE},
f AS (
  SELECT pri.*, CASE WHEN c.incomplete = 1 THEN '{DIRECTIONS[3]}' WHEN pri.ap4_enrollment_trend = 'increasing' THEN '{DIRECTIONS[0]}'
                     WHEN pri.ap4_enrollment_trend = 'decreasing' THEN '{DIRECTIONS[2]}' ELSE '{DIRECTIONS[1]}' END AS enrollment_direction
  FROM pri LEFT JOIN ap4_complete AS c USING (city_mun_psgc_code)
)
SELECT city_mun_psgc_code, queue_status, enrollment_direction FROM f WHERE {OV_FILTER}"""

# ============================================================ 2 LGU Profile
SEL = f"""sel AS (
  SELECT l.city_mun_psgc_code, l.lgu_label
  FROM lgu AS l
  JOIN {A}.lgu_priority_matrix AS p ON p.city_mun_psgc_code = l.city_mun_psgc_code
  WHERE {GEO_L}
  ORDER BY CASE WHEN l.lgu_label = :lgu THEN 0 ELSE 1 END, {QUEUE_SORT.format(c='p.classroom_priority_group')},
           p.classroom_priority_rank NULLS LAST, p.ap2_affected_learners DESC, l.city_mun_psgc_code
  LIMIT 1
)"""

PR_CARD = f"""WITH {PRI},
{SEL}
SELECT p.lgu_label, p.city_mun_name, p.queue_status,
       p.lgu_type_label || ' · '
         || CASE WHEN p.province_label = 'Independent cities (no province)' THEN p.region_name ELSE p.province_label END
         || ' · ' || p.queue_status
         || CASE WHEN p.classroom_priority_rank IS NOT NULL
                 THEN ' · rank ' || format_number(p.classroom_priority_rank, 0) || ' of '
                      || format_number((SELECT COUNT(*) FROM {A}.lgu_priority_matrix
                                        WHERE classroom_priority_group = 'reported_congestion_screen'), 0)
                 ELSE '' END
         || CASE WHEN :lgu <> '{TOP_LGU}' AND p.lgu_label <> :lgu THEN ' · top place in the filters' ELSE '' END AS details,
       p.active_public_school_count AS public_schools, p.reported_instructional_classrooms AS classrooms,
       COALESCE(p.es_teacher_count, 0) + COALESCE(p.jhs_teacher_count, 0) + COALESCE(p.shs_teacher_count, 0) AS teachers,
       p.public_school_enrollment AS public_learners
FROM pri AS p
JOIN sel ON sel.city_mun_psgc_code = p.city_mun_psgc_code"""

# The evidence behind the place's status: each measure's value beside the published reference, if it has one.
PR_EVIDENCE = f"""WITH {PRI},
{SEL},
p AS (SELECT pri.* FROM pri JOIN sel USING (city_mun_psgc_code))
SELECT 1 AS ord, '{MEASURES[1]} · school screen' AS measure,
       format_number(COALESCE(congested_school_count, 0), 0) || ' of ' || format_number(COALESCE(ratio_school_count, 0), 0)
         || ' schools, ' || format_number(COALESCE(ap2_affected_learners, 0), 0) || ' learners' AS this_place,
       'At or above {SCREEN} learners per reported room, school by school' AS reference,
       queue_status AS status
FROM p
UNION ALL SELECT 2, '{MEASURES[1]} · pooled ratio', {r1('ap2_learners_per_reported_room')} || ' learners per reported room',
       'Context: the school screen decides the queue', CASE WHEN ap2_assessed THEN 'Assessed' ELSE 'Not assessed' END FROM p
UNION ALL SELECT 3, 'Teachers, Elementary (AP3)', {r1('ap3_es_learners_per_teacher')} || ' learners per teacher',
       'Above ' || {r1('es_benchmark_max_learners_per_teacher')} || ' (historical study reference)',
       CASE WHEN es_offered_school_count = 0 THEN 'Not offered' WHEN ap3_es_learners_per_teacher IS NULL THEN 'Not assessed'
            WHEN ap3_es_learners_per_teacher > es_benchmark_max_learners_per_teacher THEN 'Above' ELSE 'At or below' END FROM p
UNION ALL SELECT 4, 'Teachers, Junior high (AP3)', {r1('ap3_jhs_learners_per_teacher')} || ' learners per teacher',
       'Above ' || {r1('jhs_benchmark_max_learners_per_teacher')} || ' (derived deployment comparison)',
       CASE WHEN jhs_offered_school_count = 0 THEN 'Not offered' WHEN ap3_jhs_learners_per_teacher IS NULL THEN 'Not assessed'
            WHEN ap3_jhs_learners_per_teacher > jhs_benchmark_max_learners_per_teacher THEN 'Above' ELSE 'At or below' END FROM p
UNION ALL SELECT 5, 'Teachers, Senior high (AP3)', {r1('ap3_shs_learners_per_teacher')} || ' learners per teacher',
       'Above ' || {r1('shs_benchmark_max_learners_per_teacher')} || ' (derived deployment comparison)',
       CASE WHEN shs_offered_school_count = 0 THEN 'Not offered' WHEN ap3_shs_learners_per_teacher IS NULL THEN 'Not assessed'
            WHEN ap3_shs_learners_per_teacher > shs_benchmark_max_learners_per_teacher THEN 'Above' ELSE 'At or below' END FROM p
UNION ALL SELECT 6, '{MEASURES[0]}', {r0('ap1_learners_per_public_school')} || ' learners per public school',
       'Context only: no published reference', CASE WHEN ap1_assessed THEN 'Assessed' ELSE 'Not assessed' END FROM p"""

PR_RELIABILITY = f"""WITH {PRI},
{SEL},
p AS (SELECT pri.* FROM pri JOIN sel USING (city_mun_psgc_code))
SELECT 1 AS ord, '{MEASURES[0]}' AS measure, {cov('ap1_coverage_pct')} AS coverage,
       CASE WHEN ap1_assessed THEN 'Assessed' ELSE 'Not assessed' END AS assessed,
       '' AS unusual_schools
FROM p
UNION ALL SELECT 2, '{MEASURES[1]}', {cov('ap2_learner_coverage_pct')},
       CASE WHEN ap2_assessed THEN 'Assessed' ELSE 'Not assessed' END,
       format_number(COALESCE(missing_room_school_count, 0), 0) || ' with no room count, '
         || format_number(COALESCE(zero_room_school_count, 0), 0) || ' with 0 rooms (left out of the screen)'
FROM p
UNION ALL SELECT 3, '{MEASURES[2]}', {cov('ap3_coverage_pct')},
       CASE WHEN ap3_fully_assessed THEN 'Assessed' ELSE 'Not fully assessed' END,
       format_number(zero_teacher_annex_schools, 0)
         || CASE WHEN zero_teacher_annex_schools = 1 THEN ' annex school level' ELSE ' annex school levels' END
         || ' with 0 teachers reported'
FROM p"""

LEVEL_LABEL = "CASE {c} WHEN 'ES' THEN 'Elementary' WHEN 'JHS' THEN 'Junior high' ELSE 'Senior high' END"
PR_TEACHERS = f"""WITH {LGU},
{SEL},
lv AS (
  SELECT city_mun_psgc_code, lgu_type, 1 AS ord, 'ES' AS lvl, es_offered_school_count AS offered, es_teacher_count AS teachers,
         es_learners_per_teacher AS ratio, es_passes_gate AS passes FROM {A}.ap3_teacher_pressure
  UNION ALL SELECT city_mun_psgc_code, lgu_type, 2, 'JHS', jhs_offered_school_count, jhs_teacher_count,
         jhs_learners_per_teacher, jhs_passes_gate FROM {A}.ap3_teacher_pressure
  UNION ALL SELECT city_mun_psgc_code, lgu_type, 3, 'SHS', shs_offered_school_count, shs_teacher_count,
         shs_learners_per_teacher, shs_passes_gate FROM {A}.ap3_teacher_pressure
),
ref AS (
  SELECT 'ES' AS lvl, MAX(es_benchmark_max_learners_per_teacher) AS reference FROM {A}.ap3_teacher_pressure
  UNION ALL SELECT 'JHS', MAX(jhs_benchmark_max_learners_per_teacher) FROM {A}.ap3_teacher_pressure
  UNION ALL SELECT 'SHS', MAX(shs_benchmark_max_learners_per_teacher) FROM {A}.ap3_teacher_pressure
),
me AS (
  SELECT lv.*, r.reference, {LEVEL_LABEL.format(c='lv.lvl')} AS level_label
  FROM lv JOIN sel USING (city_mun_psgc_code)
  LEFT JOIN ref AS r ON r.lvl = lv.lvl
  WHERE lv.offered > 0
)
SELECT level_label, ord, 'This place' AS series, ratio AS learners_per_teacher FROM me
UNION ALL SELECT level_label, ord, 'Reference (D-060)', reference FROM me"""

PR_ENROLLMENT = f"""WITH {LGU},
{SEL},
y AS (SELECT a.* FROM {A}.ap4_enrollment_trend AS a JOIN sel USING (city_mun_psgc_code))
SELECT 'SY ' || school_year AS school_year_label, 'All sectors' AS scope, enrollment_all_sectors AS learners FROM y
UNION ALL SELECT 'SY ' || school_year, 'Public schools', public_school_enrollment FROM y"""

BANDS = ["Kindergarten age (5)", "Elementary age (6-11)", "Junior high age (12-15)", "Senior high age (16-17)"]
PR_COHORTS = f"""WITH {LGU},
{SEL},
a AS (
  SELECT CASE WHEN p.age = 5 THEN '{BANDS[0]}' WHEN p.age <= 11 THEN '{BANDS[1]}' WHEN p.age <= 15 THEN '{BANDS[2]}'
              ELSE '{BANDS[3]}' END AS age_band,
         SUM(CASE WHEN p.reference_year = 2020 THEN p.population END) AS children_2020,
         SUM(CASE WHEN p.reference_year = 2024 THEN p.population END) AS children_2024
  FROM {G}.fact_city_school_age_population AS p JOIN sel ON sel.city_mun_psgc_code = p.city_mun_psgc_code
  WHERE p.age BETWEEN 5 AND 17 AND p.sex IN ('male', 'female') AND p.reference_year IN (2020, 2024)
  GROUP BY 1
)
SELECT age_band, children_2020, children_2024,
       (children_2024 - children_2020) / NULLIF(CAST(children_2020 AS DOUBLE), 0) AS change
FROM a"""

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
    """Active and blank-count public schools in the selected LGU, SY 2023-24, with the reasons to verify each.

    A school is screened like AP2 does it (D-060): complete enrollment over more than zero reported rooms, at or
    above SCREEN learners per reported room."""
    level = (f"CASE WHEN :level = '{ALL_LEVELS}' THEN NULL ELSE :level END") if level_param else "CAST(NULL AS STRING)"
    return f"""{LGU},
{SEL},
lvl AS (SELECT {level} AS level_code),
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
           CASE WHEN s.incomplete_levels = 0 AND r.instructional_classrooms_total > 0
                     AND s.learners / CAST(r.instructional_classrooms_total AS DOUBLE) >= {SCREEN}
                THEN 'Learners per reported room ' || {r1('s.learners / CAST(r.instructional_classrooms_total AS DOUBLE)')}
                     || ' is at or above the illustrative screen of {SCREEN}' END,
           CASE WHEN r.school_id IS NULL OR r.instructional_classrooms_total IS NULL THEN 'Classroom count not reported' END,
           CASE WHEN r.instructional_classrooms_total = 0 THEN '0 classrooms reported' END,
           CASE WHEN s.incomplete_levels > 0 THEN 'An offered level has no learner count' END,
           CASE WHEN s.offers_es = 1 AND (t.es_rows IS NULL OR t.es_rows = 0 OR t.es_teachers IS NULL) THEN 'Elementary offered but no teacher count' END,
           CASE WHEN s.offers_jhs = 1 AND (t.jhs_rows IS NULL OR t.jhs_rows = 0 OR t.jhs_teachers IS NULL) THEN 'Junior high offered but no teacher count' END,
           CASE WHEN s.offers_shs = 1 AND (t.shs_rows IS NULL OR t.shs_rows = 0 OR t.shs_teachers IS NULL) THEN 'Senior high offered but no teacher count' END,
           CASE WHEN s.annex_status <> 'Annex/Extension School' AND ((s.offers_es = 1 AND t.es_teachers = 0)
                  OR (s.offers_jhs = 1 AND t.jhs_teachers = 0) OR (s.offers_shs = 1 AND t.shs_teachers = 0))
                THEN '0 teachers reported at an offered level' END) AS reasons,
         CASE WHEN s.incomplete_levels = 0 AND r.instructional_classrooms_total > 0
                   AND s.learners / CAST(r.instructional_classrooms_total AS DOUBLE) >= {SCREEN}
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
  LEFT JOIN years AS y ON y.school_id = s.school_id
  WHERE s.is_active = 1 OR s.is_blank
),
schools AS (
  SELECT x.*, status <> '{STATUS_ORDER[3]}' AS to_check,
         -- a chosen level shows only its own ratio; the all-level ratio never stands in for a missing one
         CASE WHEN (SELECT level_code FROM lvl) IS NULL THEN learners_per_teacher
              ELSE learners_per_teacher_at_level END AS teacher_ratio,
         ROW_NUMBER() OVER (ORDER BY CASE WHEN status <> '{STATUS_ORDER[3]}' THEN 0 ELSE 1 END,
                                     learners_per_room DESC NULLS LAST, school_name) AS list_order
  FROM x
)"""


BARANGAY = f"(:barangay = '{ALL_BARANGAYS}' OR barangay_name = :barangay)"

PR_ANSWERS = f"""WITH {school_base(level_param=False)},
{PRI_CTE},
p AS (SELECT pri.* FROM pri JOIN sel USING (city_mun_psgc_code)),
tr AS (
  SELECT MAX(enrollment_change_pct_first_to_latest) AS change_pct, MAX(first_school_year) AS first_year,
         MAX(latest_school_year) AS last_year
  FROM {A}.ap4_enrollment_trend AS a JOIN sel USING (city_mun_psgc_code)
)
-- one row: each question's answer for this place, shown as a counter
SELECT {r0('p.ap1_learners_per_public_school')} || ' learners per public school' AS answer_1,
       CASE WHEN NOT p.ap2_assessed THEN 'Not assessed: under 90% of learners have a room count'
            ELSE format_number(COALESCE(p.congested_school_count, 0), 0) || ' of '
                 || format_number(COALESCE(p.ratio_school_count, 0), 0) || ' schools, '
                 || {r1('p.ap2_affected_learner_share_pct')} || '% of learners' END AS answer_2,
       concat_ws(' · ', CASE WHEN p.es_offered_school_count > 0 THEN 'ES ' || {r1('p.ap3_es_learners_per_teacher')} END,
                        CASE WHEN p.jhs_offered_school_count > 0 THEN 'JHS ' || {r1('p.ap3_jhs_learners_per_teacher')} END,
                        CASE WHEN p.shs_offered_school_count > 0 THEN 'SHS ' || {r1('p.ap3_shs_learners_per_teacher')} END)
         || CASE WHEN p.teacher_levels_above <> '' THEN ' (above the reference: ' || p.teacher_levels_above || ')' ELSE '' END
         AS answer_3,
       CASE WHEN tr.change_pct >= 0 THEN '+' ELSE '' END || {r1('100 * tr.change_pct')} || '% from SY ' || tr.first_year
         || ' to SY ' || tr.last_year AS answer_4
FROM p CROSS JOIN tr"""

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
FROM (SELECT schools.*, ROW_NUMBER() OVER (ORDER BY list_order) AS teaser_order FROM schools WHERE {BARANGAY}) AS f
WHERE teaser_order <= 5
ORDER BY teaser_order"""

# Deterministic insights: fixed rules over the same tables as the visuals, at most four, each suppressed when its
# data is missing. They state facts and never a cause.
PR_INSIGHTS = f"""WITH {school_base(level_param=False)},
{PRI_CTE},
p AS (SELECT pri.* FROM pri JOIN sel USING (city_mun_psgc_code)),
screen AS (
  SELECT 'Classrooms: ' || format_number(COALESCE(congested_school_count, 0), 0) || ' of '
           || format_number(COALESCE(ratio_school_count, 0), 0) || ' public schools have at least {SCREEN} learners per reported room, with '
           || format_number(COALESCE(ap2_affected_learners, 0), 0) || ' learners (' || {r1('ap2_affected_learner_share_pct')}
           || '% of public learners).'
           || CASE WHEN classroom_priority_rank IS NOT NULL
                   THEN ' Rank ' || format_number(classroom_priority_rank, 0) || ' in the classroom review queue.'
                   ELSE ' No school passes the screen; this is not proof the rooms are adequate.' END AS insight
  FROM p WHERE ap2_assessed
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
  SELECT 1 AS ord, insight FROM screen
  UNION ALL
  SELECT 2, CASE WHEN queue_status = '{QUEUE[2]}' THEN 'Not placed in the queue yet: ' || data_review_reason || '.'
                 ELSE format_number(COALESCE(missing_room_school_count, 0) + COALESCE(zero_room_school_count, 0), 0)
                      || ' public schools report no usable room count and are left out of the screen. Check them with '
                      || 'the Schools Division Office.' END
  FROM p
  WHERE queue_status = '{QUEUE[2]}' OR COALESCE(missing_room_school_count, 0) + COALESCE(zero_room_school_count, 0) > 0
  UNION ALL
  SELECT 3, 'Enrollment in all sectors went from ' || format_number(first_value, 0) || ' in SY ' || first_year || ' to '
            || format_number(last_value, 0) || ' in SY ' || last_year || ' (' || CASE WHEN change_pct >= 0 THEN '+' ELSE '' END
            || {r1('100 * change_pct')} || '%). Context only: it does not place an LGU in the queue.'
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
-- one row: the first four rules, each a counter with its own heading (empty when its data is incomplete)
SELECT MAX(CASE WHEN ord = 1 THEN insight END) AS finding_1,
       MAX(CASE WHEN ord = 2 THEN insight END) AS finding_2,
       MAX(CASE WHEN ord = 3 THEN insight END) AS finding_3,
       MAX(CASE WHEN ord = 4 THEN insight END) AS finding_4
FROM rules
WHERE insight IS NOT NULL AND ord <= 4"""

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
       s.learners_per_room, s.learners_per_teacher, s.teacher_ratio,
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
       s.teacher_ratio,
       CASE WHEN s.school_id = (SELECT school_id FROM pick) THEN 'Selected school'
            WHEN s.to_check THEN 'Figures to check' ELSE 'Other schools' END AS series
FROM schools AS s
WHERE s.offers_level = 1 AND s.learners_per_room IS NOT NULL
  AND s.teacher_ratio IS NOT NULL"""

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
       CASE WHEN to_check THEN reasons ELSE 'Every figure is reported, and the school is below the illustrative screen of {SCREEN} learners per reported room.' END AS reason,
       'Confirm with the school and the Schools Division Office before using this figure for planning.' AS next_step
FROM s"""

SA_LIST = f"""WITH {school_base()}
SELECT list_order, school_name, school_id, barangay_name, levels_offered, learners, learners_per_room,
       teacher_ratio, enrollment_change,
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

AP4_STATUS = ["Complete and comparable", "An incomplete school year", "Boundaries changed 2020 to 2024"]
DM_AP4 = f"""WITH {LGU},
{AP4_INCOMPLETE}
SELECT CASE WHEN c.incomplete = 1 THEN '{AP4_STATUS[1]}' WHEN c.comparable = 0 THEN '{AP4_STATUS[2]}'
            ELSE '{AP4_STATUS[0]}' END AS ap4_status,
       COUNT(*) AS lgus
FROM lgu AS l JOIN ap4_complete AS c ON c.city_mun_psgc_code = l.city_mun_psgc_code
WHERE {GEO_L}
GROUP BY 1"""

DM_KPI = f"""WITH {PRI}
SELECT COUNT(*) AS lgus,
       COUNT_IF(queue_status <> '{QUEUE[2]}') AS assessed,
       COUNT_IF(queue_status = '{QUEUE[2]}') AS data_review,
       COUNT_IF(queue_status = '{QUEUE[0]}') AS queue_lgus,
       SUM(COALESCE(congested_school_count, 0)) AS screened_schools
FROM pri
WHERE {GEO}"""

BENCHMARKS = json.loads((ROOT / "config" / "analytics_benchmarks.json").read_text(encoding="utf-8"))


def references():
    """The D-060 reference values as published in config/analytics_benchmarks.json, one row each."""
    ap2, ap3 = BENCHMARKS["ap2"], BENCHMARKS["ap3"]
    rows = [(MEASURES[1], "School learners per reported room", f"{ap2['operator']} {ap2['threshold']:g}", ap2["label"],
             "Places an LGU in the review queue"),
            ("Teachers, Elementary (AP3)", "Learners per teacher", f"> {ap3['es_max_learners_per_teacher']:g}",
             ap3["es_label"], "Context: never ranked"),
            ("Teachers, Junior high (AP3)", "Learners per teacher", f"> {ap3['jhs_max_learners_per_teacher']:g}",
             "derived deployment comparison (" + ap3["jhs_derivation"] + ")", "Context: never ranked"),
            ("Teachers, Senior high (AP3)", "Learners per teacher", "> 80/3 (26.7)",
             "derived deployment comparison (" + ap3["shs_derivation"] + ")", "Context: never ranked"),
            (MEASURES[0], "Learners per public school", "none", "no published reference", "Context only")]
    body = ",\n  ".join("(" + ", ".join("'" + str(v).replace("'", "''") + "'" for v in r) + ")" for r in rows)
    return f"SELECT * FROM (VALUES\n  {body}) AS r(measure, unit, reference, basis, use_in_dashboard)"


DM_REFS = references()

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

SHARE_BANDS = ["No school screened", "Under 10%", "10-25%", "25-50%", "50% or more"]
DM_SHARE = f"""WITH {PRI}
SELECT CASE WHEN COALESCE(ap2_affected_learners, 0) = 0 THEN '{SHARE_BANDS[0]}'
            WHEN ap2_affected_learner_share_pct < 10 THEN '{SHARE_BANDS[1]}'
            WHEN ap2_affected_learner_share_pct < 25 THEN '{SHARE_BANDS[2]}'
            WHEN ap2_affected_learner_share_pct < 50 THEN '{SHARE_BANDS[3]}' ELSE '{SHARE_BANDS[4]}' END AS share_band,
       lgu_type_label, COUNT(*) AS lgus
FROM pri
WHERE ap2_assessed AND {GEO}
GROUP BY ALL"""

LEVEL_STATUS = ["Above the reference", "At or below", "Not assessed"]
DM_TEACHER_LEVELS = f"""WITH {PRI},
lv AS (
  SELECT 'Elementary' AS level, es_offered_school_count AS offered, ap3_es_learners_per_teacher AS ratio,
         es_benchmark_max_learners_per_teacher AS reference FROM pri WHERE {GEO}
  UNION ALL SELECT 'Junior high', jhs_offered_school_count, ap3_jhs_learners_per_teacher, jhs_benchmark_max_learners_per_teacher
  FROM pri WHERE {GEO}
  UNION ALL SELECT 'Senior high', shs_offered_school_count, ap3_shs_learners_per_teacher, shs_benchmark_max_learners_per_teacher
  FROM pri WHERE {GEO}
)
SELECT level, CASE WHEN ratio IS NULL THEN '{LEVEL_STATUS[2]}' WHEN ratio > reference THEN '{LEVEL_STATUS[0]}'
                   ELSE '{LEVEL_STATUS[1]}' END AS status,
       COUNT(*) AS lgus
FROM lv
WHERE offered > 0
GROUP BY ALL"""

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

DEFAULTS = {"region": ALL_REGIONS, "province": ALL_PROVINCES, "lgu_type": ALL_TYPES, "queue": ALL_QUEUE,
            "coverage": ALL_COVERAGE, "lgu": TOP_LGU, "barangay": ALL_BARANGAYS, "level": ALL_LEVELS,
            "school_status": ALL_SCHOOLS, "school": FIRST_SCHOOL, "measure": ALL_MEASURES}
OPTION_FIELDS = {"region": ("opt_region", "region"), "province": ("opt_province", "province"),
                 "lgu_type": ("opt_type", "lgu_type_option"), "queue": ("opt_queue", "queue_option"),
                 "coverage": ("opt_coverage", "coverage_option"), "lgu": ("opt_lgu", "lgu_option"),
                 "barangay": ("opt_barangay", "barangay_option"), "level": ("opt_level", "level_option"),
                 "school_status": ("opt_status", "status_option"), "school": ("opt_school", "school_option"),
                 "measure": ("opt_measure", "measure_option")}

GEO_P = ["region", "province", "lgu_type"]
OV_P = GEO_P + ["queue", "coverage"]
LGU_P = GEO_P + ["lgu"]
SCHOOL_P = LGU_P + ["barangay", "level", "school"]


def datasets(b):
    b.dataset("ov_lgu", "Overview: LGUs and boundaries", OV_LGU, OV_P)
    b.dataset("ov_kpi", "Overview: KPIs", OV_KPI, OV_P)
    b.dataset("ov_teachers", "Overview: teacher references beside the queue", OV_TEACHERS, OV_P)
    b.dataset("ov_demand", "Overview: review status against enrollment direction", OV_DEMAND, OV_P)
    b.dataset("pr_card", "LGU Profile: selected LGU", PR_CARD, LGU_P)
    b.dataset("pr_answers", "LGU Profile: the four questions", PR_ANSWERS, LGU_P)
    b.dataset("pr_insights", "LGU Profile: what stands out", PR_INSIGHTS, LGU_P)
    b.dataset("pr_evidence", "LGU Profile: evidence against the references", PR_EVIDENCE, LGU_P)
    b.dataset("pr_reliability", "LGU Profile: result reliability", PR_RELIABILITY, LGU_P)
    b.dataset("pr_teachers", "LGU Profile: teachers by level", PR_TEACHERS, LGU_P)
    b.dataset("pr_enrollment", "LGU Profile: enrollment by school year", PR_ENROLLMENT, LGU_P)
    b.dataset("pr_census", "LGU Profile: school-age population (context)", PR_CENSUS, LGU_P)
    b.dataset("pr_cohorts", "LGU Profile: children coming up", PR_COHORTS, LGU_P)
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
    b.dataset("dm_ap4", "Data and Method: enrollment trend completeness", DM_AP4, GEO_P)
    b.dataset("dm_refs", "Data and Method: published references", DM_REFS)
    b.dataset("dm_coverage", "Data and Method: coverage bands", DM_COVERAGE, GEO_P + ["measure"])
    b.dataset("dm_reasons", "Data and Method: data review reasons", DM_REASONS, GEO_P + ["measure"])
    b.dataset("dm_share", "Data and Method: share of learners in screened schools", DM_SHARE, GEO_P)
    b.dataset("dm_teacher_levels", "Data and Method: teacher references by level", DM_TEACHER_LEVELS, GEO_P)
    b.dataset("dm_sources", "Data and Method: source years", DM_SOURCES)
    b.dataset("dm_checks", "Data and Method: latest data quality checks", DM_CHECKS)
    b.dataset("opt_region", "Filter: region", OPT_REGION)
    b.dataset("opt_province", "Filter: province", OPT_PROVINCE, ["region"])
    b.dataset("opt_type", "Filter: LGU type", values("lgu_type_option", [ALL_TYPES, "City", "Municipality"]))
    b.dataset("opt_queue", "Filter: review status", values("queue_option", [ALL_QUEUE] + QUEUE))
    b.dataset("opt_coverage", "Filter: coverage status", values("coverage_option", [ALL_COVERAGE, "Assessed", "Data review"]))
    b.dataset("opt_lgu", "Filter: city or municipality", OPT_LGU, GEO_P)
    b.dataset("opt_barangay", "Filter: barangay (LGU Profile)", OPT_BARANGAY, LGU_P)
    b.dataset("opt_barangay_school", "Filter: barangay (School Action)", OPT_BARANGAY, LGU_P)
    b.dataset("opt_level", "Filter: education level", values("level_option", [ALL_LEVELS, "ES", "JHS", "SHS"]))
    b.dataset("opt_status", "Filter: school status",
              values("status_option", [ALL_SCHOOLS, "Figures to check"] + STATUS_ORDER))
    b.dataset("opt_school", "Filter: school", OPT_SCHOOL, LGU_P + ["barangay", "level"])
    b.dataset("opt_measure", "Filter: measure", values("measure_option", [ALL_MEASURES] + MEASURES))


# ------------------------------------------------------------------------------------------ pages


def overview(b):
    p = Page("overview", "Overview")
    targets = ["ov_lgu", "ov_kpi", "ov_teachers", "ov_demand"]
    intro = text(b, "# Which cities and municipalities should we inspect first for crowded classrooms?\n", "\n",
                 f"Public schools with at least {SCREEN} learners per reported instructional room, SY 2023–24, ordered "
                 "by the learners in them (D-060). An order for review, not a shortage count.")
    queue = param_filter(b, "queue", "Review status", targets, "Show LGUs with the selected review status.")
    coverage = param_filter(b, "coverage", "Coverage status", targets,
                            "Separate assessed LGUs from places that require data review.")
    p.columns([(8, [(intro, 2)]), (4, [(queue, 1), (coverage, 1)])], 2)
    bold = {"fontStyle": "normal", "fontWeight": 700}
    p.row([(kpi(b, "ov_kpi", "LGUs in the review queue", "queue_lgus", num(),
                desc=f"At least one school at {SCREEN} or more per reported room", style=bold, card_style=KPI_CARD), 3),
           (kpi(b, "ov_kpi", "Learners in screened schools", "screened_learners", num(1, True),
                "{{ @formatted }} ({{share_txt}})", "SY 2023-24 · share of public learners in view",
                extra=("share_txt",), style=bold, card_style=KPI_CARD), 3),
           (kpi(b, "ov_kpi", "Screened schools", "screened_schools", num(), desc="Public schools at or above the screen",
                style=bold, card_style=KPI_CARD), 3),
           (kpi(b, "ov_kpi", "LGUs needing data review", "data_review_lgus", num(),
                desc="Under 90% of learners have a room count", style=bold, card_style=KPI_CARD), 3)], 3)
    queue_map = choropleth(
        b, "ov_lgu", "**Where is the classroom review queue?**", "queue_status", "Review status",
        [("lgu_label", "City or municipality"), ("queue_status", "Review status"),
         ("ap2_affected_learners", "Learners in screened schools")], QUEUE_COLORS, QUEUE,
        "Shows the review status of every city and municipality in the selected area.\n\nLGUs without available map "
        "boundaries are not drawn. A missing area should not be read as no reported congestion.")
    teachers = bar(b, "ov_teachers", "Teacher references beside the queue", "queue_status", "Review status", "count",
                   "city_mun_psgc_code", "Cities and municipalities", color="teacher_status", color_label="AP3",
                   mappings=TEACHER_COLORS, order=QUEUE, color_order=TEACHER_STATUS, layout="stack", legend=LEGEND_BOTTOM,
                   desc="Whether any offered level's learners per teacher is above its published reference. Context "
                        "only: AP3 never ranks or moves a place (D-060).")
    by_region = bar(b, "ov_lgu", "Places by region and review status", "region_short", "Region", "count",
                    "city_mun_psgc_code", "Cities and municipalities", color="queue_status", color_label="Review status",
                    mappings=QUEUE_COLORS, color_order=QUEUE, layout="stack", categories_shown=8, sort_by="x-reversed",
                    legend=LEGEND_BOTTOM,
                    desc="Every region in view, stacked by review status with the same colors as the map.")
    p.columns([(5, [(queue_map, 14)]), (7, [(teachers, 6), (by_region, 8)])], 14)
    p.row([(table(b, "ov_lgu", "Classroom review queue", [
        ("classroom_priority_rank", "Queue rank", None), ("lgu_label", "City or municipality", None),
        ("lgu_type_label", "Type", None), ("queue_status", "Review status", None),
        ("congested_school_count", "Screened schools", num()), ("ap2_affected_learners", "Learners in them", num()),
        ("ap2_affected_learner_share_pct", "Share of learners %", num(1)),
        ("ap2_learners_per_reported_room", "Learners per room (pooled)", num(1)),
        ("teacher_levels_above", "Teacher levels above reference", None),
        ("ap1_learners_per_public_school", "Learners per school", num()),
        ("lowest_coverage_pct", "Lowest coverage %", num()), ("data_review_reason", "Data review reason", None)],
        "The queue ranks LGUs by learners in screened schools, then screened schools, then the pooled ratio; exact ties "
        "share a rank. It orders review effort and is not an official shortage, construction entitlement or funding "
        "allocation."), 12)], 10)
    p.row([(bar(b, "ov_demand", "**Which LGUs in the queue have rising enrollment?**", "queue_status", "Review status",
                "count", "city_mun_psgc_code", "Cities and municipalities", color="enrollment_direction",
                color_label="Enrollment, SY 2020-21 to 2025-26", mappings=DIRECTION_COLORS, order=QUEUE,
                color_order=DIRECTIONS, layout="stack", legend={"hideTitle": False, "title": "Enrollment trend"},
                desc="Shows the number of LGUs with each review status by whether all-sector enrollment increased, "
                     "decreased or could not be fully assessed from SY 2020–21 to SY 2025–26. Context only."), 12)], 7)
    p.row([(text(b, "**Next:** Open **LGU Profile** and choose a city or municipality to review its counts, the "
                    "evidence behind its status, reporting coverage, barangays and first schools for follow-up.\n", "\n",
                 "Before acting, validate the screened schools against actual classroom counts, building condition, "
                 "shifts, enrolment projections and planned projects. The queue does not prescribe how many classrooms, "
                 "teachers or schools to add."), 12)], 2)
    return p


def lgu_profile(b):
    p = Page("lgu_profile", "LGU Profile")
    profile = [n for n in b.params if n.startswith("pr_")] + ["opt_barangay"]
    intro = text(b, "# Why is this place a priority, and where should the board look?\n", "\n",
                 "See which resources are under the most pressure, how reliable the result is and where the board "
                 "should look next.")
    place = param_filter(b, "lgu", "City or municipality", profile, "Choose the LGU you want to review.")
    barangay = param_filter(b, "barangay", "Barangay", ["pr_barangays", "pr_teaser"],
                            "Narrow the barangay and school sections to one barangay.")
    p.columns([(8, [(intro, 2)]), (4, [(place, 1), (barangay, 1)])], 2)
    p.row([(kpi(b, "pr_card", "Selected city or municipality", "city_mun_name", None,
                desc="Change it with City or municipality above", style=TITLE_STYLE, heading=True, align="left"), 12)], 1)
    p.row([(kpi(b, "pr_card", "Place details", "details", None,
                desc="Type · province (or region) · review status · queue rank",
                style=DETAIL_STYLE, heading=True, align="left"), 12)], 1)
    p.row([(kpi(b, "pr_card", "Public schools", "public_schools", num(), desc="Active, SY 2023-24", style=KPI_STYLE,
                card_style=KPI_CARD), 3),
           (kpi(b, "pr_card", "Instructional classrooms", "classrooms", num(), desc="Usable counts, SY 2023-24",
                style=KPI_STYLE, card_style=KPI_CARD), 3),
           (kpi(b, "pr_card", "Teachers", "teachers", num(), desc="Elementary to senior high, SY 2023-24",
                style=KPI_STYLE, card_style=KPI_CARD), 3),
           (kpi(b, "pr_card", "Public learners", "public_learners", num(), desc="Public-school enrollment, SY 2023-24",
                style=KPI_STYLE, card_style=KPI_CARD), 3)], 3)
    for i, heading in enumerate(FINDINGS, 1):
        p.row([(note(b, "pr_insights", heading, f"finding_{i}", style=SENTENCE_STYLE), 12)], 1)
    p.row([(note(b, "pr_answers", title, f"answer_{i}", desc, SENTENCE_STYLE, label=label), 3)
           for i, (title, label, desc) in enumerate(ANSWERS, 1)], 4)
    p.row([(table(b, "pr_evidence", "**The evidence behind this status**", [
                ("measure", "Measure", None), ("this_place", "This place", None), ("reference", "Reference", None),
                ("status", "Status", None)],
                "Each measure beside the reference D-060 publishes for it. Only the classroom school screen places an LGU "
                "in the queue; teachers and schools are context."), 6),
           (bar(b, "pr_teachers", "Learners per teacher by level", "level_label", "Level", "max", "learners_per_teacher",
                "Learners per teacher", color="series", color_label="",
                mappings=[{"value": "This place", "color": "#712B13"}, {"value": "Reference (D-060)", "color": "#A9B4BF"}],
                color_order=["This place", "Reference (D-060)"], layout="group", fmt=num(1),
                desc="Each offered level against its reference: ES 35 is a historical study reference, JHS 36 and SHS "
                     "80/3 are derived deployment comparisons. Not a staffing entitlement."), 6)], 7)
    p.row([(line(b, "pr_enrollment", "**How has enrollment changed?**", "school_year_label", "School year",
                 "sum", "learners", "Learners", num(1, True), color="scope", color_label="Scope", kind="area",
                 mappings=[{"value": "All sectors", "color": "#5B6B7A"}, {"value": "Public schools", "color": "#C9A227"}],
                 x_order=SCHOOL_YEARS,
                 desc="Shows public-school enrollment and enrollment across all school sectors for each available "
                      "school year."), 6),
           (bar(b, "pr_cohorts", "**How is the school-age population changing?**", "age_band", "Age group", "max",
                "change", "Change, 2020 to 2024", order=BANDS, fmt=pct(1),
                desc="Shows the change in resident children grouped by the school level corresponding to their age. An "
                     "increase in younger age groups may indicate future demand at higher school levels."), 6)], 7)
    p.row([(bar(b, "pr_census", "**How do resident children and local enrollment compare?**", "period",
                "Census · school year", "sum", "people", "People", horizontal=False, color="series", color_label="Series",
                layout="group", legend=LEGEND_BOTTOM,
                mappings=[{"value": CENSUS_SERIES[0], "color": "#5B6B7A"}, {"value": CENSUS_SERIES[1], "color": "#A9B4BF"},
                          {"value": CENSUS_SERIES[2], "color": "#C9A227"}],
                color_order=CENSUS_SERIES, fmt=num(1, True),
                desc="Compares resident children aged 5–17 with learners enrolled in local schools. Children are counted "
                     "where they live, while learners are counted where they attend school. The difference is not an "
                     "estimate of children who are out of school."), 6),
           (table(b, "pr_barangays", "**Barangay access screening**", [
               ("barangay_name", "Barangay", None), ("urban_rural", "Urban or rural", None),
               ("public_schools", "Public schools", num()), ("public_es", "Public elementary", None),
               ("learners", "Public learners", num())],
               "Shows public-school access in each barangay, with barangays that have no matched public elementary "
               "school listed first."), 6)], 8)
    p.row([(table(b, "pr_teaser", "**Schools for follow-up**", [
        ("school_name", "School", None), ("barangay_name", "Barangay", None), ("learners_per_room", "Learners per classroom", num(1)),
        ("status", "Status", None), ("reasons", "Why", None)],
        "School records to verify first, followed by schools with the highest classroom pressure."), 12)], 5)
    p.row([(table(b, "pr_reliability", "**Data coverage and verification checks**", [
        ("measure", "Measure", None), ("coverage", "Share reported", None), ("assessed", "Status", None),
        ("unusual_schools", "Unusual figures", None)],
        "Shows whether enough data were reported for each measure, and the schools left out because a room or teacher "
        "count is missing or zero."), 12)], 4)
    return p


def school_action(b):
    p = Page("school_action", "School Action")
    targets = ["sa_school", "sa_peers", "sa_trend", "sa_rooms", "sa_verify", "sa_list", "opt_school"]
    intro = text(b, "# Which schools should we check, and why?\n",
                 "Public schools in one city or municipality, SY 2023-24. Choose the place, then a school to see its "
                 "figures.")
    place = param_filter(b, "lgu", "City or municipality", targets + ["opt_barangay_school"],
                         "Its own choice: picking a place on LGU Profile does not change it. Defaults to the top place.",
                         options=("opt_lgu", "lgu_option"))
    barangay = param_filter(b, "barangay", "Barangay", targets, options=("opt_barangay_school", "barangay_option"))
    p.columns([(8, [(intro, 2)]), (4, [(place, 1), (barangay, 1)])], 2)
    level = param_filter(b, "level", "Education level", targets)
    status = param_filter(b, "school_status", "School status", ["sa_list"])
    school = param_filter(b, "school", "School", targets, "Defaults to the first school to check.")
    p.row([(school, 4), (status, 4), (level, 4)], 1)
    p.row([(kpi(b, "sa_school", "Selected school", "school_name", None,
                desc="Change it in School above", style=TITLE_STYLE, heading=True, align="left"), 12)], 1)
    p.row([(kpi(b, "sa_school", "School details", "details", None,
                desc="School ID · barangay · main or annex · levels · learners, SY 2023-24 · figures to check",
                style={"fontSize": 16}, heading=True, align="left"), 12)], 1)
    p.row([(kpi(b, "sa_school", "Learners per reported room", "learners_per_room", num(1),
                desc="All levels · rooms include labs", style=KPI_STYLE, card_style=KPI_CARD), 3),
           (kpi(b, "sa_school", "Learners per teacher", "teacher_ratio", num(1), desc="At the education level chosen above",
                style=KPI_STYLE, card_style=KPI_CARD), 3),
           (kpi(b, "sa_school", "Enrollment change", "enrollment_change", pct(1), desc="SY 2020-21 to 2025-26, if complete",
                style=KPI_STYLE, card_style=KPI_CARD), 3),
           (kpi(b, "sa_school", "Temporary and makeshift rooms", "temporary_or_makeshift_rooms", num(),
                desc="SY 2023-24", style=KPI_STYLE, card_style=KPI_CARD), 3)], 3)
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
    intro = text(b, "# Can we rely on these results, and how were they produced?\n",
                 "Start with the summary and the rule; the checks behind them follow.")
    measure = param_filter(b, "measure", "Measure", ["dm_coverage", "dm_reasons"])
    p.columns([(9, [(intro, 2)]), (3, [(measure, 2)])], 2)
    p.row([(kpi(b, "dm_kpi", "Assessed LGUs", "assessed", num(), "{{ @formatted }} of {{lgus}}",
                "At least 90% of learners have a room count", extra=("lgus",), style=KPI_STYLE, card_style=KPI_CARD), 3),
           (kpi(b, "dm_kpi", "LGUs requiring data review", "data_review", num(), desc="Classroom coverage below 90%",
                style=KPI_STYLE, card_style=KPI_CARD), 3),
           (kpi(b, "dm_kpi", "LGUs in the review queue", "queue_lgus", num(), "{{ @formatted }} of {{assessed}}",
                "Of the assessed LGUs", extra=("assessed",), style=KPI_STYLE, card_style=KPI_CARD), 3),
           (kpi(b, "dm_kpi", "Screened schools", "screened_schools", num(),
                desc=f"Public schools at or above {SCREEN} per reported room", style=KPI_STYLE, card_style=KPI_CARD), 3)], 3)
    p.row([(kpi(b, "freshness", "Data freshness", "freshness", None,
                desc="Latest successful pipeline run and the school years it covers", style={"fontSize": 16},
                align="left"), 12)], 1)
    p.row([(text(b, "## How the review queue is built (D-060)\n\n",
                 f"1. **School screen, SY 2023-24:** each active public school with complete enrollment and more than "
                 f"zero reported instructional rooms passes when it has at least {SCREEN} learners per reported room. A "
                 "PIDS-style illustrative screen, not an official DepEd ratio.\n",
                 "2. **Coverage gate:** an LGU is assessed only when at least 90% of its learners are in schools with a "
                 "room count. Otherwise it is **Data review**.\n",
                 "3. **Queue:** an assessed LGU with at least one passing school enters the **classroom review queue**; "
                 "one with none is **No reported congestion**, which is not proof of adequacy.\n",
                 "4. **Rank:** learners in passing schools, then passing schools, then the pooled ratio, with "
                 "`DENSE_RANK()`, so exact ties share a rank.\n",
                 "5. **Context only:** AP1 schools, AP3 teacher references, AP4 enrollment, school-age population and "
                 "poverty never rank or move a place."), 6),
           (table(b, "dm_refs", "Published references", [
               ("measure", "Measure", None), ("unit", "Unit", None), ("reference", "Reference", None),
               ("basis", "Basis", None), ("use_in_dashboard", "Use", None)],
               "From config/analytics_benchmarks.json, the values the Analytics SQL writes. A comparison, never a "
               "staffing or construction entitlement."), 6)], 5)
    p.row([(bar(b, "dm_coverage", "Coverage by measure", "measure", "Measure", "sum", "lgus", "Cities and municipalities",
                color="coverage_band", color_label="Coverage", layout="stack", color_order=COVERAGE_BANDS,
                order=COVERAGE_MEASURES, desc="Below 90% a measure is not assessed; for classrooms the place goes to "
                                              "data review."), 5),
           (bar(b, "dm_ap4", "How complete the enrollment trend is", "ap4_status", "Status", "sum", "lgus",
                "Cities and municipalities", order=AP4_STATUS,
                desc="Context only. An incomplete year means a school total is missing in some year; boundary changes "
                     "make 2020 and 2024 harder to compare."), 7)], 7)
    p.row([(bar(b, "dm_reasons", "Why places are not assessed", "reason", "Reason", "sum", "lgus",
                "Cities and municipalities", color="measure", color_label="Measure", color_order=MEASURES,
                layout="stack", legend=LEGEND_BOTTOM, desc="A place can be counted under more than one measure."), 6),
           (bar(b, "dm_share", "Share of learners in screened schools", "share_band", "Share", "sum", "lgus",
                "Assessed cities and municipalities", color="lgu_type_label", color_label="Type", layout="stack",
                order=SHARE_BANDS, legend=LEGEND_BOTTOM,
                desc="How concentrated the screened learners are in each assessed place. Follows Region, Province and "
                     "LGU type."), 6)], 7)
    p.row([(bar(b, "dm_teacher_levels", "Teacher references by level", "level", "Level", "sum", "lgus",
                "Cities and municipalities offering the level", color="status", color_label="Learners per teacher",
                layout="stack", order=["Elementary", "Junior high", "Senior high"], color_order=LEVEL_STATUS,
                legend=LEGEND_BOTTOM,
                desc="Context only: AP3 has no teacher-priority rank (D-060)."), 6),
           (heatmap(b, "dm_sources", "Which school years each source covers", "school_year", "School year", None,
                    "source", "Source", None, "max", "has_data", "Has data (1 = yes)",
                    "Classrooms and teachers are available only for SY 2023-24, the year the queue uses."), 6)], 6)
    p.row([(bar(b, "dm_checks", "Latest automatic data checks", "layer", "Processing step", "sum", "checks", "Checks",
                horizontal=False, color="status", color_label="Result",
                mappings=[{"value": "PASS", "color": "#5B6B7A"}, {"value": "WARN", "color": "#E3A008"},
                          {"value": "FAIL", "color": "#A32D2D"}],
                order=["control", "bronze", "silver", "integration", "gold", "analytics"],
                desc="Each processing step's latest checks. A failed check stops that step from publishing."), 6),
           (text(b, "## What this dashboard cannot tell you\n\n",
                 "- **How many resources to add.** The queue orders review; it is not an official shortage, "
                 "construction entitlement or funding allocation.\n",
                 "- **Teacher allocation priority.** The data count teachers working in schools, not authorized "
                 "positions or vacancies.\n",
                 "- **Room type and condition.** The room count is broader than K–12 classrooms and does not show "
                 "condition, shifts or utilization.\n",
                 "- **How far learners travel.** Enrollment is counted at the school.\n",
                 "- **Classroom or teacher trends.** Only SY 2023-24 has comparable classroom and teacher data."), 6)], 6)
    return p


def build():
    b = Builder(DEFAULTS, OPTION_FIELDS)
    datasets(b)
    pages = [overview(b), lgu_profile(b), school_action(b), data_and_method(b)]
    global_page = Page("global_filters", "Global filters")
    all_targets = [d["name"] for d in b.datasets]
    for i, (keyword, title, desc) in enumerate([
            ("region", "Region", None), ("province", "Province", None), ("lgu_type", "LGU type", None)]):
        global_page.items.append({"widget": param_filter(b, keyword, title, all_targets, desc),
                                  "position": {"x": 0, "y": i * 2, "width": 12, "height": 2}})
    return {
        "datasets": b.datasets,
        "pages": [page.json() for page in pages] + [global_page.json("PAGE_TYPE_GLOBAL_FILTERS")],
        "uiSettings": {"theme": {
            "canvasBackgroundColor": {"light": "#FFFFFF", "dark": "#151B20"},
            "widgetBackgroundColor": {"light": "#FFFFFF", "dark": "#1E262C"},
            "widgetBorderColor": {"light": "#FFFFFF", "dark": "#1E262C"},
            "fontColor": {"light": "#14212B", "dark": "#E8ECF0"},
            "selectionColor": {"light": "#712B13", "dark": "#F0997B"},
            "visualizationColors": ["#712B13", "#5B6B7A", "#C9A227", "#D85A30", "#A9B4BF", "#8A96A3", "#2F6F8F"],
            "fontFamily": "Inter", "fontSettings": {"base": {"fontFamily": "Inter"}, "widgetTitle": {"fontSize": 16}},
            "widgetHeaderAlignment": "LEFT", "textBoxVerticalAlign": "VERTICAL_ALIGN_TOP", "widgetPadding": 16, "widgetMargin": 8, "widgetCornerRadius": 8},
            "applyModeEnabled": False},
    }


def render():
    return json.dumps(build(), indent=2) + "\n"


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else OUTPUT
    target.write_text(render(), encoding="utf-8")
    print(f"wrote {target}")
