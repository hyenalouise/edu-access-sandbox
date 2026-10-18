# Evidence: the DepEd school-to-PSGC crosswalk reconciles from Bronze to Silver locally, row by row, and a rebuild gives the same rows

Issue #163 · local DuckDB (D-017) · first run 2026-10-16, rerun after review 2026-10-18, Manila time (UTC+8) · run by @maeveylain

## The claim

The Silver build and gate for `deped_enrollment_psgc` (D-049), run on the real SY 2023-24 Bronze batch, put every Bronze row of kind `unit` either in `deped_enrollment_psgc_clean` or in `deped_enrollment_psgc_quarantine`. Every clean row resolves to exactly one current Bronze row, and every value in it equals the value recomputed from that row, with no FAIL. Every profiled count the rules file states is met. A second build gives identical content.

Databricks: see [the dev runs](../pipeline-runs/2026-10-16-deped-enrollment-psgc-silver-databricks.md).

## What was run

- Code: branch `feat/163-silver-deped-enrollment-psgc` at `6852fbe01549deae29eccc14739a60a361de7a0a` (clean), after the PR #169 review, with `code_revision` set to that commit. The gate has 32 checks. (The first run, on 2026-10-16 at `0398ade`, had the 28 checks before review and the same row counts.)
- Data: a fresh copy of the local Bronze database from the [Bronze evidence](../pipeline-runs/2026-10-16-deped-enrollment-psgc-local-idempotency.md): batch `deped_enrollment_psgc__2023-24__746d69530d22`, workbook SHA-256 `746d6953…acd5`, 60,285 rows (60,275 `unit`, 9 `blank`, 1 `no_identifier`).
- The generated files, run in order by `DuckDBStore.run_file`, twice: `etl/03_silver/07_clean_deped_enrollment_psgc.sql`, then `etl/03_silver/90_validate_deped_enrollment_psgc_clean.sql`.

| | Run 1 | Run 2 |
|---|---|---|
| `run_id` | `00077788-598b-4b21-87d1-a541644b1e35` | `a229378a-331f-4923-9d9b-9485200255bd` |
| Build, gate | 3.0 s, 1.6 s | 1.6 s, 1.4 s |
| Checks | 31 PASS, 1 WARN (`quarantine_rate`), 0 FAIL | 31 PASS, 1 WARN, 0 FAIL |
| Clean / quarantine rows | 60,273 / 2 | 60,273 / 2 |
| SHA-256 of both tables' content, ordered by `school_id`, without `run_id` and `cleaned_at_utc` | `225f506a…5f2c` | `225f506a…5f2c` (identical) |

After run 2, the published tables hold only run 2's rows (one `run_id`), all stamped `6852fbe…7a0a`, from the one batch.

## Results

### 1. Reconciliation, row by row

| | Rows |
|---|---|
| Bronze, kind `unit` | 60,275 |
| Silver clean | 60,273 |
| Silver quarantine | 2: `1406363` `school_id_malformed` (Excel row 60181); `404520` `school_id_identical_copy` (row 60267; its first copy, row 60263, is in clean) |
| Bronze, other kinds (counted, not carried) | 10: 9 `blank`, 1 `no_identifier` |

`rows_resolve_to_current_bronze` 0: every clean and quarantine row points at exactly one current Bronze `unit` row through its batch, file SHA-256, and Excel row. `values_reconcile` 0: for every clean row, the codes, null reasons, Sulu flag, `barangay_outside_city`, coordinates, `coordinate_flag`, and published text equal the values recomputed from its Bronze row. `coordinates_reconcile` 0: `longitude_published` and `latitude_published` equal the Bronze text exactly, and each DOUBLE equals the cast of that text.

### 2. Every rule, against its profiled count

| Check (gate) | Rules file | Silver |
|---|---|---|
| Barangay codes padded from 9 digits | 36,010 | 36,010 |
| City null, `source_na` / `not_in_workbook` | 663 / 106 | 663 / 106 |
| Barangay null, `source_na` / `not_in_workbook` | 667 / 106 | 667 / 106 |
| Sulu recoded (`19066…` → `09066…`, region `1900000000` → `0900000000`) | 467 | 467 |
| `barangay_outside_city` | 3 | 3 |
| `coordinate_flag` missing / zero / outside the Philippines | 13,899 / 6 / 54 | 13,899 / 6 / 54 (46,314 not flagged) |

**How the coordinate counts relate to the profile and #163:**

- Bronze has 13,901 school rows with a missing coordinate (13,793 `#N/A` and 108 blank, profile O-10). 2 of them are the quarantined rows (Excel rows 60181 and 60267), so 13,899 clean rows are `missing`. No coordinate is dropped.
- The profile's 60 points outside the Philippines box include the 6 at (0, 0). Silver flags those 6 as `zero` and the other 54 as `outside_philippines`.

All 16 FAIL checks are 0: the current batch is present, rows reconcile and resolve to Bronze, values and coordinates reconcile, `school_id` is unique and 6 digits, every code is 10 digits, there is no unrecognized code, region, province, or coordinate text, null reasons match the codes, region and province are null exactly with the city, coordinates come in pairs, lineage is complete, and all rows are from this run. `quarantine_rate` is WARN (2 rows; FAIL only above 1% of 60,275).

### 3. Coordinates: the published text beside the number

43,136 of the clean rows' coordinate values (longitude and latitude together) have published text that differs from the DOUBLE's text. These are Excel's float digits: `120.80636699999999` reads as `120.806367`. `longitude_published` and `latitude_published` keep the text exactly, and `coordinates_reconcile` ties both to Bronze.

### 4. Outside the gate: the codes against PSGC 2Q 2026

Not a Silver check (the match is Integration's, #44), but it tests the padding and the recode. Of the clean rows, every non-null code exists in `PSGC-2Q-2026-Publication-Datafile.xlsx` (psa_psgc) at all four levels: 59,504 region, 59,504 province, 59,504 city or municipality, and 59,500 barangay codes.

## Not checked here

- Databricks: see [the dev runs](../pipeline-runs/2026-10-16-deped-enrollment-psgc-silver-databricks.md).
