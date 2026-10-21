# Evidence: the school boundary map and dim_school_location reconcile to Silver on the real data, every school gets one boundary status, and a rebuild is identical

Issue #217 · local run (DuckDB) only; nothing has run on Databricks · 2026-10-21 · checked by @catweyine

## The claim

On the real data, the Integration map `deped_school_boundary_map` has one row per school of `deped_psgc_coordinates_clean`: 47,818, with none dropped or repeated.
- Each row keeps the school's point, flag and Silver lineage unchanged.
- It carries the city the school PSGC map assigns, and one `boundary_status`, consistent with its inputs.

The Gold dimension `dim_school_location` projects that map:
- 47,818 rows, every school in `dim_school`;
- every value equal to the map's.

All 18 Integration checks pass or warn as designed (17 PASS, 1 WARN for the schools outside their boundary), and all 7 Gold checks pass. A second build of each is identical. The Gold table is byte-identical to the earlier version of this branch, which ran the boundary test inside Gold.

**Not claimed:** anything on Databricks; that an `inside` point is the school's exact place (the test is at city or municipality level); anything about barangays (HDX ADM4 is not in Silver).

## What was run

1. **The whole local job on `main`** at `66f6552` (after #218), on the real files in `RAW_DATA_DIR`: `python -m src.job.local_run --db <scratch>/job.duckdb`. Status `succeeded`, every task. This gives the published inputs:
   - `deped_psgc_coordinates_clean`: 47,818 rows;
   - `deped_school_psgc_map`, `hdx_adm3_psgc_map`, `hdx_adm3_clean`;
   - `dim_school`: 63,793 rows.
2. **On a copy of that database**, at commit `5f6fb0f97ee97a039c3499dbeee91dea7a51225d` on `feat/217-dim-school-location` (clean worktree), twice (`run_id` `loc-ev-1`, `loc-ev-2`):
   - `etl/04_integration/06_map_deped_school_boundary.sql`, then `90_validate_deped_school_boundary_map.sql`;
   - `etl/05_gold/07_build_dim_school_location.sql`, then `90_validate_dim_school_location.sql`.

macOS 26.4.1, Python 3.12.14, DuckDB 1.4.5 with its spatial extension (loaded by `DuckDBStore` for `st_*` functions, as for HDX Silver).

## Results

| | Run 1 | Run 2 |
|---|---|---|
| Map build / map gate / Gold build / Gold gate (local) | 1.6 / 0.3 / 0.0 / 0.0 s | 1.4 / 0.1 / 0.2 / 0.0 s |
| Integration checks | 17 PASS, 1 WARN | 17 PASS, 1 WARN |
| Gold checks | 7 PASS | 7 PASS |
| `pipeline_runs` (`integration_build`, `deped_psgc_coordinates`) | `succeeded` | `succeeded` |
| Map content hash (all but the run stamp) | `291054843fcb…` | `291054843fcb…` (identical) |
| Gold content hash (all columns) | `3f629076e59b…` | `3f629076e59b…` (identical) |

**Integration FAIL checks, all passed:**
- `inputs_present` (47,818), `rows_reconcile` (47,818 = 47,818), `source_rows_not_dropped`, `one_row_per_source_row`;
- `locations_unchanged` (point, flag and lineage = Silver), `city_matches_school_map`;
- `boundary_status_allowed`, `boundary_status_follows_inputs`, `boundary_feature_in_city`;
- `hdx_release_is_latest`, `lineage_complete`, `rows_built_by_this_run`.

**Integration WARN:** `schools_outside_boundary`, 1,997.

**Gold FAIL checks, all passed:** `rows_reconcile` (= the map's 47,818), `key_unique`, `key_not_null`, `school_in_dim_school` (0 missing of 63,793), `values_match_source`, `boundary_status_allowed`, and `upstream_run_deped_school_boundary_map`, which is the succeeded map run.

### Boundary test S-1, at city or municipality level

| `boundary_status` | Schools | Why |
|---|---:|---|
| `inside` | 44,968 | the point is inside the HDX boundary of the city the school map assigns; every one names its `adm3_pcode` |
| `outside` | 1,997 | a boundary exists and the point is not in it (WARN) |
| `no_usable_point` | 738 | `coordinate_flag` set: 679 missing + 54 outside the Philippines + 5 at (0, 0), exactly Silver's flags |
| `no_boundary` | 97 | all in the 8 Special Geographic Area municipalities, which have no HDX boundary: Pahamuddin 17, Nabalawag 13, Tugunan 13, Old Kaabakan 12, Malidegao 12, Ligawasan 12, Kapalawan 10, Kadayangan 8 |
| `no_matched_city` | 18 | the school map's SY 2023-24 city status is `excluded` (9) or `ambiguous` (9) |
| **Total** | **47,818** | `inside_rate_percent`, inside ÷ (inside + outside): 95.75 |

**Sanity check of `inside` and `outside`.** For each tested school, I measured the distance from the median point of the tested schools of its own city:

| | Schools | Median | Under 10 km | 100 km or more |
|---|---:|---:|---:|---:|
| `inside` | 44,968 | 4.4 km | 39,177 | 0 |
| `outside` | 1,997 | 13.5 km | 761 | 260 |

All 260 points 100 km or more from their city are `outside`, which matches the source profile's 260 far-off points (O-6). The 761 `outside` points within 10 km are near a boundary. That is expected for small municipalities and points placed on the town edge; the city-level test cannot tell those apart from slightly misplaced points.

### Cost

- **A first version ran out of memory locally** (12.7 GB) once the city lookup read every school year of the school map (about 360,000 rows) before the boundary join. The map now reads only the location's school year, and joins unflagged points to their city before touching any shape. The build then took 1.4–1.6 s.
- **Also kept from the design:** each boundary is parsed once; there's one `st_contains` per school and city boundary, reduced to one row per school; the gates don't redo the geometry; the Gold gate's summary is written once, to a per-run table.
- **These are DuckDB times, not Databricks measurements.**

## Not checked here

- **Databricks `dev`:** Gold runs there later, as for the other Gold tables. The spatial functions are the ones HDX Silver already runs on `dev` (`try_to_geometry`, `st_contains`).
- **Whether `inside` points are at the right building.** Only the city boundary is tested.
- **D-061 (#221) is still proposed.** Until it is accepted, which statuses a map may use is a team decision; the data model's recommendation is `inside` only.
