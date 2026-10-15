# Generates the source data dictionary for deped_enrollment_psgc:
#   docs/data/source-inventory/deped_enrollment_psgc/data_dictionary.md
#
# The workbook has no separate documentation. Publisher text comes from its own title
# rows (1-5) and the notes in row 6; everything else is measured from the DB sheet.
# Output is deterministic, so rerunning on the same file changes nothing.
#
#   RAW_DATA_DIR=~/Projects/reached-hq/raw-data python analysis/profiling/dictionary_deped_enrollment_psgc.py
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

FILE = "SY 2023-2024 School Level Data on Enrollment with PSGC, Longitude and Latitude.xlsx"
SHA256 = "746d69530d228d2324590be10abbe6d75a94176c1745ef74335a4d6db550acd5"
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
        if 4 in cells:  # school rows only; the row with no school ID is profile finding O-1
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
# Finding IDs (O-n, S-n, X-n) refer to docs/data/source-inventory/deped_enrollment_psgc/profile.md.
DEPED_DICT = "deped_enrollment data dictionary"
INTERPRETATION = {
    4: ("**[other source]** The DepEd school ID, `school_id` in deped_enrollment (\"6-digit unique school identifier\", "
        f"{DEPED_DICT}). **[observed]** The 60,167 IDs in rows 9-60175 are exactly the IDs of enrollment_2023-24.csv (X-1). "
        "The 108 rows after the gaps add one 7-digit ID (`1406363`) and one ID on two identical rows (`404520`) (O-3)."),
    11: ("**[other source]** Public, Private, SUC/LUC, or PSO, as `sector` in deped_enrollment. "
         "**[observed]** Spelled `SUCsLUCs` here, the label deped_enrollment uses from SY 2025-26."),
    13: ("**[other source]** `annex_status` in deped_enrollment, with the SY 2025-26 labels."),
    16: ("**[observed]** Three values: `Partially Urban`, `Urban`, `Rural`; blank on the 108 appended rows. Not the same as column Z: "
         "1,309 `Urban` schools are in rural barangays and 244 `Rural` schools in urban barangays (O-9). "
         "**[assumed]** DepEd's own urban/rural classification of the school (S-4)."),
    17: ("**[other source]** Its six labels are labels of `Modified Curricular Offering Classification`, published from SY 2025-26 in deped_enrollment, "
         "where each label is one combination of ES, JHS, SHS offerings."),
    18: ("**[observed]** Stored as numbers, so codes of regions I to IX lost their leading zero: 36,014 values have 9 digits, 23,490 have 10. "
         "Pad to 10 digits before joining (O-5). `#N/A` on 663 rows, blank on 108 (O-6)."),
    20: ("**[observed]** As column R: leading zero dropped (O-5). For the 117 schools of Angeles City (HUC) it is Pampanga, "
         "which is not the parent of the city's own code (O-7)."),
    22: ("**[observed]** As column R: leading zero dropped (O-5); `#N/A` on 663 rows (O-6)."),
    24: ("**[observed]** As column R: leading zero dropped (O-5); `#N/A` on 667 rows (O-6). All 59,500 numeric codes, padded to 10 digits, "
         "are barangays in PSGC Q4_2023 or 2Q 2026; 2,704 are Negros Island Region codes (X-2). "
         "3 schools have a barangay outside their city or municipality code (O-7)."),
    25: ("**[observed]** Matches the DepEd `Barangay` name (column J), ignoring case and spaces, for 52,049 of 59,500 schools (O-12)."),
    26: ("**[observed]** `R`, `U`, `-` (80 schools), `#N/A` (667). The barangays of all 80 `-` schools are in PSGC 2Q 2026, and 53 of them are in Q4_2023 (X-2). "
         "psa_psgc also uses `-`, for barangays with no 2020 classification (psa_psgc O-8)."),
    27: ("**[observed]** `1St` on 89 rows is `1st` with a capital (O-8). `SGA (No Income Classification)` on 112 rows: "
         "the Special Geographic Area municipalities, `-` in psa_psgc O-7."),
    28: ("**[observed]** Column AA with the kind of LGU added (`1st Class City`, `1st Class Municipality`); "
         "the same header as AA. Never disagrees with AA (O-8)."),
    29: ("**[other source]** NSBI is the National School Building Inventory; the Technical Notes (p. 3, 12) say it covers public schools only "
         "(deped_facilities README). **[observed]** `#N/A` on 13,793 schools (22.9%), blank on 108; 6 schools at (0, 0) and 54 others "
         "outside the Philippines; 13,536 longitudes carry binary-float digits (O-10). 2,275 schools, including those 60, are over 100 km from the other schools of their city or municipality (O-11). "
         "Private schools have coordinates too, 7,503 of 12,207 (S-2)."),
    30: ("**[observed]** As column AC (O-10, O-11). Values carry binary-float digits, e.g. `5.0999999999999996` for 5.1 (O-10)."),
}
for i in range(31, WIDTH + 1):
    if "PBM" in header[i]:
        INTERPRETATION[i] = ("**[observed]** PBM is Pre-Baccalaureate Maritime: equal for every school to `g1x_maritime_*` in deped_enrollment, "
                             "\"Pre-Baccalaureate Maritime Strand students\" in its dictionary (X-1).")
for i in (31, 32):
    INTERPRETATION[i] = "**[observed]** All 58 count columns equal the matching deped_enrollment SY 2023-24 column for every school (X-1)."

# %% deped_enrollment_psgc dictionary
total_rows = q("SELECT count(*) FROM db")[0][0]
out_rows = []
for i, c in enumerate(names, start=1):
    kind, pct, distinct, sample = describe(c)
    desc, notes = DOCS.get(i, (UNDOCUMENTED, ""))
    letter, _, title = c.partition(" ")
    out_rows.append(f"| {letter} | `{cell(title)}` | {cell(desc)} | {cell(notes)} | {cell(INTERPRETATION.get(i, ''))} | {kind} | {pct} | {distinct} | {sample} |")

md = f"""# deped_enrollment_psgc: data dictionary

Generated by [`analysis/profiling/dictionary_deped_enrollment_psgc.py`](../../../../analysis/profiling/dictionary_deped_enrollment_psgc.py). Do not edit by hand; rerun the script instead.

- **Description (publisher):** the workbook has no separate documentation and states no data types. The only publisher text is its title rows 1-5, the notes in row 6, and the grade and sex bands in rows 6-7; it is quoted where it applies to a column. Column headers are in row {HEADER_ROW}.
- **Our interpretation:** what the team reads a column to mean when the publisher's description is missing or incomplete (D-011). Every entry starts with a label: **[other source]** (documented elsewhere, cited), **[observed]** (shown by the data, with the numbers), or **[assumed]** (a reasonable reading, not yet proven). Blank when the publisher's description is enough.
- **Observed columns:** measured from the `{SHEET}` sheet of `{FILE}` ({total_rows:,} school rows: every row below the header with a school ID), read as text. "Filled" is the share of rows that are not blank; `#N/A` counts as filled.
- **Kinds:** identifier (unique whole numbers), whole number (min, median, max, zeros), decimal number with text values (the text values are listed), category (up to 20 values, all listed), text (the three most common values; digit columns list their lengths and the values that are not digits), all blank.

See [profile.md](profile.md) for findings and [README.md](README.md) for the source card.

| Col | Header (row {HEADER_ROW}) | Description (publisher) | Publisher notes | Our interpretation | Observed kind | Filled | Distinct | Samples or range |
|---|---|---|---|---|---|---|---|---|
""" + "\n".join(out_rows) + "\n"

out = REPO / "docs/data/source-inventory/deped_enrollment_psgc/data_dictionary.md"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(md, encoding="utf-8")
print(f"deped_enrollment_psgc: {len(out_rows)} columns written")

workdir.cleanup()
