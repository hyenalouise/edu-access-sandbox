# psa_psgc: Philippine Standard Geographic Code (PSGC), 2Q 2026

**Status:** accepted

## Identity

| Field | Value |
|---|---|
| Source name | Philippine Standard Geographic Code (PSGC), 2Q 2026 Publication Datafile |
| Publisher / agency | Philippine Statistics Authority (PSA), Statistical Classifications Division (SCD), Standards Service |
| Source system (as stated by the publisher) | PSGC, a systematic classification and coding of geographic areas. Updated from Republic Acts and local ordinances ratified by plebiscite (COMELEC). `Metadata` sheet |
| Source URL or acquisition method | Manual download from the landing page https://psa.gov.ph/classification/psgc. Direct file URL: https://psa.gov.ph/system/files/scd/PSGC-2Q-2026-Publication-Datafile.xlsx (from the browser's download record). PSA replaces the quarterly file, so this URL may later serve a newer release; the SHA-256 below identifies the exact file used |
| Licensing or access restrictions | Access constraints: none. Use constraints: acknowledge the PSA as the source. Distributed without warranty; interpretation and use are the user's responsibility (`Metadata` sheet) |
| Owner (team member) | @maeveylain |
| Date acquired | 2026-09-27 23:41 UTC (2026-09-28 07:41 Philippine time; taken from the downloaded file's timestamp). 

## Files

| File | Format | Encoding | Size (bytes) | Row count | SHA-256 | Raw storage location |
|---|---|---|---|---|---|---|
| `PSGC-2Q-2026-Publication-Datafile.xlsx` | xlsx (6 sheets) | n/a (binary workbook; text is Unicode, e.g. "Tañong") | 3,250,889 | 43,768 data rows on sheet `PSGC` (range A1:K43769, 1 header row) | `31892bc2bdde3ea0682562d9412b5bab4d45a0be5e5a5b4f6c9d7714b94bca5d` | Team volume: `/Volumes/edu_access/00-source/raw/psa/PSGC-2Q-2026-Publication-Datafile.xlsx` (uploaded 2026-09-30, SHA-256 verified after upload). Local copy for profiling: `raw-data/psa/original/` |
| `PSGC-Q4_2023-API-all.csv` | CSV (PSA PSGC API, version `Q4_2023`, all levels) | UTF-8, no BOM, CRLF line endings. Some names have broken accents (457, e.g. `Santo NiÃ±o`) | 3,627,248 | 43,758 data rows (43,759 lines with the header), 18 columns (`code`, `area_name`, `correspondence_code`, `geographic_level`, ...) | `38a92ceba5120fe10fb45ba23a8f74458ee076829306db795044beeb40715335` | Team volume: `/Volumes/edu_access/00-source/raw/psa/PSGC-Q4_2023-API-all.csv` (uploaded 2026-10-02, SHA-256 verified on the volume, see `/Volumes/edu_access/00-source/raw/psa/SHA256SUMS.txt`). Local copy for profiling: `raw-data/psa/original/PSGC-Q4_2023-API-all.csv` |

Sheets: `Metadata`, `National Summary`, `Prov Sum`, `PSGC` (the data), `Notes`, `Coding Structure` (one image of the earlier 9-digit and the current 10-digit code structure; no cells).

`PSGC-Q4_2023-API-all.csv` is the `Q4_2023` pull used only for the comparison in [Version used and SY 2023-24](#version-used-and-sy-2023-24); it is not the master reference (D-012). It was downloaded from the PSA PSGC API page https://psa.gov.ph/classifications-api/psgc as `psgc_all.csv` and renamed to `PSGC-Q4_2023-API-all.csv` so the name says the version. Only the name changed; the contents and SHA-256 are the same. The columns match the PSA PSGC API documentation, and every row carries `version` = `Q4_2023`. It was saved on 2026-09-30 at 06:39 UTC (the file's modified time); the exact request time and the API token are not recorded. `profile_psgc.py` verifies its SHA-256 before using it (X-1).

## Raw storage and ingestion

- **Raw storage:** the 2Q 2026 workbook is the first download, so it stays flat in `/Volumes/edu_access/00-source/raw/psa/` (D-016). PSA replaces the quarterly file at a stable URL, so any later download (a new quarter, or a re-download of 2Q 2026) goes into `raw/psa/<download date>/` under its original name, with that folder's `SHA256SUMS.txt`, and never over an existing file.
- **Ingestion:** loaded to `` edu_access.`02-bronze`.psa_psgc_raw `` from the contract [`config/ingestion/psa_psgc.json`](../../../../config/ingestion/psa_psgc.json) (format `xlsx_table`, D-019), which pins the checksum, range and row count in [Files](#files). Every row of sheet `PSGC` is kept as stored text, with the workbook, sheet and Excel row number as provenance. How to add the next quarter: [ingestion runbook](../../../operations/ingestion.md#runbook-psgc).
- **Observed (ingestion, 2026-10-07):** 84 values of `10-digit PSGC` are stored in the workbook as numbers, not text. All 84 are exactly 10 digits (codes starting with `1`), so no leading zero was lost; they are kept as stored and counted as a WARN. The `2024 Population` cells use an accounting number format that displays 0 as `-`; Bronze keeps the stored `0`. Local load: 43,768 rows, every count above reproduced ([evidence](../../../../evidence/pipeline-runs/2026-10-07-psa-psgc-local-idempotency.md)); the same on Databricks `dev` on 2026-10-08 ([evidence](../../../../evidence/pipeline-runs/2026-10-08-psa-psgc-databricks-idempotency.md)).
- **Master reference:** 2Q 2026 (D-012), written as `master_reference_period` in the contract. Loading another quarter never changes it.
- **Status `accepted`** on 2026-10-21, so it loads into `prod` (D-063).

## Publisher documentation

The documentation is inside the workbook. No separate document was downloaded.

| Document | URL | SHA-256 | Sections relied on |
|---|---|---|---|
| `Metadata` sheet | inside the workbook above | same as the file | Abstract, process, progress, access and use constraints, disclaimer |
| `Notes` sheet | inside the workbook above | same as the file | A. General notes; B. Income classification; C. Urban / Rural; D. 2024 Population; E. Geographic Level codes |
| `Coding Structure` sheet (an image) | inside the workbook above | same as the file | The earlier 9-digit and the current 10-digit code structure (PSGC Revision 1) |
| `National Summary` sheet | inside the workbook above | same as the file | Counts of provinces, cities, municipalities, barangays and population by region, used to cross-check the `PSGC` sheet |

## Coverage

| Field | Value |
|---|---|
| Geographic coverage | Philippines (18 regions) |
| Geographic level | All levels in one table: region, province, city, municipality, barangay, plus 14 sub-municipalities of Manila and 2 special rows (see quality problems) |
| Time coverage | Administrative structure as of 30 June 2026. Population from the 2024 Census of Population. Our anchor data is DepEd SY 2023-24, so see "Version used and SY 2023-24" below |
| Time basis | Reference date (30 June 2026). Population: 2024 census. Urban / Rural: 2020 census (CPH) |
| Update frequency | Quarterly (`Metadata`: "Ongoing (updated quarterly)") |
| Population covered | All geographic units. Regional populations do not sum to the national total (`Notes` D.2) |

## Structure

| Field | Value |
|---|---|
| Apparent grain | One row per geographic unit (region, province, city, municipality, sub-municipality or barangay) |
| Candidate primary key | `10-digit PSGC` (43,768 rows, 43,768 unique, always 10 digits) |
| Candidate join keys | `10-digit PSGC` is the key. `Name` is usable only within its parent (province, then city or municipality, then barangay) after trimming, because names alone are ambiguous: 27,391 distinct in 43,768 rows, and 4,041 barangay names repeat. DepEd sources carry place names only, so this is the path for joining them to PSGC; see O-9 in [profile.md](profile.md) |
| PSGC available? | This is the PSGC, 2Q 2026. The `Coding Structure` sheet (an image inside the workbook) documents the 10-digit code as region (2) + province or HUC (3) + city or municipality (2) + barangay (3) digits. This is PSGC Revision 1, which widened the province code from 2 to 3 digits. The same sheet shows the earlier 9-digit code as region (2) + province (2) + municipality or city (2) + barangay (3). Sample rows are consistent with both |
| Personally identifiable or sensitive fields | None. Place names only |
| Provenance fields in the source | `Old names` (former names), `Status` (`Pob.`, `Capital`), publication date on the `Metadata` sheet |

Column-by-column descriptions, fill rates, and sample values: [data_dictionary.md](data_dictionary.md).

### Expected vs actual schema

| Column | Expected | Actual | Notes |
|---|---|---|---|
| `10-digit PSGC` | identifier | text of 10 digits | Leading zeros must be kept (e.g. `0900000000`) |
| `Name` | text | text | 2,855 values have trailing spaces |
| `Correspondence Code` | identifier | text of 9 digits | 50 blank. Not explained in the `Notes` sheet |
| `Geographic Level` | category | text, 6 values | 2 blank |
| `Old names` | text | text | Filled for 1,699 rows |
| `City Class` | category | text | Cities only (149 rows) |
| `Income Classification` | category | text | Contains `-` and starred values such as `2nd*` |
| `Urban / Rural` | category | text | Barangays only. Contains `-` |
| `2024 Population` | whole number | text | 1 cell is `#N/A` |
| (no header, column J) | none | text | Footnote text and markers, 19 rows |
| `Status` | category | text | `Pob.` or `Capital` |

## Version used and SY 2023-24

**Decision:** 2Q 2026 is the master PSGC reference for the project, including SY 2023-24 analysis. No crosswalk is built. Recorded as D-012 in [decisions.md](../../../governance/decisions.md).

**Why not a release closer to SY 2023-24:** we requested API access to look for `Q3_2023`. The API accepts the request but returns 0 records for `Q3_2023`. The nearest version it serves is `Q4_2023` (43,758 rows). That pull is recorded in [Files](#files) as `PSGC-Q4_2023-API-all.csv`, and `profile_psgc.py` reruns the counts below under X-1 when the file is in the raw folder.

**What this file shows on its own (2Q 2026, no comparison needed):**

- **Observed:** codes starting with `18` are the Negros Island Region: 1 region, 3 provinces, 19 cities, 44 municipalities, and 1,353 barangays.
- **Observed:** 430 codes start with `09066` (Sulu), listed under Region IX (Zamboanga Peninsula). Footnotes b and c on the `National Summary` sheet say the Region IX population includes Sulu and the BARMM population excludes it.

**What differs between `Q4_2023` and 2Q 2026** (compared by `10-digit PSGC`):

- **Observed:** 41,903 codes are in both files. 1,855 exist only in `Q4_2023` and 1,865 only in 2Q 2026.
- **Observed:** almost all changed codes come from the two moves above. In `Q4_2023` the same units carried Region VI and VII codes (`06...`, `07...`) for Negros and BARMM codes (`19066...`) for Sulu.
- **Observed:** the 8 special government units in `Q4_2023` are municipalities in 2Q 2026. Barangay 176 in NCR is split into 176-A to 176-F.
- **Observed:** 1,853 of the 1,865 new codes have a `Correspondence Code` that matches the same unit in `Q4_2023`. The other 12 have none (11 barangays and the NIR region row).
- **Observed:** `City Class` and `Urban / Rural` are unchanged on every shared code. `Income Classification` differs on 1,160 units because 2Q 2026 uses DOF DO No. 074.2024.
- **Observed:** `Q4_2023` has 457 names with broken accents (for example `Santo NiÃ±o`) and no 2024 population for about 1,780 barangays. 2Q 2026 has neither problem. It has no 2015 or 2020 population.

**Rules for using this file with DepEd SY 2023-24** (DepEd data has place names only, and Negros and Sulu were in Regions VI, VII, and BARMM that year):

- Match on province, municipality, and barangay names. **Never use region as a match key.**
- Match a barangay name only inside its own city or municipality, never across the file. The same barangay name exists in many cities (for example `Barangay 176` in Caloocan, Tondo, and Pasay), so a match outside the parent would be wrong. In 2Q 2026 no barangay name repeats inside the same city or municipality (0 repeats), so a match inside the parent is unique.
- Matching order for each DepEd place name: (1) exact match on the trimmed current name inside the parent; (2) if none, match on `Old names` inside the same parent; (3) if there is still no match, or more than one, flag it as unmatched or ambiguous and **do not force a match**. Example: `Barangay 176` in Caloocan was split into `176-A` to `176-F`, and all six carry `Barangay 176` in `Old names`, so it is flagged as ambiguous. In 2Q 2026, 33 pairs of (city or municipality, old name) point to more than one barangay (100 barangays).
- For SY 2023-24 results by region, use DepEd's own region column, or report at province level. Do not take the region from this file for Negros or Sulu.
- Record which PSGC version each match used (2Q 2026).

## Known quality problems

See [profile.md](profile.md) for evidence.

- **Observed:** 2 rows have a blank `Geographic Level`: "City of Isabela (Not a Province)" (`0990100000`, population `#N/A`) and "Special Geographic Area" (`1999900000`).
- **Observed:** 50 rows have no `Correspondence Code` (38 barangays, 8 municipalities, 2 provinces, 1 region, 1 blank-level row).
- **Observed:** 1 population cell is the text `#N/A`.
- **Observed:** column J has no header and holds footnote text such as "(excluding CITY OF BAGUIO)" and markers `1/`, `2/`, `3/` (19 rows).
- **Observed:** `Income Classification` mixes classes with `-` (8 municipalities in the Special Geographic Area) and starred classes (6 rows). `Notes` B explains the asterisk as a class retained after downgrade.
- **Observed:** `Urban / Rural` is `-` for 38 barangays, and they are exactly the 38 barangays with no `Correspondence Code`.
- **Observed:** 12 barangays have a population of 0.
- **Observed:** the `Notes` legend for `Geographic Level` lists `Dist`, but no row uses it. The data uses `City`, which the legend omits.
- **Observed:** names are not unique, and 2,855 names have trailing spaces.
- **Observed:** regional populations sum to 112,727,776, and the national figure is 112,729,484. The 1,708 difference matches the `Notes` D.2 explanation (Filipinos in embassies and consulates abroad).
- **Observed:** unit counts on the `PSGC` sheet match the `National Summary` sheet (82 provinces, 149 cities, 1,493 municipalities, 42,010 barangays).
- **Observed:** the hierarchy is complete: every barangay has its city or municipality in the file, and every province, city, and municipality has its region.
- **Suspected:** the 38 barangays without a code or urban/rural class are new or split barangays created after the 2020 census. To test against the previous PSGC quarter.

## Limitations for analysis

- One snapshot in time. The only history is the `Old names` column.
- Population is 2024 only and urban/rural is based on 2020, so the two bases differ.
- No coordinates or boundaries.
- Sub-municipalities of Manila are not officially municipalities (`Notes` A.1). City of Isabela is geographically in Basilan but belongs to Region IX with a special code (`Notes` A.2).
- Population counts do not add up to the national total (`Notes` D.2).
- Codes change when local government units are created, merged, or renamed. Joining to sources built on another PSGC version needs a version check first.
