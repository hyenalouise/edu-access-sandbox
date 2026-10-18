# Evidence: downstream tasks start from the gates they read, and the fan-in is an audit

PR #166 · D-051 · Databricks `dev` · 2026-10-18 · checked by @hyenalouise

## The claim

With D-051, each Integration, Gold, and Analytics task depends on the gates of the tasks it reads, not on `90_validate_control`. On Databricks:

1. The only live Integration map, `04_map_deped_annex_mother`, starts as soon as the enrollment Silver gate passes, without waiting for the other lanes.
2. `90_validate_control` starts once every Silver gate has finished, and `90_validate_freshness` follows it. A disabled task resolves only after the tasks before it, so the fan-in, and therefore freshness, also waits for the EMISD Bronze load, whose Silver tasks are still placeholders.
3. The fan-in still writes one `silver_lane_succeeded` result per Silver lane switched on, and every result carries the commit that ran.

## What was run

The job `[dev ina_magno] edu_access_pipeline` (job `651937364323543`), deployed with `databricks bundle deploy --target dev --profile reached-hq` from a clean checkout of the pushed commit `135c1ace77313358b786a1011dbf3850c577a88d` (`bundle validate` OK; 90 tasks). The job's `code_revision` parameter equals that commit. No other job run was active in the workspace before the deploy or before the run (`databricks jobs list-runs --active-only`). It was run once with `databricks bundle run edu_access_pipeline --target dev --profile reached-hq`. Times are Manila (UTC+8).

| | Job run `18257140364359` |
|---|---|
| Whole job | 11:08:11 to 11:16:37 (03:08:11 to 03:16:37 UTC), 8 min 26 s, `SUCCESS` |
| Tasks | 43 `SUCCESS`, 47 disabled |
| Every file | Already loaded, so each load skipped and inserted nothing |

Later commits on the branch change only comments and documentation, including one comment line in the generated `90_validate_control.sql`. No dependency or SQL statement changed after `135c1ac`.

## Results

### Run graph: the annex map hangs off the enrollment gate, and only freshness follows the fan-in
<img width="1080" height="367" alt="image" src="https://github.com/user-attachments/assets/11430719-e976-45ab-b8c5-22e83522c9a6" />

### 1. The annex map does not wait for other lanes

| Task | Start | End |
|---|---|---|
| `90_validate_deped_enrollment_clean` | 11:12:53 | 11:14:04 |
| `04_map_deped_annex_mother` | **11:14:04** | 11:14:10 |
| `90_validate_deped_annex_mother_map` | 11:14:10 | 11:14:21 |
| `90_validate_deped_personnel_clean` | 11:13:00 | 11:14:18 |
| `06_clean_hdx_adm3` | 11:15:19 | 11:15:50 |
| `90_validate_hdx_adm3_clean` | 11:15:50 | 11:16:26 |

The annex map started the moment the enrollment Silver gate passed. The personnel gate was still running, and HDX had not started cleaning. The annex map and its gate had finished before HDX began. Under D-039 the map would have waited for `90_validate_control` to finish at 11:16:32, about two and a half minutes later.

### Run timeline: the annex map finishes while personnel and HDX are still running
<img width="1307" height="455" alt="image" src="https://github.com/user-attachments/assets/e11b97c7-3e03-4da7-9647-51d1dade777a" />

### 2. Freshness follows the fan-in, after every Bronze load

| Task | `run_if` | Start | End | Result |
|---|---|---|---|---|
| `90_validate_deped_enrollment_psgc_raw` (EMISD Bronze) | `ALL_SUCCESS` | 11:15:08 | 11:15:19 | `SUCCESS` |
| `07_clean_deped_enrollment_psgc`, `90_validate_deped_enrollment_psgc_clean` (EMISD Silver placeholders) | `ALL_SUCCESS` | resolved 11:15:19 | — | `DISABLED` |
| `90_validate_hdx_adm3_clean` (last Silver gate) | `ALL_SUCCESS` | 11:15:50 | 11:16:26 | `SUCCESS` |
| `90_validate_control` | `ALL_DONE` | 11:16:27 | 11:16:32 | `SUCCESS` |
| `90_validate_freshness` | `ALL_DONE` | 11:16:32 | 11:16:37 | `SUCCESS` |

The disabled EMISD Silver tasks resolved at 11:15:19, the second the EMISD Bronze gate finished, not at the start of the run. So the fan-in, which waits for every Silver gate including placeholders, waited for the EMISD load, and freshness, which waits only for the fan-in, checked EMISD's latest batch after that load had finished.

### Timeline: the fan-in, then freshness, after the last Silver gate
<img width="710" height="250" alt="image" src="https://github.com/user-attachments/assets/3c0fdaf0-14d9-44ea-8aeb-9dd8704a4768" />

### 3. Control results for this run

On the SQL warehouse after the run (`run_id = '18257140364359'`):

| Check | Expected | Actual | Result |
|---|---|---|---|
| `silver_lane_succeeded` results | 6, one per Silver lane switched on | 6 | OK |
| … that are PASS | 6 | 6 (`deped_enrollment`, `deped_facilities`, `deped_personnel`, `hdx_boundaries`, `psa_poverty_stat`, `psa_psgc`) | OK |
| `source_fresh` results | 7, one per loaded source | 7, all PASS | OK |
| `code_revision` on every control result | `135c1ac…` | `135c1ac…` | OK |
| `pipeline_runs` for this job run | 7 `bronze_ingest`, 6 `silver_build`, all succeeded | the same | OK |
| FAIL results in this run, any layer | 0 | 0 | OK |

### Control results: 6 lane PASS and 7 freshness PASS, all at `135c1ac`
<img width="1018" height="366" alt="image" src="https://github.com/user-attachments/assets/6c037e2b-52f9-49b3-af19-c712d54ef762" />

The run wrote 424 results: 21 Bronze, 382 Silver, 8 Integration, and 13 control, of which 414 PASS and 10 WARN. The WARNs are expected and unchanged by this PR: 2,331 annexes without a mother school (D-044), and nine PSA poverty flags (coefficient of variation over 20%, a non-positive lower limit, and SE/CV inconsistencies) for 2018, 2021, and 2023.

## Earlier runs of this branch

None of these is the evidence; they are listed so their outcomes are not mistaken for faults.

| Job run | Commit | Outcome | Why |
|---|---|---|---|
| `548256684216044` | `6386c34` | Cancelled | Cancelled by hand during `06_clean_hdx_adm3`. The annex map had already started one second after the enrollment gate |
| `1106317898727605` | `12fe065` | Failed | Started nine seconds after another dev run. Both recreated `edu_access.03-silver.deped_personnel_gate_summary_candidate` at once, so the personnel gate failed on `INSUFFICIENT_PERMISSIONS` while the other run briefly owned the table, and the fan-in correctly failed the run. A collision between runs, not a code fault: dev jobs share the `edu_access` catalog, so only one should run at a time |
| `268106548429452` | `8d3f6e8` | Succeeded | The graph changed afterwards (the `dim_education_level` edge, peer tasks removed, freshness after the fan-in, the `dim_city_poverty` edge), so its evidence was withdrawn |
| `459045485758393` | `5b82a25` | Cancelled | Cancelled by hand three minutes in, to review the graph |
| `4394799964779` | `4346442` | Cancelled | Cancelled to remove freshness's direct Bronze edges before running again |

## How to reproduce

Run these on the SQL warehouse after the job run has finished, never while a run is going. For another run, replace the run id.

1. The fan-in and freshness results, expected 6 `silver_lane_succeeded` and 7 `source_fresh`, all PASS, all with `code_revision` `135c1ac…`:

   ```sql
   SELECT check_name, source_id, status, actual, code_revision
   FROM edu_access.`01-control`.data_quality_results
   WHERE run_id = '18257140364359' AND layer = 'control'
   ORDER BY check_name, source_id;
   ```

2. Every result in the run by layer and status, expected 21 Bronze, 382 Silver, 8 Integration, 13 control; 414 PASS, 10 WARN, no FAIL:

   ```sql
   SELECT layer, status, COUNT(*) AS results
   FROM edu_access.`01-control`.data_quality_results
   WHERE run_id = '18257140364359'
   GROUP BY layer, status
   ORDER BY layer, status;
   ```

3. The WARN rows, expected the annex count (2,331) and nine PSA poverty flags:

   ```sql
   SELECT layer, source_id, check_name, actual
   FROM edu_access.`01-control`.data_quality_results
   WHERE run_id = '18257140364359' AND status = 'WARN'
   ORDER BY layer, source_id, check_name;
   ```

4. The loads and Silver builds in the run, expected 7 `bronze_ingest` and 6 `silver_build`, all succeeded:

   ```sql
   SELECT pipeline_name, source_id, status
   FROM edu_access.`01-control`.pipeline_runs
   WHERE job_run_id = '18257140364359'
   ORDER BY pipeline_name, source_id;
   ```

5. The annex map's gate, expected 7 PASS and `annexes_without_mother_school` WARN with 2,331:

   ```sql
   SELECT check_name, status, actual
   FROM edu_access.`01-control`.data_quality_results
   WHERE run_id = '18257140364359' AND layer = 'integration'
   ORDER BY check_name;
   ```

6. Task start and end times, which the tables above come from, including when each disabled task resolved:

   ```bash
   databricks jobs get-run 18257140364359 --profile reached-hq -o json
   ```
