# Evidence: fact_school_enrollment builds and passes its gate locally on all six enrollment school years

Issue #46 · local DuckDB · 2026-10-19, Manila time (UTC+8) · run by @Catweyine

## The claim

`10_build_fact_school_enrollment.sql` and `90_validate_fact_school_enrollment.sql`, run by the local job on the real published `deped_enrollment_clean` (SY 2020-21 to 2025-26) and `deped_school_psgc_map`, build 1,086,066 rows, three for each of the 362,022 Silver rows. The gate records 152 PASS, 5 WARN and 0 FAIL, and publishes. A second job run gives the same table. **Observed**, local only: not yet run on Databricks.

## What was run

- `python -m src.job.local_run --db local_state/gold_check.duckdb`, with `RAW_DATA_DIR` set to the raw-data folder holding every approved delivery in `config/ingestion/` (all six enrollment years, the EMISD crosswalk, facilities, personnel, PSGC, poverty, school-age population, HDX), each matched by SHA-256.
- On a throwaway local branch that merges `main`, #168 (`dim_school`, `dim_school_year`, `dim_education_level`), #193 (`dim_city_municipality`, `dim_barangay`) and this branch, because the gate checks every key against those five dimensions. The branch is not pushed.
- Run twice: the second run skipped every delivery as already loaded (same SHA-256) and rebuilt every table.

The whole job succeeded: every Bronze, Silver, Integration and Gold task, 0 FAIL in any Gold gate.

## Results

| Silver rows by school year | 2020-21 | 2021-22 | 2022-23 | 2023-24 | 2024-25 | 2025-26 |
|---|---:|---:|---:|---:|---:|---:|
| `deped_enrollment_clean` | 60,957 | 60,429 | 60,136 | 60,167 | 60,129 | 60,204 |

| Check | Expected | Run 1 | Run 2 |
|---|---:|---:|---:|
| `rows_reconcile` (3 × 362,022) | 1,086,066 | 1,086,066 | 1,086,066 |
| `key_unique`, `key_not_null`, `geography_not_null`, `member_follows_status` | 0 | 0 | 0 |
| `school_in_dimension`, `school_year_in_dimension`, `education_level_in_dimension`, `city_in_dimension`, `barangay_in_dimension`, `barangay_in_city` | 0 | 0 | 0 |
| `offering_flag_published`, `not_offered_without_learners`, `learner_count_follows_rule` | 0 | 0 | 0 |
| `offering_flag_blank/<school year>/<level>`, `not_offered_positive/<school year>/<level>` (18 each) | 0 | 0 | 0 |
| `rows_match_silver`, `sector_matches_silver`, `annex_status_matches_silver`, `is_offered_matches_silver`, `learner_count_matches_silver`, `match_status_matches_map`, `city_matches_map`, `barangay_matches_map` (every row against a recount from Silver and the map) | 0 | 0 | 0 |
| `cells_before_start_blank` (unique-strand cells before SY 2024-25, Strengthened SHS cells before SY 2025-26) | 0 | 0 | 0 |
| `schools_city_unknown` (WARN; school years, unmatched 58 + ambiguous 94) | 0 | 152 | 152 |
| `schools_barangay_unknown` (WARN; city matched, no single barangay) | 0 | 583 | 583 |
| `schools_excluded` (Philippine Schools Overseas and SGA schools, D-031) | count | 277 | 277 |
| `offered_all_blank/2025-26/ES`, `/JHS`, `/SHS` (WARN) | 0 | 40 / 29 / 120 | 40 / 29 / 120 |
| PASS / WARN / FAIL | | 152 / 5 / 0 | 152 / 5 / 0 |
| MD5 of the published table, ordered by key | | `40553872dae531e213187a7cfc149765` | `40553872dae531e213187a7cfc149765` |

Learners (`learners/<school year>/<level>`), all sectors:

| School year | ES | JHS | SHS |
|---|---:|---:|---:|
| 2020-21 | 14,650,804 | 8,339,391 | 3,236,827 |
| 2021-22 | 14,977,991 | 8,757,957 | 3,824,713 |
| 2022-23 | 15,188,427 | 8,426,203 | 4,179,644 |
| 2023-24 | 15,201,951 | 7,749,265 | 4,130,076 |
| 2024-25 | 14,748,764 | 7,665,606 | 3,985,812 |
| 2025-26 | 14,348,159 | 7,758,408 | 3,829,296 |

Independent cross-checks (**observed**):

- The gate recounts every row from Silver and the map without the build's audit columns (plain addition, NULL when any applicable cell is blank) and compares sector, annex_status, is_offered, learner_count, match status, city and barangay on all 1,086,066 rows: 0 differ, and no key is on one side only.

- ES learners equal a direct sum of Silver's 16 ES cells for offered rows in every school year, computed outside the build.
- No offered level is partly blank in any year; the only blanks are whole levels in SY 2025-26. Of the 120 SHS ones, 21 are public schools, the 21 the metric specification names.
- No row has a blank offering flag and no level that is not offered has a positive cell, so rules 1 and 4 of the metric specification do not fail on real data, in total or in any school year and level.
- No unique-strand cell is published before SY 2024-25 and no Strengthened SHS cell before SY 2025-26, so the build leaves no published learner out of `learner_count`.

## Column types

The published table has the data model's columns and types. The build casts each one, and `test_three_rows_per_school_year_and_the_data_model_columns` checks names, order and types. DuckDB, which the local run uses, names `STRING` as `VARCHAR`; it is the same type.

| Column | Data model (Databricks) | Local DuckDB |
|---|---|---|
| `school_id`, `school_year`, `education_level_code`, `city_mun_psgc_code`, `barangay_psgc_code`, `psgc_match_status`, `sector`, `annex_status` | STRING | VARCHAR |
| `is_offered` | BOOLEAN | BOOLEAN |
| `learner_count` | BIGINT | BIGINT |

## What this does not show

- A Databricks `dev` run: the tasks wait for #168 and #193.
- The technical member codes (`UNKNOWN`, `EXCLUDED`, `<city>-UNKNOWN`) are still a proposal on #174.
