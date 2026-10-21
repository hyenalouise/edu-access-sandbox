# Evidence: the whole job, with the school boundary map and dim_school_location, succeeds on Databricks `dev`

Issue #217 · Databricks `dev`, workspace `dbc-2b6bf1c5-7bc3` (D-056) · 2026-10-21, Manila time (UTC+8) · run by @catweyine

## The claim

On Databricks `dev`, the whole job `edu_access_pipeline` succeeds when it is deployed from `feat/217-dim-school-location`. That deployment includes the new Integration map `deped_school_boundary_map` and the Gold dimension `dim_school_location`, which use the spatial functions on Databricks SQL. The job's other tasks, through the AP answers and the priority matrix, also succeed.

**Not claimed yet:** the row and status counts of the two new tables on `dev`, or their check results. See "Still to record".

## What was run

- **Job:** `[dev catherine_balane] edu_access_pipeline`, deployed with the bundle from `feat/217-dim-school-location`. The run's `code_revision` parameter starts `5b93…`, the branch head `5b930e8` ("Record the boundary map and dim_school_location run on the real data").
- **Job run `105906346445720`:** started 2026-10-21 12:52 PM and launched manually. **Status: Succeeded**, in 22 min 7 s.

Read from the job's run page. The task grid shows this run green for every Analytics task listed (`01_answer_ap1` to `04_answer_ap4`, their gates, `05_build_priority_matrix`, `90_validate_priority_matrix`). Since the job run succeeded, every enabled task succeeded, which includes:
- `06_map_deped_school_boundary` and `90_validate_deped_school_boundary_map`;
- `07_build_dim_school_location` and `90_validate_dim_school_location`.

## Still to record

Run each of these on `dev` and add the results here. The expected values are from the local run on the same files ([2026-10-21-dim-school-location-gold.md](../reconciliation/2026-10-21-dim-school-location-gold.md)).

1. **Statuses.** Expected: `inside` 44,968 · `outside` 1,997 · `no_usable_point` 738 · `no_boundary` 97 · `no_matched_city` 18.

   ```sql
   SELECT boundary_status, COUNT(*) AS schools
   FROM edu_access.`05-gold`.dim_school_location GROUP BY 1 ORDER BY 2 DESC;
   ```
2. **Checks.** Expected: Integration 17 PASS + 1 WARN (`schools_outside_boundary`), Gold 7 PASS.

   ```sql
   SELECT layer, status, COUNT(*) AS checks
   FROM edu_access.`01-control`.data_quality_results
   WHERE source_id IN ('deped_psgc_coordinates', 'dim_school_location') AND layer IN ('integration', 'gold')
     AND checked_at_utc >= TIMESTAMP '2026-10-21 04:00:00'
   GROUP BY 1, 2 ORDER BY 1, 2;
   ```
3. **The map run.** Expected: `succeeded`.

   ```sql
   SELECT run_id, status FROM edu_access.`01-control`.pipeline_runs
   WHERE pipeline_name = 'integration_build' AND source_id = 'deped_psgc_coordinates'
   ORDER BY started_at_utc DESC LIMIT 1;
   ```

## Not checked here

- Per-task durations of the new tasks, and their query plans.
- A second run on `dev` to show the rebuild is identical there. It was shown locally.
