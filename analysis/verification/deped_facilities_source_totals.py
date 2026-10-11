# %% [markdown]
# # DepEd facilities: totals of the published CSV, computed without the pipeline
#
# The facilities Silver gate reconciles Silver with Bronze (`counts_reconcile`, `true_values_reconcile`,
# `missing_counts_stay_null`, `missing_booleans_stay_null`). This program checks the step before it:
# that those four totals equal the file DepEd published. It reads the approved zip straight from
# RAW_DATA_DIR, verifies the zip's and the CSV's SHA-256 against the Bronze contract, and counts with the
# Python standard library only: nothing from src/, no Bronze, no Silver, no Databricks.
#
# Columns are classified from the CSV header alone: `school_id`, `sector`, and `school_management` are
# identity; `offers_*` and every `es_`/`hs_` `has_`/`accessible_` column are yes/no; every other column
# is a count. The program stops if that gives anything but 21 counts and 63 yes/no columns.
#
# Prints, and writes to `local_state/deped_facilities_source_totals.md` (git-ignored), counts only,
# never row values.
#
#     RAW_DATA_DIR=~/Projects/reached-hq/raw-data python analysis/verification/deped_facilities_source_totals.py
#
# %%
import csv
import hashlib
import inspect
import io
import json
import os
import re
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(inspect.currentframe().f_code.co_filename).resolve().parents[2]
CONTRACT = REPO_ROOT / "config" / "ingestion" / "deped_facilities.json"
OUT = REPO_ROOT / "local_state" / "deped_facilities_source_totals.md"
IDENTITY = ("school_id", "sector", "school_management")
YES_NO = re.compile(r"^(offers_(es|jhs|shs)|(es|hs)_(has|accessible)_[a-z0-9_]+)$")
# What the facilities Silver gate reported for SY 2023-24 (every run, locally and on dev; evidence/).
PIPELINE = {"sum of all counts": 1213740, "True values": 458922, "blank counts": 626515, "blank yes/no": 2800050}


# %%
def sha256(data):
    return hashlib.sha256(data).hexdigest()


def find_archive(raw_root, landing_dir, name):
    found = sorted((Path(raw_root) / landing_dir).rglob(name))
    if len(found) != 1:
        sys.exit(f"error: expected one {name} under {raw_root}/{landing_dir}, found {len(found)}")
    return found[0]


def read_delivery(raw_root):
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    (delivery,) = [d for d in contract["deliveries"] if d["school_year"] == "2023-24"]
    archive = find_archive(raw_root, contract["landing_dir"], delivery["archive"])
    data = archive.read_bytes()
    if sha256(data) != delivery["archive_sha256"]:
        sys.exit(f"error: {archive.name} does not match the contract's SHA-256")
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        (member,) = [n for n in zf.namelist() if n.rsplit("/", 1)[-1] == delivery["data_member"]]
        csv_bytes = zf.read(member)
    if sha256(csv_bytes) != delivery["data_member_sha256"]:
        sys.exit(f"error: {delivery['data_member']} does not match the contract's SHA-256")
    return delivery, csv_bytes.decode(delivery["encoding"])


def totals(text):
    reader = csv.reader(io.StringIO(text, newline=""))
    header = next(reader)
    yes_no = [i for i, c in enumerate(header) if YES_NO.match(c)]
    counts = [i for i, c in enumerate(header) if c not in IDENTITY and i not in yes_no]
    if (len(counts), len(yes_no)) != (21, 63):
        sys.exit(f"error: found {len(counts)} counts and {len(yes_no)} yes/no columns, not 21 and 63")
    t = {"rows": 0, "sum of all counts": 0, "True values": 0, "blank counts": 0, "blank yes/no": 0,
         "counts not a whole number": 0, "yes/no not True, False, or blank": 0, "values with surrounding spaces": 0}
    for row in reader:
        t["rows"] += 1
        for i in counts:
            value = row[i]
            t["values with surrounding spaces"] += value != value.strip()
            if value == "":
                t["blank counts"] += 1
            elif value.isdigit():
                t["sum of all counts"] += int(value)
            else:
                t["counts not a whole number"] += 1
        for i in yes_no:
            value = row[i]
            t["values with surrounding spaces"] += value != value.strip()
            t["True values"] += value == "True"
            t["blank yes/no"] += value == ""
            t["yes/no not True, False, or blank"] += value not in ("True", "False", "")
    return t


# %%
def main():
    raw_root = os.environ.get("RAW_DATA_DIR")
    if not raw_root:
        sys.exit("error: set RAW_DATA_DIR to the raw data root")
    delivery, text = read_delivery(os.path.expanduser(raw_root))
    t = totals(text)
    lines = [
        "# DepEd facilities: totals of the published CSV",
        "",
        f"`{delivery['archive']}` → `{delivery['data_member']}`, both SHA-256 equal to the contract. "
        "Counted with the Python standard library, without the pipeline.",
        "",
        "| Measure | Published CSV | Silver gate | Result |",
        "|---|---:|---:|---|",
        f"| rows | {t['rows']:,} | {delivery['row_count']:,} (contract) | {'OK' if t['rows'] == delivery['row_count'] else 'CHECK'} |",
    ]
    for name, value in PIPELINE.items():
        lines.append(f"| {name} | {t[name]:,} | {value:,} | {'OK' if t[name] == value else 'CHECK'} |")
    for name in ("counts not a whole number", "yes/no not True, False, or blank", "values with surrounding spaces"):
        lines.append(f"| {name} | {t[name]:,} | 0 (profile O-6, O-7) | {'OK' if t[name] == 0 else 'CHECK'} |")
    report = "\n".join(lines) + "\n"
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(report, encoding="utf-8")
    print(report)
    return 0 if "CHECK" not in report else 1


if __name__ == "__main__":
    sys.exit(main())
