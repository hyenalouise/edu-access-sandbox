"""Silver for hdx_boundaries (COD-AB ADM3): typing, quarantine, geometry checks, the gate, and the run record.

Made-up GeoJSON files go through the real Bronze pipeline into an in-memory DuckDB,
then through the committed Silver SQL files, run the way the job's two SQL tasks
run them: the build, then the gate, with the job parameters bound. No real
COD-AB feature is used. The geometry checks use DuckDB's spatial extension,
which src/ingestion/store.py loads the first time a statement needs it.
"""

import copy
import decimal
import json
import uuid

import pytest
import yaml

from factories.deped_deliveries import REPO_ROOT, empty_config, fake_repo, write_config
from factories.hdx_geojson import SQUARE, approve, columns, pcodes, silver_feature, write_features
from src.ingestion.errors import IngestionError
from src.ingestion.pipeline import IngestionRun
from src.ingestion.store import DuckDBStore
from src.silver import hdx_boundaries as hdx

SOURCE = "hdx_boundaries"
REVISION = "c" * 40
CONTROL = "edu_access.`01-control`"
CLEAN = "edu_access.`03-silver`.hdx_adm3_clean"
QUARANTINE = "edu_access.`03-silver`.hdx_adm3_quarantine"
CLEAN_CANDIDATE = "edu_access.`03-silver`.hdx_adm3_clean_candidate"
BUILD = "06_clean_hdx_adm3.sql"
GATE = "90_validate_hdx_adm3_clean.sql"

BOWTIE = ('{"type": "Polygon", "coordinates": '
          '[[[120.5, 14.0], [120.6, 14.1], [120.6, 14.0], [120.5, 14.1], [120.5, 14.0]]]}')
feature = silver_feature


class Env:
    def __init__(self, tmp_path):
        self.config = empty_config(SOURCE)
        self.landing = tmp_path / "landing"
        self.inbox = self.landing / "admin_boundaries"
        self.repo = fake_repo(tmp_path / "repo", self.config)
        self.store = DuckDBStore()

    def deliver(self, features):
        path = write_features(self.inbox, features)
        approve(self.config, path, len(features))
        write_config(self.repo, self.config)
        summary = IngestionRun(self.store, self.repo, SOURCE, self.landing, "local", REVISION).execute()
        assert summary.status == "succeeded", summary
        return summary

    def silver(self, run_id=None):
        """The job's two Silver SQL tasks: the build, then the gate. Returns (run_id, error or None)."""
        run_id = run_id or str(uuid.uuid4())
        params = {"run_id": run_id, "code_revision": REVISION, "environment": "local"}
        folder = self.repo / "etl" / "03_silver"
        try:
            self.store.run_file(folder / BUILD, params)
            self.store.run_file(folder / GATE, params)
        except Exception as e:  # the gate stops the task on any FAIL
            return run_id, str(e)
        return run_id, None

    def q(self, sql):
        return self.store.query(sql)

    def one(self, sql):
        return self.q(sql)[0][0]

    def rows(self, sql):
        return self.store.records(sql)

    def checks(self, run_id):
        return {r["check_name"]: r for r in self.rows(
            f"SELECT * FROM {CONTROL}.data_quality_results WHERE run_id = '{run_id}' AND source_id = '{SOURCE}' "
            "AND layer = 'silver'")}

    def run_status(self, run_id):
        return self.one(f"SELECT status FROM {CONTROL}.pipeline_runs WHERE run_id = '{run_id}' "
                        f"AND pipeline_name = 'silver_build' AND source_id = '{SOURCE}'")


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def good(n, start=1):
    return [feature(i) for i in range(start, start + n)]


# --- A clean delivery --------------------------------------------------------------------

def test_every_feature_is_typed_and_the_gate_publishes(env):
    env.deliver(good(3))
    run_id, error = env.silver()
    assert error is None
    assert env.run_status(run_id) == "succeeded"
    checks = env.checks(run_id)
    assert not [n for n, c in checks.items() if c["status"] != "PASS"], checks
    assert {n for n, _, _ in hdx.gate_checks(hdx.load_spec(env.repo))} == set(checks)
    assert env.one(f"SELECT COUNT(*) FROM {CLEAN}") == 3
    assert env.one(f"SELECT COUNT(*) FROM {QUARANTINE}") == 0

    row = env.rows(f"SELECT * FROM {CLEAN} WHERE adm3_pcode = '{pcodes(1)[0]}'")[0]
    assert row["area_sqkm"] == decimal.Decimal("112.24600000000012")   # every published digit
    assert row["center_lat"] == decimal.Decimal("14.05")
    assert str(row["valid_on"]) == "2025-02-13" and row["valid_to"] is None
    assert row["geometry"] == SQUARE                                     # the published text
    assert row["adm1_name"] == "Region I (Ilocos Region)" and row["adm3_name1"] is None
    assert (row["hierarchy_consistent"], row["geometry_is_valid"], row["center_inside_geometry"]) == (True, True, True)


def test_a_rerun_builds_the_same_rows(env):
    env.deliver(good(3))
    content = "SELECT * EXCLUDE (run_id, cleaned_at_utc, code_revision) FROM {} ORDER BY source_row_number"
    assert env.silver()[1] is None
    first = env.q(content.format(CLEAN))
    assert env.silver()[1] is None
    assert env.q(content.format(CLEAN)) == first


def test_text_is_trimmed_and_labels_with_extra_spaces_still_map(env):
    env.deliver(good(150) + [feature(151, adm3_name='"  Town   151 "', adm1_name='" Region I  (Ilocos Region) "')])
    run_id, error = env.silver()
    assert error is None
    row = env.rows(f"SELECT adm3_name, adm1_name FROM {CLEAN} WHERE adm3_pcode = '{pcodes(151)[0]}'")[0]
    assert row == {"adm3_name": "Town 151", "adm1_name": "Region I (Ilocos Region)"}
    assert env.checks(run_id)["rule_whitespace_normalized"]["actual"] == "1"


# --- Flags: kept, never repaired ---------------------------------------------------------

def test_invalid_shapes_far_centres_and_broken_chains_are_flagged_not_dropped(env):
    env.deliver(good(150) + [
        feature(151, geometry=BOWTIE),
        feature(152, center_lon="121.9"),
        feature(153, adm2_pcode='"PH01099"'),
    ])
    run_id, error = env.silver()
    assert error is None
    assert env.one(f"SELECT COUNT(*) FROM {CLEAN}") == 153
    flags = {r["adm3_pcode"]: r for r in env.rows(
        f"SELECT adm3_pcode, geometry, hierarchy_consistent, geometry_is_valid, center_inside_geometry FROM {CLEAN} "
        "WHERE NOT (hierarchy_consistent AND geometry_is_valid AND center_inside_geometry)")}
    assert flags[pcodes(151)[0]]["geometry_is_valid"] is False
    assert flags[pcodes(151)[0]]["geometry"] == BOWTIE                       # never repaired
    assert flags[pcodes(152)[0]]["center_inside_geometry"] is False
    assert flags[pcodes(153)[0]]["hierarchy_consistent"] is False
    checks = env.checks(run_id)
    assert {n: checks[n]["status"] for n in ("geometry_valid", "center_inside_geometry", "hierarchy_consistent")} == {
        "geometry_valid": "WARN", "center_inside_geometry": "WARN", "hierarchy_consistent": "WARN"}


# --- Quarantine ------------------------------------------------------------------------------

BAD = {
    "adm3_pcode_malformed": dict(adm3_pcode='"PH12"'),
    "valid_to_uncastable": dict(valid_to='"2025-13-01"'),
    "area_uncastable": dict(area_sqkm="1.123456789012345"),      # 15 decimals would be rounded
    "area_not_positive": dict(area_sqkm="0"),
    "center_uncastable": dict(center_lat='"n/a"'),
}


@pytest.mark.parametrize("reason", sorted(BAD))
def test_a_value_that_cannot_be_typed_exactly_is_quarantined(env, reason):
    env.deliver(good(150) + [feature(151, **BAD[reason])])
    run_id, error = env.silver()
    assert error is None                                                  # 1 of 151 is under 1%: WARN
    assert env.rows(f"SELECT quarantine_reasons FROM {QUARANTINE}") == [{"quarantine_reasons": [reason]}]
    checks = env.checks(run_id)
    assert checks[f"quarantine_reason_{reason}"]["status"] == "WARN"
    assert checks["rows_reconcile"]["status"] == "PASS"


def test_a_blank_area_stays_null_and_the_row_is_kept(env):
    env.deliver(good(2) + [feature(3, area_sqkm="null")])                 # Bronze does not require an area
    run_id, error = env.silver()
    assert error is None
    assert env.one(f"SELECT COUNT(*) FROM {CLEAN} WHERE area_sqkm IS NULL") == 1
    assert env.one(f"SELECT COUNT(*) FROM {QUARANTINE}") == 0
    assert env.checks(run_id)["area_positive"]["status"] == "PASS"     # the gate agrees with the build


@pytest.mark.parametrize("geometry, reason", [
    ('{"type": "Point", "coordinates": [120.55, 14.05]}', "geometry_wrong_type"),
    ('{"type": "Polygon", "coordinates": "not coordinates"}', "geometry_unparseable"),
])
def test_a_shape_that_is_not_a_polygon_is_quarantined(env, geometry, reason):
    env.deliver(good(150) + [feature(151, geometry=geometry)])
    run_id, error = env.silver()
    assert error is None
    assert env.rows(f"SELECT quarantine_reasons FROM {QUARANTINE}") == [{"quarantine_reasons": [reason]}]


def test_a_repeated_pcode_quarantines_every_copy(env):
    env.deliver(good(250) + [feature(1)])                                 # 2 of 251: under 1%
    run_id, error = env.silver()
    assert error is None
    assert env.one(f"SELECT COUNT(*) FROM {QUARANTINE} WHERE array_contains(quarantine_reasons, 'adm3_pcode_duplicated')") == 2
    assert env.checks(run_id)["adm3_pcode_unique"]["status"] == "PASS"


# --- The gate stops a bad build -----------------------------------------------------------------

def test_too_many_quarantined_rows_fail_the_gate_and_nothing_is_published(env):
    env.deliver(good(2) + [feature(3, area_sqkm='"x"')])                  # 1 of 3 is over 1%
    run_id, error = env.silver()
    assert error and "Silver gate failed" in error
    assert env.checks(run_id)["quarantine_rate"]["status"] == "FAIL"
    assert env.run_status(run_id) == "failed"
    assert env.one(f"SELECT COUNT(*) FROM {CLEAN_CANDIDATE}") == 2          # built, checked,
    published = env.one("SELECT COUNT(*) FROM information_schema.tables "
                        "WHERE table_schema = '03-silver' AND table_name = 'hdx_adm3_clean'")
    assert published == 0                                                  # and never published


def test_an_unmapped_label_fails_the_gate(env):
    env.deliver(good(3) + [feature(4, adm1_name='"Negros Island Region (NIR)"')])
    run_id, error = env.silver()
    assert error and "Silver gate failed" in error
    assert env.checks(run_id)["labels_mapped_adm1_name"]["status"] == "FAIL"


# --- The rules file -----------------------------------------------------------------------------

def _spec(mapping=None, contract=None):
    registry = yaml.safe_load((REPO_ROOT / "config" / "tables.yml").read_text(encoding="utf-8"))
    entry = next(s for s in registry["source_tables"] if s["source_id"] == SOURCE)
    mapping = mapping or json.loads((REPO_ROOT / "config" / "mappings" / f"{SOURCE}.json").read_text(encoding="utf-8"))
    return hdx.build_spec(mapping, contract or empty_config(SOURCE), entry)


def test_every_published_column_is_classified_once():
    spec = _spec()
    assert [c for c, _ in spec.columns] == columns()
    assert dict(spec.columns)["geometry"] == "geometry"
    assert spec.silver_type("area_sqkm") == "decimal(20,14)"


def test_a_new_publisher_column_needs_a_reviewed_rule():
    contract = empty_config(SOURCE)
    contract["schema_versions"]["v1"]["columns"].insert(-1, "adm3_alt_name")
    with pytest.raises(IngestionError, match="adm3_alt_name"):
        _spec(contract=contract)


@pytest.mark.parametrize("break_it, message", [
    (lambda m: m["categories"]["version"]["labels"].append({"published": "v04", "standard": "v04", "evidence": ""}),
     "not in the standard set"),
    (lambda m: m["categories"]["lang"]["labels"].append({"published": "en", "standard": "en", "evidence": ""}),
     "listed twice"),
    (lambda m: m["free_text_columns"].append("adm2_pcode"), "classified twice"),
    (lambda m: m["decimal_columns"]["columns"]["area_sqkm"].update(type="DOUBLE"), "DECIMAL"),
])
def test_a_broken_rules_file_is_refused(break_it, message):
    mapping = json.loads((REPO_ROOT / "config" / "mappings" / f"{SOURCE}.json").read_text(encoding="utf-8"))
    mapping = copy.deepcopy(mapping)
    break_it(mapping)
    with pytest.raises(IngestionError, match=message):
        _spec(mapping=mapping)


@pytest.mark.parametrize("kind, path, function", [
    ("sql", "etl/03_silver/{clean_file}", hdx.build_sql),
    ("gate", "etl/03_silver/90_validate_{table}.sql", hdx.gate_sql),
    ("dictionary", "docs/data/silver/{doc}.md", hdx.dictionary_markdown),
])
def test_committed_files_match_the_generator(kind, path, function):
    spec = hdx.load_spec(REPO_ROOT)
    target = REPO_ROOT / path.format(table=spec.clean_table, clean_file=spec.clean_file,
                                     doc=spec.clean_table.replace("_", "-"))
    assert target.read_text(encoding="utf-8") == function(spec), (
        f"Regenerate: python -m src.silver.cli {kind} --source {SOURCE} > {target.relative_to(REPO_ROOT)}")
