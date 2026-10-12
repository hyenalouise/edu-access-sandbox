# Evidence: DepEd Personnel Silver passes on Databricks

Issue #87 · Databricks `dev` · 2026-10-12 · checked by @mafelisilda

## Claim

The independent Personnel Silver lane builds and validates the approved SY 2023–24 delivery without dropping or quarantining valid source rows. It preserves the published principal-total discrepancies and completes every gate check without WARN or FAIL.

## Run

The targeted tasks of `[dev angela_felisilda] edu_access_pipeline` ran in Databricks job `533947017846780`, job run `39814735711789`, at commit `fbbf0dbf7787e2747b8d38bc0a3383d3a2ff124f`:

- `03_clean_deped_personnel` succeeded in 1 minute 49 seconds.
- `90_validate_deped_personnel_clean` succeeded in 1 minute 19 seconds.

The displayed `code_revision` matched the pushed commit. The run followed two failed attempts at the prior revision where the Databricks execution engine did not respond during the wide validation query. Commit `fbbf0db` materialized the gate summary once; the successful run confirms that design on Databricks.

## Results

| Check | Expected | Actual | Result |
|---|---:|---:|---|
| Current Bronze rows | 60,167 | 60,167 | PASS |
| Clean rows | 60,167 | 60,167 | PASS |
| Quarantined rows | 0 | 0 | PASS |
| Principal-total discrepancies | 1,090 | 1,090 | PASS |
| Personnel Silver PASS results | 24 | 24 | PASS |
| Personnel Silver WARN results | 0 | 0 | PASS |
| Personnel Silver FAIL results | 0 | 0 | PASS |

The 60,167 clean rows reconcile exactly to the current Bronze batch. The nine schools previously quarantined by a cross-source Enrollment comparison now remain in clean Personnel Silver as required by D-041; Integration #91 owns that comparison and must preserve the published Personnel values.

## Limitations

- This record covers one targeted Databricks build and gate run. Automated tests cover safe repeated local rebuilds; this record does not claim a second Databricks rebuild comparison.
- A failing Personnel data-quality rule was not deliberately exercised in the shared `dev` environment.

## Reproduce

```powershell
databricks bundle validate --target dev --profile reached-hq
databricks bundle deploy --target dev --profile reached-hq
databricks bundle run edu_access_pipeline `
  --only 03_clean_deped_personnel,90_validate_deped_personnel_clean `
  --target dev `
  --profile reached-hq
```
