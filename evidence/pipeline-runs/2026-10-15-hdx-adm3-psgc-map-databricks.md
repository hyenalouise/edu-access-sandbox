# Evidence: the HDX ADM3 to PSGC map builds and passes its gate on Databricks, after the source-lane fan-in, with the same result as locally

Issue #93 · Databricks `dev` · 2026-10-15, rerun 2026-10-18 · checked by @saraevcldn

## The claim

The two Integration tasks of `edu_access_pipeline` for the map, `03_map_hdx_adm3_psgc` and `90_validate_hdx_adm3_psgc_map`, run by Spark on the SQL warehouse after the source-lane fan-in `90_validate_control` (D-039), build `hdx_adm3_psgc_map` from the published `hdx_adm3_clean` and `psa_psgc_clean`: 1,642 rows, the same count per match method as the local run ([2026-10-15 local record](../reconciliation/2026-10-15-hdx-adm3-psgc-map.md)), 29 PASS, 1 WARN (the 8 Special Geographic Area units, reviewed unmatched) and 0 FAIL. The 12 reviewed overrides apply on Spark as on DuckDB. A second run on the same Silver tables and the same commit gives the same counts and results.

After the review changes of `3c32944` and the merge of `main` (`882873e`), two more runs give the same count per method, 29 PASS, 2 WARN (the 8 unmatched features, and the new `psgc_units_without_feature`: the 8 PSGC Special Geographic Area municipalities no feature matches) and 0 FAIL. See [Rerun at `882873e`](#rerun-at-882873e-2026-10-18).

## What was run

The job `[dev sara_celadina] edu_access_pipeline`, deployed with `databricks bundle deploy --target dev --profile reached-hq` from the pushed branch `feat/93-hdx-adm3-psgc-map` at commit `99b03878c628e92ccc953f9fb0b7b19b736f1fdc` (the `code_revision` every Bronze task printed and every map row carries). That commit holds the map code and overrides of `adcbf0c` unchanged, plus the local evidence record. The run was announced to the team first. The job was run twice with `databricks bundle run edu_access_pipeline --target dev --profile reached-hq`. Times are Manila (UTC+8).

| | Run 1 | Run 2 |
|---|---|---|
| Job run (`job_run_id`) | `311552286952841` | `1092224191077542` |
| Whole job | 11:25:39 to 11:37:45, about 12 min, `TERMINATED SUCCESS` | 11:43:49 to 11:52:30, about 9 min, `TERMINATED SUCCESS` |
| Bronze | every load skipped (already loaded; same SHA-256), including `hdx_boundaries__2025-02-13__f682747fbb26` (1,642) and `psa_psgc__2026-Q2__31892bc2bdde` (43,768) | same |
| Silver | all six lanes built and passed their gates | same |
| `90_validate_control`, `03_map_hdx_adm3_psgc`, `90_validate_hdx_adm3_psgc_map` | succeeded | succeeded |

## Results

Gate results per run, from `pipeline_runs` (`pipeline_name = 'integration_build'`) and `data_quality_results` (`layer = 'integration'`):

| `job_run_id` | status | `code_revision` | PASS | WARN | FAIL |
|---|---|---|---:|---:|---:|
| `311552286952841` | succeeded | `99b0387…` | 29 | 1 | 0 |
| `1092224191077542` | succeeded | `99b0387…` | 29 | 1 | 0 |

The published map after run 2, by method, next to the local run:

| match_status | match_method | review_status | Databricks | Local |
|---|---|---|---:|---:|
| matched | `code` | rule | 1,480 | 1,480 |
| matched | `correspondence_code` | rule | 96 | 96 |
| matched | `name_exact` | rule | 29 | 29 |
| matched | `code_region_moved` | rule | 19 | 19 |
| unmatched | | reviewed | 8 | 8 |
| matched | `name_normalized` | rule | 6 | 6 |
| matched | `code_renamed` | reviewed | 4 | 4 |
| | | **Total** | **1,642** | **1,642** |

Content of the published map after run 2, without the run stamp:

| rows | content MD5 | `run_id` |
|---:|---|---|
| 1642 | `896447200a94591b0bc3e78a2479669e` | `1092224191077542` |

The next run on the same Silver tables should give the same MD5.

## Rerun at `882873e` (2026-10-18)

`3c32944` changed the build and the gate after review: a code that agrees with a different name is `ambiguous` and `pending` instead of `matched`; no name search across the country when the province is not found; every step keyed by (`adm3_pcode`, `source_reference_date`); `source_row_ref` added; `geographic_level` = `city_mun` on every row; `one_psgc_version` counts master periods in `psa_psgc_clean`; and a new WARN, `psgc_units_without_feature`. `882873e` merges `main` into that commit (only `evidence/README.md` conflicted). The full local suite passed at `882873e` (784 passed, 1 skipped, Windows).

Deployed from the pushed branch at `882873e72e2e56dd4646b7a3ea2e5a0e8b01e8ea` with the same two commands, after telling the team. Times are Manila (UTC+8).

| | Run 3 | Run 4 |
|---|---|---|
| Job run (`job_run_id`) | `616457249833823` | `219943628912238` |
| Whole job | 08:13:05 queued, 08:13:19 to 08:25:49, `TERMINATED SUCCESS` | 08:26:27 to 08:35:03, `TERMINATED SUCCESS` |
| Bronze | every load skipped (already loaded; same SHA-256), including `hdx_boundaries__2025-02-13__f682747fbb26` (1,642) and `psa_psgc__2026-Q2__31892bc2bdde` (43,768) | same |
| `90_validate_control`, `03_map_hdx_adm3_psgc`, `90_validate_hdx_adm3_psgc_map` | succeeded | succeeded |

Gate results, from the first query below (all four runs):

| `job_run_id` | status | `code_revision` | PASS | WARN | FAIL |
|---|---|---|---:|---:|---:|
| `311552286952841` | succeeded | `99b0387…` | 29 | 1 | 0 |
| `1092224191077542` | succeeded | `99b0387…` | 29 | 1 | 0 |
| `616457249833823` | succeeded | `882873e…` | 29 | 2 | 0 |
| `219943628912238` | succeeded | `882873e…` | 29 | 2 | 0 |

The extra WARN is the new check, not a change in the map: the published map after run 4 has the same count per method as after run 2 and as the local rerun ([local record](../reconciliation/2026-10-15-hdx-adm3-psgc-map.md#rerun-at-882873e-2026-10-18)): 1,480 `code`, 96 `correspondence_code`, 29 `name_exact`, 19 `code_region_moved`, 8 unmatched (reviewed), 6 `name_normalized`, 4 `code_renamed` (reviewed); 1,642 in all.

| rows | content MD5 | `run_id` |
|---:|---|---|
| 1642 | `7f93831043a34f93abb061e1844f9325` | `219943628912238` |

The MD5 differs from run 2's on purpose: the rows now carry `source_row_ref`, `geographic_level` on the 8 unmatched rows, and new `reason` texts.

## Rerun at `63f6318` (2026-10-18)

`63f6318` adds the FAIL check `status_combination_valid` (a `matched` row is `rule` or `reviewed` with a method and a code; `ambiguous` is `pending` and `unmatched` is `pending` or `reviewed`, neither with a method or a code) and counts `psgc_units_without_feature` per HDX release. `c40194d` before it merged `main` and renumbered the decision to D-052. Both runs deployed the bundle at `63f6318` to `dev` and ran the whole job (`databricks bundle run edu_access_pipeline -t dev`).

| Run | Job run | Result | Map tasks | Gate | `code_revision` |
|---|---|---|---|---|---|
| 5 | `1021051251022782` | succeeded, 553 s | both succeeded | 30 PASS, 2 WARN, 0 FAIL | `63f6318` |
| 6 | `628254422157103` | succeeded, 404 s | both succeeded | 30 PASS, 2 WARN, 0 FAIL | `63f6318` |

In both runs `status_combination_valid` is PASS (0), the WARNs are `unmatched` 8 and `psgc_units_without_feature` 8 (one HDX release, so per release is still the 8 Special Geographic Area municipalities), and the count per method is unchanged: 1,480 `code`, 96 `correspondence_code`, 29 `name_exact`, 19 `code_region_moved`, 6 `name_normalized`, 4 `code_renamed` (reviewed), 8 unmatched (reviewed). No task failed; the tasks that did not run are the ones still `disabled` in `databricks.yml`.

| rows | content MD5 | `run_id` |
|---:|---|---|
| 1642 | `7f93831043a34f93abb061e1844f9325` | `628254422157103` |

The MD5 equals run 4's at `882873e`: the new check and the per-release count change the gate, not a single map row.

## Queries

```sql
SELECT r.job_run_id, r.status, r.code_revision,
       COUNT_IF(q.status = 'PASS') AS pass, COUNT_IF(q.status = 'WARN') AS warn, COUNT_IF(q.status = 'FAIL') AS fail
FROM edu_access.`01-control`.pipeline_runs AS r
LEFT JOIN edu_access.`01-control`.data_quality_results AS q
  ON q.run_id = r.run_id AND q.source_id = 'hdx_boundaries' AND q.layer = 'integration'
WHERE r.pipeline_name = 'integration_build' AND r.source_id = 'hdx_boundaries'
GROUP BY r.job_run_id, r.status, r.code_revision, r.started_at_utc
ORDER BY r.started_at_utc;
```

```sql
SELECT match_status, match_method, review_status, COUNT(*) AS features
FROM edu_access.`04-integration`.hdx_adm3_psgc_map
GROUP BY ALL ORDER BY features DESC;
```

```sql
SELECT COUNT(*) AS rows,
       md5(concat_ws('|', sort_array(collect_list(md5(to_json(struct(* EXCEPT (run_id, built_at_utc, code_revision)))))))) AS content_md5,
       MIN(run_id) AS run_id
FROM edu_access.`04-integration`.hdx_adm3_psgc_map;
```

## What this does not show

- The content MD5 was taken once per pair, after runs 2 and 4, so it does not compare runs 1 and 3 with them. Each pair read the same Silver tables at the same commit and gave the same counts and check results.
- The map did not fail on the real data, so a failing gate (a PSGC code taken twice, a bad override) and an override for a P-code missing from the release are shown by the local tests on made-up rows (`tests/test_integration_hdx.py`; full suite 710 passed, 1 skipped at `99b0387`, 784 passed, 1 skipped at `882873e`), not on Databricks.
- Per-task timings were not recorded.
