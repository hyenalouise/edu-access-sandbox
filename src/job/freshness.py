"""The source freshness check, `90_validate_freshness`, generated from the job (D-043).

`90_validate_freshness` runs after the source-lane fan-in has finished, passed
or not (`run_if: ALL_DONE`), so every run records, for each source the job
loads, whether its latest succeeded batch is older than that source's limit.
A stale source is a WARN, never a FAIL: the run goes on, and the stale-source
alert in `databricks.yml` reports it.

Which sources it checks and their limits come from two reviewed files, never
typed by hand: `databricks.yml` (the Bronze loads switched on) and
`config/freshness.yml` (each source's limit and its basis). A pull request that
adds a source load must add its limit and regenerate the file; a test fails
until it does.

    python -m src.job.freshness > etl/01_control/90_validate_freshness.sql
"""

import inspect
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(inspect.currentframe().f_code.co_filename).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.job.local_run import load_job  # noqa: E402

TASK = "90_validate_freshness"
PATH = "etl/01_control/90_validate_freshness.sql"
CONFIG = "config/freshness.yml"
CONTROL = "edu_access.`01-control`"
CHECK = "source_fresh"


class FreshnessError(Exception):
    pass


def loaded_sources(job):
    """Source ids of the Bronze loads (`cli.py ingest --source X`) switched on, in job order."""
    sources = []
    for task in job["tasks"]:
        args = task.get("spark_python_task", {}).get("parameters", [])
        if args[:1] == ["ingest"] and "--source" in args and not task.get("disabled"):
            sources.append(args[args.index("--source") + 1])
    return sources


def limits(repo_root=REPO_ROOT, job=None):
    """[(source_id, max_age_days, basis)] for every source the job loads."""
    if job is None:
        _, job = load_job(repo_root)
    config = yaml.safe_load((Path(repo_root) / CONFIG).read_text(encoding="utf-8"))["sources"]
    loaded = loaded_sources(job)
    if not loaded:
        raise FreshnessError("the job loads no source to check.")
    missing = [s for s in loaded if s not in config]
    if missing:
        raise FreshnessError(f"{CONFIG} has no limit for {missing}, which the job loads.")
    strays = sorted(s for s in config if s not in loaded)
    if strays:
        raise FreshnessError(f"{CONFIG} lists {strays}, which the job does not load.")
    result = []
    for source in loaded:
        days = config[source].get("max_age_days")
        if not isinstance(days, int) or isinstance(days, bool) or days <= 0:
            raise FreshnessError(f"{source}: max_age_days must be a positive whole number of days, not {days!r}.")
        if not str(config[source].get("basis", "")).strip():
            raise FreshnessError(f"{source}: give the basis for its limit.")
        result.append((source, days, " ".join(str(config[source]["basis"]).split())))
    return result


def freshness_sql(rows):
    width = max(len(source) for source, _, _ in rows)
    listed = [f"--   {source.ljust(width)}  {days:>5} days  {basis}" for source, days, basis in rows]
    values = ",\n       ".join(f"('{source}', {days}, INTERVAL '{days}' DAY)" for source, days, _ in rows)
    return "\n".join([
        "-- Source freshness. Generated from databricks.yml and config/freshness.yml:",
        f"--   python -m src.job.freshness > {PATH}",
        "-- Do not edit by hand; tests/test_freshness.py fails if it differs.",
        "--",
        "-- Runs after the source-lane fan-in has finished, passed or not (run_if: ALL_DONE), so every run",
        "-- records one result per loaded source in data_quality_results (layer 'control'): PASS when the",
        "-- source's latest succeeded batch in current_batches succeeded within its limit, WARN when it is older",
        "-- or the source has none. It never fails the task: stale data is still correct, only possibly out of",
        "-- date. The stale-source alert in databricks.yml reports the WARN rows (D-043). Limits, with their basis:",
        *listed,
        "--",
        "-- Parameters, supplied by the job (or src/job/local_run.py):",
        "--   :run_id           the job run",
        "--   :code_revision    the commit that ran, from the job parameter; never a literal",
        "--   :freshness_as_of  blank to check as of now; a UTC timestamp to check as of that time instead",
        "--                     (how the stale-source alert is tested); text that is not a timestamp fails",
        "",
        "DECLARE OR REPLACE VARIABLE freshness_as_of_utc TIMESTAMP;",
        "SET VARIABLE freshness_as_of_utc = CASE WHEN TRIM(:freshness_as_of) = '' THEN current_timestamp()",
        "                                        ELSE CAST(:freshness_as_of AS TIMESTAMP) END;",
        "",
        f"INSERT INTO {CONTROL}.data_quality_results",
        "  (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)",
        f"SELECT :run_id, CAST(NULL AS STRING), l.source_id, 'control', 'edu_access.01-control.current_batches', '{CHECK}',",
        "       CASE WHEN b.last_succeeded_at_utc >= session.freshness_as_of_utc - l.max_age THEN 'PASS' ELSE 'WARN' END,",
        "       'succeeded within ' || CAST(l.max_age_days AS STRING) || ' days of '",
        "         || CAST(CAST(session.freshness_as_of_utc AS DATE) AS STRING),",
        "       CASE WHEN b.last_succeeded_at_utc IS NULL THEN 'no succeeded batch'",
        "            ELSE 'last succeeded ' || CAST(CAST(b.last_succeeded_at_utc AS DATE) AS STRING) END,",
        "       current_timestamp(), :code_revision",
        f"FROM (VALUES {values}) AS l(source_id, max_age_days, max_age)",
        "LEFT JOIN (",
        "  SELECT source_id, MAX(succeeded_at_utc) AS last_succeeded_at_utc",
        f"  FROM {CONTROL}.current_batches",
        "  GROUP BY source_id",
        ") AS b ON b.source_id = l.source_id;",
        "",
    ])


def main():
    try:
        sys.stdout.write(freshness_sql(limits()))
    except FreshnessError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
