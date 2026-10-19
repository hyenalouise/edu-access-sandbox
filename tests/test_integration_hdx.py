"""Integration for hdx_boundaries: the HDX ADM3 → PSGC crosswalk (hdx_adm3_psgc_map, #93).

Made-up rows go straight into the two published Silver tables it reads (hdx_adm3_clean and
psa_psgc_clean) in an in-memory DuckDB, then through the generated build and gate SQL, run the way
the job's two SQL tasks run them. Each made-up HDX feature exercises one rule of #74 (HB-2).
No real COD-AB or PSGC row is used.
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
from src.integration import hdx_adm3_psgc as hdx

CONTROL = "edu_access.`01-control`"
MAP = "edu_access.`04-integration`.hdx_adm3_psgc_map"
CANDIDATE = "edu_access.`04-integration`.hdx_adm3_psgc_map_candidate"
RELEASE = "2025-02-13"  # the made-up HDX rows' valid_on
# The committed rules without its reviewed overrides, which name real COD-AB features: each test adds its own.
RULES = {**json.loads((REPO_ROOT / "config" / "integration" / "hdx_adm3_psgc.json").read_text(encoding="utf-8")),
         "overrides": []}

PSGC = [  # psgc_code, name, old_names, correspondence_code, geographic_level
    ("0100000000", "Region I (Ilocos Region)", None, "010000000", "Reg"),
    ("0102800000", "Ilocos Norte", None, "012800000", "Prov"),
    ("0102801000", "Adams", None, "012801000", "Mun"),
    ("0102802000", "Bacarra", None, "012802000", "Mun"),
    ("0102803000", "City of Batac", None, "012803000", "City"),
    ("0102804000", "Banna", None, "012804000", "Mun"),
    ("0102805000", "Banna", None, "012805000", "Mun"),
    ("0102806000", "Peñablanca", "Old Town", "012806000", "Mun"),
    ("1800000000", "Negros Island Region", None, None, "Reg"),
    ("1804500000", "Negros Occidental", None, "064500000", "Prov"),
    ("1804501000", "Bacolod City", None, "064501000", "City"),
    ("0906600000", "Sulu", None, "096600000", "Prov"),
    ("0906601000", "Jolo", None, "096601000", "Mun"),
    ("1908700000", "Maguindanao del Norte", None, None, "Prov"),
    ("1908711000", "Sultan Mastura", None, None, "Mun"),
    ("1908712000", "Parang", None, None, "Mun"),
]
# adm3_pcode, adm3_name, adm2_pcode, and what the map should say: (psgc_code, status, method, review)
HDX = {
    "PH0102801": ("Adams", "PH01028", ("0102801000", "matched", "code", "rule")),
    "PH1908711": ("Parang", "PH19087", ("1908712000", "matched", "name_exact", "rule")),   # the code names Sultan Mastura
    "PH0604501": ("Bacolod City", "PH06045", ("1804501000", "matched", "correspondence_code", "rule")),
    "PH1906601": ("Jolo", "PH19066", ("0906601000", "matched", "code_region_moved", "rule")),
    "PH0102802": ("Bacarra New Name", "PH01028", (None, "ambiguous", None, "pending")),  # code agrees, name differs
    "PH0102899": ("Batac City", "PH01028", ("0102803000", "matched", "name_exact", "rule")),
    "PH0102898": ("Banna", "PH01028", (None, "ambiguous", None, "pending")),
    "PH1909901": ("Special Geographic Area - Carmen", "PH19099", (None, "unmatched", None, "pending")),
    "PH0102897": ("Penablanca", "PH01028", ("0102806000", "matched", "name_normalized", "rule")),
}


class Env:
    def __init__(self, tmp_path, rules=None, hdx_rows=None, psgc_rows=None, db=None):
        self.tmp = tmp_path
        self.store = DuckDBStore(db)
        for path in sorted((REPO_ROOT / "etl" / "01_control").glob("0[1-4]_*.sql")):
            self.store.run_file(path)
        self.store.sql("CREATE SCHEMA IF NOT EXISTS edu_access.`03-silver`")
        self.store.sql("CREATE TABLE edu_access.`03-silver`.psa_psgc_clean (psgc_code STRING, name STRING, old_names STRING, "
                       "correspondence_code STRING, geographic_level STRING, publication_period STRING, "
                       "is_master_reference BOOLEAN, batch_id STRING, source_row_number BIGINT)")
        for i, row in enumerate(psgc_rows or PSGC, 1):
            self.store.sql("INSERT INTO edu_access.`03-silver`.psa_psgc_clean VALUES (?, ?, ?, ?, ?, '2026-Q2', TRUE, 'P1', ?)",
                           [*row, i])
        self.store.sql("CREATE TABLE edu_access.`03-silver`.hdx_adm3_clean (adm3_pcode STRING, adm3_name STRING, "
                       "adm2_pcode STRING, adm2_name STRING, adm1_pcode STRING, valid_on DATE, batch_id STRING, "
                       "source_sha256 STRING, source_row_number BIGINT)")
        for i, (pcode, (name, adm2, _)) in enumerate((hdx_rows or HDX).items(), 1):
            self.store.sql("INSERT INTO edu_access.`03-silver`.hdx_adm3_clean VALUES "
                           "(?, ?, ?, NULL, ?, DATE '2025-02-13', 'B1', 'sha', ?)", [pcode, name, adm2, adm2[:4], i])
        spec = hdx.build_spec(rules or RULES)
        self.build, self.gate = tmp_path / "build.sql", tmp_path / "gate.sql"
        self.build.write_text(hdx.build_sql(spec), encoding="utf-8")
        self.gate.write_text(hdx.gate_sql(spec), encoding="utf-8")

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
                         "AND pipeline_name = 'integration_build'")[0]["status"]


def with_overrides(*overrides):
    rules = copy.deepcopy(RULES)
    rules["overrides"] = list(overrides)
    return rules


def published(env):
    return bool(env.rows("SELECT 1 FROM information_schema.tables WHERE table_schema = '04-integration' "
                         "AND table_name = 'hdx_adm3_psgc_map'"))


# --- The rules ----------------------------------------------------------------------------

def test_every_feature_gets_one_row_by_the_rules_in_order(tmp_path):
    env = Env(tmp_path)
    run_id, error = env.run()
    assert error is None
    got = {r["adm3_pcode"]: (r["psgc_code"], r["match_status"], r["match_method"], r["review_status"])
           for r in env.rows(f"SELECT * FROM {MAP}")}
    assert got == {pcode: expected for pcode, (_, _, expected) in HDX.items()}
    assert env.run_status(run_id) == "succeeded"


def test_a_code_alone_is_not_enough(tmp_path):
    """COD-AB PH1908711 is Parang; PSGC 1908711000 is Sultan Mastura. The name decides."""
    env = Env(tmp_path)
    env.run()
    row = env.rows(f"SELECT * FROM {MAP} WHERE adm3_pcode = 'PH1908711'")[0]
    assert (row["psgc_code"], row["psgc_name"]) == ("1908712000", "Parang")
    assert "the code names another unit" in row["reason"]


def test_every_row_keeps_its_source_and_psgc_side(tmp_path):
    env = Env(tmp_path)
    env.run()
    row = env.rows(f"SELECT * FROM {MAP} WHERE adm3_pcode = 'PH0604501'")[0]
    assert (row["source_id"], row["adm3_name"], row["code_candidate"], row["psgc_version"], row["geographic_level"]) == (
        "hdx_boundaries", "Bacolod City", "0604501000", "2026-Q2", "city_mun")
    assert (row["batch_id"], row["source_row_number"], row["psgc_batch_id"]) == ("B1", 3, "P1")


# --- The gate -----------------------------------------------------------------------------

def test_the_gate_passes_and_warns_on_what_needs_review(tmp_path):
    env = Env(tmp_path)
    run_id, _ = env.run()
    checks = env.checks(run_id)
    assert set(checks) == {n for n, _ in hdx.gate_checks(hdx.build_spec(RULES))}
    assert not [n for n, c in checks.items() if c["status"] == "FAIL"]
    assert {n: checks[n]["actual"] for n in ("review_pending", "unmatched", "ambiguous", "psgc_units_without_feature")} == {
        "review_pending": "3", "unmatched": "1", "ambiguous": "2", "psgc_units_without_feature": "4"}
    assert {checks[n]["status"] for n in ("review_pending", "unmatched", "ambiguous", "psgc_units_without_feature")} == {"WARN"}
    assert checks["rows_reconcile"]["actual"] == str(len(HDX))


def test_overrides_are_applied_and_marked_reviewed(tmp_path):
    env = Env(tmp_path, rules=with_overrides(
        {"adm3_pcode": "PH1909901", "source_reference_date": RELEASE, "psgc_code": None, "match_method": None,
         "reason": "Special Geographic Area unit, no PSGC equivalent until a spatial check (D-031)", "evidence": "#74 HB-2"},
        {"adm3_pcode": "PH0102802", "source_reference_date": RELEASE, "psgc_code": "0102802000", "match_method": "code_renamed",
         "reason": "Renamed since COD-AB v03", "evidence": "made up"}))
    run_id, error = env.run()
    assert error is None
    got = {r["adm3_pcode"]: (r["match_status"], r["match_method"], r["review_status"]) for r in env.rows(f"SELECT * FROM {MAP}")}
    assert got["PH1909901"] == ("unmatched", None, "reviewed")
    assert got["PH0102802"] == ("matched", "code_renamed", "reviewed")
    assert env.checks(run_id)["overrides_applied"]["status"] == "PASS"


@pytest.mark.parametrize("override, failed", [
    ({"adm3_pcode": "PH0102898", "source_reference_date": RELEASE, "psgc_code": "0102801000", "match_method": "reviewed_alias",
      "reason": "takes Adams a second time", "evidence": "made up"}, "psgc_code_taken_once"),
])
def test_a_bad_override_fails_the_gate_and_nothing_is_published(tmp_path, override, failed):
    env = Env(tmp_path, rules=with_overrides(override))
    run_id, error = env.run()
    assert error and "Integration gate failed" in error
    assert env.checks(run_id)[failed]["status"] == "FAIL"
    assert env.run_status(run_id) == "failed"
    assert not published(env)


def test_an_override_for_a_feature_not_in_this_release_warns_and_publishes(tmp_path):
    """A later COD-AB release may drop a reviewed feature: the gate warns so the override is reviewed again."""
    env = Env(tmp_path, rules=with_overrides(
        {"adm3_pcode": "PH0109999", "source_reference_date": RELEASE, "psgc_code": None, "match_method": None, "reason": "not an HDX feature", "evidence": "made up"}))
    run_id, error = env.run()
    assert error is None
    checks = env.checks(run_id)
    assert (checks["override_feature_missing"]["status"], checks["override_feature_missing"]["actual"]) == ("WARN", "1")
    assert checks["overrides_applied"]["status"] == "PASS"
    assert published(env)


def test_the_committed_overrides_are_valid():
    spec = hdx.load_spec(REPO_ROOT)
    assert len(spec.overrides) == len({o.adm3_pcode for o in spec.overrides}) > 0
    assert {o.source_reference_date for o in spec.overrides} == {"2025-02-13"}


def test_an_override_applies_only_to_the_release_it_was_reviewed_for(tmp_path):
    """Review on #139: a later HDX release does not inherit a reviewed decision; its feature goes back to review."""
    env = Env(tmp_path, rules=with_overrides(
        {"adm3_pcode": "PH0102802", "source_reference_date": RELEASE, "psgc_code": "0102802000",
         "match_method": "code_renamed", "reason": "Renamed since COD-AB v03", "evidence": "made up"}))
    env.store.sql("INSERT INTO edu_access.`03-silver`.hdx_adm3_clean VALUES "
                  "('PH0102802', 'Bacarra New Name', 'PH01028', NULL, 'PH01', DATE '2026-01-01', 'B2', 'sha2', 1)")
    run_id, error = env.run()
    assert error is None
    got = {str(r["source_reference_date"]): (r["match_status"], r["psgc_code"], r["review_status"]) for r in env.rows(
        f"SELECT * FROM {MAP} WHERE adm3_pcode = 'PH0102802'")}
    assert got == {RELEASE: ("matched", "0102802000", "reviewed"), "2026-01-01": ("ambiguous", None, "pending")}
    assert env.checks(run_id)["overrides_applied"]["status"] == "PASS"


def test_an_override_for_a_release_without_its_feature_warns(tmp_path):
    """Review on #139: the feature is in an older release but not the one the override names."""
    env = Env(tmp_path, rules=with_overrides(
        {"adm3_pcode": "PH1909901", "source_reference_date": "2026-01-01", "psgc_code": None, "match_method": None,
         "reason": "Special Geographic Area unit (D-031)", "evidence": "made up"}))
    run_id, error = env.run()
    assert error is None
    checks = env.checks(run_id)
    assert (checks["override_feature_missing"]["status"], checks["override_feature_missing"]["actual"]) == ("WARN", "1")
    row = env.rows(f"SELECT * FROM {MAP} WHERE adm3_pcode = 'PH1909901'")[0]
    assert (row["match_status"], row["review_status"]) == ("unmatched", "pending")


def test_a_code_that_names_two_units_stays_ambiguous(tmp_path):
    """Review on #139: two PSGC units share one Correspondence Code and the name; D-030 needs one-to-one."""
    psgc = PSGC + [("1804502000", "Talisay", None, "064502000", "City"),
                   ("1804503000", "Talisay", None, "064502000", "Mun")]
    env = Env(tmp_path, psgc_rows=psgc, hdx_rows={"PH0604502": ("Talisay", "PH06045", None)})
    run_id, error = env.run()
    assert error is None
    row = env.rows(f"SELECT * FROM {MAP}")[0]
    assert (row["match_status"], row["psgc_code"], row["match_method"], row["review_status"]) == ("ambiguous", None, None, "pending")
    assert row["reason"].startswith("2 units share this code under the Correspondence Code rule")
    assert env.checks(run_id)["ambiguous"]["actual"] == "1"


def test_a_feature_is_never_dropped(tmp_path):
    env = Env(tmp_path, hdx_rows={"PH0700000": ("Nowhere", "PH07000", None)})
    run_id, error = env.run()
    assert error is None
    assert env.rows(f"SELECT match_status, geographic_level, reason FROM {MAP}") == [
        {"match_status": "unmatched", "geographic_level": "city_mun",
         "reason": "no PSGC province found for adm2_pcode, so no name match was tried"}]


def test_a_code_with_another_name_is_never_published_as_matched(tmp_path):
    """Review on #139: a code that points to a unit whose name differs is ambiguous until an override confirms it."""
    env = Env(tmp_path)
    env.run()
    row = env.rows(f"SELECT * FROM {MAP} WHERE adm3_pcode = 'PH0102802'")[0]
    assert (row["match_status"], row["psgc_code"], row["match_method"], row["review_status"]) == ("ambiguous", None, None, "pending")
    assert row["code_candidate"] == "0102802000" and "0102802000" in row["reason"]


def test_names_are_matched_only_inside_a_matched_province(tmp_path):
    """Review on #139: no nationwide fallback. A feature whose province is not in PSGC stays unmatched,
    even when its name is a PSGC unit elsewhere."""
    env = Env(tmp_path, hdx_rows={"PH0799901": ("Adams", "PH07999", None)})
    env.run()
    row = env.rows(f"SELECT * FROM {MAP}")[0]
    assert (row["match_status"], row["psgc_code"]) == ("unmatched", None)
    assert row["reason"] == "no PSGC province found for adm2_pcode, so no name match was tried"


def test_every_row_has_a_level_and_a_source_row_ref(tmp_path):
    env = Env(tmp_path)
    env.run()
    rows = env.rows(f"SELECT adm3_pcode, geographic_level, source_row_ref FROM {MAP}")
    assert {r["geographic_level"] for r in rows} == {"city_mun"}
    assert {r["source_row_ref"] for r in rows} == {f"{p}/2025-02-13" for p in HDX}


def test_a_feature_in_two_releases_gets_a_row_per_release(tmp_path):
    """The key is (adm3_pcode, source_reference_date): uniqueness and PSGC reuse are checked per release."""
    env = Env(tmp_path)
    env.store.sql("INSERT INTO edu_access.`03-silver`.hdx_adm3_clean VALUES "
                  "('PH0102801', 'Adams', 'PH01028', NULL, 'PH01', DATE '2026-01-01', 'B2', 'sha2', 1)")
    run_id, error = env.run()
    assert error is None
    rows = env.rows(f"SELECT source_reference_date, psgc_code FROM {MAP} WHERE adm3_pcode = 'PH0102801' ORDER BY 1")
    assert [r["psgc_code"] for r in rows] == ["0102801000", "0102801000"]
    checks = env.checks(run_id)
    assert {n: checks[n]["status"] for n in ("one_row_per_feature", "psgc_code_taken_once")} == {
        "one_row_per_feature": "PASS", "psgc_code_taken_once": "PASS"}


def test_psgc_units_without_feature_are_counted_per_release(tmp_path):
    """Review on #139: a PSGC unit matched only in an older release is still missing from the newer one."""
    env = Env(tmp_path)
    env.store.sql("INSERT INTO edu_access.`03-silver`.hdx_adm3_clean VALUES "
                  "('PH0102801', 'Adams', 'PH01028', NULL, 'PH01', DATE '2026-01-01', 'B2', 'sha2', 1)")
    run_id, error = env.run()
    assert error is None
    check = env.checks(run_id)["psgc_units_without_feature"]
    # 10 PSGC cities and municipalities: 4 have no feature in 2025-02-13, 9 in 2026-01-01 (only Adams there).
    assert (check["status"], check["actual"]) == ("WARN", "13")


@pytest.mark.parametrize("pcode, change", [
    ("PH0102801", "psgc_code = '1908711000', review_status = 'pending'"),   # matched, but nobody reviewed it
    ("PH1909901", "review_status = 'rule'"),                                 # unmatched by a rule
    ("PH0102898", "match_method = 'code', review_status = 'rule'"),          # ambiguous with a method
])
def test_a_status_combination_d052_forbids_fails_the_gate_and_the_published_map_is_kept(tmp_path, pcode, change):
    """Review on #139: the gate, not only the build, enforces that a matched row is rule-based or reviewed and that
    ambiguous and unmatched rows carry no method or code. A tampered candidate must never replace the published map."""
    env = Env(tmp_path)
    assert env.run()[1] is None                      # a first map is published
    before = env.rows(f"SELECT * EXCLUDE (run_id, built_at_utc) FROM {MAP} ORDER BY adm3_pcode")
    run_id = str(uuid.uuid4())
    params = {"run_id": run_id, "code_revision": "c" * 40, "environment": "local"}
    env.store.run_file(env.build, params)
    env.store.sql(f"UPDATE {CANDIDATE} SET {change} WHERE adm3_pcode = '{pcode}'")
    with pytest.raises(Exception, match="Integration gate failed"):
        env.store.run_file(env.gate, params)
    assert env.checks(run_id)["status_combination_valid"]["status"] == "FAIL"
    assert env.run_status(run_id) == "failed"
    assert env.rows(f"SELECT * EXCLUDE (run_id, built_at_utc) FROM {MAP} ORDER BY adm3_pcode") == before


@pytest.mark.parametrize("change, failed", [
    ("psgc_name = 'Wrong name'", "psgc_name_matches_unit"),
    ("psgc_code = '1908712000', psgc_name = 'Parang'", "name_match_inside_province"),
])
def test_a_tampered_name_match_fails_the_gate_and_the_published_map_is_kept(tmp_path, change, failed):
    """Issue #180: the gate re-checks both the PSGC name and the province scope of name-rule matches."""
    env = Env(tmp_path)
    assert env.run()[1] is None
    before = env.rows(f"SELECT * EXCLUDE (run_id, built_at_utc) FROM {MAP} ORDER BY adm3_pcode")
    run_id = str(uuid.uuid4())
    params = {"run_id": run_id, "code_revision": "c" * 40, "environment": "local"}
    env.store.run_file(env.build, params)
    env.store.sql(f"UPDATE {CANDIDATE} SET {change} WHERE adm3_pcode = 'PH0102899'")
    with pytest.raises(Exception, match="Integration gate failed"):
        env.store.run_file(env.gate, params)
    assert env.checks(run_id)[failed]["status"] == "FAIL"
    assert env.run_status(run_id) == "failed"
    assert env.rows(f"SELECT * EXCLUDE (run_id, built_at_utc) FROM {MAP} ORDER BY adm3_pcode") == before


def test_two_master_psgc_periods_fail_the_gate(tmp_path):
    """Review on #139: one_psgc_version counts the master periods in the PSGC input, not the map's own column."""
    env = Env(tmp_path)
    env.store.sql("INSERT INTO edu_access.`03-silver`.psa_psgc_clean VALUES "
                  "('0102807000', 'Burgos', NULL, '012807000', 'Mun', '2026-Q1', TRUE, 'P0', 99)")
    run_id, error = env.run()
    assert error and "Integration gate failed" in error
    assert env.checks(run_id)["one_psgc_version"]["actual"] == "2"
    assert not published(env)


# --- The rules file and the committed files ------------------------------------------------

@pytest.mark.parametrize("override, message", [
    ({"adm3_pcode": "PH12", "source_reference_date": RELEASE, "psgc_code": None, "match_method": None, "reason": "r", "evidence": "e"}, "must match"),
    ({"adm3_pcode": "PH0102801", "psgc_code": None, "match_method": None, "reason": "r", "evidence": "e"}, "release date"),
    ({"adm3_pcode": "PH0102801", "source_reference_date": "13/02/2025", "psgc_code": None, "match_method": None,
      "reason": "r", "evidence": "e"}, "release date"),
    ({"adm3_pcode": "PH0102801", "source_reference_date": RELEASE, "psgc_code": "12", "match_method": "code", "reason": "r", "evidence": "e"}, "ten digits"),
    ({"adm3_pcode": "PH0102801", "source_reference_date": RELEASE, "psgc_code": "0102801000", "match_method": "guess", "reason": "r", "evidence": "e"}, "D-029"),
    ({"adm3_pcode": "PH0102801", "source_reference_date": RELEASE, "psgc_code": None, "match_method": "spatial", "reason": "r", "evidence": "e"}, "no match_method"),
    ({"adm3_pcode": "PH0102801", "source_reference_date": RELEASE, "psgc_code": "0102801000", "match_method": "code", "reason": "", "evidence": "e"}, "reason and evidence"),
    ({"adm3_pcode": "PH0102801", "source_reference_date": RELEASE, "psgc_code": "0102801000", "match_method": "code", "reason": "it's", "evidence": "e"}, "quotes"),
])
def test_a_bad_override_is_refused_before_any_sql(override, message):
    with pytest.raises(IngestionError, match=message):
        hdx.build_spec(with_overrides(override))


@pytest.mark.parametrize("command, path, function", [
    ("sql", "etl/04_integration/03_map_hdx_adm3_psgc.sql", hdx.build_sql),
    ("gate", "etl/04_integration/90_validate_hdx_adm3_psgc_map.sql", hdx.gate_sql),
])
def test_committed_files_match_the_generator(command, path, function):
    assert (REPO_ROOT / path).read_text(encoding="utf-8") == function(hdx.load_spec(REPO_ROOT)), (
        f"Regenerate: python -m src.integration.hdx_adm3_psgc {command} > {path}")


# --- The verification script --------------------------------------------------------------

def test_the_verification_script_reports_the_failed_candidate_not_the_last_published_map(tmp_path, monkeypatch, capsys):
    """Review on #139: after a failed gate the published map is the previous build, so the report reads the candidate."""
    db = tmp_path / "map.duckdb"
    env = Env(tmp_path, db=db)
    assert env.run()[1] is None                      # a first map is published
    env.store.sql("INSERT INTO edu_access.`03-silver`.hdx_adm3_clean VALUES "
                  "('PH0102896', 'Nowhere', 'PH01028', NULL, 'PH01', DATE '2025-02-13', 'B1', 'sha', 99)")
    env.store.sql("INSERT INTO edu_access.`03-silver`.psa_psgc_clean VALUES "
                  "('0102807000', 'Burgos', NULL, '012807000', 'Mun', '2026-Q1', TRUE, 'P0', 99)")   # two periods: FAIL
    env.store.close()
    repo = tmp_path / "repo"
    shutil.copytree(REPO_ROOT / "etl" / "04_integration", repo / "etl" / "04_integration")
    path = REPO_ROOT / "analysis" / "verification" / "hdx_adm3_psgc_map.py"
    module_spec = importlib.util.spec_from_file_location("hdx_adm3_psgc_map_script", path)
    script = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(script)
    monkeypatch.setattr(script, "REPO_ROOT", repo)
    assert script.main(["--db", str(db)]) == 1
    out = capsys.readouterr().out
    counted = out.split("by status and method:")[1].splitlines()[1:]
    assert sum(int(line.split()[-1]) for line in counted if line.startswith("  ")) == len(HDX) + 1   # the candidate
    assert "PH0102896" in (repo / "local_state" / "hdx_adm3_psgc_review.md").read_text(encoding="utf-8")
