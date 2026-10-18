# %% [markdown]
# # PSA school-age population: local Bronze-to-Silver verification on the real workbooks
#
# Runs the school-age population lane of `edu_access_pipeline` (databricks.yml) twice on a fresh local
# DuckDB file, exactly as `python -m src.job.local_run` runs those tasks: the shared control bootstrap,
# then `08_create_psa_school_age_population_raw` → `bronze_psa_school_age_population` →
# `90_validate_psa_school_age_population_raw` → `08_clean_psa_school_age_population` →
# `90_validate_psa_school_age_population_clean`. The other source lanes and the Integration map are not
# run (they need their own raw files, and the map is still a placeholder, #159).
#
# It then prints, and writes to `local_state/psa_school_age_population_silver_verification.md`
# (git-ignored), everything the evidence record needs (#158): Bronze rows by kind, the reconciliation of
# Silver cells to Bronze count cells per sheet, the places per level, zero cells, places whose two
# concepts are equal, national totals by age, the gate's results, lineage, task timings, and a SHA-256 of
# the clean and quarantine business content after each run (the run stamp excluded). Each expected value
# is the profile's (docs/data/source-inventory/psa_school_age_population/profile.md) or the issue's.
#
# Reads the approved workbooks from RAW_DATA_DIR (checksums verified by the loader). Writes nothing
# outside local_state/. Results hold counts and hashes, never row values.
#
#     python analysis/verification/psa_school_age_population_silver.py
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

SOURCE = "psa_school_age_population"
CONTROL_TASKS = ("01_create_pipeline_runs", "02_create_ingestion_batches", "03_create_ingestion_batch_attempts",
                 "04_create_data_quality_results", "add_control_columns", "05_create_current_batches")
BRONZE = "edu_access.`02-bronze`.psa_school_age_population_raw"
CLEAN = "edu_access.`03-silver`.psa_school_age_population_clean"
QUARANTINE = "edu_access.`03-silver`.psa_school_age_population_quarantine"
CONTROL = "edu_access.`01-control`"
STAMP = ("run_id", "cleaned_at_utc", "code_revision")
SHEETS = (("2020", "total"), ("2020", "household"), ("2024", "total"), ("2024", "household"))
# The approved workbooks, as the profile and the issue state them; checked, not assumed.
EXPECTED = {
    "bronze_rows": {"2020": 3496, "2024": 13985},
    "cells": {"2020": 104520, "2024": 104640},
    "levels": {"2020": "country 1, region 17, province 82, city_municipality 1642",
               "2024": "country 1, region 18, province 83, city_municipality 1642"},
    # Profile O-7: the SGA (2020 INTERIM PROVINCE, 2024 SPECIAL GEOGRAPHIC AREA) and the eight 2020 clusters under it.
    "statuses": {"2020": "special_geographic_area 1, sga_cluster 8", "2024": "special_geographic_area 1, sga_cluster 0"},
    "zero_cells": {("2020", "total"): 21, ("2020", "household"): 24, ("2024", "total"): 7, ("2024", "household"): 7},
    "equal_places": {"2020": 366, "2024": 771},
    "national_5_24": {("2020", "total"): 42869567, ("2020", "household"): 42776570,
                      ("2024", "total"): 42178032, ("2024", "household"): 42098435},
    "national_5_17_total": {"2020": 28680299, "2024": 27569038},
    "national_by_age_total": {
        "2020": "2173620,2212845,2289672,2284473,2310027,2231835,2262827,2266206,2182926,2147568,2146923,2099597,"
                "2071780,2013745,2150770,2153992,1985173,2005151,1916272,1964165",
        "2024": "1976261,1973091,1995347,2121852,2126160,2119748,2177223,2230686,2201987,2188426,2209494,2175497,"
                "2073266,2125779,2132241,2082628,2037875,1970049,2081275,2179147"},
    "footnotes": {("2024", "total"): 11, ("2024", "household"): 10},
    "cities_under_region": 35,
}


# %%
def lane_tasks(job):
    keep = [t for t in job["tasks"] if t["task_key"] in CONTROL_TASKS
            or (SOURCE in t["task_key"] and "_map" not in t["task_key"] and "psgc" not in t["task_key"])]
    keys = {t["task_key"] for t in keep}
    for t in keep:
        missing = [d["task_key"] for d in t.get("depends_on", []) if d["task_key"] not in keys]
        assert not missing, f"{t['task_key']} depends on {missing} outside the school-age population lane"
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
                       "ORDER BY census_year, source_sheet, source_row_number, sex, age")
    return hashlib.sha256(repr(rows).encode("utf-8")).hexdigest(), len(rows)


# %%
def main(argv=None):
    parser = argparse.ArgumentParser(description="Local Bronze-to-Silver verification of PSA school-age population.")
    parser.add_argument("--landing", default=os.environ.get("RAW_DATA_DIR"))
    parser.add_argument("--db", type=Path, default=REPO_ROOT / "local_state" / "psa_school_age_population_silver_verification.duckdb")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "local_state" / "psa_school_age_population_silver_verification.md")
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

    out = ["# PSA school-age population Silver: local verification output", "",
           f"- code_revision: `{revision}`",
           f"- platform: {platform.platform()}, Python {platform.python_version()}, DuckDB {duckdb.__version__}",
           f"- database: fresh file `{args.db.name}`; landing: RAW_DATA_DIR", ""]
    hashes, last_run = [], None
    for n in (1, 2):
        run_id, results = run_lane(job, landing, args.db, revision)
        out += [f"## Run {n} (`{run_id}`)", "", "| Task | Kind | Status | Seconds | Detail |", "|---|---|---|---:|---|"]
        out += [f"| `{k}` | {kind} | {s} | {sec:.2f} | {d} |" for k, kind, s, sec, d in results]
        store = DuckDBStore(args.db)
        try:
            attempts = store.query(
                f"SELECT a.action, a.outcome, a.rows_inserted FROM {CONTROL}.ingestion_batch_attempts AS a "
                f"JOIN {CONTROL}.pipeline_runs AS r USING (run_id) "
                f"WHERE a.source_id = '{SOURCE}' AND r.job_run_id = '{run_id}' ORDER BY 1, 2, 3")
            out += ["", f"Bronze attempts in this run (action, outcome, rows inserted): {attempts}"]
            published = _exists(store, "psa_school_age_population_clean")
            clean = content_hash(store, CLEAN) if published else ("(not published)", 0)
            quarantine = content_hash(store, QUARANTINE) if published else ("(not published)", 0)
            published_run = store.query(f"SELECT DISTINCT run_id FROM {CLEAN}") if published else []
        finally:
            store.close()
        hashes.append((clean, quarantine))
        out += [f"Published clean: {clean[1]} rows, content SHA-256 `{clean[0]}`; "
                f"quarantine: {quarantine[1]} rows, `{quarantine[0]}`; published run_id {published_run}", ""]
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
        current = f"JOIN {CONTROL}.current_batches AS c ON r.batch_id = c.batch_id WHERE c.source_id = '{SOURCE}'"
        for year in ("2020", "2024"):
            kinds = dict(q(f"SELECT source_row_kind, COUNT(*) FROM {BRONZE} AS r {current} AND r.census_year = '{year}' GROUP BY 1"))
            row(f"{year} current Bronze rows", EXPECTED["bronze_rows"][year], sum(kinds.values()))
            lines.append(f"| {year} Bronze rows by kind | | {dict(sorted(kinds.items()))} | |")
        results = {(r["check_name"], r["census_year"]): r for r in store.records(
            f"SELECT d.check_name, d.status, d.expected, d.actual, b.census_year FROM {CONTROL}.data_quality_results AS d "
            f"LEFT JOIN (SELECT DISTINCT batch_id, census_year FROM {BRONZE}) AS b ON b.batch_id = d.batch_id "
            f"WHERE d.run_id = '{run_id}' AND d.source_id = '{SOURCE}' AND d.layer = 'silver'")}
        for year, concept in SHEETS:
            where = f"census_year = {year} AND population_concept = '{concept}'"
            n = q(f"SELECT COUNT(*) FROM {CLEAN} WHERE {where}")[0][0]
            quarantined = q(f"SELECT COUNT(*) FROM {QUARANTINE} WHERE {where}")[0][0]
            row(f"{year} {concept}: Silver cells = Bronze count cells", EXPECTED["cells"][year], n + quarantined)
            row(f"{year} {concept}: quarantined", 0, quarantined)
            row(f"{year} {concept}: places per level", EXPECTED["levels"][year],
                results.get((f"levels_match_expected_{concept}", year), {}).get("actual"))
            row(f"{year} {concept}: places per place_status (O-7)", EXPECTED["statuses"][year],
                results.get((f"place_status_match_expected_{concept}", year), {}).get("actual"))
            row(f"{year} {concept}: places flagged special", None, ", ".join(
                f"{name} ({status})" for name, status in q(
                    f"SELECT DISTINCT place_name, place_status FROM {CLEAN} WHERE {where} "
                    "AND place_status <> 'standard' ORDER BY place_status, place_name")))
            row(f"{year} {concept}: places whose counts are all 0", 0,
                results.get((f"no_all_zero_place_{concept}", year), {}).get("actual"))
            row(f"{year} {concept}: zero cells (Kalayaan, O-3)", EXPECTED["zero_cells"][(year, concept)],
                q(f"SELECT COUNT(*) FROM {CLEAN} WHERE {where} AND population = 0")[0][0])
            row(f"{year} {concept}: zero cells outside Kalayaan", 0,
                q(f"SELECT COUNT(*) FROM {CLEAN} WHERE {where} AND population = 0 AND place_name <> 'KALAYAAN'")[0][0])
            row(f"{year} {concept}: national, both sexes, ages 5-24", EXPECTED["national_5_24"][(year, concept)],
                q(f"SELECT SUM(population) FROM {CLEAN} WHERE {where} AND level = 'country' AND sex = 'both'")[0][0])
            if concept == "total":
                row(f"{year} total: national, both sexes, ages 5-17 (O-8)", EXPECTED["national_5_17_total"][year],
                    q(f"SELECT SUM(population) FROM {CLEAN} WHERE {where} AND level = 'country' AND sex = 'both' "
                      "AND age <= 17")[0][0])
                row(f"{year} total: national by age (O-8)", EXPECTED["national_by_age_total"][year],
                    results.get(("national_both_sexes_by_age_total", year), {}).get("actual"))
            row(f"{year} {concept}: places with a footnote marker (O-6)", EXPECTED["footnotes"].get((year, concept), 0),
                results.get((f"rule_footnote_split_{concept}", year), {}).get("actual"))
            row(f"{year} {concept}: places flagged capital", None,
                results.get((f"rule_capital_flagged_{concept}", year), {}).get("actual"))
            row(f"{year} {concept}: places with an old name or abbreviation", None,
                results.get((f"rule_old_name_split_{concept}", year), {}).get("actual"))
            row(f"{year} {concept}: cities and municipalities directly under their region (O-2)",
                EXPECTED["cities_under_region"],
                q(f"SELECT COUNT(DISTINCT place_row_number) FROM {CLEAN} WHERE {where} "
                  "AND level = 'city_municipality' AND province_name IS NULL")[0][0])
            row(f"{year} {concept}: repeated (place_name, parent_name) keys", 0,
                q(f"SELECT COUNT(*) FROM (SELECT place_name, parent_name, sex, age FROM {CLEAN} WHERE {where} "
                  "GROUP BY ALL HAVING COUNT(*) > 1)")[0][0])
        for year in ("2020", "2024"):
            row(f"{year}: places whose two concepts are equal (O-5)", EXPECTED["equal_places"][year],
                results.get(("places_with_equal_concepts", year), {}).get("actual"))
            row(f"{year}: household above total (O-5)", 0,
                results.get(("household_not_above_total", year), {}).get("actual"))
        row("lineage: clean rows that join their current Bronze row", q(f"SELECT COUNT(*) FROM {CLEAN}")[0][0], q(
            f"SELECT COUNT(*) FROM {CLEAN} AS s JOIN {BRONZE} AS b ON s.source_sha256 = b.source_sha256 "
            "AND s.source_sheet = b.source_sheet AND s.source_row_number = b.source_row_number "
            "AND s.batch_id = b.batch_id")[0][0])
        row("distinct cleaned_at_utc across both tables", 1,
            q(f"SELECT COUNT(DISTINCT t) FROM (SELECT cleaned_at_utc AS t FROM {CLEAN} UNION ALL "
              f"SELECT cleaned_at_utc FROM {QUARANTINE})")[0][0])

        records = store.records(f"SELECT d.check_name, d.batch_id, d.status, d.expected, d.actual "
                                f"FROM {CONTROL}.data_quality_results AS d WHERE d.run_id = '{run_id}' "
                                f"AND d.source_id = '{SOURCE}' AND d.layer = 'silver' ORDER BY d.check_name, d.batch_id")
        by_status = {}
        for r in records:
            by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        lines += ["", "## Silver gate results of run 2", "", f"{len(records)} results: {by_status}", "",
                  "| Check | Census year | Status | Expected | Actual |", "|---|---|---|---|---|"]
        lines += [f"| `{r['check_name']}` | {r['batch_id'].split('__')[1] if r['batch_id'] else ''} | {r['status']} | "
                  f"{r['expected']} | {r['actual']} |" for r in records]
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
