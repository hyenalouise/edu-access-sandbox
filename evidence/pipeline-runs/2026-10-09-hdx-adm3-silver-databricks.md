# Evidence: HDX ADM3 Silver builds and passes its gate on Databricks, and a second run rebuilds the same result

Issue #90 · Databricks `dev` · 2026-10-09 · checked by @saraevcldn

## The claim

The two Silver SQL tasks of `edu_access_pipeline` for `hdx_boundaries`, run by Spark on the SQL warehouse, build `hdx_adm3_clean` and `hdx_adm3_quarantine` from the current Bronze batch: 1,642 clean rows, 0 quarantined, and all 38 gate checks PASS. Every geometry function in the generated SQL (`try_to_geometry`, `st_geometrytype`, `st_isempty`, `st_isvalid`, `st_contains`) runs on Databricks as written (D-040). A second run, on the same Bronze rows and the same commit, records a second `succeeded` run with the same counts and results.

## What was run

The job `[dev sara_celadina] edu_access_pipeline` (job `413860742211114`), deployed with `databricks bundle deploy --target dev --profile reached-hq` from the pushed branch `feat/90-hdx-adm3-silver` at commit `853be19d9a6ff3f19a2ecb40944f174e37eec533` (the `code_revision` every Bronze task printed). The HDX Silver tasks `06_clean_hdx_adm3` and `90_validate_hdx_adm3_clean` are enabled in that commit. The run was announced to the team and the SQL warehouse was stopped beforehand. The job was run twice with `databricks bundle run edu_access_pipeline --target dev --profile reached-hq`. Times are Manila (UTC+8).

| | Run 1 | Run 2 |
|---|---|---|
| Job run (`run_id` of the Silver rows) | `200962982110857` | `1120928216115214` |
| Whole job | 18:37:09 to 18:43:23, about 6 min 14 s, `TERMINATED SUCCESS` | 18:45:26 to 18:49:53, about 4 min 27 s, `TERMINATED SUCCESS` |
| `bronze_hdx_boundaries` | `hdx_boundaries__2025-02-13__f682747fbb26` skip, 0 inserted, Bronze 1,642 | same |
| `90_validate_hdx_adm3_raw`, `06_clean_hdx_adm3`, `90_validate_hdx_adm3_clean` | succeeded | succeeded |
| Other lanes | every Bronze load skipped (already loaded); DepEd enrollment Silver rebuilt and passed | same |

## Results

After run 2, on the SQL warehouse:

| `job_run_id` | `pipeline_runs.status` | clean rows | quarantined | PASS | WARN | FAIL |
|---|---|---:|---:|---:|---:|---:|
| `200962982110857` | succeeded | 1642 | 0 | 38 | 0 | 0 |
| `1120928216115214` | succeeded | 1642 | 0 | 38 | 0 | 0 |

The clean and quarantine counts are of the published tables after run 2 (the tables hold the last passing build); the check counts are per run from `data_quality_results` (`layer = 'silver'`).

Content of the published clean table after run 2, without the run stamp:

| rows | content MD5 | `run_id` |
|---:|---|---|
| 1642 | `1129f8ad489148fbda904e42936c4807` | `1120928216115214` |

The next run on the same Bronze rows should give the same MD5.

Geometry functions on `hdx_adm3_raw`, read-only, before the runs (5 rows): every row `parsed = true`, `kind = MULTIPOLYGON`, `valid = true`, `centre_inside = true`.

## Queries

```sql
SELECT r.job_run_id, r.status,
       (SELECT COUNT(*) FROM edu_access.`03-silver`.hdx_adm3_clean) AS clean_rows,
       (SELECT COUNT(*) FROM edu_access.`03-silver`.hdx_adm3_quarantine) AS quarantined,
       COUNT_IF(q.status = 'PASS') AS pass, COUNT_IF(q.status = 'WARN') AS warn, COUNT_IF(q.status = 'FAIL') AS fail
FROM edu_access.`01-control`.pipeline_runs AS r
LEFT JOIN edu_access.`01-control`.data_quality_results AS q
  ON q.run_id = r.run_id AND q.source_id = 'hdx_boundaries' AND q.layer = 'silver'
WHERE r.pipeline_name = 'silver_build' AND r.source_id = 'hdx_boundaries'
GROUP BY r.job_run_id, r.status, r.started_at_utc
ORDER BY r.started_at_utc;
```

```sql
SELECT COUNT(*) AS rows,
       md5(concat_ws('|', sort_array(collect_list(md5(to_json(struct(* EXCEPT (run_id, cleaned_at_utc, code_revision)))))))) AS content_md5,
       MIN(run_id) AS run_id
FROM edu_access.`03-silver`.hdx_adm3_clean;
```

```sql
SELECT adm3_pcode,
       try_to_geometry(geometry) IS NOT NULL AS parsed,
       upper(replace(CAST(st_geometrytype(try_to_geometry(geometry)) AS STRING), 'ST_', '')) AS kind,
       st_isvalid(try_to_geometry(geometry)) AS valid,
       st_contains(try_to_geometry(geometry),
                   try_to_geometry(concat('{"type": "Point", "coordinates": [', center_lon, ', ', center_lat, ']}'))) AS centre_inside
FROM edu_access.`02-bronze`.hdx_adm3_raw
LIMIT 5;
```

## What this does not show

- The content MD5 was taken once, after run 2, so it shows run 2's content, not a comparison with run 1. Both runs read the same Bronze batch (skipped, 1,642 rows) at the same commit and gave the same counts and check results.
- Nothing was quarantined or flagged on the real file, so quarantine, the flags, and a failing gate are shown by the local tests on made-up GeoJSON (`tests/test_silver_hdx.py`, 23 passed; full suite 525 passed, 1 skipped), not on Databricks.
- Per-task timings were not recorded.
