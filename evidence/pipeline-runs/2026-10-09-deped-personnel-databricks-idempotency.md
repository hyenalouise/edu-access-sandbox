# deped_personnel: Databricks dev load, rerun, and DAG gate confirmation, 2026-10-09

**What this shows:** the approved DepEd Personnel ZIP loaded once into `` edu_access.`02-bronze`.deped_personnel_raw ``, a rerun inserted nothing, and the later `edu_access_pipeline` run executed the Personnel create, load, and separate Bronze-gate tasks successfully. Counts and identifiers are recorded here; no source records are included.

Times and dates are reported in Manila time (UTC+8) unless stated otherwise.

## Source-specific load and rerun

These runs used the earlier source-specific Bronze job at commit `7c0464b3f79a2cc0c75e33794aee468a5575c45d`.

| Run | Job run | Pipeline run | Personnel result |
|---|---|---|---|
| Initial load | `468189509671870` | `a684df42-6ab8-4a93-9045-fa7db3f194c4` | `succeeded`; 60,167 inserted; Bronze 60,167 |
| Immediate rerun | `1017863613509894` | `7cdb46d3-10c3-4ae7-a0ff-d421e234f0a5` | `skipped`; 0 inserted; Bronze remained 60,167; same SHA-256 |

The initial load ran from 19:00:45 to 19:03:23 on 2026-10-08. The rerun was queued at 19:06:26 and ended successfully at 19:07:50.

## Confirmation in `edu_access_pipeline`

@hyenalouise independently confirmed Databricks `dev` job run `696706629226090` at commit `15fcecbd45a482018d58e2f039a91c3184afd35e` during review of PR #110.

| Check | Result |
|---|---|
| Whole job | `SUCCESS` |
| `03_create_deped_personnel_raw` | Succeeded |
| `bronze_deped_personnel` | Succeeded; already-loaded delivery skipped; 0 inserted |
| `90_validate_deped_personnel_raw` | Succeeded |
| Bronze rows after the run | 60,167 |
| Pipeline duplicate rows | 0 |
| Rows missing provenance | 0 |
| Personnel gate checks | 3 PASS, 0 FAIL |

The three whole-table gate checks were:

- `no_pipeline_duplicates`
- `rows_have_a_known_batch`
- `succeeded_batches_reconcile`

## Additional independent validation

@maeveylain reran the Personnel ingestion locally with the approved ZIP during review:

- Run 1 loaded 60,167 rows.
- Runs 2 and 3 skipped the succeeded batch and inserted 0 rows.
- All 327 publisher columns remained text.
- Blank values remained distinct from the text value `0`.
- No pipeline duplicate rows were found.
- All 23 recorded checks passed.
- The complete Windows test suite reported 420 passed and 1 skipped at reviewed commit `15fcecbd`.
- At current branch commit `2da7522`, the complete test suite reported 500 passed and 1 skipped, or 501 tests collected.

## Limitations

- The `edu_access_pipeline` confirmation followed the skip path because the approved delivery had already been loaded by the earlier source-specific job. The initial Databricks load is therefore evidenced by job run `468189509671870`, while the current DAG wiring and separate gate are evidenced by job run `696706629226090`.
