# Evidence: DepEd schools map to PSGC at city and barangay level

Issue #91 · local DuckDB (D-017) · 2026-10-19, Manila time (UTC+8)

## The claim

The Integration build reads the published `deped_enrollment_clean`,
`deped_enrollment_psgc_clean`, and `psa_psgc_clean` Silver tables and publishes
`deped_school_psgc_map` only after its gate passes. The table retains every
enrollment school and produces exactly one `city_mun` and one `bgy` row for
each school year. Unmatched, ambiguous, overseas, and other excluded records
remain explicit rows rather than being dropped.

The implementation reproduces the rule reviewed in PR #153 for SY 2023-24.
For all 120,268 Philippine-school map rows in that analysis preview, the
production output has the same `match_status`, `psgc_code`, and
`match_method`.

## What was run

The full local `edu_access_pipeline` ran twice against the approved source
deliveries on branch `feat/91-deped-school-psgc-map`. The second run skipped
every unchanged Bronze delivery by SHA-256, then safely rebuilt and republished
the Integration candidate.

```bash
python -m src.job.local_run \
  --landing "$RAW_DATA_DIR" \
  --db local_state/edu_access.duckdb \
  --code-revision feat-91-final
```

| | Run 1 | Run 2 |
|---|---|---|
| `run_id` | `204fd7f8-4ed5-4700-96c9-03e4c88c62e2` | `ed1c0572-35ea-4fae-add9-a90eb429e454` |
| Integration build / gate | 1.74 s / 0.79 s | 1.73 s / 0.74 s |
| Published rows | 482,914 | 482,914 |
| Unique school/year/level keys | 482,914 | 482,914 |
| Gate results | 19 PASS, 4 WARN, 0 FAIL | 19 PASS, 4 WARN, 0 FAIL |
| Business-content SHA-256 (run stamp excluded) | `2c6611846141a28e36316ddac785a22e54118e8ce2d68b40c6d8f73b2f59d3a8` | same |

The four WARN results are the intentionally visible `unmatched`, `ambiguous`,
`excluded`, and `review_pending` counts. They do not bypass any structural
check.

## Results

There are 241,457 enrollment rows and 482,914 map rows: exactly two map rows
per enrollment row. Both levels contain 241,457 rows, and the key has no
duplicates. All matched codes resolve to the one master PSGC publication,
every matched barangay belongs to its accepted city or municipality, all
lineage fields are populated, and the gate recorded 0 FAIL.

| School year | Level | Matched | Ambiguous | Unmatched | Excluded | Total |
|---|---:|---:|---:|---:|---:|---:|
| 2020-21 | city/municipality | 60,877 | 31 | 16 | 33 | 60,957 |
| 2020-21 | barangay | 60,693 | 156 | 75 | 33 | 60,957 |
| 2023-24 | city/municipality | 60,108 | 12 | 4 | 43 | 60,167 |
| 2023-24 | barangay | 60,050 | 56 | 18 | 43 | 60,167 |
| 2024-25 | city/municipality | 60,060 | 1 | 10 | 58 | 60,129 |
| 2024-25 | barangay | 60,040 | 13 | 18 | 58 | 60,129 |
| 2025-26 | city/municipality | 60,122 | 3 | 20 | 59 | 60,204 |
| 2025-26 | barangay | 60,039 | 71 | 35 | 59 | 60,204 |

For SY 2023-24, subtracting the 33 overseas schools from the excluded count
gives the PR #153 preview exactly: city/municipality 60,108 matched, 12
ambiguous, 4 unmatched, and 10 excluded; barangay 60,050 matched, 56
ambiguous, 18 unmatched, and 10 excluded.

## Cost and rerun behavior

The SQL matches the distinct source place tuples once and joins those decisions
back to school/year rows. It does not compare every school with every PSGC
barangay. On the local validation database, the build plus gate took under
2.6 seconds per run. The candidate is published only after all FAIL checks
pass, so a failed rebuild leaves the last published table intact.

## Limitations

- DuckDB validates the local translation of the generated SQL; Spark SQL,
  Delta publication, ownership, and the small Databricks SQL warehouse still
  need a `dev` bundle run before this draft is ready to merge.
- WARN rows are deliberately retained for review. This PR does not force the
  remaining ambiguous or unmatched schools onto a PSGC unit.

