# Generates the source data dictionary for deped_psgc_coordinates:
#   docs/data/source-inventory/deped_psgc_coordinates/data_dictionary.md
#
# The workbook has no separate documentation. Publisher text comes from its own title
# rows (1-5) and the notes in row 6; everything else is measured from the DB sheet.
# Output is deterministic, so rerunning on the same file changes nothing.
#
#   RAW_DATA_DIR=~/Projects/reached-hq/raw-data python analysis/profiling/dictionary_deped_psgc_coordinates.py
#
# The workbook is read with the standard library and loaded into DuckDB as text (D-007).

# %% Setup
import csv
import hashlib
import os
import re
import sys
import tempfile
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from src.profiling.xlsx import column_letter, read_sheet

raw_dir = os.environ.get("RAW_DATA_DIR")
if not raw_dir:
    sys.exit("Set RAW_DATA_DIR to the folder that contains deped/original/.")
ORIGINAL = Path(raw_dir).expanduser() / "deped" / "original"

FILE = "SY 2023-2024 School Level Data on Enrollment with PSGC Longitude & Latitude (Public only).xlsx"
SHA256 = "edf7ba68cb768d658226a316754d636bec1d792b290692b14dd0cdd6e62fc8a1"
SHEET = "DB"
HEADER_ROW = 8
WIDTH = 88


def sql_string(text):
    return "'" + str(text).replace("'", "''") + "'"


# %% Verify checksum, load the DB sheet as text
path = ORIGINAL / FILE
if hashlib.sha256(path.read_bytes()).hexdigest() != SHA256:
    sys.exit(f"{FILE}: SHA-256 does not match the inventory card. Stop and re-inventory.")

rows = read_sheet(path, SHEET)
header = rows[HEADER_ROW - 1][1]
if max(header) != WIDTH:
    sys.exit(f"{FILE}: expected {WIDTH} header columns in row {HEADER_ROW}, found {max(header)}.")
# Columns are named "<letter> <header>", so the two columns headed "NEW INCOME CLASSIFICATION" stay apart.
names = [f"{column_letter(i)} {re.sub(r'\s+', ' ', header.get(i, '')).strip()}" for i in range(1, WIDTH + 1)]

workdir = tempfile.TemporaryDirectory()
csv_path = Path(workdir.name) / "db.csv"
with csv_path.open("w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(names)
    for _, cells in rows[HEADER_ROW:]:
        if 4 in cells:  # school rows only; every row of this file has a school ID (profile O-1)
            writer.writerow([cells.get(i, "") for i in range(1, WIDTH + 1)])

con = duckdb.connect()
name_list = "[" + ", ".join(sql_string(n) for n in names) + "]"
con.execute(f"""CREATE TABLE db AS SELECT * FROM read_csv('{csv_path}', all_varchar = true, header = true,
                names = {name_list}, strict_mode = true)""")


# %% Column statistics
def q(sql):
    return con.execute(sql).fetchall()


def cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def quoted(value):
    return "(blank)" if value is None else f"`{cell(value)}`"


def percent(filled, total):
    if not total:
        return "n/a"
    if filled == total:
        return "100.0%"
    p = 100.0 * filled / total
    return "<0.1%" if 0 < p < 0.1 else f"{min(p, 99.9):.1f}%"


def describe(column):
    col = f'"{column}"'
    total, filled, distinct, digits, numeric, decimal = q(f"""
        SELECT count(*),
               count(*) FILTER (WHERE {col} IS NOT NULL AND trim({col}) <> ''),
               count(DISTINCT {col}),
               count(*) FILTER (WHERE regexp_full_match({col}, '[0-9]+')),
               count(*) FILTER (WHERE regexp_full_match(trim({col}), '-?[0-9]+')),
               count(*) FILTER (WHERE try_cast({col} AS DOUBLE) IS NOT NULL)
        FROM db""")[0]
    pct = percent(filled, total)
    if not filled:
        return "all blank", pct, "0", "no values"
    if distinct == filled and digits == filled:
        kind = "identifier (unique)"
        sample = ", ".join(quoted(v) for (v,) in q(f"SELECT {col} FROM db WHERE {col} IS NOT NULL ORDER BY {col} LIMIT 3"))
    elif numeric == filled:
        kind = "whole number"
        lo, med, hi, zeros = q(f"""SELECT min(try_cast({col} AS BIGINT)), median(try_cast({col} AS BIGINT)),
                                          max(try_cast({col} AS BIGINT)), count(*) FILTER (WHERE try_cast({col} AS BIGINT) = 0)
                                   FROM db""")[0]
        sample = f"min {lo:,}, median {med:,.0f}, max {hi:,}; zeros: {zeros:,}"
    elif distinct <= 20:
        kind = "category"
        sample = ", ".join(f"{quoted(v)} {n:,}" for v, n in q(f"SELECT {col}, count(*) FROM db WHERE {col} IS NOT NULL GROUP BY 1 ORDER BY 2 DESC, 1"))
    elif decimal and filled - decimal <= 0.25 * filled and decimal > numeric:
        kind = "decimal number, with text values"
        lo, med, hi = q(f"""SELECT min(try_cast({col} AS DOUBLE)), median(try_cast({col} AS DOUBLE)), max(try_cast({col} AS DOUBLE)) FROM db""")[0]
        odd = q(f"""SELECT {col}, count(*) FROM db WHERE {col} IS NOT NULL AND try_cast({col} AS DOUBLE) IS NULL GROUP BY 1 ORDER BY 2 DESC, 1""")
        sample = (f"{decimal:,} of {filled:,} values are numbers (min {lo:.4f}, median {med:.4f}, max {hi:.4f}); "
                  "not a number: " + ", ".join(f"{quoted(v)} {n:,}" for v, n in odd))
    else:
        kind = "text"
        sample = "most common: " + ", ".join(f"{quoted(v)} {n:,}" for v, n in q(f"SELECT {col}, count(*) FROM db WHERE {col} IS NOT NULL GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 3"))
        if digits and filled - digits <= 0.05 * filled:
            odd = q(f"""SELECT {col}, count(*) FROM db WHERE {col} IS NOT NULL AND NOT regexp_full_match({col}, '[0-9]+') GROUP BY 1 ORDER BY 2 DESC, 1""")
            lengths = q(f"SELECT length({col}), count(*) FROM db WHERE regexp_full_match({col}, '[0-9]+') GROUP BY 1 ORDER BY 1")
            sample = (f"{digits:,} of {filled:,} values are digits (length " + ", ".join(f"{n_}: {c_:,}" for n_, c_ in lengths)
                      + "); not digits: " + ", ".join(f"{quoted(v)} {n:,}" for v, n in odd))
    return kind, pct, f"{distinct:,}", sample


# %% What the workbook itself says (title rows 1-5, notes in row 6, the grade band in row 6, sex in row 7)
UNDOCUMENTED = "**Not in the publisher's documentation (undocumented)**"
TITLE = " ".join(rows[i][1].get(1, "") for i in range(3))  # official enrollment, SY 2023-2024, LIS as of 2024-01-31
PSGC_NOTE = rows[3][1].get(1, "")
INCOME_NOTE = rows[4][1].get(1, "")
COORD_NOTE = rows[5][1].get(29, "")
band = {}
current = ""
for i in range(31, WIDTH + 1):
    current = rows[5][1].get(i, current)
    band[i] = f"{current}, {rows[6][1].get(i, '')}"

DOCS = {}
for i in range(18, 26):
    DOCS[i] = (f"Row 4 and the note above column R: \"{PSGC_NOTE}\"", "")
DOCS[26] = ("Header: \"Urban / Rural (based on 2020 CPH)\"", "")
DOCS[27] = DOCS[28] = (f"Row 5: \"{INCOME_NOTE}\"", "")
DOCS[29] = DOCS[30] = (f"Note above column AC: \"{COORD_NOTE}\"", "")
for i in range(31, WIDTH + 1):
    DOCS[i] = (f"Rows 6-7: {band[i]}. Title rows 1-3: \"{TITLE}\"", "")

# The team's reading of a column (D-011). Every entry starts with a label and gives its evidence.
# Finding IDs (O-n, S-n) refer to docs/data/source-inventory/deped_psgc_coordinates/profile.md.
DOCS[11] = ("Row 6, cell A6: \"" + rows[5][1].get(1, "") + "\"", "")
INTERPRETATION = {
    4: ("**[other source]** The DepEd school ID, `school_id` in deped_enrollment (\"6-digit unique school identifier\", "
        "deped_enrollment data dictionary). **[observed]** 6 digits and unique on all 47,818 rows (O-2)."),
    11: "**[observed]** `Public` on every row, as cell A6 states (O-1).",
    18: ("**[observed]** Stored as numbers, so codes of regions I to IX lost their leading zero: 28,811 values have 9 digits. "
         "Pad to 10 digits before joining. `#N/A` on 204 rows (O-3)."),
    20: "**[observed]** As column R: leading zero dropped, `#N/A` on 204 rows (O-3).",
    22: "**[observed]** As column R: leading zero dropped, `#N/A` on 204 rows (O-3).",
    24: "**[observed]** As column R: leading zero dropped, `#N/A` on 204 rows (O-3).",
    26: "**[observed]** `R`, `U`, `-` (29 rows), `#N/A` (O-5).",
    27: "**[observed]** `1St` on 72 rows is `1st` with a capital (O-5).",
    28: "**[observed]** The same header as column AA, with the kind of LGU added (`1st Class City`, `1st Class Municipality`).",
    29: ("**[other source]** NSBI is the National School Building Inventory, which covers public schools (School Characteristics "
         "Technical Notes, p. 3, 12). **[observed]** `#N/A` on 679 rows; 5 schools at (0, 0) and 54 others outside the Philippines (O-4). "
         "260 schools are over 100 km from the median point of their own city or municipality (O-6)."),
    30: "**[observed]** As column AC (O-4, O-6).",
}
for i in range(31, WIDTH + 1):
    if "PBM" in header[i]:
        INTERPRETATION[i] = ("**[other source]** PBM is Pre-Baccalaureate Maritime, `g1x_maritime_*` in deped_enrollment "
                             "(\"Pre-Baccalaureate Maritime Strand students\" in its dictionary).")

# %% deped_psgc_coordinates dictionary
total_rows = q("SELECT count(*) FROM db")[0][0]
out_rows = []
for i, c in enumerate(names, start=1):
    kind, pct, distinct, sample = describe(c)
    desc, notes = DOCS.get(i, (UNDOCUMENTED, ""))
    letter, _, title = c.partition(" ")
    out_rows.append(f"| {letter} | `{cell(title)}` | {cell(desc)} | {cell(notes)} | {cell(INTERPRETATION.get(i, ''))} | {kind} | {pct} | {distinct} | {sample} |")

md = f"""# deped_psgc_coordinates: data dictionary

Generated by [`analysis/profiling/dictionary_deped_psgc_coordinates.py`](../../../../analysis/profiling/dictionary_deped_psgc_coordinates.py). Do not edit by hand; rerun the script instead.

- **Description (publisher):** the workbook has no separate documentation and states no data types. The only publisher text is its title rows 1-5, the sector and notes in row 6, and the grade and sex bands in rows 6-7; it is quoted where it applies to a column. Column headers are in row {HEADER_ROW}.
- **Our interpretation:** what the team reads a column to mean when the publisher's description is missing or incomplete (D-011). Every entry starts with a label: **[other source]** (documented elsewhere, cited), **[observed]** (shown by the data, with the numbers), or **[assumed]** (a reasonable reading, not yet proven). Blank when the publisher's description is enough.
- **Observed columns:** measured from the `{SHEET}` sheet of `{FILE}` ({total_rows:,} school rows: every row below the header with a school ID), read as text. "Filled" is the share of rows that are not blank; `#N/A` counts as filled.
- **Kinds:** identifier (unique whole numbers), whole number (min, median, max, zeros), decimal number with text values (the text values are listed), category (up to 20 values, all listed), text (the three most common values; digit columns list their lengths and the values that are not digits), all blank.

See [profile.md](profile.md) for findings and [README.md](README.md) for the source card.

| Col | Header (row {HEADER_ROW}) | Description (publisher) | Publisher notes | Our interpretation | Observed kind | Filled | Distinct | Samples or range |
|---|---|---|---|---|---|---|---|---|
""" + "\n".join(out_rows) + "\n"

out = REPO / "docs/data/source-inventory/deped_psgc_coordinates/data_dictionary.md"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(md, encoding="utf-8")
print(f"deped_psgc_coordinates: {len(out_rows)} columns written")

workdir.cleanup()
