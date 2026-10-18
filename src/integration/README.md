# Integration

Code that writes each mapping table's build and gate SQL from a reviewed rules file in `config/integration/`. The SQL is committed under `etl/04_integration/` and runs as two SQL tasks of the job.

| Module | What it does |
|---|---|
| `hdx_adm3_psgc.py` | HDX ADM3 → PSGC crosswalk (`hdx_adm3_psgc_map`, #93, D-052): rules in #74's order, overrides, the build and the gate. `python -m src.integration.hdx_adm3_psgc sql\|gate` |
