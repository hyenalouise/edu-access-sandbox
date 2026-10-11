# Evidence: DepEd facilities Silver reconciles with Bronze, and every run rebuilds the same rows

Issue #86 · local run (DuckDB) · 2026-10-11 · checked by @hyenalouise

## The claim

Silver built from the real SY 2023-24 facilities Bronze keeps every Bronze row (clean + quarantined = Bronze), moves no count, TRUE value, or blank, places every school in enrollment Silver, matches the profile's numbers, and passes every gate check. A second job run with the same Bronze batch rebuilds the table with identical content.

## What was run

Commit `f5b6a30104db9b6849d80809f39db35e9057ea45`, clean detached checkout (no `-dirty`), macOS 26.3.1, Python 3.12.14, DuckDB 1.4.5, a fresh database file in a scratch folder. The approved deliveries were read from `raw-data/` (checksums verified by the loader, as on the source card). The whole job ran twice, in the order of the Databricks DAG:

```bash
RAW_DATA_DIR=~/Projects/reached-hq/raw-data python -m src.job.local_run --db <scratch>.duckdb
```

After each run, the clean table's business content (every column except `run_id`, `cleaned_at_utc`, `code_revision`, ordered by Bronze row) was hashed with SHA-256. Then `python -m pytest tests -q` at the same commit: 616 passed.

| Step | Result | Task time |
|---|---|---:|
| Run 1: `bronze_deped_facilities` | 60,167 rows loaded, `succeeded` | 2.3 s |
| Run 1: `02_clean_deped_facilities` | 60,167 Bronze rows → 60,167 clean, 0 quarantined | 0.4 s |
| Run 1: `90_validate_deped_facilities_clean` | 38 checks: 38 PASS, 0 WARN, 0 FAIL; run `succeeded` | 0.8 s |
| Run 2: `bronze_deped_facilities` | `skip`, 0 rows inserted | 0.1 s |
| Run 2: `02_clean_deped_facilities` | rebuilt: 60,167 clean, 0 quarantined | 0.4 s |
| Run 2: `90_validate_deped_facilities_clean` | 38 checks: 38 PASS; run `succeeded` | 0.8 s |

Both job runs exited 0 with every enabled task `succeeded`; enrollment and PSA Poverty Stat Silver also succeeded in both.

## Results

Identical after run 1 and run 2:

| Check | Expected | Actual | Result |
|---|---|---|---|
| Bronze rows (current batch) | 60,167 (source card) | 60,167 | OK |
| clean + quarantined | 60,167 + 0 | 60,167 + 0 | OK |
| schools not in `deped_enrollment_clean` (SY 2023-24) | 0 (profile O-2) | 0 | OK |
| `has_facility_data` | 47,817: every public school but one (profile O-3) | 47,817 of 47,818 public | OK |
| `es_classrooms_missing` | 669 (profile O-4) | 669 | OK |
| `is_overseas` | 33 (profile O-3) | 33 | OK |
| sum of all counts, Bronze kept vs clean (`counts_reconcile`) | equal | 1,213,740 = 1,213,740 | OK |
| blank counts, Bronze kept vs NULL in clean (`missing_counts_stay_null`) | equal | 626,515 = 626,515 | OK |
| `True` in Bronze vs TRUE in clean (`true_values_reconcile`) | equal | 458,922 = 458,922 | OK |
| blank yes/no, Bronze kept vs NULL in clean (`missing_booleans_stay_null`) | equal | 2,800,050 = 2,800,050 | OK |
| rows with a blank count / a blank yes/no (`rule_*`) | recorded | 59,622 / 57,820 | OK |
| labels relabelled, whitespace changed (`rule_*`) | 0 (SY 2023-24 labels are the standard) | 0 / 0 | OK |
| `facility_data_public_only`, `facility_values_within_offered_levels` | PASS | PASS / PASS | OK |
| rows from the last run, at this commit | 60,167 | 60,167 | OK |
| candidate rows not published | 0 | 0 | OK |
| clean content SHA-256, run 1 | | `c9dd4853a9102c3868e9244a2b0ffbfab74df3bc508f64b6667d94a960f36e37` | |
| clean content SHA-256, run 2 | the same | `c9dd4853a9102c3868e9244a2b0ffbfab74df3bc508f64b6667d94a960f36e37` | OK |

## Re-run at `1c2317b`: a missing school is quarantined

At commit `1c2317b79fbcf8811c140d5c3948f2023014c894`, a school missing from enrollment Silver is quarantined (`school_id_not_in_enrollment`) instead of failing the gate, and the build, not the gate, waits for the enrollment Silver gate (D-038). The same steps as above, from a clean detached checkout and a fresh database, run twice; `python -m pytest tests -q` at that commit: 618 passed.

| Check | Result |
|---|---|
| clean + quarantined | 60,167 + 0, both runs |
| `has_facility_data` / `es_classrooms_missing` / `is_overseas` | 47,817 / 669 / 33 |
| gate checks | 39 (the new `quarantine_reason_school_id_not_in_enrollment` added), all PASS, both runs |
| clean content SHA-256, both runs | `c9dd4853a9102c3868e9244a2b0ffbfab74df3bc508f64b6667d94a960f36e37`, the same as at `f5b6a30` |
| task time | build 0.4 s, gate 0.8 s |

No real school is missing from enrollment, so the change leaves every published row as it was.

## What this does not show

- Databricks: facilities Silver had not run on `dev` when this record was made. It ran there at `6b2844d` ([record](../pipeline-runs/2026-10-11-deped-facilities-silver.md)); at `1c2317b`, not yet.
- A quarantined row, an unmapped label, a school missing from enrollment, and a failing gate are shown by the made-up deliveries in `tests/test_silver_facilities.py`, not by real data: the real file has none.
