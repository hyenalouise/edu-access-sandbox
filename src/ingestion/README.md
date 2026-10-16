# Ingestion

Code that checks a raw delivery and turns it into rows for Bronze. Raw files in `00-source` are read, never modified, and never extracted to disk. Six delivery formats: `zip_csv` (DepEd: a zip with one CSV), `xlsx_sheet` (PSA Poverty Stat: one workbook sheet with a merged header, banners, and a footer), `xlsx_table` (PSA PSGC: one workbook per publication quarter), `xlsx_report` (DepEd EMISD: one workbook per school year, title rows above the header), `xlsx_census` (PSA school-age population: one workbook per census with two sheets, each loaded), and `geojson_features` (COD-AB boundaries: one GeoJSON file, not zipped).

| Module | What it does |
|---|---|
| `contract.py` | Loads and validates `config/ingestion/<source_id>.json`: schema versions, approved deliveries, school year from the file names; for workbooks, layout, estimate years, and versions per logical dataset (`xlsx_sheet`) or per quarter (`xlsx_table`); for GeoJSON, the reference date and the single-file rule |
| `workbook.py` | `prepare_workbook`: opens an xlsx safely (zip checks, no DTDs), reads one sheet as stored text, builds the column names from the merged header, finds the body and footer, classifies unit and banner rows, and runs the layout, identifier, and known-issue checks |
| `xlsx_report.py` | Format `xlsx_report` (DepEd EMISD): a report-style sheet whose header is in the contract's `header_row`; the approved title cells checked exactly; the school year from the file name checked against a title cell; every row below the header kept with its kind (`unit`, `blank`, `no_identifier`); known publisher characteristics as WARNs at their profiled counts. Reuses `xlsx_table`'s safe reading and header matching |
| `xlsx_table.py` | Format `xlsx_table` (PSA PSGC): one sheet with a single header row, read through `workbook.open_sheet` as stored text; the quarter from the file name checked against the `Metadata` sheet; the exact header mapped to Bronze names; the checks (D-019) |
| `xlsx_census.py` | Format `xlsx_census` (PSA school-age population): every sheet of a census workbook through `workbook.open_sheet`; the bands and ages checked by position; each row's kind (title, header, place, sex rows, note, source, blank) from the layout, `wide` (2020) or `long` (2024); place rows, the 2024 Total/Male/Female blocks, whole-number counts; rows keyed by sheet too |
| `geojson_features.py` | `prepare_geojson_delivery`: reads a GeoJSON FeatureCollection one feature at a time, keeps every property as the file's text and the geometry as raw GeoJSON text, and runs the geometry, reference-date, and CRS checks; `identify_geojson_delivery` approves the file by its SHA-256 (D-026) |
| `formats.py` | What differs by format (discovery pattern, period, load type, checks), so `pipeline.py` has one flow |
| `archive.py` | SHA-256 of a file; opens a zip safely (no `..`, absolute paths, symbolic links, or encrypted members; size limit); finds the data file and documents by name |
| `reader.py` | Decodes with the encoding approved for those exact bytes, strictly; parses the CSV keeping every value as text and blanks as `''`; numbers data rows from 1 |
| `validate.py` | `prepare_delivery`: from an archive on disk to checked rows, or a refusal saying why. Row checks return PASS, WARN, or FAIL |
| `batch.py` | `batch_id` (same bytes, same id), and the action for a delivery: load, skip, retry, or rerun; and its load type: initial, incremental, backfill, or revision (by school year, or by estimate-year set for workbooks) |
| `bronze.py` | Bronze columns and DDL from the contract, provenance on every row, the insert-only MERGE, and reconciliation against the file |
| `control.py` | Writes to the control tables in `etl/01_control/` |
| `pipeline.py` | One run for one source, whatever its format: optionally set up its tables, discover, decide, validate, load, reconcile, record, then the Bronze gate. The job uses explicit setup and gate tasks (`--no-gate --no-setup`) |
| `store.py` | Where tables live: `DuckDBStore` locally and in tests, `SparkStore` on Databricks; both run the same `etl/` SQL (D-017) |
| `cli.py` | `ingest`, `status`, `columns`, `ddl`, `gate` from the command line, with exit codes |
| `revision.py` | `code_revision`: the commit that produced a row (from the job parameter on Databricks, from git locally, `UNSET` otherwise) |
| `errors.py` | `IngestionError(stage, code, message)` and the command-line exit codes |

How a new delivery is approved: [config/ingestion/README.md](../../config/ingestion/README.md).

## Running it locally

```bash
RAW_DATA_DIR=~/Projects/reached-hq/raw-data python -m src.ingestion.cli ingest --source deped_enrollment
python -m src.ingestion.cli status --source deped_enrollment
```

Tables go to `local_state/edu_access.duckdb` (git-ignored). To query them in the DuckDB CLI from the repository root, start `duckdb`, then run `ATTACH 'local_state/edu_access.duckdb' AS edu_access;` so the catalog-qualified table names resolve. Exit codes: 0 loaded or already loaded, 1 a delivery failed or was blocked or the Bronze gate failed, 2 configuration error, 3 environment error. On Databricks the `edu_access_pipeline` job runs `cli.py` with `--backend spark --no-gate --no-setup` after the explicit setup tasks (see [docs/operations/ingestion.md](../../docs/operations/ingestion.md#running-on-databricks)).
