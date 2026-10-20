"""Keep the documentation navigable, free of retired paths, and in step with the repository."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote


REQUIRED_READMES = [
    Path("analysis/README.md"),
    Path("analysis/profiling/README.md"),
    Path("analysis/cross_source/README.md"),
    Path("config/README.md"),
    Path("config/ingestion/README.md"),
    Path("config/mappings/README.md"),
    Path("docs/README.md"),
    Path("docs/business/README.md"),
    Path("docs/data/README.md"),
    Path("docs/data/source-inventory/README.md"),
    Path("docs/data/cross-source/README.md"),
    Path("docs/governance/README.md"),
    Path("docs/operations/README.md"),
    Path("evidence/README.md"),
    Path("src/README.md"),
    Path("tests/README.md"),
    Path("tests/data/README.md"),
    Path("tests/factories/README.md"),
]

RETIRED_PREFIXES = (
    "notebooks/",
    "tests/fixtures/",
    "docs/cross_source/",
    "docs/source_inventory/",
    "docs/stakeholder/",
    "docs/evidence/",
)


# Status lines that described an earlier state of the pipeline. Historical
# records (the decision log and evidence/) may still quote them.
STALE_STATUS_PHRASES = (
    "milestone 01 (Discover)",
    "no approved business question yet",
    "(not created yet)",
    "intentionally unassigned",
    "assigned to follow-on work",
    "Empty until milestone",
    "> Skeleton.",
)

HISTORICAL_RECORDS = (
    Path("docs/governance/decisions.md"),
    Path("evidence"),
)

LINK_PATTERN = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def markdown_files(repo_root: Path) -> list[Path]:
    return [
        path
        for path in repo_root.rglob("*.md")
        if not any(part in {".git", ".pytest_cache", ".venv", "local_state", "tmp"} for part in path.relative_to(repo_root).parts)
    ]


def test_required_readmes_exist(repo_root):
    missing = [str(path) for path in REQUIRED_READMES if not (repo_root / path).is_file()]
    assert not missing, f"missing repository indexes: {missing}"


def test_retired_paths_are_not_committable(repo_files):
    offenders = [
        str(path)
        for path in repo_files
        if any(path.as_posix().startswith(prefix) for prefix in RETIRED_PREFIXES)
    ]
    assert not offenders, f"move files out of retired repository paths: {offenders}"


def test_markdown_local_link_targets_exist(repo_root):
    broken = []
    for path in markdown_files(repo_root):
        text = path.read_text(encoding="utf-8")
        for raw_target in LINK_PATTERN.findall(text):
            target = raw_target.strip().split(maxsplit=1)[0]
            if not target or target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            target = unquote(target.split("#", 1)[0])
            resolved = (path.parent / target).resolve()
            if not resolved.exists():
                broken.append(f"{path.relative_to(repo_root)} -> {raw_target}")

    assert not broken, "broken local Markdown links:\n" + "\n".join(broken)


def local_link_targets(path: Path) -> set[Path]:
    targets = set()
    for raw_target in LINK_PATTERN.findall(path.read_text(encoding="utf-8")):
        target = raw_target.strip().split(maxsplit=1)[0]
        if target and not target.startswith(("http://", "https://", "mailto:", "#")):
            targets.add((path.parent / unquote(target.split("#", 1)[0])).resolve())
    return targets


def test_each_etl_readme_lists_every_sql_file_in_its_stage(repo_root):
    missing = []
    for stage in sorted((repo_root / "etl").glob("[0-9][0-9]_*")):
        text = (stage / "README.md").read_text(encoding="utf-8")
        missing += [
            str(sql.relative_to(repo_root))
            for sql in sorted(stage.glob("*.sql"))
            if f"`{sql.name}`" not in text
        ]
    assert not missing, f"name these files in their stage README: {missing}"


def test_documentation_index_reaches_every_canonical_document(repo_root):
    docs = repo_root / "docs"
    index = local_link_targets(docs / "README.md")
    unlisted = []
    for path in sorted(docs.glob("*/*.md")):
        if path.name == "README.md":
            continue
        folder_index = path.parent / "README.md"
        linked = index | (local_link_targets(folder_index) if folder_index.is_file() else set())
        if path.resolve() not in linked:
            unlisted.append(str(path.relative_to(repo_root)))
    assert not unlisted, f"link these from docs/README.md or their folder README: {unlisted}"


def test_stale_status_phrases_do_not_return(repo_root):
    found = []
    for path in markdown_files(repo_root):
        relative = path.relative_to(repo_root)
        if any(relative == record or record in relative.parents for record in HISTORICAL_RECORDS):
            continue
        text = path.read_text(encoding="utf-8")
        found += [f"{relative}: {phrase}" for phrase in STALE_STATUS_PHRASES if phrase in text]
    assert not found, "describe the current state instead:\n" + "\n".join(found)
