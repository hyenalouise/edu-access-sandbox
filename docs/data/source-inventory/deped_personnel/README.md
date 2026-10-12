# deped_personnel: DepEd school-level personnel

**Status:** profiled

## Identity

| Field | Value |
|---|---|
| Source name | Personnel Data Module (School-level) |
| Publisher / agency | Department of Education (DepEd), Policy and Planning Service |
| Source system (as stated by the publisher) | Basic Education Information System (BEIS). School Characteristics Technical Notes pp. 1, 12 |
| Source URL or acquisition method | [DepEd Machine-Ready Files](https://www.deped.gov.ph/machine-ready-files/), School Characteristics section; direct archive: [School Personnel in SY 2023-2024](https://www.deped.gov.ph/wp-content/uploads/School-Personnel-in-SY-2023-2024.zip) |
| Licensing or access restrictions | Public proactive-release download. No license or reuse terms are stated on the download page or in the reviewed documentation. **UNVERIFIED** |
| Owner (team member) | @mafelisilda |
| Date acquired | 2026-09-28 23:29 UTC |

## Files

| File | Format | Encoding | Size (bytes) | Row count | SHA-256 | Raw storage location |
|---|---|---|---|---|---|---|
| `School-Personnel-in-SY-2023-2024.zip` | ZIP | n/a | 782,129 | n/a | `9d1e5adfc33d67244f0d1a796f1b8b1930f5704eadf9f901008da68d7764a817` | Databricks volume `/Volumes/edu_access/00-source/raw/deped/`; checksum verified 2026-10-06 |
| ↳ `personnel_2023-24.csv` | CSV | UTF-8 without BOM, LF | 27,335,878 | 60,167 | `5d0dd4a244fc13401787d32f84f21ab5af295bf808f037a3f762efff7d6ed6c5` | Member of the ZIP in Databricks volume `/Volumes/edu_access/00-source/raw/deped/` |

## Publisher documentation

| Document | URL | SHA-256 | Sections relied on |
|---|---|---|---|
| `README.md` in the official ZIP | [Official archive](https://www.deped.gov.ph/wp-content/uploads/School-Personnel-in-SY-2023-2024.zip) | `e2aecfdb0a94d748e75d9d3b2846012185ba68533be0ce66b964bd7ae81afb93` | Module scope, data availability, all variable tables, naming convention, abbreviations, and blank-value note |

## Ingestion

| Item | Value |
|---|---|
| Contract | [`config/ingestion/deped_personnel.json`](../../../../config/ingestion/deped_personnel.json) |
| Bronze table | `` edu_access.`02-bronze`.deped_personnel_raw ``: publisher columns as text plus complete row provenance |
| Generated SQL | [`03_create_deped_personnel_raw.sql`](../../../../etl/02_bronze/03_create_deped_personnel_raw.sql) and [`90_validate_deped_personnel_raw.sql`](../../../../etl/02_bronze/90_validate_deped_personnel_raw.sql) |
| Raw storage | `/Volumes/edu_access/00-source/raw/deped/`; the ZIP checksum was verified after upload on 2026-10-06 |
| Local validation | Real approved ZIP loaded 60,167 rows and reconciled to 60,167 Bronze rows; an immediate rerun skipped the succeeded batch and inserted 0 rows. All 327 publisher columns remained text, all rows had complete provenance, and no pipeline duplicates were found |
| Databricks confirmation | Confirmed on `dev`: the real ZIP loaded 60,167 rows and skipped on rerun; later `edu_access_pipeline` run `696706629226090` at commit `15fcecbd` successfully ran the Personnel create, load, and separate gate tasks ([evidence](../../../../evidence/pipeline-runs/2026-10-09-deped-personnel-databricks-idempotency.md)) |

Bronze preserves all 327 publisher columns as text. It does not quarantine the O-9 review cases, recompute the O-8 principal totals, or convert blank personnel counts to zero. Those decisions belong to later layers and must remain traceable to the raw values.
| School Characteristics Technical Notes | [Official PDF](https://www.deped.gov.ph/wp-content/uploads/School-Characteristics-Technical-Notes.pdf) | `a0cb8728a4b175e6eba493fa0d06146c10db9064bc3c71807162fd9266f39cbc` | BEIS lineage and purpose (p. 1); collection tools (p. 2); annual frequency and responsible encoders (p. 3); teacher-learner ratio and annex handling (p. 8); personnel limitations (p. 12) |

## Coverage

| Field | Value |
|---|---|
| Geographic coverage | Philippines, inferred from the national DepEd school roster; no location fields are present in this file |
| Geographic level | School |
| Time coverage | SY 2023-24 only |
| Time basis | School year |
| Update frequency | Annual for BEIS data collection (Technical Notes p. 3); publication schedule and delivery timing remain unverified |
| Population covered | Personnel actually working in public schools, not authorized plantilla positions in DBM's PSIPOP/GMIS (Technical Notes p. 12). |

## Structure

| Field | Value |
|---|---|
| Apparent grain | One row per school for SY 2023-24 |
| Candidate primary key | `school_id` |
| Candidate join keys | `school_id` to `deped_enrollment` SY 2023-24; all 60,167 keys match one-to-one |
| PSGC available? Which version? | No. Geographic names and codes must come from an approved school-to-geography crosswalk, initially `deped_enrollment` through `school_id`; PSGC version remains dependent on that crosswalk |
| Personally identifiable or sensitive fields | No direct personal data |
| Provenance fields in the source | None. File name and accompanying documentation provide the only school-year and source context |

Column-by-column descriptions, fill rates, and sample values: [data_dictionary.md](data_dictionary.md).

### Expected vs actual schema

| Column group | Expected type | Actual type | Notes |
|---|---|---|---|
| School identity and offering flags, 6 columns | Integer identifier, strings, booleans | Valid text representations; complete | Values match `deped_enrollment` for every school |
| Nationally funded teaching and non-teaching positions, 137 columns | Nullable integers | Whole numbers or blank; no negatives | `shs_master_teacher_iv` is entirely blank |
| Locally funded teachers, 16 columns | Nullable integers | Whole numbers or blank; no negatives | Funding-source names are documented |
| Locally funded teaching-related and non-teaching personnel, 168 columns | Nullable integers | Whole numbers or blank; no negatives | All expected `LEVEL_ROLE_FUNDING-SOURCE` combinations are present |

## Known quality problems

Summary only; evidence lives in [profile.md](profile.md).

- **Publisher-documented and observed:** the release counts personnel actually working in public schools only (Technical Notes p. 12). All personnel measures are blank for 12,349 non-public schools and one public school.
- **Observed:** blanks are ambiguous between not applicable and unavailable, and the file uses both blank and zero. Blanks must not be converted to zero.
- **Observed:** `shs_master_teacher_iv` is entirely blank despite being included in the schema.
- **Observed:** 1,090 of 7,741 populated `shs_total_school_principal` values are one greater than the sum of the four documented grade components.
- **Observed:** a repeatable cross-source rule identifies 11 personnel fields across nine schools where a single personnel count exceeds the school's total same-year enrollment. Six are high-impact locally funded values; five are smaller mismatches involving schools with zero to three reported learners. The raw values are retained and their validity remains unconfirmed.
- **Observed:** the 500 SHS administrative aides reported at school `303950` do not exceed its 9,759 learners. This value remains a review candidate because it is unusually high within its field, but it is not automatically quarantined by the enrollment consistency rule.
- **Suspected:** the two exact values of 999 may be sentinel or entry values, but no reviewed publisher documentation confirms that interpretation.
- **Observed:** no negative or non-whole-number personnel values, duplicate keys, or duplicate rows were found.
- **Suspected:** zero may mean a confirmed absence while blank may combine not applicable and not reported, but the publisher documents only the ambiguity of blanks.

## Limitations for analysis

- Staffing coverage is usable only for public schools unless DepEd supplies personnel values for other sectors.
- Counts represent personnel actually working in public schools and are explicitly different from authorized or itemized personnel in DBM's PSIPOP/GMIS (Technical Notes p. 12). Do not interpret them as vacancies, approved positions, or plantilla inventory.
- The source cannot support individual-level workforce analysis, unique-person counts across positions or school levels, vacancies, authorized plantilla counts, employment status, sex-disaggregated analysis, or personnel movement.
- A person assigned across school levels or roles may be counted more than once. The documentation does not define deduplication rules.
- Locally funded fields describe funding categories but do not identify the funding jurisdiction or period. Do not infer the responsible province, city, or municipality without a verified crosswalk.
- Staffing ratios require enrollment from the same school year and careful treatment of schools with missing personnel counts or zero learners.
- A DepEd-aligned teacher-learner ratio is total enrollment divided by total teachers, after adding annex enrollment and teacher counts to the mother school (Technical Notes p. 8). A row-level ratio that leaves annexes separate is not the published methodology.
- No cross-year trend analysis is possible from the supplied delivery.
