"""Delivery format `xlsx_report`: one workbook, delivered as is, whose data sheet is
laid out as a report: title rows, then the header lower down, then the data (DepEd
EMISD enrollment with PSGC and coordinates).

`prepare_delivery` goes from a workbook on disk to rows ready for Bronze, or
refuses it saying why. It never changes the file and never writes to disk. It
has the same shape as xlsx_table.prepare_delivery, so pipeline.py runs both alike.

| | PSGC workbook (xlsx_table) | EMISD workbook (here) |
|---|---|---|
| Header | row 1 | the contract's `header_row` (8), below title rows and a grade/sex band |
| Period | publication quarter, from the file name and the `Metadata` sheet | school year, from the file name and a title cell (`SY 2023-2024`) |
| Title | none | each title cell is pinned in the approved delivery, so a changed note (PSGC basis, coordinate date) is never loaded unseen |
| Rows loaded | every row from 2 | every row below the header, blank rows included |
| Row kind | none | `unit` (has an identifier), `blank`, `no_identifier` (cells but no identifier), counted against the approval |
| Identifier | must match its pattern, else FAIL | a known mismatch is a WARN at its profiled count |
| Mojibake | FAIL | a WARN at its profiled count: DepEd's published names hold `Ã‘` (deped_enrollment_psgc O-13) |

The rows above the header are not loaded: their text is checked against the
approval instead, and the header itself is the schema version. Every sheet is
opened by the shared, safe opener (workbook.open_sheet), and every cell is kept
as the text stored in the file, as xlsx_table describes: numbers as stored
digits (a PSGC code that lost its leading zero stays 9 digits), errors as their
text ('#N/A'), empty cells as ''. Nothing is padded, trimmed, typed or dropped.

Problems that make the file untrustworthy (unknown file, checksum, unsafe
workbook, missing sheet, header drift, a changed title, a period that does not
agree) raise IngestionError. Problems in the rows are check results: FAIL
blocks the batch, WARN is recorded and the rows still load exactly as received.
Results hold counts, never row values.
"""

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from src.ingestion import archive
from src.ingestion.errors import IngestionError
from src.ingestion.validate import FAIL, PASS, WARN, CheckResult
from src.ingestion.xlsx_table import (
    BRONZE_NAME, QUALITY_CHECKS as TABLE_CHECKS, SHA256, cell_kind, cell_text, last_column, last_row, match_header,
    mojibake, open_sheet, schema_fingerprint, sheet_names,
)
from src.profiling.xlsx import column_letter, column_number

# Columns the pipeline adds to every row. source_row_number is the Excel row, and
# source_row_kind says what the row is (unit, blank, no_identifier); the kind is
# read from the identifier cell and whether the row has any cell, never from values.
PROVENANCE_COLUMNS = (
    "source_id",
    "source_system",
    "source_url",
    "school_year",
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

UNIT, BLANK, NO_IDENTIFIER = "unit", "blank", "no_identifier"
KIND_FIELDS = {UNIT: "unit_rows", BLANK: "blank_rows", NO_IDENTIFIER: "no_identifier_rows"}
SCHOOL_YEAR = re.compile(r"^[0-9]{4}-[0-9]{2}$")
CELL = re.compile(r"^[A-Z]{1,3}[1-9][0-9]*$")
RANGE = re.compile(r"^A1:(?P<column>[A-Z]{1,3})(?P<row>[1-9][0-9]*)$")
QUALITY_CHECKS = {**TABLE_CHECKS, "matches": lambda v, arg: re.fullmatch(arg, v) is not None}
PROFILED_FIELDS = {"identifier_format", "identifier_duplicates", "duplicate_rows", "error_cells", "mojibake_cells"}

CONFIG_FIELDS = {
    "source_id", "format", "bronze_table", "landing_dir", "workbook_pattern", "data_sheet", "expected_sheets",
    "max_uncompressed_bytes", "header_row", "period_cell", "identifier_column", "identifier_pattern",
    "required_columns", "profiled", "schema_versions", "quality_checks", "deliveries",
}
DELIVERY_FIELDS = {
    "school_year", "delivery_version", "supersedes", "workbook", "workbook_sha256", "sheet", "range",
    "schema_version", "title_cells", "row_count", "unit_rows", "blank_rows", "no_identifier_rows",
    "retrieved_at_utc",
}


def _config_error(message):
    return IngestionError("config", "invalid_config", message)


def _cell_position(ref):
    m = re.match(r"([A-Z]+)([0-9]+)$", ref)
    return int(m.group(2)), column_number(m.group(1))


# --- The period ------------------------------------------------------------------

def school_year_of(match):
    """'2023', '2024' -> '2023-24'; None unless the second year follows the first."""
    start, end = int(match["start"]), int(match["end"])
    return f"{start}-{str(end)[-2:]}" if end == start + 1 else None


def period_from_name(config, name):
    """'SY 2023-2024 School Level Data ... .xlsx' -> '2023-24'; None if the name does not match."""
    match = re.match(config["workbook_pattern"], name)
    return school_year_of(match) if match else None


# --- The contract ----------------------------------------------------------------

def validate_contract(config, registry_entry):
    """Refuse an xlsx_report contract that could load something ambiguous. Raises on the first problem."""
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
        re.compile(config["identifier_pattern"])
        period_pattern = re.compile(config["period_cell"].get("pattern", ""))
    except re.error as e:
        raise _config_error(f"invalid pattern: {e}.")
    for label, groups in (("workbook_pattern", pattern.groupindex), ("period_cell pattern", period_pattern.groupindex)):
        if not {"start", "end"} <= set(groups):
            raise _config_error(f"{label} must name the groups 'start' and 'end' (the two years of the school year).")
    if not CELL.match(str(config["period_cell"].get("cell", ""))):
        raise _config_error("period_cell must name a cell, like 'A2'.")
    if config["data_sheet"] not in config["expected_sheets"]:
        raise _config_error(f"data_sheet {config['data_sheet']!r} is not in expected_sheets.")
    header_row = config["header_row"]
    if not isinstance(header_row, int) or header_row < 1:
        raise _config_error("header_row must be a positive whole number.")
    if _cell_position(config["period_cell"]["cell"])[0] >= header_row:
        raise _config_error("period_cell must be above header_row.")
    if set(config["profiled"]) != PROFILED_FIELDS or not all(
            isinstance(v, int) and v >= 0 for v in config["profiled"].values()):
        raise _config_error(f"profiled must give a whole-number count for exactly {sorted(PROFILED_FIELDS)}.")

    versions = config["schema_versions"]
    if not versions:
        raise _config_error("no schema versions.")
    for name, version in versions.items():
        columns, headers = version.get("columns") or [], version.get("source_headers")
        if not columns:
            raise _config_error(f"schema {name} has no columns.")
        if not isinstance(headers, list) or len(headers) != len(columns):
            raise _config_error(f"schema {name}: source_headers must list the exact header cell of every column.")
        if len(set(columns)) != len(columns):
            raise _config_error(f"schema {name} repeats a column name.")
        bad = [c for c in columns if not BRONZE_NAME.match(c)]
        if bad:
            raise _config_error(f"schema {name}: Bronze column names must be snake_case: {bad}.")
        clash = sorted(set(columns) & set(PROVENANCE_COLUMNS))
        if clash:
            raise _config_error(f"schema {name} has publisher columns named like provenance fields: {clash}.")
        absent = [c for c in config["required_columns"] + [config["identifier_column"]] if c not in columns]
        if absent:
            raise _config_error(f"schema {name} lacks required column(s) {absent}.")
    fingerprints = [schema_fingerprint(v["source_headers"]) for v in versions.values()]
    if len(set(fingerprints)) != len(fingerprints):
        raise _config_error("two schema versions have identical source headers.")

    known_columns = {c for v in versions.values() for c in v["columns"]}
    for check in config["quality_checks"]:
        label = f"quality check {check.get('name')!r}"
        for key in ("name", "check", "column", "profiled", "finding"):
            if key not in check:
                raise _config_error(f"{label} is missing {key!r}.")
        if check["check"] not in QUALITY_CHECKS:
            raise _config_error(f"{label}: check {check['check']!r} is not one of {sorted(QUALITY_CHECKS)}.")
        if check["column"] not in known_columns:
            raise _config_error(f"{label} names unknown column {check['column']!r}.")
    if len({c["name"] for c in config["quality_checks"]}) != len(config["quality_checks"]):
        raise _config_error("two quality checks share a name.")

    seen_sha, seen_version, by_year = set(), set(), {}
    for d in config["deliveries"]:
        label = f"delivery {d.get('workbook')!r}"
        missing = DELIVERY_FIELDS - d.keys()
        if missing:
            raise _config_error(f"{label} is missing {sorted(missing)}.")
        if not SHA256.match(str(d["workbook_sha256"])):
            raise _config_error(f"{label}: workbook_sha256 is not a lowercase SHA-256.")
        if not SCHOOL_YEAR.match(str(d["school_year"])):
            raise _config_error(f"{label}: school_year {d['school_year']!r} is not like '2023-24'.")
        named = period_from_name(config, d["workbook"])
        if named is None:
            raise _config_error(f"{label}: name does not match workbook_pattern, so it would not be discovered.")
        if named != d["school_year"]:
            raise _config_error(f"{label}: the file name says {named}, the delivery says {d['school_year']}.")
        if d["sheet"] != config["data_sheet"]:
            raise _config_error(f"{label}: sheet {d['sheet']!r} is not the contract's data_sheet {config['data_sheet']!r}.")
        if d["schema_version"] not in versions:
            raise _config_error(f"{label}: schema_version {d['schema_version']!r} is not defined.")
        titles = d["title_cells"]
        if not isinstance(titles, dict) or not titles or not all(
                CELL.match(k) and _cell_position(k)[0] < header_row for k in titles):
            raise _config_error(f"{label}: title_cells must map cells above header_row to their exact text.")
        if config["period_cell"]["cell"] not in titles:
            raise _config_error(f"{label}: title_cells must include the period cell {config['period_cell']['cell']}.")
        counts = [d[k] for k in ("row_count", *KIND_FIELDS.values())]
        if not all(isinstance(n, int) and n >= 0 for n in counts) or d["row_count"] <= 0:
            raise _config_error(f"{label}: row_count and the row-kind counts must be whole numbers, row_count above 0.")
        if sum(d[k] for k in KIND_FIELDS.values()) != d["row_count"]:
            raise _config_error(f"{label}: unit_rows + blank_rows + no_identifier_rows must equal row_count.")
        rng = RANGE.match(str(d["range"]))
        width = len(versions[d["schema_version"]]["columns"])
        if not rng or column_number(rng["column"]) != width or int(rng["row"]) != header_row + d["row_count"]:
            raise _config_error(f"{label}: range must be 'A1:{column_letter(width)}{header_row + d['row_count']}' "
                                "(down to header_row plus row_count rows, one column per schema column).")
        if d["workbook_sha256"] in seen_sha:
            raise _config_error(f"{label}: workbook_sha256 is approved twice.")
        key = (d["school_year"], d["delivery_version"])
        if key in seen_version:
            raise _config_error(f"{label}: delivery_version {d['delivery_version']} for {d['school_year']} is used twice.")
        seen_sha.add(d["workbook_sha256"])
        seen_version.add(key)
        by_year.setdefault(d["school_year"], []).append(d)

    # Versions of one school year count up from 1, and each revision names the workbook it replaces.
    for year, deliveries in by_year.items():
        deliveries.sort(key=lambda d: d["delivery_version"])
        for i, d in enumerate(deliveries, start=1):
            if d["delivery_version"] != i:
                raise _config_error(f"{year}: delivery versions must be 1, 2, 3...; found {[x['delivery_version'] for x in deliveries]}.")
            previous = deliveries[i - 2]["workbook_sha256"] if i > 1 else None
            if d["supersedes"] != previous:
                want = f"supersedes = {previous!r}" if previous else "supersedes = null"
                raise _config_error(f"{year} version {i} must have {want}.")


# --- The prepared delivery -----------------------------------------------------------

@dataclass
class PreparedReport:
    source_id: str
    school_year: str
    delivery_version: int
    supersedes: str
    archive_path: str
    archive_name: str
    archive_sha256: str
    sheet: str
    schema_version: str
    schema_fingerprint: str
    header: list                   # Bronze column names, in sheet order
    source_header: list            # the exact header cells, as the publisher wrote them
    rows: list                     # [(Excel row number, [text per column])]
    row_kinds: dict = field(default_factory=dict)   # {Excel row: unit | blank | no_identifier}
    kinds: dict = field(default_factory=dict)       # {Excel row: [cell kind per column]}
    checks: list = field(default_factory=list)
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
        return Counter(self.row_kinds.values())

    def provenance(self, registry_entry):
        return {
            "source_id": self.source_id,
            "source_system": registry_entry["source_system"],
            "source_url": registry_entry["acquisition"],
            "school_year": self.school_year,
            "delivery_version": self.delivery_version,
            "source_file": self.archive_name,
            "source_sha256": self.archive_sha256,
            "source_sheet": self.sheet,
            "schema_version": self.schema_version,
            "schema_fingerprint": self.schema_fingerprint,
        }

    def row_provenance(self, number):
        return {"source_row_kind": self.row_kinds[number]}


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
        approved = ", ".join(f"{d['school_year']} v{d['delivery_version']} {d['workbook_sha256'][:12]}" for d in same_name)
        raise IngestionError("identify", "checksum_mismatch",
                             f"{path.name} has SHA-256 {digest}, which is not approved (approved: {approved}). "
                             "If the copy is damaged, get the file again. If the publisher sent a revised file, profile it "
                             "and approve it as the next delivery_version with 'supersedes' set; the earlier version is kept.")
    raise IngestionError("identify", "unregistered_delivery",
                         f"{path.name} (SHA-256 {digest}) is not an approved delivery. "
                         "Profile it, then add it to the source config in a pull request.")


def prepare_delivery(config, registry_entry, path):
    delivery, digest = identify_delivery(config, path)
    path = Path(path)
    sheet = open_sheet(config, path, delivery["sheet"])  # safety checks, missing_sheet, unexpected_sheet
    if not sheet.cells:
        raise IngestionError("parse", "empty_sheet", f"{path.name}: sheet {delivery['sheet']!r} has no cells.")
    names = sheet_names(path)

    # The title: every approved title cell exactly as stored. A changed note is a different delivery.
    for ref, text in delivery["title_cells"].items():
        found = cell_text(sheet, *_cell_position(ref))
        if found != text:
            raise IngestionError("schema", "title_changed",
                                 f"{path.name}: cell {ref} reads {found!r}, the approved delivery says {text!r}. "
                                 "Profile the change before loading.")

    # The school year: from the name, from the title cell, and in the approval. All three must agree.
    named = period_from_name(config, path.name)
    if named is None:
        raise IngestionError("period", "period_undeterminable",
                             f"{path.name} does not match {config['workbook_pattern']!r}, so its school year is unknown.")
    spec = config["period_cell"]
    title = cell_text(sheet, *_cell_position(spec["cell"]))
    match = re.match(spec["pattern"], title)
    stated = school_year_of(match) if match else None
    if stated is None:
        raise IngestionError("period", "period_undeterminable",
                             f"{path.name}: cell {spec['cell']} ({title!r}) does not state a school year.")
    if not named == stated == delivery["school_year"]:
        raise IngestionError("period", "period_mismatch",
                             f"the file name says {named}, cell {spec['cell']} says {stated}, the approved delivery "
                             f"says {delivery['school_year']}. Check the file before loading.")

    # The header: every cell of the header row, exactly as stored, to the last column used in that row.
    header_row = config["header_row"]
    version = config["schema_versions"][delivery["schema_version"]]
    width = max(len(version["columns"]), max(sheet.cells.get(header_row, {}), default=0))
    header = [cell_text(sheet, header_row, c) for c in range(1, width + 1)]
    schema = match_header(config, header, delivery["schema_version"])
    columns = version["columns"]
    id_column = columns.index(config["identifier_column"]) + 1

    rows, kinds, row_kinds = [], {}, {}
    for number in range(header_row + 1, last_row(sheet) + 1):   # every row up to the last one holding a value
        rows.append((number, [cell_text(sheet, number, c) for c in range(1, len(columns) + 1)]))
        kinds[number] = [cell_kind(sheet, number, c) for c in range(1, len(columns) + 1)]
        if not sheet.cells.get(number):
            row_kinds[number] = BLANK
        elif cell_text(sheet, number, id_column) == "":
            row_kinds[number] = NO_IDENTIFIER
        else:
            row_kinds[number] = UNIT

    prepared = PreparedReport(
        source_id=config["source_id"],
        school_year=named,
        delivery_version=delivery["delivery_version"],
        supersedes=delivery["supersedes"],
        archive_path=str(path),
        archive_name=path.name,
        archive_sha256=digest,
        sheet=delivery["sheet"],
        schema_version=schema,
        schema_fingerprint=schema_fingerprint(header),
        header=list(columns),
        source_header=header,
        rows=rows,
        row_kinds=row_kinds,
        kinds=kinds,
    )
    prepared.checks = check_workbook(config, delivery, names, sheet, prepared)
    return prepared


def check_workbook(config, delivery, names, sheet, prepared):
    checks = []

    def add(name, ok, expected, actual, warn_only=False):
        status = PASS if ok else (WARN if warn_only else FAIL)
        checks.append(CheckResult(name, status, str(expected), str(actual)))

    def profiled(name, count, expected, finding=None):
        """A known characteristic: PASS at its profiled count, WARN when the count changes, never FAIL."""
        label = f"{expected} (profiled{', ' + finding if finding else ''})"
        add(name, count == expected, label, count, warn_only=True)

    header, counts = prepared.header, config["profiled"]
    n = len(prepared.rows)
    units = [values for number, values in prepared.rows if prepared.row_kinds[number] == UNIT]

    # Shape: exactly what was profiled and approved, row kind by row kind.
    actual_range = f"A1:{column_letter(max(last_column(sheet), len(header)))}{last_row(sheet)}"
    add("row_count_nonzero", n > 0, "> 0", n)
    add("row_count_matches_approved", n == delivery["row_count"], delivery["row_count"], n)
    add("range_matches_approved", actual_range == delivery["range"], delivery["range"], actual_range)
    found = prepared.kind_counts()
    for kind, key in KIND_FIELDS.items():
        add(f"{key}_match_approved", found[kind] == delivery[key], delivery[key], found[kind])
    missing = [c for c in config["required_columns"] if c not in header]
    add("required_columns_present", not missing, config["required_columns"], f"missing {missing}" if missing else "all present")
    add("sheets_match_contract", names == config["expected_sheets"], config["expected_sheets"], names, warn_only=True)

    # The identifier, on unit rows: known deviations are recorded, never corrected (Silver decides).
    key = config["identifier_column"]
    i = header.index(key)
    pattern = re.compile(config["identifier_pattern"])
    ids = [values[i] for values in units]
    profiled(f"{key}_format", sum(1 for v in ids if not pattern.fullmatch(v)), counts["identifier_format"])
    profiled(f"{key}_duplicates", sum(c - 1 for c in Counter(ids).values() if c > 1), counts["identifier_duplicates"])
    profiled("duplicate_rows_in_file", len(units) - len({tuple(v) for v in units}), counts["duplicate_rows"])

    # Cells and text: nothing is recalculated or repaired here.
    texts = [v for _, values in prepared.rows for v in values] + prepared.source_header
    errors = sum(1 for number in prepared.kinds for k in prepared.kinds[number] if k == "error")
    profiled("text_mojibake", sum(1 for t in texts if mojibake(t)), counts["mojibake_cells"])
    profiled("formula_cells", sheet.formulas, 0)
    profiled("error_cells", errors, counts["error_cells"])

    # Known publisher characteristics, on unit rows: PASS at the profiled count, WARN when it changes.
    for check in config["quality_checks"]:
        if check["column"] not in header:
            continue
        index = header.index(check["column"])
        count = sum(1 for values in units if QUALITY_CHECKS[check["check"]](values[index], check.get("value")))
        profiled(f"dq_{check['name']}", count, check["profiled"], check["finding"])
    return checks
