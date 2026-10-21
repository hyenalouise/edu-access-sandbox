# bpda_barmm_education: BARMM education performance indicators

**Status:** profiled

## Identity

| Field | Value |
|---|---|
| Source name | BARMM Education |
| Publisher / agency | Bangsamoro Planning and Development Authority (BPDA), Bangsamoro Knowledge Portal |
| Source system (as stated by the publisher) | Bangsamoro Ecological Profile, Population and Social Services open data |
| Source URL or acquisition method | Public XLSX download linked under **BARMM Education** on the [Bangsamoro Knowledge Portal](https://knowledge.bpda.bangsamoro.gov.ph/open-data/bangsamoro-ecological-profile/population-and-social-services); [direct export](https://docs.google.com/spreadsheets/d/1ZzQZssZMawaKfx5n8KTw6TvZ9A7b-bpyoa9V2kz6GCE/export?format=xlsx) |
| Licensing or access restrictions | Public download. No license or reuse terms were found on the landing page or in the workbook; reuse terms remain **UNVERIFIED** |
| Owner (team member) | @hyenalouise |
| Date acquired | 2026-10-04 (Philippine time) |

## Files

Raw files are kept outside git. Row count excludes the header row.

| File | Format | Encoding | Size (bytes) | Row count | SHA-256 | Raw storage location |
|---|---|---|---|---|---|---|
| `BARMM_Education.xlsx` | XLSX, one worksheet | n/a | 7,194 | 10 | `5f08cb21ab1abaa2e13277eea429293782c3984447f7217bacce08c1eb44eeca` | Databricks volume `/Volumes/edu_access/00-source/raw/bpda/` |

## Publisher documentation

| Document | URL | SHA-256 | Sections relied on |
|---|---|---|---|
| Bangsamoro Knowledge Portal: BARMM Population and Social Services (HTML snapshot `BPDA_Population_and_Social_Services_page_2026-10-04.html`, 228,264 bytes, saved 2026-10-04 Philippine time; stored in `/Volumes/edu_access/00-source/raw/bpda/`) | https://knowledge.bpda.bangsamoro.gov.ph/open-data/bangsamoro-ecological-profile/population-and-social-services | `d0b2f6d9936df9931debf1ef1fc34743a81a7af4ec0c072fb8e6d05f1ab30882` | Publisher, dataset title, placement in the Bangsamoro Ecological Profile, download link (the snapshot contains the same Google Sheet ID as the direct export). No license or reuse terms appear on the page |
| Workbook header | Inside the inventoried file | File checksum above | Exact indicator names, education levels, and school years |

No methodology, formulas, definitions, data-source note, or release note accompanies the workbook.

## Coverage

| Field | Value |
|---|---|
| Geographic coverage | Ten historical BARMM reporting areas: Basilan, Lamitan City, Lanao del Sur I and II, Maguindanao I and II, Marawi City, Sulu, Tawi-Tawi, and Cotabato City |
| Geographic level | Mixed province-like and school-division reporting areas; not a current province table |
| Time coverage | Net enrolment rate: SY 2018-2019 to 2020-2021. Completion and cohort-survival rates: SY 2019-2020 to 2020-2021 |
| Time basis | School year |
| Update frequency | **UNVERIFIED** |
| Population covered | Elementary and secondary education, with kindergarten, JHS, and SHS detail for net enrolment. Public/private and learner-population scope are **UNVERIFIED** |

## Structure

| Field | Value |
|---|---|
| Apparent grain | One wide row per published province / school-division label, with 20 indicator-period columns |
| Candidate primary key | Raw `Province / School Division`; 10 rows and 0 duplicates |
| Candidate join keys | Historical reporting-area label plus school year. A governed school-division bridge is required; do not join these labels directly to current PSGC names |
| PSGC available? Which version? | No codes. The labels reflect historical divisions and geography, include Sulu under BARMM, and predate the Maguindanao province split. PSGC 2Q 2026, the team's master reference ([D-012](../../../governance/decisions.md#d-012-which-psgc-version-to-use)), lists Sulu under Region IX and Maguindanao as del Norte and del Sur ([psa_psgc README](../psa_psgc/README.md#version-used-and-sy-2023-24)) |
| Personally identifiable or sensitive fields | None. Public aggregate rates only. Classification: **Public** |
| Provenance fields in the source | Worksheet name, row number, exact header, reporting-area label, and school year embedded in each header. No source agency, publication date, revision, or extraction timestamp appears inside the workbook |

Column-by-column descriptions, fill rates, and ranges: [data_dictionary.md](data_dictionary.md).

### Expected vs actual schema

| Column or structure | Expected type | Actual type | Notes |
|---|---|---|---|
| `Province / School Division` | Reporting-area identifier | Text | Unique, but mixes provinces, cities, and numbered school divisions |
| 20 rate columns | Percentage | Numeric decimal fractions | 192 of 200 cells filled; range 3.62% to 107.86% |
| Missing values | Null or documented marker | Physically blank cells | All eight blanks are Cotabato City completion and cohort-survival fields |
| Geographic code | PSGC or school-division code | Absent | Manual, versioned crosswalk required |

## Lineage and dependencies

Unstated originating agency/system -> BPDA Bangsamoro Ecological Profile Google Sheet -> public XLSX export -> checksum-verified raw storage -> header and rate validation -> long-form normalization with reporting-area and school-year lineage -> historical school-division bridge -> contextual access and progression indicators.

## Known quality problems

Summary only; evidence lives in [profile.md](profile.md).

- **Observed:** the workbook contains no definitions, formulas, numerators, denominators, source note, release date, or region totals.
- **Observed:** 8 of 200 rate cells are blank. They are all Cotabato City completion and cohort-survival values for SY 2019-2020 and 2020-2021.
- **Observed:** Lamitan City has elementary net enrolment rates above 100% in all three years: 107.02%, 107.86%, and 101.52%. These values are retained, not clipped.
- **Observed:** Marawi City cohort-survival rates for SY 2019-2020 are exactly 100% for both elementary and secondary. No other rate cell equals 100%. These values are retained and flagged as possible caps or placeholders.
- **Observed:** the only geographic identifier is a mixed reporting-area label. No PSGC or school-division code is supplied.
- **Observed:** the historical labels are incompatible with a direct current-PSGC join: Maguindanao is represented as Divisions I and II, while Sulu is part of the delivered BARMM table. In PSGC 2Q 2026, Sulu is under Region IX and Maguindanao is split into del Norte and del Sur ([psa_psgc README](../psa_psgc/README.md#version-used-and-sy-2023-24), [psa_psgc profile O-3](../psa_psgc/profile.md)).
- **Observed:** one header omits a space in `SY2020-2021`; this is a schema-label inconsistency, not a different time period.

## Limitations for analysis

- The source is suitable for historical, descriptive comparison of published rates across BARMM school divisions. It is not a current operational dataset.
- Rates cannot be re-aggregated to a BARMM total or weighted by population because no numerators or denominators are supplied.
- The file cannot support school-level analysis, distance analysis, class-size analysis, teacher workload, or causal claims about learning outcomes.
- The source contains access and progression indicators, not National Achievement Test or other learner-assessment scores.
- Cross-year comparison spans the COVID-19 period and must not be interpreted as a normal trend without contextual evidence.

## Recommended controls and monitoring

- Fail ingestion if the checksum, one-sheet structure, 21-column header, 10-row roster, or reporting-area key changes without re-inventory.
- Preserve exact source headers and labels alongside normalized indicator, level, and school-year fields.
- Keep blanks as null and values at or above 100% unchanged but flagged.
- Build a dated school-division bridge and record match method; never substitute current PSGC regions silently.
- Obtain MBHTE/BPDA definitions, numerators, denominators, public/private scope, release date, and explanations for the Lamitan and Marawi values before using the rates as primary evidence.

