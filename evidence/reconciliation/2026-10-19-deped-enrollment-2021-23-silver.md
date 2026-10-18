# Evidence: DepEd enrollment SY 2021-22 and 2022-23 reconcile from Bronze to Silver per school year, one malformed ID is quarantined, and the other four years are unchanged

Issue #183 (part of #43) · local run (DuckDB) only; nothing has run on Databricks · 2026-10-19 · checked by @hyenalouise

## The claim

With SY 2021-22 and 2022-23 approved (the Bronze pull request), the existing Silver build and gate process all six school years with no rule or SQL change: both years publish only labels already in the mapping. Every current Bronze row of each year is in Silver clean or quarantine. One row is quarantined: SY 2022-23's seven-digit `1404066` (`school_id_malformed`, profile O-1), a WARN for that year only. Cleaning moves no learner of the clean rows. `Local Government` stays its own `school_management` value in all three years that publish it. The other four years' Silver rows are identical to the 2026-10-16 record. A second job run rebuilds the same content.

## What was run

Commit `263ce8524c1d8a2f9df34977981ff0d7df558614` on `feat/deped-enrollment-2021-23-silver` (stacked on the Bronze branch), clean worktree. macOS 26.3.1, Python 3.12.14, DuckDB 1.4.5. Each run started on a new, empty database file in a scratch folder, with the same `RAW_DATA_DIR` as the [Bronze record](2026-10-19-deped-enrollment-2021-23-bronze.md#what-was-run): symbolic links to `~/Projects/reached-hq/raw-data`, plus the EMISD workbook in `deped/original/`. The whole job ran twice:

```bash
RAW_DATA_DIR=<scratch>/landing python -m src.job.local_run --db <scratch>/lane.duckdb
```

Both runs exited 0, and every enabled task of every lane `succeeded`.

| Step | Run 1 | Run 2 |
|---|---|---|
| `bronze_deped_enrollment` | six files loaded, 362,023 rows (17.0 s) | all six `skip`, inserted 0 (0.2 s) |
| `01_clean_deped_enrollment` | 362,022 clean, 1 quarantined (2.3 s) | rebuilt: 362,022 clean, 1 quarantined (2.6 s) |
| `90_validate_deped_enrollment_clean` | 227 checks: 225 PASS, 2 WARN; run `succeeded` (2.0 s) | the same (2.0 s) |

Two earlier runs at `68f6c68`, the Bronze branch head (no mapping text change yet), gave the same counts, results, and hashes. The mapping changes in this branch are evidence text only: `etl/03_silver/01_clean_deped_enrollment.sql` and `90_validate_deped_enrollment_clean.sql` regenerate byte-identical.

## Results

### Silver, per school year (after run 2; run 1 identical)

| School year | Bronze current rows | Clean | Quarantined | Learners, Bronze (clean rows) | Learners, clean | `labels_mapped_school_management` |
|---|---:|---:|---:|---:|---:|---|
| 2020-21 | 60,957 | 60,957 | 0 | 26,227,022 | 26,227,022 | PASS |
| 2021-22 | 60,429 | 60,429 | 0 | 27,560,661 | 27,560,661 | PASS (0 unmapped) |
| 2022-23 | 60,137 | 60,136 | 1 | 27,794,274 | 27,794,274 | PASS (0 unmapped) |
| 2023-24 | 60,167 | 60,167 | 0 | 27,081,292 | 27,081,292 | PASS |
| 2024-25 | 60,129 | 60,129 | 0 | 26,400,182 | 26,400,182 | PASS |
| 2025-26 | 60,204 | 60,204 | 0 | 25,935,863 | 25,935,863 | PASS |
| **All** | 362,023 | 362,022 | 1 | | | |

SY 2021-22's learners equal profile O-3. SY 2022-23's clean learners are profile O-3's 27,794,282 less the 8 Kindergarten learners (7 male, 1 female) of the quarantined row. `learners_reconcile` compares the clean table with the same Bronze rows, so it PASSes. The 8 learners stay in Bronze.

The quarantined row:

| School year | `school_id` | `quarantine_reasons` | Why |
|---|---|---|---|
| 2022-23 | `1404066` | `["school_id_malformed"]` | Seven digits. The same file has `404066` for `Immaculate Conception Academy of Dancalan Inc.` (660 learners, none in Kindergarten), and every other year has only `404066` (profile O-1). Not merged into `404066`: the file does not say the two IDs are the same school. |

The two WARNs are `quarantine_rate` (expected `0 (FAIL above 1% of 60137)`, actual 1) and `quarantine_reason_school_id_malformed` (actual 1), both for SY 2022-23. The Silver gate has 5 whole-table checks and 37 checks per school year, so 153 for four years became 227 for six.

`school_management` in Silver:

| Label | SY 2021-22 | SY 2022-23 |
|---|---:|---:|
| DepEd | 47,383 | 47,557 |
| Non-Sectarian | 9,006 | 8,654 |
| Sectarian | 3,616 | 3,555 |
| SUC | 190 | 189 |
| **Local Government** | **155** | **106** |
| PSO | 32 | 32 |
| LUC | 30 | 26 |
| DOST | 13 | 13 |
| International School | 2 | 2 |
| Other GA | 2 | 2 |

SY 2022-23's Sectarian is 3,556 in Bronze (profile O-8). The quarantined row accounts for the difference.

Rule and flag counts, as the gate recorded them (the other four years are unchanged from [Silver, Cleaning rules](../../docs/operations/silver.md#cleaning-rules)):

| Rule or flag | SY 2021-22 | SY 2022-23 |
|---|---:|---:|
| `rule_whitespace_normalized` | 5 | 5 |
| `rule_characters_repaired` | 277 | 275 |
| `rule_blank_text_to_null` (rows; street_address 5,672 / 5,412, barangay 75 / 75) | 5,741 | 5,481 |
| `rule_placeholder_to_null` | 0 | 0 |
| `rule_blank_counts_to_null` (the four `*_unique_*` columns, O-16) | 60,429 | 60,137 |
| `rule_absent_columns_null` (v2-only columns) | 60,429 | 60,137 |
| `rule_labels_standardized` | 0 | 0 |
| `flag_is_overseas` | 32 | 32 |
| `flag_enrollment_all_zero` | 206 | 153 |
| `flag_enrollment_no_counts` | 0 | 0 |
| `flag_barangay_possibly_truncated` | 25 | 25 |
| `flag_barangay_blank` | 75 | 75 |

The rule counts are per Bronze row, so SY 2022-23's include the quarantined row.

Kept as published, for Integration or Analytics to disclose: the 192 Cotabato City and Special Geographic Area schools labelled `BARMM` from SY 2021-22 (O-10); 2,525 and 2,520 `Region XII` rows; the 1,481 SY 2021-22 and 698 SY 2022-23 school IDs absent from SY 2023-24, and so from the EMISD crosswalk (O-12); 206 and 153 zero-enrollment schools (S-1); the 6 SY 2021-22 rows with province `Davao Occidental` in mixed case (O-5); the school `305365` placed in Pampanga from SY 2022-23 (S-2); and 32 PSO rows per year.

The verification query in [Silver, Running on Databricks](../../docs/operations/silver.md#running-on-databricks), updated in this branch for six deliveries, ran through the local store after run 2 with the commit above filled in. All 25 rows were `OK`.

### Content hashes (run stamps excluded)

The query from the [2026-10-09 record](2026-10-09-deped-enrollment-bronze-to-silver.md), in school year and row order, every column except the run stamp:

| Table | Rows | After run 1 | After run 2 |
|---|---:|---|---|
| `deped_enrollment_clean`, all six years | 362,022 | `9e4f1f463db3d2880ae7e586ebb8febd` | same |
| `deped_enrollment_clean`, SY 2021-22 only | 60,429 | `a33a212a24a18f40b3860387c52c36e8` | same |
| `deped_enrollment_clean`, SY 2022-23 only | 60,136 | `d256b69fbc5a9d4a734694533b6e3375` | same |
| `deped_enrollment_clean`, SY 2020-21 and 2023-24 to 2025-26 | 241,457 | `caf188b7ec19d4be1f900332e17bcfdc` | same |
| `deped_enrollment_clean`, SY 2020-21 only | 60,957 | `ddb817284d3a645ee7a599113b55bd5e` | same |
| `deped_enrollment_clean`, SY 2023-24 to 2025-26 | 180,500 | `311b445851533467fd7e669d3cf6e537` | same |
| `deped_enrollment_quarantine` | 1 | `9dec325f82995802744cd913f8058300` | same |

The four-year, SY 2020-21, and three-year hashes equal the [2026-10-16 record](2026-10-16-deped-enrollment-2020-21-bronze-to-silver.md#content-hashes-run-stamps-excluded) and the 2026-10-09 record. So adding SY 2021-22 and 2022-23, and the mapping text, changed no Silver row of the other four years.

## Why it holds

1. The Silver build and gate are generated from the contract and the mapping, with no school year in them, and read `current_batches`, so every approved year is processed. This branch changes only evidence and rule text in the mapping; the regenerated SQL is byte-identical (`tests/test_silver.py::test_silver_files_match_the_mapping`).
2. Every label both years publish is already mapped (checked against Bronze for `region`, `legislative_district`, `sector`, `school_management`, `annex_status`, and the three `offers_*` booleans), so no `labels_mapped_*` check can fail.
3. The quarantine rule for a malformed `school_id` is D-024's, unchanged. One row of 60,137 is 0.002%, far below the 1% FAIL.
4. Skips and rebuilds: see the [2026-10-09 record](2026-10-09-deped-enrollment-bronze-to-silver.md#why-it-holds).

## Also shown by tests

`python -m pytest tests -q`: 943 passed. New for these deliveries, in `tests/test_silver.py`: across six years of made-up rows, adding SY 2021-22 and 2022-23 leaves the other four years' Silver rows unchanged; each year reconciles rows, learners, and labels; `Local Government` stays its own value in SY 2020-21, 2021-22, and 2022-23; the seven-digit `1404066` is quarantined as `school_id_malformed` with `quarantine_rate` WARN for that year only; a rerun rebuilds the same rows.

## What this does not prove

- Anything on Databricks. See the [Bronze record's Awaiting authorization](2026-10-19-deped-enrollment-2021-23-bronze.md#awaiting-authorization). After those runs, the verification query above should show every row `OK`.
- That `1404066` is `404066`'s Kindergarten under a mistyped ID. If DepEd confirms it, merging the two rows is a new Silver rule that the source owner approves; until then, Silver does not guess.
- That `Local Government` schools were managed differently from `DepEd` schools (as in the [2026-10-16 record](2026-10-16-deped-enrollment-2020-21-bronze-to-silver.md#what-this-does-not-prove)).

## How to reproduce

From a clean checkout of the commit above, with `RAW_DATA_DIR` set as described, run the job command above twice against a new database file. Then run the Silver verification query and the hash queries through `DuckDBStore("<scratch>/lane.duckdb").query(sql)` from `src.ingestion.store`.
