# Profiles psa_school_age_population: PSA population aged 5-24 by single-year age, sex, and
# city/municipality, from the 2020 Census of Population and Housing and the 2024 Census of
# Population, each as total population and household population.
#
# Reproduces every finding in:
#   docs/data/source-inventory/psa_school_age_population/profile.md
# Each check prints under its finding ID (O-n observed, S-n suspected, X-n cross-source).
#
# Runs locally with DuckDB; no Databricks compute. Open it in VS Code to run
# cell by cell (# %% markers), or run the whole file:
#   RAW_DATA_DIR=~/Projects/reached-hq/raw-data python analysis/profiling/profile_psa_school_age_population.py
#
# RAW_DATA_DIR must contain psa/original/ with the two workbooks listed in FILES. The cross-checks
# are optional: X-1 needs the psa_population_per_age_group CSV and X-2 the PSGC 2Q 2026 workbook,
# both in psa/original/ with the SHA-256 on their cards; each is skipped with a message otherwise.
# The xlsx reader is shared with the other profiling scripts: src/profiling/xlsx.py (D-007).
# Raw files are read, never modified.

# %% Setup
import collections
import csv
import hashlib
import os
import re
import sys
import tempfile
import zipfile
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from src.profiling.xlsx import read_sheet, sheet_names

raw_dir = os.environ.get("RAW_DATA_DIR")
if not raw_dir:
    sys.exit("Set RAW_DATA_DIR to the folder that contains psa/original/.")
ORIGINAL = Path(raw_dir).expanduser() / "psa" / "original"

FILES = {
    2020: ("2020 School-Age Population by Single Year Age, Sex, and City Municipality.xlsx",
           "e40d71839b951926cd3c9515c1edafbb6a2121f734670716e3b21bd3f9dcd35f"),
    2024: ("2024 School-Age Population by Single Year Age, Sex, and City Municipality.xlsx",
           "49d15bb0cdd191cd6aef4a14f4b063da247ba791b32caa653c37c464dff15954"),
}
CONCEPTS = {"total": "Total Pop", "household": "Household Pop"}  # sheet "<year> <suffix>"
AGES = list(range(5, 25))
SEXES = ("both", "male", "female")
AGE_GROUP_CSV = ("Household Population by Age-Group Region, Province, and Highly Urbanized City- Philippines, 2024 Census of Population.csv",
                 "ce797046a055f870c30f5a2ce6d42b4bdc8f14f4dd8145269f450372c6c93ad6")
PSGC_2Q2026 = ("PSGC-2Q-2026-Publication-Datafile.xlsx", "31892bc2bdde3ea0682562d9412b5bab4d45a0be5e5a5b4f6c9d7714b94bca5d")


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def show(finding, text):
    print(f"[{finding}] {text}")


def fmt(pairs):
    return ", ".join(f"{k} {v:,}" if isinstance(v, int) else f"{k} {v}" for k, v in pairs)


# %% Read each sheet into places: (sheet_row, label, [60 values: both 5-24, male 5-24, female 5-24])
# 2020 is wide: one row per place, columns B-U both sexes, V-AO male, AP-BI female (ages in row 3).
# 2024 is long: a place row with no values, then Total / Male / Female rows, columns B-U (ages in row 3).
def ages_in_row3(rows, first, count):
    return [int(float(rows[2][1].get(c, "nan"))) for c in range(first, first + count)]


def read_wide(rows):
    if ages_in_row3(rows, 2, 60) != AGES * 3:
        sys.exit("2020: row 3 does not hold ages 5-24 three times in columns B-BI.")
    places, other = [], []
    for row, cells in rows[4:]:
        label = cells.get(1)
        values = [cells.get(c) for c in range(2, 62)]
        if label is not None and all(v is not None for v in values):
            places.append((row, label, values))
        elif label is not None or any(v is not None for v in values):
            other.append((row, label))
    return places, other


def read_long(rows):
    if ages_in_row3(rows, 2, 20) != AGES:
        sys.exit("2024: row 3 does not hold ages 5-24 in columns B-U.")
    places, other, current, by_sex = [], [], None, {}
    for row, cells in rows[3:]:
        label = cells.get(1)
        values = [cells.get(c) for c in range(2, 22)]
        if label in ("Total", "Male", "Female") and all(v is not None for v in values):
            by_sex[label] = values
            if label == "Female":
                if current is None or set(by_sex) != {"Total", "Male", "Female"}:
                    sys.exit(f"2024: sheet row {row}: a Total / Male / Female block without its place row.")
                places.append((current[0], current[1], by_sex["Total"] + by_sex["Male"] + by_sex["Female"]))
                current, by_sex = None, {}
        elif label is not None and all(v is None for v in values):
            if current is not None:
                other.append(current)  # a label row that no block followed: a note
            current = (row, label)
        elif label is not None or any(v is not None for v in values):
            other.append((row, label))
    if current is not None:
        other.append(current)
    return places, other


# %% Verify checksums and read every sheet
# A changed file must stop the run, not silently produce new numbers under the old checksum.
for year, (name, digest) in FILES.items():
    actual = sha256(ORIGINAL / name)
    if actual != digest:
        sys.exit(f"{name}: SHA-256 {actual} does not match the inventory card. Stop and re-inventory.")

sheets = {}  # (year, concept) -> dict
for year, (name, _) in FILES.items():
    path = ORIGINAL / name
    with zipfile.ZipFile(path) as zf:
        found = sheet_names(zf)
    expected = [f"{year} {s}" for s in CONCEPTS.values()]
    if found != expected:
        sys.exit(f"{name}: sheets {found}, expected {expected}.")
    for concept, suffix in CONCEPTS.items():
        rows = read_sheet(path, f"{year} {suffix}")
        places, other = (read_wide if year == 2020 else read_long)(rows)
        bad = [(r, l) for r, l, v in places for x in v if not re.fullmatch(r"[0-9]+", x)]
        if bad:
            sys.exit(f"{year} {concept}: values that are not whole numbers, e.g. rows {bad[:5]}")
        places = [(r, l, [int(x) for x in v]) for r, l, v in places]
        sheets[(year, concept)] = {"rows": rows, "places": places, "other": other}
        print(f"{year} {concept}: {len(places):,} places, {len(places) * 60:,} counts, checksum OK")


# %% Hierarchy from the sums: a place is an aggregate when the places right after it add up to it,
# in all 60 cells, with each nested aggregate counted once. Computed from the last row up.
def build_tree(places):
    n = len(places)
    end = [None] * n  # end[i]: index after the last descendant of aggregate i
    for i in range(n - 1, -1, -1):
        target, acc, j = places[i][2], [0] * 60, i + 1
        while j < n:
            acc = [a + b for a, b in zip(acc, places[j][2])]
            j = end[j] or j + 1
            if acc == target:
                end[i] = j
                break
            if any(a > b for a, b in zip(acc, target)):
                break
    parent, depth, stack = [None] * n, [0] * n, []
    for i in range(n):
        while stack and i >= end[stack[-1]]:
            stack.pop()
        parent[i] = stack[-1] if stack else None
        depth[i] = len(stack)
        if end[i]:
            stack.append(i)
    covered = n == 0 or end[0] == n
    return end, parent, depth, covered


def clean(label):
    """Label without footnote markers (a/, 1/), bracketed text, and case differences."""
    label = re.sub(r"\s+[a-z0-9]{1,2}/$", "", label)
    label = re.sub(r"\s*\([^)]*\)", "", label)
    return re.sub(r"\s+", " ", label).strip().upper()


LEVELS = {0: "country", 1: "region", 2: "province_or_lgu", 3: "city_municipality"}
workdir = tempfile.TemporaryDirectory()
long_csv = Path(workdir.name) / "long.csv"
with long_csv.open("w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["year", "concept", "pos", "sheet_row", "label", "depth", "is_lgu", "province", "region", "sex", "age", "value"])
    for (year, concept), s in sheets.items():
        places = s["places"]
        end, parent, depth, covered = build_tree(places)
        s.update(end=end, parent=parent, depth=depth, covered=covered)
        for i, (row, label, values) in enumerate(places):
            lgu = end[i] is None  # a leaf: a city or municipality (or NCR's Pateros)
            up = [parent[i]]
            while up[-1] is not None:
                up.append(parent[up[-1]])
            chain = [places[k][1] for k in up[:-1]]  # parent, grandparent, ... below the country
            region = chain[-2] if len(chain) >= 2 else (label if depth[i] == 1 else "")
            province = chain[0] if lgu and depth[i] == 3 else ""
            for s_i, sex in enumerate(SEXES):
                for a_i, age in enumerate(AGES):
                    w.writerow([year, concept, i, row, label, depth[i], lgu, province, region, sex, age, values[s_i * 20 + a_i]])

con = duckdb.connect()
con.execute(f"""CREATE TABLE p AS SELECT * REPLACE (year::INT AS year, pos::INT AS pos, sheet_row::INT AS sheet_row, depth::INT AS depth,
                is_lgu::BOOLEAN AS is_lgu, age::INT AS age, value::BIGINT AS value)
                FROM read_csv('{long_csv.as_posix()}', all_varchar = true, header = true, strict_mode = true)""")


def q(sql):
    return con.execute(sql).fetchall()


def one(sql):
    return q(sql)[0][0]


print("\n=== psa_school_age_population ===")

# %% O-1 Layout: two workbooks, two sheets each, and two different layouts
for (year, concept), s in sheets.items():
    rows = s["rows"]
    title = rows[0][1].get(1, "")
    header = " | ".join(v for _, v in sorted(rows[1][1].items()))
    show("O-1", f"{year} {concept}: title {title!r}; row 2 {header!r}")
for (year, concept), s in sheets.items():
    show("O-1", f"{year} {concept}: rows that are not a place: " + "; ".join(f"row {r} {l!r}" for r, l in s["other"]))

# %% O-2 No codes and no level column: levels recovered from the sums
for (year, concept), s in sheets.items():
    depth, end = s["depth"], s["end"]
    by_level = collections.Counter((LEVELS[d], end[i] is None) for i, d in enumerate(depth))
    show("O-2", f"{year} {concept}: every place inside one tree whose sums close: {s['covered']}; " + fmt(
        (f"{lvl}{'' if leaf else ' (aggregate)'}", n) for (lvl, leaf), n in sorted(by_level.items(), key=lambda x: (list(LEVELS.values()).index(x[0][0]), x[0][1]))))
year_lgus = {y: one(f"SELECT count(DISTINCT sheet_row) FROM p WHERE year = {y} AND concept = 'total' AND is_lgu") for y in FILES}
show("O-2", "cities and municipalities (places with no children): " + fmt((y, n) for y, n in year_lgus.items()))
show("O-2", "cities and municipalities directly under a region (no province row above): " + "; ".join(
    f"{y}: {n} ({names})" for y, n, names in q("""SELECT year, count(DISTINCT sheet_row), string_agg(DISTINCT label, ', ' ORDER BY label)
        FROM p WHERE concept = 'total' AND is_lgu AND depth = 2 GROUP BY 1 ORDER BY 1""")))
show("O-2", "aggregates with exactly one child: " + "; ".join(
    f"{y} {c}: {', '.join(repr(s['places'][i][1]) for i in range(len(s['places'])) if s['end'][i] == i + 2) or 'none'}"
    for (y, c), s in sheets.items()))

# %% O-3 Values are complete whole numbers; the zeros
show("O-3", "cells: " + fmt((f"{y} {c}", n) for y, c, n in q("SELECT year, concept, count(*) FROM p GROUP BY 1, 2 ORDER BY 1, 2"))
     + "; blank or not a whole number: 0 (the script stops otherwise)")
show("O-3", "zero cells, by place: " + "; ".join(
    f"{y} {c} {l} ({pr}): {n} of 60" for y, c, l, pr, n in q("""SELECT year, concept, label, province, count(*) FROM p WHERE value = 0
        GROUP BY 1, 2, 3, 4 ORDER BY 1, 2, 3, 4""")))
show("O-3", "smallest and largest city/municipality (both sexes, ages 5-17, total population): " + "; ".join(
    f"{y}: {lo} {lv:,} / {hi} {hv:,}" for y, lo, lv, hi, hv in q("""WITH t AS (SELECT year, label, sum(value) v FROM p
        WHERE concept = 'total' AND is_lgu AND sex = 'both' AND age <= 17 GROUP BY 1, 2)
        SELECT year, arg_min(label, v), min(v), arg_max(label, v), max(v) FROM t GROUP BY 1 ORDER BY 1""")))

# %% O-4 Sexes add up
show("O-4", "cells where both sexes <> male + female: " + fmt((f"{y} {c}", n) for y, c, n in q("""
    SELECT b.year, b.concept, count(*) FILTER (WHERE b.value <> m.value + f.value) FROM p b
    JOIN p m ON m.year = b.year AND m.concept = b.concept AND m.sheet_row = b.sheet_row AND m.age = b.age AND m.sex = 'male'
    JOIN p f ON f.year = b.year AND f.concept = b.concept AND f.sheet_row = b.sheet_row AND f.age = b.age AND f.sex = 'female'
    WHERE b.sex = 'both' GROUP BY 1, 2 ORDER BY 1, 2""")))

# %% O-5 Total population and household population
for year in FILES:
    t, h = sheets[(year, "total")]["places"], sheets[(year, "household")]["places"]
    show("O-5", f"{year}: same places in the same order on both sheets: {[l for _, l, _ in t] == [l for _, l, _ in h]}; "
         "labels that differ: " + (", ".join(f"{a!r} / {b!r}" for (_, a, _), (_, b, _) in zip(t, h) if a != b) or "none"))
# The two sheets list the same places in the same order (checked above), so places pair by position.
show("O-5", "cells where household > total: " + fmt((y, n) for y, n in q("""SELECT t.year, count(*) FILTER (WHERE h.value > t.value)
    FROM p t JOIN p h ON h.year = t.year AND h.pos = t.pos AND h.sex = t.sex AND h.age = t.age AND h.concept = 'household'
    WHERE t.concept = 'total' GROUP BY 1 ORDER BY 1""")) + "; places where household = total in all 60 cells: " + fmt(
    (y, n) for y, n in q("""SELECT year, count(*) FROM (SELECT t.year, t.pos FROM p t JOIN p h ON h.year = t.year AND h.pos = t.pos
    AND h.sex = t.sex AND h.age = t.age AND h.concept = 'household' WHERE t.concept = 'total' GROUP BY 1, 2
    HAVING bool_and(h.value = t.value)) GROUP BY 1 ORDER BY 1""")))
show("O-5", "national, both sexes, ages 5-24, total / household / not in households: " + "; ".join(
    f"{y}: {t:,} / {h:,} / {t - h:,}" for y, t, h in q("""SELECT year, sum(value) FILTER (WHERE concept = 'total'),
    sum(value) FILTER (WHERE concept = 'household') FROM p WHERE depth = 0 AND sex = 'both' GROUP BY 1 ORDER BY 1""")))
show("O-5", "cities/municipalities with the largest share not in households (both sexes, 5-24): " + "; ".join(
    f"{y} {l} ({pr}) {s:.1f}%" for y, l, pr, s in q("""WITH t AS (SELECT year, label, province, sum(value) FILTER (WHERE concept = 'total') tv,
        sum(value) FILTER (WHERE concept = 'household') hv FROM p WHERE is_lgu AND sex = 'both' GROUP BY 1, 2, 3)
        SELECT year, label, province, 100.0 * (tv - hv) / tv s FROM t WHERE tv > 0 QUALIFY row_number() OVER (PARTITION BY year ORDER BY s DESC) <= 3
        ORDER BY 1, 4 DESC""")))

# %% O-6 Place labels: brackets, footnote markers, case, repeated names
for (year, concept) in [(y, "total") for y in FILES]:
    labels = [l for _, l, _ in sheets[(year, concept)]["places"]]
    brackets = collections.Counter(m.upper() for l in labels for m in re.findall(r"\(([^)]*)\)", l))
    show("O-6", f"{year}: labels with brackets {sum('(' in l for l in labels)}: capital {brackets['CAPITAL']} "
         f"(spelled {', '.join(sorted({m for l in labels for m in re.findall(r'[(](capital)[)]', l, re.I)}))}), "
         f"other {sum(n for k, n in brackets.items() if k != 'CAPITAL')}, e.g. "
         + ", ".join(l for l in labels if "(" in l and "CAPITAL" not in l.upper())[:200])
    show("O-6", f"{year}: footnote markers: " + (", ".join(l for l in labels if re.search(r"\s[a-z0-9]{1,2}/$", l)) or "none"))
    show("O-6", f"{year}: labels with lower-case letters (outside '(Capital)'): "
         + (", ".join(l for l in labels if re.search(r"[a-z]", re.sub(r"\((?i:capital)\)", "", l))) or "none"))
for y in FILES:
    s = sheets[(y, "total")]
    names = collections.Counter(clean(l) for i, (_, l, _) in enumerate(s["places"]) if s["end"][i] is None)
    show("O-6", f"{y}: city/municipality names (cleaned) shared by more than one place: {sum(c > 1 for c in names.values())} names, "
         f"{sum(c for c in names.values() if c > 1)} places; most shared: " + fmt(names.most_common(3)))
for y in FILES:
    s = sheets[(y, "total")]
    keys = collections.Counter((clean(l), clean(s["places"][s["parent"][i]][1])) for i, (_, l, _) in enumerate(s["places"]) if s["end"][i] is None)
    show("O-6", f"{y}: repeated (name, parent) pairs after cleaning: {sum(c > 1 for c in keys.values())}")

# %% O-7 Geography: 2020 against 2024
def lgu_keys(year):
    s = sheets[(year, "total")]
    out = {}
    for i, (_, label, _) in enumerate(s["places"]):
        if s["end"][i] is None:
            par = s["places"][s["parent"][i]][1]
            out[(clean(label), clean(par) if s["depth"][i] == 3 else "-")] = (label, par)
    return out


k20, k24 = lgu_keys(2020), lgu_keys(2024)
only20, only24 = sorted(set(k20) - set(k24)), sorted(set(k24) - set(k20))
show("O-7", f"cities/municipalities matched by cleaned name and province (or '-' under a region): {len(set(k20) & set(k24)):,}; "
     f"only in 2020: {len(only20)}; only in 2024: {len(only24)}")
names20, names24 = collections.defaultdict(set), collections.defaultdict(set)
for n, par in only20:
    names20[n].add(par)
for n, par in only24:
    names24[n].add(par)
moved = sorted(set(names20) & set(names24))
show("O-7", f"same name, different parent: {len(moved)}; parent pairs: " + fmt(
    (f"{a} -> {b}", c) for (a, b), c in sorted(collections.Counter((min(names20[n]), min(names24[n])) for n in moved).items())))
show("O-7", "left in 2020: " + ", ".join(f"{k20[k][0]} ({k20[k][1]})" for k in only20 if k[0] not in moved))
show("O-7", "left in 2024: " + ", ".join(f"{k24[k][0]} ({k24[k][1]})" for k in only24 if k[0] not in moved))
for y in FILES:
    s = sheets[(y, "total")]
    regions = [l for i, (_, l, _) in enumerate(s["places"]) if s["depth"][i] == 1]
    provinces = sorted(clean(l) for i, (_, l, _) in enumerate(s["places"]) if s["depth"][i] == 2 and s["end"][i])
    s["provinces"] = provinces
    show("O-7", f"{y}: {len(regions)} regions: " + ", ".join(regions))
show("O-7", "provinces only in 2020: " + ", ".join(sorted(set(sheets[(2020, 'total')]["provinces"]) - set(sheets[(2024, 'total')]["provinces"])))
     + "; only in 2024: " + ", ".join(sorted(set(sheets[(2024, 'total')]["provinces"]) - set(sheets[(2020, 'total')]["provinces"]))))
show("O-7", "Special Geographic Area / Interim Province, both sexes ages 5-24, total population: " + "; ".join(
    f"{y} {l}: {v:,} in {n} units" for y, l, v, n in q("""SELECT a.year, a.label, sum(a.value) FILTER (WHERE a.sex = 'both'),
        count(DISTINCT c.sheet_row) FROM p a LEFT JOIN p c ON c.year = a.year AND c.concept = a.concept AND c.province = a.label
        AND c.sex = 'both' AND c.age = 5 WHERE a.concept = 'total' AND a.depth = 2 AND NOT a.is_lgu
        AND (a.label LIKE 'INTERIM PROVINCE%' OR a.label LIKE 'SPECIAL GEOGRAPHIC AREA%') GROUP BY 1, 2 ORDER BY 1""")))
show("O-7", "their units: " + "; ".join(f"{y}: {u}" for y, u in q("""SELECT year, string_agg(DISTINCT label, ', ' ORDER BY label) FROM p
    WHERE concept = 'total' AND (province LIKE 'INTERIM PROVINCE%' OR province LIKE 'SPECIAL GEOGRAPHIC AREA%') GROUP BY 1 ORDER BY 1""")))

# %% O-8 National counts by age
for y in FILES:
    show("O-8", f"{y} national, both sexes, total population, by age: " + fmt(
        (a, v) for a, v in q(f"SELECT age, value FROM p WHERE year = {y} AND concept = 'total' AND depth = 0 AND sex = 'both' ORDER BY age")))
show("O-8", "national, both sexes, total population, ages 5-17 / 5-24 (and DepEd bands 5, 6-11, 12-15, 16-17): " + "; ".join(
    f"{y}: {a:,} / {b:,} ({c:,}, {d:,}, {e:,}, {g:,})" for y, a, b, c, d, e, g in q("""SELECT year,
        sum(value) FILTER (WHERE age <= 17), sum(value), sum(value) FILTER (WHERE age = 5),
        sum(value) FILTER (WHERE age BETWEEN 6 AND 11), sum(value) FILTER (WHERE age BETWEEN 12 AND 15),
        sum(value) FILTER (WHERE age BETWEEN 16 AND 17)
        FROM p WHERE concept = 'total' AND depth = 0 AND sex = 'both' GROUP BY 1 ORDER BY 1""")))
show("O-8", "national males per 100 females, ages 5-17, total population: " + fmt((y, f"{r:.1f}") for y, r in q(
    """SELECT year, 100.0 * sum(value) FILTER (WHERE sex = 'male') / sum(value) FILTER (WHERE sex = 'female')
       FROM p WHERE concept = 'total' AND depth = 0 AND age <= 17 GROUP BY 1 ORDER BY 1""")))

# %% S-1 to S-3 Suspected findings
show("S-1", "the 2020 Interim Province units and the 2024 Special Geographic Area municipalities are listed under O-7; "
     "whether they cover the same barangays needs PSA or the PSGC barangay list (no query here)")
show("S-2", "census reference dates and the age definition are not stated in the files: documentary, ask PSA (no query)")
show("S-3", "Kalayaan (Palawan), both sexes, ages 5-24, total / household: " + "; ".join(
    f"{y}: {t:,} / {h:,}" for y, t, h in q("""SELECT year, sum(value) FILTER (WHERE concept = 'total'),
        sum(value) FILTER (WHERE concept = 'household') FROM p WHERE label = 'KALAYAAN' AND province = 'PALAWAN' AND sex = 'both' GROUP BY 1 ORDER BY 1""")))

# %% X-1 2024 household population against psa_population_per_age_group (five-year bands)
# The CSV marks its levels with leading dots (none: country, 2: region, 4: province or HUC) and
# keeps footnote markers in labels; places are paired by cleaned name within the same level.
csv_path = ORIGINAL / AGE_GROUP_CSV[0]
if not csv_path.exists() or sha256(csv_path) != AGE_GROUP_CSV[1]:
    show("X-1", f"skipped: {AGE_GROUP_CSV[0]} with the SHA-256 on the psa_population_per_age_group card is not in {ORIGINAL}")
else:
    with csv_path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        next(reader)  # title
        header = next(reader)
        age_group = [dict(zip(header, r)) for r in reader]
    bands = {"5 - 9": (5, 9), "10 - 14": (10, 14), "15 - 19": (15, 19), "20 - 24": (20, 24)}
    sexes = (("Both Sexes", "both"), ("Male", "male"), ("Female", "female"))

    def csv_key(label):
        dots = len(label) - len(label.lstrip("."))
        return {0: 0, 2: 1, 4: 2}.get(dots), clean(label.lstrip(".").replace("*", ""))

    theirs = {}
    for r in age_group:
        if r["Age Group"] in bands:
            depth, name = csv_key(r["Geographic Location"])
            theirs[(depth, name, r["Age Group"])] = {s: int(r[c]) for c, s in sexes}
    mine = {}
    for depth, label, sex, lo, v in q("""SELECT depth, label, sex, CASE WHEN age <= 9 THEN 5 WHEN age <= 14 THEN 10
            WHEN age <= 19 THEN 15 ELSE 20 END, sum(value) FROM p WHERE year = 2024 AND concept = 'household' AND depth <= 2
            GROUP BY ALL"""):
        band = {5: "5 - 9", 10: "10 - 14", 15: "15 - 19", 20: "20 - 24"}[lo]
        mine.setdefault((depth, clean(label), band), {})[sex] = v
    for depth, level in ((0, "national"), (1, "region"), (2, "province or HUC")):
        ours = {k for k in mine if k[0] == depth}
        paired = ours & set(theirs)
        equal = sum(mine[k][s] == theirs[k][s] for k in paired for _, s in sexes)
        show("X-1", f"{level}: places in this file {len(ours) // 4}, in the CSV {sum(1 for k in theirs if k[0] == depth) // 4}, "
             f"paired by name {len(paired) // 4}; cells equal {equal:,} of {len(paired) * 3:,} (4 bands x 3 sexes)")
        unpaired = sorted({k[1] for k in ours - set(theirs)})
        if unpaired:
            show("X-1", f"{level}: not paired by name: " + ", ".join(unpaired))
    show("X-1", "national 5 - 9, both sexes: this file {:,}, CSV {:,}".format(
        mine.get((0, "PHILIPPINES", "5 - 9"), {}).get("both", 0), theirs.get((0, "PHILIPPINES", "5 - 9"), {}).get("both", 0)))

# %% X-2 cities and municipalities against PSGC 2Q 2026 by name within province, both census years
psgc_path = ORIGINAL / PSGC_2Q2026[0]
if not psgc_path.exists() or sha256(psgc_path) != PSGC_2Q2026[1]:
    show("X-2", f"skipped: {PSGC_2Q2026[0]} with the SHA-256 on the psa_psgc card is not in {ORIGINAL}")
else:
    units = [(c.get(1, "").strip(), c.get(2, "").strip(), c.get(4, "").strip()) for _, c in read_sheet(psgc_path, "PSGC")[1:]]
    provinces = {code[:5]: name for code, name, level in units if level == "Prov"}
    psgc = collections.defaultdict(list)
    for code, name, level in units:
        if level in ("City", "Mun"):
            psgc[(clean(name), clean(provinces.get(code[:5], "-")))].append(code)
    show("X-2", f"PSGC 2Q 2026 cities and municipalities: {sum(len(v) for v in psgc.values()):,}")
    show("X-2", "PSGC 2Q 2026 provinces named Samar, Western Samar, Maguindanao, or Interim: " + (", ".join(
        f"{code} {name}" for code, name, level in units if level == "Prov" and re.search(r"^(WESTERN )?SAMAR$|MAGUINDANAO|INTERIM", name.upper())) or "none"))
    for year, keys in ((2020, k20), (2024, k24)):
        hit = [k for k in keys if len(psgc.get(k, [])) == 1]
        missed = [k for k in sorted(keys) if k not in psgc]
        show("X-2", f"{year}: places {len(keys):,}; matched exactly one PSGC unit by cleaned name and province: {len(hit):,}; "
             f"none: {len(missed)}; more than one: {sum(len(psgc.get(k, [])) > 1 for k in keys)}")
        show("X-2", f"{year}: not matched, by parent: " + fmt(collections.Counter(keys[k][1] for k in missed).most_common()))
        show("X-2", f"{year}: not matched: " + ", ".join(f"{keys[k][0]} ({keys[k][1]})" for k in missed))
    # S-4: for the 2024 names that are neither Western Samar nor the Special Geographic Area, the PSGC
    # cities and municipalities of the same province, to see whether a respelling or rename explains them.
    for k in sorted(k24):
        if k in psgc or k[1] in ("WESTERN SAMAR", "SPECIAL GEOGRAPHIC AREA"):
            continue
        near = sorted(n for n, prov in psgc if prov == k[1] and (n[:4] == k[0][:4] or n.replace("CITY OF ", "")[:4] == k[0][:4]))
        show("S-4", f"{k24[k][0]} ({k24[k][1]}): PSGC units in the same province starting the same way: {', '.join(near) or 'none'}")

workdir.cleanup()
