# deped_psgc_coordinates: DepEd school-level enrollment with PSGC and coordinates, public schools only

**Status:** profiled

SY 2023-24 school-level enrollment for public schools only (title cell A6 reads `SECTOR: PUBLIC ONLY`), with each school's PSGC codes, longitude and latitude. One workbook, one sheet, 47,818 schools.

## Identity

| Field | Value |
|---|---|
| Source name | SY 2023-2024 School Level Data on Enrollment with PSGC Longitude & Latitude (Public only) |
| Publisher / agency | Department of Education (DepEd), as the title rows state the data's sources |
| Source system (as stated in the workbook) | Enrollment: Learner Information System (LIS), as of 2024-01-31. PSGC: PSA, 4th quarter 2024. Income class: DOF D.O. 74 s. 2024. Coordinates: NSBI, as of 2025-07-07. Title rows 1-6 |
| Source URL or acquisition method | Not published online. Requested from `phcd.staff@psa.gov.ph` (PSA). The request and reply are not in the repository |
| Licensing or access restrictions | None stated in the workbook. UNVERIFIED: ask the sender |
| Owner (team member) | @catweyine |
| Date acquired | UNVERIFIED. The file's modification time is 2026-10-21 00:54 (+08:00), used as `retrieved_at_utc` until the reply's date is recorded |

## Files

Raw files are kept in raw storage, never in git.

| File | Format | Encoding | Size (bytes) | Row count | SHA-256 | Raw storage location |
|---|---|---|---|---|---|---|
| `SY 2023-2024 School Level Data on Enrollment with PSGC Longitude & Latitude (Public only).xlsx` | xlsx, one sheet `DB` | n/a | 19,301,577 | 47,818 rows below the header (range A1:CJ47826): 47,818 schools, 0 blank, 0 with no school ID | `edf7ba68cb768d658226a316754d636bec1d792b290692b14dd0cdd6e62fc8a1` | `RAW_DATA_DIR/deped/original/`; `/Volumes/edu_access/00-source/raw/deped/` (uploaded by @catweyine) |

## Coverage

| Field | Value |
|---|---|
| Geographic coverage | Philippines; no Philippine Schools Overseas (public only) |
| Geographic level | School, with PSGC codes and names down to barangay, and coordinates |
| Time coverage | SY 2023-24 only |
| Population covered | Public schools only: 47,818 (`sector` = `Public` on every row) |

## Structure

| Field | Value |
|---|---|
| Apparent grain | One row per public school (SY 2023-24) |
| Candidate primary key | `BEIS School ID`: 6 digits and unique on every row |
| Schema | `v1`: 88 header cells in row 8 (5 title rows above, notes in row 6, sex in row 7), mapped by position to Bronze names. See [data_dictionary.md](data_dictionary.md) |
| PSGC available? Which version? | Yes, region to barangay, for 47,614 of 47,818 schools (204 `#N/A`). Stated as PSA Q4 2024 |

## Known quality problems

Summary only; evidence in [profile.md](profile.md).

- **Observed:** 28,811 PSGC codes lost their leading zero; 204 schools have `#N/A` codes (O-3).
- **Observed:** 679 schools have `#N/A` coordinates, 5 are at (0, 0), and 54 others are outside the Philippines (O-4).
- **Observed:** 40,046 of 47,080 located schools (85%) are within 10 km of the median point of their own city or municipality; 260 are over 100 km away (O-6).

## Ingestion

| Field | Value |
|---|---|
| Contract | [`config/ingestion/deped_psgc_coordinates.json`](../../../../config/ingestion/deped_psgc_coordinates.json), format `xlsx_report`. The file name, SHA-256, range, title cells and row counts are pinned in the approved delivery |
| Bronze table | `` edu_access.`02-bronze`.deped_psgc_coordinates_raw ``: every sheet row below the header as text, with its Excel row number and kind, and the 16 provenance columns. Nothing is padded, typed, or filtered (D-015). `dq_sector_not_public` WARNs if a row of another sector ever appears |
| Pipeline | Lane 09 of `edu_access_pipeline`: `09_create_deped_psgc_coordinates_raw` → `bronze_deped_psgc_coordinates` → `90_validate_deped_psgc_coordinates_raw`, then Silver `09_clean_deped_psgc_coordinates` → `90_validate_deped_psgc_coordinates_clean` |
| Silver table | `` edu_access.`03-silver`.deped_psgc_coordinates_clean ``: one row per public school, SY 2023-24, with its PSGC codes (padded, Sulu recoded) and coordinates (typed, flagged); the enrollment counts and the columns `deped_enrollment` already holds are not carried ([dictionary](../../silver/deped-psgc-coordinates-clean.md), [rules](../../../operations/silver.md#deped-public-school-locations), #217) |
| Loaded | Locally, 2026-10-21 ([evidence](../../../../evidence/pipeline-runs/2026-10-21-deped-psgc-coordinates-local-idempotency.md)); not yet on Databricks |

## Limitations for analysis

- Licensing and the acquisition record are UNVERIFIED.
- Coordinates need a boundary test (point-in-polygon against the approved boundaries) before distance measures.
