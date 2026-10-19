"""Gold dim_barangay (#174): its build and gate, run the way the job's two SQL tasks run them.

Made-up rows go straight into psa_psgc_clean in an in-memory DuckDB. No real PSGC row is used.
"""

import uuid

from factories.deped_deliveries import REPO_ROOT
from src.ingestion.store import DuckDBStore

CONTROL = "edu_access.`01-control`"
DIM = "edu_access.`05-gold`.dim_barangay"
BUILD = REPO_ROOT / "etl" / "05_gold" / "05_build_dim_barangay.sql"
GATE = REPO_ROOT / "etl" / "05_gold" / "90_validate_dim_barangay.sql"

# psgc_code, name, geographic_level, city_municipality_code, urban_rural
PSGC = [
    ("0102801000", "Town A", "Mun", None, None),
    ("0102801001", "Barangay A1", "Bgy", "0102801000", "R"),
    ("0102801002", "Barangay A2", "Bgy", "0102801000", None),     # PSGC '-'
    ("1380600000", "City of Manila", "City", None, None),
    ("1380601000", "Tondo I/II", "SubMun", None, None),
    ("1380601001", "Barangay 1", "Bgy", "1380601000", "U"),       # under a district
    ("1381701000", "Pateros", "Mun", None, None),                  # no barangay in this made-up set
]


class Env:
    def __init__(self, psgc=PSGC):
        self.store = DuckDBStore()
        for path in sorted((REPO_ROOT / "etl" / "01_control").glob("0[1-4]_*.sql")):
            self.store.run_file(path)
        self.store.sql("CREATE SCHEMA IF NOT EXISTS edu_access.`03-silver`")
        self.store.sql("CREATE TABLE edu_access.`03-silver`.psa_psgc_clean (psgc_code STRING, name STRING, "
                       "geographic_level STRING, city_municipality_code STRING, urban_rural STRING, "
                       "publication_period STRING, is_master_reference BOOLEAN, run_id STRING)")
        for row in psgc:
            self.store.sql("INSERT INTO edu_access.`03-silver`.psa_psgc_clean VALUES (?, ?, ?, ?, ?, '2026-Q2', TRUE, 'S1')", list(row))
        # a non-master quarter: never read
        self.store.sql("INSERT INTO edu_access.`03-silver`.psa_psgc_clean VALUES "
                       "('0102801099', 'Old Barangay', 'Bgy', '0102801000', 'R', '2025-Q4', FALSE, 'S0')")
        self.store.sql(f"INSERT INTO {CONTROL}.pipeline_runs (run_id, pipeline_name, source_id, environment, status, code_revision, "
                       "started_at_utc) VALUES ('S1', 'silver_build', 'psa_psgc', 'local', 'succeeded', 'c', TIMESTAMP '2026-10-19 00:00:00')")

    def run(self, build=True):
        run_id = str(uuid.uuid4())
        params = {"run_id": run_id, "code_revision": "c" * 40, "environment": "local"}
        try:
            if build:
                self.store.run_file(BUILD, params)
            self.store.run_file(GATE, params)
        except Exception as e:
            return run_id, str(e)
        return run_id, None

    def checks(self, run_id):
        return {r["check_name"]: r for r in self.store.records(
            f"SELECT * FROM {CONTROL}.data_quality_results WHERE run_id = '{run_id}' AND layer = 'gold'")}

    def dim(self):
        return {r["barangay_psgc_code"]: r for r in self.store.records(f"SELECT * FROM {DIM}")}


def test_builds_every_barangay_and_the_technical_members():
    env = Env()
    run_id, error = env.run()
    assert error is None
    dim = env.dim()
    assert sorted(dim) == ["0102801000-UNKNOWN", "0102801001", "0102801002", "1380600000-UNKNOWN", "1380601001",
                           "1381701000-UNKNOWN", "EXCLUDED", "UNKNOWN"]
    checks = env.checks(run_id)
    assert {c["status"] for c in checks.values()} == {"PASS", "WARN"}
    assert checks["regular_without_urban_rural"]["actual"] == "1"
    assert checks["rolled_up_from_district"]["actual"] == "1"


def test_columns_follow_the_data_model():
    env = Env()
    env.run()
    dim = env.dim()
    assert {k: (r["city_mun_psgc_code"], r["urban_rural"], r["member_type"]) for k, r in dim.items()} == {
        "0102801001": ("0102801000", "R", "regular"),
        "0102801002": ("0102801000", None, "regular"),
        "1380601001": ("1380600000", "U", "regular"),   # rolled up from the Tondo district to the City of Manila
        "0102801000-UNKNOWN": ("0102801000", None, "unknown"),
        "1380600000-UNKNOWN": ("1380600000", None, "unknown"),
        "1381701000-UNKNOWN": ("1381701000", None, "unknown"),
        "UNKNOWN": ("UNKNOWN", None, "unknown"),
        "EXCLUDED": ("EXCLUDED", None, "excluded"),
    }
    assert dim["1380600000-UNKNOWN"]["barangay_name"] == "Unknown barangay in City of Manila"


def test_rerun_gives_the_same_table():
    env = Env()
    env.run()
    first = env.dim()
    _, error = env.run()
    assert error is None
    assert env.dim() == first


def test_a_barangay_without_its_city_fails_and_keeps_the_last_good_build():
    env = Env()
    env.run()
    good = env.dim()
    env.store.sql("INSERT INTO edu_access.`03-silver`.psa_psgc_clean VALUES "
                  "('0102899001', 'Orphan', 'Bgy', '0102899000', 'R', '2026-Q2', TRUE, 'S1')")
    run_id, error = env.run()
    assert error and "Gold gate failed for dim_barangay" in error
    assert env.checks(run_id)["parent_is_city_or_municipality"]["status"] == "FAIL"
    assert env.dim() == good


def test_a_psgc_run_that_did_not_succeed_fails():
    env = Env()
    env.store.sql(f"UPDATE {CONTROL}.pipeline_runs SET status = 'running'")
    run_id, error = env.run()
    assert error
    assert env.checks(run_id)["upstream_run_psa_psgc_clean"]["status"] == "FAIL"


def test_a_barangay_moved_to_another_valid_city_fails():
    """The parent is a real city, so only the source reconciliation can catch the move."""
    env = Env()
    env.run()
    good = env.dim()
    env.store.sql("UPDATE edu_access.`05-gold`.dim_barangay_candidate SET city_mun_psgc_code = '1381701000' "
                  "WHERE barangay_psgc_code = '1380601001'")
    run_id, error = env.run(build=False)
    assert error
    checks = env.checks(run_id)
    assert checks["values_match_source"]["status"] == "FAIL"
    assert checks["parent_is_city_or_municipality"]["status"] == "PASS"
    assert env.dim() == good


def test_the_gate_summary_is_dropped_after_a_pass_and_a_fail():
    leftovers = "SELECT table_name FROM information_schema.tables WHERE table_name LIKE '%gate_summary_r_%'"
    env = Env()
    _, error = env.run()
    assert error is None and env.store.query(leftovers) == []
    env.store.sql("INSERT INTO edu_access.`03-silver`.psa_psgc_clean VALUES "
                  "('0102899001', 'Orphan', 'Bgy', '0102899000', 'R', '2026-Q2', TRUE, 'S1')")
    _, error = env.run()
    assert error and env.store.query(leftovers) == []
