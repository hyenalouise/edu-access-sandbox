# Failure-recovery runbook

Use this runbook after a pipeline task, data-quality check, alert, or dashboard result fails. It complements the source-specific procedures in [ingestion.md](ingestion.md) and follows D-014, D-015, D-020, D-025, D-043, and D-051.

## First response

1. Do not delete, overwrite, or edit a raw delivery, Bronze row, control row, or published Silver or Gold table. The one cleanup step is dropping the Integration work tables a failed or cancelled run left behind, as [integration.md](integration.md) describes, after diagnosis.
2. Record the job run ID, failed task, UTC time, target, and deployed commit.
3. Check the failed task output and the control tables before rerunning anything.
4. Classify the failure using the response table below.
5. Fix or approve the cause through a reviewed pull request when code, a contract, or a mapping changes.
6. Recover with the narrowest safe command, then verify the failed check and every downstream table it feeds.

Start with these queries in the Databricks SQL editor. Replace the values in angle brackets. Read the WARN rows too: some problems, such as a missing approved file for most sources, are only a WARN and the job still succeeds.

```sql
SELECT *
FROM edu_access.`01-control`.pipeline_runs
WHERE job_run_id = '<job-run-id>' OR run_id = '<job-run-id>'
ORDER BY started_at_utc, pipeline_name, source_id;
```

```sql
SELECT layer, source_id, table_name, check_name, status, expected, actual, batch_id, code_revision
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = '<job-run-id>'
ORDER BY CASE status WHEN 'FAIL' THEN 1 WHEN 'WARN' THEN 2 ELSE 3 END, layer, source_id, check_name;
```

```sql
SELECT batch_id, source_id, school_year, logical_dataset, load_type, status, archive_path, archive_sha256,
       source_sha256, delivery_version, attempt_count, failure_stage, error_code, error_message, code_revision
FROM edu_access.`01-control`.ingestion_batches
WHERE last_run_id = '<bronze-run-id>' OR batch_id = '<batch-id>';
```

## Failure responses

| Failure type | Diagnose | Response | Recovery and verification |
|---|---|---|---|
| Compute timeout or Free Edition capacity wait | The job reaches its timeout, or the task log shows capacity rather than a data or code error | Confirm no other full run is active. Do not change data or code | Retry the full job with a new run (see [New run, not Repair run](#new-run-not-repair-run)). Idempotent Bronze MERGEs add only missing rows; Silver, Integration, Gold, and Analytics rebuild candidates and publish only after their gates pass. Confirm the new run uses the same commit and has no FAIL results |
| Missing or blocked file | `approved_deliveries_present`, `unregistered_delivery`, or `checksum_mismatch` identifies the file. `approved_deliveries_present` is a FAIL only for a contract with `require_approved_deliveries`; for every other source a missing file is a WARN and the run succeeds | Compare the file name and SHA-256 with its source contract under `config/ingestion/` (D-014). Upload a missing approved file. Never replace an existing raw file | Run the job again. Confirm the batch is `succeeded`, its checksum matches the contract, and its Bronze row count reconciles |
| Schema change | The loader reports `unknown_schema_drift`, an unknown header, sheet, range, or layout | Profile the new delivery. Add a reviewed schema version and regenerate affected SQL or dictionaries. Do not weaken the old schema to accept both silently | Deploy the reviewed commit and run the job. Confirm the new schema version is recorded and old deliveries still pass their tests |
| Code bug | A reproducible exception or failed gate is caused by repository code, SQL, configuration, or a mapping | Add a failing test, fix the defect, run focused and complete tests, merge to `main`, and redeploy the exact pushed commit (see [Redeploy a fix](#redeploy-a-fix)). The job runs the commit pinned at deploy, so running it without redeploying runs the old code again | Run the affected job again with a new run. Confirm `code_revision` equals the deployed commit and all affected gates pass before trusting published tables |
| Bad source data | The bytes match an approved delivery, but validation finds invalid values or excessive quarantine | Leave the raw file and Bronze evidence unchanged. Keep affected rows in quarantine where the documented rule permits it; otherwise let the gate fail. Investigate with the publisher and record observed evidence separately from suspected causes | After a reviewed rule or corrected delivery is available, rerun. Confirm clean plus quarantine reconciles to Bronze and the quarantine count and reasons are recorded |
| Publisher revision | The publisher changes a previously loaded period or logical dataset | Save it in a new dated raw folder. Approve it as the next `delivery_version` with `supersedes` pointing to the prior checksum (D-015). Never overwrite version 1 | Run the job. Confirm both versions remain in Bronze, only the newest succeeded version is in `current_batches`, and affected Silver and Gold totals are revalidated |

If the cause does not fit one row, stop and ask a teammate before changing data or bypassing a gate. A manual table edit is not a recovery procedure.

## Retry, rerun, and backfill

These terms are different:

| Action | When | Command | Expected result |
|---|---|---|---|
| Retry | A run or batch failed or was interrupted, and the cause is fixed | `databricks bundle run edu_access_pipeline --target dev --profile reached-hq-dev` | Failed or `loading` batches are retried automatically. Existing Bronze keys are not duplicated. Downstream candidates rebuild and publish only after their gates pass |
| Rerun | A succeeded full pipeline must be repeated to verify determinism or apply new downstream code | `databricks bundle run edu_access_pipeline --target dev --profile reached-hq-dev` | Succeeded Bronze deliveries skip with zero inserted rows. Enabled downstream tables rebuild from the same current inputs and retain the same keys, row counts, and business totals |
| Forced Bronze rerun | One succeeded batch must be validated and merged again | Local only: `python -m src.ingestion.cli ingest --source <source-id> --rerun <batch-id> --db <database-path>`. The job has no rerun parameter, so there is no `dev` command yet | The attempt is recorded as `rerun`, zero rows are inserted, and reconciliation runs again. Silver and Gold are not rebuilt; run the job for that |
| Backfill | An approved older period arrives after newer periods | Add the delivery and checksum to its contract, place the original file in a new dated publisher folder, then run `databricks bundle run edu_access_pipeline --target dev --profile reached-hq-dev` | The batch records `load_type = backfill`; existing periods and versions remain present and unchanged |

For a local rehearsal, replace the Databricks command with `python -m src.job.local_run --landing <raw-data-root> --db <database-path>`. Always use a separate database path when the purpose is a destructive failure rehearsal.

### New run, not Repair run

Recover with a new run (`databricks bundle run`, or **Run now** in the Jobs UI), never with **Repair run** on the failed run. A repaired run keeps its `run_id`, and the Bronze gate counts every result under that `run_id`, so the old FAIL fails the repaired gate again (D-020; see the open questions in [silver.md](silver.md)).

### Redeploy a fix

From a clean checkout of the merged `main`:

```bash
databricks bundle validate --target dev --profile reached-hq-dev
databricks bundle deploy --target dev --profile reached-hq-dev
databricks bundle summary --target dev --profile reached-hq-dev
```

Confirm in the summary that `git_commit` and the `code_revision` parameter both equal `git rev-parse HEAD`, then start a new run.

### Deploying to prod

`prod` is its own workspace, `dbc-76bcfddb-1669` (D-063). Deploy it only from a clean `main` that equals `origin/main`, after the change has run on `dev`:

```bash
git switch main
git pull
python -m src.job.deploy_prod
```

The script refuses (exit code 2, nothing deployed) on another branch, with uncommitted or untracked changes, or when `HEAD` is not `origin/main`; `--check` runs only these checks. Otherwise it runs `databricks bundle validate`, `deploy`, and `summary` with `--target prod --profile reached-hq-prod`. Confirm in the summary that `git_commit` and `code_revision` both equal `git rev-parse HEAD`, announce the run to the team, then start it:

```bash
databricks bundle run edu_access_pipeline --target prod --profile reached-hq-prod
```

Record the deploy and run in [`evidence/pipeline-runs/`](../../evidence/pipeline-runs/), naming `prod` and the workspace. The CLI also refuses `--target prod` from a branch other than `main` (`git.branch` in `databricks.yml`), so skipping the script still cannot deploy a branch.

## Verify recovery

Recovery is complete only when all of the following are true:

- The new job run finished, and the affected `pipeline_runs` rows are `succeeded`.
- The affected run has zero FAIL results in `data_quality_results`; WARN results are understood and documented.
- The deployed commit equals `code_revision` in the run, batch, and check records.
- The affected source reconciles from current Bronze through Silver, and the affected Gold gate passes.
- A same-input rerun retains the same published keys, row counts, and business totals.
- The dashboard or downstream query now returns the verified Gold or Analytics result.

Do not mark recovery complete because the Databricks job alone says `Succeeded`. The data-quality gates are the evidence that the published data passed its rules.

## Trace a dashboard number to its raw file

Trace the exact metric, filters, and grain. Do not start from a rounded tile value alone.

1. Identify the dashboard query and its `06-analytics` output or `05-gold` table. Record the keys, such as city or municipality, school year, school, and education level.
2. Recompute the value from the named Gold fact at the same grain. Use its validation SQL under `etl/05_gold/90_validate_*.sql` to see the reconciliation rule.
3. Follow the fact's keys to the published Silver table and, where used, its Integration map. The Gold build under `etl/05_gold/` names every input and join.
4. From the Silver row, copy `batch_id`, `source_sha256`, and `source_row_number`. Those values identify one Bronze row. Use the Silver build and gate under `etl/03_silver/` to see every cleaning, null, quarantine, and reconciliation rule.
5. Join `batch_id` to `ingestion_batches` to obtain the raw `archive_path`, file names, checksums, schema version, delivery version, and code revision. Verify the checksum against the source contract and source inventory.

For example, start from one city or municipality's `public_school_enrollment` in AP1. List the Gold fact rows behind it; `etl/06_analytics/01_answer_ap1.sql` sums the offered levels of the active public schools whose offered levels all have a `learner_count`:

```sql
SELECT a.city_mun_psgc_code, a.city_mun_name, a.public_school_enrollment,
       f.school_id, f.education_level_code, f.is_offered, f.learner_count
FROM edu_access.`06-analytics`.ap1_school_provision AS a
JOIN edu_access.`05-gold`.fact_school_enrollment AS f
  ON f.city_mun_psgc_code = a.city_mun_psgc_code AND f.school_year = a.school_year
 AND f.sector = 'Public' AND f.psgc_match_status = 'matched'
WHERE a.city_mun_psgc_code = '<city-mun-psgc-code>'
ORDER BY f.school_id, f.education_level_code;
```

Then trace one of those fact rows to its Silver row, the map row that placed it, and its Bronze batch:

```sql
SELECT f.school_id, f.school_year, f.education_level_code, f.learner_count,
       m.psgc_code, m.match_status, m.match_method, m.reason, m.crosswalk_batch_id,
       s.batch_id, s.source_sha256, s.source_row_number,
       b.archive_path, b.archive_name, b.source_file, b.archive_sha256,
       b.schema_version, b.delivery_version, b.code_revision
FROM edu_access.`05-gold`.fact_school_enrollment AS f
JOIN edu_access.`03-silver`.deped_enrollment_clean AS s
  ON s.school_id = f.school_id AND s.school_year = f.school_year
JOIN edu_access.`04-integration`.deped_school_psgc_map AS m
  ON m.school_id = f.school_id AND m.school_year = f.school_year AND m.geographic_level = 'city_mun'
JOIN edu_access.`01-control`.ingestion_batches AS b ON b.batch_id = s.batch_id
WHERE f.school_id = '<school-id>'
  AND f.school_year = '<school-year>'
  AND f.education_level_code = '<ES-JHS-or-SHS>';
```

`archive_path` is relative to the landing root, `/Volumes/edu_access/00-source/raw` on `dev`.

Then inspect the exact Bronze row without copying its values into `data_quality_results`:

```sql
SELECT *
FROM edu_access.`02-bronze`.deped_enrollment_raw
WHERE source_sha256 = '<source-sha256>' AND source_row_number = <source-row-number>;
```

## End-to-end rehearsal

The recorded rehearsal for this runbook is [2026-10-20 failure recovery](../../evidence/pipeline-runs/2026-10-20-failure-recovery-local.md). It uses only made-up data and an isolated local DuckDB database. It demonstrates detection, diagnosis, impact containment, recovery, verification, and a same-input rerun across every published Silver, Integration, Gold, and Analytics table without using Databricks compute. The recorded same-input rerun on Databricks `dev`, source to Gold, is [2026-10-20 Gold on dev](../../evidence/pipeline-runs/2026-10-20-gold-databricks-dev.md).
