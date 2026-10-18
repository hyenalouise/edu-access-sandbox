# Metric and dashboard specification

**Status:** Draft analytical contract. No metric in this document is an official DepEd indicator or adequacy standard unless its row explicitly says so. Team approval, source validation, and implemented tests are still required before publication.

## Purpose and document boundary

This document translates the approved [business and analytical questions](business-analytics-problem.md) into candidate measures and dashboard fields. It owns formulas, grains, filters, comparison rules, display fields, and validation status. It does not redefine the approved questions, assign datasets to scope, describe stakeholder authority, or establish external standards; those belong to the business-question document, [dataset use map](dataset-use-map.md), [stakeholder document](stakeholders.md), and [national benchmark register](national-benchmarks-and-indicators.md).

## Current validation conclusion

The proposed ratio structures are reasonable analytical candidates, but they are **not yet fully validated production metrics**.

| Area | What is supported now | What prevents final approval |
|---|---|---|
| **AP1 · Schools** | Public-school and enrollment counts can be aggregated by matched LGU and school year; 97.9% of SY 2023-24 schools (58,876 of 60,134) reach a PSGC barangay by name; the active-school, zero-enrollment, and annex rules are set | How a multi-level school counts in level-specific school counts is still open; the barangay roll-up needs a rule for the 1,258 schools without a unique barangay match |
| **AP2 · Classrooms** | SY 2023-24 enrollment and facilities match one-to-one by `school_id`; classroom counts are typed; levels are combined into one total-room ratio, and all-blank room counts are missing, not zero | The facilities field uses the NSBI “instructional classroom” definition, which includes rooms beyond Kindergarten-to-Grade-12 classrooms. It is not DepEd's published classroom–learner ratio, and its extreme observations are still under review |
| **AP3 · Teachers** | SY 2023-24 enrollment and personnel match one-to-one by `school_id`; personnel counts are typed; the ratio is by level and the teacher positions are set | The source cannot show whether one person is counted in two columns, blanks are ambiguous, outliers remain under review, and without a mother-school ID the ratio is project-defined, not DepEd's indicator |
| **AP4 · Population and enrollment** | Ages 5–17, the two matched periods (2020 and 2024), and all-sector enrollment are defined; PSA single-year-age workbooks for every city and municipality were found for 2020 and 2024; SY 2024-25 enrollment is acquired | The PSA workbooks are profiled (`psa_school_age_population`) but not yet ingested, and carry names only, with no PSGC codes; SY 2020-21 enrollment is not yet acquired |
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

## Candidate analytical metrics

These formulas define what must be validated; they do not by themselves authorize publication.

### AP1 · School-provision context

```text
learners_per_public_school = public_school_enrollment / public_school_count
public_schools_per_10k_residents = public_school_count / total_population * 10,000

barangays_without_public_es =
    PSGC barangays in the LGU with no matched public school offering elementary
barangays_without_public_es_pct =
    barangays_without_public_es / PSGC barangays in the LGU * 100
```

Use `COUNT(DISTINCT school_id)` and sum enrollment at the same LGU, education-level, and school-year grain. Total population must retain its own reference year. This measure describes provision and school size; it does not measure travel access or prove that construction is required.

**Which schools count.** `public_school_count` counts active public schools, including annexes (D-047):

- **Active school:** total enrollment above 0 in that school year. A school with zero or blank total enrollment stays in the record and is shown as a count, but it is not counted and does not serve a barangay. There are 4 such public schools in SY 2023-24, 1 in SY 2024-25, and 3 in SY 2025-26 (the SY 2025-26 schools have every enrollment field blank).
- **Annexes:** annex and extension schools count as schools. The label is **public schools (including annexes)**, with the annex count shown beside it. DepEd publishes no mother-school ID (#134), and 52 annexes are the only public elementary school in their barangay, so dropping them would mark served barangays as unserved. The Technical Notes rule that adds annexes to their mother school (p. 8) applies only to the teacher–learner ratio.

The barangay measures follow DepEd Order No. 40, s. 2014, which expects at least one Kindergarten-to-Grade-6 school for every barangay (see the [national benchmark register](national-benchmarks-and-indicators.md#ap1--school-provision-references)). They are calculated per city or municipality and school year from the full PSGC 2Q 2026 barangay list and are never ranked by barangay. A school that does not reach a unique barangay can make a served barangay look unserved, so each LGU also shows its count of public schools without a barangay match, and a result with any such school is labelled an upper bound. A barangay without its own school may still be served by a nearby school, so the count is a screen for review, not evidence that a school is needed.

**Validation status:** candidate. The active-school, zero-enrollment, and annex rules are set. Before implementation, approve how a multi-level school counts in level-specific school counts and how schools without a unique barangay match are handled.

### AP2 · Classroom pressure

```text
total_instructional_rooms =
    sum of es_, jhs_, and shs_classrooms_instructional that are not blank
    (missing when all three are blank)

learners_per_reported_instructional_room =
    sum(total_learners) / sum(total_instructional_rooms)
    over public schools with total_instructional_rooms > 0

school_coverage_pct =
    public_schools_with_usable_room_count / public_schools_in_scope * 100

learner_coverage_pct =
    enrollment_in_schools_with_usable_room_count / public_school_enrollment * 100
```

The ratio uses each school's total learners and total instructional rooms across all levels, per school year, and then sums to the city or municipality (D-047). This follows the form of the Technical Notes classroom–learner formula (p. 8), total learners over total classrooms; the room definition still differs, as explained below. A school is usable when its total rooms are above 0. When all three room counts are blank the total is missing, not zero (608 public schools in SY 2023-24), and is reported separately. A school with a total of 0 is not silently dropped: it gets a separate zero-denominator flag and count.

Levels are combined because rooms are shared across levels: 768 public schools have JHS learners and ES rooms but no JHS rooms. Learner coverage is 99.3% with totals, compared with 98.8% when learners and rooms are matched level by level.

The dashboard label must say **learners per reported instructional room**, with the source shown separately as **DepEd School Facilities (NSBI)**. It must not be labelled “DepEd classroom–learner ratio.” NSBI is the source system behind the DepEd School Facilities data; it is not a different facilities dataset. DepEd's source documentation says `*_classrooms_instructional` includes ALS, audio-visual, computer, industrial-arts, home-economics, and laboratory rooms, while its published classroom–learner indicator uses Kindergarten-to-Grade-12 classrooms. The available data therefore tend to produce a lower ratio than the official indicator.

**Validation status:** candidate for a project-defined descriptive measure, limited to SY 2023-24. Levels are combined (D-047). Review the extreme upper tail before publication.

### AP3 · Teacher pressure

```text
for each level (ES, JHS, SHS):

learners_per_teacher =
    sum(public_school_enrollment at the level) / sum(teacher_count at the level)
    over public schools with teacher_count at the level > 0,
    plus the learners of annexes that report 0 teachers

school_coverage_pct =
    public_schools_with_usable_teacher_count / public_schools_in_scope * 100

learner_coverage_pct =
    enrollment_in_schools_with_usable_teacher_count / public_school_enrollment * 100
```

The ratio is calculated by level because the Technical Notes define the teacher–learner ratio “at a specific level.” `teacher_count` at a level is the sum of these personnel columns at that level (D-047):

- Teacher I–III, Master Teacher I–IV, and Head Teacher I–VI;
- SPED/SNED teachers, Special Science teachers, and Instructors;
- locally funded teachers paid from SEF province, SEF city/municipality, LGU, or other funding. Kindergarten locally funded teachers go under ES.

Principals and all non-teaching staff are excluded. This gives 935,421 public-school teachers in SY 2023-24. The four locally funded columns are shown per level as a funding split.

A school with learners at a level but teachers only at another level is flagged: 255 schools at JHS and 109 at SHS in SY 2023-24. Its learners at that level have no usable denominator there and appear in the coverage gap.

Known limit: the source cannot show whether one person is counted in two columns.

The source measures personnel actually working in public schools; they are not authorized plantilla positions, vacancies, or approved new items.

DepEd's documented teacher–learner method adds annex enrollment and teachers to the mother school before division. DepEd publishes no mother-school ID (#134), so AP3 cannot do this school by school. The ratio is labelled **project-defined** and must not claim to reproduce DepEd's indicator (D-047). An annex that reports 0 teachers keeps its learners in the city or municipality total instead of being dropped by the usable-denominator rule: 48 annexes with 21,114 learners in SY 2023-24. Because the ratio is summed to the city or municipality, this matches DepEd's add-to-mother rule whenever the annex and its mother school are in the same city or municipality.

**Validation status:** candidate for a project-defined ratio by level, limited to SY 2023-24. Teacher positions, levels, and annex handling are set (D-047). It is not DepEd's teacher–learner ratio. Resolve the reviewed personnel outliers and ambiguous blanks before publication.

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

**Validation status:** method defined; calculation blocked pending ingestion and profiling of the PSA 2020 and 2024 single-year-age workbooks, a name match of their cities and municipalities to PSGC, and acquisition of SY 2020-21 enrollment. Source details are in the [dataset use map](dataset-use-map.md#school-age-population-source).

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
| **AP1 context** | public-school count (including annexes), public-school enrollment, learners per public school, total population, schools per 10,000 residents, barangays without a public elementary school (count and share) | population reference year, annex count, zero-enrollment school count, school-count rule, schools without a barangay match, upper-bound label, barangay drill-down | Candidate |
| **Classroom priority** | learners per reported instructional room (all levels), matched enrollment, reported room count | school and learner coverage, missing-room schools, zero-room schools, outlier/quality flags; source displayed as DepEd School Facilities (NSBI) | Candidate for SY 2023-24 |
| **Teacher priority** | learners per teacher by level, matched enrollment, teacher count | school and learner coverage, included-position version, funding-source split, learners-without-same-level-teachers flag, annex status, outlier/quality flags | Candidate (project-defined) for SY 2023-24 |
| **AP4 context** | population aged 5–17, enrollment in all sectors, gap, gap share, change from 2020 to 2024, public-school share | census and school year for each point, population source, "not available" label for unmatched school years, negative-gap note, geography-comparability flag, name-match coverage | Blocked pending ingestion and profiling |
| **Poverty context** | poverty incidence 2023, 90% interval, "less precise" label | poverty status and reason, estimate year beside the school year | Decided (D-046); not built |
| **Comparisons** | applicable benchmark and status, peer percentile, peer median, national same-type median | benchmark citation/version, peer ID/count/fallback, IQR, national distribution, comparison status | Blocked until method approval |
| **Priority label** | relative-pressure band or benchmark status, affected enrollment | sort rule/version, missingness and quality warnings | Blocked until ranking rule approval |

## Decisions required before implementation

1. AP1 level-specific counting for multi-level schools, and the handling of schools without a unique barangay match in the barangay roll-up. The active-school, zero-enrollment, and annex rules are set (D-047).
2. **Set (D-047):** ES, JHS, and SHS room counts are combined into one total per school.
3. **Set (D-047):** AP3 teacher positions, levels, and funding columns. Possible double counting of one person is a documented limit the source cannot resolve.
4. **Set (D-047):** no annex-to-mother-school link exists, so AP3 is labelled project-defined, and annexes that report 0 teachers keep their learners in the city or municipality total.
5. **Set (D-045):** only the DepEd Order No. 40, s. 2014 school-presence screen is active, for AP1. RA No. 7880's 45:1 rule and the 2009 teacher bands stay in documentation, and the PSIP III 45-seat configuration is a design reference for the candidate classroom planning calculation only.
6. AP4 name-match rule from the PSA census workbooks to PSGC, and how the dashboard shows cities and municipalities flagged for the 2020-to-2024 change. The age range, matched periods, enrollment scope, and the no-modelling rule are set in the AP4 section above.
7. Peer criteria, density bands, minimum group size, fallback, and percentile convention. The land-area source is HDX.
8. Relative-priority sorting or banding rule; a combined score remains out of scope unless separately approved.
9. BARMM coverage and geography treatment.
10. **Set (D-046):** poverty 2023 is context only, never a ranking, flag, peer criterion, or score input; see Context · Poverty 2023.

## Validation gate

A metric becomes dashboard-ready only when all of the following are present in a reviewed pull request:

- approved business definition and exact source columns;
- executable calculation at the declared grain;
- reconciliation to source totals and matched-school coverage;
- tests for NULL, zero, duplicate, outlier, and zero-denominator behavior;
- comparison with any publisher-defined indicator it claims to reproduce;
- approved labels, thresholds, sorting, and missing-data display; and
- traceable source, period, geography-match, and metric-version fields.
