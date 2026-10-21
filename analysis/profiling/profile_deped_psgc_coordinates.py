# Profiles deped_psgc_coordinates: the SY 2023-2024 school-level enrollment workbook with PSGC codes,
# longitude, and latitude, public schools only. Each check prints under the finding ID used in
# docs/data/source-inventory/deped_psgc_coordinates/profile.md.
#
#   RAW_DATA_DIR=~/Projects/reached-hq/raw-data python analysis/profiling/profile_deped_psgc_coordinates.py
#
# RAW_DATA_DIR must contain deped/original/ with FILE. The row-level counts are the Bronze contract's own checks
# (src/ingestion/xlsx_report.prepare_delivery), so the profile and the contract cannot count differently.
# The xlsx reader is shared with the other profiling scripts (src/profiling/xlsx.py, D-007). Raw files are
# read, never modified, and only counts are printed. Runs locally; no Databricks compute.

import hashlib
import math
import os
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from src.ingestion.contract import load_source_config  # noqa: E402
from src.ingestion.xlsx_report import prepare_delivery  # noqa: E402
from src.profiling.xlsx import read_sheet  # noqa: E402

raw_dir = os.environ.get("RAW_DATA_DIR")
if not raw_dir:
    sys.exit("Set RAW_DATA_DIR to the folder that contains deped/original/.")
ORIGINAL = Path(raw_dir).expanduser() / "deped" / "original"
FILE = "SY 2023-2024 School Level Data on Enrollment with PSGC Longitude & Latitude (Public only).xlsx"
SHA256 = "edf7ba68cb768d658226a316754d636bec1d792b290692b14dd0cdd6e62fc8a1"
SCHOOL_ID, SECTOR, CITY, LON, LAT = 4, 11, 22, 29, 30  # sheet columns D, K, V, AC, AD
# The Philippine box used for coordinates across the project (config/mappings, Silver coordinate flags).
BOX = {"longitude_min": 116, "longitude_max": 127, "latitude_min": 4, "latitude_max": 21.5}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def schools(path):
    """{school_id: (Excel row, 88 cells as text)} for rows below the header that have a school ID."""
    out = {}
    for r, cells in read_sheet(str(path), "DB"):
        if r > 8 and cells.get(SCHOOL_ID):
            out.setdefault(str(cells[SCHOOL_ID]), (r, [str(cells.get(c, "")) for c in range(1, 89)]))
    return out


def in_box(lon, lat):
    return (lon is not None and lat is not None and BOX["longitude_min"] <= lon <= BOX["longitude_max"]
            and BOX["latitude_min"] <= lat <= BOX["latitude_max"])


def distance_bands(rows):
    """Distance of each school from the median point of its own city or municipality code (O-6)."""
    located = [(v[CITY - 1], number(v[LON - 1]), number(v[LAT - 1])) for _, v in rows]
    located = [p for p in located if in_box(p[1], p[2]) and p[0] not in ("", "#N/A")]
    by_city = defaultdict(list)
    for city, lon, lat in located:
        by_city[city].append((lon, lat))
    centre = {c: (statistics.median(p[0] for p in v), statistics.median(p[1] for p in v)) for c, v in by_city.items()}
    bands = Counter()
    for city, lon, lat in located:
        clon, clat = centre[city]
        km = 6371 * math.hypot(math.radians(lon - clon) * math.cos(math.radians((lat + clat) / 2)), math.radians(lat - clat))
        bands["< 10 km" if km < 10 else "10-25 km" if km < 25 else "25-50 km" if km < 50 else "50-100 km" if km < 100
              else "> 100 km"] += 1
    return len(located), [(b, bands[b]) for b in ("< 10 km", "10-25 km", "25-50 km", "50-100 km", "> 100 km")]


path = ORIGINAL / FILE
if sha256(path) != SHA256:
    sys.exit(f"{FILE}: SHA-256 differs from the source card; profile the new file before trusting these findings.")
config, entry = load_source_config(REPO, "deped_psgc_coordinates")
prepared = prepare_delivery(config, entry, path)   # refuses a changed header, title, or school year
units = schools(path)

print("== O-1 shape and scope")
kinds = Counter(prepared.row_kinds.values())
print(f"rows below the header {len(prepared.rows):,}; by kind {dict(kinds)}; schema {prepared.schema_version}")
print(f"title A6: {config['deliveries'][0]['title_cells']['A6']!r}")
print(f"sector {sorted(Counter(v[SECTOR - 1] for _, v in units.values()).items())}; distinct school_id {len(units):,}")
print("== Contract checks (O-1 to O-5): name, actual")
for check in prepared.checks:
    print(f"  {check.status:<4} {check.check_name:<36} {check.actual}")

print("== O-4 coordinates")
pairs = [(number(v[LON - 1]), number(v[LAT - 1])) for _, v in units.values()]
numeric = [p for p in pairs if None not in p]
print(f"numeric pairs {len(numeric):,}; inside the box {sum(in_box(*p) for p in numeric):,}; "
      f"(0, 0) {sum(p == (0, 0) for p in numeric)}; #N/A {sum(v[LON - 1] == '#N/A' for _, v in units.values())}")

print("== O-6 distance from the school's own city or municipality (median point)")
print(distance_bands(units.values()))
