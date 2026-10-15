# deped_enrollment_psgc: DepEd school-level enrollment with PSGC and coordinates

**Status:** profiled

Issue: #135. The same SY 2023-24 enrollment as [deped_enrollment](../deped_enrollment/README.md), with PSGC codes and school coordinates added. It supplements deped_enrollment rather than replacing it: the team agreed in #137 on option B, so deped_enrollment stays the only enrollment source and this file is used as a `school_id` → PSGC crosswalk, the first DepEd match method, with name matching as the fallback. The decision is recorded in `docs/governance/decisions.md` when #137 closes.

## Identity

| Field | Value |
|---|---|
| Source name | SY 2023-2024 School Level Data on Enrollment with PSGC, Longitude and Latitude |
| Publisher / agency | Department of Education (DepEd), Planning Service, Education Management Information System Division (EMISD) |
| Source system (as stated by the publisher) | Enrollment: Learner Information System (LIS), as of 2024-01-31. PSGC: PSA, 4th quarter 2024. Income class: DOF D.O. 74 s. 2024. Coordinates: NSBI, as of 2025-07-07. All from the workbook's title rows 1-6 |
| Source URL or acquisition method | Not published online. Requested from DepEd EMISD by a team member; EMISD sent the workbook as an email attachment "in response to your request". The email is kept with the raw file as a PDF, not in git (see Publisher documentation) |
| Licensing or access restrictions | Provided "for your information and reference" (EMISD email). No license terms stated; whether results may be published from it is UNVERIFIED. Publishing derived outputs (presentation, dashboard) is on hold until EMISD clarifies; the question is listed in the [profile](profile.md#questions-for-the-publisher-or-mentor) |
| Owner (team member) | @maeveylain |
| Date acquired | 2026-10-14, 17:46 (+08:00): date of the EMISD email |

## Files

Raw files are kept in raw storage, never in git. Record exactly what arrived.

| File | Format | Encoding | Size (bytes) | Row count | SHA-256 | Raw storage location |
|---|---|---|---|---|---|---|
| `SY 2023-2024 School Level Data on Enrollment with PSGC, Longitude and Latitude.xlsx` | xlsx, one sheet `DB` | n/a | 24,527,420 | 60,275 schools (sheet rows 9-60293; see profile O-1, O-2) | `746d69530d228d2324590be10abbe6d75a94176c1745ef74335a4d6db550acd5` | `RAW_DATA_DIR/deped/original/` (local). Not yet uploaded to the Databricks volume |

## Publisher documentation

| Document | URL | SHA-256 | Sections relied on |
|---|---|---|---|
| EMISD email, 2026-10-14: `Request for SY 2023–2024 Basic Education School Coordinates.pdf` (171,051 bytes), in `RAW_DATA_DIR/deped/original/` | none (email) | `9ad6cf870c41cc5afa8e294f852ca19c9406b47d7f9394c826b2cd021978a69e` | Publisher office, acquisition channel, and terms ("for your information and reference") |
| Title rows 1-5 and notes in row 6 of the workbook itself | in the file above | as above | Reference dates and the basis of PSGC, income class, and coordinates |
| School Characteristics Technical Notes (PDF), via deped_facilities | https://www.deped.gov.ph/wp-content/uploads/School-Characteristics-Technical-Notes.pdf | `a0cb8728a4b175e6eba493fa0d06146c10db9064bc3c71807162fd9266f39cbc` | NSBI covers public schools only (p. 3, 12) |

No other documentation was found. Column meanings shared with deped_enrollment are cited from its [data dictionary](../deped_enrollment/data_dictionary.md).

## Coverage

| Field | Value |
|---|---|
| Geographic coverage | Philippines, plus 33 Philippine Schools Overseas (PSO) |
| Geographic level | School, with PSGC codes and names down to barangay, and coordinates |
| Time coverage | SY 2023-24 only |
| Time basis | School year (enrollment as of 2024-01-31). PSGC codes and coordinates have later reference dates: Q4 2024 and 2025-07-07 |
| Update frequency | Unknown |
| Population covered | All sectors: Public 47,831, Private 12,207, SUC/LUC 204, PSO 33 |

## Structure

| Field | Value |
|---|---|
| Apparent grain | One row per school (SY 2023-24) |
| Candidate primary key | `BEIS School ID`: unique and 6 digits in the main block; one duplicate and one 7-digit ID in the 108 appended rows (profile O-3) |
| Candidate join keys | `BEIS School ID` to other DepEd school data (identical to deped_enrollment SY 2023-24, X-1). `(PSGC) BARANGAY` to PSA sources, after padding to 10 digits (O-5) |
| PSGC available? Which version? | **Yes**, region to barangay, for 59,504 of 60,275 schools. Stated as PSA Q4 2024; codes fit a late-2024 version (X-2, S-5) |
| Personally identifiable or sensitive fields | None found. Counts are aggregated per school. School coordinates are public facility locations |
| Provenance fields in the source | None. School year and reference dates come from the title rows |

Column-by-column descriptions, fill rates, and sample values: [data_dictionary.md](data_dictionary.md).

### Expected vs actual schema

| Column | Expected type | Actual type | Notes |
|---|---|---|---|
| `BEIS School ID` | 6-digit text | number cell | One 7-digit value (O-3) |
| `(PSGC) REGION` … `(PSGC) BARANGAY` | 10-digit text | number cell, or `#N/A` text | Leading zero lost on 36,014 rows (O-5); `#N/A` on 663-667 (O-6) |
| `NEW INCOME CLASSIFICATION (Based on DOF)` | one column | two columns with the same header (AA, AB) | O-8 |
| `Longitude`, `Latitude` | decimal | number cell, or `#N/A` text | 13,793 `#N/A` (O-10) |
| 58 enrollment counts | whole number | whole number | Same values as deped_enrollment (X-1) |

## Known quality problems

Summary only; evidence lives in [profile.md](profile.md).

- **Observed:** a report layout: 5 title rows, a 3-row header, 9 blank rows, and one row of `#N/A` only (O-1).
- **Observed:** 108 schools appended after the main block, with no PSGC, coordinates, or `URP`; they include one duplicated and one 7-digit school ID (O-2, O-3).
- **Observed:** PSGC codes lost their leading zero for regions I to IX (O-5); 667 schools have `#N/A` codes (O-6); 3 schools have a barangay outside their city or municipality (O-7).
- **Observed:** 23% of coordinates are `#N/A`, and 2,275 are over 100 km from their own city or municipality; these 2,275 include the 60 points at (0, 0) or outside the Philippines (O-10, O-11).
- **Observed:** two urban/rural columns that disagree, one undocumented (O-9); income class has a `1St` typo (O-8).
- **Suspected:** far-off coordinates are wrong locations (S-1); private-school coordinates come from somewhere other than NSBI (S-2).

## Limitations for analysis

- Adds no enrollment information beyond deped_enrollment SY 2023-24; only location columns are new.
- One school year only. Other years still need name matching to PSGC.
- Coordinates are not fit for distance or travel-time measures until checked against boundaries (S-1), and their absence is not random: NCR and private schools are missing most often (O-10).
- The three reference dates differ (enrollment January 2024, PSGC Q4 2024, coordinates July 2025). A school that moved or closed between them is placed by its later location.
