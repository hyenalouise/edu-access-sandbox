"""PSA PSGC loads through the same pipeline as DepEd, from its own contract (format xlsx_table).

Every test builds made-up workbooks (tests/factories/psgc_workbooks.py), approves
them into a copy of the real psa_psgc contract inside a throwaway repository
root, and runs the real etl/ SQL on an in-memory DuckDB. No PSGC row, raw file,
or credential is used.

test_psgc_idempotency_demonstration walks the whole story in order; the others
check one behavior each.
"""

import copy
import zipfile

import pytest
import yaml

from factories.deped_deliveries import fake_repo, write_config
from factories.psgc_workbooks import (
    LEVELS, POPULATION_ABROAD, UNITS, approve, default_rows, empty_config, headers, make_workbook, real_config,
    registry_entry, workbook_name,
)
from src.ingestion import cli
from src.ingestion.contract import load_source_config, validate_config
from src.ingestion.errors import IngestionError
from src.ingestion.pipeline import IngestionRun, discover
from src.ingestion.store import DuckDBStore
from src.ingestion.validate import FAIL, PASS, WARN
from src.ingestion.xlsx_table import PROVENANCE_COLUMNS, mojibake, period_from_name, prepare_delivery

REVISION = "c" * 40
BRONZE = "edu_access.`02-bronze`.psa_psgc_raw"
CONTROL = "edu_access.`01-control`"
N = len(UNITS)


class SimulatedCrash(BaseException):
    """The process dying mid-load. BaseException, so the pipeline cannot catch and record it."""


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


class Env:
    def __init__(self, tmp_path):
        self.config = empty_config()
        self.landing = tmp_path / "landing"
        self.inbox = self.landing / "psa"
        self.repo = fake_repo(tmp_path / "repo", self.config)
        self.store = DuckDBStore()
        self.tmp = tmp_path

    def deliver(self, period="2026-Q2", folder="original", approve_it=True, approve_kwargs=None, **kwargs):
        path = make_workbook(self.inbox / folder, period, **kwargs)
        if approve_it:
            self.approve(path, period, **(approve_kwargs or {}))
        return path

    def approve(self, path, period="2026-Q2", **kwargs):
        entry = approve(self.config, path, period, **kwargs)
        write_config(self.repo, self.config)
        return entry

    def run(self, rerun=(), hook=None):
        return IngestionRun(self.store, self.repo, "psa_psgc", self.landing, "local", REVISION,
                            rerun_batch_ids=rerun, hook=hook).execute()

    def q(self, sql):
        return self.store.query(sql)

    def one(self, sql):
        return self.q(sql)[0][0]

    def bronze_rows(self, where="TRUE"):
        return self.one(f"SELECT COUNT(*) FROM {BRONZE} WHERE {where}")

    def batch(self, period, version=1):
        rows = self.store.records(f"SELECT * FROM {CONTROL}.ingestion_batches "
                                  f"WHERE school_year = '{period}' AND delivery_version = {version}")
        return rows[0] if rows else None

    def checks(self, run_id):
        return {name: (status, actual) for name, status, actual in self.q(
            f"SELECT check_name, status, actual FROM {CONTROL}.data_quality_results WHERE run_id = '{run_id}'")}


def outcome(summary, period):
    return next(o for o in summary.outcomes if o.school_year == period)


def refused(code, fn, *args, **kwargs):
    with pytest.raises(IngestionError) as e:
        fn(*args, **kwargs)
    assert e.value.code == code, e.value
    return e.value


def prepared_for(tmp_path, rows=None, period="2026-Q2", approve_kwargs=None, **kwargs):
    config = empty_config()
    path = make_workbook(tmp_path, period, rows=rows, **kwargs)
    approve(config, path, period, **(approve_kwargs or {"row_count": len(rows) if rows is not None else N}))
    return prepare_delivery(config, registry_entry(), path), config, path


def by_name(prepared):
    return {c.check_name: c for c in prepared.checks}


# --- The demonstration -------------------------------------------------------------

def test_psgc_idempotency_demonstration(env):
    # 1. Load a 2026-Q2 workbook; record its batch and Bronze row count.
    env.deliver("2026-Q2")
    first = env.run()
    assert first.status == "succeeded"
    assert (outcome(first, "2026-Q2").action, outcome(first, "2026-Q2").load_type) == ("load", "initial")
    assert env.bronze_rows() == N
    q2 = env.batch("2026-Q2")
    assert (q2["status"], q2["source_rows"], q2["bronze_rows"], q2["expected_rows"]) == ("succeeded", N, N, N)
    assert q2["batch_id"].startswith("psa_psgc__2026-Q2__")

    # 2. Run it again: skipped, no Bronze rows added.
    second = env.run()
    assert (outcome(second, "2026-Q2").action, outcome(second, "2026-Q2").outcome) == ("skip", "skipped")
    assert env.bronze_rows() == N

    # 3. The audit history records both attempts.
    attempts = env.q(f"SELECT run_id, action, outcome, rows_inserted FROM {CONTROL}.ingestion_batch_attempts "
                     "ORDER BY started_at_utc")
    assert attempts == [(first.run_id, "load", "succeeded", N), (second.run_id, "skip", "skipped", 0)]

    # 4. A new quarter is a new period; 2026-Q2 rows are untouched.
    env.deliver("2026-Q3")
    third = env.run()
    assert (outcome(third, "2026-Q3").action, outcome(third, "2026-Q3").load_type) == ("load", "incremental")
    assert env.bronze_rows("publication_period = '2026-Q2'") == N
    assert env.one(f"SELECT COUNT(DISTINCT run_id) FROM {BRONZE} WHERE publication_period = '2026-Q2'") == 1

    # 5. An older quarter arriving later is a backfill, and the master reference does not move (D-012).
    env.deliver("2026-Q1")
    fourth = env.run()
    assert (outcome(fourth, "2026-Q1").action, outcome(fourth, "2026-Q1").load_type) == ("load", "backfill")
    assert load_source_config(env.repo, "psa_psgc")[0]["master_reference_period"] == "2026-Q2"
    assert env.bronze_rows() == 3 * N

    # 6. The same 2026-Q2 file name with other bytes: recorded as a likely revision, not the original.
    original = env.inbox / "original" / workbook_name("2026-Q2")
    reissue = make_workbook(env.inbox / "2026-10-15", "2026-Q2", rows=default_rows() + [
        ["2000102002", "Bagong Barangay Test", "", "Bgy", "", "", "", "-", 5, "", ""]])
    assert reissue.name == original.name
    fifth = env.run()
    blocked = next(o for o in fifth.outcomes if o.outcome == "blocked")
    assert (blocked.load_type, fifth.status) == ("revision", "failed")
    assert "checksum_mismatch" in env.one(f"SELECT error_code FROM {CONTROL}.ingestion_batches WHERE status = 'blocked'")
    assert env.bronze_rows("publication_period = '2026-Q2'") == N
    # ...and, once the team approves it as version 2, both versions are kept and v2 is current.
    env.approve(reissue, "2026-Q2", row_count=N + 1, delivery_version=2,
                supersedes=env.config["deliveries"][0]["workbook_sha256"])
    sixth = env.run()
    assert sixth.status == "succeeded"
    assert env.bronze_rows("publication_period = '2026-Q2'") == N + N + 1
    current = env.q(f"SELECT school_year, delivery_version FROM {CONTROL}.current_batches "
                    "WHERE source_id = 'psa_psgc' ORDER BY 1")
    assert current == [("2026-Q1", 1), ("2026-Q2", 2), ("2026-Q3", 1)]

    # 7. A changed header (a new DOF order in the income header) fails as unknown drift.
    drifted = headers()
    drifted[6] = "Income\nClassification (DOF DO No. 999.2027)"
    env.deliver("2026-Q4", header=drifted)
    seventh = env.run()
    failed = outcome(seventh, "2026-Q4")
    assert (failed.outcome, seventh.status) == ("failed", "failed")
    assert env.batch("2026-Q4")["error_code"] == "unknown_schema_drift"
    assert env.bronze_rows("publication_period = '2026-Q4'") == 0


# --- Checksums and identity ------------------------------------------------------

def test_approved_checksum_is_accepted(tmp_path):
    prepared, _, path = prepared_for(tmp_path)
    assert (prepared.publication_period, prepared.schema_version, len(prepared.rows)) == ("2026-Q2", "v1", N)
    assert not prepared.failed_checks, prepared.failed_checks


def test_same_name_with_changed_bytes_is_not_the_approved_file(tmp_path):
    config = empty_config()
    approve(config, make_workbook(tmp_path / "a"))
    changed = make_workbook(tmp_path / "b", rows=default_rows()[:-1])
    error = refused("checksum_mismatch", prepare_delivery, config, registry_entry(), changed)
    assert "next delivery_version" in error.message


def test_unknown_workbook_is_refused(tmp_path):
    refused("unregistered_delivery", prepare_delivery, empty_config(), registry_entry(), make_workbook(tmp_path))


def test_missing_workbook(tmp_path):
    refused("missing_archive", prepare_delivery, empty_config(), registry_entry(), tmp_path / workbook_name("2026-Q2"))


def test_same_bytes_give_the_same_batch(env):
    path = env.deliver()
    copy_path = env.inbox / "2026-12-01" / path.name
    copy_path.parent.mkdir()
    copy_path.write_bytes(path.read_bytes())
    assert len(discover(env.config, env.landing)) == 1, "the same bytes in two folders are one delivery"
    summary = env.run()
    assert [o.batch_id for o in summary.outcomes] == [env.batch("2026-Q2")["batch_id"]]


# --- Opening the workbook safely ---------------------------------------------------

def _approved(tmp_path, **kwargs):
    config = empty_config()
    path = make_workbook(tmp_path, **kwargs)
    approve(config, path)
    return config, path


@pytest.mark.parametrize("member", ["../evil.xml", "/abs.xml"])
def test_unsafe_zip_parts_are_refused(tmp_path, member):
    config, path = _approved(tmp_path, extra_parts={member: b"<x/>"})
    refused("unsafe_member", prepare_delivery, config, registry_entry(), path)


def test_oversized_workbook_is_refused(tmp_path):
    config, path = _approved(tmp_path)
    config["max_uncompressed_bytes"] = 100
    refused("archive_too_large", prepare_delivery, config, registry_entry(), path)


def test_corrupt_workbook_is_refused(tmp_path):
    config = empty_config()
    path = tmp_path / workbook_name("2026-Q2")
    path.write_bytes(b"this is not a zip")
    approve(config, path)
    refused("corrupt_archive", prepare_delivery, config, registry_entry(), path)


def test_a_zip_that_is_not_a_workbook_is_refused(tmp_path):
    config = empty_config()
    path = tmp_path / workbook_name("2026-Q2")
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("readme.txt", "hello")
    approve(config, path)
    refused("corrupt_workbook", prepare_delivery, config, registry_entry(), path)


def test_xml_entities_are_refused_before_parsing(tmp_path):
    bomb = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><workbook>&a;</workbook>'
    config, path = _approved(tmp_path, part_override={"xl/workbook.xml": bomb})
    refused("unsafe_workbook", prepare_delivery, config, registry_entry(), path)


def test_macro_enabled_workbook_is_refused(tmp_path):
    config, path = _approved(tmp_path, extra_parts={"xl/vbaProject.bin": b"\x00"})
    refused("macro_enabled_workbook", prepare_delivery, config, registry_entry(), path)


def test_missing_psgc_sheet_is_refused(tmp_path):
    config, path = _approved(tmp_path, sheets=["Metadata", "National Summary", "Notes"])
    error = refused("missing_sheet", prepare_delivery, config, registry_entry(), path)
    assert "PSGC" in error.message


def test_a_sheet_the_contract_does_not_list_stops_the_batch(tmp_path):
    """The shared opener (workbook.open_sheet) refuses it: a new sheet may hold data."""
    config, path = _approved(tmp_path, sheets=["Metadata", "National Summary", "Prov Sum", "PSGC", "Notes",
                                               "Coding Structure", "New Sheet"])
    refused("unexpected_sheet", prepare_delivery, config, registry_entry(), path)


def test_a_missing_documentation_sheet_is_recorded(tmp_path):
    config, path = _approved(tmp_path, sheets=["Metadata", "National Summary", "PSGC"])
    assert by_name(prepare_delivery(config, registry_entry(), path))["sheets_match_contract"].status == WARN


def test_empty_sheet_is_refused(tmp_path):
    config, path = _approved(tmp_path, rows=[], header=[])
    refused("empty_sheet", prepare_delivery, config, registry_entry(), path)


def test_header_only_sheet_fails_the_row_checks(tmp_path):
    config = empty_config()
    path = make_workbook(tmp_path, rows=[])
    approve(config, path)
    checks = by_name(prepare_delivery(config, registry_entry(), path))
    assert checks["row_count_nonzero"].status == FAIL
    assert checks["row_count_matches_approved"].status == FAIL


# --- Header contract ---------------------------------------------------------------

def test_header_keeps_its_line_breaks_and_the_unnamed_column_j(tmp_path):
    prepared, _, _ = prepared_for(tmp_path)
    assert prepared.source_header[6] == "Income\nClassification (DOF DO No. 074.2024)"
    assert prepared.source_header[7] == "Urban / Rural\n(based on 2020 CPH)"
    assert prepared.source_header[9] == ""
    assert prepared.header[9] == "column_j_footnote"
    assert prepared.header == real_config()["schema_versions"]["v1"]["columns"]


@pytest.mark.parametrize("change", [
    lambda h: h.__setitem__(6, "Income Classification (DOF DO No. 074.2024)"),   # line break normalized away
    lambda h: h.__setitem__(9, "Notes"),                                          # column J given a header
    lambda h: h.__setitem__(6, "Income\nClassification (DOF DO No. 999.2027)"),   # a new DOF order
    lambda h: h.__setitem__(7, "Urban / Rural\n(based on 2030 CPH)"),             # a new census
    lambda h: h.append("New Column"),                                             # a column added
    lambda h: h.insert(1, h.pop(2)),                                              # columns reordered
])
def test_any_other_header_is_unknown_drift(tmp_path, change):
    header = headers()
    change(header)
    rows = [row + [""] for row in default_rows()] if len(header) > 11 else None
    config, path = _approved(tmp_path, header=header, rows=rows)
    error = refused("unknown_schema_drift", prepare_delivery, config, registry_entry(), path)
    assert "add a schema version" in error.message


def test_a_known_header_that_is_not_the_approved_one_is_refused(tmp_path):
    config = empty_config()
    v2 = copy.deepcopy(config["schema_versions"]["v1"])
    v2["source_headers"][6] = "Income\nClassification (DOF DO No. 999.2027)"
    config["schema_versions"]["v2"] = v2
    header = headers()
    header[6] = v2["source_headers"][6]
    path = make_workbook(tmp_path, header=header)
    approve(config, path, schema_version="v1")
    refused("schema_version_mismatch", prepare_delivery, config, registry_entry(), path)


def test_a_new_schema_version_loads_into_the_same_bronze_columns(tmp_path):
    config = empty_config()
    v2 = copy.deepcopy(config["schema_versions"]["v1"])
    v2["source_headers"][6] = "Income\nClassification (DOF DO No. 999.2027)"
    config["schema_versions"]["v2"] = v2
    header = headers()
    header[6] = v2["source_headers"][6]
    path = make_workbook(tmp_path, header=header)
    approve(config, path, schema_version="v2")
    prepared = prepare_delivery(config, registry_entry(), path)
    assert prepared.schema_version == "v2" and prepared.header == config["schema_versions"]["v1"]["columns"]


# --- Values kept exactly as received ------------------------------------------------

def test_values_stay_exactly_as_received(tmp_path):
    prepared, _, _ = prepared_for(tmp_path)
    rows = {values[0]: values for _, values in prepared.rows}
    assert rows["0000101001"][1] == "Doña Prueba"                   # Unicode, byte for byte
    assert rows["2000102001"][1] == "Ñañong Test"
    assert rows["0000101002"][1] == "Poblacion Test "               # trailing space kept
    assert rows["0000101002"][2] == ""                               # blank correspondence code stays ''
    assert rows["2099900000"][3] == ""                               # blank level stays ''
    assert rows["2099900000"][8] == "#N/A"                           # error cell kept as its text
    assert rows["2000102001"][8] == "0"                              # 0 is 0, never '-' or blank
    assert rows["0000101002"][7] == "-"                              # '-' stays '-', never 0 or rural
    assert rows["0000101000"][6] == "2nd*"                           # starred class not split
    assert rows["0000100000"][9] == "(excluding CITY OF PAGSUBOK) "  # column J footnote kept
    assert rows["0000101000"][4] == "Luma"


def test_leading_zero_codes_stay_text(tmp_path):
    prepared, _, _ = prepared_for(tmp_path)
    codes = [values[0] for _, values in prepared.rows]
    assert "0000000000" in codes and "0000100000" in codes
    assert all(len(c) == 10 for c in codes)


def test_ten_digit_code_stored_as_number_is_kept_and_counted(tmp_path):
    prepared, _, _ = prepared_for(tmp_path)
    checks = by_name(prepared)
    assert "2000000000" in [values[0] for _, values in prepared.rows]
    assert (checks["psgc_code_stored_as_number"].status, checks["psgc_code_stored_as_number"].actual) == (WARN, "1")
    assert checks["psgc_code_number_cells_match_format"].status == PASS


def test_code_that_lost_its_leading_zero_fails_and_is_not_padded(tmp_path):
    rows = default_rows()
    rows[1][0] = 100000   # '0000100000' stored as a number: Excel dropped the leading zeros
    prepared, _, _ = prepared_for(tmp_path, rows=rows)
    checks = by_name(prepared)
    assert checks["psgc_code_format"].status == FAIL
    assert checks["psgc_code_number_cells_match_format"].status == FAIL
    assert "100000" in [values[0] for _, values in prepared.rows], "never padded back"


def test_blank_code_fails(tmp_path):
    rows = default_rows()
    rows[3][0] = ""
    assert by_name(prepared_for(tmp_path, rows=rows)[0])["psgc_code_not_blank"].status == FAIL


def test_inline_strings_are_read(tmp_path):
    rows = default_rows()
    rows[3][1] = ("inline", "Doña Inline")
    prepared, _, _ = prepared_for(tmp_path, rows=rows)
    assert prepared.rows[3][1][1] == "Doña Inline"


def test_mojibake_fails_the_batch(tmp_path):
    rows = default_rows()
    rows[3][1] = "Santo NiÃ±o"   # UTF-8 bytes read as Windows-1252, as in the Q4_2023 API file
    assert by_name(prepared_for(tmp_path, rows=rows)[0])["text_mojibake"].status == FAIL


@pytest.mark.parametrize("text, broken", [("Santo NiÃ±o", True), ("Ã‘ato", True), ("Santo Niño", False),
                                           ("Tañong", False), ("bad � byte", True), ("Plain", False)])
def test_mojibake_detection(text, broken):
    assert mojibake(text) is broken


def test_formula_cells_are_counted_not_recalculated(tmp_path):
    rows = default_rows()
    rows[3][8] = ("formula", "SUM(I1:I2)")
    prepared = prepared_for(tmp_path, rows=rows)[0]
    assert (by_name(prepared)["formula_cells"].status, by_name(prepared)["formula_cells"].actual) == (WARN, "1")
    assert prepared.rows[3][1][8] == "", "no cached result: loaded as stored (blank), never recalculated"


# --- The publication quarter ------------------------------------------------------------

@pytest.mark.parametrize("name, period", [
    ("PSGC-2Q-2026-Publication-Datafile.xlsx", "2026-Q2"),
    ("PSGC-1Q-2027-Publication-Datafile.xlsx", "2027-Q1"),
    ("PSGC-5Q-2026-Publication-Datafile.xlsx", None),
    ("PSGC-Q4_2023-API-all.csv", None),
    ("2_2023 SAE_with PSGC_noHUC_06Feb2026.xlsx", None),
])
def test_quarter_comes_from_the_file_name(name, period):
    assert period_from_name(real_config(), name) == period


def test_metadata_date_must_be_in_the_file_name_quarter(tmp_path):
    config, path = _approved(tmp_path, publication_date="30 September 2026")
    error = refused("period_mismatch", prepare_delivery, config, registry_entry(), path)
    assert "2026-Q3" in error.message


def test_metadata_date_as_a_date_serial_is_read(tmp_path):
    prepared, _, _ = prepared_for(tmp_path, publication_date=46203)   # 2026-06-30 as an Excel serial
    assert prepared.publication_date == "2026-06-30"


@pytest.mark.parametrize("kwargs", [{"publication_date": "sometime"}, {"sheets": ["PSGC"]}])
def test_quarter_not_determinable(tmp_path, kwargs):
    config, path = _approved(tmp_path, **kwargs)
    refused("period_undeterminable", prepare_delivery, config, registry_entry(), path)


def test_approval_must_agree_with_the_workbook(tmp_path):
    config = empty_config()
    path = make_workbook(tmp_path)
    approve(config, path, publication_date="2026-05-15")
    refused("period_mismatch", prepare_delivery, config, registry_entry(), path)


# --- Data-quality results: recorded, never blocking -----------------------------------

def test_quality_counts_are_recorded_as_warnings(tmp_path):
    checks = by_name(prepared_for(tmp_path)[0])
    expected = {"dq_blank_geographic_level": "1", "dq_blank_correspondence_code": "2",
                "dq_population_not_whole_number": "1", "dq_population_zero": "1", "dq_income_class_dash": "1",
                "dq_income_class_starred": "1", "dq_urban_rural_dash": "1", "dq_name_trailing_space": "1",
                "dq_column_j_footnote_filled": "2"}
    assert {k: checks[k].actual for k in expected} == expected
    # Where the made-up workbook's count differs from the real profile it is a WARN that shows the change;
    # its one '#N/A' population equals the profiled 1, so that check passes.
    assert {k for k in expected if checks[k].status == PASS} == {"dq_population_not_whole_number"}
    assert all(checks[k].status == WARN for k in expected if k != "dq_population_not_whole_number")
    assert checks["dq_blank_geographic_level"].expected == "2 (profiled, O-2)"


def test_a_count_equal_to_the_profile_passes(tmp_path):
    """Sara's review: a known characteristic at its profiled count is PASS; only a change is a WARN."""
    config = empty_config()
    for check in config["quality_checks"]:
        check["profiled"] = {"blank_geographic_level": 1, "blank_correspondence_code": 2, "population_not_whole_number": 1,
                             "population_zero": 1, "income_class_dash": 1, "income_class_starred": 1,
                             "urban_rural_dash": 1, "name_trailing_space": 1, "column_j_footnote_filled": 2}[check["name"]]
    config["identifier_number_cells_profiled"], config["error_cells_profiled"] = 1, 1
    path = make_workbook(tmp_path)
    approve(config, path)
    checks = by_name(prepare_delivery(config, registry_entry(), path))
    assert not [c for c in checks.values() if c.status != PASS], [c for c in checks.values() if c.status != PASS]


def test_counts_reconcile_with_the_workbooks_own_national_summary(tmp_path):
    checks = by_name(prepared_for(tmp_path)[0])
    for level, n in LEVELS.items():
        check = checks[f"level_count_{level.lower()}_matches_national_summary"]
        assert (check.status, check.expected, check.actual) == (PASS, str(n), str(n))
    assert checks["region_population_reconciles_to_national"].actual == str(POPULATION_ABROAD)
    assert checks["region_population_reconciles_to_national"].status == PASS


def test_a_summary_that_disagrees_is_a_warning(tmp_path):
    checks = by_name(prepared_for(tmp_path, national={"Bgy": 99, "population": 1})[0])
    assert checks["level_count_bgy_matches_national_summary"].status == WARN
    assert checks["region_population_reconciles_to_national"].status == WARN
    assert not [c for c in checks.values() if c.status == FAIL]


def test_hierarchy_by_code_prefix(tmp_path):
    checks = by_name(prepared_for(tmp_path)[0])
    for name in ("hierarchy_barangays_without_city_or_municipality", "hierarchy_units_without_region",
                 "hierarchy_municipalities_without_province", "hierarchy_no_province_region_has_no_provinces"):
        assert checks[name].status == PASS, name
    rows = default_rows() + [["2000105001", "Ulila Test", "", "Bgy", "", "", "", "R", 1, "", ""]]
    orphan = by_name(prepared_for(tmp_path / "orphan", rows=rows)[0])
    assert (orphan["hierarchy_barangays_without_city_or_municipality"].status,
            orphan["hierarchy_barangays_without_city_or_municipality"].actual) == (WARN, "1")


def test_check_results_hold_counts_not_values(tmp_path):
    text = " ".join(f"{c.expected} {c.actual}" for c in prepared_for(tmp_path)[0].checks)
    for value in ("Doña", "Rehiyon", "0000101001", "#N/A"):
        assert value not in text


# --- Bronze, provenance and the control tables ------------------------------------------

def test_provenance_is_complete_on_every_row(env):
    env.deliver()
    summary = env.run()
    row = env.store.records(f"SELECT * FROM {BRONZE} WHERE source_row_number = 2")[0]
    assert (row["source_id"], row["source_sheet"], row["publication_period"], row["publication_date"]) == (
        "psa_psgc", "PSGC", "2026-Q2", "2026-06-30")
    assert row["source_url"] == registry_entry()["acquisition"] and row["source_system"]
    assert row["source_file"] == workbook_name("2026-Q2") and len(row["source_sha256"]) == 64
    assert (row["delivery_version"], row["schema_version"], len(row["schema_fingerprint"])) == (1, "v1", 64)
    assert (row["run_id"], row["code_revision"], row["psgc_code"]) == (summary.run_id, REVISION, "0000000000")
    assert row["batch_id"].startswith("psa_psgc__2026-Q2__") and row["ingested_at_utc"] is not None
    nulls = " OR ".join(f"`{c}` IS NULL" for c in PROVENANCE_COLUMNS)
    assert env.bronze_rows(nulls) == 0


def test_source_row_number_is_the_excel_row(env):
    env.deliver()
    env.run()
    assert env.q(f"SELECT MIN(source_row_number), MAX(source_row_number) FROM {BRONZE}") == [(2, N + 1)]
    assert env.one(f"SELECT name FROM {BRONZE} WHERE source_row_number = 5") == UNITS[3][1]


def test_bronze_keeps_blanks_and_text_exactly(env):
    env.deliver()
    env.run()
    assert env.one(f"SELECT name FROM {BRONZE} WHERE psgc_code = '0000101002'") == "Poblacion Test "
    assert env.one(f"SELECT population FROM {BRONZE} WHERE psgc_code = '2099900000'") == "#N/A"
    assert env.one(f"SELECT geographic_level FROM {BRONZE} WHERE psgc_code = '2099900000'") == ""
    assert env.one(f"SELECT name FROM {BRONZE} WHERE psgc_code = '2000102001'") == "Ñañong Test"


def test_control_rows_carry_the_quarter_where_deped_has_a_school_year(env):
    env.deliver()
    env.run()
    batch = env.batch("2026-Q2")
    assert (batch["source_file"], batch["encoding"], batch["schema_version"]) == (workbook_name("2026-Q2"), "utf-8", "v1")
    assert batch["archive_sha256"] == batch["source_sha256"], "the workbook is both the delivery and the data file"
    assert env.one(f"SELECT school_year FROM {CONTROL}.ingestion_batch_attempts") == "2026-Q2"


def test_row_count_must_reconcile_with_the_approval(env):
    env.deliver(approve_kwargs={"row_count": N + 1})
    summary = env.run()
    assert summary.status == "failed"
    assert env.batch("2026-Q2")["error_code"] == "failed_checks"
    assert env.bronze_rows() == 0
    statuses = env.checks(summary.run_id)
    assert statuses["row_count_matches_approved"] == (FAIL, str(N))


def test_rerun_adds_no_pipeline_duplicates(env):
    env.deliver()
    env.run()
    bid = env.batch("2026-Q2")["batch_id"]
    again = env.run(rerun=[bid])
    assert (again.outcomes[0].action, again.outcomes[0].rows_inserted) == ("rerun", 0)
    assert env.one(f"SELECT COUNT(*) - COUNT(DISTINCT source_sha256 || ':' || CAST(source_row_number AS VARCHAR)) "
                   f"FROM {BRONZE}") == 0
    assert env.checks(again.run_id)["no_pipeline_duplicates"][0] == PASS


def test_source_duplicate_code_is_flagged_but_kept(env):
    rows = default_rows() + [copy.deepcopy(UNITS[3])]
    env.deliver(rows=rows, approve_kwargs={"row_count": N + 1})
    summary = env.run()
    assert summary.status == "succeeded"
    assert env.bronze_rows("psgc_code = '0000101001'") == 2
    checks = env.checks(summary.run_id)
    assert checks["psgc_code_unique_in_file"] == (WARN, "1")
    assert checks["duplicate_rows_in_file"] == (WARN, "1")


def test_failed_batch_can_be_retried(env):
    config_entry_kwargs = {"row_count": N + 5}
    path = env.deliver(approve_kwargs=config_entry_kwargs)
    assert env.run().status == "failed"
    env.config["deliveries"][0]["row_count"] = N
    env.config["deliveries"][0]["range"] = f"A1:K{N + 1}"
    write_config(env.repo, env.config)
    retried = env.run()
    assert (retried.outcomes[0].action, retried.outcomes[0].outcome) == ("retry", "succeeded")
    assert env.batch("2026-Q2")["attempt_count"] == 2 and env.bronze_rows() == N
    assert path.exists()


def test_interrupted_load_is_recovered_without_duplicates(env):
    env.deliver()

    def crash(stage):
        if stage == "after_bronze_merge":
            raise SimulatedCrash()

    with pytest.raises(SimulatedCrash):
        env.run(hook=crash)
    assert env.batch("2026-Q2")["status"] == "loading"
    assert env.one(f"SELECT COUNT(*) FROM {CONTROL}.current_batches WHERE source_id = 'psa_psgc'") == 0
    recovered = env.run()
    assert (recovered.outcomes[0].action, recovered.outcomes[0].rows_inserted) == ("retry", 0)
    assert env.batch("2026-Q2")["status"] == "succeeded" and env.bronze_rows() == N


def test_partial_write_is_completed(env):
    env.deliver()

    def crash(stage):
        if stage == "after_bronze_merge":
            raise SimulatedCrash()

    with pytest.raises(SimulatedCrash):
        env.run(hook=crash)
    env.store.sql(f"DELETE FROM {BRONZE} WHERE source_row_number > 4")   # only part of the file landed
    recovered = env.run()
    assert recovered.outcomes[0].rows_inserted == N - 3
    assert env.bronze_rows() == N


def test_an_approved_workbook_missing_from_landing_fails_the_run(env):
    path = env.deliver()
    path.unlink()
    summary = env.run()
    assert summary.status == "failed" and summary.missing_deliveries == [workbook_name("2026-Q2")]
    run = env.store.records(f"SELECT failure_stage, error_message FROM {CONTROL}.pipeline_runs")[0]
    assert run["failure_stage"] == "discover" and "Upload" in run["error_message"]


def test_unrelated_psa_files_are_not_psgc_deliveries(env):
    env.deliver()
    other = env.inbox / "original" / "2_2023 SAE_with PSGC_noHUC_06Feb2026.xlsx"
    other.write_bytes(b"not looked at")
    lock = env.inbox / "original" / ("~$" + workbook_name("2026-Q2"))
    lock.write_bytes(b"office lock file")
    assert [p.name for _, p in discover(env.config, env.landing)] == [workbook_name("2026-Q2")]


# --- The contract ------------------------------------------------------------------------

def test_real_contract_loads_and_stays_profiled(repo_root):
    config, entry = load_source_config(repo_root, "psa_psgc")
    d = config["deliveries"][0]
    assert (d["publication_period"], d["row_count"], d["range"]) == ("2026-Q2", 43768, "A1:K43769")
    assert d["workbook_sha256"] == "31892bc2bdde3ea0682562d9412b5bab4d45a0be5e5a5b4f6c9d7714b94bca5d"
    assert config["master_reference_period"] == "2026-Q2"
    assert entry["status"] == "accepted", "accepted by the team on 2026-10-21 (D-063); a status change is a team decision"


def _with_delivery():
    config = real_config()
    return config, config["deliveries"][0]


@pytest.mark.parametrize("break_it, message", [
    (lambda c, d: c["deliveries"].append(copy.deepcopy(d)), "approved twice"),
    (lambda c, d: d.update(publication_period="2026-Q3"), "file name says"),
    (lambda c, d: d.update(publication_period="2026Q2"), "not like"),
    (lambda c, d: d.update(publication_date="2026-07-01"), "inside 2026-Q2"),
    (lambda c, d: d.update(workbook="psgc.xlsx"), "would not be discovered"),
    (lambda c, d: d.update(range="A1:K100"), "range"),
    (lambda c, d: d.update(sheet="Data"), "data_sheet"),
    (lambda c, d: d.update(delivery_version=2), "1, 2, 3"),
    (lambda c, d: d.update(workbook_sha256="ABC"), "SHA-256"),
    (lambda c, d: d.update(schema_version="v9"), "not defined"),
    (lambda c, d: c["schema_versions"]["v1"]["source_headers"].pop(), "exact header cell"),
    (lambda c, d: c["schema_versions"]["v1"]["columns"].__setitem__(1, "source_file"), "provenance"),
    (lambda c, d: c["schema_versions"]["v1"]["columns"].__setitem__(1, "Name"), "snake_case"),
    (lambda c, d: c["schema_versions"]["v1"]["columns"].__setitem__(1, "psgc_code"), "repeats"),
    (lambda c, d: c.update(master_reference_period="2026-Q1"), "master_reference_period"),
    (lambda c, d: c.update(workbook_pattern="^PSGC-.*\\.xlsx$"), "'quarter' and 'year'"),
    (lambda c, d: c["quality_checks"].append({"name": "x", "check": "guess", "column": "name", "profiled": 0,
                                              "finding": "-"}), "is not one of"),
    (lambda c, d: c["quality_checks"].append({"name": "x", "check": "blank", "column": "nope", "profiled": 0,
                                              "finding": "-"}), "unknown column"),
])
def test_contract_refuses_ambiguous_config(break_it, message):
    config, delivery = _with_delivery()
    break_it(config, delivery)
    error = refused("invalid_config", validate_config, config, registry_entry())
    assert message in error.message


def test_a_reissue_must_name_what_it_supersedes():
    config, delivery = _with_delivery()
    reissue = copy.deepcopy(delivery)
    reissue.update(delivery_version=2, workbook_sha256="1" * 64)
    config["deliveries"].append(reissue)
    refused("invalid_config", validate_config, config, registry_entry())
    reissue["supersedes"] = delivery["workbook_sha256"]
    validate_config(config, registry_entry())


def test_an_unknown_format_is_refused():
    config = real_config()
    config["format"] = "xlsx_magic"
    refused("invalid_config", validate_config, config, registry_entry())


# --- The job and the command line ---------------------------------------------------------

def test_psgc_loads_in_its_own_lane_of_the_pipeline_job(repo_root):
    bundle = yaml.safe_load((repo_root / "databricks.yml").read_text(encoding="utf-8"))
    tasks = {t["task_key"]: t for t in bundle["resources"]["jobs"]["edu_access_pipeline"]["tasks"]}
    psgc = tasks["bronze_psa_psgc"]
    args = psgc["spark_python_task"]["parameters"]
    assert args[args.index("--source") + 1] == "psa_psgc"
    assert psgc["run_if"] == "ALL_SUCCESS"
    assert [d["task_key"] for d in psgc["depends_on"]] == ["04_create_psa_psgc_raw"]


def test_cli_exit_code_for_a_blocked_workbook(tmp_path, capsys, monkeypatch):
    config = empty_config()
    repo = fake_repo(tmp_path / "repo", config)
    make_workbook(tmp_path / "landing" / "psa")
    monkeypatch.setattr(cli, "REPO_ROOT", repo)
    code = cli.main(["ingest", "--source", "psa_psgc", "--landing", str(tmp_path / "landing"),
                     "--db", str(tmp_path / "t.duckdb"), "--code-revision", REVISION])
    assert code == 1
    assert "unregistered_delivery" not in capsys.readouterr().err  # reported per batch on stdout, not a crash


# --- The control columns added by D-018 (#109) ---------------------------------------

def test_psgc_control_rows_fill_the_workbook_columns(env):
    """main creates logical_dataset, estimate_years_covered and source_sheet (D-018). PSGC has no estimate
    years, so the first two are NULL; source_sheet is the data sheet, as in Bronze. current_batches
    partitions by COALESCE(school_year, logical_dataset), so it still keeps one version per quarter."""
    env.deliver("2026-Q2")
    env.deliver("2026-Q3")
    env.run()
    rows = env.q(f"SELECT school_year, logical_dataset, estimate_years_covered, source_sheet "
                 f"FROM {CONTROL}.ingestion_batches ORDER BY school_year")
    assert rows == [("2026-Q2", None, None, "PSGC"), ("2026-Q3", None, None, "PSGC")]
    attempts = env.q(f"SELECT DISTINCT logical_dataset, estimate_years_covered FROM {CONTROL}.ingestion_batch_attempts")
    assert attempts == [(None, None)]
    assert env.q(f"SELECT school_year FROM {CONTROL}.current_batches WHERE source_id = 'psa_psgc' ORDER BY 1") == [
        ("2026-Q2",), ("2026-Q3",)]


def test_an_unknown_format_is_not_read_as_another_one():
    """Sara's review: formats.for_config looks the format up, so a new format fails loudly."""
    from src.ingestion import formats
    config = real_config()
    config["format"] = "xlsx_magic"  # a format no source uses; geojson_features now exists (D-026)
    with pytest.raises(KeyError):
        formats.for_config(config)
