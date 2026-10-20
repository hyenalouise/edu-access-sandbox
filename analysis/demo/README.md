# Demo

Walkthroughs that run the real pipeline code on made-up inputs, for presentations. No raw data, no credentials, no Databricks; they leave nothing behind.

| Script | Shows |
|---|---|
| `psa_ingestion_demo.py` | PSA Poverty Stat ingestion is incremental, idempotent, and traceable: loads, a skipped rerun, a new estimate year, a blocked changed file |

```bash
python analysis/demo/psa_ingestion_demo.py
```

Or run it cell by cell in VS Code (`# %%` cells). The same behavior is asserted, not just printed, in `tests/test_ingestion_psa.py`.
