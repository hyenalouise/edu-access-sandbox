# Evidence: every PSA school-age population place maps to PSGC 2Q 2026, except the 8 2020 Interim Province clusters, which are reviewed unmatched

Issue #159 · local DuckDB (D-017) · 2026-10-19, Manila time (UTC+8) · run by @maeveylain

## The claim

With the rules, regions, province aliases and overrides in `config/integration/psa_school_age_population_psgc.json` at commit `796a5df`, the generated map build and gate (`etl/04_integration/05_map_psa_school_age_population_psgc.sql`, `90_validate_psa_school_age_population_psgc_map.sql`) turn the real `psa_school_age_population_clean` (2020 and 2024 census workbooks) and `psa_psgc_clean` (2Q 2026) into `psa_school_age_population_psgc_map` with one row per census year and city or municipality, none dropped. 2024: 1,642 of 1,642 match one PSGC city or municipality each. 2020: 1,634 match, and the 8 Interim Province clusters stay unmatched by review (profile O-7, S-1; D-031). No PSGC code is taken twice in a census year, no place is pending or ambiguous, the mapped places add up to the national total in every cell, and every FAIL check passes. A second run gives the same map.

Databricks `dev` was confirmed afterwards, the same day, in two runs at `8c57f54` with the same count per method and an identical map in both runs: [2026-10-19 Databricks record](../pipeline-runs/2026-10-19-psa-school-age-population-psgc-map-databricks.md).

## What was run

On Windows, Python 3.12 and the project's DuckDB, `RAW_DATA_DIR` set to the raw-data root, and a git-ignored database:

```powershell
python -m src.job.local_run --db local_state/edu_access.duckdb
```

Every lane loaded and passed its gates (job run `9b3e5156-3b3c-48df-b4e4-e5d520f0566a`, code revision `988ef0d`), including `psa_school_age_population` (batches `psa_school_age_population__2020__e40d71839b95` and `__2024__49d15bb0cdd1`) and `psa_psgc` (`psa_psgc__2026-Q2__31892bc2bdde`). The map tasks were still disabled at that commit, so the map was then run directly on the two published Silver tables:

```powershell
python analysis\verification\psa_school_age_population_psgc_map.py --db local_state\edu_access.duckdb
```

The script runs the two committed map files through `DuckDBStore.run_file`, as the job would, with `code_revision` `local`.

| | Run 1: rules only, first old-name tier | Run 2: rules and the 17 reviewed overrides | Run 3: run 2 again |
|---|---|---|---|
| Gate | passed, map published | passed, map published | passed, map published |
| FAIL checks | 0 | 0 | 0 |
| Pending review | 21 | 0 | 0 |
| Map content MD5 (key, code, status, method, review, parent, reason, lineage) | | `1157c23f90f04f348467024b43ccf2ae` | `1157c23f90f04f348467024b43ccf2ae` |

Run 1, before the old-name tier also compared old name with old name, left 21 places pending: the 6 names of profile S-4 in 2024 (Sanchez-Mira already matched by the folded tier, so 5), and in 2020 the same names plus the renames of O-7 and the 8 clusters. Four 2020 places carry an old name in brackets that PSGC also lists as the unit's old name (`PIO V. CORPUZ (LIMBUHAN)`, `PRES. CARLOS P. GARCIA (PITOGO)`, `AMAI MANABILANG 1 (BUMBARAN)`, `RIZAL (MARCOS)`), so the old-name tier compares old name with old name too, and those match by rule. The other 17 are overrides.

## Results (run 2)

| Check | 2020 | 2024 |
|---|---:|---:|
| Census places in / map rows | 1,642 / 1,642 | 1,642 / 1,642 |
| Matched / distinct PSGC codes | 1,634 / 1,634 | 1,642 / 1,642 |
| Match rate | 99.51% | 100.00% |
| AP4 population matched (total, both sexes, 5-17) | 99.77% | 100.00% |
| Unmatched (reviewed) / ambiguous / pending | 8 / 0 / 0 | 0 / 0 / 0 |
| PSGC cities and municipalities with no place | 8 (the Special Geographic Area municipalities) | 0 |

PSGC version 2026-Q2 for every row; 17 overrides listed, 17 applied, 0 whose place is missing; every census region listed; 1 census province without a PSGC parent (2020 `INTERIM PROVINCE`). `population_reconciles` PASS: for each census year, concept, sex and age, the mapped places sum to the Silver national total.

By method and parent:

| Year | match_status | match_method | review_status | parent_match | Places |
|---|---|---|---|---|---:|
| 2020 | matched | `name_exact` | rule | `province_name` | 1,550 |
| 2020 | matched | `name_exact` | rule | `province_alias` (Maguindanao) | 36 |
| 2020 | matched | `name_exact` | rule | `region` | 35 |
| 2020 | matched | `name_old` | rule | `province_name` | 5 |
| 2020 | matched | `reviewed_alias` | reviewed | `province_name` | 4 |
| 2020 | matched | `name_normalized` | rule | `province_name` | 3 |
| 2020 | matched | `name_normalized` | rule | `province_alias` (Maguindanao) | 1 |
| 2020 | unmatched | | reviewed | | 8 |
| 2024 | matched | `name_exact` | rule | `province_name` | 1,575 |
| 2024 | matched | `name_exact` | rule | `region` | 35 |
| 2024 | matched | `name_exact` | rule | `province_alias` (Western Samar) | 26 |
| 2024 | matched | `reviewed_alias` | reviewed | `province_name` | 5 |
| 2024 | matched | `name_normalized` | rule | `province_name` | 1 |

## The profile's baseline is reproduced

The issue asks that profile X-2's counts (cleaned name inside the province, no alias) are reproduced:

- **2024: 1,602.** `name_exact` inside a province found by name (1,575) or under its region (35) is 1,610; less the 8 Special Geographic Area municipalities, whose parent X-2 did not have (PSGC gives the SGA no province level, so the map finds it as a blank-level container), is 1,602. Then + 8 SGA + 26 Western Samar (alias) + 1 `SANCHEZ-MIRA` (folded) + 5 overrides = 1,642.
- **2020: 1,585.** 1,550 + 35 = 1,585 by exact name with no alias. Then + 37 Maguindanao (alias: 36 exact, `DATU SAUDI-AMPATUAN` folded) + 3 `name_normalized` (`SANCHEZ-MIRA` folded; `CALACA` and `CARMONA`, now cities, by the word City ignored) + 5 `name_old` (`BACUNGAN (Leon T. Postigo)` and the four above) + 4 overrides = 1,634, and the 8 clusters = 1,642.

## The exceptions

| Year | Census place (parent) | PSGC | How | Why |
|---|---|---|---|---|
| 2020, 2024 | `BALIUAG` (Bulacan) | `0301403000` City of Baliwag | override | respelling; same alias in the DepEd match (#8) |
| 2020, 2024 | `SAN ISIDRO` (Davao del Norte) | `1102324000` Sawata | override | renamed; no San Isidro in Davao del Norte; CMCI alias, barangay population BP-4 |
| 2020, 2024 | `DON VICTORIANO CHIONGBIAN` (Misamis Occidental) | `1004217000` Don Victoriano | override | PSGC short name; HDX override (#93), BP-4 |
| 2020 | `SANTO TOMAS` (Pampanga) | `0305421000` Sto. Tomas | override | abbreviation; the only Santo Tomas in Pampanga; 2024 writes `STO. TOMAS` |
| 2024 | `PIO V. CORPUZ` (Masbate) | `0504116000` Pio V. Corpus | override | respelling; 2020 matches by its old name Limbuhan |
| 2024 | `RIZAL` (Palawan) | `1705323000` Dr. Jose P. Rizal | override | renamed; 2020 matches by its old name Marcos |
| 2020 | the 8 `INTERIM PROVINCE` clusters | none | override, unmatched | PSA groupings of SGA barangays, not LGUs (O-7, S-1, D-031) |

Every census place with the same name and parent in both years (1,549) gets the same PSGC code in both, and every PSGC code matched in 2020 is matched in 2024.

## Rerun after review (#187)

The reviews by @catweyine and @hyenalouise asked for four gate changes:
- #181's two FAIL checks (D-052): `psgc_name_matches_unit`, and `name_match_inside_province`, which recomputes each name-rule match's parent in the gate, independently of the build;
- `rule_codes_in_psgc` as a FAIL instead of a WARN (a region or alias code missing from the master quarter);
- `psgc_source_row_number` in `lineage_complete`.

`main` was merged first (#181, #153). The build SQL did not change; the gate now writes 38 results. Two runs of the verification script on the same database, with the final gate:

| | Run 6 | Run 7 |
|---|---|---|
| Gate | passed, map published | passed, map published |
| PASS / WARN / FAIL | 35 / 3 / 0 | 35 / 3 / 0 |
| `psgc_name_matches_unit` / `name_match_inside_province` / `rule_codes_in_psgc` / `lineage_complete` | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 |
| Map content MD5 | `1157c23f90f04f348467024b43ccf2ae` | `1157c23f90f04f348467024b43ccf2ae` |

The same three WARNs, the same count per method, and the same map as runs 2 and 3: on the real data, every name match is inside its parent and carries the master name. New tests tamper with a candidate (a wrong name; a unit in another province, another region, and outside an aliased province's codes; a missing PSGC row or batch), or give the rules a region or alias code the master quarter lacks or has at another level. Each fails its check and keeps the published map.

## What this does not show

- Whether a rule match is right beyond the names: no codes exist to check against. The cross-year agreement above and the zero ambiguous rows are the checks available.
- The 8 Special Geographic Area municipalities cannot be compared between 2020 and 2024 city by city; their 2020 population sits in the 8 unmatched clusters (S-1 is still open).
