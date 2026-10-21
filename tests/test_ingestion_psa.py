"""PSA Poverty Stat (xlsx_sheet): what a workbook delivery must pass, and how it loads.

Every workbook here is made up (tests/factories/psa_workbooks.py) and approved into a copy
of the real psa_poverty_stat contract. Pipeline tests run the real etl/01_control
and etl/02_bronze SQL on an in-memory DuckDB inside a throwaway repository root.

test_psa_idempotency_demonstration walks the whole story in order; the others
check one behavior each.
"""

import copy
import shutil
import zipfile

import pytest

from factories import psa_workbooks as psa
from factories.deped_deliveries import approve as approve_zip, empty_config as empty_zip_config, make_delivery
from factories.psa_workbooks import (
    SHEET, SOURCE, WORKBOOK, add_schema, approve, banner, columns_for, default_rows, empty_config, fake_repo,
    real_config, registry_entry, unit, workbook_bytes, write_config, write_workbook,
)
from src.ingestion import cli, control, pipeline
from src.ingestion.batch import batch_id, load_type_for_years
from src.ingestion.contract import XLSX_PROVENANCE_COLUMNS, load_source_config, validate_config
from src.ingestion.errors import IngestionError
from src.ingestion.pipeline import IngestionRun
from src.ingestion.store import DuckDBStore
from src.ingestion.validate import FAIL, PASS, WARN
from src.ingestion.workbook import prepare_workbook

REVISION = "c" * 40
BRONZE = "edu_access.`02-bronze`.psa_poverty_stat_raw"
CONTROL = "edu_access.`01-control`"
YEARS = ("2018", "2021", "2023")


def refused(code, fn, *args, **kwargs):
    with pytest.raises(IngestionError) as e:
        fn(*args, **kwargs)
    assert e.value.code == code, e.value
    return e.value


def checks(prepared):
    return {c.check_name: c for c in prepared.checks}


def prepared_for(tmp_path, config=None, approve_kwargs=None, **workbook_kwargs):
    config = config or empty_config()
    path = write_workbook(tmp_path / "psa" / WORKBOOK, **workbook_kwargs)
    approve(config, path, rows=workbook_kwargs.get("rows"), footer=workbook_kwargs.get("footer"),
            **(approve_kwargs or {}))
    return prepare_workbook(config, registry_entry(SOURCE), path)


# --- The real contract ---------------------------------------------------------

def test_real_psa_contract_loads_and_does_not_promote_the_source(repo_root):
    config, entry = load_source_config(repo_root, SOURCE)
    d = config["deliveries"][0]
    assert (d["workbook"], d["sheet"], d["estimate_years"]) == (WORKBOOK, SHEET, list(YEARS))
    assert (d["body_rows"], d["unit_rows"], d["banner_rows"], d["footer_rows"]) == ({"first": 6, "last": 1635}, 1612, 18, 6)
    assert entry["status"] == "accepted", "accepted by the team on 2026-10-21 (D-063); a status change is a team decision"


def test_v1_columns_are_the_data_dictionary_columns(repo_root):
    """The contract's 18 names are the ones the profile built from the merged header, in order."""
    dictionary = (repo_root / "docs/data/source-inventory/psa_poverty_stat/data_dictionary.md").read_text(encoding="utf-8")
    documented = [line.split("|")[1].strip().strip("`") for line in dictionary.splitlines()
                  if line.startswith("| `")]
    assert real_config()["schema_versions"]["v1"]["columns"] == documented == columns_for(YEARS)


def test_xlsx_provenance_covers_the_required_set():
    required = {"source_id", "source_system", "source_url", "source_sheet", "source_file", "source_sha256",
                "source_row_number", "estimate_years_covered", "ingested_at_utc", "batch_id", "run_id",
                "schema_version", "schema_fingerprint", "code_revision"}
    assert required <= set(XLSX_PROVENANCE_COLUMNS)
    assert "school_year" not in XLSX_PROVENANCE_COLUMNS  # years are delivery metadata, not one row's year


@pytest.mark.parametrize("break_it, message", [
    (lambda c: c["deliveries"].append(copy.deepcopy(c["deliveries"][0])), "approved twice"),
    (lambda c: c["deliveries"][0].update(estimate_years=["2018", "2021"]), "differ from the years"),
    (lambda c: c["deliveries"][0].update(estimate_years=["2023", "2018", "2021"]), "sorted"),
    (lambda c: c["deliveries"][0].update(delivery_version=2), "1, 2, 3"),
    (lambda c: c["deliveries"][0].update(workbook_sha256="ABC"), "SHA-256"),
    (lambda c: c["deliveries"][0].update(workbook="poverty.xlsx"), "would not be discovered"),
    (lambda c: c["deliveries"][0].update(unit_rows=1613), "must equal the body rows"),
    (lambda c: c["deliveries"][0].update(schema_version="v9"), "not defined"),
    (lambda c: c["schema_versions"]["v1"]["columns"].append("batch_id"), "provenance"),
    (lambda c: c["schema_versions"]["v1"]["columns"].append("source_row_kind"), "provenance"),
    (lambda c: c["schema_versions"]["v1"]["columns"].remove("PSGC ID"), "required"),
    (lambda c: c["schema_versions"]["v1"]["layout"].pop("footer_marker"), "layout is missing"),
    (lambda c: c["known_issues"].append({"name": "x", "check": "guess", "finding": "-", "profiled": 0}), "is not one of"),
    (lambda c: c.update(format="pdf"), "format"),
])
def test_contract_refuses_ambiguous_config(break_it, message):
    config = real_config()
    break_it(config)
    error = refused("invalid_config", validate_config, config, registry_entry(SOURCE))
    assert message in error.message


def test_overlapping_years_must_be_a_version_of_the_same_dataset():
    """A workbook republishing an approved year can only be approved as the next version of that dataset."""
    config = real_config()
    other = copy.deepcopy(config["deliveries"][0])
    other.update(logical_dataset="sae_rerelease", workbook="3_2023 SAE_revised.xlsx", workbook_sha256="1" * 64)
    config["deliveries"].append(other)
    error = refused("invalid_config", validate_config, config, registry_entry(SOURCE))
    assert "both cover" in error.message

    other.update(logical_dataset=config["deliveries"][0]["logical_dataset"], delivery_version=2, supersedes=None)
    refused("invalid_config", validate_config, config, registry_entry(SOURCE))  # must name what it supersedes
    other["supersedes"] = config["deliveries"][0]["workbook_sha256"]
    validate_config(config, registry_entry(SOURCE))


def test_a_revision_must_keep_every_estimate_year_it_supersedes():
    """current_batches makes one version per logical dataset current, so a revision that drops a year would hide it.

    Review of #109: v1 covers 2018, 2021, 2023 and v2 covers 2023, 2025. Without this rule both load, and Silver,
    reading current_batches, sees only v2: 2018 and 2021 disappear although they are still in Bronze.
    """
    config = real_config()
    v1 = config["deliveries"][0]
    add_schema(config, "v2", ["2023", "2025"])
    v2 = copy.deepcopy(v1)
    v2.update(estimate_years=["2023", "2025"], schema_version="v2", delivery_version=2,
              supersedes=v1["workbook_sha256"], workbook="2_2025 SAE_with PSGC_noHUC_01Feb2028.xlsx",
              workbook_sha256="2" * 64)
    config["deliveries"].append(v2)
    error = refused("invalid_config", validate_config, config, registry_entry(SOURCE))
    assert "drops ['2018', '2021']" in error.message

    add_schema(config, "v3", ["2018", "2021", "2023", "2025"])
    v2.update(estimate_years=["2018", "2021", "2023", "2025"], schema_version="v3")
    validate_config(config, registry_entry(SOURCE))  # a revision that keeps every year and adds one is fine


# --- Checksums and identity --------------------------------------------------------

def test_approved_fixture_passes_and_flags_known_quirks(tmp_path):
    prepared = prepared_for(tmp_path)
    by_name = checks(prepared)
    assert not prepared.failed_checks, prepared.failed_checks
    assert (prepared.estimate_years, prepared.sheet, len(prepared.header)) == (list(YEARS), SHEET, 18)
    assert dict(prepared.kind_counts()) == {"title": 1, "header": 4, "unit": 6, "region_banner": 2, "footer": 6}
    for name in ("psgc_id_leading_zero_lost", "unit_rows_without_estimates", "province_label_continued",
                 "lower_limit_zero_or_negative", "cv_over_20_2018", "se_disagrees_with_cv_2018"):
        assert by_name[f"known_issue_{name}"].status == WARN, name
    assert by_name["known_issue_psgc_id_leading_zero_lost"].expected == "0 (profiled: 1073, O-2)"


def test_same_bytes_give_the_same_checksum_and_batch_id(tmp_path):
    a = write_workbook(tmp_path / "a" / WORKBOOK)
    b = write_workbook(tmp_path / "b" / "renamed.xlsx")
    assert a.read_bytes() == b.read_bytes()
    assert batch_id(SOURCE, "2018,2021,2023", "f" * 64) == f"{SOURCE}__2018-2021-2023__ffffffffffff"


def test_same_filename_with_changed_bytes_is_not_the_approved_file(tmp_path):
    config = empty_config()
    path = write_workbook(tmp_path / WORKBOOK)
    approve(config, path)
    write_workbook(path, rows=default_rows()[:-1])  # one unit fewer, same name
    error = refused("checksum_mismatch", prepare_workbook, config, registry_entry(SOURCE), path)
    assert "not approved" in error.message and "supersedes" in error.message


def test_unknown_and_missing_workbooks_are_refused(tmp_path):
    path = write_workbook(tmp_path / WORKBOOK)
    refused("unregistered_delivery", prepare_workbook, empty_config(), registry_entry(SOURCE), path)
    refused("missing_archive", prepare_workbook, empty_config(), registry_entry(SOURCE), tmp_path / "gone.xlsx")


# --- Safe reading ----------------------------------------------------------------------

def approved_bytes(tmp_path, data_or_parts):
    """Write bytes (or parts) under the workbook name and approve exactly those bytes."""
    config = empty_config()
    path = tmp_path / WORKBOOK
    if isinstance(data_or_parts, bytes):
        path.write_bytes(data_or_parts)
    else:
        write_workbook(path, parts=data_or_parts)
    approve(config, path)
    return config, path


def test_a_file_that_is_not_a_zip_is_refused(tmp_path):
    config, path = approved_bytes(tmp_path, b"this is not a workbook")
    refused("corrupt_archive", prepare_workbook, config, registry_entry(SOURCE), path)


def test_a_zip_that_is_not_a_workbook_is_refused(tmp_path):
    config, path = approved_bytes(tmp_path, {"data.csv": "a,b\n1,2\n"})
    refused("corrupt_workbook", prepare_workbook, config, registry_entry(SOURCE), path)


def test_xml_with_a_dtd_is_refused_before_parsing(tmp_path):
    parts = workbook_bytes()
    parts["xl/sharedStrings.xml"] = parts["xl/sharedStrings.xml"].replace(
        "<sst ", '<!DOCTYPE sst [<!ENTITY a "aaaa">]><sst ', 1)
    config, path = approved_bytes(tmp_path, parts)
    refused("unsafe_workbook", prepare_workbook, config, registry_entry(SOURCE), path)


def test_unsafe_member_paths_are_refused(tmp_path):
    parts = workbook_bytes()
    parts["../../evil.xml"] = "<x/>"
    config, path = approved_bytes(tmp_path, parts)
    refused("unsafe_member", prepare_workbook, config, registry_entry(SOURCE), path)


def test_oversized_workbook_is_refused(tmp_path):
    config, path = approved_bytes(tmp_path, workbook_bytes())
    config["max_uncompressed_bytes"] = 1000
    refused("archive_too_large", prepare_workbook, config, registry_entry(SOURCE), path)


def test_truncated_workbook_is_refused(tmp_path):
    good = write_workbook(tmp_path / "good.xlsx").read_bytes()
    config, path = approved_bytes(tmp_path, good[: len(good) // 2])
    with pytest.raises(IngestionError) as e:
        prepare_workbook(config, registry_entry(SOURCE), path)
    assert e.value.code in ("corrupt_archive", "corrupt_workbook")


def test_reading_never_changes_the_file(tmp_path):
    path = write_workbook(tmp_path / "psa" / WORKBOOK)
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    config = empty_config()
    approve(config, path)
    prepare_workbook(config, registry_entry(SOURCE), path)
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    assert sorted(p.name for p in path.parent.iterdir()) == [WORKBOOK]  # nothing extracted


# --- Sheet, merged header, banners, footer ---------------------------------------------

def test_missing_sheet_is_refused(tmp_path):
    config = empty_config()
    path = write_workbook(tmp_path / WORKBOOK, sheet="2025_NoHUC")
    approve(config, path)
    refused("missing_sheet", prepare_workbook, config, registry_entry(SOURCE), path)


def test_an_extra_sheet_is_refused_until_approved(tmp_path):
    config = empty_config()
    path = write_workbook(tmp_path / WORKBOOK, extra_sheets=["HUC"])
    entry = approve(config, path)
    refused("unexpected_sheet", prepare_workbook, config, registry_entry(SOURCE), path)
    entry["expected_sheets"] = [SHEET, "HUC"]  # a reviewer approved it, having profiled it
    assert not prepare_workbook(config, registry_entry(SOURCE), path).failed_checks


def test_renamed_header_is_unknown_drift(tmp_path):
    config = empty_config()
    path = write_workbook(tmp_path / WORKBOOK, header_override={(2, 7): "CV"})
    approve(config, path)
    error = refused("unknown_schema_drift", prepare_workbook, config, registry_entry(SOURCE), path)
    assert "Coefficient of Variation 2018" in error.message


def test_a_new_year_in_the_header_is_unknown_drift(tmp_path):
    config = empty_config()
    path = write_workbook(tmp_path / WORKBOOK, years=("2018", "2021", "2023", "2025"))
    approve(config, path, rows=default_rows(("2018", "2021", "2023", "2025")))
    refused("unknown_schema_drift", prepare_workbook, config, registry_entry(SOURCE), path)


def test_header_that_is_not_merged_as_profiled_is_refused(tmp_path):
    config = empty_config()
    path = write_workbook(tmp_path / WORKBOOK, merges=["B2:B5", "C2:C5"])
    approve(config, path)
    error = refused("unexpected_header_layout", prepare_workbook, config, registry_entry(SOURCE), path)
    assert "'Poverty Incidence' (D2:F2)" in error.message


def test_missing_footer_is_refused(tmp_path):
    config = empty_config()
    path = write_workbook(tmp_path / WORKBOOK, footer=["Source: made up"])
    approve(config, path, footer=["Source: made up"])
    refused("footer_not_found", prepare_workbook, config, registry_entry(SOURCE), path)


def test_footer_and_body_boundaries_are_reconciled(tmp_path):
    longer = psa.FOOTER + ["4/ A new footnote."]
    prepared = prepared_for(tmp_path, footer=longer, approve_kwargs={"footer_rows": 6})
    assert checks(prepared)["footer_rows_match_approved"].status == FAIL
    assert [n for n, k in prepared.row_kinds.items() if k in ("unit", "region_banner")] == list(range(6, 14))
    assert [n for n, k in prepared.row_kinds.items() if k == "footer"] == list(range(14, 21))  # kept, but never data


def test_unit_and_banner_counts_are_reconciled_separately(tmp_path):
    prepared = prepared_for(tmp_path, approve_kwargs={"unit_rows": 7, "banner_rows": 1})
    by_name = checks(prepared)
    assert (by_name["unit_rows_match_approved"].status, by_name["region_banner_rows_match_approved"].status) == (FAIL, FAIL)
    assert by_name["row_count_matches_approved"].status == PASS  # the total alone would have hidden it


def test_a_row_that_is_neither_unit_nor_banner_fails(tmp_path):
    rows = default_rows() + [{"Region/Province": "Odd", "Poverty Incidence 2018": "12.5"}]  # values, no ID
    prepared = prepared_for(tmp_path, rows=rows, approve_kwargs={"unit_rows": 6, "banner_rows": 3})
    assert checks(prepared)["unclassified_rows"].status == FAIL


def test_blank_rows_in_the_body_are_kept_and_counted(tmp_path):
    rows = default_rows()[:4] + [{}] + default_rows()[4:]
    prepared = prepared_for(tmp_path, rows=rows)
    assert checks(prepared)["blank_rows_match_approved"].status == PASS
    assert prepared.row_kinds[10] == "blank" and dict(prepared.rows)[10] == [""] * 18


def test_values_in_ignored_column_s_or_beyond_fail(tmp_path):
    prepared = prepared_for(tmp_path, extra_cells={(8, 19): "1", (9, 21): "x"})
    by_name = checks(prepared)
    assert by_name["ignored_columns_empty"].status == FAIL and by_name["ignored_columns_empty"].actual == "1"
    assert by_name["no_cells_outside_layout"].status == FAIL


def test_used_range_must_match_the_approval(tmp_path):
    prepared = prepared_for(tmp_path, approve_kwargs={"used_range": "A1:S99"})
    assert checks(prepared)["used_range_matches_approved"].status == FAIL


def test_title_header_and_footer_rows_are_kept_with_their_text(tmp_path):
    """No worksheet row is dropped: context rows are loaded as received and labelled, not treated as data."""
    prepared = prepared_for(tmp_path)
    rows, kinds = dict(prepared.rows), prepared.row_kinds
    assert [n for n in sorted(kinds)] == list(range(1, 20))
    assert kinds[1] == "title" and rows[1][1] == psa.TITLE
    assert kinds[4] == "header" and rows[4][0] == "ID" and rows[5][3] == "2018"
    assert kinds[14] == "footer" and rows[14][0] == "Notes:" and rows[19][0].startswith("Source:")
    assert kinds[18] == "footer" and rows[18] == [""] * 18  # a blank footer line is kept too


def test_formula_cells_keep_their_stored_value_and_are_flagged(tmp_path):
    """A formula is never evaluated: Bronze keeps the value Excel stored, and the batch records a WARN."""
    parts = workbook_bytes()
    sheet = parts["xl/worksheets/sheet1.xml"]
    stored = '<c r="D7"><v>13.5</v></c>'
    assert stored in sheet
    parts["xl/worksheets/sheet1.xml"] = sheet.replace(stored, '<c r="D7"><f>1+1</f><v>13.5</v></c>')
    config, path = approved_bytes(tmp_path, parts)
    prepared = prepare_workbook(config, registry_entry(SOURCE), path)
    assert dict(prepared.rows)[7][3] == "13.5"
    assert checks(prepared)["formula_cells"].status == WARN and checks(prepared)["formula_cells"].actual == "1"


def test_a_repeated_header_inside_the_body_fails(tmp_path):
    """A header repeated mid-sheet (as on a printed page break) is not a city: its 'PSGC' fails the ID check."""
    repeat = {"PSGC ID": "PSGC", "Region/Province": "Region/Province", "Municipality/City": "Municipality/City"}
    rows = default_rows()[:4] + [repeat] + default_rows()[4:]
    prepared = prepared_for(tmp_path, rows=rows)
    assert checks(prepared)["PSGC ID_format_on_unit_rows"].status == FAIL


# --- Values kept exactly as received --------------------------------------------------

def test_unicode_precision_and_blanks_are_preserved(tmp_path):
    prepared = prepared_for(tmp_path)
    rows = dict(prepared.rows)
    h = prepared.header
    assert rows[7][h.index("Municipality/City")] == "Doña Test"
    assert rows[7][h.index("PSGC ID")] == "99101"  # 5 digits, not padded in Bronze
    assert rows[8][h.index("90% Confidence Interval Lower Limit 2023")] == "-2.4063453271442992E-2"  # not clipped
    assert rows[8][h.index("Poverty Incidence 2023")] == "0.69430000000000003"  # not rounded
    assert rows[9][3:] == [""] * 15  # no estimate: blank, not zero
    assert rows[6] == ["", "Test Region Alpha"] + [""] * 16  # banner kept with its label
    assert rows[11][h.index("Region/Province")] == "(Continued)"  # labels not standardized
    assert prepared.row_kinds[6] == "region_banner" and prepared.row_kinds[7] == "unit"


def test_malformed_identifier_on_a_unit_row_fails(tmp_path):
    rows = default_rows()
    rows[1] = dict(rows[1], **{"PSGC ID": "9910A"})
    assert checks(prepared_for(tmp_path, rows=rows))["PSGC ID_format_on_unit_rows"].status == FAIL


def test_source_duplicates_are_warned_not_dropped(tmp_path):
    rows = default_rows() + [dict(default_rows()[1])]
    prepared = prepared_for(tmp_path, rows=rows)
    by_name = checks(prepared)
    assert (by_name["PSGC ID_unique_in_file"].status, by_name["duplicate_rows_in_file"].status) == (WARN, WARN)
    assert sum(1 for k in prepared.row_kinds.values() if k == "unit") == 7 and not prepared.failed_checks


def test_known_issue_checks_for_other_years_do_not_apply(tmp_path):
    """A 2025-only workbook has no 2018 CV column: that check is skipped, not crashed on or counted as 0."""
    config = empty_config()
    add_schema(config, "v2", ["2025"])
    path = write_workbook(tmp_path / "2_2025 SAE_test.xlsx", years=("2025",))
    approve(config, path, years=("2025",), rows=default_rows(("2025",)), logical_dataset="sae_2025", schema_version="v2")
    prepared = prepare_workbook(config, registry_entry(SOURCE), path)
    names = set(checks(prepared))
    assert not prepared.failed_checks
    assert "known_issue_cv_over_20_2018" not in names and "known_issue_psgc_id_leading_zero_lost" in names


def test_check_results_hold_counts_not_values(tmp_path):
    for c in prepared_for(tmp_path).checks:
        for text in ("Doña", "Test City", "99101", "12.5"):
            assert text not in c.actual


# --- Load types ------------------------------------------------------------------------

@pytest.mark.parametrize("years, version, succeeded, expected", [
    (["2018", "2021", "2023"], 1, set(), "initial"),
    (["2025"], 1, {"2018", "2021", "2023"}, "incremental"),
    (["2015"], 1, {"2018", "2021", "2023"}, "backfill"),
    (["2018", "2021", "2023"], 2, {"2018", "2021", "2023"}, "revision"),
    (["2023", "2025"], 1, {"2018", "2021", "2023"}, "revision"),
])
def test_load_type_compares_estimate_year_sets(years, version, succeeded, expected):
    assert load_type_for_years({"estimate_years": years, "delivery_version": version}, succeeded) == expected


# --- The pipeline ------------------------------------------------------------------------

class Env:
    def __init__(self, tmp_path):
        self.config = empty_config()
        self.landing = tmp_path / "landing"
        self.inbox = self.landing / "psa"
        self.repo = fake_repo(tmp_path / "repo", self.config)
        self.store = DuckDBStore()

    def deliver(self, name=WORKBOOK, folder="original", approve_it=True, years=YEARS, approve_kwargs=None, **kwargs):
        path = write_workbook(self.inbox / folder / name, years=years, **kwargs)
        if approve_it:
            self.approve(path, years=years, rows=kwargs.get("rows"), **(approve_kwargs or {}))
        return path

    def approve(self, path, **kwargs):
        entry = approve(self.config, path, **kwargs)
        write_config(self.repo, self.config)
        return entry

    def run(self, rerun=(), hook=None):
        return IngestionRun(self.store, self.repo, SOURCE, self.landing, "local", REVISION,
                            rerun_batch_ids=rerun, hook=hook).execute()

    def q(self, sql):
        return self.store.query(sql)

    def one(self, sql):
        return self.q(sql)[0][0]

    def bronze_rows(self, where="TRUE"):
        return self.one(f"SELECT COUNT(*) FROM {BRONZE} WHERE {where}")

    def batch(self, where):
        rows = self.store.records(f"SELECT * FROM {CONTROL}.ingestion_batches WHERE {where}")
        return rows[0] if rows else None


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def outcome(summary, label):
    return next(o for o in summary.outcomes if o.school_year == label)


V1 = "2018,2021,2023"
SHEET_ROWS = 19  # a default fixture sheet: 1 title + 4 header + 8 body (6 units, 2 banners) + 6 footer rows
NEW = "2_2025 SAE_with PSGC_noHUC_01Feb2028.xlsx"
OLD = "2_2015 SAE_with PSGC_noHUC_01Jan2017.xlsx"


def test_psa_idempotency_demonstration(env):
    # 1-2. Load one workbook; record its batch and Bronze row count.
    env.deliver()
    first = env.run()
    assert first.status == "succeeded"
    o = outcome(first, V1)
    assert (o.action, o.load_type, o.rows_inserted, o.bronze_rows) == ("load", "initial", SHEET_ROWS, SHEET_ROWS)
    batch = env.batch(f"estimate_years_covered = '{V1}'")
    assert (batch["status"], batch["expected_rows"], batch["source_rows"], batch["bronze_rows"]) == ("succeeded", SHEET_ROWS, SHEET_ROWS, SHEET_ROWS)
    assert (batch["logical_dataset"], batch["source_sheet"], batch["school_year"]) == (
        "sae_city_municipal_2018_2021_2023", SHEET, None)
    assert env.q(f"SELECT source_row_kind, COUNT(*) FROM {BRONZE} GROUP BY 1 ORDER BY 1") == [
        ("footer", 6), ("header", 4), ("region_banner", 2), ("title", 1), ("unit", 6)]  # every sheet row, by kind

    # 3-4. The exact same ingestion again: skipped, no new rows.
    second = env.run()
    assert (second.status, outcome(second, V1).action, outcome(second, V1).rows_inserted) == ("succeeded", "skip", 0)
    assert env.bronze_rows() == SHEET_ROWS

    # 5. The audit history says what happened, run by run.
    attempts = env.q(f"SELECT run_id, action, outcome, rows_inserted, estimate_years_covered "
                     f"FROM {CONTROL}.ingestion_batch_attempts ORDER BY started_at_utc")
    assert attempts == [(first.run_id, "load", "succeeded", SHEET_ROWS, V1), (second.run_id, "skip", "skipped", 0, V1)]

    # 6. A workbook with a new estimate year loads as an incremental batch; the first is untouched.
    add_schema(env.config, "v2", ["2025"])
    env.deliver(NEW, folder="2028-02-15", years=("2025",), rows=default_rows(("2025",), first_id=99201),
                approve_kwargs={"logical_dataset": "sae_city_municipal_2025", "schema_version": "v2"})
    third = env.run()
    assert (outcome(third, "2025").action, outcome(third, "2025").load_type) == ("load", "incremental")
    assert outcome(third, V1).action == "skip"
    assert env.one(f"SELECT COUNT(DISTINCT run_id) FROM {BRONZE} WHERE estimate_years_covered = '{V1}'") == 1
    assert env.bronze_rows("estimate_years_covered = '2025' AND source_row_kind = 'unit'") == 6
    assert env.bronze_rows("estimate_years_covered = '2025' AND \"Poverty Incidence 2018\" IS NULL") == SHEET_ROWS  # absent, not blank

    # 7. Same file name, different bytes: blocked, and recognized as a likely revision of loaded years.
    write_workbook(env.inbox / "redownload" / WORKBOOK, rows=default_rows()[:-1])
    fourth = env.run()
    changed = next(o for o in fourth.outcomes if o.outcome == "blocked")
    assert (changed.archive_name, changed.load_type) == (WORKBOOK, "revision")
    assert "not approved" in changed.message
    assert fourth.status == "failed"
    assert env.bronze_rows(f"estimate_years_covered = '{V1}'") == SHEET_ROWS
    assert env.batch(f"estimate_years_covered = '{V1}' AND status = 'blocked'")["error_code"] == "checksum_mismatch"


def test_every_bronze_row_traces_to_its_excel_row(env):
    path = env.deliver()
    summary = env.run()
    row = env.store.records(f"SELECT * FROM {BRONZE} WHERE source_row_number = 7")[0]
    assert (row["source_id"], row["source_file"], row["source_sheet"]) == (SOURCE, WORKBOOK, SHEET)
    assert row["source_url"].startswith("https://psa.gov.ph/") and row["source_system"]
    assert (row["logical_dataset"], row["estimate_years_covered"], row["delivery_version"]) == (
        "sae_city_municipal_2018_2021_2023", V1, 1)
    assert row["source_sha256"] == env.config["deliveries"][0]["workbook_sha256"] == psa.hashlib.sha256(path.read_bytes()).hexdigest()
    assert (row["source_row_kind"], row["PSGC ID"], row["Municipality/City"]) == ("unit", "99101", "Doña Test")
    assert (row["run_id"], row["code_revision"], row["schema_version"]) == (summary.run_id, REVISION, "v1")
    assert len(row["schema_fingerprint"]) == 64 and row["ingested_at_utc"] is not None
    assert row["batch_id"].startswith(f"{SOURCE}__2018-2021-2023__")
    assert env.q(f"SELECT MIN(source_row_number), MAX(source_row_number) FROM {BRONZE}") == [(1, SHEET_ROWS)]
    assert env.q(f"SELECT source_row_kind FROM {BRONZE} WHERE source_row_number IN (1, 2, 6, 14) ORDER BY source_row_number") == [
        ("title",), ("header",), ("region_banner",), ("footer",)]
    nulls = " OR ".join(f'"{c}" IS NULL' for c in XLSX_PROVENANCE_COLUMNS)
    assert env.bronze_rows(nulls) == 0


def test_bronze_keeps_raw_values(env):
    env.deliver()
    env.run()
    blank = env.bronze_rows("\"Municipality/City\" = 'No Estimate Town' AND \"Poverty Incidence 2018\" = ''")
    assert blank == 1  # blank, not NULL and not 0
    assert env.one(f"SELECT \"90% Confidence Interval Lower Limit 2023\" FROM {BRONZE} WHERE source_row_number = 8") == "-2.4063453271442992E-2"
    assert env.bronze_rows("\"PSGC ID\" = '99101'") == 1 and env.bronze_rows("\"PSGC ID\" = '099101'") == 0


def test_rerun_validates_again_and_adds_nothing(env):
    env.deliver()
    env.run()
    bid = env.batch("TRUE")["batch_id"]
    o = env.run(rerun=[bid]).outcomes[0]
    assert (o.action, o.outcome, o.rows_inserted, o.bronze_rows) == ("rerun", "succeeded", 0, SHEET_ROWS)
    assert env.bronze_rows() == SHEET_ROWS and env.batch("TRUE")["attempt_count"] == 2


def test_failed_batch_can_be_retried(env):
    path = env.deliver(approve_kwargs={"unit_rows": 7, "banner_rows": 1})  # an approval mistake
    first = env.run()
    assert (first.outcomes[0].outcome, first.status) == ("failed", "failed")
    assert env.bronze_rows() == 0  # nothing loaded when a pre-load check fails
    fails = {r[0] for r in env.q(f"SELECT check_name FROM {CONTROL}.data_quality_results WHERE status = 'FAIL'")}
    assert fails == {"unit_rows_match_approved", "region_banner_rows_match_approved"}

    env.config["deliveries"][0].update(unit_rows=6, banner_rows=2)  # fixed in review
    write_config(env.repo, env.config)
    o = env.run().outcomes[0]
    assert (o.action, o.outcome, o.load_type) == ("retry", "succeeded", "initial")
    assert env.batch("TRUE")["attempt_count"] == 2 and path.exists()


def test_late_historical_year_is_a_backfill(env):
    env.deliver()
    env.run()
    add_schema(env.config, "v2015", ["2015"])
    env.deliver(OLD, folder="2026-11-01", years=("2015",), rows=default_rows(("2015",), first_id=99301),
                approve_kwargs={"logical_dataset": "sae_city_municipal_2015", "schema_version": "v2015"})
    summary = env.run()
    assert [(o.school_year, o.action, o.load_type) for o in summary.outcomes] == [
        ("2015", "load", "backfill"), (V1, "skip", "initial")]
    assert env.bronze_rows("source_row_kind = 'unit'") == 12


def test_approved_revision_keeps_both_versions(env):
    v1 = env.deliver()
    env.run()
    revised = write_workbook(env.inbox / "2026-12-01" / WORKBOOK, rows=default_rows()[:-1])
    env.approve(revised, rows=default_rows()[:-1], delivery_version=2,
                supersedes=env.config["deliveries"][0]["workbook_sha256"])
    summary = env.run()
    o = next(o for o in summary.outcomes if o.action == "load")
    assert (o.load_type, o.rows_inserted) == ("revision", SHEET_ROWS - 1)
    assert env.q(f"SELECT delivery_version, COUNT(*) FROM {BRONZE} WHERE source_row_kind = 'unit' GROUP BY 1 ORDER BY 1") == [(1, 6), (2, 5)]
    assert env.q(f"SELECT logical_dataset, delivery_version FROM {CONTROL}.current_batches") == [
        ("sae_city_municipal_2018_2021_2023", 2)]
    assert v1.exists()


REVISED = "2_2025 SAE_with PSGC_noHUC_01Feb2028.xlsx"


def test_revision_dropping_estimate_years_is_refused_and_every_year_stays_current(env):
    """The reviewer's case from #109, end to end: a v2 covering 2023, 2025 must not hide 2018 and 2021."""
    v1 = env.deliver()
    env.run()
    add_schema(env.config, "v2", ["2023", "2025"])
    years = ("2023", "2025")
    env.deliver(REVISED, folder="2027-12-01", years=years, rows=default_rows(years),
                approve_kwargs={"schema_version": "v2", "delivery_version": 2,
                                "supersedes": env.config["deliveries"][0]["workbook_sha256"]})
    error = refused("invalid_config", env.run)
    assert "drops ['2018', '2021']" in error.message
    # Nothing was loaded, and v1, with all three years, is still what Silver reads.
    assert env.q(f"SELECT estimate_years_covered, delivery_version FROM {CONTROL}.current_batches") == [(V1, 1)]
    assert env.bronze_rows() == SHEET_ROWS and v1.exists()


def test_superset_revision_keeps_every_year_current(env):
    """A revision that keeps the old years and adds one becomes current with every year still visible."""
    env.deliver()
    env.run()
    add_schema(env.config, "v2", ["2018", "2021", "2023", "2025"])
    years = ("2018", "2021", "2023", "2025")
    env.deliver(REVISED, folder="2027-12-01", years=years, rows=default_rows(years),
                approve_kwargs={"schema_version": "v2", "delivery_version": 2,
                                "supersedes": env.config["deliveries"][0]["workbook_sha256"]})
    summary = env.run()
    o = next(o for o in summary.outcomes if o.action == "load")
    assert (o.load_type, o.outcome) == ("revision", "succeeded")
    assert env.q(f"SELECT estimate_years_covered, delivery_version FROM {CONTROL}.current_batches") == [
        ("2018,2021,2023,2025", 2)]
    assert env.q(f"SELECT delivery_version, COUNT(*) FROM {BRONZE} WHERE source_row_kind = 'unit' "
                 "GROUP BY 1 ORDER BY 1") == [(1, 6), (2, 6)]  # v1 stays in Bronze


def test_separate_datasets_are_each_current(env):
    """current_batches partitions workbook batches by logical dataset, so a 2025 workbook does not hide 2018-2023."""
    env.deliver()
    add_schema(env.config, "v2", ["2025"])
    env.deliver(NEW, years=("2025",), rows=default_rows(("2025",), first_id=99201),
                approve_kwargs={"logical_dataset": "sae_city_municipal_2025", "schema_version": "v2"})
    env.run()
    assert env.q(f"SELECT estimate_years_covered FROM {CONTROL}.current_batches ORDER BY 1") == [("2018,2021,2023",), ("2025",)]


def test_unknown_drift_fails_the_batch_and_loads_nothing(env):
    env.deliver(header_override={(2, 10): "Std Error"})
    summary = env.run()
    assert (summary.outcomes[0].outcome, summary.status) == ("failed", "failed")
    assert env.batch("TRUE")["error_code"] == "unknown_schema_drift"
    assert env.bronze_rows() == 0


class SimulatedCrash(BaseException):
    """The process dying mid-load. BaseException, so the pipeline cannot catch and record it."""


def test_interrupted_load_is_invisible_then_recovered(env):
    env.deliver()

    def crash(stage):
        if stage == "after_bronze_merge":
            raise SimulatedCrash()

    with pytest.raises(SimulatedCrash):
        env.run(hook=crash)
    assert env.batch("TRUE")["status"] == "loading"
    assert env.q(f"SELECT * FROM {CONTROL}.current_batches") == []  # downstream cannot see it
    o = env.run().outcomes[0]
    assert (o.action, o.outcome, o.rows_inserted, o.bronze_rows) == ("retry", "succeeded", 0, SHEET_ROWS)


def test_partial_write_is_completed_without_duplicates(env):
    env.deliver()

    def lose_rows(stage):
        if stage == "after_bronze_merge":
            env.store.sql(f"DELETE FROM {BRONZE} WHERE source_row_number > 9")
            raise SimulatedCrash()

    with pytest.raises(SimulatedCrash):
        env.run(hook=lose_rows)
    assert env.bronze_rows() == 9
    o = env.run().outcomes[0]
    assert (o.outcome, o.rows_inserted, o.bronze_rows) == ("succeeded", SHEET_ROWS - 9, SHEET_ROWS)
    assert env.one(f"SELECT COUNT(*) - COUNT(DISTINCT source_row_number) FROM {BRONZE}") == 0


def test_a_lost_banner_row_fails_reconciliation(env):
    env.deliver()

    def lose_banner(stage):
        if stage == "after_bronze_merge":
            env.store.sql(f"DELETE FROM {BRONZE} WHERE source_row_kind = 'region_banner' AND source_row_number = 10")

    summary = env.run(hook=lose_banner)
    assert summary.status == "failed"
    fails = {r[0] for r in env.q(f"SELECT check_name FROM {CONTROL}.data_quality_results WHERE status = 'FAIL'")}
    assert {"bronze_rows_match_source", "bronze_row_kinds_match_source"} <= fails
    assert env.q(f"SELECT * FROM {CONTROL}.current_batches") == []


def test_gate_catches_pipeline_duplicates(env):
    env.deliver()
    env.run()
    env.store.sql(f"INSERT INTO {BRONZE} SELECT * FROM {BRONZE} LIMIT 1")
    summary = env.run()
    assert summary.status == "failed" and "Bronze gate failed" in summary.gate_error
    fails = {r[0] for r in env.q(f"SELECT check_name FROM {CONTROL}.data_quality_results "
                                 f"WHERE run_id = '{summary.run_id}' AND status = 'FAIL'")}
    assert "no_pipeline_duplicates" in fails


def test_office_lock_files_and_other_psa_files_are_not_deliveries(env):
    env.deliver()
    (env.inbox / "original" / f"~${WORKBOOK}").write_bytes(b"lock")
    (env.inbox / "original" / "PSGC-2Q-2026-Publication-Datafile.xlsx").write_bytes(b"another source")
    summary = env.run()
    assert [o.archive_name for o in summary.outcomes] == [WORKBOOK] and summary.status == "succeeded"


def test_known_issue_warnings_are_recorded_and_do_not_block(env):
    env.deliver()
    summary = env.run()
    warns = {r[0] for r in env.q(f"SELECT check_name FROM {CONTROL}.data_quality_results "
                                 f"WHERE run_id = '{summary.run_id}' AND status = 'WARN'")}
    assert {"known_issue_psgc_id_leading_zero_lost", "known_issue_unit_rows_without_estimates"} <= warns
    assert summary.status == "succeeded"


# --- Shared control tables ----------------------------------------------------------------

def test_existing_control_tables_gain_the_new_columns_and_keep_their_rows(env, tmp_path):
    """Control tables created before this change (as on Databricks since 2026-10-06) are migrated in place."""
    deped = empty_zip_config()
    approve_zip(deped, make_delivery(env.landing / "deped" / "original", "2023-24"), "2023-24")
    write_config(env.repo, deped)
    assert IngestionRun(env.store, env.repo, "deped_enrollment", env.landing, "local", REVISION).execute().status == "succeeded"
    for table, columns in control.ADDED_COLUMNS.items():   # roll the tables back to the old shape
        for name, _ in columns:
            env.store.sql(f'ALTER TABLE {CONTROL}.{table} DROP COLUMN "{name}"')

    env.deliver()
    assert env.run().status == "succeeded"
    assert env.q(f"SELECT source_id, school_year, estimate_years_covered FROM {CONTROL}.ingestion_batches ORDER BY 1") == [
        ("deped_enrollment", "2023-24", None), (SOURCE, None, V1)]
    assert env.q(f"SELECT source_id, COALESCE(school_year, logical_dataset) FROM {CONTROL}.current_batches ORDER BY 1") == [
        ("deped_enrollment", "2023-24"), (SOURCE, "sae_city_municipal_2018_2021_2023")]


# --- Command line -------------------------------------------------------------------------

def test_cli_loads_skips_and_reports(env, tmp_path, capsys, monkeypatch):
    env.deliver()
    monkeypatch.setattr(cli, "REPO_ROOT", env.repo)
    db = ["--db", str(tmp_path / "t.duckdb")]
    args = ["ingest", "--source", SOURCE, "--landing", str(env.landing), "--code-revision", REVISION, *db]
    assert cli.main(args) == 0
    assert cli.main(args) == 0
    out = capsys.readouterr().out
    assert "load   initial" in out and "skip" in out
    assert cli.main(["status", "--source", SOURCE, *db]) == 0
    assert "2018,2021,2023" in capsys.readouterr().out


def test_cli_exit_codes(env, tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "REPO_ROOT", env.repo)
    db = ["--db", str(tmp_path / "t.duckdb")]
    assert cli.main(["ingest", "--source", SOURCE, "--landing", str(tmp_path / "nowhere"), *db]) == 3
    write_workbook(env.inbox / WORKBOOK)  # not approved
    assert cli.main(["ingest", "--source", SOURCE, "--landing", str(env.landing), *db]) == 1
    def profiled(*args, **kwargs):
        config, entry = load_source_config(*args, **kwargs)
        return config, {**entry, "status": "profiled"}
    monkeypatch.setattr(pipeline, "load_source_config", profiled)
    assert cli.main(["ingest", "--source", SOURCE, "--landing", str(env.landing), "--environment", "prod",
                     "--code-revision", REVISION, *db]) == 2  # not an accepted source
