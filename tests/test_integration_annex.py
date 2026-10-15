"""DepEd annex-to-mother Integration map and gate, using only made-up rows."""

import pytest

from src.ingestion.store import DuckDBStore

REVISION = "a" * 40
RUN_ID = "annex-test-run"
MAP = "edu_access.`04-integration`.deped_annex_mother_map"
CONTROL = "edu_access.`01-control`.data_quality_results"


@pytest.fixture
def store(repo_root):
    db = DuckDBStore()
    for schema in ("01-control", "03-silver", "04-integration"):
        db.sql(f"CREATE SCHEMA edu_access.`{schema}`")
    db.sql("""
        CREATE TABLE edu_access.`01-control`.data_quality_results (
          run_id STRING, batch_id STRING, source_id STRING, layer STRING, table_name STRING,
          check_name STRING, status STRING, expected STRING, actual STRING,
          checked_at_utc TIMESTAMP, code_revision STRING
        )
    """)
    db.sql("""
        CREATE TABLE edu_access.`03-silver`.deped_enrollment_clean (
          school_year STRING, school_id STRING, annex_status STRING, batch_id STRING,
          source_sha256 STRING, source_row_number BIGINT
        )
    """)
    db.sql("""
        INSERT INTO edu_access.`03-silver`.deped_enrollment_clean
        VALUES
          ('2023-24', '900001', 'Annex/Extension School', 'batch-1', 'hash-1', 1),
          ('2023-24', '900002', 'Mother School', 'batch-1', 'hash-1', 2),
          ('2024-25', '900001', 'Annex/Extension School', 'batch-2', 'hash-2', 1)
    """)
    params = {"run_id": RUN_ID, "code_revision": REVISION}
    db.run_file(repo_root / "etl" / "04_integration" / "04_map_deped_annex_mother.sql", params)
    db.run_file(repo_root / "etl" / "04_integration" / "90_validate_deped_annex_mother_map.sql", params)
    return db


def test_every_annex_year_is_listed_without_an_invented_match(store):
    rows = store.records(f"SELECT * FROM {MAP} ORDER BY school_year")
    assert [(row["school_year"], row["annex_school_id"]) for row in rows] == [("2023-24", "900001"), ("2024-25", "900001")]
    assert all(row["mother_school_id"] is None and row["match_method"] is None for row in rows)
    assert all(row["match_status"] == "unmatched" and row["evidence"] == "deped_enrollment_annex_status_only" for row in rows)


def test_gate_records_the_unmatched_count_and_no_failures(store):
    checks = {row[0]: (row[1], row[2]) for row in store.query(
        f"SELECT check_name, status, actual FROM {CONTROL} WHERE run_id = '{RUN_ID}'")}
    assert checks["annexes_without_mother_school"] == ("WARN", "2")
    assert checks["rows_reconcile"] == ("PASS", "2")
    assert not [check for check, (status, _) in checks.items() if status == "FAIL"]
