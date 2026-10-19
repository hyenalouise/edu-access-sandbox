# Dashboard Version 3: detailed outline

Three views, one story: **Overview** (which LGUs first) → **LGU Profile** (why this one, which barangays and schools) → **Data and Method** (can we trust it). The planner is the LGU Local School Board. All capacity measures are SY 2023-24 under rule D-057 unless a row says otherwise.

This outline replaces the four-view v2 guide. It reads from the Analytics and Gold tables in the sandbox build (`06-analytics.*`, `05-gold.*`, `01-control.*`). Items marked **Build note** need a dataset query or a column that does not exist yet.

## Contents

1. [Datasets](#1-datasets)
2. [Global filters and dependency rules](#2-global-filters-and-dependency-rules)
3. [Colour, labels and accessibility](#3-colour-labels-and-accessibility)
4. [View 1: Overview](#4-view-1-overview)
5. [View 2: LGU Profile](#5-view-2-lgu-profile)
6. [View 3: Data and Method](#6-view-3-data-and-method)
7. [Visual interaction matrix](#7-visual-interaction-matrix)
8. [Narrow-screen behaviour](#8-narrow-screen-behaviour)
9. [Build order](#9-build-order)
10. [Acceptance checklist](#10-acceptance-checklist)

---

## 1. Datasets

| ID | Dataset | Grain | Source | Notes |
|---|---|---|---|---|
| `ds_priority` | LGU priority | LGU, SY 2023-24 | `06-analytics.lgu_priority` | Tier, percentiles, relative pressure, coverage, scenarios. Add a derived `combo` field from `ap1_status`, `ap2_status`, `ap3_status` (for example "Schools + Teachers"), because `high_measures` carries the AP3 level and would split one combination into three |
| `ds_priority_national` | Same as above, geography renamed | LGU | `ds_priority` with `region_name` and `province_name` aliased (for example `region_nat`) | **Build note:** global filters bind by field, so renaming the geography fields keeps national diagnostics from being narrowed by Region and Province. LGU type still binds |
| `ds_boundaries` | City/municipality boundaries | LGU | HDX COD-AB ADM3 matched to PSGC, as in v2 | Reuse the v2 map dataset. The 8 Special Geographic Area municipalities have no boundary |
| `ds_ap1_years` | Schools and learners by year | LGU × school year | `06-analytics.ap1_school_provision` | SY 2020-21 to 2025-26 |
| `ds_ap3_levels` | Teachers by level | LGU × level, SY 2023-24 | `06-analytics.ap3_teacher_pressure` | **Build note:** add the same-type baseline per level: `SUM(learners_in_ratio) / SUM(teachers_in_ratio)` over LGUs of the same type with `schools_in_scope > 0` and `learner_coverage_pct >= 90`. `lgu_priority` stores it only for the level that sets AP3 |
| `ds_ap4` | Population and enrollment gap | LGU × reference year | `06-analytics.ap4_population_enrollment_gap` | 2020 pairs with SY 2020-21; 2024 pairs with SY 2024-25 |
| `ds_age` | School-age population by age | LGU × year × age | `05-gold.fact_city_school_age_population` | Ages 5–17 only (the table holds 5–24); sum `female` and `male` |
| `ds_sector` | Enrollment by sector | LGU × school year × sector | `05-gold.fact_school_enrollment` | `is_offered`, SY 2020-21 and 2024-25, sectors Public, Private, SUC/LUC; PSO excluded |
| `ds_poverty` | Poverty 2023 | LGU | `05-gold.dim_city_poverty` | Context only |
| `ds_barangay` | Barangay summary | Barangay, SY 2023-24 | `05-gold.dim_barangay` (`member_type = 'regular'`) LEFT JOIN active public schools from `fact_school_enrollment` | **Build note:** schools, learners, rooms (`fact_school_classroom_capacity`), teachers (`fact_school_teacher_capacity`), `offers_public_es`, `urban_rural`. Barangays with no school must still appear |
| `ds_schools` | School action list | School, SY 2023-24 | `fact_school_enrollment` + both capacity facts + `lgu_priority_outlier_schools` | **Build note:** one row per active public school: barangay, annex status, levels offered, learners, rooms, learners per room, teachers and learners per teacher per level, temporary and makeshift rooms, flags (`room_outlier`, `teacher_outlier_<level>`, `rooms_missing`, `rooms_zero`, `level_without_teachers`) |
| `ds_overlap` | Measure relationships | Measure pair × LGU type | Computed from `ds_priority` | **Build note:** Spearman = Pearson correlation of the within-type ranks; overlap = share of LGUs high on measure A that are also high on B |
| `ds_sources` | Source-year coverage | Source × school year | `05-gold.fact_school_year_source_availability` | |
| `ds_checks` | Latest quality checks | Check, latest run | `01-control.data_quality_results` | Latest `run_id` per `table_name` |

---

## 2. Global filters and dependency rules

| Filter | Field | Options depend on | Default |
|---|---|---|---|
| Region | `region_name` | none | All |
| Province | `province_name` | Region | All. Independent cities are grouped as "Independent cities (no province)" |
| LGU type | `lgu_type` | none | Both |

**Rules**

1. **Global filters narrow what is shown; they never recalculate anything.** Percentiles, baselines, relative pressure and tiers are stored nationally within type and read as-is.
2. **Province follows Region.** Changing Region clears Province if the chosen province is no longer in it.
3. **The LGU list on the Profile follows all three global filters.**
   - If a global change makes the chosen LGU invalid, the Profile falls back to the first LGU in `priority_rank` order within the new filter.
   - A text banner says: "The selected LGU is outside your filters, so the profile now shows {LGU}."
   - **Build note:** check whether the editor can show this banner. If not, show the LGU name prominently in the identity card so the switch is visible.
4. **Global filters persist across pages; page filters reset on page change.** Exception: the LGU picked from the Overview table carries into the Profile.
5. **National method diagnostics** (marked with the label on the visual) read `ds_priority_national` and ignore Region and Province. LGU type still applies.
6. **No ranking-scope control anywhere.** The national ranking is only a diagnostic on Data and Method.

**Build note on carrying the LGU across pages:** Databricks AI/BI page filters do not pass between pages. Options, in order of preference:

- **(a)** A table link from the Overview to the Profile with the LGU as a URL parameter, if the editor supports it.
- **(b)** Make City/municipality a global filter that only the Profile uses.
- **(c)** The user picks the LGU on the Profile.

Test (a) first.

---

## 3. Colour, labels and accessibility

**Tier colours.** One ordinal ramp, because the tier is an order. Data review is neutral.

| Tier | `tier_code` | Fill | Text on fill | Label always shown |
|---|---|---|---|---|
| Critical | 3 | `#712B13` | white | "Critical · high on 3 of 3" |
| Elevated | 2 | `#D85A30` | white | "Elevated · 2 of 3" |
| Targeted | 1 | `#F0997B` | `#4A1B0C` | "Targeted · {measure}" |
| Monitor | 0 | `#FAECE7` | `#4A1B0C` | "Monitor" |
| Data review | `data_review` | `#B4B2A9` | `#2C2C2A` | "Data review · {reason}" |

**Coverage and warnings** use a separate neutral system:

- grey for "not assessed"
- an amber outline with a ⚠ text marker for a warning (coverage below 95%, outlier present, upper-bound count)
- never a tier colour

**Context only** (AP4, poverty) sits in a muted amber band titled "Context only · never in the tier".

**Do not rely on colour alone**

- Every tier appears as text in tables, tooltips and the identity card.
- Map tooltips name the tier.
- The tier legend lists the meaning.
- Scatters carry the tier in the tooltip and a "High on" column in the linked table.
- Check contrast at 4.5:1 for all text on fills.

**Words not to use:** shortage, deficit, required resources, under-capacity, enrollment rate, out-of-school, "DepEd classroom–learner ratio", "DepEd teacher–learner ratio".

**Fixed phrases**

- "Learners per reported instructional room"
- "Learners per teacher (project-defined)"
- "Relative pressure: compared with all {cities | municipalities} combined"
- "Relative capacity pressure"

---

## 4. View 1: Overview

**Purpose:** Which cities and municipalities should planners review first?

**Page filters**

| Filter | Field | Options | Applies to |
|---|---|---|---|
| Priority tier | `tier_label` | All, Critical, Elevated, Targeted, Monitor, Data review | Map, region bar, priority table |
| High measure | `combo` | All, plus each combination | Map, region bar, priority table |
| Coverage status | derived: `tier_code = 'data_review'` | All, Assessed, Data review | Map, priority table |

The KPIs and the trend and context charts ignore the page filters on purpose, so the totals stay readable while the table narrows.

### KPIs (row 1, above the fold)

| # | Title | Formula | Subtitle | Filters |
|---|---|---|---|---|
| K1 | Cities and municipalities | `COUNT(DISTINCT city_mun_psgc_code)` from `ds_priority` | "{n} assessed · {m} in Data review" | Global |
| K2 | Public learners | `SUM(affected_learners)` | "SY 2023-24 · schools with complete counts" | Global |
| K3 | Priority LGUs | `COUNT_IF(tier_code IN ('3','2'))` | "Critical {c} · Elevated {e}" | Global |
| K4 | Learners in priority LGUs | `SUM(affected_learners WHERE tier_code IN ('3','2')) / SUM(affected_learners)` | "{x} learners" | Global |

**Dynamic titles:** if the editor supports them, append the filter context, for example "Priority LGUs · Region VII". Otherwise rely on the filter chips.

### O1 · Tier map

| Item | Content |
|---|---|
| Type | Choropleth, w7 h10, above the fold |
| Question | Where are the priority LGUs? |
| Field | `tier_sort` (colour), joined to `ds_boundaries` on `city_mun_psgc_code` |
| Encoding | Fill = tier (section 3). Data review = grey. No boundary = blank, listed in the caption |
| Reference | Legend with meanings |
| Tooltip | LGU, province, tier label, high measures, the three percentiles, affected learners, coverage status |
| Coverage | Data review LGUs are grey, with the reason in the tooltip |
| Warning | Caption: "8 Special Geographic Area municipalities have no boundary and are not drawn" |
| Filters | Global and all page filters |
| Cross-filter | Clicking an LGU filters O5 to that LGU. Clicking empty space clears it |
| Drill | None (use the table) |
| Empty state | "No LGUs match these filters." |
| Caveat | "Tiers compare cities with cities and municipalities with municipalities. A tier is relative pressure, not a shortage." |
| Period | SY 2023-24 |
| Copy | Title: "Where the pressure is". Subtitle: "Darker means more of the three measures are high" |

### O2 · What drives the priority

| Item | Content |
|---|---|
| Type | Horizontal bar, stacked by tier, w5 h10, above the fold |
| Question | Is it schools, classrooms, teachers, or a combination? |
| Field | `COUNT(*)` by `combo`, stacked by `tier_label`. Excludes Monitor and Data review |
| Sorting | By count, descending |
| Tooltip | Combination, tier, LGU count, affected learners |
| Filters | Global and Priority tier. Ignores the High measure filter, because it is the selector for it |
| Cross-filter | Clicking a bar sets the High measure filter, which narrows O1, O3 and O5 |
| Empty state | "No LGU is high on any measure in this view." |
| Caveat | "AP3 counts as high when the education level with the highest percentile is high." |
| Copy | Title: "What drives the priority" |

### O3 · Priority LGUs by region

| Item | Content |
|---|---|
| Type | Horizontal bar, stacked by tier, w6 h7, below the fold |
| Question | Which regions hold the most priority LGUs? |
| Field | `COUNT(*)` where `tier_code IN ('3','2','1')`, by `region_name`, stacked by `tier_label` |
| Sorting | Critical + Elevated count, descending |
| Tooltip | Region, tier counts, affected learners in priority LGUs |
| Filters | Global and all page filters |
| Cross-filter | Clicking a region sets the Region global filter |
| Caveat | "Counts compare regions, but each LGU is ranked against its own type nationally." |
| Copy | Title: "Priority LGUs by region" |

### O4 · How far above the rest?

| Item | Content |
|---|---|
| Type | Box plot, w6 h7, below the fold |
| Question | How much more pressure do high LGUs carry than everyone else? |
| Field | `ap1_relative_pressure`, `ap2_relative_pressure`, `ap3_relative_pressure` (unpivoted to `measure`, `relative_pressure`), split by `lgu_type`, with high and not-high shown side by side |
| Reference | Line at 1.00, labelled "all {type} combined" |
| Tooltip | Measure, type, median, quartiles, the lowest relative pressure that is high |
| Filters | Global only |
| Warning | AP3 note: "AP3 uses the level that sets the measure. The high line differs by level." |
| Caveat | "Relative pressure shows size, not the tier. Only the percentile sets high." |
| Copy | Title: "How far above the rest?" |

### O5 · Priority table

| Item | Content |
|---|---|
| Type | Table, w12 h10, below the fold |
| Question | Which LGUs first, and in what order? |
| Columns | `priority_rank`, LGU, type, province, `tier_label`, `high_measures`; then for each AP the percentile (0–100), relative pressure (2 decimals, labelled ×) and coverage; then `affected_learners`, `is_stable` |
| Sorting | `tier_sort`, then `affected_learners` descending, then `lowest_percentile` descending, then `city_mun_psgc_code` ascending |
| Coverage | A coverage cell below 90% is grey with "not assessed". Data review rows sort last and show the reason |
| Warning | ⚠ when `outlier_schools > 0`, with the tooltip "{n} outlier schools; the tier stays the same without them" (or "changes to {tier}") |
| Filters | Global and all page filters |
| Drill | Clicking an LGU name opens the LGU Profile (section 2, carrying the LGU) |
| Download | CSV |
| Empty state | "No LGUs match these filters." |
| Copy | Title: "Priority list" |

### O6 · Learners and schools by school year

| Item | Content |
|---|---|
| Type | Line, w6 h7, below the fold |
| Question | Is public enrollment growing or shrinking? |
| Field | `SUM(public_learners)` and `SUM(active_public_schools)` by `school_year` from `ds_ap1_years` |
| Encoding | Learners on the left axis, schools on the right axis. If the editor has no dual axis, show learners as the line and schools in the tooltip |
| Filters | Global only |
| Caveat | "Learners in schools with complete counts. Each school year is that year's DepEd file." |
| Period | SY 2020-21 to 2025-26 |
| Copy | Title: "Public learners and schools by school year" |

### O7 · Context only · school-age population and enrollment, 2020 and 2024

| Item | Content |
|---|---|
| Type | Grouped bar, w6 h7, below the fold, in the context band |
| Question | How do resident children compare with enrollment at the two census points? |
| Field | `SUM(school_age_population)` and `SUM(enrollment_all_sectors)` by `reference_year` from `ds_ap4`, over LGUs with a non-null gap in both years |
| Encoding | x = 2020 (SY 2020-21) and 2024 (SY 2024-25); two bars each; gap share as a data label |
| Tooltip | Population 5–17, enrollment all sectors, gap, gap share, LGUs included |
| Filters | Global only |
| Warning | "{n} LGUs excluded: boundary or name not comparable between 2020 and 2024" |
| Caveat | "Context only, never in the tier. Population is counted where children live, enrollment where schools are, so the gap is not an out-of-school count." |
| Copy | Title: "Context only · children aged 5–17 and enrollment" |

---

## 5. View 2: LGU Profile

**Purpose:** Why did this LGU get its tier, and which barangays and schools should be checked?

**Page filters**

| Filter | Field | Options | Applies to |
|---|---|---|---|
| City or municipality | `city_mun_psgc_code` (shown as name, province) | LGUs in the global filters, in `priority_rank` order | Everything on the page |
| Education level | `education_level_code` | ES, JHS, SHS. Default: the level that sets AP3 (`ap3_highest_level`) | P4, P13, P15 (teacher columns) |
| School status | derived flag | All, Outlier, Missing data, Zero denominator | P13, P15 |

### Identity card (top)

Text widget from `ds_priority`:

- **{LGU}**, {city_class} {type}, {province}, {region}
- Tier badge "{tier_label}", with rank "{priority_rank} of {N}" and "{rank_within_tier} in {tier}"
- High on: {high_measures} (or "None high")
- Stable badge when `is_stable`
- Footer: "SY 2023-24 · rule {rule_version}"
- Data review: show "Data review · {measure} coverage below 90%" instead of a rank

### KPIs (row 2)

| # | Title | Formula | Subtitle |
|---|---|---|---|
| PK1 | Public learners | `public_learners` from `ds_ap1_years`, SY 2023-24 | "{±x%} since SY 2020-21" |
| PK2 | Public schools | `active_public_schools` | "including {active_annexes} annexes" |
| PK3 | Barangays without a public elementary school | `barangays_without_public_es` | "of {regular_barangays} barangays". Prefix "At most" when `barangay_count_is_upper_bound` |
| PK4 | Schools to check | `COUNT_IF(any flag)` from `ds_schools` | "outlier or missing data" |

### P1–P3 · Measure cards (AP1, AP2, AP3)

One card per measure, w4 h6, above the fold. **Build note:** use a counter for the ratio with a small table beneath, or a single formatted table. A bullet-style bar is not a native widget.

| Row | AP1 | AP2 | AP3 |
|---|---|---|---|
| Title | Learners per public school | Learners per reported instructional room | Learners per teacher, {level} (project-defined) |
| Observed | `ap1_learners_per_public_school` | `ap2_learners_per_room` | the `ap3_{level}_learners_per_teacher` that matches `ap3_highest_level` |
| Coverage | `ap1_coverage_pct` (schools with complete enrollment) | `ap2_coverage_pct` (learners) | `ap3_{level}_coverage_pct` (learners) |
| Percentile | `ap1_percentile` × 100, bar with a 90 mark | `ap2_percentile` | `ap3_percentile` |
| Relative pressure | `ap1_relative_pressure` "× all {type}s combined" | `ap2_relative_pressure` | `ap3_relative_pressure` |
| Status | `ap1_status` → High / Not high / Not assessed | `ap2_status` | `ap3_status` |

**Card rules**

- **Not assessed:** grey card, "Coverage {x}% is below 90%, so this measure is not ranked." The observed ratio is still shown.
- **Tooltip** on relative pressure: "{value} ÷ {baseline} (all {type}s combined, LGUs with ≥ 90% coverage)."
- **AP2 caveat:** "Rooms include labs and other instructional rooms, so this is not DepEd's classroom–learner ratio."
- **AP3 caveat:** "Annex staff are not added to their mother school, so this is not DepEd's teacher–learner ratio."

### P4 · Teachers by level

| Item | Content |
|---|---|
| Type | Grouped bar, w6 h7, below the fold |
| Question | Which school level is most stretched? |
| Field | `learners_per_teacher` per level (`ds_ap3_levels`), with the level baseline as a second bar or a tick |
| Encoding | The level that sets AP3 gets a ★ label. A level below 90% coverage is hatched or grey with "not assessed" |
| Tooltip | Level, ratio, baseline, relative pressure, percentile, coverage, learners without a same-level teacher |
| Filters | LGU. Education level highlights its bar |
| Caveat | "Each level is ranked separately, so the high line differs by level." |
| Copy | Title: "Learners per teacher by level" |

### P5 · Learners and schools by school year

| Item | Content |
|---|---|
| Type | Line, w6 h7 |
| Question | Is pressure building in this LGU? |
| Field | `public_learners` and `active_public_schools` by `school_year` (`ds_ap1_years`) |
| Encoding | Same as O6 |
| Caveat | "Capacity measures are SY 2023-24 only; this shows enrollment and school counts." |
| Copy | Title: "Learners and schools, SY 2020-21 to 2025-26" |

### Context band · never in the tier

| ID | Visual | Type, size | Field | Notes |
|---|---|---|---|---|
| P6 | Children aged 5–17 and enrollment | Grouped bar, w4 h7 | `school_age_population`, `enrollment_all_sectors` for 2020 and 2024 | Gap and gap share as labels. A negative gap is labelled "school hub: enrols children from nearby LGUs". Show `gap_change_2020_2024` in the subtitle. If `is_2020_2024_geography_comparable` is false: "Boundaries changed; compare the two years with care" |
| P7 | School-age population by age | Line, w4 h7 | `ds_age`, ages 5–17, female + male, 2020 vs 2024 | Shows which ages grew or shrank, the pipeline for future enrollment |
| P8 | Enrollment by sector | Stacked bar, w4 h7 | `ds_sector`, SY 2020-21 vs SY 2024-25, Public / Private / SUC-LUC | Public share as a label |
| P9 | Poverty 2023 | Counter, w12 h2 | `poverty_incidence` with `poverty_ci90_lower`–`upper` | "Less precise" when `cv_over_20`. Missing: "{poverty_status}: {status_reason}", never 0 |

Band copy: "Context only. These help explain the place; they never change the tier, and they do not show cause."

### Barangays in this LGU

#### P10 · Schools and learners by barangay

| Item | Content |
|---|---|
| Type | Horizontal bar, w5 h9 |
| Question | Where in the LGU are the learners and schools? |
| Field | `learners` (bar) and `schools` (label) by barangay from `ds_barangay` |
| Sorting | No-public-ES barangays first, then learners descending |
| Encoding | Barangays without a public ES are marked "No public ES" in the label, not by colour only |
| Size limit | The LGU median is 21 barangays, but some have hundreds (897 at most). Show the first 25 and say "{n} more in the table" |
| Cross-filter | Clicking a barangay filters P11–P15 |
| Caveat | "Sorted for reading, not a priority order. Barangays are never ranked." |
| Copy | Title: "Learners and schools by barangay" |

#### P11 · Barangay table

| Item | Content |
|---|---|
| Type | Table, w7 h9 |
| Columns | Barangay, urban/rural, public schools, offers public ES (yes/no), learners, instructional rooms, teachers |
| Note above | "{schools_without_barangay_match} schools match this LGU but not a barangay, so the no-ES count is an upper bound." Shown only when greater than 0 |
| Cross-filter | Clicking a row filters P13–P15 |
| Download | CSV |
| Empty state | "No barangays found for this LGU in PSGC." |

### Schools in this LGU

#### P13 · School pressure

| Item | Content |
|---|---|
| Type | Scatter, w8 h8 |
| Question | Which schools are crowded on rooms, teachers, or both? |
| Field | x = learners per room (all levels); y = learners per teacher at the selected level; size = learners |
| Encoding | Colour by flag (outlier, missing, none) in neutral and amber, never tier colours; flag also in the tooltip |
| Reference | Dashed lines at the LGU's own ratios |
| Tooltip | School, barangay, annex, learners, rooms, teachers at the level, both ratios, flags, how far above the outlier fence |
| Filters | LGU, Education level, School status, barangay cross-filter |
| Empty state | Missing rooms or teachers are excluded from the plot and counted in P14 |
| Copy | Title: "Schools by room and teacher pressure" |

#### P14 · What to check

| Item | Content |
|---|---|
| Type | Bar, w4 h8 |
| Field | Schools per issue: room outlier, teacher outlier, rooms not reported, zero rooms, a level with no teachers |
| Filters | LGU, Education level, barangay cross-filter. Ignores School status, because it is the selector for it |
| Cross-filter | Clicking an issue sets School status |
| Caveat | "Outlier schools stay in every published number. They are flagged so their reports can be checked with the Schools Division Office." |

#### P15 · School action table

| Item | Content |
|---|---|
| Type | Table, w12 h10 |
| Columns | School ID, school, barangay, main/annex, levels offered, learners, rooms, learners per room, teachers and learners per teacher at the selected level, temporary and makeshift rooms, flags, distance above fence |
| Sorting | Flagged first, then learners per room descending |
| Filters | All Profile filters and cross-filters |
| Download | CSV, titled "{LGU} school check list SY 2023-24" |
| Copy | Title: "Schools to check" |

---

## 6. View 3: Data and Method

**Purpose:** Can planners trust the prioritization, and what can it not tell them?

**Page filters**

| Filter | Options | Applies to |
|---|---|---|
| Measure | AP1, AP2, AP3 ES, AP3 JHS, AP3 SHS | M2, M7 |
| Validation scenario | National ranking, 0.85 line, 0.80 line, 95% gate, without outliers | M4 |
| Coverage band | 95–100, 90–95, 80–90, 50–80, under 50, no value | M2 |

### Lead section (presentation)

#### M1 · Does the Critical list hold?

| Item | Content |
|---|---|
| Type | Grouped bar, w6 h8 |
| Label | National method diagnostic |
| Field | For each scenario, two bars: Critical count, and how many are also Critical under the main rule. Scenarios: main (`tier_code='3'`), national (`national_tier_code='3'`), 0.85 (`critical_at_line_085`), 0.80 (`critical_at_line_080`), 95% gate (`critical_at_gate_95`), without outliers (`tier_code_without_outliers='3'`) |
| Reference | 80% retention line (the D-057 revisit trigger), shown as a label "{x}% kept" on each scenario |
| Filters | LGU type only |
| Caveat | "Lower lines only add LGUs. None of these change the published tier." |

#### M2 · Coverage and Data review

| Item | Content |
|---|---|
| Type | Stacked bar (w4) plus bar (w2), w6 h8 |
| Field | Left: LGUs per coverage band per measure. Right: Data review LGUs by the measure that failed |
| Filters | Global, Measure, Coverage band |
| Caveat | "An LGU under 90% coverage is Data review, not low pressure." |

#### M3 · What this can and can't tell you

Text, w12 h4. A plain summary first, then a "Technical rules" section that lists D-057 steps 1–7.

**It can tell you**
- Which LGUs carry more learners per school, room and teacher than others of their type.

**It can't tell you**
- How many rooms or teachers to add.
- What happens across school years. The capacity measures are one year.
- How far children travel.
- Anything about why: poverty and the gap are context only.
- Data reported by schools is taken as reported.

### Details (Q&A)

| ID | Visual | Type, size | Field | Filters | Label |
|---|---|---|---|---|---|
| M4 | Main tier vs scenario tier | Heatmap, w4 h7 | Count of LGUs by main `tier_code` × the selected scenario's tier | LGU type, Scenario | National method diagnostic |
| M5 | Classroom and teacher percentiles | Scatter, w4 h7 | x = `ap2_percentile`, y = `ap3_percentile`, colour = tier, lines at 90 | Global | |
| M6 | Do the measures say the same thing? | Heatmap, w4 h7 | `ds_overlap`: Spearman for each pair by type, plus % high-on-A also high-on-B (10% expected if unrelated) | LGU type | National method diagnostic |
| M7 | LGUs whose tier would change without outliers | Table, w8 h7 | `tier_code <> tier_code_without_outliers`: LGU, tier, tier without outliers, `outlier_schools` | Global, Measure | |
| M8 | Outlier schools by measure | Bar, w4 h7 | `lgu_priority_outlier_schools` by `measure`, `education_level_code`, `lgu_type` | Global | |
| M9 | Which school years each source covers | Heatmap, w6 h5 | `ds_sources` | None | |
| M10 | Latest quality checks | Stacked bar, w6 h5 | `ds_checks` by `layer` × `status` | None | "Run {run_id}, {checked_at}" |

---

## 7. Visual interaction matrix

| Source action | Overview effect | Profile effect | Data and Method effect |
|---|---|---|---|
| Global Region / Province | Narrows all; K1–K4 recount | Narrows the LGU list; resets an invalid LGU | Narrows M2, M5, M7, M8 only |
| Global LGU type | Narrows all | Narrows the LGU list | Narrows every visual except M9–M10 |
| Map click (O1) | Filters O5 to the LGU | | |
| Combination bar click (O2) | Sets High measure; filters O1, O3, O5 | | |
| Region bar click (O3) | Sets the Region global filter | Carries over | Carries over |
| Table LGU click (O5) | | Opens the Profile for that LGU | |
| Education level (Profile) | | P4 highlight; P13 y-axis; P15 teacher columns. AP1, AP2 and the cards are unchanged | |
| Barangay click (P10/P11) | | Filters P13–P15 | |
| School status (Profile) | | Filters P13 and P15 only | |
| Scenario (D&M) | | | Changes M4's comparison column |

---

## 8. Narrow-screen behaviour

Databricks stacks widgets in grid order on narrow screens, so the layout order is the reading order:

- KPIs wrap two per row.
- Side-by-side pairs stack left first: map before the combination bar, cards AP1 → AP2 → AP3.
- Tables keep the first three columns (rank, LGU, tier) and scroll horizontally for the rest.
- On the Profile, the identity card and KPIs stay first, so a phone user sees the tier and its reason before scrolling.

---

## 9. Build order

1. **Datasets:** `ds_priority` with `combo`, `ds_priority_national`, `ds_ap3_levels` baseline, `ds_barangay`, `ds_schools`, `ds_overlap`. Validate each against the Analytics totals (section 10) before building visuals.
2. **Global filters and their cascade.**
3. **Overview:** K1–K4, O1, O5 (the answer), then O2, O3, O4, O6, O7.
4. **Profile:** identity card, PK1–PK4, P1–P3, P4–P5, context band, barangay section, school section.
5. **Test** carrying the LGU from O5 to the Profile (section 2, option a, then b).
6. **Data and Method:** M1–M3, then M4–M10.
7. **Copy pass:** check every title and caveat against the wording rules in section 3.
8. **Acceptance checklist.**

---

## 10. Acceptance checklist

**Metric accuracy**
- [ ] K1 with no filters = 1,642 and equals `COUNT(*)` of `lgu_priority`.
- [ ] K3 = the `tier_code IN ('3','2')` count; Critical + Elevated + Targeted + Monitor + Data review = K1.
- [ ] K2 equals `SUM(public_learners)` from `ap1_school_provision` for SY 2023-24.
- [ ] A spot-checked Profile card shows the same value, percentile, relative pressure and coverage as its `lgu_priority` row.
- [ ] Relative pressure × baseline = observed ratio (within rounding) on three LGUs.
- [ ] The P4 level baseline for the AP3 level equals `ap3_same_type_baseline`.
- [ ] `ds_barangay` count of regular barangays and no-ES barangays equals `regular_barangays` and `barangays_without_public_es` for three LGUs.
- [ ] `ds_schools` learners and rooms sum to `ap2_classroom_pressure.learners_in_ratio` and `rooms_in_ratio` for usable schools in three LGUs.
- [ ] P6 2020 and 2024 values match `ap4_population_enrollment_gap`.
- [ ] M1 main Critical count equals K3's Critical count with no filters.

**Filter behaviour**
- [ ] Choosing a region never changes any LGU's percentile, relative pressure or tier.
- [ ] Province options follow Region; a stale province clears.
- [ ] An LGU outside new global filters resets with the visible notice.
- [ ] National-diagnostic visuals do not change with Region or Province but do with LGU type.
- [ ] Education level changes only P4, P13 and P15.
- [ ] School status changes only P13 and P15.
- [ ] Page filters reset on page change; global filters persist.

**Wording and accessibility**
- [ ] No banned term appears anywhere (section 3).
- [ ] AP4 and poverty sit only in "Context only" sections.
- [ ] Every tier is readable without colour (label or text column).
- [ ] Data review never shows as Monitor or as low pressure.
- [ ] Every capacity value shows SY 2023-24 nearby.

---

## 11. Draft build notes

The draft is [`reached_planner_v3.lvdash.json`](reached_planner_v3.lvdash.json), deployed as `resources.dashboards.reached_planner` in `databricks.yml`. Where the build differs from this outline:

- **Barangay selection is a page filter, not a click.**
  - AI/BI cross-filters only widgets on the same dataset, and the barangay bar (first 25) and the school list are different datasets.
  - The Profile therefore has a **Barangay** filter that narrows the school scatter, issue counts and school table.
- **High measure is a page filter, not a click.** Clicking a bar in "What drives the priority" does not set it.
- **Map and table cross-filter.** The tier map and the priority table share one dataset (`ov_lgu`), so clicking an LGU on the map narrows the table.
- **Education level defaults to "Level that sets AP3",** which resolves to `ap3_highest_level` for the chosen LGU. It changes only the teacher columns of the school list, the school scatter's y-axis and the teacher-outlier count.
- **The selected LGU carries no state across pages.** The Profile's LGU filter defaults to the top-ranked LGU in the global filters. A selection outside the global filters falls back to that LGU, and the identity card says so.
- **National method diagnostics** ("Does the Critical list hold?", the scenario heatmap, measure overlap) take only the LGU type parameter, so Region and Province never narrow them.
- **Data review LGUs are blank on the map** (no tier level) and are named in the table's Data review column.
- **Tested on the local DuckDB build only:** every dataset and widget query under five filter scenarios. Profile numbers were cross-checked against `lgu_priority`, `ap1_school_provision` and `ap2_classroom_pressure` for five LGUs. Not yet opened in Databricks.
