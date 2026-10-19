# Evidence: the PSA school-age population to PSGC map builds and passes its gate on Databricks, with the same result as locally

Issue #159 · Databricks `dev` · 2026-10-19 · run by @maeveylain

## The claim

The two Integration tasks of `edu_access_pipeline` for the map, `05_map_psa_school_age_population_psgc` and `90_validate_psa_school_age_population_psgc_map`, run by Spark on the SQL warehouse after the school-age population and PSGC Silver gates (D-051). They build `psa_school_age_population_psgc_map` from the published `psa_school_age_population_clean` and `psa_psgc_clean`: 3,284 rows (1,642 per census year), the same count per match method as the local run ([2026-10-19 local record](../reconciliation/2026-10-19-psa-school-age-population-psgc-map.md)), 33 PASS, 3 WARN, 0 FAIL. The 17 reviewed overrides, the region list and the two province aliases apply on Spark as on DuckDB. A second run on the same Silver tables and the same commit gives the same results and an identical map.

## What was run

The job `edu_access_pipeline` (job `921726647955407`), deployed with `databricks bundle deploy --target dev --profile reached-hq` from the pushed branch `feat/159-map-psa-school-age-psgc` at commit `8c57f543dec64f8f3b78d2b17fc7d9f914a837ef`. That is the `code_revision` on every map row and on both runs' `pipeline_runs` rows. It holds the map code and overrides of `796a5df` unchanged; only the `owner` field and the decision text differ. The job was run twice with `databricks bundle run edu_access_pipeline --target dev --profile reached-hq`. Times are Manila (UTC+8), 2026-10-19.

| | Run 1 | Run 2 |
|---|---|---|
| Job run (`job_run_id`) | `506650735997573` | `524734028492647` |
| Whole job | 01:35:06 to 01:45:11, `TERMINATED SUCCESS` | 01:46:11 to 01:54:21, `TERMINATED SUCCESS` |
| Tasks | 54 succeeded, 36 disabled, 0 failed | same |
| Bronze | every load skipped (same SHA-256): `psa_school_age_population__2020__e40d71839b95`, `__2024__49d15bb0cdd1`, `psa_psgc__2026-Q2__31892bc2bdde`; 0 rows inserted | same |
| `05_map_psa_school_age_population_psgc` | 01:43:47 to 01:44:09, succeeded | 01:52:53 to 01:53:18, succeeded |
| `90_validate_psa_school_age_population_psgc_map` | 01:44:09 to 01:45:11, succeeded | 01:53:18 to 01:54:20, succeeded |

The batches are the ones the local run read.

## Results

Gate results per run, from `pipeline_runs` (`pipeline_name = 'integration_build'`, `source_id = 'psa_school_age_population'`) and `data_quality_results` (`layer = 'integration'`):

| `job_run_id` | status | `code_revision` | PASS | WARN | FAIL |
|---|---|---|---:|---:|---:|
| `506650735997573` | succeeded | `8c57f54…` | 33 | 3 | 0 |
| `524734028492647` | succeeded | `8c57f54…` | 33 | 3 | 0 |

Both runs give the same value for every check below; the local run gives the same:

| Check | Status | Actual |
|---|---|---:|
| `rows_reconcile` | PASS | 3,284 |
| `psgc_code_taken_once` | PASS | 3,276 |
| `overrides_applied` | PASS | 17 |
| `population_reconciles` | PASS | 0 cells off |
| `review_pending` | PASS | 0 |
| `unmatched` | WARN | 8 (the 2020 Interim Province clusters, reviewed) |
| `psgc_units_without_place` | WARN | 8 (the Special Geographic Area municipalities in 2020) |
| `province_without_psgc_parent` | WARN | 1 (2020 `INTERIM PROVINCE`) |
| `match_rate_percent_2020` / `_2024` | record | 99.51 / 100.00 |
| `ap4_population_matched_percent_2020` / `_2024` | record | 99.77 / 100.00 |

The published map after run 2, by census year, method and parent, next to the local run:

| Year | match_status | match_method | review_status | parent_match | Databricks | Local |
|---|---|---|---|---|---:|---:|
| 2020 | matched | `name_exact` | rule | `province_name` | 1,550 | 1,550 |
| 2020 | matched | `name_exact` | rule | `province_alias` | 36 | 36 |
| 2020 | matched | `name_exact` | rule | `region` | 35 | 35 |
| 2020 | unmatched | | reviewed | | 8 | 8 |
| 2020 | matched | `name_old` | rule | `province_name` | 5 | 5 |
| 2020 | matched | `reviewed_alias` | reviewed | `province_name` | 4 | 4 |
| 2020 | matched | `name_normalized` | rule | `province_name` | 3 | 3 |
| 2020 | matched | `name_normalized` | rule | `province_alias` | 1 | 1 |
| 2024 | matched | `name_exact` | rule | `province_name` | 1,575 | 1,575 |
| 2024 | matched | `name_exact` | rule | `region` | 35 | 35 |
| 2024 | matched | `name_exact` | rule | `province_alias` | 26 | 26 |
| 2024 | matched | `reviewed_alias` | reviewed | `province_name` | 5 | 5 |
| 2024 | matched | `name_normalized` | rule | `province_name` | 1 | 1 |
| | | | | **Total** | **3,284** | **3,284** |

Content of the published map, without the run stamp. Each run replaced the table, so run 1's map was read through Delta time travel (version 0) and run 2's is the current table (version 1):

| Delta version | `run_id` | rows | content MD5 |
|---:|---|---:|---|
| 0 | `506650735997573` | 3,284 | `494d7576afdade45000b8c1247afb383` |
| 1 | `524734028492647` | 3,284 | `494d7576afdade45000b8c1247afb383` |

## Queries

```sql
SELECT r.job_run_id, r.status, r.code_revision,
       COUNT_IF(q.status = 'PASS') AS pass, COUNT_IF(q.status = 'WARN') AS warn, COUNT_IF(q.status = 'FAIL') AS fail
FROM edu_access.`01-control`.pipeline_runs AS r
LEFT JOIN edu_access.`01-control`.data_quality_results AS q
  ON q.run_id = r.run_id AND q.source_id = 'psa_school_age_population' AND q.layer = 'integration'
WHERE r.pipeline_name = 'integration_build' AND r.source_id = 'psa_school_age_population'
  AND r.job_run_id IN ('506650735997573', '524734028492647')
GROUP BY ALL ORDER BY r.started_at_utc;
```

```sql
SELECT census_year, match_status, match_method, review_status, parent_match, COUNT(*) AS places
FROM edu_access.`04-integration`.psa_school_age_population_psgc_map
GROUP BY ALL ORDER BY census_year, places DESC;
```

```sql
SELECT COUNT(*) AS rows,
       md5(concat_ws('|', sort_array(collect_list(md5(to_json(struct(* EXCEPT (run_id, built_at_utc, code_revision)))))))) AS content_md5,
       MIN(run_id) AS run_id
FROM edu_access.`04-integration`.psa_school_age_population_psgc_map VERSION AS OF 0;   -- and VERSION AS OF 1
```

```sql
SELECT a.source_id, a.action, a.outcome, COUNT(*) AS attempts, SUM(a.rows_inserted) AS inserted
FROM edu_access.`01-control`.ingestion_batch_attempts AS a
JOIN edu_access.`01-control`.pipeline_runs AS r ON r.run_id = a.run_id
WHERE r.job_run_id IN ('506650735997573', '524734028492647') AND a.source_id IN ('psa_school_age_population', 'psa_psgc')
GROUP BY ALL;
```

## What this does not show

- The map did not fail on the real data. A failing gate (a PSGC code taken twice, a dropped place, a status combination D-052 forbids, two master periods) is shown only by the local tests on made-up rows (`tests/test_integration_school_age.py`).
- The Databricks content MD5 (Spark `to_json`) and the local MD5 (DuckDB) are computed differently, so they are not compared. The counts per method and the check values are compared instead, and they are equal.
