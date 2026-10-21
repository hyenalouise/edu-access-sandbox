"""The public-only DepEd workbook (deped_psgc_coordinates) loads through the same xlsx_report pipeline.

A separate file from deped_enrollment_psgc's: the same layout and schema v1, a sector note in A6, and public
schools only. Every test builds made-up workbooks (tests/factories/report_workbooks.py) and runs the real etl/
SQL on an in-memory DuckDB. No row of the real workbook is used.
"""

import pytest

from factories.deped_deliveries import fake_repo, write_config
from factories.report_workbooks import (
    COORDINATES, PUBLIC_ONLY, PUBLIC_ONLY_TITLE, approve, coordinates_config, make_workbook, real_config,
    school,
)
from src.ingestion.contract import load_source_config
from src.ingestion.pipeline import IngestionRun
from src.ingestion.store import DuckDBStore
from src.ingestion.validate import WARN
from src.ingestion.xlsx_report import period_from_name

REVISION = "e" * 40
BRONZE = "edu_access.`02-bronze`.deped_psgc_coordinates_raw"
CONTROL = "edu_access.`01-control`"
ROWS = {9: school(100001), 10: school(100002, lon=("error", "#N/A"), lat=("error", "#N/A"))}
COUNTS = dict(row_count=2, unit_rows=2, blank_rows=0, no_identifier_rows=0, last_row=10)


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


class Env:
    def __init__(self, tmp_path):
        self.config = coordinates_config()
        self.landing = tmp_path / "landing"
        self.inbox = self.landing / "deped" / "original"
        self.repo = fake_repo(tmp_path / "repo", self.config)
        self.store = DuckDBStore()

    def deliver(self, rows=ROWS, folder=None, title=PUBLIC_ONLY_TITLE, **counts):
        path = make_workbook(folder or self.inbox, rows=rows, name=PUBLIC_ONLY, title=title)
        approve(self.config, path, title=title, **{**COUNTS, **counts})
        write_config(self.repo, self.config)
        return path

    def run(self):
        return IngestionRun(self.store, self.repo, COORDINATES, self.landing, "local", REVISION).execute()

    def q(self, sql):
        return self.store.query(sql)


def test_real_contract_pins_the_public_only_workbook(repo_root):
    config, entry = load_source_config(repo_root, COORDINATES)
    (d,) = config["deliveries"]
    assert (d["workbook"], d["workbook_sha256"][:12]) == (PUBLIC_ONLY, "edf7ba68cb76")
    assert (d["row_count"], d["unit_rows"], d["blank_rows"], d["no_identifier_rows"], d["range"]) == (
        47818, 47818, 0, 0, "A1:CJ47826")
    assert d["title_cells"]["A6"] == "SECTOR: PUBLIC ONLY"
    assert config["bronze_table"] == "deped_psgc_coordinates_raw" and entry["status"] == "accepted"
    # The same 88 columns as the all-sector workbook, so Silver can read both alike.
    assert config["schema_versions"] == real_config()["schema_versions"]


def test_the_two_deped_workbooks_are_told_apart_by_name():
    coordinates, everything = coordinates_config(), real_config()
    all_sector = "SY 2023-2024 School Level Data on Enrollment with PSGC, Longitude and Latitude.xlsx"
    assert period_from_name(coordinates, PUBLIC_ONLY) == "2023-24"
    assert period_from_name(coordinates, all_sector) is None
    assert period_from_name(everything, PUBLIC_ONLY) is None


def test_load_reconciles_and_a_rerun_adds_nothing(env):
    env.deliver()
    assert env.run().status == "succeeded"
    assert env.q(f"SELECT source_row_number, school_id, sector, longitude, source_file FROM {BRONZE} ORDER BY 1") == [
        (9, "100001", "Public", "120.5", PUBLIC_ONLY), (10, "100002", "Public", "#N/A", PUBLIC_ONLY)]
    assert env.run().status == "succeeded"
    assert env.q(f"SELECT COUNT(*) FROM {BRONZE}") == [(2,)]
    assert env.q(f"SELECT school_year, delivery_version FROM {CONTROL}.current_batches") == [("2023-24", 1)]


def test_a_row_that_is_not_public_is_kept_and_warned(env):
    private = school(400001)
    private[10] = "Private"
    env.deliver(rows={9: school(100001), 10: private})
    assert env.run().status == "succeeded"
    assert env.q(f"SELECT sector FROM {BRONZE} ORDER BY source_row_number") == [("Public",), ("Private",)]
    assert env.q(f"SELECT status, actual FROM {CONTROL}.data_quality_results "
                 "WHERE check_name = 'dq_sector_not_public'") == [(WARN, "1")]


def test_a_workbook_without_the_public_only_note_is_refused(env):
    """Same name, but row 6 no longer says the file is public only: a different delivery, never loaded unseen."""
    path = make_workbook(env.inbox, rows=ROWS, name=PUBLIC_ONLY)
    approve(env.config, path, title=PUBLIC_ONLY_TITLE, **COUNTS)
    write_config(env.repo, env.config)
    assert env.run().status == "failed"
    assert env.q(f"SELECT error_code FROM {CONTROL}.ingestion_batches") == [("title_changed",)]
    assert env.q(f"SELECT COUNT(*) FROM {BRONZE}") == [(0,)]


def test_a_changed_file_for_the_loaded_year_is_blocked_as_a_revision(env):
    env.deliver()
    env.run()
    make_workbook(env.inbox / "resent", rows={**ROWS, 9: school(100001, learners=2)}, name=PUBLIC_ONLY,
                  title=PUBLIC_ONLY_TITLE)
    assert env.run().status == "failed"
    assert env.q(f"SELECT status, load_type, error_code FROM {CONTROL}.ingestion_batches WHERE status <> 'succeeded'") == [
        ("blocked", "revision", "checksum_mismatch")]
    assert env.q(f"SELECT COUNT(*) FROM {BRONZE}") == [(2,)]


def test_a_missing_approved_workbook_fails_the_run(env):
    """An approved file that is not in the landing folder fails the lane, so an empty Bronze table
    never passes for a loaded one (as for PSGC, require_approved_deliveries)."""
    path = env.deliver()
    path.unlink()
    summary = env.run()
    assert summary.status == "failed" and summary.missing_deliveries == [PUBLIC_ONLY]
    assert env.q(f"SELECT status FROM {CONTROL}.data_quality_results WHERE check_name = 'approved_deliveries_present'") == [
        ("FAIL",)]
    assert env.q(f"SELECT COUNT(*) FROM {BRONZE}") == [(0,)]
