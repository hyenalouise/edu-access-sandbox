# Evidence: PSA school-age population Bronze reconciles to Silver, and a rebuild gives the same content

Issue #158 · local DuckDB (D-017) · 2026-10-18, Manila time (UTC+8) · run by @saraevcldn

## The claim

At commit `6bb76a6b8fb13d3f30b6b2ea1e261c80f76c4c82`, the generated school-age Silver build and gate (`etl/03_silver/08_clean_psa_school_age_population.sql`, `90_validate_psa_school_age_population_clean.sql`) turn the real 2020 and 2024 census workbooks into `psa_school_age_population_clean`:
- Every count cell is accounted for.
- Every count equals its own Bronze cell.
- The levels recovered from the sums match the profile's place counts, and the tree closes on all four sheets.
- The gate gives 0 FAIL.

A second run of the lane gives identical business content.

Databricks `dev`: two runs at `8d90086`, in [their own record](../pipeline-runs/2026-10-18-psa-school-age-population-silver-databricks.md). The rerun at that head is below.

## What was run

The run used branch `feat/158-silver-psa-school-age-population` with the #158 patch applied as `6bb76a6` (no uncommitted change, so `code_revision` carries no `-dirty`). It ran on Windows 11 with Python 3.12.10 and DuckDB 1.4.5, a fresh git-ignored database, and `RAW_DATA_DIR` set to the raw-data root. The script runs the lane's tasks of `edu_access_pipeline` twice, as `python -m src.job.local_run` runs them: control bootstrap, Bronze DDL, Bronze load, Bronze gate, Silver build, Silver gate.

```powershell
python analysis/verification/psa_school_age_population_silver.py
```

| | Run 1 | Run 2 |
|---|---|---|
| `run_id` | `ca22d1ec-1a9e-4ad9-9d4a-84ec2b8767dd` | `2fdbd707-aef3-4e56-804a-b6bc939e063f` |
| Started / finished (local) | 07:19:43 / 07:20:27 | 07:20:35 / 07:21:21 |
| Bronze | `load succeeded`, 3,496 + 13,985 inserted | `skip` both, "already loaded; same SHA-256", 0 inserted |
| Silver build / gate | 15.7 s / 28.5 s | 17.7 s / 28.3 s |
| `silver_build` run | `succeeded` | `succeeded` |
| Gate results | 116: 112 PASS, 4 WARN, 0 FAIL | 116: 112 PASS, 4 WARN, 0 FAIL |
| Clean / quarantined | 418,320 / 0 | 418,320 / 0 |
| SHA-256 of the clean business content (the run stamp excluded) | `e637b9bf3158b8f0…` | `e637b9bf3158b8f0…` (identical) |
| SHA-256 of the quarantine business content | `4f53cda18c2baa0c…` | `4f53cda18c2baa0c…` (identical, empty) |

Full hashes: clean `e637b9bf3158b8f0d3d70673667f32a38d6dacd44f209aeb9b772bba6c6eded2`, quarantine `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945`.

## Results

These were queried after run 2. The expected values come from the profile (`docs/data/source-inventory/psa_school_age_population/profile.md`) and the issue. Every row matched.

| Check | 2020 total | 2020 household | 2024 total | 2024 household |
|---|---|---|---|---|
| Silver cells = Bronze count cells (places × 60) | 104,520 | 104,520 | 104,640 | 104,640 |
| Quarantined | 0 | 0 | 0 | 0 |
| Places per level (country / region / province / city or municipality) | 1 / 17 / 82 / 1,642 | 1 / 17 / 82 / 1,642 | 1 / 18 / 83 / 1,642 | 1 / 18 / 83 / 1,642 |
| Cities and municipalities directly under their region (O-2) | 35 | 35 | 35 | 35 |
| Zero cells, all Kalayaan (O-3) | 21 | 24 | 7 | 7 |
| National, both sexes, ages 5-24 | 42,869,567 | 42,776,570 | 42,178,032 | 42,098,435 |
| National, both sexes, ages 5-17 (O-8) | 28,680,299 | | 27,569,038 | |
| Places with a footnote marker (O-6) | 0 | 0 | 11 | 10 |
| Places flagged capital | 81 | 81 | 46 | 46 |
| Places with an old name or abbreviation | 96 | 96 | 2 | 2 |
| Repeated (`place_name`, `parent_name`) keys | 0 | 0 | 0 | 0 |

The national totals by single year of age (both sexes, total) also equal the profile's 20 values for each year (O-8).

- Bronze rows by kind, 2020: 3,496 = 3,484 place + 12 structural (2 title, 4 header, 4 blank, 2 source).
- Bronze rows by kind, 2024: 13,985 = 3,488 place + 3 × 3,488 sex rows + 33 structural (2 title, 4 header, 20 note, 5 blank, 2 source).
- Places whose two concepts are equal (O-5): 366 in 2020, 771 in 2024.
- Household above total: 0 in both years.
- Lineage: all 418,320 clean rows join their current Bronze row, and both tables carry one `cleaned_at_utc`.

**Gate:** every FAIL check recorded 0 or its expected value. That covers reconciliation, `population_matches_bronze`, `key_unique`, `place_levels_assigned`, `one_country`, `parents_resolve`, `tree_closes`, `levels_match_expected`, `sexes_add_up`, `household_not_above_total`, `concepts_pair_up`, `quarantined_cells` and lineage. The 4 WARN are `zero_population_cells` on each sheet (Kalayaan), as expected. The rule records count what each rule did:
- footnote split: 0 / 0 / 11 / 10
- old name split: 96 / 96 / 2 / 2
- capital flagged: 81 / 81 / 46 / 46
- structural rows: 12 (2020) and 33 (2024)

## Rerun at `8d90086` (2026-10-18)

After review, the branch was rebased onto `main` and changed: the tree is built from work tables instead of views, `place_status` flags the Interim Province and Special Geographic Area (`special_geographic_area`) and the eight 2020 cluster rows (`sga_cluster`), and a new FAIL check, `no_all_zero_place`, refuses a place with 0 in all 60 cells. `8d90086` restored the lane in the fan-in and in `tests/test_local_job.py` after the rebase. The same script ran on the working tree before that commit (`code_revision` `18ff46a…-dirty`; the uncommitted change touched only the fan-in and that test, not this lane), run by @maeveylain with Python 3.14.7 and DuckDB 1.4.5:

| | Run 1 | Run 2 |
|---|---|---|
| `run_id` | `820e2b98-b7c4-4f5f-ae4f-60d0fad59e48` | `1b9949c9-b118-483a-97a3-7dab9a8418b0` |
| Bronze | `load succeeded`, 3,496 + 13,985 inserted | `skip` both, 0 inserted |
| Silver build / gate | 8.0 s / 26.8 s | 6.5 s / 34.0 s |
| Gate results | 124: 120 PASS, 4 WARN, 0 FAIL | 124: 120 PASS, 4 WARN, 0 FAIL |
| Clean / quarantined | 418,320 / 0 | 418,320 / 0 |
| SHA-256 of the clean business content | `8933d05cdcb93c73…` | `8933d05cdcb93c73…` (identical) |
| SHA-256 of the quarantine business content | `4f53cda18c2baa0c…` | `4f53cda18c2baa0c…` (identical, empty) |

Full clean hash: `8933d05cdcb93c7307536dfd60856ce7bb2e9186fe3cf63289108260ac82ba38`. It differs from `e637b9bf…` above on purpose: every row now carries `place_status`. All 68 comparisons with the profile are OK, as before, plus the new ones: `place_status` per workbook is `special_geographic_area` 1 and `sga_cluster` 8 in 2020, `special_geographic_area` 1 and `sga_cluster` 0 in 2024, and `no_all_zero_place` is PASS (0) on all four sheets. Full test suite: 939 passed, 1 skipped. Databricks `dev` at `8d90086`: [its own record](../pipeline-runs/2026-10-18-psa-school-age-population-silver-databricks.md).

## Limitations

- Local DuckDB stands in for Spark and Delta (D-017). What only Databricks can confirm is listed in [Silver, Running on Databricks (school-age)](../../docs/operations/silver.md#running-on-databricks-school-age).
- Only the approved delivery of each census year was run. A tree that does not close, sexes that do not add up, household above total, a blank or negative count, an unpinned or mispinned workbook, and a rebuild are shown by `tests/test_silver_school_age.py` on made-up workbooks.

## How to reproduce

From a checkout with the #158 change and `RAW_DATA_DIR` set, run the command above. It writes `local_state/psa_school_age_population_silver_verification.md`. Expected at `8d90086` or later: 418,320 clean rows, 0 quarantined, 124 checks with 0 FAIL and 4 WARN, and identical content hashes across the two runs (`8933d05c…`).
