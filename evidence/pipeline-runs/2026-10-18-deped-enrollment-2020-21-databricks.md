# Evidence: DepEd enrollment SY 2020-21 loads on Databricks `dev` as a backfill, Silver passes every check, and a second run inserts nothing

Issue #170 (part of #43) · Databricks `dev` (D-017) · 2026-10-18, Manila time (UTC+8) · run by @hyenalouise

## The claim

On Databricks `dev`, the job `edu_access_pipeline` loads the SY 2020-21 enrollment delivery into the existing `deped_enrollment_raw` table as a `backfill`, leaving the three years already loaded untouched. Silver rebuilds all four years and passes all 153 gate checks, with the same counts as the [local run](../reconciliation/2026-10-16-deped-enrollment-2020-21-bronze-to-silver.md). Running the job again skips all four deliveries and inserts nothing.

## What was run

1. **File move.** After #171 and #172 merged, the three files in `raw/_holding/deped/2026-10-16/` (`Enrollment-in-SY-2020-2021.zip`, `SHA256SUMS.txt`, `RETRIEVED.txt`) were copied to `/Volumes/edu_access/00-source/raw/deped/2026-10-16/` with `databricks fs cp`. The copied zip was downloaded back and hashed: `65c400aa31ba63730b8f9a7b4d60ade91c6a29cdb34a3c6bf255e5fc9e91a241`, equal to the contract and to the folder's `SHA256SUMS.txt`; `RETRIEVED.txt` also matched its listed hash. The holding folder was then removed, so `raw/_holding/deped/` is empty.
2. **Deploy.** `databricks bundle validate` and `databricks bundle deploy --target dev` from a clean checkout of `main` at `df63d635c3cb73873d4ad70d195f9724ab83624a`. `databricks bundle summary` showed both `git_source.git_commit` and the `code_revision` parameter equal to that commit. No other job run was active.
3. **Runs.** `databricks bundle run edu_access_pipeline --target dev`, twice.

The commands, in order (`--profile reached-hq` on each):

```bash
databricks fs mkdir dbfs:/Volumes/edu_access/00-source/raw/deped/2026-10-16
databricks fs cp dbfs:/Volumes/edu_access/00-source/raw/_holding/deped/2026-10-16/Enrollment-in-SY-2020-2021.zip dbfs:/Volumes/edu_access/00-source/raw/deped/2026-10-16/
databricks fs cp dbfs:/Volumes/edu_access/00-source/raw/_holding/deped/2026-10-16/SHA256SUMS.txt dbfs:/Volumes/edu_access/00-source/raw/deped/2026-10-16/
databricks fs cp dbfs:/Volumes/edu_access/00-source/raw/_holding/deped/2026-10-16/RETRIEVED.txt dbfs:/Volumes/edu_access/00-source/raw/deped/2026-10-16/
databricks fs cp dbfs:/Volumes/edu_access/00-source/raw/deped/2026-10-16/Enrollment-in-SY-2020-2021.zip <scratch>/check/
shasum -a 256 <scratch>/check/Enrollment-in-SY-2020-2021.zip    # 65c400aa31ba63730b8f9a7b4d60ade91c6a29cdb34a3c6bf255e5fc9e91a241
databricks fs cat dbfs:/Volumes/edu_access/00-source/raw/deped/2026-10-16/SHA256SUMS.txt
#   65c400aa31ba63730b8f9a7b4d60ade91c6a29cdb34a3c6bf255e5fc9e91a241  Enrollment-in-SY-2020-2021.zip
#   420943248755bdd22e94e9c81cd5a16d007f8e64f102d39c09119a7e479a4ee7  RETRIEVED.txt
databricks fs cp dbfs:/Volumes/edu_access/00-source/raw/deped/2026-10-16/RETRIEVED.txt <scratch>/check/
shasum -a 256 <scratch>/check/RETRIEVED.txt                      # 420943248755bdd22e94e9c81cd5a16d007f8e64f102d39c09119a7e479a4ee7
databricks fs rm -r dbfs:/Volumes/edu_access/00-source/raw/_holding/deped/2026-10-16
databricks bundle validate --target dev
databricks bundle deploy --target dev
databricks bundle summary --target dev
databricks bundle run edu_access_pipeline --target dev
databricks bundle run edu_access_pipeline --target dev
databricks jobs get-run 146052617753176
databricks jobs get-run 250134607484273
```

| | Run 1 | Run 2 |
|---|---|---|
| Job run | `146052617753176` | `250134607484273` |
| Job start → end (UTC) | 2026-10-18 03:43:23 → 04:02:12 | 2026-10-18 04:03:11 → 04:11:42 |
| Job result | `SUCCESS`: 43 enabled tasks succeeded, 26 disabled | `SUCCESS`: 43 enabled tasks succeeded, 26 disabled |
| `bronze_deped_enrollment` (UTC) | `SUCCESS`, 03:51:50 → 03:54:49 | `SUCCESS`, 04:03:59 → 04:05:31 |
| `90_validate_deped_enrollment_raw` (UTC) | `SUCCESS`, 03:54:50 → 03:55:16 | `SUCCESS`, 04:05:31 → 04:05:54 |
| `01_clean_deped_enrollment` (UTC) | `SUCCESS`, 03:55:16 → 03:56:15 | `SUCCESS`, 04:05:54 → 04:06:52 |
| `90_validate_deped_enrollment_clean` (UTC) | `SUCCESS`, 03:56:15 → 03:58:53 | `SUCCESS`, 04:06:53 → 04:09:08 |
| Ingestion `run_id` | `1c504726-f1d2-4b4c-a5bf-6fa41507c4a3` | `97c1baca-29c6-43e6-bda1-67cae03a040c` |

The job-run and task rows come from `databricks jobs get-run`, and the screenshots below show the two runs. The queries ran on the job's SQL warehouse (`71d3ccb9cea611c0`) after run 2, first through the Statement Execution API (`databricks api post /api/2.0/sql/statements`); the screenshot under each query shows its result.
<img width="1154" height="322" alt="image" src="https://github.com/user-attachments/assets/f6930c73-dfb1-4258-b8f2-031b20c28c65" />
<img width="1153" height="294" alt="image" src="https://github.com/user-attachments/assets/e89aa279-5b2f-499e-a766-2c33a0d1bdc6" />



## Results

### Bronze

Bronze rows per school year:

```sql
SELECT school_year, delivery_version, COUNT(*) AS rows
FROM edu_access.`02-bronze`.deped_enrollment_raw GROUP BY ALL ORDER BY 1, 2;
```
<img width="806" height="153" alt="image" src="https://github.com/user-attachments/assets/9a0e1739-df3b-4f0c-9662-986bbd8d2edb" />



```sql
SELECT a.run_id, a.action, a.outcome, a.rows_inserted
FROM edu_access.`01-control`.ingestion_batch_attempts AS a
JOIN edu_access.`01-control`.pipeline_runs AS r USING (run_id)
WHERE a.batch_id LIKE 'deped_enrollment__2020-21%'
ORDER BY r.started_at_utc;
```
<img width="807" height="145" alt="image" src="https://github.com/user-attachments/assets/bb001198-d6f7-4341-9cef-ab2f19e0ee53" />


The SY 2020-21 batch's attempts, in run order: `load` / `succeeded` / 60,957 rows (run 1), then `skip` / `skipped` / 0 (run 2).

Every enrollment batch's attempt in the two recorded ingestion runs:

```sql
SELECT a.batch_id, a.run_id, a.action, a.outcome, a.rows_inserted
FROM edu_access.`01-control`.ingestion_batch_attempts AS a
JOIN edu_access.`01-control`.pipeline_runs AS r USING (run_id)
WHERE a.run_id IN ('1c504726-f1d2-4b4c-a5bf-6fa41507c4a3', '97c1baca-29c6-43e6-bda1-67cae03a040c')
  AND a.batch_id LIKE 'deped_enrollment\_\_%'
ORDER BY r.started_at_utc, a.batch_id;
```

| `batch_id` | `run_id` | `action` | `outcome` | `rows_inserted` |
|---|---|---|---|---:|
| `deped_enrollment__2020-21__65c400aa31ba` | `1c504726…` (run 1) | `load` | `succeeded` | 60,957 |
| `deped_enrollment__2023-24__a10f4d0f9082` | `1c504726…` (run 1) | `skip` | `skipped` | 0 |
| `deped_enrollment__2024-25__fd5dd74a62b8` | `1c504726…` (run 1) | `skip` | `skipped` | 0 |
| `deped_enrollment__2025-26__ab4d7e24b3a4` | `1c504726…` (run 1) | `skip` | `skipped` | 0 |
| `deped_enrollment__2020-21__65c400aa31ba` | `97c1baca…` (run 2) | `skip` | `skipped` | 0 |
| `deped_enrollment__2023-24__a10f4d0f9082` | `97c1baca…` (run 2) | `skip` | `skipped` | 0 |
| `deped_enrollment__2024-25__fd5dd74a62b8` | `97c1baca…` (run 2) | `skip` | `skipped` | 0 |
| `deped_enrollment__2025-26__ab4d7e24b3a4` | `97c1baca…` (run 2) | `skip` | `skipped` | 0 |

One load and seven skips. The attempts are the loader's own record of what it decided. The rows themselves show that the three earlier years were not rewritten: every Bronze row still carries the run that wrote it.

```sql
SELECT b.school_year, b.run_id, MIN(r.started_at_utc) AS run_started_utc, COUNT(*) AS rows
FROM edu_access.`02-bronze`.deped_enrollment_raw AS b
LEFT JOIN edu_access.`01-control`.pipeline_runs AS r ON r.run_id = b.run_id AND r.source_id = 'deped_enrollment'
GROUP BY ALL ORDER BY 1;
```

| `school_year` | `run_id` that wrote the rows | Run started (UTC) | rows |
|---|---|---|---:|
| 2020-21 | `1c504726-f1d2-4b4c-a5bf-6fa41507c4a3` (run 1) | 2026-10-18 03:52:08 | 60,957 |
| 2023-24 | `67a608ec-7f00-4597-890c-962f638d372c` | 2026-10-05 17:57:46 | 60,167 |
| 2024-25 | `67a608ec-7f00-4597-890c-962f638d372c` | 2026-10-05 17:57:46 | 60,129 |
| 2025-26 | `67a608ec-7f00-4597-890c-962f638d372c` | 2026-10-05 17:57:46 | 60,204 |

`67a608ec…` is the first load in the [2026-10-06 record](2026-10-06-deped-enrollment-idempotency.md). No row of SY 2023-24 to 2025-26 was written by either run here.

```sql
SELECT school_year, load_type, status, attempt_count, first_run_id, last_run_id
FROM edu_access.`01-control`.ingestion_batches
WHERE source_id = 'deped_enrollment' ORDER BY school_year;
```

| `school_year` | `load_type` | `status` | `attempt_count` | `first_run_id` = `last_run_id` |
|---|---|---|---:|---|
| 2020-21 | `backfill` | `succeeded` | 1 | `1c504726…` (run 1) |
| 2023-24 | `initial` | `succeeded` | 1 | `67a608ec…` |
| 2024-25 | `incremental` | `succeeded` | 1 | `67a608ec…` |
| 2025-26 | `incremental` | `succeeded` | 1 | `67a608ec…` |

So the backfill inserted only SY 2020-21, and the three earlier batches were neither reloaded nor re-attempted.

### Checks

```sql
SELECT r.job_run_id, d.layer, d.status, COUNT(*)
FROM edu_access.`01-control`.data_quality_results AS d
JOIN edu_access.`01-control`.pipeline_runs AS r ON r.run_id = d.run_id AND r.source_id = d.source_id
WHERE d.source_id = 'deped_enrollment' AND r.job_run_id IN ('146052617753176', '250134607484273')
GROUP BY ALL ORDER BY 1, 2, 3;
```
<img width="808" height="222" alt="image" src="https://github.com/user-attachments/assets/b4b4cb86-a453-4203-9068-2eb8ebad470f" />


```sql
SELECT job_run_id, pipeline_name, status, run_id
FROM edu_access.`01-control`.pipeline_runs
WHERE source_id = 'deped_enrollment' AND job_run_id IN ('146052617753176', '250134607484273')
ORDER BY started_at_utc;
```
<img width="802" height="155" alt="image" src="https://github.com/user-attachments/assets/f4584910-3921-42af-83db-68963ac7d7ea" />

Both runs' `bronze_ingest` and `silver_build` rows are `succeeded`; the `bronze_ingest` run IDs are the ingestion `run_id`s in the table above.

### Silver

The verification query in [Silver, Running on Databricks](../../docs/operations/silver.md#running-on-databricks), with `<commit that ran>` set to `df63d635c3cb73873d4ad70d195f9724ab83624a`, returned `OK` on all 22 rows:

| Check | Expected | Actual |
|---|---|---|
| clean rows SY 2020-21 / 2023-24 / 2024-25 / 2025-26 | 60957 / 60167 / 60129 / 60204 | same |
| quarantined rows | 0 | 0 |
| repeated keys | 0 | 0 |
| learners SY 2020-21 / 2023-24 / 2024-25 / 2025-26 | 26227022 / 27081292 / 26400182 / 25935863 | same |
| blank SHS counts kept NULL, SY 2025-26 | 47352 | 47352 |
| absent v2 column NULL in v1 rows | 181253 | 181253 |
| standard labels, school_management, SY 2025-26 | 9 | 9 |
| Local Government kept, SY 2020-21 | 154 | 154 |
| mangled `Ã‘` left | 0 | 0 |
| overseas flagged | 137 | 137 |
| no counts published, SY 2025-26 | 46 | 46 |
| checks in the last run / not PASS | 153 / 0 | 153 / 0 |
| rows from the last run | 241457 | 241457 |
| rows from another commit | 0 | 0 |
| last silver run | succeeded | succeeded |
| silver runs succeeded at this commit | 2 | 2 |
| published rows from a succeeded run | 241457 | 241457 |
| candidate rows not published | 0 | 0 |

```sql
SELECT school_management, COUNT(*)
FROM edu_access.`03-silver`.deped_enrollment_clean
WHERE school_year = '2020-21' GROUP BY 1 ORDER BY 2 DESC;
```
<img width="806" height="270" alt="image" src="https://github.com/user-attachments/assets/cef508a4-8be9-4b2b-a779-9c672ab4e92e" />


SY 2020-21 `school_management` in Silver: DepEd 47,252; Non-Sectarian 9,496; Sectarian 3,758; SUC 210; Local Government 154; LUC 37; PSO 33; DOST 13; International School 2; Other GA 2. This is the same breakdown as the local run.

## What this does not prove

- Byte-level equality with the local Silver content. The local record compares MD5 hashes; this record compares counts, learners, labels, and flags, as the earlier Databricks records do.
- The job wiring of #166, which merged at 04:07 UTC during run 2. Both runs used the job as deployed at `df63d63`. #166 changed which downstream tasks wait for which gates, not the enrollment Bronze or Silver files, and its new Integration and Gold tasks are disabled.
- Quarantine on real data: no real row is quarantined.
- That `Local Government` schools were managed differently from `DepEd` schools (see the local record).

## How to reproduce

From a clean checkout of `df63d63`, deploy with `databricks bundle deploy --target dev`, run `databricks bundle run edu_access_pipeline --target dev` (a third run should skip all four deliveries), and run the queries above in a notebook or through the SQL warehouse.
