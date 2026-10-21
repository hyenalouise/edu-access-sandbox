# `deped_psgc_coordinates_clean`

Generated from the reviewed contract and mapping (`config/mappings/deped_psgc_coordinates.json`):
`python -m src.silver.cli dictionary --source deped_psgc_coordinates`. Do not edit by hand.

Each public school's location from the public-only DepEd workbook (#217): its PSGC codes and its published coordinates, one row per school for SY 2023-24. It is not an enrollment table: the workbook's counts equal `deped_enrollment`, so enrollment comes only from `deped_enrollment_clean`. Only Bronze rows of kind `unit` are read. Scope: `school_year` in `2023-24` (else `school_year_out_of_scope`); `sector` in `Public` (else `sector_not_public`). Licensing is unverified (source card).

The coordinates are each school's own published point from the National School Building Inventory, not an administrative-area centre: of the 47,080 unflagged points, only 126 pairs are shared by more than one school (254 schools), and 40,046 lie within 10 km of the median point of their own city or municipality (profile O-6). They are kept and flagged, never corrected, geocoded, or inferred.

| Column | Type | Meaning |
|---|---|---|
| `school_year` | `STRING` | School year of the approved Bronze batch; `2023-24` only (scope) |
| `school_id` | `STRING` | Six-digit DepEd school ID, as published (leading zeros kept); one row per school and school year |
| `psgc_region` | `STRING` | The workbook's region PSGC code for the school, left-padded to 10 digits; Sulu recoded to 2Q 2026 (see `psgc_recoded`). `NULL` when the workbook has none |
| `psgc_province` | `STRING` | The workbook's province PSGC code for the school, left-padded to 10 digits; Sulu recoded to 2Q 2026 (see `psgc_recoded`). `NULL` when the workbook has none |
| `psgc_city_municipality` | `STRING` | The workbook's city or municipality PSGC code for the school, left-padded to 10 digits; Sulu recoded to 2Q 2026 (see `psgc_recoded`). `NULL` when the workbook has none |
| `psgc_barangay` | `STRING` | The workbook's barangay PSGC code for the school, left-padded to 10 digits; Sulu recoded to 2Q 2026 (see `psgc_recoded`). `NULL` when the workbook has none |
| `psgc_recoded` | `BOOLEAN` | `TRUE` when the province is Sulu's Q4 2024 code (`19066…`): each code that starts with `19066` became `09066…`, and region `1900000000` became `0900000000`, so the code exists in the master PSGC 2Q 2026 (D-049, D-012) |
| `psgc_null_reason` | `STRING` | Why a code in the row is `NULL`: `source_na` (`#N/A` in the workbook) or `not_in_workbook` (blank). `NULL` when every code is present. Region, province and city are `NULL` together; the barangay may also be `NULL` alone, for the same reason (the gate fails if the reasons ever differ) |
| `barangay_outside_city` | `BOOLEAN` | The barangay code's first 7 digits (region, province, city or municipality) differ from the city or municipality code, which breaks the PSGC hierarchy. Flagged, not corrected: which code is wrong is unknown |
| `longitude`, `latitude` | `DOUBLE` | The school's published point as a number (NSBI, as of 2025-07-07, workbook note above column AC). `NULL` for `#N/A` or blank, with `coordinate_flag` `missing`; the exact text stays in Bronze. Not corrected |
| `coordinate_flag` | `STRING` | `missing`, `zero` (0, 0), `outside_philippines` (outside lon 116-127, lat 4-21.5), or `NULL`. A `NULL` flag is not proof of the right place: 260 schools are over 100 km from their own city or municipality (profile O-6, S-1) |
| `batch_id` | `STRING` | Bronze lineage |
| `delivery_version` | `INT` | Bronze lineage |
| `schema_version` | `STRING` | Bronze lineage |
| `source_sha256` | `STRING` | Bronze lineage |
| `source_row_number` | `BIGINT` | Bronze lineage |
| `run_id`, `cleaned_at_utc`, `code_revision` | `STRING`, `TIMESTAMP`, `STRING` | The Silver run that built the row |

## Not carried from Bronze

Every Bronze column stays in `deped_psgc_coordinates_raw`. These are not carried, because another Silver table already holds them for the same schools, or nothing downstream uses them (checked 2026-10-21, school by school):

| Bronze columns | Why Silver does not carry them |
|---|---|
| 58 enrollment counts (`k_male` … `g12_arts_female`) | Equal to `deped_enrollment` SY 2023-24 for all 47,818 schools (0 differences); enrollment comes only from `deped_enrollment_clean` |
| `school_name`, `region`, `division`, `district`, `province`, `municipality`, `legislative_district`, `barangay`, `street_address` | The same values as `deped_enrollment` for the same schools, apart from spacing, case, quote marks, and `-` or `n/a` where the CSV is blank; `deped_enrollment_clean` cleans them |
| `sector` | `Public` on every row; checked here by the scope rule, then not carried |
| `school_subclassification`, `school_type` | Relabels of `school_management` and `annex_status` in `deped_enrollment` (`DepED Managed` = `DepEd`, `School with no Annexes` = `Standalone School`, …) |
| `modified_coc`, `curricular_offering_classification` | `modified_coc` maps one to one to `offers_es`, `offers_jhs`, `offers_shs` in `deped_enrollment` for every school; each of the 14 `curricular_offering_classification` labels rolls up to one `modified_coc` (0 exceptions), and its finer detail (e.g. Kindergarten offered) stays in Bronze |
| `psgc_region_name`, `psgc_province_name`, `psgc_city_municipality_name`, `psgc_barangay_name` | Names come from `psa_psgc` through the code |
| `urban_rural`, `income_class`, `income_class_long` | PSA and DOF classifications, carried by `psa_psgc` and Gold's geography dimensions through the code |
| `urp`, `implementing_unit` | Undocumented or unused by AP1 to AP4, and in no other source; kept in Bronze if they are ever needed |

## Quarantine

`deped_psgc_coordinates_quarantine` keeps each school row Silver does not carry, with its reasons and Bronze lineage:

- `school_id_malformed`: not 6 digits.
- `school_id_identical_copy`: a repeated `school_id` whose rows are identical in every published column; the first copy (lowest Excel row) stays in Silver.
- `school_id_duplicated`: a repeated `school_id` whose rows differ; every copy is quarantined.
- `school_year_out_of_scope`: `school_year` is missing or not `2023-24`.
- `sector_not_public`: `sector` is missing or not `Public`.

Above 1% of the Bronze unit rows in quarantine fails the gate.

## Profiled counts

The gate records each count: PASS at the profiled value, WARN when it changes, never FAIL.

| Check | Profiled |
|---|---|
| `bronze_unit_rows` | 47,818 |
| `bronze_other_rows` | 0 |
| `barangay_codes_padded` | 28,811 |
| `city_source_na` | 204 |
| `city_not_in_workbook` | 0 |
| `barangay_source_na` | 204 |
| `barangay_not_in_workbook` | 0 |
| `recoded` | 446 |
| `barangay_outside_city` | 2 |
| `coordinate_missing` | 679 |
| `coordinate_zero` | 5 |
| `coordinate_outside_philippines` | 54 |
| `quarantine_school_id_malformed` | 0 |
| `quarantine_school_id_duplicated` | 0 |
| `quarantine_school_id_identical_copy` | 0 |
| `quarantine_school_year_out_of_scope` | 0 |
| `quarantine_sector_not_public` | 0 |
