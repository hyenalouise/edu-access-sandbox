# Silver

Code that writes each source's Silver SQL from reviewed configuration. The SQL itself is in `etl/03_silver/` and runs as two SQL tasks of the job (`databricks.yml`): the build, into candidate tables, then the gate, which publishes them only if every check passes. Design: [docs/operations/silver.md](../../docs/operations/silver.md).

| Module | What it does |
|---|---|
| `spec.py` | Loads the Bronze contract and the Silver mapping (`config/mappings/<source_id>.json`) and classifies every publisher column (identifier, free text, category, boolean, count); stops on any column or label it cannot place |
| `sql.py` | Generates the build SQL (`NN_clean_<source>.sql`) and the gate (`90_validate_<table>.sql`) from the spec |
| `dictionary.py` | Generates the Silver data dictionary (`docs/data/silver/`) from the spec |
| `psa_poverty_stat.py` | PSA Poverty Stat's own spec, build, gate, and dictionary: unpivots the wide workbook rows to one row per unit and estimate year (D-034). `gate_checks()` lists every check the gate writes |
| `deped_facilities.py` | DepEd facilities' own spec, build, gate, and dictionary: count groups with their own maximums, sixty facility yes/no columns, and public-scope and offered-level warnings (D-038). `gate_checks()` lists every check the gate writes |
| `generators.py` | Chooses a source's generator: the module named by `generator` in its rules file, or the DepEd enrollment modules above |
| `cli.py` | `sql`, `gate`, `dictionary`: print a generated file. Exit code 2 if the contract or mapping is invalid |

Run the job, Silver included, locally on DuckDB:

```bash
RAW_DATA_DIR=~/Projects/reached-hq/raw-data python -m src.job.local_run
```
