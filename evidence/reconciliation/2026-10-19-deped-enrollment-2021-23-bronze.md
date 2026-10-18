# Evidence: DepEd enrollment SY 2021-22 and 2022-23 load into the existing Bronze table, reconcile per school year, and reruns change nothing

Issue #183 (part of #43) · local run (DuckDB) only; nothing has run on Databricks · 2026-10-19 · checked by @hyenalouise

## The claim

SY 2021-22 and 2022-23 are the fifth and sixth approved deliveries of `deped_enrollment`. They load into the existing `deped_enrollment_raw` table under schema `v1` through the existing task, with no new task, table, or schema version. Each school year's Bronze rows equal its file and its approved `row_count`. Bronze keeps SY 2022-23's seven-digit school ID `1404066` (profile O-1) and WARNs on it; nothing fails. The four other years' Bronze rows are identical to a run of `main` on the same four files. A second job run inserts no Bronze rows.

## What was run

Commit `68f6c68769d8622a0bbc56f513661d0f89aaa9b3` on `feat/deped-enrollment-2021-23-bronze` (stacked on the profile branch), clean worktree (`code_revision` has no `-dirty`). macOS 26.3.1, Python 3.12.14, DuckDB 1.4.5. Each run started on a new, empty database file in a scratch folder.

Before the run, both zips, CSVs, and READMEs were hashed and compared with the source card: SY 2021-22 `62f41246…0acd`, `ffbfcd0b…5287`; SY 2022-23 `6d567d80…f9bf`, `d53142a5…ec49`; README `5eb05f7d…2a80` in both (the same README as SY 2020-21 and 2023-24). All equal. The loader verified them again.

`RAW_DATA_DIR` was a scratch folder of symbolic links to every file in `~/Projects/reached-hq/raw-data`, plus one link in `deped/original/` to the EMISD workbook that the local copy keeps in `school_coordinates/original/`. Without that link the `deped_enrollment_psgc` lane fails its Silver gate locally ("approved but not in the landing folder"), which fails the whole job. The enrollment lane does not read the workbook. The whole job ran twice, in the order of the Databricks DAG:

```bash
RAW_DATA_DIR=<scratch>/landing python -m src.job.local_run --db <scratch>/lane.duckdb
```

Both runs exited 0, and every enabled task of every lane `succeeded`.

| Step | Run 1 | Run 2 |
|---|---|---|
| `bronze_deped_enrollment` | SY 2020-21 `load initial` inserted 60,957; 2021-22, 2022-23, 2023-24, 2024-25, 2025-26 `load incremental` inserted 60,429, 60,137, 60,167, 60,129, 60,204 (15.6 s) | all six `skip`, inserted 0 (0.2 s) |
| `90_validate_deped_enrollment_raw` | 3 checks PASS | 3 checks PASS |

On the fresh database SY 2020-21 loads first, so it is `initial` here and the two new years are `incremental`. On Databricks, where SY 2020-21 and 2023-24 to 2025-26 are already loaded, both new years will be `backfill`. `tests/test_ingestion_pipeline.py::test_sy_2021_22_and_2022_23_load_as_v1_backfills_and_leave_the_other_years_untouched` shows that case with made-up files.

## Results

### Bronze, per school year

| School year | Approved `row_count` | File rows | Bronze rows | Run 1 inserted | Run 2 inserted | Schema |
|---|---:|---:|---:|---:|---:|---|
| 2020-21 | 60,957 | 60,957 | 60,957 | 60,957 | 0 | v1 |
| 2021-22 | 60,429 | 60,429 | 60,429 | 60,429 | 0 | v1 |
| 2022-23 | 60,137 | 60,137 | 60,137 | 60,137 | 0 | v1 |
| 2023-24 | 60,167 | 60,167 | 60,167 | 60,167 | 0 | v1 |
| 2024-25 | 60,129 | 60,129 | 60,129 | 60,129 | 0 | v1 |
| 2025-26 | 60,204 | 60,204 | 60,204 | 60,204 | 0 | v2 |
| **All** | | | **362,023** | 362,023 | **0** | |

Each batch has `attempt_count = 1`, and its `first_run_id` and `last_run_id` are both run 1. The attempts log shows `load` for each of the six files in run 1 and `skip` with 0 rows in run 2.

Gate results by layer (PASS / WARN / FAIL):

| Results | Run 1 | Run 2 |
|---|---|---|
| Bronze, load task (batch checks and `approved_deliveries_present`) | 66 / 1 / 0 | 1 / 0 / 0 (skips write no batch checks) |
| Bronze gate (`no_pipeline_duplicates`, `rows_have_a_known_batch`, `succeeded_batches_reconcile`) | 3 / 0 / 0 | 3 / 0 / 0 |

The one WARN is `school_id_format` on the SY 2022-23 batch: expected `0 not matching ^[0-9]{6}$`, actual 1. It is `1404066` (profile O-1). The check is warn-only by design: Bronze keeps every published row, and Silver decides. The batch checks went from 45 for four deliveries to 67 for six (11 per delivery, plus `approved_deliveries_present`).

### The other four years are unchanged

Content hash over every Bronze column except the run stamp (`run_id`, `ingested_at_utc`, `code_revision`), in school year and row order, with the query from the [2026-10-09 record](2026-10-09-deped-enrollment-bronze-to-silver.md):

| Bronze rows | This branch, after run 1 | After run 2 | `main` at `988ef0d`, same four files |
|---|---|---|---|
| All six years (362,023) | `04bc4517a2817dcb6e45e20e1635568c` | same | n/a |
| SY 2020-21 and 2023-24 to 2025-26 (241,457) | `c7cd6f96e7424452155aa749fbd345b6` | same | `c7cd6f96e7424452155aa749fbd345b6` |

The `main` run used a copy of the landing folder without the two new zips, because `main` blocks them as `unregistered_delivery`. The four-year hash differs from the `df759ca3…75c8` in the [2026-10-16 record](2026-10-16-deped-enrollment-2020-21-bronze-to-silver.md), and `main` gives the same value as this branch. So that difference comes from code merged to `main` since 2026-10-16, not from this branch.

The Silver build and gate ran in both job runs and passed with 2 WARN and 0 FAIL. The Silver results, including the quarantined `1404066`, are recorded in the Silver pull request.

## Why it holds

1. The Bronze DDL and gate are generated from the contract. Adding deliveries under an existing schema version leaves both files byte-identical (`tests/test_ingestion_pipeline.py::test_bronze_sql_matches_the_contract`).
2. The loader identifies each file by checksum and skips a batch that already succeeded with the same checksum, so a rerun inserts nothing ([2026-10-09 record](2026-10-09-deped-enrollment-bronze-to-silver.md#why-it-holds)).

## Also shown by tests

`python -m pytest tests -q`: 942 passed. New or changed for these deliveries, in `tests/test_ingestion_pipeline.py`:

- The contract's six deliveries match the source card's checksums and row counts, and `config/tables.yml` lists the same years.
- SY 2021-22 and 2022-23 use the 78-column `v1` header.
- Made-up SY 2021-22 and 2022-23 files load as `v1` backfills after the four other years, without changing those years' Bronze rows or batches. Bronze reconciles per year, and a rerun inserts nothing.
- A seven-digit `school_id` is kept in Bronze, with `school_id_format` WARN and `school_id_not_blank` PASS.

## What this does not prove

- Anything on Databricks. Both zips are still in `raw/_holding/deped/2026-10-19/`, and no job has run with them. See [Awaiting authorization](#awaiting-authorization).
- That `1404066` and `404066` are the same school. The profile reads the extra row as the school's Kindergarten filed under a mistyped ID, but DepEd has not confirmed it.

## Awaiting authorization

Following [ingestion.md, Runbook 1](../../docs/operations/ingestion.md#runbook): merge the contract pull request first, then move the files, then run the job from `main`. Moving the files into `raw/deped/` before the merge would make every run from `main` block them as `unregistered_delivery` and fail. The CLI has no `mv`, so the move is a copy, a checksum check, and then removing the holding folder:

```bash
databricks fs ls dbfs:/Volumes/edu_access/00-source/raw/_holding/deped/2026-10-19/ --profile reached-hq
databricks fs ls dbfs:/Volumes/edu_access/00-source/raw/deped/ --profile reached-hq
databricks fs mkdir dbfs:/Volumes/edu_access/00-source/raw/deped/2026-10-19 --profile reached-hq
databricks fs cp dbfs:/Volumes/edu_access/00-source/raw/_holding/deped/2026-10-19/Enrollment-in-SY-2021-2022.zip dbfs:/Volumes/edu_access/00-source/raw/deped/2026-10-19/ --profile reached-hq
databricks fs cp dbfs:/Volumes/edu_access/00-source/raw/_holding/deped/2026-10-19/Enrollment-in-SY-2022-2023.zip dbfs:/Volumes/edu_access/00-source/raw/deped/2026-10-19/ --profile reached-hq
databricks fs cp dbfs:/Volumes/edu_access/00-source/raw/_holding/deped/2026-10-19/SHA256SUMS.txt dbfs:/Volumes/edu_access/00-source/raw/deped/2026-10-19/ --profile reached-hq
databricks fs cp dbfs:/Volumes/edu_access/00-source/raw/_holding/deped/2026-10-19/RETRIEVED.txt dbfs:/Volumes/edu_access/00-source/raw/deped/2026-10-19/ --profile reached-hq
databricks fs cp -r dbfs:/Volumes/edu_access/00-source/raw/deped/2026-10-19/ <scratch>/check/ --profile reached-hq
(cd <scratch>/check && shasum -a 256 -c SHA256SUMS.txt)     # expect 62f41246…0acd, 6d567d80…f9bf, and RETRIEVED.txt: OK
databricks fs rm -r dbfs:/Volumes/edu_access/00-source/raw/_holding/deped/2026-10-19 --profile reached-hq
```

Then deploy and run from a clean checkout of `main`, after announcing the run and stopping other serverless compute:

```bash
databricks bundle validate --target dev --profile reached-hq
databricks bundle deploy --target dev --profile reached-hq
databricks bundle summary --target dev --profile reached-hq     # git_commit and code_revision = git rev-parse HEAD
databricks bundle run edu_access_pipeline --target dev --profile reached-hq
databricks bundle run edu_access_pipeline --target dev --profile reached-hq
```

Expected: run 1 loads SY 2021-22 and 2022-23 as `backfill`, with 60,429 and 60,137 rows, and the other four years `skip`; run 2 skips all six and inserts 0. Bronze has 362,023 rows after both runs. Record the results in `evidence/pipeline-runs/<date>-deped-enrollment-2021-23-databricks.md`.

## How to reproduce

From a clean checkout of the commit above, with `RAW_DATA_DIR` set as described, run the job command above twice against a new database file. Then run the [Bronze queries in ingestion.md](../../docs/operations/ingestion.md) and the hash query through `DuckDBStore("<scratch>/lane.duckdb").query(sql)` from `src.ingestion.store`.
