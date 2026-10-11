# Evidence: the source-lane fan-in checks every Silver lane on Databricks, and Integration starts only from it

Issue #127 · Databricks `dev` · 2026-10-11 · checked by @hyenalouise

## The claim

With `90_validate_control` switched on (D-039), a job run on Databricks runs it after the Silver gates have finished. It writes one `silver_lane_succeeded` result per Silver lane switched on, PASS for each lane whose `silver_build` run in the same job run succeeded, stamped with the commit that ran, and succeeds. The three map tasks depend only on it.

## What was run

The job `[dev ina_magno] edu_access_pipeline` (job `651937364323543`), deployed with `databricks bundle deploy --target dev --profile reached-hq` from a clean checkout of the pushed commit `1962bce2fc566b6846ea35e5bbedca76e4afbd37` (`bundle validate` OK). Read back from `databricks bundle summary` before running:
- the git commit and the `code_revision` parameter both equal that commit
- `90_validate_control` is enabled, `run_if: ALL_DONE`, waiting for all six Silver gates
- `01_map_deped_school_psgc`, `02_map_psa_poverty_psgc`, and `03_map_hdx_adm3_psgc` are disabled and depend only on `90_validate_control`

CI ("Repository checks") passed on that commit. The job was run once with `databricks bundle run edu_access_pipeline --target dev --profile reached-hq`. Times are Manila (UTC+8).

### Job details: the three maps with one arrow each, from 90_validate_control
<img width="1262" height="660" alt="image" src="https://github.com/user-attachments/assets/e782efe8-c78f-4bc6-ac00-6753c1895c6d" />

| | Job run `43200517535648` |
|---|---|
| Whole job | 17:49:11 to 17:55:36 (09:49:11 to 09:55:36 UTC), 6 min 25 s, `SUCCESS` |
| Tasks | 29 `SUCCESS`, 34 disabled |
| `90_validate_deped_enrollment_clean` | `SUCCESS`, 89 s, from 17:53:55 |
| `90_validate_psa_poverty_stat_clean` | `SUCCESS`, 86 s, from 17:54:02 |
| `90_validate_control` | `SUCCESS`, 6 s, from 17:55:28, once the last Silver gate had finished |
| The three map tasks | `DISABLED` (placeholders), after `90_validate_control` |

The Silver lanes switched on at this commit are `deped_enrollment` and `psa_poverty_stat`. The other four Silver gates (facilities, personnel, PSGC, HDX) are disabled on `main`, so the fan-in waited for them as finished and did not check them.

### Run timeline: 90_validate_control after the Silver gates, the maps disabled
<img width="1263" height="629" alt="image" src="https://github.com/user-attachments/assets/9878756d-d14f-49a4-b6ff-ca25dea64c54" />

## Results

On the SQL warehouse after the run:

| Check | Expected | Actual | Result |
|---|---|---|---|
| fan-in results in this run (`layer = 'control'`) | 2 | 2 | OK |
| fan-in results that are FAIL | 0 | 0 | OK |
| lanes checked | deped_enrollment, psa_poverty_stat | deped_enrollment, psa_poverty_stat | OK |
| `actual` of each result | succeeded, succeeded | succeeded, succeeded | OK |
| commit on the results | `1962bce…` | `1962bce…` | OK |
| `silver_build` runs in this job run | deped_enrollment succeeded, psa_poverty_stat succeeded | the same | OK |

### Fan-in results: two PASS rows
<img width="884" height="225" alt="image" src="https://github.com/user-attachments/assets/28919555-3965-46c6-b5e1-cd13d49ca379" />

What this run confirms that the local runs could not (D-017): Spark runs the generated SQL as DuckDB does, including `VALUES … AS l(source_id)` joined to `pipeline_runs`, the session variable that limits the check to this execution, and `raise_error` in a `CASE` that does not fire. Databricks also runs an `ALL_DONE` task after every Silver gate, disabled ones included.

## Limitations

- A failing lane was not exercised on Databricks, to keep the shared `dev` tables at a good build. `tests/test_local_job.py` shows it locally: when enrollment's Bronze gate fails, the fan-in still runs, records enrollment as `not run` and PSA as `succeeded`, and fails.
- The maps are disabled placeholders, so "Integration does not run when a lane fails" is shown by the fan-in failing, not yet by a skipped map.
- Since this run, `dev` holds #128's job definition, with facilities Silver disabled. A later facilities run (#126) needs a deploy from that branch first.

## How to reproduce

From a clean checkout of the commit above: `databricks bundle validate` and `databricks bundle deploy --target dev --profile reached-hq`, confirm the deployed commit and the layout with `databricks bundle summary`, then `databricks bundle run edu_access_pipeline --target dev --profile reached-hq`. On the SQL warehouse, with the job run id filled in:

```sql
WITH d AS (SELECT * FROM edu_access.`01-control`.data_quality_results WHERE layer = 'control' AND run_id = '<job run id>'),
pr AS (SELECT * FROM edu_access.`01-control`.pipeline_runs WHERE pipeline_name = 'silver_build' AND run_id = '<job run id>')
SELECT 'control results' AS check_name, '2' AS expected, CAST(COUNT(*) AS STRING) AS actual FROM d
UNION ALL SELECT 'control FAIL', '0', CAST(COUNT_IF(status = 'FAIL') AS STRING) FROM d
UNION ALL SELECT 'lanes', 'deped_enrollment, psa_poverty_stat', array_join(sort_array(collect_list(source_id)), ', ') FROM d
UNION ALL SELECT 'actuals', 'succeeded, succeeded', array_join(collect_list(actual), ', ') FROM d
UNION ALL SELECT 'commit on results', '1962bce2fc566b6846ea35e5bbedca76e4afbd37', array_join(collect_set(code_revision), ', ') FROM d
UNION ALL SELECT 'silver_build runs this job run', 'deped_enrollment succeeded, psa_poverty_stat succeeded',
  array_join(sort_array(collect_list(source_id || ' ' || status)), ', ') FROM pr;
```
