# `deped_enrollment_psgc_clean`

Generated from the reviewed contract and mapping (`config/mappings/deped_enrollment_psgc.json`):
`python -m src.silver.cli dictionary --source deped_enrollment_psgc`. Do not edit by hand.

DepEd's own PSGC code per school, from the EMISD workbook, for Integration to match DepEd schools by code first (D-049, #44). It is a crosswalk, not an enrollment table: enrollment counts come only from `deped_enrollment_clean`. Only Bronze rows of kind `unit` are read. Licensing is unverified: published outputs use the codes only to place schools in their city or municipality (D-049).

| Column | Type | Meaning |
|---|---|---|
| `school_year` | `STRING` | School year of the approved Bronze batch (`2023-24`) |
| `school_id` | `STRING` | Six-digit DepEd school ID; one row per school and school year |
| `psgc_region` | `STRING` | DepEd's region PSGC code for the school, left-padded to 10 digits; Sulu recoded to 2Q 2026 (see `psgc_recoded`). `NULL` when the workbook has none |
| `psgc_province` | `STRING` | DepEd's province PSGC code for the school, left-padded to 10 digits; Sulu recoded to 2Q 2026 (see `psgc_recoded`). `NULL` when the workbook has none |
| `psgc_city_municipality` | `STRING` | DepEd's city or municipality PSGC code for the school, left-padded to 10 digits; Sulu recoded to 2Q 2026 (see `psgc_recoded`). `NULL` when the workbook has none |
| `psgc_barangay` | `STRING` | DepEd's barangay PSGC code for the school, left-padded to 10 digits; Sulu recoded to 2Q 2026 (see `psgc_recoded`). `NULL` when the workbook has none |
| `psgc_recoded` | `BOOLEAN` | `TRUE` when the province is Sulu's Q4 2024 code (`19066…`): each code that starts with `19066` became `09066…`, and region `1900000000` became `0900000000` |
| `psgc_city_municipality_null_reason` | `STRING` | Why region, province, and city/municipality are `NULL`: `source_na` (`#N/A` in the workbook) or `not_in_workbook` (no value). `NULL` when the code is present |
| `psgc_barangay_null_reason` | `STRING` | Why the barangay code is `NULL`, as above |
| `barangay_outside_city` | `BOOLEAN` | The barangay code's first 7 digits differ from the city or municipality code (profile O-7). Kept as published |
| `longitude`, `latitude` | `DOUBLE` | The published value as a number (NSBI, 2025-07-07), for maps and distances. `NULL` for `#N/A` or blank. Not corrected; Excel's float noise (e.g. `120.79600000000001`) reads as `120.796` |
| `longitude_published`, `latitude_published` | `STRING` | The exact Bronze text, including `#N/A` and blank. The gate fails unless it equals Bronze and the `DOUBLE` equals its cast |
| `coordinate_flag` | `STRING` | `missing`, `zero` (0, 0), `outside_philippines`, or `NULL`. Coordinates feed no Gold measure until the boundary test (S-1) |
| `school_name` | `STRING` | Published `school_name`, unchanged |
| `region` | `STRING` | Published `region`, unchanged |
| `division` | `STRING` | Published `division`, unchanged |
| `district` | `STRING` | Published `district`, unchanged |
| `province` | `STRING` | Published `province`, unchanged |
| `municipality` | `STRING` | Published `municipality`, unchanged |
| `legislative_district` | `STRING` | Published `legislative_district`, unchanged |
| `barangay` | `STRING` | Published `barangay`, unchanged |
| `sector` | `STRING` | Published `sector`, unchanged |
| `urp` | `STRING` | Published `urp`, unchanged |
| `psgc_region_name` | `STRING` | Published `psgc_region_name` (Q4 2024 PSGC names; Sulu's still say BARMM after the code recode), unchanged. For PSGC names, use psa_psgc through the code |
| `psgc_province_name` | `STRING` | Published `psgc_province_name` (Q4 2024 PSGC names; Sulu's still say BARMM after the code recode), unchanged. For PSGC names, use psa_psgc through the code |
| `psgc_city_municipality_name` | `STRING` | Published `psgc_city_municipality_name` (Q4 2024 PSGC names; Sulu's still say BARMM after the code recode), unchanged. For PSGC names, use psa_psgc through the code |
| `psgc_barangay_name` | `STRING` | Published `psgc_barangay_name` (Q4 2024 PSGC names; Sulu's still say BARMM after the code recode), unchanged. For PSGC names, use psa_psgc through the code |
| `batch_id` | `STRING` | Bronze lineage |
| `delivery_version` | `INT` | Bronze lineage |
| `schema_version` | `STRING` | Bronze lineage |
| `source_sha256` | `STRING` | Bronze lineage |
| `source_row_number` | `BIGINT` | Bronze lineage |
| `run_id`, `cleaned_at_utc`, `code_revision` | `STRING`, `TIMESTAMP`, `STRING` | The Silver run that built the row |

## Quarantine

`deped_enrollment_psgc_quarantine` keeps each school row Silver does not carry, with its reasons and Bronze lineage:

- `school_id_malformed`: not 6 digits.
- `school_id_identical_copy`: a repeated `school_id` whose rows are identical in every published column; the first copy (lowest Excel row) stays in Silver.
- `school_id_duplicated`: a repeated `school_id` whose rows differ; every copy is quarantined.

## Profiled counts

The gate records each count: PASS at the profiled value, WARN when it changes, never FAIL.

| Check | Profiled |
|---|---|
| `bronze_unit_rows` | 60,275 |
| `bronze_other_rows` | 10 |
| `barangay_codes_padded` | 36,010 |
| `city_source_na` | 663 |
| `city_not_in_workbook` | 106 |
| `barangay_source_na` | 667 |
| `barangay_not_in_workbook` | 106 |
| `recoded` | 467 |
| `barangay_outside_city` | 3 |
| `coordinate_missing` | 13,899 |
| `coordinate_zero` | 6 |
| `coordinate_outside_philippines` | 54 |
| `quarantine_school_id_malformed` | 1 |
| `quarantine_school_id_duplicated` | 0 |
| `quarantine_school_id_identical_copy` | 1 |
