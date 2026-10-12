"""Reads and writes of the control tables in `01-control` (etl/01_control/).

Each function is one statement: a MERGE for current state (pipeline_runs,
ingestion_batches), an INSERT for the append-only logs (attempts, data-quality
results). Values reach SQL only through staged rows, never pasted into the
statement, so an error message with a quote in it cannot break a write.
"""

from pathlib import Path

from src.ingestion.store import table_name

SCHEMA = "01-control"
RUNS = "pipeline_runs"
BATCHES = "ingestion_batches"
ATTEMPTS = "ingestion_batch_attempts"
DQ = "data_quality_results"


# Columns added after the tables were first created on Databricks (2026-10-06):
# for sources whose deliveries cover estimate years instead of one school year
# (D-018), and the job run that links a load to its Bronze gate task (D-020).
# A fresh table gets them from its CREATE statement; an existing one gets them
# here, before the views that read them are replaced. Additive and nullable, so
# rows already written keep their meaning (NULL: not a workbook delivery, or not
# a job run).
ADDED_COLUMNS = {
    "ingestion_batches": [("logical_dataset", "STRING"), ("estimate_years_covered", "STRING"), ("source_sheet", "STRING")],
    "ingestion_batch_attempts": [("logical_dataset", "STRING"), ("estimate_years_covered", "STRING")],
    "pipeline_runs": [("job_run_id", "STRING")],
}


def create_tables(store, repo_root):
    """Create the control tables, add any later columns, then (re)create the views."""
    files = sorted((Path(repo_root) / "etl" / "01_control").glob("[0-8]*.sql"))
    views = [p for p in files if "CREATE OR REPLACE VIEW" in p.read_text(encoding="utf-8")]
    for path in files:
        if path not in views:
            store.run_file(path)
    add_missing_columns(store)
    for path in views:
        store.run_file(path)


def add_missing_columns(store):
    """Databricks has no ADD COLUMN IF NOT EXISTS, so check first. In the job this runs once,
    as its own task (`cli.py columns`), before the views are replaced and the lanes fan out."""
    for table, columns in ADDED_COLUMNS.items():
        existing = {name for name, _ in store.columns(SCHEMA, table)}
        for name, kind in columns:
            if name not in existing:
                store.sql(f"ALTER TABLE {table_name(SCHEMA, table)} ADD COLUMN `{name}` {kind}")


def _complete(columns, rows):
    """Supply NULL for unnamed nullable columns so staged inserts match the live table.

    Matched upserts update only fields named by the caller, so these staged NULLs
    cannot erase values written to newer columns by another deployment.
    """
    return [{column: row.get(column) for column, _ in columns} for row in rows]


def _upsert(store, table, key, row):
    columns = store.columns(SCHEMA, table)
    store.stage(f"{table}_stage", columns, _complete(columns, [row]))
    named = {name for name in row}
    updates = [name for name, _ in columns if name in named and name != key]
    if not updates:
        updates = [key]
    assignments = ", ".join(f"`{name}` = s.`{name}`" for name in updates)
    store.sql(
        f"MERGE INTO {table_name(SCHEMA, table)} AS t USING {table}_stage AS s ON t.{key} = s.{key} "
        f"WHEN MATCHED THEN UPDATE SET {assignments} WHEN NOT MATCHED THEN INSERT *"
    )


def _append(store, table, rows):
    if not rows:
        return
    columns = store.columns(SCHEMA, table)
    store.stage(f"{table}_stage", columns, _complete(columns, rows))
    names = ", ".join(f"`{c}`" for c, _ in columns)
    store.sql(f"INSERT INTO {table_name(SCHEMA, table)} ({names}) SELECT {names} FROM {table}_stage")


def save_run(store, row):
    _upsert(store, RUNS, "run_id", row)


def save_batch(store, row):
    _upsert(store, BATCHES, "batch_id", row)


def add_attempt(store, row):
    _append(store, ATTEMPTS, [row])


def add_checks(store, rows):
    _append(store, DQ, rows)


def find_batch(store, archive_sha256):
    rows = store.records(
        f"SELECT * FROM {table_name(SCHEMA, BATCHES)} WHERE archive_sha256 = '{archive_sha256}'")
    return rows[0] if rows else None


def succeeded_years(store, source_id):
    rows = store.query(
        f"SELECT DISTINCT school_year FROM {table_name(SCHEMA, BATCHES)} "
        f"WHERE source_id = '{source_id}' AND status = 'succeeded'")
    return {r[0] for r in rows}


def succeeded_estimate_years(store, source_id):
    rows = store.query(
        f"SELECT DISTINCT estimate_years_covered FROM {table_name(SCHEMA, BATCHES)} "
        f"WHERE source_id = '{source_id}' AND status = 'succeeded' AND estimate_years_covered IS NOT NULL")
    return {year for (label,) in rows for year in label.split(",")}
