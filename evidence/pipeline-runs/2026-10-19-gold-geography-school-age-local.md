# Evidence: the city and barangay dimensions and the school-age population fact build, pass their gates, and reconcile

Issues #174 and #46 · local DuckDB (D-017) · 2026-10-19, Manila time (UTC+8) · run by @maeveylain · local only, not yet run on Databricks

## The claim

The three Gold builds and their gates turn the real published Silver and Integration tables into:

- `dim_city_municipality`: every PSGC 2Q 2026 city and municipality once (1,642) plus `UNKNOWN` and `EXCLUDED`, 1,644 rows
- `dim_barangay`: every PSGC 2Q 2026 barangay once (42,010), one unknown barangay per city or municipality (1,642) plus `UNKNOWN` and `EXCLUDED`, 43,654 rows
- `fact_city_school_age_population`: 131,080 male and female rows whose population equals Silver's for both census years, with no place dropped

Every FAIL check passes, including the full-row reconciliation of every Gold row to its source row (review on #193) and the upstream-run check of integrity rule 1 of the metric specification. Each WARN is a known, counted gap. Run at `c948e8b`, after main was merged in, the 8 reviewed 2020 clusters moved to `EXCLUDED`, and the comparability flag was set to territory changes only (review on #193). Earlier runs: `f638c04`, `c19f751`, `5cd23b8` (first build) and `67bc8c8` (hierarchy changes flagged, 136 codes) gave the same dimension rows.

## What was run

On Windows 11, Python 3.14 and the project's DuckDB. The inputs were the published Silver and Integration tables of a local job run on the real files (PSGC 2Q 2026 workbook, HDX COD-AB ADM3 2025-02-13, PSA 2020 and 2024 census age-sex workbooks), copied to a scratch database. Each table's build and gate were run on it twice, in the job's order, through `DuckDBStore.run_file` with the job's parameters, the same way `src.job.local_run` runs a SQL task. The full local job was not rerun for this.

| Table | Rows | PASS / WARN / FAIL (both runs) | MD5 of every row, run 1 = run 2 |
|---|---:|---|---|
| `dim_city_municipality` | 1,644 | 27 / 1 / 0 | `884f607a…` |
| `dim_barangay` | 43,654 | 15 / 1 / 0 | `ac14dad0…` |
| `fact_city_school_age_population` | 131,080 | 22 / 1 / 0 | `09d10ceb…` |

Full-row reconciliation: the gates rebuild every expected row from the source and compare all columns both ways (`EXCEPT ALL`). Rows that differ: `dim_city_municipality` 0 of 1,644 (`values_match_source`), `dim_barangay` 0 of 43,654 (`values_match_source`), `fact_city_school_age_population` 0 of 131,080 (`cells_match_silver`).

Upstream runs (one PASS result per distinct `run_id` read, each with a succeeded build in `pipeline_runs`): `psa_psgc_clean`, `hdx_adm3_clean`, `psa_school_age_population_clean` from Silver run `9b3e5156…`; `hdx_adm3_psgc_map` from Integration run `9b3e5156…`; `psa_school_age_population_psgc_map` from Integration run `local-map-80f44f29`.

## `dim_city_municipality`

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

## `dim_barangay`

| Check | Expected | Actual |
|---|---|---|
| Regular members / PSGC Bgy rows of the master quarter | equal | 42,010 / 42,010 |
| Repeated or NULL keys | 0 | 0 |
| Parent not a PSGC City or Mun | 0 | 0 |
| `<code>-UNKNOWN` members / cities and municipalities | equal | 1,642 / 1,642 |
| Technical members (`UNKNOWN`, `EXCLUDED`) | 2 | 2 |
| Barangays rolled up from a Manila district to `1380600000` | | 897 |
| Barangays without `urban_rural`, PSGC `-` (WARN) | | 38 |

## `fact_city_school_age_population`

| Check | Expected | Actual |
|---|---|---|
| Rows 2020 / 2024 | | 65,400 / 65,680 |
| Repeated or NULL keys | 0 | 0 |
| Codes not in `dim_city_municipality` | 0 | 0 |
| Silver city rows (total, male + female) without a map row | 0 | 0 |
| Population 2020 / 2024, fact = Silver | equal | 42,869,567 / 42,178,032 |
| City, year and age where male + female ≠ the published total | 0 | 0 |
| City, year and sex missing an age (20 ages, 5 to 24) | 0 | 0 |
| Regular cities and municipalities without 2024 rows | 0 | 0 |
| Population on `EXCLUDED`, 2020, the 8 reviewed SGA clusters (WARN) / on `UNKNOWN` | | 96,899 / 0 |
| Codes / rows not comparable 2020 to 2024 | | 17 / 1,000 |

The 17 codes not comparable: the 8 territory changes (Makati and Taguig, EMBO; Carmen, Kabacan, Midsayap, Pigkawayan, Pikit and Aleosan in Cotabato), the 8 Special Geographic Area municipalities, which exist only in 2024, and `EXCLUDED`. Province and region changes (Negros Island Region, Sulu, Maguindanao) no longer make a city's own trend not comparable (review on #193); Gold groups both years by the one PSGC 2Q 2026 hierarchy. 2020 rows: 1,634 matched places × 20 ages × 2 sexes, plus 40 on `EXCLUDED`. 2024: 1,642 × 40.

## Not checked

- Databricks `dev`: not run yet.
- The technical member codes are proposed on #174 and not yet agreed; `fact_school_enrollment` (#46), which also uses them, is not built here.
- The territory-change list (EMBO from the metric specification's AP4 list, plus the Cotabato towns of D-031 and D-054) has no PSA list of boundary changes between the censuses to check against (UNVERIFIED that it is complete).
- Whether the starred income class means retained after downgrade stays UNVERIFIED (D-035); the column carries Silver's value.
