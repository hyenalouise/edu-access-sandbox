# 02 Bronze

Each source landed unchanged, every column as text, plus provenance columns saying where each row came from.

| File | What it does |
|---|---|
| `NN_create_<table>.sql` | One table per logical source, including all delivery years. `NN` is the source order in `config/tables.yml`. Generated from `config/ingestion/<source_id>.json` once that source has an ingestion contract (`python -m src.ingestion.cli ddl --source <source_id>`); a test fails if it differs |
| `90_validate_<table>.sql` | Bronze gate, run after every load (in the job, as its own SQL task right after the load): no pipeline duplicates, every row has a known batch, every succeeded batch reconciles to its file. Writes to `data_quality_results` and fails on any FAIL. Reads `:run_id` and `:code_revision`. Generated the same way (`cli gate`) |

Implemented sources: `deped_enrollment`, `deped_facilities`, `psa_psgc` (an xlsx workbook per quarter; rows identified by the workbook's SHA-256 and the Excel row number, carrying `source_sheet`, `publication_period` and `publication_date`), `psa_poverty_stat` (an xlsx workbook; its rows are identified by the workbook's SHA-256 and the Excel row number, and carry `source_sheet` and `source_row_kind`; every row of the sheet is kept, including title, header and footer rows), `hdx_boundaries` (one GeoJSON file, table `hdx_adm3_raw`; rows are identified by the file's SHA-256 and the feature's position, and the geometry is kept as raw GeoJSON text), `deped_enrollment_psgc` (the DepEd EMISD workbook, format `xlsx_report`; rows are identified by the workbook's SHA-256 and the Excel row number, and carry `school_year`, `source_sheet` and `source_row_kind`; every row below the header is kept, including blank rows), `psa_school_age_population` (two census workbooks, format `xlsx_census`; both sheets of each are loaded, so rows are identified by the workbook's SHA-256, the sheet and the Excel row number, and carry `logical_dataset`, `census_year` and `source_row_kind`; every row of each sheet is kept, including title, header, note and source rows). Final names for these and the known sources still awaiting ingestion contracts are in the
[ETL table registry](../../docs/standards/tables.md).

Loading is Python (`src/ingestion/`), because the files arrive as zips with a declared encoding, as workbooks whose cells must be kept exactly as stored, or as one GeoJSON file with polygons of several megabytes. The rules:

- Values are kept exactly as received, as text. A blank stays `''`; a column that a year's file does not have is `NULL`. No trimming, relabeling, typing, or deduplication: that is Silver.
- A row is identified by `(source_sha256, source_row_number)`, and loaded with an insert-only MERGE, so loading a file again adds nothing (D-015). Rows the publisher repeated are all kept and flagged as WARN.
- Downstream reads only rows whose batch is in `` `01-control`.current_batches ``.

Files follow `NN_<verb>_<object>.sql`, with checks in `90_validate_<object>.sql` (see [File naming and layout](../../docs/architecture/overview.md#file-naming-and-layout)).
