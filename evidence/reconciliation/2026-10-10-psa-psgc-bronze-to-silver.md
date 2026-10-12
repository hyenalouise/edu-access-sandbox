# Evidence: PSGC 2Q 2026 Bronze reconciles to Silver, and a rebuild gives the same content

Issue #88 · local DuckDB (D-017) · 2026-10-10, Manila time (UTC+8) · run by @maeveylain

## The claim

At commit `9d2ee0181e597cd6c6fc4357a99c67dcd4889ebb`, the generated PSGC Silver build and gate (`etl/03_silver/04_clean_psa_psgc.sql`, `90_validate_psa_psgc_clean.sql`) turn the real 2Q 2026 Bronze rows into `psa_psgc_clean` with every row accounted for, every value equal to its rule applied to its own Bronze cell, and every gate check PASS. A second build gives identical business content.

Databricks `dev` was confirmed afterwards, on 2026-10-11: [below](#databricks-dev-two-runs-2026-10-11).

## What was run

A clean checkout of `9d2ee01` (a git worktree, no uncommitted change, so `code_revision` carries no `-dirty`), the project's Python 3.14.7 and DuckDB 1.4.5, a fresh git-ignored database, and `RAW_DATA_DIR` set to the raw-data root:

```bash
python -m src.ingestion.cli ingest --source psa_psgc --db local_state/psgc_silver_evidence.duckdb
```

Then the two Silver SQL files, run twice through `DuckDBStore.run_file` with the job's parameters (`run_id`, `code_revision` = `9d2ee01…`, `environment` = `local`), as `src/job/local_run.py` runs them.

| | Bronze | Silver run 1 | Silver run 2 |
|---|---|---|---|
| Run | `bb1b7a91-9961-434e-bd2c-70d2e74a9fbb` | `local-silver-1-256448e7` | `local-silver-2-57ce100d` |
| Started (UTC) | 2026-10-10 | 03:21:07 | 03:21:15 |
| Result | `load initial succeeded`, 43,768 inserted | `succeeded` | `succeeded` |
| Build / gate | | 5.7 s / 3.3 s | 2.0 s / 1.9 s |
| Gate results | | 50 PASS, 0 WARN, 0 FAIL | 50 PASS, 0 WARN, 0 FAIL |
| Clean / quarantined | | 43,768 / 0 | 43,768 / 0 |
| SHA-256 of the business content (every clean column but `run_id`, `cleaned_at_utc`, `code_revision`, ordered by code) | | `2aa69c692ebefc61…` | `2aa69c692ebefc61…` (identical) |

## Results

Queried in the database after run 2.

| Check | Expected (source card, mapping) | Silver |
|---|---|---|
| Rows; distinct codes | 43,768; 43,768 | 43,768; 43,768 |
| Rows flagged as the master quarter (2026-Q2) | 43,768 | 43,768 |
| Codes starting with `0` | 29,620 | 29,620 |
| Levels `Bgy` / `Mun` / `City` / `Prov` / `Reg` / `SubMun` / blank | 42,010 / 1,493 / 149 / 82 / 18 / 14 / 2 | the same; the 2 blank levels NULL with `level_blank` |
| Names ending in a space | 2,855 in Bronze | 0 |
| Population NULL / 0 | 1 `#N/A` / 12 | 1 (`publisher_na`) / 12 |
| Sum of the 18 regions' population | 112,727,776 (O-4) | 112,727,776 |
| Correspondence code NULL | 50 | 50 |
| `urban_rural` `-` → NULL `unknown` | 38 | 38 |
| Starred income classes split / `-` → `not_classified` | 6 / 8 | 6 / 8 |
| Rows with a population footnote | 19 | 19 |
| Barangays whose `city_municipality_code` is a municipality / city / sub-municipality | 34,007 / 7,106 / 897 (mapping) | the same; 0 missing |
| Cities / municipalities with no `province_code` | 33 HUCs / 1 (Pateros) | 33 / 1 |
| Distinct `run_id` and `code_revision` on the clean rows | 1 and `9d2ee01…` | 1 and `9d2ee01…` |

Rule records of the gate (always PASS, a count of what each rule did): `rule_text_whitespace_normalized` 2,874 rows (2,855 names, plus old names and footnotes), `rule_population_marker_to_null` 1, `rule_income_class_star_split` 6, `rule_placeholder_to_null` 46 cells (38 `urban_rural`, 8 `income_classification`), `flag_level_blank` 2, `flag_population_is_zero` 12, `flag_has_population_footnote` 19. Every FAIL check (reconciliation, uniqueness, the 18 `*_matches_bronze` checks, the 5 `labels_mapped_*` checks, the 3 parent checks, flags, lineage) recorded 0.

Both Silver runs are `succeeded` in `pipeline_runs`, with `code_revision` `9d2ee01…`.

## Limitations

- Local DuckDB stands in for Spark and Delta (D-017). The SQL features only Databricks can confirm are listed in [Silver, Running on Databricks (PSGC)](../../docs/operations/silver.md#running-on-databricks-psgc).
- One quarter only. Several quarters, a re-issued quarter, a duplicated code, an unmapped label and quarantine above 1% are shown by `tests/test_silver_psgc.py` on made-up workbooks.

## How to reproduce

From a clean checkout of `9d2ee01` (or later), with `RAW_DATA_DIR` set: load Bronze with the command above, then run the whole job with `python -m src.job.local_run --db <fresh file>`, or the two Silver files as described. Expected: 43,768 clean rows, 0 quarantined, 50 PASS.

## Databricks `dev`, two runs (2026-10-11)

The job `[dev maeve_lumague] edu_access_pipeline` (job ID `921726647955407`), deployed from branch `feat/88-psgc-silver` at merge commit `a6d34a90910ef03000ce78b2b0e33439b6ca00fc` (the PSGC Silver code of `9d2ee01`, merged with `main` for DepEd personnel #110). The deployed job's `git_source.git_commit` and `code_revision` parameter were both `a6d34a9…`, and the two PSGC Silver tasks were enabled. The run was announced to the team first.

```bash
databricks bundle validate --target dev --profile reached-hq
```

```bash
databricks bundle deploy --target dev --profile reached-hq
```

```bash
databricks bundle run edu_access_pipeline --target dev --profile reached-hq
```

The last command was run twice. The deploy replaced the old `[dev maeve_lumague] bronze_ingest` job (D-020), whose earlier runs are recorded in the Bronze evidence.

| | Run 1 | Run 2 |
|---|---|---|
| Job run | `913496403202511` | `677939887807442` |
| Whole job (Manila; UTC in brackets) | 09:16:42 to 09:24:14 (01:16:42 to 01:24:14), `SUCCESS` | 09:25:52 to 09:30:45 (01:25:52 to 01:30:45), `SUCCESS` |
| Tasks | 30 `SUCCESS` on the first attempt, 33 disabled | same |
| Bronze loads | every source skipped its files (PSGC: `skip`, 0 inserted, Bronze 43,768) | same |
| `04_clean_psa_psgc` | 01:21:02 to 01:22:00 UTC, `SUCCESS` | 01:28:16 to 01:28:38 UTC, `SUCCESS` |
| `90_validate_psa_psgc_clean` | 01:22:00 to 01:24:10 UTC, `SUCCESS` | 01:28:39 to 01:30:24 UTC, `SUCCESS` |
| `silver_build` run in `pipeline_runs` | `succeeded`, `code_revision` `a6d34a9…` | `succeeded`, `code_revision` `a6d34a9…` |

After run 2 the CLI printed `unexpected EOF` while fetching the task output; the run itself had ended `TERMINATED SUCCESS`, and the API shows every task's result as above.

Checked read-only through the SQL warehouse after both runs, with the query in [Silver, Running on Databricks (PSGC)](../../docs/operations/silver.md#running-on-databricks-psgc) (commit filled in). Every check OK:

| Check | Expected | Databricks |
|---|---|---|
| Clean rows 2026-Q2 / quarantined / repeated keys | 43,768 / 0 / 0 | 43,768 / 0 / 0 |
| Master reference rows / codes starting with `0` | 43,768 / 29,620 | 43,768 / 29,620 |
| Names ending in a space | 0 | 0 |
| Population NULL / zero; regions' total | 1 / 12; 112,727,776 | 1 / 12; 112,727,776 |
| Blank levels / `urban_rural` unknown / starred income classes | 2 / 38 / 6 | 2 / 38 / 6 |
| Checks in the last run; FAIL / WARN | 50; 0 / 0 | 50; 0 / 0 |
| Rows from another commit | 0 | 0 |
| Silver runs succeeded at this commit; last run | 2; succeeded | 2; succeeded |
| Candidate rows not published | 0 | 0 |

Also checked: levels 42,010 / 1,493 / 149 / 82 / 18 / 14 / 2 blank; barangay parents 34,007 municipality, 7,106 city, 897 sub-municipality, none missing; the rule records equal the local run (whitespace 2,874, marker 1, star split 6, placeholders 46, blank level 2, zeros 12, footnotes 19); the four tables (clean, quarantine, and their candidates) belong to `reached-hq`, and only the two candidates carry the "Unpublished build ... Do not read" comment. The warehouse was stopped after the job; this read-only check started it, and it stops on its own when idle.

What this confirms on Databricks: the Spark SQL of the build and the gate (`regexp_like`, `substr`, `split`/`array_contains`, `IS NOT DISTINCT FROM`, `CAST` to DATE and INT), publish-after-gate, and the lineage. What it does not: a failing gate, a quarantined row or a repeated code on Databricks (shown by the local tests), and the business content of run 1 against run 2 (the published table is replaced each run; identical content on rebuild is shown locally, above).

## Repeated after review, at `ee9392c` (2026-10-11, local)

Cath's review of #124 added two things to the gate at `ee9392ca3019e6f46a8c3cc412d75c4000e169b1`: a FAIL check, `province_code_missing_only_where_listed` (a city or municipality with no `province_code` must be an HUC or listed in the rules file; today only Pateros, `1381701000`), and a record, `rule_population_blank_to_null`, for the new `blank` population reason. The gate now writes 52 checks, not 50. The local run was repeated the same way, from a clean checkout of `ee9392c`, on a fresh database:

| | Bronze | Silver run 1 | Silver run 2 |
|---|---|---|---|
| Run | `20720b5b-f328-490d-9c0e-acb96f6bbd10` | `local-silver-1-bacb5306` | `local-silver-2-4dda0a5f` |
| Started (UTC) | 2026-10-11 | 04:06:17 | 04:06:23 |
| Result | `load initial succeeded`, 43,768 inserted | `succeeded` | `succeeded` |
| Gate results | | 52 PASS, 0 WARN, 0 FAIL | 52 PASS, 0 WARN, 0 FAIL |
| `province_code_missing_only_where_listed` | | PASS, 0 | PASS, 0 |
| `rule_population_blank_to_null` | | 0 | 0 |
| Clean / quarantined | | 43,768 / 0 | 43,768 / 0 |
| Content SHA-256 (as above) | | `2aa69c692ebefc61…` | `2aa69c692ebefc61…` |

The content hash equals the one at `9d2ee01`: the review changed the checks, not one value of the table. Every NULL population has a reason (1 `publisher_na`, 0 `blank`); the cities and municipalities with no `province_code` are the 33 HUCs and Pateros; every other count and record equals the run above.

## Databricks `dev` after review, at `a4d21b0` (2026-10-11)

The same job, redeployed from `a4d21b0553810ee10c60c285e3fcc9c567b5be66` (the code of `ee9392c` plus the local evidence above; both `git_source.git_commit` and `code_revision` were `a4d21b0…`), announced, and run twice with the same commands as above.

| | Run 3 | Run 4 |
|---|---|---|
| Job run | `375940486094107` | `918157622982175` |
| Whole job (Manila; UTC in brackets) | 14:24:23 to 14:31:19 (06:24:23 to 06:31:19), `SUCCESS` | 14:36:43 to 14:41:55 (06:36:43 to 06:41:55), `SUCCESS` |
| Tasks | 30 `SUCCESS` on the first attempt, 33 disabled | same |
| PSGC lane | all five tasks `SUCCESS`; Bronze skipped the loaded workbook | same |
| `silver_build` run | `succeeded`, `code_revision` `a4d21b0…` | `succeeded`, `code_revision` `a4d21b0…` |

The query in [Silver, Running on Databricks (PSGC)](../../docs/operations/silver.md#running-on-databricks-psgc) with this commit and 52 checks: every check OK (43,768 clean, 0 quarantined, 0 repeated keys, 52 checks with 0 FAIL / 0 WARN, every row from `a4d21b0`, 2 Silver runs succeeded at this commit, nothing unpublished in the candidates). The new checks: `province_code_missing_only_where_listed` PASS with 0 (no province only for the 33 HUCs and Pateros), `rule_population_blank_to_null` 0, and no NULL population without a reason. The other records equal the earlier runs. The hash of the published table's business columns, computed on Databricks, is `25017adf…` after these runs as after runs 1 and 2: the review changed no value.
