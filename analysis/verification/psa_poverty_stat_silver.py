# %% [markdown]
# # PSA Poverty Stat: local Bronze-to-Silver verification on the real workbook
#
# Runs the PSA Poverty Stat lane of `edu_access_pipeline` (databricks.yml) twice on a fresh local
# DuckDB file, exactly as `python -m src.job.local_run` runs those tasks: the shared control
# bootstrap, then `05_create_psa_poverty_stat_raw` → `bronze_psa_poverty_stat` →
# `90_validate_psa_poverty_stat_raw` → `05_clean_psa_poverty_stat` → `90_validate_psa_poverty_stat_clean`.
# The other source lanes are not run (they need their own raw files and do not touch PSA).
#
# It then prints, and writes to `local_state/psa_poverty_stat_silver_verification.md` (git-ignored),
# everything the evidence record needs: Bronze rows by kind, candidates / clean / quarantined per
# estimate year, missing estimates, warning flags, the gate's results, lineage, task timings, and a
# SHA-256 of the clean and quarantine business content after each run (the run stamp excluded).
#
# Reads the approved workbook from RAW_DATA_DIR (checksum verified by the loader). Writes nothing
# outside local_state/. Results hold counts and hashes, never row values.
#
#     python analysis/verification/psa_poverty_stat_silver.py
#
# %%
import argparse
import hashlib
import inspect
import os
import platform
import sys
import time
import uuid
from pathlib import Path

REPO_ROOT = Path(inspect.currentframe().f_code.co_filename).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import duckdb  # noqa: E402

from src.ingestion.revision import resolve_code_revision  # noqa: E402
from src.ingestion.store import DuckDBStore  # noqa: E402
from src.job import local_run  # noqa: E402

SOURCE = "psa_poverty_stat"
CONTROL_TASKS = ("01_create_pipeline_runs", "02_create_ingestion_batches", "03_create_ingestion_batch_attempts",
                 "04_create_data_quality_results", "add_control_columns", "05_create_current_batches")
BRONZE = "edu_access.`02-bronze`.psa_poverty_stat_raw"
CLEAN = "edu_access.`03-silver`.psa_poverty_stat_clean"
QUARANTINE = "edu_access.`03-silver`.psa_poverty_stat_quarantine"
CONTROL = "edu_access.`01-control`"
STAMP = ("run_id", "cleaned_at_utc", "code_revision")
# The currently approved workbook, as the prompt and the profile state them; checked, not assumed.
EXPECTED = {"bronze_rows": 1641, "unit": 1612, "structural": 29, "candidates_per_year": 1612,
            "estimated_per_year": 1611, "no_estimate_per_year": 1, "cv_over_20": {"2018": 171, "2021": 84, "2023": 156},
            "se_cv_inconsistent": {"2018": 6, "2021": 133, "2023": 1}, "lower_limit_not_positive_total": 3,
            "padded_ids_per_year": 1073}


# %%
def lane_tasks(job):
    keep = [t for t in job["tasks"] if t["task_key"] in CONTROL_TASKS or SOURCE in t["task_key"]]
    keys = {t["task_key"] for t in keep}
    for t in keep:
        missing = [d["task_key"] for d in t.get("depends_on", []) if d["task_key"] not in keys]
        assert not missing, f"{t['task_key']} depends on {missing} outside the PSA lane"
    return local_run.in_order(keep)


def run_lane(job, landing, db, revision):
    run_id = str(uuid.uuid4())
    params = local_run.job_parameters(job, revision, run_id)
    results, statuses = [], {}
    for task in lane_tasks(job):
        key, kind = task["task_key"], "sql" if "sql_task" in task else "python"
        deps = [statuses[d["task_key"]] for d in task.get("depends_on", [])]
        if task.get("disabled"):
            status, detail, seconds = "disabled", "", 0.0
        elif any(s != "succeeded" for s in deps):
            status, detail, seconds = "upstream_failed", "", 0.0
        else:
            started = time.monotonic()
            try:
                if kind == "sql":
                    status, detail = local_run.run_sql(task, REPO_ROOT, db, params)
                else:
                    status, detail = local_run.run_python(task, REPO_ROOT, landing, db, params)
            except Exception as e:  # as local_run does: a crashed task is a failed task
                status, detail = "failed", local_run.failure_detail(e)
            seconds = round(time.monotonic() - started, 3)
        statuses[key] = status
        results.append((key, kind, status, seconds, detail))
    return run_id, results


def content_hash(store, table):
    """SHA-256 of every row without the run stamp, in a fixed order: same business content, same hash."""
    name = table.split(".")[-1]
    columns = [r[0] for r in store.query(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = '03-silver' "
        f"AND table_name = '{name}' ORDER BY ordinal_position") if r[0] not in STAMP]
    rows = store.query(f"SELECT {', '.join('`' + c + '`' for c in columns)} FROM {table} "
                       "ORDER BY estimate_year, source_sha256, source_row_number")
    return hashlib.sha256(repr(rows).encode("utf-8")).hexdigest(), len(rows)


# %%
def main(argv=None):
    parser = argparse.ArgumentParser(description="Local Bronze-to-Silver verification of PSA Poverty Stat.")
    parser.add_argument("--landing", default=os.environ.get("RAW_DATA_DIR"))
    parser.add_argument("--db", type=Path, default=REPO_ROOT / "local_state" / "psa_poverty_stat_silver_verification.duckdb")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "local_state" / "psa_poverty_stat_silver_verification.md")
    args = parser.parse_args(argv)
    if not args.landing:
        print("error: set RAW_DATA_DIR (or --landing) to the raw data root that holds psa/.", file=sys.stderr)
        return 3
    landing = Path(args.landing).expanduser()
    args.db.parent.mkdir(parents=True, exist_ok=True)
    for stale in (args.db, Path(str(args.db) + ".wal")):
        if stale.exists():
            stale.unlink()                     # a fresh database: run 1 must really load
    revision = resolve_code_revision(REPO_ROOT, None)
    _, job = local_run.load_job(REPO_ROOT)

    out = ["# PSA Poverty Stat Silver: local verification output", "",
           f"- code_revision: `{revision}`",
           f"- platform: {platform.platform()}, Python {platform.python_version()}, DuckDB {duckdb.__version__}",
           f"- database: fresh file `{args.db.name}`; landing: RAW_DATA_DIR", ""]
    hashes = []
    for n in (1, 2):
        run_id, results = run_lane(job, landing, args.db, revision)
        out += [f"## Run {n} (`{run_id}`)", "", "| Task | Kind | Status | Seconds | Detail |", "|---|---|---|---:|---|"]
        out += [f"| `{k}` | {kind} | {s} | {sec:.2f} | {d} |" for k, kind, s, sec, d in results]
        store = DuckDBStore(args.db)
        try:
            attempts = store.query(
                f"SELECT a.action, a.outcome, a.rows_inserted FROM {CONTROL}.ingestion_batch_attempts AS a "
                f"JOIN {CONTROL}.pipeline_runs AS r USING (run_id) "
                f"WHERE a.source_id = '{SOURCE}' AND r.job_run_id = '{run_id}'")
            out += ["", f"Bronze attempt in this run (action, outcome, rows inserted): {attempts}"]
            published = _exists(store, "psa_poverty_stat_clean")
            clean = content_hash(store, CLEAN) if published else ("(not published)", 0)
            quarantine = content_hash(store, QUARANTINE) if published else ("(not published)", 0)
            published_run = store.query(f"SELECT DISTINCT run_id FROM {CLEAN}") if published else []
        finally:
            store.close()
        hashes.append((clean, quarantine))
        out += [f"Published clean: {clean[1]} rows, content SHA-256 `{clean[0]}`; "
                f"quarantine: {quarantine[1]} rows, `{quarantine[0]}`; published run_id {published_run}", ""]
        if n == 2:
            last_run = run_id

    out += ["## Repeated full rebuild", "",
            f"Clean content identical across the two runs: **{hashes[0][0] == hashes[1][0]}**; "
            f"quarantine identical: **{hashes[0][1] == hashes[1][1]}**", ""]
    out += report(args.db, last_run)
    text = "\n".join(out) + "\n"
    args.out.write_text(text, encoding="utf-8")
    print(text)
    print(f"Written to {args.out.relative_to(REPO_ROOT)}")
    return 0


def _exists(store, table):
    return bool(store.query("SELECT 1 FROM information_schema.tables WHERE table_schema = '03-silver' "
                            f"AND table_name = '{table}'"))


def report(db, run_id):
    store = DuckDBStore(db)
    q = store.query
    lines = ["## Reconciliation after run 2", ""]

    def row(label, expected, actual):
        ok = "OK" if expected is None or str(expected) == str(actual) else "DIFF"
        lines.append(f"| {label} | {'' if expected is None else expected} | {actual} | {ok} |")

    try:
        lines += ["| Check | Expected | Actual | Result |", "|---|---|---|---|"]
        kinds = dict(q(f"SELECT source_row_kind, COUNT(*) FROM {BRONZE} AS r JOIN {CONTROL}.current_batches AS c "
                       f"ON r.batch_id = c.batch_id WHERE c.source_id = '{SOURCE}' GROUP BY 1"))
        row("current Bronze rows", EXPECTED["bronze_rows"], sum(kinds.values()))
        row("  unit", EXPECTED["unit"], kinds.get("unit", 0))
        row("  structural (title + header + region_banner + blank + footer)", EXPECTED["structural"],
            sum(v for k, v in kinds.items() if k != "unit"))
        for kind in ("title", "header", "region_banner", "blank", "footer"):
            row(f"    {kind}", None, kinds.get(kind, 0))
        clean = {str(y): n for y, n in q(f"SELECT estimate_year, COUNT(*) FROM {CLEAN} GROUP BY 1")}
        quarantined = {str(y): n for y, n in q(f"SELECT estimate_year, COUNT(*) FROM {QUARANTINE} GROUP BY 1")}
        for y in ("2018", "2021", "2023"):
            row(f"{y} candidates = clean + quarantined", EXPECTED["candidates_per_year"], clean.get(y, 0) + quarantined.get(y, 0))
            row(f"{y} clean", None, clean.get(y, 0))
            row(f"{y} quarantined", 0, quarantined.get(y, 0))
            stats = store.records(
                f"SELECT COUNT_IF(estimate_status = 'estimated') AS estimated, COUNT_IF(estimate_status = 'no_estimate') AS no_estimate, "
                "COUNT_IF(estimate_status = 'partial_estimate') AS partial, COUNT_IF(cv_over_20) AS cv, "
                "COUNT_IF(se_cv_inconsistent) AS se, COUNT_IF(lower_limit_not_positive) AS lower, "
                "COUNT_IF(poverty_incidence IS NULL) AS null_incidence "
                f"FROM {CLEAN} WHERE estimate_year = {y}")[0]
            row(f"{y} estimated", EXPECTED["estimated_per_year"], stats["estimated"])
            row(f"{y} no_estimate (Kalayaan)", EXPECTED["no_estimate_per_year"], stats["no_estimate"])
            row(f"{y} partial_estimate", 0, stats["partial"])
            row(f"{y} NULL poverty incidence", EXPECTED["no_estimate_per_year"], stats["null_incidence"])
            row(f"{y} cv_over_20", EXPECTED["cv_over_20"][y], stats["cv"])
            row(f"{y} se_cv_inconsistent", EXPECTED["se_cv_inconsistent"][y], stats["se"])
            row(f"{y} lower_limit_not_positive", None, stats["lower"])
            row(f"{y} IDs padded from 5 digits", EXPECTED["padded_ids_per_year"], q(
                f"SELECT COUNT(*) FROM {CLEAN} AS c JOIN {BRONZE} AS b ON c.source_sha256 = b.source_sha256 "
                f"AND c.source_row_number = b.source_row_number WHERE c.estimate_year = {y} AND length(b.`PSGC ID`) = 5 "
                "AND c.psgc_id = '0' || b.`PSGC ID`")[0][0])
        row("lower_limit_not_positive, all years", EXPECTED["lower_limit_not_positive_total"],
            q(f"SELECT COUNT_IF(lower_limit_not_positive) FROM {CLEAN}")[0][0])
        kalayaan = store.records(f"SELECT estimate_year, psgc_id, municipality, estimate_status, poverty_incidence "
                                 f"FROM {CLEAN} WHERE estimate_status = 'no_estimate' ORDER BY 1")
        row("no_estimate rows are Excel row 641 (Kalayaan)", "3",
            q(f"SELECT COUNT(*) FROM {CLEAN} WHERE estimate_status = 'no_estimate' AND source_row_number = 641")[0][0])
        row("lineage: clean rows that join their current Bronze unit row", sum(clean.values()), q(
            f"SELECT COUNT(*) FROM {CLEAN} AS c JOIN {BRONZE} AS b ON c.source_sha256 = b.source_sha256 "
            "AND c.source_row_number = b.source_row_number AND c.batch_id = b.batch_id AND b.source_row_kind = 'unit' "
            "AND c.psgc_id = lpad(b.`PSGC ID`, 6, '0')")[0][0])
        row("key (psgc_id, estimate_year) duplicates", 0,
            q(f"SELECT COUNT(*) - COUNT(DISTINCT (psgc_id, estimate_year)) FROM {CLEAN}")[0][0])
        row("distinct cleaned_at_utc across both tables", 1,
            q(f"SELECT COUNT(DISTINCT t) FROM (SELECT cleaned_at_utc AS t FROM {CLEAN} UNION ALL "
              f"SELECT cleaned_at_utc FROM {QUARANTINE})")[0][0])
        lines += ["", f"No-estimate rows: {[(r['estimate_year'], r['psgc_id'], r['municipality']) for r in kalayaan]}"]

        results = store.records(f"SELECT check_name, status, expected, actual FROM {CONTROL}.data_quality_results "
                                f"WHERE run_id = '{run_id}' AND source_id = '{SOURCE}' AND layer = 'silver' ORDER BY check_name")
        by_status = {}
        for r in results:
            by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        lines += ["", "## Silver gate results of run 2", "", f"{len(results)} results: {by_status}", "",
                  "| Check | Status | Expected | Actual |", "|---|---|---|---|"]
        lines += [f"| `{r['check_name']}` | {r['status']} | {r['expected']} | {r['actual']} |" for r in results]
        runs = store.records(f"SELECT run_id, status, failure_stage, code_revision, started_at_utc, finished_at_utc "
                             f"FROM {CONTROL}.pipeline_runs WHERE pipeline_name = 'silver_build' AND source_id = '{SOURCE}' "
                             "ORDER BY started_at_utc")
        lines += ["", "## silver_build runs", "", "| run_id | status | failure_stage | code_revision | started | finished |",
                  "|---|---|---|---|---|---|"]
        lines += [f"| `{r['run_id']}` | {r['status']} | {r['failure_stage']} | `{r['code_revision'][:12]}` | "
                  f"{r['started_at_utc']} | {r['finished_at_utc']} |" for r in runs]
    finally:
        store.close()
    return lines


# %%
if __name__ == "__main__":
    sys.exit(main())
