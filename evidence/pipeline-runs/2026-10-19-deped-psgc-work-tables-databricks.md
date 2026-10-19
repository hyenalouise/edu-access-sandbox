# Evidence: the DepEd school-to-PSGC map builds on Databricks with its work-table stages, and its gate passes

Issue #91 · PR #197 · Databricks Free Edition, @hyenalouise's sandbox workspace · 2026-10-19, Manila time (UTC+8) · run by @hyenalouise

## The claim

With the matching stages stored as run-specific Delta work tables (PR #197) and the gate's summary row
written to a table before its checks read it, `01_map_deped_school_psgc` and
`90_validate_deped_school_psgc_map` both succeed on Databricks SQL. The build takes about a minute,
where `main` at `c70095e` ran out of JVM memory after 35 minutes. The map has 724,044 rows, the gate records
44 PASS, 5 WARN and 0 FAIL, and the build drops every one of its work tables after the candidate is written.

## Before the change

| Run | Where | Commit | Result |
|---|---|---|---|
| `350271822258008` | team `dev` workspace | `c70095e` (`main`) | `01_map_deped_school_psgc` failed after 35 min 6 s: `JVM_OUT_OF_MEMORY: GC overhead limit exceeded` |
| `735539360671238` | sandbox workspace | same map build | `01_map_deped_school_psgc` failed: `TASK_FAILED_EXECUTOR_LOSS`, heartbeat timeout |
| `379760909854034` | sandbox workspace | same gate as `main` | `90_validate_deped_school_psgc_map` failed: `INTERNAL_ERROR`, Spark SQL phase optimization |
| `259490155849270` | sandbox workspace | PR #197 at `474fc4c` | map build succeeded in 77 s; the gate failed with the same optimizer `INTERNAL_ERROR`, twice |

The optimizer error is not a FAIL check: Spark fails while planning the gate, whose one-row summary
(a CROSS JOIN of five aggregates) is read 25 times as a common table expression. Each part ran on its own;
written to `deped_school_psgc_map_gate_summary` first, every check runs.

## What was run

The sandbox job `[dev hyenalouise] edu_access_pipeline` (job `453778467112903`), deployed with
`databricks bundle deploy --target dev --profile sandbox` from `hyenalouise/edu-access-sandbox` at commit
`52a2f876e16d5347b6e097233e25417e48426713` (the `code_revision` on the run). The sandbox is a copy of this
repository; at that commit the generator, the build and gate SQL, `src/ingestion/store.py`, the runbook
and the Integration tests are byte-identical to this branch (`tests/test_bundle.py` has this PR's change
applied over the sandbox's own). Only the two
map tasks were run (`databricks jobs run-now` with `only`), on the Silver tables of the sandbox's last full
run, which uses the same approved deliveries.

| | Job run `270543567731742` |
|---|---|
| Whole run | 19:42:20 to 19:43:54, `TERMINATED SUCCESS` |
| `01_map_deped_school_psgc` | task run `842294102493444`, 19:42:20 to 19:43:30, about 70 s, succeeded |
| `90_validate_deped_school_psgc_map` | task run `562423963440371`, 19:43:30 to 19:43:53, about 23 s, succeeded |

## Results

| Check | Value |
|---|---:|
| `deped_school_psgc_map_candidate` rows | 724,044 |
| `deped_school_psgc_map` rows (published), one `run_id` | 724,044 |
| `data_quality_results`, this run, `layer = 'integration'` | 44 PASS, 5 WARN, 0 FAIL |
| WARN: `ambiguous` / `excluded` / `unmatched` | 611 / 554 / 276 |
| WARN: `review_pending` / `override_without_unit` | 1,441 / 4 |
| `pipeline_runs`, `integration_build` | `succeeded` |
| This run's work tables left (`deped_school_psgc_map_work_r_7b326245…`) | none |

The counts are the same as the local run on the same deliveries.

## The stages read stored work tables

From the SQL warehouse's query history for the build task: each stage is its own statement, and every
stage after `units` reads the earlier stages through `IDENTIFIER(session.integration_work_*)`, which
names a stored Delta table, instead of expanding the matching graph again.

| Stage | Query ID | Duration | Bytes read | Reads work tables |
|---|---|---:|---:|---|
| `units` | `01f1cbb2-2e1f-1014-998b-63d1ed18e8b4` | 3.3 s | 0.9 MB | none (PSGC Silver) |
| `province_pairs` | `01f1cbb2-2e1f-1015-8471-d379b0b480a4` | 4.1 s | 5.7 MB | `units` |
| `city_pairs` | `01f1cbb2-2e1f-1016-b8e2-4297b17af907` | 4.8 s | 7.7 MB | `units`, `province_pairs` |
| `cities` | `01f1cbb2-2e1f-1017-9e84-b62a37b87210` | 3.4 s | 1.2 MB | `units`, `province_pairs`, `city_pairs` |
| `barangay_pairs` | `01f1cbb2-2e1f-1018-9403-60ece3b8f1aa` | 3.8 s | 2.3 MB | `units`, `cities` |
| `places` | `01f1cbb2-2e1f-1019-b54d-c57469fddf79` | 3.5 s | 7.0 MB | `cities`, `barangay_pairs` |
| `decisions` | `01f1cbb2-2e1f-101a-8f52-6e44f4e8901c` | 7.3 s | 9.5 MB | `units`, `places` |
| candidate | `01f1cbb2-2e1f-101c-81dd-9e495139ab0f` | 2.9 s | 13.6 MB | `units`, `decisions` |

Each query's plan is in the workspace under SQL › Query History › the query ID › Query profile.

## What this does not show

- The run is on the sandbox workspace, not the team `dev` workspace; the team's group run of this commit
  is still to come.
- A work table from another run, `deped_school_psgc_map_work_r_3771fd8f…_units`, is still in the sandbox's
  `04-integration` from an earlier failed attempt, as the runbook describes for failed runs.
