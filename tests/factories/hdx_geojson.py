"""Made-up COD-AB-shaped GeoJSON for tests (hdx_boundaries).

Columns come from the real contract; places and codes are invented (PH99...).
The text is written by hand, not by json.dumps, so a test can check that Bronze
keeps the file's exact characters: "112.2460" stays "112.2460", not 112.246.
"""

import hashlib
import json
from pathlib import Path

from factories.deped_deliveries import real_config

SOURCE = "hdx_boundaries"
FILE_NAME = "phl_admin3.geojson"
PERIOD = "2025-02-13"
GEOMETRY_TEXT = ('{"type": "Polygon", "coordinates": '
                 '[[[120.50, 14.0], [120.60, 14.0], [120.60, 14.10], [120.50, 14.0]]]}')
NUMBERS = {"area_sqkm": "112.2460", "center_lat": "11.5000", "center_lon": "122.8000"}
PARENT_CODES = {"adm2_pcode": "PH99001", "adm1_pcode": "PH99", "adm0_pcode": "PH"}


def columns():
    return list(real_config(SOURCE)["schema_versions"]["v1"]["columns"])


def _value(column, i, period):
    if column in NUMBERS:
        return NUMBERS[column]
    if column == "valid_on":
        return json.dumps(period)
    if column == "valid_to" or column[-1] in "123":  # *_name1..3 and lang1..3 are empty in the real file
        return "null"
    if column == "adm3_pcode":
        return json.dumps(f"PH99{i:05d}")
    if column in PARENT_CODES:
        return json.dumps(PARENT_CODES[column])
    if column == "version":
        return '"v03"'
    if column == "lang":
        return '"en"'
    return json.dumps(f"Test Place {i}")


def feature_text(i, header, period=PERIOD, geometry=GEOMETRY_TEXT):
    props = ", ".join(f"{json.dumps(c)}: {_value(c, i, period)}" for c in header if c != "geometry")
    return f'{{"type": "Feature", "properties": {{{props}}}, "geometry": {geometry}}}'


def make_geojson(folder, n=3, period=PERIOD, header=None, name=FILE_NAME):
    """Write a FeatureCollection of n features into folder and return its path."""
    header = header or columns()
    features = ",\n".join(feature_text(i, header, period) for i in range(1, n + 1))
    return write_text(Path(folder) / name,
                      f'{{"type": "FeatureCollection", "name": "phl_admin3", "features": [\n{features}\n]}}\n')


def write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def approve(config, path, row_count, period=PERIOD, delivery_version=1, supersedes=None):
    """Add an approved-delivery entry for a fixture file, as a reviewer would."""
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    entry = {
        "school_year": period,
        "delivery_version": delivery_version,
        "supersedes": supersedes,
        "archive": Path(path).name,
        "archive_sha256": digest,
        "data_member": Path(path).name,
        "data_member_sha256": digest,
        "document_sha256": {},
        "encoding": "utf-8",
        "schema_version": "v1",
        "row_count": row_count,
        "retrieved_at_utc": "2026-01-01T00:00:00Z",
    }
    config["deliveries"].append(entry)
    return entry


# --- Features Silver accepts -----------------------------------------------------------------
# The features above use made-up labels ("Test Place 1") that Bronze keeps but the Silver gate
# rejects (labels_mapped_*). These use the real region, country, version and language labels,
# a closed square, and a centre inside it, so a build passes every Silver check.

SQUARE = ('{"type": "Polygon", "coordinates": '
          '[[[120.5, 14.0], [120.6, 14.0], [120.6, 14.1], [120.5, 14.1], [120.5, 14.0]]]}')


def pcodes(i):
    """Made-up P-codes for feature i: 100 towns per made-up province, so the codes stay PH + 7 digits."""
    province = f"PH01{10 + i // 100:03d}"
    return province + f"{i % 100:02d}", province


def silver_properties(i, **changes):
    """JSON text of each property, as a COD-AB file writes it; changes = {column: JSON text}."""
    adm3, adm2 = pcodes(i)
    values = {c: "null" for c in columns() if c != "geometry"}
    values.update({
        "adm3_name": json.dumps(f"Town {i}"), "adm3_ref_name": json.dumps(f"Town {i}"),
        "adm3_pcode": json.dumps(adm3), "adm2_name": json.dumps(f"Province {i // 100}"), "adm2_pcode": json.dumps(adm2),
        "adm1_name": '"Region I (Ilocos Region)"', "adm1_pcode": '"PH01"',
        "adm0_name": '"Philippines"', "adm0_pcode": '"PH"',
        "valid_on": json.dumps(PERIOD), "version": '"v03"', "lang": '"en"',
        "area_sqkm": "112.24600000000012", "center_lat": "14.05", "center_lon": "120.55",
    })
    values.update(changes)
    return values


def silver_feature(i, geometry=SQUARE, **changes):
    props = ", ".join(f"{json.dumps(c)}: {v}" for c, v in silver_properties(i, **changes).items())
    return f'{{"type": "Feature", "properties": {{{props}}}, "geometry": {geometry}}}'


def write_features(folder, features, name=FILE_NAME):
    """Write a FeatureCollection of the given feature texts into folder and return its path."""
    text = '{"type": "FeatureCollection", "name": "phl_admin3", "features": [\n' + ",\n".join(features) + "\n]}\n"
    return write_text(Path(folder) / name, text)

