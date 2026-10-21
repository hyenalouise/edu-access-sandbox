"""DepEd EMISD enrollment with PSGC loads through the same pipeline, from its own contract (format xlsx_report).

Every test builds made-up workbooks (tests/factories/report_workbooks.py), approves
them into a copy of the real deped_enrollment_psgc contract inside a throwaway
repository root, and runs the real etl/ SQL on an in-memory DuckDB. No row of the
real workbook, raw file, or credential is used.
"""

import copy

import pytest

from factories.deped_deliveries import fake_repo, write_config
from factories.report_workbooks import (
    FIXTURE_COUNTS, FIXTURE_QUALITY, approve, default_rows, empty_config, headers, make_workbook, real_config,
    registry_entry, school, titles, workbook_name,
)
from src.ingestion import formats
from src.ingestion.contract import load_source_config, validate_config
from src.ingestion.errors import IngestionError
from src.ingestion.pipeline import IngestionRun
from src.ingestion.store import DuckDBStore
from src.ingestion.validate import FAIL, PASS, WARN
from src.ingestion.xlsx_report import PROVENANCE_COLUMNS, period_from_name, prepare_delivery

REVISION = "e" * 40
SOURCE = "deped_enrollment_psgc"
BRONZE = "edu_access.`02-bronze`.deped_enrollment_psgc_raw"
CONTROL = "edu_access.`01-control`"


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


class Env:
    def __init__(self, tmp_path):
        self.config = empty_config()
        self.landing = tmp_path / "landing"
        self.inbox = self.landing / "deped" / "original"
        self.repo = fake_repo(tmp_path / "repo", self.config)
        self.store = DuckDBStore()

    def deliver(self, approve_kwargs=None, **kwargs):
        path = make_workbook(self.inbox, **kwargs)
        approve(self.config, path, **(approve_kwargs or {}))
        write_config(self.repo, self.config)
        return path

    def run(self):
        return IngestionRun(self.store, self.repo, SOURCE, self.landing, "local", REVISION).execute()

    def q(self, sql):
        return self.store.query(sql)


def prepared(tmp_path, approve_kwargs=None, **kwargs):
    config = empty_config()
    path = make_workbook(tmp_path, **kwargs)
    approve(config, path, **(approve_kwargs or {}))
    return prepare_delivery(config, registry_entry(), path)


def checks(p):
    return {c.check_name: c for c in p.checks}


def refused(code, fn, *args):
    with pytest.raises(IngestionError) as e:
        fn(*args)
    assert e.value.code == code, e.value
    return e.value


# --- The real contract ----------------------------------------------------------

def test_real_contract_loads_and_stays_profiled(repo_root):
    config, entry = load_source_config(repo_root, SOURCE)
    assert config["format"] == "xlsx_report"
    assert [d["school_year"] for d in config["deliveries"]] == ["2023-24"]
    assert entry["status"] == "accepted", "accepted by the team on 2026-10-21 (D-063); a status change is a team decision"


def test_real_contract_pins_the_profiled_shape(repo_root):
    """The approved counts are the profile's: 60,285 rows below the header (profile O-1, O-2)."""
    config, _ = load_source_config(repo_root, SOURCE)
    d = config["deliveries"][0]
    assert (d["row_count"], d["unit_rows"], d["blank_rows"], d["no_identifier_rows"]) == (60285, 60275, 9, 1)
    assert d["range"] == "A1:CJ60293" and config["header_row"] == 8
    columns = config["schema_versions"]["v1"]["columns"]
    assert len(columns) == 88
    # Columns AA and AB share a header in the workbook but not a Bronze name (profile O-8).
    headers_ = config["schema_versions"]["v1"]["source_headers"]
    assert headers_[26] == headers_[27] and columns[26:28] == ["income_class", "income_class_long"]


# --- A delivery that matches its approval ---------------------------------------------

def test_every_row_below_the_header_is_kept_with_its_kind(tmp_path):
    p = prepared(tmp_path)
    assert [n for n, _ in p.rows] == list(range(9, 16))   # row 14 is blank in the file and still a row
    assert p.row_kinds == {9: "unit", 10: "unit", 11: "unit", 12: "unit", 13: "no_identifier", 14: "blank", 15: "unit"}
    assert p.school_year == "2023-24" and p.schema_version == "v1"
    assert all(c.status == PASS for c in p.checks), [c for c in p.checks if c.status != PASS]


def test_values_stay_exactly_as_stored(tmp_path):
    rows = dict(prepared(tmp_path).rows)
    columns = real_config()["schema_versions"]["v1"]["columns"]
    row9, row10 = dict(zip(columns, rows[9])), dict(zip(columns, rows[10]))
    assert row9["psgc_barangay"] == "102802013"            # lost its leading zero; never padded (O-5)
    assert row10["psgc_barangay"] == "1380100001"
    assert row10["longitude"] == "#N/A"                    # an error cell's text (O-10)
    assert row10["income_class"] == "1St"                  # as published (O-8)
    assert row9["longitude"] == "120.5" and row9["k_male"] == "1"
    assert set(rows[14]) == {""}                           # a blank row is '' everywhere, never NULL


def test_known_characteristics_warn_when_their_count_changes_and_never_fail(tmp_path):
    rows = default_rows()
    rows[16] = school(9999999)                             # a second 7-digit school ID
    p = prepared(tmp_path, rows=rows, approve_kwargs=dict(row_count=8, unit_rows=6, last_row=16))
    found = checks(p)
    assert found["school_id_format"].status == WARN and found["school_id_format"].actual == "2"
    assert found["dq_psgc_region_9_digits"].status == WARN
    assert not p.failed_checks


def test_a_row_kind_count_that_differs_from_the_approval_fails(tmp_path):
    p = prepared(tmp_path, approve_kwargs=dict(unit_rows=4, blank_rows=2))
    found = checks(p)
    assert found["unit_rows_match_approved"].status == FAIL
    assert found["blank_rows_match_approved"].status == FAIL


def test_mojibake_is_recorded_not_refused(tmp_path):
    rows = default_rows()
    rows[9] = school(100001, name="Paaralang DOÃ‘A")
    found = checks(prepared(tmp_path, rows=rows))
    assert found["text_mojibake"].status == WARN and found["text_mojibake"].actual == "2"


def test_check_results_hold_counts_not_values(tmp_path):
    for c in prepared(tmp_path).checks:
        assert "Pagsubok" not in c.actual and "100001" not in c.actual


# --- Refusals -----------------------------------------------------------------------

def test_unknown_workbook_is_refused(tmp_path):
    path = make_workbook(tmp_path)
    refused("unregistered_delivery", prepare_delivery, empty_config(), registry_entry(), path)


def test_same_name_with_changed_bytes_is_not_the_approved_file(tmp_path):
    config = empty_config()
    approve(config, make_workbook(tmp_path / "a"))
    changed = make_workbook(tmp_path / "b", rows={9: school(100001)})
    refused("checksum_mismatch", prepare_delivery, config, registry_entry(), changed)


def test_a_changed_header_is_unknown_drift(tmp_path):
    header = headers()
    header[23] = "(PSGC) BRGY"
    config = empty_config()
    approve(config, path := make_workbook(tmp_path, header=header))
    refused("unknown_schema_drift", prepare_delivery, config, registry_entry(), path)


def test_a_title_that_differs_from_the_approval_is_refused(tmp_path):
    """A changed note (here the coordinate source) is a different delivery, never loaded unseen."""
    config = empty_config()
    path = make_workbook(tmp_path, title={"AC6": "Longitude & Latitude are made up, as of a later date"})
    approve(config, path)
    refused("title_changed", prepare_delivery, config, registry_entry(), path)


def test_the_school_year_must_agree_in_name_title_and_approval(tmp_path):
    config = empty_config()
    path = make_workbook(tmp_path, title={"A2": "SY 2024-2025"})
    approve(config, path, title={"A2": "SY 2024-2025"})
    refused("period_mismatch", prepare_delivery, config, registry_entry(), path)


def test_a_title_without_a_school_year_is_refused(tmp_path):
    config = empty_config()
    path = make_workbook(tmp_path, title={"A2": "School year 2023"})
    approve(config, path, title={"A2": "School year 2023"})
    refused("period_undeterminable", prepare_delivery, config, registry_entry(), path)


def test_a_sheet_the_contract_does_not_list_stops_the_batch(tmp_path):
    config = empty_config()
    approve(config, path := make_workbook(tmp_path, sheets=["DB", "Extra"]))
    refused("unexpected_sheet", prepare_delivery, config, registry_entry(), path)


@pytest.mark.parametrize("name, year", [
    (workbook_name("2023-24"), "2023-24"),
    ("SY 2023-2025 School Level Data on Enrollment with PSGC, Longitude and Latitude.xlsx", None),
    ("enrollment.xlsx", None),
])
def test_school_year_comes_from_the_file_name(name, year):
    assert period_from_name(real_config(), name) == year


# --- Bronze, through the pipeline ------------------------------------------------------

def test_load_reconciles_by_row_kind_and_a_rerun_adds_nothing(env):
    env.deliver()
    first = env.run()
    assert first.status == "succeeded", first
    n = FIXTURE_COUNTS["row_count"]
    assert env.q(f"SELECT COUNT(*) FROM {BRONZE}") == [(n,)]
    assert env.q(f"SELECT source_row_kind, COUNT(*) FROM {BRONZE} GROUP BY 1 ORDER BY 1") == [
        ("blank", 1), ("no_identifier", 1), ("unit", 5)]
    assert env.q(f"SELECT MIN(source_row_number), MAX(source_row_number) FROM {BRONZE}") == [(9, 15)]
    second = env.run()
    assert second.status == "succeeded"
    assert env.q(f"SELECT COUNT(*) FROM {BRONZE}") == [(n,)]
    assert env.q(f"SELECT COUNT(*) FROM {CONTROL}.ingestion_batches WHERE source_id = '{SOURCE}'") == [(1,)]


def test_provenance_is_complete_on_every_row(env):
    env.deliver()
    env.run()
    nulls = " OR ".join(f"{c} IS NULL" for c in PROVENANCE_COLUMNS)
    assert env.q(f"SELECT COUNT(*) FROM {BRONZE} WHERE {nulls}") == [(0,)]
    assert env.q(f"SELECT DISTINCT school_year, source_sheet, source_file FROM {BRONZE}") == [
        ("2023-24", "DB", workbook_name())]


def test_control_rows_carry_the_school_year_and_sheet(env):
    env.deliver()
    env.run()
    assert env.q(f"SELECT school_year, source_sheet, expected_rows, source_rows, status FROM {CONTROL}.ingestion_batches "
                 f"WHERE source_id = '{SOURCE}'") == [("2023-24", "DB", 7, 7, "succeeded")]


def test_a_failed_shape_blocks_the_batch_and_loads_nothing(env):
    env.deliver(approve_kwargs=dict(unit_rows=4, blank_rows=2))
    assert env.run().status == "failed"
    assert env.q(f"SELECT COUNT(*) FROM {BRONZE}") == [(0,)]


def test_the_format_puts_the_school_year_where_deped_has_it():
    fmt = formats.for_config(real_config())
    delivery = real_config()["deliveries"][0]
    assert fmt.describe(delivery, delivery["workbook"])["school_year"] == "2023-24"
    assert fmt.describe(delivery, delivery["workbook"])["source_sheet"] == "DB"


# --- The contract refuses anything ambiguous -------------------------------------------

def _approved_config(tmp_path):
    config = empty_config()
    approve(config, make_workbook(tmp_path))
    return config


@pytest.mark.parametrize("break_it, message", [
    (lambda c: c["deliveries"][0].update(unit_rows=6), "must equal row_count"),
    (lambda c: c["deliveries"][0].update(range="A1:CJ99"), "range must be"),
    (lambda c: c["deliveries"][0].update(school_year="2024-25"), "file name says"),
    (lambda c: c["deliveries"][0]["title_cells"].pop("A2"), "period cell"),
    (lambda c: c["deliveries"][0]["title_cells"].update(A9="below the header"), "above header_row"),
    (lambda c: c["deliveries"].append(copy.deepcopy(c["deliveries"][0])), "approved twice"),
    (lambda c: c["deliveries"][0].update(delivery_version=2), "1, 2, 3"),
    (lambda c: c.update(period_cell={"cell": "A9", "pattern": c["period_cell"]["pattern"]}), "above header_row"),
    (lambda c: c["profiled"].pop("error_cells"), "profiled"),
    (lambda c: c["quality_checks"].append(dict(c["quality_checks"][0])), "share a name"),
    (lambda c: c["schema_versions"]["v1"]["columns"].__setitem__(0, "batch_id"), "provenance"),
    (lambda c: c["schema_versions"]["v1"]["columns"].__setitem__(1, "region"), "repeats"),
])
def test_contract_refuses_ambiguous_config(tmp_path, break_it, message):
    config = _approved_config(tmp_path)
    break_it(config)
    with pytest.raises(IngestionError, match=message):
        validate_config(config, registry_entry())


def test_fixture_counts_cover_every_quality_check():
    """Guards the factory: every real check has a fixture count, so a new check cannot pass vacuously."""
    assert {c["name"] for c in real_config()["quality_checks"]} == set(FIXTURE_QUALITY)
    assert titles()["A2"] == "SY 2023-2024"
