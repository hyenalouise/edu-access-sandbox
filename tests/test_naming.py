"""Enforce the repository's machine-readable naming contract."""

import re

import yaml


ETL_LAYERS = {
    "01_control",
    "02_bronze",
    "03_silver",
    "04_integration",
    "05_gold",
    "06_analytics",
}
ETL_FILE = re.compile(r"^\d{2}_[a-z0-9_]+\.(sql|py)$")
ANALYSIS_FILE = re.compile(r"^(profile|dictionary|cross_source)_[a-z0-9_]+\.py$")
SQL_FILE = re.compile(r"^\d{2}_[a-z0-9_]+\.sql$")


def test_naming_configuration_parses(repo_root):
    naming = yaml.safe_load((repo_root / "config" / "naming.yml").read_text())
    assert naming["catalog"] == "edu_access"
    assert naming["schemas"] == {
        "source": "00-source",
        "control": "01-control",
        "bronze": "02-bronze",
        "silver": "03-silver",
        "integration": "04-integration",
        "gold": "05-gold",
        "analytics": "06-analytics",
    }


def test_known_source_table_names_are_registered(repo_root):
    registry = yaml.safe_load((repo_root / "config" / "tables.yml").read_text())
    sources = registry["source_tables"]
    assert [source["source_id"] for source in sources] == [
        "deped_enrollment",
        "deped_facilities",
        "deped_personnel",
        "psa_psgc",
        "psa_poverty_stat",
        "hdx_boundaries",
        "deped_enrollment_psgc",
    ]

    for number, source in enumerate(sources, start=1):
        bronze = source["bronze"]
        # A source may be registered before its Silver names are settled; then it has no silver entry,
        # and it cannot have a Silver mapping either (checked below).
        silver = source.get("silver")
        assert bronze["table"].endswith("_raw")
        assert SQL_FILE.fullmatch(bronze["create_file"])
        prefix = f"{number:02d}_"
        assert bronze["create_file"].startswith(prefix + "create_")
        assert SQL_FILE.fullmatch(bronze["validate_file"])
        if silver is not None:
            assert silver["table"].endswith("_clean")
            assert silver["quarantine_table"].endswith("_quarantine")
            assert silver["candidate_table"] == silver["table"] + "_candidate"
            assert silver["candidate_quarantine_table"] == silver["quarantine_table"] + "_candidate"
            assert SQL_FILE.fullmatch(silver["clean_file"])
            assert silver["clean_file"].startswith(prefix + "clean_")
            assert SQL_FILE.fullmatch(silver["validate_file"])

        if (repo_root / "config" / "ingestion" / f"{source['source_id']}.json").is_file():
            assert (repo_root / "etl" / "02_bronze" / bronze["create_file"]).is_file()
        if (repo_root / "config" / "mappings" / f"{source['source_id']}.json").is_file():
            assert silver is not None, f"{source['source_id']} has a Silver mapping but no silver entry"
            assert (repo_root / "etl" / "03_silver" / silver["clean_file"]).is_file()


def test_integration_registry_is_explicitly_draft(repo_root):
    registry = yaml.safe_load((repo_root / "config" / "tables.yml").read_text())
    assert registry["draft_integration_tables"]
    assert registry["deferred_layers"] == ["gold", "analytics"]
    for candidate in registry["draft_integration_tables"]:
        assert candidate["table"].endswith("_map")
        assert SQL_FILE.fullmatch(candidate["candidate_file"])
        assert "_map_" in candidate["candidate_file"]


def test_etl_files_follow_the_layer_layout(repo_files):
    problems = []
    for path in repo_files:
        if not path.parts or path.parts[0] != "etl" or len(path.parts) < 3:
            continue
        layer = path.parts[1]
        if layer not in ETL_LAYERS:
            problems.append(f"{path}: unknown ETL layer")
        elif len(path.parts) != 3:
            problems.append(f"{path}: layer folders may not contain subfolders")
        elif path.name != "README.md" and not ETL_FILE.fullmatch(path.name):
            problems.append(f"{path}: expected NN_lowercase_name.sql or .py")
    assert not problems, "\n".join(problems)


def test_analysis_programs_use_role_prefixes(repo_files):
    offenders = [
        str(path)
        for path in repo_files
        if path.parts[:2] in {("analysis", "profiling"), ("analysis", "cross_source")}
        and path.suffix == ".py"
        and not ANALYSIS_FILE.fullmatch(path.name)
    ]
    assert not offenders, f"analysis programs need a role prefix: {offenders}"
