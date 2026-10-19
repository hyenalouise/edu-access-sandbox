"""databricks.yml and the Bronze gates must keep every output traceable to its commit.

The lineage path is: the deploy resolves ${bundle.git.commit} into both the job's
git_source (the code that runs) and its code_revision parameter (the value
recorded); each task passes the parameter on; each gate stamps it on its rows.
A break anywhere leaves rows that name the wrong commit, or none, and nobody
notices until a number is questioned. These tests fail at the pull request
instead.
"""

import json
import re
from pathlib import Path

import pytest
import yaml

from src.ingestion.store import split_statements

COMMIT = "${bundle.git.commit}"
PARAMETER = "{{job.parameters.code_revision}}"


@pytest.fixture(scope="module")
def bundle(repo_root):
    return yaml.safe_load((repo_root / "databricks.yml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def jobs(bundle):
    return bundle["resources"]["jobs"]


@pytest.fixture(scope="module")
def project(repo_root):
    return json.loads((repo_root / "config" / "project.json").read_text(encoding="utf-8"))


def python_tasks(jobs):
    for job_name, job in jobs.items():
        for task in job["tasks"]:
            if "spark_python_task" in task:
                yield job_name, task


def loads(jobs):
    """The source loads: `cli.py ingest` tasks (the job's other Python task adds control columns)."""
    for job_name, task in python_tasks(jobs):
        if task["spark_python_task"]["parameters"][0] == "ingest":
            yield job_name, task


def argument(task, flag):
    args = task["spark_python_task"]["parameters"]
    return args[args.index(flag) + 1] if flag in args else None


def gates(repo_root):
    return sorted(repo_root.glob("etl/*/90_validate_*.sql"))


def test_the_job_and_gates_were_found(jobs, repo_root):
    """Guards the lookups: empty lists would make every test below vacuous."""
    assert list(python_tasks(jobs))
    assert gates(repo_root)


def test_each_job_records_the_deployed_commit(jobs):
    for name, job in jobs.items():
        parameters = {p["name"]: p["default"] for p in job.get("parameters", [])}
        assert parameters.get("code_revision") == COMMIT, (
            f"{name}: job parameter code_revision must default to {COMMIT}, or runs record the wrong commit")


def test_each_job_runs_the_commit_it_records(jobs):
    for name, job in jobs.items():
        source = job.get("git_source", {})
        assert "git_branch" not in source, (
            f"{name}: git_branch is resolved at run time, so the job could run newer code than it records")
        assert source.get("git_commit") == COMMIT, f"{name}: git_source.git_commit must be {COMMIT}"


def test_each_task_passes_the_revision_and_target_on(jobs):
    for name, task in loads(jobs):
        assert argument(task, "--code-revision") == PARAMETER, f"{name}/{task['task_key']} does not pass code_revision"
        assert argument(task, "--environment") == "${bundle.target}", (
            f"{name}/{task['task_key']} must record the deploy target as its environment")


def test_each_load_records_the_job_run_its_gate_uses(jobs):
    """The Bronze gate task writes data_quality_results under :run_id; the load stores the same
    value as job_run_id, or the two cannot be joined (D-020)."""
    for name, job in jobs.items():
        parameters = {p["name"]: p["default"] for p in job.get("parameters", [])}
        assert parameters.get("run_id") == "{{job.run_id}}"
        for _, task in loads({name: job}):
                assert argument(task, "--job-run-id") == "{{job.parameters.run_id}}", (
                    f"{name}/{task['task_key']} does not record the job run its gate uses")


def test_python_tasks_read_their_file_from_git(jobs):
    """Without source: GIT the jobs API rejects a repository-relative python_file (seen on deploy, 2026-10-06)."""
    for name, task in python_tasks(jobs):
        assert task["spark_python_task"].get("source") == "GIT", f"{name}/{task['task_key']} needs source: GIT"


def test_tasks_load_sources_that_have_a_contract(jobs, repo_root, project):
    for name, task in loads(jobs):
        source = argument(task, "--source")
        contract = repo_root / "config" / "ingestion" / f"{source}.json"
        assert contract.is_file() or task.get("disabled") is True, f"{source} has no contract and must be disabled"
        assert argument(task, "--landing") == project["raw_volume_path"]
        assert argument(task, "--backend") == "spark"


def sql_tasks(jobs):
    for job_name, job in jobs.items():
        for task in job["tasks"]:
            if "sql_task" in task:
                yield job_name, task


def test_control_bootstrap_is_the_only_root(jobs):
    """Control objects are initialized once before the source lanes fan out."""
    for name, job in jobs.items():
        roots = [task["task_key"] for task in job["tasks"] if not task.get("depends_on")]
        assert roots == ["01_create_pipeline_runs"], f"{name}: unexpected roots {roots}"


def test_source_lanes_fan_out_after_control_bootstrap(jobs, repo_root):
    """Each load depends on its own raw DDL, never on another source lane."""
    registry = yaml.safe_load((repo_root / "config" / "tables.yml").read_text(encoding="utf-8"))
    tables = {entry["source_id"]: entry["bronze"]["table"] for entry in registry["source_tables"]}
    for name, job in jobs.items():
        tasks = {task["task_key"]: task for task in job["tasks"]}
        lane_loads = [task for job_name, task in loads({name: job})]
        assert lane_loads, f"{name} has no source loads"
        for load in lane_loads:
            source = argument(load, "--source")
            ddl_path = f"etl/02_bronze/{next(p.name for p in (repo_root / 'etl' / '02_bronze').glob('*_create_*.sql') if p.name.endswith(f'_create_{tables[source]}.sql'))}"
            ddl = next(task for task in job["tasks"] if task.get("sql_task", {}).get("file", {}).get("path") == ddl_path)
            assert load.get("depends_on") == [{"task_key": ddl["task_key"]}]
            assert ddl.get("depends_on") == [{"task_key": "05_create_current_batches"}]
            assert load.get("run_if") == "ALL_SUCCESS"
            assert ddl.get("run_if") == "ALL_SUCCESS"


def test_non_source_tasks_declare_dependencies(jobs):
    """After the control root, every setup, load, transform, and check names its upstream task."""
    for name, job in jobs.items():
        for task in job["tasks"]:
            if task["task_key"] != "01_create_pipeline_runs":
                assert task.get("depends_on"), f"{name}/{task['task_key']} has no dependency"


SILVER_GATES = {
    "90_validate_deped_enrollment_clean", "90_validate_deped_facilities_clean", "90_validate_deped_personnel_clean",
    "90_validate_psa_psgc_clean", "90_validate_psa_poverty_stat_clean", "90_validate_hdx_adm3_clean",
    "90_validate_deped_enrollment_psgc_clean", "90_validate_psa_school_age_population_clean",
}

# Each downstream task and the gates it reads (D-051). A task waits for these and nothing else.
DOWNSTREAM = {
    "01_map_deped_school_psgc": {
        "90_validate_deped_enrollment_clean", "90_validate_deped_enrollment_psgc_clean",
        "90_validate_psa_psgc_clean"},
    "02_map_psa_poverty_psgc": {"90_validate_psa_poverty_stat_clean", "90_validate_psa_psgc_clean"},
    "03_map_hdx_adm3_psgc": {"90_validate_hdx_adm3_clean", "90_validate_psa_psgc_clean"},
    "04_map_deped_annex_mother": {"90_validate_deped_enrollment_clean"},
    "05_map_psa_school_age_population_psgc": {
        "90_validate_psa_school_age_population_clean", "90_validate_psa_psgc_clean"},
    "01_build_dim_school": {"90_validate_deped_enrollment_clean"},
    "02_build_dim_school_year": {"90_validate_deped_enrollment_clean"},
    "15_build_fact_school_year_source_availability": {
        "90_validate_deped_enrollment_clean", "90_validate_deped_facilities_clean",
        "90_validate_deped_personnel_clean", "90_validate_dim_school_year"},
    "03_build_dim_education_level": {"05_create_current_batches"},
    "04_build_dim_city_municipality": {"90_validate_psa_psgc_clean", "90_validate_hdx_adm3_psgc_map"},
    "05_build_dim_barangay": {"90_validate_psa_psgc_clean"},
    "06_build_dim_city_poverty": {"90_validate_psa_poverty_psgc_map", "90_validate_psa_poverty_stat_clean",
                                  "90_validate_dim_city_municipality"},
    "10_build_fact_school_enrollment": {
        "90_validate_deped_school_psgc_map", "90_validate_dim_school", "90_validate_dim_school_year",
        "90_validate_dim_education_level", "90_validate_dim_city_municipality", "90_validate_dim_barangay"},
    "11_build_fact_school_classroom_capacity": {
        "90_validate_deped_facilities_clean", "90_validate_dim_school", "90_validate_dim_school_year"},
    "90_validate_fact_school_classroom_capacity": {
        "11_build_fact_school_classroom_capacity", "90_validate_fact_school_enrollment"},
    "12_build_fact_school_teacher_capacity": {
        "90_validate_deped_personnel_clean", "90_validate_dim_school", "90_validate_dim_school_year",
        "90_validate_dim_education_level"},
    "13_build_fact_city_population": {"90_validate_psa_psgc_clean", "90_validate_dim_city_municipality"},
    "14_build_fact_city_school_age_population": {
        "90_validate_psa_school_age_population_psgc_map", "90_validate_dim_city_municipality"},
    "01_answer_ap1": {"90_validate_fact_school_enrollment", "90_validate_fact_city_population", "90_validate_dim_barangay"},
    "02_answer_ap2": {"90_validate_fact_school_enrollment", "90_validate_fact_school_classroom_capacity"},
    "03_answer_ap3": {"90_validate_fact_school_enrollment", "90_validate_fact_school_teacher_capacity"},
    "04_answer_ap4": {"90_validate_fact_school_enrollment", "90_validate_fact_city_school_age_population"},
}


def test_the_fan_in_is_an_audit_no_task_waits_for(jobs):
    """Every Silver gate fans in to 90_validate_control, which runs even when a lane failed (ALL_DONE)
    and fails itself if one did, so the job run fails; only freshness follows it (D-051)."""
    tasks = {task["task_key"]: task for task in jobs["edu_access_pipeline"]["tasks"]}
    for key in ("90_validate_control", "90_validate_freshness"):
        assert tasks[key].get("run_if") == "ALL_DONE" and not tasks[key].get("disabled")
    assert {d["task_key"] for d in tasks["90_validate_control"]["depends_on"]} == SILVER_GATES
    assert {d["task_key"] for d in tasks["90_validate_freshness"]["depends_on"]} == {"90_validate_control"}
    waiting = [k for k, t in tasks.items() if {"task_key": "90_validate_control"} in t.get("depends_on", [])]
    assert waiting == ["90_validate_freshness"], f"{waiting} wait for the fan-in, which is an audit (D-051)"


def test_freshness_waits_for_every_bronze_gate(jobs):
    """Freshness reads each source's latest Bronze batch, so every Bronze gate must come before it.
    Databricks resolves a disabled task only after the tasks before it (job run 268106548429452:
    the disabled 07_clean_deped_enrollment_psgc resolved when the EMISD Bronze gate finished), so a
    path through a disabled Silver gate still waits for the load."""
    tasks = {task["task_key"]: task for task in jobs["edu_access_pipeline"]["tasks"]}
    reached, todo = set(), ["90_validate_freshness"]
    while todo:
        for dep in tasks[todo.pop()].get("depends_on", []):
            if dep["task_key"] not in reached:
                reached.add(dep["task_key"])
                todo.append(dep["task_key"])
    bronze_gates = {k for k in tasks if k.startswith("90_validate_") and k.endswith("_raw")}
    assert bronze_gates <= reached, f"freshness can run before {sorted(bronze_gates - reached)}"


def test_downstream_tasks_start_from_the_gates_they_read(jobs):
    tasks = {task["task_key"]: task for task in jobs["edu_access_pipeline"]["tasks"]}
    for key, gates in DOWNSTREAM.items():
        assert {d["task_key"] for d in tasks[key]["depends_on"]} == gates, key
        assert tasks[key].get("run_if") == "ALL_SUCCESS", key


# Which APs each Silver lane's failure stops, as D-051's consequence table states.
APS_STOPPED_BY = {
    "90_validate_deped_enrollment_clean": {"ap1", "ap2", "ap3", "ap4"},
    "90_validate_psa_psgc_clean": {"ap1", "ap2", "ap3", "ap4"},
    "90_validate_hdx_adm3_clean": {"ap1", "ap2", "ap3", "ap4"},
    "90_validate_deped_enrollment_psgc_clean": {"ap1", "ap2", "ap3", "ap4"},
    "90_validate_deped_facilities_clean": {"ap2"},
    "90_validate_deped_personnel_clean": {"ap3"},
    "90_validate_psa_school_age_population_clean": {"ap4"},
    "90_validate_psa_poverty_stat_clean": set(),
}


def test_each_lane_failure_stops_the_aps_d051_says(jobs):
    """Follows ALL_SUCCESS edges down from each Silver gate, so the D-051 table cannot drift from the job."""
    tasks = {task["task_key"]: task for task in jobs["edu_access_pipeline"]["tasks"]}
    children = {}
    for key, task in tasks.items():
        for dep in task.get("depends_on", []):
            children.setdefault(dep["task_key"], []).append(key)
    assert set(APS_STOPPED_BY) == SILVER_GATES
    for gate, aps in APS_STOPPED_BY.items():
        stopped, todo = set(), [gate]
        while todo:
            for child in children.get(todo.pop(), []):
                if child not in stopped and tasks[child].get("run_if", "ALL_SUCCESS") == "ALL_SUCCESS":
                    stopped.add(child)
                    todo.append(child)
        assert {k.split("_answer_")[1] for k in stopped if "_answer_ap" in k} == aps, gate


def test_every_downstream_build_has_its_own_gate_after_it(jobs):
    """A build or answer task is followed by its 90_validate_ gate; nothing downstream reads an unchecked build."""
    tasks = {task["task_key"]: task for task in jobs["edu_access_pipeline"]["tasks"]}
    for key in DOWNSTREAM:
        if key.startswith("90_"):
            continue
        gates = [k for k, t in tasks.items() if k.startswith("90_") and {"task_key": key} in t.get("depends_on", [])]
        assert len(gates) == 1, f"{key} should have one gate, found {gates}"
        readers = [k for k, t in tasks.items() if k not in gates and {"task_key": key} in t.get("depends_on", [])]
        assert not readers, f"{readers} read {key} before its gate"


def test_a_load_that_skips_its_gate_is_gated_by_it(jobs, repo_root):
    """`ingest --no-gate` leaves the Bronze gate to its own task. Databricks orders tasks by
    depends_on, not by their place in the file, so that gate must depend on this load, run only
    if the load succeeded, and be enabled whenever the load is. No source loads unchecked."""
    registry = yaml.safe_load((repo_root / "config" / "tables.yml").read_text(encoding="utf-8"))
    tables = {entry["source_id"]: entry["bronze"]["table"] for entry in registry["source_tables"]}
    for name, job in jobs.items():
        for _, load in loads({name: job}):
            if "--no-gate" not in load["spark_python_task"]["parameters"]:
                continue
            path = f"etl/02_bronze/90_validate_{tables[argument(load, '--source')]}.sql"
            found = [t for t in job["tasks"] if t.get("sql_task", {}).get("file", {}).get("path") == path]
            assert len(found) == 1, f"{name}/{load['task_key']} skips its gate, so one task must run {path}"
            gate = found[0]
            assert {"task_key": load["task_key"]} in gate.get("depends_on", []), (
                f"{name}/{gate['task_key']} must depend on {load['task_key']}, or it can run before the load finishes")
            assert gate.get("run_if") == "ALL_SUCCESS"
            if not load.get("disabled"):
                assert not gate.get("disabled"), f"{name}/{load['task_key']} runs but its gate is disabled"


def test_job_loads_leave_table_setup_to_explicit_sql_tasks(jobs):
    for name, task in loads(jobs):
        assert "--no-setup" in task["spark_python_task"]["parameters"], (
            f"{name}/{task['task_key']} would repeat shared DDL inside a parallel source load")


def test_control_columns_are_added_before_any_view_is_replaced(jobs, repo_root):
    """A view that reads a column added after its table was created fails on older tables
    unless the column is added first; CREATE TABLE IF NOT EXISTS never adds it."""
    for name, job in jobs.items():
        tasks = {task["task_key"]: task for task in job["tasks"]}

        def upstream(key):
            seen, todo = set(), [key]
            while todo:
                for dep in tasks[todo.pop()].get("depends_on", []):
                    if dep["task_key"] not in seen:
                        seen.add(dep["task_key"])
                        todo.append(dep["task_key"])
            return seen

        adders = [key for key, task in tasks.items()
                  if task.get("spark_python_task", {}).get("parameters", [None])[0] == "columns"]
        assert len(adders) == 1, f"{name}: expected one control-columns task, found {adders}"
        assert not tasks[adders[0]].get("disabled")
        assert argument(tasks[adders[0]], "--backend") == "spark"
        tables = {key for key, task in tasks.items()
                  if task.get("sql_task", {}).get("file", {}).get("path", "").startswith("etl/01_control/0")
                  and "CREATE OR REPLACE VIEW" not in (repo_root / task["sql_task"]["file"]["path"]).read_text()}
        assert tables <= upstream(adders[0]), f"{name}: add columns only after every control table exists"
        for key, task in tasks.items():
            path = task.get("sql_task", {}).get("file", {}).get("path", "")
            if "CREATE OR REPLACE VIEW" in ((repo_root / path).read_text() if path else ""):
                assert adders[0] in upstream(key), f"{name}/{key} replaces a view before columns are added"


def test_placeholder_tasks_are_disabled(jobs, repo_root):
    for name, task in sql_tasks(jobs):
        path = repo_root / task["sql_task"]["file"]["path"]
        if path.read_text(encoding="utf-8").lstrip().startswith("-- PLACEHOLDER:"):
            assert task.get("disabled") is True, f"{name}/{task['task_key']} runs placeholder SQL"


def test_sql_tasks_run_committed_files_on_the_warehouse(jobs, repo_root):
    tasks = list(sql_tasks(jobs))
    assert tasks, "no SQL task found"
    for name, task in tasks:
        sql = task["sql_task"]
        assert sql["file"]["source"] == "GIT", f"{name}/{task['task_key']} must read its file from the commit"
        assert (repo_root / sql["file"]["path"]).is_file(), f"{name}/{task['task_key']}: {sql['file']['path']} missing"
        assert sql["warehouse_id"] == "${var.warehouse_id}", f"{name}/{task['task_key']} must use the warehouse variable"


def test_sql_tasks_share_the_run_id(jobs):
    """A gate's results carry :run_id, and its last statement fails on a FAIL recorded under it."""
    for name, job in jobs.items():
        parameters = {p["name"]: p["default"] for p in job.get("parameters", [])}
        assert parameters.get("run_id") == "{{job.run_id}}", f"{name}: job parameter run_id must be {{{{job.run_id}}}}"


def test_every_contract_has_a_task(jobs, repo_root):
    sources = {argument(t, "--source") for _, t in python_tasks(jobs)
               if t["spark_python_task"]["python_file"] == "src/ingestion/cli.py"}
    contracts = {p.stem for p in (repo_root / "config" / "ingestion").glob("*.json")}
    assert contracts <= sources, f"contracts with no job task: {sorted(contracts - sources)}"


def test_no_schedules_during_development(jobs):
    for name, job in jobs.items():
        assert "schedule" not in job and "trigger" not in job and "continuous" not in job, (
            f"{name}: no schedules during development (docs/operations/workflow.md, Part 5)")


def test_one_run_at_a_time(jobs):
    for name, job in jobs.items():
        assert job.get("max_concurrent_runs") == 1, f"{name}: two concurrent runs could both load one batch"


def test_each_silver_build_follows_its_bronze_gate_and_precedes_its_own_gate(jobs, repo_root):
    """A source's Silver runs only after its Bronze gate passed, and its gate checks it right after
    (D-025). Every Silver mapping has both tasks."""
    mappings = sorted(p.stem for p in (repo_root / "config" / "mappings").glob("*.json"))
    assert mappings, "no Silver mapping found"
    registry = yaml.safe_load((repo_root / "config" / "tables.yml").read_text(encoding="utf-8"))
    source_tables = {entry["source_id"]: entry for entry in registry["source_tables"]}
    for name, job in jobs.items():
        keys = [t["task_key"] for t in job["tasks"]]
        for source in mappings:
            contract = json.loads((repo_root / "config" / "ingestion" / f"{source}.json").read_text())
            bronze_gate = f"90_validate_{contract['bronze_table']}"
            silver = source_tables[source]["silver"]
            build, gate = Path(silver["clean_file"]).stem, f"90_validate_{silver['table']}"
            assert keys[keys.index(bronze_gate) + 1: keys.index(bronze_gate) + 3] == [build, gate], (
                f"{name}: {source} needs {build} then {gate} right after {bronze_gate}")
            for key in (build, gate):
                task = job["tasks"][keys.index(key)]
                assert task["sql_task"]["file"]["path"] == f"etl/03_silver/{key}.sql"
                assert task.get("run_if") == "ALL_SUCCESS", f"{name}/{key} must run only if the task before succeeded"


def test_sql_tasks_get_the_environment(jobs):
    for name, job in jobs.items():
        parameters = {p["name"]: p["default"] for p in job.get("parameters", [])}
        assert parameters.get("environment") == "${bundle.target}", f"{name}: job parameter environment"


def test_the_job_is_named_for_the_whole_pipeline(jobs):
    assert list(jobs) == ["edu_access_pipeline"]
    assert jobs["edu_access_pipeline"]["name"] == "edu_access_pipeline"


def test_dev_target_names_the_project_workspace(bundle, project):
    dev = bundle["targets"]["dev"]
    assert dev["mode"] == "development"
    assert dev["workspace"]["host"] == project["workspace_host"]


def test_every_gate_result_stamps_the_revision_from_the_parameter(repo_root):
    """Checked per INSERT: one check out of several with a literal revision is enough to break lineage."""
    inserts = 0
    for path in gates(repo_root):
        for statement in split_statements(path.read_text(encoding="utf-8")):
            if not re.match(r"INSERT\s+INTO\s+\S*data_quality_results\b", statement, re.IGNORECASE):
                continue
            inserts += 1
            values = statement[statement.index(")") + 1:]  # after the column list
            assert ":code_revision" in values, f"{path.name}: a result does not read :code_revision"
            assert ":run_id" in values, f"{path.name}: a result does not read :run_id"
            assert "'UNSET'" not in values, f"{path.name} writes the sentinel instead of the parameter"
    assert inserts, "no gate writes to data_quality_results"


def test_gate_inserts_name_their_columns(repo_root):
    """A positional INSERT would put values in the wrong columns if a table's columns are ever reordered."""
    for path in sorted(repo_root.glob("etl/*/*.sql")):
        for statement in split_statements(path.read_text(encoding="utf-8")):
            match = re.match(r"INSERT\s+INTO\s+\S+\s*(\()?", statement, re.IGNORECASE)
            if match:
                assert match.group(1), f"{path.name}: INSERT must list its columns"
                head = statement[match.end():statement.index(")", match.end())]
                names = [c.strip() for c in head.split(",")]
                assert all(re.fullmatch(r"`?\w+`?", c) for c in names), f"{path.name}: column list holds {names}"


CREATES = re.compile(r"CREATE\s+(?:OR\s+REPLACE\s+)?(TABLE|VIEW|SCHEMA)\s+(?:IF\s+NOT\s+EXISTS\s+)?(\S+)", re.IGNORECASE)
OWNS = re.compile(r"ALTER\s+(TABLE|VIEW|SCHEMA)\s+(\S+)\s+OWNER\s+TO\s+`([^`]+)`", re.IGNORECASE)
DYNAMIC_TABLE_OWNS = re.compile(
    r"SET\s+VARIABLE\s+\S+\s*=\s*'ALTER TABLE '\s*\|\|\s*session\.(\w+)"
    r"\s*\|\|\s*' OWNER TO `([^`]+)`'",
    re.IGNORECASE,
)


def test_every_created_object_is_owned_by_the_team_group(repo_root, project):
    """Unity Catalog makes the creator the owner, and a dev job runs as its deployer: without
    these statements only one person could read or load the tables (found on the first
    Databricks run, 2026-10-06). D-009: objects belong to the group."""
    created = 0
    for path in sorted(repo_root.glob("etl/*/*.sql")):
        statements = split_statements(path.read_text(encoding="utf-8"))
        owned = {(kind.upper(), name): group for s in statements for kind, name, group in OWNS.findall(s)}
        owned.update(
            {("TABLE", f"IDENTIFIER(session.{variable})"): group
             for s in statements for variable, group in DYNAMIC_TABLE_OWNS.findall(s)}
        )
        for s in statements:
            match = CREATES.match(s)
            if not match:
                continue
            created += 1
            key = (match.group(1).upper(), match.group(2))
            assert owned.get(key) == project["owner_group"], f"{path.name}: {key} is not handed to {project['owner_group']}"
    assert created, "no CREATE statements found"


def test_bronze_ddl_uses_the_project_group(project):
    from src.ingestion.bronze import OWNER_GROUP
    assert OWNER_GROUP == project["owner_group"]


def test_delivered_sources_are_not_disabled(jobs, repo_root):
    """A source with a contract and real Bronze SQL already runs on main; disabling its
    create, load or gate task would quietly stop a delivered source."""
    registry = yaml.safe_load((repo_root / "config" / "tables.yml").read_text(encoding="utf-8"))
    for entry in registry["source_tables"]:
        source, bronze = entry["source_id"], entry["bronze"]
        ddl = repo_root / "etl" / "02_bronze" / bronze["create_file"]
        if not (repo_root / "config" / "ingestion" / f"{source}.json").is_file():
            continue
        if ddl.read_text(encoding="utf-8").lstrip().startswith("-- PLACEHOLDER:"):
            continue
        for name, job in jobs.items():
            lane = [task for task in job["tasks"]
                    if task.get("sql_task", {}).get("file", {}).get("path") in (
                        f"etl/02_bronze/{bronze['create_file']}", f"etl/02_bronze/90_validate_{bronze['table']}.sql")
                    or ("spark_python_task" in task and argument(task, "--source") == source)]
            assert len(lane) == 3, f"{name}: {source} should have a create, load and gate task, found {len(lane)}"
            for task in lane:
                assert task.get("disabled") is not True, f"{name}/{task['task_key']} disables delivered source {source}"


DEPLOYER = "${workspace.current_user.userName}"


def test_failed_and_slow_runs_email_the_deployer(jobs):
    """Resolved at deploy time, so whoever deployed hears about their own runs and no
    address is committed to a public repository (D-043)."""
    for name, job in jobs.items():
        emails = job.get("email_notifications", {})
        assert emails.get("on_failure") == [DEPLOYER], f"{name}: a failed run must email the deployer"
        assert emails.get("on_duration_warning_threshold_exceeded") == [DEPLOYER], (
            f"{name}: a slow run must email the deployer")
        settings = job.get("notification_settings", {})
        assert settings.get("no_alert_for_canceled_runs") is True, f"{name}: a run someone cancelled is not a failure"


def test_no_email_address_is_committed(repo_root):
    text = (repo_root / "databricks.yml").read_text(encoding="utf-8")
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text), "databricks.yml must not hold an email address"


def test_slow_runs_warn_before_they_time_out(bundle, jobs):
    """Both thresholds are variables, so an alert can be tested with a --var override; the
    warning must come first, or a slow run would only ever be reported as a failure."""
    variables = bundle["variables"]
    warning = int(variables["duration_warning_seconds"]["default"])
    timeout = int(variables["job_timeout_seconds"]["default"])
    assert 0 < warning < timeout
    for name, job in jobs.items():
        assert job.get("timeout_seconds") == "${var.job_timeout_seconds}", f"{name}: no run timeout"
        rules = job.get("health", {}).get("rules", [])
        assert {"metric": "RUN_DURATION_SECONDS", "op": "GREATER_THAN",
                "value": "${var.duration_warning_seconds}"} in rules, f"{name}: no run-duration warning"
