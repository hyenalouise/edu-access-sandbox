"""The source contract: what an approved delivery of a source looks like.

`config/ingestion/<source_id>.json` holds, per source:

- the schema versions, each an ordered list of the publisher's column names;
- the approved deliveries, each pinned to its file's SHA-256, schema version,
  and row count.

Six delivery formats exist (`format` in the contract):

- `zip_csv` (the default; DepEd): a zip holding one CSV and its documents,
  one school year per delivery, versions counted per school year.
- `xlsx_sheet` (PSA Poverty Stat): one workbook, one sheet with a merged
  header, region banner rows and a footer, and several estimate years in one
  wide row. Versions are counted per `logical_dataset`, because a delivery
  covers a set of estimate years rather than one period (see workbook.py).
- `xlsx_table` (PSA PSGC): one workbook per publication quarter, one sheet
  with a single header row whose exact cells map to Bronze column names.
  Versions are counted per quarter, which the control tables hold in their
  `school_year` column (D-019; see xlsx_table.py).
- `xlsx_report` (DepEd EMISD): one workbook per school year whose data sheet
  is laid out as a report: title rows, then the header lower down. Its title
  cells are pinned in the approval and every row below the header loads with
  its kind (unit, blank, no_identifier); see xlsx_report.py.
- `xlsx_census` (PSA school-age population): one workbook per census year
  with one sheet per population concept, each a report table of places by
  sex and single-year age in one of two layouts. Every sheet is loaded, so a
  row is identified by its sheet too; versions are counted per
  `logical_dataset` (see xlsx_census.py).
- `geojson_features` (COD-AB boundaries): one GeoJSON FeatureCollection file,
  not zipped, so the file is both the delivery and the data file. Its period is
  the boundary reference date (`valid_on`), held in `school_year` like the PSGC
  quarter, and the geometry is kept as raw text (D-026).

A delivery is approved by merging its entry in a reviewed pull request. The
pipeline never adds or edits an entry, so a file it has never been told about
is refused rather than guessed at. The source's name, system, and URL come from
the registry (`config/sources.json`) so they are written down once.
"""

import hashlib
import json
import re
from pathlib import Path

from src.ingestion.errors import IngestionError

FORMATS = ("zip_csv", "xlsx_sheet", "xlsx_table", "xlsx_report", "xlsx_census", "geojson_features")
# A geojson_features delivery's period is its reference date (valid_on), not a school year.
REFERENCE_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
SUPPORTED_ENCODINGS = {"utf-8", "cp1252"}
SHA256 = re.compile(r"^[0-9a-f]{64}$")
SCHOOL_YEAR = re.compile(r"^[0-9]{4}-[0-9]{2}$")
ESTIMATE_YEAR = re.compile(r"^[0-9]{4}$")
LOGICAL_DATASET = re.compile(r"^[a-z][a-z0-9_]*$")
# A column whose name ends in a four-digit year belongs to that estimate year.
YEAR_SUFFIX = re.compile(r" ([0-9]{4})$")

# Columns the pipeline adds to every Bronze row. A publisher column with one of
# these names would be overwritten, so the contract may not contain one.
PROVENANCE_COLUMNS = (
    "source_id",
    "source_system",
    "source_url",
    "school_year",
    "delivery_version",
    "source_archive",
    "source_archive_sha256",
    "source_file",
    "source_sha256",
    "source_row_number",
    "schema_version",
    "schema_fingerprint",
    "batch_id",
    "run_id",
    "ingested_at_utc",
    "code_revision",
)

# The same idea for a workbook. There is no archive around the data, so the
# workbook is both the delivery and the source file; the sheet and the Excel
# row number say where in it a row was. A delivery covers several estimate
# years, so there is no school_year: the years are delivery metadata, never a
# value assigned to a wide row as if it were one year. source_row_kind says
# what the row is in the sheet's layout (title, header, unit, region banner, footer); it is
# read from the layout, not from the values, and changes no source column.
XLSX_PROVENANCE_COLUMNS = (
    "source_id",
    "source_system",
    "source_url",
    "logical_dataset",
    "estimate_years_covered",
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

DELIVERY_FIELDS = {
    "school_year", "delivery_version", "supersedes", "archive", "archive_sha256",
    "data_member", "data_member_sha256", "document_sha256", "encoding",
    "schema_version", "row_count", "retrieved_at_utc",
}
CONFIG_FIELDS = {
    "source_id", "bronze_table", "landing_dir", "archive_pattern", "data_member_pattern",
    "document_members", "max_uncompressed_bytes", "identifier_column",
    "identifier_pattern", "required_columns", "schema_versions", "deliveries",
}


XLSX_DELIVERY_FIELDS = {
    "logical_dataset", "estimate_years", "delivery_version", "supersedes", "workbook", "workbook_sha256",
    "sheet", "used_range", "schema_version", "body_rows", "unit_rows", "banner_rows", "footer_rows",
    "retrieved_at_utc",
}
USED_RANGE = re.compile(r"^A1:([A-Z]+)([0-9]+)$")
XLSX_CONFIG_FIELDS = {
    "source_id", "format", "bronze_table", "landing_dir", "workbook_pattern", "max_uncompressed_bytes",
    "identifier_column", "identifier_pattern", "label_column", "required_columns", "schema_versions",
    "known_issues", "deliveries",
}
LAYOUT_FIELDS = {
    "first_data_row", "group_row", "group_fill_from_column", "sub_row", "sub_row_columns", "year_row",
    "width", "ignored_columns", "footer_marker", "value_columns_from",
}


def _config_error(message):
    return IngestionError("config", "invalid_config", message)


def source_format(config):
    return config.get("format", "zip_csv")


def provenance_columns(config):
    if source_format(config) == "xlsx_table":
        from src.ingestion.xlsx_table import PROVENANCE_COLUMNS as XLSX_TABLE_PROVENANCE  # avoids a circular import
        return XLSX_TABLE_PROVENANCE
    if source_format(config) == "xlsx_report":
        from src.ingestion.xlsx_report import PROVENANCE_COLUMNS as XLSX_REPORT_PROVENANCE  # avoids a circular import
        return XLSX_REPORT_PROVENANCE
    if source_format(config) == "xlsx_census":
        from src.ingestion.xlsx_census import PROVENANCE_COLUMNS as XLSX_CENSUS_PROVENANCE  # avoids a circular import
        return XLSX_CENSUS_PROVENANCE
    return XLSX_PROVENANCE_COLUMNS if source_format(config) == "xlsx_sheet" else PROVENANCE_COLUMNS


def row_key(config):
    """The columns that identify one Bronze row: the data file and the row in it, plus the
    sheet for a format that loads several sheets of one workbook (their row numbers repeat)."""
    if source_format(config) == "xlsx_census":
        return ("source_sha256", "source_sheet", "source_row_number")
    return ("source_sha256", "source_row_number")


def delivery_file(delivery):
    """The approved file's name: the zip for zip_csv, the GeoJSON file for geojson_features, the workbook for xlsx formats."""
    return delivery.get("archive") or delivery.get("workbook")


def delivery_sha256(delivery):
    return delivery.get("archive_sha256") or delivery.get("workbook_sha256")


def estimate_years_of(columns):
    """Estimate years named by a header, in order: from columns ending in a four-digit year."""
    return sorted({m.group(1) for m in (YEAR_SUFFIX.search(c) for c in columns) if m})


def years_label(years):
    """How a set of estimate years is written in control tables and batch ids: '2018,2021,2023'."""
    return ",".join(sorted(years))


def schema_fingerprint(columns):
    """SHA-256 of the ordered column names: any rename, addition, or reorder changes it."""
    return hashlib.sha256("\n".join(columns).encode("utf-8")).hexdigest()


def load_source_config(repo_root, source_id):
    root = Path(repo_root)
    path = root / "config" / "ingestion" / f"{source_id}.json"
    if not path.is_file():
        raise _config_error(f"{path} does not exist; {source_id} has no ingestion contract.")
    config = json.loads(path.read_text(encoding="utf-8"))
    registry = json.loads((root / "config" / "sources.json").read_text(encoding="utf-8"))
    entries = [s for s in registry["sources"] if s.get("source_id") == source_id]
    if len(entries) != 1:
        raise _config_error(f"{source_id} must appear exactly once in config/sources.json.")
    validate_config(config, entries[0])
    return config, entries[0]


def validate_config(config, registry_entry):
    """Refuse a contract that could load something ambiguous. Returns nothing; raises on the first problem."""
    if source_format(config) not in FORMATS:
        raise _config_error(f"format {config.get('format')!r} is not one of {list(FORMATS)}.")
    if source_format(config) == "xlsx_sheet":
        return validate_xlsx_config(config, registry_entry)
    if source_format(config) == "xlsx_table":
        from src.ingestion.xlsx_table import validate_contract  # avoids a circular import
        return validate_contract(config, registry_entry)
    if source_format(config) == "xlsx_report":
        from src.ingestion.xlsx_report import validate_contract as validate_report  # avoids a circular import
        return validate_report(config, registry_entry)
    if source_format(config) == "xlsx_census":
        from src.ingestion.xlsx_census import validate_contract as validate_census  # avoids a circular import
        return validate_census(config, registry_entry)
    missing = CONFIG_FIELDS - config.keys()
    if missing:
        raise _config_error(f"missing fields {sorted(missing)}.")
    if config["source_id"] != registry_entry.get("source_id"):
        raise _config_error("source_id differs from the registry entry.")
    for field in ("source_system", "acquisition"):
        if not registry_entry.get(field):
            raise _config_error(f"registry entry for {config['source_id']} has no {field!r}; provenance would be blank.")

    _check_schema_versions(config)
    versions = config["schema_versions"]
    geojson = source_format(config) == "geojson_features"
    if geojson:
        _validate_geojson(config)

    seen_archive, seen_member, seen_version = set(), set(), set()
    by_year = {}
    for d in config["deliveries"]:
        label = f"delivery {d.get('archive')!r}"
        missing = DELIVERY_FIELDS - d.keys()
        if missing:
            raise _config_error(f"{label} is missing {sorted(missing)}.")
        period, example = (REFERENCE_DATE, "'2025-02-13'") if geojson else (SCHOOL_YEAR, "'2023-24'")
        if not period.match(d["school_year"]):
            raise _config_error(f"{label}: school_year {d['school_year']!r} is not like {example}.")
        checksums = [("archive_sha256", d["archive_sha256"]), ("data_member_sha256", d["data_member_sha256"])]
        checksums += [(f"document_sha256[{k}]", v) for k, v in d["document_sha256"].items()]
        for field, value in checksums:
            if not SHA256.match(str(value)):
                raise _config_error(f"{label}: {field} is not a lowercase SHA-256.")
        if sorted(d["document_sha256"]) != sorted(config["document_members"]):
            raise _config_error(f"{label}: document_sha256 must list exactly {config['document_members']}.")
        if d["encoding"] not in SUPPORTED_ENCODINGS:
            raise _config_error(f"{label}: encoding {d['encoding']!r} is not one of {sorted(SUPPORTED_ENCODINGS)}.")
        if d["schema_version"] not in versions:
            raise _config_error(f"{label}: schema_version {d['schema_version']!r} is not defined.")
        if not isinstance(d["row_count"], int) or d["row_count"] <= 0:
            raise _config_error(f"{label}: row_count must be a positive whole number.")
        if d["archive_sha256"] in seen_archive:
            raise _config_error(f"{label}: archive_sha256 is approved twice.")
        if d["data_member_sha256"] in seen_member:
            raise _config_error(f"{label}: the same data file is approved twice; a re-zipped copy needs no new entry.")
        key = (d["school_year"], d["delivery_version"])
        if key in seen_version:
            raise _config_error(f"{label}: delivery_version {d['delivery_version']} for {d['school_year']} is used twice.")
        seen_archive.add(d["archive_sha256"])
        seen_member.add(d["data_member_sha256"])
        seen_version.add(key)
        by_year.setdefault(d["school_year"], []).append(d)
        if geojson:
            _check_direct_file(config, d, label)
            continue
        try:
            resolve_school_year(config, d["archive"], d["data_member"], expected=d["school_year"])
        except IngestionError as e:
            raise _config_error(f"{label}: {e.message}")

    # Versions of one school year count up from 1, and each revision names the
    # delivery it replaces, so a changed file is never silently a second "v1".
    for year, deliveries in by_year.items():
        deliveries.sort(key=lambda d: d["delivery_version"])
        for i, d in enumerate(deliveries, start=1):
            if d["delivery_version"] != i:
                raise _config_error(f"{year}: delivery versions must be 1, 2, 3...; found {[x['delivery_version'] for x in deliveries]}.")
            previous = deliveries[i - 2]["archive_sha256"] if i > 1 else None
            if d["supersedes"] != previous:
                want = f"supersedes = {previous!r}" if previous else "supersedes = null"
                raise _config_error(f"{year} version {i} must have {want}.")


GEOJSON_FIELDS = {"geometry_types", "period_column"}


def _validate_geojson(config):
    """A geojson_features source: one file, geometry last, a period column to check against."""
    missing = GEOJSON_FIELDS - config.keys()
    if missing:
        raise _config_error(f"a geojson_features source needs {sorted(missing)}.")
    if config["document_members"]:
        raise _config_error("a geojson_features delivery is one file; document_members must be [].")
    if not config["geometry_types"]:
        raise _config_error("geometry_types must list at least one GeoJSON geometry type.")
    stage = config.get("max_stage_bytes")
    if stage is not None and (not isinstance(stage, int) or stage <= 0):
        raise _config_error("max_stage_bytes must be a positive whole number.")
    for name, version in config["schema_versions"].items():
        columns = version["columns"]
        if columns[-1] != "geometry" or columns.count("geometry") != 1:
            raise _config_error(f"schema {name}: 'geometry' must be the last column, once.")
        if config["period_column"] not in columns:
            raise _config_error(f"schema {name} lacks the period column {config['period_column']!r}.")


def _check_direct_file(config, d, label):
    """A single-file delivery is its own data file, so both names and both checksums agree."""
    if not re.fullmatch(config["archive_pattern"], d["archive"]):
        raise _config_error(f"{label}: does not match archive_pattern {config['archive_pattern']!r}.")
    if d["data_member"] != d["archive"] or d["data_member_sha256"] != d["archive_sha256"]:
        raise _config_error(f"{label}: data_member and data_member_sha256 must equal archive and archive_sha256.")


def resolve_school_year(config, archive_name, member_name, expected=None):
    """Read the school year from the archive name and from the data file name.

    The file has no school-year column (README: 'School year comes from the file
    name'), so two independent names must agree before a year is trusted.
    """
    a = re.match(config["archive_pattern"], archive_name)
    if not a:
        raise IngestionError("identify", "unrecognized_archive_name",
                             f"{archive_name!r} does not match {config['archive_pattern']!r}.")
    m = re.match(config["data_member_pattern"], Path(member_name).name)
    if not m:
        raise IngestionError("identify", "unrecognized_member_name",
                             f"{member_name!r} does not match {config['data_member_pattern']!r}.")
    start, end = int(a["start"]), int(a["end"])
    if end != start + 1:
        raise IngestionError("identify", "school_year_mismatch", f"{archive_name!r} is not one school year ({start}-{end}).")
    year = f"{start}-{str(end)[-2:]}"
    member_year = f"{m['start']}-{m['end']}"
    if member_year != year:
        raise IngestionError("identify", "school_year_mismatch",
                             f"archive says {year} but the data file says {member_year}.")
    if expected is not None and year != expected:
        raise IngestionError("identify", "school_year_mismatch",
                             f"file names say {year} but the approved delivery says {expected}.")
    return year


def match_schema(config, header):
    """Return the schema version whose columns equal the header, or stop on drift."""
    for name, version in config["schema_versions"].items():
        if header == version["columns"]:
            return name
    nearest = max(config["schema_versions"].items(),
                  key=lambda kv: len(set(kv[1]["columns"]) & set(header)))
    known = nearest[1]["columns"]
    added = [c for c in header if c not in known]
    removed = [c for c in known if c not in header]
    detail = f"added {added}, removed {removed}" if added or removed else "same columns in a different order"
    raise IngestionError("schema", "unknown_schema_drift",
                         f"header matches no schema version; nearest is {nearest[0]} ({detail}). "
                         "If the change is real, add a new schema version to the source config in a pull request.")


def find_delivery(config, archive_sha256):
    for d in config["deliveries"]:
        if delivery_sha256(d) == archive_sha256:
            return d
    return None


def _check_schema_versions(config):
    versions = config["schema_versions"]
    if not versions:
        raise _config_error("no schema versions.")
    provenance = provenance_columns(config)
    for name, version in versions.items():
        columns = version.get("columns") or []
        if not columns:
            raise _config_error(f"schema {name} has no columns.")
        if len(set(columns)) != len(columns):
            raise _config_error(f"schema {name} repeats a column name.")
        clash = sorted(set(columns) & set(provenance))
        if clash:
            raise _config_error(f"schema {name} has publisher columns named like provenance fields: {clash}.")
        absent = [c for c in config["required_columns"] if c not in columns]
        if absent:
            raise _config_error(f"schema {name} lacks required column(s) {absent}.")
    fingerprints = [schema_fingerprint(v["columns"]) for v in versions.values()]
    if len(set(fingerprints)) != len(fingerprints):
        raise _config_error("two schema versions have identical columns.")


def validate_xlsx_config(config, registry_entry):
    """The xlsx_sheet rules. A delivery covers a set of estimate years, so:

    - versions are counted per logical_dataset (1, 2, 3...), each revision
      naming the workbook it supersedes;
    - a revision keeps every estimate year of the version it supersedes:
      current_batches makes one version per logical_dataset current, so a
      year a revision dropped would vanish from Silver while still in Bronze;
    - two logical datasets may not share an estimate year: a workbook that
      republishes a year already approved is a new version of that dataset,
      never a second, silent copy of the year.
    """
    missing = XLSX_CONFIG_FIELDS - config.keys()
    if missing:
        raise _config_error(f"missing fields {sorted(missing)}.")
    if config["source_id"] != registry_entry.get("source_id"):
        raise _config_error("source_id differs from the registry entry.")
    for field in ("source_system", "acquisition"):
        if not registry_entry.get(field):
            raise _config_error(f"registry entry for {config['source_id']} has no {field!r}; provenance would be blank.")
    try:
        re.compile(config["workbook_pattern"])
        re.compile(config["identifier_pattern"])
    except re.error as e:
        raise _config_error(f"invalid pattern: {e}.")
    _check_schema_versions(config)
    for name, version in config["schema_versions"].items():
        layout = version.get("layout") or {}
        absent = LAYOUT_FIELDS - layout.keys()
        if absent:
            raise _config_error(f"schema {name} layout is missing {sorted(absent)}.")
        if len(version["columns"]) != layout["width"]:
            raise _config_error(f"schema {name} has {len(version['columns'])} columns but layout width {layout['width']}.")
        for column in (config["identifier_column"], config["label_column"]):
            if column not in version["columns"][: layout["value_columns_from"] - 1]:
                raise _config_error(f"schema {name}: {column!r} must be a column before the value columns.")
        if not estimate_years_of(version["columns"]):
            raise _config_error(f"schema {name}: no column ends in an estimate year.")

    from src.ingestion.workbook import KNOWN_ISSUE_CHECKS  # avoids a circular import at module load
    for issue in config["known_issues"]:
        if issue.get("check") not in KNOWN_ISSUE_CHECKS:
            raise _config_error(f"known issue {issue.get('name')!r}: check {issue.get('check')!r} is not one of {sorted(KNOWN_ISSUE_CHECKS)}.")
        for field in ("name", "finding", "profiled"):
            if field not in issue:
                raise _config_error(f"known issue {issue.get('name')!r} is missing {field!r}.")
        for column in issue.get("columns", []):
            if not any(column in v["columns"] for v in config["schema_versions"].values()):
                raise _config_error(f"known issue {issue['name']!r} names unknown column {column!r}.")

    pattern = re.compile(config["workbook_pattern"])
    seen_sha, seen_version = set(), set()
    by_dataset = {}
    for d in config["deliveries"]:
        label = f"delivery {d.get('workbook')!r}"
        missing = XLSX_DELIVERY_FIELDS - d.keys()
        if missing:
            raise _config_error(f"{label} is missing {sorted(missing)}.")
        if not SHA256.match(str(d["workbook_sha256"])):
            raise _config_error(f"{label}: workbook_sha256 is not a lowercase SHA-256.")
        if not pattern.match(d["workbook"]):
            raise _config_error(f"{label}: name does not match workbook_pattern {config['workbook_pattern']!r}, so it would not be discovered.")
        if not LOGICAL_DATASET.match(str(d["logical_dataset"])):
            raise _config_error(f"{label}: logical_dataset must be snake_case.")
        years = d["estimate_years"]
        if not years or any(not ESTIMATE_YEAR.match(str(y)) for y in years) or years != sorted(set(years)):
            raise _config_error(f"{label}: estimate_years must be sorted, distinct four-digit years as text.")
        if d["schema_version"] not in config["schema_versions"]:
            raise _config_error(f"{label}: schema_version {d['schema_version']!r} is not defined.")
        version = config["schema_versions"][d["schema_version"]]
        if estimate_years_of(version["columns"]) != years:
            raise _config_error(f"{label}: estimate_years {years} differ from the years in schema "
                                f"{d['schema_version']} {estimate_years_of(version['columns'])}.")
        first, last = d["body_rows"].get("first"), d["body_rows"].get("last")
        if first != version["layout"]["first_data_row"] or not isinstance(last, int) or last < first:
            raise _config_error(f"{label}: body_rows must run from the layout's first data row to a later row.")
        counts = [d["unit_rows"], d["banner_rows"], d.get("blank_rows", 0), d["footer_rows"]]
        if any(not isinstance(n, int) or n < 0 for n in counts) or d["unit_rows"] == 0:
            raise _config_error(f"{label}: unit, banner, blank and footer row counts must be whole numbers, units > 0.")
        if d["unit_rows"] + d["banner_rows"] + d.get("blank_rows", 0) != last - first + 1:
            raise _config_error(f"{label}: unit + banner + blank rows must equal the body rows {first}..{last}.")
        used = USED_RANGE.match(str(d["used_range"]))
        if not used or int(used.group(2)) != last + d["footer_rows"]:
            raise _config_error(f"{label}: used_range must be 'A1:<column><row>' ending at the last footer row "
                                f"({last} + {d['footer_rows']} footer rows).")
        if d["workbook_sha256"] in seen_sha:
            raise _config_error(f"{label}: workbook_sha256 is approved twice.")
        key = (d["logical_dataset"], d["delivery_version"])
        if key in seen_version:
            raise _config_error(f"{label}: delivery_version {d['delivery_version']} of {d['logical_dataset']} is used twice.")
        seen_sha.add(d["workbook_sha256"])
        seen_version.add(key)
        by_dataset.setdefault(d["logical_dataset"], []).append(d)

    for dataset, deliveries in by_dataset.items():
        deliveries.sort(key=lambda d: d["delivery_version"])
        for i, d in enumerate(deliveries, start=1):
            if d["delivery_version"] != i:
                raise _config_error(f"{dataset}: delivery versions must be 1, 2, 3...; found {[x['delivery_version'] for x in deliveries]}.")
            previous = deliveries[i - 2]["workbook_sha256"] if i > 1 else None
            if d["supersedes"] != previous:
                want = f"supersedes = {previous!r}" if previous else "supersedes = null"
                raise _config_error(f"{dataset} version {i} must have {want}.")
            if i > 1:
                dropped = sorted(set(deliveries[i - 2]["estimate_years"]) - set(d["estimate_years"]))
                if dropped:
                    raise _config_error(
                        f"{dataset} version {i} covers {d['estimate_years']} and drops {dropped} from version "
                        f"{i - 1}. current_batches makes one version of a logical dataset current, so the dropped "
                        "years would disappear from Silver while still in Bronze. A revision must keep every "
                        "estimate year of the version it supersedes; if the publisher dropped a year, record a "
                        "team decision first.")

    names = sorted(by_dataset)
    for i, a in enumerate(names):
        years_a = {y for d in by_dataset[a] for y in d["estimate_years"]}
        for b in names[i + 1:]:
            shared = sorted(years_a & {y for d in by_dataset[b] for y in d["estimate_years"]})
            if shared:
                raise _config_error(
                    f"logical datasets {a!r} and {b!r} both cover {shared}. A workbook that republishes an "
                    "approved estimate year is a revision: approve it as the next delivery_version of the "
                    "dataset it overlaps, with 'supersedes' set, or record a team decision first.")
