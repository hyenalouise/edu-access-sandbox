# bpda_barmm_social_infrastructure: BARMM social infrastructure

**Status:** profiled

## Identity

| Field | Value |
|---|---|
| Source name | BARMM Social Infrastructure: Health and Education |
| Publisher / agency | Bangsamoro Planning and Development Authority (BPDA), Bangsamoro Knowledge Portal |
| Source system (as stated by the publisher) | Bangsamoro Ecological Profile, Infrastructure open data |
| Source URL or acquisition method | Public XLSX download linked under **BARMM Social Infrastructure: Health and Education** on the [Bangsamoro Knowledge Portal](https://knowledge.bpda.bangsamoro.gov.ph/open-data/bangsamoro-ecological-profile/infrastructure); [direct export](https://docs.google.com/spreadsheets/d/1XFU9wNnuIPhUF3BrxUQWWGDvYV21v7b3tySdhPYleK4/export?format=xlsx) |
| Licensing or access restrictions | Public download. No license or reuse terms were found on the landing page or in the workbook; reuse terms remain **UNVERIFIED** |
| Owner (team member) | @hyenalouise |
| Date acquired | 2026-10-04 (Philippine time) |

## Files

Raw files are kept outside git. Row count excludes the header and empty formatted rows.

| File | Format | Encoding | Size (bytes) | Row count | SHA-256 | Raw storage location |
|---|---|---|---|---|---|---|
| `BARMM_Social_Infrastructure.xlsx` | XLSX, one worksheet | n/a | 31,251 | 9 | `6af9c99e33d820f99eb554326eb126cf6a2cdb30945e8f11088a0b26197391d3` | Databricks volume `/Volumes/edu_access/00-source/raw/bpda/` |

## Publisher documentation

| Document | URL | SHA-256 | Sections relied on |
|---|---|---|---|
| Bangsamoro Knowledge Portal: Infrastructure Development in BARMM (HTML snapshot `BPDA_Infrastructure_page_2026-10-04.html`, 214,951 bytes, saved 2026-10-04 Philippine time; stored in `/Volumes/edu_access/00-source/raw/bpda/`) | https://knowledge.bpda.bangsamoro.gov.ph/open-data/bangsamoro-ecological-profile/infrastructure | `24807e66d0c5f2a313fab4b06b795a6cc3843d49a7dee03764714abc260b1999` | Publisher, dataset title, placement in the Bangsamoro Ecological Profile, download link (the snapshot contains the same Google Sheet ID as the direct export). No license or reuse terms appear on the page |
| Workbook header | Inside the inventoried file | File checksum above | Exact measure names, the few stated reference periods, and units |

No methodology, source note, geographic definition, dash-marker definition, or release note accompanies the workbook.

## Coverage

| Field | Value |
|---|---|
| Geographic coverage | Nine historical BARMM reporting areas: Maguindanao, Lanao del Sur, Basilan, Sulu, Tawi-Tawi, Cotabato City, Special Geographic Area (SGA), Lamitan City, and Marawi City |
| Geographic level | Mixed provinces, cities, and SGA |
| Time coverage | Mixed. Private/public elementary schools are labeled 2019-2021; permanent elementary classroom buildings are labeled as of 2022; hospital, RHU, and BHS facilities are labeled 2011-2021. Most education and other measures have no stated reference period |
| Time basis | Mixed period and as-of counts; row-level dates are absent |
| Update frequency | **UNVERIFIED** |
| Population covered | Education fields cover private/public elementary and secondary schools, private madaris, classroom buildings, selected school facilities, SUCs, and ministry-supervised HEIs. Sector definitions and institutional coverage are **UNVERIFIED** |

## Structure

| Field | Value |
|---|---|
| Apparent grain | One wide row per published province/city/SGA label, with 32 count measures across education and other social-infrastructure domains |
| Candidate primary key | Raw `Province/City`; 9 rows and 0 duplicates |
| Candidate join keys | Historical reporting-area label plus measure-specific reference period where known. A governed historical-geography bridge is required |
| PSGC available? Which version? | No codes. The geography uses unsplit Maguindanao, includes SGA as a separate row, and includes Sulu in BARMM |
| Personally identifiable or sensitive fields | None. Public aggregate facility counts only. Classification: **Public** |
| Provenance fields in the source | Worksheet name, row number, exact measure header, and reporting-area label. No publication date, revision, source agency per column, or extraction timestamp appears inside the workbook |

Column-by-column descriptions, fill rates, and ranges: [data_dictionary.md](data_dictionary.md).

### Expected vs actual schema

| Column or structure | Expected type | Actual type | Notes |
|---|---|---|---|
| `Province/City` | Geographic reporting area | Text | Unique, but mixes provinces, cities, and SGA |
| 32 measures | Nonnegative whole-number counts | 200 numeric values, 87 `-` markers, and 1 physical blank | All 200 numeric values are whole numbers; 4 are explicit zeroes |
| Numeric formatting | Clean number | Three numeric-looking cells contain a leading non-breaking space | Normalize Unicode whitespace after retaining raw text |
| Worksheet extent | Header plus 9 rows | 1,000 physical rows, of which 990 are empty formatted rows | Ignore only rows with no populated cells |
| Geographic code | PSGC | Absent | Manual, versioned crosswalk required |

## Lineage and dependencies

Unstated originating ministries/systems -> BPDA Bangsamoro Ecological Profile Google Sheet -> public XLSX export -> checksum-verified raw storage -> header, type, missing-marker, and reconciliation checks -> education-field selection with raw lineage -> historical reporting-area bridge -> descriptive infrastructure indicators.

## Known quality problems

Summary only; evidence lives in [profile.md](profile.md).

- **Observed:** 87 of 288 measure cells contain `-`, but the publisher does not define whether it means zero, not applicable, not available, or not reported. The profile treats it as null.
- **Observed:** one cell is physically blank, distinct from the 87 dash markers.
- **Observed:** three numeric-looking cells contain leading non-breaking spaces.
- **Observed:** the sheet has 990 empty formatted rows after the 10 non-empty rows.
- **Observed:** the semi-permanent elementary classroom-building header says `as of 20222`, an apparent typo that remains uncorrected in raw data.
- **Observed:** the 21 education columns mix stated periods and no-date measures. Values cannot be assumed to share one reference year.
- **Observed:** classroom measures count **classroom buildings**, not rooms, seats, capacity, utilization, or condition.
- **Observed:** no PSGC or other geographic code is supplied; the geography is historical and mixed-level.
- **Observed:** `Number of SUCs and Elementary Schools` is ambiguous and cannot be interpreted safely from the header alone.
- **Observed:** private elementary and private secondary school counts are identical in 5 of 9 rows (Maguindanao 88, Lanao del Sur 57, Basilan 13, Sulu 15, Tawi-Tawi 18). The other four rows differ. At least one column is probably a copy error, so both are excluded until BPDA confirms them.
- **Observed:** four permanent classroom-building counts are far out of line with school counts: Cotabato City elementary has 34.2 buildings per public school, SGA elementary 16.3, Lamitan City secondary 70.1, and Marawi City secondary 38.4, against 1.2 to 5.7 elsewhere.

## Limitations for analysis

- The source is suitable for historical descriptive context at a broad reporting-area level. It is not school-level operational data.
- It cannot support distance or travel-time analysis because it has no school addresses, coordinates, barangay, or road geometry.
- It cannot support classroom crowding or learner-to-classroom ratios: it counts buildings and supplies no learners, classrooms, seats, or design capacity at the same grain and date.
- It cannot support teacher workload because it has no teacher or personnel counts.
- Measures with unspecified reference periods must not be combined into a same-year model.
- Dashes must not be converted to zero without publisher confirmation.
- Private elementary and private secondary school counts must not be used until BPDA confirms which values are correct.
- Areas must not be ranked on classroom-building counts until BPDA explains the four outlying values.
- Non-education fields are out of project scope but remain documented because they arrived in the same source file.

## Recommended controls and monitoring

- Fail ingestion if the checksum, 33-column header, 9-row roster, or reporting-area key changes without re-inventory.
- Preserve raw text, including `-` and non-breaking spaces, alongside normalized numeric values.
- Treat `-` and physical blank as separate null-reason states until BPDA defines them.
- Select education fields explicitly; do not ingest every measure into the education fact model by accident.
- Attach a measure-level reference period and source-status field; mark unstated dates as unknown.
- Build a dated reporting-area bridge and record the match method; never force the rows onto current PSGC geography.
- Obtain data definitions, source ministry/system, dates, dash semantics, and clarification of the ambiguous/typo headers before using this as primary evidence.

