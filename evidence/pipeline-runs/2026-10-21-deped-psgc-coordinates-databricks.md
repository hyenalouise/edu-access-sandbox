# Evidence: the public-only DepEd PSGC and coordinates workbook loads into Bronze on Databricks `dev`, and a missing workbook now fails the lane

Issue #217 · Databricks `dev`, workspace `dbc-2b6bf1c5-7bc3` (D-056) · 2026-10-21, Manila time (UTC+8) · run by @catweyine

## The claim

On Databricks `dev`, lane 09 of `edu_access_pipeline` loads `SY 2023-2024 School Level Data on Enrollment with PSGC Longitude & Latitude (Public only).xlsx` from the raw volume into `` edu_access.`02-bronze`.deped_psgc_coordinates_raw ``: 47,818 rows, the same count as the approved delivery and the [local run](2026-10-21-deped-psgc-coordinates-local-idempotency.md). When the workbook is missing from the volume, the load task fails instead of succeeding with an empty table.

**Not claimed yet:** that a second run on `dev` inserts nothing, and the `dev` check results by status. See "Still to record".

## What was run

- Job `edu_access_pipeline`, job ID `381037344478146`, deployed from `feat/deped-psgc-coordinates` with `databricks bundle deploy --target dev --profile reached-hq`. The task panel shows `src/ingestion/cli.py` at commit `1471ff50` (`1471ff502371ed7f66758c8dfaaf23fcfeae853d`), the branch head at the time.
- Job run `190580077355703`, run as @catweyine. Only lane 09's Bronze tasks were rerun, with **Repair run**: `bronze_deped_psgc_coordinates` and `90_validate_deped_psgc_coordinates_raw`.

## What happened, in order

| Step | Observed |
|---|---|
| 1. First run, at the commit before `1471ff5` | `09_create_deped_psgc_coordinates_raw` created the table, and the load task succeeded, but `SELECT * FROM deped_psgc_coordinates_raw` returned no rows. The volume folder `/Volumes/edu_access/00-source/raw/deped/` held only the all-sector workbook (`…with PSGC, Longitude and Latitude.xlsx`), not the public-only one. A missing approved workbook was then only a WARN (`approved_deliveries_present`), and lane 09's Silver is disabled, so nothing failed |
| 2. Fix | `1471ff5` sets `require_approved_deliveries: true` in `config/ingestion/deped_psgc_coordinates.json`, as for PSGC, so a missing approved workbook fails the run (`tests/test_ingestion_psgc_coordinates.py::test_a_missing_approved_workbook_fails_the_run`) |
| 3. Repair at `1471ff5`, workbook still missing | Task run `897445617253795` of `bronze_deped_psgc_coordinates`, 03:25 to 03:26 (59 s): **Failed**, `SystemExit: 1`. The gate was not run. The lane now stops instead of passing empty |
| 4. Upload | The public-only workbook was uploaded to `/Volumes/edu_access/00-source/raw/deped/` under its own name, next to the all-sector one |
| 5. Repair again | `bronze_deped_psgc_coordinates` ran about 20 minutes, most of it waiting for Free Edition serverless capacity, then finished |
| 6. Result | `SELECT COUNT(*) FROM edu_access.`02-bronze`.deped_psgc_coordinates_raw` returns **47,818**, equal to the approved `row_count` and the local run |

## Still to record

Run each, then add the results here:

1. **Repair the same two tasks once more.** `COUNT(*)` must stay 47,818.
2. **The attempts:** expected one `load`/`succeeded` attempt inserting 47,818 rows, then one `skip`/`skipped` inserting 0.

   ```sql
   SELECT a.action, a.outcome, a.rows_inserted, a.run_id, a.started_at_utc
   FROM edu_access.`01-control`.ingestion_batch_attempts a
   JOIN edu_access.`01-control`.ingestion_batches b ON a.batch_id = b.batch_id
   WHERE b.source_id = 'deped_psgc_coordinates' ORDER BY a.started_at_utc;
   ```
3. **The checks:** expected PASS only after the successful load, besides step 3's `approved_deliveries_present` FAIL.

   ```sql
   SELECT status, COUNT(*) AS n FROM edu_access.`01-control`.data_quality_results
   WHERE source_id = 'deped_psgc_coordinates' GROUP BY 1;
   ```

## Not checked here

- Per-column values on `dev`. They were checked on the same file locally; the Spark backend reads the workbook with the same Python code.
- Silver: a disabled placeholder.
