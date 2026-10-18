"""DepEd enrollment school/year geography → PSGC Integration map (#91, D-049).

Only made-up Silver rows are used.  They run through the same generated build and gate SQL as the
Databricks job, proving that every school-year gets both map levels and that a failed gate preserves
the last published map.
"""

import ast
import copy
import json
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

# code, name, old_names, level, region, province, city parent
PSGC = [
    ("0100000000", "Region I", None, "Reg", "0100000000", None, None),
    ("0102800000", "Ilocos Norte", None, "Prov", "0100000000", "0102800000", None),
    ("0102801000", "Adams", None, "Mun", "0100000000", "0102800000", None),
    ("0102802000", "Bacarra", None, "Mun", "0100000000", "0102800000", None),
    ("0102803000", "City of Batac", None, "City", "0100000000", "0102800000", None),
    ("0102801001", "Poblacion", None, "Bgy", "0100000000", "0102800000", "0102801000"),
    ("0102802001", "Poblacion", None, "Bgy", "0100000000", "0102800000", "0102802000"),
    ("0102803001", "Barangay One", None, "Bgy", "0100000000", "0102800000", "0102803000"),
    ("1300000000", "National Capital Region", None, "Reg", "1300000000", None, None),
    ("1381500000", "City of Taguig", None, "City", "1300000000", None, None),
    ("1381500001", "Central Signal Village", "Signal Village", "Bgy", "1300000000", None, "1381500000"),
    ("1381500002", "South Signal Village", None, "Bgy", "1300000000", None, "1381500000"),
]


def school(school_id, province, municipality, barangay, overseas=False):
    return ("2023-24", school_id, f"School {school_id}", "PSO" if overseas else "REGION I",
            province, municipality, barangay, len(barangay or "") == 40, overseas, "E1", "esha", int(school_id))


ENROLLMENT = [
    school("100001", "ILOCOS NORTE", "ADAMS", "POBLACION"),                      # code + name agree
    school("100002", "ILOCOS NORTE", "CITY OF BATAC", "BARANGAY ONE"),         # name only
    school("100003", "ILOCOS NORTE", "BACARRA", "BARANGAY ONE"),               # code says Adams, source name does not support it
    school("100004", "NCR FOURTH DISTRICT", "TAGUIG CITY", "SIGNAL VILLAGE"),  # reviewed barangay override
    school("100005", None, None, None, True),                                      # overseas retained, excluded
]

CROSSWALK = [
    ("100001", "0102801000", "0102801001", False),
    ("100003", "0102801000", "0102801001", False),
    ("100004", "1381500000", "1381500002", False),
]


class Env:
    def __init__(self, tmp_path, rules=None):
        self.store = DuckDBStore()
        for path in sorted((REPO_ROOT / "etl" / "01_control").glob("0[1-4]_*.sql")):
            self.store.run_file(path)
        self.store.sql("CREATE SCHEMA IF NOT EXISTS edu_access.`03-silver`")
        self.store.sql("CREATE TABLE edu_access.`03-silver`.psa_psgc_clean (psgc_code STRING, name STRING, old_names STRING, "
                       "geographic_level STRING, region_code STRING, province_code STRING, city_municipality_code STRING, "
                       "publication_period STRING, is_master_reference BOOLEAN, batch_id STRING, source_row_number BIGINT)")
        for i, row in enumerate(PSGC, 1):
            self.store.sql("INSERT INTO edu_access.`03-silver`.psa_psgc_clean VALUES (?, ?, ?, ?, ?, ?, ?, '2026-Q2', TRUE, 'P1', ?)", [*row, i])
        self.store.sql("CREATE TABLE edu_access.`03-silver`.deped_enrollment_clean (school_year STRING, school_id STRING, school_name STRING, "
                       "region STRING, province STRING, municipality STRING, barangay STRING, barangay_possibly_truncated BOOLEAN, "
                       "is_overseas BOOLEAN, batch_id STRING, source_sha256 STRING, source_row_number BIGINT)")
        for row in ENROLLMENT:
            self.store.sql("INSERT INTO edu_access.`03-silver`.deped_enrollment_clean VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", list(row))
        self.store.sql("CREATE TABLE edu_access.`03-silver`.deped_enrollment_psgc_clean (school_id STRING, psgc_city_municipality STRING, "
                       "psgc_barangay STRING, psgc_recoded BOOLEAN, batch_id STRING, source_row_number BIGINT)")
        for i, row in enumerate(CROSSWALK, 1):
            self.store.sql("INSERT INTO edu_access.`03-silver`.deped_enrollment_psgc_clean VALUES (?, ?, ?, ?, 'X1', ?)", [*row, i])
        spec = deped.build_spec(rules or MADE_UP_RULES)
        self.build, self.gate = tmp_path / "build.sql", tmp_path / "gate.sql"
        self.build.write_text(deped.build_sql(spec), encoding="utf-8")
        self.gate.write_text(deped.gate_sql(spec), encoding="utf-8")

    def run(self):
        run_id = str(uuid.uuid4())
        params = {"run_id": run_id, "code_revision": "c" * 40, "environment": "local"}
        try:
            self.store.run_file(self.build, params)
            self.store.run_file(self.gate, params)
        except Exception as error:
            return run_id, str(error)
        return run_id, None

    def rows(self, sql):
        return self.store.records(sql)

    def checks(self, run_id):
        return {r["check_name"]: r for r in self.rows(
            f"SELECT * FROM {CONTROL}.data_quality_results WHERE run_id = '{run_id}' AND layer = 'integration'")}


def test_every_school_year_gets_both_levels_and_no_row_is_dropped(tmp_path):
    env = Env(tmp_path)
    run_id, error = env.run()
    assert error is None
    assert env.rows(f"SELECT COUNT(*), COUNT(DISTINCT school_id) FROM {MAP}") == [{"count_star()": 10, "count(DISTINCT school_id)": 5}]
    checks = env.checks(run_id)
    assert not [c for c in checks.values() if c["status"] == "FAIL"]
    assert checks["rows_reconcile"]["actual"] == "10"


def test_code_name_fallback_ambiguity_override_and_overseas_are_explicit(tmp_path):
    env = Env(tmp_path)
    assert env.run()[1] is None
    got = {(r["school_id"], r["geographic_level"]):
           (r["psgc_code"], r["match_status"], r["match_method"], r["review_status"])
           for r in env.rows(f"SELECT * FROM {MAP}")}
    assert got[("100001", "city_mun")] == ("0102801000", "matched", "code", "rule")
    assert got[("100002", "city_mun")] == ("0102803000", "matched", "name_exact", "rule")
    assert got[("100003", "city_mun")] == (None, "ambiguous", None, "pending")
    assert got[("100004", "bgy")] == ("1381500002", "matched", "code_name_differs", "reviewed")
    assert got[("100005", "city_mun")] == (None, "excluded", None, "pending")
    assert got[("100005", "bgy")] == (None, "excluded", None, "pending")


def test_a_failed_gate_keeps_the_last_published_map(tmp_path):
    env = Env(tmp_path)
    assert env.run()[1] is None
    before = env.rows(f"SELECT school_id, geographic_level, psgc_code FROM {MAP} ORDER BY 1,2")
    run_id = str(uuid.uuid4())
    params = {"run_id": run_id, "code_revision": "d" * 40, "environment": "local"}
    env.store.run_file(env.build, params)
    env.store.sql(f"DELETE FROM {CANDIDATE} WHERE school_id = '100001' AND geographic_level = 'bgy'")
    with pytest.raises(Exception, match="Integration gate failed"):
        env.store.run_file(env.gate, params)
    assert env.checks(run_id)["rows_reconcile"]["status"] == "FAIL"
    assert env.rows(f"SELECT school_id, geographic_level, psgc_code FROM {MAP} ORDER BY 1,2") == before


def test_config_refuses_an_unreviewed_override():
    rules = copy.deepcopy(RULES)
    rules["overrides"][0]["reviewer"] = ""
    with pytest.raises(IngestionError, match="reviewer"):
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
