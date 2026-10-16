# Generates the source data dictionary for psa_school_age_population:
#   docs/data/source-inventory/psa_school_age_population/data_dictionary.md
#
# The workbooks have no separate documentation. Publisher text comes from each sheet's title
# (row 1), its column bands (row 2), the ages (row 3), and, for 2024, the notes below the table;
# everything else is measured from the sheets. Output is deterministic, so rerunning on the same
# files changes nothing.
#
#   RAW_DATA_DIR=~/Projects/reached-hq/raw-data python analysis/profiling/dictionary_psa_school_age_population.py
#
# The workbooks are read with the standard library and loaded into DuckDB as text (D-007).

# %% Setup
import csv
import hashlib
import os
import sys
import tempfile
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from src.profiling.xlsx import column_letter, read_sheet

raw_dir = os.environ.get("RAW_DATA_DIR")
if not raw_dir:
    sys.exit("Set RAW_DATA_DIR to the folder that contains psa/original/.")
ORIGINAL = Path(raw_dir).expanduser() / "psa" / "original"

FILES = {
    2020: ("2020 School-Age Population by Single Year Age, Sex, and City Municipality.xlsx",
           "e40d71839b951926cd3c9515c1edafbb6a2121f734670716e3b21bd3f9dcd35f", 61, 4),
    2024: ("2024 School-Age Population by Single Year Age, Sex, and City Municipality.xlsx",
           "49d15bb0cdd191cd6aef4a14f4b063da247ba791b32caa653c37c464dff15954", 21, 3),
}  # file, SHA-256, columns, last header row
SHEETS = ("Total Pop", "Household Pop")


def sql_string(text):
    return "'" + str(text).replace("'", "''") + "'"


def cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


con = duckdb.connect()
workdir = tempfile.TemporaryDirectory()


def q(sql):
    return con.execute(sql).fetchall()


# The team's reading of a column (D-011). Finding IDs refer to profile.md.
LABEL_NOTE = {
    2020: ("**[observed]** Place names only, no codes and no level column. The level comes from the sums: each region, province, "
           "and the country equals the sum of the rows below it, in all 60 cells (O-2). Old names and `(Capital)` in brackets (O-6)."),
    2024: ("**[observed]** Two kinds of rows: a place name with no values, then `Total`, `Male`, `Female` rows holding the values (O-1). "
           "No codes and no level column; the level comes from the sums, as in 2020 (O-2). Footnote markers such as `1/` end some names; "
           "the notes are below the table (O-6)."),
}

sections = []
for year, (name, digest, width, header_rows) in FILES.items():
    path = ORIGINAL / name
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        sys.exit(f"{name}: SHA-256 does not match the inventory card. Stop and re-inventory.")
    for suffix in SHEETS:
        sheet = f"{year} {suffix}"
        rows = read_sheet(path, sheet)
        title = rows[0][1].get(1, "")
        band, bands = "", {}
        for c in range(1, width + 1):
            band = rows[1][1].get(c, band) if c > 1 else rows[1][1].get(1, "")
            bands[c] = band
        ages = {c: rows[2][1].get(c, "") for c in range(2, width + 1)}
        body = [cells for _, cells in rows[header_rows:]
                if cells.get(1) is not None and any(cells.get(c) is not None for c in range(2, width + 1))]
        csv_path = Path(workdir.name) / f"{year}_{suffix.replace(' ', '_')}.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([f"c{c}" for c in range(1, width + 1)])
            for cells in body:
                w.writerow([cells.get(c, "") for c in range(1, width + 1)])
        table = f"t{year}_{suffix.split()[0].lower()}"
        con.execute(f"CREATE TABLE {table} AS SELECT * FROM read_csv('{csv_path.as_posix()}', all_varchar = true, header = true, strict_mode = true)")
        out = []
        for c in range(1, width + 1):
            col = f"c{c}"
            n, filled, distinct = q(f"SELECT count(*), count({col}), count(DISTINCT {col}) FROM {table}")[0]
            if c == 1:
                header = bands[1] or "(no header)"
                desc = f"Sheet title: \"{title}\". Header: \"{bands[1]}\"" if bands[1] else f"Sheet title: \"{title}\""
                kind = "text"
                top = q(f"SELECT {col}, count(*) FROM {table} GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 3")
                sample = "most common: " + ", ".join(f"`{cell(v)}` {k:,}" for v, k in top)
                note = LABEL_NOTE[year]
            else:
                age = ages[c]
                age = str(int(float(age))) if age else ""
                header = f"{bands[c]}, age {age}" if year == 2020 else f"age {age}"
                desc = f"Row 2 \"{bands[c]}\", row 3 \"{age}\""
                lo, med, hi, zeros, whole = q(f"""SELECT min(try_cast({col} AS BIGINT)), median(try_cast({col} AS BIGINT)),
                    max(try_cast({col} AS BIGINT)), count(*) FILTER (WHERE try_cast({col} AS BIGINT) = 0),
                    count(*) FILTER (WHERE regexp_full_match({col}, '[0-9]+')) FROM {table}""")[0]
                kind = "whole number" if whole == filled else "text"
                sample = f"min {lo:,}, median {med:,.0f}, max {hi:,}; zeros: {zeros:,}"
                note = ""
                if c == 2:
                    note = ("**[observed]** Every count is a whole number, none blank. Both sexes equals male plus female in every cell (O-4). "
                            "Rows include the country, regions, and provinces, which are sums of the rows below them (O-2), so the "
                            "median and maximum mix levels.") if year == 2020 else (
                            "**[observed]** Every count is a whole number, none blank. In each place, `Total` equals `Male` plus `Female` "
                            "(O-4). Rows include the country, regions, and provinces (O-2), so the median and maximum mix levels.")
            pct = "100.0%" if filled == n else f"{100.0 * filled / n:.1f}%"
            out.append(f"| {column_letter(c)} | {cell(header)} | {cell(desc)} | {cell(note)} | {kind} | {pct} | {distinct:,} | {cell(sample)} |")
        sections.append((sheet, name, len(body), out))

md = """# psa_school_age_population: data dictionary

Generated by [`analysis/profiling/dictionary_psa_school_age_population.py`](../../../../analysis/profiling/dictionary_psa_school_age_population.py). Do not edit by hand; rerun the script instead.

- **Description (publisher):** the workbooks have no separate documentation and state no data types. The only publisher text is each sheet's title (row 1), its column bands (row 2), the ages (row 3), the source line, and, in 2024, the notes below the table; it is quoted where it applies.
- **Our interpretation:** what the team reads a column to mean when the publisher's description is missing or incomplete (D-011). Every entry starts with a label: **[other source]** (documented elsewhere, cited), **[observed]** (shown by the data, with the numbers), or **[assumed]** (a reasonable reading, not yet proven). Blank when the publisher's description is enough.
- **Observed columns:** measured from every row below the header rows that has a label and at least one value, read as text. In 2024 those are the `Total`, `Male`, `Female` rows; the place-name rows above them hold no values and are described in [profile.md](profile.md) (O-1). "Filled" is the share of those rows that are not blank.
- **Kinds:** whole number (min, median, max, zeros), text (the three most common values).

See [profile.md](profile.md) for findings and [README.md](README.md) for the source card.
"""
for sheet, name, n, out in sections:
    md += f"""
## Sheet `{sheet}`

`{name}`, {n:,} rows.

| Col | Header | Description (publisher) | Our interpretation | Observed kind | Filled | Distinct | Samples or range |
|---|---|---|---|---|---|---|---|
""" + "\n".join(out) + "\n"

target = REPO / "docs/data/source-inventory/psa_school_age_population/data_dictionary.md"
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(md, encoding="utf-8")
print(f"psa_school_age_population: {sum(len(o) for *_, o in sections)} columns in {len(sections)} sheets written")

workdir.cleanup()
