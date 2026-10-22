"""ReachED: Education Access Priority Dashboard. National Overview, LGU Profile, School Action, Data & Method.

Run `python -m src.dashboard.planner` to rewrite dashboards/reached_planner.lvdash.json from this file.

The planning status and review order, the classroom and teacher pressure signals, enrollment growth, and coverage
gates come from the Analytics tables; the dashboard only filters, labels and arranges them. Planning statuses keep their
published database values and get a plain-language display label and basis in the dataset SQL, so the wording can
change without touching the Analytics contract. Global filters (Region, Province, LGU type) and the page filters are
query parameters applied after those values are read, so a filter narrows what is shown and never changes a status,
comparison point or order. School-level views read Gold and apply the same illustrative 50-learner screen to each
school's own reported rooms.

User-facing text never shows a rule or measure code. Missing values are written as words (Not reported, Not assessed,
Not assessable, or a dash), never as null, and table counts are written in the SQL with thousands separators.
"""
import json
import sys
from pathlib import Path

from src.dashboard.widgets import (Builder, Page, badges, bar, choropleth, kpi, line, note, num, param_filter, pct,
                                   point_map, ref_line, scatter, table, text)

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "dashboards" / "reached_planner.lvdash.json"
BENCHMARKS = json.loads((ROOT / "config" / "analytics_benchmarks.json").read_text(encoding="utf-8"))
# each level's teacher comparison point, as published: ES and JHS from the config, SHS 80/3
TEACHER_REFS = {"ES": float(BENCHMARKS["ap3"]["es_max_learners_per_teacher"]),
                "JHS": float(BENCHMARKS["ap3"]["jhs_max_learners_per_teacher"]), "SHS": 80 / 3}
TEACHER_REF_TXT = " ".join(f"WHEN '{c}' THEN ' vs {v:.1f}'".replace(".0'", "'") for c, v in TEACHER_REFS.items())
TEACHER_REF_ROWS = ", ".join(f"('{c}', {i}, CAST({v!r} AS DOUBLE))" for i, (c, v) in enumerate(TEACHER_REFS.items(), 1))

A = "edu_access.`06-analytics`"
G = "edu_access.`05-gold`"
ALL_REGIONS, ALL_PROVINCES, ALL_TYPES = "All regions", "All provinces", "All LGU types"
ALL_QUEUE, ALL_COVERAGE = "All review statuses", "All LGUs"
READINESS = ["Assessed", "Insufficient data"]
TOP_LGU = "(Top LGU in the filters)"
ALL_BARANGAYS = "All barangays"
ALL_LEVELS, ALL_SCHOOLS, FIRST_SCHOOL = "All levels", "All schools", "(First school to verify)"
LEVELS = ["Elementary", "Junior high", "Senior high"]
ALL_MEASURES = "All measures"
SCHOOL_YEARS = ["SY 2020-21", "SY 2021-22", "SY 2022-23", "SY 2023-24", "SY 2024-25", "SY 2025-26"]

# Review status: the published priority categories, most urgent first, used in every legend, axis and filter. Each
# has a planning status, the plain-language reading shown beside it, and its basis
QUEUE = ["Priority 1", "Priority 2", "Priority 3", "Monitor", "No current pressure identified", "Data review"]
STATUS_LABELS = ["Immediate joint review", "High-priority review", "Targeted review", "Growth watchlist",
                 "No current pressure identified", "Insufficient data to assess"]
STATUS_BASIS = ["Classroom and teacher pressure are present, and enrollment is growing",
                "Both pressure signals are present, or one pressure signal is present with growing enrollment",
                "One pressure signal is present without growing enrollment",
                "Enrollment is growing, but no current pressure signal was identified",
                "No pressure signal or enrollment growth was identified from available data",
                "Coverage or growth data are incomplete and no known pressure signal is present"]
QUEUE_COLORS = [{"value": QUEUE[0], "color": "#712B13"}, {"value": QUEUE[1], "color": "#B85C38"},
                {"value": QUEUE[2], "color": "#C9A227"}, {"value": QUEUE[3], "color": "#5B6B7A"},
                {"value": QUEUE[4], "color": "#D9DEE3"}, {"value": QUEUE[5], "color": "#8A96A3"}]  # map legend
SCREEN = 50  # the illustrative reported-room screen, config/analytics_benchmarks.json
MEASURES = ["Public schools", "Classrooms", "Teachers"]
REASON_MEASURES = [MEASURES[1], MEASURES[2], "Enrollment trend"]  # the inputs that can send an LGU to data review
SIGNALS = ["Present", "Not identified", "Not assessed"]
GROWTH = ["Growing", "Not growing", "Not comparable"]
# the review status each combination of the two pressure signals leads to (What is driving priority?)
SIGNAL_RESULTS = [f"{QUEUE[0]} if growing, else {QUEUE[1]}", f"{QUEUE[1]} if growing, else {QUEUE[2]}",
                  f"{QUEUE[3]} if growing, else no current pressure", QUEUE[5]]
# theme palette positions (uiSettings visualizationColors) for the badge cells, with white text at WHITE
PALETTE = ["#712B13", "#5B6B7A", "#C9A227", "#D85A30", "#A9B4BF", "#8A96A3", "#2F6F8F", "#FFFFFF"]
WHITE = PALETTE.index("#FFFFFF")
SIGNAL_BADGES = [(SIGNALS[0], PALETTE.index("#D85A30")), (SIGNALS[1], PALETTE.index("#5B6B7A")),
                 (SIGNALS[2], PALETTE.index("#8A96A3"))]
RESULT_BADGES = [(SIGNAL_RESULTS[0], PALETTE.index("#712B13")), (SIGNAL_RESULTS[1], PALETTE.index("#D85A30")),
                 (SIGNAL_RESULTS[2], PALETTE.index("#2F6F8F")), (SIGNAL_RESULTS[3], PALETTE.index("#8A96A3"))]
STATUS_ORDER = ["Above classroom screen", "Missing figure", "Zero rooms or teachers", "No verification flag"]
VERIFY = ["Verification needed", "No verification flag"]
KPI_STYLE = {"fontStyle": "normal", "fontWeight": 700}  # every view's four KPIs, on neutral cards
TITLE_STYLE = {"fontSize": 40, "fontStyle": "normal", "fontWeight": 800}  # the selected place or school
DETAIL_STYLE = {"fontSize": 16, "fontStyle": "normal", "fontWeight": 400}  # the line of details under it
STATUS_STYLE = {"fontSize": 18, "fontStyle": "normal", "fontWeight": 700}  # the status and its basis
LINE_STYLE = {"fontSize": 14, "fontStyle": "normal", "fontWeight": 400}  # facts, coverage and status lines
LEGEND_BOTTOM = {"position": "bottom"}
POINT_COLORS = [{"value": "Selected school", "color": "#712B13"}, {"value": VERIFY[0], "color": "#E3A008"},
                {"value": "Other schools", "color": "#A9B4BF"}]
MAP_COLORS = [{"value": VERIFY[0], "color": "#E3A008"}, {"value": "Other schools", "color": "#8A96A3"}]
CHANGE_COLORS = [{"value": "Increase", "color": "#2F6F8F"}, {"value": "Decrease", "color": "#C9A227"}]  # not good or bad
REGION_SERIES = ["Increased", "Decreased", "Not fully comparable", "Equal counts — context only"]
REGION_COLORS = [{"value": REGION_SERIES[0], "color": "#2F6F8F"}, {"value": REGION_SERIES[1], "color": "#D85A30"},
                 {"value": REGION_SERIES[2], "color": "#A9B4BF"}, {"value": REGION_SERIES[3], "color": "#5B6B7A"}]
PEER_SERIES = ["Selected LGU", "Other LGUs in the comparison area", "Not comparable", "Equal counts — context only"]
PEER_COLORS = [{"value": PEER_SERIES[0], "color": "#712B13"}, {"value": PEER_SERIES[1], "color": "#D9DEE3"},
               {"value": PEER_SERIES[2], "color": "#8A96A3"}, {"value": PEER_SERIES[3], "color": "#5B6B7A"}]
# amber means beyond a reference everywhere; brown is kept for the priority categories
LEVEL_STATUS = ["Above comparison point", "At or below comparison point", "Not assessed"]
LEVEL_COLORS = [{"value": LEVEL_STATUS[0], "color": "#E3A008"}, {"value": LEVEL_STATUS[1], "color": "#A9B4BF"},
                {"value": LEVEL_STATUS[2], "color": "#D9DEE3"}]
SCHOOL_SERIES = ["Selected school", "Above classroom screen", VERIFY[0], "Within screen", f"{SCREEN} learners per room"]
SCHOOL_COLORS = [{"value": SCHOOL_SERIES[0], "color": "#14212B"}, {"value": SCHOOL_SERIES[1], "color": "#A32D2D"},
                 {"value": SCHOOL_SERIES[2], "color": "#E3A008"}, {"value": SCHOOL_SERIES[3], "color": "#A9B4BF"},
                 {"value": SCHOOL_SERIES[4], "color": "#5B6B7A"}]
LOCATION_COLORS = [{"value": "Selected school", "color": "#712B13"}, {"value": "Nearby public schools", "color": "#A9B4BF"}]

# ------------------------------------------------------------------------------------------ shared SQL

LGU = f"""lgu AS (
  SELECT d.city_mun_psgc_code, d.city_mun_name,
         d.city_mun_name || ', ' || COALESCE(d.province_name, d.region_name) AS lgu_label,
         COALESCE(d.province_name, 'Independent cities (no province)') AS province_label,
         d.region_name,
         CASE WHEN instr(d.region_name, '(') > 0
              THEN substring(d.region_name, instr(d.region_name, '(') + 1,
                             instr(d.region_name, ')') - instr(d.region_name, '(') - 1)
              ELSE d.region_name END AS region_short,
         CASE WHEN lower(d.lgu_type) = 'city' THEN 'City' ELSE 'Municipality' END AS lgu_type_label
  FROM {G}.dim_city_municipality AS d
  WHERE d.member_type = 'regular'
)"""


def geo(prefix=""):
    return (f"(:region = '{ALL_REGIONS}' OR {prefix}region_name = :region)"
            f" AND (:province = '{ALL_PROVINCES}' OR {prefix}province_label = :province)"
            f" AND (:lgu_type = '{ALL_TYPES}' OR {prefix}lgu_type_label = :lgu_type)")


GEO, GEO_L, GEO_PRI = geo(), geo("l."), geo("pri.")
GEO_ACTIVE = f"(:region <> '{ALL_REGIONS}' OR :province <> '{ALL_PROVINCES}' OR :lgu_type <> '{ALL_TYPES}')"
QUEUE_SORT = "CASE {c} " + " ".join(f"WHEN '{q}' THEN {i}" for i, q in enumerate(QUEUE[:-1])) + " ELSE 5 END"
STATUS_LABEL = "CASE {c} " + " ".join(f"WHEN '{q}' THEN '{s}'" for q, s in zip(QUEUE, STATUS_LABELS)) + " END"
STATUS_BASIS_SQL = "CASE {c} " + " ".join(f"WHEN '{q}' THEN '{s}'" for q, s in zip(QUEUE, STATUS_BASIS)) + " END"
LEVEL_CODE = f"CASE :level WHEN '{LEVELS[0]}' THEN 'ES' WHEN '{LEVELS[1]}' THEN 'JHS' WHEN '{LEVELS[2]}' THEN 'SHS' END"
LEVEL_LABEL = f"CASE {{c}} WHEN 'ES' THEN '{LEVELS[0]}' WHEN 'JHS' THEN '{LEVELS[1]}' ELSE '{LEVELS[2]}' END"


def r1(expr, missing="Not reported"):
    return f"COALESCE(format_number({expr}, 1), '{missing}')"


def r0(expr, missing="Not reported"):
    return f"COALESCE(format_number({expr}, 0), '{missing}')"


def cov(expr):
    return f"COALESCE(format_number({expr}, 0) || '%', 'Not available')"


def share(part, whole):
    return f"COALESCE(format_number(100.0 * {part} / NULLIF({whole}, 0), 1) || '%', '—')"


def measure(expr, places, unit, missing="Not reported"):
    """A value with its unit, or one word when it is missing: never "Not reported learners per room"."""
    return f"CASE WHEN {expr} IS NULL THEN '{missing}' ELSE format_number({expr}, {places}) || '{unit}' END"


# published reasons a measure is not assessed, as complete labels an LGU user reads
REASONS = {
    "no active public school": "No active public school",
    "no school with complete enrollment": "No school with complete enrollment",
    "coverage below 90%": "School coverage below 90%",
    "learner coverage below 90%": "Classroom learner coverage below 90%",
    "no usable classroom denominator": "No usable room count",
    "no active public school level": "No active public school level",
    "an offered level is below 90% learner coverage": "At least one offered level has teacher coverage below 90%",
    "boundary changed 2020-2024": "Geographic boundaries changed",
    "public enrollment incomplete in first or latest school year": "Enrollment trend incomplete",
    "no 2024 census population row": "No 2024 census population",
    "no AP4 enrollment row": "No enrollment trend for this LGU",
    "no public enrollment in first school year": "No public enrollment in the first school year",
}
REASON = "CASE {c} " + " ".join(f"WHEN '{k}' THEN '{v}'" for k, v in REASONS.items()) + " ELSE {c} END"


def compact(expr):
    """6.48M or 12,345: millions shortened, anything smaller in full."""
    return (f"CASE WHEN {expr} >= 1000000 THEN format_number({expr} / 1000000.0, 2) || 'M' "
            f"ELSE format_number({expr}, 0) END")


def abbrev(expr):
    """435K or 1.2M for a direct label; exact values stay in the tooltip."""
    return (f"CASE WHEN {expr} >= 1000000 THEN format_number({expr} / 1000000.0, 1) || 'M' "
            f"WHEN {expr} >= 1000 THEN format_number({expr} / 1000.0, 0) || 'K' ELSE format_number({expr}, 0) END")


def signed(expr):
    """A signed percentage from a fraction: +13.0%."""
    return f"CASE WHEN {expr} >= 0 THEN '+' ELSE '' END || format_number(100 * {expr}, 1) || '%'"


# every LGU's published planning row with its evidence, display label and basis
PRI_CTE = f"""pri AS (
  SELECT l.lgu_label, l.province_label, l.lgu_type_label, l.region_short, m.*,
         m.priority_category AS queue_status,
         {STATUS_LABEL.format(c='m.priority_category')} AS status_label,
         {STATUS_BASIS_SQL.format(c='m.priority_category')} AS status_basis,
         {QUEUE_SORT.format(c='m.priority_category')} AS queue_sort,
         m.priority_order AS national_order,
         CASE WHEN m.classroom_pressure_flag = 1 THEN '{SIGNALS[0]}' WHEN COALESCE(m.ap2_assessed, FALSE) THEN '{SIGNALS[1]}'
              ELSE '{SIGNALS[2]}' END AS classroom_signal,
         -- the published flag: a signal at one level stands even if another offered level is short of coverage
         CASE WHEN m.teacher_pressure_flag = 1 THEN '{SIGNALS[0]}' WHEN COALESCE(m.ap3_assessed, FALSE) THEN '{SIGNALS[1]}'
              ELSE '{SIGNALS[2]}' END AS teacher_signal,
         CASE WHEN m.growing_enrollment THEN '{GROWTH[0]}' WHEN NOT m.growing_enrollment THEN '{GROWTH[1]}'
              ELSE '{GROWTH[2]}' END AS growth_signal,
         COALESCE(NULLIF(concat_ws(' + ', CASE WHEN m.classroom_pressure_flag = 1 THEN 'Classroom' END,
                                          CASE WHEN m.teacher_pressure_flag = 1 THEN 'Teacher' END), ''),
                  'None identified') AS pressure_signals,
         CASE WHEN m.priority_category = '{QUEUE[5]}' THEN '{READINESS[1]}'
              WHEN NOT COALESCE(m.ap2_assessed, FALSE) OR NOT COALESCE(m.ap3_assessed, FALSE)
                   OR m.growing_enrollment IS NULL THEN 'Partly assessed'
              ELSE '{READINESS[0]}' END AS data_readiness,
         concat_ws('; ',
              CASE WHEN NOT COALESCE(m.ap2_assessed, FALSE)
                   THEN COALESCE({REASON.format(c='a2.not_assessed_reason')}, 'Classrooms not assessed') END,
              CASE WHEN NOT COALESCE(m.ap3_assessed, FALSE)
                   THEN COALESCE({REASON.format(c='a3.not_assessed_reason')}, 'Teachers not fully assessed') END,
              CASE WHEN m.growing_enrollment IS NULL
                   THEN COALESCE({REASON.format(c='m.growth_not_assessed_reason')}, 'Enrollment trend not comparable')
                   END) AS not_assessed_reason_txt,
         concat_ws(', ', CASE WHEN a3.es_benchmark_status LIKE 'above%' THEN '{LEVELS[0]}' END,
                         CASE WHEN a3.jhs_benchmark_status LIKE 'above%' THEN '{LEVELS[1]}' END,
                         CASE WHEN a3.shs_benchmark_status LIKE 'above%' THEN '{LEVELS[2]}' END) AS teacher_levels_above,
         a1.active_public_school_count, a1.public_school_enrollment,
         a2.congested_school_count, a2.ratio_school_count, a2.missing_room_school_count, a2.zero_room_school_count,
         a2.reported_instructional_classrooms, a2.eligible_learners,
         a3.es_offered_school_count, a3.jhs_offered_school_count, a3.shs_offered_school_count,
         a3.es_teacher_count, a3.jhs_teacher_count, a3.shs_teacher_count,
         a3.es_passes_gate, a3.jhs_passes_gate, a3.shs_passes_gate,
         a3.es_learner_coverage_pct, a3.jhs_learner_coverage_pct, a3.shs_learner_coverage_pct,
         a3.es_benchmark_max_learners_per_teacher, a3.jhs_benchmark_max_learners_per_teacher,
         a3.shs_benchmark_max_learners_per_teacher,
         CASE WHEN a3.es_offered_school_count > 0 THEN 1 ELSE 0 END + CASE WHEN a3.jhs_offered_school_count > 0 THEN 1 ELSE 0 END
           + CASE WHEN a3.shs_offered_school_count > 0 THEN 1 ELSE 0 END AS levels_offered,
         CASE WHEN a3.es_offered_school_count > 0 AND (a3.es_passes_gate OR a3.es_benchmark_status LIKE 'above%') THEN 1 ELSE 0 END
           + CASE WHEN a3.jhs_offered_school_count > 0 AND (a3.jhs_passes_gate OR a3.jhs_benchmark_status LIKE 'above%') THEN 1 ELSE 0 END
           + CASE WHEN a3.shs_offered_school_count > 0 AND (a3.shs_passes_gate OR a3.shs_benchmark_status LIKE 'above%') THEN 1 ELSE 0 END
           AS levels_assessed,
         COALESCE(a3.es_zero_teacher_annex_school_count, 0) + COALESCE(a3.jhs_zero_teacher_annex_school_count, 0)
           + COALESCE(a3.shs_zero_teacher_annex_school_count, 0) AS zero_teacher_annex_schools,
         NULLIF(LEAST(CASE WHEN a3.es_offered_school_count > 0 THEN COALESCE(a3.es_learner_coverage_pct, 0) ELSE 999 END,
                      CASE WHEN a3.jhs_offered_school_count > 0 THEN COALESCE(a3.jhs_learner_coverage_pct, 0) ELSE 999 END,
                      CASE WHEN a3.shs_offered_school_count > 0 THEN COALESCE(a3.shs_learner_coverage_pct, 0) ELSE 999 END),
                999) AS teacher_coverage_pct
  FROM {A}.lgu_priority_matrix AS m
  JOIN lgu AS l ON l.city_mun_psgc_code = m.city_mun_psgc_code
  LEFT JOIN {A}.ap1_school_provision AS a1 ON a1.city_mun_psgc_code = m.city_mun_psgc_code
  LEFT JOIN {A}.ap2_classroom_pressure AS a2 ON a2.city_mun_psgc_code = m.city_mun_psgc_code
  LEFT JOIN {A}.ap3_teacher_pressure AS a3 ON a3.city_mun_psgc_code = m.city_mun_psgc_code
)"""
PRI = f"""{LGU},
{PRI_CTE}"""

OV_FILTER = (f"{GEO} AND (:queue = '{ALL_QUEUE}' OR queue_status = :queue)"
             f" AND (:coverage = '{ALL_COVERAGE}' OR (:coverage = '{READINESS[0]}' AND queue_status <> '{QUEUE[5]}')"
             f" OR (:coverage = '{READINESS[1]}' AND queue_status = '{QUEUE[5]}'))")

# ============================================================ 1 National Overview
# every LGU in view, in the published review order
OV_ROWS = f"""WITH {PRI}
SELECT ROW_NUMBER() OVER (ORDER BY national_order, city_mun_psgc_code) AS rank_in_view,
       national_order, city_mun_psgc_code, city_mun_name, lgu_label, lgu_type_label, province_label, region_name,
       region_short, queue_status, queue_sort, status_label, status_basis, pressure_signals, classroom_signal,
       teacher_signal, growth_signal, priority_affected_learners,
       format_number(priority_affected_learners, 0) AS affected_txt, ap2_affected_learners, data_readiness,
       not_assessed_reason_txt
FROM pri
WHERE {OV_FILTER}"""
OV_LGU = f"""SELECT * FROM ({OV_ROWS}) AS r
ORDER BY rank_in_view"""
OV_TOP = f"""SELECT * FROM ({OV_ROWS}) AS r
WHERE rank_in_view <= 10
ORDER BY rank_in_view"""
OV_INSUFFICIENT = f"""SELECT city_mun_name, region_short, not_assessed_reason_txt FROM ({OV_ROWS}) AS r
WHERE queue_status = '{QUEUE[5]}'
ORDER BY lgu_label"""

GEOM = "st_setsrid(st_simplify(st_geomfromgeojson(h.geometry), 0.003), 4326)"
SHAPES = """LEFT JOIN edu_access.`04-integration`.hdx_adm3_psgc_map AS m
  ON m.psgc_code = r.city_mun_psgc_code AND m.match_status = 'matched'
LEFT JOIN edu_access.`03-silver`.hdx_adm3_clean AS h ON h.adm3_pcode = m.adm3_pcode"""
OV_MAP = f"""SELECT r.lgu_label, r.queue_status, r.ap2_affected_learners, {GEOM} AS boundary
FROM ({OV_ROWS}) AS r
{SHAPES}
ORDER BY r.rank_in_view"""
OV_MAP_NOTE = f"""SELECT 'Drawn ' || format_number(COUNT(DISTINCT CASE WHEN h.geometry IS NOT NULL THEN r.city_mun_psgc_code END), 0)
       || ' of ' || format_number(COUNT(DISTINCT r.city_mun_psgc_code), 0) || ' LGUs in view.'
       || CASE WHEN COUNT(DISTINCT r.city_mun_psgc_code) > COUNT(DISTINCT CASE WHEN h.geometry IS NOT NULL THEN r.city_mun_psgc_code END)
               THEN ' LGUs without a published boundary are listed in the review queue; a missing area is never no pressure.'
               ELSE '' END AS map_line
FROM ({OV_ROWS}) AS r
{SHAPES}"""

OV_KPI = f"""WITH {PRI},
k AS (
  SELECT COUNT(*) AS lgus,
         COUNT_IF(queue_status <> '{QUEUE[5]}') AS assessed,
         COUNT_IF(queue_status = '{QUEUE[0]}') AS joint_review,
         COUNT_IF(queue_status IN ('{QUEUE[0]}', '{QUEUE[1]}', '{QUEUE[2]}')) AS any_pressure,
         COUNT_IF(queue_status = '{QUEUE[5]}') AS data_review,
         SUM(COALESCE(congested_school_count, 0)) AS schools_above,
         SUM(COALESCE(ap2_affected_learners, 0)) AS learners_above,
         SUM(public_school_enrollment) AS public_learners
  FROM pri
  WHERE {OV_FILTER}
)
-- each KPI is written whole here, so Databricks never abbreviates a count to 1.38K
SELECT k.*,
       format_number(joint_review, 0) || ' (' || {share('joint_review', 'assessed')} || ')' AS joint_kpi,
       format_number(any_pressure, 0) || ' of ' || format_number(assessed, 0) AS any_kpi,
       {compact('learners_above')} || ' (' || {share('learners_above', 'public_learners')} || ')' AS learners_kpi,
       format_number(data_review, 0) || ' of ' || format_number(lgus, 0) AS data_review_kpi
FROM k"""

# the priority rule as a signal matrix: each combination of the two pressure signals, how many LGUs, how many grow
SIGNAL_SORT = "CASE {c} " + " ".join(f"WHEN '{s}' THEN {i}" for i, s in enumerate(SIGNALS)) + " END"
OV_SIGNALS = f"""SELECT classroom_signal, teacher_signal, format_number(COUNT(*), 0) AS lgus,
       format_number(COUNT_IF(growth_signal = '{GROWTH[0]}'), 0) AS growing,
       CASE WHEN classroom_signal = '{SIGNALS[0]}' AND teacher_signal = '{SIGNALS[0]}' THEN '{SIGNAL_RESULTS[0]}'
            WHEN classroom_signal = '{SIGNALS[0]}' OR teacher_signal = '{SIGNALS[0]}' THEN '{SIGNAL_RESULTS[1]}'
            WHEN classroom_signal = '{SIGNALS[1]}' AND teacher_signal = '{SIGNALS[1]}' THEN '{SIGNAL_RESULTS[2]}'
            ELSE '{SIGNAL_RESULTS[3]}' END AS resulting_status
FROM ({OV_ROWS}) AS r
GROUP BY classroom_signal, teacher_signal
ORDER BY {SIGNAL_SORT.format(c='classroom_signal')}, {SIGNAL_SORT.format(c='teacher_signal')}"""

# one row per region and status, ordered by the region's share of Priority 1 and 2 LGUs (the chart keeps this order)
OV_REGION = f"""SELECT region_short, queue_status, lgus, share_of_region
FROM (
  SELECT region_short, queue_status, MIN(queue_sort) AS queue_sort, COUNT(*) AS lgus,
         COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY region_short) AS share_of_region,
         SUM(COUNT_IF(queue_status IN ('{QUEUE[0]}', '{QUEUE[1]}'))) OVER (PARTITION BY region_short)
           / SUM(COUNT(*)) OVER (PARTITION BY region_short) AS high_share
  FROM ({OV_ROWS}) AS r
  GROUP BY region_short, queue_status
) AS t
ORDER BY high_share DESC, region_short, queue_sort"""

OV_TYPE = f"""SELECT lgu_type_label, queue_status, COUNT(*) AS lgus,
       COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY lgu_type_label) AS share_of_type
FROM ({OV_ROWS}) AS r
GROUP BY lgu_type_label, queue_status"""

# school-age population and all-sector enrollment in the two census years (2020 with SY 2020-21, 2024 with SY 2024-25),
# public-school enrollment in SY 2024-25, and whether the LGU's geography is comparable across the two censuses
POP_CTE = f"""pop AS (
  SELECT city_mun_psgc_code,
         MAX(CASE WHEN census_year = 2024 THEN school_age_population END) AS population_2024,
         MAX(CASE WHEN census_year = 2020 THEN school_age_population END) AS population_2020,
         MAX(CASE WHEN census_year = 2024 THEN enrollment_all_sectors END) AS enrolled_2024,
         MAX(CASE WHEN census_year = 2020 THEN enrollment_all_sectors END) AS enrolled_2020,
         MAX(CASE WHEN census_year = 2024 THEN public_school_enrollment END) AS public_2024,
         MIN(CASE WHEN is_2020_2024_geography_comparable THEN 1 ELSE 0 END) AS comparable
  FROM {A}.ap4_enrollment_trend
  WHERE census_year IS NOT NULL
  GROUP BY city_mun_psgc_code
)"""
EQUAL_COUNTS = "Equal counts — context only"
SCHOOL_COUNT_YEAR = "SY 2023-24"  # the year of AP1's active public-school count


def change_txt(new, old):
    return f"CASE WHEN {old} > 0 AND {new} IS NOT NULL THEN {signed(f'({new} - {old}) / CAST({old} AS DOUBLE)')} ELSE 'Not comparable' END"


def equal_line(points, columns):
    """A dotted Y = X line as 41 points from 0 to 110% of the largest x or y, so every bubble fits with room to spare;
    a scatter has no diagonal line. columns: the points' other columns, filled with NULL (size 0)."""
    nulls = ", ".join("0" if c == "size" else f"CAST(NULL AS STRING) AS {c}" for c in columns)
    return (f"SELECT '{EQUAL_COUNTS}' AS label, g.i * m.top / 40.0 AS x, g.i * m.top / 40.0 AS y, "
            f"'{EQUAL_COUNTS}' AS series, {nulls}\n"
            f"FROM (SELECT 1.1 * GREATEST(MAX(x), MAX(y)) AS top FROM {points}) AS m CROSS JOIN (VALUES {LINE_STEPS}) AS g(i)\n"
            f"WHERE m.top IS NOT NULL")


LINE_STEPS = ", ".join(f"({i})" for i in range(41))
REGION_TIPS = ["lgus_txt", "population_2020_txt", "population_2024_txt", "population_change_txt", "enrolled_2020_txt",
               "enrolled_2024_txt", "enrollment_change_txt", "public_2024_txt", "size", "schools_txt", "school_year_txt",
               "comparable_txt", "review_txt"]
# one bubble per region, summed over the LGUs left after every filter; population change from comparable LGUs only
OV_REGION_BUBBLE = f"""WITH {PRI},
{POP_CTE},
f AS (
  SELECT pri.region_short, pri.queue_status, pri.active_public_school_count, pop.*
  FROM pri LEFT JOIN pop ON pop.city_mun_psgc_code = pri.city_mun_psgc_code
  WHERE {OV_FILTER}
),
r AS (
  SELECT region_short, COUNT(*) AS lgus, SUM(population_2024) AS population_2024, SUM(population_2020) AS population_2020,
         SUM(CASE WHEN comparable = 1 AND population_2020 > 0 THEN population_2024 END) AS comparable_2024,
         SUM(CASE WHEN comparable = 1 AND population_2020 > 0 THEN population_2020 END) AS comparable_2020,
         COUNT_IF(COALESCE(comparable = 1 AND population_2020 > 0, FALSE)) AS comparable_lgus,
         SUM(enrolled_2020) AS enrolled_2020, SUM(enrolled_2024) AS enrolled_2024, SUM(public_2024) AS public_2024,
         SUM(active_public_school_count) AS schools, COUNT_IF(queue_status = '{QUEUE[5]}') AS review_lgus
  FROM f GROUP BY region_short
),
pts AS (
  SELECT region_short AS label, CAST(population_2024 AS DOUBLE) AS x, CAST(enrolled_2024 AS DOUBLE) AS y,
         CASE WHEN comparable_lgus < lgus THEN 'Not fully comparable'
              WHEN comparable_2024 >= comparable_2020 THEN 'Increased' ELSE 'Decreased' END AS series,
         format_number(lgus, 0) AS lgus_txt, {r0('population_2020')} AS population_2020_txt,
         {r0('population_2024')} AS population_2024_txt,
         CASE WHEN comparable_2020 > 0 THEN {change_txt('comparable_2024', 'comparable_2020')} || ' (comparable LGUs only)'
              ELSE 'Not comparable' END AS population_change_txt,
         {r0('enrolled_2020')} AS enrolled_2020_txt, {r0('enrolled_2024')} AS enrolled_2024_txt,
         {change_txt('enrolled_2024', 'enrolled_2020')} AS enrollment_change_txt, {r0('public_2024')} AS public_2024_txt,
         schools AS size, {r0('schools')} AS schools_txt, '{SCHOOL_COUNT_YEAR}' AS school_year_txt,
         format_number(comparable_lgus, 0) || ' of ' || format_number(lgus, 0) AS comparable_txt,
         format_number(review_lgus, 0) AS review_txt
  FROM r
  WHERE population_2024 IS NOT NULL AND enrolled_2024 IS NOT NULL
)
SELECT label, x, y, series, {", ".join(REGION_TIPS)} FROM pts
UNION ALL
{equal_line("pts", REGION_TIPS)}"""

# ============================================================ 2 LGU Profile
SEL = f"""sel AS (
  SELECT l.city_mun_psgc_code, l.lgu_label
  FROM lgu AS l
  JOIN {A}.lgu_priority_matrix AS p ON p.city_mun_psgc_code = l.city_mun_psgc_code
  WHERE {GEO_L}
  ORDER BY CASE WHEN l.lgu_label = :lgu THEN 0 ELSE 1 END, p.priority_order, l.city_mun_psgc_code
  LIMIT 1
)"""

PR_CARD = f"""WITH {PRI},
{SEL},
scoped AS (
  SELECT city_mun_psgc_code, ROW_NUMBER() OVER (ORDER BY priority_order) AS scope_order, COUNT(*) OVER () AS scope_total
  FROM pri WHERE {GEO}
)
SELECT p.lgu_label, p.city_mun_name, p.queue_status, p.status_label,
       p.queue_status || ' · ' || p.status_label || ': ' || p.status_basis AS status_line,
       p.lgu_type_label || ' · '
         || CASE WHEN p.province_label = 'Independent cities (no province)' THEN p.region_name ELSE p.province_label END
         || ' · National review order: ' || format_number(p.priority_order, 0) || ' of '
         || format_number((SELECT COUNT(*) FROM pri), 0) || ' LGUs'
         || CASE WHEN {GEO_ACTIVE} THEN ' · ' || format_number(s.scope_order, 0) || ' of '
                 || format_number(s.scope_total, 0) || ' LGUs in current scope' ELSE '' END
         || ' · Data readiness: ' || p.data_readiness
         || CASE WHEN :lgu <> '{TOP_LGU}' AND p.lgu_label <> :lgu THEN ' · your choice is outside the filters, so this is the first LGU in them'
                 ELSE '' END AS details,
       -- each KPI is a short value; what it means is in the card's subtitle and the decision panel
       CASE WHEN NOT COALESCE(p.ap2_assessed, FALSE) THEN 'Not assessed'
            ELSE format_number(COALESCE(p.congested_school_count, 0), 0) || ' of '
                 || format_number(COALESCE(p.ratio_school_count, 0), 0) END AS classroom_kpi,
       CASE WHEN p.levels_offered = 0 THEN 'None offered' WHEN p.levels_assessed = 0 THEN 'Not assessed'
            ELSE format_number(p.ap3_pressured_level_count, 0) || ' of ' || format_number(p.levels_assessed, 0) END
         AS teacher_kpi,
       CASE WHEN p.growing_enrollment IS NULL OR p.ap4_public_enrollment_change_pct IS NULL THEN 'Not comparable'
            ELSE {signed('p.ap4_public_enrollment_change_pct / 100')} END AS enrollment_kpi,
       CASE WHEN p.queue_status = '{QUEUE[5]}' THEN '{QUEUE[5]}'
            ELSE {cov('LEAST(p.ap2_learner_coverage_pct, p.teacher_coverage_pct)')} END AS readiness_kpi,
       format_number(COALESCE(p.active_public_school_count, 0), 0) || ' public schools · '
         || {r0('p.reported_instructional_classrooms')} || ' reported instructional rooms · '
         || format_number(COALESCE(p.es_teacher_count, 0) + COALESCE(p.jhs_teacher_count, 0)
                          + COALESCE(p.shs_teacher_count, 0), 0) || ' reported teachers · '
         || {r0('p.public_school_enrollment')} || ' public learners · SY 2023-24' AS facts
FROM pri AS p
JOIN sel ON sel.city_mun_psgc_code = p.city_mun_psgc_code
LEFT JOIN scoped AS s ON s.city_mun_psgc_code = p.city_mun_psgc_code"""

# why the LGU has its status: the two pressure signals and growth, each Yes, No or Not assessed, then the result
PR_DECISION = f"""WITH {PRI},
{SEL},
p AS (SELECT pri.* FROM pri JOIN sel USING (city_mun_psgc_code))
SELECT 1 AS ord, 'Classroom pressure' AS signal,
       CASE classroom_signal WHEN '{SIGNALS[0]}' THEN 'Yes' WHEN '{SIGNALS[1]}' THEN 'No' ELSE 'Not assessed' END AS result,
       CASE WHEN NOT COALESCE(ap2_assessed, FALSE) THEN 'Under 90% of public learners are in schools with a usable room count'
            ELSE format_number(COALESCE(congested_school_count, 0), 0) || ' of ' || format_number(COALESCE(ratio_school_count, 0), 0)
                 || ' schools at or above {SCREEN} learners per reported room ('
                 || format_number(COALESCE(ap2_affected_learners, 0), 0) || ' learners, '
                 || {r1('ap2_affected_learner_share_pct', '0.0')} || '% of public learners), SY 2023-24' END AS basis
FROM p
UNION ALL
SELECT 2, 'Teacher pressure',
       CASE teacher_signal WHEN '{SIGNALS[0]}' THEN 'Yes' WHEN '{SIGNALS[1]}' THEN 'No' ELSE 'Not assessed' END,
       CASE WHEN teacher_pressure_flag = 1
              THEN teacher_levels_above || ' above the published comparison point, SY 2023-24'
            WHEN COALESCE(ap3_assessed, FALSE) THEN 'No offered level is above its comparison point, SY 2023-24'
            ELSE 'An offered level has under 90% of learners in schools with a teacher count' END
FROM p
UNION ALL
SELECT 3, 'Enrollment growing',
       CASE growth_signal WHEN '{GROWTH[0]}' THEN 'Yes' WHEN '{GROWTH[1]}' THEN 'No' ELSE 'Not assessed' END,
       CASE WHEN growing_enrollment IS NULL OR ap4_public_enrollment_change_pct IS NULL
              THEN 'Not comparable: ' || COALESCE({REASON.format(c='growth_not_assessed_reason')},
                                                  'boundaries or school years are incomplete')
            ELSE 'Public enrollment ' || {signed('ap4_public_enrollment_change_pct / 100')} || ' from SY 2020-21 to SY 2025-26 ('
                 || {r0('ap4_public_enrollment_first')} || ' to ' || {r0('ap4_public_enrollment_latest')} || ')' END
FROM p
UNION ALL
SELECT 4, 'Review status', queue_status, status_label || ': ' || status_basis FROM p
ORDER BY ord"""


def teacher_row(ord_, level, prefix, basis):
    ratio, ref = f"ap3_{prefix}_learners_per_teacher", f"{prefix}_benchmark_max_learners_per_teacher"
    return (f"SELECT {ord_}, 'Teacher pressure · {level}',\n"
            f"       CASE WHEN {prefix}_offered_school_count = 0 THEN '—'\n"
            f"            ELSE {measure(ratio, 1, ' learners per reported teacher')} END,\n"
            f"       'Comparison point ' || {r1(ref)} || ' ({basis})',\n"
            f"       CASE WHEN {prefix}_offered_school_count = 0 THEN 'Not offered' WHEN {ratio} IS NULL THEN 'Not assessed'\n"
            f"            WHEN {ratio} > {ref} THEN 'Above comparison point' ELSE 'At or below comparison point' END,\n"
            f"       CASE WHEN {prefix}_offered_school_count = 0 THEN '—' ELSE {cov(f'{prefix}_learner_coverage_pct')} END\n"
            f"FROM p")


# the measures beside their published comparison points
PR_EVIDENCE = f"""WITH {PRI},
{SEL},
p AS (SELECT pri.* FROM pri JOIN sel USING (city_mun_psgc_code))
SELECT 1 AS ord, 'Classroom pressure · school screen' AS measure,
       CASE WHEN NOT COALESCE(ap2_assessed, FALSE) THEN 'Not assessed'
            ELSE format_number(COALESCE(congested_school_count, 0), 0) || ' of ' || format_number(COALESCE(ratio_school_count, 0), 0)
                 || ' schools, ' || format_number(COALESCE(ap2_affected_learners, 0), 0) || ' learners' END AS this_lgu,
       'At or above {SCREEN} learners per reported room, school by school' AS comparison,
       CASE classroom_signal WHEN '{SIGNALS[0]}' THEN 'Signal present' WHEN '{SIGNALS[1]}' THEN 'No signal'
            ELSE 'Not assessed' END AS status,
       {cov('ap2_learner_coverage_pct')} AS coverage
FROM p
UNION ALL
SELECT 2, 'Classroom pressure · all schools pooled', {measure('ap2_learners_per_reported_room', 1, ' learners per reported room')},
       'Context: the school screen sets the signal', CASE WHEN ap2_assessed THEN 'Context' ELSE 'Not assessed' END,
       {cov('ap2_learner_coverage_pct')}
FROM p
UNION ALL
{teacher_row(3, LEVELS[0], 'es', 'historical study reference')}
UNION ALL
{teacher_row(4, LEVELS[1], 'jhs', 'derived deployment comparison')}
UNION ALL
{teacher_row(5, LEVELS[2], 'shs', 'derived deployment comparison')}
UNION ALL
SELECT 6, 'School network context', {measure('ap1_learners_per_public_school', 0, ' learners per public school')},
       'No published comparison point', 'Context only', {cov('ap1_coverage_pct')}
FROM p
ORDER BY ord"""

PR_RELIABILITY = f"""WITH {PRI},
{SEL},
p AS (SELECT pri.* FROM pri JOIN sel USING (city_mun_psgc_code))
SELECT 1 AS ord, '{MEASURES[0]}' AS measure, {cov('ap1_coverage_pct')} AS coverage,
       CASE WHEN ap1_assessed THEN 'Assessed' ELSE 'Not assessed' END AS assessed,
       '—' AS unusual_schools
FROM p
UNION ALL SELECT 2, '{MEASURES[1]}', {cov('ap2_learner_coverage_pct')},
       CASE WHEN ap2_assessed THEN 'Assessed' ELSE 'Not assessed' END,
       CASE WHEN COALESCE(missing_room_school_count, 0) + COALESCE(zero_room_school_count, 0) = 0 THEN 'None identified'
            ELSE format_number(COALESCE(missing_room_school_count, 0), 0) || ' with no room count, '
                 || format_number(COALESCE(zero_room_school_count, 0), 0) || ' with 0 rooms (left out of the screen)' END
FROM p
UNION ALL SELECT 3, '{MEASURES[2]}', {cov('teacher_coverage_pct')},
       CASE WHEN ap3_assessed THEN 'Assessed' ELSE 'Not fully assessed' END,
       CASE WHEN zero_teacher_annex_schools = 0 THEN 'None identified'
            ELSE format_number(zero_teacher_annex_schools, 0)
                 || CASE WHEN zero_teacher_annex_schools = 1 THEN ' annex school level' ELSE ' annex school levels' END
                 || ' with 0 teachers reported' END
FROM p
ORDER BY ord"""

# one bar per offered level: its learners per reported teacher as a share of the comparison point, so every level
# reads on the same scale against one marker at 100%
PR_TEACHERS = f"""WITH {LGU},
{SEL},
lv AS (
  SELECT city_mun_psgc_code, 1 AS ord, 'ES' AS lvl, es_offered_school_count AS offered, es_learners_per_teacher AS ratio,
         es_passes_gate AS passes, es_benchmark_max_learners_per_teacher AS reference FROM {A}.ap3_teacher_pressure
  UNION ALL SELECT city_mun_psgc_code, 2, 'JHS', jhs_offered_school_count, jhs_learners_per_teacher, jhs_passes_gate,
         jhs_benchmark_max_learners_per_teacher FROM {A}.ap3_teacher_pressure
  UNION ALL SELECT city_mun_psgc_code, 3, 'SHS', shs_offered_school_count, shs_learners_per_teacher, shs_passes_gate,
         shs_benchmark_max_learners_per_teacher FROM {A}.ap3_teacher_pressure
)
SELECT ord, {LEVEL_LABEL.format(c='lvl')} || ' · '
         || CASE WHEN ratio IS NULL OR NOT COALESCE(passes, FALSE) THEN 'not assessed'
                 ELSE format_number(ratio, 1) || ' vs ' || format_number(reference, 1) END AS level_axis,
       CASE WHEN ratio IS NOT NULL AND COALESCE(passes, FALSE) THEN ratio / NULLIF(reference, 0) END AS share_of_comparison,
       CASE WHEN ratio IS NULL OR NOT COALESCE(passes, FALSE) THEN '{LEVEL_STATUS[2]}'
            WHEN ratio > reference THEN '{LEVEL_STATUS[0]}' ELSE '{LEVEL_STATUS[1]}' END AS status
FROM lv JOIN sel USING (city_mun_psgc_code)
WHERE offered > 0"""

ENROLLMENT_SERIES = ["Public schools", "All school sectors"]
PR_ENROLLMENT = f"""WITH {LGU},
{SEL},
y AS (SELECT a.* FROM {A}.ap4_enrollment_trend AS a JOIN sel USING (city_mun_psgc_code))
SELECT 'SY ' || school_year AS school_year_label, '{ENROLLMENT_SERIES[0]}' AS scope, public_school_enrollment AS learners FROM y
UNION ALL SELECT 'SY ' || school_year, '{ENROLLMENT_SERIES[1]}', enrollment_all_sectors FROM y"""

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
       (children_2024 - children_2020) / NULLIF(CAST(children_2020 AS DOUBLE), 0) AS change,
       CASE WHEN children_2020 IS NULL OR children_2024 IS NULL THEN 'Not available'
            WHEN children_2024 >= children_2020 THEN 'Increase' ELSE 'Decrease' END AS direction
FROM a"""

CENSUS_SERIES = ["Resident children aged 5-17", "Enrolled in local schools, all sectors"]
CENSUS_YEARS = ["2020 census", "2024 census"]
PR_CENSUS = f"""WITH {LGU},
{SEL},
c AS (
  SELECT CAST(a.census_year AS STRING) || ' census' AS period, a.*
  FROM {A}.ap4_enrollment_trend AS a JOIN sel USING (city_mun_psgc_code)
  WHERE a.census_year IS NOT NULL
)
SELECT period, '{CENSUS_SERIES[0]}' AS series, school_age_population AS people FROM c
UNION ALL SELECT period, '{CENSUS_SERIES[1]}', enrollment_all_sectors FROM c"""

# the selected LGU among the other LGUs of its comparison area: its province, or its region for an independent or highly
# urbanized city (no province). Region, Province and LGU type narrow the area; the selected LGU always stays.
PEER_TIPS = ["province_label", "region_short", "queue_status", "population_2020_txt", "population_2024_txt",
             "population_change_txt", "enrolled_2020_txt", "enrolled_2024_txt", "enrollment_change_txt", "public_2024_txt",
             "size", "schools_txt", "learners_per_school_txt", "children_per_school_txt", "barangays_txt",
             "match_txt", "comparability_txt"]
PEER_AREA = f"""{PRI},
{SEL},
{POP_CTE},
me AS (SELECT pri.city_mun_psgc_code, pri.province_label, pri.region_name FROM pri JOIN sel USING (city_mun_psgc_code)),
area AS (
  SELECT pri.*, pop.population_2024, pop.population_2020, pop.enrolled_2024, pop.enrolled_2020, pop.public_2024,
         pop.comparable, pri.city_mun_psgc_code = me.city_mun_psgc_code AS is_selected
  FROM pri LEFT JOIN pop ON pop.city_mun_psgc_code = pri.city_mun_psgc_code
  CROSS JOIN me
  WHERE CASE WHEN me.province_label = 'Independent cities (no province)' THEN pri.region_name = me.region_name
             ELSE pri.province_label = me.province_label END
    AND ({GEO_PRI} OR pri.city_mun_psgc_code = me.city_mun_psgc_code)
)"""
PR_PEERS = f"""WITH {PEER_AREA},
es AS (
  SELECT DISTINCT e.barangay_psgc_code FROM {G}.fact_school_enrollment AS e JOIN area USING (city_mun_psgc_code)
  WHERE e.sector = 'Public' AND e.psgc_match_status = 'matched' AND e.school_year = '2023-24'
    AND e.education_level_code = 'ES' AND e.is_offered AND e.learner_count > 0
),
bgy AS (
  SELECT b.city_mun_psgc_code, COUNT(*) AS barangays, COUNT_IF(es.barangay_psgc_code IS NULL) AS without_es
  FROM {G}.dim_barangay AS b JOIN area USING (city_mun_psgc_code)
  LEFT JOIN es ON es.barangay_psgc_code = b.barangay_psgc_code
  WHERE b.member_type = 'regular' GROUP BY b.city_mun_psgc_code
),
mc AS (
  SELECT e.city_mun_psgc_code, COUNT(DISTINCT e.school_id) AS schools,
         COUNT(DISTINCT CASE WHEN e.barangay_psgc_code IS NOT NULL THEN e.school_id END) AS matched
  FROM {G}.fact_school_enrollment AS e JOIN area USING (city_mun_psgc_code)
  WHERE e.sector = 'Public' AND e.psgc_match_status = 'matched' AND e.school_year = '2023-24'
  GROUP BY e.city_mun_psgc_code
),
pts AS (
  SELECT a.lgu_label AS label, CAST(a.population_2024 AS DOUBLE) AS x, CAST(a.enrolled_2024 AS DOUBLE) AS y,
         CASE WHEN a.is_selected THEN '{PEER_SERIES[0]}'
              WHEN a.comparable = 0 OR a.population_2020 IS NULL THEN '{PEER_SERIES[2]}' ELSE '{PEER_SERIES[1]}' END AS series,
         a.province_label, a.region_short, a.queue_status,
         {r0('a.population_2020')} AS population_2020_txt, {r0('a.population_2024')} AS population_2024_txt,
         CASE WHEN a.comparable = 0 THEN 'Not comparable' ELSE {change_txt('a.population_2024', 'a.population_2020')} END
           AS population_change_txt,
         {r0('a.enrolled_2020')} AS enrolled_2020_txt, {r0('a.enrolled_2024')} AS enrolled_2024_txt,
         {change_txt('a.enrolled_2024', 'a.enrolled_2020')} AS enrollment_change_txt, {r0('a.public_2024')} AS public_2024_txt,
         a.active_public_school_count AS size, {r0('a.active_public_school_count')} AS schools_txt,
         {r0('a.ap1_learners_per_public_school')} AS learners_per_school_txt,
         {r0('a.ap1_school_age_population_per_public_school')} AS children_per_school_txt,
         CASE WHEN bgy.barangays IS NULL THEN 'Not reported'
              ELSE format_number(bgy.without_es, 0) || ' of ' || format_number(bgy.barangays, 0) END AS barangays_txt,
         {cov('100.0 * mc.matched / NULLIF(mc.schools, 0)')} AS match_txt,
         CASE WHEN a.comparable = 1 AND a.population_2020 IS NOT NULL THEN 'Comparable 2020 to 2024'
              ELSE 'Not comparable: boundaries changed or a census year is missing' END AS comparability_txt
  FROM area AS a
  LEFT JOIN bgy ON bgy.city_mun_psgc_code = a.city_mun_psgc_code
  LEFT JOIN mc ON mc.city_mun_psgc_code = a.city_mun_psgc_code
  WHERE a.population_2024 IS NOT NULL AND a.enrolled_2024 IS NOT NULL
)
SELECT label, x, y, series, {", ".join(PEER_TIPS)} FROM pts
UNION ALL
{equal_line("pts", PEER_TIPS)}"""

# the direct label the chart cannot draw: the selected LGU's three values, abbreviated
PR_PEER_NOTE = f"""WITH {PEER_AREA}
SELECT city_mun_name || ': ' || COALESCE({abbrev('population_2024')} || ' resident children', 'resident children not reported')
       || ' · ' || COALESCE({abbrev('enrolled_2024')} || ' learners enrolled locally', 'enrollment not reported')
       || ' · ' || format_number(COALESCE(active_public_school_count, 0), 0) || ' active public schools ({SCHOOL_COUNT_YEAR})'
         AS peer_line
FROM area WHERE is_selected"""


def school_base(level_param=True):
    """Active and blank-count public schools in the selected LGU, SY 2023-24, with what to verify at each.

    A school is screened like the classroom-pressure measure does it: complete enrollment over more than zero reported
    rooms, at or above SCREEN learners per reported room. Every school gets a reason it is listed; one with no flag is
    listed by classroom-pressure order."""
    level = (f"CASE WHEN :level = '{ALL_LEVELS}' THEN NULL ELSE {LEVEL_CODE} END") if level_param else "CAST(NULL AS STRING)"
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
         SUM(COALESCE(sef_provincial_teacher_count, 0) + COALESCE(sef_city_municipal_teacher_count, 0)
             + COALESCE(lgu_funded_teacher_count, 0) + COALESCE(other_funded_teacher_count, 0)) AS locally_funded_teachers
  FROM {G}.fact_school_teacher_capacity WHERE school_year = '2023-24' GROUP BY school_id
),
x AS (
  SELECT s.school_id, COALESCE(ds.school_name, s.school_id) AS school_name, b.barangay_psgc_code,
         COALESCE(b.barangay_name, 'Barangay not matched') AS barangay_name,
         CASE WHEN s.annex_status = 'Annex/Extension School' THEN 'Annex' ELSE 'Main' END AS school_kind,
         concat_ws(' + ', CASE WHEN s.offers_es = 1 THEN 'ES' END, CASE WHEN s.offers_jhs = 1 THEN 'JHS' END,
                          CASE WHEN s.offers_shs = 1 THEN 'SHS' END) AS levels_offered,
         concat_ws(' + ', CASE WHEN s.offers_es = 1 THEN '{LEVELS[0]}' END, CASE WHEN s.offers_jhs = 1 THEN '{LEVELS[1]}' END,
                          CASE WHEN s.offers_shs = 1 THEN '{LEVELS[2]}' END) AS levels_offered_full,
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
         -- one flag per figure to verify; a flag means verify, not incorrect
         CASE WHEN s.incomplete_levels = 0 AND r.instructional_classrooms_total > 0
                   AND s.learners / CAST(r.instructional_classrooms_total AS DOUBLE) >= {SCREEN} THEN 1 ELSE 0 END AS f_above,
         CASE WHEN r.school_id IS NULL OR r.instructional_classrooms_total IS NULL THEN 1 ELSE 0 END AS f_rooms_missing,
         CASE WHEN r.instructional_classrooms_total = 0 THEN 1 ELSE 0 END AS f_rooms_zero,
         CASE WHEN s.incomplete_levels > 0 THEN 1 ELSE 0 END AS f_learners_missing,
         CASE WHEN (s.offers_es = 1 AND t.es_teachers IS NULL) OR (s.offers_jhs = 1 AND t.jhs_teachers IS NULL)
                   OR (s.offers_shs = 1 AND t.shs_teachers IS NULL) THEN 1 ELSE 0 END AS f_teachers_missing,
         CASE WHEN s.annex_status <> 'Annex/Extension School' AND ((s.offers_es = 1 AND t.es_teachers = 0)
                   OR (s.offers_jhs = 1 AND t.jhs_teachers = 0) OR (s.offers_shs = 1 AND t.shs_teachers = 0))
              THEN 1 ELSE 0 END AS f_teachers_zero
  FROM sch AS s
  LEFT JOIN {G}.dim_school AS ds ON ds.school_id = s.school_id
  LEFT JOIN {G}.dim_barangay AS b ON b.barangay_psgc_code = s.barangay_psgc_code AND b.member_type = 'regular'
  LEFT JOIN {G}.fact_school_classroom_capacity AS r ON r.school_id = s.school_id AND r.school_year = '2023-24'
  LEFT JOIN t ON t.school_id = s.school_id
  LEFT JOIN years AS y ON y.school_id = s.school_id
  WHERE s.is_active = 1 OR s.is_blank
),
z AS (
  SELECT x.*,
         f_above + f_rooms_missing + f_rooms_zero + f_learners_missing + f_teachers_missing + f_teachers_zero AS checks,
         -- a chosen level shows only its own ratio; the all-level ratio never stands in for a missing one
         CASE WHEN (SELECT level_code FROM lvl) IS NULL THEN learners_per_teacher
              ELSE learners_per_teacher_at_level END AS teacher_ratio,
         CASE WHEN f_above = 1 THEN '{STATUS_ORDER[0]}'
              WHEN f_rooms_missing = 1 OR f_learners_missing = 1 OR f_teachers_missing = 1 THEN '{STATUS_ORDER[1]}'
              WHEN f_rooms_zero = 1 OR f_teachers_zero = 1 THEN '{STATUS_ORDER[2]}'
              ELSE '{STATUS_ORDER[3]}' END AS status
  FROM x
),
schools AS (
  SELECT z.*, checks > 0 AS to_check,
         CASE WHEN checks > 0 THEN '{VERIFY[0]}' ELSE '{VERIFY[1]}' END AS verification_status,
         COALESCE(NULLIF(concat_ws('; ',
           CASE WHEN f_rooms_missing = 1 THEN 'Missing room count' END,
           CASE WHEN f_rooms_zero = 1 THEN 'Zero rooms reported' END,
           CASE WHEN f_learners_missing = 1 THEN 'Missing learner count' END,
           CASE WHEN f_teachers_missing = 1 THEN 'Missing teacher count' END,
           CASE WHEN f_teachers_zero = 1 THEN 'Zero teachers reported' END,
           CASE WHEN f_above = 1 THEN 'Above classroom screen' END), ''), 'Included by classroom-pressure order') AS why_listed,
         CASE WHEN f_rooms_missing = 1 OR f_rooms_zero = 1 THEN 'Verify reported room count'
              WHEN f_learners_missing = 1 THEN 'Verify enrollment by level'
              WHEN f_teachers_missing = 1 OR f_teachers_zero = 1 THEN 'Verify teacher count by level'
              WHEN f_above = 1 THEN 'Verify reported room count and enrollment'
              ELSE '{VERIFY[1]}' END AS verify_header,
         CASE WHEN f_rooms_missing = 1 OR f_rooms_zero = 1 THEN 'Ask the Schools Division Office for the room count'
              WHEN f_learners_missing = 1 THEN 'Confirm enrollment by level with the school'
              WHEN f_teachers_missing = 1 OR f_teachers_zero = 1 THEN 'Confirm teachers by level with the Schools Division Office'
              WHEN f_above = 1 THEN 'Confirm rooms in use and enrollment with the school'
              ELSE 'No figure to verify' END AS next_step,
         {r0('learners')} AS learners_txt,
         {r1('learners_per_room', 'Not assessable')} AS per_room_txt,
         {r1('teacher_ratio', 'Not assessable')} AS per_teacher_txt,
         CASE WHEN enrollment_change IS NULL THEN 'Incomplete trend' ELSE {signed('enrollment_change')} END AS change_txt,
         ROW_NUMBER() OVER (ORDER BY CASE WHEN checks > 0 THEN 0 ELSE 1 END,
                                     learners_per_room DESC NULLS LAST, school_name) AS list_order
  FROM z
)"""


BARANGAY = f"(:barangay = '{ALL_BARANGAYS}' OR barangay_name = :barangay)"

PR_BARANGAYS = f"""WITH {school_base(level_param=False)},
-- by PSGC code, since two barangays can share a name; a school counts for ES from its own ES learners, so a
-- missing count at another level never hides it
bs AS (
  SELECT barangay_psgc_code, COUNT(*) AS public_schools, MAX(CASE WHEN offers_es = 1 AND es_learners > 0 THEN 1 ELSE 0 END) AS has_es,
         SUM(learners) AS learners
  FROM schools WHERE barangay_psgc_code IS NOT NULL GROUP BY barangay_psgc_code
)
SELECT b.barangay_name,
       CASE upper(b.urban_rural) WHEN 'U' THEN 'Urban' WHEN 'R' THEN 'Rural' ELSE COALESCE(b.urban_rural, 'Not reported') END
         AS urban_rural,
       COALESCE(bs.public_schools, 0) AS public_schools, format_number(COALESCE(bs.public_schools, 0), 0) AS public_schools_txt,
       CASE WHEN COALESCE(bs.has_es, 0) = 1 THEN 'Yes' ELSE 'No' END AS public_es,
       COALESCE(bs.learners, 0) AS learners, format_number(COALESCE(bs.learners, 0), 0) AS learners_txt,
       CASE WHEN COALESCE(bs.has_es, 0) = 1 THEN 1 ELSE 0 END AS es_sort
FROM {G}.dim_barangay AS b
JOIN sel ON sel.city_mun_psgc_code = b.city_mun_psgc_code
LEFT JOIN bs ON bs.barangay_psgc_code = b.barangay_psgc_code
WHERE b.member_type = 'regular' AND {BARANGAY.replace('barangay_name', 'b.barangay_name')}
ORDER BY es_sort, learners DESC, b.barangay_name"""

# school points: only locations inside the matched city or municipality boundary are plotted
LOCATIONS = f"""loc AS (
  SELECT s.*, l.latitude, l.longitude, COALESCE(l.boundary_status, 'no_usable_point') AS boundary_status
  FROM schools AS s LEFT JOIN {G}.dim_school_location AS l ON l.school_id = s.school_id
  WHERE {BARANGAY}
)"""
PR_MAP = f"""WITH {school_base(level_param=False)},
{LOCATIONS}
SELECT school_name, school_id, barangay_name, school_kind, levels_offered_full, learners_txt, per_room_txt, per_teacher_txt,
       verification_status, why_listed, 'Inside the LGU boundary' AS location_status, latitude, longitude,
       CASE WHEN to_check THEN '{VERIFY[0]}' ELSE 'Other schools' END AS map_series
FROM loc
WHERE boundary_status = 'inside'"""
PR_MAP_NOTE = f"""WITH {school_base(level_param=False)},
{LOCATIONS}
SELECT CASE WHEN COUNT(*) = 0 THEN 'No matching schools' ELSE
       'Mapped ' || format_number(COUNT_IF(boundary_status = 'inside'), 0) || ' of ' || format_number(COUNT(*), 0)
       || ' public schools in view'
       || CASE WHEN COUNT_IF(boundary_status = 'outside') > 0
               THEN ' · ' || format_number(COUNT_IF(boundary_status = 'outside'), 0) || ' outside the LGU boundary (locations to verify)'
               ELSE '' END
       || CASE WHEN COUNT_IF(boundary_status = 'no_usable_point') > 0
               THEN ' · ' || format_number(COUNT_IF(boundary_status = 'no_usable_point'), 0) || ' with no usable coordinates'
               ELSE '' END
       || CASE WHEN COUNT_IF(boundary_status IN ('no_matched_city', 'no_boundary')) > 0
               THEN ' · ' || format_number(COUNT_IF(boundary_status IN ('no_matched_city', 'no_boundary')), 0)
                    || ' with a boundary not validated'
               ELSE '' END END AS map_line
FROM loc"""

PR_TEASER = f"""WITH {school_base(level_param=False)}
SELECT school_name, barangay_name, per_room_txt, verification_status, why_listed, next_step
FROM schools
WHERE list_order <= 5
ORDER BY list_order"""

# ============================================================ 3 School Action
PICK = """pick AS (
  SELECT school_id FROM schools
  WHERE offers_level = 1
  ORDER BY CASE WHEN school_name || ' · ' || school_id = :school THEN 0 ELSE 1 END, list_order
  LIMIT 1
)"""

SA_SCHOOL = f"""WITH {school_base()},
{PRI_CTE},
{PICK}
SELECT s.school_name, s.school_id, s.verify_header,
       'ID ' || s.school_id || ' · ' || s.barangay_name || ' · ' || s.school_kind || ' · ' || s.levels_offered
         || ' · ' || s.learners_txt || ' learners, SY 2023-24 · LGU review status: ' || st.queue_status
         || CASE WHEN :school <> '{FIRST_SCHOOL}' AND s.school_name || ' · ' || s.school_id <> :school
                 THEN ' · your school is outside the filters, so this is the first school to verify' ELSE '' END AS details,
       {measure('s.learners_per_room', 1, '', 'Not assessable')} AS room_kpi,
       -- the teacher figure carries only the chosen level's comparison point
       CASE WHEN s.teacher_ratio IS NULL THEN 'Not assessable'
            ELSE format_number(s.teacher_ratio, 1) || CASE (SELECT level_code FROM lvl) {TEACHER_REF_TXT} ELSE '' END
            END AS teacher_kpi,
       CASE WHEN s.enrollment_change IS NULL THEN 'Incomplete' ELSE s.change_txt END AS change_kpi,
       CASE WHEN s.checks = 1 THEN '1 verification item'
            WHEN s.checks > 1 THEN format_number(s.checks, 0) || ' verification items' ELSE 'None' END AS verify_kpi
FROM schools AS s
JOIN pick USING (school_id)
CROSS JOIN (SELECT pri.queue_status FROM pri JOIN sel USING (city_mun_psgc_code)) AS st"""

# learners against reported rooms; a dotted line of points marks 50 learners per room (a scatter has no diagonal)
SA_PEERS = f"""WITH {school_base()},
{PICK},
pts AS (
  SELECT s.school_name, CAST(s.learners AS DOUBLE) AS learners, CAST(s.rooms AS DOUBLE) AS rooms, s.teachers,
         CASE WHEN s.school_id = (SELECT school_id FROM pick) THEN '{SCHOOL_SERIES[0]}'
              WHEN s.f_above = 1 THEN '{SCHOOL_SERIES[1]}' WHEN s.to_check THEN '{SCHOOL_SERIES[2]}'
              ELSE '{SCHOOL_SERIES[3]}' END AS series
  FROM schools AS s
  WHERE s.offers_level = 1 AND s.learners IS NOT NULL AND s.rooms IS NOT NULL
)
SELECT * FROM pts
UNION ALL
SELECT '{SCHOOL_SERIES[4]}', g.i * m.top / 40.0, g.i * m.top / 40.0 / {SCREEN}, 0, '{SCHOOL_SERIES[4]}'
FROM (SELECT MAX(learners) AS top FROM pts) AS m CROSS JOIN (VALUES {LINE_STEPS}) AS g(i)
WHERE m.top IS NOT NULL"""

# the selected school's room and teacher figures against their references, on one scale (100% = the reference)
SA_BULLET = f"""WITH {school_base()},
{PICK},
s AS (SELECT schools.* FROM schools JOIN pick USING (school_id)),
refs AS (SELECT * FROM (VALUES {TEACHER_REF_ROWS}) AS r(code, ord, reference)),
lv AS (
  SELECT 'ES' AS code, offers_es AS offered, es_learners AS learners, es_teachers AS teachers FROM s
  UNION ALL SELECT 'JHS', offers_jhs, jhs_learners, jhs_teachers FROM s
  UNION ALL SELECT 'SHS', offers_shs, shs_learners, shs_teachers FROM s
),
lt AS (
  SELECT r.ord, {LEVEL_LABEL.format(c='lv.code')} AS level, r.reference,
         lv.learners / NULLIF(CAST(lv.teachers AS DOUBLE), 0) AS ratio
  FROM lv JOIN refs AS r ON r.code = lv.code
  WHERE lv.offered = 1 AND ((SELECT level_code FROM lvl) IS NULL OR lv.code = (SELECT level_code FROM lvl))
)
SELECT 0 AS ord, 'Learners per reported room · ' || {measure('learners_per_room', 1, f' vs {SCREEN}', 'not assessable')} AS figure,
       learners_per_room / {SCREEN}.0 AS share_of_reference,
       CASE WHEN learners_per_room IS NULL THEN '{LEVEL_STATUS[2]}' WHEN learners_per_room >= {SCREEN} THEN '{LEVEL_STATUS[0]}'
            ELSE '{LEVEL_STATUS[1]}' END AS status
FROM s
UNION ALL
SELECT ord, 'Learners per ' || lower(level) || ' teacher · '
         || CASE WHEN ratio IS NULL THEN 'not assessable' ELSE format_number(ratio, 1) || ' vs ' || format_number(reference, 1) END,
       ratio / reference,
       CASE WHEN ratio IS NULL THEN '{LEVEL_STATUS[2]}' WHEN ratio > reference THEN '{LEVEL_STATUS[0]}' ELSE '{LEVEL_STATUS[1]}' END
FROM lt
ORDER BY ord"""

# nearby public schools (within about 3 km) around the selected school's validated location
SA_LOCATION = f"""WITH {school_base()},
{PICK},
here AS (
  SELECT l.latitude, l.longitude FROM pick JOIN {G}.dim_school_location AS l ON l.school_id = pick.school_id
  WHERE l.boundary_status = 'inside'
)
SELECT s.school_name, s.levels_offered_full, l.latitude, l.longitude,
       CASE WHEN s.school_id = (SELECT school_id FROM pick) THEN 'Selected school' ELSE 'Nearby public schools' END AS series
FROM schools AS s
JOIN {G}.dim_school_location AS l ON l.school_id = s.school_id
CROSS JOIN here
WHERE l.boundary_status = 'inside' AND abs(l.latitude - here.latitude) <= 0.03 AND abs(l.longitude - here.longitude) <= 0.03"""

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
  SELECT 1 AS ord, '{LEVELS[0]}' AS level, offers_es AS offered, es_learners AS learners, es_teachers AS teachers FROM s
  UNION ALL SELECT 2, '{LEVELS[1]}', offers_jhs, jhs_learners, jhs_teachers FROM s
  UNION ALL SELECT 3, '{LEVELS[2]}', offers_shs, shs_learners, shs_teachers FROM s
)
-- rooms are reported for the whole school, so a level row shows a dash, not a count
SELECT ord, level, {r0('learners')} AS learners, {r0('teachers')} AS teachers,
       {r1('learners / NULLIF(CAST(teachers AS DOUBLE), 0)', 'Not assessable')} AS learners_per_teacher,
       '—' AS classrooms, '—' AS temporary_rooms, '—' AS makeshift_rooms
FROM lv WHERE offered = 1
UNION ALL
SELECT 4, 'Whole school', learners_txt, format_number(teachers, 0), {r1('learners_per_teacher', 'Not assessable')},
       {r0('rooms')}, {r0('temporary_learning_spaces')}, {r0('makeshift_rooms')}
FROM s
ORDER BY ord"""

# one row per figure to verify, each with a concrete next step
SA_VERIFY = f"""WITH {school_base()},
{PICK},
s AS (SELECT schools.* FROM schools JOIN pick USING (school_id))
SELECT 1 AS ord, 'Reported room count' AS item, 'No instructional room count is reported' AS why,
       'Ask the Schools Division Office for the room count in the latest facilities report' AS next_step
FROM s WHERE f_rooms_missing = 1
UNION ALL SELECT 2, 'Reported room count', '0 instructional rooms reported while learners are enrolled',
       'Confirm the rooms in use with the school' FROM s WHERE f_rooms_zero = 1
UNION ALL SELECT 3, 'Enrollment total', 'An offered level has no learner count',
       'Confirm enrollment by level with the school' FROM s WHERE f_learners_missing = 1
UNION ALL SELECT 4, 'Teacher count',
       'No teacher count for ' || concat_ws(', ', CASE WHEN offers_es = 1 AND es_teachers IS NULL THEN '{LEVELS[0]}' END,
                                                  CASE WHEN offers_jhs = 1 AND jhs_teachers IS NULL THEN '{LEVELS[1]}' END,
                                                  CASE WHEN offers_shs = 1 AND shs_teachers IS NULL THEN '{LEVELS[2]}' END),
       'Confirm teachers by level with the Schools Division Office' FROM s WHERE f_teachers_missing = 1
UNION ALL SELECT 5, 'Teacher count', '0 teachers reported at an offered level',
       'Confirm teachers by level with the Schools Division Office' FROM s WHERE f_teachers_zero = 1
UNION ALL SELECT 6, 'Classroom pressure',
       'Learners per reported room is ' || format_number(learners_per_room, 1) || ', at or above the screen of {SCREEN}',
       'Confirm rooms in use and enrollment with the school before planning' FROM s WHERE f_above = 1
UNION ALL SELECT 7, '{VERIFY[1]}', 'Every figure is reported and the school is below the classroom screen',
       'No action needed' FROM s WHERE checks = 0
ORDER BY ord"""

SCHOOL_FILTERS = (f"{BARANGAY} AND offers_level = 1"
                  f" AND (:school_status = '{ALL_SCHOOLS}' OR (:school_status = '{VERIFY[0]}' AND to_check)"
                  f" OR status = :school_status)")
SA_LIST = f"""WITH {school_base()}
SELECT list_order, school_name, school_id, barangay_name, levels_offered, levels_offered_full, per_room_txt, per_teacher_txt,
       verification_status, why_listed, next_step,
       learners, learners_per_room, teacher_ratio, enrollment_change, temporary_or_makeshift_rooms, locally_funded_teachers,
       school_kind, status
FROM schools
WHERE {SCHOOL_FILTERS}
ORDER BY list_order"""

# ============================================================ 4 Data & Method
FRESHNESS = f"""WITH runs AS (
  SELECT MAX(finished_at_utc) AS last_run FROM edu_access.`01-control`.pipeline_runs WHERE status = 'succeeded'
),
years AS (
  SELECT MIN(CASE WHEN source_id = 'deped_enrollment' AND has_data THEN school_year END) AS first_enrollment,
         MAX(CASE WHEN source_id = 'deped_enrollment' AND has_data THEN school_year END) AS last_enrollment,
         MAX(CASE WHEN source_id IN ('deped_facilities', 'deped_personnel') AND has_data THEN school_year END) AS last_capacity
  FROM {G}.fact_school_year_source_availability
),
checks AS (
  SELECT COUNT(*) AS checks, COUNT_IF(status = 'FAIL') AS failed
  FROM (
    SELECT status FROM edu_access.`01-control`.data_quality_results
    QUALIFY ROW_NUMBER() OVER (PARTITION BY layer, table_name, check_name ORDER BY checked_at_utc DESC) = 1
  ) AS latest
)
SELECT COALESCE(CAST(CAST(runs.last_run AS DATE) AS STRING), 'Not available') AS updated,
       'Publication status: '
         || CASE WHEN checks.checks = 0 THEN 'No checks recorded' WHEN checks.failed > 0 THEN 'Needs attention' ELSE 'Ready' END
         || ' · enrollment SY ' || COALESCE(years.first_enrollment, 'not available') || ' to SY '
         || COALESCE(years.last_enrollment, 'not available')
         || ' · classrooms and teachers SY ' || COALESCE(years.last_capacity, 'not available')
         || ' · check counts are on the engineering data-quality dashboard' AS health_line
FROM runs CROSS JOIN years CROSS JOIN checks"""

DM_KPI = f"""WITH {PRI},
k AS (
  SELECT COUNT(*) AS lgus,
         COUNT_IF(COALESCE(ap2_assessed, FALSE)) AS classroom_assessed,
         COUNT_IF(COALESCE(ap3_assessed, FALSE)) AS teacher_assessed,
         COUNT_IF(levels_offered > 0) AS offering,
         COUNT_IF(growing_enrollment IS NOT NULL) AS trends_comparable,
         COUNT_IF(queue_status = '{QUEUE[5]}') AS data_review
  FROM pri
  WHERE {GEO}
)
SELECT k.*,
       format_number(classroom_assessed, 0) || ' of ' || format_number(lgus, 0) AS classroom_kpi,
       format_number(teacher_assessed, 0) || ' of ' || format_number(offering, 0) AS teacher_kpi,
       format_number(trends_comparable, 0) || ' of ' || format_number(lgus, 0) AS trend_kpi,
       -- why this page's counts differ from the Overview's: an LGU keeps a review status when one measure is not
       -- fully assessed but another shows pressure
       CASE WHEN data_review = 0 THEN 'No LGU in this scope requires data review.'
            ELSE format_number(data_review, 0) || CASE WHEN data_review = 1 THEN ' LGU requires' ELSE ' LGUs require' END
                 || ' data review; the other ' || format_number(lgus - data_review, 0)
                 || ' have a review status, some with one measure not fully assessed.' END AS alert_line
FROM k"""

AP4_STATUS = ["Complete and comparable", "An incomplete school year", "Boundaries changed 2020 to 2024"]
AP4_INCOMPLETE = f"""ap4_complete AS (
  SELECT city_mun_psgc_code, MAX(CASE WHEN schools_incomplete > 0 THEN 1 ELSE 0 END) AS incomplete,
         MIN(CASE WHEN is_2020_2024_geography_comparable THEN 1 ELSE 0 END) AS comparable
  FROM {A}.ap4_enrollment_trend WHERE member_type = 'regular' GROUP BY city_mun_psgc_code
)"""
DM_AP4 = f"""WITH {LGU},
{AP4_INCOMPLETE}
SELECT CASE WHEN c.incomplete = 1 THEN '{AP4_STATUS[1]}' WHEN c.comparable = 0 THEN '{AP4_STATUS[2]}'
            ELSE '{AP4_STATUS[0]}' END AS ap4_status,
       COUNT(*) AS lgus
FROM lgu AS l JOIN ap4_complete AS c ON c.city_mun_psgc_code = l.city_mun_psgc_code
WHERE {GEO_L}
GROUP BY 1"""

def literal_rows(rows, columns):
    body = ",\n  ".join("(" + ", ".join("'" + str(v).replace("'", "''") + "'" for v in r) + ")" for r in rows)
    return f"SELECT * FROM (VALUES\n  {body}) AS r({', '.join(columns)})"


def references():
    """The comparison points as published in config/analytics_benchmarks.json, one row each."""
    ap2, ap3 = BENCHMARKS["ap2"], BENCHMARKS["ap3"]
    def derived(text):
        return "Derived: " + text.replace(" * ", " × ").replace(" / ", " ÷ ")

    rows = [("Classroom pressure", "School learners per reported room", f"{ap2['threshold']:g} or more",
             ap2["label"], "Sets the classroom-pressure signal"),
            (f"Teacher pressure · {LEVELS[0]}", "Learners per reported teacher",
             f"More than {ap3['es_max_learners_per_teacher']:g}", ap3["es_label"].capitalize(),
             "Sets the teacher-pressure signal"),
            (f"Teacher pressure · {LEVELS[1]}", "Learners per reported teacher",
             f"More than {ap3['jhs_max_learners_per_teacher']:g}", derived(ap3["jhs_derivation"]),
             "Sets the teacher-pressure signal"),
            (f"Teacher pressure · {LEVELS[2]}", "Learners per reported teacher", "More than 26.7",
             derived(ap3["shs_derivation"]), "Sets the teacher-pressure signal"),
            ("School network context", "Learners per public school", "None", "No published comparison point",
             "Context only")]
    return literal_rows(rows, ["measure", "unit", "comparison_point", "basis", "use_in_dashboard"])


DM_REFS = references()

# how each planning status is assigned, in plain language
DM_RULES = literal_rows([
    (QUEUE[0], STATUS_LABELS[0], "Classroom and teacher", "Yes"),
    (QUEUE[1], STATUS_LABELS[1], "Classroom and teacher", "No or not comparable"),
    (QUEUE[1], STATUS_LABELS[1], "Classroom or teacher", "Yes"),
    (QUEUE[2], STATUS_LABELS[2], "Classroom or teacher", "No or not comparable"),
    (QUEUE[3], STATUS_LABELS[3], "None", "Yes"),
    (QUEUE[4], STATUS_LABELS[4], "None, both assessed", "No"),
    (QUEUE[5], STATUS_LABELS[5], "None known", "Coverage or growth incomplete")],
    ["review_status", "planning_status", "pressure_signals", "enrollment_growing"])

COVERAGE_STATUS = ["Assessed (90% or more)", "Incomplete (under 90%)", "Unavailable"]
COVERAGE_COLORS = [{"value": COVERAGE_STATUS[0], "color": "#A9B4BF"}, {"value": COVERAGE_STATUS[1], "color": "#C9A227"},
                   {"value": COVERAGE_STATUS[2], "color": "#5B6B7A"}]
AP4_COLORS = [{"value": "Complete and comparable", "color": "#A9B4BF"},
              {"value": "An incomplete school year", "color": "#C9A227"},
              {"value": "Boundaries changed 2020 to 2024", "color": "#5B6B7A"}]
REASON_COLORS = [{"value": REASON_MEASURES[0], "color": "#5B6B7A"}, {"value": REASON_MEASURES[1], "color": "#A9B4BF"},
                 {"value": REASON_MEASURES[2], "color": "#C9A227"}]
COVERAGE_MEASURES = [MEASURES[0], MEASURES[1]] + [f"{MEASURES[2]} · {level}" for level in LEVELS]
DM_COVERAGE = f"""WITH {PRI},
c AS (
  SELECT '{COVERAGE_MEASURES[0]}' AS measure, ap1_coverage_pct AS coverage FROM pri WHERE {GEO}
  UNION ALL SELECT '{COVERAGE_MEASURES[1]}', ap2_learner_coverage_pct FROM pri WHERE {GEO}
  UNION ALL SELECT '{COVERAGE_MEASURES[2]}', es_learner_coverage_pct FROM pri WHERE es_offered_school_count > 0 AND {GEO}
  UNION ALL SELECT '{COVERAGE_MEASURES[3]}', jhs_learner_coverage_pct FROM pri WHERE jhs_offered_school_count > 0 AND {GEO}
  UNION ALL SELECT '{COVERAGE_MEASURES[4]}', shs_learner_coverage_pct FROM pri WHERE shs_offered_school_count > 0 AND {GEO}
),
b AS (
  SELECT measure,
         CASE WHEN coverage IS NULL THEN '{COVERAGE_STATUS[2]}' WHEN coverage < 90 THEN '{COVERAGE_STATUS[1]}'
              ELSE '{COVERAGE_STATUS[0]}' END AS coverage_status
  FROM c
  WHERE (:measure = '{ALL_MEASURES}' OR measure = :measure OR (measure LIKE '{MEASURES[2]}%' AND :measure = '{MEASURES[2]}'))
)
SELECT measure, coverage_status, COUNT(*) AS lgus, COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY measure) AS share
FROM b
GROUP BY measure, coverage_status"""

DM_REASONS = f"""WITH {PRI},
-- the data review LGUs only, by the input that could not be checked
r AS (
  SELECT '{REASON_MEASURES[0]}' AS measure, a.not_assessed_reason AS reason
  FROM pri JOIN {A}.ap2_classroom_pressure AS a USING (city_mun_psgc_code) WHERE pri.queue_status = '{QUEUE[5]}' AND {GEO_PRI}
  UNION ALL SELECT '{REASON_MEASURES[1]}', a.not_assessed_reason
  FROM pri JOIN {A}.ap3_teacher_pressure AS a USING (city_mun_psgc_code) WHERE pri.queue_status = '{QUEUE[5]}' AND {GEO_PRI}
  UNION ALL SELECT '{REASON_MEASURES[2]}', growth_not_assessed_reason FROM pri WHERE queue_status = '{QUEUE[5]}' AND {GEO}
)
SELECT measure, {REASON.format(c='reason')} AS reason, COUNT(*) AS lgus
FROM r
WHERE reason IS NOT NULL AND (:measure = '{ALL_MEASURES}' OR measure = :measure)
GROUP BY 1, 2"""

SHARE_BANDS = ["No school above the screen", "Under 10%", "10-25%", "25-50%", "50% or more"]
DM_SHARE = f"""WITH {PRI}
SELECT CASE WHEN COALESCE(ap2_affected_learners, 0) = 0 THEN '{SHARE_BANDS[0]}'
            WHEN ap2_affected_learner_share_pct < 10 THEN '{SHARE_BANDS[1]}'
            WHEN ap2_affected_learner_share_pct < 25 THEN '{SHARE_BANDS[2]}'
            WHEN ap2_affected_learner_share_pct < 50 THEN '{SHARE_BANDS[3]}' ELSE '{SHARE_BANDS[4]}' END AS share_band,
       COUNT(*) AS lgus
FROM pri
WHERE ap2_assessed AND {GEO}
GROUP BY 1"""

DM_TEACHER_LEVELS = f"""WITH {PRI},
lv AS (
  SELECT '{LEVELS[0]}' AS level, es_offered_school_count AS offered, ap3_es_learners_per_teacher AS ratio,
         es_benchmark_max_learners_per_teacher AS reference FROM pri WHERE {GEO}
  UNION ALL SELECT '{LEVELS[1]}', jhs_offered_school_count, ap3_jhs_learners_per_teacher, jhs_benchmark_max_learners_per_teacher
  FROM pri WHERE {GEO}
  UNION ALL SELECT '{LEVELS[2]}', shs_offered_school_count, ap3_shs_learners_per_teacher, shs_benchmark_max_learners_per_teacher
  FROM pri WHERE {GEO}
)
SELECT level, CASE WHEN ratio IS NULL THEN '{LEVEL_STATUS[2]}' WHEN ratio > reference THEN '{LEVEL_STATUS[0]}'
                   ELSE '{LEVEL_STATUS[1]}' END AS status,
       COUNT(*) AS lgus, COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY level) AS share
FROM lv
WHERE offered > 0
GROUP BY 1, 2"""

# one row per source, one column per school year: Available or Not available
SOURCE_YEARS = [y.removeprefix("SY ") for y in SCHOOL_YEARS]
DM_SOURCES = f"""SELECT source, """ + ",\n       ".join(
    f"CASE WHEN MAX(CASE WHEN school_year = '{y}' AND has_data THEN 1 ELSE 0 END) = 1 THEN 'Available' "
    f"ELSE 'Not available' END AS sy_{y.replace('-', '_')}" for y in SOURCE_YEARS) + f"""
FROM (
  SELECT school_year, has_data,
         CASE source_id WHEN 'deped_enrollment' THEN 'Enrollment' WHEN 'deped_facilities' THEN 'Classrooms (facilities)'
              WHEN 'deped_personnel' THEN 'Teachers (personnel)' ELSE source_id END AS source
  FROM {G}.fact_school_year_source_availability
) AS a
GROUP BY source
ORDER BY source"""

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
  UNION ALL SELECT school_name || ' · ' || school_id, 1 FROM schools WHERE offers_level = 1
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
SCHOOL_P = LGU_P + ["level", "school"]


def datasets(b):
    b.dataset("ov_lgu", "Overview: LGU review queue", OV_LGU, OV_P)
    b.dataset("ov_top", "Overview: top LGUs to review", OV_TOP, OV_P)
    b.dataset("ov_map", "Overview: LGU boundaries", OV_MAP, OV_P)
    b.dataset("ov_map_note", "Overview: map coverage", OV_MAP_NOTE, OV_P)
    b.dataset("ov_kpi", "Overview: KPIs", OV_KPI, OV_P)
    b.dataset("ov_signals", "Overview: what drives priority", OV_SIGNALS, OV_P)
    b.dataset("ov_region", "Overview: review status by region", OV_REGION, OV_P)
    b.dataset("ov_type", "Overview: review status by LGU type", OV_TYPE, OV_P)
    b.dataset("ov_region_bubble", "Overview: children, enrollment and schools by region", OV_REGION_BUBBLE, OV_P)
    b.dataset("ov_insufficient", "Overview: data review LGUs", OV_INSUFFICIENT, OV_P)
    b.dataset("pr_card", "LGU Profile: selected LGU", PR_CARD, LGU_P)
    b.dataset("pr_decision", "LGU Profile: why this LGU has this status", PR_DECISION, LGU_P)
    b.dataset("pr_evidence", "LGU Profile: measures and comparison points", PR_EVIDENCE, LGU_P)
    b.dataset("pr_reliability", "LGU Profile: data coverage and checks", PR_RELIABILITY, LGU_P)
    b.dataset("pr_teachers", "LGU Profile: teachers by level", PR_TEACHERS, LGU_P)
    b.dataset("pr_enrollment", "LGU Profile: enrollment over time", PR_ENROLLMENT, LGU_P)
    b.dataset("pr_census", "LGU Profile: resident children and local enrollment", PR_CENSUS, LGU_P)
    b.dataset("pr_cohorts", "LGU Profile: school-age population change", PR_COHORTS, LGU_P)
    b.dataset("pr_peers", "LGU Profile: the LGU in its comparison area", PR_PEERS, LGU_P)
    b.dataset("pr_peer_note", "LGU Profile: the selected LGU's label", PR_PEER_NOTE, LGU_P)
    b.dataset("pr_barangays", "LGU Profile: barangay access", PR_BARANGAYS, LGU_P + ["barangay"])
    b.dataset("pr_map", "LGU Profile: school locations", PR_MAP, LGU_P + ["barangay"])
    b.dataset("pr_map_note", "LGU Profile: school location coverage", PR_MAP_NOTE, LGU_P + ["barangay"])
    b.dataset("pr_teaser", "LGU Profile: schools to validate first", PR_TEASER, LGU_P)
    b.dataset("sa_school", "School Action: selected school", SA_SCHOOL, SCHOOL_P)
    b.dataset("sa_bullet", "School Action: figures against their references", SA_BULLET, SCHOOL_P)
    b.dataset("sa_peers", "School Action: schools in the LGU", SA_PEERS, SCHOOL_P)
    b.dataset("sa_location", "School Action: school location", SA_LOCATION, SCHOOL_P)
    b.dataset("sa_trend", "School Action: enrollment by level", SA_TREND, SCHOOL_P)
    b.dataset("sa_rooms", "School Action: reported rooms and teachers", SA_ROOMS, SCHOOL_P)
    b.dataset("sa_verify", "School Action: what to verify", SA_VERIFY, SCHOOL_P)
    b.dataset("sa_list", "School Action: school validation list", SA_LIST, LGU_P + ["barangay", "level", "school_status"])
    b.dataset("freshness", "Data & Method: freshness and publication status", FRESHNESS)
    b.dataset("dm_kpi", "Data & Method: KPIs", DM_KPI, GEO_P)
    b.dataset("dm_rules", "Data & Method: how the review status is assigned", DM_RULES)
    b.dataset("dm_ap4", "Data & Method: enrollment trend availability", DM_AP4, GEO_P)
    b.dataset("dm_refs", "Data & Method: published comparison points", DM_REFS)
    b.dataset("dm_coverage", "Data & Method: coverage by measure", DM_COVERAGE, GEO_P + ["measure"])
    b.dataset("dm_reasons", "Data & Method: why LGUs need data review", DM_REASONS, GEO_P + ["measure"])
    b.dataset("dm_share", "Data & Method: how concentrated classroom pressure is", DM_SHARE, GEO_P)
    b.dataset("dm_teacher_levels", "Data & Method: teacher-pressure assessment by level", DM_TEACHER_LEVELS, GEO_P)
    b.dataset("dm_sources", "Data & Method: source years", DM_SOURCES)
    b.dataset("opt_region", "Filter: region", OPT_REGION)
    b.dataset("opt_province", "Filter: province", OPT_PROVINCE, ["region"])
    b.dataset("opt_type", "Filter: LGU type", values("lgu_type_option", [ALL_TYPES, "City", "Municipality"]))
    b.dataset("opt_queue", "Filter: priority status", values("queue_option", [ALL_QUEUE] + QUEUE))
    b.dataset("opt_coverage", "Filter: data readiness", values("coverage_option", [ALL_COVERAGE] + READINESS))
    b.dataset("opt_lgu", "Filter: city or municipality", OPT_LGU, GEO_P)
    b.dataset("opt_barangay", "Filter: barangay (LGU Profile)", OPT_BARANGAY, LGU_P)
    b.dataset("opt_barangay_school", "Filter: barangay (School Action)", OPT_BARANGAY, LGU_P)
    b.dataset("opt_level", "Filter: education level", values("level_option", [ALL_LEVELS] + LEVELS))
    b.dataset("opt_status", "Filter: school status", values("status_option", [ALL_SCHOOLS, VERIFY[0]] + STATUS_ORDER))
    b.dataset("opt_school", "Filter: school", OPT_SCHOOL, LGU_P + ["level"])
    b.dataset("opt_measure", "Filter: measure",
              values("measure_option", [ALL_MEASURES] + MEASURES + [REASON_MEASURES[2]]))


# ------------------------------------------------------------------------------------------ pages


def status_share_bar(b, dataset, title, category, label, value, order, desc, raw=False):
    """A 100% stacked horizontal bar: each row's LGUs split by review status in the priority colours."""
    return bar(b, dataset, title, category, label, "sum", value, "Share of LGUs", color="queue_status",
               color_label="Review status", mappings=QUEUE_COLORS, order=order, color_order=QUEUE, fmt=pct(0),
               layout="stack", legend=LEGEND_BOTTOM, desc=desc, raw=raw,
               sort_by="natural-order" if raw else None)


def overview(b):
    p = Page("overview", "National Overview")
    targets = [n for n in b.params if n.startswith("ov_")]
    intro = text(b, "# Where should the Local School Board review first?\n", "\n",
                 "Prioritizes cities and municipalities for validation using classroom pressure, teacher pressure, "
                 "enrollment direction, and data completeness. It does not prescribe staffing, construction, or funding.")
    queue = param_filter(b, "queue", "Review status", targets, "Show LGUs with the selected review status.")
    coverage = param_filter(b, "coverage", "Data readiness", targets,
                            "Separate assessed LGUs from LGUs with insufficient data.")
    p.columns([(8, [(intro, 3)]), (4, [(queue, 1), (coverage, 1)])], 3)
    p.row([(kpi(b, "ov_kpi", "LGUs requiring immediate joint review", "joint_kpi", None, desc="Immediate joint review · of LGUs with a status",
                style=KPI_STYLE), 3),
           (kpi(b, "ov_kpi", "LGUs with a current pressure signal", "any_kpi", None, desc="Priority 1 to 3, of LGUs with a status",
                style=KPI_STYLE), 3),
           (kpi(b, "ov_kpi", "Learners above classroom screen", "learners_kpi", None,
                desc="Share of public learners, SY 2023-24", style=KPI_STYLE), 3),
           (kpi(b, "ov_kpi", "LGUs requiring data review", "data_review_kpi", None, desc="Insufficient data to assess, of all LGUs",
                style=KPI_STYLE), 3)], 3)
    queue_map = choropleth(
        b, "ov_map", "Planning priority across the Philippines", "queue_status", "Review status",
        [("lgu_label", "City or municipality"), ("queue_status", "Review status"),
         ("ap2_affected_learners", "Learners in screened schools")], QUEUE_COLORS, QUEUE,
        "Each LGU is coloured by its priority category. A missing area has no published boundary, not no pressure.",
        legend=LEGEND_BOTTOM)
    map_note = note(b, "ov_map_note", "Map coverage", "map_line", style=LINE_STYLE, show_title=False)
    top = table(b, "ov_top", "Top LGUs to review", [
        ("rank_in_view", "#", None), ("city_mun_name", "City or municipality", None),
        ("affected_txt", "Affected learners", None)],
        "The first ten LGUs in view, in the published review order.")
    p.columns([(8, [(queue_map, 10), (map_note, 1)]), (4, [(top, 11)])], 11)
    p.row([(status_share_bar(b, "ov_region", "Review status by region", "region_short", "Region", "share_of_region",
                             None, "Each region's LGUs by review status, regions with the most Priority 1 and 2 first.",
                             raw=True), 6),
           (table(b, "ov_signals", "What is driving priority?", [
               ("classroom_signal", "Classroom pressure", None, badges(SIGNAL_BADGES, WHITE)),
               ("teacher_signal", "Teacher pressure", None, badges(SIGNAL_BADGES, WHITE)),
               ("lgus", "LGUs", None), ("growing", "Growing enrollment", None),
               ("resulting_status", "Review status", None, badges(RESULT_BADGES, WHITE))],
               "LGUs by the two pressure signals, how many also have growing public enrollment, and the review status "
               "that results."), 6)], 8)
    p.row([(table(b, "ov_lgu", "LGU review queue", [
        ("rank_in_view", "#", None), ("city_mun_name", "City or municipality", None),
        ("province_label", "Province", None), ("region_short", "Region", None),
        ("queue_status", "Review status", None), ("status_label", "Planning status", None),
        ("pressure_signals", "Pressure signals", None), ("affected_txt", "Affected learners", None),
        ("data_readiness", "Data readiness", None)],
        "Orders LGUs for validation using classroom pressure, teacher pressure, enrollment direction, affected "
        "learners, and data readiness. A review order, not a performance rank, shortage, or allocation. Open LGU "
        "Profile and choose an LGU to see its evidence."), 12)], 10)
    p.row([(table(b, "ov_insufficient", "LGUs requiring data review", [
               ("city_mun_name", "City or municipality", None), ("region_short", "Region", None),
               ("not_assessed_reason_txt", "Reason data could not be assessed", None)],
               "Insufficient data to assess: no known pressure signal, and coverage or growth could not be checked."), 6),
           (status_share_bar(b, "ov_type", "Review status by LGU type", "lgu_type_label", "LGU type", "share_of_type",
                             ["City", "Municipality"],
                             "Share of cities and of municipalities in each review status."), 6)], 7)
    p.row([(scatter(b, "ov_region_bubble", "Resident children, local enrollment and public schools by region", "x",
                    "School-age population, ages 5-17, 2024", "y", "All-sector enrollment in local schools, SY 2024-25",
                    "series", "School-age population change, 2020-2024", REGION_COLORS, REGION_SERIES, "size",
                    f"Active public schools, {SCHOOL_COUNT_YEAR}",
                    desc="Each circle represents a region. Position compares resident children ages 5-17 with learners "
                         "enrolled in local schools; circle size represents active public schools. Enrollment is counted "
                         "where learners attend, while population is counted where children live. The dotted line marks "
                         "equal counts, for context only. The chart does not measure out-of-school children or determine "
                         "how many schools are needed.",
                    extra=[("label", "Region"), ("lgus_txt", "Cities and municipalities in view"),
                           ("population_2020_txt", "School-age population, 2020"),
                           ("population_2024_txt", "School-age population, 2024"),
                           ("population_change_txt", "Population change, 2020-2024"),
                           ("enrolled_2020_txt", "All-sector enrollment, SY 2020-21"),
                           ("enrolled_2024_txt", "All-sector enrollment, SY 2024-25"),
                           ("enrollment_change_txt", "Enrollment change"),
                           ("public_2024_txt", "Public-school enrollment, SY 2024-25"),
                           ("schools_txt", "Active public schools"), ("school_year_txt", "School-count year"),
                           ("comparable_txt", "LGUs with comparable population data"),
                           ("review_txt", "LGUs requiring data review")]), 12)], 9)
    p.row([(text(b, "**Next:** open **LGU Profile** and choose a city or municipality from the queue.\n", "\n",
                 "Before acting, validate flagged schools against actual classroom counts, building condition, shifts, "
                 "enrollment projections and planned projects. The queue prioritizes validation, not allocation."), 12)], 2)
    return p


def lgu_profile(b):
    p = Page("lgu_profile", "LGU Profile")
    profile = [n for n in b.params if n.startswith("pr_")] + ["opt_barangay"]
    intro = text(b, "# What is driving the planning status in this LGU?\n", "\n",
                 "Shows the evidence behind the selected LGU's planning status, the reliability of the result, and the "
                 "barangays and schools to validate first.")
    place = param_filter(b, "lgu", "City or municipality", profile, "Choose the LGU you want to review.")
    p.columns([(8, [(intro, 2)]), (4, [(place, 2)])], 2)
    p.row([(kpi(b, "pr_card", "Selected city or municipality", "city_mun_name", None,
                desc="Change it with City or municipality above", style=TITLE_STYLE, heading=True, align="left"), 5),
           (kpi(b, "pr_card", "LGU details", "details", None,
                desc="Type · province or region · national review order · data readiness",
                style=DETAIL_STYLE, heading=True, align="left"), 7)], 1)
    p.row([(note(b, "pr_card", "Facts", "facts", style=LINE_STYLE, show_title=False), 12)], 1)
    p.row([(kpi(b, "pr_card", "Schools above classroom screen", "classroom_kpi", None,
                desc=f"Of schools assessed, at {SCREEN}+ learners per room", style=KPI_STYLE), 3),
           (kpi(b, "pr_card", "Levels above teacher comparison", "teacher_kpi", None,
                desc="Of education levels assessed; named in the panel below", style=KPI_STYLE), 3),
           (kpi(b, "pr_card", "Public enrollment change", "enrollment_kpi", None,
                desc="SY 2020-21 to SY 2025-26", style=KPI_STYLE), 3),
           (kpi(b, "pr_card", "Lowest learner coverage", "readiness_kpi", None,
                desc="Classrooms and offered teacher levels", style=KPI_STYLE), 3)], 3)
    p.row([(kpi(b, "pr_card", "Review status", "status_line", None, desc="Review status · planning status: basis",
                style=STATUS_STYLE, heading=True, align="left"), 12)], 1)
    p.row([(table(b, "pr_decision", "Why this LGU has this status", [
                ("signal", "Signal", None), ("result", "Result", None), ("basis", "Basis", None)],
                "The two pressure signals and enrollment growth, each Yes, No or Not assessed, and the review status "
                "they produce."), 6),
           (table(b, "pr_evidence", "Measures and comparison points", [
                ("measure", "Measure", None), ("this_lgu", "This LGU", None), ("comparison", "Comparison point", None),
                ("status", "Status", None), ("coverage", "Coverage", None)],
                "Each measure beside its published comparison point, SY 2023-24. Teacher ratios to one decimal."), 6)], 5)
    p.row([(bar(b, "pr_teachers", "Learners per reported teacher by level", "level_axis", "Level · value vs comparison point",
                "max", "share_of_comparison", "Share of the comparison point", fmt=pct(0), color="status",
                color_label="Against the comparison point", mappings=LEVEL_COLORS, color_order=LEVEL_STATUS,
                legend=LEGEND_BOTTOM, annotations=[ref_line("x", 1, "Comparison point")],
                desc="Each offered level's learners per reported teacher against its published comparison point, on one "
                     "scale; past the line is above it. Not a staffing entitlement."), 6),
           (line(b, "pr_enrollment", "Enrollment over time", "school_year_label", "School year", "sum", "learners",
                 "Learners", num(1, True), color="scope", color_label="Scope",
                 mappings=[{"value": ENROLLMENT_SERIES[0], "color": "#C9A227"},
                           {"value": ENROLLMENT_SERIES[1], "color": "#5B6B7A"}],
                 color_order=ENROLLMENT_SERIES, x_order=SCHOOL_YEARS,
                 desc="Public-school and all-sector enrollment by school year. Public is part of all sectors, so the "
                      "lines are not added."), 6)], 7)
    p.row([(bar(b, "pr_cohorts", "Change in school-age population, 2020–2024", "age_band", "Age group", "max",
                "change", "Change, 2020 to 2024", order=BANDS, fmt=pct(1), color="direction", color_label="Direction",
                mappings=CHANGE_COLORS, color_order=[c["value"] for c in CHANGE_COLORS], legend=LEGEND_BOTTOM,
                annotations=[ref_line("x", 0, "No change")],
                desc="Percentage change in resident children by the school level matching their age."), 6),
           (bar(b, "pr_census", "Resident children and local enrollment", "period", "Census", "sum", "people", "People",
                horizontal=False, color="series", color_label="Series",
                mappings=[{"value": CENSUS_SERIES[0], "color": "#5B6B7A"}, {"value": CENSUS_SERIES[1], "color": "#C9A227"}],
                order=CENSUS_YEARS, color_order=CENSUS_SERIES, layout="group", fmt=num(1, True), legend=LEGEND_BOTTOM,
                desc="Children are counted where they live, learners where they attend school. A school hub can enroll "
                     "more learners than its resident children; the gap is not a count of children out of school."), 6)], 7)
    peers = scatter(
        b, "pr_peers", "How does this LGU compare with other LGUs in the area?", "x",
        "School-age population, ages 5-17, 2024", "y", "All-sector enrollment in local schools, SY 2024-25", "series",
        "Comparison area", PEER_COLORS, PEER_SERIES, "size", f"Active public schools, {SCHOOL_COUNT_YEAR}",
        desc="The selected LGU is compared with other LGUs in its province, or its region for an independent city. Moving "
             "right means more resident children; moving up means more learners enrolled locally; larger circles represent "
             "more active public schools. Differences can reflect cross-boundary attendance, school offerings and data "
             "coverage. They are not counts of out-of-school children. The dotted line marks equal counts, for context only.",
        extra=[("label", "City or municipality"), ("province_label", "Province"), ("region_short", "Region"),
               ("queue_status", "Review status"), ("population_2020_txt", "School-age population, 2020"),
               ("population_2024_txt", "School-age population, 2024"), ("population_change_txt", "Population change"),
               ("enrolled_2020_txt", "All-sector enrollment, SY 2020-21"),
               ("enrolled_2024_txt", "All-sector enrollment, SY 2024-25"), ("enrollment_change_txt", "Enrollment change"),
               ("public_2024_txt", "Public-school enrollment"), ("schools_txt", "Active public schools"),
               ("learners_per_school_txt", "Learners per public school"),
               ("children_per_school_txt", "School-age children per public school"),
               ("barangays_txt", "Barangays without a matched public elementary school"),
               ("match_txt", "School-to-barangay match coverage"), ("comparability_txt", "Population comparability status")])
    peer_note = note(b, "pr_peer_note", "Selected LGU", "peer_line", style=LINE_STYLE, show_title=False)
    p.columns([(12, [(peers, 8), (peer_note, 1)])], 9)
    barangay = param_filter(b, "barangay", "Barangay", ["pr_barangays", "pr_map", "pr_map_note"],
                            "Narrows the school map and barangay table only.", options=("opt_barangay", "barangay_option"))
    school_map = point_map(
        b, "pr_map", "School locations and barangay access", "latitude", "longitude", "map_series", "Schools",
        MAP_COLORS, [c["value"] for c in MAP_COLORS],
        [("school_name", "School"), ("school_id", "School ID"), ("barangay_name", "Barangay"), ("school_kind", "Main or annex"),
         ("levels_offered_full", "Levels offered"), ("learners_txt", "Public learners, SY 2023-24"),
         ("per_room_txt", "Learners per reported room"), ("per_teacher_txt", "Learners per reported teacher"),
         ("verification_status", "Verification status"), ("why_listed", "Why listed"),
         ("location_status", "Coordinate validation")],
        "Public schools with validated coordinates in the selected LGU, SY 2023-24 published locations. Not catchment "
        "areas, routes or walking distance.")
    map_note = note(b, "pr_map_note", "School map coverage", "map_line", style=LINE_STYLE, show_title=False)
    barangays = table(b, "pr_barangays", "Barangays without a matched public elementary school", [
        ("barangay_name", "Barangay", None), ("public_es", "Matched public elementary", None),
        ("public_schools_txt", "Public schools", None), ("learners_txt", "Public learners", None),
        ("urban_rural", "Urban or rural", None)],
        "Listed first, then every other barangay. A nearby school may serve across barangay boundaries.")
    p.columns([(7, [(school_map, 9), (map_note, 1)]), (5, [(barangay, 1), (barangays, 9)])], 10)
    p.row([(table(b, "pr_teaser", "Schools to validate first", [
               ("school_name", "School", None), ("barangay_name", "Barangay", None),
               ("per_room_txt", "Learners per room", None), ("why_listed", "Why listed", None),
               ("next_step", "Next step", None)],
               "Schools with a figure to verify first, then the highest classroom pressure. Full list on School Action."), 7),
           (table(b, "pr_reliability", "Data coverage and checks", [
               ("measure", "Measure", None), ("coverage", "Learner coverage", None), ("assessed", "Status", None),
               ("unusual_schools", "Unusual figures", None)],
               "Whether enough data were reported for each measure, and schools left out for a missing or zero count."),
            5)], 5)
    return p


def school_action(b):
    p = Page("school_action", "School Action")
    targets = ["sa_school", "sa_bullet", "sa_peers", "sa_location", "sa_trend", "sa_rooms", "sa_verify", "sa_list",
               "opt_school"]
    intro = text(b, "# Which schools should be validated first?\n", "\n",
                 "Ranks public schools within the selected LGU for verification and shows the exact figures behind "
                 "each flag, SY 2023-24.")
    place = param_filter(b, "lgu", "City or municipality", targets + ["opt_barangay_school"],
                         "Its own choice: picking an LGU on LGU Profile does not change it.",
                         options=("opt_lgu", "lgu_option"))
    p.columns([(8, [(intro, 2)]), (4, [(place, 2)])], 2)
    school = param_filter(b, "school", "School", targets, "Type to search. Defaults to the first school to verify.")
    level = param_filter(b, "level", "Education level", targets)
    p.row([(school, 6), (level, 6)], 1)
    p.row([(kpi(b, "sa_school", "Selected school", "school_name", None,
                desc="Change it in School above", style=TITLE_STYLE, heading=True, align="left"), 12)], 1)
    p.row([(kpi(b, "sa_school", "School details", "details", None,
                desc="School ID · barangay · main or annex · levels · learners · LGU review status",
                style=DETAIL_STYLE, heading=True, align="left"), 12)], 1)
    p.row([(kpi(b, "sa_school", "What to verify", "verify_header", None, desc="The first figure to verify",
                style=STATUS_STYLE, heading=True, align="left"), 12)], 1)
    p.row([(kpi(b, "sa_school", "Learners per room", "room_kpi", None,
                desc=f"All levels, reported rooms · screen {SCREEN}", style=KPI_STYLE), 3),
           (kpi(b, "sa_school", "Learners per teacher", "teacher_kpi", None,
                desc="At the chosen level, vs its comparison point", style=KPI_STYLE), 3),
           (kpi(b, "sa_school", "Enrollment change", "change_kpi", None,
                desc="SY 2020-21 to SY 2025-26", style=KPI_STYLE), 3),
           (kpi(b, "sa_school", "Verification items", "verify_kpi", None,
                desc="A flag means verify, not incorrect", style=KPI_STYLE), 3)], 3)
    p.row([(bar(b, "sa_bullet", "Classroom and teacher figures against their references", "figure", "Figure", "sum",
                "share_of_reference", "Share of the reference", fmt=pct(0), color="status", color_label="Against the reference",
                mappings=LEVEL_COLORS, color_order=LEVEL_STATUS, legend=LEGEND_BOTTOM, raw=True, sort_by="natural-order",
                annotations=[ref_line("x", 1, "Reference")],
                desc=f"Each figure on one scale, where the line is its reference: the {SCREEN}-learner room screen or the "
                     "level's teacher comparison point. Past the line is beyond the reference."), 6),
           (table(b, "sa_verify", "What should be verified?", [
               ("item", "Figure", None), ("why", "Why", None), ("next_step", "Next step", None)],
               "Each flag turned into a step with the school or the Schools Division Office."), 6)], 5)
    p.row([(scatter(b, "sa_peers", "How does this school compare with other schools in the LGU?", "learners",
                    "Learners", "rooms", "Reported instructional rooms", "series", "School", SCHOOL_COLORS, SCHOOL_SERIES,
                    "teachers", "Reported teachers", "school_name",
                    f"Each bubble is a public school offering the chosen level, sized by reported teachers. Schools below "
                    f"the dotted {SCREEN}-learners-per-room line are above the classroom screen."), 8),
           (point_map(b, "sa_location", "School location", "latitude", "longitude", "series", "Schools",
                      LOCATION_COLORS, [c["value"] for c in LOCATION_COLORS],
                      [("school_name", "School"), ("levels_offered_full", "Levels offered")],
                      "The selected school and public schools within about 3 km. Empty when the school has no validated "
                      "location; no barangay boundary is drawn."), 4)], 8)
    p.row([(line(b, "sa_trend", "How has enrollment changed in this school?", "school_year_label", "School year", "sum",
                 "learners", "Learners", num(), color="series", color_label="Series", x_order=SCHOOL_YEARS,
                 mappings=[{"value": "All levels", "color": "#712B13"}, {"value": LEVELS[0], "color": "#A9B4BF"},
                           {"value": LEVELS[1], "color": "#5B6B7A"}, {"value": LEVELS[2], "color": "#C9A227"}],
                 color_order=["All levels"] + LEVELS,
                 desc="Total enrollment, and each offered level when there is more than one. A missing year leaves a "
                      "gap. Shows whether pressure is persistent, rising or falling."), 6),
           (table(b, "sa_rooms", "Reported rooms and teachers", [
               ("level", "Level", None), ("learners", "Learners", None), ("teachers", "Reported teachers", None),
               ("learners_per_teacher", "Learners per teacher", None), ("classrooms", "Instructional rooms", None),
               ("temporary_rooms", "Temporary", None), ("makeshift_rooms", "Makeshift", None)],
               "SY 2023-24. Teachers are counted by level; rooms only for the whole school."), 6)], 6)
    status = param_filter(b, "school_status", "School status", ["sa_list"], "Changes the list below only.")
    barangay = param_filter(b, "barangay", "Barangay", ["sa_list"], "Optional: narrows the list below to one barangay.",
                            options=("opt_barangay_school", "barangay_option"))
    p.row([(status, 6), (barangay, 6)], 1)
    p.row([(table(b, "sa_list", "School validation list", [
        ("list_order", "#", None), ("school_name", "School", None), ("barangay_name", "Barangay", None),
        ("levels_offered", "Levels", None), ("per_room_txt", "Learners per room", None),
        ("per_teacher_txt", "Learners per teacher", None), ("verification_status", "Verification status", None),
        ("why_listed", "Why listed", None), ("next_step", "Next step", None)],
        "Schools with a figure to verify first, then the highest classroom pressure. Levels: ES elementary, JHS junior "
        "high, SHS senior high; the download spells them out and adds the school ID, main or annex, enrollment change, "
        "temporary or makeshift rooms and locally funded teachers."), 12)], 10)
    p.row([(text(b, "Confirm flagged figures with the Schools Division Office before using them for planning. The "
                 "dashboard prioritizes validation; it does not prescribe how many classrooms, teachers, or schools to "
                 "add."), 12)], 1)
    return p


def data_and_method(b):
    p = Page("data_and_method", "Data & Method")
    p.row([(text(b, "# How reliable are the results?\n", "\n",
                 "Explains the planning rule, source coverage, comparison points, freshness, and known limitations in "
                 "plain language."), 12)], 2)
    p.row([(kpi(b, "dm_kpi", "Classrooms assessed", "classroom_kpi", None,
                desc="LGUs with 90%+ learners in schools with a room count", style=KPI_STYLE), 3),
           (kpi(b, "dm_kpi", "Teachers assessed", "teacher_kpi", None,
                desc="LGUs where every offered level has 90%+ coverage", style=KPI_STYLE), 3),
           (kpi(b, "dm_kpi", "Comparable enrollment trends", "trend_kpi", None,
                desc="LGUs with complete years and unchanged boundaries", style=KPI_STYLE), 3),
           (kpi(b, "freshness", "Last refresh", "updated", None, desc="Latest successful pipeline run",
                style=KPI_STYLE), 3)], 3)
    p.row([(note(b, "dm_kpi", "Data review alert", "alert_line", style=STATUS_STYLE, show_title=False), 12)], 1)
    p.row([(table(b, "dm_rules", "How the review status is assigned", [
               ("review_status", "Review status", None), ("planning_status", "Planning status", None),
               ("pressure_signals", "Pressure signals present", None),
               ("enrollment_growing", "Public enrollment growing", None)],
               "Two current pressure signals, classroom and teacher, and public-enrollment growth produce each status. A "
               "known pressure always counts; where growth cannot be checked, the LGU is placed as if it were not "
               "growing."), 12)], 5)
    p.row([(table(b, "dm_refs", "Published comparison points", [
               ("measure", "Measure", None), ("comparison_point", "Comparison point", None), ("basis", "Basis", None),
               ("use_in_dashboard", "Use", None)],
               "The values the Analytics SQL writes. A comparison, never a staffing or construction entitlement."), 12)], 4)
    measure = param_filter(b, "measure", "Measure", ["dm_coverage", "dm_reasons"],
                           "Applies to the two panels below it only.")
    p.row([(measure, 4), (text(b, "The Measure filter changes **Data coverage by measure** and **Why some LGUs need data "
                                  "review** only."), 8)], 1)
    p.row([(bar(b, "dm_coverage", "Data coverage by measure", "measure", "Measure", "sum", "share", "Share of LGUs",
                color="coverage_status", color_label="Coverage", layout="stack", color_order=COVERAGE_STATUS,
                mappings=COVERAGE_COLORS, order=COVERAGE_MEASURES, fmt=pct(0), legend=LEGEND_BOTTOM,
                desc="Assessed, incomplete, and unavailable shares of LGUs for each measure."), 6),
           (bar(b, "dm_teacher_levels", "Teacher-pressure assessment by level", "level", "Level", "sum", "share",
                "Share of LGUs offering the level", color="status", color_label="Learners per teacher", layout="stack",
                order=LEVELS, color_order=LEVEL_STATUS, mappings=LEVEL_COLORS, fmt=pct(0), legend=LEGEND_BOTTOM,
                desc="Above, at or below, or not assessed against the comparison point."), 6)], 7)
    p.row([(bar(b, "dm_reasons", "Why some LGUs need data review", "reason", "", "sum", "lgus",
                "Data review LGUs", color="measure", color_label="Input", color_order=REASON_MEASURES,
                mappings=REASON_COLORS, layout="stack", legend=LEGEND_BOTTOM,
                desc="The Data review LGUs by the input that could not be checked. One LGU may have more than one "
                     "reason."), 12)], 6)
    p.row([(bar(b, "dm_ap4", "Enrollment trend availability", "ap4_status", "Status", "sum", "lgus",
                "Cities and municipalities", order=AP4_STATUS, color="ap4_status", color_label="Status",
                mappings=AP4_COLORS, color_order=AP4_STATUS,
                desc="Complete and comparable, an incomplete school year, or changed boundaries."), 6),
           (bar(b, "dm_share", "How concentrated classroom pressure is", "share_band",
                "Share of learners above the screen", "sum", "lgus", "Assessed cities and municipalities",
                order=SHARE_BANDS,
                desc="Assessed LGUs by the share of their learners in schools above the classroom screen."), 6)], 7)
    p.row([(table(b, "dm_sources", "Available school years by source", [("source", "Source", None)] + [
               (f"sy_{y.replace('-', '_')}", f"SY {y}", None) for y in SOURCE_YEARS],
               "Enrollment spans several years; classroom and teacher data exist only for SY 2023-24."), 6),
           (text(b, "## What this dashboard cannot tell you\n\n",
                 "- **How many resources to add.** The review order is not an official shortage, staffing entitlement, "
                 "construction need or funding allocation.\n",
                 "- **Room condition or use.** Reported rooms do not show condition, shifts or utilization.\n",
                 "- **Travel or access.** Enrollment is counted at the school, not where learners live.\n\n",
                 "Full methodology: the dashboards README in the project repository."), 6)], 5)
    p.row([(note(b, "freshness", "Technical data health", "health_line", style=LINE_STYLE, show_title=False), 12)], 1)
    return p


def build():
    b = Builder(DEFAULTS, OPTION_FIELDS)
    datasets(b)
    pages = [overview(b), lgu_profile(b), school_action(b), data_and_method(b)]
    global_page = Page("global_filters", "Global filters")
    all_targets = [d["name"] for d in b.datasets]
    for i, (keyword, title, desc) in enumerate([
            ("region", "Region", "Applies to every view."), ("province", "Province", "Follows Region."),
            ("lgu_type", "LGU type", None)]):
        global_page.items.append({"widget": param_filter(b, keyword, title, all_targets, desc),
                                  "position": {"x": 0, "y": i * 2, "width": 12, "height": 2}})
    return {
        "datasets": b.datasets,
        "pages": [page.json() for page in pages] + [global_page.json("PAGE_TYPE_GLOBAL_FILTERS")],
        "uiSettings": {"theme": {
            "canvasBackgroundColor": {"light": "#F7F5F2", "dark": "#151B20"},
            "widgetBackgroundColor": {"light": "#FFFFFF", "dark": "#1E262C"},
            "widgetBorderColor": {"light": "#E4DFD8", "dark": "#2A343B"},
            "fontColor": {"light": "#14212B", "dark": "#E8ECF0"},
            "selectionColor": {"light": "#712B13", "dark": "#F0997B"},
            "visualizationColors": PALETTE,
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
