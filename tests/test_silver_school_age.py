"""Silver for psa_school_age_population: one row per cell, levels and parents from the sums, the gate.

Made-up census workbooks (tests/factories/census_workbooks.py, the TREE workbooks) go
through the real Bronze pipeline into an in-memory DuckDB, then through the Silver SQL
generated from the real rules with the made-up workbooks' level counts pinned, run the
way the job's two SQL tasks run them: the build, then the gate, with the job parameters
bound. No real PSA row is used.

The tree has 14 places: the country; a region with a province of three towns (a
capital, an old name in brackets in 2020, a repeated name) and a city directly under
it; a region of cities only; and a region with a single province (so the region equals
it). 2020 is the wide layout, 2024 the long one with footnote markers.
"""

import copy
import json
import uuid
from dataclasses import dataclass

import pytest
import yaml

from factories.census_workbooks import (
    REPO_ROOT, SOURCE, TREE, TREE_LEVELS, approve_tree, empty_config, fake_repo, pin_tree_levels, real_config,
    tree_labels, tree_values, write_config, write_tree_workbook,
)
from src.ingestion.errors import IngestionError
from src.ingestion.pipeline import IngestionRun
from src.ingestion.store import DuckDBStore
from src.silver import psa_school_age_population as sap
from src.silver.generators import generator

REVISION = "f" * 40
YEARS = ("2020", "2024")
CONCEPTS = ("total", "household")
BRONZE = "edu_access.`02-bronze`.psa_school_age_population_raw"
CLEAN = "edu_access.`03-silver`.psa_school_age_population_clean"
QUARANTINE = "edu_access.`03-silver`.psa_school_age_population_quarantine"
CLEAN_CANDIDATE = "edu_access.`03-silver`.psa_school_age_population_clean_candidate"
QUARANTINE_CANDIDATE = "edu_access.`03-silver`.psa_school_age_population_quarantine_candidate"
CONTROL = "edu_access.`01-control`"
BUILD = "08_clean_psa_school_age_population.sql"
GATE = "90_validate_psa_school_age_population_clean.sql"
MAPPING = REPO_ROOT / "config" / "mappings" / f"{SOURCE}.json"
CONTENT = ("SELECT * EXCLUDE (run_id, cleaned_at_utc, code_revision) FROM {} "
           "ORDER BY census_year, source_sheet, source_row_number, sex, age")
CELLS = 14 * 60   # per sheet: 14 places x 3 sexes x 20 ages
# What the sums must give each place: (level, parent index), by TREE index.
LEVELS = ["country", "region", "province", "city_municipality", "city_municipality", "city_municipality",
          "city_municipality", "region", "city_municipality", "city_municipality", "region", "province",
          "city_municipality", "city_municipality"]


@dataclass
class SilverResult:
    run_id: str
    status: str            # succeeded | failed | built (the gate was not run)
    error: str = None


class Env:
    def __init__(self, tmp_path):
        self.config = empty_config()
        self.landing = tmp_path / "landing"
        self.repo = fake_repo(tmp_path / "repo", self.config)
        self.store = DuckDBStore()
        self.workbooks = []

    def deliver(self, years=YEARS, values=None, pin=True, levels=None, statuses=None):
        """Approve made-up tree workbooks, pin their level and place_status counts, and regenerate the Silver
        SQL. values: {year: {sheet concept: per-place counts}}; statuses: {year: {place_status: count}}."""
        for year in years:
            path = write_tree_workbook(self.landing / "psa" / "original", year, (values or {}).get(year))
            approve_tree(self.config, path, year, (values or {}).get(year))
            self.workbooks.append((year, path))
        write_config(self.repo, self.config)
        mapping = json.loads(MAPPING.read_text(encoding="utf-8"))
        mapping = pin_tree_levels(mapping, self.workbooks if pin else [], levels, statuses)
        (self.repo / "config" / "mappings" / f"{SOURCE}.json").write_text(json.dumps(mapping, indent=2), encoding="utf-8")
        spec = sap.load_spec(self.repo)
        (self.repo / "etl" / "03_silver" / BUILD).write_text(sap.build_sql(spec), encoding="utf-8")
        (self.repo / "etl" / "03_silver" / GATE).write_text(sap.gate_sql(spec), encoding="utf-8")
        return spec

    def bronze(self):
        summary = IngestionRun(self.store, self.repo, SOURCE, self.landing, "local", REVISION).execute()
        assert summary.status == "succeeded", summary
        return summary

    def silver(self, run_id=None, hook=None, gate=True):
        """The job's two Silver SQL tasks: the build, then (if it succeeded) the gate."""
        run_id = run_id or str(uuid.uuid4())
        params = {"run_id": run_id, "code_revision": REVISION, "environment": "local"}
        folder = self.repo / "etl" / "03_silver"
        try:
            self.store.run_file(folder / BUILD, params)
        except Exception as e:
            return SilverResult(run_id, "failed", f"build: {e}")
        if hook:
            hook()
        if not gate:
            return SilverResult(run_id, "built")
        try:
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

    def silver_run(self, run_id):
        return self.rows(f"SELECT * FROM {CONTROL}.pipeline_runs WHERE run_id = '{run_id}' "
                         f"AND pipeline_name = 'silver_build' AND source_id = '{SOURCE}'")[0]

    def checks(self, run_id, status=None):
        where = f" AND status = '{status}'" if status else ""
        return {(r["check_name"], r["batch_id"]): r for r in self.rows(
            f"SELECT * FROM {CONTROL}.data_quality_results WHERE run_id = '{run_id}' AND source_id = '{SOURCE}' "
            f"AND layer = 'silver'{where}")}

    def check_names(self, run_id, status):
        return sorted({name for name, _ in self.checks(run_id, status)})

    def places(self, year, concept="total", table=CLEAN):
        return self.rows(f"SELECT DISTINCT place_row_number, place_label, place_name, footnote, old_name, is_capital, "
                         f"level, region_name, province_name, parent_name FROM {table} "
                         f"WHERE census_year = {year} AND population_concept = '{concept}' ORDER BY place_row_number")


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def with_change(concept, place, cell, delta, ancestors=True):
    """Tree counts with one cell of one place changed, and (by default) the same change in every place
    above it, so the tree still closes."""
    values = tree_values(concept)
    chain = [place]
    while ancestors and TREE[chain[-1]][2] is not None:
        chain.append(TREE[chain[-1]][2])
    for i in chain:
        values[i][cell] += delta
    return values


# --- One row per cell, both layouts ------------------------------------------------------------

def test_both_layouts_give_one_row_per_cell_equal_to_its_bronze_cell(env):
    env.deliver()
    env.bronze()
    assert env.silver().status == "succeeded"
    counts = env.q(f"SELECT census_year, population_concept, COUNT(*) FROM {CLEAN} GROUP BY 1, 2 ORDER BY 1, 2")
    assert counts == [(2020, "household", CELLS), (2020, "total", CELLS), (2024, "household", CELLS), (2024, "total", CELLS)]
    assert env.one(f"SELECT COUNT(*) FROM {QUARANTINE}") == 0
    # 2020: the place row holds all 60 counts; 2024: the Male row under the place row holds the male counts.
    expected = tree_values("Total Pop")[6]
    for year, label in (("2020", "CITY OF HUC"), ("2024", "CITY OF HUC 1/")):
        row = env.rows(f"SELECT * FROM {CLEAN} WHERE census_year = {year} AND population_concept = 'total' "
                       f"AND place_label = '{label}' AND sex = 'male' AND age = 7")[0]
        assert row["population"] == expected[20 + 2]
        kind = env.one(f"SELECT source_row_kind FROM {BRONZE} WHERE source_sha256 = '{row['source_sha256']}' "
                       f"AND source_sheet = '{row['source_sheet']}' AND source_row_number = {row['source_row_number']}")
        assert kind == ("place" if year == "2020" else "sex_male")
        assert (row["place_row_number"] == row["source_row_number"]) == (year == "2020")
    assert env.q(f"SELECT DISTINCT sex FROM {CLEAN} ORDER BY 1") == [("both",), ("female",), ("male",)]
    assert env.q(f"SELECT MIN(age), MAX(age), COUNT(DISTINCT age) FROM {CLEAN}") == [(5, 24, 20)]


def test_levels_and_parents_come_from_the_sums(env):
    env.deliver()
    env.bronze()
    assert env.silver().status == "succeeded"
    for year in YEARS:
        for concept in CONCEPTS:
            places = env.places(year, concept)
            assert [p["level"] for p in places] == LEVELS
            names = [p["place_name"] for p in places]
            parents = [names[e[2]] if e[2] is not None else None for e in TREE]
            assert [p["parent_name"] for p in places] == parents
    places = {p["place_label"]: p for p in env.places("2020")}
    assert (places["CITY OF HUC"]["region_name"], places["CITY OF HUC"]["province_name"]) == ("REGION I", None)
    assert (places["CHARLIE"]["region_name"], places["CHARLIE"]["province_name"]) == ("REGION II", "PROVINCE TWO")
    assert (places["PROVINCE ONE"]["region_name"], places["PROVINCE ONE"]["province_name"]) == ("REGION I", "PROVINCE ONE")
    assert (places["PHILIPPINES"]["region_name"], places["PHILIPPINES"]["parent_name"]) == (None, None)
    # REGION II has a single province, so the two are equal in every cell; the province is still its child.
    assert places["PROVINCE TWO"]["parent_name"] == "REGION II" and places["REGION II"]["level"] == "region"


def test_a_footnote_an_old_name_and_a_capital_are_parsed(env):
    env.deliver()
    env.bronze()
    assert env.silver().status == "succeeded"
    old = {p["place_label"]: p for p in env.places("2020")}
    new = {p["place_label"]: p for p in env.places("2024")}
    assert (old["BRAVO (OLD BRAVO)"]["place_name"], old["BRAVO (OLD BRAVO)"]["old_name"]) == ("BRAVO", "OLD BRAVO")
    assert (old["ALPHA (Capital)"]["is_capital"], old["ALPHA (Capital)"]["old_name"]) == (True, None)
    assert new["ALPHA (CAPITAL)"]["is_capital"] is True
    assert (new["CITY OF HUC 1/"]["place_name"], new["CITY OF HUC 1/"]["footnote"]) == ("CITY OF HUC", "1/")
    assert (new["PHILIPPINES a/"]["place_name"], new["PHILIPPINES a/"]["footnote"]) == ("PHILIPPINES", "a/")
    assert old["NATIONAL CAPITAL REGION (NCR)"]["old_name"] == "NCR"
    assert sum(p["is_capital"] for p in old.values()) == 1 and all(p["footnote"] is None for p in old.values())


@pytest.mark.parametrize("label, expected", [
    ("ALFONSO LISTA (POTIA)", ("ALFONSO LISTA", None, "POTIA", False)),
    ("SASMUAN (Sexmoan)", ("SASMUAN", None, "Sexmoan", False)),
    ("Region IV-A (CALABARZON)", ("REGION IV-A", None, "CALABARZON", False)),
    ("CITY OF MAKATI 1/", ("CITY OF MAKATI", "1/", None, False)),
    ("SPECIAL GEOGRAPHIC AREA 8/", ("SPECIAL GEOGRAPHIC AREA", "8/", None, False)),
    ("TAGBILARAN CITY (Capital)", ("TAGBILARAN CITY", None, None, True)),
    ("LIGAO ( CAPITAL )", ("LIGAO", None, None, True)),
    ("CITY OF X (Capital) (OLD X)", ("CITY OF X", None, "OLD X", True)),
    ("A (B) (C)", ("A", None, "B, C", False)),
    ("AMAI MANABILANG 1", ("AMAI MANABILANG 1", None, None, False)),
    ("MIDSAYAP CLUSTER I", ("MIDSAYAP CLUSTER I", None, None, False)),
])
def test_label_rules_on_the_published_shapes(label, expected):
    """The label rules (profile O-6) on DuckDB, as the build writes them."""
    parts = sap._label_parts(sap.load_spec(REPO_ROOT), "x")
    store = DuckDBStore()
    found = store.query(f"SELECT {parts['place_name']}, {parts['footnote']}, {parts['old_name']}, {parts['is_capital']} "
                        f"FROM (SELECT '{label}' AS x)")[0]
    assert found == expected


# --- The gate: the tree, the sexes, the concepts -------------------------------------------------

def test_a_clean_load_passes_every_check(env):
    env.deliver()
    env.bronze()
    summary = env.silver()
    assert summary.status == "succeeded"
    checks = env.checks(summary.run_id)
    assert {r["status"] for r in checks.values()} == {"PASS"}
    spec = sap.load_spec(env.repo)
    scopes = [scope for _, scope, _ in sap.gate_checks(spec)]
    assert len(checks) == scopes.count("whole") + 2 * scopes.count("batch") + 4 * scopes.count("sheet")
    for (name, batch), r in checks.items():
        if name.startswith("levels_match_expected"):
            assert r["actual"] == r["expected"] == "country 1, region 3, province 2, city_municipality 8"
        if name.startswith("rows_reconcile"):
            assert r["actual"] == r["expected"] == str(CELLS)
    national = {n: r["actual"] for (n, _), r in checks.items() if n == "national_both_sexes_by_age_total"}
    assert national and all(v == ",".join(str(x) for x in tree_values("Total Pop")[0][:20]) for v in national.values())
    equal = [r["actual"] for (n, _), r in checks.items() if n == "places_with_equal_concepts"]
    assert equal == ["7", "7"]        # household is below total only in BRAVO and CHARLIE and the 5 places above them


def test_a_tree_that_does_not_close_fails_and_nothing_is_published(env):
    broken = tree_values("Total Pop")
    broken[2][5] += 1              # PROVINCE ONE, both sexes, age 10: no longer its towns' sum
    broken[2][25] += 1             # and male, so the sexes still add up
    env.deliver(values={"2020": {"Total Pop": broken}})
    env.bronze()
    summary = env.silver()
    assert summary.status == "failed" and "Silver gate failed" in summary.error
    failed = env.check_names(summary.run_id, "FAIL")
    assert "levels_match_expected_total" in failed and "place_levels_assigned_total" in failed
    assert not [n for n in failed if n.endswith("_household") or n.startswith("sexes")]
    assert env.silver_run(summary.run_id)["status"] == "failed"
    assert env.one("SELECT COUNT(*) FROM duckdb_tables() WHERE schema_name = '03-silver' "
                   "AND table_name = 'psa_school_age_population_clean'") == 0


def test_sexes_that_do_not_add_up_fail(env):
    values = with_change("Total Pop", place=13, cell=3, delta=2)     # CHARLIE, both sexes, age 8, and its parents
    env.deliver(values={"2024": {"Total Pop": values}})
    env.bronze()
    summary = env.silver()
    assert summary.status == "failed"
    failed = env.check_names(summary.run_id, "FAIL")
    assert "sexes_add_up_total" in failed and "tree_closes_total" not in failed
    assert env.checks(summary.run_id)[("sexes_add_up_total", _batch(env, "2024"))]["actual"] == "4"   # CHARLIE and 3 above


def test_household_above_total_fails(env):
    values = with_change("Household Pop", place=8, cell=20, delta=500)   # CITY OF ONE, male, age 5, and its parents
    for i in (8, 7, 0):
        values[i][0] += 500                                              # both sexes too, so the sexes add up
    env.deliver(values={"2020": {"Household Pop": values}})
    env.bronze()
    summary = env.silver()
    assert summary.status == "failed"
    assert env.check_names(summary.run_id, "FAIL") == ["household_not_above_total"]
    assert env.checks(summary.run_id)[("household_not_above_total", _batch(env, "2020"))]["actual"] == "6"


def test_zero_counts_are_kept_and_warned(env):
    values = tree_values("Total Pop")
    for cell in (19, 39, 59):             # PATEROS at age 24: both sexes, male, female
        values[0][cell] -= values[9][cell]
        values[7][cell] -= values[9][cell]
        values[9][cell] = 0
    env.deliver(values={"2024": {"Total Pop": values, "Household Pop": values}})
    env.bronze()
    summary = env.silver()
    assert summary.status == "succeeded"
    assert env.check_names(summary.run_id, "WARN") == ["zero_population_cells_household", "zero_population_cells_total"]
    assert env.q(f"SELECT DISTINCT place_name, population FROM {CLEAN} WHERE population = 0") == [("PATEROS", 0)]


def test_a_workbook_whose_levels_are_not_pinned_fails(env):
    env.deliver(pin=False)
    env.bronze()
    summary = env.silver()
    assert summary.status == "failed"
    failed = env.checks(summary.run_id, "FAIL")
    assert {n for n, _ in failed} == {"levels_match_expected_total", "levels_match_expected_household",
                                      "place_status_match_expected_total", "place_status_match_expected_household"}
    assert all(r["expected"].startswith("not pinned") for r in failed.values())


def test_levels_pinned_differently_fail(env):
    env.deliver(levels={**TREE_LEVELS, "city_municipality": 9})
    env.bronze()
    assert "levels_match_expected_total" in env.check_names(env.silver().run_id, "FAIL")


@pytest.fixture
def special_tree():
    """The tree with REGION II's single province as the Special Geographic Area (2020 INTERIM PROVINCE,
    2024 SPECIAL GEOGRAPHIC AREA), and one of its towns a 2020 cluster, as in profile O-7."""
    original = list(TREE)
    TREE[11] = ("INTERIM PROVINCE", "SPECIAL GEOGRAPHIC AREA 3/", 10)
    TREE[13] = ("PIKIT CLUSTER II", "PAHAMUDDIN", 11)
    yield
    TREE[:] = original


def test_the_special_geographic_area_and_its_clusters_are_flagged_and_keep_their_level(env, special_tree):
    env.deliver(statuses={"2020": {"special_geographic_area": 1, "sga_cluster": 1},
                          "2024": {"special_geographic_area": 1}})
    env.bronze()
    assert env.silver().status == "succeeded"
    flagged = env.q(f"SELECT DISTINCT census_year, place_name, level, place_status FROM {CLEAN} "
                    "WHERE place_status <> 'standard' ORDER BY 1, 2")
    assert flagged == [(2020, "INTERIM PROVINCE", "province", "special_geographic_area"),
                       (2020, "PIKIT CLUSTER II", "city_municipality", "sga_cluster"),
                       (2024, "SPECIAL GEOGRAPHIC AREA", "province", "special_geographic_area")]
    # The 2024 SGA municipality and the other town under the SGA stay standard; so does everything else.
    assert env.q(f"SELECT DISTINCT place_status FROM {CLEAN} WHERE place_name IN ('PAHAMUDDIN', 'SAN TEST')") == [("standard",)]


def test_special_places_not_pinned_fail(env, special_tree):
    env.deliver()                                                        # pins 0 for both statuses
    env.bronze()
    failed = env.checks(env.silver().run_id, "FAIL")
    assert {n for n, _ in failed} == {"place_status_match_expected_total", "place_status_match_expected_household"}
    by_year = {r["actual"] for (n, _), r in failed.items() if n == "place_status_match_expected_total"}
    assert any("special_geographic_area 1" in a for a in by_year)


def test_a_place_of_zeros_fails_because_the_sums_cannot_place_it(env):
    """CITY OF HUC follows PROVINCE ONE's span: with every cell 0 it adds nothing, so the span can swallow it
    and every sum still closes. The gate fails it rather than guess its parent (#176 review)."""
    zero = {6: [0] * 60}
    env.deliver(years=("2020",), values={"2020": {c: tree_values(c, leaves=zero) for c in ("Total Pop", "Household Pop")}})
    env.bronze()
    summary = env.silver()
    assert summary.status == "failed"
    failed = {n: r for (n, _), r in env.checks(summary.run_id, "FAIL").items()}
    assert failed["no_all_zero_place_total"]["actual"] == "1"
    assert "no_all_zero_place_household" in failed


@pytest.mark.parametrize("value, reason", [("", "population_blank"), ("-3", "population_negative"),
                                           ("1.5", "population_not_whole_number")])
def test_a_count_that_cannot_be_typed_is_quarantined_and_fails_the_gate(env, value, reason):
    env.deliver(years=("2020",))
    env.bronze()
    env.store.sql(f"UPDATE {BRONZE} SET male_age_9 = '{value}' WHERE label = 'CHARLIE' AND source_sheet = '2020 Total Pop'")
    summary = env.silver()
    assert summary.status == "failed"
    assert env.q(f"SELECT place_label, sex, age, quarantine_reasons FROM {QUARANTINE_CANDIDATE}") == [
        ("CHARLIE", "male", 9, [reason])]
    failed = env.check_names(summary.run_id, "FAIL")
    assert "quarantined_cells_total" in failed and "rows_reconcile_total" not in failed


BROKEN_BUILDS = [
    ("population_matches_bronze_total", "population = population + 1", "place_label = 'CHARLIE' AND sex = 'male' AND age = 5"),
    ("place_label_parsed_total", "place_name = 'CHARLES'", "place_label = 'CHARLIE'"),
    ("place_label_parsed_total", "old_name = NULL", "place_label = 'BRAVO (OLD BRAVO)'"),
    ("place_label_parsed_total", "is_capital = FALSE", "place_label = 'ALPHA (Capital)'"),
    ("place_levels_assigned_total", "level = NULL", "place_label = 'PROVINCE ONE'"),
    ("place_status_match_expected_total", "place_status = 'sga_cluster'", "place_label = 'CHARLIE'"),
    ("parents_resolve_total", "parent_name = 'NOWHERE'", "place_label = 'CHARLIE'"),
    ("tree_closes_total", "population = population + 1", "place_label = 'PROVINCE TWO' AND sex = 'both' AND age = 6"),
    ("one_country_total", "level = 'region'", "place_label = 'PHILIPPINES'"),
    ("population_not_null_total", "population = NULL", "place_label = 'CHARLIE' AND age = 5"),
    ("rows_resolve_to_current_bronze_cells", "source_row_number = 1", "place_label = 'CHARLIE' AND age = 5"),
    ("lineage_complete", "batch_id = NULL", "place_label = 'CHARLIE' AND age = 5"),
    ("rows_built_by_this_run", "run_id = 'an-old-run'", "place_label = 'CHARLIE'"),
    ("one_timestamp_per_run", "cleaned_at_utc = cleaned_at_utc + INTERVAL 1 SECOND", "place_label = 'CHARLIE'"),
]


@pytest.mark.parametrize("check, tamper, where", BROKEN_BUILDS, ids=[f"{c}-{t}" for c, t, _ in BROKEN_BUILDS])
def test_each_gate_check_fails_a_broken_build(env, check, tamper, where):
    """Checks the rules cannot trip on their own: each must still fail a build that breaks it."""
    env.deliver(years=("2020",))
    env.bronze()
    summary = env.silver(hook=lambda: env.store.sql(
        f"UPDATE {CLEAN_CANDIDATE} SET {tamper} WHERE population_concept = 'total' AND {where}"))
    assert summary.status == "failed"
    assert check in env.check_names(summary.run_id, "FAIL")


def test_a_lost_row_a_repeated_row_and_a_missing_concept_cell_fail(env):
    env.deliver(years=("2024",))
    env.bronze()

    def tamper():
        env.store.sql(f"DELETE FROM {CLEAN_CANDIDATE} WHERE population_concept = 'household' AND place_label = 'CHARLIE' "
                      "AND sex = 'female' AND age = 24")
        env.store.sql(f"INSERT INTO {CLEAN_CANDIDATE} SELECT * FROM {CLEAN_CANDIDATE} "
                      "WHERE population_concept = 'total' AND place_label = 'BRAVO' AND sex = 'male' AND age = 5")

    summary = env.silver(hook=tamper)
    failed = set(env.check_names(summary.run_id, "FAIL"))
    assert {"rows_reconcile_household", "rows_reconcile_total", "key_unique_total", "concepts_pair_up",
            "sexes_add_up_household"} <= failed


def test_check_results_hold_counts_not_names(env):
    env.deliver()
    env.bronze()
    summary = env.silver()
    texts = [str(v) for r in env.checks(summary.run_id).values() for v in (r["expected"], r["actual"])]
    assert not [t for t in texts if any(label in t for label in ("CHARLIE", "PROVINCE", "REGION", "PHILIPPINES"))]


def test_no_current_batch_fails_the_gate(env):
    from src.ingestion import control
    env.deliver(years=())
    control.create_tables(env.store, env.repo)
    env.store.run_file(env.repo / "etl" / "02_bronze" / "08_create_psa_school_age_population_raw.sql")
    summary = env.silver()
    assert summary.status == "failed"
    assert "current_batches_present" in env.check_names(summary.run_id, "FAIL")


# --- Reruns, failures, and the run record ------------------------------------------------------

def test_repeated_full_rebuilds_give_identical_business_content(env):
    env.deliver()
    env.bronze()
    first = env.silver()
    before = env.q(CONTENT.format(CLEAN))
    env.bronze()                                                            # a Bronze rerun that loads nothing new
    again = env.silver()
    assert first.status == again.status == "succeeded" and first.run_id != again.run_id
    assert env.q(CONTENT.format(CLEAN)) == before and len(before) == 4 * CELLS
    assert env.q(f"SELECT DISTINCT run_id FROM {CLEAN}") == [(again.run_id,)]


def test_each_tree_step_reads_a_work_table_and_the_build_drops_them(env):
    """Spark recomputes a view every time it is used, so a chain of views recomputed every earlier pass
    for each later one (a 40-minute build on Databricks). Each step is a table instead (#158)."""
    build = sap.build_sql(sap.load_spec(REPO_ROOT))
    assert "TEMPORARY VIEW psa_school_age_population_tree" not in build
    assert build.count("TEMPORARY VIEW") == 1                              # the last join only, used twice
    env.deliver()
    env.bronze()
    assert env.silver(gate=False).status == "built"
    assert env.q("SELECT table_name FROM information_schema.tables WHERE table_name LIKE '%_work_%'") == []
    assert env.one(f"SELECT COUNT(*) FROM {CLEAN_CANDIDATE}") == 4 * CELLS


def test_a_failed_build_never_replaces_the_last_good_one(env):
    env.deliver()
    env.bronze()
    good = env.silver()
    bad = env.silver(hook=lambda: env.store.sql(f"UPDATE {CLEAN_CANDIDATE} SET population = population + 1 "
                                                "WHERE place_label = 'CHARLIE'"))
    assert bad.status == "failed" and env.silver_run(bad.run_id)["status"] == "failed"
    assert env.q(f"SELECT run_id, COUNT(*) FROM {CLEAN} GROUP BY 1") == [(good.run_id, 4 * CELLS)]


def test_a_run_is_succeeded_only_after_its_gate_passes_and_carries_lineage(env):
    env.deliver()
    env.bronze()
    built = env.silver(gate=False)
    run = env.silver_run(built.run_id)
    assert (run["status"], run["environment"], run["code_revision"], run["job_run_id"]) == (
        "running", "local", REVISION, built.run_id)
    done = env.silver()
    assert env.silver_run(done.run_id)["status"] == "succeeded"
    joined = env.one(f"SELECT COUNT(*) FROM {CLEAN} AS c JOIN {BRONZE} AS b "
                     "ON c.source_sha256 = b.source_sha256 AND c.source_sheet = b.source_sheet "
                     "AND c.source_row_number = b.source_row_number AND c.batch_id = b.batch_id "
                     "AND c.delivery_version = b.delivery_version AND c.schema_version = b.schema_version "
                     "AND c.logical_dataset = b.logical_dataset AND CAST(c.census_year AS VARCHAR) = b.census_year")
    assert joined == 4 * CELLS
    stamps = env.q(f"SELECT DISTINCT run_id, cleaned_at_utc, code_revision FROM {CLEAN}")
    assert len(stamps) == 1 and stamps[0][0] == done.run_id and stamps[0][2] == REVISION


def test_a_repaired_run_is_judged_by_its_own_checks(env):
    env.deliver(years=("2020",))
    env.bronze()
    first = env.silver(run_id="job-run-9", hook=lambda: env.store.sql(
        f"DELETE FROM {CLEAN_CANDIDATE} WHERE place_label = 'CHARLIE'"))
    assert first.status == "failed"
    assert env.silver(run_id="job-run-9").status == "succeeded"
    assert env.silver_run("job-run-9")["status"] == "succeeded"


# --- The committed files and the rules file -----------------------------------------------------

def test_the_school_age_generator_is_chosen_by_its_rules_file():
    assert generator(SOURCE, REPO_ROOT) is sap


def test_committed_files_match_the_generator(repo_root):
    spec = sap.load_spec(repo_root)
    for path, text in ((f"etl/03_silver/{BUILD}", sap.build_sql(spec)), (f"etl/03_silver/{GATE}", sap.gate_sql(spec)),
                       ("docs/data/silver/psa-school-age-population-clean.md", sap.dictionary_markdown(spec))):
        assert (repo_root / path).read_text(encoding="utf-8") == text, f"Regenerate {path} (src/silver/cli.py)"


def test_every_gate_check_is_written_by_the_gate_sql():
    spec = sap.load_spec(REPO_ROOT)
    gate = sap.gate_sql(spec)
    for name, scope, _ in sap.gate_checks(spec):
        literal = f"'{name}'" if scope != "sheet" else f"'{name}_' || population_concept"
        assert f"{literal} AS check_name" in gate, name
    assert gate.count(" AS check_name") == len(sap.gate_checks(spec))


def test_the_build_never_publishes_and_the_gate_publishes_clean_last():
    spec = sap.load_spec(REPO_ROOT)
    build, gate = sap.build_sql(spec), sap.gate_sql(spec)
    for table in (spec.clean_table, spec.quarantine_table):
        assert f"CREATE OR REPLACE TABLE edu_access.`03-silver`.{table} USING" not in build
    order = [gate.index(m) for m in ("WHEN MATCHED AND s.fails > 0 THEN UPDATE SET", "raise_error(",
                                      f"CREATE OR REPLACE TABLE edu_access.`03-silver`.{spec.quarantine_table} USING",
                                      f"CREATE OR REPLACE TABLE edu_access.`03-silver`.{spec.clean_table} USING",
                                      "status = 'succeeded'")]
    assert order == sorted(order)


def _spec(mapping=None, contract=None):
    registry = yaml.safe_load((REPO_ROOT / "config" / "tables.yml").read_text(encoding="utf-8"))
    entry = next(s for s in registry["source_tables"] if s["source_id"] == SOURCE)
    mapping = mapping or json.loads(MAPPING.read_text(encoding="utf-8"))
    return sap.build_spec(mapping, contract or real_config(), entry)


def test_the_real_rules_give_sixty_cells_four_levels_and_both_workbooks_pinned():
    spec = _spec()
    assert spec.ages == list(range(5, 25)) and spec.sexes == ["both", "male", "female"] and spec.cells_per_place == 60
    assert spec.levels == ["country", "region", "province", "city_municipality"] and spec.passes == 3
    assert list(spec.concepts) == ["total", "household"]
    approved = {d["census_year"]: d["workbook_sha256"] for d in real_config()["deliveries"]}
    assert {p["census_year"]: (p["workbook_sha256"], p["region"], p["province"], p["city_municipality"])
            for p in spec.expected_levels} == {"2020": (approved["2020"], 17, 82, 1642),
                                               "2024": (approved["2024"], 18, 83, 1642)}
    assert all(sum(p[level] for level in spec.levels) == place_rows for p in spec.expected_levels
               for d in real_config()["deliveries"] if d["workbook_sha256"] == p["workbook_sha256"]
               for place_rows in {s["place_rows"] for s in d["sheets"]})


def test_a_new_count_column_needs_a_reviewed_rule():
    contract = copy.deepcopy(real_config())
    contract["schema_versions"]["v1"]["columns"].append("both_sexes_age_25")
    with pytest.raises(IngestionError, match="every sex and age exactly once"):
        _spec(contract=contract)


@pytest.mark.parametrize("break_it, message", [
    (lambda m: m.update(silver_table="school_age_silver"), "config/tables.yml"),
    (lambda m: m["sexes"]["male"].update(wide_prefix="men"), "no sex in the mapping"),
    (lambda m: m["sexes"]["male"].update(long_row_kind="sex_men"), "differ from the mapping"),
    (lambda m: m["expected_levels"][0].update(workbook_sha256="0" * 64), "not an approved delivery"),
    (lambda m: m["expected_levels"][1].update(census_year="2020"), "not an approved delivery"),
    (lambda m: m["expected_levels"][0].pop("province"), "count for every level"),
    (lambda m: m["expected_levels"][1].pop("sga_cluster"), "every place_status"),
    (lambda m: m["place_status"]["sga_cluster"].update(level="barangay"), "is not a level"),
    (lambda m: m["label"].update(footnote_pattern="x';"), "quotes, backslashes"),
    (lambda m: m["levels"].update(leaf_depths=[0]), "leaf_depths"),
    (lambda m: m["levels"].update(by_depth=["country", "region", "country"]), "each level once"),
])
def test_the_rules_file_refuses_ambiguous_rules(break_it, message):
    mapping = json.loads(MAPPING.read_text(encoding="utf-8"))
    break_it(mapping)
    with pytest.raises(IngestionError, match=message):
        _spec(mapping=mapping)


def _batch(env, year):
    return env.one(f"SELECT DISTINCT batch_id FROM {BRONZE} WHERE census_year = '{year}'")


def test_the_tree_labels_differ_by_year_as_in_the_profile():
    assert tree_labels("2020")[1] == "REGION I (TEST REGION)" and tree_labels("2024")[1] == "REGION I - TEST REGION"
