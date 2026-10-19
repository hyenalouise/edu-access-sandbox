# National benchmarks and supporting indicators

**Status:** Research register, verified against official sources on 2026-10-14. An entry in this document is not automatically approved for dashboard use. The metric must still match the source definition, education level, geographic grain, and period.

> **Superseded in part by [D-057](../governance/decisions.md#d-057-lgu-priority-rule-version-1)** (2026-10-19): peer groups no longer set any comparison. The within-type percentile sets the priority tier, and Similar LGUs (method in #96) is context only. Peer descriptors such as income class and density are planned inputs to Similar LGUs. The peer-group text below is kept until its full update in #178 and #96.

## Purpose and document boundary

This document records the official formulas, numeric references, policy criteria, national targets, and supporting datasets relevant to the approved [business and analytical questions](business-analytics-problem.md). It answers two different questions:

1. **How should an indicator be computed?**
2. **What number, if any, can be used as an official comparison?**

Those questions are not interchangeable. An official formula may have no official adequacy threshold, and a number used for budgeting, facility design, or an older deployment program may not be a current national standard. The [metric specification](metric-specification.md) remains the implementation contract; this register supplies the evidence it must cite.

## Evidence labels

| Label | Meaning | Dashboard use |
|---|---|---|
| **Official computation** | A government technical note defines the numerator, denominator, and interpretation | May define a metric after project-data compatibility is tested |
| **Statutory threshold** | A law supplies a numeric rule for a stated legal purpose | Use only for that purpose and with a compatible denominator |
| **Policy screening criterion** | An issuance supplies conditions for evaluating a possible action | May support a flag or drill-down; it is not an automatic recommendation |
| **Design reference** | A program document states how new facilities are configured | May set a parameter in a candidate planning calculation; not an adequacy threshold or shortage determination |
| **National planning target** | A national plan supplies a desired future result | Context only unless the local metric reproduces the same indicator |
| **National performance context** | An official report supplies an observed national result | Validation or context, not a local adequacy threshold |
| **Legacy guidance** | An older issuance supplies a rule whose current applicability has not been confirmed | Do not activate as a current benchmark without written confirmation |
| **Project-defined measure** | The team defines a useful calculation not published as an official indicator | Label clearly and compare only with descriptive peer or national distributions |

## Findings at a glance

| Research area | Best-supported reference | What the project can say now |
|---|---|---|
| **AP1 · School provision** | DepEd Order No. 40, s. 2014 gives school-establishment screening criteria | School presence can be screened against the published criteria, but learners per school and Population 2024 per public school have no validated national cutoff in the reviewed sources |
| **AP2 · Classrooms** | DepEd defines the classroom–learner formula; Republic Act No. 7880 defines classroom shortage using 45 learners per classroom | The 45:1 rule cannot be applied to the current NSBI field because that field includes rooms the law excludes; the PSIP III memorandum configures each new classroom for 45 learners, a design reference for candidate planning only |
| **AP3 · Teachers** | DepEd defines the teacher–learner formula and annex consolidation | No current, general national teacher threshold was found; 2009 secondary-school deployment bands are legacy evidence only |
| **AP4 · Enrollment need** | DepEd defines GER and NER by official school age; BEDP 2030 sets national NER targets | NER is a validated participation indicator, but the current project data cannot reproduce it at LGU level; the AP4 gap (population aged 5–17 minus enrollment in all sectors) is a project-defined difference, not NER or an out-of-school count |
| **Peer context** | PSA and DOF provide official LGU type, income class, population, land area, density, and poverty data | These variables can describe comparable contexts, but the resulting peer group and its median are project-defined—not national standards |

## AP1 · School-provision references

### Published school-establishment criteria

[DepEd Order No. 40, s. 2014](https://www.deped.gov.ph/wp-content/uploads/2014/08/DO_s2014_040.pdf), printed pp. 14–15, gives the following criteria for establishing a public school:

- Kindergarten to Grade 6: the feasibility study must establish urgent need, with at least one school for every barangay;
- Grades 7 to 10: at least one school for every municipality or city;
- the proposed school should have at least 100 prospective pupils or students in one or more grade levels, subject to justification by the Schools Division Superintendent when the minimum is not met; and
- the proposed school should not be within two kilometres of an existing public school in a rural area or one kilometre in an urban area, subject to stated exceptions involving capacity, geographic inaccessibility, or educational interest.

**Permitted use:** count, for each city or municipality, the barangays without a public school offering elementary, and show the barangays behind that count as drill-down for feasibility review. Barangays are not ranked or treated as a separate analytical unit.

**Not permitted:** conclude from school count alone that a new school must be built. A defensible recommendation also needs the relevant grade offering, prospective learners or resident demand, distance or accessibility, existing-school capacity, and the other feasibility requirements in the order.

### Project-defined AP1 measures

`learners per public school` and `Population 2024 per public school` remain useful descriptive measures, but no official national cutoff for either was found in the reviewed DepEd, PSA, or statutory sources. They must therefore be labelled **project-defined** and interpreted through the city/municipality distribution or an approved peer distribution.

## AP2 · Classroom references

### Official computation

The DepEd [School Characteristics Technical Notes](https://www.deped.gov.ph/wp-content/uploads/School-Characteristics-Technical-Notes.pdf), pp. 8 and 11, define:

```text
classroom_learner_ratio = total_enrollment / total_number_of_instructional_rooms
```

For this indicator, an instructional room means a Kindergarten-to-Grade-12 classroom only. The technical notes provide the formula and interpretation, but do not state an ideal numeric ratio.

### Statutory 45:1 classroom-shortage reference

[Republic Act No. 7880](https://lawphil.net/statutes/repacts/ra1995/ra_7880_1995.html), sections 3(b) and 4, defines classroom shortage as the number of classrooms whose construction would result in a **45:1 student–classroom ratio**. For this legal definition, classrooms are rooms used exclusively for instruction; offices, libraries, laboratories, workshops, and similar rooms are excluded. The law applies its capital-outlay allocation mechanism at **legislative-district** level.

The corresponding planning arithmetic is:

```text
required_eligible_classrooms = ceiling(aligned_enrollment / 45)
classroom_shortage_estimate = max(required_eligible_classrooms - existing_eligible_classrooms, 0)
```

The equations above make the law's definition operational; they are not a substitute for its full allocation rules.

### Compatibility decision for this project

The project's `*_classrooms_instructional` fields include ALS rooms, audio-visual rooms, computer rooms, industrial-arts rooms, home-economics rooms, and laboratories. Republic Act No. 7880 excludes laboratories, workshops, and similar rooms, while DepEd's published classroom–learner indicator is limited to K–12 classrooms.

Therefore:

- if the candidate metric is approved after data validation, the dashboard may publish the clearly labelled **learners per reported instructional room** descriptive measure, with its source shown as **DepEd School Facilities (NSBI)**;
- it must not call that result the official DepEd classroom–learner ratio; and
- it must not apply the 45:1 shortage threshold until a compatible count of K–12 classrooms excluding the legally excluded spaces is available.

### PSIP III classroom configuration

DepEd's [PPP for School Infrastructure Project Phase III (PSIP III) Project Information Memorandum](https://www.deped.gov.ph/wp-content/uploads/PSIP-III_Project-Information-Memorandum.pdf) (2026), p. 12, says each new PSIP III classroom will be equipped with **45 individual learners' tables and chairs**, which it calls the finalized standard classroom configuration for PSIP III. It is the most recent DepEd statement of how many learners a newly built classroom is set up for.

This is a **design reference**, not a general adequacy threshold:

- it describes classrooms built under PSIP III, a public–private partnership building 16,435 classrooms in 1,092 existing Luzon schools (p. 4);
- the same memorandum expects average class size to fall from 50 to 39 learners (p. 4), so 45 is seats per room, not a target class size; and
- it is separate from Republic Act No. 7880's 45:1 statutory shortage definition above.

It may set the 45 in the candidate classroom planning calculation in the [metric specification](metric-specification.md#candidate-resource-gap-calculations--blocked), which stays a candidate planning estimate (D-045). It must not be applied to every existing NSBI instructional room as an official shortage, for the same room-definition reason as above.

### National performance context

DepEd's [FY 2024 Q4 Budget Accountability Report](https://www.deped.gov.ph/wp-content/uploads/FY-2024-Q4-BAR-1_As-of-Dec-31-2024_Signed.pdf) reported that, for SY 2023–24, 22,981 of 47,555 Grades 1–10 public schools, or **48%**, met DepEd's classroom-ratio standard; 3,813 of 7,687 senior high schools, or **50%**, met it. These are national performance results, not the threshold definition itself, and should be used only as a reconciliation target if the project later reproduces DepEd's exact metric.

## AP3 · Teacher references

### Official computation

The DepEd School Characteristics Technical Notes, pp. 8 and 10–11, define:

```text
teacher_learner_ratio = total_enrollment / total_number_of_teachers
```

Enrollment and teachers for school annexes must be added to their mother school before the ratio is calculated. This aggregation rule is part of the official method, not an optional data-cleaning step.

The technical notes do not provide a general ideal ratio. They also explain that the public machine-ready personnel data represent personnel actually working in schools, not authorized plantilla positions or vacancies in DBM's PSIPOP/GMIS.

### Legacy secondary-school deployment bands

[DepEd Order No. 88, s. 2009](https://www.deped.gov.ph/2009/08/20/do-88-s-2009-revised-color-coding-scheme-for-the-deployment-of-teachers-in-public-secondary-schools/) published the following public-secondary-school deployment bands:

| Learners per teacher | 2009 interpretation |
|---:|---|
| Below 15.00 | Blue · excess teachers |
| 15.00–19.99 | Sky blue · excess teachers |
| 20.00–24.99 | Green · excess teachers |
| 25.00–29.99 | Yellow · teacher needs |
| 30.00–34.99 | Gold · teacher needs |
| 35.00–39.99 | Orange · teacher needs |
| 40.00 and above | Red · teacher needs |
| No teacher item | Black |

The order prioritized black, red, orange, gold, then yellow for new items or redeployment of vacant positions. Because the issuance is from 2009, applies specifically to public secondary schools, and predates the current data and staffing context, this project records it as **legacy guidance**. It must not be presented as a current nationwide adequacy standard unless DepEd confirms that it still governs the intended analysis.

DepEd's FY 2024 program report estimated learner beneficiaries at **45 learners per newly hired teacher**. That is a beneficiary-estimation assumption, not enough evidence for a general teacher-adequacy benchmark.

### Compatibility decision for this project

AP3 remains blocked as a DepEd-aligned metric until the team approves the included teacher positions, resolves possible person duplication and outliers, and consolidates annexes with mother schools. A current threshold should be requested from DepEd's Planning Service or Bureau of Human Resource and Organizational Development rather than inferred from the 2009 bands.

## AP4 · Enrollment and school-age-population references

### Official GER and NER computations

The DepEd School Characteristics Technical Notes, pp. 4–7 and 9, define:

```text
gross_enrollment_rate =
    total_enrollment_in_level_regardless_of_age
    / corresponding_official_school_age_population * 100

net_enrollment_rate =
    enrollment_in_level_within_the_official_age_group
    / corresponding_official_age_group_population * 100
```

DepEd states that LIS enrollment and PSA census-based projected population are used for these access indicators. The official-age mappings in the technical notes are:

| Level | Official age |
|---|---:|
| Kindergarten | 5 |
| Grades 1–6 | 6–11 |
| Kindergarten to Grade 6 | 5–11 |
| Junior high school, Grades 7–10 | 12–15 |
| Senior high school, Grades 11–12 | 16–17 |
| Secondary, Grades 7–12 | 12–17 |
| Kindergarten to Grade 12 | 5–17 |

The ideal maximum NER is **100%**, but DepEd explicitly warns that the difference below 100% must not be treated as the proportion of children who are not enrolled. Age-specific enrollment ratio is the preferred complementary indicator.

### BEDP 2030 national targets

The [Basic Education Development Plan 2030](https://www.deped.gov.ph/wp-content/uploads/2022/05/DO_s2022_024.pdf), Table 16, records SY 2019–20 baselines and 2030 national targets:

| Indicator | SY 2019–20 national baseline | 2030 national target |
|---|---:|---:|
| Elementary NER | 93.87% | 99% |
| Secondary NER | 83.27% | 98% |

The NEDA Board approved BEDP 2030 as the national policy and plan for basic education in April 2024. These values are national planning targets, not evidence that an LGU with a lower public-school-enrollment ratio has an equivalent number of out-of-school children.

### Population data for AP4

PSA defines “school-age population” in its general census release as ages **5–24**. The [2024 Census release](https://psa.gov.ph/content/age-and-sex-distribution-philippine-population-2024-census-population) reports 42.10 million people aged 5–24, or 37.5% of household population. This age band is broader than the project's K–12 scope of ages 5–17 and the release's national figure cannot be copied to an LGU.

PSA also publishes **Total Population by Single-Year Age, Sex, Region, Province, and City/Municipality** for the 2020 Census of Population and Housing and the 2024 Census of Population. These isolate ages 5–17 for every city and municipality, and AP4 uses them for its two matched periods. They are profiled (`psa_school_age_population`) but not yet ingested; see the [dataset use map](dataset-use-map.md#school-age-population-source).

The AP4 value, population aged 5–17 minus enrollment in all sectors except Philippine Schools Overseas, therefore remains a **project-defined arithmetic difference**, not GER, NER, enrollment demand, or an out-of-school count. It compares residence-based population with school-location enrollment and may mix age and grade populations.

## Supporting data for comparisons and equity context

| Need | Recommended official source | Appropriate use | Important limitation |
|---|---|---|---|
| Stable city/municipality identity and type | [PSA Philippine Standard Geographic Code](https://psa.gov.ph/classification/psgc) | Master PSGC code, LGU type, city class, hierarchy, and 2024 population | Version geography must be reconciled with the school year |
| Current LGU income class | [DOF-BLGF LGU Income Class](https://blgf.gov.ph/lgu-income-class/) and DOF Department Order No. 074-2024 | Peer descriptor using the current five-class reclassification under RA No. 11964 | Income class is a fiscal descriptor, not an education-need threshold |
| Land area and density | `hdx_boundaries.area_sqkm` (current source); [PSA OpenSTAT table 1A6DLPD0](https://openstat.psa.gov.ph/PXWeb/pxweb/en/DB/DB__1A__PO_2024/0221A6DLPD0.px/) (possible later cross-check) | City/municipality land area for population density and density bands | HDX does not document how area is computed; peer-band boundaries and minimum group size remain project decisions |
| Poverty and equity context | [PSA 2023 city- and municipality-level poverty estimates](https://psa.gov.ph/statistics/poverty-sae/stat-tables) | Display poverty incidence, confidence interval, and coefficient of variation beside capacity results | Small-area estimates are model-based; HUCs, Isabela, and Cotabato use a separate direct-estimate source; poverty must not silently alter the priority score |
| Total population for AP1 | PSA PSGC 2024 Census population | Numerator for Population 2024 per public school | Total population is not school-age population |
| K–12-age population for AP4 | PSA Total Population by single-year age and city/municipality, 2020 CPH and 2024 POPCEN | Ages 5–17, both sexes, for the two matched AP4 periods | Profiled and loaded in Bronze (`psa_school_age_population`), but not yet published in Silver; names only, no PSGC codes |
| Enrollment | DepEd LIS/BOSY machine-ready files | Numerator for AP1–AP3, AP4 enrollment in all sectors except Philippine Schools Overseas, and trend input | Current project files are school-location counts; SY 2020-21 and SY 2024-25 are published in Silver for AP4 |
| K–12 classrooms | DepEd NSBI with a K–12-only room definition | Official classroom–learner ratio and possible RA No. 7880 comparison | Current project field is broader than the required denominator |
| Teachers working in schools | DepEd BEIS personnel data | Teacher–learner ratio after role approval and annex consolidation | Does not show authorized positions or vacancies |
| Authorized teacher positions and vacancies | DBM PSIPOP/GMIS or a validated DepEd/DBM extract | Distinguish reallocation, vacancy filling, and creation of positions | Not present in the current public project data |

Poverty, income class, and density help explain context and support fair peer comparison. They are not themselves proof of classroom or teacher shortage and should not be combined into an opaque need score without a separate approved decision rule.

## What may enter the dashboard

| Candidate dashboard element | Decision |
|---|---|
| Official TLR and CLR formula text | **Reference-ready**, subject to compatible project columns |
| Learners per reported instructional room | **Descriptive candidate only**, with the source shown as DepEd School Facilities (NSBI) and with coverage flags |
| RA No. 7880 45:1 classroom flag or gap | **Blocked** until a compatible eligible-classroom count and intended geographic use are approved |
| DepEd Order No. 40 school-presence screen | **Conditional**, as an AP1 count per city or municipality with barangay drill-down, carrying level, match-coverage, distance, demand, and feasibility caveats |
| 2009 teacher deployment bands | **Legacy reference only**, not an active benchmark |
| NER and BEDP targets | **Reference-ready**, but local calculation is blocked until compatible age-specific enrollment and population data exist |
| Peer median, IQR, percentile, and national same-type median | **Descriptive method**, never labelled an official baseline |
| Poverty incidence | **Context only**, carrying estimate year, interval, CV, and missingness |

## Benchmark metadata required in the benchmark config

Each approved benchmark is stored as a reviewed config entry that the Analytics comparison step reads ([D-045](../governance/decisions.md#d-045-question-v1-uses-only-compatible-official-benchmarks)). Every activated benchmark or target should retain:

- benchmark ID and version;
- evidence label from this document;
- issuing authority, document title, URL, section or page, and issuance/effective date;
- education level, school sector, geographic scope, and intended policy purpose;
- exact numerator, denominator, exclusions, aggregation, and threshold or target;
- compatible project metric and source-column version;
- validation status, reviewer, review date, and applicability end date; and
- dashboard label and caveat text.

This permits more than one reference to coexist without treating a statutory capital-outlay rule, a national plan target, and a peer median as equivalent.

## Research conclusions and next actions

1. **Adopt the DepEd formulas, not unsupported labels.** AP2 and AP3 can follow the official ratio structure only after their denominators and annex treatment match the technical notes.
2. **Request a compatible classroom count.** The current NSBI field cannot support the 45:1 statutory shortage calculation.
3. **Ask DepEd to confirm the current teacher deployment norm.** Do not promote the 2009 secondary bands or the FY 2024 45-learner beneficiary assumption into a current standard.
4. **Profile and ingest the PSA 2020 and 2024 single-year-age workbooks, and acquire SY 2020-21 enrollment.** Keep AP4 unavailable until both are done; version 1 uses no modelled values.
5. **Use HDX `area_sqkm` as the current land-area source.** PSA OpenSTAT table 1A6DLPD0 is an official alternative that can be acquired and profiled later as a cross-check or replacement.
6. **Keep equity variables visible but separate.** Poverty, income class, and density should explain context; they should not change an education-capacity result unless the team approves a transparent prioritization rule.

## Official source register

| Source | Evidence used |
|---|---|
| [DepEd School Characteristics Technical Notes](https://www.deped.gov.ph/wp-content/uploads/School-Characteristics-Technical-Notes.pdf), effective 2024-09-10 | GER, NER, teacher–learner ratio, classroom–learner ratio, age mappings, annex treatment, source systems, and interpretation cautions |
| [Republic Act No. 7880](https://lawphil.net/statutes/repacts/ra1995/ra_7880_1995.html), 1995 | 45:1 classroom-shortage definition, eligible-room exclusions, and legislative-district capital-outlay mechanism |
| [DepEd PSIP III Project Information Memorandum](https://www.deped.gov.ph/wp-content/uploads/PSIP-III_Project-Information-Memorandum.pdf), 2026 | 45 individual learners' tables and chairs per new PSIP III classroom (p. 12); project scope and expected class sizes (p. 4) |
| [DepEd Order No. 40, s. 2014](https://www.deped.gov.ph/wp-content/uploads/2014/08/DO_s2014_040.pdf) | School-establishment need, coverage, prospective-enrollment, and distance criteria |
| [DepEd Order No. 88, s. 2009](https://www.deped.gov.ph/2009/08/20/do-88-s-2009-revised-color-coding-scheme-for-the-deployment-of-teachers-in-public-secondary-schools/) | Legacy public-secondary teacher deployment bands |
| [Basic Education Development Plan 2030](https://www.deped.gov.ph/wp-content/uploads/2022/05/DO_s2022_024.pdf), Table 16 | National NER baselines and 2030 targets |
| [NEDA Board approval of BEDP 2030](https://www.deped.gov.ph/2024/04/27/depeds-matatag-agenda-bedp-2030-approved-by-neda-board-as-national-policy-and-plan-for-basic-education/) | Status of BEDP 2030 as national policy and plan |
| [DepEd FY 2024 Q4 Budget Accountability Report](https://www.deped.gov.ph/wp-content/uploads/FY-2024-Q4-BAR-1_As-of-Dec-31-2024_Signed.pdf) | National percentage and count of schools reported as meeting the classroom standard |
| [DepEd FY 2024 major-program beneficiaries report](https://www.deped.gov.ph/wp-content/uploads/Major-Projects-Program-and-Activities-Beneficiaries-FY-2024.pdf) | 45 learners per newly hired teacher used as a beneficiary estimate, not an adequacy standard |
| [PSA 2020 age and sex release](https://psa.gov.ph/content/age-and-sex-distribution-philippine-population-2020-census-population-and-housing) | 2020 age and sex context |
| [PSA 2024 age and sex release](https://psa.gov.ph/content/age-and-sex-distribution-philippine-population-2024-census-population) | National 5–24 school-age definition and 2024 national count |
| [PSA PSGC](https://psa.gov.ph/classification/psgc) | Official geography, LGU type, population, and published income-class field |
| [PSA OpenSTAT population, land area, and density table](https://openstat.psa.gov.ph/PXWeb/pxweb/en/DB/DB__1A__PO_2024/0221A6DLPD0.px/) | Official city/municipality land area and population density; possible later cross-check for HDX land area |
| [DOF-BLGF LGU Income Class](https://blgf.gov.ph/lgu-income-class/) | Current income reclassification source |
| [PSA city- and municipality-level poverty tables](https://psa.gov.ph/statistics/poverty-sae/stat-tables) | 2023 small-area poverty estimates and uncertainty fields |
