# bpda_mbhte_infrastructure_projects: monitored MBHTE infrastructure projects

**Status:** profiled

## Identity

| Field | Value |
|---|---|
| Source name | Monitoring and Evaluation of Infrastructure Projects of MBHTE |
| Publisher / agency | Bangsamoro Planning and Development Authority (BPDA), Bangsamoro Knowledge Portal |
| Source system (as stated by the publisher) | BPDA Monitoring and Evaluation, MBHTE M&E open data |
| Source URL or acquisition method | Public XLSX download from the [Bangsamoro Knowledge Portal](https://knowledge.bpda.bangsamoro.gov.ph/open-data/bpda-monitoring-and-evaluation/mbhte-m-and-e); [direct export](https://docs.google.com/spreadsheets/d/1f43vvtNPMIlpiVsUsnseOpvZUUrpII64vCjpy1erJmA/export?format=xlsx) |
| Licensing or access restrictions | Public download. No license or reuse terms were found on the landing page or in the workbook; reuse terms remain **UNVERIFIED** |
| Owner (team member) | @hyenalouise |
| Date acquired | 2026-10-04 (Philippine time) |

## Files

Raw files are kept outside git. Row count excludes the header and empty formatted rows.

| File | Format | Encoding | Size (bytes) | Row count | SHA-256 | Raw storage location |
|---|---|---|---|---|---|---|
| `BARMM_MBHTE_Infrastructure_Projects.xlsx` | XLSX, three worksheets | n/a | 171,657 | 16 | `9a21113c97a773bdbeba66d23cb7855b563ff91bfa8f320268b6c0b687fee734` | Databricks volume `/Volumes/edu_access/00-source/raw/bpda/` |

## Publisher documentation

| Document | URL | SHA-256 | Sections relied on |
|---|---|---|---|
| Bangsamoro Knowledge Portal: MBHTE M&E (HTML snapshot `BPDA_MBHTE_ME_page_2026-10-04.html`, 180,436 bytes, saved 2026-10-04 Philippine time; stored in `/Volumes/edu_access/00-source/raw/bpda/`) | https://knowledge.bpda.bangsamoro.gov.ph/open-data/bpda-monitoring-and-evaluation/mbhte-m-and-e | `1ef4655de969ff6ebc9c10bea3a44712cb74a891cd0aa26c4d59507a95cbdbd9` | Publisher, dataset title, monitoring context, and download link (the snapshot contains the same Google Sheet ID as the direct export). No license or reuse terms appear on the page |
| Workbook headers and dashboard title | Inside the inventoried file | File checksum above | Exact fields, project labels, dates, statuses, and monitoring organization |

No codebook, project-selection rule, project identifier, revision history, or release note accompanies the workbook.

## Coverage

| Field | Value |
|---|---|
| Geographic coverage | All 16 delivered records are in Basilan: Lamitan City, Sumisip, Tipo Tipo, and Al Barka |
| Geographic level | Project with province and municipality/city labels; barangay column present but completely blank |
| Time coverage | Funding years 2020-2022 for 13 records; 3 funding years blank. Monitoring dates are 2024-04-22 or 2024-04-26 |
| Time basis | Funding year and date monitored |
| Update frequency | **UNVERIFIED** |
| Population covered | Sixteen infrastructure projects included in the downloaded workbook; the selection and completeness rules are **UNVERIFIED** |

## Structure

| Field | Value |
|---|---|
| Apparent grain | One row per named monitored infrastructure project |
| Candidate primary key | No governed key. Exact project name is unique in this file, but it is free text and not safe as a persistent identifier |
| Candidate join keys | Province, municipality/city, and project/school text. No school ID, project ID, barangay, PSGC, or coordinates are present |
| PSGC available? Which version? | No codes |
| Personally identifiable or sensitive fields | No learner or beneficiary records. `MONITORED BY` identifies only the organization `BPDA`. Classification: **Public** |
| Provenance fields in the source | Worksheet name, row number, project name, funding year, monitoring date, status, project type, and monitoring organization |

Column-by-column descriptions, fill rates, and samples: [data_dictionary.md](data_dictionary.md).

### Expected vs actual schema

| Column or structure | Expected type | Actual type | Notes |
|---|---|---|---|
| Province and municipality | Geographic labels | Uppercase text | Complete, but no PSGC or boundary version |
| Barangay | Geographic label | Completely blank | 0 of 16 records filled |
| Project name | Project description or identifier | Free text | 16 distinct values; capitalization and naming are not standardized |
| Program | Program category | Text acronym | 13 filled and 3 blank; acronyms not defined |
| Year funded | Whole-number year | Numeric value | 13 filled; values 2020, 2021, or 2022 |
| Date monitored | Date | Excel date serial with `yyyy-mm-dd` formatting | Complete; decodes to 2024-04-22 or 2024-04-26 using the workbook's 1900 date system |
| Remarks | Project status | Text category | 9 `COMPLETED`, 6 `ON GOING`, and 1 `ABANDONED` |
| Project type | Project category | Text category | 15 `BUILDING` and 1 `COVERED COURT` |

## Lineage and dependencies

Unstated originating project-management records -> BPDA monitoring workbook -> public Google Sheet XLSX export -> checksum-verified raw storage -> completeness, category, and date checks -> optional manual project/school matching with documented review.

## Known quality problems

Summary only; evidence lives in [profile.md](profile.md).

- **Observed:** the downloaded file contains only 16 Basilan projects and therefore is not evidence of BARMM-wide project coverage.
- **Observed:** all 16 barangay cells are blank.
- **Observed:** `Repair of Tipo-Tipo ES 6CL` and `REPAIR OF TIPO-TIPO ES3CL` name the same school with the same program, funding year, status, and monitoring date. They may be one project entered twice, so the file holds 16 records but possibly 15 projects.
- **Observed:** `PROGRAM` and `YEAR FUNDED` are both blank for the final three projects.
- **Observed:** the file has no project ID, school ID, PSGC, coordinates, cost, funding amount, physical-progress percentage, start date, completion date, or beneficiary count.
- **Observed:** 10 project names start with `Construction` and 6 with `Repair`; 3 of the 9 `COMPLETED` records are repairs.
- **Observed:** project names are free text. Classroom counts such as `2CL` or `10CL` appear inside some names but are not supplied as a defined structured field.
- **Observed:** 983 formatted rows after the populated records are empty; they are excluded from the 16-row count.
- **Observed:** the workbook contains two dashboard sheets with titles but no additional tabular records.

## Limitations for analysis

- The source can support a small descriptive account of the 16 delivered Basilan monitoring records.
- It cannot measure BARMM-wide infrastructure delivery, compare provinces, or estimate coverage without the full project universe and selection rules.
- It cannot join reliably to school-level enrollment, facilities, or outcomes because it lacks school IDs and barangay values.
- It cannot support distance analysis because it has no coordinates or geometry.
- `COMPLETED` is a published status label, not proof of completion date, usable classrooms, occupancy, or service availability.
- Classroom quantities embedded in project names should not be parsed as authoritative capacity until MBHTE defines `CL` and confirms the names are complete and standardized.
- Six of the 16 records are repairs, including 3 of the 9 `COMPLETED` records. A completed repair adds no new classrooms, so classroom tokens must never be totalled across construction and repair projects.

## Recommended controls and monitoring

- Fail ingestion if the checksum, worksheet names, 10-column header, or 16 populated rows change without re-inventory.
- Preserve original project name, status, program, date serial, decoded date, and source row.
- Keep missing barangay, program, and funding-year values null; do not infer them from the project name.
- Do not claim regional completeness or project impact from this file.
- Request the complete project register and codebook with project ID, school ID, PSGC/barangay, coordinates, project scope, budget, dates, progress measure, selection criteria, and revision history.

