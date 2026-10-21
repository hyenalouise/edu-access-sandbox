# Terminal and local setup

One-time setup for every teammate, whether you have used a terminal before or not. Go in order. Every part ends with a **Check**, so you never move on unsure.

Each part is marked with a status:

- **Works now**: tested on a teammate's machine.
- **Pending #1**: waits for the Databricks workspace setup in issue #1.
- **Not yet tested on Windows**: written from documentation. If a step is wrong, fix this file in a PR rather than working around it.

The team uses two Macs and Windows laptops, so every command is given for both.

## Why bother with a terminal

Most work happens in the browser: GitHub for issues and pull requests, Databricks for running the pipeline. The terminal is for four things the browser cannot do:

1. Running the tests before you push, so you find problems in seconds instead of waiting for CI.
2. Profiling sources locally with DuckDB, without using Databricks compute.
3. Developing SQL and PySpark on a laptop before running it on Databricks (see [workflow.md](../operations/workflow.md#part-5-where-code-runs)).
4. Later (Phase 6): deploying the pipeline to Databricks.

---

## Part 1: Opening a terminal

**Status:** works now (Mac). Not yet tested on Windows.

- **Mac:** ⌘+Space, type `Terminal`, press Enter. The prompt ends in `%` or `$`.
- **Windows:** Start, type `PowerShell`, press Enter. The prompt ends in `>`.
- **VS Code (either):** **View → Terminal**. It opens in the folder you have open, which is usually what you want.

**Check:**

```
pwd
```

It prints where you are, such as `/Users/yourname` or `C:\Users\yourname`. When something says "file not found", run `pwd` first: most terminal confusion comes from being in the wrong folder.

---

## Part 2: Five commands that cover most of it

**Status:** works now (Mac). Not yet tested on Windows.

| Command | What it does |
|---|---|
| `pwd` | Print where I am |
| `ls` (Mac) / `dir` (Windows) | List what is here |
| `cd folder-name` | Go into a folder |
| `cd ..` | Go up one level |
| `cd ~` | Go to your home folder |

Folder names with spaces need quotes: `cd "School Facilities in SY 2023-2024"`. Type the first few letters of a name and press Tab to complete it.

**Check:** `cd ~`, then `pwd` prints your home folder.

---

## Part 3: Installing the tools

**Status:** works now (Mac). Not yet tested on Windows.

| Tool | Why we need it |
|---|---|
| `git` | Version control |
| `gh` | GitHub from the terminal: login, pull requests, the project board |
| `python` 3.12 | Tests and profiling scripts. CI uses 3.12, so use the same |
| `databricks` | Databricks CLI, for login now and deploys later |
| `duckdb` (optional) | DuckDB's own command line, handy for quick queries. The Python package is installed in Part 7 either way |

### Mac

Homebrew installs the other tools. Check whether you have it:

```
brew --version
```

If it says "command not found", install it from [brew.sh](https://brew.sh) (it asks for your password), then:

```
brew install git gh databricks python@3.12 duckdb
```

### Windows

PowerShell has `winget` built in:

```
winget install Git.Git
winget install GitHub.cli
winget install Databricks.DatabricksCLI
winget install Python.Python.3.12
winget install DuckDB.cli
```

### Check

Close the terminal and open a new one first; new programs only appear in a fresh terminal. Then:

| Mac | Windows |
|---|---|
| `git --version` | `git --version` |
| `gh --version` | `gh --version` |
| `databricks --version` | `databricks --version` |
| `python3.12 --version` | `py -3.12 --version` |

Each prints a version number. "Command not found" means that one did not install: rerun only that one.

---

## Part 4: Logging in to GitHub

**Status:** works now (Mac). Not yet tested on Windows.

```
gh auth login
```

Answer: **GitHub.com**, **HTTPS**, **Yes** to authenticate Git, **Login with a web browser**. It shows a one-time code; press Enter, paste the code in the browser page, and click **Authorize**.

Then add access to the project board, which the default login does not include:

```
gh auth refresh -h github.com -s read:project,project
```

This asks the same questions and shows another one-time code. **The change only takes effect after you finish the browser step.** If you close the terminal first, nothing changes.

### Check

```
gh auth status
```

It shows your username, and the token scopes include `project`, `read:org`, `repo`, and `workflow`.

---

## Part 5: Signed commits

**Status:** works now (Mac). Not yet tested on Windows.

GitHub marks a commit **Verified** when it is signed with a key GitHub knows. We sign with the same SSH key you may already use for GitHub.

### 5.1 Have an SSH key

Mac:

```
ls ~/.ssh/id_ed25519.pub
```

Windows:

```
dir $HOME\.ssh\id_ed25519.pub
```

If the file does not exist, create one (press Enter to accept the defaults; a passphrase is optional):

```
ssh-keygen -t ed25519 -C "your-github-email@example.com"
```

### 5.2 Tell Git to sign with it

Mac:

```
git config --global gpg.format ssh
git config --global user.signingkey ~/.ssh/id_ed25519.pub
git config --global commit.gpgsign true
```

Windows (Git needs the full path with forward slashes):

```
git config --global gpg.format ssh
git config --global user.signingkey "C:/Users/<your-windows-username>/.ssh/id_ed25519.pub"
git config --global commit.gpgsign true
```

Also make sure your commit email is one GitHub has verified (github.com/settings/emails):

```
git config --global user.email
```

### 5.3 Add the key to GitHub as a signing key

GitHub keeps **authentication keys** (for logging in) and **signing keys** (for Verified commits) in separate lists. A key in the first list does not verify commits.

```
gh auth refresh -h github.com -s admin:ssh_signing_key
gh ssh-key add ~/.ssh/id_ed25519.pub --type signing --title "<your laptop>"
```

On Windows, use `$HOME\.ssh\id_ed25519.pub` as the path.

### Check

After your first commit (Part 6), open it on GitHub. It shows a **Verified** badge.

---

## Part 6: Getting the code

**Status:** works now (Mac). Not yet tested on Windows.

We keep the repository and the raw data side by side in one folder:

```
~/Projects/reached-hq/
├── edu-access-intelligence/   ← the repository
└── raw-data/                  ← raw downloads, never committed
```

Mac:

```
mkdir -p ~/Projects/reached-hq
cd ~/Projects/reached-hq
git clone https://github.com/reached-hq/edu-access-intelligence.git
cd edu-access-intelligence
```

Windows:

```
mkdir $HOME\Projects\reached-hq -Force
cd $HOME\Projects\reached-hq
git clone https://github.com/reached-hq/edu-access-intelligence.git
cd edu-access-intelligence
```

### Check

```
git log --oneline -5
```

Five recent commits. `ls` (or `dir`) shows `docs/`, `tests/`, `config/`, and `README.md`.

---

## Part 7: Python environment

**Status:** works now (Mac). Not yet tested on Windows.

A virtual environment (`.venv`) is a private set of Python packages for this project, so it cannot clash with anything else on your laptop. It is git-ignored.

Mac:

```
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

Windows:

```
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
```

If Windows refuses to run `Activate.ps1` ("running scripts is disabled on this system"), allow scripts for your user only, then activate again:

```
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Your prompt now starts with `(.venv)`. Activate it again in every new terminal before running tests or scripts.

This installs `pytest` (tests) and `duckdb` (local profiling), pinned to the versions CI uses.

### Check

```
python -m pytest tests -q
```

All tests pass in about a second. They are the same tests CI runs on every pull request.

---

## Part 8: Raw data and `RAW_DATA_DIR`

**Status:** works now (Mac). Not yet tested on Windows.

Raw files live in `raw-data/`, next to the repository and never inside it (CI blocks data files). Profiling scripts find them through the `RAW_DATA_DIR` environment variable, so nobody's personal path is written into the code.

Layout, one folder per publisher:

```
raw-data/
└── deped/
    ├── original/        ← downloads exactly as received; never edit
    ├── extracted/       ← unzipped copies
    ├── SHA256SUMS.txt   ← checksums of the originals
    └── RETRIEVED.txt    ← when they were downloaded
```

**Never open a raw CSV in Excel and save it.** Excel can silently change the encoding, reformat dates, and drop leading zeros from codes (a code like `0102800000` becomes `102800000`). If you want to look at a file, open a copy.

Set the variable for the current terminal:

| Mac | Windows |
|---|---|
| `export RAW_DATA_DIR=~/Projects/reached-hq/raw-data` | `$env:RAW_DATA_DIR = "$HOME\Projects\reached-hq\raw-data"` |

### Check

To run the whole job, you need all 15 files in [raw files the job needs](raw-data.md). For this check, the DepEd files downloaded into `raw-data/deped/original/` are enough (links in `docs/data/source-inventory/deped_enrollment/README.md`):

```
python analysis/profiling/profile_deped.py
```

The first four lines end in `checksum OK`.

---

## Part 9: Why DuckDB

We added DuckDB to the project on purpose. Here is the reasoning, so you can explain it if asked.

**What it is:** a SQL database engine that runs inside your Python process or its own small program. There is no server to start and no account to create. It reads CSV and Parquet files directly and answers SQL queries on a laptop in seconds.

**Why we use it:**

1. **It saves Databricks compute.** Our workspace is Databricks Free Edition, shared by the whole team, with limited compute. Profiling and prototyping are the most repetitive work we do: run a query, look, change it, run again. Doing that locally costs nothing.
2. **Our data is small enough.** The DepEd files are about 60,000 rows each (11 to 19 MB). DuckDB profiles all four files in about 3 seconds. Spark's strength is spreading work across many machines, which data this size does not need (Day 7: "Use the simplest tool that reliably solves the problem").
3. **It is still SQL.** The queries we write are the same kind we write in Databricks: `GROUP BY`, `JOIN`, `COUNT(*) FILTER (...)`. No new language to learn.
4. **It makes findings reproducible.** Profiling scripts run in seconds on any teammate's laptop, so every number in a `profile.md` can be rerun and checked.
5. **The course points to it.** DuckDB is in the Day 9 tool list ("Can we run some workloads in a different location?").

**What it is not:**

- **Not our production engine.** The real Bronze, Silver, and Gold tables are built in Databricks, where Unity Catalog, Delta tables, jobs, and dashboards live.
- **Not identical to Databricks SQL.** Some functions differ (for example, DuckDB's `regexp_full_match` versus Spark's `rlike`). Logic developed in DuckDB gets one confirmation run on Databricks before it is trusted.

**Where we use it:** profiling sources, prototyping SQL on local samples, and (later) testing code on small made-up files in CI.

---

## Part 10: VS Code

**Status:** works now (Mac), except 10.4, which is still being checked in #1. Not yet tested on Windows.

### 10.1 Open the project

**File → Open Folder** and choose `edu-access-intelligence`.

### 10.2 Install the extensions

From the Extensions panel (⇧⌘X on Mac, Ctrl+Shift+X on Windows):

| Extension | Why |
|---|---|
| **Python** (Microsoft) | Runs Python and picks up `.venv` |
| **Jupyter** (Microsoft) | Runs the `# %%` cells in profiling scripts one at a time |
| **Databricks** (Databricks) | Connects to the workspace (10.4) |

### 10.3 Use the project's Python

Command Palette (⇧⌘P / Ctrl+Shift+P) → **Python: Select Interpreter** → choose the one inside `.venv`.

To run profiling scripts cell by cell, the environment also needs Jupyter's kernel package. Install it once, with `.venv` active:

```
python -m pip install ipykernel
```

It is not in `requirements-dev.txt` because CI does not need it.

**Check:** open `analysis/profiling/profile_deped.py`. A **Run Cell** link appears above each `# %%` line. Run the Setup cell; the Interactive window opens without errors.

### 10.4 Connect to Databricks

**Status: pending #1.** Use the `reached-hq-dev` profile from Part 12. The Databricks extension may expect a `databricks.yml` bundle file in the repository; #1 checks this.

Before connecting, read [workflow.md, Part 5](../operations/workflow.md#part-5-where-code-runs): every run from the extension uses shared Databricks compute.

### 10.5 Terminal inside VS Code

**View → Terminal** opens a terminal already in the project folder. Activate `.venv` there too (Part 7).

---

## Part 11: Local PySpark (optional)

**Status:** optional. Not yet tested on Mac or Windows. Skip this until you work on Silver or Gold transformations in PySpark.

Local PySpark runs Spark on your laptop, so you can develop PySpark logic on samples without Databricks compute. It needs Java.

Mac:

```
brew install openjdk@17
export JAVA_HOME="$(brew --prefix openjdk@17)"
python -m pip install pyspark
```

Windows:

```
winget install EclipseAdoptium.Temurin.17.JDK
python -m pip install pyspark
```

Restart the terminal after installing Java on Windows. PySpark on Windows can also ask for Hadoop's `winutils.exe` when writing files; if you hit that, use DuckDB for local work instead and note it in this file.

`pyspark` is not in `requirements-dev.txt`: it is large and optional.

### Check

```
python -c "from pyspark.sql import SparkSession; s = SparkSession.builder.master('local[1]').getOrCreate(); print(s.range(3).count()); s.stop()"
```

It prints `3` (after some startup messages).

Local PySpark has no Unity Catalog and no Delta tables without extra packages. Use it to develop transformation logic, then confirm on Databricks.

---

## Part 12: Logging in to Databricks

**Status:** works now (Mac). Not yet tested on Windows.

The team has two workspaces, one per bundle target (D-063), and one CLI profile for each:

| Profile | Target | Host | Use |
|---|---|---|---|
| `reached-hq-dev` | `dev` | `https://dbc-2b6bf1c5-7bc3.cloud.databricks.com` | Everyday work: deploy and run your branch |
| `reached-hq-prod` | `prod` | `https://dbc-76bcfddb-1669.cloud.databricks.com` | Deploys from `main` only ([runbook, Deploying to prod](../operations/runbook.md#deploying-to-prod)) |

First accept the workspace invitations in your email, then log in to each:

```
databricks auth login --host https://dbc-2b6bf1c5-7bc3.cloud.databricks.com --profile reached-hq-dev
databricks auth login --host https://dbc-76bcfddb-1669.cloud.databricks.com --profile reached-hq-prod
```

A browser opens for each; sign in and allow access. The terminal prints `Profile reached-hq-dev was successfully saved`, then the same for `reached-hq-prod`.

**Already have the old profile names?** Before 2026-10-21 the profile was called `reached-hq` (D-056), and the old workspace was `reached-hq-old` if you kept it. In `~/.databrickscfg`, rename the `[reached-hq]` section to `[reached-hq-dev]` and `[reached-hq-old]` to `[reached-hq-prod]`, or log in again with the commands above. The hosts do not change.

**Always pass `--profile`, and match it to the target:** `--target dev --profile reached-hq-dev`, `--target prod --profile reached-hq-prod`. Without it, the CLI uses whichever workspace you logged into last, so a deploy can go to a personal workspace, and the error message blames a missing warehouse instead. Each target also names its host in `databricks.yml`, so a mismatched profile fails instead of deploying to the wrong workspace.

### Check

```
databricks auth profiles
databricks catalogs get edu_access --profile reached-hq-dev
databricks catalogs get edu_access --profile reached-hq-prod
```

The first lists `reached-hq-dev` and `reached-hq-prod` with the hosts above and `Valid: YES`. The other two each show the catalog with owner `reached-hq` (the group, which keeps its name).

---

## Part 13: Errors you will probably meet

| Message | What it means |
|---|---|
| `command not found` / `is not recognized` | Not installed, or you need a fresh terminal |
| `No such file or directory` | Wrong folder; run `pwd` |
| `externally-managed-environment` | You ran `pip` outside the virtual environment; activate `.venv` (Part 7) |
| `running scripts is disabled on this system` | Windows blocked `Activate.ps1`; see Part 7 |
| `your authentication token is missing required scopes [read:project]` | Run the `gh auth refresh` in Part 4 **and finish the browser step** |
| `Set RAW_DATA_DIR to the folder that contains ...` | Set the variable (Part 8) in this terminal |
| `SHA-256 ... does not match the inventory card` | The raw file differs from what was documented. Stop: the publisher may have changed it. Tell the source owner |
| `Invalid unicode (byte sequence mismatch) ... not utf-8 encoded` | The file is not UTF-8. Declare its encoding; never guess (see DepEd finding O-6) |
| `Unable to locate a Java Runtime` / `JAVA_HOME is not set` | Local PySpark needs Java (Part 11) |
| `This branch has conflicts` on a stacked PR | See [workflow.md, Part 3](../operations/workflow.md#stacked-pull-requests) |

Read the whole message before retrying. Most errors say exactly what is wrong.

---

## Setup checklist

Once per laptop:

- [ ] `git`, `gh`, `databricks`, and Python 3.12 print a version (Part 3)
- [ ] `gh auth status` lists the `project` scope (Part 4)
- [ ] Commit signing configured and your signing key added to GitHub (Part 5)
- [ ] Repository cloned into `~/Projects/reached-hq/` (Part 6)
- [ ] `.venv` created and `python -m pytest tests -q` passes (Part 7)
- [ ] `RAW_DATA_DIR` set and the DepEd profiling script prints `checksum OK` (Part 8)
- [ ] VS Code runs a `# %%` cell with the `.venv` interpreter (Part 10)
- [ ] `databricks auth profiles` shows `reached-hq-dev` and `reached-hq-prod` as valid (Part 12)
