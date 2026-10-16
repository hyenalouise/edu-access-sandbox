# Evidence: the EMISD workbook loads into Bronze on Databricks `dev` once, and a second run inserts nothing

Issue #152 · Databricks `dev` (D-017) · 2026-10-16, Manila time (UTC+8) · run by @maeveylain

## The claim

On Databricks `dev`, the job `edu_access_pipeline` loads the EMISD workbook from the raw volume into `deped_enrollment_psgc_raw` with every row of sheet `DB` below the header and its row kind, every check passing. Running the job again skips the workbook, and Bronze is unchanged. These are the same counts as the [local run](2026-10-16-deped-enrollment-psgc-local-idempotency.md).

## What was run

- Job `[dev maeve_lumague] edu_access_pipeline` (job ID `921726647955407`), deployed with `databricks bundle deploy --target dev` from a clean checkout of `feat/152-bronze-deped-enrollment-psgc` at `a769301022957966543d4f7b7d35cc7c1d09397d`. `databricks bundle summary` showed both `git_source.git_commit` and the `code_revision` parameter equal to that commit.
- The workbook uploaded by @maeveylain to `/Volumes/edu_access/00-source/raw/deped/` with the EMISD email PDF beside it. The job hashes the file itself; the batch ID below carries the approved SHA-256 prefix `746d69530d22`.
- Started twice with `databricks bundle run edu_access_pipeline --target dev`.

| | Run 1 | Run 2 |
|---|---|---|
| Job run | `495730698689709` | `869662006027433` |
| Job start → end (UTC) | 2026-10-15 19:46:26 → 19:57:25 | 2026-10-15 20:00:14 → 20:08:18 |
| Job result | `SUCCESS`: 41 enabled tasks succeeded, 26 disabled | `SUCCESS`: 41 enabled tasks succeeded, 26 disabled |
| `07_create_deped_enrollment_psgc_raw` (UTC) | `SUCCESS`, 19:48:02 → 19:55:10 | `SUCCESS`, 20:00:59 → 20:05:39 |
| `bronze_deped_enrollment_psgc` (UTC) | `SUCCESS`, 19:55:10 → 19:56:48 (98 s) | `SUCCESS`, 20:05:39 → 20:06:35 (56 s) |
| `90_validate_deped_enrollment_psgc_raw` (UTC) | `SUCCESS`, 19:56:48 → 19:57:03 | `SUCCESS`, 20:06:35 → 20:06:50 |
| Ingestion `run_id` | `d428d523-68f6-4e82-a38f-a529b6c5de91` | `1fb5c24e-fb2c-40d8-8efd-44c523df804c` |
| Batch action, outcome | `load`, `succeeded` | `skip`, `skipped` |

The job-run and task rows come from `databricks jobs get-run`. The ingestion rows come from the second query below.

## Results

Queried in a notebook after both runs (screenshots kept by @maeveylain).

**1. Rows by kind**

```sql
SELECT source_row_kind, COUNT(*) AS n, MIN(source_row_number), MAX(source_row_number)
FROM edu_access.`02-bronze`.deped_enrollment_psgc_raw
GROUP BY 1 ORDER BY 1;
```

| `source_row_kind` | n | first Excel row |
|---|---|---|
| `blank` | 9 | 60,177 |
| `no_identifier` | 1 | 60,176 |
| `unit` | 60,275 | 9 |

Total 60,285, equal to the card, the contract and the local run. The `MAX` column was cut off in the screenshot; @maeveylain confirmed every expected result was met.

**2. The two attempts**

```sql
SELECT r.run_id, a.action, a.outcome, a.rows_inserted, r.status, r.started_at_utc
FROM edu_access.`01-control`.ingestion_batch_attempts AS a
JOIN edu_access.`01-control`.pipeline_runs AS r ON r.run_id = a.run_id
WHERE a.batch_id = 'deped_enrollment_psgc__2023-24__746d69530d22'
ORDER BY r.started_at_utc;
```

Two rows: `load`/`succeeded`, then `skip`/`skipped` (run IDs in the table above). Query 1 ran after run 2 and still counts 60,285 rows, so run 2 inserted none.

**3. Checks**

```sql
SELECT status, COUNT(*) FROM edu_access.`01-control`.data_quality_results
WHERE source_id = 'deped_enrollment_psgc' GROUP BY 1;
```

`PASS` 41, and no other status: 0 WARN, 0 FAIL. The 41 are not broken down by check here. The local runs recorded 39 for this source; the difference was not examined, and it is not a failure, since every result passed.

**4. Duplicates and revision**

```sql
SELECT COUNT(*) - COUNT(DISTINCT source_sha256 || ':' || CAST(source_row_number AS STRING)) AS duplicates,
       COUNT(DISTINCT code_revision) AS revisions
FROM edu_access.`02-bronze`.deped_enrollment_psgc_raw;
```

`duplicates` 0, `revisions` 1 (every row from one deployed commit).

## Not checked here

- Per-column values on Databricks (9-digit codes, `#N/A`, float digits). They were checked on the same file locally; the Spark backend reads the workbook with the same Python code.
- Table ownership by `reached-hq` and Delta column mapping: not queried in this run.
- Silver: not built (#137).
