"""PSA school-age population (xlsx_census): what a census workbook must pass, and how it loads.

Every workbook here is made up (tests/factories/census_workbooks.py) and approved into a copy
of the real psa_school_age_population contract. Pipeline tests run the real etl/01_control
and etl/02_bronze SQL on an in-memory DuckDB inside a throwaway repository root, with both
layouts: 2020 wide and 2024 long.
"""

import copy

import pytest

from factories.census_workbooks import (
    PLACES, SOURCE, approve, default_sheet_rows, empty_config, fake_repo, real_config, registry_entry,
    sheet_grid, write_config, write_workbook,
)
from src.ingestion.contract import load_source_config, row_key, validate_config
from src.ingestion.errors import IngestionError
from src.ingestion.pipeline import IngestionRun
from src.ingestion.store import DuckDBStore
from src.ingestion.validate import FAIL, PASS, WARN
from src.ingestion.xlsx_census import PROVENANCE_COLUMNS, prepare_delivery

REVISION = "e" * 40
BRONZE = "edu_access.`02-bronze`.psa_school_age_population_raw"
CONTROL = "edu_access.`01-control`"


def checks(prepared):
    return {c.check_name: c for c in prepared.checks}


def prepared_for(tmp_path, year, approve_kwargs=None, **workbook_kwargs):
    config = empty_config()
    path = write_workbook(tmp_path / "psa", year, **workbook_kwargs)
    approve(config, path, year, **(approve_kwargs or {}))
    return prepare_delivery(config, registry_entry(SOURCE), path)


# --- The real contract ---------------------------------------------------------

def test_real_contract_loads_and_does_not_promote_the_source(repo_root):
    config, entry = load_source_config(repo_root, SOURCE)
    assert [(d["census_year"], d["logical_dataset"], d["schema_version"]) for d in config["deliveries"]] == [
        ("2020", "school_age_population_2020", "v1"), ("2024", "school_age_population_2024", "v2")]
    assert [[(s["sheet"], s["place_rows"]) for s in d["sheets"]] for d in config["deliveries"]] == [
        [("2020 Total Pop", 1742), ("2020 Household Pop", 1742)],
        [("2024 Total Pop", 1744), ("2024 Household Pop", 1744)]]
    assert entry["status"] == "profiled", "ingestion must not promote the source; that is a team decision"


def test_layouts_have_60_and_20_count_columns():
    versions = real_config()["schema_versions"]
    assert len(versions["v1"]["columns"]) == 61 and len(versions["v2"]["columns"]) == 21
    assert versions["v1"]["columns"][1] == "both_sexes_age_5" and versions["v1"]["columns"][-1] == "female_age_24"


def test_a_row_is_identified_by_its_sheet_too():
    assert row_key(real_config()) == ("source_sha256", "source_sheet", "source_row_number")
    assert {"source_sheet", "source_row_number", "source_row_kind", "logical_dataset", "census_year",
            "delivery_version"} <= set(PROVENANCE_COLUMNS)


@pytest.mark.parametrize("break_it, message", [
    (lambda c: c["deliveries"].append(copy.deepcopy(c["deliveries"][0])), "approved twice"),
    (lambda c: c["deliveries"][0].update(census_year="2021"), "file name says 2020"),
    (lambda c: c["deliveries"][0].update(delivery_version=2), "1, 2, 3"),
    (lambda c: c["deliveries"][0].update(workbook="population.xlsx"), "would not be discovered"),
    (lambda c: c["deliveries"][0]["sheets"].reverse(), "sheets must be exactly"),
    (lambda c: c["deliveries"][0]["sheets"][0].update(place_rows=0), "place_rows"),
    (lambda c: c["deliveries"][0]["sheets"][0].update(sheet_rows="many"), "sheet_rows"),
    (lambda c: c["deliveries"][0].update(schema_version="v9"), "not defined"),
    (lambda c: c["schema_versions"]["v1"]["columns"].append("batch_id"), "provenance"),
    (lambda c: c["schema_versions"]["v1"]["bands"].update(BJ="Total"), "band(s)"),
    (lambda c: c["schema_versions"]["v2"].pop("sex_labels"), "sex_labels"),
    (lambda c: c["known_issues"].append({"name": "x", "check": "guess", "finding": "-", "profiled": {}}), "is not one of"),
    (lambda c: c["known_issues"][1].pop("value"), "needs a non-empty text 'value'"),
    (lambda c: c["known_issues"][2].update(value=""), "needs a non-empty text 'value'"),
    (lambda c: c["known_issues"][0]["profiled"].update({"2024 Total Pops": 1}), "profiled names sheet(s)"),
    (lambda c: c["known_issues"][1]["profiled"].update({"Total Pop": 1}), "profiled names sheet(s)"),
])
def test_contract_refuses_ambiguous_config(break_it, message):
    config = real_config()
    break_it(config)
    with pytest.raises(IngestionError) as e:
        validate_config(config, registry_entry(SOURCE))
    assert e.value.code == "invalid_config" and message in e.value.message, e.value.message


def test_two_datasets_may_not_cover_the_same_census():
    config = real_config()
    other = copy.deepcopy(config["deliveries"][0])
    other.update(logical_dataset="school_age_population_2020_again", workbook_sha256="1" * 64)
    config["deliveries"].append(other)
    with pytest.raises(IngestionError) as e:
        validate_config(config, registry_entry(SOURCE))
    assert "both cover 2020" in e.value.message
    other.update(logical_dataset="school_age_population_2020", delivery_version=2,
                 supersedes=config["deliveries"][0]["workbook_sha256"])
    validate_config(config, registry_entry(SOURCE))   # a revision of the same dataset is fine


# --- One workbook: rows and checks ------------------------------------------------

EXPECTED_WARNINGS = {
    "2020": ["2020 Household Pop: known_issue_source_line_misspelled",
             "2020 Total Pop: known_issue_source_line_misspelled"],
    "2024": ["2024 Household Pop: known_issue_place_label_footnote_marker",
             "2024 Household Pop: known_issue_title_names_only_city_municipality",
             "2024 Total Pop: known_issue_place_label_footnote_marker"],
}


@pytest.mark.parametrize("year", ["2020", "2024"])
def test_a_valid_workbook_passes_every_layout_check(tmp_path, year):
    prepared = prepared_for(tmp_path, year)
    failed = [c for c in prepared.checks if c.status == FAIL]
    assert failed == []
    warned = sorted(c.check_name for c in prepared.checks if c.status == WARN)
    assert warned == EXPECTED_WARNINGS[year]   # only the publisher quirks the fixture carries, as the real files do
    assert len(prepared.rows) == sum(default_sheet_rows(year, c) for c in ("Total Pop", "Household Pop"))


def test_2020_rows_are_kinded_from_the_wide_layout(tmp_path):
    prepared = prepared_for(tmp_path, "2020")
    kinds = {key: kind for key, kind in prepared.row_kinds.items() if key[0] == "2020 Total Pop"}
    assert [kinds[("2020 Total Pop", r)] for r in range(1, 11)] == [
        "title", "header", "header", "blank", "place", "place", "place", "place", "blank", "source"]
    values = dict(prepared.rows)[("2020 Total Pop", 7)]
    assert values[0] == "CITY OF TESTVILLE (Capital)" and len(values) == 61   # kept exactly, brackets and all


def test_2024_rows_are_kinded_from_the_long_layout(tmp_path):
    prepared = prepared_for(tmp_path, "2024")
    sheet = "2024 Household Pop"   # starts one row higher than the total sheet (profile O-1)
    kinds = [kind for (s, _), kind in sorted(prepared.row_kinds.items()) if s == sheet]
    assert kinds[:8] == ["title", "header", "header", "place", "sex_total", "sex_male", "sex_female", "place"]
    assert kinds[-4:] == ["blank", "note", "note", "source"]
    assert dict(prepared.rows)[(sheet, 12)][0] == "CITY OF TESTVILLE 1/"   # footnote marker kept


def test_known_issues_warn_with_the_profiled_count_beside_the_actual(tmp_path):
    config = empty_config()
    config["known_issues"][0]["profiled"] = {"2024 Total Pop": 11, "2024 Household Pop": 10}
    path = write_workbook(tmp_path / "psa", "2024")
    approve(config, path, "2024")
    found = checks(prepare_delivery(config, registry_entry(SOURCE), path))
    check = found["2024 Total Pop: known_issue_place_label_footnote_marker"]
    assert (check.status, check.expected, check.actual) == (WARN, "0 (profiled: 11, O-6)", "2")
    title = found["2024 Household Pop: known_issue_title_names_only_city_municipality"]
    assert (title.status, title.actual) == (WARN, "1")
    # A sheet without the quirk passes.
    assert found["2024 Total Pop: known_issue_title_names_only_city_municipality"].status == PASS


@pytest.mark.parametrize("year, break_it, failing", [
    ("2020", {(3, 2): "6"}, "age_row_matches_layout"),                         # a shifted age row
    ("2024", {(3, 21): None, (3, 22): "24"}, "age_row_matches_layout"),
    ("2020", {(2, 22): "Males"}, "band_row_matches_layout"),
    ("2024", {(2, 2): "Age"}, "band_row_matches_layout"),
    ("2020", {(6, 30): "12.5"}, "counts_are_whole_numbers"),
    ("2024", {(6, 3): "1,234"}, "counts_are_whole_numbers"),
    ("2020", {(6, 30): None}, "unclassified_rows"),                            # a place with a blank count
    ("2020", {(6, 70): "x"}, "no_cells_outside_layout"),
    ("2024", {(7, 1): "Males"}, "unclassified_rows"),
])
def test_a_layout_change_fails_the_sheet(tmp_path, year, break_it, failing):
    sheet = f"{year} Total Pop"
    grid = sheet_grid(year, "Total Pop", extra=break_it)
    prepared = prepared_for(tmp_path, year, grids={sheet: grid},
                            approve_kwargs={"sheet_rows": {"Total Pop": max(grid),
                                                           "Household Pop": default_sheet_rows(year, "Household Pop")}})
    assert checks(prepared)[f"{sheet}: {failing}"].status == FAIL


@pytest.mark.parametrize("year", ["2020", "2024"])
def test_an_extra_place_row_fails(tmp_path, year):
    sheet = f"{year} Total Pop"
    grid = sheet_grid(year, "Total Pop", places=PLACES[year] + ["EXTRA TOWN"])
    prepared = prepared_for(tmp_path, year, grids={sheet: grid},
                            approve_kwargs={"sheet_rows": {"Total Pop": max(grid),
                                                           "Household Pop": default_sheet_rows(year, "Household Pop")}})
    check = checks(prepared)[f"{sheet}: place_rows_match_approved"]
    assert (check.status, check.expected, check.actual) == (FAIL, str(len(PLACES[year])), str(len(PLACES[year]) + 1))


def test_a_2024_place_without_its_sex_block_fails(tmp_path):
    grid = sheet_grid("2024", "Total Pop")
    del grid[7]   # the first place's Male row: Total, then Female
    prepared = prepared_for(tmp_path, "2024", grids={"2024 Total Pop": grid},
                            approve_kwargs={"sheet_rows": {"Total Pop": max(grid),
                                                           "Household Pop": default_sheet_rows("2024", "Household Pop")}})
    found = checks(prepared)
    assert found["2024 Total Pop: place_rows_have_one_sex_block"].status == FAIL
    assert found["2024 Total Pop: sex_male_rows_match_place_rows"].status == FAIL


def test_an_unpinned_sheet_row_count_fails_and_reports_the_count(tmp_path):
    prepared = prepared_for(tmp_path, "2024", approve_kwargs={"sheet_rows": {"Total Pop": None, "Household Pop": None}})
    check = checks(prepared)["2024 Total Pop: sheet_rows_match_approved"]
    assert check.status == FAIL and check.actual == str(default_sheet_rows("2024", "Total Pop"))
    assert "not pinned yet" in check.expected


def test_a_renamed_sheet_is_refused(tmp_path):
    with pytest.raises(IngestionError) as e:
        prepared_for(tmp_path, "2020", sheets=["2020 Total Population", "2020 Household Pop"])
    assert e.value.code == "missing_sheet"


def test_an_extra_sheet_is_refused(tmp_path):
    with pytest.raises(IngestionError) as e:
        prepared_for(tmp_path, "2020", sheets=["2020 Total Pop", "2020 Household Pop", "2020 Barangay"])
    assert e.value.code == "unexpected_sheet"


# --- The pipeline ------------------------------------------------------------------------

class Env:
    def __init__(self, tmp_path):
        self.config = empty_config()
        self.landing = tmp_path / "landing"
        self.inbox = self.landing / "psa" / "original"
        self.repo = fake_repo(tmp_path / "repo", self.config)
        self.store = DuckDBStore()

    def deliver(self, year, approve_it=True, **kwargs):
        path = write_workbook(self.inbox, year, **kwargs)
        if approve_it:
            approve(self.config, path, year)
            write_config(self.repo, self.config)
        return path

    def run(self, rerun=()):
        return IngestionRun(self.store, self.repo, SOURCE, self.landing, "local", REVISION,
                            rerun_batch_ids=rerun).execute()

    def q(self, sql):
        return self.store.query(sql)


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def rows_of(year):
    return sum(default_sheet_rows(year, c) for c in ("Total Pop", "Household Pop"))


def test_both_layouts_load_skip_and_rerun_without_new_rows(env):
    env.deliver("2020")
    env.deliver("2024")
    first = env.run()
    assert first.status == "succeeded", first
    assert [(o.school_year, o.action, o.load_type, o.outcome, o.rows_inserted) for o in first.outcomes] == [
        ("2020", "load", "initial", "succeeded", rows_of("2020")),
        ("2024", "load", "incremental", "succeeded", rows_of("2024"))]
    # Every row of every sheet, with provenance, and the two sheets' shared row numbers both kept.
    assert env.q(f"SELECT census_year, source_sheet, COUNT(*), COUNT(DISTINCT source_row_number) FROM {BRONZE} "
                 "GROUP BY 1, 2 ORDER BY 1, 2") == [
        ("2020", "2020 Household Pop", default_sheet_rows("2020", "Household Pop"), default_sheet_rows("2020", "Household Pop")),
        ("2020", "2020 Total Pop", default_sheet_rows("2020", "Total Pop"), default_sheet_rows("2020", "Total Pop")),
        ("2024", "2024 Household Pop", default_sheet_rows("2024", "Household Pop"), default_sheet_rows("2024", "Household Pop")),
        ("2024", "2024 Total Pop", default_sheet_rows("2024", "Total Pop"), default_sheet_rows("2024", "Total Pop"))]
    assert env.q(f"SELECT source_row_kind, COUNT(*) FROM {BRONZE} WHERE source_sheet = '2024 Total Pop' "
                 "GROUP BY 1 ORDER BY 1") == [("blank", 2), ("header", 2), ("note", 3), ("place", 4), ("sex_female", 4),
                                              ("sex_male", 4), ("sex_total", 4), ("source", 1), ("title", 1)]
    assert env.q(f"SELECT label, age_5, both_sexes_age_5 FROM {BRONZE} WHERE source_sheet = '2024 Total Pop' "
                 "AND source_row_number = 6") == [("Total", "100", None)]   # a column not in that layout is NULL
    assert env.q(f"SELECT label FROM {BRONZE} WHERE source_row_kind = 'place' AND census_year = '2024' "
                 "AND label LIKE '%1/'") == [("CITY OF TESTVILLE 1/",), ("CITY OF TESTVILLE 1/",)]
    assert env.q(f"SELECT logical_dataset, estimate_years_covered, source_sheet, expected_rows, source_rows, bronze_rows "
                 f"FROM {CONTROL}.ingestion_batches ORDER BY 1") == [
        ("school_age_population_2020", "2020", "2020 Total Pop,2020 Household Pop", rows_of("2020"), rows_of("2020"), rows_of("2020")),
        ("school_age_population_2024", "2024", "2024 Total Pop,2024 Household Pop", rows_of("2024"), rows_of("2024"), rows_of("2024"))]
    assert env.q(f"SELECT check_name, status FROM {CONTROL}.data_quality_results WHERE batch_id IS NULL "
                 "AND check_name IN ('no_pipeline_duplicates', 'succeeded_batches_reconcile') ORDER BY 1") == [
        ("no_pipeline_duplicates", PASS), ("succeeded_batches_reconcile", PASS)]
    assert env.q(f"SELECT COUNT(*) FROM {CONTROL}.data_quality_results WHERE status = 'FAIL'") == [(0,)]
    assert env.q(f"SELECT logical_dataset FROM {CONTROL}.current_batches ORDER BY 1") == [
        ("school_age_population_2020",), ("school_age_population_2024",)]

    # A second run skips both workbooks; a forced rerun validates and merges again, inserting nothing.
    second = env.run()
    assert [(o.action, o.outcome, o.rows_inserted) for o in second.outcomes] == [("skip", "skipped", 0)] * 2
    batch = env.q(f"SELECT batch_id FROM {CONTROL}.ingestion_batches WHERE estimate_years_covered = '2024'")[0][0]
    third = env.run(rerun=[batch])
    assert third.status == "succeeded"
    assert sorted((o.action, o.outcome, o.rows_inserted) for o in third.outcomes) == [
        ("rerun", "succeeded", 0), ("skip", "skipped", 0)]
    assert env.q(f"SELECT COUNT(*) FROM {BRONZE}") == [(rows_of("2020") + rows_of("2024"),)]


def test_a_changed_workbook_is_blocked_and_nothing_loads(env):
    env.deliver("2020")
    assert env.run().status == "succeeded"
    # Same name, different bytes: a changed count in the total sheet.
    write_workbook(env.inbox, "2020", grids={"2020 Total Pop": sheet_grid("2020", "Total Pop", extra={(5, 2): "999"})})
    run = env.run()
    assert run.status == "failed"
    (o,) = run.outcomes
    assert (o.action, o.outcome, o.load_type) == ("block", "blocked", "revision")
    assert "checksum_mismatch" in env.q(f"SELECT error_code FROM {CONTROL}.ingestion_batches WHERE status = 'blocked'")[0]
    assert env.q(f"SELECT COUNT(*) FROM {BRONZE}") == [(rows_of("2020"),)]


def test_a_failing_layout_loads_nothing(env):
    path = env.deliver("2020", approve_it=False,
                       grids={"2020 Total Pop": sheet_grid("2020", "Total Pop", extra={(3, 2): "6"})})
    approve(env.config, path, "2020")
    write_config(env.repo, env.config)
    run = env.run()
    assert run.status == "failed"
    assert env.q(f"SELECT status, error_code FROM {CONTROL}.ingestion_batches") == [("failed", "failed_checks")]
    assert env.q(f"SELECT COUNT(*) FROM {BRONZE}") == [(0,)]
    assert ("2020 Total Pop: age_row_matches_layout", FAIL) in env.q(
        f"SELECT check_name, status FROM {CONTROL}.data_quality_results")
