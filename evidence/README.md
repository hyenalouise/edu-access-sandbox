# Evidence

Records that prove a claim about pipeline behavior. Results contain counts and
identifiers only, never source records or bulk outputs.

| Folder | Contents |
|---|---|
| `pipeline-runs/` | Run-specific, human-readable execution and rerun evidence |
| `source-validation/` | Compact machine-readable source-gate results when implemented |
| `reconciliation/` | Source-to-layer count and measure reconciliation when implemented |

| Evidence | Claim | Issue |
|---|---|---|
| [2026-10-06-deped-enrollment-idempotency.md](pipeline-runs/2026-10-06-deped-enrollment-idempotency.md) | Loading DepEd enrollment into Bronze twice on Databricks inserts nothing the second time | #11 |
| [2026-10-06-deped-facilities-idempotency.md](pipeline-runs/2026-10-06-deped-facilities-idempotency.md) | DepEd facilities loads once from its own contract, a second run inserts nothing, and enrollment is untouched | #11 |
| [2026-10-07-deped-enrollment-bronze-to-silver.md](reconciliation/2026-10-07-deped-enrollment-bronze-to-silver.md) | Superseded by the 2026-10-09 record: the earlier skip-when-unchanged design of DepEd enrollment Silver, run locally on the real data | #85 |
| [2026-10-09-deped-personnel-databricks-idempotency.md](pipeline-runs/2026-10-09-deped-personnel-databricks-idempotency.md) | DepEd Personnel loads 60,167 rows once, skips unchanged input on rerun, and its create, load, and separate Bronze gate succeed in `edu_access_pipeline` | #81 |
| [2026-10-07-psa-poverty-stat-local-idempotency.md](pipeline-runs/2026-10-07-psa-poverty-stat-local-idempotency.md) | PSA Poverty Stat loads once, skips on rerun, loads new and older estimate years incrementally, blocks a changed file, and recovers from a crash (local: made-up workbooks, and the real workbook loaded then skipped; Databricks: skip runs only, in the 2026-10-08 `edu_access_pipeline` evidence) | #83 |
| [2026-10-08-pipeline-dag-databricks-idempotency.md](pipeline-runs/2026-10-08-pipeline-dag-databricks-idempotency.md) | The `edu_access_pipeline` DAG runs every delivered Bronze lane and gate on Databricks, a second run inserts nothing, and each load joins to its gate through `job_run_id` (local: the same DAG loads the real files, then skips them) | #47 |
| [2026-10-09-deped-enrollment-bronze-to-silver.md](reconciliation/2026-10-09-deped-enrollment-bronze-to-silver.md) | DepEd enrollment Silver, built locally by the job from the real Bronze data, reconciles with Bronze per school year (rows and learners), passes every gate check, and a second run rebuilds identical content | #85 |
| [2026-10-09-psa-poverty-stat-bronze-to-silver.md](reconciliation/2026-10-09-psa-poverty-stat-bronze-to-silver.md) | PSA Poverty Stat Silver, built locally from the real workbook's Bronze rows, reconciles per estimate year (1,612 each), matches every Bronze cell, passes every FAIL check (9 WARN: statistical flags), and a second run rebuilds identical content. Local only | #89 |
| [2026-10-09-deped-enrollment-silver.md](pipeline-runs/2026-10-09-deped-enrollment-silver.md) | DepEd enrollment Silver builds and passes its gate on Databricks `dev`, a second run rebuilds identical rows, and Bronze loads nothing new | #85 |
| [2026-10-09-silver-publish-after-gate.md](pipeline-runs/2026-10-09-silver-publish-after-gate.md) | DepEd enrollment Silver is published only after its gate passes: two Databricks `dev` runs publish the same rows as before, and a failing build (local, real data) leaves the last good one in place | #119 |
| [2026-10-09-hdx-adm3-silver-databricks.md](pipeline-runs/2026-10-09-hdx-adm3-silver-databricks.md) | HDX ADM3 Silver builds 1,642 rows and passes all 38 gate checks on Databricks `dev` in two runs; every geometry function in the generated SQL runs as written | #90 |
| [2026-10-11-deped-facilities-bronze-to-silver.md](reconciliation/2026-10-11-deped-facilities-bronze-to-silver.md) | DepEd facilities Silver, built locally by the job from the real SY 2023-24 Bronze, reconciles rows, counts, TRUE values, and blanks with Bronze, places every school in enrollment Silver, passes all 38 checks, and a second run rebuilds identical content; re-run at `1c2317b` and `02089c9` (the enrollment check moved to Integration) with the same content. Local only | #86 |
| [2026-10-11-deped-facilities-silver.md](pipeline-runs/2026-10-11-deped-facilities-silver.md) | DepEd facilities Silver builds and passes its gate on Databricks `dev`, twice at `6b2844d` (38 checks) and twice at `9197926` as a parallel lane (37 checks); every run rebuilds identical rows, and Bronze loads nothing new | #86 |
| [2026-10-11-source-lane-fan-in.md](pipeline-runs/2026-10-11-source-lane-fan-in.md) | The source-lane fan-in runs on Databricks `dev` after the Silver gates, writes one PASS per Silver lane switched on, stamped with the commit (enrollment and PSA Poverty Stat at `1962bce`; plus facilities at `3719301`, after #126; plus PSGC at `a405f70`, after #124; plus HDX at `7e4b2a5`, after #122), and the three maps depend only on it | #127 |
