# Evidence: the whole job runs on Databricks `dev`, source to Gold, twice, with every gate passing and identical results

Issues #174 and #46 · Databricks `dev`, workspace `dbc-2b6bf1c5-7bc3` (D-056) · 2026-10-20, Manila time (UTC+8) · run by @maeveylain · two job runs of `edu_access_pipeline`

## The claim

At commit `7542cc0` (`main`, after #202), `edu_access_pipeline` ran twice on Databricks `dev` from start to Gold:
- **Both runs succeeded.** 82 tasks succeeded in each and 8 were disabled: the AP1 to AP4 Analytics tasks, not yet merged.
- **No gate failed.** Every Bronze, Silver, Integration and Gold gate wrote 0 FAIL.
- **The two runs agree.** 305 of the 315 Gold checks are identical between the runs, in status and value. The other 10 are the `upstream_run_*` checks, whose value is each run's own `run_id`.

This is the Databricks evidence for the Gold pull requests that merged on local evidence only, under "run less, merge more" (D-056):

| Pull request | Tables |
|---|---|
| #168 | `dim_school`, `dim_school_year`, `dim_education_level`, `fact_school_classroom_capacity`, `fact_school_teacher_capacity`, `fact_school_year_source_availability` |
| #193, #202 | `dim_city_municipality`, `dim_barangay`, `fact_city_school_age_population` |
| #194 | `dim_city_poverty` |
| #195 | `fact_city_population` |
| #196 | `fact_school_enrollment` |
| #197 | the DepEd school-to-PSGC map work tables |

## What was run

The bundle was deployed to `dev` from `main`; the job's parameters show `code_revision = 7542cc082c9e978f9cc01d32f72ef741d1732783` and `environment = dev`. Both runs were started manually (trigger `ONE_TIME`, creator @maeveylain), one after the other, as the runbook describes:

```bash
databricks bundle deploy --target dev --profile reached-hq
databricks bundle run edu_access_pipeline --target dev --profile reached-hq
```

| | Run 1 | Run 2 |
|---|---|---|
| Job run | [`1085767927326340`](https://dbc-2b6bf1c5-7bc3.cloud.databricks.com/jobs/303213353262793/runs/1085767927326340?o=7474651774377250) | [`575313135268521`](https://dbc-2b6bf1c5-7bc3.cloud.databricks.com/jobs/303213353262793/runs/575313135268521?o=7474651774377250) |
| Job | `303213353262793` | `303213353262793` |
| Start → end | 01:28:34 → 01:47:17 (18 min 43 s) | 01:48:35 → 02:03:57 (15 min 22 s) |
| Result | SUCCESS | SUCCESS |
| Tasks succeeded / disabled / failed | 82 / 8 / 0 | 82 / 8 / 0 |
| Bronze loads: runs succeeded; batches loaded / skipped / failed / blocked | 8; 0 / 14 / 0 / 0 | 8; 0 / 14 / 0 / 0 |
| Silver builds / Integration builds succeeded | 8 / 4 | 8 / 4 |

Every Bronze batch was already loaded before run 1, so both runs skipped all 14 batches and rebuilt Silver, Integration and Gold from them.

## Gate results

`data_quality_results` for each job run, per layer. The two runs are identical.

| Layer | PASS | WARN | FAIL |
|---|---:|---:|---:|
| control | 16 | 0 | 0 |
| bronze | 24 | 0 | 0 |
| silver | 633 | 16 | 0 |
| integration | 162 | 15 | 0 |
| gold | 303 | 12 | 0 |

Gold by table:

| Table | PASS / WARN / FAIL (each run) | Rows published |
|---|---|---:|
| `dim_city_municipality` | 27 / 1 / 0 | 1,644 |
| `dim_barangay` | 15 / 1 / 0 | 43,654 |
| `dim_school` | 5 / 0 / 0 | 63,793 |
| `dim_school_year` | 4 / 0 / 0 | 6 |
| `dim_education_level` | 4 / 0 / 0 | 3 |
| `dim_city_poverty` | 26 / 0 / 0 | 1,642 |
| `fact_school_enrollment` | 152 / 5 / 0 | 1,086,066 |
| `fact_school_classroom_capacity` | 10 / 2 / 0 | 47,818 |
| `fact_school_teacher_capacity` | 12 / 2 / 0 | 143,454 |
| `fact_city_population` | 20 / 0 / 0 | 1,642 |
| `fact_city_school_age_population` | 22 / 1 / 0 | 131,080 |
| `fact_school_year_source_availability` | 6 / 0 / 0 | 18 |

The Gold WARNs, the same in both runs, are known and counted gaps:

| Table | Check | Actual |
|---|---|---:|
| `dim_barangay` | `regular_without_urban_rural` (PSGC `-`) | 38 |
| `dim_city_municipality` | `regular_without_land_area` (8 SGA municipalities, no HDX feature) | 8 |
| `fact_city_school_age_population` | `excluded_member_population` (the 8 2020 SGA clusters) | 96,899 |
| `fact_school_classroom_capacity` | `offered_levels_without_room_data` | 669 |
| `fact_school_classroom_capacity` | `zero_room_denominators` | 268 |
| `fact_school_enrollment` | `offered_all_blank/2025-26/ES`, `JHS`, `SHS` | 40, 29, 120 |
| `fact_school_enrollment` | `schools_barangay_unknown` | 583 |
| `fact_school_enrollment` | `schools_city_unknown` | 152 |
| `fact_school_teacher_capacity` | `offered_levels_without_teacher_data` | 6 |
| `fact_school_teacher_capacity` | `zero_teacher_denominators` | 562 |

The three gates fixed in #202 match their local evidence exactly ([2026-10-19-gold-geography-school-age-local.md](2026-10-19-gold-geography-school-age-local.md)). The school-age fact's `cells_match_silver` is 0. It has 65,400 rows in 2020 and 65,680 in 2024, population 42,869,567 (2020) and 42,178,032 (2024), and 17 codes (1,000 rows) not comparable from 2020 to 2024. `90_validate_fact_city_school_age_population`, which failed with Spark `INTERNAL_ERROR` (XX000) in job run `424746161586143` before #202, succeeded in both runs, in 34 s and 37 s.

## How it was read

The run results come from `databricks jobs get-run <job_run_id> --profile reached-hq`. The counts come from read-only queries on warehouse `ba94770acbbc293c` after run 2, for example:

```sql
SELECT run_id, layer, source_id, status, COUNT(*)
FROM edu_access.`01-control`.data_quality_results
WHERE run_id IN ('1085767927326340', '575313135268521')
GROUP BY ALL;
```

The runs were compared by joining the two runs' Gold checks on (`source_id`, `check_name`), leaving out the 10 `upstream_run_*` checks, whose `actual` is each run's own `run_id`. 305 checks were compared, and 0 differ in status or value:

```sql
WITH r AS (
  SELECT run_id, source_id, check_name, status, actual
  FROM edu_access.`01-control`.data_quality_results
  WHERE run_id IN ('1085767927326340', '575313135268521')
    AND layer = 'gold' AND check_name NOT LIKE 'upstream_run_%'
)
SELECT COUNT(*) AS checks_compared,
       COUNT_IF(a.status IS DISTINCT FROM b.status OR a.actual IS DISTINCT FROM b.actual) AS checks_that_differ
FROM (SELECT * FROM r WHERE run_id = '1085767927326340') AS a
FULL OUTER JOIN (SELECT * FROM r WHERE run_id = '575313135268521') AS b
  USING (source_id, check_name);
```

Result: `checks_compared` 305, `checks_that_differ` 0.

## Observed, not acted on

- **The per-run summary tables were dropped.** After run 2, `05-gold` holds no `*_gate_summary_r_*` table, so the #202 gates removed theirs.
- **One older summary table remains.** `05-gold` still holds `fact_school_enrollment_gate_summary_candidate`, a fixed-name table from the `fact_school_enrollment` gate. It is not a published table; its owner may want to drop it or move it to the per-run pattern.

## Not checked

- Row-level content hashes on Databricks: rows are compared through the gates' reconciliation checks and the identical check values, not by hashing every row.
- Analytics (AP1 to AP4 and the priority matrix): disabled in this deployment; #199 and #203 are open.
- Production (`prod` target): not deployed.
