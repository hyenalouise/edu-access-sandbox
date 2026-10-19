# Evidence: DepEd enrollment SY 2021-22 and 2022-23 load on Databricks `dev`, the other four years skip, and Silver passes every check

Issue #183 (part of #43) · Databricks `dev` (D-017) · 2026-10-19, Manila time (UTC+8) · run by @hyenalouise

## The claim

On Databricks `dev`, one run of `edu_access_pipeline` from `main` loads the SY 2021-22 and 2022-23 enrollment deliveries into `deped_enrollment_raw`. The four school years already loaded are skipped, and none of their rows is rewritten. Silver rebuilds all six years and passes all 227 gate checks with 2 WARN and no FAIL, with the same counts as the [local run](../reconciliation/2026-10-19-deped-enrollment-2021-23-silver.md).

## What was run

1. **File move.** After #185 merged, the four files in `raw/_holding/deped/2026-10-19/` were copied to `/Volumes/edu_access/00-source/raw/deped/2026-10-19/`:
   - `Enrollment-in-SY-2021-2022.zip`
   - `Enrollment-in-SY-2022-2023.zip`
   - `SHA256SUMS.txt`
   - `RETRIEVED.txt`

   The copied folder was downloaded back, and `shasum -a 256 -c SHA256SUMS.txt` passed for both zips and `RETRIEVED.txt`. The holding folder was then removed, so `raw/_holding/deped/` is empty.
2. **Deploy.** `databricks bundle validate` and `databricks bundle deploy --target dev`, from a clean checkout of `main` at `ae7ca8062a06b26f6369e78d55201e11e2884be6` (#185's merge). `databricks bundle summary` showed `git_source.git_commit` and the `code_revision` parameter both equal to that commit. No other job run was active.
3. **Run.** `databricks bundle run edu_access_pipeline --target dev`, once. The second, rerun-safety run was not done on Databricks, to save compute. See [What this does not prove](#what-this-does-not-prove).

The commands, in order (`--profile reached-hq` on each):

```bash
databricks fs mkdir dbfs:/Volumes/edu_access/00-source/raw/deped/2026-10-19
databricks fs cp dbfs:/Volumes/edu_access/00-source/raw/_holding/deped/2026-10-19/Enrollment-in-SY-2021-2022.zip dbfs:/Volumes/edu_access/00-source/raw/deped/2026-10-19/
databricks fs cp dbfs:/Volumes/edu_access/00-source/raw/_holding/deped/2026-10-19/Enrollment-in-SY-2022-2023.zip dbfs:/Volumes/edu_access/00-source/raw/deped/2026-10-19/
databricks fs cp dbfs:/Volumes/edu_access/00-source/raw/_holding/deped/2026-10-19/SHA256SUMS.txt dbfs:/Volumes/edu_access/00-source/raw/deped/2026-10-19/
databricks fs cp dbfs:/Volumes/edu_access/00-source/raw/_holding/deped/2026-10-19/RETRIEVED.txt dbfs:/Volumes/edu_access/00-source/raw/deped/2026-10-19/
databricks fs cp -r dbfs:/Volumes/edu_access/00-source/raw/deped/2026-10-19/ <scratch>/check/
(cd <scratch>/check && shasum -a 256 -c SHA256SUMS.txt)     # Enrollment-in-SY-2021-2022.zip: OK, Enrollment-in-SY-2022-2023.zip: OK, RETRIEVED.txt: OK
databricks fs rm -r dbfs:/Volumes/edu_access/00-source/raw/_holding/deped/2026-10-19
databricks bundle validate --target dev
databricks bundle deploy --target dev
databricks bundle summary --target dev
databricks bundle run edu_access_pipeline --target dev
databricks jobs get-run 134284218399221
```

| | Run 1 |
|---|---|
| Job | `[dev ina_magno] edu_access_pipeline` (`651937364323543`) |
| Job run | `134284218399221` |
| Job start → end (UTC) | 2026-10-19 01:43:23 → 01:56:42 |
| Job result | `SUCCESS`: 52 enabled tasks succeeded, 38 disabled |
| `01_create_deped_enrollment_raw` (UTC) | `SUCCESS`, 01:44:57 → 01:45:03 |
| `bronze_deped_enrollment` (UTC) | `SUCCESS`, 01:45:04 → 01:48:36 |
| `90_validate_deped_enrollment_raw` (UTC) | `SUCCESS`, 01:48:36 → 01:48:58 |
| `01_clean_deped_enrollment` (UTC) | `SUCCESS`, 01:48:58 → 01:50:36 |
| `90_validate_deped_enrollment_clean` (UTC) | `SUCCESS`, 01:50:36 → 01:52:27 |
| `90_validate_control`, `90_validate_freshness` (UTC) | `SUCCESS`, 01:56:28 → 01:56:42 |
| Ingestion `run_id` | `5ef7b50b-a1d4-4e2e-8a95-f07684d312fa` |

The job-run and task rows come from `databricks jobs get-run`. The queries below ran on the job's SQL warehouse (`71d3ccb9cea611c0`) right after the run, through the Statement Execution API (`databricks api post /api/2.0/sql/statements`).

## Results

### Bronze

Every enrollment batch's attempt in this run:

```sql
SELECT a.batch_id, a.run_id, a.action, a.outcome, a.rows_inserted
FROM edu_access.`01-control`.ingestion_batch_attempts AS a
JOIN edu_access.`01-control`.pipeline_runs AS r USING (run_id)
WHERE r.job_run_id = '134284218399221' AND a.batch_id LIKE 'deped_enrollment\_\_%'
ORDER BY a.batch_id;
```

| `batch_id` | `action` | `outcome` | `rows_inserted` |
|---|---|---|---:|
| `deped_enrollment__2020-21__65c400aa31ba` | `skip` | `skipped` | 0 |
| `deped_enrollment__2021-22__62f412466435` | `load` | `succeeded` | 60,429 |
| `deped_enrollment__2022-23__6d567d801a8d` | `load` | `succeeded` | 60,137 |
| `deped_enrollment__2023-24__a10f4d0f9082` | `skip` | `skipped` | 0 |
| `deped_enrollment__2024-25__fd5dd74a62b8` | `skip` | `skipped` | 0 |
| `deped_enrollment__2025-26__ab4d7e24b3a4` | `skip` | `skipped` | 0 |

The rows show that the four other years were not rewritten: every Bronze row still carries the run that wrote it.

```sql
SELECT b.school_year, b.run_id, MIN(r.started_at_utc) AS run_started_utc, COUNT(*) AS rows
FROM edu_access.`02-bronze`.deped_enrollment_raw AS b
LEFT JOIN edu_access.`01-control`.pipeline_runs AS r ON r.run_id = b.run_id AND r.source_id = 'deped_enrollment'
GROUP BY ALL ORDER BY 1;
```

| `school_year` | `run_id` that wrote the rows | Run started (UTC) | rows |
|---|---|---|---:|
| 2020-21 | `1c504726-f1d2-4b4c-a5bf-6fa41507c4a3` ([2026-10-18 record](2026-10-18-deped-enrollment-2020-21-databricks.md)) | 2026-10-18 03:52:08 | 60,957 |
| 2021-22 | `5ef7b50b-a1d4-4e2e-8a95-f07684d312fa` (this run) | 2026-10-19 01:45:19 | 60,429 |
| 2022-23 | `5ef7b50b-a1d4-4e2e-8a95-f07684d312fa` (this run) | 2026-10-19 01:45:19 | 60,137 |
| 2023-24 | `67a608ec-7f00-4597-890c-962f638d372c` ([2026-10-06 record](2026-10-06-deped-enrollment-idempotency.md)) | 2026-10-05 17:57:46 | 60,167 |
| 2024-25 | `67a608ec-7f00-4597-890c-962f638d372c` | 2026-10-05 17:57:46 | 60,129 |
| 2025-26 | `67a608ec-7f00-4597-890c-962f638d372c` | 2026-10-05 17:57:46 | 60,204 |

362,023 Bronze rows, each school year equal to its approved `row_count`.

### Silver

The verification query in [Silver, Running on Databricks](../../docs/operations/silver.md#running-on-databricks) for six deliveries, with commit `ae7ca8062a06b26f6369e78d55201e11e2884be6` filled in. 24 of its 25 rows are `OK`:

| Check | Expected | Actual | Result |
|---|---|---|---|
| clean rows SY 2020-21 / 2021-22 / 2022-23 / 2023-24 / 2024-25 / 2025-26 | 60,957 / 60,429 / 60,136 / 60,167 / 60,129 / 60,204 | the same | OK (six rows) |
| quarantined rows | 1 | 1 | OK |
| quarantined school_id, SY 2022-23 | `1404066` | `1404066` | OK |
| repeated keys | 0 | 0 | OK |
| learners, SY 2020-21 to 2025-26 | 26,227,022 / 27,560,661 / 27,794,274 / 27,081,292 / 26,400,182 / 25,935,863 | the same | OK |
| blank SHS counts kept NULL, SY 2025-26 | 47,352 | 47,352 | OK |
| absent v2 column NULL in v1 rows | 301,818 | 301,818 | OK |
| standard labels, school_management, SY 2025-26 | 9 | 9 | OK |
| Local Government kept, SY 2020-21 / 2021-22 / 2022-23 | 154 / 155 / 106 | the same | OK |
| mangled `Ã‘` left | 0 | 0 | OK |
| overseas flagged | 201 | 201 | OK |
| no counts published, SY 2025-26 | 46 | 46 | OK |
| checks in the last run | 227 | 227 | OK |
| checks in the last run not PASS (the two SY 2022-23 quarantine WARNs) | 2 | 2 | OK |
| rows from the last run | 362,022 | 362,022 | OK |
| rows from another commit | 0 | 0 | OK |
| last silver run | succeeded | succeeded | OK |
| silver runs succeeded at this commit | 2 | 1 | CHECK: one run, by choice |
| published rows from a succeeded run | 362,022 | 362,022 | OK |
| candidate rows not published | 0 | 0 | OK |

The counts, learners, quarantined row, and gate results equal the [local run](../reconciliation/2026-10-19-deped-enrollment-2021-23-silver.md). The one `CHECK` expects two runs at the commit; only one ran.

## What this does not prove

- **Rerun safety on Databricks.** A second run, which would skip all six deliveries and insert 0, was not done, to save compute. It is shown locally: two whole-job runs on the real data, the second inserting nothing and rebuilding identical Silver content ([Bronze](../reconciliation/2026-10-19-deped-enrollment-2021-23-bronze.md), [Silver](../reconciliation/2026-10-19-deped-enrollment-2021-23-silver.md)). It is also shown on Databricks for the same code path by the SY 2020-21 runs ([2026-10-18 record](2026-10-18-deped-enrollment-2020-21-databricks.md)). #183's acceptance item was amended on 2026-10-19 to one `dev` run for this reason.
- Content hashes on Databricks. They were taken locally only.
