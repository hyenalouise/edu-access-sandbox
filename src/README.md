# Python source

Reusable application code lives under `src/`.

| Folder | Purpose |
|---|---|
| `ingestion/` | Validate approved deliveries, track batches, and load source-preserving Bronze rows |
| `silver/` | Generate each source's Silver build and gate SQL, and its data dictionary, from its reviewed mapping |
| `integration/` | Generate each mapping table's build and gate SQL from its reviewed rules file (`config/integration/`) |
| `profiling/` | Helpers shared by programs under `analysis/` |
| `dashboard/` | Generate the AI/BI dashboards under `dashboards/` from reviewed config |
| `job/` | Run the Databricks job's tasks from `databricks.yml` locally, in order, on DuckDB |

Source-specific research stays in `analysis/`; relational production
transformations stay in `etl/`.
