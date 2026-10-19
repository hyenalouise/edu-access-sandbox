"""DepEd enrollment school/year geography → PSGC Integration map (#91, D-049).

Only made-up Silver rows are used.  They run through the same generated build and gate SQL as the
Databricks job.  Each school is one branch of the reviewed rule (PR #153,
tests/test_deped_school_psgc_rule.py), so the production SQL is held to the same cases as the
analysis functions; the gate tests change one candidate row and check that nothing is published.
"""

import ast
import copy
import json
import sys
import uuid

import pytest

from factories.deped_deliveries import REPO_ROOT
from src.ingestion.errors import IngestionError
from src.ingestion.store import DuckDBStore
from src.integration import deped_school_psgc as deped

CONTROL = "edu_access.`01-control`"
MAP = "edu_access.`04-integration`.deped_school_psgc_map"
CANDIDATE = "edu_access.`04-integration`.deped_school_psgc_map_candidate"
RULES = json.loads((REPO_ROOT / "config" / "mappings" / "integration" / "deped_school_psgc.json").read_text(encoding="utf-8"))
# The made-up schools are a handful of edge cases, so their match rate and counts are not the real ones.
MADE_UP_RULES = copy.deepcopy(RULES)
MADE_UP_RULES["gate"] |= {"min_match_rate_pct": 0, "profiled_counts": {}}

LONG_NAME = "Barangay With A Very Long Name That Keeps Going"  # DepEd cuts barangay names at 40 characters (O-18)

# code, name, old_names, level, region, province, city parent
PSGC = [
    ("0100000000", "Region I", None, "Reg", "0100000000", None, None),
    ("0102800000", "Ilocos Norte", None, "Prov", "0100000000", "0102800000", None),
    ("0102801000", "Adams", None, "Mun", "0100000000", "0102800000", None),
    ("0102802000", "Bacarra", None, "Mun", "0100000000", "0102800000", None),
    ("0102803000", "City of Batac", None, "City", "0100000000", "0102800000", None),
    ("0102804000", "City of Isabela", None, "City", "0100000000", "0102800000", None),  # made-up namesake: only the province scope tells them apart
    ("0102801001", "Poblacion", None, "Bgy", "0100000000", "0102800000", "0102801000"),
    ("0102802001", "Poblacion", None, "Bgy", "0100000000", "0102800000", "0102802000"),
    ("0102802002", "San Roque", None, "Bgy", "0100000000", "0102800000", "0102802000"),
    ("0102802003", "San Roque", None, "Bgy", "0100000000", "0102800000", "0102802000"),
    ("0102802004", "Nueva Era", "Old Town", "Bgy", "0100000000", "0102800000", "0102802000"),
    ("0102802005", LONG_NAME, None, "Bgy", "0100000000", "0102800000", "0102802000"),
    ("0102803001", "Barangay One", None, "Bgy", "0100000000", "0102800000", "0102803000"),
    ("0102803002", "Calayab", None, "Bgy", "0100000000", "0102800000", "0102803000"),
    ("0900000000", "Region IX", None, "Reg", "0900000000", None, None),
    ("0990100000", "City of Isabela (Not a Province)", None, None, "0900000000", "0990100000", None),  # level blank
    ("0990101000", "City of Isabela", None, "City", "0900000000", "0990100000", None),
    ("0990101002", "Aguada", None, "Bgy", "0900000000", "0990100000", "0990101000"),
    ("0906600000", "Sulu", None, "Prov", "0900000000", "0906600000", None),
    ("0906601000", "Jolo", None, "Mun", "0900000000", "0906600000", None),
    ("0906601001", "Asturias", None, "Bgy", "0900000000", "0906600000", "0906601000"),
    ("0907300000", "Zamboanga del Sur", None, "Prov", "0900000000", "0907300000", None),
    ("0907301000", "Dimataling", None, "Mun", "0900000000", "0907300000", None),
    ("0907301001", "Saloagan", None, "Bgy", "0900000000", "0907300000", "0907301000"),
    ("1200000000", "Region XII", None, "Reg", "1200000000", None, None),
    ("1204700000", "Cotabato", "North Cotabato", "Prov", "1200000000", "1204700000", None),
    ("1204714000", "Pikit", None, "Mun", "1200000000", "1204700000", None),
    ("1204714001", "Ginatilan", None, "Bgy", "1200000000", "1204700000", "1204714000"),
    ("1300000000", "National Capital Region", None, "Reg", "1300000000", None, None),
    ("1380100000", "City of Caloocan", None, "City", "1300000000", None, None),
    ("1380100001", "Barangay 1", None, "Bgy", "1300000000", None, "1380100000"),
    ("1380600000", "City of Manila", None, "City", "1300000000", None, None),
    ("1380608000", "Sampaloc", None, "SubMun", "1300000000", None, None),
    ("1380608001", "Barangay 395", None, "Bgy", "1300000000", None, "1380608000"),
    ("1381500000", "City of Taguig", None, "City", "1300000000", None, None),
    ("1381500001", "Central Signal Village", "Signal Village", "Bgy", "1300000000", None, "1381500000"),
    ("1381500002", "South Signal Village", None, "Bgy", "1300000000", None, "1381500000"),
    ("1500000000", "BARMM", None, "Reg", "1500000000", None, None),
    ("1538700000", "Maguindanao del Norte", None, "Prov", "1500000000", "1538700000", None),
    ("1538800000", "Maguindanao del Sur", None, "Prov", "1500000000", "1538800000", None),
    ("1538701000", "Datu Odin Sinsuat", None, "Mun", "1500000000", "1538700000", None),
    ("1538701001", "Awang", None, "Bgy", "1500000000", "1538700000", "1538701000"),
    ("1999901000", "Pahamuddin", None, "Mun", "1900000000", None, None),
    ("1999904000", "Nabalawag", None, "Mun", "1900000000", None, None),
    ("1999901001", "Buliok", None, "Bgy", "1900000000", None, "1999901000"),
    ("1999904001", "Damatulan", None, "Bgy", "1900000000", None, "1999904000"),
]

BARMM, XII, NCR = "BARMM", "Region XII", "NCR"
MANILA_PROVINCE = "NCR, CITY OF MANILA, FIRST DISTRICT"


def school(school_id, province, municipality, barangay, region="REGION I", year="2023-24", overseas=False):
    return (year, school_id, f"School {school_id}", "PSO" if overseas else region,
            province, municipality, barangay, len(barangay or "") == 40, overseas, "E1", "esha", int(school_id))


# One school per branch; the comment names the branch.
ENROLLMENT = [
    school("100001", "ILOCOS NORTE", "ADAMS", "POBLACION"),                    # code and name agree
    school("100002", "ILOCOS NORTE", "CITY OF BATAC", "BARANGAY ONE"),       # name only
    school("100003", "ILOCOS NORTE", "BACARRA", "BARANGAY ONE"),             # code and name differ, unsupported
    school("100004", "NCR FOURTH DISTRICT", "TAGUIG CITY", "SIGNAL VILLAGE", NCR),  # override, names differ
    school("100005", None, None, None, overseas=True),                          # overseas
    school("100006", "ILOCOS NORTE", "BACARRA", "CALAYAB"),                  # code and name differ, barangay supports code
    school("100007", "ILOCOS NORTE", "NOWHERE TOWN", "POBLACION"),           # code only
    school("100008", "ILOCOS NORTE", "NOWHERE TOWN", "NOWHERE"),             # neither
    school("100009", "ILOCOS NORTE", "ADAMS", "POBLACION"),                  # code barangay outside the city
    school("100010", MANILA_PROVINCE, "SAMPALOC", "BARANGAY 395", NCR),      # Manila rollup by code
    school("100011", MANILA_PROVINCE, "SAMPALOC", "BARANGAY 395", NCR),      # Manila rollup by name
    school("100012", "SULU", "JOLO", "ASTURIAS", BARMM),                     # Sulu code recoded by Silver
    school("100013", "SULU", "DIMATALING", "SALOAGAN", BARMM),               # recoded row, codes not recoded
    school("100014", "NORTH COTABATO", "PIKIT", "BULIOK", BARMM),            # SGA, barangay supports code
    school("100015", "NORTH COTABATO", "PIKIT", "GINATILAN", BARMM),         # SGA, barangay does not
    school("100016", "NORTH COTABATO", "PIKIT", "DAMATULAN", BARMM),         # SGA, code barangay in another municipality (207519)
    school("100015", "NORTH COTABATO", "PIKIT", "GINATILAN", XII, "2020-21"),  # SGA by code, filed under Region XII
    school("100017", "(SGA - North Cotabato)", "PIKIT", "BULIOK", BARMM, "2024-25"),  # SGA spelling, no code
    school("100018", "NORTH COTABATO", "PIKIT", "GINATILAN", XII),           # Region XII school, not SGA
    school("100019", "NCR THIRD DISTRICT", "KALOOKAN CITY", "BARANGAY 1", NCR),  # reviewed alias
    school("100020", "ILOCOS NORTE", "BACARRA", "OLD TOWN"),                 # barangay old name
    school("100021", "ILOCOS NORTE", "BACARRA", LONG_NAME[:40].upper()),     # barangay cut at 40 characters
    school("100022", "ILOCOS NORTE", "BACARRA", "SAN ROQUE"),                # two barangays share the name
    school("100023", "NCR FOURTH DISTRICT", "TAGUIG CITY", "SIGNAL VILLAGE", NCR),  # override, names agree
    school("100024", "NCR FOURTH DISTRICT", "TAGUIG CITY", "SIGNAL VILLAGE", NCR),  # override, no code
    school("100025", "MAGUINDANAO", "DATU ODIN SINSUAT", "AWANG", BARMM),    # Maguindanao, split since 2022
    school("100026", "CITY OF ISABELA", "CITY OF ISABELA (Capital)", "AGUADA", "REGION IX"),  # province is a blank-level unit
]

# school_id, city code, barangay code, Sulu recoded
CROSSWALK = [
    ("100001", "0102801000", "0102801001", False),
    ("100003", "0102801000", "0102801001", False),
    ("100004", "1381500000", "1381500002", False),
    ("100006", "0102803000", "0102803002", False),
    ("100007", "0102801000", "0102801001", False),
    ("100009", "0102801000", "0102802001", False),
    ("100010", "1380608000", "1380608001", False),
    ("100012", "0906601000", "0906601001", True),
    ("100013", "0907301000", "0907301001", True),
    ("100014", "1999901000", "1999901001", False),
    ("100015", "1999901000", "1999901001", False),
    ("100016", "1999901000", "1999904001", False),
    ("100023", "1381500000", "1381500001", False),
]

BGY_SUPPORTS = "DepEd barangay name matches the code's barangay"


class Env:
    def __init__(self, tmp_path, rules=None):
        self.store = DuckDBStore()
        for path in sorted((REPO_ROOT / "etl" / "01_control").glob("0[1-4]_*.sql")):
            self.store.run_file(path)
        self.store.sql("CREATE SCHEMA IF NOT EXISTS edu_access.`03-silver`")
        self.store.sql("CREATE TABLE edu_access.`03-silver`.psa_psgc_clean (psgc_code STRING, name STRING, old_names STRING, "
                       "geographic_level STRING, level_blank BOOLEAN, region_code STRING, province_code STRING, city_municipality_code STRING, "
                       "publication_period STRING, is_master_reference BOOLEAN, batch_id STRING, source_row_number BIGINT)")
        for i, row in enumerate(PSGC, 1):
            code, name, old, level, region, province, parent = row
            self.store.sql("INSERT INTO edu_access.`03-silver`.psa_psgc_clean VALUES (?, ?, ?, ?, ?, ?, ?, ?, '2026-Q2', TRUE, 'P1', ?)",
                           [code, name, old, level, level is None, region, province, parent, i])
        self.store.sql("CREATE TABLE edu_access.`03-silver`.deped_enrollment_clean (school_year STRING, school_id STRING, school_name STRING, "
                       "region STRING, province STRING, municipality STRING, barangay STRING, barangay_possibly_truncated BOOLEAN, "
                       "is_overseas BOOLEAN, batch_id STRING, source_sha256 STRING, source_row_number BIGINT)")
        for row in ENROLLMENT:
            self.store.sql("INSERT INTO edu_access.`03-silver`.deped_enrollment_clean VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", list(row))
        self.store.sql("CREATE TABLE edu_access.`03-silver`.deped_enrollment_psgc_clean (school_id STRING, psgc_city_municipality STRING, "
                       "psgc_barangay STRING, psgc_recoded BOOLEAN, batch_id STRING, source_row_number BIGINT)")
        for i, row in enumerate(CROSSWALK, 1):
            self.store.sql("INSERT INTO edu_access.`03-silver`.deped_enrollment_psgc_clean VALUES (?, ?, ?, ?, 'X1', ?)", [*row, i])
        self.write(rules or MADE_UP_RULES, tmp_path)

    def write(self, rules, tmp_path):
        spec = deped.build_spec(rules)
        self.build, self.gate = tmp_path / "build.sql", tmp_path / "gate.sql"
        self.build.write_text(deped.build_sql(spec), encoding="utf-8")
        self.gate.write_text(deped.gate_sql(spec), encoding="utf-8")

    def params(self):
        return {"run_id": str(uuid.uuid4()), "code_revision": "c" * 40, "environment": "local"}

    def run(self, change=None):
        """Build, optionally change the candidate, then gate. Returns (run_id, error)."""
        params = self.params()
        try:
            self.store.run_file(self.build, params)
            if change:
                self.store.sql(change)
            self.store.run_file(self.gate, params)
        except Exception as error:
            return params["run_id"], str(error)
        return params["run_id"], None

    def rows(self, sql):
        return self.store.records(sql)

    def map(self, table=MAP):
        return {(r["school_year"], r["school_id"], r["geographic_level"]):
                (r["psgc_code"], r["match_status"], r["match_method"], r["reason"], r["review_status"])
                for r in self.rows(f"SELECT * FROM {table}")}

    def checks(self, run_id):
        return {r["check_name"]: r for r in self.rows(
            f"SELECT * FROM {CONTROL}.data_quality_results WHERE run_id = '{run_id}' AND layer = 'integration'")}

    def published(self):
        return self.rows("SELECT COUNT(*) AS n FROM information_schema.tables "
                         "WHERE table_schema = '04-integration' AND table_name = 'deped_school_psgc_map'")[0]["n"] == 1


@pytest.fixture
def got(tmp_path):
    env = Env(tmp_path)
    run_id, error = env.run()
    assert error is None
    return env.map()


def city(got, school_id, year="2023-24"):
    return got[(year, school_id, "city_mun")]


def bgy(got, school_id, year="2023-24"):
    return got[(year, school_id, "bgy")]


def test_every_school_year_gets_both_levels_and_no_row_is_dropped(tmp_path):
    env = Env(tmp_path)
    run_id, error = env.run()
    assert error is None
    assert env.rows(f"SELECT COUNT(*) AS n, COUNT(DISTINCT school_year || school_id) AS k FROM {MAP}") == [
        {"n": 2 * len(ENROLLMENT), "k": len(ENROLLMENT)}]
    checks = env.checks(run_id)
    assert not [c for c in checks.values() if c["status"] == "FAIL"]
    assert checks["rows_reconcile"]["actual"] == str(2 * len(ENROLLMENT))


def test_code_and_name_agree_is_code(got):
    assert city(got, "100001") == ("0102801000", "matched", "code", "code and name agree", "rule")
    assert bgy(got, "100001")[:4] == ("0102801001", "matched", "code", "code and name agree")


def test_name_only_uses_the_name_tier(got):
    assert city(got, "100002")[:4] == ("0102803000", "matched", "name_exact", "name only")
    assert bgy(got, "100002")[:3] == ("0102803001", "matched", "name_exact")


def test_code_wins_a_disagreement_only_when_the_deped_barangay_supports_it(got):
    assert city(got, "100003") == (None, "ambiguous", None, "code and name differ", "pending")
    assert bgy(got, "100003") == (None, "ambiguous", None, "city or municipality ambiguous", "pending")
    assert city(got, "100006")[:4] == ("0102803000", "matched", "code_name_differs", f"code; {BGY_SUPPORTS}")
    assert bgy(got, "100006")[:4] == ("0102803002", "matched", "code", "code; DepEd barangay name matches")


def test_code_only_is_code_name_differs_and_neither_is_unmatched(got):
    assert city(got, "100007")[:4] == ("0102801000", "matched", "code_name_differs", "code only")
    assert city(got, "100008") == (None, "unmatched", None, "no code, no name match", "pending")
    assert bgy(got, "100008") == (None, "unmatched", None, "city or municipality unmatched", "pending")


def test_barangay_outside_the_accepted_city_is_ambiguous(got):
    assert city(got, "100009")[:2] == ("0102801000", "matched")
    assert bgy(got, "100009") == (None, "ambiguous", None, "barangay outside the accepted city or municipality", "pending")


def test_manila_sub_municipality_rolls_up_by_code_or_name(got):
    assert city(got, "100010")[:4] == ("1380600000", "matched", "rollup", "code and name agree; Manila sub-municipality rolled up")
    assert bgy(got, "100010")[:3] == ("1380608001", "matched", "code")
    assert city(got, "100011")[:4] == ("1380600000", "matched", "rollup", "name only; Manila sub-municipality rolled up")
    assert bgy(got, "100011")[:3] == ("1380608001", "matched", "name_exact")


def test_code_region_moved_only_for_a_code_silver_recoded(got):
    assert city(got, "100012")[:3] == ("0906601000", "matched", "code_region_moved")
    assert bgy(got, "100012")[:3] == ("0906601001", "matched", "code_region_moved")
    # The school's row is recoded (Sulu province), but its codes point to Zamboanga del Sur and were kept.
    assert city(got, "100013")[:3] == ("0907301000", "matched", "code_name_differs")
    assert bgy(got, "100013")[:3] == ("0907301001", "matched", "code")


def test_special_geographic_area_matched_by_code_when_the_barangay_supports_it(got):
    assert city(got, "100014")[:4] == ("1999901000", "matched", "code_name_differs", f"Special Geographic Area; {BGY_SUPPORTS}")
    assert bgy(got, "100014")[:3] == ("1999901001", "matched", "code")


def test_special_geographic_area_otherwise_excluded_with_no_code(got):
    for school_id in ("100015", "100016"):  # 100016: the code's barangay is in another SGA municipality (207519)
        assert city(got, school_id) == (None, "excluded", None, "Special Geographic Area (D-031)", "pending")
        assert bgy(got, school_id) == (None, "excluded", None, "city or municipality excluded", "pending")


def test_special_geographic_area_is_found_by_code_and_by_every_listed_spelling(got):
    # SY 2020-21 files the school under Region XII; its EMISD code is in an SGA municipality.
    assert city(got, "100015", "2020-21")[:2] == (None, "excluded")
    # SY 2024-25 adds the province "(SGA - North Cotabato)"; with no code the school stays excluded.
    assert city(got, "100017", "2024-25")[:2] == (None, "excluded")
    # A Region XII school with no SGA code is an ordinary Cotabato school.
    assert city(got, "100018")[:3] == ("1204714000", "matched", "name_exact")


def test_reviewed_alias_old_name_and_truncated_barangay(got):
    assert city(got, "100019")[:3] == ("1380100000", "matched", "reviewed_alias")
    assert bgy(got, "100019")[:3] == ("1380100001", "matched", "name_exact")
    assert bgy(got, "100020")[:3] == ("0102802004", "matched", "name_old")
    assert bgy(got, "100021")[:3] == ("0102802005", "matched", "name_normalized")


def test_two_barangays_with_the_best_name_stay_unmatched_with_the_reason(got):
    assert bgy(got, "100022") == (None, "unmatched", None, "2 PSGC barangays match the best name tier", "pending")


def test_maguindanao_matches_inside_both_new_provinces(got):
    assert city(got, "100025")[:3] == ("1538701000", "matched", "name_exact")
    assert bgy(got, "100025")[:3] == ("1538701001", "matched", "name_exact")


def test_override_method_follows_the_code_rule_and_a_missing_unit_stays_pending(got):
    assert bgy(got, "100004") == ("1381500002", "matched", "code_name_differs", "reviewed override", "reviewed")
    assert bgy(got, "100023") == ("1381500001", "matched", "code", "reviewed override", "reviewed")
    assert bgy(got, "100024") == (None, "unmatched", None, "reviewed override: no unit", "pending")


def test_a_blank_level_unit_at_the_province_position_is_a_province(got):
    # City of Isabela is not a province, but PSGC files it at the province position with a blank level;
    # reading it as the province keeps the made-up namesake in Ilocos Norte out.
    assert city(got, "100026")[:4] == ("0990101000", "matched", "name_exact", "name only")
    assert bgy(got, "100026")[:3] == ("0990101002", "matched", "name_exact")


def test_overseas_schools_are_kept_and_excluded(got):
    assert city(got, "100005") == (None, "excluded", None, "Philippine Schools Overseas", "pending")
    assert bgy(got, "100005") == (None, "excluded", None, "city or municipality excluded", "pending")


def test_the_gate_warns_on_what_needs_review(tmp_path):
    env = Env(tmp_path)
    run_id, error = env.run()
    assert error is None
    checks = env.checks(run_id)
    assert checks["override_without_unit"]["status"] == "WARN" and checks["override_without_unit"]["actual"] == "1"
    assert checks["override_without_school"]["status"] == "PASS"
    assert {checks[n]["status"] for n in ("unmatched", "ambiguous", "excluded", "review_pending")} == {"WARN"}
    assert checks["code_not_in_psgc"]["status"] == "PASS"


def test_a_barangay_code_missing_from_the_psgc_counts_as_no_code(tmp_path, monkeypatch):
    # As in the reviewed rule and at city level: the name decides, and the gate warns instead of failing.
    monkeypatch.setattr(sys.modules[__name__], "ENROLLMENT", ENROLLMENT + [
        school("100098", "ILOCOS NORTE", "BACARRA", "NUEVA ERA"), school("100099", "ILOCOS NORTE", "ADAMS", "NOWHERE")])
    monkeypatch.setattr(sys.modules[__name__], "CROSSWALK", CROSSWALK + [
        ("100098", "0102802000", "0102802999", False), ("100099", "0102801000", "0102801999", False)])
    env = Env(tmp_path)
    run_id, error = env.run()
    assert error is None
    got = env.map()
    assert bgy(got, "100098") == ("0102802004", "matched", "name_exact", "name only", "rule")
    assert bgy(got, "100099") == (None, "unmatched", None, "no code, no name match", "pending")
    assert env.rows(f"SELECT code_candidate FROM {MAP} WHERE school_id = '100098' AND geographic_level = 'bgy'") == [
        {"code_candidate": "0102802999"}]
    checks = env.checks(run_id)
    assert checks["code_not_in_psgc"]["status"] == "WARN" and checks["code_not_in_psgc"]["actual"] == "2"


@pytest.mark.parametrize("check,change", [
    ("rows_reconcile", f"DELETE FROM {CANDIDATE} WHERE school_id = '100001' AND geographic_level = 'bgy'"),
    ("source_keys_match", f"UPDATE {CANDIDATE} SET school_id = '999999', source_row_ref = school_year || '/999999/' || geographic_level WHERE school_id = '100001'"),
    ("barangay_inside_city", f"UPDATE {CANDIDATE} SET psgc_code = '0102802001' WHERE school_id = '100001' AND geographic_level = 'bgy'"),
    ("status_combination_valid", f"UPDATE {CANDIDATE} SET match_status = 'ambiguous' WHERE school_id = '100001' AND geographic_level = 'city_mun'"),
    ("psgc_level_valid", f"UPDATE {CANDIDATE} SET psgc_code = '0102800000' WHERE school_id = '100001' AND geographic_level = 'city_mun'"),
    ("lineage_complete", f"UPDATE {CANDIDATE} SET source_reference_date = NULL WHERE school_id = '100001'"),
    ("rows_built_by_this_run", f"UPDATE {CANDIDATE} SET run_id = 'an-earlier-run' WHERE school_id = '100001'"),
    ("master_psgc_version", "UPDATE edu_access.`03-silver`.psa_psgc_clean SET publication_period = '2026-Q3'"),
])
def test_a_failed_check_keeps_the_last_published_map(tmp_path, check, change):
    env = Env(tmp_path)
    assert env.run()[1] is None
    before = env.map()
    run_id, error = env.run(change)
    assert "Integration gate failed" in error
    assert env.checks(run_id)[check]["status"] == "FAIL"
    assert env.map() == before


def test_a_match_rate_below_the_floor_fails_and_publishes_nothing(tmp_path):
    rules = copy.deepcopy(MADE_UP_RULES)
    rules["gate"]["min_match_rate_pct"] = 99.0
    env = Env(tmp_path, rules)
    run_id, error = env.run()
    assert "Integration gate failed" in error
    assert env.checks(run_id)["match_rate_2023-24_bgy"]["status"] == "FAIL"
    assert not env.published()


def test_profiled_counts_pass_when_unchanged_and_block_publication_when_they_change(tmp_path):
    env = Env(tmp_path)
    assert env.run()[1] is None
    counts = {}
    for r in env.rows(f"SELECT school_year, geographic_level, match_status, COUNT(*) AS n FROM {MAP} GROUP BY ALL"):
        counts.setdefault(r["school_year"], {}).setdefault(r["geographic_level"], dict.fromkeys(
            ("matched", "ambiguous", "unmatched", "excluded"), 0))[r["match_status"]] = r["n"]
    rules = copy.deepcopy(MADE_UP_RULES)
    rules["gate"]["profiled_counts"] = counts
    env.write(rules, tmp_path)
    run_id, error = env.run()
    assert error is None
    before = env.map()
    profiled = {k: v["status"] for k, v in env.checks(run_id).items() if k.startswith("profiled_")}
    assert profiled and set(profiled.values()) == {"PASS"}
    rules["gate"]["profiled_counts"]["2023-24"]["bgy"]["matched"] += 1
    env.write(rules, tmp_path)
    run_id, error = env.run()
    assert "Integration gate failed" in error
    assert env.checks(run_id)["profiled_2023-24_bgy"]["status"] == "FAIL"
    assert env.map() == before


def test_an_override_for_a_place_with_no_school_warns(tmp_path):
    rules = copy.deepcopy(MADE_UP_RULES)
    rules["overrides"].append(dict(rules["overrides"][0], deped_barangay="NOT A BARANGAY"))
    env = Env(tmp_path, rules)
    run_id, error = env.run()
    assert error is None
    assert env.checks(run_id)["override_without_school"]["status"] == "WARN"


@pytest.mark.parametrize("change,message", [
    (lambda r: r["overrides"][0].update(reviewer=""), "reviewer"),
    (lambda r: r["overrides"][0].update(level="city_mun"), "city_mun overrides"),
    (lambda r: r.pop("special_geographic_area"), "special_geographic_area"),
    (lambda r: r["gate"].update(min_match_rate_pct=101), "min_match_rate_pct"),
    (lambda r: r.update(psgc_version="2Q 2026"), "psgc_version"),
    (lambda r: r["gate"]["profiled_counts"].update({"2023-24": {"bgy": {}}}), "profiled_counts"),
])
def test_config_refuses_incomplete_rules(change, message):
    rules = copy.deepcopy(RULES)
    change(rules)
    with pytest.raises(IngestionError, match=message):
        deped.build_spec(rules)


def test_production_aliases_equal_the_reviewed_analysis_aliases():
    tree = ast.parse((REPO_ROOT / "analysis" / "cross_source" / "cross_source_deped.py").read_text(encoding="utf-8"))
    assignment = next(n for n in tree.body if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == "LOCALITY_ALIASES" for t in n.targets))
    assert {a["deped_name"]: a["psgc_code"] for a in RULES["locality_aliases"]} == ast.literal_eval(assignment.value)


@pytest.mark.parametrize("command,path,function", [
    ("sql", "etl/04_integration/01_map_deped_school_psgc.sql", deped.build_sql),
    ("gate", "etl/04_integration/90_validate_deped_school_psgc_map.sql", deped.gate_sql),
])
def test_committed_sql_matches_the_generator(command, path, function):
    assert (REPO_ROOT / path).read_text(encoding="utf-8") == function(deped.load_spec(REPO_ROOT)), (
        f"Regenerate: python -m src.integration.deped_school_psgc {command} > {path}")
