# Evidence: HDX ADM3 features map to PSGC one-to-one except the 8 Special Geographic Area units, with every exception reviewed

Issue #93 · local DuckDB (D-017) · 2026-10-15, rerun 2026-10-18, Manila time (UTC+8) · run by @saraevcldn

## The claim

With the rules and overrides in `config/integration/hdx_adm3_psgc.json` at commit `adcbf0c`, the generated map build and gate (`etl/04_integration/03_map_hdx_adm3_psgc.sql`, `90_validate_hdx_adm3_psgc_map.sql`) turn the real `hdx_adm3_clean` (1,642 COD-AB ADM3 features, valid on 2025-02-13) and `psa_psgc_clean` (2Q 2026) into `hdx_adm3_psgc_map` with one row per feature, none dropped. 1,634 features match one PSGC city or municipality each, no PSGC code is taken twice, the 8 Special Geographic Area units stay unmatched by review (D-031), no feature is left pending, and every FAIL check passes.

Databricks `dev` was confirmed afterwards, the same day, in two runs at `99b0387` with the same count per method: [2026-10-15 Databricks record](../pipeline-runs/2026-10-15-hdx-adm3-psgc-map-databricks.md).

After the review changes of `3c32944` and the merge of `main`, the map was run again at `882873e` with the same count per method and no FAIL: [Rerun at `882873e`](#rerun-at-882873e-2026-10-18).

## What was run

On Windows, Python 3.12 and the project's DuckDB, `RAW_DATA_DIR` set to the raw-data root (holding only `admin_boundaries/` and `psa/`), and the default git-ignored database:

```powershell
python -m src.job.local_run
```

This loaded PSGC (`psa_psgc__2026-Q2__31892bc2bdde`, 43,768 rows) and HDX (`hdx_boundaries__2025-02-13__f682747fbb26`, 1,642 rows) into Bronze and built both Silver tables, every gate passing (job run `a18033fd-ff1e-4399-b140-0aa8b7cd817c`, code revision `3adf2ff`). The job stopped before Integration: the DepEd files and one PSA Poverty Stat workbook are not on this computer, so those lanes failed and the source-lane fan-in `90_validate_control` stopped the map tasks, as D-039 intends. The map reads only the two published Silver tables, so it was then run directly:

```powershell
python analysis\verification\hdx_adm3_psgc_map.py
```

The script runs the two committed map files through `DuckDBStore.run_file`, as the job would, with `code_revision` `local`. It ran twice:

| | Run 1: rules only | Run 2: rules and the 12 reviewed overrides |
|---|---|---|
| Code | `3adf2ff` (no overrides) | the working tree committed unchanged as `adcbf0c` |
| Gate | passed, map published | passed, map published |
| FAIL checks | 0 | 0 |
| WARN | `review_pending` 12, `unmatched` 8 | `unmatched` 8 |
| Pending review | 12 | 0 |

## Results (run 2)

| Check | Expected | Map |
|---|---|---|
| HDX features in / map rows / distinct P-codes | 1,642 | 1,642 / 1,642 / 1,642 |
| Matched rows / distinct PSGC codes | equal | 1,634 / 1,634 |
| Match rate | | 99.51% |
| PSGC versions used | 1 | 1 (2026-Q2) |
| Overrides listed / applied / P-code not in the release | 12 / 12 / 0 | 12 / 12 / 0 |
| Pending review | 0 | 0 |

By method:

| match_status | match_method | review_status | Features |
|---|---|---|---:|
| matched | `code` | rule | 1,480 |
| matched | `correspondence_code` (D-030) | rule | 96 |
| matched | `name_exact` | rule | 29 |
| matched | `code_region_moved` (Sulu) | rule | 19 |
| matched | `name_normalized` | rule | 6 |
| matched | `code_renamed` | reviewed | 4 |
| unmatched | | reviewed | 8 |
| | | **Total** | **1,642** |

The other FAIL checks (`matched_has_psgc_unit`, `unmatched_has_no_psgc`, `status_valid`, `method_valid`, `review_status_valid`, `code_is_the_pcode`, `correspondence_is_the_old_code`, `region_moved_is_sulu`, `lineage_complete`, `rows_built_by_this_run`) all recorded 0. `ambiguous` recorded 0.

### The issue's 1,500 exact matches

#93 counted 1,500 features whose P-code, read as a PSGC code, exists in PSGC. The map counts a code only when the names also agree (D-052), so 20 of those 1,500 move out of `code`:

- 16 in Maguindanao, where COD-AB reuses a PSGC code number for a different town (`docs/governance/limitations.md`). Each is matched to its own town by name, inside the 29 `name_exact`.
- 4 renamed LGUs, kept as `code_renamed` and confirmed by review.

1,480 + 16 + 4 = 1,500. The remaining 142 are the 96 Correspondence Code matches, the 19 Sulu units, 19 of the name matches (29 + 6 - 16), and the 8 Special Geographic Area units.

### The 12 reviewed features

| P-code | COD-AB name | Decision |
|---|---|---|
| PH0907226 | Bacungan (Leon T. Postigo) | `0907226000` Leon T. Postigo, `code_renamed` |
| PH1004217 | Don Victoriano Chiongbian (Don Mariano Marcos) | `1004217000` Don Victoriano, `code_renamed` |
| PH1102324 | San Isidro | `1102324000` Sawata, `code_renamed` |
| PH1705323 | Rizal (Marcos) | `1705323000` Dr. Jose P. Rizal, `code_renamed` |
| PH1909901 to PH1909908 | Special Geographic Area - Carmen, Kabacan, Midsayap I, Midsayap II, Pigkawayan, Pikit I, Pikit II, Pikit III | unmatched until a spatial check (D-031) |

Each override's reason and evidence is in the config. The script writes the same list, with every column, to `local_state/hdx_adm3_psgc_review.md` (git-ignored).

## Rerun at `882873e` (2026-10-18)

`3c32944` changed the build and the gate after review (a code with a different name is `ambiguous` and `pending`, never `matched`; no name search across the country; keyed by release; `source_row_ref`; `geographic_level` on every row; master periods counted in `psa_psgc_clean`; new WARN `psgc_units_without_feature`), and `882873e` merges `main` into it. Same commands, at `882873e`, with `RAW_DATA_DIR` set to the raw-data root:

- `python -m src.job.local_run` (job run `05ff3809-5a04-48f6-8d60-ab0795dbcc06`): PSGC Bronze skipped (already loaded; same SHA-256), HDX Bronze loaded nothing new (`phl_admin3.geojson` not in the landing folder, so the loaded batch `hdx_boundaries__2025-02-13__f682747fbb26` stays current), and both Silver tables rebuilt and passed their gates. The PSA Poverty Stat Silver gate failed (one workbook is not on this computer), so the fan-in stopped the map tasks, as in the first run.
- `python analysis\verification\hdx_adm3_psgc_map.py`: gate passed, map published, exit code 0.

| | 2026-10-15, `adcbf0c` | 2026-10-18, `882873e` |
|---|---|---|
| Map rows / matched / distinct PSGC codes | 1,642 / 1,634 / 1,634 | 1,642 / 1,634 / 1,634 |
| Match rate | 99.51% | 99.51% |
| Overrides applied / pending | 12 / 0 | 12 / 0 |
| FAIL | 0 | 0 |
| WARN | `unmatched` 8 | `unmatched` 8, `psgc_units_without_feature` 8 |

The count per method is unchanged (1,480 / 96 / 29 / 19 / 6 / 4 matched, 8 unmatched), and `ambiguous` is 0, so on this data the stricter rules change no match. The new WARN counts the PSGC side: the 8 PSGC Special Geographic Area municipalities that no HDX feature matches, and which therefore have no HDX land area. The full suite passed at `882873e` (784 passed, 1 skipped). Databricks: two runs at `882873e`, 29 PASS, 2 WARN, 0 FAIL, the same count per method ([Databricks record](../pipeline-runs/2026-10-15-hdx-adm3-psgc-map-databricks.md#rerun-at-882873e-2026-10-18)).

## Rerun at `63f6318` (2026-10-18)

`63f6318` adds the FAIL check `status_combination_valid` and counts `psgc_units_without_feature` per HDX release (D-052); `c40194d` merged `main` and renumbered the decision to D-052. Run on the same working tree before it was committed (`code_revision` `69f3254…-dirty`, the parent plus these changes), with `RAW_DATA_DIR` holding every source, including `admin_boundaries/phl_admin3.geojson` (SHA-256 `f682747f…eec41`):

- `python -m src.job.local_run` (job run `2d2a9d87-28e8-42f7-b542-bf60f70066ac`) on a fresh DuckDB file: the whole job succeeded, HDX Bronze included (`hdx_boundaries__2025-02-13__f682747fbb26`, 1,642 rows), and both map tasks succeeded.
- `python analysis\verification\hdx_adm3_psgc_map.py`: gate passed, map published, exit code 0.

| | 2026-10-18, `882873e` | 2026-10-18, `63f6318` |
|---|---|---|
| Map rows / matched / distinct PSGC codes | 1,642 / 1,634 / 1,634 | 1,642 / 1,634 / 1,634 |
| Match rate | 99.51% | 99.51% |
| Overrides applied / pending | 12 / 0 | 12 / 0 |
| `status_combination_valid` | (not yet a check) | PASS, 0 |
| FAIL | 0 | 0 |
| WARN | `unmatched` 8, `psgc_units_without_feature` 8 | `unmatched` 8, `psgc_units_without_feature` 8 (per release; one release) |

The count per method is unchanged (1,480 / 96 / 29 / 19 / 6 / 4 matched, 8 unmatched). The new tests in `tests/test_integration_hdx.py` show what this data cannot: three status combinations D-052 forbids each fail the gate and leave the published map unchanged, and a second release that holds only one feature raises `psgc_units_without_feature` from 4 to 13. All four fail on the gate at `69f3254`. Full suite: 869 passed, 1 skipped.

## Limitations

- Local DuckDB stands in for Spark and Delta (D-017). The Databricks runs are in their own record, linked above.
- The map ran through the verification script, not through the job, because the job's other lanes had no raw files on this computer. The job runs the same two files after the fan-in.
- `code_revision` on the map rows is `local`, not the commit. Run 2's working tree was committed unchanged as `adcbf0c`, after the run.
- One build per configuration; a rebuild's identical content is not compared here.

## How to reproduce

From a checkout of `adcbf0c` (or later), with `RAW_DATA_DIR` holding at least `admin_boundaries/` and `psa/`: `python -m src.job.local_run`, then `python analysis/verification/hdx_adm3_psgc_map.py`. Expected: gate passed, 1,642 rows, 1,634 matched, 12 reviewed, 0 pending, no FAIL; WARN `unmatched` 8, and from `3c32944` on also `psgc_units_without_feature` 8; exit code 0.
