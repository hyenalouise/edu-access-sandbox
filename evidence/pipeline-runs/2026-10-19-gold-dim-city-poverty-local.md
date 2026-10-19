# Evidence: dim_city_poverty builds and passes its gate locally on real data, with D-046's counts

Issue #174 · local DuckDB · 2026-10-19, Manila time (UTC+8) · run by @Catweyine

## The claim

`06_build_dim_city_poverty.sql` and `90_validate_dim_city_poverty.sql`, run on the real published `psa_poverty_psgc_map` (PSA 2023, D-054) and the regular PSGC 2Q 2026 cities and municipalities, build 1,642 rows with the status counts D-046 reconciled: 1,597 `estimated`, 1 `no_estimate`, 44 `not_in_source`. The gate records 26 PASS, 0 WARN, 0 FAIL and publishes. A second run gives the same table. **Observed**, local only: not yet run on Databricks.

## What was run

- A copy of the local database `local_state/poverty_check.duckdb` (not committed). It holds the published `psa_psgc_clean`, `psa_poverty_stat_clean` and `psa_poverty_psgc_map` of the #92 local run: map run `0eed74ff-d307-46ea-a35c-c2653c95830a`, 4,836 rows, `integration_build` succeeded in `pipeline_runs`.
- **Stand-in for `dim_city_municipality`:** #193, which builds it, is not merged. Its regular members are the master quarter's `City` and `Mun` rows of `psa_psgc_clean` (149 + 1,493 = 1,642), so the stand-in held exactly those rows plus `UNKNOWN` and `EXCLUDED`, with the columns the build and gate read: `city_mun_psgc_code`, `member_type`, and for the Manila check `city_mun_name` and `city_class`, taken from `psa_psgc_clean` as #193 takes them. This run proves the poverty rules, not #193's dimension.
- The build and gate SQL of this branch, through `DuckDBStore.run_file` with the job's parameters, as the job's two SQL tasks run them. Run twice.

## Results

| Check | Expected | Run 1 | Run 2 |
|---|---:|---:|---:|
| `rows_match_pin` | 1,642 | 1,642 | 1,642 |
| `estimated_match_pin` | 1,597 | 1,597 | 1,597 |
| `no_estimate_match_pin` | 1 | 1 | 1 |
| `not_in_source_match_pin` | 44 | 44 | 44 |
| `manila_reason_match_pin` | 1 | 1 | 1 |
| `manila_reason_on_city_of_manila` (the row with that reason is the HUC named City of Manila, with 14 matched 2023 district rows) | 1 | 1 | 1 |
| `map_rows_carried` (2023 city and municipality map rows = rows with a PSA row) | 1,598 | 1,598 | 1,598 |
| `map_rows_matched`, `map_rows_in_dimension`, `values_equal_map` | 0 | 0 | 0 |
| `no_partial_estimate`, `no_value_without_estimate`, `estimate_complete`, `cv_over_20_follows_cv` | 0 | 0 | 0 |
| `district_rows_kept_out` (Manila's districts, still in the map) | count | 14 | 14 |
| `cv_over_20_rows` | count | 150 | 150 |
| `lower_limit_not_positive` | count | 1 | 1 |
| PASS / WARN / FAIL | | 26 / 0 / 0 | 26 / 0 / 0 |
| MD5 of the published table, ordered by key | | `6d33771bbe17b3e2556a21fe306cecf1` | `6d33771bbe17b3e2556a21fe306cecf1` |

Who is not `estimated` (joined back to `psa_psgc_clean` to read names):

| Status | Places | Count |
|---|---|---:|
| `no_estimate` | Kalayaan, Palawan (reason "PSA published no 2023 estimate") | 1 |
| `not_in_source` | the 33 highly urbanized cities, the City of Manila among them with its own reason | 33 |
| `not_in_source` | City of Isabela (CC), City of Cotabato (ICC), Pateros | 3 |
| `not_in_source` | the 8 Special Geographic Area municipalities | 8 |

These are D-046's 44. The one published lower limit below 0 is Ivana, Batanes (`-0.02406…`), stored as published. `cv_over_20` is 150, D-046's count once Manila's 6 districts are left out.

## Rerun on #193's real dim_city_municipality

On 2026-10-19 the whole job ran locally (`python -m src.job.local_run`) on a throwaway branch that merges #168, #193 and the three Gold branches, with every approved raw file except `Enrollment-in-SY-2021-2022.zip`. `06_build_dim_city_poverty` built on #193's real `dim_city_municipality` (1,642 regular members, plus `UNKNOWN` and `EXCLUDED`) and its gate passed: 25 PASS, 0 WARN, 0 FAIL, statuses 1,597 / 1 / 44. The published table has the same MD5 as above, `6d33771bbe17b3e2556a21fe306cecf1`, so the stand-in matched. That run was before the gate gained `manila_reason_on_city_of_manila` (review on #194); the check was then run on the stand-in only, which takes the name and class from the same `psa_psgc_clean` rows as #193.

## Column types

The published table has the data model's columns and types. The build casts each one, and the test `test_columns_follow_the_data_model` checks names, order and types. DuckDB, which the local run uses, names two Databricks types differently: `STRING` is `VARCHAR` and `INT` is `INTEGER` (`int32`); `BIGINT` shows as `int64` when printed. They are the same types.

| Column | Data model (Databricks) | Local DuckDB |
|---|---|---|
| `city_mun_psgc_code` | STRING | VARCHAR |
| `estimate_year` | INT | INTEGER |
| `poverty_incidence`, `poverty_ci90_lower`, `poverty_ci90_upper`, `poverty_cv` | DOUBLE | DOUBLE |
| `cv_over_20` | BOOLEAN | BOOLEAN |
| `poverty_status`, `status_reason` | STRING | VARCHAR |

## What this does not show

- A Databricks `dev` run. The tasks are enabled, but they wait for `90_validate_dim_city_municipality` (#193).
- Made-up cases are in `tests/test_gold_dim_city_poverty.py`: a partial estimate, an unmatched 2023 row, two rows for one place, a missing PSA row, Manila's districts coded under another place, and an extra member each fail and keep the last good build, and so does a map from a run that did not succeed.
