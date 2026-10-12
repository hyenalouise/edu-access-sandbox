# 03 Silver

Typed, standardized, and validated data at the source's own grain, with a quarantine for rows that cannot be trusted. Design, rules, counts, and runbook: [docs/operations/silver.md](../../docs/operations/silver.md).

| File | What it does |
|---|---|
| `NN_clean_<source>.sql` | Job task: rebuilds the source's two candidate tables (`<table>_candidate`, `<quarantine>_candidate`) from the Bronze rows of `` `01-control`.current_batches `` only, on every run. `NN` matches the source order in `config/tables.yml`. It keeps one run stamp in session variables (`:run_id`, `:code_revision`, one timestamp), records the run as `running` in `pipeline_runs`, classifies every row in a temporary view (cleaned values and quarantine reasons), then runs two `CREATE OR REPLACE TABLE ... AS SELECT`, each commented as an unpublished build not to read and handed to `reached-hq`. It never writes the Silver tables |
| `90_validate_<table>.sql` | Job task after the build, on the candidate tables: reconciliation with Bronze per school year, keys, ranges, NULLs, labels, lineage, quarantine rate, and a record of each rule's affected rows. Writes to `data_quality_results` (`layer = 'silver'`). On any FAIL it records the run `failed` and fails the task before publishing; otherwise it copies the candidates to the Silver tables (quarantine, then clean) and records the run `succeeded` (D-025). Reads `:run_id` and `:code_revision` |

Both files are generated from the Bronze contract (`config/ingestion/<source_id>.json`) and the reviewed Silver mapping (`config/mappings/<source_id>.json`); a test fails if they differ:

```bash
python -m src.silver.cli sql --source deped_enrollment > etl/03_silver/01_clean_deped_enrollment.sql
```

```bash
python -m src.silver.cli gate --source deped_enrollment > etl/03_silver/90_validate_deped_enrollment_clean.sql
```

On Windows, set `PYTHONUTF8=1` first (in PowerShell, `$env:PYTHONUTF8 = "1"`), or the files are written in cp1252 and the `Ñ` repair breaks the build.

Implemented: `deped_enrollment` → `deped_enrollment_clean`, `deped_enrollment_quarantine` ([data dictionary](../../docs/data/silver/deped-enrollment-clean.md)); `psa_poverty_stat` → `psa_poverty_stat_clean`, `psa_poverty_stat_quarantine`, one row per unit and estimate year, checked per batch and estimate year ([data dictionary](../../docs/data/silver/psa-poverty-stat-clean.md), D-034; regenerate with `--source psa_poverty_stat`); `deped_facilities` → `deped_facilities_clean`, `deped_facilities_quarantine` ([data dictionary](../../docs/data/silver/deped-facilities-clean.md), D-038; regenerate with `--source deped_facilities`); `deped_personnel` → `deped_personnel_clean`, `deped_personnel_quarantine`, one row per school and school year with typed personnel measures ([data dictionary](../../docs/data/silver/deped-personnel-clean.md), D-041; regenerate with `--source deped_personnel`); `psa_psgc` → `psa_psgc_clean`, `psa_psgc_quarantine`, one row per PSGC code per quarter with derived parent codes ([data dictionary](../../docs/data/silver/psa-psgc-clean.md), D-035; regenerate with `--source psa_psgc`); `hdx_boundaries` → `hdx_adm3_clean`, `hdx_adm3_quarantine`, one row per ADM3 unit, geometry kept as published text ([data dictionary](../../docs/data/silver/hdx-adm3-clean.md), D-040; regenerate with `--source hdx_boundaries`). Final names for the other sources are in the [ETL table registry](../../docs/standards/tables.md).

The SQL uses only what Databricks and DuckDB share; `src/ingestion/store.py` translates `regexp_like` and `regexp_replace` for DuckDB. Files follow `NN_<verb>_<object>.sql`, with checks in `90_validate_<object>.sql` (see [File naming and layout](../../docs/architecture/overview.md#file-naming-and-layout)).

Personnel is implemented by `03_clean_deped_personnel.sql` and `90_validate_deped_personnel_clean.sql`. It keeps one typed row per school and school year, records rule counts, and publishes only after reconciliation and lineage checks pass.
