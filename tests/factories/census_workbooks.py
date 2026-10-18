"""Made-up PSA school-age population workbooks (format xlsx_census) for tests.

Builds workbooks shaped like the two PSA census workbooks as profiled
(psa_school_age_population profile.md O-1): two sheets, `<year> Total Pop` and
`<year> Household Pop`, each with a title in row 1, the bands in row 2 and ages
5-24 in row 3. 2020 is wide (one row per place, Both Sexes, Male and Female
bands of 20 ages each); 2024 is long (a place row with no values, then Total,
Male and Female rows). Places and counts are invented; no PSA record is copied.
Written with the standard library and fixed zip timestamps, so the same
arguments always give the same SHA-256.

The default rows carry the publisher's quirks the contract flags: a footnote
marker in 2024 labels, a bracketed name, the misspelled 2020 source line, and a
2024 household title naming only City/Municipality.
"""

import copy
import hashlib
import json
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from factories.deped_deliveries import REPO_ROOT, fake_repo, registry_entry, write_config  # noqa: F401 (re-exported)
from factories.psa_workbooks import FIXED_TIME, _cell
from src.profiling.xlsx import column_letter

SOURCE = "psa_school_age_population"
AGES = list(range(5, 25))
CONCEPTS = ("Total Pop", "Household Pop")
PLACES = {
    "2020": ["PHILIPPINES", "TEST REGION (TR)", "CITY OF TESTVILLE (Capital)", "SAN TEST"],
    "2024": ["PHILIPPINES a/", "TEST REGION - TR", "CITY OF TESTVILLE 1/", "SAN TEST"],
}
TITLES = {
    ("2020", "Total Pop"): "Total Population by Single-Year Age, Sex, Region, Province, City/Municipality and Barangay : Test, 2020",
    ("2020", "Household Pop"): "Household Population by Single-Year Age, Sex, Region, Province, City/Municipality and Barangay : Test, 2020",
    ("2024", "Total Pop"): "Total Population by Single Year Age, Sex, Region, Province/Highly Urbanized City, and City/Municipality: Test, 2024",
    ("2024", "Household Pop"): "Household Population by Single Year Age, Sex, and City/Municipality: Test, 2024",
}
SOURCE_LINE = {
    "2020": "Source: Philippine Stataistics Authority, made up for tests",
    "2024": "Source: Philippine Statistics Authority, made up for tests",
}
NOTES_2024 = ["Notes:", "a/ Made-up note a.", "1/ Made-up note one."]


def workbook_name(year):
    return f"{year} School-Age Population by Single Year Age, Sex, and City Municipality.xlsx"


def real_config():
    return json.loads((REPO_ROOT / "config" / "ingestion" / f"{SOURCE}.json").read_text(encoding="utf-8"))


# The known issues' counts on the made-up workbooks. A sheet's counts join the contract when its
# delivery is approved, as the contract only accepts profiled counts for approved sheets.
FIXTURE_PROFILED = {
    "place_label_footnote_marker": {"2024 Total Pop": 2, "2024 Household Pop": 2},
    "source_line_misspelled": {"2020 Total Pop": 1, "2020 Household Pop": 1},
    "title_names_only_city_municipality": {"2024 Household Pop": 1},
}


def empty_config():
    """The real contract with no deliveries and nothing profiled yet."""
    config = copy.deepcopy(real_config())
    config["deliveries"] = []
    for issue in config["known_issues"]:
        issue["profiled"] = {}
    return config


def counts(seed, n):
    return [str(100 + seed * 7 + i) for i in range(n)]


def sheet_grid(year, concept, places=None, blank_after_header=True, extra=None):
    """{row: {column: text}} for one sheet. extra: {(row, column): text} written over everything else."""
    places = PLACES[year] if places is None else places
    grid = {1: {1: TITLES[(year, concept)]}}
    if year == "2020":
        grid[2] = {1: "Region, Province, City/Municipality and Barangay", 2: "Both Sexes", 22: "Male", 42: "Female"}
        grid[3] = {c: str(AGES[(c - 2) % 20]) for c in range(2, 62)}
        r = 5 if blank_after_header else 4
        for i, name in enumerate(places):
            grid[r] = {1: name, **{c: v for c, v in zip(range(2, 62), counts(i, 60))}}
            r += 1
        r += 1
        grid[r] = {1: SOURCE_LINE[year]}
    else:
        grid[2] = {1: "Region, Province/Highly Urbanized City, City/Municipality, and Sex", 2: "Single Year Age"}
        grid[3] = {c: str(AGES[c - 2]) for c in range(2, 22)}
        r = 5 if blank_after_header else 4
        for i, name in enumerate(places):
            grid[r] = {1: name}
            for j, sex in enumerate(("Total", "Male", "Female")):
                grid[r + 1 + j] = {1: sex, **{c: v for c, v in zip(range(2, 22), counts(i * 3 + j, 20))}}
            r += 4
        r += 1
        for line in NOTES_2024 if concept == "Total Pop" else NOTES_2024[:1] + NOTES_2024[2:]:
            grid[r] = {1: line}
            r += 1
        grid[r] = {1: SOURCE_LINE[year]}
    for (row, col), text in (extra or {}).items():
        if text is None:
            grid.get(row, {}).pop(col, None)
        else:
            grid.setdefault(row, {})[col] = text
    return grid


def workbook_parts(year, sheets=None, grids=None):
    """The workbook's XML parts. sheets: names in order; grids: {sheet name: grid} replacing the default."""
    names = sheets or [f"{year} {c}" for c in CONCEPTS]
    grids = grids or {}
    strings, sheet_xml = [], []
    for name in names:
        concept = name.split(" ", 1)[1] if name.split(" ", 1)[1] in CONCEPTS else CONCEPTS[0]
        grid = grids.get(name) or sheet_grid(year, concept, blank_after_header=concept == "Total Pop")
        rows = []
        for row in range(1, max(grid) + 1):
            cells = "".join(_cell(f"{column_letter(c)}{row}", t, strings) for c, t in sorted(grid.get(row, {}).items()))
            rows.append(f'<row r="{row}">{cells}</row>')
        width = max((c for cells in grid.values() for c in cells), default=1)
        sheet_xml.append('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                         '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                         f'<dimension ref="A1:{column_letter(width)}{max(grid)}"/><sheetData>' + "".join(rows)
                         + "</sheetData></worksheet>")
    shared = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              f'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="{len(strings)}" '
              f'uniqueCount="{len(strings)}">' + "".join(f"<si><t>{escape(s)}</t></si>" for s in strings) + "</sst>")
    workbook = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                + "".join(f'<sheet name="{escape(n)}" sheetId="{i}" r:id="rId{i}"/>' for i, n in enumerate(names, 1))
                + "</sheets></workbook>")
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                      f'Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(names) + 1))
            + f'<Relationship Id="rId{len(names) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/>'
            + "</Relationships>")
    content_types = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                     '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                     '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                     '<Default Extension="xml" ContentType="application/xml"/>'
                     '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                     + "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                               for i in range(1, len(names) + 1))
                     + '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
                     "</Types>")
    root_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                 '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                 "</Relationships>")
    return {
        "[Content_Types].xml": content_types,
        "_rels/.rels": root_rels,
        "xl/workbook.xml": workbook,
        "xl/_rels/workbook.xml.rels": rels,
        "xl/sharedStrings.xml": shared,
        **{f"xl/worksheets/sheet{i}.xml": xml for i, xml in enumerate(sheet_xml, 1)},
    }


def write_workbook(folder, year, name=None, **kwargs):
    path = Path(folder) / (name or workbook_name(year))
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for part, text in workbook_parts(year, **kwargs).items():
            info = zipfile.ZipInfo(part, FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, text.encode("utf-8"))
    return path


def default_sheet_rows(year, concept):
    return max(sheet_grid(year, concept, blank_after_header=concept == "Total Pop"))


def approve(config, path, year, delivery_version=1, supersedes=None, place_rows=None, sheet_rows=None, **overrides):
    """Add an approved-delivery entry for a fixture workbook, as a reviewer would after profiling it."""
    entry = {
        "logical_dataset": f"school_age_population_{year}",
        "census_year": year,
        "delivery_version": delivery_version,
        "supersedes": supersedes,
        "workbook": Path(path).name,
        "workbook_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        "schema_version": "v1" if year == "2020" else "v2",
        "sheets": [{"sheet": f"{year} {c}",
                    "place_rows": len(PLACES[year]) if place_rows is None else place_rows,
                    "sheet_rows": default_sheet_rows(year, c) if sheet_rows is None else sheet_rows.get(c)}
                   for c in CONCEPTS],
        "retrieved_at_utc": "2026-10-15T02:07:00Z",
    }
    entry.update(overrides)
    config["deliveries"].append(entry)
    sheets = {s["sheet"] for s in entry["sheets"]}
    for issue in config["known_issues"]:
        issue["profiled"].update({k: n for k, n in FIXTURE_PROFILED.get(issue["name"], {}).items() if k in sheets})
    return entry
