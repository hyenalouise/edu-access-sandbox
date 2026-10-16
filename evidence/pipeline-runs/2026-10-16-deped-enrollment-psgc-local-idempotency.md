# Evidence: the real EMISD workbook loads into Bronze locally once, and a second run inserts nothing

Issue #152 · local DuckDB (D-017) · 2026-10-16, Manila time (UTC+8) · run by @maeveylain

## The claim

The DepEd EMISD workbook `SY 2023-2024 School Level Data on Enrollment with PSGC, Longitude and Latitude.xlsx` loads through the shared pipeline (format `xlsx_report`, contract `config/ingestion/deped_enrollment_psgc.json`) into `deped_enrollment_psgc_raw` with every row of sheet `DB` below the header, every value as stored, each row's kind, and complete provenance. Its counts equal the source card and the profile. Running the same ingestion again skips the workbook and inserts nothing.

**Not claimed:** anything about Databricks. The workbook is not yet in the raw volume (#10), and the `dev` confirmation run has not been done.

## What was run

Code: branch `feat/152-bronze-deped-enrollment-psgc` at commit `d80b00ce4b3b8f6029648deff8a0d7e8dbd86ea6` (clean, so `code_revision` is that commit). Python 3.14, DuckDB 1.4.5.

The workbook: `$RAW_DATA_DIR/deped/original/SY 2023-2024 School Level Data on Enrollment with PSGC, Longitude and Latitude.xlsx`, SHA-256 `746d69530d228d2324590be10abbe6d75a94176c1745ef74335a4d6db550acd5`, equal to the [source card](../../docs/data/source-inventory/deped_enrollment_psgc/README.md#files). The file was only read.

A fresh database outside the repository, so no earlier local tables were involved. The command was run twice from Git Bash, with `RAW_DATA_DIR` set to the raw-data root:

```bash
python -m src.ingestion.cli ingest --source deped_enrollment_psgc --db <scratch>/emisd.duckdb
```

| | Run 1 | Run 2 |
|---|---|---|
| `run_id` | `a309b166-709a-44cc-b62b-62542b2740e1` | `ee0b2f4f-bc1d-4a24-af6e-7341389c04b4` |
| Started (UTC) | 2026-10-15 19:08:52 | 2026-10-15 19:10:52 |
| Batch | `deped_enrollment_psgc__2023-24__746d69530d22` | same |
| Action, outcome | `load`, `initial`, `succeeded` | `skip`, `skipped` ("already loaded; same SHA-256") |
| Rows inserted | **60,285** | **0** |
| Pipeline time (`duration_seconds`) | 115.5 s | 0.3 s |
| Exit code | 0 | 0 |

## Results

### 1. Bronze against the source card and the profile

| Check | Card / profile | Bronze |
|---|---|---|
| Rows below the header (A1:CJ60293) | 60,285 (card) | 60,285, Excel rows 9 to 60,293, all distinct |
| `unit` / `blank` / `no_identifier` rows | 60,275 / 9 / 1 (card; profile O-1, O-2) | 60,275 / 9 / 1 |
| Distinct school IDs on `unit` rows; IDs not 6 digits | 60,274; 1 (O-3) | 60,274; 1 |
| Learners, summed over the 58 count columns of `unit` rows | 27,084,335 (O-4) | 27,084,335 |
| `psgc_barangay` 9 digits / `#N/A` / blank | 36,010 / 667 / 108 (O-5, O-6, O-2) | 36,010 / 667 / 108 (not padded) |
| `longitude` = `#N/A`; `income_class` = `1St`; `urban_rural` = `-` | 13,793; 89; 80 (O-10, O-8, O-9) | 13,793; 89; 80 |
| Row 9 coordinates | stored binary floats (O-10) | `120.80636699999999`, `18.523045` (not rounded) |
| Blank rows | `''` in every column | 0 blank rows with a value or a NULL school ID |

### 2. Identity and provenance

- 0 rows with a NULL in any of the 16 provenance columns.
- One value each: `school_year` `2023-24`, `source_sheet` `DB`, `schema_version` `v1`, `delivery_version` 1, `code_revision` `d80b00ce…6ea6`, `source_url` "Email request to DepEd Planning Service, EMISD", `source_system` "Learner Information System (LIS); coordinates from NSBI".
- `ingestion_batches`: one row, `succeeded`, `expected_rows` = `source_rows` = 60,285.

### 3. Checks

39 results in `data_quality_results`, all PASS: the batch checks of run 1 (shape, row kinds, the profiled characteristics at their counts, and the post-load reconciliation by row kind), and the 4 Bronze gate checks of each run (`approved_deliveries_present`, `no_pipeline_duplicates`, `rows_have_a_known_batch`, `succeeded_batches_reconcile`). 0 WARN, 0 FAIL.

## Not checked here

- The Databricks `dev` run (Spark backend, the Volume path, the SQL warehouse gate). To be recorded after the raw upload under #10.
- Silver: not built (#137).
