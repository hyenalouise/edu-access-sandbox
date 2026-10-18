# Evidence: the PSA school-age population workbooks load into Bronze on Databricks `dev` once, and a second run inserts nothing

Issue #157 · Databricks `dev` (D-017) · 2026-10-16, Manila time (UTC+8) · run by @saraevcldn

## The claim

On Databricks `dev`, the job `edu_access_pipeline` loads the two PSA school-age population workbooks from the raw volume into `psa_school_age_population_raw`. Each sheet's row count equals the contract, the source card and the [local run](2026-10-16-psa-school-age-population-local-idempotency.md), and the Bronze gate passes. Running the job again skips both workbooks, and Bronze is unchanged. A forced rerun at the branch head records the five known publisher quirks as WARN, each at its profiled count, and inserts nothing.

## What was run

- Job `[dev sara_celadina] edu_access_pipeline` (job ID `413860742211114`), deployed with `databricks bundle deploy --target dev` from `feat/157-bronze-psa-school-age-population` at `3dcdd8dd895f5c65bd39c58cdaff8c0194eded1f`. Every load task in both runs printed `code_revision=3dcdd8dd895f5c65bd39c58cdaff8c0194eded1f`.
- The branch was rebased onto `main` after these runs, so the hashes here are no longer on it. The same changes are now `3dcdd8d` = `2a80477` and `ae631ea` = `846310c` (identical `git patch-id`).
- Both workbooks uploaded by @saraevcldn to `/Volumes/edu_access/00-source/raw/psa/`. The job hashes each file itself. The batch IDs below carry the approved SHA-256 prefixes (`e40d71839b95` for 2020, `49d15bb0cdd1` for 2024).
- Started twice with `databricks bundle run edu_access_pipeline --target dev --profile reached-hq`.

| | Run 1 | Run 2 |
|---|---|---|
| Job queued → ended (Manila) | 19:49:04 → 19:58:08 | 19:59:57 → 20:06:27 |
| Job result | `TERMINATED SUCCESS` | `TERMINATED SUCCESS` |
| Ingestion `run_id` (`bronze_psa_school_age_population`) | `69c1b236-b5f8-4912-81ca-bea37ed531f8` | `4a80912b-db89-46f0-b6b7-3f8d21f6ee21` |
| 2020 batch | `load`, `initial`, `succeeded`, inserted 3,496 | `skip`, "already loaded; same SHA-256", inserted 0 |
| 2024 batch | `load`, `incremental`, `succeeded`, inserted 13,985 | `skip`, "already loaded; same SHA-256", inserted 0 |
| `90_validate_psa_school_age_population_raw` | succeeded | succeeded |
| Other sources | every batch `skip`, inserted 0 | every batch `skip`, inserted 0 |

The rows come from the `databricks bundle run` output.

## Results

Queried in the Databricks SQL editor after both runs.

**1. Rows per sheet**

```sql
SELECT census_year, source_sheet, count(*) AS rows
FROM edu_access.`02-bronze`.psa_school_age_population_raw
GROUP BY ALL ORDER BY ALL;
```

| `census_year` | `source_sheet` | rows |
|---|---|---:|
| 2020 | `2020 Household Pop` | 1,748 |
| 2020 | `2020 Total Pop` | 1,748 |
| 2024 | `2024 Household Pop` | 6,991 |
| 2024 | `2024 Total Pop` | 6,994 |

These equal the pinned `sheet_rows` and the local run. The query ran after run 2, so run 2 inserted nothing.

**2. Duplicate keys**

```sql
SELECT count(*) AS duplicate_keys FROM (
  SELECT source_sha256, source_sheet, source_row_number
  FROM edu_access.`02-bronze`.psa_school_age_population_raw
  GROUP BY ALL HAVING count(*) > 1);
```

`duplicate_keys` 0.

**3. Checks of the load**

```sql
SELECT status, count(*) AS checks
FROM edu_access.`01-control`.data_quality_results
WHERE source_id = 'psa_school_age_population' AND run_id = '69c1b236-b5f8-4912-81ca-bea37ed531f8'
GROUP BY ALL;
```

`PASS` 79, and no other status.

## Forced rerun at the branch head (2026-10-17)

Runs 1 and 2 came before the known-issue fix, so they recorded the quirks as PASS. To show the fix on `dev`, both batches were rerun on purpose at `9255854783b99defc14c3b54d6aedda799169442` (the branch head, which carries the fix as `846310c`).

- For this one run only, `databricks.yml` was edited locally, not committed, to add `--rerun psa_school_age_population__2020__e40d71839b95 --rerun psa_school_age_population__2024__49d15bb0cdd1` to the `bronze_psa_school_age_population` task. Then `databricks bundle deploy --target dev` and `databricks bundle run edu_access_pipeline --target dev --profile reached-hq`. Afterwards the edit was reverted and the bundle redeployed.
- Ingestion `run_id` `a88473c4-258c-4484-8251-8bc47e86d6a9`, `code_revision=9255854783b99defc14c3b54d6aedda799169442`, status `succeeded`.

| Batch | Action | Result | Inserted | Bronze rows |
|---|---|---|---:|---:|
| `psa_school_age_population__2020__e40d71839b95` | `rerun`, `initial` | `succeeded` | 0 | 3,496 |
| `psa_school_age_population__2024__49d15bb0cdd1` | `rerun`, `incremental` | `succeeded` | 0 | 13,985 |

```sql
SELECT check_name, status, expected, actual
FROM edu_access.`01-control`.data_quality_results
WHERE run_id = 'a88473c4-258c-4484-8251-8bc47e86d6a9' AND source_id = 'psa_school_age_population' AND status <> 'PASS';
```

`PASS` 74 and `WARN` 5: the same 79 checks as run 1, with the five quirks now WARN.

| `check_name` | `status` | `expected` | `actual` |
|---|---|---|---:|
| `2020 Total Pop: known_issue_source_line_misspelled` | WARN | 0 (profiled: 1, O-1) | 1 |
| `2020 Household Pop: known_issue_source_line_misspelled` | WARN | 0 (profiled: 1, O-1) | 1 |
| `2024 Total Pop: known_issue_place_label_footnote_marker` | WARN | 0 (profiled: 11, O-6) | 11 |
| `2024 Household Pop: known_issue_place_label_footnote_marker` | WARN | 0 (profiled: 10, O-6) | 10 |
| `2024 Household Pop: known_issue_title_names_only_city_municipality` | WARN | 0 (profiled: 1, O-1) | 1 |

These match the local forced rerun (step 5 of the [local evidence](2026-10-16-psa-school-age-population-local-idempotency.md)).

## Not checked here

- Runs 1 and 2 show the known publisher quirks as PASS, because that commit recorded a quirk as PASS when its count equalled the profile. The fix (`ae631ea`, now `846310c`) records them as WARN, as #157 asks; the forced rerun above shows it on `dev`.
- Job-run IDs and per-task timings (`databricks jobs get-run`) were not recorded.
- Table ownership by `reached-hq` and Delta column mapping were not queried.
- Silver: not built.
