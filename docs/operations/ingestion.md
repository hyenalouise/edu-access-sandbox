# Ingestion: Source → Control → Bronze

How raw files become Bronze rows, how to add the next delivery, and how to check that it worked. The DepEd sources use ZIP deliveries: `deped_enrollment` was first, `deped_facilities` second, and `deped_personnel` third. Personnel uses the same ingestion code with its own contract, generated SQL, tests, and job lane. `psa_poverty_stat` is the first workbook source: same pipeline, a second delivery format ([PSA Poverty Stat](#psa-poverty-stat-xlsx-workbook) below). `psa_psgc` uses `xlsx_table`: one workbook per publication quarter ([PSA PSGC](#psa-psgc-xlsx-workbook-one-per-quarter) below). `hdx_boundaries` (ADM3) uses `geojson_features`: one GeoJSON file per boundary edition ([Administrative boundaries](#administrative-boundaries-cod-ab-adm3-geojson) below).

**Status:** the current `edu_access_pipeline` was verified on Databricks `dev` for all six Bronze sources. `deped_personnel` passed local real-file validation and its create, load, and gate tasks were confirmed on Databricks `dev` at commit `15fcecbd` ([evidence](../../evidence/pipeline-runs/2026-10-09-deped-personnel-databricks-idempotency.md)). The source cards and evidence files record the uploaded files, tables, and completed runs.

## The flow

```
DepEd download page                         (official zip, one per school year)
   │  download by hand; never modify
   ▼
00 Source   /Volumes/edu_access/00-source/raw/deped/[<download date>/]<original name>.zip
   │  discover → checksum → is it an approved delivery?   (config/ingestion/deped_enrollment.json)
   ▼
01 Control  pipeline_runs · ingestion_batches · ingestion_batch_attempts · data_quality_results
   │  validate → MERGE into Bronze → reconcile → mark the batch succeeded   (Python task)
   │  → Bronze gate, 90_validate_<table>_raw.sql                             (its own SQL task)
   ▼
02 Bronze   edu_access.`02-bronze`.deped_enrollment_raw     (all years, all versions, text, with provenance)
   │
   ▼  Silver reads only batches listed in `01-control`.current_batches
```

Code: `src/ingestion/` ([module list](../../src/ingestion/README.md)). SQL: `etl/01_control/`, `etl/02_bronze/`. Contract: `config/ingestion/` ([how to approve a delivery](../../config/ingestion/README.md)). Decisions: D-014 to D-017 in [decisions.md](../governance/decisions.md).

## The nine questions, for `deped_enrollment`

| Question | Answer |
|---|---|
| What is ingested? | Every row of sheet `2023_NoHUC_Maguindanao grouped` (used range A1:S1641, 1,641 rows), so no worksheet row is dropped: the title (row 1), the 4 header rows, the 1,630 body rows (Excel rows 6 to 1635: 1,612 city/municipality rows and 18 region banner rows), and the 6 footer rows (notes and source line). Each row is labelled by `source_row_kind`; only `unit` rows are data. Column S is in the used range but empty, and checked, not loaded |
| How often does it arrive? | Yearly, one zip per school year (SY 2025-26 was added 2026-07-23). DepEd also re-uploads published years (2025-10-15) |
| What identifies a new delivery? | An archive SHA-256 not seen before |
| What shows a delivery changed? | The same school year (from the file names) with a different SHA-256 |
| Has this exact file been processed? | `ingestion_batches.status = 'succeeded'` for its `archive_sha256` |
| Are previous versions kept? | Yes, in Source (never overwritten; later downloads in dated subfolders, D-016) and in Bronze (`delivery_version`, D-015) |
| Is the delivery valid? | The checks under [Validation](#validation) |
| Can it be rerun safely? | Yes: a succeeded file is skipped, and a forced rerun inserts nothing |
| Where did each row come from? | Its provenance columns, joined to `ingestion_batches` and `pipeline_runs` |

The DepEd files have no `updated_at` or change column, so none is invented: the file checksum is the change signal. The source is an official download, so there is no scraping and no API (official download → API → database → scraping).

## Identity

| Level | Identified by | Why |
|---|---|---|
| Delivery (batch) | `archive_sha256`; `batch_id` = `<source_id>__<school_year>__<archive_sha256[:12]>` | The same bytes always get the same batch, wherever the file sits |
| Logical period | `source_id` + `school_year` + `delivery_version` | A revised file is version 2 of the same school year, never a silent replacement |
| Bronze row | `source_sha256` (the CSV's checksum) + `source_row_number` | A rerun inserts nothing. A re-zipped copy of the same CSV inserts nothing. Publisher duplicates have different row numbers, so all are kept |
| Schema | `schema_version` + `schema_fingerprint` (SHA-256 of the ordered column names) | Any rename, addition, or reorder changes the fingerprint |
| Code | `code_revision` | The commit that ran ([below](#code_revision)) |

The school year is read from both the archive name (`Enrollment-in-SY-2025-2026.zip`) and the CSV name (`enrollment_2025-26.csv`); they must agree with each other and with the approved entry.

## Storage layout

Raw files are kept exactly as downloaded and are never overwritten (D-016, provisional). The first downloads are in the publisher folder; any later download goes into a dated subfolder:

```
/Volumes/edu_access/00-source/raw/
└── deped/
    ├── Enrollment-in-SY-2023-2024.zip      first downloads, uploaded 2026-09-30
    ├── Enrollment-in-SY-2024-2025.zip
    ├── Enrollment-in-SY-2025-2026.zip
    ├── SHA256SUMS.txt                      covers every file in this folder
    ├── ...                                 other DepEd sources
    └── 2027-08-15/                         a later download (example date)
        ├── Enrollment-in-SY-2026-2027.zip
        └── SHA256SUMS.txt
```

A re-download of a published file therefore sits beside the earlier one. The pipeline searches `raw/deped/` at any depth and identifies files by checksum, so the layout does not matter to it, and it also works with the flat local layout used for profiling (`raw-data/deped/original/`).

## Validation

Before anything is written to Bronze (`src/ingestion/validate.py`):

| Check | On failure |
|---|---|
| Archive exists and is an approved delivery (by SHA-256) | `blocked`: `unregistered_delivery`, or `checksum_mismatch` if the name is approved but the bytes are not |
| Archive opens; no `..`, absolute, symbolic-link, or encrypted members; under the size limit | `failed`: `corrupt_archive`, `unsafe_member`, `archive_too_large` |
| Exactly one data file and the expected `README.md`; nothing else | `failed`: `missing_data_member`, `missing_document_member`, `unexpected_member` |
| CSV and README checksums match the approved entry | `failed`: `member_checksum_mismatch`, `document_checksum_mismatch` |
| School year agrees across archive name, CSV name, and approval | `failed`: `school_year_mismatch` |
| CSV decodes strictly with the approved encoding | `failed`: `encoding_mismatch` |
| Every row has as many fields as the header | `failed`: `ragged_row` |
| Header equals a known schema version, and the approved one | `failed`: `unknown_schema_drift`, `schema_version_mismatch` |
| Row count is nonzero and equals the approved count | FAIL → `failed`, nothing loaded |
| `school_id` is never blank | FAIL → `failed`, nothing loaded |
| `school_id` is 6 digits; unique in the file; no fully repeated rows | WARN: recorded, rows loaded as received |

After the MERGE, before the batch is marked succeeded (`bronze.reconcile`): Bronze rows for the file equal the source rows, no row number appears twice, row numbers run 1..n, and no provenance column is NULL. Then the Bronze gate (`etl/02_bronze/90_validate_deped_enrollment_raw.sql`) checks the whole table. In the job it is its own SQL task right after the load (the load runs with `--no-gate`), and it fails that task on any FAIL it records; run by hand without `--no-gate`, `ingest` runs it itself and fails the run.

Each run also records `approved_deliveries_present`: a WARN naming any approved zip that is not in the landing folder.

### Schema versions

| Version | School years | Columns | Encoding |
|---|---|---|---|
| `v1` | 2023-24, 2024-25 | 78 | UTF-8, LF |
| `v2` | 2025-26 | 83: v1 plus `Modified Curricular Offering Classification` (undocumented) and four `g11_sshs_*` | Windows-1252, CRLF |

The SY 2025-26 changes are expected because they are documented in the [profile](../data/source-inventory/deped_enrollment/profile.md) (O-6 to O-8). Any other header stops the batch. To accept a real change, add a schema version to the contract in a pull request; Bronze then gains the new columns (`ALTER TABLE ... ADD COLUMN`), never from a file directly.

## Bronze

`edu_access.`02-bronze`.deped_enrollment_raw`: one table, all school years and versions.

- Every publisher column, as text, exactly as received. A blank stays `''`; a column the year's file does not have is `NULL`. No trimming, relabeling (`True`/`Yes` stay as they are), typing, or deduplication.
- The column name with spaces is kept as is, which needs Delta column mapping (`delta.columnMapping.mode = 'name'`).

Provenance columns on every row:

| Column | Meaning |
|---|---|
| `source_id`, `source_system`, `source_url` | From the registry (`config/sources.json`) |
| `school_year`, `delivery_version` | The period and which delivery of it |
| `source_archive`, `source_archive_sha256` | The zip |
| `source_file`, `source_sha256`, `source_row_number` | The CSV inside it and the row's position (data rows from 1) |
| `schema_version`, `schema_fingerprint` | Which header it had |
| `batch_id`, `run_id`, `ingested_at_utc` | The batch and the run that inserted the row |
| `code_revision` | The commit that inserted the row |

### Two kinds of duplicate

| Kind | Example | Handling |
|---|---|---|
| Pipeline duplicate | The same file loaded twice | Prevented: the insert-only MERGE on `(source_sha256, source_row_number)`; checked by `no_pipeline_duplicates` |
| Source duplicate | DepEd lists one school twice | Kept: both rows in Bronze as evidence, flagged WARN (`school_id_unique_in_file`, `duplicate_rows_in_file`); Silver decides |

## Control tables

See [etl/01_control/README.md](../../etl/01_control/README.md). Batch statuses: `validating` → `loading` → `succeeded`; or `failed`, `blocked`, `skipped`. **`succeeded` is written last.** Delta commits one table at a time, so Bronze and the batch status cannot change together; instead, downstream reads only batches in `current_batches`, and a batch reaches that view only after its rows are reconciled.

## Retry, rerun, backfill, revision

| Term | Meaning | What to do | What happens |
|---|---|---|---|
| **Skip** | Same file, already succeeded | Nothing: any run | Attempt logged `skip`; 0 rows |
| **Retry** | Repeat a failed or interrupted batch | Fix the cause, run again | Batch is picked up automatically; the MERGE adds only missing rows; `attempt_count` goes up |
| **Rerun** | Repeat a succeeded batch on purpose | `--rerun <batch_id>` | Validated, merged (adds 0 rows), reconciled again |
| **Backfill** | An older school year arrives later | Approve it and upload it | `load_type = backfill`; other years untouched |
| **Revision** | A changed file for a loaded school year | Approve it as the next `delivery_version` with `supersedes` | Before approval: `blocked`. After: loaded beside version 1; `current_batches` points to the new version |

## Failure and recovery

| Failure | What the pipeline does | What you do |
|---|---|---|
| Approved zip missing from landing | WARN `approved_deliveries_present`, naming it | Upload it (#10) |
| Checksum differs from approval | `blocked` `checksum_mismatch`; run fails (exit 1) | Damaged: download again. Revised: approve as the next version |
| Unknown zip | `blocked` `unregistered_delivery` | Profile it, approve it |
| Corrupt zip, unsafe path, missing or extra member | `failed`, nothing loaded | Inspect the file; tell the publisher if needed |
| Wrong or unknown encoding | `failed` `encoding_mismatch`, nothing loaded | Re-profile; correct the approved encoding |
| Undocumented schema change | `failed` `unknown_schema_drift`, nothing loaded | Profile it; add a schema version |
| Empty file, wrong row count, blank `school_id` | FAIL check, `failed`, nothing loaded | Check the file against the source card |
| Process dies mid-load | Batch stays `loading`; downstream cannot see it | Run again: it is retried and completed |
| Bronze write incomplete | Reconciliation FAIL; batch `failed`, not current | Run again: the MERGE adds the missing rows only |
| Same file loaded twice | Skipped; nothing inserted | Nothing |
| Not a full commit on Databricks | Exit 2 `code_revision_required` before anything runs | Deploy from a clean, pushed `main` |
| No Spark or workspace | Exit 3 `store_unavailable` | Run locally, or fix the login (`databricks auth login --profile reached-hq`) |
| `prod` with a source that is not `accepted` | Exit 2 `source_not_accepted` | Use `dev` until the team accepts the source |

Exit codes: 0 everything loaded or already loaded; 1 a batch failed or was blocked, or the gate failed; 2 configuration; 3 environment.

## Running locally

From the repository root, with the virtual environment active ([terminal-setup.md](../getting-started/terminal-setup.md)):

```bash
python -m pytest tests -q
```

```bash
RAW_DATA_DIR=~/Projects/reached-hq/raw-data python -m src.ingestion.cli ingest --source deped_enrollment
```

```bash
python -m src.ingestion.cli status --source deped_enrollment
```

To run the whole job as Databricks would, every task of `databricks.yml` in order (including the gates as separate SQL steps):

```bash
RAW_DATA_DIR=~/Projects/reached-hq/raw-data python -m src.job.local_run
```

Tables go to `local_state/edu_access.duckdb` (git-ignored); delete the file to start over. Results from 2026-10-06 on the three real files: 60,167 + 60,129 + 60,204 rows loaded in about 7 seconds, all checks PASS; the second run skipped all three and inserted nothing.

After changing a schema version in the contract, regenerate the Bronze DDL and gate (a test fails until you do):

```bash
python -m src.ingestion.cli ddl --source deped_enrollment > etl/02_bronze/01_create_deped_enrollment_raw.sql
```

```bash
python -m src.ingestion.cli gate --source deped_enrollment > etl/02_bronze/90_validate_deped_enrollment_raw.sql
```

### Adding another source shaped like these (a zip with one CSV and a README)

1. Write `config/ingestion/<source_id>.json`: file-name patterns, the column list as a schema version, and the approved deliveries copied from the source card ([config/ingestion/README.md](../../config/ingestion/README.md)).
2. Generate `etl/02_bronze/01_create_<source_id>_raw.sql` and `90_validate_<source_id>_raw.sql` with the two commands above.
3. Add the publisher's file names to `NAMES` in `tests/factories/deped_deliveries.py` and a test that loads a made-up delivery (see `tests/test_ingestion_facilities.py`).
4. Add a source lane to `edu_access_pipeline` in `databricks.yml`: its raw-table DDL depends only on `05_create_current_batches`, its load (`ingest --no-gate --no-setup`) depends only on that DDL, and its Bronze gate runs `etl/02_bronze/90_validate_<source_id>_raw.sql` after the load. `--no-setup` prevents parallel loaders from repeating the shared DDL that the explicit SQL tasks already ran. Continue the source's Silver tasks in the same lane. All source DDL tasks therefore fan out together after control setup, without cross-source dependencies. `tests/test_bundle.py` checks this fan-out and that every load is followed by its own gate.
5. Load the real file locally and compare with the source card, then open the pull request, run the job twice on `dev`, and record the evidence.

## Running on Databricks

**Current job: `edu_access_pipeline` (D-020).** Last confirmed on 2026-10-08 at `bb040a9`: two dev runs, every enabled task succeeded, neither inserted rows (every file was already loaded, so both skipped), and every Bronze gate passed and joined to its load ([evidence](../../evidence/pipeline-runs/2026-10-08-pipeline-dag-databricks-idempotency.md)). The runs under [First Databricks run](#first-databricks-run) are earlier, source-specific evidence from the `bronze_ingest` job. These are the steps for the deliberate confirmation run (D-008). They need: the `reached-hq` CLI profile, the raw files in the volume, the commit pushed to GitHub, and the run announced to the team (workflow, Part 5).

1. Raw files. The three enrollment zips are already in `/Volumes/edu_access/00-source/raw/deped/` (checked 2026-10-06: sizes match the source card, and the folder's `SHA256SUMS.txt` lists the approved checksums). The first run hashes every zip itself, so a damaged upload is blocked, not loaded. For a later download, list the folder first, then upload into a new dated folder, never over an existing file:

   ```bash
   databricks fs ls dbfs:/Volumes/edu_access/00-source/raw/deped/ --profile reached-hq
   ```

   ```bash
   databricks fs cp "$RAW_DATA_DIR/deped/original/Enrollment-in-SY-2026-2027.zip" dbfs:/Volumes/edu_access/00-source/raw/deped/2027-08-15/ --profile reached-hq
   ```

   Then upload that folder's `SHA256SUMS.txt`.

2. Deploy from a clean checkout of a pushed commit: the pull request branch for the confirmation run, `main` afterwards. `${bundle.git.commit}` is `HEAD`, and the job clones that commit from GitHub:

   ```bash
   git switch main && git pull --ff-only && git status --short
   ```

   ```bash
   databricks bundle validate --target dev --profile reached-hq
   ```

   ```bash
   databricks bundle deploy --target dev --profile reached-hq
   ```

3. Confirm what was deployed: in the job (`[dev <user>] edu_access_pipeline`; `[dev <user>] bronze_ingest` before #47), `git_source.git_commit` and the `code_revision` parameter must both equal `git rev-parse HEAD`:

   ```bash
   databricks bundle summary --target dev --profile reached-hq
   ```

4. Run it twice. The second run must skip every file and insert no rows:

   ```bash
   databricks bundle run edu_access_pipeline --target dev --profile reached-hq
   ```

5. Check the results with the queries below ("A load's true outcome" shows each load with its gate), and record the run as evidence in `evidence/pipeline-runs/`.

Before step 4, stop other serverless compute: detach notebooks and leave the SQL warehouse stopped (the job starts it for its SQL tasks), and do not query it while the job runs. On Free Edition a job waits until serverless capacity is free; the first run waited 35 minutes for 3.5 minutes of work. Check the results after the run ends.

`databricks bundle validate` was last run on 2026-10-08 at `bb040a9` and passed; both commit values resolved to the same SHA.

### First Databricks run

Historical: these runs used the earlier `bronze_ingest` job (one Python task per source, one after another, with the gate inside the load). They show each source's load on Databricks, not the current DAG; for that, see the [2026-10-08 evidence](../../evidence/pipeline-runs/2026-10-08-pipeline-dag-databricks-idempotency.md).

Evidence for both runs, with the queries and their results: [evidence/2026-10-06-deped-enrollment-idempotency.md](../../evidence/pipeline-runs/2026-10-06-deped-enrollment-idempotency.md).

Facilities, the second source, was loaded and rerun the same day at commit `acec94d` (rebased counterpart `9bcdb12`): 60,167 rows, then a skip, with enrollment untouched ([evidence](../../evidence/pipeline-runs/2026-10-06-deped-facilities-idempotency.md)). With the SQL warehouse stopped and notebooks detached, the whole job took 3 min 41 s, then 1 min 52 s: it did not wait for capacity.

Times here are Manila time (UTC+8), with UTC in brackets where it helps. Timestamps in the tables are stored in UTC (`*_utc` columns); convert them for display with `from_utc_timestamp(col, 'Asia/Manila')`.

Run 1: 2026-10-06 Manila (2026-10-05 UTC), `dev`, job `[dev cheimlouise] bronze_ingest`, run `738752819100453`, commit `e681c5b` (rebased counterpart `a55e6e9`):

- Loaded 60,167 + 60,129 + 60,204 rows (initial, incremental, incremental), as reported by the job; the task ended `SUCCESS`. This confirms behavior 4 below (zips read from `/Volumes/`) and that the job runs without `__file__` and exits cleanly.
- It took 39 minutes (2,327 s), against about 7 seconds locally. The run's own timestamps show where: the job started at 01:21:37 Manila (17:21:37 UTC), the pipeline wrote its run row at 01:57:46, and the job ended at 02:00:42. The job was waiting for compute: the serverless cluster's ID (`1005-175705-…`) shows it started at 01:57:05 Manila (17:57:05 UTC), 35.5 minutes after the job, and `DESCRIBE HISTORY` shows `pipeline_runs` created at 01:57:34. Free Edition's serverless capacity was in use elsewhere (the SQL warehouse reported `RESOURCE_EXHAUSTED` at the time), most likely by a notebook. Once it had compute, discovery, loading all 180,500 rows, reconciliation, and the gate took about 3.5 minutes; each small control-table write took 3 to 13 seconds.
- Two problems found and fixed: the first deploy was rejected until the task declared `source: GIT`; and the tables were owned by the account that deployed the job, so nobody else could read them. Ownership of the six objects was moved to `reached-hq`, and every `CREATE` in `etl/` is now followed by `OWNER TO `reached-hq`` (D-009).
- Verified the same day in a notebook, by a different account in the `reached-hq` group (the SQL warehouse could not start while other serverless compute was running: Free Edition's limit). Every check matched: rows 60,167 / 60,129 / 60,204; 0 pipeline duplicates; 0 rows missing provenance; 0 rows from another commit; 5,203 blank street addresses kept blank in SY 2023-24; the v2-only column NULL in all 120,296 v1-year rows; 595 SY 2025-26 rows with "ñ"; 3 batches succeeded and reconciled; 37 checks recorded, none other than PASS; 1 run succeeded in `dev`. `delta.columnMapping.mode` is `name`. The same numbers as the local load.
- Run 2, 2026-10-06 02:30 Manila (18:30 UTC), `1088383272500634`, commit `d931112` (rebased counterpart `96b27f0`), the same files: all three batches `skip`, 0 rows inserted, run `succeeded`, task `SUCCESS`, 9.5 minutes, of which 7.6 waiting for compute (cluster started 02:38:04 Manila) and 1.8 working. Verified in the tables: the attempts log shows `load` for each file in run 1 and `skip` in run 2; Bronze still has 180,500 rows, 0 pipeline duplicates, and every row from run 1; 2 succeeded runs; no check other than PASS. Every object, and both schemas, still belongs to `reached-hq` after the run re-applied ownership.

### Validation queries (Databricks SQL editor)

```sql
-- Every batch and its state
SELECT batch_id, school_year, delivery_version, load_type, status, attempt_count, expected_rows, source_rows, bronze_rows, error_code
FROM edu_access.`01-control`.ingestion_batches WHERE source_id = 'deped_enrollment' ORDER BY school_year, delivery_version;

-- What happened, run by run (proves skips)
SELECT r.started_at_utc, r.status, a.batch_id, a.action, a.outcome, a.rows_inserted, a.code_revision
FROM edu_access.`01-control`.ingestion_batch_attempts AS a JOIN edu_access.`01-control`.pipeline_runs AS r USING (run_id)
ORDER BY r.started_at_utc, a.batch_id;

-- Row counts reconcile to the approved files: expect 60,167 / 60,129 / 60,204
SELECT school_year, delivery_version, COUNT(*) AS rows FROM edu_access.`02-bronze`.deped_enrollment_raw GROUP BY ALL ORDER BY 1, 2;

-- No pipeline duplicates: expect 0
SELECT COUNT(*) - COUNT(DISTINCT source_sha256, source_row_number) FROM edu_access.`02-bronze`.deped_enrollment_raw;

-- Where one row came from
SELECT source_archive, source_file, source_sha256, source_row_number, batch_id, run_id, ingested_at_utc, code_revision
FROM edu_access.`02-bronze`.deped_enrollment_raw WHERE school_year = '2025-26' AND source_row_number = 1;

-- Checks for the latest job run: expect no FAIL. Each load writes its batch checks under its own
-- run_id, and each Bronze gate task and Silver gate task writes under the job run id (D-020), so read both
WITH latest AS (SELECT MAX_BY(job_run_id, started_at_utc) AS job_run_id FROM edu_access.`01-control`.pipeline_runs WHERE job_run_id IS NOT NULL)
SELECT source_id, check_name, status, expected, actual FROM edu_access.`01-control`.data_quality_results
WHERE run_id IN (SELECT job_run_id FROM latest
                 UNION ALL SELECT run_id FROM edu_access.`01-control`.pipeline_runs WHERE job_run_id = (SELECT job_run_id FROM latest))
ORDER BY source_id, status, check_name;

-- A load's true outcome: pipeline_runs alone can say succeeded when its gate task failed.
-- gate_checks = 0 for a job run means its gate task has not run (a manual run gates inside the load)
-- Loads only: a silver_build row's run_id is the job run id, so it would join to the Bronze gate's checks
SELECT r.source_id, r.started_at_utc, r.status AS load_status, r.job_run_id,
       COUNT_IF(q.run_id = r.job_run_id) AS gate_checks,
       COUNT_IF(q.status = 'FAIL') AS failed_checks, COUNT_IF(q.status = 'WARN') AS warned_checks
FROM edu_access.`01-control`.pipeline_runs AS r
LEFT JOIN edu_access.`01-control`.data_quality_results AS q
  ON q.run_id IN (r.run_id, r.job_run_id) AND q.source_id = r.source_id AND q.layer = 'bronze'
WHERE r.pipeline_name = 'bronze_ingest'
GROUP BY ALL ORDER BY r.started_at_utc DESC;

-- Column mapping is on (needed for the column name with spaces)
SHOW TBLPROPERTIES edu_access.`02-bronze`.deped_enrollment_raw ('delta.columnMapping.mode');
```

All checks in one query, each marked `OK` or `CHECK`. The expected values are for the three approved deliveries after one loading run; replace the commit with the one that loaded them:

```sql
WITH r AS (SELECT * FROM edu_access.`02-bronze`.deped_enrollment_raw),
     b AS (SELECT * FROM edu_access.`01-control`.ingestion_batches),
     q AS (SELECT * FROM edu_access.`01-control`.data_quality_results),
     p AS (SELECT * FROM edu_access.`01-control`.pipeline_runs),
checks AS (
  SELECT 'rows SY 2023-24' AS check_name, '60167' AS expected, CAST(COUNT_IF(school_year = '2023-24') AS STRING) AS actual FROM r
  UNION ALL SELECT 'rows SY 2024-25', '60129', CAST(COUNT_IF(school_year = '2024-25') AS STRING) FROM r
  UNION ALL SELECT 'rows SY 2025-26', '60204', CAST(COUNT_IF(school_year = '2025-26') AS STRING) FROM r
  UNION ALL SELECT 'pipeline duplicates', '0', CAST(COUNT(*) - COUNT(DISTINCT source_sha256, source_row_number) AS STRING) FROM r
  UNION ALL SELECT 'rows missing provenance', '0', CAST(COUNT_IF(source_sha256 IS NULL OR source_row_number IS NULL OR batch_id IS NULL OR run_id IS NULL OR code_revision IS NULL) AS STRING) FROM r
  UNION ALL SELECT 'rows from another commit', '0', CAST(COUNT_IF(code_revision <> 'e681c5bb62374e4ec5501f63c54c087f60e2651b') AS STRING) FROM r
  UNION ALL SELECT 'blank street_address kept blank, SY 2023-24', '5203', CAST(COUNT_IF(school_year = '2023-24' AND street_address = '') AS STRING) FROM r
  UNION ALL SELECT 'v2-only column NULL in v1 years', '120296', CAST(COUNT_IF(`Modified Curricular Offering Classification` IS NULL) AS STRING) FROM r
  UNION ALL SELECT 'SY 2025-26 rows with ñ', '595', CAST(COUNT_IF(school_year = '2025-26' AND (barangay LIKE '%ñ%' OR municipality LIKE '%ñ%' OR school_name LIKE '%ñ%')) AS STRING) FROM r
  UNION ALL SELECT 'batches succeeded and reconciled', '3', CAST(COUNT_IF(status = 'succeeded' AND source_rows = expected_rows AND bronze_rows = source_rows) AS STRING) FROM b
  UNION ALL SELECT 'checks that are not PASS', '0', CAST(COUNT_IF(status <> 'PASS') AS STRING) FROM q
  UNION ALL SELECT 'checks recorded', '37', CAST(COUNT(*) AS STRING) FROM q
  UNION ALL SELECT 'runs succeeded in dev with 3 loads', '1', CAST(COUNT_IF(status = 'succeeded' AND environment = 'dev' AND batches_loaded = 3) AS STRING) FROM p
)
SELECT check_name, expected, actual, CASE WHEN expected = actual THEN 'OK' ELSE 'CHECK' END AS result FROM checks;
```

### What only the Databricks run can prove (D-017)

Status after run 1: items 1, 3 (after handing the tables to the group), and 4 are confirmed; item 2 is not tested, because nothing failed.

1. Delta accepts `Modified Curricular Offering Classification` with column mapping.
2. The MERGE and the control writes behave as single-table commits.
3. The `reached-hq` group's Unity Catalog permissions allow the job to create and write the tables.
4. Python reads the zips from `/Volumes/...` paths on serverless compute.

Also to watch: `createDataFrame` of about 60,000 rows per year on serverless (Spark Connect), whether the job can clone the public repository without a Git credential, and whether the explicit Delta protocol versions in the Bronze DDL are accepted alongside the workspace's default table features.

Unity Catalog makes whoever creates a table its owner, and a `dev` job runs as whoever deployed it, so each object is handed to the team group right after it is created; `tests/test_bundle.py` checks every `CREATE` in `etl/`. Locally the ownership statements are skipped (DuckDB has no owners).

Three runtime differences are imitated locally in `tests/test_databricks_runtime.py`, because each would otherwise surface only on Databricks: a job's Python file runs with `exec` and no `__file__`; it runs inside IPython, which reports even `SystemExit(0)` as a failure, so the command line exits only on failure; and `spark.sql()` runs a `SELECT` only when collected, so the Spark store collects every statement (otherwise the Bronze gate's final check would never run).

## code_revision

Every Bronze row, control row, and check result records the commit that produced it.

- **Databricks:** the job parameter `code_revision` defaults to `${bundle.git.commit}`, the same substitution as `git_source.git_commit`, so the code that runs and the commit recorded cannot differ. The task passes it with `--code-revision`; the gate reads it as `:code_revision`. A job run without a full 40-character SHA stops before doing anything (exit 2).
- **Locally:** read from git; `-dirty` is added when there are uncommitted or untracked changes.
- **Unknown:** `UNSET`, the only spelling.

Rebasing or squash-merging a branch does not change a stored `code_revision`, and it can make that exact commit unreachable from the rewritten branch. Before rewriting a branch used for a Databricks run, either tag the run commit so it remains reachable or record the run SHA and its rebased or squashed counterpart in the evidence file. Never rewrite the stored revision: it identifies the code that actually ran.

`tests/test_bundle.py` fails if the job follows a branch, if the parameter or `git_commit` stops being `${bundle.git.commit}`, if a task stops passing it, or if any gate result stops reading `:code_revision`.

## Handoff to Silver

Bronze preserves; Silver cleans. **Built for `deped_enrollment`** (#85; [Silver](silver.md)), locally and on the real data, and on Databricks `dev` ([evidence](../../evidence/pipeline-runs/2026-10-09-deped-enrollment-silver.md)). As planned here, Silver:

- reads only rows whose `batch_id` is in `` `01-control`.current_batches `` (the latest succeeded version per school year);
- types the counts (all whole numbers, profile O-2) and keeps blanks as NULL, never 0;
- maps each year's labels to one set through a reviewed file (`True`/`Yes`, `DepEd`/`DepED Managed`, trailing spaces; profile O-8), and trims and collapses spaces in place names (profile O-5), recording affected counts;
- quarantines publisher duplicates of `school_id` rather than dropping them (none so far, profile O-1);
- keeps `batch_id`, `source_sha256`, and `source_row_number`, so every Silver row traces back to its Bronze row.

Silver's two SQL tasks run right after this source's Bronze gate task, only if it passed, and rebuild from `current_batches` on every run (D-025).

## Runbook

**1. How do I add a new DepEd school year?**
Download the zip from the official page; do not rename or open-and-save it. Profile it and update the source card (checksums, encoding, rows). Add the delivery to `config/ingestion/deped_enrollment.json` (and a schema version if the header changed; then regenerate the DDL), and merge the pull request. Upload the zip to `raw/deped/<download date>/`, never over an existing file. Run the job. An older year loads as `backfill`, a newer one as `incremental`; other years are untouched.

**2. How do I know whether it was already processed?**
`python -m src.ingestion.cli status --source deped_enrollment` locally, or the first validation query on Databricks. Look up the file's SHA-256: `succeeded` means processed.

**3. What happens if the publisher replaces a file?**
The new bytes do not match the approved checksum, so the batch is `blocked` (`checksum_mismatch`, `load_type = revision`) and the run fails; nothing is overwritten. If the change is real, approve it as `delivery_version: 2` with `supersedes` set to version 1's `archive_sha256`. Both versions stay in Bronze, and `current_batches` moves to version 2.

**4. How do I inspect a failed batch?**
`status` shows `error_code`. Then:

```sql
SELECT failure_stage, error_code, error_message, attempt_count, last_run_id
FROM edu_access.`01-control`.ingestion_batches WHERE status IN ('failed', 'blocked', 'loading');
```

and the checks for that batch in `data_quality_results` (`WHERE batch_id = '...'`). Messages hold counts and checksums, never row values.

**5. How do I safely rerun it?**
Fix the cause and run the same command again. A `failed` or `loading` batch is retried automatically and the MERGE adds only missing rows. To repeat a succeeded batch, add `--rerun <batch_id>`; it inserts nothing.

**6. How do I verify the Bronze output?**
Row counts per school year equal the approved `row_count` (third query); the run has no FAIL (sixth query); pick a row and trace it by its provenance columns to the file and line it came from.

**7. How do I prove the same batch did not create duplicates?**
Run the job twice. The attempts query shows `load` then `skip` with `rows_inserted = 0`, the row counts do not change, and the duplicate query returns 0. Locally, `tests/test_ingestion_pipeline.py::test_idempotency_demonstration` proves the same with made-up files.

## Limitations

- Not yet confirmed on Databricks (D-017 lists what only that run proves).
- A file named unlike `Enrollment-in-SY-YYYY-YYYY.zip` and not yet approved is not discovered; a renamed publisher file must be noticed by whoever downloads it.
- Approval is manual by design: a new year needs a profile update and a pull request before it loads.
- A revision reloads all rows of the school year (about 60,000), even if one value changed.
- No `prod` target yet; `dev` is the only deploy target.
- SY 2017-18 to 2022-23 are published but not acquired; their headers are unknown and will likely need new schema versions.

## Open questions

| Question | Default until decided | Where |
|---|---|---|
| Should the latest version of a school year always be current, or do revisions need review first? | Latest succeeded version | D-015 |
| Are per-publisher raw folders enough, given #10 asked for one folder per source? | First downloads flat in `raw/deped/`, later ones in dated subfolders | D-016 |
| When is a `prod` target added, and how is its data kept apart from `dev`? There is one workspace and one catalog, and `edu_access` is hardcoded in the SQL and `store.py` | `dev` only | Before #47 |
| How long are superseded versions kept in Bronze and Source? | Forever | Not yet logged |
| Who can approve a delivery, and does `deped_enrollment` move to `accepted` before a `prod` target exists? | Any reviewer; stays `profiled` | Team |
| Should a blank `school_id` fail the whole year, or be quarantined in Silver? | Fail the batch (none observed) | Profile O-1 |
| Does DepEd publish the promised school ID mapping file, and should it be a delivery member? | Unexpected members fail the batch | Source card |

## PSA Poverty Stat (xlsx workbook)

`psa_poverty_stat` loads through the same pipeline as DepEd, from its own contract, `config/ingestion/psa_poverty_stat.json` (`format: xlsx_sheet`). What differs is in `src/ingestion/workbook.py` (reading and checking the workbook) and `src/ingestion/formats.py` (period, versions, load type). Decision: D-018.

**Status:** implemented and tested locally with made-up workbooks (`tests/test_ingestion_psa.py`), and **verified locally on the real workbook** on 2026-10-07: every layout check passed, 1,641 rows loaded (1,612 unit, 18 region_banner, 1 title, 4 header, 6 footer), every known-issue count equal to the profile, and a second run skipped it ([evidence](../../evidence/pipeline-runs/2026-10-07-psa-poverty-stat-local-idempotency.md#real-workbook-local-duckdb)). **On Databricks `dev`**, its lane in `edu_access_pipeline` (D-020, #113) ran in four job runs on 2026-10-08: each skipped the workbook (already in Bronze, 1,641 rows), inserted 0, and its Bronze gate task passed (3 checks, 0 FAIL), joined to the load through `job_run_id` ([evidence](../../evidence/pipeline-runs/2026-10-08-pipeline-dag-databricks-idempotency.md)). The run that first loaded the workbook into `dev` is not recorded as evidence: those skip runs show the lane and the Bronze gate on Databricks, not its first-load path. The source stays `profiled`. Its Silver build and gate now continue the lane ([Silver, PSA Poverty Stat](silver.md#psa-poverty-stat), D-034); they are tested locally and ran twice on Databricks `dev` on 2026-10-09 ([Silver evidence](../../evidence/reconciliation/2026-10-09-psa-poverty-stat-bronze-to-silver.md)).

### The flow

```
psa.gov.ph stat-tables page                (official xlsx; no API, no scraping)
   │  download by hand; never modify, never re-save in Excel
   ▼
00 Source   /Volumes/edu_access/00-source/raw/psa/[<download date>/]2_2023 SAE_with PSGC_noHUC_06Feb2026.xlsx
   │  discover *SAE*.xlsx → SHA-256 → approved?   (config/ingestion/psa_poverty_stat.json)
   ▼
   │  open safely → expected sheet only → header names from the merged header → schema version
   │  → estimate years from the header → footer 'Notes:' → every row 1..1641 labelled title / header /
   │    unit / region_banner / footer
01 Control  pipeline_runs · ingestion_batches (+ logical_dataset, estimate_years_covered, source_sheet)
   │        · ingestion_batch_attempts · data_quality_results
   │  checks (FAIL blocks; WARN records) → MERGE → reconcile (rows, units, banners) → succeeded
   │  → Bronze gate: in the job, its own SQL task 90_validate_psa_poverty_stat_raw (D-020)
   ▼
02 Bronze   edu_access.`02-bronze`.psa_poverty_stat_raw   (1,641 rows per delivery: the whole sheet, text, with provenance)
   │
   ▼  Silver reads only batches in `01-control`.current_batches
```

### The nine questions

| Question | Answer |
|---|---|
| What is ingested? | Sheet `2023_NoHUC_Maguindanao grouped` of the approved workbook: the whole used range, all 1,641 rows (1 title, 4 header, 1,612 city/municipality `unit` rows, 18 `region_banner` rows, 6 footer rows), each labelled by `source_row_kind` (D-018). Only `unit` rows become Silver estimates |
| How often does it arrive? | UNVERIFIED. One workbook so far, covering 2018, 2021 and 2023 (released 2026-02-06). Treated as an irregular batch, never as a stream |
| What identifies a new delivery? | A workbook SHA-256 not seen before |
| What shows a delivery changed? | The same file name (or estimate years already loaded) with a different SHA-256. There is no `updated_at` in the workbook, and none is invented |
| Has this exact file been processed? | `ingestion_batches.status = 'succeeded'` for its `archive_sha256` (the workbook's) |
| Are previous versions kept? | Yes: in Source (no overwrite, D-016) and in Bronze (`delivery_version` per `logical_dataset`, D-015, D-018) |
| Is the delivery valid? | The checks under [PSA validation](#psa-validation) |
| Can it be rerun safely? | Yes: a succeeded workbook is skipped; a forced rerun inserts nothing |
| Where did each row come from? | `source_file`, `source_sha256`, `source_sheet`, `source_row_number` (the Excel row), plus `batch_id`, `run_id`, `code_revision` |

### Identity

| Level | Identified by | Why |
|---|---|---|
| Delivery (batch) | Workbook SHA-256; `batch_id` = `psa_poverty_stat__2018-2021-2023__<sha[:12]>` | Same bytes, same batch, wherever the file sits |
| Logical period | `logical_dataset` + `delivery_version` (e.g. `sae_city_municipal_2018_2021_2023` v1) | One workbook covers three estimate years, so versions are counted per dataset, not per year |
| Estimate years | `estimate_years_covered` = `2018,2021,2023`, read from the header and checked against the approval | Delivery metadata. A wide row holds all three years; no row is given a single year |
| Bronze row | `source_sha256` + `source_row_number` (Excel row) | A rerun inserts nothing; repeated publisher rows (different Excel rows) are all kept. One sheet per approved workbook keeps the pair unique; loading a second sheet would need `source_sheet` in the key |
| Schema | `schema_version` + `schema_fingerprint` of the 18 built column names | Any renamed, added, or reordered header changes it |

Why not a hash of the row's content? Two identical publisher rows would merge into one, which is silent deduplication. Why not the file name? PSA can replace the file at the same URL and name.

### Layout as a versioned contract

Schema `v1` pins the layout the profile found (O-1), and anything else stops the batch:

| Element | Contract | On anything else |
|---|---|---|
| Sheets | Only `2023_NoHUC_Maguindanao grouped` | `missing_sheet` / `unexpected_sheet` (a new sheet may hold data) |
| Header | Rows 2 (group, merged across its columns), 4 (ID; Lower/Upper Limit), 5 (year) build 18 names that must equal `v1` exactly | `unknown_schema_drift`; groups not merged as profiled: `unexpected_header_layout` |
| Estimate years | From the column names: 2018, 2021, 2023, equal to the approval | `estimate_years_mismatch` |
| Used range | `A1:S1641`, as declared in the sheet | FAIL |
| Body | Row 6 to the row before `Notes:` in column A: 1,630 rows | `footer_not_found`; count FAIL |
| Row kinds | `unit` (has `PSGC ID`), `region_banner` (only `Region/Province`), `blank`, `unclassified` | Units 1,612 and banners 18 each reconciled; any `unclassified` row FAILs |
| Footer | 6 rows (1636 to 1641), loaded as `footer` | FAIL |
| Title and header | Row 1 (`title`) and rows 2 to 5 (`header`), loaded as received | Header drift stops the batch (above) |
| Column S | Empty and ignored; nothing right of it | FAIL |

### PSA validation

Before Bronze, in addition to the layout above:

| Check | Status |
|---|---|
| Workbook exists, approved by SHA-256 | `blocked` (`unregistered_delivery`; `checksum_mismatch` for an approved name with other bytes) |
| Opens as a zip without `..`, absolute, linked or encrypted parts, under 50 MB expanded; no XML DTD or entities | `failed` (`corrupt_archive`, `corrupt_workbook`, `unsafe_member`, `unsafe_workbook`, `archive_too_large`) |
| `PSGC ID` matches `[0-9]{5,6}` on every unit row (banners exempt) | FAIL |
| Units, banners, blank rows, body rows, footer rows equal the approval | FAIL |
| `PSGC ID` unique; no fully repeated rows | WARN, rows kept (source duplicates) |
| Non-numeric values in estimate columns; formula cells; error cells | WARN, rows kept |
| Known publisher issues (below) | WARN with the profiled count beside the actual count |

Known issues are flagged, never corrected, in Bronze:

| Check (`known_issue_…`) | Profiled | Finding | Bronze keeps |
|---|---|---|---|
| `psgc_id_leading_zero_lost` (ID shorter than 6 digits) | 1,073 | O-2 | `12801`, not `012801` |
| `unit_rows_without_estimates` (Kalayaan) | 1 | O-5 | 15 blanks `''`; never 0. Missing is not zero poverty |
| `province_label_continued` | 1 | O-3 | `(Continued)` as written |
| `lower_limit_zero_or_negative` | 3 | O-7 | `-2.4063453271442992E-2`, not clipped |
| `se_disagrees_with_cv_2018` / `_2021` / `_2023` (tolerance 0.05) | 6 / 133 / 1 | O-8 (2021: CALABARZON) | SE as published |
| `cv_over_20_2018` / `_2021` / `_2023` | 171 / 84 / 156 | O-9 | CV as published |

Values are the text stored in the file: numbers keep every stored digit (no rounding, no added precision), text keeps its Unicode, and labels and names are not standardized (61 differ from PSGC, O-10/X-1). Results hold counts only, never values.

After the MERGE: Bronze rows for the workbook equal the sheet's rows (1,641), Excel row numbers run 1..1641 with no repeats, every provenance column is filled, and the counts by `source_row_kind` equal the file's (`bronze_row_kinds_match_source`: title 1, header 4, unit 1,612, region_banner 18, footer 6). Then the generated gate (`etl/02_bronze/90_validate_psa_poverty_stat_raw.sql`) checks the whole table: in the job as its own SQL task right after the load (the load runs with `--no-gate`), and inside the load when `ingest` is run by hand.

### Bronze table

`edu_access.`02-bronze`.psa_poverty_stat_raw` (generated: `etl/02_bronze/05_create_psa_poverty_stat_raw.sql`): 17 provenance columns, then the 18 publisher columns as text. Poverty incidence is the percentage of **persons** below the poverty threshold (press release 2026-43), not of families or students. Each year's estimate keeps its CV, standard error, and both 90% limits in the same row.

| Provenance column | Meaning |
|---|---|
| `source_id`, `source_system`, `source_url` | From the registry |
| `logical_dataset`, `estimate_years_covered`, `delivery_version` | Which delivery, of which dataset, covering which years |
| `source_file`, `source_sha256`, `source_sheet`, `source_row_number` | The workbook, its checksum, the sheet, the Excel row |
| `source_row_kind` | `title`, `header`, `unit`, `region_banner`, `blank`, or `footer`, from the layout; changes no source column. Silver reads only `unit` rows as data |
| `schema_version`, `schema_fingerprint` | Which header it had |
| `batch_id`, `run_id`, `ingested_at_utc`, `code_revision` | The batch, the run, when, and the commit |

### Retry, rerun, backfill, revision (workbooks)

| Term | Example | What happens |
|---|---|---|
| Skip | The same workbook again | Attempt logged `skip`; 0 rows |
| Retry | A batch that failed (for example an approval with a wrong count, later fixed) or was interrupted | Picked up automatically; MERGE adds only missing rows |
| Rerun | `--rerun psa_poverty_stat__2018-2021-2023__303fb0e87bff` | Validated and merged again; 0 rows |
| Incremental | A workbook with only later years (e.g. 2025) | New `logical_dataset`, `load_type = incremental`; earlier rows untouched |
| Backfill | A workbook with only earlier years (e.g. 2015) | New `logical_dataset`, `load_type = backfill`; nothing rebuilt |
| Revised delivery | A changed workbook for years already loaded (same name, or overlapping years) | Before approval: `blocked`, `load_type = revision`, run fails, nothing overwritten. After approval as `delivery_version: 2` of the same `logical_dataset` with `supersedes`: loaded beside v1; `current_batches` points to v2. v2 must cover every estimate year of v1 (it may add years): `current_batches` keeps one version per dataset, so a dropped year would vanish from Silver. A v2 that drops a year is refused as `invalid_config` before anything runs |

The contract refuses two logical datasets that share an estimate year, so a workbook that republishes 2023 can only enter as a reviewed revision, never as a silent second copy of 2023. Whether a later release that adds a year (2018 to 2025, say) is a revision of the existing dataset or a new dataset is a team decision when it happens (open question below); until then the contract forces the question.

<a id="psa-running-locally"></a>
### Running locally

In VS Code's terminal, from the repository root, with the virtual environment active:

```bash
python -m pytest tests -q
```

```bash
python -m src.ingestion.cli ingest --source psa_poverty_stat
```

```bash
python -m src.ingestion.cli status --source psa_poverty_stat
```

`RAW_DATA_DIR` must be set in that terminal first ([terminal setup, Part 8](../getting-started/terminal-setup.md#part-8-raw-data-and-raw_data_dir)), or given with `--landing <raw root>`. The workbook must be under `$RAW_DATA_DIR/psa/` (for example `psa/original/`). Expected on the real file: one batch `load initial`, `inserted=1641 bronze=1641`, status `succeeded`, every FAIL-type check PASS and the known-issue WARNs at their profiled counts; the second run `skip`, `inserted=0`. If the first run reports `unexpected_header_layout`, `footer_rows_match_approved` or another layout FAIL, the profile's description of the layout and the real file differ: do not change the data, record what was found and adjust the contract in review.

Run by hand, `ingest` creates the control and Bronze tables itself and runs the Bronze gate inside the load. To run PSA Poverty Stat the way the job does (its own lane: `05_create_psa_poverty_stat_raw` → `bronze_psa_poverty_stat` with `--no-gate --no-setup` → `90_validate_psa_poverty_stat_raw`, beside the other sources), run the whole job locally ([src/job](../../src/job/README.md)):

```bash
python -m src.job.local_run
```

After changing the contract's schema, regenerate the SQL (a test fails until you do):

```bash
python -m src.ingestion.cli ddl --source psa_poverty_stat > etl/02_bronze/05_create_psa_poverty_stat_raw.sql
```

```bash
python -m src.ingestion.cli gate --source psa_poverty_stat > etl/02_bronze/90_validate_psa_poverty_stat_raw.sql
```

### Databricks confirmation (skip runs only)

**Skip runs done on 2026-10-08** (`dev`, job `edu_access_pipeline`, runs `129683751826546` and `871133851621812` at `819a248`, runs `471206277550325` and `374205222997457` at `bb040a9`): every run skipped the workbook (`already loaded; same SHA-256`), inserted 0, left Bronze at 1,641 rows, and passed the Bronze gate task (3 PASS, 0 FAIL, 0 WARN: a skip checks no batch) ([evidence](../../evidence/pipeline-runs/2026-10-08-pipeline-dag-databricks-idempotency.md)). The load path (validate, MERGE, reconcile) on Databricks, and the 10 known-issue WARNs, are shown only by the local runs; the run that first loaded the workbook into `dev` is not recorded as evidence. A Databricks run that loads it again needs a new approved delivery, or an empty `dev`.

In `edu_access_pipeline`, PSA Poverty Stat has its own lane: `05_create_psa_poverty_stat_raw` → `bronze_psa_poverty_stat` → `90_validate_psa_poverty_stat_raw` (D-020). It starts after the shared control setup and does not wait for any other source. Before running the job: the run is announced to the team (it touches the shared control tables), and the CLI profile `reached-hq` works. The workbook is already on the volume (card: uploaded 2026-09-30, checksum verified). Then the same steps as for DepEd ([Running on Databricks](#running-on-databricks)): `databricks bundle validate`, `deploy`, `summary`, `run` twice.

In the job, `bronze_psa_poverty_stat` runs `cli.py ingest --no-gate --no-setup --job-run-id {{job.parameters.run_id}}`: it creates no table, runs no gate, and stores the job run id in `pipeline_runs.job_run_id` so the load joins to its gate task's checks (D-020). The control columns this source needs (D-018: three in `ingestion_batches`, two in `ingestion_batch_attempts`) and `job_run_id` are added once, only if missing, by the job's `add_control_columns` task, before `05_create_current_batches` replaces the view; the PSA lane no longer adds them. On `dev`, D-018's columns were already present before these runs, so their `ALTER TABLE … ADD COLUMN` on older tables is shown only locally; `job_run_id` was added on `dev` by the first DAG run.

Validation queries (Databricks SQL editor):

```sql
-- The batch and its counts: expect 1 succeeded, expected = source = bronze = 1641 (the whole sheet)
SELECT batch_id, logical_dataset, estimate_years_covered, source_sheet, delivery_version, load_type, status,
       expected_rows, source_rows, bronze_rows, error_code
FROM edu_access.`01-control`.ingestion_batches WHERE source_id = 'psa_poverty_stat';

-- Every sheet row by kind: expect footer 6, header 4, region_banner 18, title 1, unit 1612
SELECT source_row_kind, COUNT(*) FROM edu_access.`02-bronze`.psa_poverty_stat_raw GROUP BY ALL ORDER BY 1;

-- Load then skip: expect 'load' in run 1 and 'skip' with 0 rows in run 2
SELECT r.started_at_utc, a.action, a.outcome, a.rows_inserted, a.estimate_years_covered
FROM edu_access.`01-control`.ingestion_batch_attempts AS a JOIN edu_access.`01-control`.pipeline_runs AS r USING (run_id)
WHERE a.source_id = 'psa_poverty_stat' ORDER BY r.started_at_utc;

-- No pipeline duplicates: expect 0
SELECT COUNT(*) - COUNT(DISTINCT source_sha256, source_row_number) FROM edu_access.`02-bronze`.psa_poverty_stat_raw;

-- Excel rows: expect 1 and 1641
SELECT MIN(source_row_number), MAX(source_row_number) FROM edu_access.`02-bronze`.psa_poverty_stat_raw;

-- Known issues kept as received: expect 1073 five-digit IDs, 1 unit with a blank 2023 estimate
SELECT COUNT_IF(source_row_kind = 'unit' AND length(`PSGC ID`) = 5) AS five_digit_ids,
       COUNT_IF(source_row_kind = 'unit' AND `Poverty Incidence 2023` = '') AS blank_2023
FROM edu_access.`02-bronze`.psa_poverty_stat_raw;

-- Checks for the PSA batch: expect no FAIL, and WARNs at the profiled counts
SELECT check_name, status, expected, actual FROM edu_access.`01-control`.data_quality_results
WHERE source_id = 'psa_poverty_stat'
  AND layer = 'bronze'
  AND run_id IN (SELECT MAX_BY(run_id, started_at_utc) FROM edu_access.`01-control`.pipeline_runs
                 WHERE source_id = 'psa_poverty_stat' AND pipeline_name = 'bronze_ingest'
                 UNION ALL  -- the gate task's rows, under the job run id (D-020)
                 SELECT MAX_BY(job_run_id, started_at_utc) FROM edu_access.`01-control`.pipeline_runs
                 WHERE source_id = 'psa_poverty_stat' AND pipeline_name = 'bronze_ingest')
ORDER BY status, check_name;

-- Where one row came from
SELECT source_file, source_sha256, source_sheet, source_row_number, source_row_kind, batch_id, run_id, code_revision
FROM edu_access.`02-bronze`.psa_poverty_stat_raw WHERE source_row_number = 641;
```

### Handoff to Silver

Built as described in [Silver, PSA Poverty Stat](silver.md#psa-poverty-stat) (D-034). What Bronze hands over, and what Silver does with it:

- read only rows whose `batch_id` is in `current_batches`, and only `source_row_kind = 'unit'`; use the banner rows to carry the region label down (O-3), never as places;
- keep `PSGC ID` raw, and add a padded 6-digit code (`lpad(…, 6, '0')`) and the PSGC Correspondence Code (padded code + `000`); the geographic join to PSGC belongs in Integration (X-1, D-012);
- unpivot to one row per unit and estimate year, typing estimates, CV, SE and limits as DOUBLE numbers (the stored values, scientific notation included) without rounding; blanks become NULL with a reason (`no_estimate` for Kalayaan), never 0;
- flag, not fix: CV over 20, the 2021 CALABARZON standard errors, zero or negative lower limits (clip only in a documented, reversible column if a rule is approved);
- never treat the unit rows' province labels (`(Continued)`, Surigao rows, O-3) as authoritative: Silver does not carry them, and Integration takes the province from PSGC through the Correspondence Code; take region from the banner, not the ID prefix (Negros Island Region has two prefixes);
- add no rows for places the workbook does not cover (33 highly urbanized cities, Isabela, Cotabato, Pateros, 8 SGA municipalities): Integration records them as `not_in_source` against PSGC, never as zero poverty;
- keep `batch_id` and `source_row_number` on every row.

Cross-year comparability (S-3) and update frequency remain unverified; a trend across 2018, 2021 and 2023 needs the team's decision first.

### Runbook (PSA)

**1. How do I add a new PSA Poverty Stat workbook delivery?**
Download it from the stat-tables page; do not rename it, open-and-save it, or convert it. Upload it to `raw/psa/<download date>/` (never over an existing file) with that folder's `SHA256SUMS.txt`. Profile it (`analysis/profiling/profile_psa_poverty.py`, adjusted for its name and checksum), update the card, and add the delivery to `config/ingestion/psa_poverty_stat.json` in a pull request: `logical_dataset`, `estimate_years`, `workbook`, `workbook_sha256`, `sheet`, `schema_version`, `body_rows`, `unit_rows`, `banner_rows`, `footer_rows`, `retrieved_at_utc`. If the header has other years or columns, add a schema version (and regenerate the DDL). Then run the job.

**2. How do I know whether it was already processed?**
`python -m src.ingestion.cli status --source psa_poverty_stat`, or the first validation query: `succeeded` for its SHA-256 means processed.

**3. What happens if the publisher replaces a file?**
The new bytes do not match the approved SHA-256: the batch is `blocked` (`checksum_mismatch`, `load_type = revision` when its header names years already loaded) and the run fails. Nothing is overwritten. If the change is real, approve it as `delivery_version: 2` of the same `logical_dataset` with `supersedes` set to v1's `workbook_sha256`. v2 must keep every estimate year of v1 (adding years is fine); a revision that drops a year is refused, because `current_batches` would then hide that year from Silver. Both versions stay in Bronze.

**4. How do I inspect a failed batch?**

```sql
SELECT batch_id, status, failure_stage, error_code, error_message, attempt_count, last_run_id
FROM edu_access.`01-control`.ingestion_batches
WHERE source_id = 'psa_poverty_stat' AND status IN ('failed', 'blocked', 'loading');
```

Then its checks: `SELECT check_name, status, expected, actual FROM edu_access.`01-control`.data_quality_results WHERE batch_id = '<batch_id>'`.

**5. How do I safely rerun it?**
Fix the cause and run again: a `failed` or `loading` batch is retried and the MERGE adds only missing rows. To repeat a succeeded batch on purpose: `--rerun <batch_id>` (adds 0 rows).

**6. How do I verify the Bronze output?**
1,641 rows for the workbook (1 `title`, 4 `header`, 1,612 `unit`, 18 `region_banner`, 6 `footer`), Excel rows 1 to 1641, no FAIL, the known-issue WARNs at their profiled counts, and one row traced to its sheet line with the last query above (row 641 is Kalayaan, blank estimates).

**7. How do I prove the same batch did not create duplicates?**
Run twice. The attempts query shows `load` then `skip` with 0 rows, Bronze still has 1,641 rows, and the duplicate query returns 0. Locally, `tests/test_ingestion_psa.py::test_psa_idempotency_demonstration` proves the same with made-up workbooks, and `analysis/demo/psa_ingestion_demo.py` prints the whole story (load, skip, a new year, a changed file blocked, a crash and its recovery, one row traced to its Excel line) for a presentation: run it cell by cell in VS Code, or `python analysis/demo/psa_ingestion_demo.py`. It uses no raw data and no Databricks.

### Limitations and open questions (PSA)

- Verified on made-up workbooks and on the real workbook locally (DuckDB). On Databricks `dev`, only skip runs of the lane in `edu_access_pipeline` are recorded (2026-10-08, D-020); the load path there is not.
- The merged-header check expects each group in row 2 to be merged across its columns, as in the real workbook; a future file laid out differently stops the batch, and the contract is corrected in review, not the file.
- `known_issue` checks compare against counts from one profile run; they warn, they never block.
- Update frequency, cross-year comparability (S-3), and the PSGC version of the ID are unverified.

| Question | Default until decided | Where |
|---|---|---|
| Is a later release that adds a year (and may revise old ones) a revision of the current dataset, or a new dataset? | The contract refuses overlap across datasets, and a revision must keep every year of the version it supersedes. So a release covering all earlier years plus a new one loads as a revision; one that overlaps but drops a year (e.g. 2023, 2025 after 2018, 2021, 2023) cannot be approved either way until the team decides | D-018 |
| Should the latest version always be current after a revision? | Latest succeeded version | D-015 |
| Does `psa_poverty_stat` move from `profiled` to `accepted`? | Stays `profiled`; loads to `local` and `dev` only | Team (owner @maeveylain) |
| How long are superseded versions kept? | Forever | Not yet logged |
| Should Silver clip negative lower limits, or only flag them? | Flag only (`lower_limit_not_positive`); proposed in D-034, not yet reviewed | D-034 |

## PSA PSGC (xlsx workbook, one per quarter)

`psa_psgc` loads through the same pipeline as DepEd, from its own contract, [`config/ingestion/psa_psgc.json`](../../config/ingestion/psa_psgc.json) (`format: xlsx_table`). What differs is in [`src/ingestion/xlsx_table.py`](../../src/ingestion/xlsx_table.py): reading the workbook, the quarter, the header mapping and the checks. Decision: D-019.

**Status:** built and tested locally with made-up workbooks (`tests/test_ingestion_psgc.py`), and loaded locally from the real 2Q 2026 workbook: 43,768 rows, every count equal to the source card, 0 FAIL, then a skip ([evidence](../../evidence/pipeline-runs/2026-10-07-psa-psgc-local-idempotency.md)). **Verified on Databricks `dev`** on 2026-10-08 at commit `cb274bf`: 43,768 rows loaded, every count equal to the local runs, 0 FAIL, then a skip ([evidence](../../evidence/pipeline-runs/2026-10-08-psa-psgc-databricks-idempotency.md)). The source stays `profiled`.

### The flow (PSGC)

```
psa.gov.ph/classification/psgc            (official quarterly xlsx; no API, no scraping)
   │  download by hand; never rename, open-and-save, or convert
   ▼
00 Source   /Volumes/edu_access/00-source/raw/psa/[<download date>/]PSGC-<n>Q-<yyyy>-Publication-Datafile.xlsx
   │  discover PSGC-*Q-*-Publication-Datafile.xlsx → SHA-256 → approved?   (config/ingestion/psa_psgc.json)
   ▼
   │  open safely → sheet PSGC → exact header = a schema version → quarter from the name = Metadata date
   │  → every row 2..last as stored text → checks (FAIL blocks; WARN records)
01 Control  pipeline_runs · ingestion_batches · ingestion_batch_attempts · data_quality_results
   │  MERGE → reconcile → succeeded → Bronze gate
   ▼
02 Bronze   edu_access.`02-bronze`.psa_psgc_raw    (every quarter, every version, text, with provenance)
   │
   ▼  Silver reads only batches in `01-control`.current_batches, and the quarter named in master_reference_period
```

### The nine questions, for `psa_psgc`

| Question | Answer |
|---|---|
| What should be ingested? | Every data row of sheet `PSGC` of the approved workbook: 2Q 2026 is `A1:K43769`, 1 header row and 43,768 rows (all levels from region to barangay, sub-municipalities, and 2 rows with a blank level), all 11 columns including the unnamed column J. `Metadata` and `National Summary` are read for checks only; `Prov Sum`, `Notes` and `Coding Structure` (an image) are publisher documentation and stay in Source |
| How often does it arrive? | Quarterly (`Metadata`: "Ongoing (updated quarterly)"). Downloaded by hand when the team decides to take a new quarter; never on a schedule |
| What identifies a new delivery? | A workbook SHA-256 not seen before. Its quarter comes from the file name (`PSGC-2Q-2026-…` is `2026-Q2`) and must equal the quarter of the `Metadata` publication date and the approved entry |
| What indicates that an existing delivery changed? | The same quarter (same file name) with a different SHA-256. PSA replaces the file at a stable URL, so a re-download can carry new bytes under the old name. The workbook has no `updated_at`, and none is invented |
| Has this exact file already been processed? | `ingestion_batches.status = 'succeeded'` for its `archive_sha256` (the workbook's). The next run then records a `skip` |
| Does the team need to retain previous versions? | Yes. Every quarter is a complete snapshot, codes change between quarters (Negros Island Region, Sulu: D-012), and a re-issued quarter is a correction to compare against. Source keeps every file (D-016); Bronze keeps every quarter and every version (D-015) |
| Is the delivery valid? | The checks under [PSGC validation](#psgc-validation) |
| Can the ingestion be safely rerun? | Yes: a succeeded workbook is skipped; a forced rerun inserts nothing; an interrupted or failed one is retried and the MERGE adds only missing rows |
| Where did every resulting row come from? | `source_file`, `source_sha256`, `source_sheet`, `source_row_number` (the Excel row) and `publication_period`, joined by `batch_id` and `run_id` to the control tables, with `code_revision` for the code |

### Identity (PSGC)

| Level | Identified by | Why |
|---|---|---|
| Delivery (batch) | Workbook SHA-256; `batch_id` = `psa_psgc__<quarter>__<sha256[:12]>`, e.g. `psa_psgc__2026-Q2__31892bc2bdde` | Same bytes, same batch, wherever the file sits |
| Logical period | `source_id` + publication quarter + `delivery_version` | A re-issued quarter is version 2, never a silent replacement |
| Bronze row | `source_sha256` + `source_row_number` (the Excel row, 2 to 43,769) | A rerun inserts nothing. The contract approves one sheet per workbook, so the pair is unique; `source_sheet` is recorded but not needed in the key |
| Schema | `schema_version` + `schema_fingerprint` (SHA-256 of the exact header cells, line breaks included) | Any change to any header cell changes it |
| Code | `code_revision` | The commit that ran ([above](#code_revision)) |

The control tables have one period column, `school_year`. For `psa_psgc` it holds the publication quarter (`2026-Q2`): a documented convention rather than a new column (D-019). Quarters sort like school years, so `current_batches`, backfill detection and every existing query work unchanged, and no shared table changes. Bronze names the column properly: `publication_period`.

**Why a row is not identified by its PSGC code.** The code identifies a place, not a row of a delivery. Keyed on the code, a MERGE would update rows in place when the next quarter arrives, turning Bronze into a latest-state table and destroying the quarterly history that D-012 and the Negros and Sulu comparison depend on; it would also merge a code the publisher listed twice, hiding a source duplicate. Keyed on (file checksum, Excel row), every quarter and version is kept as delivered, and the code's uniqueness is checked instead (`psgc_code_unique_in_file`). The cost: a re-issued quarter that changes one value reloads all 43,768 rows as a new version, which is acceptable at this size.

### Storage layout (PSGC)

The first download stays flat in the publisher folder; any later download, whether a new quarter or a re-download of a published one, goes into a dated subfolder under its original name (D-016):

```
/Volumes/edu_access/00-source/raw/psa/
├── PSGC-2Q-2026-Publication-Datafile.xlsx      first download, uploaded 2026-09-30, checksum verified
├── PSGC-Q4_2023-API-all.csv                    D-012 comparison only; not ingested
├── 2_2023 SAE_with PSGC_noHUC_06Feb2026.xlsx   psa_poverty_stat, not this source
├── SHA256SUMS.txt
└── 2027-01-15/                                 a later download (example date)
    ├── PSGC-3Q-2026-Publication-Datafile.xlsx
    └── SHA256SUMS.txt
```

This matters for PSA in particular: the quarterly file is replaced at a stable URL, so a same-named file with different bytes must never overwrite the original. The pipeline searches `raw/psa/` at any depth for names like `PSGC-<n>Q-<yyyy>-Publication-Datafile.xlsx` (`workbook_pattern` in the contract; no path is hardcoded) and identifies files by checksum, so the other PSA files are not touched, and Office lock files (`~$…`) are ignored.

### Checksum verification (PSGC)

A workbook is loaded only if its SHA-256 equals an approved `workbook_sha256` in the contract, copied from the source card in a reviewed pull request (D-014). The 2Q 2026 checksum `31892bc2…ca5d` is on the card and in `SHA256SUMS.txt`; `tests/test_ingestion_validate.py` fails if the contract's checksum, file name, row count and range are not on the same card row. An approved name with other bytes is `blocked` as `checksum_mismatch`; an unknown file is `blocked` as `unregistered_delivery`.

### Header and schema versions (PSGC)

The header is matched exactly, cell by cell, against the contract's `source_headers`; nothing is normalized. Each source header maps to a fixed Bronze name, so the exact text is kept in the contract and the Bronze names stay stable:

| Column | Exact source header (`v1`) | Bronze column |
|---|---|---|
| A | `10-digit PSGC` | `psgc_code` |
| B | `Name` | `name` |
| C | `Correspondence Code` | `correspondence_code` |
| D | `Geographic Level` | `geographic_level` |
| E | `Old names` | `old_names` |
| F | `City Class` | `city_class` |
| G | `Income` + line break + `Classification (DOF DO No. 074.2024)` | `income_classification` |
| H | `Urban / Rural` + line break + `(based on 2020 CPH)` | `urban_rural` |
| I | `2024 Population` | `population` |
| J | (empty styled cell; the column holds footnote text and markers) | `column_j_footnote` |
| K | `Status` | `status` |

Anything else stops the batch. A header equal to a known version other than the approved one is `schema_version_mismatch` (known drift). Any other change is `unknown_schema_drift`, with the changed cells named in the message: a line break normalized away, a header added to column J, or a moved, added or removed column.

**Expected future evolution.** Two headers embed version-specific text: the DOF order (`DOF DO No. 074.2024`) and the census (`based on 2020 CPH`, `2024 Population`). A new DOF order or census will change them. That fails as drift until someone profiles the new quarter and adds `v2` to the contract on purpose, with the new `source_headers` and the same Bronze columns, so Silver can tell from `schema_version` which order or census a value belongs to (`test_a_new_schema_version_loads_into_the_same_bronze_columns`). A genuinely new column gets a new Bronze column, added from the contract (`ALTER TABLE … ADD COLUMN`).

<a id="psgc-validation"></a>
### PSGC validation

Blocking, before anything reaches Bronze (`failed` or `blocked`; nothing loaded; the run fails):

| Check | On failure |
|---|---|
| Workbook exists and its SHA-256 is approved | `missing_archive`; `blocked`: `checksum_mismatch`, `unregistered_delivery` |
| Opens through the shared `workbook.open_sheet`: a zip with no `..`, absolute, linked or encrypted parts, under 100 MB expanded; an xlsx; no macros; no XML part with a DTD, entities, or a non-UTF-8 encoding | `corrupt_archive`, `unsafe_member`, `archive_too_large`, `corrupt_workbook`, `macro_enabled_workbook`, `unsafe_workbook` |
| Sheet `PSGC` exists and has cells; no sheet the contract does not list (a new sheet may hold data) | `missing_sheet`, `empty_sheet`, `unexpected_sheet` |
| The quarter: file name, `Metadata` "Publication date:" and the approval agree | `period_undeterminable`, `period_mismatch` |
| Header equals a schema version exactly, and the approved one | `unknown_schema_drift`, `schema_version_mismatch` |
| Row count nonzero and equal to the approval; used range equal to the approved range | FAIL `row_count_nonzero`, `row_count_matches_approved`, `range_matches_approved` |
| `psgc_code` on every row, matching `^[0-9]{10}$` as stored text | FAIL `psgc_code_not_blank`, `psgc_code_format` |
| A code stored as a number is accepted only if its stored digits are already 10 digits; never padded | FAIL `psgc_code_number_cells_match_format` |
| No mojibake (`Ã±` for `ñ`, as in the Q4_2023 API file) and no replacement characters | FAIL `text_mojibake` |
| The approved workbook is in the landing folder (`require_approved_deliveries`) | FAIL `approved_deliveries_present`; the run fails at stage `discover` |

After the MERGE (`bronze.reconcile`), before the batch is marked succeeded: Bronze rows for the workbook equal the sheet's data rows, Excel rows run exactly 2..last with none repeated, and no provenance column is NULL. Then the generated gate (`etl/02_bronze/90_validate_psa_psgc_raw.sql`) checks the whole table: no pipeline duplicates, every row has a known batch, every succeeded batch reconciles.

Recorded, not blocking (WARN; rows loaded as received; whether any should block is an [open question](#open-questions-psgc)):

| Check | 2Q 2026 | Finding |
|---|---|---|
| `psgc_code_unique_in_file` (source duplicates) | 0 | O-1; kept in Bronze if they appear, and Silver stops on them (below) |
| `duplicate_rows_in_file` | 0 | O-1 |
| `psgc_code_stored_as_number` | 84 (all 10 digits) | found 2026-10-07 |
| `level_count_{prov,city,mun,bgy}_matches_national_summary`, read from the same workbook | 82 / 149 / 1,493 / 42,010, all equal | O-5 |
| `region_population_reconciles_to_national` (national minus the sum of regions, against the approved `documented_population_abroad`) | 1,708 = 1,708 | O-4, `Notes` D.2 |
| `hierarchy_*`: barangays without their city or municipality; provinces, cities and municipalities without their region; non-NCR municipalities without their province; provinces in NCR | 0, 0, 0, 0 | O-10 |
| `dq_blank_geographic_level` / `dq_blank_correspondence_code` | 2 / 50 | O-2 / O-3 |
| `dq_population_not_whole_number` / `dq_population_zero` / `error_cells` | 1 / 12 / 1 | O-4 |
| `dq_income_class_dash` / `dq_income_class_starred` | 8 / 6 | O-7 |
| `dq_urban_rural_dash` | 38 | O-8 |
| `dq_name_trailing_space` | 2,855 | O-9 |
| `dq_column_j_footnote_filled` | 19 | O-6 |
| `sheets_match_contract` (a documentation sheet missing; an extra sheet already stopped the batch) | the six sheets | |
| `formula_cells`, `error_cells` | 0, 1 (the `#N/A` population) | a formula's cached result is loaded; nothing is recalculated |

A known characteristic is PASS when its count equals the profiled count and WARN when the count changes, with the profiled count beside the actual one: a normal run is quiet, and a new quarter that changes a count stands out. When a new quarter is profiled and approved, update the profiled counts in the contract with it. The National Summary values are read from each workbook, never hardcoded. Results hold counts only, never row values.

### Bronze table (PSGC)

``edu_access.`02-bronze`.psa_psgc_raw`` (generated: `etl/02_bronze/04_create_psa_psgc_raw.sql`): 16 provenance columns, then the 11 source columns, all as text.

| Provenance column | Meaning |
|---|---|
| `source_id`, `source_system`, `source_url` | From the registry (`config/sources.json`); the URL is the acquisition page |
| `publication_period`, `publication_date`, `delivery_version` | The quarter (`2026-Q2`), the `Metadata` publication date (`2026-06-30`), and which delivery of that quarter |
| `source_file`, `source_sha256`, `source_sheet`, `source_row_number` | The workbook, its checksum, the sheet (`PSGC`), and the **Excel row number** (the header is row 1, data starts at 2), so anyone can open the workbook at the exact line |
| `schema_version`, `schema_fingerprint` | Which header it had (fingerprint of the exact header cells) |
| `batch_id`, `run_id`, `ingested_at_utc`, `code_revision` | The batch, the run, when, and the commit |

Every cell is kept as the text the publisher stored: text exactly (trailing spaces, line breaks, Unicode such as `Tañong`), errors as their text (`#N/A`), blanks as `''`. **Numbers keep their stored digits**; the rule is the cell's stored value, not Excel's display. The population column uses an accounting format that adds thousands separators and shows `0` as `-`. Reproducing the display would turn the 12 zero-population barangays into the same `-` the publisher uses for "unknown" in other columns, so Bronze keeps `0`, and `1489` rather than `1,489` (`test_values_stay_exactly_as_received`). No trimming, typing, padding, level assignment, class splitting or name normalization happens in Bronze.

### Retry, rerun, backfill, revision (quarters)

| Term | Example | What happens |
|---|---|---|
| Skip | 2Q 2026 again | Attempt logged `skip`; 0 rows |
| Retry | A batch that failed (for example an approval with a wrong count, later fixed) or was interrupted | Picked up automatically; the MERGE adds only missing rows; `attempt_count` goes up |
| Rerun | `--rerun psa_psgc__2026-Q2__31892bc2bdde` | Validated and merged again; 0 rows |
| New quarter | 3Q 2026 after 2Q 2026 | `load_type = incremental`; earlier quarters untouched |
| Backfill | 1Q 2026 downloaded after 2Q 2026 | `load_type = backfill`; earlier rows untouched |
| Revised delivery | PSA re-issues 2Q 2026 under the same name | Before approval: `blocked`, `checksum_mismatch`, `load_type = revision`; the run fails; nothing is overwritten. After approval as `delivery_version: 2` with `supersedes` set to v1's `workbook_sha256`: loaded beside v1, and `current_batches` points to v2 for 2026-Q2 (D-015 default) |

Each quarter is a complete snapshot of the classification, so a new quarter is a new period, never a revision of the last one. **Which quarter is the master reference is not decided by loading**: it is `master_reference_period` in the contract (`2026-Q2`, D-012), validated to be an approved quarter, and changed only by a reviewed pull request after a team decision. A newer or backfilled quarter therefore never moves it (tested in the demonstration). `current_batches` answers a different question: the latest succeeded version of each quarter.

All seven steps, on made-up workbooks: `tests/test_ingestion_psgc.py::test_psgc_idempotency_demonstration` (load, skip, both attempts in the log, a new quarter, a backfill, a re-issue blocked and then approved as v2, a new DOF header failing as drift).

### Failure and recovery (PSGC)

| Failure | Stage / code | Exit | What you do |
|---|---|---|---|
| Landing folder missing | `discover` / `missing_landing` | 3 | Set `RAW_DATA_DIR` or `--landing` to the raw root |
| Approved workbook missing from the folder | FAIL `approved_deliveries_present`; run stage `discover` | 1 | Upload it (dated subfolder, never over a file) |
| Checksum differs from the approval | `identify` / `checksum_mismatch`, `blocked` | 1 | Damaged: download again. Re-issued: profile, approve as the next version |
| Unknown workbook | `identify` / `unregistered_delivery`, `blocked` | 1 | Profile it, approve it |
| Corrupt xlsx | `archive` / `corrupt_archive`; `workbook` / `corrupt_workbook` | 1 | Download again and compare the checksum |
| Unsafe zip parts, too large, macros, DTD or entities | `archive` / `unsafe_member`, `archive_too_large`; `workbook` / `macro_enabled_workbook`, `unsafe_workbook` | 1 | Do not open it; tell the team and PSA |
| Sheet `PSGC` missing, or empty | `workbook` / `missing_sheet`; `parse` / `empty_sheet` | 1 | Inspect the file; profile it |
| Header drift, known or unknown | `schema` / `schema_version_mismatch`, `unknown_schema_drift` | 1 | Profile; add a schema version in a pull request |
| A code lost its leading zero, or a number-stored code is not 10 digits | FAIL `psgc_code_format`, `psgc_code_number_cells_match_format` | 1 | Never pad; check the download; ask PSA |
| Quarter not determinable, or name and `Metadata` disagree | `period` / `period_undeterminable`, `period_mismatch` | 1 | Check the name and the `Metadata` sheet; never rename the file to make it pass |
| Same workbook again | `skip` | 0 | Nothing |
| Process dies mid-load | Batch stays `loading`; not in `current_batches` | (crash) | Run again: it is retried and completed |
| Partial Bronze write | Reconciliation FAIL; `failed` | 1 | Run again: the MERGE adds the missing rows only |
| Same quarter, changed bytes | `blocked`, `load_type = revision` | 1 | Approve as `delivery_version: 2` after review |
| Databricks unavailable | `setup` / `store_unavailable` | 3 | Run locally, or `databricks auth login --profile reached-hq` |
| `prod` while the source is `profiled` | `config` / `source_not_accepted` | 2 | Use `dev` until the team accepts it |

### Running locally (PSGC)

From the repository root, with the project's own interpreter. In PowerShell, first check that `python -c "import sys; print(sys.executable)"` points into this repository's `.venv`.

```bash
python -m pytest tests -q
```

```bash
python -m src.ingestion.cli ingest --source psa_psgc
```

```bash
python -m src.ingestion.cli status --source psa_psgc
```

`RAW_DATA_DIR` must be set (or `--landing` given), with the workbook somewhere under `$RAW_DATA_DIR/psa/`. Expected on the real file: `load initial succeeded inserted=43768`, then on the second run `skip`, `inserted=0`. Result on 2026-10-07: [evidence](../../evidence/pipeline-runs/2026-10-07-psa-psgc-local-idempotency.md).

After changing the contract's schema, regenerate the SQL (a test fails until you do). In Windows PowerShell 5.1, `>` writes UTF-16 and `Out-File -Encoding utf8` adds a byte-order mark; run these from Git Bash, or pipe to `Out-File -Encoding ascii`:

```bash
python -m src.ingestion.cli ddl --source psa_psgc > etl/02_bronze/04_create_psa_psgc_raw.sql
```

```bash
python -m src.ingestion.cli gate --source psa_psgc > etl/02_bronze/90_validate_psa_psgc_raw.sql
```

### Databricks confirmation (PSGC)

**Done on 2026-10-08** (`dev`, job runs `468579404509795` then `96808622487518`, commit `cb274bf`): load 43,768, then skip; [evidence](../../evidence/pipeline-runs/2026-10-08-psa-psgc-databricks-idempotency.md). The first attempt failed because the shared `dev` control tables already carried D-018's columns before #109 merged; with #109 merged, `main` handles those columns itself.

In `edu_access_pipeline`, PSGC has its own lane: `04_create_psa_psgc_raw` → `bronze_psa_psgc` → `90_validate_psa_psgc_raw` (D-020). Before running it, the pull request must be reviewed, the run announced to the team (the workspace and control tables are shared), and the `reached-hq` profile working. The workbook is already on the volume (card: uploaded 2026-09-30, checksum verified). This change adds no column to the control tables, and works whether or not they carry #109's columns. Then, as for DepEd ([Running on Databricks](#running-on-databricks)):

```bash
databricks bundle validate --target dev --profile reached-hq
```

```bash
databricks bundle deploy --target dev --profile reached-hq
```

```bash
databricks bundle summary --target dev --profile reached-hq
```

```bash
databricks bundle run edu_access_pipeline --target dev --profile reached-hq
```

Run the last command twice: the second run must skip every file. The other source lanes run in parallel and skip their files.

### Validation queries (PSGC)

```sql
-- Batches: expect 2026-Q2 v1 succeeded, expected = source = bronze = 43768
SELECT batch_id, school_year AS publication_period, delivery_version, load_type, status, attempt_count,
       expected_rows, source_rows, bronze_rows, error_code
FROM edu_access.`01-control`.ingestion_batches WHERE source_id = 'psa_psgc' ORDER BY school_year, delivery_version;

-- Load then skip: expect 'load' 43768 in run 1, 'skip' 0 in run 2
SELECT r.started_at_utc, a.action, a.outcome, a.rows_inserted, a.code_revision
FROM edu_access.`01-control`.ingestion_batch_attempts AS a JOIN edu_access.`01-control`.pipeline_runs AS r USING (run_id)
WHERE a.source_id = 'psa_psgc' ORDER BY r.started_at_utc;

-- Rows per quarter and version
SELECT publication_period, delivery_version, COUNT(*) FROM edu_access.`02-bronze`.psa_psgc_raw GROUP BY ALL ORDER BY 1, 2;

-- No pipeline duplicates: expect 0
SELECT COUNT(*) - COUNT(DISTINCT source_sha256, source_row_number) FROM edu_access.`02-bronze`.psa_psgc_raw;

-- Units by level, as in the workbook's National Summary: expect Bgy 42010, Mun 1493, City 149, Prov 82, Reg 18, SubMun 14, '' 2
SELECT geographic_level, COUNT(*) FROM edu_access.`02-bronze`.psa_psgc_raw WHERE publication_period = '2026-Q2' GROUP BY 1 ORDER BY 2 DESC;

-- Kept as received: expect 50, 1, 12, 38, 2855, 29620, 0
SELECT COUNT_IF(correspondence_code = ''), COUNT_IF(population = '#N/A'), COUNT_IF(population = '0'),
       COUNT_IF(urban_rural = '-'), COUNT_IF(name LIKE '% '), COUNT_IF(psgc_code LIKE '0%'),
       COUNT_IF(NOT psgc_code RLIKE '^[0-9]{10}$')
FROM edu_access.`02-bronze`.psa_psgc_raw WHERE publication_period = '2026-Q2';

-- Checks for the latest PSGC run: expect no FAIL, and the WARNs at their profiled counts
SELECT check_name, status, expected, actual FROM edu_access.`01-control`.data_quality_results
WHERE source_id = 'psa_psgc'
  AND layer = 'bronze'
  AND run_id IN (SELECT MAX_BY(run_id, started_at_utc) FROM edu_access.`01-control`.pipeline_runs
                 WHERE source_id = 'psa_psgc' AND pipeline_name = 'bronze_ingest'
                 UNION ALL  -- the gate task's rows, under the job run id (D-020)
                 SELECT MAX_BY(job_run_id, started_at_utc) FROM edu_access.`01-control`.pipeline_runs
                 WHERE source_id = 'psa_psgc' AND pipeline_name = 'bronze_ingest')
ORDER BY status, check_name;

-- Where one row came from: Excel row 2 of sheet PSGC
SELECT source_file, source_sha256, source_sheet, source_row_number, publication_period, batch_id, run_id, code_revision
FROM edu_access.`02-bronze`.psa_psgc_raw WHERE publication_period = '2026-Q2' AND source_row_number = 2;

-- Column mapping is on
SHOW TBLPROPERTIES edu_access.`02-bronze`.psa_psgc_raw ('delta.columnMapping.mode');
```

### Handoff to Silver (PSGC, not built here)

Bronze preserves; Silver cleans. Silver (`psa_psgc_clean`) should:

- read only rows whose `batch_id` is in `current_batches`, and use the quarter in the contract's `master_reference_period` (2Q 2026, D-012) as the reference; other quarters are for comparison;
- trim names (2,855 trailing spaces), keeping the original in Bronze;
- type `population`: `#N/A` becomes NULL with a flag; `0` stays 0; never read a blank or `-` as 0;
- split `income_classification` into the class and `retained_after_downgrade` (the `*`, `Notes` B); keep `-` as unknown;
- keep `urban_rural` `-` as unknown, never rural; report the urban share with its denominator;
- assign a level to the 2 blank-level rows (City of Isabela, Special Geographic Area) only by a documented rule, or leave them unassigned with a flag;
- derive parent codes from the prefix (region 2 digits, province 5, city or municipality 7) and assert them; handle NCR (no provinces) and the special rows explicitly;
- exclude `column_j_footnote` from the model, but note that province populations exclude the cities it names;
- **stop on any duplicate `psgc_code` within a quarter's current version**: PSGC is what Integration joins to, so a duplicate would multiply joined rows. Bronze keeps both rows and records `psgc_code_unique_in_file`; Silver's gate must fail, and the duplicates are resolved by a documented rule or by the publisher, never by keeping one at random (none in 2Q 2026);
- keep `schema_version`, so the DOF order and census behind each value stay known;
- for DepEd SY 2023-24, apply the D-012 matching rules: never match on region; match a barangay only inside its own city or municipality; then try `old_names` inside the same parent; flag unmatched or ambiguous names and never force a match; record the PSGC version (`publication_period`, `delivery_version`) used for each match;
- keep `batch_id` and `source_row_number` on every row.

Downstream consumers: Sara's geographic lane, including `hdx_boundaries` (ADM3; 1,500 of 1,642 codes matched in its profile, O-11), and the PSA population and poverty sources, whose IDs are joined to PSGC in Integration.

### Runbook (PSGC)

**1. How do I add a new PSGC quarter?**
Download it from https://psa.gov.ph/classification/psgc; do not rename it, open-and-save it, or convert it. Record its SHA-256 and retrieval time, then upload it to `raw/psa/<download date>/` (list the folder first; never over an existing file) with that folder's `SHA256SUMS.txt`. Profile it (`analysis/profiling/profile_psgc.py`, with its name and checksum), update the source card, and add the delivery to `config/ingestion/psa_psgc.json` in a pull request: `publication_period`, `publication_date`, `workbook`, `workbook_sha256`, `sheet`, `range`, `schema_version`, `row_count`, `documented_population_abroad`, `retrieved_at_utc`. If the header changed (a new DOF order or census), add a schema version and regenerate the SQL. Run the job. A newer quarter loads as `incremental`, an older one as `backfill`; `master_reference_period` does not change.

**2. How do I know whether it was already processed?**
`python -m src.ingestion.cli status --source psa_psgc`, or the first validation query. `succeeded` for its batch (its SHA-256) means processed.

**3. What happens if PSA re-issues the same quarter under the same filename?**
Download it into a new dated folder. Its bytes do not match the approved checksum, so the batch is `blocked` (`checksum_mismatch`, `load_type = revision`) and the run fails; nothing is overwritten. Compare it with the first version (question 8). If the change is real, approve it as `delivery_version: 2` with `supersedes` set to v1's `workbook_sha256`. Both versions stay in Bronze, and `current_batches` moves to v2 for that quarter (D-015 default; see the open questions).

**4. How do I inspect a failed batch?**

```sql
SELECT batch_id, status, failure_stage, error_code, error_message, attempt_count, last_run_id
FROM edu_access.`01-control`.ingestion_batches
WHERE source_id = 'psa_psgc' AND status IN ('failed', 'blocked', 'loading');
```

Then its checks: ``SELECT check_name, status, expected, actual FROM edu_access.`01-control`.data_quality_results WHERE batch_id = '<batch_id>'``. Messages hold counts, checksums and header text, never row values.

**5. How do I safely rerun it?**
Fix the cause and run the same command again: a `failed` or `loading` batch is retried, and the MERGE adds only missing rows. To repeat a succeeded batch on purpose, add `--rerun <batch_id>` (it adds 0 rows).

**6. How do I verify the Bronze output against the workbook's own `National Summary`?**
The run records it: `level_count_*_matches_national_summary` and `region_population_reconciles_to_national` must be PASS (both read their expected values from the same workbook). Also run the units-by-level query above and compare it with the `National Summary` sheet: 82 provinces, 149 cities, 1,493 municipalities, 42,010 barangays for 2Q 2026.

**7. How do I prove a rerun created no duplicates?**
Run twice. The attempts query shows `load` then `skip` with 0 rows, the row count per quarter does not change, and the duplicate query returns 0. Locally, `tests/test_ingestion_psgc.py::test_psgc_idempotency_demonstration` and `test_rerun_adds_no_pipeline_duplicates` prove it with made-up workbooks.

**8. When a new quarter arrives, how is it compared with the previous one before anyone considers changing the master reference (D-012)?**
Load it (loading never makes it the master), then compare the two quarters in Bronze by code:

```sql
WITH a AS (SELECT * FROM edu_access.`02-bronze`.psa_psgc_raw
           WHERE batch_id IN (SELECT batch_id FROM edu_access.`01-control`.current_batches WHERE school_year = '2026-Q3')),
     b AS (SELECT * FROM edu_access.`02-bronze`.psa_psgc_raw
           WHERE batch_id IN (SELECT batch_id FROM edu_access.`01-control`.current_batches WHERE school_year = '2026-Q2'))
SELECT COUNT_IF(b.psgc_code IS NULL) AS only_in_new,
       COUNT_IF(a.psgc_code IS NULL) AS only_in_old,
       COUNT_IF(a.psgc_code IS NOT NULL AND b.psgc_code IS NOT NULL AND trim(a.name) <> trim(b.name)) AS renamed,
       COUNT_IF(a.psgc_code IS NOT NULL AND b.psgc_code IS NOT NULL AND a.geographic_level <> b.geographic_level) AS level_changed
FROM a FULL OUTER JOIN b ON a.psgc_code = b.psgc_code;
```

For codes only in the new quarter, look for their `correspondence_code` among the codes only in the old one; that is how the Negros and Sulu moves showed up (X-1). Write the counts and the reasons on the source card and the issue. Only then may the team decide to change `master_reference_period`, in a pull request with a decision-log entry; until then 2Q 2026 stays the master.

### Limitations (PSGC)

- Verified on made-up workbooks, on the real workbook locally (DuckDB, D-017), and on Databricks `dev` (2026-10-08): column mapping, reading from `/Volumes/` and Unity Catalog permissions are confirmed; a single-table commit under a real mid-load failure is not tested. Re-issue, new-quarter and backfill behavior is proven with made-up workbooks only.
- The National Summary and hierarchy checks rely on the layout those sheets have in 2Q 2026 (a header row with `PROV.`, `CITIES`, `MUN.`, `BGY.`; a `PHILIPPINES` row). If PSA changes it, the run reports `national_summary_readable` WARN instead of comparing.
- The quarter rule assumes the `Metadata` publication date falls inside the quarter named in the file (2Q 2026: 30 June 2026). If PSA starts writing the release date instead, the batch stops as `period_mismatch`, and the rule is revisited; the file is never renamed to pass.
- Only one quarter is acquired, so re-issue behavior is unobserved; the rules above are the safe default.
- The control tables' period column is named `school_year` and holds the quarter for this source (D-019).

<a id="open-questions-psgc"></a>
### Open questions (PSGC)

| Question | Default until decided | Where |
|---|---|---|
| Should any data-quality result block (for example a National Summary mismatch, or a source-duplicate code)? | All WARN; only the identifier, shape, period, header and safety checks block | Team |
| When PSA re-issues a quarter, is the latest version always current, or does it need review first? | Latest succeeded version | D-015 |
| Should historical PSGC versions served by the PSA API (e.g. `PSGC-Q4_2023-API-all.csv`) be ingested as Bronze? | No: the API file was used only for the D-012 comparison | Team |
| How long are superseded quarters and versions kept? | Forever | Not yet logged |
| Should the control tables get a generic `period` column instead of the `school_year` convention? | Keep the convention; no shared DDL change | D-019, Ina |
| When does the master reference move from 2Q 2026? | Never by loading; only by a team decision after the question-8 comparison | D-012 |
| Does `psa_psgc` move from `profiled` to `accepted`? | Stays `profiled`; loads to `local` and `dev` only | Team (owner @maeveylain) |
| What is the `Correspondence Code`, and why are 84 codes stored as numbers in the workbook? | Kept as stored; to ask the publisher | Source card |

## Administrative boundaries (COD-AB ADM3 GeoJSON)

`hdx_boundaries` loads through the same pipeline from its own contract, `config/ingestion/hdx_boundaries.json` (`format: geojson_features`). What differs is in `src/ingestion/geojson_features.py` (reading and checking the GeoJSON file) and the `GeojsonFeatures` class in `src/ingestion/formats.py`. Only the ADM3 file (cities and municipalities) is loaded; the ADM4 file beside it is not. Decision: D-026.

**Status:** implemented and tested locally with made-up GeoJSON (`tests/test_ingestion_boundaries.py`), and **verified locally on the real file** on 2026-10-08: 1,642 rows loaded (feature positions 1 to 1,642, every `valid_on` 2025-02-13, no missing geometry), 24 PASS, 0 WARN, 0 FAIL, and a second run skipped it ([evidence](../../evidence/pipeline-runs/2026-10-08-hdx-boundaries-local-idempotency.md)). **Verified on Databricks `dev`** on 2026-10-08 at commit `67ea4a2`: 1,642 rows loaded, every count equal to the local runs, 0 FAIL, then two runs skipped it ([evidence](../../evidence/pipeline-runs/2026-10-08-hdx-boundaries-databricks-idempotency.md)).The source stays `profiled`.

### The flow (boundaries)

```
data.humdata.org COD-AB page               (official GeoJSON; no API, no scraping)
   │  download by hand; never modify, never re-save in a GIS tool
   ▼
00 Source   /Volumes/edu_access/00-source/raw/admin_boundaries/[<download date>/]phl_admin3.geojson
   │  discover *.geojson matching ^phl_admin3\.geojson$ → SHA-256 → approved?   (config/ingestion/hdx_boundaries.json)
   ▼
   │  read the FeatureCollection one feature at a time → properties against the contract → schema version
   │  → one row per feature: properties as written text, geometry as raw GeoJSON text
01 Control  pipeline_runs · ingestion_batches · ingestion_batch_attempts · data_quality_results
   │  checks (FAIL blocks; WARN records) → MERGE in chunks of at most 64 MB → reconcile → succeeded → gate
   ▼
02 Bronze   edu_access.`02-bronze`.hdx_adm3_raw   (1,642 rows per delivery: one per feature, text, with provenance)
   │
   ▼  Silver reads only batches in `01-control`.current_batches
```

### The nine questions, for `hdx_boundaries`

| Question | Answer |
|---|---|
| What is ingested? | Every feature of `phl_admin3.geojson`: 1,642 cities and municipalities (ADM3), each with its 31 properties and its geometry. `phl_admin4.geojson` (42,048 barangays) sits in the same folder and is not ingested |
| How often does it arrive? | UNVERIFIED. One file so far, dated `valid_on = 2025-02-13` (downloaded 2026-10-02). Treated as an irregular batch, never as a stream |
| What identifies a new delivery? | A file SHA-256 not seen before. The file is not zipped, so the file itself is the delivery |
| What shows a delivery changed? | The same file name with a different SHA-256. The file's `version` and `valid_on` properties also mark an edition, but the checksum is the signal; nothing else is trusted alone |
| Has this exact file been processed? | `ingestion_batches.status = 'succeeded'` for its `archive_sha256` (the file's) |
| Are previous versions kept? | Yes: in Source (later downloads in dated subfolders, D-016) and in Bronze (`delivery_version`, D-015) |
| Is the delivery valid? | The checks under [Boundaries validation](#boundaries-validation) |
| Can it be rerun safely? | Yes: a succeeded file is skipped; a forced rerun inserts nothing; an interrupted run is retried and the MERGE adds only missing rows |
| Where did each row come from? | `source_file`, `source_sha256`, `source_row_number` (the feature's position in the file), plus `batch_id`, `run_id`, `code_revision` |

### Identity (boundaries)

| Level | Identified by | Why |
|---|---|---|
| Delivery (batch) | File SHA-256; `batch_id` = `hdx_boundaries__2025-02-13__f682747fbb26` | Same bytes, same batch, wherever the file sits |
| Logical period | `school_year` = the reference date `2025-02-13`, + `delivery_version` | The file's date, not a school year; stored in the control tables' period column, as PSGC stores its quarter (D-019). Every feature's `valid_on` must equal it |
| Bronze row | `source_sha256` + `source_row_number` (feature position, 1 to 1,642) | A rerun inserts nothing; two identical features would both be kept |
| Schema | `schema_version` + `schema_fingerprint` of the 32 column names (31 properties, then `geometry`) | Any renamed, added, removed, or reordered property changes it |

Because there is no zip, `archive` and `data_member` in the contract name the same file, and both checksums are the file's SHA-256 (`f682747f…ec41`).

Why not `adm3_pcode` as the row key? A MERGE keyed on the code would overwrite a municipality's row when a new edition arrives, turning Bronze into a latest-state table and losing the edition that earlier results used.

### Layout as a versioned contract (boundaries)

Schema `v1` pins what the profile found, and anything else stops the batch:

| Element | Contract | On anything else |
|---|---|---|
| File | Valid JSON; a `FeatureCollection` with a `features` list | `malformed_geojson`, `not_a_feature_collection` |
| Properties | Exactly the 31 of `v1`, in file order | `unknown_schema_drift`, naming the difference |
| Property values | Single values only (text, number, true/false, null) | `nested_property` |
| Geometry | Present on every feature; Polygon or MultiPolygon | FAIL if missing; WARN for another type |
| Coordinates | WGS 84 (no other CRS declared) | FAIL |
| Period | Every `valid_on` equals the delivery's reference date | FAIL |
| Row count | 1,642 features | FAIL |

**Values are kept exactly as written.** Numbers keep the file's digits (feature 1's `area_sqkm` is stored as `111.14398463000001`, exactly as in the file), `true`/`false` stay as text, and JSON `null` becomes NULL.

**Geometry is kept as the raw GeoJSON text**, in the last column, `geometry`: not parsed, simplified, or reprojected. Parsing it into a spatial type would mean choosing a library, a precision, and a validity rule now, and any of those could change a shape silently. As text it is exactly the file's characters, so Silver can parse it with whatever the team chooses and always check it against the raw file.

<a id="boundaries-validation"></a>
### Boundaries validation

Before Bronze, in addition to the layout above:

| Check | Status |
|---|---|
| File exists, approved by SHA-256 | `blocked` (`unregistered_delivery`; `checksum_mismatch` for an approved name with other bytes) |
| A geometry on every feature (`geometry_not_null`) | FAIL |
| Every `valid_on` equals the reference date (`valid_on_is_the_approved_period`) | FAIL |
| Coordinates in WGS 84 (`crs_is_wgs84`) | FAIL |
| `adm3_pcode` never blank | FAIL |
| `adm3_pcode` matches `^PH[0-9]{7}$`; unique; no fully repeated features | WARN, rows kept (source duplicates) |
| A geometry type other than Polygon or MultiPolygon (`geometry_types_allowed`) | WARN, rows kept |
| A byte-order mark at the start of the file (`no_byte_order_mark`) | WARN |

On the real file every one of these passed: no WARN and no FAIL.

After the MERGE: Bronze rows for the file equal the features (1,642), row numbers run 1..1642 with no repeats, and every provenance column is filled. Then the generated gate (`etl/02_bronze/90_validate_hdx_adm3_raw.sql`) checks the whole table.

### Bronze table (boundaries)

``edu_access.`02-bronze`.hdx_adm3_raw`` (generated: `etl/02_bronze/01_create_hdx_adm3_raw.sql`): the same provenance columns as DepEd, then the 31 properties and `geometry`, all as text. `source_archive` and `source_file` are both `phl_admin3.geojson`.

Rows are merged in chunks of at most `max_stage_bytes` (64 MB), because one polygon can be megabytes: the largest is 11.7 million characters. Each chunk is its own MERGE, so a run that stops part-way leaves the batch `loading`, and the retry adds only the missing rows. Locally, DuckDB's JSON row limit (16 MB by default) is raised to 1 GB so a large polygon fits.

The file is 555 MB. The reader never decodes the whole `features` list at once, but the file and its rows are held in memory, so a run peaks at about 1.7 GB.

### Retry, rerun, backfill, revision (boundaries)

| Term | Example | What happens |
|---|---|---|
| Skip | The same file again | Attempt logged `skip`; 0 rows |
| Retry | A run that stopped part-way through the chunks | Picked up automatically; MERGE adds only missing rows |
| Rerun | `--rerun hdx_boundaries__2025-02-13__f682747fbb26` | Validated and merged again; 0 rows |
| Incremental | A newer COD-AB edition (a later `valid_on`) | `blocked` until approved; then loaded with its own reference date beside the existing one |
| Backfill | An older edition | The same, as `backfill`; nothing rebuilt |
| Revised delivery | The same edition re-published with changes (same name, other bytes) | Before approval: `blocked`, `checksum_mismatch`, run fails, nothing overwritten. After approval as `delivery_version: 2` with `supersedes`: loaded beside v1; `current_batches` points to v2 |

<a id="boundaries-running-locally"></a>
### Running locally (boundaries)

In VS Code's terminal, from the repository root, with the virtual environment active:

```bash
python -m pytest tests -q
```

```bash
python -m src.ingestion.cli ingest --source hdx_boundaries
```

```bash
python -m src.ingestion.cli status --source hdx_boundaries
```

`RAW_DATA_DIR` must be set first, or given with `--landing <raw root>`; the file must be under `$RAW_DATA_DIR/admin_boundaries/`. Expected on the real file: one batch `load initial`, `inserted=1642 bronze=1642`, status `succeeded`, 24 PASS and no WARN or FAIL; the second run `skip`, `inserted=0`. If the first run reports `unknown_schema_drift`, the contract's property order and the file differ: do not change the data; correct the contract in review.

After changing the contract's schema, regenerate the SQL (a test fails until you do). In Windows PowerShell, `>` writes UTF-16, so run these from Git Bash, or have Python write the files as UTF-8:

```bash
python -m src.ingestion.cli ddl --source hdx_boundaries > etl/02_bronze/01_create_hdx_adm3_raw.sql
```

```bash
python -m src.ingestion.cli gate --source hdx_boundaries > etl/02_bronze/90_validate_hdx_adm3_raw.sql
```

### Databricks confirmation (boundaries)

**Done on 2026-10-08** (`dev`, job runs `275546090497316` then `990080691102176` and `370044913196063`, commit `67ea4a2`): load 1,642, then two skips; [evidence](../../evidence/pipeline-runs/2026-10-08-hdx-boundaries-databricks-idempotency.md). The first attempt (`555332578823580`) failed before loading anything, because the shared `dev` control tables carried #47's `job_run_id` column; #81's `control.py` fix (`7c0464b`) is included here.

In `edu_access_pipeline`, the boundaries have their own lane: `06_create_hdx_adm3_raw` → `bronze_hdx_boundaries` → `90_validate_hdx_adm3_raw` (D-020); the Silver tasks after it stay disabled. The runs above used the earlier `bronze_ingest` job, before the DAG merged; the lane runs the same load and gate code. Before running it, the pull request must be reviewed, the run announced to the team, and the `reached-hq` profile working. Then, as for DepEd ([Running on Databricks](#running-on-databricks)): `databricks bundle validate`, `deploy`, `summary`, `run` twice.

**Confirmed in the DAG on 2026-10-09** (run `876944030170305`, commit `e352330`): the lane's three tasks succeeded, the load skipped the already-loaded file (0 inserted, Bronze 1,642), and the gate passed as its own task ([evidence](../../evidence/pipeline-runs/2026-10-08-hdx-boundaries-databricks-idempotency.md#in-the-edu_access_pipeline-dag-after-113)).

That run confirmed what only Databricks could prove for this source (D-017): serverless has enough memory for the 555 MB file, and 64 MB chunks go through Spark Connect.

Validation queries (Databricks SQL editor):

```sql
-- The batch and its counts: expect 1 succeeded, expected = source = bronze = 1642
SELECT batch_id, school_year, delivery_version, load_type, status, expected_rows, source_rows, bronze_rows, error_code
FROM edu_access.`01-control`.ingestion_batches WHERE source_id = 'hdx_boundaries';

-- Load then skip: expect 'load' in run 1 and 'skip' with 0 rows in run 2
SELECT r.started_at_utc, a.action, a.outcome, a.rows_inserted
FROM edu_access.`01-control`.ingestion_batch_attempts AS a JOIN edu_access.`01-control`.pipeline_runs AS r USING (run_id)
WHERE a.source_id = 'hdx_boundaries' ORDER BY r.started_at_utc;

-- No pipeline duplicates: expect 0. Feature positions: expect 1 and 1642
SELECT COUNT(*) - COUNT(DISTINCT source_sha256, source_row_number), MIN(source_row_number), MAX(source_row_number)
FROM edu_access.`02-bronze`.hdx_adm3_raw;

-- Kept as written: expect 0 rows without geometry, the largest geometry 11727901 characters,
-- and feature 1's area exactly as in the file
SELECT COUNT_IF(geometry IS NULL) AS no_geometry, MAX(length(geometry)) AS largest_geometry_chars,
       MAX(CASE WHEN source_row_number = 1 THEN area_sqkm END) AS feature_1_area
FROM edu_access.`02-bronze`.hdx_adm3_raw;

-- Checks for the boundaries batch: expect no FAIL
SELECT check_name, status, expected, actual FROM edu_access.`01-control`.data_quality_results
WHERE source_id = 'hdx_boundaries' AND run_id = (SELECT MAX_BY(run_id, started_at_utc) FROM edu_access.`01-control`.pipeline_runs
                                                WHERE source_id = 'hdx_boundaries') ORDER BY status, check_name;

-- Where one row came from: expect Adams, Ilocos Norte, PH0102801
SELECT source_file, source_sha256, source_row_number, adm3_pcode, adm3_name, adm2_name, batch_id, run_id, code_revision
FROM edu_access.`02-bronze`.hdx_adm3_raw WHERE source_row_number = 1;
```

### Handoff to Silver (boundaries, not built here)

Silver should:

- read only rows whose `batch_id` is in `current_batches`;
- parse `geometry` into a spatial type, check validity, and record any repair rather than doing it silently;
- type the numbers (`area_sqkm`, `center_lat`, `center_lon`) and dates (`valid_on`, `valid_to`) from their stored text, without rounding;
- map `adm3_pcode` to PSGC only through a validated crosswalk: 1,500 of 1,642 match structurally (profile O-11), and the other 142 must not be forced by name; the join to PSGC belongs in Integration (D-012);
- record the boundary edition (`2025-02-13`) beside every result that uses it, since it differs from the DepEd school year and the PSGC quarter;
- keep `batch_id` and `source_row_number` on every row.

### Runbook (boundaries)

**1. How do I add a new COD-AB edition?**
Download it from the HDX COD-AB page; do not rename, convert, or re-save it. Upload it to `raw/admin_boundaries/<download date>/` (never over an existing file) with that folder's `SHA256SUMS.txt`. Profile it (`analysis/profiling/profile_boundaries.py`, with its name and checksum), update the card, and add the delivery to `config/ingestion/hdx_boundaries.json` in a pull request: `archive` and `data_member` (both the file name), both checksums (both the file's), `school_year` (its `valid_on` date), `document_sha256: {}`, `encoding`, `schema_version`, `row_count`, `retrieved_at_utc`. If the properties changed, add a schema version and regenerate the SQL. Then run the job.

**2. How do I know whether it was already processed?**
`python -m src.ingestion.cli status --source hdx_boundaries`, or the first validation query: `succeeded` for its SHA-256 means processed.

**3. What happens if the publisher replaces the file?**
The new bytes do not match the approved SHA-256: the batch is `blocked` (`checksum_mismatch`) and the run fails. Nothing is overwritten. If the change is real, approve it as `delivery_version: 2` with `supersedes` set to v1's checksum; both versions stay in Bronze.

**4. How do I inspect a failed batch?**

```sql
SELECT batch_id, status, failure_stage, error_code, error_message, attempt_count, last_run_id
FROM edu_access.`01-control`.ingestion_batches
WHERE source_id = 'hdx_boundaries' AND status IN ('failed', 'blocked', 'loading');
```

Then its checks: ``SELECT check_name, status, expected, actual FROM edu_access.`01-control`.data_quality_results WHERE batch_id = '<batch_id>'``.

**5. How do I safely rerun it?**
Fix the cause and run again: a `failed` or `loading` batch is retried and the MERGE adds only missing rows. To repeat a succeeded batch on purpose: `--rerun <batch_id>` (adds 0 rows).

**6. How do I verify the Bronze output?**
1,642 rows, feature positions 1 to 1642, no FAIL, no row without geometry, and one row traced to its feature with the last query above (feature 1 is Adams, Ilocos Norte).

**7. How do I prove the same batch did not create duplicates?**
Run twice. The attempts query shows `load` then `skip` with 0 rows, Bronze still has 1,642 rows, and the duplicate query returns 0. Locally, `tests/test_ingestion_boundaries.py::test_loads_once_and_a_rerun_skips` proves the same with made-up GeoJSON.

### Limitations and open questions (boundaries)

- Verified on made-up GeoJSON and on the real file locally (DuckDB); the Databricks run is pending.
- Only ADM3 is ingested; ingesting ADM4 would be a separate contract and table.
- Bronze does not check that polygons are valid shapes; that is Silver's job once the geometry is parsed.
- The 1.7 GB memory peak and the 64 MB chunks are proved only by the Databricks run (D-017).
- Update frequency and licensing terms are unverified (source card).

| Question | Default until decided | Where |
|---|---|---|
| Should `school_year` be renamed to a generic `period` for non-school sources? | Keep the column; it holds the reference date `2025-02-13` | D-019, D-026|
| Is storing geometry as raw GeoJSON text in Bronze the rule for spatial sources? | Raw text; parsed in Silver | D-026 |
| Should ADM4 (`phl_admin4.geojson`) be ingested? | Not now | Team (owner @saraevcldn) |
| Does `hdx_boundaries` move from `profiled` to `accepted`? | Stays `profiled`; loads to `local` and `dev` only | Team (owner @saraevcldn) |
