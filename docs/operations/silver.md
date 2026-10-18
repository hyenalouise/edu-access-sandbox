# Silver: Bronze → clean, typed, standardized

How the Bronze rows of each source's current deliveries become one clean, typed, validated table, what each rule changes, what is set aside, and how each run is recorded. The first source built this way is `deped_enrollment` (#85); `psa_poverty_stat` ([PSA Poverty Stat](#psa-poverty-stat), D-034) and `deped_facilities` ([DepEd facilities](#deped-facilities), D-038) follow the same task, run, and publishing design with their own shape and rules.

**Status:** two SQL tasks of the job `edu_access_pipeline`, built and tested locally, and run by the job on the real Bronze data of all three school years (2026-10-09, [evidence](../../evidence/reconciliation/2026-10-09-deped-enrollment-bronze-to-silver.md)). Run on Databricks `dev` on 2026-10-09 at `7d93d8e`: two job runs, every check OK, identical rows ([evidence](../../evidence/pipeline-runs/2026-10-09-deped-enrollment-silver.md)); and with publishing after the gate at `acd6416`, with the same rows ([evidence](../../evidence/pipeline-runs/2026-10-09-silver-publish-after-gate.md)).

## The flow

```
bronze_deped_enrollment             Python: check and load the deliveries          (serverless)
90_validate_deped_enrollment_raw    SQL: the Bronze gate                            (SQL warehouse)
   │  only if it passed
   ▼
01_clean_deped_enrollment           SQL: run stamp in session variables; pipeline_runs 'running';
   │                                     rebuild the candidates from 01-control.current_batches only:
   │                                       deped_enrollment_clean_candidate       one row per school per school year
   │                                       deped_enrollment_quarantine_candidate  rows that cannot be trusted, with reasons
   │  only if it succeeded
   ▼
90_validate_deped_enrollment_clean  SQL: check the candidates, one row per check in data_quality_results
                                         any FAIL: pipeline_runs 'failed', the task stops, nothing published
                                         all PASS or WARN: publish quarantine, then clean:
                                           deped_enrollment_quarantine, deped_enrollment_clean
                                         then pipeline_runs 'succeeded'
   │
   ▼  this source lane is complete; other source lanes run independently in parallel
      90_validate_control is the fan-in: it records every Silver lane and fails if one did not succeed;
      only freshness follows it. Each Integration and Gold task starts from the Silver gates it reads (D-051),
      and reads a Silver table only when the run its rows carry succeeded
```

Code: `src/silver/` ([module list](../../src/silver/README.md)). SQL: `etl/03_silver/` ([files](../../etl/03_silver/README.md)), generated from the Bronze contract and the [Silver mapping](../../config/mappings/deped_enrollment.json). Columns: [data dictionary](../data/silver/deped-enrollment-clean.md). The job: D-020; Silver: D-021 to D-025 in [decisions.md](../governance/decisions.md).

## The question Silver answers

> When a planner reads a number built from Silver, can the team say exactly which Bronze row it came from, what was changed, why, and what was set aside, without rerunning everything or spending compute it does not need?

| Part | How |
|---|---|
| Which Bronze row | Every clean and quarantined row carries `batch_id`, `delivery_version`, `schema_version`, `source_sha256`, and `source_row_number`; the last two identify the Bronze row exactly. The gate checks that every Silver row resolves to a current Bronze row |
| What was changed | Each rule is one generated SQL expression from a reviewed file. Every build records how many rows each rule changed or flagged (`rule_*`, `flag_*` in `data_quality_results`), and the published value is always one join away in Bronze |
| Why | The rule table below, the evidence for every label in the mapping, and decisions D-021 to D-025 |
| What was set aside | `deped_enrollment_quarantine`, with the reasons; `rows_reconcile` proves Bronze rows = clean + quarantined, per school year. A build that fails its gate is never published; it waits in the candidate tables for review |
| Which run and code | `run_id` (the job run), `cleaned_at_utc` (one value per build), and `code_revision` on every row and every check; the run itself in `pipeline_runs` |
| Compute | Silver runs only after its Bronze gate passed, as two SQL tasks on the warehouse the Bronze gate already started. Rebuilding 180,000 rows takes about a second locally (D-025) |

## Grain and shape

One row per school per school year, key (`school_id`, `school_year`), wide as published: the 66 grade × sex × strand count columns stay columns (D-021). Gold unpivots them when its grain is agreed. Column names are snake_case; the one publisher column that is not, `Modified Curricular Offering Classification` (SY 2025-26 only, undocumented), is renamed `modified_curricular_offering_classification`.

## Cleaning rules

Counts are from the local run on the real Bronze data, current batches only (version 1 of each school year), on 2026-10-07; SY 2020-21 from the local run of 2026-10-16, which reproduced the other three years exactly ([evidence](../../evidence/reconciliation/2026-10-16-deped-enrollment-2020-21-bronze-to-silver.md)); SY 2021-22 and 2022-23 from the local run of 2026-10-19, which reproduced the other four years exactly ([evidence](../../evidence/reconciliation/2026-10-19-deped-enrollment-2021-23-silver.md)). Every build records the same numbers in `data_quality_results`. Action: **transform** changes a value, **flag** adds a column and keeps the row, **quarantine** sets the row aside, **fail** stops the run.

| Rule | Finding | Action | Why | SY 2020-21 | SY 2021-22 | SY 2022-23 | SY 2023-24 | SY 2024-25 | SY 2025-26 | Information that may be lost (all of it stays in Bronze) |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---|
| Read only the current batch of each school year | D-015 | transform | Older versions stay in Bronze, never in Silver | 60,957 rows | 60,429 | 60,137 | 60,167 | 60,129 | 60,204 | Superseded versions (none yet) |
| `school_id` kept as text, exactly six digits, unique per year | O-1 | quarantine | A key that is blank, malformed, or repeated cannot be trusted | 0 | 0 | 1 (`1404066`) | 0 | 0 | 0 | The quarantined rows, until resolved |
| Counts to INT when 1–9 digits | O-2 | transform | Whole numbers type without loss | 0 not castable | 0 | 0 | 0 | 0 | 0 | None |
| Negative or non-whole count | O-2 | quarantine | A count cannot be negative or fractional | 0 | 0 | 0 | 0 | 0 | 0 | The quarantined rows |
| Count above 10,000 (`plausible_max`) | O-2 | quarantine | The largest published count is 4,097; above 10,000 is a count with an extra digit, which reconciliation cannot see | 0 | 0 | 0 | 0 | 0 | 0 | The quarantined rows |
| Blank count stays NULL, not 0 (rows with a blank count) | O-16, Bronze | transform | Never invent a value; in SY 2025-26 blank means "not published". In SY 2020-21 to 2023-24 the four unique-strand columns (`g11_unique_*`, `g12_unique_*`) are blank in every row and no other count is blank, so those years publish no unique-strand enrollment: NULL, not 0 | 60,957 | 60,429 | 60,137 | 60,167 | 0 | 48,709 | None |
| Column absent from the year's file stays NULL (rows) | O-7 | transform | Told apart from a blank by `schema_version` (`v1`) | 60,957 | 60,429 | 60,137 | 60,167 | 60,129 | 0 | None |
| Learners unchanged by cleaning (`learners_reconcile`) | O-3 | fail if not | Cleaning must move no learner | 26,227,022 | 27,560,661 | 27,794,274 (the file's 27,794,282 less the quarantined row's 8) | 27,081,292 | 26,400,182 | 25,935,863 | — |
| Labels mapped to one standard set (rows with any relabel) | O-8, O-9 | transform; unmapped **fails** | One label per category across years | 0 | 0 | 0 | 0 | 0 | 60,204 | The year's own wording |
| `True`/`Yes` → TRUE, `False`/`No` → FALSE, blank → NULL | O-8 | transform; unmapped **fails** | One boolean representation | 0 unmapped | 0 | 0 | 0 | 0 | 0 | None |
| Trim, collapse spaces, tabs, no-break spaces (rows) | O-5 | transform | Spacing differences break joins (`NCR   SECOND DISTRICT`, `Non-Sectarian `) | 5 | 5 | 5 | 6 | 4 | 13,958 | Exact spacing |
| Repair `Ã‘` → `Ñ` and `Ã±` → `ñ` in free text (rows) | O-17 | transform | Mangled in the published data, every year | 281 | 277 | 275 | 273 | 274 | 274 | The mangled bytes |
| Blank text → NULL (rows; `street_address` 5,782 / 5,672 / 5,412 / 5,203 / 5,038 / 0 and `barangay` 84 / 75 / 75 / 70 / 65 / 7) | O-14, O-15 | transform | Make missingness explicit | 5,859 | 5,741 | 5,481 | 5,266 | 5,096 | 7 | None |
| `street_address` `-`, `n/a`, `N/A` → NULL | O-14 | transform | Placeholders mean no address | 0 | 0 | 0 | 0 | 0 | 3,555 | The placeholder spelling |
| `is_overseas` (PSO, SCHOOL ABROAD) | O-13 | flag | Placed in Pasig City in SY 2025-26; Gold excludes from geography | 33 | 32 | 32 | 33 | 35 | 36 | None |
| `enrollment_status = 'all_zero'` | S-1 | flag | Possibly closed or non-reporting; never dropped | 439 | 206 | 153 | 115 | 24 | 0 | None |
| `enrollment_status = 'no_counts'` | S-1, Bronze | flag | No count published at all | 0 | 0 | 0 | 0 | 0 | 46 | None |
| `barangay_possibly_truncated` (published length exactly 40) | O-18 | flag | Cannot be repaired | 25 | 25 | 25 | 24 | 25 | 25 | None |
| Blank `barangay` (NULL) | O-15 | flag (NULL) | Placement below the municipality is unknown | 84 | 75 | 75 | 70 | 65 | 7 | None |
| Region and province changes (192 Cotabato City and Special Geographic Area schools labelled Region XII in SY 2020-21, BARMM from SY 2021-22), `(Capital)` and other place-name spelling | O-10, O-11, O-5 | none | Comparability and matching belong to Integration and Gold (D-012) | kept | kept | kept | kept | kept | kept | — |
| School ID churn (2,517 SY 2020-21, 1,481 SY 2021-22, and 698 SY 2022-23 clean IDs absent from SY 2023-24; 699 in the SY 2022-23 file, counting the quarantined `1404066`, profile O-12) | O-12 | none | Not a data error; Gold reports it | — | — | — | — | — | — | — |

Silver keeps "(Capital)" on 5,541 / 5,487 / 5,455 / 5,450 / 5,454 / 5,446 rows (SY 2020-21 to 2025-26) and every other place spelling, so Integration can match them to PSGC.

**`Local Government` (SY 2020-21 to 2022-23).** 154, 155, and 106 public schools publish `school_management = Local Government`, a label no year from SY 2023-24 uses. All 154 of SY 2020-21 keep it in SY 2021-22; 47 of SY 2021-22's become `DepEd` in SY 2022-23, and 102 of SY 2022-23's are `DepEd` in SY 2023-24. Over SY 2020-21 to 2023-24, 149 of the 154 become `DepEd`, and the other 5 are not in SY 2023-24 or 2024-25 (profile O-8). Silver keeps it as its own standard value. Mapping it to `DepEd` would claim a management the file does not publish for that year, and mapping it to `LUC` would mix it with a SUC/LUC-sector label. Bronze keeps the published value. The facilities and personnel mappings share this standard set, so it is listed there too, although their SY 2023-24 files never publish it. Whether a year-over-year management comparison should treat it as `DepEd` is a question for Gold.

### What the Bronze data showed beyond the profile

Profiling Bronze rather than the raw files confirmed every count above, and found three things the profile does not say (to add to [profile.md](../data/source-inventory/deped_enrollment/profile.md) with the profiling script, D-007):

- **SY 2025-26 leaves counts blank where earlier years publish 0.** All 47,232 schools with `offers_shs = No` have blank senior-high columns, where SY 2024-25 publishes 0 for such schools, and 1,403 schools have blank kindergarten-to-grade-10 columns. Sums are unaffected; a school-level comparison across years must not read NULL as 0.
- **S-1 for SY 2025-26 is 46 schools with no count at all**, not 46 schools with zero counts (Private 35, PSO 8, Public 3). No SY 2025-26 school publishes all zeros.
- **O-17's "11, 11, 10 school names" are lowercase `Ã±`**, not `Ã‘`. Three to four school names and addresses per year also contain a tab or a no-break space.

## Quarantine

`deped_enrollment_quarantine` holds `school_year`, `school_id` as published, `quarantine_reasons` (every reason that applies), the Bronze lineage, and the run stamp. Read the published values from Bronze by `source_sha256` and `source_row_number`. Reasons: `school_id_blank`, `school_id_malformed`, `school_id_duplicated`, `count_negative`, `count_uncastable`, `count_above_plausible_max` (D-024). Of the six approved years, only SY 2022-23 quarantines a row: `1404066` (`school_id_malformed`), a seven-digit ID with 8 Kindergarten learners, published beside the school's six-digit `404066` (profile O-1). It is not merged into `404066`, because the file does not say the two IDs are the same school; its learners stay in Bronze.

A row's reasons are decided with explicit NULL handling (`school_id IS NULL OR school_id = ''`), and the reasons string is never NULL, so the split into the two tables cannot lose a row whose `school_id` is NULL; `tests/test_silver.py` proves it with such a row.

## The gate

`etl/03_silver/90_validate_deped_enrollment_clean.sql` is the job task after every build, reading Bronze, the two candidate tables, and `current_batches`. It writes one row per check to `` `01-control`.data_quality_results `` with `layer = 'silver'`, `:run_id`, `:code_revision`, and the candidate table checked as `table_name`. If this execution recorded any FAIL it records the run `failed` and fails the task before publishing anything. Otherwise it publishes the candidates (quarantine first, then clean) and records the run `succeeded`. Only this execution's results count, so a repaired job run (same `run_id`) is judged on its own. Column types are fixed by the build itself (every count through `TRY_CAST(... AS INT)`); `tests/test_silver.py` checks them locally, and the Databricks check below checks them in Unity Catalog.

| Check | Per | FAIL when |
|---|---|---|
| `rows_reconcile` | school year | Bronze current rows ≠ clean + quarantined |
| `school_id_unique`, `school_id_valid` | school year | A key repeats, is NULL, or is not six digits in the clean table |
| `counts_non_negative` | school year | A count is negative |
| `counts_within_plausible_max` | school year | A count is above 10,000 in the clean table |
| `learners_reconcile` | school year | Clean learners ≠ Bronze learners of the same rows |
| `missing_counts_stay_null` | school year | NULL count cells in clean ≠ blank or absent cells in Bronze (catches blank → 0) |
| `absent_columns_stay_null` | school year | A column the year's schema lacks is filled |
| `labels_mapped_<column>` (9 columns) | school year | A published label is not in the reviewed mapping, on a clean or a quarantined row |
| `enrollment_status_valid` | school year | A status outside the three values |
| `current_batches_present` | table | Bronze has no current batch for the source, so Silver would be empty |
| `lineage_complete`, `rows_resolve_to_current_bronze` | table | A lineage column is NULL, or a Silver row is not a current Bronze row |
| `rows_built_by_this_run`, `one_timestamp_per_run` | table | A row is left from another run, or the tables disagree on `cleaned_at_utc` |
| `quarantine_rate` | school year | WARN above 0; **FAIL above 1%** of the year's Bronze rows |
| `quarantine_reason_<reason>` | school year | WARN above 0 |
| `rule_*`, `flag_*` | school year | Never: records of how many rows each rule changed or flagged (expected is NULL) |

| Status | Meaning | Action |
|---|---|---|
| PASS | As expected | None |
| WARN | Rows were quarantined (at most 1% of a year) | Recorded; the build is published; the source owner reviews the reasons |
| FAIL | The candidate build cannot be trusted | The gate task fails before publishing and `pipeline_runs` says `failed`; the Silver tables keep the last build that passed, and the failed one waits in the candidate tables until the next run. Other source lanes are independent and keep running |

The local run on the real data recorded 116 results for three years, all PASS (2026-10-09), 153 for four years, all PASS (2026-10-16), and 227 for six years, 225 PASS and 2 WARN, `quarantine_rate` and `quarantine_reason_school_id_malformed` for SY 2022-23 (2026-10-19): 5 table checks and 37 per school year.

## Every run rebuilds, and every run is recorded

Silver rebuilds both candidate tables on every job run with `CREATE OR REPLACE TABLE ... AS SELECT` from the current batches, and publishes them when the gate passes (D-025): the same Bronze gives the same rows, so a rerun changes nothing but the run stamp, and a revised delivery (`delivery_version` 2) replaces its school year because `current_batches` points to it. On the real data, the MD5 of all 180,500 clean rows (without the run stamp) was `311b445851533467fd7e669d3cf6e537` after both of two job runs ([evidence](../../evidence/reconciliation/2026-10-09-deped-enrollment-bronze-to-silver.md), with the query). With SY 2020-21 added, all 241,457 clean rows hash to `caf188b7ec19d4be1f900332e17bcfdc` after both of two runs, and the three earlier years alone still hash to `311b4458…` ([evidence](../../evidence/reconciliation/2026-10-16-deped-enrollment-2020-21-bronze-to-silver.md)). With SY 2021-22 and 2022-23 added, all 362,022 clean rows hash to `9e4f1f463db3d2880ae7e586ebb8febd` after both of two runs, and the other four years alone still hash to `caf188b7…` ([evidence](../../evidence/reconciliation/2026-10-19-deped-enrollment-2021-23-silver.md)).

Each published table is one Delta commit; the pair is not, so the run row is the commit marker, as `ingestion_batches` is for Bronze. Its `run_id` is the job run id, which every source's build in that job run shares, so the row is keyed by `run_id`, `pipeline_name`, and `source_id`, and `job_run_id` holds the same id, so filtering `pipeline_runs` on `job_run_id` finds a job run's Bronze loads and Silver builds together (D-020):

| `pipeline_runs.status` (`pipeline_name = 'silver_build'`) | Written by | Meaning |
|---|---|---|
| `running` | the build task, first | The build started; with no later status it never finished, its gate never ran, or the task died while publishing |
| `succeeded` | the gate task, after publishing | Every check passed or warned, and both tables were published: Silver rows carrying this `run_id` may be read |
| `failed` | the gate task, after its checks | At least one FAIL: nothing was published; the build is in the candidate tables |

Gold's rule follows: a Silver table is trusted when the `run_id` its rows carry is a `silver_build` run that `succeeded`. After a failed run the published tables still carry the last good run, so they stay readable; the rule also covers a task that dies between the two copies, which leaves the Silver quarantine from a `running` run and the Silver clean table from the last good one. A task that dies after both copies but before the `succeeded` row (only the clean table's owner statement and that row come between) leaves both tables carrying a `running` run, so Gold has no trusted Silver for the source until the next run passes and republishes. That is the safe side: Gold never reads a build whose run was not confirmed.

## Compute

Free Edition's serverless capacity is shared; in the Bronze runs most time was spent waiting for it, and each small control-table statement took 3 to 13 seconds.

- **Two SQL tasks on the warehouse.** The Bronze gate before them has already started it, so Silver adds two tasks' statements, not a new start-up. No notebook.
- **No skip.** A file cannot decide to skip itself, and the rebuild is cheap (about a second for 180,500 rows locally), so every run rebuilds (D-025). The saving given up is that work, not a warehouse start.
- **A build** is about 17 statements: the run stamp (6), the run row, the schema and its owner, the classification view, two `CREATE OR REPLACE`, two comments, and two owner statements, all on the candidate tables. Each candidate's comment says it is unpublished and names the Silver table to read instead; the published copies carry no comment. **The gate** is 10: its start time (2), the checks, the `failed` run row, the stop, two copies and two owner statements to publish, and the `succeeded` run row. Locally: about 1.1 s and 0.7 s.
- **Parallel source lanes.** Tasks within this source stay ordered, while unrelated sources may run at the same time. There is no schedule, and `max_concurrent_runs: 1` prevents two whole job runs from overlapping.

On Databricks `dev` the build took 30 to 56 s and the gate 44 to 50 s before it published, 47 to 63 s since, with no queue or setup time ([evidence](../../evidence/pipeline-runs/2026-10-09-deped-enrollment-silver.md), [with publishing](../../evidence/pipeline-runs/2026-10-09-silver-publish-after-gate.md)): the warehouse's time per statement, not the 180,500 rows.

## Running locally

From the repository root, with the virtual environment active, run the whole job on DuckDB in a deterministic dependency order equivalent to the Databricks DAG:

```bash
RAW_DATA_DIR=~/Projects/reached-hq/raw-data python -m src.job.local_run
```

The tables go to `local_state/edu_access.duckdb` (`--db <path>` for another file). Bronze loads only new files; Silver rebuilds every time. Exit code 0 when every task succeeded, 1 otherwise, with the failed tasks named.

## Changing a rule or approving a label

1. Edit `config/mappings/deped_enrollment.json`: a new label goes under its column with the standard value and the evidence (how many of the same schools carried the old label). A new column in a new schema version must be classified there too, or the generator stops.
2. Regenerate the three generated files (a test fails until you do):

   On Windows, set `PYTHONUTF8=1` first (in PowerShell, `$env:PYTHONUTF8 = "1"`). Without it Python writes the redirected file in cp1252, the `Ñ` repair becomes an invalid byte, and the build fails with `'utf-8' codec can't decode byte 0xd1`.

   ```bash
   python -m src.silver.cli sql --source deped_enrollment > etl/03_silver/01_clean_deped_enrollment.sql
   ```

   ```bash
   python -m src.silver.cli gate --source deped_enrollment > etl/03_silver/90_validate_deped_enrollment_clean.sql
   ```

   ```bash
   python -m src.silver.cli dictionary --source deped_enrollment > docs/data/silver/deped-enrollment-clean.md
   ```

3. Run the tests and the job locally on the real data; compare the `rule_*` counts with the table above. The source owner approves the pull request. The next job run builds with the new rules.

## Running on Databricks

**Run on `dev` on 2026-10-09** at `be5ee73`, with Silver publishing only after its gate passes ([evidence](../../evidence/pipeline-runs/2026-10-09-silver-publish-after-gate.md#re-run-at-the-head-commit-be5ee73)); first at `7d93d8e` ([evidence](../../evidence/pipeline-runs/2026-10-09-deped-enrollment-silver.md)). The deliberate confirmation run (D-008), repeated after any change to the Silver SQL, after the branch is pushed:

1. From a clean checkout of the pushed commit, announce the run, detach notebooks, leave the SQL warehouse stopped (the job starts it).
2. `databricks bundle validate --target dev --profile reached-hq`, then `databricks bundle deploy --target dev --profile reached-hq`; confirm in `databricks bundle summary` that `git_commit` and `code_revision` both equal `git rev-parse HEAD`.
3. `databricks bundle run edu_access_pipeline --target dev --profile reached-hq` twice. In both runs the Bronze loads skip (already loaded), the gates pass, and Silver rebuilds.
4. Check with the queries below, then record the evidence in `evidence/pipeline-runs/<date>-deped-enrollment-silver.md` in the layout of the Bronze evidence, with per-task timings (job start, task start and end, queue and setup time) so waiting for compute is told apart from work.

What only Databricks can show, all confirmed by the 2026-10-09 runs: Spark's behavior for the shared SQL (`regexp_like`, `translate`, `chr(160)`, session variables, the CTE inside `INSERT`, `MERGE` with variables), job parameters reaching SQL file tasks, `CREATE OR REPLACE TABLE` and ownership on existing Unity Catalog tables, and the real cost of the warehouse tasks.

All checks in one query, each marked `OK` or `CHECK`, for the six approved deliveries after two runs. Replace the commit with the one that ran:

```sql
WITH c AS (SELECT * FROM edu_access.`03-silver`.deped_enrollment_clean),
     q AS (SELECT * FROM edu_access.`03-silver`.deped_enrollment_quarantine),
     pr AS (SELECT * FROM edu_access.`01-control`.pipeline_runs WHERE pipeline_name = 'silver_build' AND source_id = 'deped_enrollment'),
     last_run AS (SELECT MAX_BY(run_id, started_at_utc) AS run_id FROM pr),
     d AS (SELECT * FROM edu_access.`01-control`.data_quality_results
           WHERE layer = 'silver' AND source_id = 'deped_enrollment' AND run_id = (SELECT run_id FROM last_run)),
checks AS (
  SELECT 'clean rows SY 2020-21' AS check_name, '60957' AS expected, CAST(COUNT_IF(school_year = '2020-21') AS STRING) AS actual FROM c
  UNION ALL SELECT 'clean rows SY 2021-22', '60429', CAST(COUNT_IF(school_year = '2021-22') AS STRING) FROM c
  UNION ALL SELECT 'clean rows SY 2022-23', '60136', CAST(COUNT_IF(school_year = '2022-23') AS STRING) FROM c
  UNION ALL SELECT 'clean rows SY 2023-24', '60167', CAST(COUNT_IF(school_year = '2023-24') AS STRING) FROM c
  UNION ALL SELECT 'clean rows SY 2024-25', '60129', CAST(COUNT_IF(school_year = '2024-25') AS STRING) FROM c
  UNION ALL SELECT 'clean rows SY 2025-26', '60204', CAST(COUNT_IF(school_year = '2025-26') AS STRING) FROM c
  UNION ALL SELECT 'quarantined rows', '1', CAST(COUNT(*) AS STRING) FROM q
  UNION ALL SELECT 'quarantined school_id, SY 2022-23', '1404066', MAX(CASE WHEN school_year = '2022-23' THEN school_id END) FROM q
  UNION ALL SELECT 'repeated keys', '0', CAST(COUNT(*) - COUNT(DISTINCT school_id || school_year) AS STRING) FROM c
  UNION ALL SELECT 'learners SY 2020-21 / 2021-22 / 2022-23 / 2023-24 / 2024-25 / 2025-26', '26227022 / 27560661 / 27794274 / 27081292 / 26400182 / 25935863',
    MAX(CASE WHEN batch_id LIKE '%2020-21%' THEN actual END) || ' / ' || MAX(CASE WHEN batch_id LIKE '%2021-22%' THEN actual END) || ' / ' || MAX(CASE WHEN batch_id LIKE '%2022-23%' THEN actual END)
    || ' / ' || MAX(CASE WHEN batch_id LIKE '%2023-24%' THEN actual END) || ' / ' || MAX(CASE WHEN batch_id LIKE '%2024-25%' THEN actual END)
    || ' / ' || MAX(CASE WHEN batch_id LIKE '%2025-26%' THEN actual END) FROM d WHERE check_name = 'learners_reconcile'
  UNION ALL SELECT 'blank SHS counts kept NULL, SY 2025-26', '47352', CAST(COUNT_IF(school_year = '2025-26' AND g11_stem_male IS NULL) AS STRING) FROM c
  UNION ALL SELECT 'absent v2 column NULL in v1 rows', '301818', CAST(COUNT_IF(schema_version = 'v1' AND g11_sshs_acad_male IS NULL) AS STRING) FROM c
  UNION ALL SELECT 'standard labels, school_management, SY 2025-26', '9', CAST(COUNT(DISTINCT CASE WHEN school_year = '2025-26' THEN school_management END) AS STRING) FROM c
  UNION ALL SELECT 'Local Government kept, SY 2020-21 / 2021-22 / 2022-23', '154 / 155 / 106',
    CAST(COUNT_IF(school_year = '2020-21' AND school_management = 'Local Government') AS STRING) || ' / '
    || CAST(COUNT_IF(school_year = '2021-22' AND school_management = 'Local Government') AS STRING) || ' / '
    || CAST(COUNT_IF(school_year = '2022-23' AND school_management = 'Local Government') AS STRING) FROM c
  UNION ALL SELECT 'mangled Ã‘ left', '0', CAST(COUNT_IF(barangay LIKE '%Ã‘%' OR street_address LIKE '%Ã‘%') AS STRING) FROM c
  UNION ALL SELECT 'overseas flagged', '201', CAST(COUNT_IF(is_overseas) AS STRING) FROM c
  UNION ALL SELECT 'no counts published, SY 2025-26', '46', CAST(COUNT_IF(enrollment_status = 'no_counts') AS STRING) FROM c
  UNION ALL SELECT 'checks in the last run', '227', CAST(COUNT(*) AS STRING) FROM d
  UNION ALL SELECT 'checks in the last run not PASS (the two SY 2022-23 quarantine WARNs)', '2', CAST(COUNT_IF(status <> 'PASS') AS STRING) FROM d
  UNION ALL SELECT 'rows from the last run', '362022', CAST(COUNT_IF(run_id = (SELECT run_id FROM last_run)) AS STRING) FROM c
  UNION ALL SELECT 'rows from another commit', '0', CAST(COUNT_IF(code_revision <> '<commit that ran>') AS STRING) FROM c
  UNION ALL SELECT 'last silver run', 'succeeded', MAX(status) FROM pr WHERE run_id = (SELECT run_id FROM last_run)
  UNION ALL SELECT 'silver runs succeeded at this commit', '2', CAST(COUNT_IF(status = 'succeeded' AND code_revision = '<commit that ran>') AS STRING) FROM pr
  UNION ALL SELECT 'published rows from a succeeded run', '362022', CAST(COUNT(*) AS STRING)
    FROM c JOIN pr ON pr.run_id = c.run_id AND pr.status = 'succeeded'
  UNION ALL SELECT 'candidate rows not published', '0', CAST(COUNT(*) AS STRING) FROM (
    SELECT * FROM edu_access.`03-silver`.deped_enrollment_clean_candidate EXCEPT ALL SELECT * FROM c)
)
SELECT check_name, expected, actual, CASE WHEN expected = actual THEN 'OK' ELSE 'CHECK' END AS result FROM checks;
```

After a run that failed its gate, four rows show `CHECK` by design, because they describe that latest run: `checks in the last run not PASS` (its FAIL results), `rows from the last run` (0: nothing of it was published), `last silver run` (`failed`), and `candidate rows not published` (the failed build waits in the candidate table). `published rows from a succeeded run` stays OK: the Silver tables still hold the last good build. To check that build instead, read `data_quality_results` for its `run_id`.

Column types, in Unity Catalog only (expect `INT` 66):

```sql
SELECT data_type, COUNT(*) AS columns
FROM edu_access.information_schema.columns
WHERE table_schema = '03-silver' AND table_name = 'deped_enrollment_clean' AND column_name LIKE '%male'
GROUP BY data_type;
```

## Handoff to Integration and Gold

What Silver guarantees, per run that ended `succeeded`:

- One row per (`school_id`, `school_year`) for the current delivery of every school year; Bronze rows = clean + quarantined; learner totals equal Bronze's.
- Counts are INT or NULL; NULL is never 0. Booleans are TRUE, FALSE, or NULL. Every category value is in the reviewed standard set.
- Every row names its Bronze row, delivery, schema version, Silver run, timestamp, and commit.

What Gold must respect:

- Read a Silver table only when the `run_id` its rows carry is a `silver_build` run that `succeeded` in `pipeline_runs`. A later failed run does not change what is published, so the last good build stays readable. Never read the `_candidate` tables.
- `is_overseas`: exclude from any geographic analysis; their place names are placeholders in SY 2025-26.
- Suspected over-reporting (profile S-4): schools 410978, 410977, and 410472 report Grade 11 strands that grow 5 to 23 times in a year, to the largest counts in the data. Silver keeps them as published; decide whether strand- and school-level results include them.
- `enrollment_status`: `all_zero` and `no_counts` schools are kept in Silver; decide per measure whether they count as schools (S-1).
- `barangay_possibly_truncated` and NULL `barangay`: barangay-level results for these schools are uncertain.
- NULL counts: "not published"; in SY 2025-26 usually "level not offered". Use `schema_version` to tell a column the year lacks from a blank, and NULL-safe filters (`IS NOT TRUE`) on nullable booleans.
- Region is as published: NIR exists from SY 2024-25, and 192 Cotabato City and Special Geographic Area schools are Region XII in SY 2020-21 and BARMM from SY 2021-22 (O-10); compare regions across years only through PSGC (D-012).
- `school_management = 'Local Government'` exists only in SY 2020-21 to 2022-23 (154, 155, and 106 public schools). Filter public schools on `sector`, not on `school_management = 'DepEd'`, or those years lose them.
- School IDs change between years (O-12): a missing ID is not a closed school. 2,517 SY 2020-21 IDs (1,711 private), 1,481 SY 2021-22 IDs (963 private), and 698 SY 2022-23 IDs (393 private) in Silver clean are not in SY 2023-24, so they are not in the EMISD crosswalk either. Profile O-12 gives 699 (394 private) for SY 2022-23 because it also counts the quarantined `1404066`.
- SY 2022-23's `1404066` is in the quarantine, not the clean table: SY 2022-23 Silver has 8 fewer Kindergarten learners than the file (O-1, O-3).
- Unpivot grade, sex, and strand there (D-021), and decide how `g11_sshs_*` relates to the older strand columns.

**SY 2020-21 to 2022-23 downstream.** All three years take the path described here for SY 2020-21; SY 2021-22 and 2022-23 differ only in their own IDs absent from SY 2023-24, which need the same name match. SY 2020-21 Silver feeds the DepEd school-to-PSGC Integration (#91), then `fact_school_enrollment` (#46), then AP1 to AP4 (#143); AP4 pairs it with the 2020 Census (D-042). The Integration places a school by the EMISD crosswalk (`deped_enrollment_psgc`, D-049) when its `school_id` is there, and by reviewed place-name matching otherwise; the crosswalk is keyed on SY 2023-24 IDs, so the 2,517 SY 2020-21 IDs absent from SY 2023-24 use the name match. It retains `is_overseas` schools as `excluded` with no PSGC code instead of deleting them. Silver deliberately leaves these SY 2020-21 conditions as published, for Integration or Analytics to disclose: the 192 Region XII schools that are BARMM from SY 2021-22 (191 of them still in SY 2023-24; `405811` is not), the 2,517 IDs absent from SY 2023-24, the 439 zero-enrollment schools, historical municipality, province, and barangay names, and the 33 PSO rows.

Integration implements this in `deped_school_psgc_map`; see [Integration operations](integration.md). It matches the Silver names to the master PSGC quarter, including the 40-character barangay-prefix rule (O-18), and records every unresolved row.

## PSA Poverty Stat

`psa_poverty_stat` uses the design above (two SQL tasks, candidates, publish after the gate, `pipeline_runs`; D-020, D-025) with its own shape and rules (D-034). Its SQL and dictionary are generated by `src/silver/psa_poverty_stat.py` from the Bronze contract and the [Silver rules](../../config/mappings/psa_poverty_stat.json); columns: [data dictionary](../data/silver/psa-poverty-stat-clean.md).

**Status:** implemented and tested locally on made-up workbooks (`tests/test_silver_psa.py`), and **run locally on the real workbook** on 2026-10-09 at `e799be3`: 1,612 clean rows per estimate year, 0 quarantined, every value equal to its Bronze cell, 115 gate results (0 FAIL, 9 WARN), and identical content on a second run. **Run twice on Databricks `dev`** on 2026-10-09 at `6cc39ca` (job runs `1080268183594725` and `846140731363521`, both succeeded): every check of the query below OK ([evidence](../../evidence/reconciliation/2026-10-09-psa-poverty-stat-bronze-to-silver.md)).

### The flow (PSA)

```
05_create_psa_poverty_stat_raw      SQL: Bronze DDL
bronze_psa_poverty_stat             Python: check and load the workbook (skip when already loaded)
90_validate_psa_poverty_stat_raw    SQL: the Bronze gate
   │  only if it passed
   ▼
05_clean_psa_poverty_stat           SQL: run stamp; pipeline_runs 'running'; from current_batches only:
   │                                     unit rows → one candidate per unit and estimate year the delivery covers
   │                                       psa_poverty_stat_clean_candidate       one row per unit per estimate year
   │                                       psa_poverty_stat_quarantine_candidate  candidates that cannot be trusted
   │  only if it succeeded
   ▼
90_validate_psa_poverty_stat_clean  SQL: 115 results for the current workbook (6 whole build, 7 per batch,
                                         34 per batch and estimate year x 3); any FAIL: 'failed', stop,
                                         nothing published; else publish quarantine, then clean, then 'succeeded'
```

The lane does not wait for any other source; `90_validate_control` is the fan-in (D-051).

### Grain and shape (PSA)

One Bronze `unit` row holds all three estimate years side by side. Silver unpivots it: **one row per unit (city or municipality row) per estimate year the delivery covers**, key (`psgc_id`, `estimate_year`), with that year's poverty incidence, CV, SE and both 90% limits together in the same row. This differs from DepEd's wide Silver (D-021) on purpose: PSA's five measures per year are one estimate and its precision, not five counts, and each year's estimate is what a planner reads (D-034). The years come from the contract's columns; a delivery's `estimate_years_covered` says which of them it covers, so an absent year gives no row at all rather than a row of NULLs.

Title, header, region banner, blank and footer rows stay in Bronze. For the current workbook: 1,641 Bronze rows = 1,612 `unit` + 29 structural (1 title, 4 header, 18 region banner, 6 footer), so 1,612 candidates per estimate year and 4,836 in all.

### Cleaning rules (PSA)

| Rule | What it does | Why | Current workbook (independent check, see evidence) |
|---|---|---|---|
| Current batches only | Reads Bronze rows whose `batch_id` is in `current_batches`, `source_row_kind = 'unit'` | D-015, D-018 | 1,612 units |
| Unpivot | One candidate per unit and covered estimate year | D-034 | 1,612 per year |
| Region banner context | The nearest banner above the unit in Excel row order, within the same batch and sheet; never across deliveries; never from the ID prefix (Negros Island Region holds 06 and 07) | O-3 | 0 units without a banner |
| ID padded, Correspondence Code | `psgc_id` = the published `PSGC ID` left-padded to 6 digits (the unpadded value stays in Bronze); `correspondence_code` = `psgc_id` + `000` (9 digits, the same name and format as PSGC's own `correspondence_code`, the key Integration joins on; not the 10-digit PSGC code) | O-2, X-1 | 1,073 IDs padded per year |
| Names as published | `municipality`: whitespace normalized (tabs, no-break spaces, runs of spaces), blank → NULL; former names in parentheses and Bumbaran unchanged; no PSGC matching. The sparse province labels of unit rows (1,527 of 1,612 blank, `(Continued)`, one code shared by two Maguindanao provinces) are not carried into Silver: they stay in Bronze, and Integration takes the official province from PSGC | O-3, O-10 | |
| Measures typed | Plain or scientific-notation numbers → DOUBLE, every stored digit, no rounding, no trimming; blank stays NULL, never 0 | O-6 | |
| No estimate | All five measures blank → NULL with `estimate_status = 'no_estimate'`; kept, not quarantined | O-5 | 1 per year (Kalayaan, Excel row 641) |
| Partial estimate | Some measures blank → `partial_estimate`, kept, WARN | | 0 |
| Flags, never corrections | `cv_over_20` (CV > 20), `se_cv_inconsistent` (\|SE − incidence × CV / 100\| > 0.05), `lower_limit_not_positive` (lower ≤ 0); never NULL; SE not recomputed, limits not clipped or replaced | O-7, O-8, O-9 | 171 / 84 / 156; 6 / 133 / 1; 1 / 1 / 1 (2018 / 2021 / 2023) |
| No synthetic rows | Places absent from the workbook (33 HUCs, Isabela, Cotabato, Pateros, 8 SGA municipalities) get no row; Integration lists them against PSGC | X-1 | |

### Quarantine (PSA)

A candidate is quarantined, with every reason that applies, when its `PSGC ID` is blank (`psgc_id_blank`) or not 5 or 6 digits (`psgc_id_malformed`), when its padded ID appears more than once in the estimate year among current batches (`psgc_id_duplicated`: every copy), when a measure is not blank and not a number (`measure_uncastable`), or when its values are impossible: incidence outside 0 to 100, a negative CV or SE, a lower limit above the upper limit, or an estimate outside its own interval. Quarantine is per estimate year: a bad 2021 cell sets aside the 2021 row only. Any quarantined row is WARN; more than 1% of a batch's units in one estimate year is FAIL (as D-024). The current workbook quarantines nothing.

### The gate (PSA)

Per estimate year, the checks write `<check>_<year>` (for example `rows_reconcile_2021`); `data_quality_results` has no year column. FAIL checks: `current_batches_present`, `estimate_years_known` (a covered year the generated SQL does not know: regenerate after a new schema version), `lineage_complete`, `rows_resolve_to_current_bronze_units`, `rows_built_by_this_run`, `one_timestamp_per_run`; per batch `bronze_rows_accounted` (every Bronze row is a unit or a known structural kind); per year `rows_reconcile` (units = clean + quarantined), `psgc_id_unique`, `psgc_id_valid` (padding against the Bronze ID, Correspondence Code), `estimate_year_covered`, `<measure>_matches_bronze` for each of the five measures (the Silver value equals CAST of its own Bronze cell for that year, exactly), `missing_measures_stay_null`, `estimate_status_valid`, `poverty_incidence_within_bounds`, `cv_non_negative`, `se_non_negative`, `ci_contains_estimate`, `flags_consistent`, `region_banner_assigned`, and `quarantine_rate`. WARN checks: each quarantine reason, `flag_cv_over_20`, `flag_se_cv_inconsistent`, `flag_lower_limit_not_positive`, `flag_partial_estimate`. Records (always PASS): `rows_kind_<kind>`, `rule_structural_rows_not_estimates`, `rule_no_estimate`, `rule_psgc_id_padded`, `rule_text_whitespace_normalized`, `rule_blank_measures_to_null`. Poverty percentages are never summed or averaged as a check: they are not counts. `psa.gate_checks()` lists them all, and a test checks the SQL writes exactly those.

On the current workbook the expected gate result is 0 FAIL and 9 WARN (the three statistical flags in each of the three years); the rest PASS.

### Running locally (PSA)

The whole job, as for every source: `python -m src.job.local_run`. To run only the PSA lane twice on a fresh database and print every number the evidence needs (Bronze rows by kind, candidates, clean and quarantined per year, missing estimates, flags, gate results, lineage, task timings, and a SHA-256 of the business content after each run):

```bash
python analysis/verification/psa_poverty_stat_silver.py
```

It needs `RAW_DATA_DIR` with the approved workbook under `psa/` (the loader verifies its SHA-256) and writes only to `local_state/` (git-ignored).

Changing a rule: edit `config/mappings/psa_poverty_stat.json` (a new publisher column must get a rule there, or the generator stops), then regenerate (a test fails until you do):

```bash
python -m src.silver.cli sql --source psa_poverty_stat > etl/03_silver/05_clean_psa_poverty_stat.sql
```

```bash
python -m src.silver.cli gate --source psa_poverty_stat > etl/03_silver/90_validate_psa_poverty_stat_clean.sql
```

```bash
python -m src.silver.cli dictionary --source psa_poverty_stat > docs/data/silver/psa-poverty-stat-clean.md
```

A new schema version with another estimate year (D-018) also needs these three commands: until then the gate fails `estimate_years_known` and the last good build stays published.

### Running on Databricks (PSA)

**Run on `dev` on 2026-10-09 at `6cc39ca`**: two runs, both succeeded, every check below OK ([evidence](../../evidence/reconciliation/2026-10-09-psa-poverty-stat-bronze-to-silver.md)). A new confirmation follows [Running on Databricks](#running-on-databricks): a clean, pushed checkout of the exact commit; announce the run; `bundle validate`, `deploy`, `summary` (confirm `git_commit` and `code_revision`); run `edu_access_pipeline` twice. Expected: both runs skip the already-loaded workbook in Bronze, and PSA Silver rebuilds on both. Then, replacing the commit:

```sql
WITH c AS (SELECT * FROM edu_access.`03-silver`.psa_poverty_stat_clean),
     q AS (SELECT * FROM edu_access.`03-silver`.psa_poverty_stat_quarantine),
     pr AS (SELECT * FROM edu_access.`01-control`.pipeline_runs WHERE pipeline_name = 'silver_build' AND source_id = 'psa_poverty_stat'),
     last_run AS (SELECT MAX_BY(run_id, started_at_utc) AS run_id FROM pr),
     d AS (SELECT * FROM edu_access.`01-control`.data_quality_results
           WHERE layer = 'silver' AND source_id = 'psa_poverty_stat' AND run_id = (SELECT run_id FROM last_run)),
checks AS (
  SELECT 'clean rows 2018 / 2021 / 2023' AS check_name, '1612 / 1612 / 1612' AS expected,
         COUNT_IF(estimate_year = 2018) || ' / ' || COUNT_IF(estimate_year = 2021) || ' / ' || COUNT_IF(estimate_year = 2023) AS actual FROM c
  UNION ALL SELECT 'quarantined rows', '0', CAST(COUNT(*) AS STRING) FROM q
  UNION ALL SELECT 'repeated keys', '0', CAST(COUNT(*) - COUNT(DISTINCT psgc_id, estimate_year) AS STRING) FROM c
  UNION ALL SELECT 'no_estimate rows (Kalayaan, Excel row 641)', '3', CAST(COUNT_IF(estimate_status = 'no_estimate' AND source_row_number = 641 AND poverty_incidence IS NULL) AS STRING) FROM c
  UNION ALL SELECT 'cv_over_20 2018 / 2021 / 2023', '171 / 84 / 156',
         COUNT_IF(cv_over_20 AND estimate_year = 2018) || ' / ' || COUNT_IF(cv_over_20 AND estimate_year = 2021) || ' / ' || COUNT_IF(cv_over_20 AND estimate_year = 2023) FROM c
  UNION ALL SELECT 'se_cv_inconsistent 2018 / 2021 / 2023', '6 / 133 / 1',
         COUNT_IF(se_cv_inconsistent AND estimate_year = 2018) || ' / ' || COUNT_IF(se_cv_inconsistent AND estimate_year = 2021) || ' / ' || COUNT_IF(se_cv_inconsistent AND estimate_year = 2023) FROM c
  UNION ALL SELECT 'lower_limit_not_positive', '3', CAST(COUNT_IF(lower_limit_not_positive) AS STRING) FROM c
  UNION ALL SELECT 'IDs padded from 5 digits', '3219', CAST(SUM(CAST(actual AS INT)) AS STRING) FROM d WHERE check_name LIKE 'rule_psgc_id_padded%'
  UNION ALL SELECT 'units without a region banner', '0', CAST(COUNT_IF(region IS NULL) AS STRING) FROM c
  UNION ALL SELECT 'measure mismatches with Bronze', '0', CAST(SUM(CAST(actual AS INT)) AS STRING) FROM d WHERE check_name LIKE '%matches_bronze%'
  UNION ALL SELECT 'checks in the last run', '115', CAST(COUNT(*) AS STRING) FROM d
  UNION ALL SELECT 'FAIL / WARN in the last run', '0 / 9', COUNT_IF(status = 'FAIL') || ' / ' || COUNT_IF(status = 'WARN') FROM d
  UNION ALL SELECT 'rows from the last run', '4836', CAST(COUNT_IF(run_id = (SELECT run_id FROM last_run)) AS STRING) FROM c
  UNION ALL SELECT 'rows from another commit', '0', CAST(COUNT_IF(code_revision <> '<commit that ran>') AS STRING) FROM c
  UNION ALL SELECT 'last silver run', 'succeeded', MAX(status) FROM pr WHERE run_id = (SELECT run_id FROM last_run)
  UNION ALL SELECT 'silver runs succeeded at this commit', '2', CAST(COUNT_IF(status = 'succeeded' AND code_revision = '<commit that ran>') AS STRING) FROM pr
  UNION ALL SELECT 'candidate rows not published', '0', CAST(COUNT(*) AS STRING) FROM (
    SELECT * FROM edu_access.`03-silver`.psa_poverty_stat_clean_candidate EXCEPT ALL SELECT * FROM c)
)
SELECT check_name, expected, actual, CASE WHEN expected = actual THEN 'OK' ELSE 'CHECK' END AS result FROM checks;
```

Business content of the two builds (run once after each run; the two hashes must be equal):

```sql
SELECT sha2(concat_ws('\n', sort_array(collect_list(concat_ws('|', CAST(estimate_year AS STRING), psgc_id, source_sha256,
         CAST(source_row_number AS STRING), CAST(poverty_incidence AS STRING), CAST(coefficient_of_variation AS STRING),
         CAST(standard_error AS STRING), CAST(ci90_lower_limit AS STRING), CAST(ci90_upper_limit AS STRING),
         estimate_status, CAST(cv_over_20 AS STRING), CAST(se_cv_inconsistent AS STRING),
         CAST(lower_limit_not_positive AS STRING), region, municipality)))), 256) AS content_sha256
FROM edu_access.`03-silver`.psa_poverty_stat_clean;
```

What only Databricks can show for PSA: Spark's `split`/`array_contains`, `TRY_CAST` to DOUBLE of scientific notation, `lpad`, the window over banner rows, `VALUES` with column aliases and `IS NOT DISTINCT FROM` in the gate, and the warehouse time of two more tasks.

### Evidence (PSA)

- Local, made-up workbooks: `tests/test_silver_psa.py` (run with the whole suite).
- Local, real workbook, two runs at `e799be3`: [evidence/reconciliation/2026-10-09-psa-poverty-stat-bronze-to-silver.md](../../evidence/reconciliation/2026-10-09-psa-poverty-stat-bronze-to-silver.md).
- Databricks `dev`, two runs at `6cc39ca` (`1080268183594725`, `846140731363521`): the same evidence file.

### Handoff to Integration and Gold (PSA)

- Read only a `succeeded` run's rows (as above). One row per (`psgc_id`, `estimate_year`); 1,612 per year for the current workbook.
- **Poverty incidence is the percentage of persons below the poverty threshold**, not families, students, or a count of people. Never sum it; aggregate only with population weights from another source, and say so.
- `no_estimate` (Kalayaan) is missing, not zero poverty. Places not in the workbook have no row: list them against PSGC as `not_in_source`, never as zero.
- Carry `cv_over_20`, the interval, and `se_cv_inconsistent` to every display or ranking; for the 2021 CALABARZON rows prefer CV and the interval to SE (profile O-8). A negative lower limit is a statistical warning, not a negative count.
- Region and province: `region` is the published banner label; Silver has no province column. Canonical region and province come from matching `correspondence_code` to PSGC's `correspondence_code` in Integration (`02_map_psa_poverty_psgc`), never from the labels or the ID prefix alone.
- Cross-year comparability (S-3) is unverified: a 2018 → 2023 trend needs a team decision first.

## PSA PSGC

`psa_psgc` uses the design above (two SQL tasks, candidates, publish after the gate, `pipeline_runs`; D-020, D-025) with its own rules (D-035). Its SQL and dictionary are generated by `src/silver/psa_psgc.py` from the Bronze contract and the [Silver rules](../../config/mappings/psa_psgc.json); columns: [data dictionary](../data/silver/psa-psgc-clean.md).

**Status:** implemented and tested locally on made-up workbooks (`tests/test_silver_psgc.py`), and run locally on the real 2Q 2026 workbook on 2026-10-10 at `9d2ee01`: 43,768 clean rows, 0 quarantined, 50 gate results, all PASS, and identical content on a second build. **Run on Databricks `dev`** on 2026-10-11: twice at `a6d34a9` (job runs `913496403202511`, `677939887807442`) and, after review added two checks, twice at `a4d21b0` (`375940486094107`, `918157622982175`), all succeeded: every check of the query below OK, 52 checks with 0 FAIL ([evidence](../../evidence/reconciliation/2026-10-10-psa-psgc-bronze-to-silver.md)).

### The flow (PSGC)

```
04_create_psa_psgc_raw        SQL: Bronze DDL
bronze_psa_psgc               Python: check and load the workbook (skip when already loaded)
90_validate_psa_psgc_raw      SQL: the Bronze gate
   │  only if it passed
   ▼
04_clean_psa_psgc             SQL: run stamp; pipeline_runs 'running'; from current_batches only:
   │                               every row → psa_psgc_clean_candidate       one row per code per quarter
   │                                           psa_psgc_quarantine_candidate  rows that cannot be trusted
   │  only if it succeeded
   ▼
90_validate_psa_psgc_clean    SQL: 52 results for one current quarter (6 whole build, 46 per batch); any FAIL:
                                   'failed', stop, nothing published; else publish quarantine, then clean,
                                   then 'succeeded'
```

The lane does not wait for any other source; `90_validate_control` is the fan-in (D-051). The mapping tasks of Integration that need PSGC (`01_map_deped_school_psgc`, `02_map_psa_poverty_psgc`, `03_map_hdx_adm3_psgc`, `05_map_psa_school_age_population_psgc`) start from this lane's gate, together with the gate of the other source each one reads.

### Grain and shape (PSGC)

The source's grain (D-021): **one row per PSGC code per publication quarter**, key (`publication_period`, `psgc_code`), for the current delivery version of every quarter in `current_batches` (a re-issued quarter replaces its rows once its build passes; D-015). Every quarter is kept. `is_master_reference` marks the quarter named by `master_reference_period` in the Bronze contract (2026-Q2, D-012): Integration matches against those rows, and other quarters are for comparison. Silver adds three parent codes derived from the code (O-10) and changes nothing else about the shape. For 2Q 2026: 43,768 Bronze rows, 43,768 clean.

### Cleaning rules (PSGC)

Every rule, label and count is in [config/mappings/psa_psgc.json](../../config/mappings/psa_psgc.json), with its evidence.

| Rule | What it does | Why | 2Q 2026 |
|---|---|---|---|
| Current batches only | Reads Bronze rows whose `batch_id` is in `current_batches` | D-015 | 43,768 rows, one quarter |
| Codes as published | `psgc_code` exactly as published (leading zeros kept, never padded or trimmed); `correspondence_code` too, blank → NULL, never derived | O-1, O-3, D-030 | 29,620 codes start with 0; 50 NULL correspondence codes |
| Text | `name`, `old_names` and the renamed `population_footnote` (column J): tabs, no-break spaces and runs of spaces become one space, trimmed; blank → NULL; spelling unchanged | O-9, O-11, O-6, D-023 | 2,855 trailing spaces removed |
| Population | `population` INT when 1 to 9 digits; `#N/A` → NULL with `population_null_reason = 'publisher_na'`, a blank cell → NULL with `blank`; 0 stays 0 (`population_is_zero`) | O-4, D-033 | 1 NULL (City of Isabela container), 12 zeros |
| Income class | Split into `income_class` and `income_class_retained_after_downgrade` (the star); `-` → NULL with `income_class_null_reason = 'not_classified'` | O-7 | 6 starred, 8 `-` |
| Categories | `geographic_level`, `city_class`, `urban_rural`, `status` kept as published, each through its list of accepted labels (D-022); `urban_rural` `-` → NULL with `urban_rural_null_reason = 'unknown'`, never rural | O-2, O-8, O-12 | 38 `-` |
| Blank level | Stays NULL with `level_blank`; no level is assigned (open decision) | O-2 | 2 rows |
| Parent codes | `region_code` (first 2 digits + 8 zeros); `province_code` (first 5 + 5 zeros, when that code is a province row or a blank-level container of the same quarter); `city_municipality_code` (barangays: first 7 + 3 zeros) | O-10 | Barangays under a municipality 34,007, a city 7,106, a sub-municipality 897 |

### Quarantine (PSGC)

A row is quarantined, with every reason that applies, when its code is blank (`psgc_code_blank`) or not ten digits as published (`psgc_code_malformed`), when its code appears more than once in the quarter (`psgc_code_duplicated`: every copy), when a filled correspondence code is not nine digits (`correspondence_code_malformed`), or when its population is neither digits nor a known marker (`population_uncastable`). Any quarantined row is WARN; more than 1% of a batch is FAIL (D-024). **A duplicated code also FAILs the gate on its own** (`psgc_code_duplicates_absent`), however few: PSGC is what Integration joins to, and a repeated code would multiply joined rows (D-019, D-035). The 2Q 2026 delivery quarantines nothing.

### The gate (PSGC)

FAIL checks: `current_batches_present`, `master_reference_current` (exactly one current batch of the master quarter), `lineage_complete`, `rows_resolve_to_current_bronze`, `rows_built_by_this_run`, `one_timestamp_per_run`; per batch `rows_reconcile` (Bronze rows = clean + quarantined), `psgc_code_unique`, `psgc_code_valid`, `psgc_code_duplicates_absent`, `<column>_matches_bronze` for each of the 18 Silver value columns (the value equals the rule applied to its own Bronze cell), `labels_mapped_<column>` for the five category columns (an unlisted label fails, D-022), `region_code_exists`, `province_code_exists`, `city_municipality_code_exists` (every derived parent is a published row of the same quarter), `province_code_missing_only_where_listed` (a city or municipality with no `province_code` must be an HUC or listed in the rules file's `no_province_exceptions`, today only Pateros, `1381701000`; anything else means a province row is missing), `flags_consistent`, and `quarantine_rate`. WARN checks: each quarantine reason. Records (always PASS): `flag_level_blank`, `flag_population_is_zero`, `flag_has_population_footnote`, `rule_text_whitespace_normalized`, `rule_population_marker_to_null`, `rule_population_blank_to_null`, `rule_income_class_star_split`, `rule_placeholder_to_null`. The gate never compares with hardcoded 2Q 2026 counts: each quarter is reconciled with its own Bronze rows, and Bronze already compared the workbook with its `National Summary`. `psa_psgc.gate_checks()` lists every check, and a test checks the SQL writes exactly those.

On the 2Q 2026 workbook every result is PASS. Records: 2 blank levels, 12 zeros, 0 blank populations, 19 footnotes, 2,874 rows whose text changed (2,855 names, plus old names and footnotes), 1 marker, 6 starred classes, 46 placeholder cells.

### Running locally (PSGC)

The whole job: `python -m src.job.local_run`. Changing a rule or approving a label: edit `config/mappings/psa_psgc.json` (a new publisher column must get a rule there, or the generator stops), then regenerate from Git Bash, or in PowerShell with `$env:PYTHONUTF8 = "1"` and `Out-File -Encoding ascii` (a test fails until you do):

```bash
python -m src.silver.cli sql --source psa_psgc > etl/03_silver/04_clean_psa_psgc.sql
```

```bash
python -m src.silver.cli gate --source psa_psgc > etl/03_silver/90_validate_psa_psgc_clean.sql
```

```bash
python -m src.silver.cli dictionary --source psa_psgc > docs/data/silver/psa-psgc-clean.md
```

A new PSGC quarter needs no change here once Bronze has approved it: Silver builds it as another quarter and keeps `is_master_reference` on 2026-Q2. A new DOF order or census header is a new Bronze schema version with the same columns, so it needs none either. A new label (a new level, class or status) fails `labels_mapped_<column>` until the owner adds it to the mapping.

### Running on Databricks (PSGC)

**Run on `dev` on 2026-10-11**, last at `a4d21b0`: two runs, both succeeded, every check below OK ([evidence](../../evidence/reconciliation/2026-10-10-psa-psgc-bronze-to-silver.md)). A new confirmation follows [Running on Databricks](#running-on-databricks): a clean, pushed checkout of the exact commit; announce the run; `bundle validate`, `deploy`, `summary` (confirm `git_commit` and `code_revision`); run `edu_access_pipeline` twice. Expected: both runs skip the already-loaded workbook in Bronze, and PSGC Silver rebuilds on both, with every check below OK:

```sql
WITH c AS (SELECT * FROM edu_access.`03-silver`.psa_psgc_clean),
     q AS (SELECT * FROM edu_access.`03-silver`.psa_psgc_quarantine),
     pr AS (SELECT * FROM edu_access.`01-control`.pipeline_runs WHERE pipeline_name = 'silver_build' AND source_id = 'psa_psgc'),
     last_run AS (SELECT MAX_BY(run_id, started_at_utc) AS run_id FROM pr),
     d AS (SELECT * FROM edu_access.`01-control`.data_quality_results
           WHERE layer = 'silver' AND source_id = 'psa_psgc' AND run_id = (SELECT run_id FROM last_run)),
checks AS (
  SELECT 'clean rows 2026-Q2' AS check_name, '43768' AS expected, CAST(COUNT_IF(publication_period = '2026-Q2') AS STRING) AS actual FROM c
  UNION ALL SELECT 'quarantined rows', '0', CAST(COUNT(*) AS STRING) FROM q
  UNION ALL SELECT 'repeated keys', '0', CAST(COUNT(*) - COUNT(DISTINCT publication_period, psgc_code) AS STRING) FROM c
  UNION ALL SELECT 'master reference rows', '43768', CAST(COUNT_IF(is_master_reference) AS STRING) FROM c
  UNION ALL SELECT 'codes starting with 0', '29620', CAST(COUNT_IF(psgc_code LIKE '0%') AS STRING) FROM c
  UNION ALL SELECT 'names ending in a space', '0', CAST(COUNT_IF(name LIKE '% ') AS STRING) FROM c
  UNION ALL SELECT 'population NULL / zero', '1 / 12', COUNT_IF(population IS NULL) || ' / ' || COUNT_IF(population = 0) FROM c
  UNION ALL SELECT 'region population total', '112727776', CAST(SUM(CASE WHEN geographic_level = 'Reg' THEN population END) AS STRING) FROM c
  UNION ALL SELECT 'blank levels', '2', CAST(COUNT_IF(level_blank) AS STRING) FROM c
  UNION ALL SELECT 'urban_rural unknown', '38', CAST(COUNT_IF(urban_rural_null_reason = 'unknown') AS STRING) FROM c
  UNION ALL SELECT 'starred income classes', '6', CAST(COUNT_IF(income_class_retained_after_downgrade) AS STRING) FROM c
  UNION ALL SELECT 'checks in the last run', '52', CAST(COUNT(*) AS STRING) FROM d
  UNION ALL SELECT 'FAIL / WARN in the last run', '0 / 0', COUNT_IF(status = 'FAIL') || ' / ' || COUNT_IF(status = 'WARN') FROM d
  UNION ALL SELECT 'rows from another commit', '0', CAST(COUNT_IF(code_revision <> '<commit that ran>') AS STRING) FROM c
  UNION ALL SELECT 'last silver run', 'succeeded', MAX(status) FROM pr WHERE run_id = (SELECT run_id FROM last_run)
)
SELECT check_name, expected, actual, CASE WHEN expected = actual THEN 'OK' ELSE 'CHECK' END AS result FROM checks;
```

What only Databricks can show for PSGC: Spark's `regexp_like`, `substr`, `split`/`array_contains` and `IS NOT DISTINCT FROM` on the same SQL, `CAST(... AS DATE)` of the publication date, and the warehouse time of two more tasks.

### Handoff to Integration and Gold (PSGC)

- Read only a `succeeded` run's rows, and the master quarter for matching: `WHERE is_master_reference` (D-012). Other quarters are for comparison (the quarter-to-quarter query in the [ingestion runbook](ingestion.md#runbook-psgc)).
- `psgc_code` is unique per quarter, with every parent it names published in the same quarter: join on it as text, never as a number.
- `correspondence_code` may be joined for sources that carry old 9-digit codes, one-to-one and name-checked, with `match_method = correspondence_code` (D-029, D-030). The 50 rows without one match by name only.
- `name` is trimmed, not otherwise standardized. Match DepEd names inside their parent (`city_municipality_code`, `province_code`), never on region, then `old_names`; flag ambiguous matches and never force one (D-012). The 33 HUCs and Pateros have no `province_code`.
- **City of Manila:** its 897 barangays point to its 14 sub-municipalities (`city_municipality_code` `1380601000` to `1380614000`), not to the City of Manila (`1380600000`), and have no `province_code` (Manila is an HUC). A sub-municipality rolls up to Manila by its first 5 digits + `00000`. For DepEd's "CITY OF MANILA" or a city-level total, Integration must include the 14 sub-municipalities, or a Manila total comes out empty or split.
- `region_code` and `province_code` point to the row itself for a region, a province and the two blank-level containers: a group by `province_code` holds the province's own row as well as its units, so exclude `geographic_level = 'Prov'` before summing population.
- Barangay population is `population` (D-033): NULL is not 0 (`population_null_reason`), a 0 is a published 0, and a province's population excludes the cities in its `population_footnote`. The 18 regions sum to 112,727,776, 1,708 below the national total (O-4): never compare a sum of units with the national figure.
- `urban_rural` NULL with `unknown` is not rural; report the urban share with its denominator. `income_class` is NULL below the municipality level.
- The two blank-level rows (`level_blank`) are containers, not provinces: City of Isabela (`0990100000`, population NULL) and the Special Geographic Area (`1999900000`). They have no level until the team decides one.
- Record the PSGC version of every match: `publication_period` and `delivery_version`.

## DepEd facilities

`deped_facilities` uses the design above (two SQL tasks, candidates, publish after the gate, `pipeline_runs`; D-020, D-025) with its own generator, `src/silver/deped_facilities.py`, and [Silver mapping](../../config/mappings/deped_facilities.json) (D-038); columns: [data dictionary](../data/silver/deped-facilities-clean.md).

**Status:** implemented and tested locally on made-up deliveries (`tests/test_silver_facilities.py`), and **run locally on the real SY 2023-24 file** on 2026-10-11 with the whole job ([evidence](../../evidence/reconciliation/2026-10-11-deped-facilities-bronze-to-silver.md)). **Run twice on Databricks `dev`** on 2026-10-11 at `6b2844d` (job runs `1045250185878076` and `700607904560713`, both succeeded): the same rows and checks as locally, all 38 checks PASS, and identical content in both runs ([evidence](../../evidence/pipeline-runs/2026-10-11-deped-facilities-silver.md)). Since then the lane runs in parallel and the enrollment check moved to Integration (D-038): rerun locally on the real file at `02089c9` with the same rows and content, 37 checks all PASS, and **twice on `dev` at `9197926`** (job runs `89482607322789` and `948438707623608`): all 37 checks PASS, the same content as before, and the two lanes' Silver gates running side by side ([evidence](../../evidence/pipeline-runs/2026-10-11-deped-facilities-silver.md#re-run-at-9197926-the-parallel-lane)). The query in that evidence is the facilities check for a new confirmation run, following [Running on Databricks](#running-on-databricks).

### The flow (facilities)

```
bronze_deped_facilities              Python: check and load the delivery
90_validate_deped_facilities_raw     SQL: the Bronze gate
   │  only if it passed
   ▼
02_clean_deped_facilities            SQL: run stamp; pipeline_runs 'running'; from current_batches only:
   │                                       deped_facilities_clean_candidate       one row per school per school year
   │                                       deped_facilities_quarantine_candidate  rows that cannot be trusted, with reasons
   │  only if it succeeded
   ▼
90_validate_deped_facilities_clean   SQL: 37 results for SY 2023-24;
                                          any FAIL: 'failed', stop, nothing published;
                                          else publish quarantine, then clean, then 'succeeded'
```

The lane reads only facilities Bronze and waits for no other source; `90_validate_control` is the fan-in. Location comes from enrollment (O-2), and Integration (#91) checks that every facilities school is there.

### Grain, shape, and rules (facilities)

One wide row per school per school year, key (`school_id`, `school_year`), every column in published order. Every school is kept, public or not: the facility measures exist for public schools only (O-3), and Gold scopes to `sector = 'Public'`.

| Rule | What it does | Why | SY 2023-24 |
|---|---|---|---|
| Current batches only | Reads Bronze rows whose `batch_id` is in `current_batches` | D-015 | 60,167 rows |
| Labels | `sector`, `school_management`: whitespace normalized, mapped to enrollment's standard sets; an unmapped label fails the gate | D-022 | 0 relabelled |
| Yes/no | `offers_*` and the 60 `es_has_*`, `hs_has_*`, `*_accessible_*` columns: `True` → TRUE, `False` → FALSE, blank → NULL; any other label fails the gate | O-7 | 57,820 rows with a blank yes/no |
| Counts | The 21 counts: whole number → INT, blank → NULL, never 0; negative, not a whole number, or above the group's maximum (buildings 200; classrooms 1,000; temporary and makeshift 1,000) quarantines the row | O-6, D-038 | 59,622 rows with a blank count; largest 52 / 231 / 445 |
| `is_overseas` | `sector` or `school_management` is `PSO` | O-3 | 33 |
| `has_facility_data` | Any count or facility yes/no is published | O-3 | 47,817 (every public school but one) |
| `es_classrooms_missing` | A public school offering elementary with a blank `es_classrooms_instructional`; kept NULL, never 0 | O-4, O-5, S-2 | 669 |

### The gate (facilities)

FAIL checks: `current_batches_present`, `lineage_complete`, `rows_resolve_to_current_bronze`, `rows_built_by_this_run`, `one_timestamp_per_run`; per school year `rows_reconcile`, `school_id_unique`, `school_id_valid`, `counts_non_negative`, `counts_within_plausible_max`, `counts_reconcile` (the sum of every count equals Bronze's), `missing_counts_stay_null`, `true_values_reconcile` (the number of TRUE values equals Bronze's `True`), `missing_booleans_stay_null`, `labels_mapped_<column>` for `sector`, `school_management`, and each `offers_*`, `labels_mapped_facility_booleans` (all 60 together), and `quarantine_rate`. WARN checks: each quarantine reason; `facility_data_public_only` (a non-public school has a facility value: the scope may have changed); `facility_values_within_offered_levels` (a school has a value for a level it does not offer: Gold reads those blanks as not applicable). Records (always PASS): `rule_whitespace_normalized`, `rule_blank_counts_to_null`, `rule_blank_booleans_to_null`, `rule_labels_standardized`, `flag_is_overseas`, `flag_has_facility_data`, `flag_public_without_facility_data`, `flag_es_classrooms_missing`. `deped_facilities.gate_checks()` lists them all, and a test checks the SQL writes exactly those. On SY 2023-24 every check is PASS.

### Changing a rule (facilities)

Edit `config/mappings/deped_facilities.json` (a new publisher column must be classified there, or the generator stops), then regenerate (a test fails until you do):

```bash
python -m src.silver.cli sql --source deped_facilities > etl/03_silver/02_clean_deped_facilities.sql
```

```bash
python -m src.silver.cli gate --source deped_facilities > etl/03_silver/90_validate_deped_facilities_clean.sql
```

```bash
python -m src.silver.cli dictionary --source deped_facilities > docs/data/silver/deped-facilities-clean.md
```

A new schema version also needs a reviewed change to `src/silver/deped_facilities.py`, which does not yet handle columns absent from one year.

### Handoff to Integration and Gold (facilities)

- Read only a `succeeded` run's rows. One row per (`school_id`, `school_year`); location from `deped_enrollment_clean` on the same key.
- Facility results are for public schools only (`sector = 'Public'`); say so. `has_facility_data` FALSE marks the one public school with no facility value.
- NULL is never 0. A blank for a level the school does not offer is not applicable; `es_classrooms_missing` schools are left out of, or shown apart from, any classroom result.
- `*_classrooms_instructional` follows the NSBI definition (ALS, audio-visual, computer rooms, and laboratories count), not DepEd's official classroom-learner ratio (O-9): name the measure accordingly.
- Learners per room (O-8, S-1) is computed in Integration (#91), with any threshold decided and cited there. Integration also checks that every facilities school is in enrollment Silver for the same school year (O-2).

## Limitations

- On Databricks only `dev` has run it, and only with nothing to quarantine: a quarantined row and a failing gate are shown by the local tests, not on Databricks.
- `region` and the other categories are gated, so any new label stops Silver until it is reviewed, by design.
- With the PSA Silver tasks on, an environment whose Bronze has no current PSA batch (no approved workbook loaded) fails the job at `current_batches_present`, as DepEd does: Silver never publishes an empty table as if it were data. Intended (fail loudly rather than serve nothing silently); such an environment loads the workbook first. Raised in review of #121; the team has not yet confirmed it. The same holds for PSGC since its Silver tasks are on (#88).
- Every run rebuilds every school year, and starts the SQL warehouse; fine at 180,000 rows, revisit for larger sources.
- The two Silver tables are published one after the other: a task that dies between them leaves them from different runs until the next run. Gold's rule (the run each table's rows carry) keeps the clean table readable; a reader comparing the two tables must check both runs. A task that dies after both copies but before recording `succeeded` leaves nothing trusted for the source until the next run passes.
- `deped_enrollment`, `deped_facilities`, `deped_personnel`, `psa_psgc`, `psa_poverty_stat`, and `hdx_boundaries` have Silver.

## Open questions

| Question | Default until decided | Where |
|---|---|---|
| Should `Ã±` → `ñ` be repaired with `Ã‘` → `Ñ`, or left for Integration? | Repaired (exact pattern, counted) | D-023 |
| Should more address placeholders become NULL (`none` 709, `not applicable` about 300 a year, `NA`/`na` 44, `0` 104 in SY 2025-26)? | Only `-`, `n/a`, `N/A` | D-023 |
| Is 1% the right FAIL threshold for quarantine? | 1% of a school year's Bronze rows (PSA: of a batch's units in one estimate year) | D-024, D-034 |
| PSA: unpivot to one row per unit and estimate year in Silver, unlike DepEd's wide Silver? | Unpivot (D-034) | Team (source owner) |
| PSA: should a `partial_estimate` row (some measures blank) be quarantined rather than kept with a WARN? | Kept, WARN | D-034 |
| Should a source with no current Bronze batch fail the whole job (`current_batches_present`), or skip its Silver tasks? | Fail, as for DepEd | Team (#121 review) |
| Should a school with two conflicting rows keep one copy if the rows are identical? | Every copy quarantined | D-024 |
| PSGC: which level do the two blank-level containers (City of Isabela `0990100000`, Special Geographic Area `1999900000`) get? | NULL with `level_blank` | Team (#88) |
| PSGC: does the starred income class mean "retained after downgrade"? The `Notes` sheet does not say | Split, marked UNVERIFIED | @maeveylain, mentor (#88) |
| Facilities: does a blank elementary classroom count mean no permanent room (S-2)? | Unknown: NULL, flagged `es_classrooms_missing` | D-038 |
| Should Gold treat `no_counts` like `all_zero`? | Gold decides per measure | D-024 |
| Should Silver skip when Bronze is unchanged, with a condition task in the job? | Rebuild every run | D-025 |
| Should the Bronze gate also count only its own execution's results, so a repaired job run is judged on its own, as the Silver gate does? Changing it means regenerating every source's Bronze gate | Start a new run instead of repairing a failed one | D-020 |
| Drop `01-control.layer_builds` on dev, created by the cancelled run of 2026-10-08 and no longer used? | Left in place | Team |
| Should profile.md record the three Bronze findings above (and S-1's correction)? | Recorded here only | D-007 |
# DepEd personnel

The Personnel Silver lane runs after its own Bronze gate and reads only Personnel Bronze (D-041). It rebuilds `deped_personnel_clean_candidate` and `deped_personnel_quarantine_candidate`, then publishes only after `90_validate_deped_personnel_clean.sql` records no FAIL result. The lane does not wait for or read enrollment; cross-source checks belong to Integration (#91).

| Rule | Handling | Expected profiled effect | Possible information loss |
|---|---|---:|---|
| 321 personnel measures | Whole numbers become nullable `INT`; integer-equivalent decimal text such as `0.0` is accepted in every measure; blank becomes `NULL`; recorded zero stays `0` | 5,372,726 filled cells, including 5,108,840 recorded zeros | Formatting such as `.0` is removed by typing; Bronze text remains unchanged |
| `sector`, `school_management`, and `offers_*` | Map to enrollment's reviewed standard sets; an unreviewed label fails the gate | All current labels map | None. Bronze text remains unchanged |
| Public-school scope and offered level | A populated value outside its documented scope quarantines the school row | 0 profiled violations | The row is excluded from derived staffing measures, but retained in quarantine and Bronze |
| `shs_master_teacher_iv` | Keep the typed column and set `shs_master_teacher_iv_unavailable` | All 60,167 publisher values blank | No value is invented. The role cannot be analyzed |
| SHS principal total | Keep `shs_total_school_principal`; add the sum of grades I to IV and a discrepancy flag | 1,090 discrepancies | None. Both totals remain available |
| Personnel exceeds enrollment | Keep every valid Personnel row; compare with enrollment and flag in Integration (#91) | 11 fields across 9 schools in the profile | None in Silver. The published staff counts remain available to Gold |

The gate writes reconciliation, lineage, blank-versus-zero, principal-discrepancy, all-blank-field, label-mapping, quarantine-rate, and every quarantine-reason count to `01-control.data_quality_results`. Quarantine above 0 is WARN and above 1% of Bronze rows is FAIL. The approved delivery produces 60,167 clean rows and 0 quarantined rows locally.

## HDX ADM3 boundaries

`hdx_boundaries` uses the design above (two SQL tasks, candidates, publish after the gate, `pipeline_runs`; D-020, D-025) with its own rules (D-040). Its SQL and dictionary are generated by `src/silver/hdx_boundaries.py` from the Bronze contract and the [Silver rules](../../config/mappings/hdx_boundaries.json); columns: [data dictionary](../data/silver/hdx-adm3-clean.md).

**Status:** implemented and tested locally on made-up GeoJSON (`tests/test_silver_hdx.py`, with DuckDB's spatial extension); every geometry function the SQL uses was checked read-only on Databricks `dev` on 2026-10-09. Run by the job on Databricks `dev` on 2026-10-09 at `853be19`, twice: 1,642 clean rows, 0 quarantined, all 38 checks PASS in both runs ([evidence](../../evidence/pipeline-runs/2026-10-09-hdx-adm3-silver-databricks.md)).

### The flow (HDX)

```
06_create_hdx_adm3_raw        SQL: Bronze DDL
bronze_hdx_boundaries         Python: check and load the GeoJSON file (skip when already loaded)
90_validate_hdx_adm3_raw      SQL: the Bronze gate
   │  only if it passed
   ▼
06_clean_hdx_adm3             SQL: run stamp; pipeline_runs 'running'; from current_batches only:
   │                               hdx_adm3_clean_candidate       one row per ADM3 unit
   │                               hdx_adm3_quarantine_candidate  features that cannot be trusted
   │  only if it succeeded
   ▼
90_validate_hdx_adm3_clean    SQL: 38 checks (5 whole build, 33 per batch); any FAIL: 'failed', stop,
                                   nothing published; else publish quarantine, then clean, then 'succeeded'
```

### Grain and shape (HDX)

One row per COD-AB ADM3 feature (city or municipality) of each current batch, key (`adm3_pcode`, `valid_on`), all 32 published columns in file order, then three flags, the lineage, and the run stamp. The geometry is the published GeoJSON text (D-040): parse it with `try_to_geometry` on Databricks or `ST_GeomFromGeoJSON` in DuckDB spatial.

### Cleaning rules (HDX)

| Rule | Action | Why | Real file (2026-10-09 checks) |
|---|---|---|---|
| Current batches only | transform | D-015 | 1,642 features |
| `adm3_pcode` and parent codes kept exactly as published | none | Not PSGC codes (#74, HB-2) | |
| Blank, malformed (`^PH[0-9]{7}$`) or repeated `adm3_pcode` | quarantine | A key that cannot be trusted | 0 / 0 / 0 |
| Names trimmed, spaces collapsed, blank → NULL | transform | Joins | 0 with extra spaces |
| Region, country, version, language mapped to reviewed labels | transform; unmapped **fails** | One label per category | 17 / 1 / 1 / 1 labels |
| `valid_on`, `valid_to` → DATE when `YYYY-MM-DD` | transform; else quarantine | | 0 failures; `valid_to` blank in all rows |
| `area_sqkm` → DECIMAL(20,14), `center_lat`/`center_lon` → DECIMAL(18,14), only when the text fits exactly | transform; else quarantine | No digit rounded (D-023) | up to 4+14 digits; 0 failures |
| `area_sqkm` zero or negative | quarantine | Impossible | min 0.399814 |
| Geometry does not parse, is empty, or is not Polygon/MultiPolygon | quarantine | | 0 / 0 / 0 (1,273 Polygon, 369 MultiPolygon) |
| Geometry parses but is not valid | flag `geometry_is_valid` | Never repaired | 0 |
| Published centre outside its shape | flag `center_inside_geometry` | | 0 |
| adm3 → adm2 → adm1 code chain broken | flag `hierarchy_consistent` | | 0 |

### The gate (HDX)

Besides the shared whole-build checks (`current_batches_present`, `lineage_complete`, `rows_resolve_to_current_bronze`, `rows_built_by_this_run`, `one_timestamp_per_run`), per batch: `rows_reconcile`, `adm3_pcode_unique`, `adm3_pcode_valid`, `codes_as_published`, `geometry_as_published`, `values_kept` (a clean value is NULL only where Bronze is blank), `valid_on_is_reference_date`, `geometry_parsed`, `geometry_type_allowed`, `geometry_not_empty`, `area_positive`, `flags_consistent` (the gate re-parses every shape and recomputes the flags), and `labels_mapped_*` (FAIL); `geometry_valid`, `center_inside_geometry`, `hierarchy_consistent`, and `quarantine_reason_*` (WARN); `quarantine_rate` (WARN above 0, FAIL above 1%); and two `rule_*` records. `hdx_boundaries.gate_checks()` lists them.

### Running locally (HDX)

`python -m src.job.local_run` runs the lane with the rest of the job. The first statement that uses a geometry function makes DuckDB install and load its spatial extension (downloaded once from duckdb.org).

### Handoff to Integration and Gold (HDX)

- `adm3_pcode` is a COD-AB P-code, not a PSGC code; match by code and name together (`03_map_hdx_adm3_psgc`), and relate the 8 Special Geographic Area units spatially ([limitations](../governance/limitations.md)).
- Regions are COD-AB's 17, before the Negros Island Region; take regions from PSGC.
- Parse `geometry` where a spatial type is needed; never write a repaired shape back to Silver.

## DepEd school-to-PSGC crosswalk

`deped_enrollment_psgc` uses the design above (two SQL tasks, candidates, publish after the gate, `pipeline_runs`; D-020, D-025) with its own rules (D-049, #163). Its SQL and dictionary are generated by `src/silver/deped_enrollment_psgc.py` from the Bronze contract and the [Silver rules](../../config/mappings/deped_enrollment_psgc.json); columns: [data dictionary](../data/silver/deped-enrollment-psgc-clean.md).

It is a crosswalk, not an enrollment table: DepEd's own PSGC code per school, from the EMISD workbook, for Integration to match DepEd schools by code first (#44). None of the workbook's enrollment counts reach Silver.

**Status:** implemented and tested locally on made-up workbooks (`tests/test_silver_deped_enrollment_psgc.py`), and run locally on the real SY 2023-24 batch at `6852fbe` after review: 60,273 clean rows, 2 quarantined, every row reconciled to its Bronze row, 31 of 32 checks PASS and `quarantine_rate` WARN (2 rows), identical on a rebuild ([evidence](../../evidence/reconciliation/2026-10-16-deped-enrollment-psgc-bronze-to-silver.md)). Run by the job on Databricks `dev` after review, at `773d9f7`, in two job runs: both SUCCESS, 60,273 clean and 2 quarantined, 31 PASS and 1 WARN each, every row reconciled ([evidence](../../evidence/pipeline-runs/2026-10-16-deped-enrollment-psgc-silver-databricks.md)).

### The flow (crosswalk)

```
07_create_deped_enrollment_psgc_raw        SQL: Bronze DDL
bronze_deped_enrollment_psgc               Python: check and load the workbook (skip when already loaded)
90_validate_deped_enrollment_psgc_raw      SQL: the Bronze gate
   │  only if it passed
   ▼
07_clean_deped_enrollment_psgc             SQL: run stamp; pipeline_runs 'running'; from current_batches, rows of kind unit only:
   │                                            deped_enrollment_psgc_clean_candidate       one row per school
   │                                            deped_enrollment_psgc_quarantine_candidate  rows not carried, with reasons
   │  only if it succeeded
   ▼
90_validate_deped_enrollment_psgc_clean    SQL: 32 checks; any FAIL: 'failed', stop, nothing published;
                                                else publish quarantine, then clean, then 'succeeded'
```

### Grain and shape (crosswalk)

One row per `school_id` and `school_year` (`2023-24`): the four PSGC codes, `psgc_recoded`, two null reasons, `barangay_outside_city`, the coordinates typed and as published, and `coordinate_flag`, the published DepEd and PSGC names, `sector` and `urp` as published, the Bronze lineage, and the run stamp.

### Cleaning rules (crosswalk)

| Rule | Action | Why | Real batch (2026-10-16) |
|---|---|---|---|
| Bronze rows of kind `unit` only | transform | D-049: blank and `no_identifier` rows stay in Bronze | 60,275 read; 10 others counted |
| `school_id` not 6 digits | quarantine `school_id_malformed` | As DepEd enrollment Silver (#85) | 1 (`1406363`) |
| Repeated `school_id`, rows identical | keep the lowest Excel row; quarantine the rest as `school_id_identical_copy` | One school, published twice | 1 (`404520`, row 60267) |
| Repeated `school_id`, rows differ | quarantine every copy as `school_id_duplicated` | Which row is right is unknown | 0 |
| PSGC codes stored as 9 or 10 digits | left-pad to 10 | Profile O-5 | 36,010 barangay codes had 9 digits |
| `#N/A` or blank code | NULL with `source_na` or `not_in_workbook`; any other value **fails** | Profile O-6, O-2; D-023 | city 663 / 106; barangay 667 / 106 |
| Province code `19066…` (Sulu, Q4 2024) | each code that itself starts with `19066` to `09066…`, region `1900000000` to `0900000000`; `psgc_recoded`. A code pointing elsewhere is kept | D-049, profile X-2 | 467 schools |
| Barangay code outside its city or municipality code | flag `barangay_outside_city` | Profile O-7; kept as published | 3 |
| Longitude, latitude | DOUBLE, plus `longitude_published` / `latitude_published` keeping the exact Bronze text; unreadable text **fails**; the gate fails unless both reconcile to Bronze | D-023; Excel stored float noise (`120.79600000000001`), which the DOUBLE reads as `120.796` and the text keeps | 46,374 numeric |
| Coordinates missing, (0, 0), or outside the Philippines box | flag `coordinate_flag` | Profile O-10; S-1 is open | 13,899 / 6 / 54 |

How these counts relate to the profile: Bronze has 13,901 school rows with a missing coordinate (13,793 `#N/A` and 108 blank, O-10); 2 of them are the quarantined rows (Excel rows 60181 and 60267), so 13,899 clean rows are `missing`. The profile's 60 points outside the Philippines box include the 6 at (0, 0); Silver flags those 6 as `zero` and the other 54 as `outside_philippines`. No coordinate is dropped.

After padding and the recode, every one of the 59,500 barangay codes and 59,504 city codes exists in PSGC 2Q 2026 (checked outside the gate; the match itself is Integration's).

### The gate (crosswalk)

FAIL: `current_batch_present` (with no current batch the gate fails and publishes nothing), `rows_reconcile` (clean + quarantine = Bronze unit rows), `rows_resolve_to_current_bronze` (each row points at exactly one current Bronze `unit` row through its lineage), `values_reconcile` (every value recomputed from its Bronze row with the build's own expressions equals the candidate's), `coordinates_reconcile` (the published text equals Bronze and the DOUBLE equals its cast), `school_id_unique`, `school_id_format`, `codes_ten_digits`, `code_values_recognized`, `region_province_values_recognized`, `null_reason_matches_code`, `levels_null_together` (region and province NULL exactly when the city is), `coordinates_in_pairs`, `coordinate_values_recognized`, `lineage_complete`, `rows_built_by_this_run`. `quarantine_rate`: WARN above 0, FAIL above 1%. Fifteen `profiled_*` records: PASS at the count in the rules file, WARN when it changes, never FAIL. `deped_enrollment_psgc.gate_checks()` lists them.

What `values_reconcile` proves: the published table is today's build of the current Bronze rows, because the gate recomputes every value with the build's own expressions. It does not prove the rules are right: a mistake in a rule (for example a wrong Sulu prefix) would be in both and pass. The rules themselves are checked by `tests/test_silver_deped_enrollment_psgc.py`, which hard-codes the expected codes, reasons, and flags.

### Running locally (crosswalk)

`python -m src.job.local_run` runs the lane with the rest of the job. It reads the 60,275 school rows in about 10 seconds.

### Handoff to Integration and Gold (crosswalk)

- Integration (#44) matches DepEd schools by `psgc_barangay` first, then by name, and records the method (D-049). Rows with a null reason fall back to names.
- Manila's schools carry district codes (`1380601000` to `1380614000`); Integration rolls them up to the City of Manila (D-049).
- The workbook's PSGC names are as published: Sulu's still say BARMM after the recode. Take names and urban/rural or income class from psa_psgc through the code.
- Coordinates feed no Gold measure until the boundary test (S-1). Licensing is unverified: published outputs use the codes only to place schools in their city or municipality (D-049).
- Confirmed by @hyenalouise for the DepEd lane (PR #169, 2026-10-18): the identical-copy collapse, quarantining the 7-digit ID, and keeping the 106 appended schools with NULL codes.

## PSA school-age population

`psa_school_age_population` uses the design above (two SQL tasks, candidates, publish after the gate, `pipeline_runs`; D-020, D-025) with its own rules (D-053). Its SQL and dictionary are generated by `src/silver/psa_school_age_population.py` from the Bronze contract and the [Silver rules](../../config/mappings/psa_school_age_population.json); columns: [data dictionary](../data/silver/psa-school-age-population-clean.md).

**Status:** implemented and tested locally on made-up workbooks of both layouts (`tests/test_silver_school_age.py`). Run locally on the real workbooks on 2026-10-18, twice at `6bb76a6` and twice at `8d90086`: 418,320 clean rows, 0 quarantined, the levels equal to the profile's place counts, 0 FAIL / 4 WARN in every run (124 results at `8d90086`), identical content ([evidence](../../evidence/reconciliation/2026-10-18-psa-school-age-population-bronze-to-silver.md)). Run twice on Databricks `dev` at `8d90086`: both succeeded with the same results and identical content ([evidence](../../evidence/pipeline-runs/2026-10-18-psa-school-age-population-silver-databricks.md)).

### The flow (school-age)

```
08_create_psa_school_age_population_raw        SQL: Bronze DDL
bronze_psa_school_age_population               Python: check and load both census workbooks (skip when already loaded)
90_validate_psa_school_age_population_raw      SQL: the Bronze gate
   │  only if it passed
   ▼
08_clean_psa_school_age_population             SQL: run stamp; pipeline_runs 'running'; from current_batches only:
   │                                                psa_school_age_population_clean_candidate       one row per count cell
   │                                                psa_school_age_population_quarantine_candidate  cells whose count cannot be typed
   │  only if it succeeded
   ▼
90_validate_psa_school_age_population_clean    SQL: 124 checks (6 whole build, 15 per batch, 22 per sheet); any FAIL:
                                                    'failed', stop, nothing published; else publish, then 'succeeded'
```

### Grain and shape (school-age)

One row per count cell of each current census workbook: census year, population concept (one sheet each), place, sex, and single-year age 5 to 24, so 60 rows per place and sheet. Key (`census_year`, `population_concept`, `place_name`, `parent_name`, `sex`, `age`): 114 city and municipality names repeat, so the name alone is not a key. Both layouts give the same rows: 2020 (`v1`) has one wide row per place with three bands of 20 ages, and 2024 (`v2`) has a label row followed by `Total`, `Male` and `Female` rows of 20 ages.

For the approved workbooks: 2020, 1,742 places × 60 = 104,520 cells per sheet; 2024, 1,744 × 60 = 104,640; 418,320 rows in all. Title, header, note, source and blank rows stay in Bronze; the gate accounts for every Bronze row by kind.

### Cleaning rules (school-age)

| Rule | What it does | Why |
|---|---|---|
| Current batches only | One batch per census year, from `current_batches` | D-015, D-018 |
| Concept from the sheet | `<year> Total Pop` is `total`, `<year> Household Pop` is `household`; both kept, never mixed | D-029, O-5 |
| Label kept, name parsed | `place_label` is the label with whitespace normalized; `place_name` drops the trailing footnote marker (`1/`, `a/`) and every bracket, upper case; `footnote`, `old_name` (`, `-separated) and `is_capital` keep what was dropped | O-6 |
| Level and parent from the sums | See below; no PSGC code and no name matching in Silver | O-2 |
| Special places flagged | `place_status` is `special_geographic_area` for the 2020 `INTERIM PROVINCE` and the 2024 `SPECIAL GEOGRAPHIC AREA`, `sga_cluster` for a 2020 place under it whose name ends in `CLUSTER` (optional Roman numeral), else `standard` | O-7, S-1 |
| Counts typed | Whole numbers of up to nine digits become INT; 0 stays 0 (Kalayaan) | O-3 |
| `both` as published | Never recomputed from male + female; the gate checks it | O-4 |

### Levels from the sums (school-age)

The workbooks give no level and no code, only an ordered list of places. Silver recovers the tree from the counts alone. A place is an aggregate when the places right after it add up to it in all 60 cells, each nested aggregate counted once; the places it covers are its children. The build does this in three passes (provinces, then regions, then the country), with running sums per cell: in each pass, a place whose own count equals the sum of the following places up to some row, in every cell, spans those rows, and an aggregate with a single child (a region with one province) spans its child too. Depth is the number of spans a place is inside. An aggregate at depth 0, 1 or 2 is the country, a region or a province; a place with no children at depth 3 is a city or municipality under its province, and at depth 2 one directly under its region (NCR, Pateros, and the highly urbanized and independent cities). Any other shape gets no level and fails the gate.

Each step is written to a work table (`psa_school_age_population_work_cells`, `_work_places`, `_work_spans`, `_work_tree` in `03-silver`), and the next step reads that table. Spark does not keep a view's result: written as one chain of views, the build recomputed every earlier pass each time a later one used it, and ran for over 40 minutes on Databricks `dev` (2026-10-18). The work tables are rebuilt by every run and dropped at the end of the build; nothing reads them.

The level counts of each approved workbook are pinned by SHA-256 in the Silver rules (`expected_levels`): 2020, country 1, region 17, province 82, city or municipality 1,642; 2024, 1 / 18 / 83 / 1,642. A workbook with no pinned counts fails `levels_match_expected` until a reviewer adds them.

The level is the place's position in the tree, not a verified PSGC level. Two kinds of place sit at a province or city position without being a PSGC province or LGU, and `place_status` marks them: the Special Geographic Area (2020 `INTERIM PROVINCE`, 2024 `SPECIAL GEOGRAPHIC AREA`) is `special_geographic_area`, and the eight 2020 `... CLUSTER` places under it (PSA's grouping of SGA barangays by former Cotabato town) are `sga_cluster`. Their level stays the tree position, so the level counts still hold; the counts per status are pinned too (2020: 1 and 8; 2024: 1 and 0), and `place_status_match_expected` fails when they differ. The eight 2024 SGA municipalities are PSGC municipalities and stay `standard`. AP4 and #159 should leave out `sga_cluster` rows when counting LGUs.

A place whose 60 counts are all 0 fails `no_all_zero_place`: it adds nothing to any sum, so a span before it could cover it and the tree would still close with the wrong parent. No such place is in the approved workbooks (Kalayaan has zeros in some cells only).

### Quarantine (school-age)

A cell is quarantined, with every reason, when its count is blank (`population_blank`), negative (`population_negative`), or anything else that is not a whole number (`population_not_whole_number`). Any quarantined cell fails the gate (`quarantined_cells`): the profile found every count complete, so one missing count is a broken delivery, and a tree with a hole cannot be checked.

### The gate (school-age)

FAIL checks, whole build: `current_batches_present`, `one_current_batch_per_census_year`, `lineage_complete`, `rows_resolve_to_current_bronze_cells`, `rows_built_by_this_run`, `one_timestamp_per_run`. Per batch: `bronze_rows_accounted`, `sheets_are_concepts`, `household_not_above_total` (every place, sex and age), and `concepts_pair_up` (both sheets list the same places). Per sheet, written as `<check>_<concept>` (for example `tree_closes_total`): `rows_reconcile` (places × 60 = clean + quarantined), `population_matches_bronze`, `population_not_null`, `place_label_parsed`, `key_unique`, `place_levels_assigned`, `one_country`, `parents_resolve`, `tree_closes`, `levels_match_expected`, `place_status_match_expected`, `no_all_zero_place`, `sexes_add_up`, and `quarantined_cells`.

The gate checks the tree independently of the build: it resolves each place's parent by name and parent level (qualified by region), then checks that every aggregate equals the sum of its children in every cell. WARN: `zero_population_cells` (Kalayaan). Records (always PASS): `places_with_equal_concepts`, `national_both_sexes_by_age`, `rows_kind_<kind>`, `quarantine_reason_<reason>`, and the `rule_*` records. `psa_school_age_population.gate_checks()` lists them all, and a test checks the SQL writes exactly those.

On the approved workbooks the expected result is 0 FAIL and 4 WARN (zero cells on each of the four sheets).

### Running locally (school-age)

The whole job, as for every source: `python -m src.job.local_run`. To run only the school-age lane twice on a fresh database and print every number the evidence needs (Bronze rows by kind, cells per sheet against places × 60, places per level, zero cells, places with equal concepts, national totals by age, gate results, lineage, task timings, and a SHA-256 of the business content after each run):

```bash
python analysis/verification/psa_school_age_population_silver.py
```

It needs `RAW_DATA_DIR` with both approved workbooks (the loader verifies their SHA-256) and writes only to `local_state/` (git-ignored). Each number is compared with the profile's.

Changing a rule: edit `config/mappings/psa_school_age_population.json`, then regenerate (a test fails until you do):

```bash
python -m src.silver.cli sql --source psa_school_age_population > etl/03_silver/08_clean_psa_school_age_population.sql
```

```bash
python -m src.silver.cli gate --source psa_school_age_population > etl/03_silver/90_validate_psa_school_age_population_clean.sql
```

```bash
python -m src.silver.cli dictionary --source psa_school_age_population > docs/data/silver/psa-school-age-population-clean.md
```

A revised workbook (D-018) has a new SHA-256, so its level counts must be pinned in the rules file before its Silver publishes.

### Running on Databricks (school-age)

Follow [Running on Databricks](#running-on-databricks): a clean, pushed checkout of the exact commit; `bundle validate`, `deploy`, `summary`; run `edu_access_pipeline` twice. Expected: both runs skip the already-loaded workbooks in Bronze, and school-age Silver rebuilds on both. Then, replacing the commit:

```sql
WITH c AS (SELECT * FROM edu_access.`03-silver`.psa_school_age_population_clean),
     q AS (SELECT * FROM edu_access.`03-silver`.psa_school_age_population_quarantine),
     pr AS (SELECT * FROM edu_access.`01-control`.pipeline_runs WHERE pipeline_name = 'silver_build' AND source_id = 'psa_school_age_population'),
     last_run AS (SELECT MAX_BY(run_id, started_at_utc) AS run_id FROM pr),
     d AS (SELECT * FROM edu_access.`01-control`.data_quality_results
           WHERE layer = 'silver' AND source_id = 'psa_school_age_population' AND run_id = (SELECT run_id FROM last_run)),
     lv AS (SELECT census_year, level, COUNT(DISTINCT place_name, parent_name) AS n FROM c
            WHERE population_concept = 'total' AND sex = 'both' AND age = 5 GROUP BY census_year, level),
checks AS (
  SELECT 'cells 2020 total / household' AS check_name, '104520 / 104520' AS expected,
         COUNT_IF(census_year = 2020 AND population_concept = 'total') || ' / ' || COUNT_IF(census_year = 2020 AND population_concept = 'household') AS actual FROM c
  UNION ALL SELECT 'cells 2024 total / household', '104640 / 104640',
         COUNT_IF(census_year = 2024 AND population_concept = 'total') || ' / ' || COUNT_IF(census_year = 2024 AND population_concept = 'household') FROM c
  UNION ALL SELECT 'quarantined cells', '0', CAST(COUNT(*) AS STRING) FROM q
  UNION ALL SELECT 'repeated keys', '0', CAST(COUNT(*) - COUNT(DISTINCT census_year, population_concept, place_name, parent_name, sex, age) AS STRING) FROM c
  UNION ALL SELECT 'levels 2020 (country / region / province / city_municipality)', '1 / 17 / 82 / 1642',
         MAX(CASE WHEN level = 'country' THEN n END) || ' / ' || MAX(CASE WHEN level = 'region' THEN n END) || ' / ' ||
         MAX(CASE WHEN level = 'province' THEN n END) || ' / ' || MAX(CASE WHEN level = 'city_municipality' THEN n END) FROM lv WHERE census_year = 2020
  UNION ALL SELECT 'levels 2024 (country / region / province / city_municipality)', '1 / 18 / 83 / 1642',
         MAX(CASE WHEN level = 'country' THEN n END) || ' / ' || MAX(CASE WHEN level = 'region' THEN n END) || ' / ' ||
         MAX(CASE WHEN level = 'province' THEN n END) || ' / ' || MAX(CASE WHEN level = 'city_municipality' THEN n END) FROM lv WHERE census_year = 2024
  UNION ALL SELECT 'rows without a level', '0', CAST(COUNT_IF(level IS NULL) AS STRING) FROM c
  UNION ALL SELECT 'checks in the last run', '124', CAST(COUNT(*) AS STRING) FROM d
  UNION ALL SELECT 'FAIL / WARN in the last run', '0 / 4', COUNT_IF(status = 'FAIL') || ' / ' || COUNT_IF(status = 'WARN') FROM d
  UNION ALL SELECT 'rows from the last run', '418320', CAST(COUNT_IF(run_id = (SELECT run_id FROM last_run)) AS STRING) FROM c
  UNION ALL SELECT 'rows from another commit', '0', CAST(COUNT_IF(code_revision <> '<commit that ran>') AS STRING) FROM c
  UNION ALL SELECT 'last silver run', 'succeeded', MAX(status) FROM pr WHERE run_id = (SELECT run_id FROM last_run)
  UNION ALL SELECT 'silver runs succeeded at this commit', '2', CAST(COUNT_IF(status = 'succeeded' AND code_revision = '<commit that ran>') AS STRING) FROM pr
  UNION ALL SELECT 'candidate rows not published', '0', CAST(COUNT(*) AS STRING) FROM (
    SELECT * FROM edu_access.`03-silver`.psa_school_age_population_clean_candidate EXCEPT ALL SELECT * FROM c)
)
SELECT check_name, expected, actual, CASE WHEN expected = actual THEN 'OK' ELSE 'CHECK' END AS result FROM checks;
```

Business content of the two builds (run once after each run; the two hashes must be equal):

```sql
SELECT sha2(concat_ws('\n', sort_array(collect_list(concat_ws('|', CAST(census_year AS STRING), population_concept,
         place_label, place_name, footnote, old_name, CAST(is_capital AS STRING), level, region_name, province_name,
         parent_name, sex, CAST(age AS STRING), CAST(population AS STRING), source_sha256, source_sheet,
         CAST(source_row_number AS STRING), CAST(place_row_number AS STRING))))), 256) AS content_sha256
FROM edu_access.`03-silver`.psa_school_age_population_clean;
```

What only Databricks can show for school-age: Spark's running-sum windows and the 60-cell span join over about 210,000 rows per census year, `regexp_extract` and `array_join` on the labels, and the warehouse time of the two tasks.

### Evidence (school-age)

- Local, made-up workbooks: `tests/test_silver_school_age.py` (run with the whole suite).
- Local, real workbooks, two runs at `6bb76a6` and two at `8d90086`: [evidence/reconciliation/2026-10-18-psa-school-age-population-bronze-to-silver.md](../../evidence/reconciliation/2026-10-18-psa-school-age-population-bronze-to-silver.md).
- Databricks `dev`, two runs at `8d90086` (`5447221548394`, `820540420665033`): [evidence/pipeline-runs/2026-10-18-psa-school-age-population-silver-databricks.md](../../evidence/pipeline-runs/2026-10-18-psa-school-age-population-silver-databricks.md).

### Handoff to Integration and Gold (school-age)

- Read only a `succeeded` run's rows. Filter `level` before summing: every level is in the table, and the country, regions and provinces are sums of the places below them.
- Never mix `total` and `household` in one ratio (D-029); AP4 uses `total`, both sexes, ages 5-17 (D-042).
- Places are names only. Match `city_municipality` rows to PSGC 2Q 2026 in Integration (`05_map_psa_school_age_population_psgc`, #159) by `place_name` with `province_name` or `region_name`, using the shared matching rules and reviewed aliases; `old_name` can help but is not a PSGC name.
- 2020 has 17 regions and 2024 has 18 (the Negros Island Region): compare years at city or municipality level through PSGC, never by region name.
- A zero count (Kalayaan) is a real count, not missing.
