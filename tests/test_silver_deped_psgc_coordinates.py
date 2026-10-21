"""Public-school locations in Silver (deped_psgc_coordinates, #217): scope, codes, coordinates, reconciliation.

Each test builds a made-up public-only workbook (tests/factories/report_workbooks.py), loads it through the
real Bronze pipeline, and runs the generated Silver SQL on DuckDB. No row of the real workbook is used.
The build and gate are the crosswalk generator's (D-049) with a scope; the scope, the columns Silver keeps,
and the reconciliation are tested here.
"""

import uuid

import pytest

from factories.deped_deliveries import fake_repo, write_config
from factories.report_workbooks import (
    NA, PUBLIC_ONLY, PUBLIC_ONLY_TITLE, approve, coordinates_config, make_workbook, school,
)
from src.ingestion.pipeline import IngestionRun
from src.ingestion.store import DuckDBStore
from src.silver import deped_psgc_coordinates
from src.silver.generators import REPO_ROOT, generator

REVISION = "f" * 40
SOURCE = "deped_psgc_coordinates"
CONTROL = "edu_access.`01-control`"
BRONZE = "edu_access.`02-bronze`.deped_psgc_coordinates_raw"
CLEAN = "edu_access.`03-silver`.deped_psgc_coordinates_clean"
QUARANTINE = "edu_access.`03-silver`.deped_psgc_coordinates_quarantine"
CANDIDATE = "edu_access.`03-silver`.deped_psgc_coordinates_clean_candidate"
ORDINARY = 700   # enough ordinary schools that the 5 quarantined rows stay under the 1% FAIL line

SULU = (1900000000, 1906600000, 1906601000, 1906601018)
CODED = (100000000, 102800000, 102802000, 102802013)
KEPT = ["school_year", "school_id", "psgc_region", "psgc_province", "psgc_city_municipality", "psgc_barangay",
        "psgc_recoded", "psgc_null_reason", "barangay_outside_city", "longitude", "latitude", "coordinate_flag",
        "batch_id", "delivery_version", "schema_version", "source_sha256", "source_row_number",
        "run_id", "cleaned_at_utc", "code_revision"]


def in_sector(sector, school_id, **kwargs):
    cells = school(school_id, **kwargs)
    cells[10] = sector
    return cells


def rows():
    """{Excel row: cells}: ordinary public schools, then one row for each rule."""
    out = {9 + i: school(200000 + i) for i in range(ORDINARY)}
    r = 9 + ORDINARY
    blank_count = school(300109)
    blank_count[31] = ""                                              # a blank enrollment count in Bronze
    special = [
        school("012345"),                                                 # a school ID with a leading zero
        school(300101, codes=SULU),                                       # Sulu, recoded
        school(300102, codes=(NA, NA, NA, NA), lon=NA, lat=NA),          # #N/A codes and coordinates
        school(300104, lon=0, lat=0),                                    # (0, 0)
        school(300105, lon=112.1, lat=12.7),                             # outside the Philippines
        school(300106, codes=(CODED[0], CODED[1], CODED[2], 102803001)),  # barangay outside its city
        school(300107, lon=120.5, lat=16.25),                            # the same point as the ordinary schools
        blank_count,
        in_sector("Private", 400001),                                    # not public: quarantined, not dropped
        school(300201), school(300201),                                  # identical repeat: one is kept
        school(300202, name="Paaralang Una"), school(300202, name="Paaralang Ikalawa"),  # differing repeat
        school(1000004),                                                  # malformed ID
    ]
    for cells in special:
        out[r] = cells
        r += 1
    return out, r - 1


class Lane:
    def __init__(self, tmp_path):
        self.config = coordinates_config()
        self.landing = tmp_path / "landing"
        self.repo = fake_repo(tmp_path / "repo", self.config)
        self.store = DuckDBStore()

    def deliver(self, cells, last, school_year="2023-24", folder="original"):
        start = int(school_year[:4])
        name = PUBLIC_ONLY.replace("2023-2024", f"{start}-{start + 1}")
        path = make_workbook(self.landing / "deped" / folder, school_year=school_year, rows=cells, name=name,
                             title=PUBLIC_ONLY_TITLE)
        approve(self.config, path, school_year=school_year, title=PUBLIC_ONLY_TITLE, row_count=last - 8,
                unit_rows=len(cells), blank_rows=last - 8 - len(cells), no_identifier_rows=0, last_row=last)
        write_config(self.repo, self.config)
        summary = IngestionRun(self.store, self.repo, SOURCE, self.landing, "local", REVISION).execute()
        assert summary.status == "succeeded", summary
        return len(cells)

    def build(self, run_id=None):
        params = {"run_id": run_id or str(uuid.uuid4()), "code_revision": REVISION, "environment": "local"}
        self.store.run_file(self.repo / "etl" / "03_silver" / "09_clean_deped_psgc_coordinates.sql", params)
        return params

    def gate(self, params):
        self.store.run_file(self.repo / "etl" / "03_silver" / "90_validate_deped_psgc_coordinates_clean.sql", params)

    def q(self, sql):
        return self.store.query(sql)

    def row(self, school_id, columns):
        return self.q(f"SELECT {columns} FROM {CLEAN} WHERE school_id = '{school_id}'")

    def checks(self, run_id):
        return {name: (status, actual) for name, status, actual in self.q(
            f"SELECT check_name, status, actual FROM {CONTROL}.data_quality_results WHERE run_id = '{run_id}' AND layer = 'silver'")}


@pytest.fixture
def lane(tmp_path):
    lane = Lane(tmp_path)
    cells, last = rows()
    lane.units = lane.deliver(cells, last)
    return lane


def built(lane):
    params = lane.build()
    lane.gate(params)
    return params


def test_silver_keeps_only_location_columns(lane):
    built(lane)
    assert [name for (name, *_) in lane.q(f"DESCRIBE {CLEAN}")] == KEPT
    assert lane.q(f"SELECT COUNT(*) FROM {BRONZE} WHERE k_male IS NOT NULL") == [(lane.units,)]  # counts stay in Bronze


def test_rows_reconcile_to_bronze_and_every_quarantined_row_has_its_reason(lane):
    params = built(lane)
    assert lane.q(f"SELECT COUNT(*) FROM {CLEAN}") == [(lane.units - 5,)]
    assert lane.q(f"SELECT school_id, quarantine_reasons FROM {QUARANTINE} ORDER BY school_id, source_row_number") == [
        ("1000004", ["school_id_malformed"]), ("300201", ["school_id_identical_copy"]),
        ("300202", ["school_id_duplicated"]), ("300202", ["school_id_duplicated"]), ("400001", ["sector_not_public"])]
    found = lane.checks(params["run_id"])
    assert found["rows_reconcile"] == ("PASS", str(lane.units))
    assert found["rows_in_scope"] == ("PASS", "0")
    assert found["profiled_quarantine_sector_not_public"] == ("WARN", "1")   # profiled at 0 for the real file
    assert not [name for name, (status, _) in found.items() if status == "FAIL"]
    spec = deped_psgc_coordinates.load_spec(REPO_ROOT, SOURCE)
    assert set(found) == set(deped_psgc_coordinates.gate_checks(spec))


def test_identifiers_and_codes_keep_their_leading_zeros(lane):
    built(lane)
    assert lane.row("012345", "school_id, psgc_region") == [("012345", "0100000000")]
    assert lane.row("200000", "psgc_region, psgc_province, psgc_city_municipality, psgc_barangay") == [
        ("0100000000", "0102800000", "0102802000", "0102802013")]


def test_sulu_is_recoded_and_missing_codes_keep_their_reason(lane):
    built(lane)
    assert lane.row("300101", "psgc_region, psgc_province, psgc_city_municipality, psgc_barangay, psgc_recoded") == [
        ("0900000000", "0906600000", "0906601000", "0906601018", True)]
    assert lane.row("300102", "psgc_city_municipality, psgc_barangay, psgc_null_reason") == [(None, None, "source_na")]
    assert lane.row("200000", "psgc_null_reason") == [(None,)]
    assert lane.row("300106", "barangay_outside_city") == [(True,)]


def test_coordinates_are_typed_and_flagged(lane):
    built(lane)
    assert lane.row("200000", "longitude, latitude, coordinate_flag") == [(120.5, 16.25, None)]
    assert lane.row("300102", "longitude, latitude, coordinate_flag") == [(None, None, "missing")]   # #N/A is NULL in Silver
    assert lane.q(f"SELECT longitude FROM {BRONZE} WHERE school_id = '300102'") == [("#N/A",)]     # and stays as text in Bronze
    assert lane.row("300104", "coordinate_flag") == [("zero",)]
    assert lane.row("300105", "longitude, coordinate_flag") == [(112.1, "outside_philippines")]
    # A point shared with other schools is kept for each of them, unchanged and unflagged.
    assert lane.row("300107", "longitude, latitude, coordinate_flag") == [(120.5, 16.25, None)]


def test_a_blank_enrollment_count_in_bronze_does_not_touch_the_location_row(lane):
    built(lane)
    assert lane.q(f"SELECT k_female FROM {BRONZE} WHERE school_id = '300109'") == [("",)]
    assert lane.row("300109", "psgc_barangay, coordinate_flag") == [("0102802013", None)]


def test_one_clean_row_per_bronze_row_and_per_school(lane):
    built(lane)
    assert lane.q(f"""SELECT COUNT(*), COUNT(DISTINCT (c.school_year, c.school_id)) FROM {CLEAN} AS c
                      JOIN {BRONZE} AS b ON b.source_sha256 = c.source_sha256 AND b.source_row_number = c.source_row_number""") == [
        (lane.units - 5, lane.units - 5)]


def test_a_rerun_rebuilds_the_same_rows(lane):
    first = built(lane)
    content = f"SELECT * EXCLUDE (run_id, cleaned_at_utc) FROM {CLEAN} ORDER BY school_id"
    before = (lane.q(content), lane.q(f"SELECT * EXCLUDE (run_id, cleaned_at_utc) FROM {QUARANTINE} ORDER BY school_id, source_row_number"))
    second = built(lane)
    assert second["run_id"] != first["run_id"]
    assert (lane.q(content), lane.q(f"SELECT * EXCLUDE (run_id, cleaned_at_utc) FROM {QUARANTINE} ORDER BY school_id, source_row_number")) == before
    assert lane.q(f"SELECT DISTINCT run_id FROM {CLEAN}") == [(second["run_id"],)]


def test_another_school_year_is_quarantined_not_cleaned(tmp_path):
    lane = Lane(tmp_path)
    cells, last = rows()
    lane.deliver(cells, last)
    lane.deliver({9: school(500001)}, 9, school_year="2024-25", folder="later")
    params = built(lane)
    assert lane.q(f"SELECT school_year, school_id, quarantine_reasons FROM {QUARANTINE} WHERE school_year = '2024-25'") == [
        ("2024-25", "500001", ["school_year_out_of_scope"])]
    assert lane.q(f"SELECT DISTINCT school_year FROM {CLEAN}") == [("2023-24",)]
    assert lane.checks(params["run_id"])["rows_in_scope"][0] == "PASS"


def test_many_rows_outside_the_scope_fail_the_gate(lane):
    lane.store.sql(f"UPDATE {BRONZE} SET sector = 'Private' WHERE school_id LIKE '2000%'")
    params = lane.build()
    with pytest.raises(Exception, match="FAIL result"):
        lane.gate(params)
    assert lane.checks(params["run_id"])["quarantine_rate"][0] == "FAIL"
    assert lane.q("SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'deped_psgc_coordinates_clean'") == [(0,)]


@pytest.mark.parametrize("tamper, check", [
    ("psgc_barangay = '0102802099'", "values_reconcile"),
    ("longitude = longitude + 0.000001", "coordinates_reconcile"),
    ("school_id = '400001', source_row_number = (SELECT source_row_number FROM edu_access.`02-bronze`.deped_psgc_coordinates_raw "
     "WHERE school_id = '400001')", "rows_in_scope"),
])
def test_a_candidate_that_differs_from_bronze_or_leaves_the_scope_fails_the_gate(lane, tamper, check):
    params = lane.build()
    lane.store.sql(f"UPDATE {CANDIDATE} SET {tamper} WHERE school_id = '200001'")
    with pytest.raises(Exception, match="FAIL result"):
        lane.gate(params)
    assert lane.checks(params["run_id"])[check][0] == "FAIL"


def test_the_crosswalk_generator_is_shared_and_its_output_unchanged():
    """deped_psgc_coordinates reuses the D-049 build and gate; the scope adds nothing to a source without one."""
    assert generator(SOURCE, REPO_ROOT).build_sql is generator("deped_enrollment_psgc", REPO_ROOT).build_sql
    crosswalk = generator("deped_enrollment_psgc", REPO_ROOT)
    spec = crosswalk.load_spec(REPO_ROOT, "deped_enrollment_psgc")
    assert spec.scope == [] and "scope_" not in crosswalk.build_sql(spec) and "rows_in_scope" not in crosswalk.gate_sql(spec)


def test_no_code_or_number_column_holds_na_text(lane):
    built(lane)
    text = " OR ".join(f"CAST({c} AS VARCHAR) IN ('#N/A', '')" for c in
                       ("psgc_region", "psgc_province", "psgc_city_municipality", "psgc_barangay", "longitude", "latitude"))
    assert lane.q(f"SELECT COUNT(*) FROM {CLEAN} WHERE {text}") == [(0,)]


def test_city_known_and_barangay_missing_keeps_the_city_and_gives_the_barangay_reason(lane):
    lane.store.sql(f"UPDATE {BRONZE} SET psgc_barangay = '#N/A' WHERE school_id = '200001'")
    params = built(lane)
    assert lane.row("200001", "psgc_city_municipality, psgc_barangay, psgc_null_reason") == [("0102802000", None, "source_na")]
    assert lane.checks(params["run_id"])["null_reasons_agree"] == ("PASS", "0")


def test_codes_missing_for_different_reasons_fail_the_gate(lane):
    """City '#N/A' but barangay blank: one psgc_null_reason could not say both, so the gate stops."""
    lane.store.sql(f"UPDATE {BRONZE} SET psgc_region = '#N/A', psgc_province = '#N/A', psgc_city_municipality = '#N/A', "
                   f"psgc_barangay = '' WHERE school_id = '200001'")
    params = lane.build()
    with pytest.raises(Exception, match="FAIL result"):
        lane.gate(params)
    assert lane.checks(params["run_id"])["null_reasons_agree"] == ("FAIL", "1")
