# Option B check for #137 and #91: compare the PSGC codes in the EMISD workbook
# (deped_enrollment_psgc, #135) with the name match of cross_source_deped.py, school by school,
# for SY 2023-24. Answers: how often do they agree, where do they disagree and why, and how
# many schools are matched when the EMISD code comes first and the name match is the fallback.
#
#   RAW_DATA_DIR=~/Projects/reached-hq/raw-data python analysis/cross_source/cross_source_deped_enrollment_psgc.py
#
# RAW_DATA_DIR needs the files of cross_source_deped.py plus, in deped/original/, the EMISD
# workbook (FILE below). Raw files are read, never modified (D-007). Runs locally; no Databricks.
# Writes two CSVs to work/ (git-ignored) or OUT_DIR; they hold school-level rows, so they are not
# committed: one row per school that does not agree at both levels (EP-11), and the map preview (EP-16).
#
# Part 2 (EP-12 to EP-18) applies the proposed #91 match rule (cross_source_deped_school_psgc_rule.py,
# described in config/mappings/integration/deped_school_psgc.json) and writes a preview of the map,
# one row per school and level, with the D-029 columns.
#
# Rules applied to the EMISD codes before comparing (EP-2 and EP-3 count the tiers):
#   - padded to 10 digits: Excel stored them as numbers and dropped the leading zero (profile O-5);
#   - `#N/A` and blank mean no code (O-6);
#   - a school ID on more than one row keeps its first row; the duplicates are counted, and the run
#     stops if one is a school compared here (profile O-3);
#   - "Sulu region": a Sulu code (`19066…`) missing from PSGC 2Q 2026 whose `09066…` form is in it
#     (Q4 2024 still had Sulu under BARMM; D-029 `code_region_moved`, as for HDX, D-049);
#   - a code still missing from PSGC 2Q 2026 is "code not in 2Q 2026" and not used;
#   - a Manila sub-municipality rolls up to the City of Manila, as the name match does.

# %% Setup
import collections
import contextlib
import csv
import hashlib
import io
import json
import os
import re
import runpy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))
from src.profiling.xlsx import read_sheet

sys.path.insert(0, str(HERE))
from cross_source_deped_school_psgc_rule import Rule

# Name match of every SY 2023-24 school: the rules, tiers and aliases of cross_source_deped.py.
with contextlib.redirect_stdout(io.StringIO()):
    deped = runpy.run_path(str(HERE / "cross_source_deped.py"), run_name="__main__")
RAW = deped["RAW"]
schools = deped["schools"]  # (school_id, region, province, municipality, barangay), PSO excluded
loc_result, bgy_result = deped["loc_result"], deped["bgy_result"]
units_by_id = deped["units_by_id"]
city_or_municipality = deped["city_or_municipality"]
name_match, barangay_candidates = deped["match"], deped["barangay_candidates"]

FILE = "SY 2023-2024 School Level Data on Enrollment with PSGC, Longitude and Latitude.xlsx"
SHA256 = "746d69530d228d2324590be10abbe6d75a94176c1745ef74335a4d6db550acd5"
SHEET, HEADER_ROW = "DB", 8
# Columns by number (A = 1), from the deped_enrollment_psgc data dictionary; the header is checked below.
COLUMNS = {"school_id": (4, "BEIS School ID"), "mun": (22, "(PSGC) MUNCIPAL/CITY"), "bgy": (24, "(PSGC) BARANGAY")}
# work/ is git-ignored; set OUT_DIR to write elsewhere.
OUT_DIR = Path(os.environ.get("OUT_DIR", REPO / "work")).expanduser()
OUT = OUT_DIR / "deped_enrollment_psgc_vs_name_match.csv"
MAP_OUT = OUT_DIR / "deped_school_psgc_map_preview.csv"
RULES = json.loads((REPO / "config" / "mappings" / "integration" / "deped_school_psgc.json").read_text(encoding="utf-8"))


def show(finding, text):
    print(f"[{finding}] {text}")


def pct(n, d):
    return f"{n:,} of {d:,} ({100 * n / d:.1f}%)" if d else f"{n:,} of 0"


# %% Load the EMISD codes
path = RAW / "deped" / "original" / FILE
if hashlib.sha256(path.read_bytes()).hexdigest() != SHA256:
    sys.exit(f"{FILE}: SHA-256 does not match the deped_enrollment_psgc card. Stop and re-inventory.")
rows = read_sheet(path, SHEET)
header = dict(rows[HEADER_ROW - 1][1])
for key, (col, name) in COLUMNS.items():
    if re.sub(r"\s+", " ", header.get(col, "")).strip() != name:
        sys.exit(f"{FILE}: column {col} is {header.get(col)!r}, expected {name!r}. The header changed; stop.")


def psgc(raw, levels):
    """(tier, unit) for an EMISD code cell, on PSGC 2Q 2026."""
    text = (raw or "").strip()
    if text in ("", "#N/A"):
        return "no code", None
    if not text.isdigit():
        return "code not digits", None
    code = text.zfill(10)
    unit = units_by_id.get(code)
    tier = "code"
    if unit is None and code.startswith("19066") and units_by_id.get("09" + code[2:]):
        unit, tier = units_by_id["09" + code[2:]], "code, Sulu region"
    if unit is None:
        return "code not in 2Q 2026", None
    if unit.level not in levels:
        return f"code is a {unit.level}", None
    return tier, unit


emisd = {}
duplicates = collections.Counter()
for _, cells in rows[HEADER_ROW:]:
    school_id = cells.get(COLUMNS["school_id"][0], "").strip()
    if school_id in emisd:
        duplicates[school_id] += 1
    elif school_id:
        emisd[school_id] = (
            psgc(cells.get(COLUMNS["mun"][0]), ("City", "Mun", "SubMun")),
            psgc(cells.get(COLUMNS["bgy"][0]), ("Bgy",)),
        )
show("run", f"{FILE}: {len(emisd):,} school IDs, checksum OK; "
     f"{sum(duplicates.values()):,} duplicate rows of {len(duplicates):,} school IDs, first row kept: {sorted(duplicates)}")
compared_duplicates = sorted(set(duplicates) & {s[0] for s in schools})
if compared_duplicates:
    sys.exit(f"{FILE}: school IDs compared here appear on more than one row: {compared_duplicates}. Stop and review.")

# %% Compare, level by level
sga = {s[0] for s in schools if s[1] == "BARMM" and s[2] == "NORTH COTABATO"}  # D-031


def in_taguig(unit):
    """True when a PSGC unit is the City of Taguig or one of its barangays (Embo moved there from Makati)."""
    parents = [unit] + [units_by_id.get(unit.id[:n] + "0" * (10 - n)) for n in (7, 5)]
    return any(u is not None and "Taguig" in u.name for u in parents)


def same_barangay_name(deped_barangay, unit):
    """True when DepEd's barangay name matches this PSGC barangay by the DepEd tiers (as HDX does)."""
    return bool(deped_barangay) and unit is not None and name_match(deped_barangay, [unit])[1] is not None


LEVELS = ("city or municipality", "barangay")
outcome = {lvl: collections.Counter() for lvl in LEVELS}
tiers = {lvl: collections.Counter() for lvl in LEVELS}
b_matched = {lvl: 0 for lvl in LEVELS}
b_method = {lvl: collections.Counter() for lvl in LEVELS}
disagree_by_province = {lvl: collections.Counter() for lvl in LEVELS}
unexplained = {}  # school_id -> True when DepEd's barangay name matches the code's barangay
out_rows = []

for school_id, region, province, municipality, barangay in schools:
    name_loc = loc_result[(province, municipality)][1]
    name_bgy = bgy_result[(province, municipality, barangay)][1]
    names = {
        "city or municipality": (loc_result[(province, municipality)][0], city_or_municipality(name_loc) if name_loc else None),
        "barangay": (bgy_result[(province, municipality, barangay)][0], name_bgy),
    }
    (mun_tier, mun_unit), (bgy_tier, bgy_unit) = emisd.get(school_id, (("not in workbook", None), ("not in workbook", None)))
    codes = {
        "city or municipality": (mun_tier, city_or_municipality(mun_unit) if mun_unit else None),
        "barangay": (bgy_tier, bgy_unit),
    }
    row = {"school_id": school_id, "deped_region": region, "deped_province": province,
           "deped_municipality": municipality, "deped_barangay": barangay}
    keep = False
    bgy_supports_code = same_barangay_name(barangay, bgy_unit)
    for lvl in LEVELS:
        (c_tier, c_unit), (n_tier, n_unit) = codes[lvl], names[lvl]
        tiers[lvl][c_tier] += 1
        if c_unit and n_unit:
            result = "agree" if c_unit.id == n_unit.id else "disagree"
        elif c_unit:
            result = "code only"
        elif n_unit:
            result = "name only"
        else:
            result = "neither"
        if result == "disagree":
            if school_id in sga:
                result = "disagree: Special Geographic Area"
            elif "MAKATI" in (municipality or "").upper() and in_taguig(c_unit) and bgy_supports_code:
                result = "disagree: Embo (Makati to Taguig)"
            else:
                disagree_by_province[lvl][province] += 1
                unexplained[school_id] = bgy_supports_code
        outcome[lvl][result] += 1
        # Option B: the EMISD code first, the name match as fallback.
        if c_unit:
            b_matched[lvl] += 1
            b_method[lvl]["code, Sulu region" if c_tier == "code, Sulu region" else "code"] += 1
        elif n_unit:
            b_matched[lvl] += 1
            b_method[lvl][f"name: {n_tier}"] += 1
        key = "mun" if lvl == "city or municipality" else "bgy"
        row |= {f"{key}_result": result, f"{key}_code_tier": c_tier, f"{key}_code": c_unit.id if c_unit else "",
                f"{key}_code_name": c_unit.name if c_unit else "", f"{key}_name_tier": n_tier,
                f"{key}_name_code": n_unit.id if n_unit else "", f"{key}_name_name": n_unit.name if n_unit else ""}
        keep = keep or result != "agree"
    if keep:
        out_rows.append(row)

total = len(schools)
show("EP-1", f"schools compared: {total:,} (SY 2023-24, PSO excluded); in the EMISD workbook: "
     f"{pct(sum(1 for s in schools if s[0] in emisd), total)}")
for i, lvl in enumerate(LEVELS):
    show(f"EP-{2 + i}", f"{lvl}, EMISD code: {dict(tiers[lvl].most_common())}")
for i, lvl in enumerate(LEVELS):
    show(f"EP-{4 + i}", f"{lvl}, code vs name: " + "; ".join(f"{k} {pct(v, total)}" for k, v in outcome[lvl].most_common()))
for i, lvl in enumerate(LEVELS):
    show(f"EP-{6 + i}", f"{lvl}, unexplained disagreements by DepEd province (top 10): "
         f"{dict(disagree_by_province[lvl].most_common(10))}")
for i, lvl in enumerate(LEVELS):
    show(f"EP-{8 + i}", f"{lvl}, Option B (code first, name fallback): matched {pct(b_matched[lvl], total)}; "
         f"by method {dict(b_method[lvl].most_common())}")
name_only_full = sum(1 for s in schools if bgy_result[(s[2], s[3], s[4])][1] is not None)
show("EP-10", f"barangay coverage, name match alone {pct(name_only_full, total)} vs Option B {pct(b_matched['barangay'], total)}")

# %% Write the schools that do not agree at both levels
OUT.parent.mkdir(parents=True, exist_ok=True)
with OUT.open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=list(out_rows[0]) if out_rows else ["school_id"])
    writer.writeheader()
    writer.writerows(out_rows)
show("EP-11", f"wrote {OUT}: {len(out_rows):,} schools that do not agree at both levels")


# %% Part 2: the proposed #91 match rule (cross_source_deped_school_psgc_rule.py)
rule = Rule(RULES, sga, city_or_municipality, barangay_candidates, same_barangay_name)
override_places = collections.Counter()  # (level, province, municipality, barangay) -> schools
override_differ = collections.Counter()  # of them, schools whose code and name match differ at that level

status = {lvl: collections.Counter() for lvl in ("city_mun", "bgy")}
method = {lvl: collections.Counter() for lvl in ("city_mun", "bgy")}
detail = {lvl: collections.Counter() for lvl in ("city_mun", "bgy")}
map_rows = []
for school in schools:
    school_id, region, province, municipality, barangay = school
    (mun_tier, mun_unit), (bgy_tier, bgy_unit) = emisd.get(school_id, (("not in workbook", None), ("not in workbook", None)))
    n_loc_tier, n_loc = loc_result[(province, municipality)]
    n_bgy_tier, n_bgy = bgy_result[(province, municipality, barangay)]
    city = rule.decide_city(school, mun_unit, mun_tier, n_loc, n_loc_tier, bgy_unit)
    bgy = rule.decide_barangay(school, city, bgy_unit, bgy_tier, n_bgy, n_bgy_tier)
    for key in rule.overrides:
        if key[1:] == (province, municipality, barangay):
            c, n = ((mun_unit and city_or_municipality(mun_unit)), (n_loc and city_or_municipality(n_loc))) \
                if key[0] == "city_mun" else (bgy_unit, n_bgy)
            override_places[key] += 1
            override_differ[key] += bool(c and n and c.id != n.id)
    for lvl, (st, unit, meth, why) in (("city_mun", city), ("bgy", bgy)):
        status[lvl][st] += 1
        method[lvl][meth or "-"] += 1
        detail[lvl][(st, why)] += 1
        map_rows.append({
            "source_id": "deped_enrollment", "source_row_ref": f"{school_id}|2023-24", "school_id": school_id,
            "deped_region": region, "deped_province": province, "deped_municipality": municipality, "deped_barangay": barangay,
            "source_reference_date": "SY 2023-24", "psgc_version": RULES["psgc_version"],
            "geographic_level": lvl, "psgc_code": unit.id if unit else "", "psgc_name": unit.name if unit else "",
            "match_status": st, "match_method": meth or "", "match_detail": why,
        })

for i, lvl in enumerate(("city_mun", "bgy")):
    show(f"EP-{12 + i}", f"{lvl}, proposed rule: " + "; ".join(f"{k} {pct(v, total)}" for k, v in status[lvl].most_common())
         + f"; by method {dict(method[lvl].most_common())}")
for i, lvl in enumerate(("city_mun", "bgy")):
    show(f"EP-{14 + i}", f"{lvl}, not matched, by reason: "
         + str({f"{st}: {why}": n for (st, why), n in detail[lvl].most_common() if st != "matched"}))
MAP_OUT.parent.mkdir(parents=True, exist_ok=True)
with MAP_OUT.open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=list(map_rows[0]))
    writer.writeheader()
    writer.writerows(map_rows)
show("EP-16", f"reviewed overrides applied: {dict(rule.override_hits)}; wrote {MAP_OUT}: {len(map_rows):,} rows (school x level)")
supported = sum(unexplained.values())
show("EP-17", f"schools with an unexplained code-vs-name disagreement at either level (EP-6, EP-7): {len(unexplained):,}; "
     f"DepEd barangay name matches the code's barangay (the place changed, code right) {supported:,}; "
     f"does not {len(unexplained) - supported:,}")
for key, n in override_places.items():
    show("EP-18", f"override {' / '.join(key)}: {n:,} schools; code and name match differ for {override_differ[key]:,} "
         f"(listed in {OUT.name}, EP-11)")
