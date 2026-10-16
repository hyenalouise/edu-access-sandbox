"""Made-up DepEd deliveries (zip with one CSV and a README) for tests.

Builds zips shaped like the publisher's (a folder holding the CSV and a
README.md) from a source's real column contract, with invented schools (IDs
from 900001) in an invented place. No DepEd record is copied. Zip entries get a
fixed timestamp, so the same arguments always give the same SHA-256.

Every function takes `source_id` (default `deped_enrollment`); add a source to
NAMES to build its files.
"""

import copy
import hashlib
import json
import zipfile
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXED_TIME = (2026, 1, 1, 0, 0, 0)
README = b"# Made-up README for tests\n"
DEFAULT = "deped_enrollment"

# The publisher's names, per source: zip, CSV inside it, and the folder inside the zip.
NAMES = {
    "deped_enrollment": ("Enrollment-in-SY-{start}-{end}.zip", "enrollment_{sy}.csv", "Enrollment in SY {start}-{end}"),
    "deped_facilities": ("School-Facilities-in-SY-{start}-{end}.zip", "facilities_{sy}.csv", "School Facilities in SY {start}-{end}"),
    "deped_personnel": ("School-Personnel-in-SY-{start}-{end}.zip", "personnel_{sy}.csv", "School Personnel in SY {start}-{end}"),
}

TEXT_VALUES = {
    "school_name": "Test School {i}",
    "region": "Region I",  # a real label: the Silver gate fails on any region not in the reviewed mapping
    "division": "Test Division",
    "province": "TEST PROVINCE",
    "school_district": "Test District",
    "legislative_district": "Lone District",
    "municipality": "TEST CITY (Capital)",
    "barangay": "Doña Test",  # ñ: decodes differently in UTF-8 and Windows-1252
    "street_address": "",  # blank as received; must stay '' in Bronze
    "sector": "Public",
    "school_management": "DepEd",
    "annex_status": "Standalone School",
    "offers_es": "True",
    "offers_jhs": "False",
    "offers_shs": "False",
    "Modified Curricular Offering Classification": "Purely ES",
}


def real_config(source_id=DEFAULT):
    return json.loads((REPO_ROOT / "config" / "ingestion" / f"{source_id}.json").read_text(encoding="utf-8"))


def registry_entry(source_id=DEFAULT):
    registry = json.loads((REPO_ROOT / "config" / "sources.json").read_text(encoding="utf-8"))
    return next(s for s in registry["sources"] if s["source_id"] == source_id)


def columns(schema_version, source_id=DEFAULT):
    return list(real_config(source_id)["schema_versions"][schema_version]["columns"])


def make_rows(header, n_rows=3, first_id=900001):
    rows = []
    for i in range(n_rows):
        row = []
        for column in header:
            if column == "school_id":
                row.append(str(first_id + i))
            elif column in TEXT_VALUES:
                row.append(TEXT_VALUES[column].format(i=i + 1))
            elif "unique" in column:
                row.append("")  # blank count, as in SY 2023-24 (profile O-16); not zero
            elif "_has_" in column or "_accessible_" in column:
                row.append(("True", "False", "")[i % 3])  # facilities yes/no, blank as published (profile O-7)
            else:
                row.append(str(i % 4))
        rows.append(row)
    return rows


def with_values(header, row, values):
    """A copy of one made-up row with some columns set by name, e.g. {'g1_male': '-3'}."""
    row = list(row)
    for column, value in values.items():
        row[header.index(column)] = value
    return row


def csv_bytes(header, rows, encoding="utf-8", line_ending="\n"):
    def quote(value):
        return f'"{value}"' if any(ch in value for ch in ',"\n') else value
    lines = [",".join(quote(v) for v in line) for line in [header, *rows]]
    return (line_ending.join(lines) + line_ending).encode(encoding)


def sy_names(school_year, source_id=DEFAULT):
    """(zip name, CSV name, folder inside the zip) for a school year such as '2023-24'."""
    start = int(school_year[:4])
    return tuple(n.format(start=start, end=start + 1, sy=school_year) for n in NAMES[source_id])


def write_zip(path, members):
    """members: {archive path: bytes}. Directory entries are added for each folder."""
    path.parent.mkdir(parents=True, exist_ok=True)
    folders = sorted({str(PurePosixPath(name).parent) + "/" for name in members if "/" in name})
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for folder in folders:
            zf.writestr(zipfile.ZipInfo(folder, FIXED_TIME), b"")
        for name, data in members.items():
            info = zipfile.ZipInfo(name, FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, data)
    return path


def make_delivery(folder, school_year, schema_version="v1", n_rows=3, first_id=900001,
                  encoding="utf-8", line_ending="\n", rows=None, header=None, zip_folder=None,
                  extra_members=None, archive_name=None, source_id=DEFAULT):
    """Write a publisher-shaped zip into `folder` and return its path."""
    default_archive, csv_name, default_folder = sy_names(school_year, source_id)
    header = header or columns(schema_version, source_id)
    rows = rows if rows is not None else make_rows(header, n_rows, first_id)
    inner = zip_folder if zip_folder is not None else default_folder
    prefix = f"{inner}/" if inner else ""
    members = {
        f"{prefix}{csv_name}": csv_bytes(header, rows, encoding, line_ending),
        f"{prefix}README.md": README,
        **(extra_members or {}),
    }
    return write_zip(Path(folder) / (archive_name or default_archive), members)


def approve(config, archive_path, school_year, schema_version="v1", encoding="utf-8",
            row_count=None, delivery_version=1, supersedes=None):
    """Add an approved-delivery entry for a fixture zip, as a reviewer would."""
    with zipfile.ZipFile(archive_path) as zf:
        data_name = next(n for n in zf.namelist() if n.endswith(".csv"))
        data = zf.read(data_name)
        readme = zf.read(next(n for n in zf.namelist() if n.endswith("README.md")))
    entry = {
        "school_year": school_year,
        "delivery_version": delivery_version,
        "supersedes": supersedes,
        "archive": Path(archive_path).name,
        "archive_sha256": hashlib.sha256(Path(archive_path).read_bytes()).hexdigest(),
        "data_member": PurePosixPath(data_name).name,
        "data_member_sha256": hashlib.sha256(data).hexdigest(),
        "document_sha256": {"README.md": hashlib.sha256(readme).hexdigest()},
        "encoding": encoding,
        "schema_version": schema_version,
        "row_count": row_count if row_count is not None else data.count(b"\n") - 1,
        "retrieved_at_utc": "2026-01-01T00:00:00Z",
    }
    config["deliveries"].append(entry)
    return entry


def empty_config(source_id=DEFAULT):
    """The real contract with no approved deliveries, for tests to approve fixtures into."""
    config = copy.deepcopy(real_config(source_id))
    config["deliveries"] = []
    return config


def fake_repo(root, config):
    """A throwaway repository root: the real registries, mappings, and etl/ SQL, with `config` as the contract."""
    import shutil

    root = Path(root)
    (root / "config" / "ingestion").mkdir(parents=True, exist_ok=True)
    for name in ("sources.json", "tables.yml"):
        shutil.copy(REPO_ROOT / "config" / name, root / "config" / name)
    shutil.copytree(REPO_ROOT / "config" / "mappings", root / "config" / "mappings", dirs_exist_ok=True)
    write_config(root, config)
    for stage in ("01_control", "02_bronze", "03_silver", "04_integration"):
        shutil.copytree(REPO_ROOT / "etl" / stage, root / "etl" / stage, dirs_exist_ok=True)
    return root


def write_config(root, config):
    path = Path(root) / "config" / "ingestion" / f"{config['source_id']}.json"
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")
