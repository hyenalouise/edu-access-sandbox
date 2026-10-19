# Evidence: PSA school-age population Silver builds and passes its gate on Databricks, with identical content on a rerun

Issue #158 · Databricks `dev` · 2026-10-18, Manila time (UTC+8) · runs by @maeveylain for @saraevcldn

## The claim

At commit `8d90086` (the rebased #158 branch plus the restored fan-in lane), the whole `edu_access_pipeline` job succeeds on Databricks `dev` twice:
- The school-age Silver build and gate succeed on Spark, with the tree built from work tables.
- The gate gives 124 results: 120 PASS, 4 WARN, 0 FAIL, the same as the local run.
- The fan-in records the school-age lane as succeeded.
- Both runs publish 418,320 clean rows, 0 quarantined, with identical business content.

## What was run

From a checkout of `8d90086`:

```powershell
databricks bundle deploy -t dev --profile reached-hq
databricks bundle run edu_access_pipeline -t dev --profile reached-hq   # twice
```

| | Run 1 | Run 2 |
|---|---|---|
| Job run | `5447221548394` | `820540420665033` |
| `code_revision` | `8d90086c727638e9d8353dd0916f3a8e7a54b753` | `8d90086c727638e9d8353dd0916f3a8e7a54b753` |
| Job result | succeeded, 560 s | succeeded, 534 s |
| Tasks | 52 succeeded, 0 failed (the rest are `disabled` in `databricks.yml`) | 52 succeeded, 0 failed |
| `08_clean_psa_school_age_population` | succeeded, 79 s | succeeded, 70 s |
| `90_validate_psa_school_age_population_clean` | succeeded, 67 s | succeeded, 64 s |
| `90_validate_control`, `silver_lane_succeeded` for this lane | PASS (`succeeded`) | PASS (`succeeded`) |
| Gate results | 124: 120 PASS, 4 WARN, 0 FAIL | 124: 120 PASS, 4 WARN, 0 FAIL |

The 4 WARNs are the zero-population cells, as locally: `zero_population_cells_total` 21 (2020) and 7 (2024), `zero_population_cells_household` 24 (2020) and 7 (2024).

## Results

Each run rebuilds `edu_access.03-silver.psa_school_age_population_clean` (`CREATE OR REPLACE TABLE`), so each run left its own Delta version. Run 1 wrote version 4 and run 2 version 5:

| Version | Rows | `run_id` | Content MD5 (run stamp excluded) |
|---:|---:|---|---|
| 4 | 418,320 | `5447221548394` | `f6c136f44682ad23a36ea286674b5759` |
| 5 | 418,320 | `820540420665033` | `f6c136f44682ad23a36ea286674b5759` |

The quarantine table has 0 rows. Places per level and `place_status` (each place once, by label and parent), the same in both concepts:

| Census year | country | region | province | of which `special_geographic_area` | city or municipality | of which `sga_cluster` |
|---|---:|---:|---:|---:|---:|---:|
| 2020 | 1 | 17 | 82 | 1 (Interim Province) | 1,642 | 8 |
| 2024 | 1 | 18 | 83 | 1 (Special Geographic Area) | 1,642 | 0 |

These are the pinned counts in `config/mappings/psa_school_age_population.json`. National totals, both sexes, ages 5–17: total 28,680,299 (2020) and 27,569,038 (2024), household 28,654,448 and 27,551,106. The two totals equal the profile's (O-8).

## Queries

```sql
SELECT run_id, status, COUNT(*) AS results
FROM edu_access.`01-control`.data_quality_results
WHERE source_id = 'psa_school_age_population' AND layer = 'silver'
  AND run_id IN ('5447221548394', '820540420665033')
GROUP BY 1, 2 ORDER BY 1, 2;
```

```sql
SELECT COUNT(*) AS rows, MIN(run_id) AS run_id,
       md5(concat_ws('|', sort_array(collect_list(md5(to_json(struct(* EXCEPT (run_id, cleaned_at_utc, code_revision)))))))) AS content_md5
FROM edu_access.`03-silver`.psa_school_age_population_clean VERSION AS OF 4;   -- and VERSION AS OF 5
```

```sql
SELECT census_year, population_concept, level, place_status,
       COUNT(DISTINCT place_label || '|' || coalesce(parent_name, '')) AS places
FROM edu_access.`03-silver`.psa_school_age_population_clean
GROUP BY ALL ORDER BY ALL;
```

## What this does not show

- The content MD5 here and the local SHA-256 ([local record](../reconciliation/2026-10-18-psa-school-age-population-bronze-to-silver.md)) hash different serializations, so they cannot be compared to each other. Each shows that its own engine's two runs are identical; the counts, levels, flags and national totals agree across engines.
- The gate did not fail on the real data, so a tree that does not close, an all-zero place, a mispinned workbook and the other FAIL cases are shown by `tests/test_silver_school_age.py` on made-up workbooks.
- Sara's earlier `dev` runs (`330313806603002`, `967044693610530`) ran the same school-age code at `8bd6437`, a commit replaced by the rebase; these two runs are at the branch's current code.
