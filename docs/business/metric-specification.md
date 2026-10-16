# Metric and dashboard specification

**Status:** Implementation contract for Gold facts and Analytics calculations. The formulas, grains, scopes, source fields, and missing-data rules below are ready to implement under #46. A metric is not dashboard-ready until it also passes the validation gate in this document. No metric is an official DepEd indicator or adequacy standard unless its row explicitly says so.

## Purpose and document boundary

This document translates the approved [business and analytical questions](business-analytics-problem.md) into candidate measures and dashboard fields. It owns formulas, grains, filters, comparison rules, display fields, and validation status. It does not redefine the approved questions, assign datasets to scope, describe stakeholder authority, or establish external standards; those belong to the business-question document, [dataset use map](dataset-use-map.md), [stakeholder document](stakeholders.md), and [national benchmark register](national-benchmarks-and-indicators.md).

## Current validation conclusion

The metric contracts are complete enough to build and test the Gold facts. Publication readiness remains separate: a complete formula can still be unavailable for a period, limited by source coverage, or blocked from an official benchmark comparison.

| Area | What is supported now | What prevents final approval |
|---|---|---|
| **AP1 · Schools** | Public-school and enrollment counts can be aggregated by LGU and school year; multi-level, active-school, annex, and unmatched-barangay rules are set | Publication must show geography-match coverage and preserve the screen's distance, demand, and feasibility caveats |
| **AP2 · Classrooms** | SY 2023-24 enrollment and facilities match one-to-one by `school_id`; classroom counts are typed; levels are combined into one total-room ratio, and all-blank room counts are missing, not zero | The facilities field uses the NSBI “instructional classroom” definition, which includes rooms beyond Kindergarten-to-Grade-12 classrooms. It is not DepEd's published classroom–learner ratio, and its extreme observations are still under review |
| **AP3 · Teachers** | SY 2023-24 enrollment and personnel match one-to-one by `school_id`; personnel counts are typed; the ratio is by level and the teacher positions and null rules are set | The source cannot show whether one person is counted in two columns, outliers remain under review, and without a mother-school ID the ratio is project-defined, not DepEd's indicator |
| **AP4 · Population and enrollment** | Ages 5–17, the two matched periods (2020 and 2024), and all-sector enrollment are defined; PSA single-year-age workbooks for every city and municipality were found for 2020 and 2024; SY 2024-25 enrollment is acquired | The PSA workbooks are profiled (`psa_school_age_population`) but not yet ingested, and carry names only, with no PSGC codes; SY 2020-21 enrollment is not yet acquired |
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
| Enrollment by level | `deped_enrollment_clean.school_id`, `school_year`, `sector`, `annex_status`, `offers_es`, `offers_jhs`, `offers_shs`, `is_overseas`; ES counts `kinder_{male,female}`, `g1_{male,female}` through `g6_{male,female}`, `esng_{male,female}`; JHS counts `g7_{male,female}` through `g10_{male,female}`, `jhsng_{male,female}`; SHS counts every `g11_*_{male,female}` and `g12_*_{male,female}` field present in the approved schema version | School x school year x education level. AP1 to AP3 require `sector = 'Public'` and `is_overseas = false`. AP4 accepts `Public`, `Private`, and `SUC/LUC` and excludes `PSO` or `is_overseas = true`. Geography and `psgc_match_status` come from the reviewed Integration result. |
| Classroom capacity | `deped_facilities_clean.school_id`, `school_year`, `es_classrooms_instructional`, `jhs_classrooms_instructional`, `shs_classrooms_instructional` | School x school year. Require public scope. Sum the three room fields that are not NULL; return NULL when all three are NULL. Do not substitute makeshift rooms, temporary learning spaces, or non-instructional rooms into this denominator. |
| Teacher capacity | The level-specific personnel fields listed immediately below | School x school year x education level. Require public scope. Principals, assistant principals, administrative, health, guidance, library, security, utility, and all other non-teaching roles are excluded. |
| AP1 total population | `fact_city_population.city_mun_psgc_code`, `reference_year`, `population`, `estimate_status` | City or municipality x reference year. Use only `estimate_status = 'available'`; label the reference year and do not substitute school-age population. |
| AP4 school-age population | `fact_city_school_age_population.city_mun_psgc_code`, `reference_year`, `age`, `sex`, `population`, `psgc_match_status`, `is_2020_2024_geography_comparable` | City or municipality x reference year. Sum `sex IN ('male', 'female')` and `age BETWEEN 5 AND 17`; use only reviewed PSGC matches. Never add a published both-sexes total to the male and female rows. |

### AP3 included personnel fields

`teacher_count` is the sum of the following fields for the row's education level:

- **ES:** `es_teacher_i` through `es_teacher_iii`; `es_master_teacher_i` through `es_master_teacher_iv`; `es_head_teacher_i` through `es_head_teacher_vi`; `es_sped_sned_teacher_i` through `es_sped_sned_teacher_v`; and the eight locally funded fields `kinder_teachers_{sef_province,sef_municipality_city,lgu_funding,other_funding}` and `es_teachers_{sef_province,sef_municipality_city,lgu_funding,other_funding}`.
- **JHS:** `jhs_teacher_i` through `jhs_teacher_iii`; `jhs_master_teacher_i` through `jhs_master_teacher_iv`; `jhs_head_teacher_i` through `jhs_head_teacher_vi`; `jhs_sped_teacher_i` through `jhs_sped_teacher_v`; `jhs_special_science_teacher_i`; `jhs_instructor_i` through `jhs_instructor_iii`; and `jhs_teachers_{sef_province,sef_municipality_city,lgu_funding,other_funding}`.
- **SHS:** `shs_teacher_i` through `shs_teacher_iii`; `shs_master_teacher_i` through `shs_master_teacher_iv`; `shs_head_teacher_i` through `shs_head_teacher_vi`; `shs_special_science_teacher_i`; and `shs_teachers_{sef_province,sef_municipality_city,lgu_funding,other_funding}`.

The four funding subtotals use only the corresponding `*_teachers_*` fields above. They are already included in `teacher_count` and must never be added to it again. For ES, each funding subtotal combines its Kindergarten and ES fields.

For classroom and teacher totals, sum non-NULL included fields and return NULL only when every included field is NULL. A recorded zero remains zero. The Gold validation must report rows with a mixture of NULL and non-NULL included fields so partial reporting is visible. A ratio denominator is usable only when the resulting total is greater than zero.

## Analytical metric contracts

These formulas are the implementation baseline. They do not by themselves authorize dashboard publication.

### AP1 · School-provision context

```text
learners_per_public_school = public_school_enrollment / public_school_count
public_schools_per_10k_residents = public_school_count / total_population * 10,000

barangays_without_public_es =
    PSGC barangays in the LGU with no matched public school offering elementary
barangays_without_public_es_pct =
    barangays_without_public_es / PSGC barangays in the LGU * 100
```

Use `COUNT(DISTINCT school_id)` and sum enrollment at the same LGU, education-level, and school-year grain. For the all-level result, count an active multi-level school once. For a level-specific result, count it once in every level where `is_offered = true`; do not infer an offering from a positive learner count or from another source. The overall active-school rule still applies, so a school with total enrollment of zero or NULL is not counted at any level. Total population must retain its own reference year. This measure describes provision and school size; it does not measure travel access or prove that construction is required.

**Which schools count.** `public_school_count` counts active public schools, including annexes (D-047):

- **Active school:** total enrollment above 0 in that school year. A school with zero or blank total enrollment stays in the record and is shown as a count, but it is not counted and does not serve a barangay. There are 4 such public schools in SY 2023-24, 1 in SY 2024-25, and 3 in SY 2025-26 (the SY 2025-26 schools have every enrollment field blank).
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

For AP3, `enrollment_included_in_ratio` includes learners at denominator-usable schools and the explicit zero-teacher annex exception. Report the zero-teacher annex school and learner counts beside coverage so the exception remains auditable.

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
- **Special Geographic Area:** eight new municipalities that did not exist in 2020, already excluded from city and municipality joins under D-031.

For Negros, Sulu, and Maguindanao the cities and municipalities themselves did not change; only their province or region did. The flag matters for name matching and for any province or region grouping.

**Validation status:** method defined; calculation blocked pending ingestion of the profiled PSA 2020 and 2024 single-year-age workbooks, a reviewed name match of their cities and municipalities to PSGC, and acquisition of SY 2020-21 enrollment. Source details are in the [dataset use map](dataset-use-map.md#school-age-population-source).

### Poverty incidence 2023 · context only

Poverty is not AP1 to AP4 and never enters a ratio, rank, peer group, pressure flag, or priority calculation. Display the published 2023 city or municipality estimate from `dim_city_poverty` beside the education measures under its own **Poverty 2023** label.

| Item | Contract |
|---|---|
| Grain | One city or municipality |
| Value | `poverty_incidence`, the published share of persons below the poverty threshold |
| Uncertainty | Always show `poverty_ci90_lower` and `poverty_ci90_upper`; show **Less precise** when `cv_over_20 = true` |
| Availability | `estimated` shows the value and interval; `no_estimate` shows the publisher's reason; `not_in_source` shows that the area is outside this source |
| Filters | Not affected by school year, sector, or education-level filters |
| Aggregation | None. Do not average LGUs, create a province or region value, or combine Manila's sub-municipalities |

A published negative confidence-interval bound is retained in the fact lineage and may be displayed as 0.0% only with a note that the published bound was below zero. Missing is never zero or blank, and nothing is imputed. Dashboard wording may describe the poverty estimate but must not say or imply that poverty caused or explains a classroom or teacher result.

## BARMM and geography scope

AP1 to AP4 apply the same metric rules to BARMM as to every other region. A school enters a city or municipality result only through the reviewed school-to-PSGC Integration result. Special Geographic Area schools enter city or municipality results when their published DepEd code resolves to one of the eight SGA municipalities under D-049. A school that remains `unmatched`, `ambiguous`, or `excluded` stays in the retained technical member, does not inherit a similarly named Region XII municipality, and is reported in geography coverage.

The BPDA BARMM datasets remain separately labelled historical or broader-grain context. They do not replace DepEd enrollment, facilities, or personnel in AP1 to AP3 and are not combined with those measures. Sulu, Negros Island Region, Maguindanao, EMBO, and SGA hierarchy changes follow the AP4 comparability rules above. The AP outputs remain at city or municipality grain; a current region label must not be presented as proof of a like-for-like historical regional trend.

## Reproducibility and integrity rules

Every implementation of these contracts must satisfy all of the following:

1. Read only reviewed current Silver or Integration rows and retain their `batch_id`, `source_sha256`, `delivery_version`, `schema_version`, pipeline `run_id`, and code revision through an auditable lineage path.
2. Build each Gold fact at the grain and key in the [Gold data model](../architecture/data-model.md). Fail on duplicate keys, unresolved foreign keys, or row-count reconciliation errors. Use the explicit unknown or excluded member where the model requires one; never create a silent NULL geography key.
3. Derive every ratio from aggregated numerator and denominator sums over the same eligible school set. Never average school-level ratios or round inputs before division.
4. Preserve NULL, recorded zero, and positive values as distinct states. Use `NULLIF(denominator, 0)` or an equivalent explicit guard. A missing or zero denominator produces a NULL ratio plus its reason and affected school and learner counts.
5. Emit the numerator, denominator, ratio, school coverage, learner coverage, unmatched or excluded counts, source period, geography-match version, and metric-definition version together. A displayed ratio without these audit fields is incomplete.
6. Reconcile enrollment, classroom, teacher, population, and geography totals independently before joining them. The classroom and teacher joins must not increase the enrollment row count at their declared grains.
7. Keep calculations deterministic and safe to rerun. The same approved source versions and code revision must produce the same keyed rows and totals, and a rerun must replace or merge those rows without duplication.
8. Record outlier checks as quality results. Do not delete, cap, winsorize, or silently correct an observed value in Gold or Analytics.

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
| **Common identity** | LGU PSGC code, LGU name, LGU type, province/region, education level, school year | geography-match version, unmatched/excluded school counts, source versions | Required |
| **AP1 context** | public-school count (including annexes), public-school enrollment, learners per public school, total population, schools per 10,000 residents, barangays without a public elementary school (count and share) | population reference year, annex count, zero-enrollment school count, school-count rule, schools without a barangay match, upper-bound label, barangay drill-down | Ready to implement and validate |
| **Classroom priority** | learners per reported instructional room (all levels), matched enrollment, reported room count | school and learner coverage, missing-room schools, zero-room schools, outlier/quality flags; source displayed as DepEd School Facilities (NSBI) | Ready to implement and validate for SY 2023-24 |
| **Teacher priority** | learners per teacher by level, matched enrollment, teacher count | school and learner coverage, included-position version, funding-source split, learners-without-same-level-teachers flag, annex status, outlier/quality flags | Ready to implement and validate for SY 2023-24; project-defined |
| **AP4 context** | population aged 5–17, enrollment in all sectors, gap, gap share, change from 2020 to 2024, public-school share | census and school year for each point, population source, "not available" label for unmatched school years, negative-gap note, geography-comparability flag, name-match coverage | Blocked pending ingestion and profiling |
| **Comparisons** | applicable benchmark and status, peer percentile, peer median, national same-type median | benchmark citation/version, peer ID/count/fallback, IQR, national distribution, comparison status | Blocked until method approval |
| **Priority label** | relative-pressure band or benchmark status, affected enrollment | sort rule/version, missingness and quality warnings | Blocked until ranking rule approval |

## Separate follow-on decisions

The AP1 to AP4 fact and metric contracts above do not depend on the following work. These items must not be guessed inside #46:

1. The AP4 name-match implementation from the PSA census workbooks to PSGC. The matching issue must preserve the approved ages, periods, enrollment scope, comparability flag, and no-modelling rule.
2. Peer criteria, density bands, minimum group size, fallback, and percentile convention. HDX is the current land-area source.
3. Relative-priority sorting or banding. A combined classroom-teacher score remains out of scope unless a later decision approves its weights and interpretation.
4. Activation of the candidate classroom planning calculation or any teacher resource-gap calculation. These require compatible denominators and separate approval.

## Validation gate

A metric becomes dashboard-ready only when all of the following are present in a reviewed pull request:

- approved business definition and exact source columns;
- executable calculation at the declared grain;
- reconciliation to source totals and matched-school coverage;
- tests for NULL, zero, duplicate, outlier, and zero-denominator behavior;
- comparison with any publisher-defined indicator it claims to reproduce;
- approved labels, thresholds, sorting, and missing-data display; and
- traceable source, period, geography-match, and metric-version fields.
