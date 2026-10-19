# deped_enrollment: DepEd school-level enrollment

**Status:** profiled

## Identity

| Field | Value |
|---|---|
| Source name | Enrollment (School Characteristics, machine-ready files) |
| Publisher / agency | Department of Education (DepEd), Policy and Planning Service |
| Source system (as stated by the publisher) | Learner Information System (LIS), Beginning of School Year (BOSY) collection. Technical Notes p. 1, 3 |
| Source URL or acquisition method | Download from https://www.deped.gov.ph/machine-ready-files/ (School Characteristics section), one zip per school year |
| Licensing or access restrictions | Public download. No license terms stated on the page. UNVERIFIED |
| Owner (team member) | @hyenalouise |
| Date acquired | 2026-09-28 22:55 UTC (SY 2023-24 to 2025-26); 2026-10-15 20:15 UTC, 2026-10-16 Philippine time (SY 2020-21); 2026-10-18 16:09 UTC, 2026-10-19 Philippine time (SY 2021-22 and 2022-23) |

## Files

Published years: SY 2017-18 to SY 2025-26. Acquired so far: the six years below, SY 2020-21 to 2025-26.

| File | Format | Encoding | Size (bytes) | Row count | SHA-256 | Raw storage location |
|---|---|---|---|---|---|---|
| `Enrollment-in-SY-2020-2021.zip` | zip | n/a | 2,965,093 | n/a | `65c400aa31ba63730b8f9a7b4d60ade91c6a29cdb34a3c6bf255e5fc9e91a241` | `/Volumes/edu_access/00-source/raw/deped/2026-10-16/` (uploaded 2026-10-16 to `raw/_holding/deped/2026-10-16/` with a `RETRIEVED.txt` giving the source URL and download time and a `SHA256SUMS.txt`; moved here 2026-10-18 after the contract pull request merged, checksum verified after the move) |
| ↳ `enrollment_2020-21.csv` | CSV | UTF-8, LF | 19,159,186 | 60,957 | `5cef0e62c4998dbf74bb2116a468f1b87ea1f296f29bd830988796cc543cf1cb` | extracted from the zip |
| `Enrollment-in-SY-2021-2022.zip` | zip | n/a | 2,963,183 | n/a | `62f412466435db6feba57684643f5af99ca901c6ea88accb420efe9a9bfb0acd` | `/Volumes/edu_access/00-source/raw/deped/2026-10-19/` (uploaded 2026-10-19 to `raw/_holding/deped/2026-10-19/` with a `RETRIEVED.txt` giving the source URL, download time, and server Last-Modified, and a `SHA256SUMS.txt`, and downloaded back with matching checksums; it moves here once its contract pull request merges, so the loader does not find it before approval) |
| ↳ `enrollment_2021-22.csv` | CSV | UTF-8, LF | 19,015,035 | 60,429 | `ffbfcd0bfe326c80a5f11b55ee7a9b20d4014107e7a5dc1e7023142b9be35287` | extracted from the zip |
| `Enrollment-in-SY-2022-2023.zip` | zip | n/a | 2,964,672 | n/a | `6d567d801a8d4eb6c9dec3c032ba208e4cd929c226b6326bc7c687c83efbf9bf` | `/Volumes/edu_access/00-source/raw/deped/2026-10-19/` (same upload, checks, and move as SY 2021-22) |
| ↳ `enrollment_2022-23.csv` | CSV | UTF-8, LF | 18,970,785 | 60,137 | `d53142a5a1f50886336479d67fbbebe3e16a65f15bfbfa2cb57714ac3d05ec49` | extracted from the zip |
| `Enrollment-in-SY-2023-2024.zip` | zip | n/a | 2,969,709 | n/a | `a10f4d0f9082919c13b3a091774c8231c99c95b1b1872310714107013b77dbbb` | `/Volumes/edu_access/00-source/raw/deped/` (uploaded 2026-09-30) |
| ↳ `enrollment_2023-24.csv` | CSV | UTF-8, LF | 19,010,469 | 60,167 | `cb9457d1dd12cccde880e0d8065212f16a4a5970ac525d5e2f8c90069f1c3657` | extracted from the zip |
| `Enrollment-in-SY-2024-2025.zip` | zip | n/a | 2,962,042 | n/a | `fd5dd74a62b828608c62335b7c324ddf05be58e3f05465fee68854795f5b1a92` | `/Volumes/edu_access/00-source/raw/deped/` (uploaded 2026-09-30) |
| ↳ `enrollment_2024-25.csv` | CSV | UTF-8, LF | 19,223,401 | 60,129 | `dd14e211bb32d8b80450c1e061397f6d7d3c819cef2070f204ddf33395ff5dac` | extracted from the zip |
| `Enrollment-in-SY-2025-2026.zip` | zip | n/a | 2,981,421 | n/a | `ab4d7e24b3a46a99db2c76dee5279a976e4c3a76062e79f7217e70dc6dd1b450` | `/Volumes/edu_access/00-source/raw/deped/` (uploaded 2026-09-30) |
| ↳ `enrollment_2025-26.csv` | CSV | **Windows-1252, CRLF** | 18,840,355 | 60,204 | `8c80173a7fc29eb3dd7b9e018d603022c731713d794945a8c9c2a2f0f190ee9e` | extracted from the zip |

## Publisher documentation

| Document | URL | SHA-256 | Sections relied on |
|---|---|---|---|
| `README.md` in the SY 2020-21 to 2024-25 zips (identical) | inside the zips above | `5eb05f7dc0bb7ecc7f9b531eca109af0b86b9379957d9c2261640500ba492a80` | Variable documentation, notes on school ID and region changes |
| `README.md` in the SY 2025-26 zip | inside the zip above | `f2aa7710a2448a69e6276672ad15ebb46abd6666e6b923a5639bd4e9541cb0b6` | Adds the four `g11_sshs_*` columns |
| School Characteristics Technical Notes (PDF, 12 pages, effective 2024-09-10) | https://www.deped.gov.ph/wp-content/uploads/School-Characteristics-Technical-Notes.pdf | `a0cb8728a4b175e6eba493fa0d06146c10db9064bc3c71807162fd9266f39cbc` | Data sources (p. 1-2), collection timing (p. 3), indicator formulas (p. 4-9), data limitations (p. 11-12) |

## Coverage

| Field | Value |
|---|---|
| Geographic coverage | Philippines, plus Philippine Schools Overseas (PSO) |
| Geographic level | School, with names of region, division, province, municipality, and barangay |
| Time coverage | SY 2020-21 to 2025-26 acquired, six consecutive years (SY 2017-18 onward published) |
| Time basis | School year. Enrollment is the official BOSY count (Technical Notes p. 3) |
| Update frequency | Annual. Files re-uploaded 2025-10-15; SY 2025-26 added 2026-07-23 |
| Population covered | All sectors: public, private, SUC/LUC, PSO |

## Structure

| Field | Value |
|---|---|
| Apparent grain | One row per school per school year |
| Candidate primary key | `school_id` (unique within each file; expected to be 6 digits, with one documented seven-digit exception in SY 2022-23) |
| Candidate join keys | `school_id` to other DepEd school datasets. Location names to PSGC (by name matching only) |
| PSGC available? | **No.** Location is names only |
| Personally identifiable or sensitive fields | None found. Counts are aggregated per school |
| Provenance fields in the source | None. School year comes from the file name |

Column-by-column descriptions, fill rates, and sample values: [data_dictionary.md](data_dictionary.md).

### Expected vs actual schema

| Column group | Expected (README) | Actual | Notes |
|---|---|---|---|
| School information (17 columns) | as documented | matches in 2020-21 to 2024-25 | 2025-26 adds undocumented `Modified Curricular Offering Classification` |
| Enrollment counts | nullable integers | 62 columns (2020-21 to 2024-25), 66 (2025-26) | All values are whole numbers; none negative |
| `offers_es/jhs/shs` | boolean | `True`/`False` (2020-21 to 2024-25); `Yes`/`No` (2025-26) | Label change |

## Known quality problems

See [profile.md](profile.md) for evidence.

- **Observed:** no PSGC codes; place names need standardizing before matching (suffixes like "(Capital)", mixed capitalization, extra spaces in 2025-26).
- **Observed:** about 173 place names per year contain mangled characters (`Ã‘` for `Ñ`), and barangay names appear to be capped at 40 characters.
- **Observed:** SY 2025-26 differs in encoding, columns, and category labels.
- **Observed:** Negros Island Region (NIR) appears from SY 2024-25; 2,704 schools moved into it from Regions VI and VII.
- **Observed:** 192 schools in Cotabato City and North Cotabato's Special Geographic Area change from Region XII in SY 2020-21 to BARMM in SY 2021-22. Of those, 191 remain present in SY 2023-24; `405811`, Menang Institute of Technology, is absent by then.
- **Observed:** SY 2022-23 has one seven-digit school ID, `1404066`, with 8 Kindergarten learners. The same file has the same school name under six-digit ID `404066`, but the source does not confirm that the IDs identify the same school; Silver's six-digit rule quarantines `1404066` rather than merging it.
- **Observed:** `Local Government` management appears only in SY 2020-21 to 2022-23 (154, 155, and 106 schools).
- **Observed:** about 1% of school IDs appear or disappear between consecutive years; 2,517 SY 2020-21 IDs (1,711 private) are gone by SY 2023-24, 1,064 of them already in SY 2021-22.
- **Suspected:** schools with zero enrollment (439 in SY 2020-21, 206 in 2021-22, 153 in 2022-23, and 115 in 2023-24, mostly private) may be closed or non-reporting.

## Ingestion

| Field | Value |
|---|---|
| Status by school year | Six years acquired and profiled. Four in the contract: SY 2020-21, 2023-24, 2024-25, 2025-26. SY 2021-22 and 2022-23 (profiled 2026-10-19) are not in the contract yet, so nothing loads them into Bronze or Silver. SY 2020-21 was added 2026-10-16 as the fourth delivery of the same lane (no new task or table) and is loaded in Bronze and Silver locally and on Databricks `dev` (2026-10-18, [evidence](../../../../evidence/pipeline-runs/2026-10-18-deped-enrollment-2020-21-databricks.md)) |
| Contract (approved deliveries, schema versions) | [`config/ingestion/deped_enrollment.json`](../../../../config/ingestion/deped_enrollment.json) |
| Bronze table | `` edu_access.`02-bronze`.deped_enrollment_raw ``: all school years and delivery versions, text, with provenance |
| Schema versions | `v1` (SY 2020-21, 2023-24, 2024-25), `v2` (SY 2025-26) |
| Loaded locally | SY 2023-24, 2024-25, 2025-26, 2026-10-06; all four years, 2026-10-16 at `98487d6`: 60,957 + 60,167 + 60,129 + 60,204 rows, matching the table above, every gate check PASS, and a second run inserted 0 ([evidence](../../../../evidence/reconciliation/2026-10-16-deped-enrollment-2020-21-bronze-to-silver.md)) |
| Raw storage | `/Volumes/edu_access/00-source/raw/deped/`, uploaded 2026-09-30; SY 2020-21 in `raw/deped/2026-10-16/`, uploaded 2026-10-16 to `raw/_holding/deped/2026-10-16/` so the loader did not find it before approval, and moved 2026-10-18 after the contract pull request merged; SY 2021-22 and 2022-23 in `raw/deped/2026-10-19/`, uploaded 2026-10-19 to `raw/_holding/deped/2026-10-19/` the same way and moved once their contract pull request merges; a local copy for profiling and the local runs stays in `raw-data/deped/original/` |
| Checksums after upload | Match the table above. The ingestion job hashed each zip in the volume, and the CSV and README inside it, before loading, and refuses any file whose checksum differs; all three loaded (job run `738752819100453`, 2026-10-06). The folder's `SHA256SUMS.txt` lists the same values. SY 2020-21: downloaded back after the move on 2026-10-18 and matched the table, then hashed and loaded by the job (job run `146052617753176`); `raw/deped/2026-10-16/SHA256SUMS.txt` lists it. SY 2021-22 and 2022-23: downloaded back from the holding folder on 2026-10-19 and matched the table; the folder's `SHA256SUMS.txt`, which moves with them, lists both zips and `RETRIEVED.txt` |
| Loaded on Databricks | SY 2023-24 to 2025-26 only, 2026-10-06 (`dev`): all three loaded and verified; a second run skipped them all ([evidence](../../../../evidence/pipeline-runs/2026-10-06-deped-enrollment-idempotency.md)). SY 2020-21, 2026-10-18 (`dev`): loaded as a backfill of 60,957 rows while the other three skipped; a second run skipped all four ([evidence](../../../../evidence/pipeline-runs/2026-10-18-deped-enrollment-2020-21-databricks.md)) |
| Silver tables | `` edu_access.`03-silver`.deped_enrollment_clean `` and `deped_enrollment_quarantine`: one row per school per school year, current delivery only ([dictionary](../../silver/deped-enrollment-clean.md), [rules and counts](../../../operations/silver.md#cleaning-rules)). Built locally on the real data 2026-10-07, and on Databricks `dev` 2026-10-09 for SY 2023-24 to 2025-26 ([evidence](../../../../evidence/pipeline-runs/2026-10-09-deped-enrollment-silver.md)). SY 2020-21 built locally 2026-10-16: 60,957 clean, 0 quarantined, 26,227,022 learners, `Local Government` kept as its own `school_management` value ([evidence](../../../../evidence/reconciliation/2026-10-16-deped-enrollment-2020-21-bronze-to-silver.md)); the same on Databricks `dev` 2026-10-18, 153 checks PASS in both runs ([evidence](../../../../evidence/pipeline-runs/2026-10-18-deped-enrollment-2020-21-databricks.md)) |

How a new school year or a revised file is added: [ingestion.md, Runbook](../../../operations/ingestion.md#runbook).

## Limitations for analysis

- Enrollment rates (GER, NER) require PSA projected population. DepEd itself reports them no lower than the school division (Technical Notes p. 11-12).
- A below-100% NER must not be read as the share of children not enrolled (Technical Notes p. 9).
- Year-over-year school comparisons are affected by school ID changes; DepEd has not yet published an ID mapping (README).
