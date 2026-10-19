"""Integration for psa_school_age_population: the census places → PSGC map (psa_school_age_population_psgc_map, #159).

Made-up rows go straight into the two published Silver tables it reads (psa_school_age_population_clean and
psa_psgc_clean) in an in-memory DuckDB, then through the generated build and gate SQL, run the way the job's
two SQL tasks run them. Each made-up place exercises one rule. No real census or PSGC row is used.
"""

import copy
import importlib.util
import json
import shutil
import uuid

import pytest

from factories.deped_deliveries import REPO_ROOT
from src.ingestion.errors import IngestionError
from src.ingestion.store import DuckDBStore
from src.integration import psa_school_age_population_psgc as sap

CONTROL = "edu_access.`01-control`"
SILVER = "edu_access.`03-silver`"
MAP = "edu_access.`04-integration`.psa_school_age_population_psgc_map"
CANDIDATE = "edu_access.`04-integration`.psa_school_age_population_psgc_map_candidate"

PSGC = [  # psgc_code, name, old_names, geographic_level, level_blank, province_code
    ("0100000000", "Region I (Ilocos Region)", None, "Reg", False, None),
    ("0102800000", "Ilocos Norte", None, "Prov", False, "0102800000"),
    ("0102801000", "Adams", None, "Mun", False, "0102800000"),
    ("0102803000", "City of Batac", None, "City", False, "0102800000"),
    ("0102804000", "Banna", "Espiritu", "Mun", False, "0102800000"),
    ("0102805000", "San Nicolas", None, "Mun", False, "0102800000"),
    ("0102806000", "Peñablanca", None, "Mun", False, "0102800000"),
    ("0102807000", "Burgos", None, "Mun", False, "0102800000"),
    ("0102808000", "Burgos", None, "City", False, "0102800000"),
    ("0102809000", "City of Laoag", None, "City", False, "0102800000"),
    ("0600000000", "Region VI (Western Visayas)", None, "Reg", False, None),
    ("0800000000", "Region VIII (Eastern Visayas)", None, "Reg", False, None),
    ("0806000000", "Samar", "Western Samar", "Prov", False, "0806000000"),
    ("0806001000", "Almagro", None, "Mun", False, "0806000000"),
    ("1300000000", "National Capital Region (NCR)", None, "Reg", False, None),
    ("1380600000", "City of Manila", None, "City", False, None),
    ("1381701000", "Pateros", None, "Mun", False, None),
    ("1800000000", "Negros Island Region (NIR)", None, "Reg", False, None),
    ("1830200000", "City of Bacolod", None, "City", False, None),
    ("1900000000", "Bangsamoro Autonomous Region In Muslim Mindanao (BARMM)", None, "Reg", False, None),
    ("1908700000", "Maguindanao del Norte", None, "Prov", False, "1908700000"),
    ("1908701000", "Parang", None, "Mun", False, "1908700000"),
    ("1908800000", "Maguindanao del Sur", None, "Prov", False, "1908800000"),
    ("1908801000", "Buluan", None, "Mun", False, "1908800000"),
    ("1999900000", "Special Geographic Area", None, None, True, "1999900000"),
    ("1999901000", "Kapalawan", None, "Mun", False, "1999900000"),
]
R1, NCR, R6, R8, BARMM = "REGION I", "NATIONAL CAPITAL REGION", "REGION VI", "REGION VIII", "BARMM"
# (census_year, region_name, province_name, place_name, old_name) -> (psgc_code, status, method, review, parent_match)
PLACES = {
    (2020, R1, "ILOCOS NORTE", "ADAMS", None): ("0102801000", "matched", "name_exact", "rule", "province_name"),
    (2020, R1, "ILOCOS NORTE", "CITY OF BATAC", None): ("0102803000", "matched", "name_exact", "rule", "province_name"),
    (2020, R1, "ILOCOS NORTE", "PENABLANCA", None): ("0102806000", "matched", "name_normalized", "rule", "province_name"),
    (2020, R1, "ILOCOS NORTE", "LAOAG", None): ("0102809000", "matched", "name_normalized", "rule", "province_name"),
    (2020, R1, "ILOCOS NORTE", "ESPIRITU", None): ("0102804000", "matched", "name_old", "rule", "province_name"),
    (2020, R1, "ILOCOS NORTE", "BURGOS", None): (None, "ambiguous", None, "pending", "province_name"),
    (2020, R1, "ILOCOS NORTE", "ALMAGRO", None): (None, "unmatched", None, "pending", "province_name"),
    (2020, NCR, None, "CITY OF MANILA", None): ("1380600000", "matched", "name_exact", "rule", "region"),
    (2020, NCR, None, "PATEROS", None): ("1381701000", "matched", "name_exact", "rule", "region"),
    (2020, R6, None, "CITY OF BACOLOD", None): ("1830200000", "matched", "name_exact", "rule", "region"),
    (2020, BARMM, "MAGUINDANAO", "PARANG", None): ("1908701000", "matched", "name_exact", "rule", "province_alias"),
    (2020, BARMM, "MAGUINDANAO", "BULUAN", None): ("1908801000", "matched", "name_exact", "rule", "province_alias"),
    (2020, BARMM, "INTERIM PROVINCE", "CARMEN CLUSTER", None): (None, "unmatched", None, "pending", None),
    (2024, R8, "WESTERN SAMAR", "ALMAGRO", None): ("0806001000", "matched", "name_exact", "rule", "province_old_name"),
    (2024, BARMM, "SPECIAL GEOGRAPHIC AREA", "KAPALAWAN", None): ("1999901000", "matched", "name_exact", "rule", "province_name"),
    (2024, R1, "ILOCOS NORTE", "OLD SAN NICOLAS", "SAN NICOLAS"): ("0102805000", "matched", "name_old", "rule", "province_name"),
}
REGIONS = [
    {"census_year": 2020, "region_name": R1, "psgc_region_codes": ["0100000000"], "reason": "r"},
    {"census_year": 2020, "region_name": NCR, "psgc_region_codes": ["1300000000"], "reason": "r"},
    {"census_year": 2020, "region_name": R6, "psgc_region_codes": ["0600000000", "1800000000"], "reason": "r"},
    {"census_year": 2020, "region_name": BARMM, "psgc_region_codes": ["1900000000"], "reason": "r"},
    {"census_year": 2024, "region_name": R1, "psgc_region_codes": ["0100000000"], "reason": "r"},
    {"census_year": 2024, "region_name": R8, "psgc_region_codes": ["0800000000"], "reason": "r"},
    {"census_year": 2024, "region_name": BARMM, "psgc_region_codes": ["1900000000"], "reason": "r"},
]
ALIASES = [{"census_year": 2020, "province_name": "MAGUINDANAO", "psgc_province_codes": ["1908700000", "1908800000"],
            "reason": "split in 2022", "evidence": "made up"}]
# The committed rules with made-up regions and aliases and no overrides, which name real census places.
RULES = {**json.loads((REPO_ROOT / sap.CONFIG).read_text(encoding="utf-8")),
         "regions": REGIONS, "province_aliases": ALIASES, "overrides": []}
CLUSTER = {"census_year": 2020, "parent_name": "INTERIM PROVINCE", "place_name": "CARMEN CLUSTER", "psgc_code": None,
           "match_method": None, "reason": "PSA cluster, not an LGU (D-031)", "evidence": "made up"}
CELLS = (("total", "both", 5), ("total", "both", 6), ("total", "male", 5), ("household", "both", 5))


class Env:
    def __init__(self, tmp_path, rules=None, places=None, psgc_rows=None, db=None):
        self.store = DuckDBStore(db)
        for path in sorted((REPO_ROOT / "etl" / "01_control").glob("0[1-4]_*.sql")):
            self.store.run_file(path)
        self.store.sql(f"CREATE SCHEMA IF NOT EXISTS {SILVER}")
        self.store.sql(f"CREATE TABLE {SILVER}.psa_psgc_clean (psgc_code STRING, name STRING, old_names STRING, "
                       "geographic_level STRING, level_blank BOOLEAN, province_code STRING, publication_period STRING, "
                       "is_master_reference BOOLEAN, batch_id STRING, source_row_number BIGINT)")
        for i, row in enumerate(psgc_rows or PSGC, 1):
            self.store.sql(f"INSERT INTO {SILVER}.psa_psgc_clean VALUES (?, ?, ?, ?, ?, ?, '2026-Q2', TRUE, 'P1', ?)", [*row, i])
        self.store.sql(f"CREATE TABLE {SILVER}.psa_school_age_population_clean (census_year INT, population_concept STRING, "
                       "place_label STRING, place_name STRING, old_name STRING, level STRING, place_status STRING, "
                       "region_name STRING, province_name STRING, parent_name STRING, sex STRING, age INT, population INT, "
                       "batch_id STRING, source_sha256 STRING, source_sheet STRING, place_row_number BIGINT)")
        totals = {}
        for i, (year, region, province, name, old) in enumerate(places or PLACES, 1):
            for concept, sex, age in CELLS:
                self.add(year, concept, name, old, "city_municipality", region, province, province or region, sex, age, 10 + i, i)
                totals[(year, concept, sex, age)] = totals.get((year, concept, sex, age), 0) + 10 + i
        for (year, concept, sex, age), n in totals.items():
            self.add(year, concept, "PHILIPPINES", None, "country", None, None, None, sex, age, n, 0)
        spec = sap.build_spec(rules or RULES)
        self.build, self.gate = tmp_path / "build.sql", tmp_path / "gate.sql"
        self.build.write_text(sap.build_sql(spec), encoding="utf-8")
        self.gate.write_text(sap.gate_sql(spec), encoding="utf-8")

    def add(self, year, concept, name, old, level, region, province, parent, sex, age, population, row):
        label = name + (f" ({old})" if old else "")
        self.store.sql(f"INSERT INTO {SILVER}.psa_school_age_population_clean VALUES "
                       "(?, ?, ?, ?, ?, ?, 'standard', ?, ?, ?, ?, ?, ?, 'B1', 'sha', ?, ?)",
                       [year, concept, label, name, old, level, region, province, parent, sex, age, population,
                        f"{year} {concept}", row])

    def run(self):
        run_id = str(uuid.uuid4())
        params = {"run_id": run_id, "code_revision": "c" * 40, "environment": "local"}
        try:
            self.store.run_file(self.build, params)
            self.store.run_file(self.gate, params)
        except Exception as e:
            return run_id, str(e)
        return run_id, None

    def rows(self, sql):
        return self.store.records(sql)

    def checks(self, run_id):
        return {r["check_name"]: r for r in self.rows(
            f"SELECT * FROM {CONTROL}.data_quality_results WHERE run_id = '{run_id}' AND layer = 'integration'")}

    def run_status(self, run_id):
        return self.rows(f"SELECT status FROM {CONTROL}.pipeline_runs WHERE run_id = '{run_id}' "
                         "AND pipeline_name = 'integration_build' AND source_id = 'psa_school_age_population'")[0]["status"]

    def place(self, year, name):
        return self.rows(f"SELECT * FROM {MAP} WHERE census_year = {year} AND place_name = '{name}'")[0]


def with_rules(overrides=(), **changes):
    rules = copy.deepcopy(RULES)
    rules["overrides"] = list(overrides)
    rules.update(changes)
    return rules


def published(env):
    return bool(env.rows("SELECT 1 FROM information_schema.tables WHERE table_schema = '04-integration' "
                         "AND table_name = 'psa_school_age_population_psgc_map'"))


# --- The rules ----------------------------------------------------------------------------

def test_every_place_gets_one_row_by_the_rules_in_order(tmp_path):
    env = Env(tmp_path)
    run_id, error = env.run()
    assert error is None
    got = {(r["census_year"], r["place_name"]): (r["psgc_code"], r["match_status"], r["match_method"], r["review_status"],
                                                 r["parent_match"]) for r in env.rows(f"SELECT * FROM {MAP}")}
    assert got == {(year, name): expected for (year, _, _, name, _), expected in PLACES.items()}
    assert env.run_status(run_id) == "succeeded"


def test_a_name_is_never_matched_outside_its_province(tmp_path):
    """Almagro is a PSGC municipality of Samar: the Ilocos Norte place of that name stays unmatched."""
    env = Env(tmp_path)
    env.run()
    row = env.place(2020, "ALMAGRO")
    assert (row["match_status"], row["psgc_code"], row["reason"]) == ("unmatched", None, "no name match in the parent")


def test_a_place_under_its_region_is_matched_among_the_region_units_without_a_province(tmp_path):
    """2020 Region VI still held Bacolod: the rules list NIR (18) among the PSGC regions it covers today."""
    env = Env(tmp_path)
    env.run()
    assert env.place(2020, "CITY OF BACOLOD")["psgc_name"] == "City of Bacolod"


def test_a_province_found_by_no_rule_gets_no_name_match(tmp_path):
    env = Env(tmp_path)
    run_id, _ = env.run()
    row = env.place(2020, "CARMEN CLUSTER")
    assert row["reason"] == "no PSGC province found for the province name, so no name match was tried"
    assert env.checks(run_id)["province_without_psgc_parent"]["actual"] == "1"


def test_every_row_keeps_its_source_and_psgc_side(tmp_path):
    env = Env(tmp_path)
    env.run()
    row = env.place(2020, "ADAMS")
    assert (row["source_id"], row["source_row_ref"], row["psgc_version"], row["geographic_level"]) == (
        "psa_school_age_population", "2020/ILOCOS NORTE/ADAMS", "2026-Q2", "city_mun")
    assert (row["batch_id"], row["source_sheet"], row["place_row_number"], row["psgc_batch_id"]) == (
        "B1", "2020 total", 1, "P1")


# --- The gate -----------------------------------------------------------------------------

def test_the_gate_passes_and_warns_on_what_needs_review(tmp_path):
    env = Env(tmp_path)
    run_id, _ = env.run()
    checks = env.checks(run_id)
    assert set(checks) == {n for n, _ in sap.gate_checks(sap.build_spec(RULES))}
    assert not [n for n, c in checks.items() if c["status"] == "FAIL"]
    assert {n: checks[n]["actual"] for n in ("review_pending", "unmatched", "ambiguous")} == {
        "review_pending": "3", "unmatched": "2", "ambiguous": "1"}
    assert checks["rows_reconcile"]["actual"] == str(len(PLACES))
    assert (checks["method_name_old_2020"]["actual"], checks["match_rate_percent_2024"]["actual"]) == ("1", "100.0")
    assert checks["population_reconciles"]["status"] == "PASS"


def test_overrides_are_applied_and_marked_reviewed(tmp_path):
    env = Env(tmp_path, rules=with_rules([
        CLUSTER,
        {"census_year": 2020, "parent_name": "ILOCOS NORTE", "place_name": "BURGOS", "psgc_code": "0102807000",
         "match_method": "reviewed_alias", "reason": "the municipality, not the city", "evidence": "made up"}]))
    run_id, error = env.run()
    assert error is None
    assert (env.place(2020, "CARMEN CLUSTER")["match_status"], env.place(2020, "CARMEN CLUSTER")["review_status"]) == (
        "unmatched", "reviewed")
    row = env.place(2020, "BURGOS")
    assert (row["match_status"], row["psgc_code"], row["match_method"], row["review_status"]) == (
        "matched", "0102807000", "reviewed_alias", "reviewed")
    checks = env.checks(run_id)
    assert (checks["overrides_applied"]["actual"], checks["review_pending"]["actual"]) == ("2", "1")


def test_an_override_applies_only_to_its_census_year(tmp_path):
    places = {**PLACES, (2024, BARMM, "INTERIM PROVINCE", "CARMEN CLUSTER", None): None}
    env = Env(tmp_path, places=places, rules=with_rules([CLUSTER]))
    env.run()
    assert env.place(2020, "CARMEN CLUSTER")["review_status"] == "reviewed"
    assert env.place(2024, "CARMEN CLUSTER")["review_status"] == "pending"


def test_a_bad_override_fails_the_gate_and_nothing_is_published(tmp_path):
    env = Env(tmp_path, rules=with_rules([
        {"census_year": 2020, "parent_name": "ILOCOS NORTE", "place_name": "ALMAGRO", "psgc_code": "0102801000",
         "match_method": "reviewed_alias", "reason": "takes Adams a second time", "evidence": "made up"}]))
    run_id, error = env.run()
    assert error and "Integration gate failed" in error
    assert env.checks(run_id)["psgc_code_taken_once"]["status"] == "FAIL"
    assert env.run_status(run_id) == "failed"
    assert not published(env)


def test_an_override_for_a_place_not_in_the_data_warns_and_publishes(tmp_path):
    env = Env(tmp_path, rules=with_rules([{**CLUSTER, "place_name": "NO SUCH CLUSTER"}]))
    run_id, error = env.run()
    assert error is None
    check = env.checks(run_id)["override_place_missing"]
    assert (check["status"], check["actual"]) == ("WARN", "1")
    assert published(env)


def test_a_region_the_rules_do_not_list_warns_and_its_places_stay_unmatched(tmp_path):
    env = Env(tmp_path, rules=with_rules(regions=[r for r in REGIONS if r["region_name"] != NCR]))
    run_id, error = env.run()
    assert error is None
    assert env.checks(run_id)["region_not_listed"]["actual"] == "1"
    row = env.place(2020, "PATEROS")
    assert (row["match_status"], row["reason"]) == ("unmatched", "region not listed in the rules, so no name match was tried")


@pytest.mark.parametrize("change, bad", [
    ({"regions": [*REGIONS, {"census_year": 2024, "region_name": NCR, "psgc_region_codes": ["1500000000"], "reason": "r"}]}, 1),
    ({"province_aliases": [{**ALIASES[0], "psgc_province_codes": ["1908700000", "1908900000"]}]}, 1),
    # A real code at the wrong level: a municipality named as a province alias.
    ({"province_aliases": [{**ALIASES[0], "psgc_province_codes": ["1908700000", "1908801000"]}]}, 1),
])
def test_a_rule_code_missing_from_the_master_quarter_fails_the_gate_and_the_published_map_is_kept(tmp_path, change, bad):
    """Review on #187: region and alias codes are reviewed configuration; a typo or a stale code must stop publication."""
    env = Env(tmp_path)
    assert env.run()[1] is None                      # a first map is published
    before = env.rows(f"SELECT * EXCLUDE (run_id, built_at_utc) FROM {MAP} ORDER BY source_row_ref")
    spec = sap.build_spec(with_rules(**change))
    env.build.write_text(sap.build_sql(spec), encoding="utf-8")
    env.gate.write_text(sap.gate_sql(spec), encoding="utf-8")
    run_id, error = env.run()
    assert error and "Integration gate failed" in error
    check = env.checks(run_id)["rule_codes_in_psgc"]
    assert (check["status"], check["actual"]) == ("FAIL", str(bad))
    assert env.run_status(run_id) == "failed"
    assert env.rows(f"SELECT * EXCLUDE (run_id, built_at_utc) FROM {MAP} ORDER BY source_row_ref") == before


def test_a_place_only_one_concept_lists_fails_the_gate(tmp_path):
    """Every place of either sheet needs its map row; the build reads the total sheet."""
    env = Env(tmp_path)
    env.add(2024, "household", "LONE PLACE", None, "city_municipality", R1, "ILOCOS NORTE", "ILOCOS NORTE", "both", 5, 0, 99)
    run_id, error = env.run()
    assert error and "Integration gate failed" in error
    assert env.checks(run_id)["rows_reconcile"]["status"] == "FAIL"


def test_a_dropped_place_fails_the_population_check_and_the_published_map_is_kept(tmp_path):
    env = Env(tmp_path)
    assert env.run()[1] is None
    before = env.rows(f"SELECT * EXCLUDE (run_id, built_at_utc) FROM {MAP} ORDER BY source_row_ref")
    run_id = str(uuid.uuid4())
    params = {"run_id": run_id, "code_revision": "c" * 40, "environment": "local"}
    env.store.run_file(env.build, params)
    env.store.sql(f"DELETE FROM {CANDIDATE} WHERE place_name = 'ADAMS'")
    with pytest.raises(Exception, match="Integration gate failed"):
        env.store.run_file(env.gate, params)
    checks = env.checks(run_id)
    assert {n: checks[n]["status"] for n in ("rows_reconcile", "population_reconciles")} == {
        "rows_reconcile": "FAIL", "population_reconciles": "FAIL"}
    assert checks["population_reconciles"]["actual"] == str(len(CELLS))
    assert env.rows(f"SELECT * EXCLUDE (run_id, built_at_utc) FROM {MAP} ORDER BY source_row_ref") == before


@pytest.mark.parametrize("name, change", [
    ("ADAMS", "review_status = 'pending'"),                                   # matched, but nobody reviewed it
    ("ALMAGRO", "review_status = 'rule'"),                                    # unmatched by a rule
    ("BURGOS", "match_method = 'name_exact'"),                                # ambiguous with a method
])
def test_a_status_combination_d052_forbids_fails_the_gate(tmp_path, name, change):
    env = Env(tmp_path)
    run_id = str(uuid.uuid4())
    params = {"run_id": run_id, "code_revision": "c" * 40, "environment": "local"}
    env.store.run_file(env.build, params)
    env.store.sql(f"UPDATE {CANDIDATE} SET {change} WHERE place_name = '{name}' AND census_year = 2020")
    with pytest.raises(Exception, match="Integration gate failed"):
        env.store.run_file(env.gate, params)
    assert env.checks(run_id)["status_combination_valid"]["status"] == "FAIL"
    assert env.run_status(run_id) == "failed"


@pytest.mark.parametrize("name, change, failed", [
    ("ADAMS", "psgc_name = 'Wrong name'", "psgc_name_matches_unit"),
    # Almagro is a real unit with its own name, but in Samar, not in the place's Ilocos Norte.
    ("ADAMS", "psgc_code = '0806001000', psgc_name = 'Almagro'", "name_match_inside_province"),
    # Directly under NCR: Kapalawan has no PSGC province too, but it is in BARMM, not in the place's region.
    ("CITY OF MANILA", "psgc_code = '1999901000', psgc_name = 'Kapalawan'", "name_match_inside_province"),
    # Under an aliased province: San Nicolas is outside both Maguindanao provinces the alias names.
    ("PARANG", "psgc_code = '0102805000', psgc_name = 'San Nicolas'", "name_match_inside_province"),
    # Review on #187: a matched row must name its PSGC row, not only its PSGC batch.
    ("ADAMS", "psgc_source_row_number = NULL", "lineage_complete"),
    ("ADAMS", "psgc_batch_id = NULL", "lineage_complete"),
])
def test_a_tampered_match_fails_the_gate_and_the_published_map_is_kept(tmp_path, name, change, failed):
    """Review on #187 (#181, D-052): the gate re-checks the PSGC name, recomputes the parent of every name-rule match,
    and requires both halves of the PSGC lineage. Each tampering fails only its own check."""
    env = Env(tmp_path)
    assert env.run()[1] is None                      # a first map is published
    before = env.rows(f"SELECT * EXCLUDE (run_id, built_at_utc) FROM {MAP} ORDER BY source_row_ref")
    run_id = str(uuid.uuid4())
    params = {"run_id": run_id, "code_revision": "c" * 40, "environment": "local"}
    env.store.run_file(env.build, params)
    env.store.sql(f"UPDATE {CANDIDATE} SET {change} WHERE place_name = '{name}' AND census_year = 2020")
    with pytest.raises(Exception, match="Integration gate failed"):
        env.store.run_file(env.gate, params)
    checks = env.checks(run_id)
    assert checks[failed]["status"] == "FAIL"
    assert [n for n, c in checks.items() if c["status"] == "FAIL"] == [failed]
    assert env.run_status(run_id) == "failed"
    assert env.rows(f"SELECT * EXCLUDE (run_id, built_at_utc) FROM {MAP} ORDER BY source_row_ref") == before


def test_every_rule_match_passes_the_name_and_parent_checks(tmp_path):
    """Each parent kind of the made-up places (province name, old name, alias, the SGA container, region) is accepted."""
    env = Env(tmp_path)
    run_id, error = env.run()
    assert error is None
    checks = env.checks(run_id)
    assert {n: (checks[n]["status"], checks[n]["actual"]) for n in ("psgc_name_matches_unit", "name_match_inside_province")} == {
        "psgc_name_matches_unit": ("PASS", "0"), "name_match_inside_province": ("PASS", "0")}


def test_two_master_psgc_periods_fail_the_gate(tmp_path):
    env = Env(tmp_path)
    env.store.sql(f"INSERT INTO {SILVER}.psa_psgc_clean VALUES "
                  "('0102899000', 'Pagudpud', NULL, 'Mun', FALSE, '0102800000', '2026-Q1', TRUE, 'P0', 99)")
    run_id, error = env.run()
    assert error and "Integration gate failed" in error
    assert env.checks(run_id)["one_psgc_version"]["actual"] == "2"
    assert not published(env)


# --- The rules file and the committed files ------------------------------------------------

@pytest.mark.parametrize("change, message", [
    ({"overrides": [{**CLUSTER, "census_year": "2020"}]}, "whole number"),
    ({"overrides": [{**CLUSTER, "parent_name": None}]}, "parent_name and place_name"),
    ({"overrides": [CLUSTER, CLUSTER]}, "listed twice"),
    ({"overrides": [{**CLUSTER, "psgc_code": "12", "match_method": "reviewed_alias"}]}, "ten digits"),
    ({"overrides": [{**CLUSTER, "match_method": "reviewed_alias"}]}, "no match_method"),
    ({"overrides": [{**CLUSTER, "psgc_code": "0102801000", "match_method": "guess"}]}, "is not one of"),
    ({"overrides": [{**CLUSTER, "evidence": ""}]}, "reason and evidence"),
    ({"overrides": [{**CLUSTER, "reason": "it's"}]}, "quotes"),
    ({"overrides": [{**CLUSTER, "place_name": "STO. NIÑO"}]}, "non-ASCII"),
    ({"regions": [{**REGIONS[0], "psgc_region_codes": ["0102800000"]}]}, "region codes"),
    ({"regions": [REGIONS[0], REGIONS[0]]}, "once per census year"),
    ({"province_aliases": [{**ALIASES[0], "psgc_province_codes": []}]}, "ten-digit"),
    ({"province_aliases": [{**ALIASES[0], "evidence": None}]}, "reason and evidence"),
])
def test_a_bad_rules_file_is_refused_before_any_sql(change, message):
    with pytest.raises(IngestionError, match=message):
        sap.build_spec({**copy.deepcopy(RULES), **change})


def test_the_committed_rules_are_valid():
    spec = sap.load_spec(REPO_ROOT)
    assert spec.census_years == [2020, 2024]
    assert len({(r.census_year, r.region_name) for r in spec.regions}) == 17 + 18
    keys = [(o.census_year, o.parent_name, o.place_name) for o in spec.overrides]
    assert len(keys) == len(set(keys)) > 0


@pytest.mark.parametrize("command, path, function", [
    ("sql", "etl/04_integration/05_map_psa_school_age_population_psgc.sql", sap.build_sql),
    ("gate", "etl/04_integration/90_validate_psa_school_age_population_psgc_map.sql", sap.gate_sql),
])
def test_committed_files_match_the_generator(command, path, function):
    text = (REPO_ROOT / path).read_text(encoding="utf-8")
    assert text == function(sap.load_spec(REPO_ROOT)), (
        f"Regenerate: python -m src.integration.psa_school_age_population_psgc {command} > {path}")
    assert text.isascii()


# --- The verification script --------------------------------------------------------------

def test_the_verification_script_reports_the_failed_candidate(tmp_path, monkeypatch, capsys):
    db = tmp_path / "map.duckdb"
    env = Env(tmp_path, db=db)
    env.store.sql(f"INSERT INTO {SILVER}.psa_psgc_clean VALUES "
                  "('0102899000', 'Pagudpud', NULL, 'Mun', FALSE, '0102800000', '2026-Q1', TRUE, 'P0', 99)")  # FAIL
    env.store.close()
    repo = tmp_path / "repo"
    shutil.copytree(REPO_ROOT / "etl" / "04_integration", repo / "etl" / "04_integration")
    path = REPO_ROOT / "analysis" / "verification" / "psa_school_age_population_psgc_map.py"
    module_spec = importlib.util.spec_from_file_location("psa_school_age_population_psgc_map_script", path)
    script = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(script)
    monkeypatch.setattr(script, "REPO_ROOT", repo)
    assert script.main(["--db", str(db)]) == 1
    out = capsys.readouterr().out
    assert "gate: FAILED" in out
    assert "BURGOS" in (repo / "local_state" / "psa_school_age_population_psgc_review.md").read_text(encoding="utf-8")
