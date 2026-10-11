# Evidence: DepEd facilities Silver builds and passes its gate on Databricks, and a second run rebuilds identical rows

Issue #86 · Databricks `dev` · 2026-10-11 · checked by @hyenalouise

The runs below are at `6b2844d`, when the facilities gate also waited for the enrollment Silver gate. Review then moved the enrollment check to Integration and made the lane parallel; the confirmation runs at that commit, `9197926`, are in [Re-run at `9197926`](#re-run-at-9197926-the-parallel-lane).

## The claim

The two facilities Silver SQL tasks of `edu_access_pipeline`, run by Spark on the SQL warehouse after the enrollment Silver gate, build `deped_facilities_clean` and `deped_facilities_quarantine` with the same result as the [local runs](../reconciliation/2026-10-11-deped-facilities-bronze-to-silver.md): 60,167 clean rows, 0 quarantined, every school in enrollment Silver, counts, TRUE values and blanks equal to Bronze, and all 38 gate checks PASS. A second run rebuilds rows identical to the first, apart from the run stamp, and records a second `succeeded` run.

## What was run

The job `[dev ina_magno] edu_access_pipeline` (job `651937364323543`), deployed with `databricks bundle deploy --target dev --profile reached-hq` from a clean checkout of the pushed commit `6b2844dbb82ab596384f70160f0439cbe7e97654` (`databricks bundle validate` OK first). Read back from `databricks bundle summary` before running: the bundle's git commit and the `code_revision` parameter both equal that commit, and the two facilities Silver tasks are enabled. The job was then run twice with `databricks bundle run edu_access_pipeline --target dev --profile reached-hq`. Times are Manila (UTC+8).

### Job details: the task graph with the facilities Silver tasks enabled, and code_revision 6b2844d
<img width="1437" height="567" alt="image" src="https://github.com/user-attachments/assets/7666984d-7568-4f64-9895-bea0193b2120" />

| | Run 1 | Run 2 |
|---|---|---|
| Job run (`run_id` of the Silver rows) | `1045250185878076` | `700607904560713` |
| Whole job | 13:24:34 to 13:32:01 (05:24:34 to 05:32:01 UTC), 7 min 26 s, `SUCCESS` | 13:33:05 to 14:01:16 (05:33:05 to 06:01:16 UTC), 28 min 10 s, `SUCCESS` |
| Tasks | 30 `SUCCESS` on the first attempt, 33 disabled | same |
| `add_control_columns` | 43 s (setup 3 s) | 688 s (**setup 455 s**, execution 233 s) |
| `bronze_deped_facilities` | skip, 0 inserted, 102 s (setup 2 s) | skip, 0 inserted, 633 s (**setup 525 s**) |
| `90_validate_deped_facilities_raw` | 35 s | 56 s |
| `02_clean_deped_facilities` | 52 s | 60 s |
| `90_validate_deped_enrollment_clean` (ends) | 13:30:54 | 14:00:06 |
| `90_validate_deped_facilities_clean` | 64 s, from 13:30:54 | 66 s, from 14:00:07 |

No task waited in a queue. Run 2's extra 21 minutes are serverless setup of two Python tasks ("Waiting for cluster" in the UI): Free Edition's shared serverless capacity, not this change, which touches neither task. The facilities SQL took about the same in both runs.

The facilities gate now depends on the enrollment Silver gate (D-038). In run 1 the facilities build finished at 13:28:59 and its gate started at 13:30:54, when the enrollment Silver gate ended: about 115 s of waiting that the job did not have before.

### Run 1 timeline: every enabled task green, 90_validate_deped_facilities_clean after both 02_clean_deped_facilities and 90_validate_deped_enrollment_clean
<img width="1436" height="663" alt="image" src="https://github.com/user-attachments/assets/759a550b-ec9b-4d21-8c0e-6a5923d168d1" />

### Run 2 timeline: the same 30 tasks green, add_control_columns 11m 28s
<img width="1441" height="668" alt="image" src="https://github.com/user-attachments/assets/20f3782a-301f-4564-93f5-d52a4762060c" />

### Run 2 setup waits: add_control_columns (11m 28s) and bronze_deped_facilities (10m 33s), mostly setup ("Waiting for cluster")
<img width="751" height="415" alt="image" src="https://github.com/user-attachments/assets/95f5f199-589d-4610-9eae-1806c2eb5d65" />
<img width="716" height="422" alt="image" src="https://github.com/user-attachments/assets/284a764d-2ef4-4f08-b116-0e4307533bc8" />


## Results

The verification query below, run on the SQL warehouse after run 2:

| Check | Expected | Actual | Result |
|---|---|---|---|
| clean rows SY 2023-24 | 60167 | 60167 | OK |
| quarantined rows | 0 | 0 | OK |
| repeated keys | 0 | 0 | OK |
| schools not in enrollment Silver | 0 | 0 | OK |
| has_facility_data | 47817 | 47817 | OK |
| es_classrooms_missing | 669 | 669 | OK |
| is_overseas | 33 | 33 | OK |
| counts_reconcile | 1213740 | 1213740 | OK |
| true_values_reconcile | 458922 | 458922 | OK |
| missing_counts_stay_null | 626515 | 626515 | OK |
| missing_booleans_stay_null | 2800050 | 2800050 | OK |
| checks in the last run | 38 | 38 | OK |
| checks in the last run not PASS | 0 | 0 | OK |
| rows from the last run | 60167 | 60167 | OK |
| rows from another commit | 0 | 0 | OK |
| last silver run | succeeded | succeeded | OK |
| silver runs succeeded at this commit | 2 | 2 | OK |
| candidate rows not published | 0 | 0 | OK |
| INT columns / BOOLEAN columns | 22 / 66 | 22 / 66 | OK |

After run 1 the same query gave the same values, with 1 run at this commit. `content_sha256` (every clean column except the run stamp) was `215d71392756655b873b33c1cfaa2b3b6616280ebe1a6888a3c140bea6c6b68c` after both runs.

### Verification query after run 2: 20 rows, 19 OK and the content hash
<img width="1012" height="502" alt="image" src="https://github.com/user-attachments/assets/800cac7b-be01-48bb-87b8-651d10558801" />

Also checked on the warehouse:

| Check | Result |
|---|---|
| Gate results of the two runs | facilities: 76 Silver results (38 per run) and 6 Bronze results (3 per run), all PASS |
| Bronze rerun | `bronze_deped_facilities` skipped its one batch in both runs, 0 rows inserted |
| Silver runs | `pipeline_runs` holds exactly two facilities `silver_build` runs, both `succeeded`: the two job runs above |
| Every source in run 2 | `succeeded` for every `pipeline_runs` row of job run `700607904560713`: Bronze and Silver for enrollment, facilities and PSA Poverty Stat, Bronze for personnel, PSGC and HDX |
| Owners | `deped_facilities_clean`, `deped_facilities_quarantine`, and both candidates are owned by `reached-hq` (D-009) |
| Identical rebuild | Delta versions 0 (run 1, the table's first) and 1 (run 2) of `deped_facilities_clean`, without `run_id`, `cleaned_at_utc`, and `code_revision`: 0 rows in either `EXCEPT ALL` direction |

### Gate results of the two runs: bronze PASS 6, silver PASS 76
<img width="1003" height="199" alt="image" src="https://github.com/user-attachments/assets/49f07ccc-affa-41c7-8573-5d265ad6125a" />

### Owners: the four facilities Silver tables owned by reached-hq
<img width="1010" height="203" alt="image" src="https://github.com/user-attachments/assets/ed947c0d-7c18-427b-b114-521c10e950f5" />

### DESCRIBE HISTORY deped_facilities_clean: versions 0 and 1 are the two runs
<img width="1009" height="204" alt="image" src="https://github.com/user-attachments/assets/bbb2d09a-019e-401e-90ec-256049c7101f" />

#### Versions 0 and 1 compared: 0 and 0
<img width="1006" height="204" alt="image" src="https://github.com/user-attachments/assets/983f8207-9056-4f56-9111-11e51e98a225" />

What these runs confirm that the local runs could not (D-017): Spark runs the facilities SQL as DuckDB does, including the 81-term `has_facility_data` expression, `IS DISTINCT FROM`, `split` and `array_contains` on the quarantine reasons, the gate's join to the published enrollment Silver, the job waiting for two upstream tasks (`depends_on` on the enrollment Silver gate), and `CREATE OR REPLACE TABLE` creating the four facilities tables in Unity Catalog with ownership handed to the group.

## Re-run at `9197926`: the parallel lane

After review, facilities Silver reads only its own Bronze, its lane waits for no other source, and the enrollment check is left to Integration (#91, D-038). The job was deployed from a clean checkout of the pushed commit `9197926689e286762edca8acbdea459408713b32` (`bundle validate` OK; `bundle summary` showed that commit as the git commit and the `code_revision` parameter, `02_clean_deped_facilities` depending only on `90_validate_deped_facilities_raw`, and `90_validate_deped_facilities_clean` only on the build) and run twice. CI ("Repository checks") passed on that commit.

| | Run 1 | Run 2 |
|---|---|---|
| Job run | `89482607322789` | `948438707623608` |
| Whole job | 16:22:20 to 16:29:30 (08:22:20 to 08:29:30 UTC), 7 min 10 s, `SUCCESS` | 16:30:35 to 16:35:46 (08:30:35 to 08:35:46 UTC), 5 min 10 s, `SUCCESS` |
| Tasks | 30 `SUCCESS`, 33 disabled | same |
| `bronze_deped_facilities` | skip, 0 inserted, 107 s | skip, 0 inserted, 92 s |
| `90_validate_deped_facilities_raw` | 41 s | 18 s |
| `02_clean_deped_facilities` | 63 s, from 16:26:23, right after its own Bronze gate | 59 s, from 16:33:06 |
| `90_validate_deped_facilities_clean` | 119 s, from 16:27:27 | 91 s, from 16:34:05 |
| `90_validate_deped_enrollment_clean` | 16:27:21 to 16:29:28 | 16:34:00 to 16:35:32 |

The two Silver gates ran at the same time in both runs: the lanes are parallel, and the facilities build no longer waits for enrollment. No task queued; setup was at most 3 s.

### Job details: the facilities lane with no link to enrollment, code_revision 9197926
<img width="1461" height="623" alt="image" src="https://github.com/user-attachments/assets/338c7bcb-573b-4bce-8dd7-5c654ce27c15" />

### Run 1 timeline: the two Silver gates side by side
<img width="1445" height="636" alt="image" src="https://github.com/user-attachments/assets/cd6da7a4-3db2-483f-92a3-acd1878e3869" />

### Run 2 timeline: the same 30 tasks green
<img width="1455" height="626" alt="image" src="https://github.com/user-attachments/assets/477b518e-d536-4b3b-b5ae-0880145e9f6a" />

The verification query (below, with the commit filled in and `checks in the last run` expecting 37) after run 2: all 20 rows OK, including 2 succeeded runs at this commit and `content_sha256` `215d71392756655b873b33c1cfaa2b3b6616280ebe1a6888a3c140bea6c6b68c`, now the expected value: the same as after both runs at `6b2844d`. Also checked:

| Check | Result |
|---|---|
| Gate results of the two runs | 74 Silver results (37 per run) and 6 Bronze results, all PASS |
| Bronze rerun | `bronze_deped_facilities` skipped its one batch in both runs |
| Owners | the four facilities Silver tables still owned by `reached-hq` |
| Identical rebuild | Delta versions 2 (run 1) and 3 (run 2): 0 rows in either `EXCEPT ALL` direction |
| Unchanged by review | Version 1 (run 2 at `6b2844d`) and version 3: 0 rows in either direction |

The four reconciled totals in that query (1,213,740 / 458,922 / 626,515 / 2,800,050) also equal the published CSV, counted without the pipeline ([local record](../reconciliation/2026-10-11-deped-facilities-bronze-to-silver.md#the-published-file-counted-without-the-pipeline)).

### Verification query after run 2: 20 rows, all OK
<img width="1026" height="503" alt="image" src="https://github.com/user-attachments/assets/0ff31489-8b3a-43a3-9d56-b374f486fc9d" />

### Gate results of the two runs: bronze PASS 6, silver PASS 74
<img width="676" height="206" alt="image" src="https://github.com/user-attachments/assets/1b5295d9-88a3-43a6-837b-6feedf533d36" />

### DESCRIBE HISTORY deped_facilities_clean: versions 2 and 3 are the two runs
<img width="946" height="199" alt="image" src="https://github.com/user-attachments/assets/722b0453-f3bc-4eae-86d3-42d0a3c57fd0" />

#### Versions 2 and 3 compared: 0 and 0
<img width="942" height="202" alt="image" src="https://github.com/user-attachments/assets/be557a49-e7b3-4d6a-8a8d-83d4ed8d182f" />

A run in between, `358678952220373` at `77821bc` (the build then waited for the enrollment Silver gate), was cancelled by hand during its facilities gate to correct the job layout. It left one facilities `silver_build` row `running` in `pipeline_runs`, never published: Gold trusts only `succeeded` runs (D-025), and the next build replaced its candidate tables.

## Limitations

- No real row is quarantined, and every school is in enrollment, so quarantine and the `school_id_in_enrollment` FAIL are shown on Databricks only by the checks passing on clean data; the made-up rows of `tests/test_silver_facilities.py` show the rest locally.
- A failing facilities gate was not exercised on Databricks, to keep the shared `dev` tables at a good build.
- Run 2's setup waits make the whole-job time an upper bound for Free Edition, not a cost of the facilities tasks.

## How to reproduce

From a clean checkout of the commit above: `databricks bundle validate` and `databricks bundle deploy --target dev --profile reached-hq`, confirm the deployed commit with `databricks bundle summary`, then `databricks bundle run edu_access_pipeline --target dev --profile reached-hq` twice. On the SQL warehouse, with the commit filled in:

```sql
WITH c AS (SELECT * FROM edu_access.`03-silver`.deped_facilities_clean),
     q AS (SELECT * FROM edu_access.`03-silver`.deped_facilities_quarantine),
     e AS (SELECT school_year, school_id FROM edu_access.`03-silver`.deped_enrollment_clean),
     pr AS (SELECT * FROM edu_access.`01-control`.pipeline_runs WHERE pipeline_name = 'silver_build' AND source_id = 'deped_facilities'),
     last_run AS (SELECT MAX_BY(run_id, started_at_utc) AS run_id FROM pr),
     d AS (SELECT * FROM edu_access.`01-control`.data_quality_results
           WHERE layer = 'silver' AND source_id = 'deped_facilities' AND run_id = (SELECT run_id FROM last_run)),
checks AS (
  SELECT 'clean rows SY 2023-24' AS check_name, '60167' AS expected, CAST(COUNT(*) AS STRING) AS actual FROM c
  UNION ALL SELECT 'quarantined rows', '0', CAST(COUNT(*) AS STRING) FROM q
  UNION ALL SELECT 'repeated keys', '0', CAST(COUNT(*) - COUNT(DISTINCT school_id, school_year) AS STRING) FROM c
  UNION ALL SELECT 'schools not in enrollment Silver', '0', CAST(COUNT(*) AS STRING) FROM c LEFT ANTI JOIN e USING (school_year, school_id)
  UNION ALL SELECT 'has_facility_data', '47817', CAST(COUNT_IF(has_facility_data) AS STRING) FROM c
  UNION ALL SELECT 'es_classrooms_missing', '669', CAST(COUNT_IF(es_classrooms_missing) AS STRING) FROM c
  UNION ALL SELECT 'is_overseas', '33', CAST(COUNT_IF(is_overseas) AS STRING) FROM c
  UNION ALL SELECT 'counts_reconcile', '1213740', MAX(CASE WHEN check_name = 'counts_reconcile' THEN actual END) FROM d
  UNION ALL SELECT 'true_values_reconcile', '458922', MAX(CASE WHEN check_name = 'true_values_reconcile' THEN actual END) FROM d
  UNION ALL SELECT 'missing_counts_stay_null', '626515', MAX(CASE WHEN check_name = 'missing_counts_stay_null' THEN actual END) FROM d
  UNION ALL SELECT 'missing_booleans_stay_null', '2800050', MAX(CASE WHEN check_name = 'missing_booleans_stay_null' THEN actual END) FROM d
  UNION ALL SELECT 'checks in the last run', '38', CAST(COUNT(*) AS STRING) FROM d
  UNION ALL SELECT 'checks in the last run not PASS', '0', CAST(COUNT_IF(status <> 'PASS') AS STRING) FROM d
  UNION ALL SELECT 'rows from the last run', '60167', CAST(COUNT_IF(run_id = (SELECT run_id FROM last_run)) AS STRING) FROM c
  UNION ALL SELECT 'rows from another commit', '0', CAST(COUNT_IF(code_revision <> '<commit that ran>') AS STRING) FROM c
  UNION ALL SELECT 'last silver run', 'succeeded', MAX(status) FROM pr WHERE run_id = (SELECT run_id FROM last_run)
  UNION ALL SELECT 'silver runs succeeded at this commit', '2', CAST(COUNT_IF(status = 'succeeded' AND code_revision = '<commit that ran>') AS STRING) FROM pr
  UNION ALL SELECT 'candidate rows not published', '0', CAST(COUNT(*) AS STRING) FROM (
    SELECT * FROM edu_access.`03-silver`.deped_facilities_clean_candidate EXCEPT ALL SELECT * FROM c)
  UNION ALL SELECT 'INT columns / BOOLEAN columns', '22 / 66',
    CAST(COUNT_IF(data_type = 'INT') AS STRING) || ' / ' || CAST(COUNT_IF(data_type = 'BOOLEAN') AS STRING)
    FROM edu_access.information_schema.columns WHERE table_schema = '03-silver' AND table_name = 'deped_facilities_clean'
  UNION ALL SELECT 'content_sha256', 'same in both runs', sha2(concat_ws('|', sort_array(collect_list(
    sha2(to_json(struct(* EXCEPT (run_id, cleaned_at_utc, code_revision))), 256)))), 256) FROM c
)
SELECT check_name, expected, actual, CASE WHEN expected = actual THEN 'OK' ELSE 'CHECK' END AS result FROM checks;
```

The other checks:

```sql
SELECT run_id, layer, status, COUNT(*) FROM edu_access.`01-control`.data_quality_results
WHERE source_id = 'deped_facilities' AND run_id IN ('1045250185878076', '700607904560713') GROUP BY ALL ORDER BY ALL;

SELECT table_name, table_owner FROM edu_access.information_schema.tables
WHERE table_schema = '03-silver' AND table_name LIKE 'deped_facilities%' ORDER BY 1;

DESCRIBE HISTORY edu_access.`03-silver`.deped_facilities_clean;

-- For the runs at 9197926, use job runs 89482607322789 and 948438707623608 and versions 2 and 3 below.

SELECT
  (SELECT COUNT(*) FROM (
     SELECT * EXCEPT (run_id, cleaned_at_utc, code_revision) FROM edu_access.`03-silver`.deped_facilities_clean VERSION AS OF 0
     EXCEPT ALL
     SELECT * EXCEPT (run_id, cleaned_at_utc, code_revision) FROM edu_access.`03-silver`.deped_facilities_clean VERSION AS OF 1)) AS only_in_0,
  (SELECT COUNT(*) FROM (
     SELECT * EXCEPT (run_id, cleaned_at_utc, code_revision) FROM edu_access.`03-silver`.deped_facilities_clean VERSION AS OF 1
     EXCEPT ALL
     SELECT * EXCEPT (run_id, cleaned_at_utc, code_revision) FROM edu_access.`03-silver`.deped_facilities_clean VERSION AS OF 0)) AS only_in_1;
```
