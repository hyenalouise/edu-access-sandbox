"""The prod deploy refuses anything but a clean, pushed main (D-063). Runs on throwaway git repositories."""

import subprocess

import pytest

from src.job import deploy_prod


BUNDLE = """targets:
  prod:
    variables:
      team_notification_destination_id: "{destination}"
"""


def run(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def clone(tmp_path):
    """A clone of a one-commit origin, on main and level with origin/main."""
    origin = tmp_path / "origin"
    origin.mkdir()
    run(origin, "init", "--quiet", "--initial-branch", "main")
    (origin / "databricks.yml").write_text(BUNDLE.format(destination="d-123"))
    run(origin, "add", "databricks.yml")
    run(origin, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "--quiet", "-m", "first")
    work = tmp_path / "work"
    run(tmp_path, "clone", "--quiet", str(origin), str(work))
    return work


def commit(repo, message):
    run(repo, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "--quiet", "--allow-empty", "-m", message)


def test_clean_pushed_main_passes(clone):
    assert deploy_prod.problems(clone) == []
    assert deploy_prod.main(["--check"], repo=clone) == 0


def test_another_branch_is_refused(clone):
    run(clone, "switch", "--quiet", "-c", "feat/x")
    assert any("not 'main'" in p for p in deploy_prod.problems(clone))


def test_uncommitted_changes_are_refused(clone):
    (clone / "new.txt").write_text("x")
    assert any("uncommitted" in p for p in deploy_prod.problems(clone))


def test_unpushed_commit_is_refused(clone):
    commit(clone, "local only")
    assert any("is not origin/main" in p for p in deploy_prod.problems(clone))


def test_blank_team_destination_is_refused(clone):
    (clone / "databricks.yml").write_text(BUNDLE.format(destination=""))
    assert "targets.prod.variables.team_notification_destination_id in databricks.yml is blank" in (
        deploy_prod.problems(clone))


def test_refusal_runs_no_databricks_command(clone, monkeypatch):
    calls = []
    monkeypatch.setattr(deploy_prod, "problems", lambda repo: ["refused for the test"])
    monkeypatch.setattr(deploy_prod.subprocess, "run", lambda *args, **kwargs: calls.append(args))
    assert deploy_prod.main([], repo=clone) == 2
    assert calls == []
