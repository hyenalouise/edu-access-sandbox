# Evidence: the real PSA school-age population workbooks load into Bronze locally once, and later runs insert nothing

Issue #157 · local DuckDB (D-017) · 2026-10-16, Manila time (UTC+8) · run by @saraevcldn

## The claim

The two PSA school-age population workbooks (2020 and 2024) load through the shared pipeline (format `xlsx_census`, contract `config/ingestion/psa_school_age_population.json`) into `psa_school_age_population_raw`. Every row of all four sheets is loaded, the layout checks pass, and each sheet's row count equals the count pinned in the contract and on the source card. Running the ingestion again skips both workbooks, and a forced rerun inserts nothing. The three known publisher quirks are recorded as WARN, each with its actual count equal to the profiled count.

## What was run

Code: branch `feat/157-bronze-psa-school-age-population`, Windows, PowerShell, the repository's `.venv`, `RAW_DATA_DIR` set to the raw-data root. The workbooks were in `$RAW_DATA_DIR/psa/original/` under their original names and were only read. The batch IDs below carry the approved SHA-256 prefixes (`e40d71839b95` for 2020, `49d15bb0cdd1` for 2024).

```powershell
python -m src.ingestion.cli ingest --source psa_school_age_population
python -m src.ingestion.cli status --source psa_school_age_population
```

| Step | Commit | `run_id` | Result |
|---|---|---|---|
| 1. First run, `sheet_rows` not yet pinned | `90fc80f` | `f7983888-47bd-48f1-b84d-f9acbd8ebb68` | Both batches `failed` on `sheet_rows_match_approved` only (4 FAIL, one per sheet), as designed. Nothing loaded. |
| 2. Counts pinned in the contract and on the card | `3dcdd8d` | | |
| 3. Load | `3dcdd8d` | not captured | Both batches `succeeded` (`status` shows 2 tries each, the first being step 1) |
| 4. Second run | `3dcdd8d` | `721ba0f7-72e1-4052-80c6-a14071988cc1` | Both batches `skip`, "already loaded; same SHA-256", inserted 0 |
| 5. Forced rerun, after the known-issue fix | `ae631ea` | `da770869-3ae0-479a-b50b-73d1f3cee2ba` | Both batches `rerun`, `succeeded`, inserted 0 |

Step 5 used `--rerun psa_school_age_population__2020__e40d71839b95 --rerun psa_school_age_population__2024__49d15bb0cdd1`.

## Results

**Sheet row counts** reported by step 1 (`actual` of `sheet_rows_match_approved` in `data_quality_results`) and pinned in step 2:

| Sheet | Rows |
|---|---:|
| `2020 Total Pop` | 1,748 |
| `2020 Household Pop` | 1,748 |
| `2024 Total Pop` | 6,994 |
| `2024 Household Pop` | 6,991 |

**Batches** after step 4 (`status`):

| `batch_id` | Period | Status | Tries | Source rows | Bronze rows |
|---|---|---|---:|---:|---:|
| `psa_school_age_population__2020__e40d71839b95` | 2020 | `succeeded` | 2 | 3,496 | 3,496 |
| `psa_school_age_population__2024__49d15bb0cdd1` | 2024 | `succeeded` | 2 | 13,985 | 13,985 |

3,496 = 1,748 × 2 sheets and 13,985 = 6,994 + 6,991, so Bronze equals the sheet counts.

**Known issues** after step 5:

| Check | Expected | Actual |
|---|---|---:|
| `2024 Total Pop: known_issue_place_label_footnote_marker` | 0 (profiled: 11, O-6) | 11 |
| `2024 Household Pop: known_issue_place_label_footnote_marker` | 0 (profiled: 10, O-6) | 10 |
| `2024 Household Pop: known_issue_title_names_only_city_municipality` | 0 (profiled: 1, O-1) | 1 |
| `2020 Total Pop: known_issue_source_line_misspelled` | 0 (profiled: 1, O-1) | 1 |
| `2020 Household Pop: known_issue_source_line_misspelled` | 0 (profiled: 1, O-1) | 1 |

All five are WARN, and each actual count equals its profiled count.

**Tests:** `python -m pytest tests -q` on the branch: 805 passed, 1 skipped (277 s).

## Not checked here

- The output of the load in step 3 was not kept, so its `run_id` is missing. The `status` output and the skip in step 4 show that it succeeded.
- Steps 1 to 4 ran before the known-issue fix (`ae631ea`), when a quirk whose count matched the profile was recorded as PASS. Step 5 records them under the fixed code.
- The local database was the repository's default `local_state/edu_access.duckdb`, not a fresh one.
- Databricks: see [the dev runs](2026-10-16-psa-school-age-population-databricks-idempotency.md).
