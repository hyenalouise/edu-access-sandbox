# deped_facilities: DepEd school facilities (classroom inventory)

**Status:** profiled

## Identity

| Field | Value |
|---|---|
| Source name | School Facilities (School Characteristics, machine-ready files) |
| Publisher / agency | Department of Education (DepEd), Policy and Planning Service |
| Source system (as stated by the publisher) | National School Building Inventory (NSBI). Technical Notes p. 1 |
| Source URL or acquisition method | Download from https://www.deped.gov.ph/machine-ready-files/ (School Characteristics section) |
| Licensing or access restrictions | Public download. No license terms stated on the page. UNVERIFIED |
| Owner (team member) | @hyenalouise |
| Date acquired | 2026-09-28 22:55 UTC |

## Files

| File | Format | Encoding | Size (bytes) | Row count | SHA-256 | Raw storage location |
|---|---|---|---|---|---|---|
| `School-Facilities-in-SY-2023-2024.zip` | zip | n/a | 757,576 | n/a | `9317af02b595d3a8d7381715780ef183a92da35354bbe0f3796045490e546609` | `/Volumes/edu_access/00-source/raw/deped/` (uploaded 2026-09-30); local copy in `raw-data/deped/original/` |
| ↳ `facilities_2023-24.csv` | CSV | UTF-8, LF | 11,512,476 | 60,167 | `cd60cc375fe8d4b4b4428fa2bafbe88436bbf7430e577343cfd291607429fb0e` | extracted from the zip |

## Publisher documentation

| Document | URL | SHA-256 | Sections relied on |
|---|---|---|---|
| `README.md` in the zip | inside the zip above | `7e0053dff88abac9b7b0940915a8dbcb78272a5a8711ec01b9a10a80678e41e8` | Variable definitions, including what counts as an instructional classroom |
| School Characteristics Technical Notes (PDF) | https://www.deped.gov.ph/wp-content/uploads/School-Characteristics-Technical-Notes.pdf | `a0cb8728a4b175e6eba493fa0d06146c10db9064bc3c71807162fd9266f39cbc` | NSBI covers public schools only (p. 3, 12); classroom-learner ratio definition (p. 8, 11) |

## Coverage

| Field | Value |
|---|---|
| Geographic coverage | Philippines |
| Geographic level | School only. **No location columns**; location comes from `deped_enrollment` via `school_id` |
| Time coverage | **SY 2023-24 only** (no other year is published on the page) |
| Time basis | School year |
| Update frequency | Collected annually (Technical Notes p. 3); only one year published |
| Population covered | **Public schools only** for all facility measures (Technical Notes p. 3, 12; confirmed in the data) |

## Structure

| Field | Value |
|---|---|
| Apparent grain | One row per school, SY 2023-24 |
| Candidate primary key | `school_id` |
| Candidate join keys | `school_id` to `deped_enrollment` SY 2023-24 (60,167 of 60,167 match) |
| PSGC available? | No, and no location names either |
| Personally identifiable or sensitive fields | None |
| Provenance fields in the source | None |

Column-by-column descriptions, fill rates, and sample values: [data_dictionary.md](data_dictionary.md).

### Expected vs actual schema

| Column group | Expected (README) | Actual | Notes |
|---|---|---|---|
| School information | 6 columns | matches | Same values as enrollment for every school |
| Classroom, building, temporary space counts | nullable integers | 21 columns, all whole numbers, none negative | Blank for all non-public schools |
| Amenities, road, transport access | nullable booleans | 60 columns with values `True`, `False`, or blank | 34.6% to 96.1% blank per column |

## Known quality problems

See [profile.md](profile.md) for evidence.

- **Observed:** facility measures exist for public schools only.
- **Observed:** 669 public schools that offer elementary have no elementary classroom count, and no school records 0 elementary classrooms.
- **Observed:** the "instructional classroom" definition here is broader than the one DepEd uses for its classroom-learner ratio.
- **Suspected:** extreme learner-per-room values point to classroom undercounts or reporting errors.

## Ingestion

| Field | Value |
|---|---|
| Contract (approved deliveries, schema versions) | [`config/ingestion/deped_facilities.json`](../../../../config/ingestion/deped_facilities.json) |
| Bronze table | `` edu_access.`02-bronze`.deped_facilities_raw ``: every school year and delivery version, text, with provenance |
| Schema versions | `v1` (SY 2023-24, 87 columns) |
| Loaded locally | SY 2023-24, 2026-10-06: 60,167 rows, matching the table above; a second run skipped it. Blanks stay blank: 669 public elementary schools have `es_classrooms_instructional` = `''` (O-4), and none has `'0'` (O-5) |
| Raw storage | `/Volumes/edu_access/00-source/raw/deped/`, uploaded 2026-09-30; a local copy for profiling stays in `raw-data/deped/original/` |
| Checksums after upload | Match the table above. The ingestion job hashed the zip in the volume, and the CSV and README inside it, before loading, and refuses any file whose checksum differs; it loaded (job run `588715548188592`, 2026-10-06). The folder's `SHA256SUMS.txt` lists the same value |
| Loaded on Databricks | Yes, 2026-10-06 (`dev`): 60,167 rows loaded and verified; a second run skipped it ([evidence](../../../../evidence/pipeline-runs/2026-10-06-deped-facilities-idempotency.md)) |
| Silver | `` edu_access.`03-silver`.deped_facilities_clean `` and `deped_facilities_quarantine` ([data dictionary](../../silver/deped-facilities-clean.md), [runbook](../../../operations/silver.md#deped-facilities), D-038). Built locally from the real SY 2023-24 file on 2026-10-11: 60,167 clean rows, none quarantined, every check PASS ([evidence](../../../../evidence/reconciliation/2026-10-11-deped-facilities-bronze-to-silver.md)); the same on Databricks `dev`, twice, at `6b2844d` ([evidence](../../../../evidence/pipeline-runs/2026-10-11-deped-facilities-silver.md)). A school missing from enrollment Silver is now quarantined (D-038); rerun locally at `1c2317b` with the same result, the `dev` run at that commit is still to do |

How a new school year or a revised file is added: [ingestion.md, Runbook](../../../operations/ingestion.md#runbook).

## Limitations for analysis

- Any capacity measure covers **public schools only** and **SY 2023-24 only**.
- `*_classrooms_instructional` includes ALS rooms, audio-visual rooms, computer rooms, and laboratories (README). DepEd's classroom-learner ratio uses Kindergarten to Grade 12 classrooms only (Technical Notes p. 11). A ratio computed from this file will show **fewer learners per room than DepEd's official figure** and must be named accordingly, e.g. "learners per instructional room (NSBI definition)".
- No official standard or ideal ratio is given in the Technical Notes. None may be applied without a cited source.
