"""Tests for the scripts the GitHub workflows run (.github/scripts/)."""

import importlib.util
import re

import pytest

from conftest import REPO_ROOT


def _load(name):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / ".github/scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


title_labels = _load("title_labels")
pr_ai_help = _load("pr_ai_help")


# --- title_labels ---------------------------------------------------------

@pytest.mark.parametrize("title, expected", [
    ("[BRONZE] Load sources into Bronze tables", ["infra"]),
    ("[SOURCE] Find, download, and first look: PSGC", ["source-candidate"]),
    ("[DECISION] Pick the business question", ["decision"]),
    ("[docs] lowercase tag", ["docs"]),
    ("[DASHBOARD] [AI/BI] Build the dashboard", ["dashboard"]),
    ("[SETUP] [DOCS] Two tags", ["infra", "docs"]),
    ("[FRAME] Draft candidate questions", ["framing"]),
    ("[DQ] Add null checks", ["data-quality"]),
    ("[PROOF] Capture run logs", ["evidence"]),
    ("[PRESENT] Build the deck", ["presentation"]),
    ("[UNKNOWN] Not a team tag", []),
    ("No tag at all", []),
    ("Tag later [DOCS] is ignored", []),
])
def test_labels_for(title, expected):
    assert title_labels.labels_for(title) == expected


def test_every_workflow_tag_has_a_label():
    # The tags listed in docs/operations/workflow.md, Issue titles.
    tags = {"SETUP", "DECISION", "SOURCE", "FRAME", "PROFILE", "BRONZE", "SILVER", "INTEGRATE", "GOLD",
            "DQ", "DEPLOY", "MONITOR", "OPS", "DASHBOARD", "AI/BI", "DOCS", "PROOF", "PRESENT"}
    assert tags <= set(title_labels.TAG_LABELS)


def test_every_mapped_label_is_a_known_repo_label():
    # Labels created in the repository (gh label list). Adding a mapping to a
    # label that does not exist would make the workflow fail.
    known = {
        "infra", "decision", "source-candidate", "research", "dashboard", "docs", "data-issue",
        "framing", "data-quality", "evidence", "presentation",
    }
    assert set(title_labels.TAG_LABELS.values()) <= known


# --- pr_ai_help -----------------------------------------------------------

GATES_TICKED = """
  - [x] **Data:** only public or made-up data
  - [x] **AI claims:** every fact checked
  - [x] **Output:** I checked the result myself
  - [x] **Accountability:** I can explain every part
"""


def _body(section):
    return f"## Summary\n\nText.\n\n## AI help\n\n{section}\n\n## Reviewer notes\n\nCheck X.\n"


def test_template_itself_fails():
    template = (REPO_ROOT / ".github/pull_request_template.md").read_text()
    assert pr_ai_help.problems(template) == ["Tick exactly one: 'No AI help' or 'AI helped'."]


def test_template_has_every_gate_the_check_requires():
    template = (REPO_ROOT / ".github/pull_request_template.md").read_text()
    for gate in pr_ai_help.GATES:
        assert f"**{gate}:**" in template


def test_missing_section_fails():
    assert "no '## AI help' section" in pr_ai_help.problems("## Summary\n\nCloses #1\n")[0]


def test_no_ai_help_passes():
    assert pr_ai_help.problems(_body("- [x] No AI help\n- [ ] AI helped")) == []


def test_both_ticked_fails():
    assert pr_ai_help.problems(_body("- [x] No AI help\n- [x] AI helped")) == ["Tick exactly one: 'No AI help' or 'AI helped'."]


def test_ai_helped_with_everything_passes():
    section = "- [ ] No AI help\n- [x] AI helped, and it passed all four gates:" + GATES_TICKED
    section += "\n**What the AI did** (leave blank if no AI help): Claude drafted the wording."
    assert pr_ai_help.problems(_body(section)) == []


def test_note_written_in_bold_label_style_passes():
    section = "- [x] AI helped" + GATES_TICKED + "\n**What the AI did:** Claude drafted the wording."
    assert pr_ai_help.problems(_body(section)) == []


def test_missing_gate_fails():
    section = "- [x] AI helped" + GATES_TICKED.replace("[x] **Output:**", "[ ] **Output:**") + "\n**What the AI did:** X."
    assert pr_ai_help.problems(_body(section)) == ["The Output gate is not ticked. Fix the work until you can tick it."]


def test_empty_note_fails():
    section = "- [x] AI helped" + GATES_TICKED + "\n**What the AI did** (leave blank if no AI help):\n"
    assert pr_ai_help.problems(_body(section)) == ["Say what the AI did: which tool, and which parts of the work."]


def test_ticks_in_html_comments_are_ignored():
    assert pr_ai_help.problems(_body("<!-- - [x] No AI help -->\n- [ ] No AI help\n- [ ] AI helped"))


# --- pr_reviewers ---------------------------------------------------------

pr_reviewers = _load("pr_reviewers")
REVIEWERS = pr_reviewers.load_table()


def test_reviewers_known_author():
    assert pr_reviewers.reviewers_for("hyenalouise", REVIEWERS) == ["maeveylain", "saraevcldn"]


def test_reviewers_unknown_author_gets_none():
    assert pr_reviewers.reviewers_for("someone-else", REVIEWERS) == []


def test_every_author_has_two_other_teammates_as_reviewers():
    team = set(REVIEWERS)
    for author, reviewers in REVIEWERS.items():
        assert len(reviewers) == 2 and len(set(reviewers)) == 2, author
        assert author not in reviewers, f"{author} reviews their own PRs"
        assert set(reviewers) <= team, f"{author} has a reviewer outside the team"


def test_review_load_is_balanced():
    load = {person: 0 for person in REVIEWERS}
    for reviewers in REVIEWERS.values():
        for r in reviewers:
            load[r] += 1
    assert set(load.values()) == {2}, load


# --- linked_issues --------------------------------------------------------

linked_issues = _load("linked_issues")


@pytest.mark.parametrize("body, expected", [
    ("Closes #23", [23]),
    ("Part of #3 and related to #8", [3, 8]),
    ("fixes #5\nResolves #5", [5]),
    ("See #12 for context", []),
    ("<!-- Closes #1 -->\nCloses #2", [2]),
    ("", []),
])
def test_linked_issues(body, expected):
    assert linked_issues.linked_issues(body) == expected


# --- closing_issues -------------------------------------------------------

closing_issues = _load("closing_issues")


def _issue(number, subs):
    return {"number": number, "title": f"Issue {number}", "subIssuesSummary": {"total": subs}}


def test_closing_a_leaf_issue_passes():
    assert closing_issues.problems([_issue(80, 0)]) == []


def test_closing_nothing_passes():
    assert closing_issues.problems([]) == []


def test_closing_a_parent_issue_fails_and_names_it():
    found = closing_issues.problems([_issue(11, 8)])
    assert len(found) == 1
    assert "#11" in found[0] and "Part of #11" in found[0] and "8 sub-issues" in found[0]


def test_closing_more_than_one_leaf_issue_fails_and_names_each():
    found = closing_issues.problems([_issue(80, 0), _issue(81, 0)])
    assert len(found) == 1
    assert "at most one" in found[0] and "#80" in found[0] and "#81" in found[0]


def test_multiple_closures_report_count_and_parent_problems():
    found = closing_issues.problems([_issue(11, 8), _issue(80, 0)])
    assert len(found) == 2
    assert "at most one" in found[0]
    assert "parent issue" in found[1]


def test_missing_sub_issue_summary_counts_as_leaf():
    assert closing_issues.problems([{"number": 5, "title": "x", "subIssuesSummary": None}]) == []


# --- linked_issue_states --------------------------------------------------

linked_issue_states = _load("linked_issue_states")


def test_open_linked_issue_passes():
    assert linked_issue_states.problems([{"number": 80, "state": "open", "is_pull_request": False}]) == ([], [])


def test_missing_linked_issue_fails():
    errors, warnings = linked_issue_states.problems([{"number": 9999, "missing": True}])
    assert len(errors) == 1 and "#9999" in errors[0] and warnings == []


def test_linking_a_pull_request_fails():
    errors, _ = linked_issue_states.problems([{"number": 105, "state": "open", "is_pull_request": True}])
    assert len(errors) == 1 and "pull request" in errors[0]


def test_closed_linked_issue_only_warns():
    errors, warnings = linked_issue_states.problems([{"number": 30, "state": "closed", "is_pull_request": False}])
    assert errors == [] and len(warnings) == 1 and "#30" in warnings[0]


# --- issue_hygiene --------------------------------------------------------

issue_hygiene = _load("issue_hygiene")


def _hygiene_issue(number, state, subs=(), status=None):
    issue = {
        "number": number,
        "title": f"Issue {number}",
        "url": f"https://github.com/x/y/issues/{number}",
        "state": state,
        "subIssues": {"nodes": [{"number": n, "state": s} for n, s in subs]},
    }
    if status is not None:
        issue["projectItems"] = {"nodes": [{"project": {"title": "Board"}, "fieldValueByName": {"name": status}}]}
    return issue


def test_consistent_issues_have_no_findings():
    issues = [
        _hygiene_issue(11, "OPEN", [(77, "OPEN"), (80, "CLOSED")], status="In progress"),
        _hygiene_issue(80, "CLOSED", status="Done"),
        _hygiene_issue(12, "CLOSED", [(13, "CLOSED")]),
    ]
    assert issue_hygiene.findings(issues) == []


def test_closed_issue_with_open_sub_issues_is_reported():
    found = issue_hygiene.findings([_hygiene_issue(11, "CLOSED", [(77, "OPEN"), (78, "OPEN"), (80, "CLOSED")])])
    assert [h for h, _ in found] == [issue_hygiene.CLOSED_PARENT]
    assert "#77, #78" in found[0][1] and "#80" not in found[0][1]


def test_open_parent_with_all_sub_issues_closed_is_reported():
    found = issue_hygiene.findings([_hygiene_issue(43, "OPEN", [(85, "CLOSED"), (86, "CLOSED")])])
    assert [h for h, _ in found] == [issue_hygiene.FINISHED_PARENT]
    assert "all 2" in found[0][1]


def test_open_issue_in_done_is_reported():
    found = issue_hygiene.findings([_hygiene_issue(85, "OPEN", status="Done")])
    assert [h for h, _ in found] == [issue_hygiene.OPEN_IN_DONE]
    assert "Board" in found[0][1]


def test_issue_without_sub_issues_or_board_item_is_fine():
    issue = {"number": 5, "title": "x", "url": "u", "state": "OPEN", "subIssues": None}
    assert issue_hygiene.findings([issue]) == []


def test_summary_says_when_the_board_was_not_checked():
    text = issue_hygiene.summary([_hygiene_issue(5, "OPEN")], [])
    assert "Checked 1 issues." in text and "PROJECT_READ_TOKEN" in text


def test_summary_lists_board_findings_when_the_board_was_read():
    issues = [_hygiene_issue(85, "OPEN", status="Done")]
    text = issue_hygiene.summary(issues, issue_hygiene.findings(issues))
    assert "PROJECT_READ_TOKEN" not in text and "#85 is open but sits in Done" in text


def test_pr_template_defaults_to_part_of(repo_root):
    template = (repo_root / ".github" / "pull_request_template.md").read_text()
    assert re.search(r"(?m)^Part of #\s*$", template)
    assert not re.search(r"(?mi)^(?:Closes|Fixes|Resolves) #\s*$", template)


def test_issue_templates_use_reorganized_paths(repo_root):
    text = "\n".join(
        path.read_text()
        for path in (repo_root / ".github" / "ISSUE_TEMPLATE").glob("*.md")
    )
    assert "docs/source_inventory" not in text
    assert "notebooks/profiling" not in text
    assert "docs/data/source-inventory" in text
    assert "analysis/profiling" in text


# --- reviewer_comment -----------------------------------------------------

reviewer_comment = _load("reviewer_comment")
REVIEWER_PAIR = ["maeveylain", "saraevcldn"]


def test_comment_starts_with_marker_and_mentions_both_reviewers():
    body = reviewer_comment.build(24, "hyenalouise", REVIEWER_PAIR, 23, "01 · Discover")
    assert body.startswith(reviewer_comment.MARKER)
    assert "@maeveylain" in body and "@saraevcldn" in body
    assert "references #23" in body and "belongs to 01 · Discover" in body


def test_opener_and_meme_rotate_by_pr_number():
    for number in range(10):
        opener, meme, _ = reviewer_comment.PAIRS[number % len(reviewer_comment.PAIRS)]
        body = reviewer_comment.build(number, "hyenalouise", REVIEWER_PAIR)
        assert opener.format(a="@maeveylain", b="@saraevcldn") in body
        assert meme in body


def test_same_pr_always_gets_the_same_comment():
    assert reviewer_comment.build(7, "x", REVIEWER_PAIR) == reviewer_comment.build(7, "x", REVIEWER_PAIR)


def test_comment_without_issue_or_milestone():
    body = reviewer_comment.build(1, "hyenalouise", REVIEWER_PAIR)
    assert "isn't linked to an issue yet" in body and "has no milestone yet" in body


def test_author_not_in_table_asks_for_a_manual_request():
    body = reviewer_comment.build(1, "newcomer", [])
    assert body.startswith(reviewer_comment.MARKER)
    assert "@newcomer isn't in `.github/reviewers.json`" in body and "<img" not in body


def test_every_meme_file_exists():
    for _, meme, alt in reviewer_comment.PAIRS:
        path = REPO_ROOT / ".github/memes" / meme
        assert path.is_file(), meme
        assert path.stat().st_size < 200_000, f"{meme} is large; resize it to about 360px wide"
        assert alt


def test_the_prod_deploy_waits_for_the_same_tests_as_ci():
    """D-064: deploy.yml tests the commit it deploys with CI's own test steps, and deploys only after them."""
    import yaml

    def jobs(name):
        return yaml.safe_load((REPO_ROOT / ".github/workflows" / name).read_text(encoding="utf-8"))["jobs"]

    ci, deploy = jobs("ci.yml")["repository-checks"], jobs("deploy.yml")
    assert deploy["deploy"]["needs"] == "tests"
    assert deploy["tests"]["steps"] == ci["steps"]
    assert "environment" not in deploy["tests"], "the tests job must not read the prod token"
