# Evidence: DepEd enrollment SY 2020-21 loads into the existing Bronze and Silver lane, reconciles per school year, and reruns change nothing

Issue #170 (part of #43) · local run (DuckDB) only; nothing has run on Databricks · 2026-10-16 · checked by @hyenalouise

## The claim

SY 2020-21 is the fourth approved delivery of `deped_enrollment`. It loads into the existing `deped_enrollment_raw` table under schema `v1` through the existing tasks, with no new task, table, or schema version. Every current Bronze row of each of the four school years is in Silver clean or quarantine. Cleaning moves no learner: SY 2020-21 has 26,227,022, equal to the profile's O-3 and DepEd's published total (S-3). Every gate check passes. `Local Government` is kept as its own `school_management` value. The three earlier years' Silver rows are identical to the 2026-10-09 record. A second job run inserts no Bronze rows and rebuilds the same Silver content.

## What was run

Commit `98487d609e7e0d001da42d74fa5265df74cabc47` on `feat/deped-enrollment-2020-21-bronze` (stacked on the Silver branch with the `Local Government` mapping), clean worktree (`code_revision` has no `-dirty`). macOS 26.3.1, Python 3.12.14, DuckDB 1.4.5. Each run started on a new, empty database file in a scratch folder. `RAW_DATA_DIR` was `~/Projects/reached-hq/raw-data`; the four enrollment zips are in `deped/original/`. Before the run, the SY 2020-21 zip, CSV, and README were hashed and compared with the source card: `65c400aa…a241`, `5cef0e62…f1cb`, and `5eb05f7d…2a80`, all equal. The loader verified them again. The whole job ran twice, in the order of the Databricks DAG:

```bash
RAW_DATA_DIR=~/Projects/reached-hq/raw-data python -m src.job.local_run --db <scratch>/lane.duckdb
```

Both runs exited 0, and every enabled task of every lane `succeeded`.

| Step | Run 1 | Run 2 |
|---|---|---|
| `bronze_deped_enrollment` | SY 2020-21 `load initial` inserted 60,957; 2023-24, 2024-25, 2025-26 `load incremental` inserted 60,167, 60,129, 60,204 (10.7 s) | all four `skip`, inserted 0 (0.15 s) |
| `90_validate_deped_enrollment_raw` | 3 checks PASS | 3 checks PASS |
| `01_clean_deped_enrollment` | 241,457 clean, 0 quarantined (1.5 s) | rebuilt: 241,457 clean, 0 quarantined (1.7 s) |
| `90_validate_deped_enrollment_clean` | 153 checks PASS; run `succeeded` (1.6 s) | 153 checks PASS; run `succeeded` (1.5 s) |

On the fresh database SY 2020-21 loads first, so it is `initial` here. On Databricks, where the three later years are already loaded, it will be `backfill`. `tests/test_ingestion_pipeline.py::test_sy_2020_21_loads_as_a_v1_backfill_and_leaves_the_later_years_untouched` shows that case with made-up files.

## Results

### Bronze, per school year

| School year | Approved `row_count` | File rows | Bronze rows | Run 1 inserted | Run 2 inserted | Schema |
|---|---:|---:|---:|---:|---:|---|
| 2020-21 | 60,957 | 60,957 | 60,957 | 60,957 | 0 | v1 |
| 2023-24 | 60,167 | 60,167 | 60,167 | 60,167 | 0 | v1 |
| 2024-25 | 60,129 | 60,129 | 60,129 | 60,129 | 0 | v1 |
| 2025-26 | 60,204 | 60,204 | 60,204 | 60,204 | 0 | v2 |
| **All** | | | **241,457** | 241,457 | **0** | |

Each batch still has `attempt_count = 1`, and its `first_run_id` and `last_run_id` are both run 1. The attempts log shows `load` for each file in run 1 and `skip` with 0 rows in run 2.

Gate results by layer (PASS / WARN / FAIL):

| Results | Run 1 | Run 2 |
|---|---|---|
| Bronze, load task (batch checks and `approved_deliveries_present`) | 45 / 0 / 0 | 1 / 0 / 0 (skips write no batch checks) |
| Bronze gate (`no_pipeline_duplicates`, `rows_have_a_known_batch`, `succeeded_batches_reconcile`) | 3 / 0 / 0 | 3 / 0 / 0 |
| Silver gate | 153 / 0 / 0 | 153 / 0 / 0 |
| Control (`silver_lane_succeeded`, `source_fresh`) | 2 / 0 / 0 | 2 / 0 / 0 |

The Silver gate has 5 whole-table checks and 37 checks per school year, so 116 for three years became 153 for four.

### Silver, per school year (after run 2; run 1 identical)

| School year | Bronze current rows | Clean | Quarantined | Learners, Bronze | Learners, clean | `labels_mapped_school_management` |
|---|---:|---:|---:|---:|---:|---|
| 2020-21 | 60,957 | 60,957 | 0 | 26,227,022 | 26,227,022 | PASS (0 unmapped) |
| 2023-24 | 60,167 | 60,167 | 0 | 27,081,292 | 27,081,292 | PASS |
| 2024-25 | 60,129 | 60,129 | 0 | 26,400,182 | 26,400,182 | PASS |
| 2025-26 | 60,204 | 60,204 | 0 | 25,935,863 | 25,935,863 | PASS |
| **All** | 241,457 | 241,457 | 0 | 105,644,359 | 105,644,359 | |

The SY 2020-21 learner total equals profile O-3 and DepEd's 2021-09-23 release (profile S-3). The other three equal the 2026-10-09 record.

SY 2020-21 `school_management` in Silver: DepEd 47,252; Non-Sectarian 9,496; Sectarian 3,758; SUC 210; **Local Government 154**; LUC 37; PSO 33; DOST 13; International School 2; Other GA 2. The 154 Bronze rows still read `Local Government`.

SY 2020-21 rule and flag counts, as the gate recorded them (the other years are unchanged from [Silver, Cleaning rules](../../docs/operations/silver.md#cleaning-rules)):

| Rule or flag | SY 2020-21 |
|---|---:|
| `rule_whitespace_normalized` | 5 |
| `rule_characters_repaired` | 281 |
| `rule_blank_text_to_null` (street_address 5,782, barangay 84) | 5,859 |
| `rule_placeholder_to_null` | 0 |
| `rule_blank_counts_to_null` (the four `*_unique_*` columns, O-16) | 60,957 |
| `rule_absent_columns_null` (v2-only columns) | 60,957 |
| `rule_labels_standardized` | 0 |
| `flag_is_overseas` | 33 |
| `flag_enrollment_all_zero` | 439 |
| `flag_enrollment_no_counts` | 0 |
| `flag_barangay_possibly_truncated` | 25 |
| `flag_barangay_blank` | 84 |

Kept as published, as the profile describes them, and left for Integration or Analytics to disclose: 2,714 SY 2020-21 rows say `Region XII`, including the 191 schools that are `BARMM` from SY 2023-24 (O-10); the 2,517 school IDs absent from SY 2023-24 (O-12); the 439 zero-enrollment schools (S-1); historical place names; and the 33 PSO rows.

The verification query in [Silver, Running on Databricks](../../docs/operations/silver.md#running-on-databricks), updated in this branch for four deliveries, ran through the local store after run 2 with the commit above filled in. All 22 rows were `OK`.

### Content hashes (run stamps excluded)

The query from the [2026-10-09 record](2026-10-09-deped-enrollment-bronze-to-silver.md), in school year and row order: every column except the run stamp: `run_id`, `cleaned_at_utc`, and `code_revision` for Silver; `run_id`, `ingested_at_utc`, and `code_revision` for Bronze.

| Table | Rows | After run 1 | After run 2 |
|---|---:|---|---|
| `deped_enrollment_clean`, all four years | 241,457 | `caf188b7ec19d4be1f900332e17bcfdc` | `caf188b7ec19d4be1f900332e17bcfdc` |
| `deped_enrollment_clean`, SY 2020-21 only | 60,957 | `ddb817284d3a645ee7a599113b55bd5e` | same |
| `deped_enrollment_clean`, SY 2023-24 to 2025-26 | 180,500 | `311b445851533467fd7e669d3cf6e537` | same |
| `deped_enrollment_quarantine` | 0 | empty | empty |
| `deped_enrollment_raw` (Bronze) | 241,457 | `df759ca3119a5e0ed3ac676355de75c8` | `df759ca3119a5e0ed3ac676355de75c8` |

The three-year hash equals the 2026-10-09 value, so adding SY 2020-21 and the `Local Government` label changed no row of the earlier years. Two earlier runs at `260a178`, with the same code before the branch was split into its Silver and Bronze pull requests, gave the same counts, results, and Silver hashes.

## Why it holds

1. The Bronze DDL and gate are generated from the contract. Adding a delivery under an existing schema version leaves both files byte-identical (`tests/test_ingestion_pipeline.py::test_bronze_sql_matches_the_contract`).
2. The Silver build and gate are generated from the contract and mapping, with no school year in them. They read `current_batches`, so every approved year is processed. The only SQL change is one `WHEN 'Local Government'` branch and that label in the gate's accepted list (`etl/03_silver/01_clean_deped_enrollment.sql`, `90_validate_deped_enrollment_clean.sql`). Without it the gate fails on SY 2020-21: the new tests fail against the `main` SQL.
3. Skips and rebuilds: see the [2026-10-09 record](2026-10-09-deped-enrollment-bronze-to-silver.md#why-it-holds).

## Also shown by tests

`python -m pytest tests -q`: 768 passed. New for this delivery:

- `tests/test_ingestion_pipeline.py`: the contract's four deliveries match the source card's checksums and row counts, and `config/tables.yml` lists the same years; SY 2020-21 uses the 78-column `v1` header; a made-up SY 2020-21 file loads as a `v1` backfill after the three later years, leaving their Bronze rows and batches unchanged; per-year Bronze reconciliation; a rerun inserts nothing.
- `tests/test_silver.py`: `Local Government` stays its own value (not `DepEd` or `LUC`), and Bronze keeps it; across four years, clean + quarantine = Bronze per year, `rows_reconcile`, `learners_reconcile`, and `labels_mapped_school_management` pass per year, and a quarantined SY 2020-21 row WARNs only that year; the three later years' Silver rows do not change when SY 2020-21 is added; a rerun rebuilds the same content.

## What this does not prove

- Anything on Databricks. The zip is still in `raw/_holding/deped/2026-10-16/`, and no job has run with it. See [Awaiting authorization](#awaiting-authorization).
- Quarantine on real data: no real row is quarantined. It is shown only with made-up rows.
- That `Local Government` schools were managed differently from `DepEd` schools. The label is kept because DepEd published it, not because its meaning is confirmed (assumption, not checked with DepEd).

## Awaiting authorization

Following [ingestion.md, Runbook 1](../../docs/operations/ingestion.md#runbook): merge the contract pull request first, then move the file, then run the job from `main`. Moving the file into `raw/deped/` before the merge would make every run from `main` block it as `unregistered_delivery` and fail. The CLI has no `mv`, so the move is a copy, a checksum check, and then removing the holding folder:

```bash
databricks fs ls dbfs:/Volumes/edu_access/00-source/raw/_holding/deped/2026-10-16/ --profile reached-hq
databricks fs ls dbfs:/Volumes/edu_access/00-source/raw/deped/ --profile reached-hq
databricks fs mkdir dbfs:/Volumes/edu_access/00-source/raw/deped/2026-10-16 --profile reached-hq
databricks fs cp dbfs:/Volumes/edu_access/00-source/raw/_holding/deped/2026-10-16/Enrollment-in-SY-2020-2021.zip dbfs:/Volumes/edu_access/00-source/raw/deped/2026-10-16/ --profile reached-hq
databricks fs cp dbfs:/Volumes/edu_access/00-source/raw/_holding/deped/2026-10-16/SHA256SUMS.txt dbfs:/Volumes/edu_access/00-source/raw/deped/2026-10-16/ --profile reached-hq
databricks fs cp dbfs:/Volumes/edu_access/00-source/raw/_holding/deped/2026-10-16/RETRIEVED.txt dbfs:/Volumes/edu_access/00-source/raw/deped/2026-10-16/ --profile reached-hq
databricks fs cp dbfs:/Volumes/edu_access/00-source/raw/deped/2026-10-16/Enrollment-in-SY-2020-2021.zip <scratch>/check/ --profile reached-hq
shasum -a 256 <scratch>/check/Enrollment-in-SY-2020-2021.zip     # expect 65c400aa31ba63730b8f9a7b4d60ade91c6a29cdb34a3c6bf255e5fc9e91a241
databricks fs rm -r dbfs:/Volumes/edu_access/00-source/raw/_holding/deped/2026-10-16 --profile reached-hq
```

Then deploy and run from a clean checkout of `main`, after announcing the run and stopping other serverless compute:

```bash
databricks bundle validate --target dev --profile reached-hq
databricks bundle deploy --target dev --profile reached-hq
databricks bundle summary --target dev --profile reached-hq     # git_commit and code_revision = git rev-parse HEAD
databricks bundle run edu_access_pipeline --target dev --profile reached-hq
databricks bundle run edu_access_pipeline --target dev --profile reached-hq
```

Expected: run 1 loads SY 2020-21 as `backfill` with 60,957 rows, and the other three years `skip`; run 2 skips all four and inserts 0. Silver has 241,457 clean rows and 0 quarantined after both runs. Every row of the Silver verification query is `OK`. Record the results in `evidence/pipeline-runs/<date>-deped-enrollment-2020-21-databricks.md`.

## How to reproduce

From a clean checkout of the commit above, with `RAW_DATA_DIR` set, run the job command above twice against a new database file. Then run the Silver verification query and the hash queries through `DuckDBStore("<scratch>/lane.duckdb").query(sql)` from `src.ingestion.store`.
