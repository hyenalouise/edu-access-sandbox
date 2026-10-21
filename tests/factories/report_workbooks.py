"""Made-up DepEd EMISD workbooks (format xlsx_report) for tests.

Builds xlsx files shaped like the publisher's: one sheet `DB`, five title rows,
the notes above columns R and AC in row 6, a sex row 7, the header in row 8 with
its line breaks, and the data from row 9. Schools, codes and names are invented;
no row of the real workbook is copied. The rows hold one of each characteristic
the profile found: codes stored as numbers that lost their leading zero, `#N/A`
error cells, `1St`, `-`, a repeated school, a row with no school ID, a blank row,
a 7-digit ID, and mojibake. Zip entries get a fixed timestamp, so the same
arguments always give the same SHA-256.
"""

import copy
import hashlib
import json
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from factories.psgc_workbooks import NS, REL_NS, FIXED_TIME, _cell, _Strings
from src.profiling.xlsx import column_letter

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE = "deped_enrollment_psgc"
WIDTH = 88
NA = ("error", "#N/A")


def real_config():
    return json.loads((REPO_ROOT / "config" / "ingestion" / f"{SOURCE}.json").read_text(encoding="utf-8"))


def registry_entry():
    registry = json.loads((REPO_ROOT / "config" / "sources.json").read_text(encoding="utf-8"))
    return next(s for s in registry["sources"] if s["source_id"] == SOURCE)


def headers(schema_version="v1"):
    return list(real_config()["schema_versions"][schema_version]["source_headers"])


def workbook_name(school_year="2023-24"):
    start = int(school_year[:4])
    return f"SY {start}-{start + 1} School Level Data on Enrollment with PSGC, Longitude and Latitude.xlsx"


def titles(school_year="2023-24"):
    start = int(school_year[:4])
    return {
        "A1": "MADE-UP SCHOOL LEVEL DATA FOR TESTS",
        "A2": f"SY {start}-{start + 1}",
        "A3": "Made up, as of a test date",
        "A4": "PSGC CODE IS MADE UP",
        "A5": "INCOME CLASS IS MADE UP",
        "R6": "PSGC CODE IS MADE UP",
        "AC6": "Longitude & Latitude are made up",
    }


def school(school_id, codes=(100000000, 102800000, 102802000, 102802013), lon=120.5, lat=16.25,
           income=("2nd", "2nd Class Municipality"), urban_rural="R", urp="Partially Urban", name="Paaralang Pagsubok",
           barangay="PAGSUBOK", learners=1):
    """One school row of 88 cells. Codes and coordinates are numbers unless given as text or an error cell."""
    reg, prv, mun, bgy = codes
    row = ["Region I", "Division Pagsubok", "District I", school_id, name, "Purok 1", "LALAWIGAN", "BAYAN",
           "1st District", barangay, "Public", "DepED Managed", "School with no Annexes", "Kinder & Grade 1-6",
           "No", urp, "Purely ES", reg, "Region I (Made Up)", prv, "Lalawigan", mun, "Bayan", bgy, "Pagsubok",
           urban_rural, income[0], income[1], lon, lat]
    return row + [learners] + [0] * (WIDTH - 31)


def default_rows():
    """{Excel row: cells}. Row 14 is absent (blank), as rows 60177-60180 are in the real sheet."""
    repeated = school(100003, codes=(200000000, 203100000, 203101000, 203101001))
    return {
        9: school(100001),
        10: school(100002, codes=(1300000000, 1380100000, 1380100000, 1380100001), lon=NA, lat=NA,
                  income=("1St", "1St Class Municipality"), urban_rural="-", urp="Urban"),
        11: repeated,
        12: copy.deepcopy(repeated),
        13: [""] * 17 + [NA] * 13,                      # no school ID: only #N/A, as row 60176
        15: school(1000004, codes=("", "", "", ""), lon="", lat="", income=("", ""), urban_rural="", urp="",
                   name="Paaralang ALMEÃ‘ANA", learners=0),   # appended after a gap, mojibake as published
    }


# What default_rows() holds, for the fixture contract (the real one carries the real workbook's counts).
FIXTURE_COUNTS = {"row_count": 7, "unit_rows": 5, "blank_rows": 1, "no_identifier_rows": 1, "last_row": 15}
FIXTURE_PROFILED = {"identifier_format": 1, "identifier_duplicates": 1, "duplicate_rows": 1, "error_cells": 15,
                    "mojibake_cells": 1}
FIXTURE_QUALITY = {
    "psgc_region_9_digits": 3, "psgc_barangay_9_digits": 3, "psgc_city_municipality_na": 0, "psgc_barangay_na": 0,
    "psgc_barangay_blank": 1, "longitude_na": 1, "longitude_blank": 1, "longitude_zero": 0, "urp_blank": 1,
    "barangay_blank": 0, "income_class_capital_st": 1, "urban_rural_dash": 1,
}


def sheet_xml(cells_by_row, strings):
    body = []
    for r in sorted(cells_by_row):
        cells = "".join(_cell(f"{column_letter(c)}{r}", v, strings) for c, v in enumerate(cells_by_row[r], start=1))
        body.append(f'<row r="{r}">{cells}</row>')
    return f'<worksheet xmlns="{NS}"><sheetData>{"".join(body)}</sheetData></worksheet>'


def make_workbook(folder, school_year="2023-24", rows=None, header=None, title=None, sheets=None, name=None,
                  extra_parts=None):
    """Write an EMISD-shaped workbook into `folder` and return its path.

    rows: {Excel row from 9: [cells]}; title: {cell: text}, merged over titles(school_year).
    """
    strings = _Strings()
    rows = default_rows() if rows is None else rows
    header = headers() if header is None else header
    cells = {}
    for ref, text in {**titles(school_year), **(title or {})}.items():
        r, c = int(ref.lstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ")), ref.rstrip("0123456789")
        column = sum((ord(ch) - 64) * 26 ** i for i, ch in enumerate(reversed(c)))
        cells.setdefault(r, [""] * WIDTH)[column - 1] = text
    cells[7] = [""] * 30 + ["Male", "Female"] * 29
    cells[8] = header
    cells.update(rows)
    names = ["DB"] if sheets is None else sheets
    parts = {}
    for i, sheet in enumerate(names, start=1):
        parts[f"xl/worksheets/sheet{i}.xml"] = sheet_xml(cells if sheet == "DB" else {1: ["other"]}, strings)
    sheet_tags = "".join(f'<sheet name="{escape(n)}" sheetId="{i}" r:id="rId{i}"/>' for i, n in enumerate(names, start=1))
    rel_tags = "".join(f'<Relationship Id="rId{i}" Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(names) + 1))
    parts["[Content_Types].xml"] = '<?xml version="1.0" encoding="UTF-8"?><Types/>'
    parts["xl/workbook.xml"] = f'<workbook xmlns="{NS}" xmlns:r="{REL_NS}"><sheets>{sheet_tags}</sheets></workbook>'
    parts["xl/_rels/workbook.xml.rels"] = f"<Relationships>{rel_tags}</Relationships>"
    parts["xl/sharedStrings.xml"] = strings.xml()
    parts = {k: v.encode("utf-8") for k, v in parts.items()}
    parts.update(extra_parts or {})

    path = Path(folder) / (name or workbook_name(school_year))
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for member, data in parts.items():
            info = zipfile.ZipInfo(member, FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, data)
    return path


def approve(config, path, school_year="2023-24", delivery_version=1, supersedes=None, title=None, **counts):
    """Add an approved-delivery entry for a fixture workbook, as a reviewer would."""
    n = {**FIXTURE_COUNTS, **counts}
    entry = {
        "school_year": school_year,
        "delivery_version": delivery_version,
        "supersedes": supersedes,
        "workbook": Path(path).name,
        "workbook_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        "sheet": "DB",
        "range": f"A1:{column_letter(WIDTH)}{n['last_row']}",
        "schema_version": "v1",
        "title_cells": {**titles(school_year), **(title or {})},
        "row_count": n["row_count"],
        "unit_rows": n["unit_rows"],
        "blank_rows": n["blank_rows"],
        "no_identifier_rows": n["no_identifier_rows"],
        "retrieved_at_utc": "2026-01-01T00:00Z",
    }
    config["deliveries"].append(entry)
    return entry


# The public-only workbook (deped_psgc_coordinates): a separate file, same layout and schema v1, with a sector note in A6.
COORDINATES = "deped_psgc_coordinates"
PUBLIC_ONLY = "SY 2023-2024 School Level Data on Enrollment with PSGC Longitude & Latitude (Public only).xlsx"
PUBLIC_ONLY_TITLE = {"A6": "SECTOR: PUBLIC ONLY"}


def coordinates_config():
    """The real public-only contract with no approved deliveries and the fixture's profiled counts."""
    config = json.loads((REPO_ROOT / "config" / "ingestion" / f"{COORDINATES}.json").read_text(encoding="utf-8"))
    config["deliveries"] = []
    config["profiled"] = dict(FIXTURE_PROFILED)
    for check in config["quality_checks"]:
        check["profiled"] = FIXTURE_QUALITY.get(check["name"], 0)
    return config


def empty_config():
    """The real contract with no approved deliveries and the fixture's profiled counts."""
    config = copy.deepcopy(real_config())
    config["deliveries"] = []
    config["profiled"] = dict(FIXTURE_PROFILED)
    for check in config["quality_checks"]:
        check["profiled"] = FIXTURE_QUALITY[check["name"]]
    return config
