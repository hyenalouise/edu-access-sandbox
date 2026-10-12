# Evidence: DepEd Personnel Silver builds and passes its gate on Databricks

> **Superseded for the current design:** this run proved the earlier build at `287bc51`, which quarantined nine personnel-versus-enrollment outliers. D-041 moves that cross-source check to Integration (#91), keeps those rows in clean Personnel Silver, and requires a new Databricks confirmation after the review changes. The historical results below remain unchanged.

Issue #87 · Databricks `dev` · 2026-10-11 · checked by @mafelisilda

## The claim

The Personnel Silver tasks of `edu_access_pipeline`, run by Spark on the SQL warehouse, build and validate the approved SY 2023–24 Personnel data. Every current Bronze row reaches either the clean or quarantine table, blank remains distinct from recorded zero, the known principal-total discrepancies remain visible, and the gate publishes with no FAIL result.

## What was run

The targeted Personnel Silver tasks of `[dev angela_felisilda] edu_access_pipeline` ran as Databricks job `533947017846780`, job run `423839712402245`, at pushed commit `287bc519c1afa8f4e615f6a8eb87e4fba71ad905`:

- `03_clean_deped_personnel`
- `90_validate_deped_personnel_clean`

The displayed `code_revision` matched the pushed commit. The results below were queried after the gate completed.

## Results

| Check | Expected | Actual | Result |
|---|---:|---:|---|
| Current Bronze rows | 60,167 | 60,167 | OK |
| Clean rows | 60,158 | 60,158 | OK |
| Quarantined rows | 9 | 9 | OK |
| Clean plus quarantine | 60,167 | 60,167 | OK |
| Personnel Silver PASS results | 20 | 20 | OK |
| Personnel Silver WARN results | 1 expected | 1 | OK |
| Personnel Silver FAIL results | 0 | 0 | OK |
| Enrollment-outlier rows | 9 | 9 | OK |
| Enrollment-outlier fields | 11 | 11 | OK |
| Unexpected non-null values in `shs_master_teacher_iv` | 0 | 0 | OK |
| Principal-total discrepancies in the complete source | 1,090 | 1,090 | OK |
| Principal-total discrepancies in clean Silver | 1,089 | 1,089 | OK |

The remaining principal-total discrepancy belongs to one of the nine quarantined rows. The quarantine table intentionally stores identifiers, lineage, and reasons rather than the derived discrepancy flag, so the complete-source count was reproduced directly from the current Bronze batch.

The gate recorded `recorded_zero_preserved` as PASS with 5,107,851 zero measures among the non-quarantined rows. This includes integer-equivalent Bronze text such as `0.0`, which Silver stores as integer `0`. The single WARN was `quarantine_reason_personnel_exceeds_enrollment`, with an actual count of 9. It records the known review cases and does not represent a failed gate.

## What this confirms

- Spark accepts the generated Personnel build and gate SQL.
- Job parameters carry the pushed code revision into the SQL tasks.
- The portable decimal-to-integer cast handles the four kindergarten fields on Databricks.
- The blank-versus-zero and recorded-zero checks pass on the real approved delivery.
- All 60,167 Bronze rows remain accounted for through clean or quarantine output.
- The nine reproducible enrollment outliers are set aside with reasons instead of being rewritten or dropped.
- The gate publishes with no FAIL result.

## Limitations

- This record covers one targeted Databricks run of the Personnel build and gate. Automated tests cover safe repeated rebuilds; this record does not claim a second Databricks rebuild comparison.
- The one WARN is expected for the nine documented enrollment outliers. Their source values remain unverified and unchanged in Bronze.
- A failing Personnel gate was not deliberately exercised in the shared `dev` environment.

## How to reproduce

From a clean checkout of the commit above, validate and deploy the bundle, confirm the deployed `git_commit` and `code_revision`, then run only the Personnel Silver build and gate:

```powershell
databricks bundle validate --target dev --profile reached-hq
databricks bundle deploy --target dev --profile reached-hq
databricks bundle run edu_access_pipeline `
  --only 03_clean_deped_personnel,90_validate_deped_personnel_clean `
  --target dev `
  --profile reached-hq
```

Run the Personnel verification queries from the review notebook against the resulting job run ID.
