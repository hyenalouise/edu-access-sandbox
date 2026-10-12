"""PSGC Silver: one row per code per quarter, typed and standardized, published only after its gate passes.

Every test loads made-up PSGC workbooks (tests/factories/psgc_workbooks.py) through
the real Bronze pipeline into an in-memory DuckDB, then runs the two generated
Silver SQL tasks (etl/03_silver/04_clean_psa_psgc.sql and
90_validate_psa_psgc_clean.sql) as the job would. No PSGC row or raw file is used.
"""

import copy
import json
import uuid
from dataclasses import dataclass

import pytest
import yaml

from factories.deped_deliveries import fake_repo, write_config
from factories.psgc_workbooks import UNITS, approve, default_rows, empty_config, make_workbook, real_config
from src.ingestion.errors import IngestionError
from src.ingestion.pipeline import IngestionRun
from src.ingestion.store import DuckDBStore
from src.silver import psa_psgc
from src.silver.generators import generator

SOURCE = "psa_psgc"
REPO_ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
REVISION = "d" * 40
CLEAN = "edu_access.`03-silver`.psa_psgc_clean"
QUARANTINE = "edu_access.`03-silver`.psa_psgc_quarantine"
CLEAN_CANDIDATE = "edu_access.`03-silver`.psa_psgc_clean_candidate"
QUARANTINE_CANDIDATE = "edu_access.`03-silver`.psa_psgc_quarantine_candidate"
CONTROL = "edu_access.`01-control`"
BUILD = "04_clean_psa_psgc.sql"
GATE = "90_validate_psa_psgc_clean.sql"
CONTENT = ("SELECT * EXCLUDE (run_id, cleaned_at_utc, code_revision) FROM {} "
           "ORDER BY publication_period, source_sha256, source_row_number")


@dataclass
class SilverResult:
    run_id: str
    status: str            # succeeded | failed
    error: str = None


class Env:
    def __init__(self, tmp_path):
        self.config = empty_config()
        self.landing = tmp_path / "landing"
        self.inbox = self.landing / "psa"
        self.repo = fake_repo(tmp_path / "repo", self.config)
        self.store = DuckDBStore()

    def deliver(self, period="2026-Q2", rows=None, folder="original", **approve_kwargs):
        rows = default_rows() if rows is None else rows
        path = make_workbook(self.inbox / folder, period, rows=rows)
        approve(self.config, path, period, row_count=len(rows), **approve_kwargs)
        write_config(self.repo, self.config)
        return path

    def bronze(self):
        summary = IngestionRun(self.store, self.repo, SOURCE, self.landing, "local", REVISION).execute()
        assert summary.status == "succeeded", summary
        return summary

    def silver(self, run_id=None):
        """The job's two Silver SQL tasks: the build, then the gate."""
        run_id = run_id or str(uuid.uuid4())
        params = {"run_id": run_id, "code_revision": REVISION, "environment": "local"}
        folder = self.repo / "etl" / "03_silver"
        try:
            self.store.run_file(folder / BUILD, params)
            self.store.run_file(folder / GATE, params)
        except Exception as e:
            return SilverResult(run_id, "failed", str(e))
        return SilverResult(run_id, "succeeded")

    def q(self, sql):
        return self.store.query(sql)

    def one(self, sql):
        return self.q(sql)[0][0]

    def rows(self, sql):
        return self.store.records(sql)

    def row(self, code, table=CLEAN):
        found = self.rows(f"SELECT * FROM {table} WHERE psgc_code = '{code}'")
        assert len(found) == 1, found
        return found[0]

    def checks(self, run_id, status=None):
        where = f" AND status = '{status}'" if status else ""
        return {r["check_name"]: r for r in self.rows(
            f"SELECT * FROM {CONTROL}.data_quality_results WHERE run_id = '{run_id}' AND source_id = '{SOURCE}' "
            f"AND layer = 'silver'{where}")}

    def silver_run(self, run_id):
        return self.rows(f"SELECT * FROM {CONTROL}.pipeline_runs WHERE run_id = '{run_id}' "
                         f"AND pipeline_name = 'silver_build' AND source_id = '{SOURCE}'")[0]

    def exists(self, table):
        name = table.split(".")[-1]
        return self.one(f"SELECT COUNT(*) FROM duckdb_tables() WHERE schema_name = '03-silver' AND table_name = '{name}'") == 1


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def many_barangays(n, changes=None):
    """The made-up units plus n barangays under the made-up municipality; changes = {index: {column index: value}}."""
    rows = default_rows()
    for i in range(n):
        row = [f"0000101{100 + i:03d}", f"Barangay {i}", f"000101{100 + i:03d}", "Bgy", "", "", "", "R", 10 + i, "", ""]
        for column, value in (changes or {}).get(i, {}).items():
            row[column] = value
        rows.append(row)
    return rows


# --- The generator and the committed files -------------------------------------------------

def test_the_psgc_generator_is_chosen_by_its_rules_file():
    assert generator(SOURCE, REPO_ROOT) is psa_psgc


def test_committed_psgc_files_match_the_generator(repo_root):
    spec = psa_psgc.load_spec(repo_root)
    for path, text in ((f"etl/03_silver/{BUILD}", psa_psgc.build_sql(spec)), (f"etl/03_silver/{GATE}", psa_psgc.gate_sql(spec)),
                       ("docs/data/silver/psa-psgc-clean.md", psa_psgc.dictionary_markdown(spec))):
        assert (repo_root / path).read_text(encoding="utf-8") == text, f"Regenerate {path} (src/silver/cli.py)"


def test_every_gate_check_is_written_by_the_gate_sql():
    spec = psa_psgc.load_spec(REPO_ROOT)
    gate = psa_psgc.gate_sql(spec)
    for name, _, _ in psa_psgc.gate_checks(spec):
        assert f"'{name}' AS check_name" in gate, name
    assert gate.count(" AS check_name") == len(psa_psgc.gate_checks(spec))


def test_the_build_never_publishes_and_the_gate_publishes_clean_last():
    spec = psa_psgc.load_spec(REPO_ROOT)
    build, gate = psa_psgc.build_sql(spec), psa_psgc.gate_sql(spec)
    for table in (spec.clean_table, spec.quarantine_table):
        assert f"CREATE OR REPLACE TABLE edu_access.`03-silver`.{table} USING" not in build
    order = [gate.index(m) for m in ("WHEN MATCHED AND s.fails > 0 THEN UPDATE SET", "raise_error(",
                                      f"CREATE OR REPLACE TABLE edu_access.`03-silver`.{spec.quarantine_table} USING",
                                      f"CREATE OR REPLACE TABLE edu_access.`03-silver`.{spec.clean_table} USING",
                                      "status = 'succeeded'")]
    assert order == sorted(order)


def test_the_real_rules_describe_every_bronze_column_and_take_the_master_from_the_contract():
    spec = psa_psgc.load_spec(REPO_ROOT)
    assert spec.master_period == real_config()["master_reference_period"] == "2026-Q2"
    assert spec.text_columns == {"name": "name", "old_names": "old_names", "column_j_footnote": "population_footnote"}


# --- A clean delivery ----------------------------------------------------------------------

def test_a_clean_delivery_passes_every_check_and_is_published(env):
    env.deliver()
    env.bronze()
    result = env.silver()
    assert result.status == "succeeded", result.error
    checks = env.checks(result.run_id)
    assert {c["status"] for c in checks.values()} == {"PASS"}, {n: c["status"] for n, c in checks.items() if c["status"] != "PASS"}
    assert checks["rows_reconcile"]["actual"] == str(len(UNITS))
    assert env.one(f"SELECT COUNT(*) FROM {CLEAN}") == len(UNITS)
    assert env.one(f"SELECT COUNT(*) FROM {QUARANTINE}") == 0
    run = env.silver_run(result.run_id)
    assert (run["status"], run["job_run_id"]) == ("succeeded", result.run_id)
    assert env.one(f"SELECT COUNT(DISTINCT run_id) FROM {CLEAN}") == 1


def test_codes_keep_their_zeros_and_names_are_trimmed_not_rewritten(env):
    env.deliver()
    env.bronze()
    env.silver()
    assert env.row("0000000000")["psgc_code"] == "0000000000"
    assert env.row("0000101002")["name"] == "Poblacion Test"          # trailing space removed
    assert env.row("0000101001")["name"] == "Doña Prueba"             # Unicode kept
    assert env.row("2000102001")["name"] == "Ñañong Test"
    assert env.row("2000000000")["psgc_code"] == "2000000000"         # stored as a number in the workbook
    assert env.row("0000101002")["correspondence_code"] is None       # blank stays NULL, never derived
    assert env.row("0000101001")["correspondence_code"] == "000101001"
    assert env.row("0000101000")["old_names"] == "Luma"


def test_population_markers_zeros_and_footnotes(env):
    env.deliver()
    env.bronze()
    env.silver()
    na = env.row("2099900000")
    assert (na["population"], na["population_null_reason"]) == (None, "publisher_na")
    zero = env.row("2000102001")
    assert (zero["population"], zero["population_null_reason"], zero["population_is_zero"]) == (0, None, True)
    assert env.row("0000101001")["population"] == 400
    province = env.row("0000100000")
    assert (province["population_footnote"], province["has_population_footnote"]) == ("(excluding CITY OF PAGSUBOK)", True)
    assert env.row("0000000000")["population_footnote"] == "1/"


def test_the_income_class_is_split_and_a_dash_is_not_classified(env):
    env.deliver()
    env.bronze()
    env.silver()
    starred = env.row("0000101000")
    assert (starred["income_class"], starred["income_class_retained_after_downgrade"]) == ("2nd", True)
    plain = env.row("0000100000")
    assert (plain["income_class"], plain["income_class_retained_after_downgrade"]) == ("1st", False)
    dash = env.row("2000102000")
    assert (dash["income_class"], dash["income_class_retained_after_downgrade"], dash["income_class_null_reason"]) == (
        None, None, "not_classified")
    barangay = env.row("0000101001")
    assert (barangay["income_class"], barangay["income_class_null_reason"]) == (None, None)


def test_urban_rural_dash_is_unknown_never_rural(env):
    env.deliver()
    env.bronze()
    env.silver()
    dash = env.row("0000101002")
    assert (dash["urban_rural"], dash["urban_rural_null_reason"]) == (None, "unknown")
    assert env.row("0000101001")["urban_rural"] == "R"
    assert env.row("2000102001")["urban_rural"] == "U"
    assert (env.row("0000100000")["urban_rural"], env.row("0000100000")["urban_rural_null_reason"]) == (None, None)


def test_a_blank_level_stays_null_flagged_and_holds_the_units_below_it(env):
    env.deliver()
    env.bronze()
    env.silver()
    container = env.row("2099900000")
    assert (container["geographic_level"], container["level_blank"], container["province_code"]) == (None, True, "2099900000")
    assert env.one(f"SELECT COUNT_IF(level_blank) FROM {CLEAN}") == 1


def test_parent_codes_come_from_the_code_and_exist(env):
    env.deliver()
    env.bronze()
    env.silver()
    barangay = env.row("0000101001")
    assert (barangay["region_code"], barangay["province_code"], barangay["city_municipality_code"]) == (
        "0000000000", "0000100000", "0000101000")
    city = env.row("2000102000")                 # no province row above it, like an HUC
    assert (city["region_code"], city["province_code"], city["city_municipality_code"]) == ("2000000000", None, None)
    assert env.row("2000102001")["city_municipality_code"] == "2000102000"
    region = env.row("0000000000")
    assert (region["region_code"], region["province_code"]) == ("0000000000", None)


def test_every_current_quarter_is_kept_and_only_the_master_is_flagged(env):
    env.deliver("2026-Q2")
    env.deliver("2026-Q3")
    env.bronze()
    result = env.silver()
    assert result.status == "succeeded", result.error
    by_period = dict(env.q(f"SELECT publication_period, COUNT(*) FROM {CLEAN} GROUP BY 1"))
    assert by_period == {"2026-Q2": len(UNITS), "2026-Q3": len(UNITS)}
    assert dict(env.q(f"SELECT publication_period, BOOL_AND(is_master_reference) FROM {CLEAN} GROUP BY 1")) == {
        "2026-Q2": True, "2026-Q3": False}
    assert env.one(f"SELECT COUNT(*) FROM {CLEAN} WHERE psgc_code = '0000101001'") == 2   # one per quarter


def test_a_reissued_quarter_replaces_its_rows_and_the_first_version_stays_in_bronze(env):
    first = env.deliver("2026-Q2")
    env.bronze()
    assert env.silver().status == "succeeded"
    rows = default_rows()
    rows[3][1] = "Doña Prueba Bago"
    sha = env.config["deliveries"][0]["workbook_sha256"]
    env.deliver("2026-Q2", rows=rows, folder="2026-11-01", delivery_version=2, supersedes=sha)
    env.bronze()
    result = env.silver()
    assert result.status == "succeeded", result.error
    assert env.row("0000101001")["name"] == "Doña Prueba Bago"
    assert env.one(f"SELECT COUNT(DISTINCT delivery_version) FROM {CLEAN}") == 1
    assert env.one(f"SELECT COUNT(*) FROM {CLEAN}") == len(UNITS)
    assert env.one("SELECT COUNT(*) FROM edu_access.`02-bronze`.psa_psgc_raw") == 2 * len(UNITS)
    assert first.exists()


def test_repeated_rebuilds_give_identical_content(env):
    env.deliver()
    env.bronze()
    contents = []
    for _ in range(2):
        assert env.silver().status == "succeeded"
        contents.append(env.q(CONTENT.format(CLEAN)))
    assert contents[0] == contents[1]


# --- What the gate refuses ------------------------------------------------------------------

def test_an_unmapped_label_fails_the_gate_and_nothing_is_published(env):
    rows = default_rows()
    rows[3][3] = "Dist"                         # a level the reviewed mapping does not list
    env.deliver(rows=rows)
    env.bronze()
    result = env.silver()
    assert result.status == "failed" and "Silver gate failed" in result.error
    failed = env.checks(result.run_id, "FAIL")
    assert set(failed) == {"labels_mapped_geographic_level"}, set(failed)
    assert failed["labels_mapped_geographic_level"]["actual"] == "1"
    assert not env.exists(CLEAN)
    assert env.silver_run(result.run_id)["status"] == "failed"


def test_a_duplicated_code_is_quarantined_everywhere_and_fails_the_gate(env):
    """D-019: PSGC is what Integration joins to, so a repeated code stops Silver even below 1%."""
    rows = many_barangays(300)
    rows.append(copy.deepcopy(rows[3]))
    env.deliver(rows=rows)
    env.bronze()
    result = env.silver()
    assert result.status == "failed"
    failed = env.checks(result.run_id, "FAIL")
    assert set(failed) == {"psgc_code_duplicates_absent"}, set(failed)
    reasons = env.q(f"SELECT psgc_code, quarantine_reasons FROM {QUARANTINE_CANDIDATE}")
    assert reasons == [("0000101001", ["psgc_code_duplicated"])] * 2
    assert env.checks(result.run_id)["quarantine_rate"]["status"] == "WARN"
    assert not env.exists(CLEAN)


def test_a_missing_province_row_fails_the_gate(env):
    """Cath's review of #124: without its province row, a municipality looks like an HUC or Pateros. Only an HUC
    (city_class) or a listed exception may have no province_code, so this must FAIL, not pass silently."""
    rows = [r for r in default_rows() if r[0] != "0000100000"]       # drop the made-up province
    env.deliver(rows=rows)
    env.bronze()
    result = env.silver()
    assert result.status == "failed"
    failed = env.checks(result.run_id, "FAIL")
    assert set(failed) == {"province_code_missing_only_where_listed"}, set(failed)
    assert failed["province_code_missing_only_where_listed"]["actual"] == "1"
    assert not env.exists(CLEAN)


def test_an_hucs_missing_province_is_expected(env):
    env.deliver()                                                    # 2000102000 is an HUC with no province row
    env.bronze()
    result = env.silver()
    assert result.status == "succeeded", result.error
    assert env.checks(result.run_id)["province_code_missing_only_where_listed"]["actual"] == "0"
    assert env.row("2000102000")["province_code"] is None


def test_a_blank_population_is_null_with_its_reason_and_counted(env):
    rows = default_rows()
    rows[4][8] = ""                                                  # a blank population cell
    env.deliver(rows=rows)
    env.bronze()
    result = env.silver()
    assert result.status == "succeeded", result.error
    blank = env.row("0000101002")
    assert (blank["population"], blank["population_null_reason"], blank["population_is_zero"]) == (None, "blank", False)
    assert env.checks(result.run_id)["rule_population_blank_to_null"]["actual"] == "1"
    assert env.row("2099900000")["population_null_reason"] == "publisher_na"


def test_rows_point_to_themselves_as_their_own_region_and_province(env):
    env.deliver()
    env.bronze()
    env.silver()
    assert env.row("0000000000")["region_code"] == "0000000000"
    assert env.row("0000100000")["province_code"] == "0000100000"


def test_a_malformed_correspondence_code_is_quarantined_with_a_warning(env):
    env.deliver(rows=many_barangays(150, {0: {2: "12345"}}))
    env.bronze()
    result = env.silver()
    assert result.status == "succeeded", result.error
    checks = env.checks(result.run_id)
    assert (checks["quarantine_rate"]["status"], checks["quarantine_rate"]["actual"]) == ("WARN", "1")
    assert checks["quarantine_reason_correspondence_code_malformed"]["status"] == "WARN"
    assert env.q(f"SELECT psgc_code, quarantine_reasons FROM {QUARANTINE}") == [("0000101100", ["correspondence_code_malformed"])]
    assert env.one(f"SELECT COUNT(*) FROM {CLEAN}") == len(UNITS) + 149


def test_quarantine_above_one_percent_fails_and_nothing_is_published(env):
    env.deliver(rows=many_barangays(20, {i: {2: "12345"} for i in range(5)}))
    env.bronze()
    result = env.silver()
    assert result.status == "failed"
    assert set(env.checks(result.run_id, "FAIL")) == {"quarantine_rate"}
    assert not env.exists(CLEAN)


def test_a_failed_build_never_replaces_the_last_good_one(env):
    env.deliver()
    env.bronze()
    good = env.silver()
    assert good.status == "succeeded"
    before = env.q(CONTENT.format(CLEAN))
    rows = default_rows()
    rows[3][7] = "Rural"                        # an urban/rural label the mapping does not list
    env.deliver("2026-Q3", rows=rows)
    env.bronze()
    bad = env.silver()
    assert bad.status == "failed"
    assert env.q(CONTENT.format(CLEAN)) == before
    assert env.one(f"SELECT MIN(run_id) FROM {CLEAN}") == good.run_id
    assert env.one(f"SELECT COUNT(DISTINCT publication_period) FROM {CLEAN_CANDIDATE}") == 2   # kept for review


def test_no_current_batch_fails_the_gate(env):
    env.deliver()
    env.bronze()
    env.store.sql(f"UPDATE {CONTROL}.ingestion_batches SET status = 'failed'")
    result = env.silver()
    assert result.status == "failed"
    failed = env.checks(result.run_id, "FAIL")
    assert {"current_batches_present", "master_reference_current"} <= set(failed)


def test_check_results_hold_counts_not_values(env):
    env.deliver()
    env.bronze()
    result = env.silver()
    text = " ".join(f"{c['expected']} {c['actual']}" for c in env.checks(result.run_id).values())
    for value in ("Doña", "Rehiyon", "0000101001", "#N/A", "Luma"):
        assert value not in text


# --- The rules file --------------------------------------------------------------------------

def _spec(mapping=None, contract=None):
    registry = yaml.safe_load((REPO_ROOT / "config" / "tables.yml").read_text(encoding="utf-8"))
    entry = next(s for s in registry["source_tables"] if s["source_id"] == SOURCE)
    mapping = mapping or json.loads((REPO_ROOT / "config" / "mappings" / f"{SOURCE}.json").read_text(encoding="utf-8"))
    return psa_psgc.build_spec(mapping, contract or real_config(), entry)


def _mapping():
    return json.loads((REPO_ROOT / "config" / "mappings" / f"{SOURCE}.json").read_text(encoding="utf-8"))


def test_a_new_publisher_column_needs_a_reviewed_rule():
    contract = real_config()
    contract["schema_versions"]["v2"] = copy.deepcopy(contract["schema_versions"]["v1"])
    contract["schema_versions"]["v2"]["columns"].append("barangay_type")
    with pytest.raises(IngestionError) as e:
        _spec(contract=contract)
    assert "barangay_type" in e.value.message


@pytest.mark.parametrize("break_it, message", [
    (lambda m: m["categories"]["urban_rural"]["labels"][0].update(null_reason="unknown"), "not both or neither"),
    (lambda m: m["categories"]["status"]["labels"].append({"published": "Capital ", "standard": "Capital"}), "same after whitespace"),
    (lambda m: m["categories"]["status"]["labels"].append({"published": "O'Brien", "standard": "x"}), "quotes"),
    (lambda m: m["quarantine"].update(fail_above_percent=100), "fail_above_percent"),
    (lambda m: m["hierarchy"]["levels"].update(province="Province"), "hierarchy.levels"),
    (lambda m: m["hierarchy"].update(no_province_city_class="Metro"), "no_province_city_class"),
    (lambda m: m["hierarchy"]["no_province_exceptions"].append({"code": "13817", "name": "x"}), "no_province_exceptions"),
    (lambda m: m.update(silver_table="psgc_clean"), "config/tables.yml"),
    (lambda m: m["categories"].pop("status"), "no Silver rule"),
])
def test_the_rules_file_refuses_ambiguous_rules(break_it, message):
    mapping = _mapping()
    break_it(mapping)
    with pytest.raises(IngestionError) as e:
        _spec(mapping=mapping)
    assert message in e.value.message, e.value.message
