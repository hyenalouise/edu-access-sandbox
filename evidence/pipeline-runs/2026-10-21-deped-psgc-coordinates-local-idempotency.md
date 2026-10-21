# Evidence: the public-only DepEd PSGC and coordinates workbook loads into Bronze locally once, and a second run inserts nothing

Issue #217 · local DuckDB (D-017) only; nothing has run on Databricks · 2026-10-21, Manila time (UTC+8) · run by @catweyine

## The claim

The workbook `SY 2023-2024 School Level Data on Enrollment with PSGC Longitude & Latitude (Public only).xlsx` loads through the shared pipeline (format `xlsx_report`, contract `config/ingestion/deped_psgc_coordinates.json`) into `deped_psgc_coordinates_raw`. Every row of sheet `DB` below the header is loaded, with every value as stored and complete provenance. Its counts equal the [profile](../../docs/data/source-inventory/deped_psgc_coordinates/profile.md), and its learners equal `deped_enrollment` SY 2023-24 public learners. Running the same ingestion again skips the workbook and inserts nothing.

**Not claimed:** anything on Databricks. The file is in the raw volume (uploaded by @catweyine), but lane 09 has not run on `dev`. Silver is a disabled placeholder.

## What was run

Commit `76b3f648af387a7c955c146e39fc0f6c20d9224a` on `feat/deped-psgc-coordinates`, clean worktree (`code_revision` has no `-dirty`). macOS 26.4.1, Python 3.12.14, DuckDB 1.4.5. A new, empty DuckDB file in a scratch folder outside the repository.

The workbook is at `$RAW_DATA_DIR/deped/original/`, copied from where it was received, with the SHA-256 checked on both copies: `edf7ba68cb768d658226a316754d636bec1d792b290692b14dd0cdd6e62fc8a1`, equal to the [source card](../../docs/data/source-inventory/deped_psgc_coordinates/README.md#files). It was only read.

```bash
python -m src.ingestion.cli ingest --source deped_psgc_coordinates --db <scratch>/coords.duckdb   # twice
```

| | Run 1 | Run 2 |
|---|---|---|
| `run_id` | `63059e33-0e2a-4ef4-a8f4-5c6f525b1ac0` | `40efc3b4-dc43-4e84-98eb-a4b30356422e` |
| Batch | `deped_psgc_coordinates__2023-24__edf7ba68cb76` | same |
| Action, outcome | `load`, `initial`, `succeeded` | `skip`, `skipped` ("already loaded; same SHA-256") |
| Rows inserted | **47,818** | **0** |
| Exit code | 0 | 0 |

## Results

| Check | Profile | Bronze |
|---|---|---|
| Rows below the header (A1:CJ47826) | 47,818 (O-1) | 47,818, Excel rows 9 to 47,826, all `unit` |
| `sector` | `Public` on every row (O-1) | `Public` 47,818 |
| Distinct `school_id`; not 6 digits | 47,818; 0 (O-2) | 47,818; 0 |
| `psgc_barangay` 9 digits / 10 digits / `#N/A` | 28,811 / 18,803 / 204 (O-3) | 28,811 / 18,803 / 204 (not padded) |
| `longitude` = `#N/A` | 679 (O-4) | 679 |
| Blank count cells (58 columns) | none | 0 |
| Learners, summed over the 58 counts | | 23,225,427, equal to `deped_enrollment` SY 2023-24 public learners ([its profile O-3](../../docs/data/source-inventory/deped_enrollment/profile.md)) |
| Repeated `(source_sha256, source_row_number)` | | 0 |
| NULL in any of the 16 provenance columns | | 0 |

Provenance values: `source_id` `deped_psgc_coordinates`, `school_year` `2023-24`, `delivery_version` 1, `source_sheet` `DB`, `schema_version` `v1`, `source_url` "Requested data from phcd.staff@psa.gov.ph", `code_revision` `76b3f648…224a`.

Control: one `ingestion_batches` row (`succeeded`, `initial`, expected = source = Bronze = 47,818), and two attempts (`load` 47,818, then `skip` 0). `data_quality_results`: 40 results, all PASS. That is the batch's checks, including `dq_sector_not_public` at 0, plus the 4 Bronze gate checks of each run (`approved_deliveries_present`, `no_pipeline_duplicates`, `rows_have_a_known_batch`, `succeeded_batches_reconcile`).

## Tests

`tests/test_ingestion_psgc_coordinates.py`, on made-up workbooks, covers:
- the real contract pins this file;
- the two DepEd workbooks are told apart by name;
- a load reconciles and a rerun adds nothing;
- a non-public row is kept and WARNs;
- a workbook without the `SECTOR: PUBLIC ONLY` note is refused;
- a changed file for the loaded year is blocked as a `revision`.

`tests/test_local_job.py` runs lane 09 in the whole local job, with its two Silver placeholders disabled.

## Not checked here

- The Databricks `dev` run of lane 09: the Spark backend, the volume path, the SQL warehouse gate.
- Silver: a placeholder.
- Which coordinates downstream should use (profile S-1): a team decision.
