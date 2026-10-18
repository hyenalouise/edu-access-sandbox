"""What a DepEd enrollment delivery must pass before anything reaches Bronze.

Each test builds made-up zips in a temporary folder (tests/factories/deped_deliveries.py),
approves them into a copy of the real contract, and checks that the right
delivery is accepted and every wrong one is refused with a clear reason.
"""

import copy
import json
import os
import zipfile

import pytest

from factories.deped_deliveries import (
    REPO_ROOT, approve, columns, empty_config, make_delivery, make_rows, real_config,
    registry_entry, write_zip,
)
from src.ingestion import archive
from src.ingestion.contract import (
    PROVENANCE_COLUMNS, load_source_config, match_schema, resolve_school_year, validate_config,
)
from src.ingestion.errors import IngestionError
from src.ingestion.reader import decode, parse_csv
from src.ingestion.revision import UNSET, resolve_code_revision
from src.ingestion.validate import FAIL, PASS, WARN, prepare_delivery


def refused(code, fn, *args, **kwargs):
    with pytest.raises(IngestionError) as e:
        fn(*args, **kwargs)
    assert e.value.code == code, e.value
    return e.value


def checks_by_name(prepared):
    return {c.check_name: c for c in prepared.checks}


# --- The real contract -------------------------------------------------------

def test_real_contract_loads(repo_root):
    config, entry = load_source_config(repo_root, "deped_enrollment")
    assert [d["school_year"] for d in config["deliveries"]] == ["2020-21", "2023-24", "2024-25", "2025-26"]
    assert entry["status"] == "profiled", "ingestion must not promote the source; that is a team decision"


CONTRACTS = sorted((REPO_ROOT / "config" / "ingestion").glob("*.json"))


def test_the_contracts_were_found():
    """Guards the glob: an empty list would make the next tests vacuous."""
    assert CONTRACTS


@pytest.mark.parametrize("path", CONTRACTS, ids=lambda p: p.stem)
def test_every_contract_is_valid(repo_root, path):
    load_source_config(repo_root, path.stem)


# How each approved encoding is written in a card's Files table.
ENCODING_ON_CARD = {"utf-8": "UTF-8", "cp1252": "Windows-1252"}


@pytest.mark.parametrize("path", CONTRACTS, ids=lambda p: p.stem)
def test_contract_matches_the_source_card_row_by_row(repo_root, path):
    """The contract and the inventory card must describe the same files, value for value.

    Each value must sit on the card row of the file it belongs to: the zip's name
    and checksum on one row, and the CSV's name, checksum, row count, and encoding
    on another. A row count or encoding copied from another year's file fails.
    """
    card = (
        repo_root / "docs" / "data" / "source-inventory" / path.stem / "README.md"
    ).read_text(encoding="utf-8")
    lines = card.splitlines()
    config = json.loads(path.read_text(encoding="utf-8"))
    if config.get("format") == "xlsx_sheet":
        return _workbook_matches_the_card(config, lines)
    if config.get("format") == "xlsx_table":
        return _workbook_table_matches_the_card(config, lines)
    if config.get("format") == "xlsx_report":
        return _workbook_report_matches_the_card(config, lines)
    if config.get("format") == "xlsx_census":
        return _workbook_census_matches_the_card(config, lines)
    for d in config["deliveries"]:
        archive_rows = [line for line in lines if d["archive_sha256"] in line]
        assert len(archive_rows) == 1, f"{d['archive']}: its checksum must be on exactly one card row"
        assert f"`{d['archive']}`" in archive_rows[0], f"{d['archive']}: checksum is on another file's row"

        csv_rows = [line for line in lines if d["data_member_sha256"] in line]
        assert len(csv_rows) == 1, f"{d['data_member']}: its checksum must be on exactly one card row"
        row = csv_rows[0]
        assert f"`{d['data_member']}`" in row, f"{d['data_member']}: checksum is on another file's row"
        assert f"{d['row_count']:,}" in row, f"{d['data_member']}: row count {d['row_count']:,} is not on its card row"
        assert ENCODING_ON_CARD[d["encoding"]] in row, f"{d['data_member']}: encoding {d['encoding']} is not on its card row"

        for name, digest in d["document_sha256"].items():
            assert digest in card, f"{d['archive']}: {name} checksum is not on the card"


def _workbook_matches_the_card(config, lines):
    """A workbook's card row holds its name, checksum, sheet, and the profiled row counts."""
    for d in config["deliveries"]:
        rows = [line for line in lines if d["workbook_sha256"] in line]
        assert len(rows) == 1, f"{d['workbook']}: its checksum must be on exactly one card row"
        row = rows[0]
        body = d["body_rows"]["last"] - d["body_rows"]["first"] + 1
        assert f"`{d['workbook']}`" in row, f"{d['workbook']}: checksum is on another file's row"
        assert f"`{d['sheet']}`" in row, f"{d['workbook']}: sheet {d['sheet']!r} is not on its card row"
        for label, n in (("data rows", body), ("unit rows", d["unit_rows"]), ("banner rows", d["banner_rows"])):
            assert f"{n:,}" in row, f"{d['workbook']}: {label} {n:,} is not on its card row"
        assert f"range {d['used_range']}" in row, f"{d['workbook']}: used range {d['used_range']} is not on its card row"
        rows_text = f"rows {d['body_rows']['first']} to {d['body_rows']['last']}"
        assert rows_text in row, f"{d['workbook']}: {rows_text!r} is not on its card row"


def _workbook_table_matches_the_card(config, lines):
    """An xlsx_table workbook (PSGC): name, checksum, data rows and range on one card row."""
    for d in config["deliveries"]:
        rows = [line for line in lines if d["workbook_sha256"] in line]
        assert len(rows) == 1, f"{d['workbook']}: its checksum must be on exactly one card row"
        assert f"`{d['workbook']}`" in rows[0], f"{d['workbook']}: checksum is on another file's row"
        assert f"{d['row_count']:,}" in rows[0], f"{d['workbook']}: row count {d['row_count']:,} is not on its card row"
        assert d["range"] in rows[0], f"{d['workbook']}: range {d['range']} is not on its card row"


def _workbook_report_matches_the_card(config, lines):
    """An xlsx_report workbook (DepEd EMISD): name, checksum, sheet, range, and every row-kind count on one card row."""
    for d in config["deliveries"]:
        rows = [line for line in lines if d["workbook_sha256"] in line]
        assert len(rows) == 1, f"{d['workbook']}: its checksum must be on exactly one card row"
        row = rows[0]
        assert f"`{d['workbook']}`" in row, f"{d['workbook']}: checksum is on another file's row"
        assert f"`{d['sheet']}`" in row, f"{d['workbook']}: sheet {d['sheet']!r} is not on its card row"
        assert f"range {d['range']}" in row, f"{d['workbook']}: range {d['range']} is not on its card row"
        for label in ("row_count", "unit_rows", "blank_rows", "no_identifier_rows"):
            assert f"{d[label]:,}" in row, f"{d['workbook']}: {label} {d[label]:,} is not on its card row"


def _workbook_census_matches_the_card(config, lines):
    """An xlsx_census workbook (PSA school-age population): name, checksum, every sheet and its place rows,
    and each sheet's row count once pinned, on one card row."""
    for d in config["deliveries"]:
        rows = [line for line in lines if d["workbook_sha256"] in line]
        assert len(rows) == 1, f"{d['workbook']}: its checksum must be on exactly one card row"
        row = rows[0]
        assert f"`{d['workbook']}`" in row, f"{d['workbook']}: checksum is on another file's row"
        for s in d["sheets"]:
            assert f"`{s['sheet']}`" in row, f"{d['workbook']}: sheet {s['sheet']!r} is not on its card row"
            assert f"{s['place_rows']:,} places" in row, f"{d['workbook']}: {s['place_rows']:,} places is not on its card row"
            if s["sheet_rows"] is not None:
                assert f"`{s['sheet']}` {s['sheet_rows']:,} rows" in row, (
                    f"{d['workbook']}: {s['sheet']} has {s['sheet_rows']:,} rows in the contract but not on its card row")


def test_v2_adds_columns_without_reordering_v1():
    v1, v2 = columns("v1"), columns("v2")
    assert [c for c in v2 if c in v1] == v1
    assert len(v1) == 78 and len(v2) == 83


@pytest.mark.parametrize("break_it, message", [
    (lambda c: c["deliveries"].append(copy.deepcopy(c["deliveries"][0])), "approved twice"),
    (lambda c: c["deliveries"][0].update(encoding="latin-1"), "encoding"),
    (lambda c: c["deliveries"][0].update(schema_version="v9"), "not defined"),
    (lambda c: c["deliveries"][0].update(delivery_version=2), "1, 2, 3"),
    (lambda c: c["deliveries"][0].update(archive_sha256="ABC"), "SHA-256"),
    (lambda c: c["deliveries"][0].update(school_year="2023-2024"), "school_year"),
    (lambda c: c["deliveries"][0].update(data_member="enrollment_2024-25.csv"), "data file says"),
    (lambda c: c["schema_versions"]["v1"]["columns"].append("batch_id"), "provenance"),
    (lambda c: c["schema_versions"]["v1"]["columns"].append("school_id"), "repeats"),
    (lambda c: c["schema_versions"]["v1"]["columns"].remove("school_id"), "required"),
])
def test_contract_refuses_ambiguous_config(break_it, message):
    config = real_config()
    break_it(config)
    error = refused("invalid_config", validate_config, config, registry_entry())
    assert message in error.message


def test_a_revision_must_name_what_it_supersedes():
    config = real_config()
    revised = copy.deepcopy(config["deliveries"][2])
    revised.update(delivery_version=2, archive_sha256="1" * 64, data_member_sha256="2" * 64)
    config["deliveries"].append(revised)
    refused("invalid_config", validate_config, config, registry_entry())
    revised["supersedes"] = config["deliveries"][2]["archive_sha256"]
    validate_config(config, registry_entry())


def test_provenance_columns_cover_the_required_set():
    required = {"source_id", "source_system", "source_url", "source_archive", "source_file", "source_sha256",
                "source_row_number", "school_year", "ingested_at_utc", "batch_id", "run_id",
                "schema_version", "code_revision"}
    assert required <= set(PROVENANCE_COLUMNS)


# --- Checksums and identity --------------------------------------------------

def test_approved_fixture_is_accepted(tmp_path):
    config = empty_config()
    path = make_delivery(tmp_path, "2023-24")
    approve(config, path, "2023-24")
    prepared = prepare_delivery(config, registry_entry(), path)
    assert (prepared.school_year, prepared.schema_version, len(prepared.rows)) == ("2023-24", "v1", 3)
    assert all(c.status == PASS for c in prepared.checks), prepared.checks


def test_same_bytes_give_the_same_checksum(tmp_path):
    a = make_delivery(tmp_path / "a", "2023-24")
    b = make_delivery(tmp_path / "b", "2023-24")
    assert archive.sha256_file(a) == archive.sha256_file(b)


def test_same_filename_with_changed_bytes_is_not_the_approved_file(tmp_path):
    config = empty_config()
    approve(config, make_delivery(tmp_path / "v1", "2025-26", "v2", encoding="cp1252"), "2025-26", "v2", "cp1252")
    changed = make_delivery(tmp_path / "v2", "2025-26", "v2", encoding="cp1252", n_rows=4)
    error = refused("checksum_mismatch", prepare_delivery, config, registry_entry(), changed)
    assert "delivery_version" in error.message and "supersedes" in error.message


def test_unknown_file_is_refused(tmp_path):
    path = make_delivery(tmp_path, "2026-27")
    refused("unregistered_delivery", prepare_delivery, empty_config(), registry_entry(), path)


def test_missing_archive(tmp_path):
    refused("missing_archive", prepare_delivery, empty_config(), registry_entry(), tmp_path / "nope.zip")


def test_member_checksum_must_match(tmp_path):
    config = empty_config()
    path = make_delivery(tmp_path, "2023-24")
    approve(config, path, "2023-24")["data_member_sha256"] = "0" * 64
    refused("member_checksum_mismatch", prepare_delivery, config, registry_entry(), path)


def test_document_checksum_must_match(tmp_path):
    config = empty_config()
    path = make_delivery(tmp_path, "2023-24")
    approve(config, path, "2023-24")["document_sha256"]["README.md"] = "0" * 64
    refused("document_checksum_mismatch", prepare_delivery, config, registry_entry(), path)


# --- Safe zip handling -------------------------------------------------------

ON_WINDOWS = os.sep == "\\"


@pytest.mark.parametrize("name", [
    "../escape.csv",
    "/etc/enrollment_2023-24.csv",
    "C:/x/enrollment.csv",
    # Refused everywhere: as a backslash on Linux and macOS, and as '..' on
    # Windows, where zipfile turns the backslash into '/'.
    "..\\escape.csv",
    pytest.param("a\\b.csv", marks=pytest.mark.skipif(
        ON_WINDOWS, reason="On Windows, zipfile turns '\\' into '/' when writing and reading, so 'a\\b.csv' "
                           "becomes the harmless 'a/b.csv'. '..\\escape.csv' covers the dangerous case there.")),
])
def test_unsafe_paths_are_refused(tmp_path, name):
    path = write_zip(tmp_path / "Enrollment-in-SY-2023-2024.zip", {name: b"x"})
    refused("unsafe_member", archive.list_members, path, 10_000)


def test_symlink_member_is_refused(tmp_path):
    path = tmp_path / "Enrollment-in-SY-2023-2024.zip"
    with zipfile.ZipFile(path, "w") as zf:
        info = zipfile.ZipInfo("link.csv")
        info.external_attr = (0o120777 << 16)
        zf.writestr(info, "/etc/passwd")
    refused("unsafe_member", archive.list_members, path, 10_000)


def test_corrupt_zip_is_refused(tmp_path):
    path = tmp_path / "Enrollment-in-SY-2023-2024.zip"
    path.write_bytes(b"PK\x03\x04 this is not a zip")
    refused("corrupt_archive", archive.list_members, path, 10_000)


def test_oversized_archive_is_refused(tmp_path):
    path = make_delivery(tmp_path, "2023-24", n_rows=50)
    refused("archive_too_large", archive.list_members, path, 100)


@pytest.mark.parametrize("folder", ["Enrollment in SY 2023-2024", "Enrollment-in-SY-2023-2024", ""])
def test_members_are_found_whatever_the_publisher_folder(tmp_path, folder):
    config = empty_config()
    path = make_delivery(tmp_path, "2023-24", zip_folder=folder)
    approve(config, path, "2023-24")
    assert prepare_delivery(config, registry_entry(), path).data_member.endswith("enrollment_2023-24.csv")


def test_missing_csv_member(tmp_path):
    path = write_zip(tmp_path / "Enrollment-in-SY-2023-2024.zip", {"x/README.md": b"r"})
    members = archive.list_members(path, 10_000)
    refused("missing_data_member", archive.resolve_members, members, real_config()["data_member_pattern"], ["README.md"])


def test_missing_readme_member(tmp_path):
    path = write_zip(tmp_path / "Enrollment-in-SY-2023-2024.zip", {"x/enrollment_2023-24.csv": b"a"})
    members = archive.list_members(path, 10_000)
    refused("missing_document_member", archive.resolve_members, members, real_config()["data_member_pattern"], ["README.md"])


def test_unexpected_member_stops_the_load(tmp_path):
    config = empty_config()
    path = make_delivery(tmp_path, "2023-24", extra_members={"x/enrollment_mapping.csv": b"a,b\n"})
    approve(config, path, "2023-24")
    refused("unexpected_member", prepare_delivery, config, registry_entry(), path)


# --- Encodings ---------------------------------------------------------------

def test_windows_1252_delivery_keeps_its_characters(tmp_path):
    """SY 2025-26 is Windows-1252 with CRLF line endings (profile O-6)."""
    config = empty_config()
    path = make_delivery(tmp_path, "2025-26", "v2", encoding="cp1252", line_ending="\r\n")
    approve(config, path, "2025-26", "v2", "cp1252")
    prepared = prepare_delivery(config, registry_entry(), path)
    barangay = prepared.header.index("barangay")
    assert {values[barangay] for _, values in prepared.rows} == {"Do\u00f1a Test"}
    assert not any(v.endswith("\r") for _, values in prepared.rows for v in values)


def test_windows_1252_bytes_approved_as_utf8_fail_loudly(tmp_path):
    config = empty_config()
    path = make_delivery(tmp_path, "2025-26", "v2", encoding="cp1252")
    approve(config, path, "2025-26", "v2", encoding="utf-8")
    refused("encoding_mismatch", prepare_delivery, config, registry_entry(), path)


def test_unknown_codec_is_refused():
    refused("unsupported_encoding", decode, b"a", "not-a-codec", "x.csv")


# --- Schema contract ---------------------------------------------------------

def test_both_known_schemas_are_recognized():
    assert match_schema(real_config(), columns("v1")) == "v1"
    assert match_schema(real_config(), columns("v2")) == "v2"


@pytest.mark.parametrize("change, detail", [
    (lambda h: h + ["g13_male"], "added ['g13_male']"),
    (lambda h: [c for c in h if c != "street_address"], "removed ['street_address']"),
    (lambda h: [h[1], h[0], *h[2:]], "different order"),
])
def test_unknown_drift_is_refused(change, detail):
    error = refused("unknown_schema_drift", match_schema, real_config(), change(columns("v2")))
    assert detail in error.message and "nearest is v2" in error.message


def test_drift_in_a_delivery_stops_it(tmp_path):
    config = empty_config()
    header = columns("v2") + ["new_column"]
    path = make_delivery(tmp_path, "2026-27", header=header)
    approve(config, path, "2026-27", "v2")
    refused("unknown_schema_drift", prepare_delivery, config, registry_entry(), path)


def test_header_must_be_the_approved_version(tmp_path):
    config = empty_config()
    path = make_delivery(tmp_path, "2025-26", "v2")
    approve(config, path, "2025-26", schema_version="v1")
    refused("schema_version_mismatch", prepare_delivery, config, registry_entry(), path)


# --- School year -------------------------------------------------------------

def test_school_year_comes_from_two_names_that_agree():
    config = real_config()
    assert resolve_school_year(config, "Enrollment-in-SY-2025-2026.zip", "x/enrollment_2025-26.csv") == "2025-26"
    refused("school_year_mismatch", resolve_school_year, config, "Enrollment-in-SY-2025-2026.zip", "enrollment_2024-25.csv")
    refused("school_year_mismatch", resolve_school_year, config, "Enrollment-in-SY-2025-2027.zip", "enrollment_2025-26.csv")
    refused("unrecognized_archive_name", resolve_school_year, config, "enrollment.zip", "enrollment_2025-26.csv")


# --- Rows: preserved as received ---------------------------------------------

def test_blanks_stay_blank_and_rows_are_numbered(tmp_path):
    config = empty_config()
    path = make_delivery(tmp_path, "2023-24", n_rows=5)
    approve(config, path, "2023-24")
    prepared = prepare_delivery(config, registry_entry(), path)
    assert [n for n, _ in prepared.rows] == [1, 2, 3, 4, 5]
    street = prepared.header.index("street_address")
    unique = prepared.header.index("g11_unique_male")
    assert all(values[street] == "" and values[unique] == "" for _, values in prepared.rows)


def test_header_only_file_fails_the_row_checks(tmp_path):
    config = empty_config()
    path = make_delivery(tmp_path, "2023-24", rows=[])
    approve(config, path, "2023-24", row_count=1)
    checks = checks_by_name(prepare_delivery(config, registry_entry(), path))
    assert checks["row_count_nonzero"].status == FAIL
    assert checks["row_count_matches_approved"].status == FAIL


def test_ragged_row_is_refused():
    refused("ragged_row", parse_csv, "a,b\n1,2\n3\n", "x.csv")


def test_blank_school_id_fails(tmp_path):
    config = empty_config()
    rows = make_rows(columns("v1"))
    rows[1][0] = ""
    path = make_delivery(tmp_path, "2023-24", rows=rows)
    approve(config, path, "2023-24")
    prepared = prepare_delivery(config, registry_entry(), path)
    assert checks_by_name(prepared)["school_id_not_blank"].status == FAIL
    assert prepared.failed_checks


def test_source_duplicates_are_kept_and_flagged(tmp_path):
    """Publisher duplicates are evidence: kept in Bronze, flagged, resolved in Silver."""
    config = empty_config()
    rows = make_rows(columns("v1"))
    rows.append(list(rows[0]))  # an exact repeat of row 1
    rows[1][0] = "12345"        # a malformed ID
    path = make_delivery(tmp_path, "2023-24", rows=rows)
    approve(config, path, "2023-24")
    prepared = prepare_delivery(config, registry_entry(), path)
    checks = checks_by_name(prepared)
    assert len(prepared.rows) == 4
    assert (checks["school_id_unique_in_file"].status, checks["school_id_unique_in_file"].actual) == (WARN, "1")
    assert checks["duplicate_rows_in_file"].status == WARN
    assert checks["school_id_format"].status == WARN
    assert not prepared.failed_checks


def test_identifier_format_checks_the_whole_value(tmp_path):
    config = empty_config()
    rows = make_rows(columns("v1"))
    rows[0][0] = "900001\n"  # '$' in a regex also matches before a final newline
    path = make_delivery(tmp_path, "2023-24", rows=rows)
    approve(config, path, "2023-24")
    assert checks_by_name(prepare_delivery(config, registry_entry(), path))["school_id_format"].actual == "1"


def test_check_results_hold_counts_not_values(tmp_path):
    config = empty_config()
    path = make_delivery(tmp_path, "2023-24")
    approve(config, path, "2023-24")
    text = " ".join(f"{c.expected} {c.actual}" for c in prepare_delivery(config, registry_entry(), path).checks)
    assert "900001" not in text and "Test School" not in text


# --- code_revision -----------------------------------------------------------

def test_explicit_revision_wins(repo_root):
    assert resolve_code_revision(repo_root, explicit="a" * 40, require_commit=True) == "a" * 40


@pytest.mark.parametrize("value", [UNSET, "abc123", "a" * 40 + "-dirty", "${bundle.git.commit}"])
def test_a_job_run_needs_a_full_commit(repo_root, value):
    refused("code_revision_required", resolve_code_revision, repo_root, explicit=value, require_commit=True)


def test_outside_git_the_revision_is_unset(tmp_path):
    assert resolve_code_revision(tmp_path) == UNSET


def test_local_revision_is_a_commit_or_marked_dirty(repo_root):
    revision = resolve_code_revision(repo_root)
    assert revision == UNSET or len(revision.removesuffix("-dirty")) == 40
