# Metric and dashboard specification

**Status:** Implementation contract for Gold facts and Analytics calculations. The formulas, grains, scopes, source fields, and missing-data rules below are ready to implement under #46. A metric is not dashboard-ready until it also passes the validation gate in this document. No metric is an official DepEd indicator or adequacy standard unless its row explicitly says so.

## Purpose and document boundary

This document translates the approved [business and analytical questions](business-analytics-problem.md) into implementation-ready measures and dashboard fields. It owns formulas, grains, filters, comparison rules, display fields, and validation status. It does not redefine the approved questions, assign datasets to scope, describe stakeholder authority, or establish external standards; those belong to the business-question document, [dataset use map](dataset-use-map.md), [stakeholder document](stakeholders.md), and [national benchmark register](national-benchmarks-and-indicators.md).

## Current validation conclusion

The metric contracts are complete enough to build and test the Gold facts. Publication readiness remains separate: a complete formula can still be unavailable for a period, limited by source coverage, or blocked from an official benchmark comparison.

| Area | What is supported now | What prevents final approval |
|---|---|---|
| **AP1 · Schools** | Public-school and enrollment counts can be aggregated by LGU and school year; multi-level, active-school, annex, and unmatched-barangay rules are set | Publication must show geography-match coverage and preserve the screen's distance, demand, and feasibility caveats |
| **AP2 · Classrooms** | SY 2023-24 enrollment and facilities match one-to-one by `school_id`; classroom counts are typed; levels are combined into one total-room ratio, and all-blank room counts are missing, not zero; EDCOM 2/PIDS supplies the adopted >=50 congestion screen | The facilities field uses the broader NSBI “instructional classroom” definition. The result is a congestion screen, not DepEd's published classroom–learner ratio or an RA No. 7880 shortage calculation |
| **AP3 · Teachers** | SY 2023-24 enrollment and personnel match one-to-one by `school_id`; personnel counts are typed; the ratio is by level; the World Bank study supplies an aggregate ES reference and RM 379 supplies deployment-equivalent references for JHS and SHS | The source cannot show whether one person is counted in two columns, and without a mother-school ID the ratio remains project-defined. The ES reference is based on older DepEd service standards |
| **AP4 · Population and enrollment** | Ages 5–17, the two matched periods (2020 and 2024), and all-sector enrollment are defined; PSA single-year-age workbooks for every city and municipality were found, profiled, and loaded in Bronze for 2020 and 2024; SY 2020-21 and SY 2024-25 enrollment are acquired, validated in Bronze, and published in Silver | Built in `ap4_enrollment_trend` (#208) from `fact_city_school_age_population` (2020 and 2024) and `fact_school_enrollment`. The gap is not an out-of-school count, and the change is NULL where the geography is not comparable |
| **Poverty 2023 · Context** | PSA's 2023 estimate, 90% interval, and CV for 1,597 of the 1,642 cities and municipalities; the status of the other 45 is defined (D-046) | `dim_city_poverty` is built in Gold with D-046's checks (#174), and the ERD is approved (D-048); it is context only and never an analytical result |
| **Resource-gap estimates** | AP2 and AP3 now carry benchmark statuses that describe pressure | Neither benchmark authorizes a room or teacher shortage estimate. The current NSBI room field remains incompatible with RA No. 7880, and RM 379 deployment factors are not staffing entitlements for this aggregated dataset |

The DepEd evidence for these limitations is recorded in the source cards for [enrollment](../data/source-inventory/deped_enrollment/README.md#limitations-for-analysis), [facilities](../data/source-inventory/deped_facilities/README.md#limitations-for-analysis), and [personnel](../data/source-inventory/deped_personnel/README.md#limitations-for-analysis), with observed tests in their linked profiles.

## Contract conventions

Every published measure must declare:

1. **grain** — LGU, school year, and education level where supported;
2. **scope** — public schools only for AP1 to AP3; all sectors for AP4; Philippine Schools Overseas excluded from every LGU result;
3. **numerator and denominator** — exact approved fields and filters, covering the same schools, education level, school scope, geography, and period;
4. **aggregation** — calculate ratios from aggregated sums, not the unweighted average of school ratios;
5. **missingness** — NULL remains missing and is never converted to zero without publisher evidence;
6. **coverage** — both school and enrolled-learner coverage accompany AP2 and AP3, and the share of active public schools with complete all-level enrollment accompanies AP1 for the [priority rule](#priority-rule);
7. **geography** — the school-to-PSGC match version and unmatched/excluded counts;
8. **period** — school year or population reference year shown on every result; and
9. **quality status** — unresolved outliers, annex handling, and definition mismatches remain visible.

### Education levels

Every level-specific measure uses these enrollment columns (D-047):

| Level | Enrollment columns |
|---|---|
| **ES** | Kindergarten, Grades 1–6, and ES non-graded |
| **JHS** | Grades 7–10 and JHS non-graded |
| **SHS** | Grades 11–12, all strands |

Non-graded learners are learners in special education classes without a grade level. They count in their level: 82,347 public-school learners in SY 2023-24.

## Implementable source contract

The Gold build uses the reviewed tables and fields below. Brace notation is shorthand for every named expansion, not a wildcard evaluated at runtime. Implementations must name the expanded columns explicitly so a source schema change fails review or validation instead of silently changing a metric.

| Output | Reviewed input fields | Grain and required filters |
|---|---|---|
| Enrollment by level | `deped_enrollment_clean.school_id`, `school_year`, `sector`, `annex_status`, `offers_es`, `offers_jhs`, `offers_shs`, `is_overseas`; ES counts `kinder_{male,female}`, `g1_{male,female}` through `g6_{male,female}`, `esng_{male,female}`; JHS counts `g7_{male,female}` through `g10_{male,female}`, `jhsng_{male,female}`; SHS counts `{g11,g12}_{abm,arts,gas,humss,maritime,sports,stem,tvl,unique}_{male,female}` plus `g11_sshs_{acad,techpro}_{male,female}` where those columns exist in the approved schema version. The exact expansions are listed in the [Silver enrollment dictionary](../data/silver/deped-enrollment-clean.md). | School x school year x education level. AP1 to AP3 require `sector = 'Public'` and `is_overseas = false`. AP4 accepts `Public`, `Private`, and `SUC/LUC` and excludes `PSO` or `is_overseas = true`. Geography and `psgc_match_status` come from the reviewed Integration result. |
| Classroom capacity | `deped_facilities_clean.school_id`, `school_year`, `es_classrooms_instructional`, `jhs_classrooms_instructional`, `shs_classrooms_instructional` | School x school year. Require public scope. Sum the three room fields that are not NULL; return NULL when all three are NULL. Do not substitute makeshift rooms, temporary learning spaces, or non-instructional rooms into this denominator. |
| Teacher capacity | The level-specific personnel fields listed immediately below | School x school year x education level. Require public scope. Principals, assistant principals, administrative, health, guidance, library, security, utility, and all other non-teaching roles are excluded. |
| DepEd source availability | `fact_school_year_source_availability.school_year`, `source_id`, `has_data` | School year x source. Require one row for each school year and each of `deped_enrollment`, `deped_facilities`, and `deped_personnel`. Use this fact only to determine whether a source has data for the selected year. It does not establish school or education-level coverage. |
| AP1 school-age population (context) | `fact_city_school_age_population.city_mun_psgc_code`, `reference_year`, `age`, `sex`, `population`, `psgc_match_status` | City or municipality x reference year. Use only `reference_year = 2024`, ages 5–17, `sex IN ('male', 'female')` and `psgc_match_status = 'matched'`, following the team's BP and AP metrics; label the value **School-age population 2024**. Total population (`fact_city_population`) is not used by AP1. |
| AP4 school-age population | `fact_city_school_age_population.city_mun_psgc_code`, `reference_year`, `age`, `sex`, `population`, `psgc_match_status`, `is_2020_2024_geography_comparable` | City or municipality x reference year. Sum `sex IN ('male', 'female')` and `age BETWEEN 5 AND 17`; use only reviewed PSGC matches. Never add a published both-sexes total to the male and female rows. |

### AP3 included personnel fields

`teacher_count` is the sum of the following fields for the row's education level:

- **ES:** `es_teacher_i` through `es_teacher_iii`; `es_master_teacher_i` through `es_master_teacher_iv`; `es_head_teacher_i` through `es_head_teacher_vi`; `es_sped_sned_teacher_i` through `es_sped_sned_teacher_v`; and the eight locally funded fields `kinder_teachers_{sef_province,sef_municipality_city,lgu_funding,other_funding}` and `es_teachers_{sef_province,sef_municipality_city,lgu_funding,other_funding}`.
- **JHS:** `jhs_teacher_i` through `jhs_teacher_iii`; `jhs_master_teacher_i` through `jhs_master_teacher_iv`; `jhs_head_teacher_i` through `jhs_head_teacher_vi`; `jhs_sped_teacher_i` through `jhs_sped_teacher_v`; `jhs_special_science_teacher_i`; `jhs_instructor_i` through `jhs_instructor_iii`; and `jhs_teachers_{sef_province,sef_municipality_city,lgu_funding,other_funding}`.
- **SHS:** `shs_teacher_i` through `shs_teacher_iii`; `shs_master_teacher_i` through `shs_master_teacher_iv`; `shs_head_teacher_i` through `shs_head_teacher_vi`; `shs_special_science_teacher_i`; and `shs_teachers_{sef_province,sef_municipality_city,lgu_funding,other_funding}`.

The four funding subtotals use only the corresponding `*_teachers_*` fields above. They are already included in `teacher_count` and must never be added to it again. For ES, each funding subtotal combines its Kindergarten and ES fields.

### Enrollment aggregation and missingness

Gold derives each level's `learner_count` from an explicit set of applicable source columns for that delivery. A column is not applicable only when the reviewed source metadata says that the delivery did not publish that measure. The current exceptions are:

- `g11_unique_{male,female}` and `g12_unique_{male,female}` are not applicable before SY 2024-25 because DepEd states that these fields start in SY 2024-25;
- `g11_sshs_{acad,techpro}_{male,female}` are not applicable before SY 2025-26 and do not exist in schema v1; and
- a future delivery may change this set only through reviewed source metadata and a metric-contract change. Gold must not infer applicability merely because a column happens to be all NULL.

For each school, school year, and level:

1. When `is_offered = false`, set `learner_count = 0`. Source count cells remain unchanged upstream, and validation must fail if any applicable cell is positive because the offering flag and counts conflict.
2. When `is_offered = true`, sum the applicable cells only when every applicable cell is non-NULL. A recorded zero participates in the sum as zero.
3. When `is_offered = true` and one or more applicable cells are NULL, set `learner_count = NULL`. Do not produce a partial sum by coalescing the missing cells to zero.
4. When the offering flag is NULL, retain the row for reconciliation, set `learner_count = NULL`, and fail the Gold gate. Gold must not infer the offering from the counts.

The Gold validation must report, by school year and education level, the numbers of offered rows with complete counts, offered rows with partially published counts, offered rows with every applicable count NULL, non-offered rows with positive counts, and rows with a NULL offering flag. It must also report the sum of the non-NULL published cells on partial rows as an audit value, never as `learner_count`. AP1 to AP4 exclude NULL `learner_count` values from their enrollment sums and publish the affected school count plus the observed non-NULL learner-cell sum as an enrollment-coverage warning. An all-level school total is the sum of ES, JHS, and SHS only when every offered level has a non-NULL `learner_count`; if any offered level is NULL, the all-level total is NULL. This total controls the all-level AP1, AP2, and AP4 enrollment sums, but it does not control whether the school is active. A school is active when at least one offered level has a complete `learner_count` above 0. A level-specific result may use a complete level even when another offered level is NULL, but it must still carry the school's partial-reporting warning. This keeps schema absence, published blanks, recorded zero, and complete enrollment distinct.

For classroom and teacher totals, sum non-NULL included fields and return NULL only when every included field is NULL. A recorded zero remains zero. The Gold validation must report rows with a mixture of NULL and non-NULL included fields so partial reporting is visible. A ratio denominator is usable only when the resulting total is greater than zero.

`dim_school_year` holds only `school_year`, `start_year`, and `end_year`. Source availability belongs in `fact_school_year_source_availability`, following the six-fact Gold model. When `has_data = false`, the dashboard shows the affected source measure as **not available** for that school year. When `has_data = true`, consumers must still calculate and display fact-level school and learner coverage because availability does not mean that every school or education level has a usable value.

## Analytical metric contracts

These formulas are the implementation baseline. They do not by themselves authorize dashboard publication.

### AP1 · School-provision context

```text
learners_per_public_school = complete_public_school_enrollment / active_public_schools_with_complete_all_level_enrollment
school_age_population_per_public_school = school_age_population_2024 (ages 5–17) / public_school_count

barangays_without_public_es =
    PSGC barangays in the LGU with no matched public school offering elementary
barangays_without_public_es_pct =
    barangays_without_public_es / PSGC barangays in the LGU * 100
```

Use `COUNT(DISTINCT school_id)` and sum enrollment at the same LGU, education-level, and school-year grain. For the all-level school count, count an active multi-level school once. For a level-specific school count, count it once in every level where `is_offered = true`; do not infer an offering from a positive learner count or from another source. A school is active when at least one offered level has a complete `learner_count` above 0, even when another offered level is incomplete. For `learners_per_public_school`, use only active public schools whose all-level total is complete in both the numerator and denominator. Also publish the total active-public-school count, the number excluded from this ratio because their all-level total is incomplete, and the non-NULL learner-cell audit sum. `school_age_population_per_public_school` divides the LGU's 2024 school-age population (PSA, ages 5–17) by the full active-public-school count. It is labelled **School-age population 2024 per public school**, not schools per 10,000 residents. Both AP1 ratios are descriptive context under D-061 and are not ranked. Because learners may attend school outside their LGU, neither is read as a school shortage. A NULL or zero school count produces a NULL ratio with its reason. These measures describe provision and school size; they do not measure travel access or prove that construction is required.

The AP1 population join is fixed and must not select a population row by proximity, latest-year logic, or an unconstrained join:

| Enrollment school year | Population reference year | Display label |
|---|---:|---|
| SY 2020-21 | 2024 | Population 2024 |
| SY 2023-24 | 2024 | Population 2024 |
| SY 2024-25 | 2024 | Population 2024 |
| SY 2025-26 | 2024 | Population 2024 |

A newly approved enrollment school year also maps to 2024 until a reviewed decision changes the AP1 reference population. The implementation must join on `city_mun_psgc_code` and `reference_year = 2024`, assert at most one available population row per LGU, and retain LGUs without an available population row with a NULL ratio and explicit reason.

**Which schools count.** `public_school_count` counts active public schools, including annexes (D-047):

- **Active school:** at least one offered level has a complete `learner_count` above 0 in that school year. A school with no complete positive offered level stays in the record and is shown in the coverage counts, but it is not counted and does not serve a barangay. There are 23 such public schools in SY 2020-21, 4 in SY 2023-24, 1 in SY 2024-25, and 3 in SY 2025-26. Separately, 21 public schools in SY 2025-26 offer SHS but have every applicable SHS count blank. They retain active status when another offered level has a complete positive count, while their all-level total remains NULL and is excluded from the all-level learner ratio.
- **Annexes:** annex and extension schools count as schools. The label is **public schools (including annexes)**, with the annex count shown beside it. DepEd publishes no mother-school ID (#134), and 52 annexes are the only public elementary school in their barangay, so dropping them would mark served barangays as unserved. The Technical Notes rule that adds annexes to their mother school (p. 8) applies only to the teacher–learner ratio.

The barangay measures follow DepEd Order No. 40, s. 2014, which expects at least one Kindergarten-to-Grade-6 school for every barangay (see the [national benchmark register](national-benchmarks-and-indicators.md#ap1--school-provision-references)). They are calculated per city or municipality and school year from `member_type = 'regular'` barangays in the PSGC 2Q 2026 master and are never ranked by barangay. A public school serves a barangay only when it is active, offers ES, and has a reviewed match to that regular barangay. A school assigned to the LGU's unknown-barangay member is retained in LGU totals but does not serve a specific barangay. If an LGU has one or more such schools, show `at most N barangays without a matched public elementary school`, the unmatched-school count, and geography-match coverage. A barangay without its own school may still be served by a nearby school, so the count is a screen for review, not evidence that a school is needed.

**Validation status:** built for SY 2023-24 in `ap1_school_provision` (#208): learners per public school and school-age population per public school as descriptive context, with coverage and no percentile or priority flag. A school that offers a level but has every offered count blank is not active, but it is missing data rather than a closed school, so it is added to the coverage denominator (`blank_enrollment_school_count`). The barangay measures are not built yet. The active-school, multi-level, zero-enrollment, annex, and unmatched-barangay rules are set. Dashboard publication still requires the validation gate and the stated caveats.

### AP2 · Classroom pressure

```text
total_instructional_rooms =
    sum of es_, jhs_, and shs_classrooms_instructional that are not blank
    (missing when all three are blank)

learners_per_reported_instructional_room =
    sum(total_learners for denominator-usable schools)
    / sum(total_instructional_rooms for the same schools)

school_coverage_pct =
    active_public_schools_with_complete_enrollment_and_usable_room_count
    / (active_public_schools_in_scope + schools_with_every_offered_count_blank) * 100

learner_coverage_pct =
    enrollment_in_schools_with_usable_room_count / public_school_enrollment * 100

school_screen =
    "passes" when a usable school's learners / reported rooms >= 50
    "does not pass" otherwise

lgu_benchmark_status =
    "not assessed" when learner coverage is below 90% or the LGU ratio is unavailable
    "reported congestion identified" when one or more usable schools pass
    "no reported congestion identified" otherwise
```

The ratio uses each active public school's total learners and total instructional rooms across all levels, per school year, and then sums to the city or municipality (D-047). Its numerator and denominator use the same set of schools. This follows the form of the Technical Notes classroom–learner formula (p. 8), total learners over total classrooms; the room definition still differs, as explained below. A school is denominator-usable when its total rooms are above 0. When all three room counts are blank the total is missing, not zero (608 public schools in SY 2023-24), and its school and learner counts are reported separately. A reported total of 0 is also excluded from both ratio sums and gets a separate zero-denominator school and learner count. If an LGU has no denominator-usable school, its ratio is NULL, never 0.

Levels are combined because rooms are shared across levels: 768 public schools have JHS learners and ES rooms but no JHS rooms. Learner coverage is 99.3% with totals, compared with 98.8% when learners and rooms are matched level by level.

The dashboard label must say **learners per reported instructional room**, with the source shown separately as **DepEd School Facilities (NSBI)**. It must not be labelled “DepEd classroom–learner ratio.” NSBI is the source system behind the DepEd School Facilities data; it is not a different facilities dataset. DepEd's source documentation says `*_classrooms_instructional` includes ALS, audio-visual, computer, industrial-arts, home-economics, and laboratory rooms, while its published classroom–learner indicator uses Kindergarten-to-Grade-12 classrooms. The available data therefore tend to produce a lower ratio than the official indicator. PIDS Discussion Paper 2025-10 uses at least 50 learners per classroom as an illustrative school-level congestion definition. The project applies the line to each usable school's all-level reported-room ratio, then aggregates passing schools, affected learners, and the affected-learner share to the LGU. Because the paper analyzes school-and-level BEIS classroom data while the project has a broader all-level NSBI room total, the output is labelled **PIDS-style illustrative reported-room screen**. It is not an exact reproduction, official ratio, shortage count, or construction entitlement.

**Validation status:** built for SY 2023-24 in `ap2_classroom_pressure` (#208), gated at 90% learner coverage under D-061. The output includes `congestion_benchmark = 50`, affected schools and learners, affected-learner share, and a validated `benchmark_status`. Outlier schools are counted and never change a result. School coverage is published beside it, counting a school as covered only with both a complete enrollment total and a usable room count, over active plus blank-enrollment schools. A project-defined screening measure, limited to SY 2023-24. Levels are combined (D-047). Review the extreme upper tail before dashboard publication.

### AP3 · Teacher pressure

```text
for each level (ES, JHS, SHS):

learners_per_teacher =
    sum(level enrollment for denominator-usable schools
        plus level enrollment for annexes that report 0 teachers)
    / sum(teacher_count for denominator-usable schools)

es_benchmark_max_learners_per_teacher = 35
jhs_benchmark_max_learners_per_teacher = 45 * 4 / 5 = 36
shs_benchmark_max_learners_per_teacher = 40 * 6 / 9 = 80 / 3

level_benchmark_status =
    "not applicable" when the LGU does not offer the level
    "not assessed" when the level does not pass the coverage gate
    "above historical study reference" or "above derived deployment comparison" when its ratio is above the applicable value
    "at or below historical study reference" or "at or below derived deployment comparison" otherwise

school_coverage_pct =
    active_public_schools_with_usable_teacher_count / active_public_schools_in_scope_at_level * 100

learner_coverage_pct =
    enrollment_included_in_ratio / public_school_enrollment_at_level * 100
```

For AP3, a school is in scope at a level when it is active, public, not overseas, and `is_offered = true` for that level. `enrollment_included_in_ratio` includes learners at denominator-usable schools and the explicit zero-teacher annex exception. A zero-teacher annex contributes its learners to the ratio numerator and learner coverage, but it does not count as a school with a usable teacher denominator in school coverage. Report the zero-teacher annex school and learner counts beside both coverage measures so the exception remains auditable.

The ratio is calculated by level because the Technical Notes define the teacher–learner ratio “at a specific level.” `teacher_count` at a level is the sum of these personnel columns at that level (D-047):

- Teacher I–III, Master Teacher I–IV, and Head Teacher I–VI;
- SPED/SNED teachers, Special Science teachers, and Instructors;
- locally funded teachers paid from SEF province, SEF city/municipality, LGU, or other funding. Kindergarten locally funded teachers go under ES.

Principals and all non-teaching staff are excluded. This gives 935,421 public-school teachers in SY 2023-24. The four locally funded columns are shown per level as a funding split.

A non-annex school is denominator-usable at a level only when `teacher_count > 0`. A school with learners at a level but teachers only at another level is flagged: 255 schools at JHS and 109 at SHS in SY 2023-24. Its learners at that level have no usable denominator there and appear in the coverage gap. A NULL teacher count is missing, not zero, and never receives the annex-zero exception. If an LGU has no positive teacher denominator at the level, its ratio is NULL, never 0.

Known limit: the source cannot show whether one person is counted in two columns.

The [World Bank Philippines Education Note](https://documents.worldbank.org/curated/en/519221468948112271/pdf/106960-REVISED-16-PGS-PH-PETS-QSDS-Note-2.pdf), pages 3 and 15, gives an average elementary reference of 35 learners per teacher derived from older DepEd service standards. A value above 35 is `above historical study reference`; equality or below is `at or below historical study reference`. Page 5 of [DepEd CALABARZON RM 379, s. 2025](https://depedcalabarzon.ph/wp-content/uploads/2025/05/Personnel-RM-2025-379.pdf) gives maximum class sizes and deployment factors. JHS has a maximum of 45 learners per class and 5 teachers for every 4 classes, giving 36 learners per teacher. SHS has a maximum of 40 learners per class and 9 teachers for every 6 classes, giving 80/3, or about 26.67, learners per teacher. Values above those references are `above derived deployment comparison`; equality or below is `at or below derived deployment comparison`. The overall status is `pressure signal identified` whenever any offered level that passes coverage is above its reference. Otherwise it is `not fully assessed` if an offered level fails coverage, and `no pressure signal identified` only when all offered levels are assessed and none is above. This ordering prevents incomplete data at one level from hiding an observed signal at another.

The published 45 for JHS and 40 for SHS are **learners per class**, not learners per teacher. AP3 cannot compare its learner-to-teacher ratio directly with either number because a secondary class is served by several subject teachers. RM 379's staffing factors make the units compatible: four JHS classes at the maximum hold `4 * 45 = 180` learners and are assigned five teachers, so `180 / 5 = 36` learners per teacher; six SHS classes at the maximum hold `6 * 40 = 240` learners and are assigned nine teachers, so `240 / 9 = 80/3`, about 26.67 learners per teacher. Applying 45 or 40 directly to AP3 would treat one class as one teacher and under-flag pressure. For example, a JHS result of 40 learners per teacher is below the class-size maximum of 45 but above the compatible deployment reference of 36. The derived values are therefore transparent unit conversions, not ratios directly printed in the memorandum and not estimates of teachers needed.

The source measures personnel actually working in public schools; they are not authorized plantilla positions, vacancies, or approved new items.

DepEd's documented teacher–learner method adds annex enrollment and teachers to the mother school before division. DepEd publishes no mother-school ID (#134), so AP3 cannot do this school by school. The ratio is labelled **project-defined** and must not claim to reproduce DepEd's indicator (D-047). An annex that reports 0 teachers keeps its learners in the city or municipality total instead of being dropped by the usable-denominator rule: 48 annexes with 21,114 learners in SY 2023-24. Because the ratio is summed to the city or municipality, this matches DepEd's add-to-mother rule whenever the annex and its mother school are in the same city or municipality.

**Validation status:** built for SY 2023-24 in `ap3_teacher_pressure` (#208): ES, JHS and SHS side by side, each with its ratio, coverage and bounded reference status. The three reference values, level statuses, and overall status are validated independently. AP3 has no percentile or teacher-priority rank. It is a project-defined ratio by level, limited to SY 2023-24, and is not DepEd's teacher–learner ratio. Resolve the reviewed personnel outliers before dashboard publication.

### AP4 · School-age population and enrollment gap

```text
school_age_population =
    PSA Total Population, ages 5–17, both sexes
enrollment_all_sectors =
    enrollment in public, private, and SUC/LUC schools,
    excluding Philippine Schools Overseas

population_enrollment_gap = school_age_population - enrollment_all_sectors
gap_share = population_enrollment_gap / school_age_population
gap_change_2020_2024 = population_enrollment_gap (2024) - population_enrollment_gap (2020)

public_school_share = public_school_enrollment / enrollment_all_sectors
```

**Matched periods.** "Over time" means two points. Each pairs a census with the school year that starts in the same year:

| AP4 period | Population | Enrollment |
|---|---|---|
| **2020** | 2020 Census of Population and Housing (CPH), reference date May 1, 2020 | SY 2020-21 |
| **2024** | 2024 Census of Population (POPCEN), reference date July 1, 2024 | SY 2024-25, which opened on July 29, 2024 (DepEd Order No. 9, s. 2024) |

SY 2023-24 and SY 2025-26 have no census in the same year, so their AP4 value is **not available**. Their enrollment can still appear in a separate enrollment trend. Version 1 does not interpolate or extrapolate population between or beyond the two census years.

**Age range.** Ages 5–17 match Kindergarten to Grade 12 at official school age. The [DepEd School Characteristics Technical Notes](https://www.deped.gov.ph/wp-content/uploads/School-Characteristics-Technical-Notes.pdf) (pp. 4–5) map Kindergarten to age 5, Grades 1–6 to ages 6–11, Grades 7–10 to ages 12–15, and Grades 11–12 to ages 16–17. PSA's broader 5–24 "school-age population" is not used. Population comes from the Total Population sheet (not Household Population), both sexes combined.

**Enrollment scope.** Unlike AP1 to AP3, AP4 counts learners in every sector, because the population side counts every resident child wherever they study. Philippine Schools Overseas are excluded because their learners are abroad and belong to no city or municipality. The public-school share is shown beside the gap. Using public-school enrollment alone would count private-school learners as part of the gap. For 2024 nationally:

| | Enrollment, SY 2024-25 | Gap from 27,569,038 residents aged 5–17 | Gap share |
|---|---:|---:|---:|
| All sectors except Philippine Schools Overseas | 26,375,327 | 1,193,711 | 4.3% |
| Public schools only | 22,543,711 | 5,025,327 | 18.2% |

About 3.83 million of the public-only gap is private and SUC/LUC learners.

**Reading the gap.**

- Population is counted where people live; enrollment is counted where the school is. The gap is not an out-of-school count or an enrollment rate and must never be labelled as either.
- A negative gap is kept, not set to zero. It usually means the city or municipality is a school hub that enrolls learners from neighboring areas. Learners outside ages 5–17 can also add to enrollment.
- The gap shows scale and the gap share allows comparison between cities and municipalities of different size; both are shown.

**Geography comparability, for the 2020-to-2024 change only.** Each single-year gap is internally consistent, because each school year's enrollment file records the school's location for that year. The change between the two points is flagged where boundaries or assignments moved in between:

- **Makati and Taguig:** 10 EMBO barangays moved from Makati to Taguig (Supreme Court, GR 235316);
- **Negros Island Region:** re-established under RA No. 12000, taking Negros Occidental, Negros Oriental, and Siquijor from Regions VI and VII;
- **Sulu:** reassigned from BARMM to Region IX by Executive Order No. 91, s. 2025, following the Supreme Court ruling of September 9, 2024;
- **Maguindanao:** split into Maguindanao del Norte and Maguindanao del Sur (RA No. 11550);
- **Special Geographic Area:** eight new municipalities that did not exist in 2020. Under D-049, schools enter city and municipality results when the reviewed EMISD code resolves to an SGA municipality; the 2020-to-2024 change remains flagged because those municipalities did not exist in 2020.

For Negros, Sulu, and Maguindanao the cities and municipalities themselves did not change; only their province or region did. The flag matters for name matching and for any province or region grouping.

**Which way is enrollment moving.** AP4 publishes one row per city or municipality and school year for every school year in `fact_school_enrollment` (SY 2020-21 to 2025-26 today). Each row has all-sector and public-school enrollment, annual change, and first-to-latest change. `public_enrollment_trend` is `increasing`, `decreasing`, or `no change` by the sign of the public-school change. It is NULL when the first endpoint is zero or unavailable, or when either endpoint has no complete public school or has any public school with an incomplete enrollment total. A school with a blank offered level is left out of the sums and counted in `schools_incomplete`, never read as 0. The census context (`census_year`, `school_age_population`, `population_enrollment_gap`, `gap_share`) is filled only on SY 2020-21 and 2024-25. The `UNKNOWN` and `EXCLUDED` members keep their rows so totals reconcile; dashboards filter `member_type = 'regular'`. The priority table reads the public-school endpoints, absolute and percentage growth, endpoint-completeness flag, and growth direction. Population gaps remain context.

**Validation status:** built in `ap4_enrollment_trend` (#208, the design of #199): enrollment by school year and its trend, with the 2020 and 2024 gap as census-year context. The gate rebuilds every row from the two Gold facts and compares all columns. D-061 uses only the first-to-latest public-school enrollment change for priority; the all-sector trend and population gap remain context. Source details are in the [dataset use map](dataset-use-map.md#school-age-population-source).

### Context · Poverty 2023

Poverty answers none of AP1 to AP4. It is shown beside the education measures so planners can see how poor an area is, and is never used in a ratio, rank, gap flag, queue, priority, or score ([D-046](../governance/decisions.md#d-046-psa-poverty-2023-as-context-in-the-area-comparison-view)). Its one other possible use is as an input to the context-only [Similar LGUs](#similar-lgus-context) list.

| Item | Contract |
|---|---|
| Definition | Share of persons whose per capita income is below the poverty threshold: PSA's 2023 small-area estimate, not computed by us |
| Unit | % of persons |
| Grain | City or municipality, one value per regular PSGC 2Q 2026 member (1,642) |
| Source | `dim_city_poverty` (`poverty_incidence`, `poverty_ci90_lower`, `poverty_ci90_upper`, `poverty_cv`, `cv_over_20`, `poverty_status`, `status_reason`), from `psa_poverty_stat` Silver (D-034) |
| Period | 2023, labelled "Poverty 2023" next to "SY 2023-24" (D-027); the sector, education level, and school-year filters do not change it |
| Aggregation | None: no region or province figure, no average of areas, and the 14 Manila district estimates are not combined into a City of Manila value |
| Uncertainty | The published 90% interval is always shown. "Less precise" when the CV is above 20 (150 of 1,597 estimated areas), a team label, not a PSA rule. A published lower limit below 0 (Ivana, Batanes) is stored as published and shown as 0.0% with a note |
| Missing | `estimated` 1,597; `no_estimate` 1 (Kalayaan); `not_in_source` 44 (D-028). A missing value is shown with its `status_reason`, never as 0, and is never imputed |
| Wording | Descriptive only: "Poverty incidence 2023: 30% (90% interval 25 to 35%)". No sentence may say or imply that poverty causes or explains a classroom or teacher gap |

**Validation status:** decided (D-046, provisional until the team mentor approves the ERD); built in #174. The counts are recounted in the [2023 recount evidence](../../evidence/reconciliation/2026-10-16-psa-poverty-2023-city-recount.md).

## BARMM and geography scope

AP1 to AP4 apply the same metric rules to BARMM as to every other region. A school enters a city or municipality result only through the reviewed school-to-PSGC Integration result. Special Geographic Area schools enter city or municipality results when their published DepEd code resolves to one of the eight SGA municipalities under D-049. A school that remains `unmatched`, `ambiguous`, or `excluded` stays in the retained technical member, does not inherit a similarly named Region XII municipality, and is reported in geography coverage.

The BPDA BARMM datasets remain separately labelled historical or broader-grain context. They do not replace DepEd enrollment, facilities, or personnel in AP1 to AP3 and are not combined with those measures. Sulu, Negros Island Region, Maguindanao, EMBO, and SGA hierarchy changes follow the AP4 comparability rules above. The AP outputs remain at city or municipality grain; a current region label must not be presented as proof of a like-for-like historical regional trend.

## Reproducibility and integrity rules

Every implementation of these contracts must satisfy all of the following:

1. Read only reviewed current Silver or Integration rows. Gold facts keep the business columns defined in the Gold data model rather than duplicating row-level Silver lineage columns. For every Gold build, its validation results must record the job `run_id` and `code_revision`, verify the distinct upstream Silver or Integration `run_id` values read, and preserve the query path from those upstream rows to `batch_id`, `source_sha256`, `delivery_version`, and `schema_version`.
2. Build each Gold fact at the grain and key in the [Gold data model](../architecture/data-model.md). Fail on duplicate keys, unresolved foreign keys, or row-count reconciliation errors. Use the explicit unknown or excluded member where the model requires one; never create a silent NULL geography key.
3. Derive every ratio from aggregated numerator and denominator sums over the same eligible school set. Never average school-level ratios or round inputs before division.
4. Preserve NULL, recorded zero, and positive values as distinct states. Use `NULLIF(denominator, 0)` or an equivalent explicit guard. A missing or zero denominator produces a NULL ratio plus its reason and affected school and learner counts.
5. Emit the numerator, denominator, ratio, school coverage, learner coverage, unmatched or excluded counts, source period, geography-match version, and metric-contract version together. The metric-contract version is the implementation `code_revision` governed by D-050; no separate version column is added to the Gold facts. A displayed ratio without these audit fields is incomplete.
6. Reconcile enrollment, classroom, teacher, population, and geography totals independently before joining them. The classroom and teacher joins must not increase the enrollment row count at their declared grains.
7. Keep calculations deterministic and safe to rerun. The same approved source versions and code revision must produce the same keyed rows and totals, and a rerun must replace or merge those rows without duplication.
8. Record outlier checks as quality results. Do not delete, cap, winsorize, or silently correct an observed value in Gold or Analytics.
9. Validate exactly one `fact_school_year_source_availability` row for every school year and approved DepEd `source_id`, reject duplicate or unknown source keys, and reconcile `has_data` to the reviewed Silver source periods. Do not infer fact-level coverage from this flag.

## Comparison and prioritization methods

The dashboard may show four distinct evidence types without treating them as interchangeable:

| Evidence | Permitted use |
|---|---|
| **LGU observed value** | Primary local measure, with coverage and quality status |
| **Validated official benchmark** | Benchmark comparison only when authority, formula, scope, education level, effective period, and denominator compatibility match the observed metric; see the [research register](national-benchmarks-and-indicators.md) |
| **National same-type distribution** | Descriptive context only; it does not set a queue, tier, or threshold |
| **Similar LGUs** | The most similar LGUs of the same type, shown as context (method set in #96); never sets or changes a priority |

### Similar LGUs (context)

Similar LGUs replaces the proposed peer groups. For each city or municipality, the LGU profile may list the most similar LGUs of the same type. The planned inputs are income class, population density (Population 2024 ÷ `hdx_boundaries.area_sqkm`; see the [dataset use map](dataset-use-map.md)), poverty incidence 2023 (D-046), and Population 2024. The method is not yet defined: how inputs are standardized, how income class is encoded, the distance measure, how many LGUs are listed, the rule for a missing input, and the tie-break are set and recorded in #96 before the view is built. The list describes the place; it never changes the D-061 priority category.

If distribution summaries are shown, they are descriptive only and must not be used as a need threshold or priority rule.

### Planning-priority rule

D-061 supersedes D-060. It combines two separate benchmarked current-pressure flags with the direction of public-school enrollment growth. It does not create a weighted score or add classroom-affected and teacher-affected learners.

1. **Classroom pressure.** AP2 passes its 90% learner-coverage gate and at least one usable school has `school_learners / school_reported_rooms >= 50`.
2. **Teacher pressure.** AP3 passes its level-coverage gate and at least one offered level exceeds its reference: ES 35, JHS 36, or SHS 80/3 learners per eligible teacher. Equality is within the reference.
3. **Enrollment growth.** Compare public-school enrollment in SY 2020-21 and SY 2025-26. `growth = latest - first`; `growth_pct = growth / first * 100`, with NULL when the first endpoint is missing or zero. Growth is TRUE only when the change is positive.
4. **Coverage.** A known pressure always counts, even when another measure is incomplete. If growth cannot be assessed, an LGU with a known pressure is placed as if it were not growing, and `growth_not_assessed_reason` says why. An LGU with no known pressure is `Data review` when AP2 or an AP3 level fails its coverage gate or growth cannot be assessed. Missing evidence is never zero or absence of pressure.
5. **Category.** Let `current_pressure_count = classroom_pressure_flag + teacher_pressure_flag`. Priority 1 is two pressures plus growth. Priority 2 is two pressures without growth, or one pressure plus growth. Priority 3 is one pressure without growth. Monitor is growth without current pressure. No current pressure identified is neither pressure nor growth.
6. **Ordering.** Sort by category, pressure count, affected learners, classroom-affected learners, pressured teacher levels, absolute growth, percentage growth, and PSGC code. Keep classroom and teacher affected learners separate. `priority_affected_learners` is their larger value, not their sum, because learners may overlap.
7. **Bounded interpretation.** The categories order planning review. They do not estimate shortages, construction, hiring, deployment entitlements, funding, or the intervention an LGU should choose.

AP1, the population-enrollment gap, poverty, Similar LGUs, and national distribution summaries remain context and never change the priority category.

Before acting, users validate passing schools against actual K–12 classroom counts, building condition, shifts and utilization, enrolment projections, accessibility, and planned or funded projects. Those data are not all present in the current project.

### Outlier sensitivity (D-065)

The published planning priority keeps every otherwise valid school. A sensitivity check shows whether it depends on extreme school figures.

1. **Fence.** For the classroom ratio within LGU type, and for the teacher ratio within LGU type and level, compute `Q1`, `Q3` and `IQR = Q3 − Q1` over the public schools in the ratio in SY 2023-24. The outer fences are `Q1 − 3 × IQR` and `Q3 + 3 × IQR`. A group of fewer than 10 schools has no fence.
2. **Flag.** A classroom ratio above the upper fence is a suspected extreme outlier. A teacher ratio above the upper or below the lower fence is one. The flag is a quality result: nothing is deleted, capped, or corrected.
3. **Scenario B.** Recalculate AP2 and AP3 without the flagged schools, removing each from both the numerator and the denominator of that ratio, keeping every enrolled learner in the coverage denominator, and apply the D-061 category and ordering again.
4. **Status.** Priority-sensitive (category changes), Classification-sensitive (a pressure flag changes), Coverage-sensitive (a coverage gate no longer passes), Magnitude-sensitive (priority affected learners change by more than 10%), Stable, or No suspected outliers, the first that applies.
5. **Use.** The published category stays the review status. An outlier-sensitive LGU needs its flagged schools verified before planning action.

## Candidate resource-gap calculations — blocked

The following equations are arithmetically coherent but **not validated for dashboard use**:

```text
candidate_required_classrooms = ceiling(aligned_enrollment / 45)
candidate_classroom_gap = max(candidate_required_classrooms - aligned_existing_classrooms, 0)

candidate_required_teachers = ceiling(aligned_enrollment / approved_student_teacher_norm)
candidate_teacher_gap = max(candidate_required_teachers - approved_existing_teacher_count, 0)
```

The 45 is the PSIP III classroom configuration: 45 individual learners' tables and chairs per new classroom ([PSIP III Project Information Memorandum](https://www.deped.gov.ph/wp-content/uploads/PSIP-III_Project-Information-Memorandum.pdf), p. 12; see the [benchmark register](national-benchmarks-and-indicators.md#psip-iii-classroom-configuration)). The result is a candidate planning estimate. It must not be called an official classroom shortage, construction requirement, or allocation order unless the team confirms that the classroom count is compatible with that use. The current NSBI instructional-room count includes laboratories and other rooms that are not classrooms, so it would understate the gap.

In every equation, the enrollment and the classroom or teacher counts must cover the same schools, education level, geography, and school year. The equations may be activated only if the cited norm is intended for this conversion and matches the observed denominator. Validation must also address education level, shifts, room utilization and condition, temporary spaces, multi-grade classes, annexes, teacher roles, funding source, and whether reallocation is feasible. Even after validation, the result is a planning estimate—not a construction order, staffing item, or budget request.

## Dashboard output contract

The dashboard should expose concise decision fields while keeping audit fields available in a drill-down or download.

| View | Main fields | Coverage and drill-down fields | Current status |
|---|---|---|---|
| **Common identity** | LGU PSGC code, LGU name, LGU type, province/region, education level, school year | source availability by school year, geography-match version, unmatched/excluded school counts, source versions | Required |
| **AP1 context** | public-school count (including annexes), public-school enrollment, learners per public school, school-age population 2024 (5–17), school-age population 2024 per public school, barangays without a public elementary school (count and share) | population reference year, annex count, zero-enrollment school count, school-count rule, schools without a barangay match, upper-bound label, barangay drill-down | Built in `ap1_school_provision` (#208); barangay measures not built |
| **Classroom priority** | learners per reported instructional room (all levels), matched enrollment, reported room count | school and learner coverage, missing-room schools, zero-room schools, outlier/quality flags; source displayed as DepEd School Facilities (NSBI) | Built in `ap2_classroom_pressure` for SY 2023-24 (#208) |
| **Teacher priority** | learners per teacher by level, matched enrollment, teacher count | school and learner coverage, included-position version, funding-source split, learners-without-same-level-teachers flag, annex status, outlier/quality flags | Built in `ap3_teacher_pressure` for SY 2023-24 (#208); project-defined |
| **AP4 growth and context** | public-school enrollment change and direction from SY 2020-21 to SY 2025-26; all-sector trend and the 2020 and 2024 population gap remain context | endpoint availability, absolute and percentage change, census metadata, negative-gap note, geography-comparability flag | Public growth feeds D-061; population gap remains context |
| **Poverty context** | poverty incidence 2023, 90% interval, "less precise" label | poverty status and reason, estimate year beside the school year | `dim_city_poverty` built (#174); the dashboard view is in #96 |
| **Comparisons** | applicable bounded reference and status, national same-type summary, Similar LGUs | citation/version, comparison-group count, spread, Similar LGUs inputs | References built; Similar LGUs method planned in #96 |
| **Planning priority** | priority category and order, separate classroom and teacher pressure flags, growth flag | D-061 rule version, AP2/AP3 coverage, public-enrollment endpoints, affected schools, learners, and levels | Built in `lgu_priority_matrix`; no weighted score or shortage estimate |

## Separate follow-on decisions

The AP1 to AP4 fact and metric contracts above do not depend on the following work. These items must not be guessed inside #46:

1. The AP4 name-match implementation from the PSA census workbooks to PSGC. The matching issue must preserve the approved ages, periods, enrollment scope, comparability flag, and no-modelling rule.
2. Similar LGUs criteria, distance method, missing-input fallback, and display are planned in #96; they remain context only.
3. Any teacher-allocation amount, classroom-shortage count, or weighted classroom-teacher score remains out of scope until compatible requirements data and a separately approved rule exist.
4. Activation of the candidate classroom planning calculation or any teacher resource-gap calculation. These require compatible denominators and separate approval.

Already set: poverty 2023 is context only, never a ranking, flag, queue, or score input (D-046). The complete display, uncertainty, missingness, and recount contract is in [Context · Poverty 2023](#context--poverty-2023).

## Validation gate

A metric becomes dashboard-ready only when all of the following are present in a reviewed pull request:

- approved business definition and exact source columns;
- executable calculation at the declared grain;
- reconciliation to source totals and matched-school coverage;
- tests for NULL, zero, duplicate, outlier, and zero-denominator behavior;
- comparison with any publisher-defined indicator it claims to reproduce;
- approved labels, thresholds, sorting, and missing-data display; and
- traceable source, period, geography-match, and metric-version fields.
