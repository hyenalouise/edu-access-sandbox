# Compares the two DepEd workbooks with PSGC and coordinates for the public schools they share (#217):
# deped_enrollment_psgc (all sectors, lane 07) and deped_psgc_coordinates (public only, lane 09).
# Both are loaded through the real Bronze pipeline and Silver SQL into a new local DuckDB file, so the
# comparison reads exactly what Silver publishes: padded and Sulu-recoded codes, typed and flagged
# coordinates. Prints counts only, under the IDs PC-1 to PC-3 (docs/data/cross-source/README.md).
#
#   RAW_DATA_DIR=~/Projects/reached-hq/raw-data python analysis/cross_source/cross_source_deped_psgc_coordinates.py
#
# RAW_DATA_DIR must hold both approved workbooks in deped/original/ (the loaders check their SHA-256):
#   SY 2023-2024 School Level Data on Enrollment with PSGC, Longitude and Latitude.xlsx        (deped_enrollment_psgc)
#   SY 2023-2024 School Level Data on Enrollment with PSGC Longitude & Latitude (Public only).xlsx  (deped_psgc_coordinates)
# A missing one stops the script with its name.
# The DuckDB file is written to local_state/ (git-ignored) and replaced on each run. No Databricks compute.

import argparse
import os
import sys
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from src.ingestion.contract import load_source_config  # noqa: E402
from src.ingestion.pipeline import IngestionRun  # noqa: E402
from src.ingestion.revision import resolve_code_revision  # noqa: E402
from src.ingestion.store import DuckDBStore  # noqa: E402

LANES = (("deped_enrollment_psgc", "07_clean_deped_enrollment_psgc"), ("deped_psgc_coordinates", "09_clean_deped_psgc_coordinates"))
SILVER = "edu_access.`03-silver`"
# Great-circle distance in km between the two files' points (haversine).
KM = ("2 * 6371 * asin(sqrt(power(sin(radians(n.latitude - o.latitude) / 2), 2) + cos(radians(o.latitude)) * "
      "cos(radians(n.latitude)) * power(sin(radians(n.longitude - o.longitude) / 2), 2)))")


def load(store, landing, revision):
    for source, clean in LANES:
        summary = IngestionRun(store, REPO, source, landing, "local", revision).execute()
        if summary.status != "succeeded":
            sys.exit(f"{source}: Bronze load {summary.status}; check the workbook in deped/original/.")
        # A missing workbook is only a WARN for a contract without require_approved_deliveries (#220): the load
        # succeeds with 0 rows. Stop here with the file's name, before the Silver gate fails on no current batch.
        config, _ = load_source_config(REPO, source)
        rows = store.query(f"SELECT COUNT(*) FROM edu_access.`02-bronze`.{config['bronze_table']} AS r "
                           f"JOIN edu_access.`01-control`.current_batches AS b ON r.batch_id = b.batch_id "
                           f"WHERE b.source_id = '{source}'")[0][0]
        if not rows:
            files = ", ".join(d["workbook"] for d in config["deliveries"])
            sys.exit(f"{source}: no Bronze rows. Put the approved workbook in {landing / config['landing_dir'] / 'original'}: {files}")
        params = {"run_id": f"cross-{uuid.uuid4().hex[:8]}", "code_revision": revision, "environment": "local"}
        store.run_file(REPO / "etl" / "03_silver" / f"{clean}.sql", params)
        store.run_file(REPO / "etl" / "03_silver" / f"90_validate_{source}_clean.sql", params)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=REPO / "local_state" / "cross_source_deped_psgc_coordinates.duckdb")
    args = parser.parse_args(argv)
    raw = os.environ.get("RAW_DATA_DIR")
    if not raw:
        sys.exit("Set RAW_DATA_DIR to the folder that contains deped/original/.")
    args.db.parent.mkdir(exist_ok=True)
    args.db.unlink(missing_ok=True)
    store = DuckDBStore(args.db)
    load(store, Path(raw).expanduser(), resolve_code_revision(REPO))

    pair = (f"FROM {SILVER}.deped_psgc_coordinates_clean AS n "
            f"JOIN {SILVER}.deped_enrollment_psgc_clean AS o ON o.school_id = n.school_id AND o.school_year = n.school_year")
    print("== Schools")
    print(store.records(f"""SELECT
        (SELECT COUNT(*) FROM {SILVER}.deped_psgc_coordinates_clean) AS public_only_file,
        (SELECT COUNT(*) FROM {SILVER}.deped_enrollment_psgc_clean WHERE sector = 'Public') AS all_sector_file_public,
        (SELECT COUNT(*) {pair}) AS in_both,
        (SELECT COUNT(*) {pair} WHERE o.sector <> 'Public') AS in_both_not_public_there""")[0])

    print("== PC-1 PSGC codes, public schools in both")
    for level in ("city_municipality", "barangay"):
        col = f"psgc_{level}"
        print(level, store.records(f"""SELECT
            COUNT_IF(n.{col} = o.{col}) AS same_code,
            COUNT_IF(n.{col} <> o.{col}) AS different_code,
            COUNT_IF(n.{col} IS NOT NULL AND o.{col} IS NULL) AS only_public_only_file,
            COUNT_IF(n.{col} IS NULL AND o.{col} IS NOT NULL) AS only_all_sector_file,
            COUNT_IF(n.{col} IS NULL AND o.{col} IS NULL) AS neither
            {pair}""")[0])
    print("psgc_recoded agrees:", store.query(f"SELECT COUNT_IF(n.psgc_recoded = o.psgc_recoded), COUNT(*) {pair}")[0])

    print("== PC-2 coordinates, public schools in both")
    print(store.records(f"""SELECT
        COUNT_IF(n.coordinate_flag IS NULL AND o.coordinate_flag IS NULL) AS usable_in_both,
        COUNT_IF(n.coordinate_flag IS NULL AND o.coordinate_flag IS NOT NULL) AS usable_only_public_only_file,
        COUNT_IF(n.coordinate_flag IS NOT NULL AND o.coordinate_flag IS NULL) AS usable_only_all_sector_file,
        COUNT_IF(n.coordinate_flag IS NOT NULL AND o.coordinate_flag IS NOT NULL) AS usable_in_neither
        {pair}""")[0])
    both = f"{pair} WHERE n.coordinate_flag IS NULL AND o.coordinate_flag IS NULL"
    print("usable in both, distance between the two points:")
    for band, n in store.query(f"""SELECT CASE WHEN n.longitude = o.longitude AND n.latitude = o.latitude THEN '0 identical'
            WHEN {KM} < 0.1 THEN '1 < 100 m' WHEN {KM} < 1 THEN '2 100 m - 1 km' WHEN {KM} < 10 THEN '3 1 - 10 km'
            WHEN {KM} < 100 THEN '4 10 - 100 km' ELSE '5 > 100 km' END AS band, COUNT(*) {both} GROUP BY 1 ORDER BY 1"""):
        print(f"  {band[2:]:<14} {n:>7,}")
    print("same barangay code and a point over 10 km apart:",
          store.query(f"SELECT COUNT(*) {both} AND n.psgc_barangay = o.psgc_barangay AND {KM} >= 10")[0][0])

    print("== PC-3 is each all-sector point somewhere in the public-only file, and at which school (rounded to 5 decimals)")
    print(store.records(f"""
        WITH n AS (SELECT school_id, round(longitude, 5) AS lon, round(latitude, 5) AS lat
                   FROM {SILVER}.deped_psgc_coordinates_clean WHERE coordinate_flag IS NULL),
             o AS (SELECT school_id, round(longitude, 5) AS lon, round(latitude, 5) AS lat
                   FROM {SILVER}.deped_enrollment_psgc_clean WHERE coordinate_flag IS NULL AND sector = 'Public'),
             hit AS (SELECT o.school_id AS o_id, n.school_id AS n_id FROM o JOIN n ON n.lon = o.lon AND n.lat = o.lat)
        SELECT (SELECT COUNT(*) FROM o) AS all_sector_points,
               (SELECT COUNT(DISTINCT o_id) FROM hit) AS found_in_public_only_file,
               (SELECT COUNT(DISTINCT o_id) FROM hit WHERE o_id = n_id) AS at_the_same_school,
               (SELECT COUNT(DISTINCT o_id) FROM hit WHERE o_id <> n_id) AS at_another_school""")[0])
    print("school_id gap (public-only school minus all-sector school), most common:", store.query(f"""
        WITH n AS (SELECT school_id, round(longitude, 5) AS lon, round(latitude, 5) AS lat
                   FROM {SILVER}.deped_psgc_coordinates_clean WHERE coordinate_flag IS NULL),
             o AS (SELECT school_id, round(longitude, 5) AS lon, round(latitude, 5) AS lat
                   FROM {SILVER}.deped_enrollment_psgc_clean WHERE coordinate_flag IS NULL AND sector = 'Public')
        SELECT CAST(n.school_id AS BIGINT) - CAST(o.school_id AS BIGINT) AS gap, COUNT(*) AS schools
        FROM o JOIN n ON n.lon = o.lon AND n.lat = o.lat WHERE o.school_id <> n.school_id
        GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 5"""))
    store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
