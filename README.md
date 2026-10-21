# Education Access Intelligence

A data engineering capstone by **ReachED** for the FTW Data Engineering program.

[Architecture](docs/architecture/overview.md) ·
[Data model](docs/architecture/data-model.md) ·
[Setup](docs/getting-started/terminal-setup.md) ·
[Docs index](docs/README.md) ·
[Decisions](docs/governance/decisions.md) ·
[Evidence](evidence/README.md) ·
[Contributing](CONTRIBUTING.md)

## What it does

The pipeline turns official DepEd, PSA, and HDX files into city- and municipality-level measures of classroom and teacher pressure, and puts the LGUs whose schools pass a classroom congestion screen into a review queue.

> **Business question:** How should we prioritize the provision of classrooms and teachers among cities based on their respective enrollment needs?

- **Users:** LGU Local School Boards, which decide how the Special Education Fund is spent (D-057).
- **Scope:** public basic education, Kinder to Grade 12, in every Philippine city and municipality (D-003).
- **Outputs:** one table per analytical question (AP1 to AP4) and `lgu_priority_matrix`, which shows AP1 to AP4 side by side and ranks the LGUs with reported classroom congestion into a review queue (D-060).

The wording, the four analytical questions, and their limits are in [business and analytical questions](docs/business/business-analytics-problem.md); the formulas are in the [metric specification](docs/business/metric-specification.md).

## Pipeline at a glance

```mermaid
flowchart LR
    files[Official files: DepEd, PSA, HDX] --> raw[(00-source volume)]
    raw --> bronze[02 Bronze] --> silver[03 Silver] --> integration[04 Integration] --> gold[05 Gold] --> analytics[06 Analytics]
    bronze & silver & integration & gold & analytics -.->|check results| control[(01 Control)]
    control -.-> dq[Data-quality dashboard]
```

Each source moves through Bronze and Silver in its own lane. From Silver on, every table is built as a candidate and replaces the published table only when its validation gate passes, so a failed check never overwrites the last good result. Details: [architecture overview](docs/architecture/overview.md).

## Status

| | |
|---|---|
| **Implemented** | 9 sources through Bronze and Silver, 5 Integration maps, 12 Gold tables, 5 Analytics outputs, the data-quality dashboard, freshness and quality alerts. All are enabled in [`databricks.yml`](databricks.yml) and run by CI on made-up data |
| **Proven on Databricks `dev`** | Source to Gold, twice, every gate passing and identical results, at `7542cc0` ([evidence](evidence/pipeline-runs/2026-10-20-gold-databricks-dev.md)); the school-coordinates Bronze load ([evidence](evidence/pipeline-runs/2026-10-21-deped-psgc-coordinates-databricks.md)); totals traced from source file to Gold in [validation](docs/operations/validation.md) |
| **Proven locally only** | The Analytics outputs and the data-quality dashboard (tested in CI, no Databricks run in `evidence/` yet); failure recovery, rehearsed end to end ([evidence](evidence/pipeline-runs/2026-10-20-failure-recovery-local.md)); the school-coordinates Silver lane, reconciled on the real workbook ([evidence](evidence/reconciliation/2026-10-21-deped-psgc-coordinates-bronze-to-silver.md)) |
| **Not built** | A run on `prod`: the target is defined in its own workspace (D-063) but not yet deployed (#99); the LGU planner dashboard is in review (#224) |

A commit on `main` is not what runs in the workspace until it is deployed: the job records the commit it ran as `code_revision` on every row it writes.

## Repository map

| Path | What is there |
|---|---|
| [`etl/`](etl/README.md) | The SQL of every stage, `01_control` to `06_analytics`; each build has a `90_validate_*` gate |
| [`src/`](src/README.md) | Python: ingestion, the generators of the Silver, Integration, and dashboard files, and the local job runner |
| [`config/`](config/README.md) | Source contracts, reviewed mappings and rules, the table registry, freshness limits |
| [`databricks.yml`](databricks.yml) | The job, its alerts, and the dashboard (Databricks Asset Bundle) |
| [`dashboards/`](dashboards/README.md) | Generated AI/BI dashboards |
| [`tests/`](tests/README.md) | pytest suite run by CI, on made-up data only |
| [`docs/`](docs/README.md) | Architecture, business framing, source inventory, operations, decisions |
| [`evidence/`](evidence/README.md) | Recorded runs and reconciliations that back each claim |
| [`analysis/`](analysis/README.md) | Profiling and cross-source research scripts; not pipeline tasks |

Several files under `etl/`, `docs/data/silver/`, and `dashboards/` are generated from `config/`. Each stage README says which, and a test fails if a committed file differs from what its generator prints.

## Setup

Set up a laptop once with [terminal setup](docs/getting-started/terminal-setup.md), then, on macOS or Linux:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

On Windows, in PowerShell:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
```

Raw files are never committed. Locally they sit in `raw-data/` beside the repository ([terminal setup, Part 8](docs/getting-started/terminal-setup.md#part-8-raw-data-and-raw_data_dir)); on Databricks they are in `` edu_access.`00-source`.raw ``. Each source contract in `config/ingestion/` names the approved files by SHA-256, and each [source card](docs/data/source-inventory/README.md) records where to download them.

## Run it

| What | Command |
|---|---|
| Tests and policy checks (what CI runs) | `python -m pytest tests -q` |
| The whole job, locally on DuckDB | macOS or Linux: `RAW_DATA_DIR=~/Projects/reached-hq/raw-data python -m src.job.local_run`. Windows PowerShell: `$env:RAW_DATA_DIR = "$HOME\Projects\reached-hq\raw-data"; python -m src.job.local_run` |
| Deploy the job to `dev` | `databricks bundle deploy --target dev --profile reached-hq-dev` |
| Run the job on `dev` | `databricks bundle run edu_access_pipeline --target dev --profile reached-hq-dev` |

The local run writes to `local_state/edu_access.duckdb` (git-ignored) and exits 0 only when every task succeeded. Deploy from a clean, pushed `main`; Databricks compute is shared, so agree a run with the team first ([workflow, Part 5](docs/operations/workflow.md#part-5-where-code-runs)).

## Check that it worked

- **Every task succeeded** and the run's `code_revision` is the commit you deployed.
- **No gate wrote a FAIL.** The [data-quality dashboard](dashboards/README.md) shows each check's newest result; `` edu_access.`01-control`.data_quality_results `` holds them all.
- **The totals match the source.** [Validation](docs/operations/validation.md) lists the counts to compare, layer by layer.

## When something fails

The failed task names the gate or step. Its results are in `data_quality_results`, and the batch's state is in `` `01-control`.ingestion_batches ``. Reruns are safe: Bronze adds only missing rows, and every later layer rebuilds and publishes only after its gate passes. Start with the [failure-recovery runbook](docs/operations/runbook.md): the first response, what to do for each failure type, how to retry, rerun, or backfill, and how to trace a number back to its raw file.

## Changing or extending it

- **New delivery of a known source:** [approving a delivery](config/ingestion/README.md).
- **New or changed cleaning rule:** [Silver, Changing a rule](docs/operations/silver.md#changing-a-rule-or-approving-a-label), then regenerate the SQL.
- **New table:** register it in [`config/tables.yml`](config/tables.yml), add the build and its gate to its `etl/` stage and to `databricks.yml`, and list both files in the stage README.
- **A design choice:** record it in the [decision log](docs/governance/decisions.md).

Process, branches, and reviews: [CONTRIBUTING.md](CONTRIBUTING.md).

## Known limitations

- Enrollment is observed demand at the school's location, not learner residence, and the classroom queue is a screen for review, not a shortage count ([business framing](docs/business/business-analytics-problem.md)).
- Classroom and teacher capacity cover SY 2023-24 only; enrollment covers SY 2020-21 to 2025-26.
- Annex schools publish no mother-school ID, so their counts are not consolidated (D-044).
- `prod` is defined in its own workspace but has not run yet; its team notification destination still has to be created there (D-063, #99).

Every confirmed data limit, with its evidence, is in [limitations](docs/governance/limitations.md).
