"""Deploy the bundle to prod, only from a clean, pushed main (D-063).

    python -m src.job.deploy_prod            # check, then validate, deploy, summary
    python -m src.job.deploy_prod --check    # check only, deploy nothing

prod runs the commit it was deployed from (git_source.git_commit), so a deploy
from a branch, from uncommitted changes, or from a commit GitHub does not have
would put unreviewed or unreachable code in prod. Before any databricks
command this refuses unless:

- the current branch is main;
- the working tree has no uncommitted or untracked changes;
- HEAD equals origin/main after a fetch, so the commit is pushed and current.

The databricks commands always pass --target prod --profile reached-hq-prod.
Starting a run is left to the person deploying (docs/operations/runbook.md,
"Deploying to prod").
"""

import argparse
import inspect
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(inspect.currentframe().f_code.co_filename).resolve().parents[2]

TARGET = "prod"
PROFILE = "reached-hq-prod"
BRANCH = "main"


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def problems(repo, fetch=True):
    """Every reason this checkout must not deploy to prod; empty when it may."""
    found = []
    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if branch != BRANCH:
        found.append(f"on branch {branch!r}, not {BRANCH!r}")
    if git(repo, "status", "--porcelain"):
        found.append("the working tree has uncommitted or untracked changes")
    if fetch:
        git(repo, "fetch", "--quiet", "origin", BRANCH)
    head = git(repo, "rev-parse", "HEAD")
    remote = git(repo, "rev-parse", f"origin/{BRANCH}")
    if head != remote:
        found.append(f"HEAD {head[:7]} is not origin/{BRANCH} {remote[:7]}: pull, or push and merge first")
    return found


def main(argv=None, repo=REPO_ROOT):
    parser = argparse.ArgumentParser(prog="python -m src.job.deploy_prod", description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="only check the checkout; deploy nothing")
    args = parser.parse_args(argv)
    found = problems(repo)
    if found:
        for problem in found:
            print(f"refused: {problem}", file=sys.stderr)
        return 2
    commit = git(repo, "rev-parse", "HEAD")
    print(f"ok: clean {BRANCH} at {commit}, same as origin/{BRANCH}")
    if args.check:
        return 0
    for step in ("validate", "deploy", "summary"):
        command = ["databricks", "bundle", step, "--target", TARGET, "--profile", PROFILE]
        print("$ " + " ".join(command), flush=True)
        if subprocess.run(command, cwd=repo).returncode:
            return 1
    print(f"Deployed {commit} to {TARGET}. Check that git_commit and code_revision in the summary equal it.")
    return 0


if __name__ == "__main__":
    exit_code = main()
    if exit_code:
        sys.exit(exit_code)
