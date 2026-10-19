# Profiles two sources: deped_enrollment and deped_facilities.
#
# Reproduces every finding in:
#   docs/data/source-inventory/deped_enrollment/profile.md
#   docs/data/source-inventory/deped_facilities/profile.md
# Each check prints under its finding ID (O-n observed, S-n suspected).
#
# Runs locally with DuckDB; no Databricks compute. Open it in VS Code to run
# cell by cell (# %% markers), or run the whole file:
#   RAW_DATA_DIR=~/Projects/reached-hq/raw-data python analysis/profiling/profile_deped.py
#
# RAW_DATA_DIR must contain deped/original/ with the zips listed in FILES.
# Raw files are read, never modified.

# %% Setup
import hashlib
import os
import sys
import tempfile
import zipfile
from pathlib import Path

import duckdb

raw_dir = os.environ.get("RAW_DATA_DIR")
if not raw_dir:
    sys.exit("Set RAW_DATA_DIR to the folder that contains deped/original/.")
ORIGINAL = Path(raw_dir).expanduser() / "deped" / "original"

# What arrived, as recorded in the inventory cards. The encoding is declared,
# not guessed: SY 2025-26 is Windows-1252, the rest UTF-8 (enrollment O-6).
FILES = {
    "enr_2020_21": {
        "zip": "Enrollment-in-SY-2020-2021.zip",
        "zip_sha256": "65c400aa31ba63730b8f9a7b4d60ade91c6a29cdb34a3c6bf255e5fc9e91a241",
        "csv": "enrollment_2020-21.csv",
        "encoding": "utf-8",
    },
    "enr_2021_22": {
        "zip": "Enrollment-in-SY-2021-2022.zip",
        "zip_sha256": "62f412466435db6feba57684643f5af99ca901c6ea88accb420efe9a9bfb0acd",
        "csv": "enrollment_2021-22.csv",
        "encoding": "utf-8",
    },
    "enr_2022_23": {
        "zip": "Enrollment-in-SY-2022-2023.zip",
        "zip_sha256": "6d567d801a8d4eb6c9dec3c032ba208e4cd929c226b6326bc7c687c83efbf9bf",
        "csv": "enrollment_2022-23.csv",
        "encoding": "utf-8",
    },
    "enr_2023_24": {
        "zip": "Enrollment-in-SY-2023-2024.zip",
        "zip_sha256": "a10f4d0f9082919c13b3a091774c8231c99c95b1b1872310714107013b77dbbb",
        "csv": "enrollment_2023-24.csv",
        "encoding": "utf-8",
    },
    "enr_2024_25": {
        "zip": "Enrollment-in-SY-2024-2025.zip",
        "zip_sha256": "fd5dd74a62b828608c62335b7c324ddf05be58e3f05465fee68854795f5b1a92",
        "csv": "enrollment_2024-25.csv",
        "encoding": "utf-8",
    },
    "enr_2025_26": {
        "zip": "Enrollment-in-SY-2025-2026.zip",
        "zip_sha256": "ab4d7e24b3a46a99db2c76dee5279a976e4c3a76062e79f7217e70dc6dd1b450",
        "csv": "enrollment_2025-26.csv",
        "encoding": "cp1252",
    },
    "fac_2023_24": {
        "zip": "School-Facilities-in-SY-2023-2024.zip",
        "zip_sha256": "9317af02b595d3a8d7381715780ef183a92da35354bbe0f3796045490e546609",
        "csv": "facilities_2023-24.csv",
        "encoding": "utf-8",
    },
}
ENROLLMENT = ["enr_2020_21", "enr_2021_22", "enr_2022_23", "enr_2023_24", "enr_2024_25", "enr_2025_26"]
CONSECUTIVE = list(zip(ENROLLMENT, ENROLLMENT[1:]))

con = duckdb.connect()


def q(sql):
    return con.execute(sql).fetchall()


def one(sql):
    return q(sql)[0][0]


def show(finding, text):
    print(f"[{finding}] {text}")


# %% Verify checksums and load every column as text
# A changed file must stop the run, not silently produce new numbers
# under the old checksum.
raw_bytes = {}
workdir = tempfile.TemporaryDirectory()
for table, spec in FILES.items():
    zip_path = ORIGINAL / spec["zip"]
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    if digest != spec["zip_sha256"]:
        sys.exit(f"{spec['zip']}: SHA-256 {digest} does not match the inventory card. Stop and re-inventory.")
    with zipfile.ZipFile(zip_path) as zf:
        member = next(n for n in zf.namelist() if n.endswith("/" + spec["csv"]))
        data = zf.read(member)
    raw_bytes[table] = data
    text = data.decode(spec["encoding"]).replace("\r\n", "\n")
    utf8_copy = Path(workdir.name) / spec["csv"]
    utf8_copy.write_text(text, encoding="utf-8")
    con.execute(
        f"CREATE TABLE {table} AS SELECT * FROM read_csv('{utf8_copy}', "
        "all_varchar = true, header = true, strict_mode = true)"
    )
    print(f"{table}: {one(f'SELECT count(*) FROM {table}'):,} rows, "
          f"{len(q(f'DESCRIBE {table}'))} columns, checksum OK")


def columns(table):
    return [r[0] for r in q(f"DESCRIBE {table}")]


def count_columns(table):
    return [c for c in columns(table) if c.endswith(("_male", "_female"))]


def total_expr(cols):
    return " + ".join(f"coalesce(try_cast({c} AS BIGINT), 0)" for c in cols)


ES_PREFIXES = ("kinder", "g1", "g2", "g3", "g4", "g5", "g6", "esng")

# %% deped_enrollment
print("\n=== deped_enrollment ===")

for t in ENROLLMENT:
    r = q(f"""SELECT count(*) FILTER (WHERE school_id IS NULL),
                     count(*) FILTER (WHERE NOT regexp_full_match(school_id, '[0-9]+')),
                     count(*) FILTER (WHERE length(school_id) <> 6),
                     count(*) - count(DISTINCT school_id)
              FROM {t}""")[0]
    full_dupes = one(f"SELECT count(*) - (SELECT count(*) FROM (SELECT DISTINCT * FROM {t})) FROM {t}")
    show("O-1", f"{t}: blank={r[0]} non_numeric={r[1]} not_6_digits={r[2]} duplicate_ids={r[3]} full_duplicate_rows={full_dupes}")
r = q("""SELECT school_id, school_name, sector, municipality, kinder_male, kinder_female FROM enr_2022_23 WHERE length(school_id) <> 6""")
show("O-1", f"enr_2022_23 school_id not 6 digits (school, name, sector, municipality, kinder male, kinder female): {r}; "
     f"same name in the same file: {q(f'SELECT school_id FROM enr_2022_23 WHERE school_name = {chr(39)}{r[0][1]}{chr(39)} AND length(school_id) = 6')}")

for t in ENROLLMENT:
    cc = count_columns(t)
    non_int = sum(one(f"SELECT count(*) FROM {t} WHERE {c} IS NOT NULL AND NOT regexp_full_match(trim({c}), '-?[0-9]+')") for c in cc)
    negative = sum(one(f"SELECT count(*) FROM {t} WHERE try_cast({c} AS BIGINT) < 0") for c in cc)
    es = total_expr([c for c in cc if c.split("_")[0] in ES_PREFIXES])
    es_mismatch = one(f"SELECT count(*) FROM {t} WHERE offers_es IN ('False', 'No') AND ({es}) > 0")
    show("O-2", f"{t}: {len(cc)} count columns, non_integer={non_int} negative={negative} es_learners_at_non_es_schools={es_mismatch}")

for t in ENROLLMENT:
    show("O-3", f"{t}: total learners = {one(f'SELECT sum({total_expr(count_columns(t))}) FROM {t}'):,}")
for t in ENROLLMENT[:4]:
    show("O-3", f"{t}: learners by sector = {q(f'SELECT sector, sum({total_expr(count_columns(t))}) FROM {t} GROUP BY 1 ORDER BY 2 DESC')}")

psgc_like = [c for t in ENROLLMENT for c in columns(t) if "psgc" in c.lower() or c.lower().endswith("_code")]
show("O-4", f"columns that look like geographic codes: {sorted(set(psgc_like)) or 'none'}")

capital = one("SELECT count(*) FROM enr_2023_24 WHERE municipality LIKE '%(Capital)%'")
cebu = one("SELECT count(*) FROM enr_2023_24 WHERE municipality = 'CEBU CITY (Capital)'")
show("O-5", f"enr_2023_24 rows with '(Capital)' in municipality: {capital:,} (e.g. 'CEBU CITY (Capital)': {cebu})")
for t in ENROLLMENT:
    r = q(f"""SELECT count(*) FILTER (WHERE province = upper(province)),
                     count(*) FILTER (WHERE division = upper(division)),
                     count(*) FILTER (WHERE municipality LIKE '%  %'),
                     count(*) FILTER (WHERE municipality <> trim(municipality) OR province <> trim(province)
                                      OR barangay <> trim(barangay))
              FROM {t} WHERE region <> 'PSO'""")[0]
    show("O-5", f"{t}: province ALL CAPS rows={r[0]:,} division ALL CAPS rows={r[1]:,} municipality with double space={r[2]} rows with leading/trailing spaces={r[3]}")
r = q("""SELECT count(*),
                count(*) FILTER (WHERE regexp_replace(a.municipality, ' +', ' ', 'g') = regexp_replace(b.municipality, ' +', ' ', 'g'))
         FROM enr_2024_25 a JOIN enr_2025_26 b USING (school_id) WHERE a.municipality <> b.municipality""")[0]
show("O-5", f"municipality text changed 2024-25 -> 2025-26: {r[0]} schools, of which {r[1]} differ only by spacing")

def utf8_failures(data):
    failures = 0
    for line in data.split(b"\n"):
        try:
            line.decode("utf-8")
        except UnicodeDecodeError:
            failures += 1
    return failures


CRLF = b"\r\n"
for t in ENROLLMENT:
    data = raw_bytes[t]
    show("O-6", f"{t}: lines failing UTF-8 = {utf8_failures(data):,}, CRLF line endings = {CRLF in data}")

base_order = columns("enr_2023_24")
base = set(base_order)
for t in [t for t in ENROLLMENT if t != "enr_2023_24"]:
    cols = set(columns(t))
    show("O-7", f"{t} vs enr_2023_24: added={sorted(cols - base)} removed={sorted(base - cols)} "
         f"same_columns_in_same_order={columns(t) == base_order}")
vals = q('SELECT "Modified Curricular Offering Classification", count(*) FROM enr_2025_26 GROUP BY 1 ORDER BY 2 DESC')
show("O-7", "enr_2025_26 Modified Curricular Offering Classification: " + "; ".join(f"{v} {n:,}" for v, n in vals))

for col in ["sector", "school_management", "annex_status", "offers_es"]:
    for t in ENROLLMENT:
        vals = q(f"SELECT '[' || coalesce({col}, 'NULL') || ']', count(*) FROM {t} GROUP BY 1 ORDER BY 2 DESC, 1")
        show("O-8", f"{t}.{col}: " + "; ".join(f"{v} {n:,}" for v, n in vals))
lg = q("""SELECT b.school_management, count(*) FROM enr_2020_21 a JOIN enr_2023_24 b USING (school_id)
          WHERE a.school_management = 'Local Government' GROUP BY 1 ORDER BY 2 DESC""")
show("O-8", f"enr_2020_21 'Local Government' schools, by 2023-24 school_management: {lg}")
for t in ENROLLMENT:
    show("O-8", f"{t}: 'Local Government' rows = {one(f'SELECT count(*) FROM {t} WHERE school_management = {chr(39)}Local Government{chr(39)}')}")
lg = q("""SELECT coalesce(b.school_management, '(not in 2021-22)'), count(*) FROM enr_2020_21 a LEFT JOIN enr_2021_22 b USING (school_id)
          WHERE a.school_management = 'Local Government' GROUP BY 1 ORDER BY 2 DESC""")
show("O-8", f"enr_2020_21 'Local Government' schools, by 2021-22 school_management: {lg}")
for a, b in CONSECUTIVE[1:3]:
    lg = q(f"""SELECT coalesce(y.school_management, '(not in {b})'), count(*) FROM {a} x LEFT JOIN {b} y USING (school_id)
               WHERE x.school_management = 'Local Government' GROUP BY 1 ORDER BY 2 DESC""")
    show("O-8", f"{a} 'Local Government' schools, by {b} school_management: {lg}")
gone = q("""SELECT sector, region, municipality, count(*) FROM enr_2020_21 WHERE school_management = 'Local Government'
             AND school_id NOT IN (SELECT school_id FROM enr_2023_24) AND school_id NOT IN (SELECT school_id FROM enr_2024_25)
             GROUP BY ALL ORDER BY 4 DESC, 3""")
show("O-8", f"enr_2020_21 'Local Government' schools in neither enr_2023_24 nor enr_2024_25 (sector, region, municipality, schools): {gone}")
show("O-9", "compare the school_management values above with the README, which lists 'DepEd Managed'")

origins = q("""SELECT a.region, count(*) FROM enr_2023_24 a JOIN enr_2024_25 b USING (school_id)
               WHERE b.region = 'NIR' GROUP BY 1 ORDER BY 2 DESC""")
other_moves = one("""SELECT count(*) FROM enr_2023_24 a JOIN enr_2024_25 b USING (school_id)
                     WHERE a.region <> b.region AND b.region <> 'NIR'""")
show("O-10", f"schools in NIR in 2024-25, by 2023-24 region: {origins}; other region changes: {other_moves}")
moves = q("""SELECT a.region, b.region, a.division, b.division, count(*) FROM enr_2020_21 a JOIN enr_2023_24 b USING (school_id)
             WHERE a.region <> b.region GROUP BY ALL ORDER BY 5 DESC""")
show("O-10", f"region changes 2020-21 -> 2023-24 (region, region, division, division, schools): {moves}")
by_sector = q("""SELECT a.division, a.sector, count(*) FROM enr_2020_21 a JOIN enr_2023_24 b USING (school_id)
                 WHERE a.region <> b.region GROUP BY ALL ORDER BY 1, 3 DESC""")
show("O-10", f"those schools by 2020-21 division and sector: {by_sector}")
# With SY 2021-22 and 2022-23 acquired, the year of the Region XII -> BARMM relabel is visible.
for a, b in CONSECUTIVE[:3]:
    moves = q(f"""SELECT x.region, y.region, x.division, y.division, count(*) FROM {a} x JOIN {b} y USING (school_id)
                  WHERE x.region <> y.region GROUP BY ALL ORDER BY 5 DESC""")
    show("O-10", f"region changes {a} -> {b} (region, region, division, division, schools): {moves}")
relabelled_gone = q("""SELECT x.school_id, x.school_name, x.sector, x.division FROM enr_2020_21 x JOIN enr_2021_22 y USING (school_id)
            WHERE x.region <> y.region AND x.school_id NOT IN (SELECT school_id FROM enr_2023_24)""")
show("O-10", f"relabelled 2020-21 -> 2021-22 but absent from enr_2023_24, so 192 there vs 191 in the direct comparison "
     f"(school, name, sector, division): {relabelled_gone}")
moved = q("""SELECT x.school_id, x.school_name, x.sector, x.municipality, y.municipality FROM enr_2021_22 x JOIN enr_2022_23 y USING (school_id)
             WHERE x.region = 'NCR' AND y.region <> 'NCR'""")
show("O-10", f"enr_2021_22 NCR schools outside NCR in enr_2022_23 (school, name, sector, municipality, municipality): {moved}")
# Selected by division, not province: from SY 2024-25 some of these schools publish province '(SGA - North Cotabato)' (O-11).
for t in ENROLLMENT:
    show("O-10", f"{t}: BARMM schools in the Special Geographic division (province, division, schools) = "
         f"{q(f'SELECT province, division, count(*) FROM {t} WHERE region = {chr(39)}BARMM{chr(39)} AND division LIKE {chr(39)}Special Geographic%{chr(39)} GROUP BY ALL ORDER BY 3 DESC')}")

for t in ENROLLMENT:
    show("O-11", f"{t}: distinct provinces = {one(f'SELECT count(DISTINCT province) FROM {t}')}")
show("O-11", f"provinces new in 2024-25: {[r[0] for r in q('SELECT DISTINCT province FROM enr_2024_25 EXCEPT SELECT DISTINCT province FROM enr_2023_24')]}")

for a, b in [("enr_2020_21", "enr_2023_24")] + CONSECUTIVE:
    r = q(f"""SELECT count(*) FILTER (WHERE x.school_id IS NOT NULL AND y.school_id IS NOT NULL),
                     count(*) FILTER (WHERE y.school_id IS NULL), count(*) FILTER (WHERE x.school_id IS NULL)
              FROM {a} x FULL OUTER JOIN {b} y USING (school_id)""")[0]
    show("O-12", f"{a} -> {b}: kept={r[0]:,} dropped={r[1]:,} new={r[2]:,}")
for side, keep, other in [("dropped", "enr_2020_21", "enr_2023_24"), ("new", "enr_2023_24", "enr_2020_21")]:
    show("O-12", f"2020-21 -> 2023-24 {side} by sector = "
         f"{q(f'SELECT sector, count(*) FROM {keep} WHERE school_id NOT IN (SELECT school_id FROM {other}) GROUP BY 1 ORDER BY 2 DESC')}")
for a, b in CONSECUTIVE[:3]:
    show("O-12", f"{a} -> {b} dropped by sector = "
         f"{q(f'SELECT sector, count(*) FROM {a} WHERE school_id NOT IN (SELECT school_id FROM {b}) GROUP BY 1 ORDER BY 2 DESC')}")
gap = q("""SELECT count(*), count(*) FILTER (WHERE school_id NOT IN (SELECT school_id FROM enr_2021_22)) FROM enr_2020_21
           WHERE school_id NOT IN (SELECT school_id FROM enr_2023_24)""")[0]
show("O-12", f"2020-21 IDs absent from 2023-24: {gap[0]:,}, of which already absent from 2021-22: {gap[1]:,}")
# AP4 counts learners, not schools (D-042), so the dropped IDs are also measured in learners.
learners_2020 = total_expr(count_columns("enr_2020_21"))
r = q(f"""SELECT sum({learners_2020}) FILTER (WHERE school_id NOT IN (SELECT school_id FROM enr_2023_24)), sum({learners_2020})
          FROM enr_2020_21""")[0]
show("O-12", f"2020-21 -> 2023-24 dropped: learners {r[0]:,} of {r[1]:,} ({r[0] / r[1]:.1%}); by sector = "
     f"{q(f'SELECT sector, sum({learners_2020}) FROM enr_2020_21 WHERE school_id NOT IN (SELECT school_id FROM enr_2023_24) GROUP BY 1 ORDER BY 2 DESC')}")

for t in ENROLLMENT[:4]:
    show("O-13", f"{t} rows with region PSO: {one(f'SELECT count(*) FROM {t} WHERE region = {chr(39)}PSO{chr(39)}')}")
pso_places = q("SELECT municipality, count(*) FROM enr_2025_26 WHERE region = 'PSO' GROUP BY 1")
show("O-13", f"enr_2025_26 PSO municipality values: {pso_places}")


def blank_count(table, column):
    return one(f"SELECT count(*) FROM {table} WHERE {column} IS NULL OR trim({column}) = ''")


for t in ENROLLMENT:
    show("O-14", f"{t}: blank street_address = {blank_count(t, 'street_address'):,}")
top = q("SELECT street_address, count(*) FROM enr_2025_26 GROUP BY 1 ORDER BY 2 DESC LIMIT 3")
show("O-14", f"enr_2025_26 most common street_address: {top}")

for t in ENROLLMENT:
    show("O-15", f"{t}: blank barangay = {blank_count(t, 'barangay')}")

for t in ENROLLMENT:
    blank = [c for c in count_columns(t) if one(f"SELECT count({c}) FROM {t}") == 0]
    show("O-16", f"{t}: entirely blank count columns = {blank}")

# "Ã‘" is how "Ñ" looks when UTF-8 text was read as Windows-1252 and saved again.
PLACE = "province LIKE '%Ã%' OR municipality LIKE '%Ã%' OR barangay LIKE '%Ã%'"
for t in ENROLLMENT:
    show("O-17", f"{t}: rows with mangled characters in place names = {one(f'SELECT count(*) FROM {t} WHERE {PLACE}')}; "
         f"distinct places = {one(f'SELECT count(DISTINCT concat_ws({chr(39)}|{chr(39)}, province, municipality, barangay)) FROM {t} WHERE {PLACE}')}; "
         f"rows with mangled school names = {one(f'SELECT count(*) FROM {t} WHERE school_name LIKE {chr(39)}%Ã%{chr(39)}')}; "
         f"examples = {[r[0] for r in q(f'SELECT DISTINCT barangay FROM {t} WHERE barangay LIKE {chr(39)}%Ã%{chr(39)} ORDER BY 1 LIMIT 3')]}")

for t in ENROLLMENT:
    lengths = dict(q(f"SELECT length(barangay), count(*) FROM {t} WHERE length(barangay) >= 38 GROUP BY 1"))
    show("O-18", f"{t}: longest barangay = {one(f'SELECT max(length(barangay)) FROM {t}')} characters; rows at 38/39/40 characters = "
         f"{lengths.get(38, 0)}/{lengths.get(39, 0)}/{lengths.get(40, 0)}; distinct 40-character names = "
         f"{one(f'SELECT count(DISTINCT barangay) FROM {t} WHERE length(barangay) = 40')}; "
         f"examples = {[r[0] for r in q(f'SELECT DISTINCT barangay FROM {t} WHERE length(barangay) = 40 ORDER BY 1 LIMIT 2')]}")

for t in ENROLLMENT:
    show("S-1", f"{t}: zero-learner schools by sector = {q(f'SELECT sector, count(*) FROM {t} WHERE ({total_expr(count_columns(t))}) = 0 GROUP BY 1 ORDER BY 2 DESC')}")

zero = f"SELECT school_id FROM enr_2020_21 WHERE ({total_expr(count_columns('enr_2020_21'))}) = 0"
r = q(f"""SELECT count(*), count(b.school_id), count(*) FILTER (WHERE ({total_expr(count_columns('enr_2023_24'))}) > 0)
          FROM ({zero}) z LEFT JOIN enr_2023_24 b USING (school_id)""")[0]
show("S-1", f"enr_2020_21 zero-learner schools: {r[0]}, of which in enr_2023_24 = {r[1]}, with learners there = {r[2]}")
for a, b in CONSECUTIVE[:3]:
    zero = f"SELECT school_id FROM {a} WHERE ({total_expr(count_columns(a))}) = 0"
    r = q(f"""SELECT count(*), count(y.school_id), count(*) FILTER (WHERE ({total_expr(count_columns(b))}) > 0)
              FROM ({zero}) z LEFT JOIN {b} y USING (school_id)""")[0]
    show("S-1", f"{a} zero-learner schools: {r[0]}, of which in {b} = {r[1]}, with learners there = {r[2]}")

for t in ENROLLMENT[:4]:
    r = q(f"""SELECT count(*), sum({total_expr(count_columns(t))}),
                     count(*) FILTER (WHERE ({total_expr(count_columns(t))}) = 0)
              FROM {t} WHERE sector = 'Private'""")[0]
    show("S-5", f"{t}: private schools = {r[0]:,}, private learners = {r[1]:,}, private schools with zero learners = {r[2]}")

STRANDS = ("abm", "arts", "gas", "humss", "maritime", "sports", "stem", "tvl", "unique")


def strand_total(table, grade, strand):
    return f"coalesce(try_cast({table}.{grade}_{strand}_male AS BIGINT), 0) + coalesce(try_cast({table}.{grade}_{strand}_female AS BIGINT), 0)"


for before, after in CONSECUTIVE:
    jumps = []
    for s in STRANDS:
        jumps += q(f"""SELECT a.school_id, '{s}', {strand_total('b', 'g11', s)}, {strand_total('a', 'g11', s)}, {strand_total('a', 'g12', s)}
                       FROM {after} AS a JOIN {before} AS b ON a.school_id = b.school_id
                       WHERE {strand_total('a', 'g11', s)} >= 1000 AND {strand_total('a', 'g11', s)} >= 5 * {strand_total('b', 'g11', s)}""")
    show("S-4", f"{before} -> {after}: Grade 11 strands with 1,000+ learners and 5x the year before "
         f"(school, strand, G11 before, G11 after, G12 after) = {sorted(jumps)}")
    # The cohort test: do those Grade 11 learners reach Grade 12 the year after?
    following = dict(CONSECUTIVE).get(after)
    if following:
        cohort = [(sid, s, g11, one(f"SELECT coalesce(max({strand_total(following, 'g12', s)}), 0) FROM {following} WHERE school_id = '{sid}'"))
                  for sid, s, _, g11, _ in sorted(jumps)]
        show("S-4", f"  same strands in {following} (school, strand, G11 in {after}, G12 in {following}) = {cohort}")

# %% deped_facilities
print("\n=== deped_facilities ===")

r = q("""SELECT count(*) FILTER (WHERE school_id IS NULL),
                count(*) FILTER (WHERE NOT regexp_full_match(school_id, '[0-9]+')),
                count(*) FILTER (WHERE length(school_id) <> 6),
                count(*) - count(DISTINCT school_id)
         FROM fac_2023_24""")[0]
full_dupes = one("SELECT count(*) - (SELECT count(*) FROM (SELECT DISTINCT * FROM fac_2023_24)) FROM fac_2023_24")
show("O-1", f"fac_2023_24: blank={r[0]} non_numeric={r[1]} not_6_digits={r[2]} duplicate_ids={r[3]} full_duplicate_rows={full_dupes}")

r = q("""SELECT count(*) FILTER (WHERE e.school_id IS NOT NULL AND f.school_id IS NOT NULL),
                count(*) FILTER (WHERE f.school_id IS NULL), count(*) FILTER (WHERE e.school_id IS NULL)
         FROM enr_2023_24 e FULL OUTER JOIN fac_2023_24 f USING (school_id)""")[0]
show("O-2", f"vs enr_2023_24: in both={r[0]:,} enrollment only={r[1]} facilities only={r[2]}")
r = q("""SELECT count(*) FILTER (WHERE e.sector <> f.sector), count(*) FILTER (WHERE e.school_management <> f.school_management),
                count(*) FILTER (WHERE e.offers_es <> f.offers_es OR e.offers_jhs <> f.offers_jhs OR e.offers_shs <> f.offers_shs)
         FROM enr_2023_24 e JOIN fac_2023_24 f USING (school_id)""")[0]
show("O-2", f"same school, different value: sector={r[0]} management={r[1]} offers={r[2]}")

for row in q("""SELECT sector, count(*), count(es_classrooms_instructional), count(buildings_good_condition),
                       count(es_temporary_learning_spaces)
                FROM fac_2023_24 GROUP BY 1 ORDER BY 2 DESC"""):
    show("O-3", f"{row[0]}: rows={row[1]:,} with_es_classrooms={row[2]:,} with_building_counts={row[3]:,} with_tls={row[4]:,}")

r = q("""SELECT count(*), count(*) FILTER (WHERE es_classrooms_instructional IS NULL) FROM fac_2023_24
         WHERE sector = 'Public' AND offers_es = 'True'""")[0]
show("O-4", f"public schools offering ES: {r[0]:,}, with blank ES classroom count: {r[1]}")
r = q("""SELECT count(*) FILTER (WHERE offers_jhs = 'True' AND jhs_classrooms_instructional IS NULL),
                count(*) FILTER (WHERE offers_shs = 'True' AND shs_classrooms_instructional IS NULL)
         FROM fac_2023_24 WHERE sector = 'Public'""")[0]
show("O-4", f"public schools offering JHS / SHS with blank classroom count: {r[0]} / {r[1]}")

fac_cols = columns("fac_2023_24")
numeric = [c for c in fac_cols if c.startswith(("es_classrooms", "jhs_classrooms", "shs_classrooms", "buildings_"))
           or "temporary_learning" in c or "makeshift" in c]
for c in [c for c in numeric if "classrooms_instructional" in c]:
    show("O-5", f"{c}: rows equal to 0 = {one(f'SELECT count(*) FROM fac_2023_24 WHERE try_cast({c} AS BIGINT) = 0'):,}")

non_int = sum(one(f"SELECT count(*) FROM fac_2023_24 WHERE {c} IS NOT NULL AND NOT regexp_full_match(trim({c}), '-?[0-9]+')") for c in numeric)
negative = sum(one(f"SELECT count(*) FROM fac_2023_24 WHERE try_cast({c} AS BIGINT) < 0") for c in numeric)
show("O-6", f"{len(numeric)} numeric columns: non_integer={non_int} negative={negative}")

info = {"school_id", "sector", "school_management", "offers_es", "offers_jhs", "offers_shs"}
flags = [c for c in fac_cols if c not in numeric and c not in info]
values = q(f"SELECT DISTINCT v FROM (SELECT unnest([{', '.join(flags)}]) AS v FROM fac_2023_24) ORDER BY 1")
shares = [one(f"SELECT 100.0 * count(*) FILTER (WHERE {c} IS NULL) / count(*) FROM fac_2023_24") for c in flags]
show("O-7", f"{len(flags)} yes/no columns, values={[v for (v,) in values]}, blank share {min(shares):.1f}% to {max(shares):.1f}%")

es = total_expr([f"e.{c}" for c in count_columns("enr_2023_24") if c.split("_")[0] in ES_PREFIXES])
r = q(f"""WITH x AS (
            SELECT ({es}) AS learners, try_cast(f.es_classrooms_instructional AS BIGINT) AS rooms
            FROM enr_2023_24 e JOIN fac_2023_24 f USING (school_id)
            WHERE f.sector = 'Public' AND f.offers_es = 'True')
          SELECT count(*) FILTER (WHERE rooms > 0),
                 count(*) FILTER (WHERE rooms > 0 AND learners = 0),
                 quantile_cont(learners / rooms, [0.05, 0.5, 0.95, 0.99]) FILTER (WHERE rooms > 0),
                 max(learners / rooms) FILTER (WHERE rooms > 0)
          FROM x""")[0]
show("O-8", f"learners per ES instructional room: schools={r[0]:,} p5/p50/p95/p99={[round(v, 1) for v in r[2]]} max={r[3]:.1f}; rooms but 0 learners={r[1]}")
show("O-9", "definition comparison is documentary: facilities README vs Technical Notes p. 11 (no query)")

workdir.cleanup()
