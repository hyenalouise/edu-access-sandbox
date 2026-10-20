# ETL

SQL for each pipeline stage. A stage number matches its folder and its Unity Catalog schema (see the [architecture overview](../docs/architecture/overview.md#pipeline-stages)).

| Folder | Stage | Schema |
|---|---|---|
| [`01_control/`](01_control/) | Pipeline runs, ingestion batches, data-quality results | `` edu_access.`01-control` `` |
| [`02_bronze/`](02_bronze/) | Source landed unchanged, plus origin fields | `` edu_access.`02-bronze` `` |
| [`03_silver/`](03_silver/) | Typed, standardized, deduplicated; quarantine | `` edu_access.`03-silver` `` |
| [`04_integration/`](04_integration/) | Matching across sources, e.g. to PSGC | `` edu_access.`04-integration` `` |
| [`05_gold/`](05_gold/) | Facts and dimensions for the business question | `` edu_access.`05-gold` `` |
| [`06_analytics/`](06_analytics/) | One dataset per business question | `` edu_access.`06-analytics` `` |

Files run in name order inside a stage: `NN_<verb>_<object>.sql`, then `90_validate_<object>.sql`.

Every layer is implemented and enabled in the `edu_access_pipeline` job
([`databricks.yml`](../databricks.yml)). Each stage README lists its files; the
name and grain of every table are in the
[ETL table registry](../docs/standards/tables.md).
