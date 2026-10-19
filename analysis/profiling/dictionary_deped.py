# Generates the source data dictionaries for deped_enrollment and deped_facilities:
#   docs/data/source-inventory/deped_enrollment/data_dictionary.md
#   docs/data/source-inventory/deped_facilities/data_dictionary.md
#
# Descriptions are copied from DepEd's README inside each zip. Everything else
# (how filled a column is, distinct values, samples, ranges) is measured from the
# data. Output is deterministic, so rerunning on the same files changes nothing.
#
#   RAW_DATA_DIR=~/Projects/reached-hq/raw-data python analysis/profiling/dictionary_deped.py
#
# The file list and loading repeat profile_deped.py on purpose for now; they move
# to src/profiling/ when a second publisher needs the same code (D-007).

# %% Setup
import hashlib
import os
import re
import sys
import tempfile
import zipfile
from pathlib import Path

import duckdb

raw_dir = os.environ.get("RAW_DATA_DIR")
if not raw_dir:
    sys.exit("Set RAW_DATA_DIR to the folder that contains deped/original/.")
ORIGINAL = Path(raw_dir).expanduser() / "deped" / "original"
REPO = Path(__file__).resolve().parents[2]

FILES = {
    "enr_2020_21": ("Enrollment-in-SY-2020-2021.zip", "65c400aa31ba63730b8f9a7b4d60ade91c6a29cdb34a3c6bf255e5fc9e91a241", "enrollment_2020-21.csv", "utf-8"),
    "enr_2021_22": ("Enrollment-in-SY-2021-2022.zip", "62f412466435db6feba57684643f5af99ca901c6ea88accb420efe9a9bfb0acd", "enrollment_2021-22.csv", "utf-8"),
    "enr_2022_23": ("Enrollment-in-SY-2022-2023.zip", "6d567d801a8d4eb6c9dec3c032ba208e4cd929c226b6326bc7c687c83efbf9bf", "enrollment_2022-23.csv", "utf-8"),
    "enr_2023_24": ("Enrollment-in-SY-2023-2024.zip", "a10f4d0f9082919c13b3a091774c8231c99c95b1b1872310714107013b77dbbb", "enrollment_2023-24.csv", "utf-8"),
    "enr_2024_25": ("Enrollment-in-SY-2024-2025.zip", "fd5dd74a62b828608c62335b7c324ddf05be58e3f05465fee68854795f5b1a92", "enrollment_2024-25.csv", "utf-8"),
    "enr_2025_26": ("Enrollment-in-SY-2025-2026.zip", "ab4d7e24b3a46a99db2c76dee5279a976e4c3a76062e79f7217e70dc6dd1b450", "enrollment_2025-26.csv", "cp1252"),
    "fac_2023_24": ("School-Facilities-in-SY-2023-2024.zip", "9317af02b595d3a8d7381715780ef183a92da35354bbe0f3796045490e546609", "facilities_2023-24.csv", "utf-8"),
}
YEARS = {"enr_2020_21": "2020-21", "enr_2021_22": "2021-22", "enr_2022_23": "2022-23", "enr_2023_24": "2023-24", "enr_2024_25": "2024-25", "enr_2025_26": "2025-26"}

con = duckdb.connect()
readmes = {}
workdir = tempfile.TemporaryDirectory()

# %% Verify checksums, load data as text, read DepEd's README
for table, (zip_name, sha, csv_name, encoding) in FILES.items():
    zip_path = ORIGINAL / zip_name
    if hashlib.sha256(zip_path.read_bytes()).hexdigest() != sha:
        sys.exit(f"{zip_name}: SHA-256 does not match the inventory card. Stop and re-inventory.")
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        data = zf.read(next(n for n in names if n.endswith("/" + csv_name)))
        readmes[table] = zf.read(next(n for n in names if n.endswith("/README.md"))).decode("utf-8", "replace")
    copy = Path(workdir.name) / csv_name
    copy.write_text(data.decode(encoding).replace("\r\n", "\n"), encoding="utf-8")
    con.execute(f"CREATE TABLE {table} AS SELECT * FROM read_csv('{copy}', all_varchar = true, header = true, strict_mode = true)")


def readme_variables(text):
    """Map variable name -> (DepEd type, description, notes) from the README tables."""
    out = {}
    for line in text.splitlines():
        m = re.match(r"^\|\s*`([^`]+)`\s*\|(.*)\|\s*$", line)
        if not m:
            continue
        cells = [c.strip() for c in m.group(2).split("|")]
        if len(cells) >= 2:
            out[m.group(1)] = (cells[0], cells[1], cells[2] if len(cells) > 2 else "")
    return out


# %% Column statistics
def q(sql):
    return con.execute(sql).fetchall()


def cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def quoted(value):
    return "(blank)" if value is None else f"`{cell(value)}`"


def describe(table, column, where="TRUE"):
    col = f'"{column}"'
    total, filled, distinct = q(f"""SELECT count(*), count(*) FILTER (WHERE {col} IS NOT NULL AND trim({col}) <> ''),
                                       count(DISTINCT {col}) FROM {table} WHERE {where}""")[0]
    pct = f"{100.0 * filled / total:.1f}%" if total else "n/a"
    values = [v for (v,) in q(f"SELECT DISTINCT {col} FROM {table} WHERE {where} AND {col} IS NOT NULL LIMIT 50")]
    if not filled:
        return "all blank", pct, "0", "no values"
    if distinct == filled and all(re.fullmatch(r"\d+", v) for v in values):
        kind = "identifier (unique)"
        sample = ", ".join(quoted(v) for (v,) in q(f"SELECT {col} FROM {table} WHERE {where} ORDER BY {col} LIMIT 3"))
    elif values and all(re.fullmatch(r"-?\d+", v.strip()) for v in values):
        kind = "whole number"
        lo, med, hi, zeros = q(f"""SELECT min(try_cast({col} AS BIGINT)), median(try_cast({col} AS BIGINT)),
                                          max(try_cast({col} AS BIGINT)), count(*) FILTER (WHERE try_cast({col} AS BIGINT) = 0)
                                   FROM {table} WHERE {where}""")[0]
        sample = f"min {lo:,}, median {med:,.0f}, max {hi:,}; zeros: {zeros:,}" if lo is not None else "all blank"
    elif values and set(values) <= {"True", "False", "Yes", "No"}:
        kind = "yes/no"
        sample = ", ".join(f"{quoted(v)} {n:,}" for v, n in q(f"SELECT {col}, count(*) FROM {table} WHERE {where} GROUP BY 1 ORDER BY 2 DESC"))
    elif distinct <= 20:
        kind = "category"
        sample = ", ".join(f"{quoted(v)} {n:,}" for v, n in q(f"SELECT {col}, count(*) FROM {table} WHERE {where} AND {col} IS NOT NULL GROUP BY 1 ORDER BY 2 DESC, 1"))
    else:
        kind = "text"
        sample = "most common: " + ", ".join(f"{quoted(v)} {n:,}" for v, n in q(f"SELECT {col}, count(*) FROM {table} WHERE {where} AND {col} IS NOT NULL GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 3"))
    return kind, pct, f"{distinct:,}", sample


def columns(table):
    return [r[0] for r in q(f"DESCRIBE {table}")]


# %% Our interpretation (D-011)
# The team's reading of a column, kept apart from DepEd's words. Every entry is
# computed from the data, so a rerun re-checks the evidence.
OFFERING = '"Modified Curricular Offering Classification"'


def offering_interpretation():
    """[observed] if each label matches exactly one offers_es/jhs/shs combination."""
    combos = {}
    for label, es, jhs, shs, n in q(f"SELECT {OFFERING}, offers_es, offers_jhs, offers_shs, count(*) FROM enr_2025_26 GROUP BY ALL ORDER BY 5 DESC"):
        combos.setdefault(label, []).append(((es, jhs, shs), n))
    if any(len(v) > 1 for v in combos.values()) or len({v[0][0] for v in combos.values()}) != len(combos):
        return "[assumed] Which levels the school offers, going by the labels. The labels do not map one-to-one to `offers_es`, `offers_jhs`, `offers_shs`."
    levels = ("ES", "JHS", "SHS")
    pairs = "; ".join(f"`{label}` = {' + '.join(l for l, flag in zip(levels, v[0][0]) if flag == 'Yes') or 'none'}" for label, v in combos.items())
    total = sum(v[0][1] for v in combos.values())
    return (f"[observed] Which levels the school offers. In SY 2025-26 each label matches exactly one combination of "
            f"`offers_es`, `offers_jhs`, `offers_shs` for all {total:,} schools: {pairs}.")


ENR_INTERPRETATION = {"Modified Curricular Offering Classification": offering_interpretation}

# Facilities columns named es_, jhs_, shs_, hs_ describe one level. Blank means the school
# does not offer that level, if no public school without the level has a value.
LEVEL_OFFERS = {
    "es": ("e.offers_es = 'True'", "elementary"),
    "jhs": ("e.offers_jhs = 'True'", "junior high"),
    "shs": ("e.offers_shs = 'True'", "senior high"),
    "hs": ("(e.offers_jhs = 'True' OR e.offers_shs = 'True')", "junior or senior high"),
}


def level_interpretation(column):
    prefix = column.split("_")[0]
    if prefix not in LEVEL_OFFERS:
        return ""
    offers, name = LEVEL_OFFERS[prefix]
    filled = f"trim(coalesce(f.\"{column}\", '')) <> ''"
    on, on_filled, off, off_filled = q(f"""SELECT count(*) FILTER (WHERE {offers}), count(*) FILTER (WHERE {offers} AND {filled}),
                                               count(*) FILTER (WHERE NOT {offers}), count(*) FILTER (WHERE NOT {offers} AND {filled})
                                        FROM fac_2023_24 f JOIN enr_2023_24 e USING (school_id) WHERE f.sector = 'Public'""")[0]
    if off_filled:
        return ""
    missing = f"; {on - on_filled:,} missing" if on_filled < on else ""
    text = (f"[observed] Only for public schools offering {name}: filled {on_filled:,} of {on:,}{missing}; "
            f"0 of {off:,} without it. Blank = not applicable, not zero.")
    if prefix == "hs":
        text += " `hs_` = junior and senior high together."
    return text


# %% deped_enrollment dictionary
enr_docs = readme_variables(readmes["enr_2023_24"])
enr_docs.update(readme_variables(readmes["enr_2025_26"]))
all_cols = []
for t in YEARS:
    for c in columns(t):
        if c not in all_cols:
            all_cols.append(c)

rows = []
for c in all_cols:
    present = [y for t, y in YEARS.items() if c in columns(t)]
    stats_table = "enr_2023_24" if "enr_2023_24" in [t for t in YEARS if c in columns(t)] else "enr_2025_26"
    kind, pct, distinct, sample = describe(stats_table, c)
    deped_type, desc, notes = enr_docs.get(c, ("", "**Not in DepEd's README (undocumented)**", ""))
    # Flag label changes only (not count changes), e.g. DepEd -> DepED Managed.
    if kind in ("category", "yes/no") and c in columns("enr_2025_26") and stats_table != "enr_2025_26":
        labels = {v for (v,) in q(f'SELECT DISTINCT "{c}" FROM {stats_table} WHERE "{c}" IS NOT NULL')}
        labels_new = {v for (v,) in q(f'SELECT DISTINCT "{c}" FROM enr_2025_26 WHERE "{c}" IS NOT NULL')}
        if labels != labels_new:
            notes = (notes + " " if notes else "") + f"**Labels change in SY 2025-26:** {describe('enr_2025_26', c)[3]}"
    stats_year = YEARS[stats_table]
    interpretation = ENR_INTERPRETATION[c]() if c in ENR_INTERPRETATION else ""
    rows.append(f"| `{c}` | {', '.join(present)} | {cell(deped_type)} | {cell(desc)} | {cell(notes)} | {cell(interpretation)} | {kind} | {pct} | {distinct} | {sample} ({stats_year}) |")

enr_md = f"""# deped_enrollment: data dictionary

Generated by [`analysis/profiling/dictionary_deped.py`](../../../../analysis/profiling/dictionary_deped.py). Do not edit by hand; rerun the script instead.

- **Description, DepEd type, and DepEd notes:** copied from DepEd's `README.md` inside the SY 2023-24 and SY 2025-26 zips (the SY 2020-21, 2021-22, and 2022-23 READMEs are identical to SY 2023-24's).
- **Our interpretation:** the team's reading where DepEd's description is missing or incomplete, labeled **[other source]**, **[observed]**, or **[assumed]** with its evidence (D-011). Computed by the script. Blank when DepEd's description is enough.
- **Observed columns:** measured from the data, read as text. Statistics use SY 2023-24 unless the column exists only in SY 2025-26. "Filled" is the share of rows that are not blank.
- **Kinds:** identifier (unique whole numbers), whole number (min, median, max, zeros), yes/no, category (up to 20 values, all listed), text (the three most common values).

See [profile.md](profile.md) for the findings behind these numbers, and [README.md](README.md) for the source card.

| Column | School years | DepEd type | Description (DepEd) | DepEd notes | Our interpretation | Observed kind | Filled | Distinct | Samples or range |
|---|---|---|---|---|---|---|---|---|---|
""" + "\n".join(rows) + "\n"

(REPO / "docs/data/source-inventory/deped_enrollment/data_dictionary.md").write_text(enr_md, encoding="utf-8")
print(f"deped_enrollment: {len(rows)} columns written")

# %% deped_facilities dictionary
fac_docs = readme_variables(readmes["fac_2023_24"])
rows = []
for c in columns("fac_2023_24"):
    kind, pct, distinct, sample = describe("fac_2023_24", c)
    _, public_pct, _, _ = describe("fac_2023_24", c, "sector = 'Public'")
    deped_type, desc, notes = fac_docs.get(c, ("", "**Not in DepEd's README (undocumented)**", ""))
    rows.append(f"| `{c}` | {cell(deped_type)} | {cell(desc)} | {cell(notes)} | {cell(level_interpretation(c))} | {kind} | {pct} | {public_pct} | {distinct} | {sample} |")

fac_md = f"""# deped_facilities: data dictionary

Generated by [`analysis/profiling/dictionary_deped.py`](../../../../analysis/profiling/dictionary_deped.py). Do not edit by hand; rerun the script instead.

- **Description, DepEd type, and DepEd notes:** copied from DepEd's `README.md` inside the SY 2023-24 zip.
- **Our interpretation:** the team's reading where DepEd's description is missing or incomplete, labeled **[other source]**, **[observed]**, or **[assumed]** with its evidence (D-011). Computed by the script. Blank when DepEd's description is enough.
- **Observed columns:** measured from SY 2023-24, read as text. "Filled" is the share of rows that are not blank, for all schools and for public schools only (facility data covers public schools only).
- **Kinds:** identifier (unique whole numbers), whole number (min, median, max, zeros), yes/no, category (up to 20 values, all listed), text (the three most common values).

Location is not in this file; it comes from `deped_enrollment` through `school_id`. See [profile.md](profile.md) for findings and [README.md](README.md) for the source card.

| Column | DepEd type | Description (DepEd) | DepEd notes | Our interpretation | Observed kind | Filled (all) | Filled (public) | Distinct | Samples or range |
|---|---|---|---|---|---|---|---|---|---|
""" + "\n".join(rows) + "\n"

(REPO / "docs/data/source-inventory/deped_facilities/data_dictionary.md").write_text(fac_md, encoding="utf-8")
print(f"deped_facilities: {len(rows)} columns written")

workdir.cleanup()
