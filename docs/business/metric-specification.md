# Metric and dashboard specification

**Status:** Implementation contract for Gold facts and Analytics calculations. The formulas, grains, scopes, source fields, and missing-data rules below are ready to implement under #46. A metric is not dashboard-ready until it also passes the validation gate in this document. No metric is an official DepEd indicator or adequacy standard unless its row explicitly says so.

## Purpose and document boundary

This document translates the approved [business and analytical questions](business-analytics-problem.md) into implementation-ready measures and dashboard fields. It owns formulas, grains, filters, comparison rules, display fields, and validation status. It does not redefine the approved questions, assign datasets to scope, describe stakeholder authority, or establish external standards; those belong to the business-question document, [dataset use map](dataset-use-map.md), [stakeholder document](stakeholders.md), and [national benchmark register](national-benchmarks-and-indicators.md).

## Current validation conclusion

The metric contracts are complete enough to build and test the Gold facts. Publication readiness remains separate: a complete formula can still be unavailable for a period, limited by source coverage, or blocked from an official benchmark comparison.

| Area | What is supported now | What prevents final approval |
|---|---|---|
| **AP1 · Schools** | Public-school and enrollment counts can be aggregated by LGU and school year; multi-level, active-school, annex, and unmatched-barangay rules are set | Publication must show geography-match coverage and preserve the screen's distance, demand, and feasibility caveats |
| **AP2 · Classrooms** | SY 2023-24 enrollment and facilities match one-to-one by `school_id`; classroom counts are typed; levels are combined into one total-room ratio, and all-blank room counts are missing, not zero | The facilities field uses the NSBI “instructional classroom” definition, which includes rooms beyond Kindergarten-to-Grade-12 classrooms. It is not DepEd's published classroom–learner ratio, and its extreme observations are still under review |
| **AP3 · Teachers** | SY 2023-24 enrollment and personnel match one-to-one by `school_id`; personnel counts are typed; the ratio is by level and the teacher positions and null rules are set | The source cannot show whether one person is counted in two columns, outliers remain under review, and without a mother-school ID the ratio is project-defined, not DepEd's indicator |
| **AP4 · Population and enrollment** | Ages 5–17, the two matched periods (2020 and 2024), and all-sector enrollment are defined; PSA single-year-age workbooks for every city and municipality were found, profiled, and loaded in Bronze for 2020 and 2024; SY 2020-21 and SY 2024-25 enrollment are acquired, validated in Bronze, and published in Silver | The PSA population workbooks are not yet published in Silver and carry names only, with no PSGC codes; the population-to-PSGC Integration match is not yet built |
| **Poverty 2023 · Context** | PSA's 2023 estimate, 90% interval, and CV for 1,597 of the 1,642 cities and municipalities; the status of the other 45 is defined (D-046) | `dim_city_poverty` is not built yet (#174), and the model stays provisional until the team mentor approves the ERD; it is context only and never an analytical result |
| **Resource-gap estimates** | RA No. 7880 supplies a 45:1 statutory classroom-shortage reference; the arithmetic form can be documented as a candidate | The current NSBI room field includes spaces excluded by the law, no current general teacher threshold has been validated, and the operational assumptions behind converting a ratio into rooms or teachers have not been approved |

The DepEd evidence for these limitations is recorded in the source cards for [enrollment](../data/source-inventory/deped_enrollment/README.md#limitations-for-analysis), [facilities](../data/source-inventory/deped_facilities/README.md#limitations-for-analysis), and [personnel](../data/source-inventory/deped_personnel/README.md#limitations-for-analysis), with observed tests in their linked profiles.

## Contract conventions

Every published measure must declare:

1. **grain** — LGU, school year, and education level where supported;
2. **scope** — public schools only for AP1 to AP3; all sectors for AP4; Philippine Schools Overseas excluded from every LGU result;
3. **numerator and denominator** — exact approved fields and filters, covering the same schools, education level, school scope, geography, and period;
4. **aggregation** — calculate ratios from aggregated sums, not the unweighted average of school ratios;
5. **missingness** — NULL remains missing and is never converted to zero without publisher evidence;
6. **coverage** — both school and enrolled-learner coverage accompany AP2 and AP3;
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
| AP1 total population | `fact_city_population.city_mun_psgc_code`, `reference_year`, `population`, `estimate_status` | City or municipality x reference year. Use only `reference_year = 2024` and `estimate_status = 'available'`; label the value **Population 2024** and do not substitute school-age population. |
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
population_per_public_school = population_2024 / public_school_count

barangays_without_public_es =
    PSGC barangays in the LGU with no matched public school offering elementary
barangays_without_public_es_pct =
    barangays_without_public_es / PSGC barangays in the LGU * 100
```

Use `COUNT(DISTINCT school_id)` and sum enrollment at the same LGU, education-level, and school-year grain. For the all-level school count, count an active multi-level school once. For a level-specific school count, count it once in every level where `is_offered = true`; do not infer an offering from a positive learner count or from another source. A school is active when at least one offered level has a complete `learner_count` above 0, even when another offered level is incomplete. For `learners_per_public_school`, use only active public schools whose all-level total is complete in both the numerator and denominator. Also publish the total active-public-school count, the number excluded from this ratio because their all-level total is incomplete, and the non-NULL learner-cell audit sum. `population_per_public_school` divides the LGU's 2024 total population by the full active-public-school count. It is labelled **Population 2024 per public school**, not schools per 10,000 residents. A NULL or zero school count produces a NULL ratio with its reason. These measures describe provision and school size; they do not measure travel access or prove that construction is required.

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

**Validation status:** ready to implement and validate. The active-school, multi-level, zero-enrollment, annex, and unmatched-barangay rules are set. Dashboard publication still requires the validation gate and the stated caveats.

### AP2 · Classroom pressure

```text
total_instructional_rooms =
    sum of es_, jhs_, and shs_classrooms_instructional that are not blank
    (missing when all three are blank)

learners_per_reported_instructional_room =
    sum(total_learners for denominator-usable schools)
    / sum(total_instructional_rooms for the same schools)

school_coverage_pct =
    active_public_schools_with_usable_room_count / active_public_schools_in_scope * 100

learner_coverage_pct =
    enrollment_in_schools_with_usable_room_count / public_school_enrollment * 100
```

The ratio uses each active public school's total learners and total instructional rooms across all levels, per school year, and then sums to the city or municipality (D-047). Its numerator and denominator use the same set of schools. This follows the form of the Technical Notes classroom–learner formula (p. 8), total learners over total classrooms; the room definition still differs, as explained below. A school is denominator-usable when its total rooms are above 0. When all three room counts are blank the total is missing, not zero (608 public schools in SY 2023-24), and its school and learner counts are reported separately. A reported total of 0 is also excluded from both ratio sums and gets a separate zero-denominator school and learner count. If an LGU has no denominator-usable school, its ratio is NULL, never 0.

Levels are combined because rooms are shared across levels: 768 public schools have JHS learners and ES rooms but no JHS rooms. Learner coverage is 99.3% with totals, compared with 98.8% when learners and rooms are matched level by level.

The dashboard label must say **learners per reported instructional room**, with the source shown separately as **DepEd School Facilities (NSBI)**. It must not be labelled “DepEd classroom–learner ratio.” NSBI is the source system behind the DepEd School Facilities data; it is not a different facilities dataset. DepEd's source documentation says `*_classrooms_instructional` includes ALS, audio-visual, computer, industrial-arts, home-economics, and laboratory rooms, while its published classroom–learner indicator uses Kindergarten-to-Grade-12 classrooms. The available data therefore tend to produce a lower ratio than the official indicator.

**Validation status:** ready to implement and validate as a project-defined descriptive measure, limited to SY 2023-24. Levels are combined (D-047). Review the extreme upper tail before dashboard publication.

### AP3 · Teacher pressure

```text
for each level (ES, JHS, SHS):

learners_per_teacher =
    sum(level enrollment for denominator-usable schools
        plus level enrollment for annexes that report 0 teachers)
    / sum(teacher_count for denominator-usable schools)

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

The source measures personnel actually working in public schools; they are not authorized plantilla positions, vacancies, or approved new items.

DepEd's documented teacher–learner method adds annex enrollment and teachers to the mother school before division. DepEd publishes no mother-school ID (#134), so AP3 cannot do this school by school. The ratio is labelled **project-defined** and must not claim to reproduce DepEd's indicator (D-047). An annex that reports 0 teachers keeps its learners in the city or municipality total instead of being dropped by the usable-denominator rule: 48 annexes with 21,114 learners in SY 2023-24. Because the ratio is summed to the city or municipality, this matches DepEd's add-to-mother rule whenever the annex and its mother school are in the same city or municipality.

**Validation status:** ready to implement and validate as a project-defined ratio by level, limited to SY 2023-24. Teacher positions, levels, null rules, and annex handling are set (D-047). It is not DepEd's teacher–learner ratio. Resolve the reviewed personnel outliers before dashboard publication.

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

**Validation status:** method defined; calculation blocked pending Silver publication of the Bronze PSA 2020 and 2024 single-year-age workbooks and a reviewed match of their cities and municipalities to PSGC. SY 2020-21 and SY 2024-25 enrollment are already validated in Silver. Source details are in the [dataset use map](dataset-use-map.md#school-age-population-source).

### Context · Poverty 2023

Poverty answers none of AP1 to AP4. It is shown beside the education measures so planners can see how poor an area is, and is never used in a ratio, rank, gap flag, peer group, priority, or score ([D-046](../governance/decisions.md#d-046-psa-poverty-2023-as-context-in-the-area-comparison-view)).

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
| **Peer distribution** | Relative context using an approved peer definition; not proof of shortage |
| **National same-type distribution** | Descriptive context for cities and municipalities separately; not an official standard |

### Proposed peer method

The current proposal groups LGUs by type, income class, and a type-specific population-density band. Density uses land area from `hdx_boundaries.area_sqkm` (see the [dataset use map](dataset-use-map.md)). If a group does not meet the approved minimum size, density is dropped; if the broader group is still too small, only national same-type context is shown. The minimum group size, density bands, and fallback labels remain team decisions.

For an approved peer group, show the median, interquartile range, percentile, and group count. Median is not the only statistic: the IQR shows spread, the percentile locates the LGU, and the national same-type distribution reveals whether pressure is widespread beyond one peer group.

### Priority output

Maintain separate classroom and teacher views. Until an official benchmark and the underlying metric are validated, sort only as **relative capacity pressure** using the observed ratio, affected enrollment, comparison position, coverage, and quality flags. Do not label the result a shortage, deficit, or number of resources needed. Do not create a combined classroom-teacher score without approved weights and interpretation.

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
| **AP1 context** | public-school count (including annexes), public-school enrollment, learners per public school, Population 2024, Population 2024 per public school, barangays without a public elementary school (count and share) | population reference year, annex count, zero-enrollment school count, school-count rule, schools without a barangay match, upper-bound label, barangay drill-down | Ready to implement and validate |
| **Classroom priority** | learners per reported instructional room (all levels), matched enrollment, reported room count | school and learner coverage, missing-room schools, zero-room schools, outlier/quality flags; source displayed as DepEd School Facilities (NSBI) | Ready to implement and validate for SY 2023-24 |
| **Teacher priority** | learners per teacher by level, matched enrollment, teacher count | school and learner coverage, included-position version, funding-source split, learners-without-same-level-teachers flag, annex status, outlier/quality flags | Ready to implement and validate for SY 2023-24; project-defined |
| **AP4 context** | population aged 5–17, enrollment in all sectors, gap, gap share, change from 2020 to 2024, public-school share | census and school year for each point, population source, "not available" label for unmatched school years, negative-gap note, geography-comparability flag, name-match coverage | Blocked pending population Silver publication and PSGC integration |
| **Poverty context** | poverty incidence 2023, 90% interval, "less precise" label | poverty status and reason, estimate year beside the school year | Decided (D-046); not built |
| **Comparisons** | applicable benchmark and status, peer percentile, peer median, national same-type median | benchmark citation/version, peer ID/count/fallback, IQR, national distribution, comparison status | Blocked until method approval |
| **Priority label** | relative-pressure band or benchmark status, affected enrollment | sort rule/version, missingness and quality warnings | Blocked until ranking rule approval |

## Separate follow-on decisions

The AP1 to AP4 fact and metric contracts above do not depend on the following work. These items must not be guessed inside #46:

1. The AP4 name-match implementation from the PSA census workbooks to PSGC. The matching issue must preserve the approved ages, periods, enrollment scope, comparability flag, and no-modelling rule.
2. Peer criteria, density bands, minimum group size, fallback, and percentile convention. HDX is the current land-area source.
3. Relative-priority sorting or banding. A combined classroom-teacher score remains out of scope unless a later decision approves its weights and interpretation.
4. Activation of the candidate classroom planning calculation or any teacher resource-gap calculation. These require compatible denominators and separate approval.

Already set: poverty 2023 is context only, never a ranking, flag, peer criterion, or score input (D-046). The complete display, uncertainty, missingness, and recount contract is in [Context · Poverty 2023](#context--poverty-2023).

## Validation gate

A metric becomes dashboard-ready only when all of the following are present in a reviewed pull request:

- approved business definition and exact source columns;
- executable calculation at the declared grain;
- reconciliation to source totals and matched-school coverage;
- tests for NULL, zero, duplicate, outlier, and zero-denominator behavior;
- comparison with any publisher-defined indicator it claims to reproduce;
- approved labels, thresholds, sorting, and missing-data display; and
- traceable source, period, geography-match, and metric-version fields.
