# Evidence: dim_city_municipality holds every PSGC 2Q 2026 city and municipality once, plus the two technical members

Issue #174 · local DuckDB (D-017) · 2026-10-19, Manila time (UTC+8) · run by @maeveylain · local only, not yet run on Databricks

## The claim

At commit `f638c04`, the Gold build and gate (`etl/05_gold/04_build_dim_city_municipality.sql`, `90_validate_dim_city_municipality.sql`) turn the published `psa_psgc_clean` (2Q 2026), `hdx_adm3_psgc_map` and `hdx_adm3_clean` into `dim_city_municipality` with one row per PSGC city or municipality of the master quarter (1,642) and the `UNKNOWN` and `EXCLUDED` technical members: 1,644 rows, a unique key, and every FAIL check passing. The only WARN is the 8 Special Geographic Area municipalities, which have no HDX land area (D-052).

## What was run

On Windows 11, Python 3.14 and the project's DuckDB. The inputs were the published Silver and Integration tables of a local job run on the real files (PSGC 2Q 2026 workbook, HDX COD-AB ADM3 2025-02-13), copied to a scratch database. The two Gold files were run on it twice, in the job's order, through `DuckDBStore.run_file` with the job's parameters, the same way `src.job.local_run` runs a SQL task. The full local job was not rerun for this.

| | Run 1 | Run 2 |
|---|---|---|
| Build and gate | succeeded | succeeded |
| Checks: PASS / WARN / FAIL | 23 / 1 / 0 | 23 / 1 / 0 |
| Rows | 1,644 | 1,644 |
| MD5 of every row, ordered by key | `884f607a…` | `884f607a…` |

## Results

| Check | Expected | Actual |
|---|---|---|
| Regular members / PSGC City + Mun rows of the master quarter | equal | 1,642 / 1,642 |
| Cities / municipalities | | 149 / 1,493 |
| Repeated or NULL keys | 0 | 0 |
| Technical members (`UNKNOWN` unknown, `EXCLUDED` excluded) | 2 | 2 |
| PSGC versions | 1 | 1 (2026-Q2) |
| Region or province code without its name | 0 | 0 |
| Municipality with a city class / city without one | 0 / 0 | 0 / 0 |
| Members without a province | | 34 (33 HUCs and Pateros) |
| Special Geographic Area members, all under `1999900000` | | 8 |
| Units matched by two HDX features of the latest release | 0 | 0 |
| Land area NULL (WARN) | | 8, all Special Geographic Area |
| Land area, cities / municipalities (sq km) | | 35,888.8168 / 257,075.1025 |

Spot checks: `0990101000` City of Isabela is a CC with province `0990100000` (its container) and 219.8697 sq km; `1380600000` City of Manila is an HUC with no province; `1381701000` Pateros has no province or city class; `1999901000` Kapalawan has `is_sga = true` and no land area. The two blank-level containers are not members.

## Not checked

- Databricks `dev`: not run yet.
- The technical member codes are proposed on #174 and not yet agreed; the facts that use them (#46) are not built.
- Whether the starred income class means retained after downgrade stays UNVERIFIED (D-035); the column carries Silver's value.
