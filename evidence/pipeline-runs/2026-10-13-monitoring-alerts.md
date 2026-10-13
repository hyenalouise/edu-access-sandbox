# Evidence: every monitoring signal fires once on Databricks, and each alert email lists its rows

Issue #100 · Databricks `dev` · 2026-10-13 · checked by @hyenalouise

## The claim

On Databricks, with the monitoring in D-043 deployed:

- a failed run emails the deployer;
- a run past the duration warning emails the deployer;
- `90_validate_freshness` writes one `source_fresh` result per loaded source, WARN when the source is older than its limit;
- the `quality_failures` alert triggers on the latest run's FAILs and the `stale_sources` alert on the latest freshness check's WARNs, each email lists the rows, and each emails again when it returns to OK.

Each signal was made to fire with a variable, a job parameter, or a partial run, never by changing code or data.

## What was run

The job `[dev ina_magno] edu_access_pipeline` (job `651937364323543`) and the alerts `[dev ina_magno] edu_access_pipeline data-quality FAIL` (`4120167082488792`) and `[dev ina_magno] edu_access_pipeline stale source` (`4120167082488791`), deployed with `databricks bundle deploy --profile reached-hq` from the pushed branch `feat/100-monitor-pipeline-runs`: first at `4a93aca629e6e33401e1a6e52906335710df43f4`, then at `bbeac4ae5b013d43ae47584a2d4ab6bd047279c1` after the fix below. `bundle validate` was OK at both commits, and `jobs get` read back the deployed commit as the job's `git_commit`. Times are UTC; the emails show Manila time (UTC+8).

Development mode pauses alert schedules, so each alert was evaluated by switching its dev copy to every minute and unpaused (`databricks alerts-v2 update-alert <id> schedule`), waiting for it to change state, then pausing it again. The final deploy read back `5 unchanged`, so the deployed alerts match `databricks.yml`.

Before the first deploy, the local deploy state (`.databricks/bundle/dev/resources.json`, serial 3) was older than the workspace's (serial 19) and the CLI refused to deploy (`lineage mismatch in state files`). The local file was moved aside, and the deploy used the workspace's state.

## Results

### Run emails, at `4a93aca` deployed with `--var duration_warning_seconds=60`

| Test | Command | Run | Result | Email |
|---|---|---|---|---|
| Failed run | `bundle run edu_access_pipeline --only 90_validate_control` | `827120061094283`, 17:53:42, 62.8 s, `FAILED` | No Silver lane ran in this run, so the fan-in wrote 6 FAIL rows (`silver_lane_succeeded`, actual `not run`, commit `4a93aca…`) and raised | "Error in run 827120061094283": `Task 90_validate_control failed` |
| Slow run | `bundle run edu_access_pipeline --only` the six control-bootstrap tasks | `409891514420038`, 17:55:16, 72.9 s, `SUCCESS` | Past the 60-second warning | "Duration threshold warning for run 409891514420038": started 1m 6s ago, warning 1m, timeout 1h 30m |

The 62.8-second run sent no duration warning: it ended about when the warning came due. The 72.9-second run, with margin, did.

### Failure email: run 827120061094283, the fan-in failed
<!-- SCREENSHOT 1-failure-email-run-827120061094283.png: replace this line with tmp/pr130-screenshots/1-failure-email-run-827120061094283.png (drag it in on GitHub) -->

### Duration warning: run 409891514420038, past the 60-second test threshold
<!-- SCREENSHOT 2-duration-warning-run-409891514420038.png: replace this line with tmp/pr130-screenshots/2-duration-warning-run-409891514420038.png (drag it in on GitHub) -->

### Alerts, at `4a93aca`

| Test | Command or step | Result | Email |
|---|---|---|---|
| `quality_failures` triggers | Evaluated after run `827120061094283` | `TRIGGERED` at 17:56:27 | "TRIGGERED, data-quality FAIL in the latest run", but the table showed only `count(check_name) = 6`, not the rows |
| Freshness WARNs | `bundle run edu_access_pipeline --only 90_validate_freshness --params freshness_as_of=2030-01-01T00:00:00` | Run `16622842542043`, 10.3 s, `SUCCESS`: 6 WARN rows, each `succeeded within <limit> days of 2030-01-01` against its real last load (enrollment and facilities 2026-10-05, poverty 2026-10-07, personnel, PSGC and HDX 2026-10-08) | None (WARN rows never fail the run) |
| `stale_sources` triggers | Evaluated after that run | `TRIGGERED` at 17:59:26 | "TRIGGERED, a source may be stale" (threaded in Gmail with the later one), again showing only a count |

**Fixed in `bbeac4a`:** with `aggregation: COUNT` on the alert, `{{QUERY_RESULT_TABLE}}` is the aggregate. Each query now returns its rows with a `COUNT(*) OVER ()` column (`fail_count`, `stale_count`), and the alert compares that column on the first row with no aggregation.

### Before the fix: the data-quality alert email shows only a count
<!-- SCREENSHOT 3-quality-alert-count-only-before-fix.png: replace this line with tmp/pr130-screenshots/3-quality-alert-count-only-before-fix.png (drag it in on GitHub) -->

### Recovery: a full run, at `4a93aca` with the default thresholds

| | Job run `746833693586021` |
|---|---|
| Whole job | 561.2 s (9 min 21 s), `SUCCESS`, no duration warning |
| Tasks | 38 `SUCCESS`, 26 disabled (Integration, Gold, and Analytics placeholders) |
| `90_validate_control` | `SUCCESS`, 8.9 s: 6 `silver_lane_succeeded` PASS |
| `90_validate_freshness` | `SUCCESS`, 5.9 s: 6 `source_fresh` PASS |
| Other non-PASS rows | 9 WARN, all `psa_poverty_stat` Silver flags (`flag_cv_over_20_*`, `flag_lower_limit_not_positive_*`, `flag_se_cv_inconsistent_*`), unchanged by this work |

Both alerts then returned to `OK` (`stale_sources` 18:11:16, `quality_failures` 18:11:24), and each sent an "OK" email.

### Alerts again, at `bbeac4a`

| Step | Run or alert | Result | Email |
|---|---|---|---|
| Failed run | `--only 90_validate_control`, run `244847351220244`, 15 s | `FAILED` | "Error in run 244847351220244" |
| Freshness WARNs | `--only 90_validate_freshness`, `freshness_as_of=2030-01-01T00:00:00`, run `754852501067810` | `SUCCESS`, 6 WARN | None |
| Failed run again | `--only 90_validate_control`, run `633922852261752`, 16 s | `FAILED`. Rerun because `quality_failures` reads only the latest run, which was the freshness run with no FAIL | "Error in run 633922852261752" |
| Both alerts | Evaluated | `quality_failures` `TRIGGERED` 18:16:25, `stale_sources` `TRIGGERED` 18:16:27 | Each lists **6 rows**: the FAILs of run `633922852261752` (layer, source, table, check, expected `succeeded`, actual `not run`), and the six stale sources of run `754852501067810` with their limit and last load date |
| Reset | `--only 90_validate_freshness`, `freshness_as_of` blank, run `387022614634972` | `SUCCESS`, 6 PASS; it is now the latest run, with no FAIL | None |
| Both alerts | Evaluated | `quality_failures` `OK` 18:20:27, `stale_sources` `OK` 18:20:25 | Each "OK" email, with an empty table |

### After the fix: the data-quality alert email lists each FAIL
<!-- SCREENSHOT 4-quality-alert-lists-rows-after-fix.png: replace this line with tmp/pr130-screenshots/4-quality-alert-lists-rows-after-fix.png (drag it in on GitHub) -->

### After the fix: the stale-source alert email lists each stale source
<!-- SCREENSHOT 5-stale-alert-lists-rows-after-fix.png: replace this line with tmp/pr130-screenshots/5-stale-alert-lists-rows-after-fix.png (drag it in on GitHub) -->

### Back to OK: the data-quality alert
<!-- SCREENSHOT 6-quality-alert-back-to-ok.png: replace this line with tmp/pr130-screenshots/6-quality-alert-back-to-ok.png (drag it in on GitHub) -->

### Back to OK: the stale-source alert
<!-- SCREENSHOT 7-stale-alert-back-to-ok.png: replace this line with tmp/pr130-screenshots/7-stale-alert-back-to-ok.png (drag it in on GitHub) -->

All emails reached the deployer's inbox only (`${workspace.current_user.userName}`), from `prod-monitoring@databricks.com` for the job and `noreply@databricks.com` for the alerts. The recipient's address is covered in the screenshots.

## What this confirms that the local tests could not (D-017)

- Spark runs the generated freshness SQL as DuckDB does: `SET VARIABLE` from `CASE … CAST(:freshness_as_of AS TIMESTAMP)`, `INTERVAL '<n>' DAY` in `VALUES`, and timestamp minus interval.
- The alert queries run on the SQL warehouse as committed, including `RANK() OVER` and `COUNT(*) OVER ()`.
- `${workspace.current_user.userName}` resolves at deploy time in both job notifications and alert subscriptions, and a `--var` override reaches `health` and `timeout_seconds`.
- Development mode pauses alert schedules and prefixes alert names with `[dev <user>]`.

## Limitations

- **Dev only.** Everything was tested on `dev`, where only the deployer is told. Telling the whole team on `prod` is #99.
- **The timeout was not made to fire.** Its setting was read back from the deployed job (`timeout_seconds` 5400) and shown in the duration email (1h 30m). A timed-out run is a failed run, and the failure email was tested.
- **`quality_failures` reads only the latest run.** A partial run (`--only`) after a failing one hides that run's FAILs until the next full run, as the rerun above shows. Scheduled and normal runs are whole runs.
- **Freshness age counts from when we loaded a batch**, not from the publisher's release date, which no source records.

## Reproduce

```bash
databricks bundle deploy --profile reached-hq --var duration_warning_seconds=60
databricks bundle run edu_access_pipeline --profile reached-hq --only 90_validate_control
databricks bundle run edu_access_pipeline --profile reached-hq --only 01_create_pipeline_runs,02_create_ingestion_batches,03_create_ingestion_batch_attempts,04_create_data_quality_results,add_control_columns,05_create_current_batches
databricks bundle run edu_access_pipeline --profile reached-hq --only 90_validate_freshness --params freshness_as_of=2030-01-01T00:00:00
databricks bundle deploy --profile reached-hq
```

Evaluate each alert from its page in the workspace, or switch its schedule to `0 * * * * ?` and unpaused with `databricks alerts-v2 update-alert <id> schedule`, then pause it again. Rerun `--only 90_validate_control` right before evaluating `quality_failures` if any other run came after it. Finish with `--only 90_validate_freshness` and a blank `freshness_as_of` so both alerts return to OK.
