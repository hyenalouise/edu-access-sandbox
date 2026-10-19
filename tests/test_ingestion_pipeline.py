"""Ingestion runs end to end: idempotency, incremental loads, revisions, failure, recovery.

Every test runs the real etl/01_control and etl/02_bronze SQL on an in-memory
DuckDB, against made-up deliveries in a temporary landing folder, inside a
throwaway repository root whose contract approves those deliveries.

test_idempotency_demonstration walks the whole story in order; the others
check one behavior each.
"""

import json
import shutil

import pytest

from factories.deped_deliveries import (
    REPO_ROOT, approve, columns, empty_config, fake_repo, make_delivery, make_rows, real_config, write_config,
)
from src.ingestion import cli, control, pipeline
from src.ingestion.bronze import bronze_ddl, bronze_gate
from src.ingestion.errors import IngestionError
from src.ingestion.pipeline import IngestionRun
from src.ingestion.store import DuckDBStore

REVISION = "a" * 40
BRONZE = "edu_access.`02-bronze`.deped_enrollment_raw"
CONTROL = "edu_access.`01-control`"


class SimulatedCrash(BaseException):
    """The process dying mid-load. BaseException, so the pipeline cannot catch and record it."""


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


class Env:
    def __init__(self, tmp_path):
        self.config = empty_config()
        self.landing = tmp_path / "landing"
        self.inbox = self.landing / "deped"
        self.repo = fake_repo(tmp_path / "repo", self.config)
        self.store = DuckDBStore()
        self.tmp = tmp_path

    def deliver(self, school_year, schema_version="v1", encoding="utf-8", folder="original", approve_it=True, **kwargs):
        path = make_delivery(self.inbox / folder, school_year, schema_version, encoding=encoding, **kwargs)
        if approve_it:
            self.approve(path, school_year, schema_version, encoding)
        return path

    def approve(self, path, school_year, schema_version="v1", encoding="utf-8", **kwargs):
        entry = approve(self.config, path, school_year, schema_version, encoding, **kwargs)
        write_config(self.repo, self.config)
        return entry

    def run(self, rerun=(), hook=None, environment="local", run_gate=True, setup_tables=True, job_run_id=None):
        return IngestionRun(self.store, self.repo, "deped_enrollment", self.landing, environment, REVISION,
                            rerun_batch_ids=rerun, hook=hook, run_gate=run_gate, setup_tables=setup_tables,
                            job_run_id=job_run_id).execute()

    def q(self, sql):
        return self.store.query(sql)

    def one(self, sql):
        return self.q(sql)[0][0]

    def bronze_rows(self, where="TRUE"):
        return self.one(f"SELECT COUNT(*) FROM {BRONZE} WHERE {where}")

    def batch(self, school_year, version=1):
        rows = self.store.records(
            f"SELECT * FROM {CONTROL}.ingestion_batches WHERE school_year = '{school_year}' AND delivery_version = {version}")
        return rows[0] if rows else None


def outcome(summary, school_year):
    return next(o for o in summary.outcomes if o.school_year == school_year)


# --- The demonstration ---------------------------------------------------------

def test_idempotency_demonstration(env):
    # 1-2. Load one delivery; record its batch and Bronze row count.
    env.deliver("2023-24", n_rows=4)
    first = env.run()
    assert first.status == "succeeded"
    assert (outcome(first, "2023-24").action, outcome(first, "2023-24").load_type) == ("load", "initial")
    assert env.bronze_rows() == 4
    batch = env.batch("2023-24")
    assert (batch["status"], batch["source_rows"], batch["bronze_rows"]) == ("succeeded", 4, 4)

    # 3-4. Run exactly the same ingestion again: skipped, no new rows.
    second = env.run()
    assert second.status == "succeeded"
    assert (outcome(second, "2023-24").action, outcome(second, "2023-24").outcome) == ("skip", "skipped")
    assert env.bronze_rows() == 4

    # 5. The audit history says what happened, run by run.
    attempts = env.q(f"SELECT run_id, action, outcome, rows_inserted FROM {CONTROL}.ingestion_batch_attempts "
                     "ORDER BY started_at_utc")
    assert [(a[0], a[1], a[2], a[3]) for a in attempts] == [
        (first.run_id, "load", "succeeded", 4), (second.run_id, "skip", "skipped", 0)]
    assert env.one(f"SELECT COUNT(*) FROM {CONTROL}.pipeline_runs WHERE status = 'succeeded'") == 2

    # 6. A different school year loads as an incremental batch, leaving the first untouched.
    env.deliver("2024-25", n_rows=3, first_id=910001)
    third = env.run()
    assert (outcome(third, "2024-25").action, outcome(third, "2024-25").load_type) == ("load", "incremental")
    assert env.bronze_rows("school_year = '2023-24'") == 4
    assert env.one(f"SELECT COUNT(DISTINCT run_id) FROM {BRONZE} WHERE school_year = '2023-24'") == 1
    assert env.one(f"SELECT MIN(run_id) FROM {BRONZE} WHERE school_year = '2023-24'") == first.run_id

    # 7. Same file name, different bytes: not treated as the original.
    original = env.inbox / "original" / "Enrollment-in-SY-2024-2025.zip"
    make_delivery(env.inbox / "redownload", "2024-25", n_rows=5, first_id=910001)
    fourth = env.run()
    changed = next(o for o in fourth.outcomes if o.outcome == "blocked")
    assert (changed.archive_name, changed.load_type) == (original.name, "revision")
    assert "not approved" in changed.message
    assert fourth.status == "failed"
    assert env.bronze_rows("school_year = '2024-25'") == 3
    assert env.batch("2024-25")["status"] == "succeeded"


# --- One behavior each ----------------------------------------------------------

def test_provenance_is_complete_on_every_row(env):
    env.deliver("2025-26", "v2", encoding="cp1252", line_ending="\r\n")
    summary = env.run()
    row = env.store.records(f"SELECT * FROM {BRONZE} WHERE source_row_number = 1")[0]
    assert row["source_id"] == "deped_enrollment"
    assert row["source_system"] and row["source_url"].startswith("https://www.deped.gov.ph/")
    assert row["source_archive"] == "Enrollment-in-SY-2025-2026.zip"
    assert row["source_file"].endswith("/enrollment_2025-26.csv")
    assert (row["school_year"], row["delivery_version"], row["schema_version"]) == ("2025-26", 1, "v2")
    assert len(row["source_sha256"]) == 64 and len(row["schema_fingerprint"]) == 64
    assert (row["run_id"], row["code_revision"]) == (summary.run_id, REVISION)
    assert row["batch_id"].startswith("deped_enrollment__2025-26__")
    assert row["ingested_at_utc"] is not None
    assert row["barangay"] == "Doña Test"


def test_blanks_and_absent_columns_stay_distinct(env):
    env.deliver("2023-24")
    env.deliver("2025-26", "v2", encoding="cp1252")
    env.run()
    new_column = '"Modified Curricular Offering Classification"'
    assert env.bronze_rows(f"school_year = '2023-24' AND {new_column} IS NULL") == 3  # not in v1
    assert env.bronze_rows("street_address = ''") == 6  # blank as received
    assert env.bronze_rows("street_address IS NULL OR g11_unique_male IS NULL") == 0
    assert {r[0] for r in env.q(f"SELECT DISTINCT offers_es FROM {BRONZE}")} == {"True"}  # labels untouched


def test_batch_id_is_the_same_for_the_same_bytes(env):
    path = env.deliver("2023-24")
    env.run()
    first_id = env.batch("2023-24")["batch_id"]
    shutil.move(str(path), env.inbox / "moved.zip")  # same bytes, another name and folder
    env.run()
    assert env.one(f"SELECT COUNT(*) FROM {CONTROL}.ingestion_batches") == 1
    assert env.batch("2023-24")["batch_id"] == first_id


def test_discovery_does_not_hash_unrelated_zips_when_approved_files_are_present(env, monkeypatch):
    delivery = env.deliver("2023-24")
    unrelated = env.inbox / "NAT-Grade-6.zip"
    unrelated.write_bytes(b"not an enrollment delivery")
    hashed = []
    sha256_file = pipeline.sha256_file

    def record_hash(path):
        hashed.append(path)
        return sha256_file(path)

    monkeypatch.setattr(pipeline, "sha256_file", record_hash)
    discovered = pipeline.discover(env.config, env.landing)

    assert [path for _, path in discovered] == [delivery]
    assert hashed == [delivery]


def test_rerun_validates_again_and_adds_nothing(env):
    env.deliver("2023-24")
    env.run()
    bid = env.batch("2023-24")["batch_id"]
    summary = env.run(rerun=[bid])
    o = outcome(summary, "2023-24")
    assert (o.action, o.outcome, o.rows_inserted, o.bronze_rows) == ("rerun", "succeeded", 0, 3)
    assert env.bronze_rows() == 3
    assert env.batch("2023-24")["attempt_count"] == 2


def test_late_historical_year_is_a_backfill(env):
    env.deliver("2024-25")
    env.deliver("2025-26", "v2")
    env.run()
    env.deliver("2022-23", first_id=920001)
    summary = env.run()
    assert outcome(summary, "2022-23").load_type == "backfill"
    assert [o.action for o in summary.outcomes] == ["load", "skip", "skip"]
    assert env.bronze_rows() == 9


def test_approved_revision_keeps_both_versions(env):
    v1 = env.deliver("2025-26", "v2")
    env.run()
    revised = make_delivery(env.inbox / "2026-08-01", "2025-26", "v2", n_rows=5)
    env.approve(revised, "2025-26", "v2", delivery_version=2,
                supersedes=env.config["deliveries"][0]["archive_sha256"])
    summary = env.run()
    o = next(o for o in summary.outcomes if o.action == "load")
    assert (o.load_type, o.rows_inserted) == ("revision", 5)
    assert env.q(f"SELECT delivery_version, COUNT(*) FROM {BRONZE} GROUP BY 1 ORDER BY 1") == [(1, 3), (2, 5)]
    assert env.q(f"SELECT school_year, delivery_version FROM {CONTROL}.current_batches") == [("2025-26", 2)]
    assert v1.exists()


def test_rezipped_copy_of_a_loaded_file_is_skipped(env):
    env.deliver("2023-24")
    env.run()
    make_delivery(env.inbox / "copy", "2023-24", zip_folder="Enrollment-in-SY-2023-2024")
    summary = env.run()
    copy = next(o for o in summary.outcomes if o.message and "different zip" in o.message)
    assert copy.rows_inserted == 0
    assert summary.status == "succeeded"
    assert env.bronze_rows() == 3


def test_unknown_file_is_blocked_and_fails_the_run(env):
    env.deliver("2026-27", approve_it=False)
    summary = env.run()
    assert (summary.outcomes[0].outcome, summary.status) == ("blocked", "failed")
    assert env.one(f"SELECT error_code FROM {CONTROL}.ingestion_batches") == "unregistered_delivery"
    assert env.bronze_rows() == 0


def test_failed_batch_can_be_retried(env):
    path = env.deliver("2023-24")
    env.config["deliveries"][0]["row_count"] = 99  # an approval mistake
    write_config(env.repo, env.config)
    first = env.run()
    assert (outcome(first, "2023-24").outcome, first.status) == ("failed", "failed")
    assert env.bronze_rows() == 0  # nothing loaded when a pre-load check fails
    assert env.one(f"SELECT COUNT(*) FROM {CONTROL}.data_quality_results WHERE status = 'FAIL'") >= 1

    env.config["deliveries"][0]["row_count"] = 3  # fixed in review
    write_config(env.repo, env.config)
    second = env.run()
    o = outcome(second, "2023-24")
    assert (o.action, o.outcome, o.load_type) == ("retry", "succeeded", "initial")
    assert env.batch("2023-24")["attempt_count"] == 2
    assert path.exists()


def test_interrupted_load_is_recovered(env):
    env.deliver("2023-24")

    def crash(stage):
        if stage == "after_bronze_merge":
            raise SimulatedCrash()

    with pytest.raises(SimulatedCrash):
        env.run(hook=crash)
    assert env.batch("2023-24")["status"] == "loading"
    assert env.bronze_rows() == 3  # the MERGE committed before the crash...
    assert env.q(f"SELECT * FROM {CONTROL}.current_batches") == []  # ...but downstream cannot see it
    assert env.one(f"SELECT status FROM {CONTROL}.pipeline_runs") == "running"

    summary = env.run()
    o = outcome(summary, "2023-24")
    assert (o.action, o.outcome, o.rows_inserted, o.bronze_rows) == ("retry", "succeeded", 0, 3)
    assert env.bronze_rows() == 3


def test_batch_is_invisible_downstream_until_its_last_write(env):
    """Marking a batch succeeded is the final write. A crash any time before it,
    even after reconciliation passed, leaves the batch out of current_batches."""
    env.deliver("2023-24")

    def crash(stage):
        if stage == "reconciled":
            raise SimulatedCrash()

    with pytest.raises(SimulatedCrash):
        env.run(hook=crash)
    assert env.batch("2023-24")["status"] == "loading"
    assert env.q(f"SELECT * FROM {CONTROL}.current_batches") == []


def test_partial_write_is_completed_without_duplicates(env):
    env.deliver("2023-24", n_rows=6)

    def lose_rows(stage):
        if stage == "after_bronze_merge":
            env.store.sql(f"DELETE FROM {BRONZE} WHERE source_row_number > 2")
            raise SimulatedCrash()

    with pytest.raises(SimulatedCrash):
        env.run(hook=lose_rows)
    assert env.bronze_rows() == 2

    o = outcome(env.run(), "2023-24")
    assert (o.outcome, o.rows_inserted, o.bronze_rows) == ("succeeded", 4, 6)
    assert env.one(f"SELECT COUNT(DISTINCT source_row_number) FROM {BRONZE}") == 6


def test_reconciliation_failure_keeps_batch_out_of_downstream(env):
    env.deliver("2023-24")

    def lose_a_row(stage):
        if stage == "after_bronze_merge":
            env.store.sql(f"DELETE FROM {BRONZE} WHERE source_row_number = 1")

    summary = env.run(hook=lose_a_row)
    o = outcome(summary, "2023-24")
    assert (o.outcome, summary.status) == ("failed", "failed")
    assert env.batch("2023-24")["error_code"] == "reconciliation_failed"
    assert env.q(f"SELECT * FROM {CONTROL}.current_batches") == []
    assert summary.gate_error and "Bronze gate failed" in summary.gate_error


def test_source_duplicates_are_kept_and_flagged(env):
    rows = make_rows(columns("v1"))
    rows.append(list(rows[0]))
    env.deliver("2023-24", rows=rows)
    summary = env.run()
    assert summary.status == "succeeded"
    assert env.bronze_rows("school_id = '900001'") == 2
    warns = {r[0] for r in env.q(f"SELECT check_name FROM {CONTROL}.data_quality_results WHERE status = 'WARN'")}
    assert warns == {"school_id_unique_in_file", "duplicate_rows_in_file"}


def test_undocumented_drift_fails_the_batch(env):
    env.deliver("2026-27", "v2", header=columns("v2") + ["g13_male"])
    summary = env.run()
    o = outcome(summary, "2026-27")
    assert (o.outcome, summary.status) == ("failed", "failed")
    assert env.batch("2026-27")["error_code"] == "unknown_schema_drift"
    assert env.bronze_rows() == 0


def test_a_new_schema_version_grows_bronze_from_the_contract(env):
    env.deliver("2025-26", "v2")
    env.run()
    env.config["schema_versions"]["v3"] = {"first_school_year": "2026-27", "note": "test",
                                            "columns": columns("v2") + ["g13_male"]}
    env.deliver("2026-27", "v3", header=columns("v2") + ["g13_male"], first_id=930001)
    summary = env.run()
    assert outcome(summary, "2026-27").outcome == "succeeded"
    assert env.bronze_rows("g13_male IS NULL") == 3   # SY 2025-26 rows: column absent
    assert env.bronze_rows("g13_male IS NOT NULL") == 3


def test_gate_catches_rows_without_a_batch(env):
    env.deliver("2023-24")
    env.run()
    env.store.sql(f"INSERT INTO {BRONZE} SELECT * REPLACE ('ghost' AS batch_id) FROM {BRONZE} LIMIT 1")
    summary = env.run()
    assert summary.status == "failed" and "Bronze gate failed" in summary.gate_error
    fails = env.q(f"SELECT check_name FROM {CONTROL}.data_quality_results "
                  f"WHERE run_id = '{summary.run_id}' AND status = 'FAIL' ORDER BY 1")
    assert fails == [("no_pipeline_duplicates",), ("rows_have_a_known_batch",), ("succeeded_batches_reconcile",)]


def test_gate_results_carry_the_code_revision(env):
    env.deliver("2023-24")
    summary = env.run()
    revisions = env.q(f"SELECT DISTINCT code_revision FROM {CONTROL}.data_quality_results "
                      f"WHERE run_id = '{summary.run_id}'")
    assert revisions == [(REVISION,)]


def test_the_gate_can_run_as_its_own_step(env):
    """With run_gate=False (the job's --no-gate), loading does not run the Bronze gate; the job runs
    the same SQL file as the next task, under the job's run_id, and that task fails on a FAIL."""
    env.deliver("2023-24")
    env.run()
    env.store.sql(f"INSERT INTO {BRONZE} SELECT * REPLACE ('ghost' AS batch_id) FROM {BRONZE} LIMIT 1")
    summary = env.run(run_gate=False)
    assert summary.status == "succeeded" and summary.gate_error is None
    assert env.one(f"SELECT COUNT(*) FROM {CONTROL}.data_quality_results WHERE run_id = '{summary.run_id}' "
                   "AND check_name = 'rows_have_a_known_batch'") == 0
    gate = env.repo / "etl" / "02_bronze" / "90_validate_deped_enrollment_raw.sql"
    with pytest.raises(Exception, match="Bronze gate failed"):
        env.store.run_file(gate, {"run_id": "job-run-1", "code_revision": REVISION})
    assert env.one(f"SELECT status FROM {CONTROL}.data_quality_results WHERE run_id = 'job-run-1' "
                   "AND check_name = 'rows_have_a_known_batch'") == "FAIL"


def test_a_job_load_can_be_joined_to_its_gate_task(env):
    """The job's load and its gate task have different run ids; job_run_id on pipeline_runs links
    them, so a load's true outcome is its run row plus its gate's rows (D-020)."""
    env.deliver("2023-24")
    manual = env.run()
    loaded = env.run(run_gate=False, job_run_id="job-run-7")
    gate = env.repo / "etl" / "02_bronze" / "90_validate_deped_enrollment_raw.sql"
    env.store.run_file(gate, {"run_id": "job-run-7", "code_revision": REVISION})
    assert env.one(f"SELECT job_run_id FROM {CONTROL}.pipeline_runs WHERE run_id = '{manual.run_id}'") is None
    assert env.q(f"""
        SELECT r.status, COUNT(q.check_name), COUNT_IF(q.status = 'FAIL')
        FROM {CONTROL}.pipeline_runs AS r
        JOIN {CONTROL}.data_quality_results AS q ON q.run_id = r.job_run_id AND q.source_id = r.source_id
        WHERE r.run_id = '{loaded.run_id}' AND q.layer = 'bronze'
        GROUP BY r.status""") == [("succeeded", 3, 0)]


def test_columns_adds_what_older_control_tables_lack(tmp_path):
    """Tables created before D-018 and D-020 lack their columns; `cli.py columns` adds them,
    and running it again changes nothing."""
    db = tmp_path / "t.duckdb"
    store = DuckDBStore(db)
    for path in sorted((REPO_ROOT / "etl" / "01_control").glob("0[1-4]_*.sql")):
        store.run_file(path)
    for table, columns in control.ADDED_COLUMNS.items():
        for name, _ in columns:
            store.sql(f"ALTER TABLE {CONTROL}.{table} DROP COLUMN {name}")
    store.close()
    for _ in range(2):
        assert cli.main(["columns", "--db", str(db)]) == 0
    store = DuckDBStore(db)
    for table, columns in control.ADDED_COLUMNS.items():
        have = {name for name, _ in store.columns("01-control", table)}
        assert {name for name, _ in columns} <= have, table
    store.close()


def test_an_approved_file_missing_from_landing_is_reported(env):
    env.deliver("2023-24")
    gone = env.deliver("2024-25", first_id=910001)
    gone.unlink()
    summary = env.run()
    assert summary.missing_deliveries == ["Enrollment-in-SY-2024-2025.zip"]
    assert summary.status == "succeeded"  # nothing is loadable from it, and nothing else is blocked
    assert env.one(f"SELECT status FROM {CONTROL}.data_quality_results "
                   "WHERE check_name = 'approved_deliveries_present'") == "WARN"


def test_prod_refuses_a_source_that_is_not_accepted(env):
    with pytest.raises(IngestionError) as e:
        env.run(environment="prod")
    assert e.value.code == "source_not_accepted"


def test_missing_landing_folder_fails_the_run(env):
    with pytest.raises(IngestionError) as e:
        env.run()
    assert e.value.code == "missing_landing"
    assert env.one(f"SELECT status FROM {CONTROL}.pipeline_runs") == "failed"


# --- The committed SQL and the command line --------------------------------------

CONTRACTS = sorted((REPO_ROOT / "config" / "ingestion").glob("*.json"))


@pytest.mark.parametrize("kind, pattern, generate", [("ddl", "[0-8][0-9]_create", bronze_ddl), ("gate", "90_validate", bronze_gate)])
@pytest.mark.parametrize("contract", CONTRACTS, ids=lambda p: p.stem)
def test_bronze_sql_matches_the_contract(contract, kind, pattern, generate):
    """The table definition and the gate are generated from each contract, never hand-edited."""
    config = json.loads(contract.read_text(encoding="utf-8"))
    matches = sorted((REPO_ROOT / "etl" / "02_bronze").glob(f"{pattern}_{config['bronze_table']}.sql"))
    assert len(matches) == 1, f"expected one {pattern}_{config['bronze_table']}.sql; found {matches}"
    path = matches[0]
    assert path.read_text(encoding="utf-8") == generate(config), (
        f"Regenerate: python -m src.ingestion.cli {kind} --source {config['source_id']} > {path.relative_to(REPO_ROOT)}")


def test_cli_blocks_an_unapproved_file(tmp_path, capsys):
    make_delivery(tmp_path / "raw" / "deped", "2030-31")
    code = cli.main(["ingest", "--source", "deped_enrollment", "--landing", str(tmp_path / "raw"),
                     "--db", str(tmp_path / "t.duckdb")])
    assert code == 1
    assert "blocked" in capsys.readouterr().out
    assert cli.main(["status", "--source", "deped_enrollment", "--db", str(tmp_path / "t.duckdb")]) == 0


def test_cli_can_leave_the_gate_to_the_next_task(tmp_path, capsys):
    raw = tmp_path / "raw"
    (raw / "deped").mkdir(parents=True)
    args = ["ingest", "--source", "deped_enrollment", "--landing", str(raw), "--db", str(tmp_path / "t.duckdb")]
    assert cli.main([*args, "--no-gate"]) == 0
    store = DuckDBStore(tmp_path / "t.duckdb")
    assert store.query(f"SELECT COUNT(*) FROM {CONTROL}.data_quality_results WHERE layer = 'bronze' "
                       "AND check_name = 'no_pipeline_duplicates'") == [(0,)]
    store.close()
    assert cli.main(args) == 0  # without the flag, the gate runs inside the task, as before
    store = DuckDBStore(tmp_path / "t.duckdb")
    assert store.query(f"SELECT COUNT(*) FROM {CONTROL}.data_quality_results WHERE layer = 'bronze' "
                       "AND check_name = 'no_pipeline_duplicates'") == [(1,)]
    store.close()


def test_cli_exit_codes_for_setup_problems(tmp_path):
    db = ["--db", str(tmp_path / "t.duckdb")]
    assert cli.main(["ingest", "--source", "deped_enrollment", "--landing", str(tmp_path / "none"), *db]) == 3
    (tmp_path / "raw" / "deped").mkdir(parents=True)
    landing = ["--landing", str(tmp_path / "raw")]
    assert cli.main(["ingest", "--source", "deped_enrollment", "--environment", "dev",
                     "--code-revision", "UNSET", *landing, *db]) == 2
    assert cli.main(["ingest", "--source", "deped_enrollment", "--environment", "dev",
                     "--code-revision", REVISION, *landing, *db]) == 0
    assert cli.main(["ingest", "--source", "no_such_source", *landing, *db]) == 2


# --- SY 2020-21 to 2022-23, the backfilled deliveries ---------------------------------

def test_the_contract_approves_the_six_deliveries_on_the_source_card():
    """Checksums, row counts and encodings are copied from the profiled source card, never typed afresh."""
    import yaml
    config = real_config()
    years = {d["school_year"]: d for d in config["deliveries"]}
    assert {sy: (d["delivery_version"], d["schema_version"], d["encoding"], d["row_count"]) for sy, d in years.items()} == {
        "2020-21": (1, "v1", "utf-8", 60957),
        "2021-22": (1, "v1", "utf-8", 60429),
        "2022-23": (1, "v1", "utf-8", 60137),
        "2023-24": (1, "v1", "utf-8", 60167),
        "2024-25": (1, "v1", "utf-8", 60129),
        "2025-26": (1, "v2", "cp1252", 60204),
    }
    card = (REPO_ROOT / "docs" / "data" / "source-inventory" / "deped_enrollment" / "README.md").read_text(encoding="utf-8")
    lines = card.splitlines()
    for d in config["deliveries"]:
        archive = next(line for line in lines if line.startswith(f"| `{d['archive']}` |"))
        member = next(line for line in lines if line.startswith(f"| ↳ `{d['data_member']}` |"))
        assert f"`{d['archive_sha256']}`" in archive
        assert f"`{d['data_member_sha256']}`" in member and f"| {d['row_count']:,} |" in member
        assert all(f"`{sha}`" in card for sha in d["document_sha256"].values())
    registry = yaml.safe_load((REPO_ROOT / "config" / "tables.yml").read_text(encoding="utf-8"))
    entry = next(s for s in registry["source_tables"] if s["source_id"] == "deped_enrollment")
    assert entry["scope"]["school_years"] == sorted(years)


def test_sy_2020_21_to_2022_23_have_the_v1_header():
    """The same 78 columns, in the same order, as SY 2023-24 (profile O-7): no new schema version."""
    config = real_config()
    by_year = {d["school_year"]: d["schema_version"] for d in config["deliveries"]}
    assert by_year["2020-21"] == by_year["2021-22"] == by_year["2022-23"] == by_year["2023-24"] == "v1"
    assert len(config["schema_versions"]["v1"]["columns"]) == 78
    assert config["schema_versions"]["v1"]["first_school_year"] == "2020-21"


def test_sy_2020_21_loads_as_a_v1_backfill_and_leaves_the_later_years_untouched(env):
    env.deliver("2023-24", n_rows=4)
    env.deliver("2024-25", n_rows=3, first_id=910001)
    env.deliver("2025-26", "v2", encoding="cp1252", line_ending="\r\n", first_id=920001)
    assert env.run().status == "succeeded"
    later = f"SELECT * FROM {BRONZE} WHERE school_year <> '2020-21' ORDER BY source_sha256, source_row_number"
    batches = (f"SELECT school_year, batch_id, status, load_type, source_rows, bronze_rows, first_run_id "
               f"FROM {CONTROL}.ingestion_batches ORDER BY school_year")
    before, batches_before = env.q(later), env.q(batches)

    env.deliver("2020-21", n_rows=5, first_id=880001)
    added = env.run()
    assert added.status == "succeeded"
    assert {o.school_year: (o.action, o.load_type) for o in added.outcomes if o.action == "load"} == {
        "2020-21": ("load", "backfill")}
    assert env.q(later) == before                                  # the three later years: not one value changed
    assert env.q(batches)[1:] == batches_before
    assert env.q(f"SELECT DISTINCT schema_version FROM {BRONZE} WHERE school_year = '2020-21'") == [("v1",)]
    assert env.one(f"SELECT COUNT(DISTINCT schema_fingerprint) FROM {BRONZE} "
                   "WHERE school_year IN ('2020-21', '2023-24')") == 1
    assert env.bronze_rows("school_year = '2020-21' AND g11_sshs_acad_male IS NULL") == 5    # not in v1

    # Per-year reconciliation: every year's Bronze rows equal its file and its approved row_count.
    per_year = env.q(f"SELECT b.school_year, b.expected_rows, b.source_rows, b.bronze_rows, COUNT(r.school_id) "
                     f"FROM {CONTROL}.ingestion_batches AS b JOIN {BRONZE} AS r ON r.batch_id = b.batch_id "
                     "GROUP BY ALL ORDER BY 1")
    assert per_year == [("2020-21", 5, 5, 5, 5), ("2023-24", 4, 4, 4, 4), ("2024-25", 3, 3, 3, 3),
                        ("2025-26", 3, 3, 3, 3)]
    results = env.q(f"SELECT check_name, status FROM {CONTROL}.data_quality_results "
                    f"WHERE run_id = '{added.run_id}' AND batch_id IS NULL ORDER BY 1")
    assert ("succeeded_batches_reconcile", "PASS") in results and all(s != "FAIL" for _, s in results)

    # A rerun inserts nothing and changes nothing.
    content = f"SELECT * EXCLUDE (run_id, ingested_at_utc) FROM {BRONZE} ORDER BY source_sha256, source_row_number"
    snapshot = env.q(content)
    again = env.run()
    assert again.status == "succeeded"
    assert {(o.action, o.rows_inserted) for o in again.outcomes} == {("skip", 0)}
    assert env.q(content) == snapshot and env.bronze_rows() == 15


def test_sy_2021_22_and_2022_23_load_as_v1_backfills_and_leave_the_other_years_untouched(env):
    env.deliver("2020-21", n_rows=5, first_id=880001)
    env.deliver("2023-24", n_rows=4)
    env.deliver("2024-25", n_rows=3, first_id=910001)
    env.deliver("2025-26", "v2", encoding="cp1252", line_ending="\r\n", first_id=920001)
    assert env.run().status == "succeeded"
    others = (f"SELECT * FROM {BRONZE} WHERE school_year NOT IN ('2021-22', '2022-23') "
              "ORDER BY source_sha256, source_row_number")
    batches = (f"SELECT school_year, batch_id, status, load_type, source_rows, bronze_rows, first_run_id "
               f"FROM {CONTROL}.ingestion_batches ORDER BY school_year")
    before, batches_before = env.q(others), env.q(batches)

    env.deliver("2021-22", n_rows=2, first_id=860001)
    env.deliver("2022-23", n_rows=6, first_id=870001)
    added = env.run()
    assert added.status == "succeeded"
    assert {o.school_year: (o.action, o.load_type) for o in added.outcomes if o.action == "load"} == {
        "2021-22": ("load", "backfill"), "2022-23": ("load", "backfill")}
    assert env.q(others) == before                                 # the four other years: not one value changed
    assert [b for b in env.q(batches) if b[0] not in ("2021-22", "2022-23")] == batches_before
    assert env.q(f"SELECT DISTINCT schema_version FROM {BRONZE} WHERE school_year IN ('2021-22', '2022-23')") == [("v1",)]
    assert env.one(f"SELECT COUNT(DISTINCT schema_fingerprint) FROM {BRONZE} "
                   "WHERE school_year IN ('2020-21', '2021-22', '2022-23', '2023-24')") == 1

    per_year = env.q(f"SELECT b.school_year, b.expected_rows, b.source_rows, b.bronze_rows, COUNT(r.school_id) "
                     f"FROM {CONTROL}.ingestion_batches AS b JOIN {BRONZE} AS r ON r.batch_id = b.batch_id "
                     "GROUP BY ALL ORDER BY 1")
    assert per_year == [("2020-21", 5, 5, 5, 5), ("2021-22", 2, 2, 2, 2), ("2022-23", 6, 6, 6, 6),
                        ("2023-24", 4, 4, 4, 4), ("2024-25", 3, 3, 3, 3), ("2025-26", 3, 3, 3, 3)]
    results = env.q(f"SELECT check_name, status FROM {CONTROL}.data_quality_results "
                    f"WHERE run_id = '{added.run_id}' AND batch_id IS NULL ORDER BY 1")
    assert ("succeeded_batches_reconcile", "PASS") in results and all(s != "FAIL" for _, s in results)

    content = f"SELECT * EXCLUDE (run_id, ingested_at_utc) FROM {BRONZE} ORDER BY source_sha256, source_row_number"
    snapshot = env.q(content)
    again = env.run()
    assert again.status == "succeeded"
    assert {(o.action, o.rows_inserted) for o in again.outcomes} == {("skip", 0)}
    assert env.q(content) == snapshot and env.bronze_rows() == 23


def test_a_seven_digit_school_id_warns_in_bronze_and_keeps_the_row(env):
    """SY 2022-23 publishes 1404066 beside 404066 (profile O-1): Bronze keeps it and WARNs; Silver decides."""
    header = columns("v1")
    rows = make_rows(header, n_rows=2, first_id=404066)
    rows[1][header.index("school_id")] = "1404066"
    env.deliver("2022-23", rows=rows)
    summary = env.run()
    assert summary.status == "succeeded"
    assert env.bronze_rows("school_id = '1404066'") == 1
    checks = dict(env.q(f"SELECT check_name, status FROM {CONTROL}.data_quality_results "
                        f"WHERE run_id = '{summary.run_id}' AND batch_id IS NOT NULL"))
    assert checks["school_id_format"] == "WARN" and checks["school_id_not_blank"] == "PASS"
