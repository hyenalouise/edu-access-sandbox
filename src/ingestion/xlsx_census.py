"""Delivery format `xlsx_census`: one workbook per census, delivered as is, with one
sheet per population concept, each laid out as a report table of places by sex
and single-year age (PSA school-age population, 2020 and 2024).

`prepare_delivery` goes from a workbook on disk to rows ready for Bronze, or
refuses it saying why. It never changes the file and never writes to disk. It
has the same shape as xlsx_table.prepare_delivery, so pipeline.py runs both alike.

| | PSA Poverty Stat (workbook.py) | PSA school-age population (here) |
|---|---|---|
| Sheets loaded | one | every sheet the contract names: `<year> Total Pop`, `<year> Household Pop` |
| Row identity | (source_sha256, source_row_number) | (source_sha256, source_sheet, source_row_number): two sheets share row numbers |
| Period | estimate years, from the header | the census year, from the file name, the sheet names and the approval |
| Header | merged, built into column names | row 2 bands and row 3 ages, checked by position against the schema's layout |
| Layout | one | one per schema version: `wide` (2020: a row per place, 60 counts) or `long` (2024: a place row with no values, then `Total` / `Male` / `Female` rows of 20 counts) |

Every row of every sheet goes to Bronze, from row 1 to the last row holding a
value, blank rows included, numbered by its Excel row. Its `source_row_kind`
comes from the layout, never from what the values mean:

| Kind | Row |
|---|---|
| `title` | row 1 |
| `header` | the band row and the age row (rows 2 and 3) |
| `place` | wide: a label and every count; long: a label and no counts, above the notes |
| `sex_total`, `sex_male`, `sex_female` | long: `Total`, `Male`, `Female` with every count |
| `note` | a label and no counts: in the long layout from the `Notes:` row on; in the wide layout any such row |
| `source` | a label starting `Source` and no counts |
| `blank` | no cell |
| `unclassified` | anything else; fails the batch |

Every cell is kept as the text stored in the file, as xlsx_table describes:
numbers as their stored digits, empty cells as ''. Labels keep their footnote
markers (`CITY OF MAKATI 1/`) and brackets (`(Capital)`); nothing is renamed,
reshaped, or corrected. The layout contract (sheets, bands, ages, place rows,
the 2024 blocks, whole-number counts) FAILs on anything else; the publisher's
known quirks are WARN results with their profiled count beside the actual one.
"""

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from src.ingestion import archive
from src.ingestion.errors import IngestionError
from src.ingestion.validate import FAIL, PASS, WARN, CheckResult
from src.ingestion.xlsx_table import BRONZE_NAME, SHA256, cell_text, last_row, mojibake, open_sheet, sheet_names
from src.ingestion.contract import LOGICAL_DATASET, schema_fingerprint
from src.profiling.xlsx import column_letter, column_number

# Columns the pipeline adds to every row. A delivery is one census, so the
# census year is delivery metadata; the sheet says which population concept a
# row belongs to, and with the Excel row number it points at one line of the file.
PROVENANCE_COLUMNS = (
    "source_id",
    "source_system",
    "source_url",
    "logical_dataset",
    "census_year",
    "delivery_version",
    "source_file",
    "source_sha256",
    "source_sheet",
    "source_row_number",
    "source_row_kind",
    "schema_version",
    "schema_fingerprint",
    "batch_id",
    "run_id",
    "ingested_at_utc",
    "code_revision",
)

TITLE, HEADER, PLACE, NOTE, SOURCE, BLANK, UNCLASSIFIED = (
    "title", "header", "place", "note", "source", "blank", "unclassified")
LAYOUTS = ("wide", "long")
CENSUS_YEAR = re.compile(r"^[0-9]{4}$")
WHOLE_NUMBER = re.compile(r"^[0-9]+$")
AGE = re.compile(r"^([0-9]+)(\.0+)?$")
FOOTNOTE_MARKER = re.compile(r"\s[a-z0-9]{1,2}/$")

CONFIG_FIELDS = {
    "source_id", "format", "bronze_table", "landing_dir", "workbook_pattern", "max_uncompressed_bytes",
    "sheet_suffixes", "notes_marker", "source_prefix", "schema_versions", "known_issues", "deliveries",
}
VERSION_FIELDS = {"layout", "band_row", "bands", "age_row", "ages", "columns"}
DELIVERY_FIELDS = {
    "logical_dataset", "census_year", "delivery_version", "supersedes", "workbook", "workbook_sha256",
    "schema_version", "sheets", "retrieved_at_utc",
}
SHEET_FIELDS = {"sheet", "place_rows", "sheet_rows"}


# --- Known publisher issues: counted, never corrected ---------------------------------

def _footnote_markers(sheet_rows, issue, config):
    return sum(1 for kind, values in sheet_rows if kind == PLACE and FOOTNOTE_MARKER.search(values[0]))


def _source_contains(sheet_rows, issue, config):
    return sum(1 for kind, values in sheet_rows if kind == SOURCE and issue["value"] in values[0])


def _title_lacks(sheet_rows, issue, config):
    return sum(1 for kind, values in sheet_rows if kind == TITLE and values[0] and issue["value"] not in values[0])


KNOWN_ISSUE_CHECKS = {
    "place_label_footnote_marker": _footnote_markers,
    "source_line_contains": _source_contains,
    "title_lacks": _title_lacks,
}
# Checks that compare against a text given in the contract as "value".
KNOWN_ISSUE_VALUE_CHECKS = {"source_line_contains", "title_lacks"}


def _config_error(message):
    return IngestionError("config", "invalid_config", message)


def period_from_name(config, name):
    """'2024 School-Age Population ... .xlsx' -> '2024'; None if the name does not match."""
    match = re.match(config["workbook_pattern"], name)
    return match["year"] if match else None


def sheet_names_for(config, year):
    """The sheets a workbook of that census must have, in workbook order: '<year> Total Pop', ..."""
    return [f"{year} {suffix}" for suffix in config["sheet_suffixes"].values()]


def width(version):
    return len(version["columns"])


def count_columns(version):
    """Excel columns holding counts: B onwards, to the layout's width."""
    return range(2, width(version) + 1)


# --- The contract ----------------------------------------------------------------

def validate_contract(config, registry_entry):
    """Refuse an xlsx_census contract that could load something ambiguous. Raises on the first problem.

    A delivery is one census year, so versions are counted per logical_dataset
    (1, 2, 3...), each revision naming the workbook it supersedes, and two
    datasets may not share a census year (D-018, as for psa_poverty_stat).
    """
    missing = CONFIG_FIELDS - config.keys()
    if missing:
        raise _config_error(f"missing fields {sorted(missing)}.")
    if config["source_id"] != registry_entry.get("source_id"):
        raise _config_error("source_id differs from the registry entry.")
    for name in ("source_system", "acquisition"):
        if not registry_entry.get(name):
            raise _config_error(f"registry entry for {config['source_id']} has no {name!r}; provenance would be blank.")
    try:
        pattern = re.compile(config["workbook_pattern"])
    except re.error as e:
        raise _config_error(f"invalid pattern: {e}.")
    if "year" not in pattern.groupindex:
        raise _config_error("workbook_pattern must name the group 'year' (the census year).")
    if not config["sheet_suffixes"]:
        raise _config_error("sheet_suffixes must name at least one sheet.")

    versions = config["schema_versions"]
    if not versions:
        raise _config_error("no schema versions.")
    for name, version in versions.items():
        absent = VERSION_FIELDS - version.keys()
        if absent:
            raise _config_error(f"schema {name} is missing {sorted(absent)}.")
        columns = version["columns"]
        if version["layout"] not in LAYOUTS:
            raise _config_error(f"schema {name}: layout {version['layout']!r} is not one of {list(LAYOUTS)}.")
        if len(set(columns)) != len(columns):
            raise _config_error(f"schema {name} repeats a column name.")
        bad = [c for c in columns if not BRONZE_NAME.match(c)]
        if bad:
            raise _config_error(f"schema {name}: Bronze column names must be snake_case: {bad}.")
        clash = sorted(set(columns) & set(PROVENANCE_COLUMNS))
        if clash:
            raise _config_error(f"schema {name} has publisher columns named like provenance fields: {clash}.")
        if columns[0] != "label":
            raise _config_error(f"schema {name}: column A must be 'label' (the place, sex, note or source text).")
        bands = {column_number(ref): text for ref, text in version["bands"].items()}
        if len(columns) != 1 + len(bands) * len(version["ages"]):
            raise _config_error(f"schema {name}: {len(columns)} columns, but 1 label column + {len(bands)} band(s) "
                                f"x {len(version['ages'])} ages make {1 + len(bands) * len(version['ages'])}.")
        starts = [2 + i * len(version["ages"]) for i in range(len(bands))]
        if sorted(bands) != starts:
            raise _config_error(f"schema {name}: each band must start where the previous one's ages end "
                                f"(columns {[column_letter(c) for c in starts]}).")
        if not (1 < version["band_row"] < version["age_row"]):
            raise _config_error(f"schema {name}: band_row must come after the title row and before age_row.")
        if version["layout"] == "long":
            sexes = version.get("sex_labels") or {}
            if sorted(sexes.values()) != ["sex_female", "sex_male", "sex_total"] or len(bands) != 1:
                raise _config_error(f"schema {name}: a long layout has one band and sex_labels mapping the labels "
                                    "of its Total, Male and Female rows to sex_total, sex_male and sex_female.")
    fingerprints = [schema_fingerprint(v["columns"]) for v in versions.values()]
    if len(set(fingerprints)) != len(fingerprints):
        raise _config_error("two schema versions have identical columns.")

    for issue in config["known_issues"]:
        label = f"known issue {issue.get('name')!r}"
        for key in ("name", "check", "finding", "profiled"):
            if key not in issue:
                raise _config_error(f"{label} is missing {key!r}.")
        if issue["check"] not in KNOWN_ISSUE_CHECKS:
            raise _config_error(f"{label}: check {issue['check']!r} is not one of {sorted(KNOWN_ISSUE_CHECKS)}.")
        if issue["check"] in KNOWN_ISSUE_VALUE_CHECKS and not (isinstance(issue.get("value"), str) and issue["value"]):
            raise _config_error(f"{label}: check {issue['check']!r} needs a non-empty text 'value'.")
        if not isinstance(issue["profiled"], dict) or not all(
                isinstance(n, int) and n >= 0 for n in issue["profiled"].values()):
            raise _config_error(f"{label}: profiled must map sheet names to whole-number counts.")
    if len({i["name"] for i in config["known_issues"]}) != len(config["known_issues"]):
        raise _config_error("two known issues share a name.")

    seen_sha, seen_version, by_dataset = set(), set(), {}
    for d in config["deliveries"]:
        label = f"delivery {d.get('workbook')!r}"
        missing = DELIVERY_FIELDS - d.keys()
        if missing:
            raise _config_error(f"{label} is missing {sorted(missing)}.")
        if not SHA256.match(str(d["workbook_sha256"])):
            raise _config_error(f"{label}: workbook_sha256 is not a lowercase SHA-256.")
        if not CENSUS_YEAR.match(str(d["census_year"])):
            raise _config_error(f"{label}: census_year {d['census_year']!r} is not a four-digit year as text.")
        named = period_from_name(config, d["workbook"])
        if named is None:
            raise _config_error(f"{label}: name does not match workbook_pattern, so it would not be discovered.")
        if named != d["census_year"]:
            raise _config_error(f"{label}: the file name says {named}, the delivery says {d['census_year']}.")
        if not LOGICAL_DATASET.match(str(d["logical_dataset"])):
            raise _config_error(f"{label}: logical_dataset must be snake_case.")
        if d["schema_version"] not in versions:
            raise _config_error(f"{label}: schema_version {d['schema_version']!r} is not defined.")
        sheets = d["sheets"]
        if not isinstance(sheets, list) or any(SHEET_FIELDS - s.keys() for s in sheets):
            raise _config_error(f"{label}: each sheet must give {sorted(SHEET_FIELDS)}.")
        if [s["sheet"] for s in sheets] != sheet_names_for(config, d["census_year"]):
            raise _config_error(f"{label}: sheets must be exactly {sheet_names_for(config, d['census_year'])}, in that order.")
        for s in sheets:
            if not isinstance(s["place_rows"], int) or s["place_rows"] <= 0:
                raise _config_error(f"{label}: place_rows of {s['sheet']!r} must be a positive whole number.")
            # null until a local run on the real workbook reports it; the load FAILs until then.
            if s["sheet_rows"] is not None and (not isinstance(s["sheet_rows"], int) or s["sheet_rows"] <= 0):
                raise _config_error(f"{label}: sheet_rows of {s['sheet']!r} must be a positive whole number or null.")
        if d["workbook_sha256"] in seen_sha:
            raise _config_error(f"{label}: workbook_sha256 is approved twice.")
        key = (d["logical_dataset"], d["delivery_version"])
        if key in seen_version:
            raise _config_error(f"{label}: delivery_version {d['delivery_version']} of {d['logical_dataset']} is used twice.")
        seen_sha.add(d["workbook_sha256"])
        seen_version.add(key)
        by_dataset.setdefault(d["logical_dataset"], []).append(d)

    # A profiled sheet must be named as a workbook sheet is ('<year> <suffix>'), so a misspelling cannot pass
    # and later read as a profiled count of 0. The year's delivery may not be approved yet.
    suffixes = sorted(config["sheet_suffixes"].values())
    for issue in config["known_issues"]:
        unknown = sorted(n for n in issue["profiled"]
                         if not (CENSUS_YEAR.match(n[:4]) and n[4:5] == " " and n[5:] in suffixes))
        if unknown:
            raise _config_error(f"known issue {issue['name']!r}: profiled names sheet(s) {unknown}; a sheet is "
                                f"'<census year> <suffix>' with a suffix in {suffixes}.")

    years = {}
    for dataset, deliveries in by_dataset.items():
        deliveries.sort(key=lambda d: d["delivery_version"])
        for i, d in enumerate(deliveries, start=1):
            if d["delivery_version"] != i:
                raise _config_error(f"{dataset}: delivery versions must be 1, 2, 3...; found {[x['delivery_version'] for x in deliveries]}.")
            previous = deliveries[i - 2]["workbook_sha256"] if i > 1 else None
            if d["supersedes"] != previous:
                want = f"supersedes = {previous!r}" if previous else "supersedes = null"
                raise _config_error(f"{dataset} version {i} must have {want}.")
            if d["census_year"] != deliveries[0]["census_year"]:
                raise _config_error(f"{dataset}: every version must be the same census year.")
        year = deliveries[0]["census_year"]
        if year in years:
            raise _config_error(f"logical datasets {years[year]!r} and {dataset!r} both cover {year}. A workbook that "
                                "republishes a census is the next delivery_version of its dataset, with 'supersedes' set.")
        years[year] = dataset


# --- The prepared delivery -----------------------------------------------------------

@dataclass
class PreparedCensus:
    source_id: str
    logical_dataset: str
    census_year: str
    delivery_version: int
    supersedes: str
    archive_path: str
    archive_name: str
    archive_sha256: str
    sheets: list                   # the sheets loaded, in workbook order
    schema_version: str
    schema_fingerprint: str
    header: list                   # Bronze column names, in sheet order
    rows: list                     # [((sheet, Excel row number), [text per column])]
    row_kinds: dict = field(default_factory=dict)   # {(sheet, Excel row): kind}
    checks: list = field(default_factory=list)
    school_year = None
    encoding = "utf-8"             # xlsx XML parts; any other encoding is refused by the opener

    @property
    def data_member(self):
        return self.archive_name   # the workbook is the data file

    @property
    def data_member_sha256(self):
        return self.archive_sha256

    @property
    def failed_checks(self):
        return [c for c in self.checks if c.status == FAIL]

    def kind_counts(self):
        """{(sheet, kind): rows}, so Bronze is reconciled sheet by sheet."""
        return Counter((sheet, kind) for (sheet, _), kind in self.row_kinds.items())

    def provenance(self, registry_entry):
        return {
            "source_id": self.source_id,
            "source_system": registry_entry["source_system"],
            "source_url": registry_entry["acquisition"],
            "logical_dataset": self.logical_dataset,
            "census_year": self.census_year,
            "delivery_version": self.delivery_version,
            "source_file": self.archive_name,
            "source_sha256": self.archive_sha256,
            "schema_version": self.schema_version,
            "schema_fingerprint": self.schema_fingerprint,
        }

    def row_provenance(self, key):
        return {"source_sheet": key[0], "source_row_kind": self.row_kinds[key]}


def expected_rows(delivery):
    """Every row of every approved sheet, or None while a sheet's row count is not pinned yet."""
    counts = [s["sheet_rows"] for s in delivery["sheets"]]
    return None if None in counts else sum(counts)


def identify_delivery(config, path):
    """Return (approved delivery, workbook SHA-256), or stop if the file is not approved."""
    path = Path(path)
    if not path.is_file():
        raise IngestionError("identify", "missing_archive",
                             f"{path} does not exist. Upload the approved workbook to raw storage, then run again.")
    digest = archive.sha256_file(path)
    delivery = next((d for d in config["deliveries"] if d["workbook_sha256"] == digest), None)
    if delivery:
        return delivery, digest
    same_name = [d for d in config["deliveries"] if d["workbook"] == path.name]
    if same_name:
        approved = ", ".join(f"{d['logical_dataset']} v{d['delivery_version']} {d['workbook_sha256'][:12]}" for d in same_name)
        raise IngestionError("identify", "checksum_mismatch",
                             f"{path.name} has SHA-256 {digest}, which is not approved (approved: {approved}). "
                             "If the copy is damaged, get the file again. If PSA sent a revised file, profile it and "
                             "approve it as the next delivery_version with 'supersedes' set; the earlier version is kept.")
    raise IngestionError("identify", "unregistered_delivery",
                         f"{path.name} (SHA-256 {digest}) is not an approved delivery. "
                         "Profile it, then add it to the source config in a pull request.")


def classify(values, version, in_notes, notes_marker, source_prefix):
    """The kind of one row below the header, from which cells are filled, never from what the counts say."""
    label, counts = values[0], values[1:]
    if not any(values):
        return BLANK
    if label and not any(counts):
        if label.startswith(source_prefix):
            return SOURCE
        if version["layout"] == "wide" or in_notes or label.startswith(notes_marker):
            return NOTE
        return PLACE
    if label and all(counts):
        if version["layout"] == "wide":
            return PLACE
        return version["sex_labels"].get(label, UNCLASSIFIED)
    return UNCLASSIFIED


def read_sheet_rows(config, version, sheet, name):
    """[((sheet, row), values)] and {(sheet, row): kind} for every row up to the last one holding a value."""
    rows, kinds, in_notes = [], {}, False
    cols = range(1, width(version) + 1)
    for number in range(1, last_row(sheet) + 1):
        values = [cell_text(sheet, number, c) for c in cols]
        key = (name, number)
        rows.append((key, values))
        if number == 1:
            kinds[key] = TITLE
        elif number <= version["age_row"]:
            kinds[key] = HEADER
        else:
            in_notes = in_notes or values[0].startswith(config["notes_marker"])
            kinds[key] = classify(values, version, in_notes, config["notes_marker"], config["source_prefix"])
    return rows, kinds


def prepare_delivery(config, registry_entry, path):
    delivery, digest = identify_delivery(config, path)
    path = Path(path)
    named = period_from_name(config, path.name)
    if named != delivery["census_year"]:
        raise IngestionError("period", "period_mismatch",
                             f"the file name says {named}, the approved delivery says {delivery['census_year']}.")
    expected_sheets = [s["sheet"] for s in delivery["sheets"]]
    version = config["schema_versions"][delivery["schema_version"]]

    rows, kinds, opened = [], {}, {}
    for name in expected_sheets:
        # The zip checks, no macros or DTDs, missing_sheet, and unexpected_sheet for any sheet not approved.
        sheet = workbook_open(config, path, name, expected_sheets)
        opened[name] = sheet
        sheet_rows, sheet_kinds = read_sheet_rows(config, version, sheet, name)
        rows += sheet_rows
        kinds.update(sheet_kinds)
    names = sheet_names(path)

    prepared = PreparedCensus(
        source_id=config["source_id"],
        logical_dataset=delivery["logical_dataset"],
        census_year=delivery["census_year"],
        delivery_version=delivery["delivery_version"],
        supersedes=delivery["supersedes"],
        archive_path=str(path),
        archive_name=path.name,
        archive_sha256=digest,
        sheets=expected_sheets,
        schema_version=delivery["schema_version"],
        schema_fingerprint=schema_fingerprint(version["columns"]),
        header=list(version["columns"]),
        rows=rows,
        row_kinds=kinds,
    )
    prepared.checks = check_workbook(config, delivery, version, names, opened, prepared)
    return prepared


def workbook_open(config, path, name, expected_sheets):
    return open_sheet({**config, "expected_sheets": expected_sheets}, path, name)


def _age(text):
    match = AGE.match(text)
    return int(match.group(1)) if match else None


def check_workbook(config, delivery, version, names, opened, prepared):
    checks = []

    def add(name, ok, expected, actual, warn_only=False):
        status = PASS if ok else (WARN if warn_only else FAIL)
        checks.append(CheckResult(name, status, str(expected), str(actual)))

    add("sheets_match_approved", names == prepared.sheets, prepared.sheets, names)
    bands = {column_number(ref): text for ref, text in version["bands"].items()}
    ages = list(version["ages"]) * len(bands)
    for spec in delivery["sheets"]:
        name = spec["sheet"]
        sheet = opened[name]
        rows = [(prepared.row_kinds[key], values) for key, values in prepared.rows if key[0] == name]
        found = Counter(kind for kind, _ in rows)
        prefix = f"{name}: "

        # The header, by position: the bands in the band row and ages 5-24 in the age row.
        band_cells = {c: t for c, (t, _) in sheet.cells.get(version["band_row"], {}).items() if c > 1}
        add(prefix + "band_row_matches_layout", band_cells == bands,
            {column_letter(c): t for c, t in bands.items()}, {column_letter(c): t for c, t in sorted(band_cells.items())})
        age_cells = sheet.cells.get(version["age_row"], {})
        found_ages = [_age(age_cells.get(c, ("", ""))[0]) for c in count_columns(version)]
        extra = sorted(c for c in age_cells if c > width(version))
        add(prefix + "age_row_matches_layout", found_ages == ages and not extra,
            f"ages {ages[0]}-{ages[-1]} in columns B-{column_letter(width(version))}",
            "as expected" if found_ages == ages and not extra else
            f"{found_ages}{'; cells right of the layout: ' + ','.join(column_letter(c) for c in extra) if extra else ''}")

        # Rows: every one classified, the places as approved, nothing outside the layout.
        outside = sum(1 for cells in sheet.cells.values() for c in cells if c > width(version))
        add(prefix + "no_cells_outside_layout", outside == 0, f"0 values right of column {column_letter(width(version))}", outside)
        add(prefix + "unclassified_rows", found[UNCLASSIFIED] == 0, 0, found[UNCLASSIFIED])
        add(prefix + "place_rows_match_approved", found[PLACE] == spec["place_rows"], spec["place_rows"], found[PLACE])
        pinned = spec["sheet_rows"]
        add(prefix + "sheet_rows_match_approved", pinned == len(rows),
            pinned if pinned is not None else "not pinned yet: copy the actual count to the card and the contract",
            len(rows))

        # The 2024 blocks: each place row followed by exactly one Total, Male, Female, in that order.
        if version["layout"] == "long":
            order = [k for k, _ in rows if k != BLANK]
            sexes = [version["sex_labels"][s] for s in ("Total", "Male", "Female")]
            broken, i = 0, 0
            while i < len(order):
                if order[i] == PLACE and order[i + 1:i + 4] == sexes:
                    i += 4
                    continue
                broken += order[i] == PLACE or order[i] in sexes  # a place without its block, or a stray sex row
                i += 1
            add(prefix + "place_rows_have_one_sex_block", broken == 0, 0, broken)
            for sex in sexes:
                add(prefix + f"{sex}_rows_match_place_rows", found[sex] == found[PLACE], found[PLACE], found[sex])

        # Counts: whole numbers as stored, on every data row (profile O-3).
        data = [values for kind, values in rows if kind == PLACE and version["layout"] == "wide"
                or kind.startswith("sex_")]
        bad = sum(1 for values in data for v in values[1:] if not WHOLE_NUMBER.match(v))
        add(prefix + "counts_are_whole_numbers", bad == 0, 0, bad)

        texts = [v for _, values in rows for v in values]
        add(prefix + "text_mojibake", not any(mojibake(t) for t in texts), 0, sum(1 for t in texts if mojibake(t)))
        add(prefix + "formula_cells", sheet.formulas == 0, 0, sheet.formulas, warn_only=True)
        add(prefix + "error_cells", sheet.errors == 0, 0, sheet.errors, warn_only=True)

        # Known publisher quirks: WARN with the profiled count beside the actual count, never a correction.
        for issue in config["known_issues"]:
            n = KNOWN_ISSUE_CHECKS[issue["check"]](rows, issue, config)
            profiled = issue["profiled"].get(name, 0)
            add(prefix + f"known_issue_{issue['name']}", n == 0, f"0 (profiled: {profiled}, {issue['finding']})",
                n, warn_only=True)
    return checks
