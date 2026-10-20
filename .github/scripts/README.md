# Workflow scripts

The logic the [workflows](../workflows/README.md) run, kept in Python so `tests/test_github_scripts.py` can test it. Standard library only.

| Script | Used by | Does |
|---|---|---|
| `linked_issues.py` | `ci.yml`, `triage.yml` | Lists the issue numbers a PR description links to |
| `linked_issue_states.py` | `ci.yml` | Fails if a linked issue does not exist or is closed |
| `closing_issues.py` | `ci.yml` | Fails if merging would close a parent issue or more than one issue |
| `pr_ai_help.py` | `ci.yml` | Fails unless exactly one AI-help option is ticked, with all four gates and a note when AI helped (D-010) |
| `title_labels.py` | `triage.yml` | Labels an issue from the `[TAG]` at the start of its title |
| `pr_reviewers.py` | `triage.yml` | The author's two reviewers, from [`../reviewers.json`](../reviewers.json) |
| `reviewer_comment.py` | `triage.yml` | The comment that @mentions the reviewers, with a meme from [`../memes/`](../memes/README.md) |
| `issue_hygiene.py` | `issue-hygiene.yml` | Lists issues whose state disagrees with their sub-issues or the board |
