# Tests

Run the complete local suite from the repository root:

```bash
python -m pytest tests -q
```

| Location | Purpose |
|---|---|
| `factories/` | Python builders that create deterministic, made-up inputs in temporary directories |
| `data/` | Small static, made-up files when a factory is not practical |
| `test_repo_policy.py` | Data, secret, environment, and file-size rules |
| `test_documentation_structure.py` | Required indexes, retired paths, and local Markdown links |
| `test_naming.py` | Naming configuration and ETL path conventions |
| `test_ingestion_*.py` | Delivery validation, loading, rerun, and source-specific behavior |
| `test_silver.py` | DepEd enrollment Silver: cleaning rules, quarantine, the gate, the run record, revisions, and the generated SQL |
| `test_silver_facilities.py` | DepEd facilities Silver on made-up deliveries with matching enrollment: typed counts and yes/no columns, blanks kept NULL, enrollment's labels, overseas, public-scope and missing-classroom flags, per-group maximums, quarantine, the enrollment reference, scope warnings, every gate check, revisions, publishing, and the rules file |
| `test_silver_psa.py` | PSA Poverty Stat Silver on made-up workbooks: unpivot, ID padding, region banners, NULL and `no_estimate`, full-precision numbers, statistical flags, quarantine, every gate check, revisions and new years, repeated rebuilds, the run record, and the generated files |
| `test_fan_in.py` | The source-lane fan-in: the committed `90_validate_control.sql` equals what `src/job/fan_in.py` generates, it checks exactly the Silver lanes switched on, and the generator refuses a fan-in that misses or adds a lane |
| `test_silver_hdx.py` | HDX ADM3 Silver: exact typing, geometry checks (DuckDB spatial), quarantine, flags, the gate, and the generated files |
| `test_bundle.py`, `test_databricks_runtime.py` | The job's commit tracking and task order, and the Databricks runtime differences imitated locally |

Tests must never depend on real source rows or credentials.
