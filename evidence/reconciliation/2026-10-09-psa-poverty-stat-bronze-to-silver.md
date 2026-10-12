# Evidence: PSA Poverty Stat Silver reconciles with Bronze per estimate year, and every run rebuilds the same rows

Issue #89 · local runs (DuckDB) at `e799be3`, and two Databricks `dev` runs at `6cc39ca` · 2026-10-09 · checked by @Catweyine

## The claim

Silver built from the real Bronze rows of the approved workbook keeps every current Bronze unit row once per estimate year (clean + quarantined = units, for 2018, 2021 and 2023), accounts for every structural row, keeps every published value exactly (each Silver measure equals its own Bronze cell), keeps Kalayaan's missing estimates NULL, flags the statistical warnings at the profiled counts, and passes every FAIL-type gate check. A second run of the same lane, with Bronze skipping the already-loaded workbook, rebuilds both tables with identical business content and records a second `succeeded` run.

## What was run

Commit `e799be3bb38a528eb9c4894c31eadf22de890941` (clean: no `-dirty`; `estimate_year` INT, and `main` merged), macOS 26.4.1 (arm64), Python 3.12.14, DuckDB 1.4.5, a fresh database file under `local_state/`. The approved workbook `2_2023 SAE_with PSGC_noHUC_06Feb2026.xlsx` (SHA-256 `303fb0e87bff046acaa21e3ac586f6def6b737b9082eb1f51451a887fd93a026`, verified by the loader) was read from `raw-data/psa/original/`.

```bash
python -m pytest tests -q
```

560 passed.

```bash
RAW_DATA_DIR=~/Documents/GitHub/raw-data python analysis/verification/psa_poverty_stat_silver.py
```

It runs the PSA Poverty Stat lane of `edu_access_pipeline` twice through `src.job.local_run`'s task runner (the shared control bootstrap, then the five PSA tasks; the other source lanes are not run), then queries the result. Task times (seconds, local):

| Task | Run 1 | Run 2 |
|---|---:|---:|
| `bronze_psa_poverty_stat` | 0.15 (`load`, 1,641 rows inserted) | 0.03 (`skip`, 0 inserted: same SHA-256) |
| `90_validate_psa_poverty_stat_raw` | 0.01 | 0.02 |
| `05_clean_psa_poverty_stat` | 0.05 | 0.05 |
| `90_validate_psa_poverty_stat_clean` | 0.05 | 0.05 |

Every task `succeeded` in both runs. The control bootstrap tasks took 0.01 s each (`add_control_columns` 0.45 s in run 1, when it created the columns).

## Results

After run 2:

| Check | Expected | Actual | Result |
|---|---|---|---|
| Current Bronze rows | 1,641 | 1,641 | OK |
| unit / structural | 1,612 / 29 | 1,612 / 29 | OK |
| structural: title / header / region_banner / blank / footer | 1 / 4 / 18 / 0 / 6 | 1 / 4 / 18 / 0 / 6 | OK |
| Candidates = clean + quarantined, 2018 / 2021 / 2023 | 1,612 each | 1,612 + 0 each | OK |
| Clean rows in all | 4,836 | 4,836 | OK |
| `estimated` per year | 1,611 | 1,611 | OK |
| `no_estimate` per year (Kalayaan, ID `175321`, Excel row 641) | 1 | 1 | OK |
| `partial_estimate` | 0 | 0 | OK |
| NULL measure cells per year (Kalayaan's five) | 5 | 5 | OK |
| `cv_over_20` 2018 / 2021 / 2023 | 171 / 84 / 156 | 171 / 84 / 156 | OK |
| `se_cv_inconsistent` 2018 / 2021 / 2023 | 6 / 133 / 1 | 6 / 133 / 1 | OK |
| `lower_limit_not_positive`, all years | 3 | 3 (1 per year) | OK |
| IDs padded from 5 digits, per year | 1,073 | 1,073 | OK |
| Clean rows that join their current Bronze unit row | 4,836 | 4,836 | OK |
| Repeated keys (`psgc_id`, `estimate_year`) | 0 | 0 | OK |
| Distinct `cleaned_at_utc` across both tables | 1 | 1 | OK |

Expected values are the profile's baselines (O-2, O-5, O-7 to O-9) and the contract's row counts. They were also recomputed before this run by an independent Python reading of the workbook (the Bronze reader `prepare_workbook`, then the rules written again in Python, without the SQL), which gave the same numbers.

**Silver gate, run 2:** 115 results: 106 PASS, 9 WARN, 0 FAIL. The 9 WARN are the three statistical flags in each year (`flag_cv_over_20_<year>`, `flag_se_cv_inconsistent_<year>`, `flag_lower_limit_not_positive_<year>`), at the counts above. Every `<measure>_matches_bronze_<year>` check (5 measures × 3 years) found 0 mismatches; `missing_measures_stay_null_<year>` 5 = 5; `rows_reconcile_<year>` 1,612 = 1,612; `bronze_rows_accounted` 1,641 = 1,641; `quarantine_rate_<year>` 0; `rule_text_whitespace_normalized` 0 (no label needed it).

**Repeated full rebuild:** SHA-256 of all clean rows without the run stamp (`run_id`, `cleaned_at_utc`, `code_revision`), in a fixed order: `9122710e4acaa7820671bb1e6dfd6c6af2e4f5a8d1d7a4f71b773c5f568ed276` after both runs (the same value @hyenalouise got at `9e7e6a3`); the empty quarantine: `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` after both. The published `run_id` moved from run 1's to run 2's.

**Run record:** two `silver_build` rows in `pipeline_runs`, both `succeeded`, both `code_revision` `e799be3`: `ebf06e97-…` and `e3f8520e-…`.

## Databricks `dev`: two runs at `6cc39ca`

Job `edu_access_pipeline` (job ID `268191948913843`, target `dev`), deployed from commit `6cc39cac96587448fe47239161f1c8fe90ff8bd0` (`code_revision` and `git_commit` of the deployment), with `estimate_year` as INT. Both runs were started manually by @Catweyine on 2026-10-09; the second used **Run now** on the same deployment, without deploying again.

| Run | Job run ID | Started (Asia/Manila) | Duration | Status |
|---|---|---|---:|---|
| 1 | `1080268183594725` | 19:20 | 26m 18s | Succeeded |
| 2 | `846140731363521` | 19:53 | 3m 54s | Succeeded |

A run that succeeds passed both PSA gates: a FAIL stops the task before publishing. The check query in [Silver, Running on Databricks (PSA)](../../docs/operations/silver.md#running-on-databricks-psa), with the commit above, was run in the SQL editor after run 2:

| Check | Expected | Actual | Result |
|---|---|---|---|
| Clean rows 2018 / 2021 / 2023 | 1612 / 1612 / 1612 | 1612 / 1612 / 1612 | OK |
| Repeated keys | 0 | 0 | OK |
| `no_estimate` rows (Kalayaan, Excel row 641) | 3 | 3 | OK |
| `cv_over_20` 2018 / 2021 / 2023 | 171 / 84 / 156 | 171 / 84 / 156 | OK |
| `se_cv_inconsistent` 2018 / 2021 / 2023 | 6 / 133 / 1 | 6 / 133 / 1 | OK |
| `lower_limit_not_positive` | 3 | 3 | OK |
| IDs padded from 5 digits | 3219 | 3219 | OK |
| Units without a region banner | 0 | 0 | OK |
| Measure mismatches with Bronze | 0 | 0 | OK |
| Checks in the last run | 115 | 115 | OK |
| FAIL / WARN in the last run | 0 / 9 | 0 / 9 | OK |
| Rows from the last run | 4836 | 4836 | OK |
| Rows from another commit | 0 | 0 | OK |
| Last Silver run | succeeded | succeeded | OK |
| Silver runs succeeded at this commit | 2 | 2 | OK |
| Candidate rows not published | 0 | 0 | OK |
| Quarantined rows | 0 | 0 | OK |

So on Spark the PSA SQL gives the same results as DuckDB: `TRY_CAST` of scientific notation to DOUBLE (every measure equals its Bronze cell), `split`/`array_contains`, `lpad` (3,219 padded IDs), the banner window (every unit has a region), and the gate's `VALUES` aliases and `IS NOT DISTINCT FROM` (115 results). The published clean table equals its candidate.

**Content after run 2:** `content_sha256` (the business-content query in the same section) `4203ae8cf20f231c546b81dfb1825debe2dfd166cfe4eec02e48c29581c9929f`. It is computed by Spark SQL, so it is not comparable with the local hash below, which hashes Python values.

## What this does not show

- **Databricks run 1's content hash was not taken**, so the two Databricks builds are shown equal by their checks and counts (both runs succeeded at this commit, the gate passed each), not by two hashes. The check query reads only run 2's gate results.
- On Databricks, only `dev` has run, and only on a workbook that quarantines nothing.
- A quarantined row, a failing gate, a revised delivery and a new estimate year are shown only by the made-up workbooks in `tests/test_silver_psa.py`, not on the real data (the workbook quarantines nothing).
- Cross-year comparability of 2018, 2021 and 2023 (profile S-3) is not tested by any of this.

Raw output: written by the script to `local_state/psa_poverty_stat_silver_verification.md` (git-ignored, not committed).

## Earlier runs

At `e53dd8b` (`estimate_year` still text, before `main` was merged), the same lane gave every count above, 558 tests passed, and its two builds had identical content (SHA-256 `417b652a…7fe97de`, a different value because the year was text). Superseded by the run above.

The same lane was first run at `39129af` (before the columns were renamed and trimmed after review, D-034): every count above was identical, and its own two builds had identical content (SHA-256 `3fdbce79…a1ea5`, a different value because the columns differ). That run is superseded by this one.
