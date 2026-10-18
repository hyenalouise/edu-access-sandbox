# Profiles deped_enrollment_psgc: the SY 2023-2024 school-level enrollment workbook
# with PSGC codes, longitude, and latitude. Each check prints under the finding ID
# used in docs/data/source-inventory/deped_enrollment_psgc/profile.md.
#
#   RAW_DATA_DIR=~/Projects/reached-hq/raw-data python analysis/profiling/profile_deped_enrollment_psgc.py
#
# RAW_DATA_DIR must contain deped/original/ with FILE. The cross-checks (X-*) also use
# deped/original/Enrollment-in-SY-2023-2024.zip (S-3 and X-4 also the SY 2020-21, 2024-25, and
# 2025-26 zips) and psa/original/ (PSGC 2Q 2026 workbook
# and Q4_2023 API extract); each is skipped with a message when its file is absent.
# X-3 reuses the team's name matching by running analysis/cross_source/cross_source_deped.py,
# so it needs that script's files too (all five DepEd zips in deped/original/); running it
# also rewrites its generated list, docs/data/cross-source/generated/deped_psgc_unmatched.md.
# The xlsx reader is shared with the other profiling scripts: src/profiling/xlsx.py (D-007).
# Raw files are read, never modified. Runs locally with DuckDB; no Databricks compute.

# %% Setup
import collections
import contextlib
import csv
import hashlib
import io
import os
import re
import runpy
import sys
import tempfile
import zipfile
from itertools import zip_longest
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from src.ingestion.xlsx_table import mojibake
from src.profiling.xlsx import column_letter, read_sheet

raw_dir = os.environ.get("RAW_DATA_DIR")
if not raw_dir:
    sys.exit("Set RAW_DATA_DIR to the folder that contains deped/original/.")
RAW = Path(raw_dir).expanduser()
ORIGINAL = RAW / "deped" / "original"

FILE = "SY 2023-2024 School Level Data on Enrollment with PSGC, Longitude and Latitude.xlsx"
SHA256 = "746d69530d228d2324590be10abbe6d75a94176c1745ef74335a4d6db550acd5"
SHEET = "DB"
HEADER_ROW = 8  # rows 1-5 are titles, 6 is the grade band, 7 is sex, 8 is the column names

ENROLLMENT_ZIP = "Enrollment-in-SY-2023-2024.zip"
ENROLLMENT_ZIP_SHA256 = "a10f4d0f9082919c13b3a091774c8231c99c95b1b1872310714107013b77dbbb"
ENROLLMENT_CSV = "Enrollment in SY 2023-2024/enrollment_2023-24.csv"
# Later deped_enrollment years, used only to look up school IDs (S-3): zip, SHA-256, csv inside, encoding.
LATER_YEARS = {
    "2024-25": ("Enrollment-in-SY-2024-2025.zip", "fd5dd74a62b828608c62335b7c324ddf05be58e3f05465fee68854795f5b1a92",
                "Enrollment in SY 2024-2025/enrollment_2024-25.csv", "utf-8"),
    "2025-26": ("Enrollment-in-SY-2025-2026.zip", "ab4d7e24b3a46a99db2c76dee5279a976e4c3a76062e79f7217e70dc6dd1b450",
                "Enrollment-in-SY-2025-2026/enrollment_2025-26.csv", "cp1252"),
}
# The earlier deped_enrollment year (S-3, X-4): AP4's 2020 point pairs the 2020 Census with
# SY 2020-21 (D-042), so X-4 also measures how many of its schools and learners get no code.
EARLIER_YEAR = ("2020-21", ("Enrollment-in-SY-2020-2021.zip", "65c400aa31ba63730b8f9a7b4d60ade91c6a29cdb34a3c6bf255e5fc9e91a241",
                            "Enrollment in SY 2020-2021/enrollment_2020-21.csv", "utf-8"))
PSGC_2Q2026 = ("PSGC-2Q-2026-Publication-Datafile.xlsx", "31892bc2bdde3ea0682562d9412b5bab4d45a0be5e5a5b4f6c9d7714b94bca5d")
PSGC_Q4_2023 = ("PSGC-Q4_2023-API-all.csv", "38a92ceba5120fe10fb45ba23a8f74458ee076829306db795044beeb40715335")

GRADES = (
    ["K", "G1", "G2", "G3", "G4", "G5", "G6", "Elem NG", "G7", "G8", "G9", "G10", "JHS NG"]
    + [f"G{g} {s}" for g in (11, 12) for s in
       ("ACAD - ABM", "ACAD - HUMSS", "ACAD STEM", "ACAD GAS", "ACAD PBM", "TVL", "SPORTS", "ARTS")]
)
COUNT_HEADERS = [f"{g} {sex}" for g in GRADES for sex in ("Male", "Female")]
# Column names in row 8, in order. Columns are renamed by position, so a moved or
# inserted column must stop the run. AA and AB share a header.
EXPECTED_HEADER = [
    "Region", "Division", "District", "BEIS School ID", "School Name", "Street Address", "Province",
    "Municipality", "Legislative District", "Barangay", "Sector", "School Subclassification", "School Type",
    "Curricular Offering Classification", "Implementing Unit", "URP", "Modified COC",
    "(PSGC) REGION", "(PSGC) REGION NAME", "(PSGC) PROVINCE", "(PSGC) PROVINCE NAME",
    "(PSGC) MUNCIPAL/CITY", "(PSGC) MUNCIPAL/CITY NAME", "(PSGC) BARANGAY", "(PSGC) BARANGAY NAME",
    "Urban / Rural (based on 2020 CPH)", "NEW INCOME CLASSIFICATION (Based on DOF)",
    "NEW INCOME CLASSIFICATION (Based on DOF)", "Longitude", "Latitude",
] + COUNT_HEADERS
COLS = [
    "region", "division", "district", "school_id", "school_name", "street_address", "province",
    "municipality", "legislative_district", "barangay", "sector", "subclassification", "school_type",
    "coc", "implementing_unit", "urp", "modified_coc",
    "psgc_reg", "psgc_reg_name", "psgc_prv", "psgc_prv_name", "psgc_mun", "psgc_mun_name", "psgc_bgy", "psgc_bgy_name",
    "urban_rural", "income_class", "income_class_long", "lon", "lat",
] + [re.sub(r"[^a-z0-9]+", "_", h.lower()).strip("_") for h in COUNT_HEADERS]
COUNTS = COLS[30:]


def sql_string(text):
    return "'" + str(text).replace("'", "''") + "'"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


path = ORIGINAL / FILE
if sha256(path) != SHA256:
    sys.exit(f"{FILE}: SHA-256 does not match the inventory card. Stop and re-inventory.")

rows = read_sheet(path, SHEET)
header = dict(rows[HEADER_ROW - 1][1])
found = [re.sub(r"\s+", " ", header.get(i, "")).strip() for i in range(1, max(max(header), len(EXPECTED_HEADER)) + 1)]
problems = [
    f"column {column_letter(i)}: expected {want!r}, found {got!r}"
    for i, (want, got) in enumerate(zip_longest(EXPECTED_HEADER, found, fillvalue="(none)"), start=1)
    if want != got
]
if problems:
    sys.exit(f"{FILE}: the {SHEET} sheet header changed, so columns cannot be mapped by position:\n  " + "\n  ".join(problems))

workdir = tempfile.TemporaryDirectory()
csv_path = Path(workdir.name) / "db.csv"
with csv_path.open("w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["sheet_row"] + COLS)
    for row_number, cells in rows[HEADER_ROW:]:
        writer.writerow([row_number] + [cells.get(i, "") for i in range(1, len(COLS) + 1)])

con = duckdb.connect()
con.execute(f"""CREATE TABLE raw AS SELECT * FROM read_csv('{csv_path}', all_varchar = true, header = true,
                names = [{", ".join(sql_string(c) for c in ["sheet_row"] + COLS)}], strict_mode = true)""")
# d holds the school rows; the one row with no school ID is reported in O-1 and left out.
con.execute("CREATE TABLE d AS SELECT * REPLACE (sheet_row::INT AS sheet_row) FROM raw WHERE school_id IS NOT NULL")


def q(sql):
    return con.execute(sql).fetchall()


def one(sql):
    return q(sql)[0][0]


def show(finding, text):
    print(f"[{finding}] {text}")


def counts(sql):
    return ", ".join(f"{v if v is not None else '(blank)'} {n:,}" for v, n in q(sql))


# Main block (first contiguous run of rows after the header) vs rows after the first gap.
sheet_rows = [r for r, _ in rows]
present = set(sheet_rows)
gaps = [r for r in range(1, max(sheet_rows) + 1) if r not in present]
first_gap = gaps[0] if gaps else max(sheet_rows) + 1
show("run", f"{FILE}: sheets {[SHEET]}; rows below the header {len(rows) - HEADER_ROW:,}; school rows {one('SELECT count(*) FROM d'):,}")

# %% O-1 Layout: title rows, a three-row header, gaps, and a leftover row
show("O-1", "title rows: " + " | ".join(rows[i][1].get(1, "") for i in range(5)))
show("O-1", "row 6 notes: " + " | ".join(v for c, v in sorted(rows[5][1].items()) if c <= 30))
show("O-1", f"sheet rows absent from the file (blank rows): {gaps}")
show("O-1", "rows with no school ID: " + "; ".join(
    f"row {r}: {n} filled cells, values {vals}" for r, n, vals in q(
        "SELECT sheet_row, len(list_filter([" + ", ".join(COLS) + "], x -> x IS NOT NULL)), "
        "list_distinct(list_filter([" + ", ".join(COLS) + "], x -> x IS NOT NULL)) FROM raw WHERE school_id IS NULL")))

# %% O-2 A main block and an appended block
main = f"sheet_row < {first_gap}"
show("O-2", "main block rows {}-{}: {:,} schools; after the first gap: {:,} schools (rows {}-{})".format(
    HEADER_ROW + 1, first_gap - 1, one(f"SELECT count(*) FROM d WHERE {main}"),
    one(f"SELECT count(*) FROM d WHERE NOT {main}"),
    one(f"SELECT min(sheet_row) FROM d WHERE NOT {main}"), one("SELECT max(sheet_row) FROM d")))
show("O-2", "appended block, filled PSGC barangay / longitude / URP: {} / {} / {}; by sector: {}".format(
    one(f"SELECT count(psgc_bgy) FROM d WHERE NOT {main}"), one(f"SELECT count(lon) FROM d WHERE NOT {main}"),
    one(f"SELECT count(urp) FROM d WHERE NOT {main}"),
    counts(f"SELECT sector, count(*) FROM d WHERE NOT {main} GROUP BY 1 ORDER BY 2 DESC, 1")))
show("O-2", "appended block by region: " + counts(f"SELECT region, count(*) FROM d WHERE NOT {main} GROUP BY 1 ORDER BY 2 DESC, 1"))

# %% O-3 School ID
show("O-3", "school_id: non-numeric {}, length {}; duplicated IDs {}; fully duplicated rows {}".format(
    one("SELECT count(*) FROM d WHERE NOT regexp_full_match(school_id, '[0-9]+')"),
    counts("SELECT length(school_id), count(*) FROM d GROUP BY 1 ORDER BY 1"),
    one("SELECT count(*) - count(DISTINCT school_id) FROM d"),
    one("SELECT count(*) - (SELECT count(*) FROM (SELECT DISTINCT * EXCLUDE (sheet_row) FROM d)) FROM d")))
show("O-3", "not 6 digits or repeated: " + "; ".join(
    f"row {r} {i} {n!r}" for r, i, n in q("""SELECT sheet_row, school_id, school_name FROM d
        WHERE length(school_id) <> 6 OR school_id IN (SELECT school_id FROM d GROUP BY 1 HAVING count(*) > 1) ORDER BY sheet_row""")))
show("O-3", f"main block: duplicated IDs {one(f'SELECT count(*) - count(DISTINCT school_id) FROM d WHERE {main}')}, "
     f"not 6 digits {one(f'SELECT count(*) FROM d WHERE {main} AND length(school_id) <> 6')}")

# %% O-4 Enrollment counts are whole numbers
not_whole = sum(q("SELECT " + ", ".join(f"count(*) FILTER (WHERE {c} IS NOT NULL AND NOT regexp_full_match({c}, '[0-9]+'))" for c in COUNTS) + " FROM d")[0])
blank = sum(q("SELECT " + ", ".join(f"count(*) FILTER (WHERE {c} IS NULL)" for c in COUNTS) + " FROM d")[0])
total = " + ".join(f"coalesce(try_cast({c} AS BIGINT), 0)" for c in COUNTS)
con.execute(f"CREATE TABLE t AS SELECT sheet_row, school_id, {total} AS total FROM d")
show("O-4", f"{len(COUNTS)} count columns; cells not a whole number {not_whole}; blank cells {blank}")
show("O-4", "total learners {:,} (main block {:,}, appended {:,}); schools with 0 learners {:,}".format(
    one("SELECT sum(total) FROM t"), one(f"SELECT sum(total) FROM t WHERE {main}"),
    one(f"SELECT sum(total) FROM t WHERE NOT {main}"), one("SELECT count(*) FROM t WHERE total = 0")))

# %% O-5 PSGC codes lost their leading zero
for c in ("psgc_reg", "psgc_prv", "psgc_mun", "psgc_bgy"):
    show("O-5", f"{c}: length " + counts(f"SELECT length({c}), count(*) FROM d WHERE regexp_full_match({c}, '[0-9]+') GROUP BY 1 ORDER BY 1")
         + "; not a number: " + counts(f"SELECT {c}, count(*) FROM d WHERE {c} IS NOT NULL AND NOT regexp_full_match({c}, '[0-9]+') GROUP BY 1")
         + f"; blank {one(f'SELECT count(*) FROM d WHERE {c} IS NULL')}")
show("O-5", "9-digit region codes: " + counts("SELECT psgc_reg || ' ' || psgc_reg_name, count(*) FROM d WHERE length(psgc_reg) = 9 GROUP BY 1 ORDER BY 1"))
con.execute("""CREATE TABLE g AS SELECT *, lpad(psgc_reg, 10, '0') r10, lpad(psgc_prv, 10, '0') p10,
               lpad(psgc_mun, 10, '0') m10, lpad(psgc_bgy, 10, '0') b10
               FROM d WHERE regexp_full_match(psgc_bgy, '[0-9]+')""")

# %% O-6 #N/A in the PSGC columns
show("O-6", "PSGC city/municipality #N/A: {:,}; barangay #N/A: {:,} (of which city/municipality also #N/A: {:,})".format(
    one("SELECT count(*) FROM d WHERE psgc_mun = '#N/A'"), one("SELECT count(*) FROM d WHERE psgc_bgy = '#N/A'"),
    one("SELECT count(*) FROM d WHERE psgc_bgy = '#N/A' AND psgc_mun = '#N/A'")))
show("O-6", "barangay #N/A by sector: " + counts("SELECT sector, count(*) FROM d WHERE psgc_bgy = '#N/A' GROUP BY 1 ORDER BY 2 DESC, 1"))
show("O-6", "barangay #N/A by region: " + counts("SELECT region, count(*) FROM d WHERE psgc_bgy = '#N/A' GROUP BY 1 ORDER BY 2 DESC, 1"))
show("O-6", "barangay #N/A while city/municipality has a code: " + "; ".join(
    f"{i} {m} {b!r}" for i, m, b in q("SELECT school_id, psgc_mun_name, barangay FROM d WHERE psgc_bgy = '#N/A' AND psgc_mun <> '#N/A' ORDER BY 1")))
show("O-6", "examples (DepEd names, no PSGC): " + "; ".join(
    f"{i} {p}/{m}/{b}" for i, p, m, b in q("SELECT school_id, province, municipality, barangay FROM d WHERE psgc_mun = '#N/A' AND region <> 'PSO' ORDER BY sheet_row LIMIT 5")))

# %% O-7 Hierarchy inside the codes
show("O-7", "barangay code not under its city/municipality code (first 7 digits): " + "; ".join(
    f"{i} {b10} {bn} / {m10} {mn}" for i, b10, bn, m10, mn in q(
        "SELECT school_id, b10, psgc_bgy_name, m10, psgc_mun_name FROM g WHERE substr(b10, 1, 7) <> substr(m10, 1, 7) ORDER BY 1")))
show("O-7", "city/municipality code not under its province code (first 5 digits, NCR excluded): " + counts(
    "SELECT psgc_mun_name || ' ' || m10 || ' in ' || psgc_prv_name || ' ' || p10, count(*) FROM g "
    "WHERE substr(m10, 1, 5) <> substr(p10, 1, 5) AND m10 NOT LIKE '13%' GROUP BY 1"))
show("O-7", "province code not under its region code: {}".format(one("SELECT count(*) FROM g WHERE substr(p10, 1, 2) <> substr(r10, 1, 2)")))

# %% O-8 Income class: two columns, one typo
show("O-8", "income_class x income_class_long: " + counts(
    "SELECT coalesce(income_class, '(blank)') || ' | ' || coalesce(income_class_long, '(blank)'), count(*) FROM d GROUP BY 1 ORDER BY 1"))

# %% O-9 Two urban/rural classifications
show("O-9", "Urban / Rural (2020 CPH): " + counts("SELECT urban_rural, count(*) FROM d GROUP BY 1 ORDER BY 2 DESC, 1"))
show("O-9", "URP (DepEd): " + counts("SELECT urp, count(*) FROM d GROUP BY 1 ORDER BY 2 DESC, 1"))
show("O-9", "URP x Urban / Rural (U/R only): " + counts(
    "SELECT urp || ' x ' || urban_rural, count(*) FROM d WHERE urban_rural IN ('U', 'R') AND urp IS NOT NULL GROUP BY 1 ORDER BY 1"))

# %% O-10 Coordinates: missing, zero, outside the Philippines, precision
con.execute("CREATE TABLE c AS SELECT *, try_cast(lon AS DOUBLE) x, try_cast(lat AS DOUBLE) y FROM d")
show("O-10", "longitude: number {:,}, #N/A {:,}, blank {:,}; latitude number {:,}; lon number but lat not (or reverse) {}".format(
    one("SELECT count(x) FROM c"), one("SELECT count(*) FROM c WHERE lon = '#N/A'"), one("SELECT count(*) FROM c WHERE lon IS NULL"),
    one("SELECT count(y) FROM c"), one("SELECT count(*) FROM c WHERE (x IS NULL) <> (y IS NULL)")))
show("O-10", "#N/A coordinates by sector (missing of total): " + ", ".join(
    f"{s} {m:,} of {n:,}" for s, m, n in q("SELECT sector, count(*) FILTER (WHERE lon = '#N/A'), count(*) FROM c GROUP BY 1 ORDER BY 3 DESC")))
show("O-10", "#N/A coordinates by region (missing of total): " + ", ".join(
    f"{s} {m:,} of {n:,}" for s, m, n in q("SELECT region, count(*) FILTER (WHERE lon = '#N/A'), count(*) FROM c GROUP BY 1 ORDER BY 2 DESC, 1")))
show("S-2", "schools with numeric coordinates by sector: " + ", ".join(
    f"{s} {m:,} of {n:,}" for s, m, n in q("SELECT sector, count(x), count(*) FROM c GROUP BY 1 ORDER BY 3 DESC")))
show("O-10", "#N/A coordinates that have a PSGC barangay code: {:,}".format(one("SELECT count(*) FROM c WHERE lon = '#N/A' AND psgc_bgy <> '#N/A'")))
show("O-10", "(0, 0): {}; outside lon 116-127 / lat 4-21.5: {} (incl. zeros); swapped-looking: {}".format(
    one("SELECT count(*) FROM c WHERE x = 0 AND y = 0"),
    one("SELECT count(*) FROM c WHERE x IS NOT NULL AND NOT (x BETWEEN 116 AND 127 AND y BETWEEN 4 AND 21.5)"),
    one("SELECT count(*) FROM c WHERE x BETWEEN 4 AND 21.5 AND y BETWEEN 116 AND 127")))
show("O-10", "outside the box, not zero: " + "; ".join(
    f"{i} {r} ({lo}, {la})" for i, r, lo, la in q(
        "SELECT school_id, region, lon, lat FROM c WHERE x IS NOT NULL AND NOT (x BETWEEN 116 AND 127 AND y BETWEEN 4 AND 21.5) AND NOT (x = 0 AND y = 0) ORDER BY x, y LIMIT 8")))
show("O-10", "longitude decimals: " + counts("SELECT length(split_part(lon, '.', 2)), count(*) FROM c WHERE x IS NOT NULL GROUP BY 1 ORDER BY 1"))
show("O-10", "coordinate pairs shared by more than one school: {} pairs, {} schools; most shared: {}".format(
    one("SELECT count(*) FROM (SELECT x, y FROM c WHERE x IS NOT NULL GROUP BY 1, 2 HAVING count(*) > 1)"),
    one("SELECT sum(n) FROM (SELECT count(*) n FROM c WHERE x IS NOT NULL GROUP BY x, y HAVING count(*) > 1)"),
    counts("SELECT '(' || lon || ', ' || lat || ')', count(*) FROM c WHERE x IS NOT NULL GROUP BY 1 HAVING count(*) > 2 ORDER BY 2 DESC, 1")))

# %% O-11 Coordinates far from the other schools in the same city/municipality
# Reference point: the median longitude and latitude of the schools with in-box coordinates
# that share the PSGC city/municipality code, the school itself included. Schools without a
# numeric barangay code have no city/municipality to measure against and are counted apart.
# Distance is an equirectangular approximation.
con.execute("""CREATE TABLE mm AS SELECT m10, median(x) mx, median(y) my, count(*) n FROM g
               JOIN c USING (sheet_row) WHERE x BETWEEN 116 AND 127 AND y BETWEEN 4 AND 21.5 GROUP BY 1""")
KM = "111.32 * sqrt(power((c.x - mm.mx) * cos(radians(mm.my)), 2) + power(c.y - mm.my, 2))"
con.execute(f"""CREATE TABLE dist AS SELECT c.sheet_row, c.school_id, c.region, g.m10, g.psgc_mun_name, c.x, c.y, {KM} km
                FROM c JOIN g USING (sheet_row) JOIN mm USING (m10) WHERE c.x IS NOT NULL""")
show("O-11", "schools by km from their city/municipality median: " + counts(
    """SELECT CASE WHEN km <= 10 THEN '0-10' WHEN km <= 25 THEN '10-25' WHEN km <= 50 THEN '25-50'
                   WHEN km <= 100 THEN '50-100' ELSE 'over 100' END, count(*) FROM dist GROUP BY 1 ORDER BY min(km)"""))
show("O-11", "schools with numeric coordinates measured {:,} of {:,}; not measured, no numeric barangay code: {}".format(
    one("SELECT count(*) FROM dist"), one("SELECT count(x) FROM c"),
    counts("SELECT psgc_bgy, count(*) FROM c WHERE x IS NOT NULL AND sheet_row NOT IN (SELECT sheet_row FROM g) GROUP BY 1")))
show("O-11", "over 100 km, by region (of schools with coordinates): " + ", ".join(
    f"{r} {m:,} of {n:,}" for r, m, n in q("SELECT region, count(*) FILTER (WHERE km > 100), count(*) FROM dist GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 8")))
show("O-11", "of the over 100 km, at (0, 0) or outside the O-10 box: {} (the rest are inside the box)".format(
    one("SELECT count(*) FROM dist WHERE km > 100 AND NOT (x BETWEEN 116 AND 127 AND y BETWEEN 4 AND 21.5)")))
show("O-11", "over 100 km in MIMAROPA, by PSGC province (of schools with coordinates): " + ", ".join(
    f"{p.strip()} {m:,} of {n:,}" for p, m, n in q("""SELECT g.psgc_prv_name, count(*) FILTER (WHERE km > 100), count(*)
        FROM dist JOIN g USING (sheet_row) WHERE dist.region = 'MIMAROPA' GROUP BY 1 ORDER BY 2 DESC, 1""")))
show("O-11", "over 100 km, not zero, examples: " + "; ".join(
    f"{i} {m} ({x}, {y}) {k:,.0f} km" for i, m, x, y, k in q(
        "SELECT school_id, psgc_mun_name, x, y, km FROM dist WHERE km > 100 AND x <> 0 ORDER BY km DESC LIMIT 5")))
# A row shift (coordinates attached to the wrong row) would put row r's point near row r+k's municipality.
for k in (-2, -1, 1, 2):
    show("O-11", f"over 100 km and within 25 km of row {k:+d}'s city/municipality median: " + str(one(f"""
        SELECT count(*) FROM dist a JOIN g b ON b.sheet_row = a.sheet_row + {k} JOIN mm ON mm.m10 = b.m10
        WHERE a.km > 100 AND 111.32 * sqrt(power((a.x - mm.mx) * cos(radians(mm.my)), 2) + power(a.y - mm.my, 2)) <= 25""")))

# %% O-12 DepEd location names next to PSGC names
show("O-12", "barangay name equal to PSGC barangay name (upper case, trimmed): {:,} of {:,}".format(
    one("SELECT count(*) FROM g WHERE upper(trim(barangay)) = upper(trim(psgc_bgy_name))"), one("SELECT count(*) FROM g")))
show("O-12", "DepEd barangay blank: {}; DepEd region values: {}".format(
    one("SELECT count(*) FROM d WHERE barangay IS NULL"), one("SELECT count(DISTINCT region) FROM d")))
# Each DepEd region is paired with the PSGC region most of its schools carry; the rest disagree.
con.execute("""CREATE TABLE usual AS SELECT region, psgc_reg_name FROM g GROUP BY region, psgc_reg_name
               QUALIFY row_number() OVER (PARTITION BY region ORDER BY count(*) DESC) = 1""")
show("O-12", "schools whose PSGC region is not the usual one for their DepEd region: {:,}; ".format(
    one("SELECT count(*) FROM g JOIN usual u USING (region) WHERE g.psgc_reg_name <> u.psgc_reg_name")) + counts(
    "SELECT g.region || ' -> ' || g.psgc_reg_name, count(*) FROM g JOIN usual u USING (region) "
    "WHERE g.psgc_reg_name <> u.psgc_reg_name GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 8"))

# %% O-13 Mojibake: UTF-8 text stored as if it were Windows-1252 ('Ã‘' for 'Ñ')
# The same test the Bronze contract counts (src/ingestion/xlsx_table.mojibake), over every cell below the header.
broken = [(r, c, v) for r, cells in rows[HEADER_ROW:] for c, v in cells.items() if mojibake(v)]
by_column = {}
for _, c, _ in broken:
    by_column[COLS[c - 1] if c <= len(COLS) else column_letter(c)] = by_column.get(COLS[c - 1] if c <= len(COLS) else column_letter(c), 0) + 1
show("O-13", "cells with mojibake below the header: {:,} in {:,} rows; header cells: {}; by column: {}".format(
    len(broken), len({r for r, _, _ in broken}), sum(mojibake(v) for v in header.values()),
    ", ".join(f"{k} {n:,}" for k, n in sorted(by_column.items(), key=lambda kv: (-kv[1], kv[0])))))
show("O-13", "distinct broken values: {:,}; examples: {}".format(
    len({v for _, _, v in broken}), "; ".join(sorted({v for _, _, v in broken})[:5])))

# %% X-1 Comparison with deped_enrollment SY 2023-24 (enrollment_2023-24.csv)
zip_path = ORIGINAL / ENROLLMENT_ZIP
if not zip_path.exists():
    show("X-1", f"skipped: {ENROLLMENT_ZIP} is not in {ORIGINAL}")
elif sha256(zip_path) != ENROLLMENT_ZIP_SHA256:
    show("X-1", f"skipped: {ENROLLMENT_ZIP} does not match the SHA-256 on the deped_enrollment card")
else:
    e_path = Path(workdir.name) / "enrollment.csv"
    with zipfile.ZipFile(zip_path) as zf:
        e_path.write_bytes(zf.read(ENROLLMENT_CSV))
    con.execute(f"CREATE TABLE e AS SELECT * FROM read_csv('{e_path}', all_varchar = true, header = true, strict_mode = true)")
    e_counts = [c for (c,) in q("SELECT column_name FROM (DESCRIBE e)") if c.endswith(("_male", "_female"))]
    show("X-1", "csv rows {:,}; schools in both {:,}; only in this workbook {:,} (all after the first gap: {}); only in the csv {:,}".format(
        one("SELECT count(*) FROM e"), one("SELECT count(*) FROM d WHERE school_id IN (SELECT school_id FROM e)"),
        one("SELECT count(*) FROM d WHERE school_id NOT IN (SELECT school_id FROM e)"),
        one(f"SELECT count(*) = 0 FROM d WHERE school_id NOT IN (SELECT school_id FROM e) AND {main}"),
        one("SELECT count(*) FROM e WHERE school_id NOT IN (SELECT school_id FROM d)")))
    e_total = " + ".join(f"coalesce(try_cast({c} AS BIGINT), 0)" for c in e_counts)
    con.execute(f"CREATE TABLE et AS SELECT school_id, {e_total} AS total FROM e")
    show("X-1", "count columns: workbook {}, csv {}; csv total {:,}; schools whose total differs {}".format(
        len(COUNTS), len(e_counts), one("SELECT sum(total) FROM et"),
        one("SELECT count(*) FROM t JOIN et USING (school_id) WHERE t.total <> et.total")))
    # Workbook column -> csv column, by name. PBM (Pre-Baccalaureate Maritime) is the csv's "maritime".
    def csv_column(c):
        c = re.sub(r"^k_", "kinder_", c).replace("elem_ng", "esng").replace("jhs_ng", "jhsng")
        return c.replace("_acad_", "_").replace("_pbm_", "_maritime_")
    mapping = {c: csv_column(c) for c in COUNTS}
    missing = [v for v in mapping.values() if v not in e_counts]
    if missing:
        sys.exit(f"X-1: csv columns not found for the mapping: {missing}")
    con.execute("CREATE TABLE j AS SELECT * FROM d JOIN e USING (school_id)")
    differ = {c: one(f"SELECT count(*) FROM j WHERE {c}::BIGINT <> {ec}::BIGINT") for c, ec in mapping.items()}
    show("X-1", "workbook column vs mapped csv column: {} of {} equal for every school; differing: {}; PBM -> maritime".format(
        sum(n == 0 for n in differ.values()), len(differ), {c: n for c, n in differ.items() if n}))
    unmapped = sorted(set(e_counts) - set(mapping.values()))
    show("X-1", "csv count columns with no workbook column: " + ", ".join(
        f"{ec} filled {one(f'SELECT count({ec}) FROM e'):,}" for ec in unmapped))

# %% S-3 The appended block: learners, and whether its schools appear in later school years
show("S-3", "appended schools {}: learners {:,}; with 0 learners {}; learners by sector: {}".format(
    one(f"SELECT count(*) FROM t WHERE NOT {main}"), one(f"SELECT sum(total) FROM t WHERE NOT {main}"),
    one(f"SELECT count(*) FROM t WHERE NOT {main} AND total = 0"),
    counts(f"SELECT d.sector, sum(t.total) FROM t JOIN d USING (sheet_row) WHERE NOT {main} GROUP BY 1 ORDER BY 2 DESC, 1")))
show("S-3", "appended schools with learners: " + "; ".join(
    f"{i} {n!r} {s} {v:,}" for i, n, s, v in q(
        f"SELECT d.school_id, d.school_name, d.sector, t.total FROM t JOIN d USING (sheet_row) WHERE NOT {main} AND t.total > 0 ORDER BY t.total DESC, 1")))
appended_ids = {i for (i,) in q(f"SELECT DISTINCT school_id FROM d WHERE NOT {main}")}
seen = {}
later = {}  # school year -> {school_id: sector}, also used in X-4
for year, (zip_name, zip_sha, member, encoding) in LATER_YEARS.items():
    zp = ORIGINAL / zip_name
    if not zp.exists() or sha256(zp) != zip_sha:
        show("S-3", f"skipped SY {year}: {zip_name} with the SHA-256 on the deped_enrollment card is not in {ORIGINAL}")
        continue
    with zipfile.ZipFile(zp) as zf:
        later[year] = {r["school_id"]: r["sector"] for r in csv.DictReader(io.StringIO(zf.read(member).decode(encoding), newline=""))}
    seen[year] = appended_ids & later[year].keys()
    show("S-3", f"appended school IDs found in deped_enrollment SY {year}: {len(seen[year])} of {len(appended_ids)}")
if len(seen) == len(LATER_YEARS):
    show("S-3", f"appended school IDs in no later year: {len(appended_ids - set().union(*seen.values()))} of {len(appended_ids)}")
earlier = {}  # school_id -> (sector, region, learners) for SY 2020-21, also used in X-4
year, (zip_name, zip_sha, member, encoding) = EARLIER_YEAR
zp = ORIGINAL / zip_name
if not zp.exists() or sha256(zp) != zip_sha:
    show("S-3", f"skipped SY {year}: {zip_name} with the SHA-256 on the deped_enrollment card is not in {ORIGINAL}")
else:
    with zipfile.ZipFile(zp) as zf:
        for r in csv.DictReader(io.StringIO(zf.read(member).decode(encoding), newline="")):
            learners = sum(int(v) for k, v in r.items() if k.endswith(("_male", "_female")) and v.strip())
            earlier[r["school_id"]] = (r["sector"], r["region"], learners)
    found = collections.Counter(earlier[i][0] for i in appended_ids & earlier.keys())
    show("S-3", f"appended school IDs found in deped_enrollment SY {year}: {sum(found.values())} of {len(appended_ids)}; by sector: "
         + ", ".join(f"{k} {n}" for k, n in found.most_common()))

# %% X-2 PSGC codes against PSA PSGC versions (psa_psgc)
psa = RAW / "psa" / "original"
have = all((psa / f).exists() and sha256(psa / f) == s for f, s in (PSGC_2Q2026, PSGC_Q4_2023))
if not have:
    show("X-2", f"skipped: {PSGC_2Q2026[0]} and {PSGC_Q4_2023[0]} with the SHA-256 on the psa_psgc card must be in {psa}")
else:
    with (Path(workdir.name) / "psgc.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "name", "level"])
        for _, cells in read_sheet(psa / PSGC_2Q2026[0], "PSGC")[1:]:
            w.writerow([cells.get(1, ""), cells.get(2, "").strip(), cells.get(4, "")])
    con.execute(f"CREATE TABLE p AS SELECT * FROM read_csv('{Path(workdir.name) / 'psgc.csv'}', all_varchar = true, header = true)")
    con.execute(f"CREATE TABLE o AS SELECT * FROM read_csv({sql_string(psa / PSGC_Q4_2023[0])}, all_varchar = true, header = true, strict_mode = true)")
    in_p, in_o = "b10 IN (SELECT id FROM p)", "b10 IN (SELECT code FROM o)"
    show("X-2", "schools with a numeric barangay code {:,}: in 2Q 2026 {:,}; in Q4_2023 {:,}; in both {:,}; only 2Q 2026 {:,}; only Q4_2023 {:,}; in neither {:,}".format(
        one("SELECT count(*) FROM g"), one(f"SELECT count(*) FROM g WHERE {in_p}"), one(f"SELECT count(*) FROM g WHERE {in_o}"),
        one(f"SELECT count(*) FROM g WHERE {in_p} AND {in_o}"), one(f"SELECT count(*) FROM g WHERE {in_p} AND NOT {in_o}"),
        one(f"SELECT count(*) FROM g WHERE NOT {in_p} AND {in_o}"), one(f"SELECT count(*) FROM g WHERE NOT {in_p} AND NOT {in_o}")))
    show("X-2", "only in 2Q 2026, by first 2 digits (region): " + counts(f"SELECT substr(b10, 1, 2), count(*) FROM g WHERE {in_p} AND NOT {in_o} GROUP BY 1 ORDER BY 2 DESC, 1"))
    show("X-2", "only in Q4_2023, by first 5 digits (province): " + counts(f"SELECT substr(b10, 1, 5) || ' ' || psgc_prv_name, count(*) FROM g WHERE NOT {in_p} AND {in_o} GROUP BY 1 ORDER BY 2 DESC, 1"))
    show("X-2", "'-' urban/rural schools whose barangay is in 2Q 2026 / Q4_2023: {} / {} of {}".format(
        one(f"SELECT count(*) FROM g WHERE urban_rural = '-' AND {in_p}"), one(f"SELECT count(*) FROM g WHERE urban_rural = '-' AND {in_o}"),
        one("SELECT count(*) FROM g WHERE urban_rural = '-'")))
    # Sulu is no longer in BARMM: 2Q 2026 codes it 0906600000 (Region IX), the file still 19066 (BARMM).
    # Test whether swapping the province prefix alone gives a 2Q 2026 barangay with the same name.
    show("X-2", "codes not in 2Q 2026 with prefix 19066, recoded to 09066: distinct codes {}; found in 2Q 2026 {}; same barangay name {}".format(
        *q(f"""WITH s AS (SELECT DISTINCT b10, psgc_bgy_name FROM g WHERE NOT {in_p} AND b10 LIKE '19066%')
               SELECT count(*), count(p.id), count(*) FILTER (WHERE upper(trim(p.name)) = upper(trim(s.psgc_bgy_name)))
               FROM s LEFT JOIN p ON p.id = '09066' || substr(s.b10, 6)""")[0]))
    show("X-2", "schools with a code not in 2Q 2026, by sector (schools, learners): " + ", ".join(
        f"{s} {n:,}, {v:,}" for s, n, v in q(f"""SELECT g.sector, count(*), sum(t.total) FROM g JOIN t USING (sheet_row)
            WHERE NOT {in_p} GROUP BY 1 ORDER BY 2 DESC""")))

# %% X-3 City or municipality from this file's codes against the team's name matching
# deped_enrollment schools are placed in PSGC 2Q 2026 by their place names (cross_source_deped.py,
# rules in docs/data/cross-source/deped-dataset-research.md). For each school in the main block,
# compare that city or municipality with the one its barangay code here gives. Manila
# sub-municipalities roll up to the City of Manila on both sides, as in the name matching.
if not have:
    show("X-3", "skipped: needs the psa_psgc files of X-2")
else:
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            names = runpy.run_path(str(REPO / "analysis" / "cross_source" / "cross_source_deped.py"), run_name="__main__")
    except (SystemExit, FileNotFoundError) as stop:
        names = None
        show("X-3", f"skipped: cross_source_deped.py could not run ({stop}); it needs every zip in its FILES in {ORIGINAL}")
    if names is not None:
        units_by_id, city = names["units_by_id"], names["city_or_municipality"]
        by_name = {}
        for school_id, _, province, municipality, _ in names["schools"]:  # overseas schools already excluded
            locality = names["loc_result"][(province, municipality)][1]
            by_name[school_id] = city(locality).id if locality is not None else None
        code_of = dict(q(f"SELECT school_id, b10 FROM g WHERE {main}"))
        sector_of = dict(q(f"SELECT school_id, sector FROM d WHERE {main}"))

        def outcome(school_id):
            code, named = code_of.get(school_id), by_name[school_id]
            parent = units_by_id.get(code[:7] + "000") if code in units_by_id else None
            coded = city(parent).id if parent is not None else None
            if coded and named:
                return ("agree" if coded == named else "disagree"), named, coded
            if coded:
                return "placed only by this file", named, coded
            if named:
                why = "this file's code not in 2Q 2026" if code else "this file's code #N/A or blank"
                return f"placed only by name ({why})", named, coded
            return "placed by neither", named, coded

        results = {i: outcome(i) for i in by_name}
        for label, keep in (("public", lambda i: sector_of.get(i) == "Public"), ("all sectors", lambda i: True)):
            tally = collections.Counter(r[0] for i, r in results.items() if keep(i))
            show("X-3", f"{label}, {sum(tally.values()):,} schools: " + ", ".join(f"{k} {n:,}" for k, n in tally.most_common()))
        moved = collections.Counter((units_by_id[n].name, units_by_id[c].name)
                                    for i, (o, n, c) in results.items() if o == "disagree" and sector_of.get(i) == "Public")
        show("X-3", "public, disagree, name matching -> this file: " + ", ".join(f"{a} -> {b} {k}" for (a, b), k in moved.most_common(15)))

# %% X-4 The barangay codes carried to every deped_enrollment school year by school_id
# Used as a school_id -> PSGC crosswalk, the SY 2023-24 codes reach a later year's school
# only if its school_id is in this file's main block with a numeric barangay code.
coded = {i for (i,) in q(f"SELECT school_id FROM g WHERE {main}")}
years = {"2023-24": dict(q(f"SELECT school_id, sector FROM d WHERE {main}")), **later}
for year, sectors in years.items():
    public = {i for i, s in sectors.items() if s == "Public"}
    show("X-4", "SY {}: schools {:,}, with a code from this file {:,} ({:.1%}); public {:,}, with a code {:,} ({:.1%})".format(
        year, len(sectors), len(coded & sectors.keys()), len(coded & sectors.keys()) / len(sectors),
        len(public), len(coded & public), len(coded & public) / len(public)))
if len(later) < len(LATER_YEARS):
    show("X-4", "later years skipped above (S-3) are not shown")
if earlier:
    # Overseas schools (region PSO) are left out: they are outside geographic analysis (deped_enrollment O-13).
    home = {i: v for i, v in earlier.items() if v[1] != "PSO"}
    all_learners = sum(v[2] for v in home.values())
    in_main = {i for (i,) in q(f"SELECT school_id FROM d WHERE {main}")}
    groups = {"gone by SY 2023-24": home.keys() - in_main, "in this file with no barangay code": (home.keys() & in_main) - coded}
    groups["without a code, total"] = home.keys() - coded
    for label, ids in groups.items():
        n = sum(home[i][2] for i in ids)
        by_sector = collections.Counter()
        for i in ids:
            by_sector[home[i][0]] += home[i][2]
        show("X-4", "SY {} (overseas excluded, {:,} schools, {:,} learners), {}: schools {:,} ({:.1%}), learners {:,} ({:.1%}); learners by sector: {}".format(
            EARLIER_YEAR[0], len(home), all_learners, label, len(ids), len(ids) / len(home), n, n / all_learners,
            ", ".join(f"{k} {v:,}" for k, v in by_sector.most_common())))
else:
    show("X-4", f"SY {EARLIER_YEAR[0]} skipped above (S-3) is not shown")

workdir.cleanup()
