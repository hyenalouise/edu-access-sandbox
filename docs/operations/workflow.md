# How we work

How work moves from an issue to `main`, and where each kind of work runs. For the rules in short form, see [CONTRIBUTING.md](../../CONTRIBUTING.md). For one-time laptop setup, see [terminal-setup.md](../getting-started/terminal-setup.md).

## Start here

| I want to... | Where | Terminal? |
|---|---|---|
| Pick up an issue, move a card | [Project board](https://github.com/orgs/reached-hq/projects/3) | No |
| Edit docs, open or review a pull request | GitHub | No |
| Run SQL on real tables | Databricks SQL editor (workspace in [architecture.md](../architecture/overview.md#workspace)) | No |
| Run the tests before pushing | Laptop | Yes |
| Profile a source | Laptop (DuckDB) | Yes |
| Develop SQL or PySpark logic on a sample | Laptop (DuckDB or local PySpark) | Yes |
| Rebase a stacked pull request | Laptop | Yes |
| Deploy the pipeline | Laptop: `dev` from any branch, `prod` only from `main` (D-063) | Yes |

---

## Part 1: The board and issues

**Use board #3 only:** https://github.com/orgs/reached-hq/projects/3. Boards #1 and #2 have the same name and are duplicates; issue #3 once went missing because it was on #2.

### Status columns

| Status | Meaning |
|---|---|
| Backlog | Not started |
| Ready | Unblocked; its prerequisites are done |
| In progress | Someone is working on it (assign yourself first) |
| In review | A pull request is open |
| Done | Merged and checked |

These board automations are switched on (board → **⋯** → **Workflows** shows what each one does):

- **Auto-add to project**: issues from the repository that match the board's filter are added when they are created or edited.
- **Item added to project**, **Item closed**, **Item reopened**, **Pull request linked to issue**, **Pull request merged**, **Code review approved**: each sets a card's status.

The board's **Auto-close issue** workflow must stay **off**. Moving a card is
organization, not evidence that acceptance criteria are complete. Closing the
leaf issue may move its card to **Done**, but moving a card to **Done must not
close the issue**.

The repository also runs these automations (`.github/workflows/triage.yml`):

- **Issue labels:** issues opened from the **Source candidate** and **Data issue** templates get `source-candidate` and `data-issue`. Any issue whose title starts with a tag also gets that tag's label (for example `[BRONZE]` → `infra`); the mapping is in `.github/scripts/title_labels.py`. `[FRAME]` → `framing`, `[DQ]` → `data-quality` (building checks; a problem found in the data is a `data-issue`), `[PROOF]` → `evidence`, `[PRESENT]` → `presentation`. Labels are only added, never removed, so fix a wrong label by hand.
- **PR assignee:** a pull request with no assignee is assigned to its author when it is opened.
- **PR reviewers:** when a pull request is opened (or a draft is marked ready for review), both of the author's reviewers are requested. **One approval is enough to merge**, so whichever reviewer gets to it first approves. The table is in `.github/reviewers.json`:

  | PR author | Reviewer 1 | Reviewer 2 |
  |---|---|---|
  | Angela (`mafelisilda`) | Ina | Maeve |
  | Ina (`hyenalouise`) | Maeve | Sara |
  | Maeve (`maeveylain`) | Sara | Cath |
  | Sara (`saraevcldn`) | Cath | Angela |
  | Cath (`catweyine`) | Angela | Ina |

  Everyone reviews for exactly two authors. To change the table, edit `reviewers.json` in a pull request; the tests keep it balanced.

  The workflow also posts a comment that @mentions both reviewers, with the linked issue, the milestone, and what to check before approving. Its opening line and meme rotate by PR number (the pairs are in `.github/scripts/reviewer_comment.py`, the images in `.github/memes/`). If the PR is reopened, the same comment is edited rather than posted again. Drafts get no reviewers and no comment until they are marked ready for review.

A weekly **issue hygiene** report (`.github/workflows/issue-hygiene.yml`, Mondays 09:00 Philippine time, or **Actions** → **Issue hygiene** → **Run workflow**) lists issues whose state disagrees with their sub-issues or the board:

- a closed issue with open sub-issues: reopen it, or finish or move the sub-issues;
- an open parent whose sub-issues are all closed: check its own acceptance evidence and close it by hand, or add a sub-issue for what is left;
- an open issue sitting in **Done**: move the card back, or close the issue if it is really finished. The workflow's own token cannot read the organization's board, so this one runs only when the repository has a `PROJECT_READ_TOKEN` secret (a token with read access to this repository's issues and the organization's projects).

It changes nothing. The run fails when there is something to fix, and the list is on the run page.
- **Issues are not auto-assigned.** Assigning yourself is how you claim an issue.

### Issue titles

Every title starts with a tag:

| Tag | Used for |
|---|---|
| `[SETUP]` | Tools, workspace, repository setup |
| `[DECISION]` | A choice to record in `docs/governance/decisions.md` |
| `[SOURCE]` | Finding, downloading, and documenting a dataset |
| `[FRAME]` | Stakeholder needs, business question, model design |
| `[PROFILE]` | Profiling and cross-source comparison |
| `[BRONZE]` `[SILVER]` `[INTEGRATE]` `[GOLD]` | Pipeline layers |
| `[DQ]` | Data-quality checks |
| `[DEPLOY]` `[MONITOR]` `[OPS]` | Jobs, monitoring, operations |
| `[DASHBOARD]` `[AI/BI]` | Serving layer |
| `[DOCS]` `[PROOF]` `[PRESENT]` | Documentation, evidence, presentation |

Assign yourself before you start, so two people never work on the same issue.

---

## Part 2: Branches and commits

Never commit to `main`; it is protected. Branch from an up-to-date `main`:

```
git switch main
git pull --ff-only
git switch -c <type>/<issue-number>-<short-description>
```

For example `docs/3-deped-source-docs` or `feat/11-bronze-loader`. Types: `feat`, `fix`, `docs`, `chore`.

Commit messages:

- Imperative mood: "Add PSGC source card", not "added stuff".
- One meaningful checkpoint per commit.
- Write each paragraph on one line; do not wrap.

Commits are signed (see [terminal-setup.md, Part 5](../getting-started/terminal-setup.md#part-5-signed-commits)), so GitHub shows them as **Verified**: proof the commit came from your key.

---

## Part 3: Pull requests

### Titles

An issue and its pull request do not share a title. The issue says what needs to happen; the pull request says what this change did. One issue can need several pull requests, and each title should tell them apart.

Tags are for issues only ([Issue titles](#issue-titles)). A pull request title has no tag; the linked issue already carries it.

| | Title |
|---|---|
| Issue | `[SOURCE] Find, download, and first look: PSGC` |
| Pull request | `Add PSGC source card, profile, and data dictionary` |

Write the pull request title from the diff, in the imperative ("Add", "Fix", "Remove").

### Linking the issue

The description must mention the issue, or the **PR links an issue** check fails:

| You write | Effect |
|---|---|
| `Closes #3` | Links the PR to the issue on the board, and **closes the issue when the PR merges** |
| `Part of #3` | Mentions the issue only; it stays open and is not linked on the board |
| `Related to #3` | Same as `Part of`: for an issue the PR touches but does not work on |
| A link in the PR sidebar (**Development**) | Same as `Closes`: **closes the issue when the PR merges**. Don't use it; write the link in the description |

Rules for closing:

1. **`Closes` only the issue this PR finishes**, meaning every item in its acceptance evidence is done once the PR merges. If another PR is still needed, write `Part of`, and only the last PR writes `Closes`. Four PRs that each profile one BPDA dataset for the same issue: the first three say `Part of`.
2. **Never close a parent issue from a PR.** A parent is an issue with sub-issues (for example #11, #43, #44). Write `Closes` for the sub-issue the PR finishes and `Part of` for the parent. Close the parent by hand once all its sub-issues are closed. CI fails if merging would close a parent, including through a sidebar link.
3. **At most one `Closes` per PR.** Split unrelated outcomes. For other issues the PR contributes to, use `Part of` or `Related to`. CI fails when a PR would close more than one issue.
4. **Close a parent manually.** Once every sub-issue is closed, check the parent's own acceptance evidence and close it by hand. If unfinished parent-level work remains, create another sub-issue.
5. **Board status does not close work.** The board's Auto-close workflow stays off; issue closure may move a card to Done, never the reverse.

The **PR links an issue** check lists every issue that merging will close. Read that list before you ask for review. A sidebar link triggers no new run, so after changing the sidebar, rerun the check (**Checks** tab → **Re-run**).

### Filling in the template

Say what changed and why, what you ran to check it (with counts when data is involved), and **what you did not check**. The last part is what makes the rest believable.

### The checks

| Check | Fails when |
|---|---|
| Repository checks | A test fails: data file committed, `.ipynb` notebook, secret-like text, invalid `config/sources.json`, a source without its documentation folder, or a broken workflow script in `.github/scripts/` |
| PR links an issue | The description has no `Closes #N` / `Part of #N`, links a number that is not an issue in this repository (a typo, or a pull request), or merging would close a parent issue or more than one issue. A link to a closed issue only shows a warning |
| PR has a milestone | The PR has no milestone and none of its linked issues has one to copy. When a linked issue has one, the check copies it onto the PR and passes |
| PR declares AI help | The **AI help** section does not tick exactly one option, or ticks **AI helped** without all four gates and a note on what the AI did ([CONTRIBUTING.md, Using AI](../../CONTRIBUTING.md#using-ai)) |

**When CI runs:** on every pull request, whatever branch it targets, so a stacked pull request is checked before its base merges. The checks block merging only into `main`, where branch protection requires them.

**What CI does not cover:** it never touches Databricks and never sees real data (raw data is not in git). A green check means the repository follows its rules, not that the data is right. Data correctness is checked by profiling now and by data-quality checks in Databricks later.

### Stacked pull requests

A pull request can be based on another pull request's branch, not `main` (PR #13 was based on #12). When the first one merges, GitHub switches the second one's base to `main`. Pull requests merge with a merge commit, so the first PR's commits are already on `main` and the second PR usually needs no rebase.

If the second PR shows **conflicts** (for example, both changed the same lines), bring `main` into your own branch and resolve them there:

```
git fetch origin
git switch <your-branch>
git merge origin/main
git push
```

Never force-push `main`.

### Reviews

- At least one teammate who is not the author approves. GitHub does not let you approve your own pull request.
- Read the code, not just the description. A question ("this reads from the internet; the issue says no network?") is worth more than a quick approval.
- **Every review conversation must be resolved** before the PR can merge. Resolve a thread once its answer or fix is in.
- **A new push needs a new approval.** Pushing to the branch dismisses existing approvals, and whoever pushed last cannot be the approver. If you push a fix to a teammate's PR, someone else approves it.
- **Admin override** (merging without an approval) is for when no teammate can review in time and CI is green. Leave a PR comment saying why. Proposed rule: confirm it with the team.
- Merging creates a merge commit on `main`, keeps the branch's commits, and deletes the branch.

---

## Part 4: Working on a source

This is the capstone's core loop: a dataset is not useful until it has been inspected and documented.

1. **Claim the issue.** Assign yourself the `[SOURCE]` issue and move the card to **In progress**.
2. **Download** the original files into `raw-data/<publisher>/original/`, never into the repository.
3. **Record provenance** in `raw-data/<publisher>/`: the SHA-256 of each file (`shasum -a 256 *` on Mac, `Get-FileHash` on Windows) and when you downloaded it.
4. **Do not open raw files in Excel and save them** ([terminal-setup.md, Part 8](../getting-started/terminal-setup.md#part-8-raw-data-and-raw_data_dir)).
5. **Read the publisher's documentation** (README files, technical notes) before profiling.
6. **Profile with a script** in `analysis/profiling/`, reading `RAW_DATA_DIR` and verifying checksums first. See `profile_deped.py` for the pattern: every result prints under a finding ID.
7. **Document** in `docs/data/source-inventory/<source_id>/`: copy `template/`, fill in `README.md` (the card) and `profile.md` (findings with evidence, **observed** vs **suspected**), and generate `data_dictionary.md` with a script (every column: the publisher's description, the team's labeled interpretation where the publisher is silent, and observed fill rate and samples). See `dictionary_deped.py` for the pattern.
8. **Register** the source in `config/sources.json`.
9. **Open a pull request** with the script's output as evidence.

---

## Part 5: Where code runs

Our Databricks workspace is **Free Edition**, shared by the whole team, with limited compute. Our data is small (about 60,000 rows per file), so one full pipeline run costs little. What uses up compute is **repetition and forgetting**: rerunning notebooks while debugging, sessions left running, dashboards refreshing on a schedule, and two people running the full pipeline at once.

So the rule is: **develop locally, run on Databricks only when the logic is ready.**

| Activity | Runs on | Databricks compute |
|---|---|---|
| Profiling a source | Laptop (DuckDB script) | None |
| Writing and debugging SQL or PySpark on a sample | Laptop (DuckDB, or local PySpark) | None |
| Tests and repository checks | Laptop and GitHub CI | None |
| Docs, issues, reviews | GitHub | None |
| Building real Bronze, Silver, and Gold tables | Databricks | Yes: planned, announced runs |
| Dashboards and Genie | Databricks | Yes: no scheduled refresh during development |

### Three ways to use VS Code

| Option | What happens | Compute | Use it for |
|---|---|---|---|
| **A. Local only** (default) | DuckDB or local PySpark run on your laptop | None | Profiling; developing logic on samples |
| **B. Databricks extension** | Files sync to the workspace and run on Databricks | Every run | Confirming that working logic also runs on Databricks |
| **C. Databricks Connect** | You write PySpark in VS Code, but Spark runs on Databricks | Every action | Rarely. It feels local but is not, which is how compute disappears unnoticed |

Local is not identical to Databricks: DuckDB SQL differs from Databricks SQL in some functions, and local PySpark has no Unity Catalog. So: **develop locally, then do one confirmation run on Databricks.** Never "it worked locally, ship it." (Why DuckDB: [terminal-setup.md, Part 9](../getting-started/terminal-setup.md#part-9-why-duckdb).)

### Rules for Databricks compute

1. **Local first.** Logic works on a local sample before it runs on Databricks.
2. **Announce full runs.** Before a full pipeline run, post in the team's Notion or chat and move the card, so only one full run happens at a time.
3. **No schedules during development.** Jobs deploy to the `dev` target with schedules paused. Dashboards get no scheduled refresh until milestones 04 and 05. On `prod` the job still has no schedule, but the two SQL alerts evaluate daily at 08:00, which starts the `prod` warehouse once a day.
4. **Stop what you start.** Detach notebooks and stop the SQL warehouse when done. Set the warehouse auto-stop to the shortest allowed (#1).
5. **Keep exploration small.** Use `LIMIT`; never `collect()` or `toPandas()` a whole table.
6. **Build once, reuse.** Loads are safe to rerun without duplicating rows, so there is no need to rebuild everything to test one step.
7. **Record runs.** Every full run writes a row to the `pipeline_runs` control table (#11), so the team can see who ran what and how often.
8. **Know the limits.** Free Edition's actual limits are recorded in #1 from Databricks' own documentation.

---

## Part 6: Databricks

**Status:** both workspaces, catalogs, and CLI profiles ready; deploying to `dev` and `prod` documented. Git folders still pending.

| What | Where |
|---|---|
| Workspace | `dev`: https://dbc-2b6bf1c5-7bc3.cloud.databricks.com, where you work; `prod`: https://dbc-76bcfddb-1669.cloud.databricks.com, deployed only from `main` (details in [architecture.md](../architecture/overview.md#workspace), D-063) |
| Catalog | `edu_access` in each workspace, owned by the `reached-hq` group |
| Schemas so far | `` `00-source` ``, `` `01-control` ``, `` `02-bronze` ``; later stages are created when they start |
| Raw files | `/Volumes/edu_access/00-source/raw/<publisher>/` |

- Write every table reference in full, with backticks around the schema: ``edu_access.`02-bronze`.deped_enrollment_raw``.
- Your own Databricks Git folder, linked to this repository: never share a folder, or you will overwrite each other. **Pending #1:** link your GitHub account in Databricks (User Settings → Linked accounts) first.
- Notebooks are saved in `.py` source format.
- Deploying and running the job: the pipeline job (`edu_access_pipeline`) is defined in `databricks.yml`; how to deploy and run it on `dev` is in [ingestion.md, Running on Databricks](ingestion.md#running-on-databricks), and on `prod` in [runbook.md, Deploying to prod](runbook.md#deploying-to-prod). Run it locally first with `python -m src.job.local_run`.

---

## Part 7: Words you will come across

| Term | Meaning |
|---|---|
| Branch | A separate line of work, so two people do not overwrite each other |
| Pull request (PR) | "Please review my branch and merge it into `main`" |
| CI | Checks GitHub runs on every pull request |
| Merge commit | The commit that joins a branch into `main`, keeping the branch's own commits |
| Stacked PR | A pull request based on another pull request's branch |
| Rebase | Replaying your commits on top of a newer base |
| Signed / Verified commit | A commit signed with your key, which GitHub confirms |
| Source card | `docs/data/source-inventory/<source_id>/README.md`: what a source is |
| Profile | `docs/data/source-inventory/<source_id>/profile.md`: what we found in it, with evidence |
| Data dictionary (source) | `docs/data/source-inventory/<source_id>/data_dictionary.md`: every column with the publisher's description, the team's labeled interpretation, and observed samples; generated, never hand-edited |
| Observed / suspected | A finding with evidence / a hypothesis still to test |
| SHA-256 | A file's fingerprint; any change to the file changes it |
| `RAW_DATA_DIR` | Environment variable pointing scripts to your `raw-data/` folder |
| PSGC | Philippine Standard Geographic Code: the codes that identify regions, provinces, cities, municipalities, and barangays |
| BOSY | Beginning of School Year: when DepEd's official enrollment is counted |
| Bronze / Silver / Gold | Raw as received / cleaned and standardized / business-ready |
| Idempotent | Running it twice gives the same result as running it once |
| Profile (Databricks CLI) | A saved login for one workspace: `reached-hq-dev` or `reached-hq-prod`. Always name it, and match it to the target |

---

## Stuck?

Read the error first; most say exactly what is wrong. [terminal-setup.md, Part 13](../getting-started/terminal-setup.md#part-13-errors-you-will-probably-meet) lists the ones we have already met.

Then tell a teammate where you are, what you ran, and what it said. "It doesn't work" takes three messages to sort out; the error text usually takes none.
