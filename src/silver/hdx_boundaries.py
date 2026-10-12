"""Silver for hdx_boundaries (COD-AB ADM3): the spec, the build SQL, the gate SQL, and the data dictionary.

Two reviewed files define it, and nothing else:

- `config/ingestion/hdx_boundaries.json`, the Bronze contract: which publisher
  columns exist in which schema version;
- `config/mappings/hdx_boundaries.json`, the Silver rules: identifier, parent
  codes, free text, categories, dates, decimals, and geometry.

The boundaries differ from DepEd's shape (D-021): no counts, but dates, exact
decimals, and a geometry column. So, like psa_poverty_stat, they have their own
generator, picked by "generator" in the rules file (src/silver/generators.py).
The SQL follows src/silver/sql.py: the build writes the candidate tables, the
gate checks them and publishes only if no check FAILs (D-025), both run as SQL
tasks, and only syntax both Databricks and DuckDB accept is used.

Geometry stays the published GeoJSON text (D-023): the same value on both
engines, never simplified, reprojected, or repaired. The build and the gate
parse it with try_to_geometry (Databricks; NULL when the text is not a
geometry), which src/ingestion/store.py gives DuckDB as a macro over its spatial
extension. A geometry type is compared as upper(replace(.., 'ST_', '')), because
Databricks says ST_Polygon where DuckDB says POLYGON. The centre point is built
from the published text as GeoJSON too, so both shapes carry the same SRID.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from src.ingestion.bronze import OWNER_GROUP, source_columns
from src.ingestion.contract import load_source_config
from src.ingestion.errors import IngestionError
from src.silver.spec import LINEAGE, RUN_STAMP, SCHEMA
from src.silver.sql import CONTROL, bq, candidate_comment, dq_table_name, joined, lit, silver_ref, whitespace

SOURCE_ID = "hdx_boundaries"
SAFE_LITERAL = re.compile(r"^[^'\\;]*$")
DECIMAL_TYPE = re.compile(r"^DECIMAL\(([0-9]+),([0-9]+)\)$")
DATE_PATTERN = "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"
FLAGS = ("hierarchy_consistent", "geometry_is_valid", "center_inside_geometry")


def _error(message):
    return IngestionError("config", "invalid_silver_mapping", message)


@dataclass
class Decimal:
    name: str
    type: str           # DECIMAL(p,s)
    pattern: str        # a published value that matches casts without rounding
    reason: str         # quarantine reason when it does not
    positive: bool
    evidence: str


@dataclass
class HdxSpec:
    source_id: str
    bronze_table: str
    clean_file: str
    clean_table: str
    quarantine_table: str
    clean_candidate: str
    quarantine_candidate: str
    columns: list                 # [(name, kind)] every publisher column, in published order
    identifier: str
    identifier_pattern: str
    codes: dict                   # parent code column -> pattern, child first (adm2, adm1, adm0)
    free_text: list               # free text and always-blank columns
    categories: dict              # column -> {published label: standard value}
    dates: list
    decimals: list                # [Decimal]
    geometry: str
    geometry_types: list          # upper case, as compared
    quarantine_reasons: tuple
    quarantine_fail_percent: float
    mapping: dict = field(repr=False)

    def kind(self, name):
        return dict(self.columns)[name]

    def silver_type(self, name):
        kind = self.kind(name)
        if kind == "date":
            return "date"
        if kind == "decimal":
            return next(d.type for d in self.decimals if d.name == name).lower()
        return "string"

    def clean_columns(self):
        """[(name, type)] of the clean table, in order."""
        columns = [(name, self.silver_type(name)) for name, _ in self.columns]
        columns += [(f, "boolean") for f in FLAGS]
        return columns + list(LINEAGE) + list(RUN_STAMP)

    def quarantine_columns(self):
        return [(self.identifier, "string"), ("quarantine_reasons", "array<string>")] + list(LINEAGE) + list(RUN_STAMP)


def _decimal_pattern(kind):
    found = DECIMAL_TYPE.match(kind)
    if not found:
        raise _error(f"decimal type {kind!r} must be written DECIMAL(p,s).")
    precision, scale = int(found.group(1)), int(found.group(2))
    if not 0 < scale < precision <= 38:
        raise _error(f"decimal type {kind!r} needs 0 < s < p <= 38.")
    return "^-?[0-9]{1,%d}([.][0-9]{1,%d})?$" % (precision - scale, scale)


def load_spec(repo_root, source_id=SOURCE_ID):
    path = Path(repo_root) / "config" / "mappings" / f"{source_id}.json"
    if not path.is_file():
        raise _error(f"{path} does not exist; {source_id} has no Silver rules.")
    mapping = json.loads(path.read_text(encoding="utf-8"))
    contract, _ = load_source_config(repo_root, source_id)
    registry = yaml.safe_load((Path(repo_root) / "config" / "tables.yml").read_text(encoding="utf-8"))
    entry = next((s for s in registry["source_tables"] if s["source_id"] == source_id), None)
    return build_spec(mapping, contract, entry)


def build_spec(mapping, contract, registry_entry):
    source_id = contract["source_id"]
    if mapping.get("source_id") != source_id:
        raise _error("source_id differs from the Bronze contract.")
    silver = (registry_entry or {}).get("silver", {})
    if registry_entry is None or silver.get("table") != mapping["silver_table"] \
            or silver.get("quarantine_table") != mapping["quarantine_table"]:
        raise _error("silver_table and quarantine_table must match config/tables.yml.")
    if len(contract["schema_versions"]) != 1:
        raise _error("the HDX Silver rules know one schema version; a new one needs a reviewed rules change.")

    identifier = mapping["identifier"]["column"]
    codes = dict(mapping["code_columns"]["columns"])
    free_text = list(mapping["free_text_columns"]) + list(mapping["blank_columns"]["columns"])
    dates = list(mapping["date_columns"]["columns"])
    geometry = mapping["geometry"]["column"]
    decimals = []
    for name, entry in mapping["decimal_columns"]["columns"].items():
        decimals.append(Decimal(name, entry["type"], _decimal_pattern(entry["type"]), entry["reason"],
                                bool(entry.get("positive", False)), entry.get("evidence", "")))

    categories = {}
    for name, entry in mapping["categories"].items():
        standard = entry["standard"]
        if len(set(standard)) != len(standard):
            raise _error(f"{name}: the standard set repeats a value.")
        labels = {}
        for label in entry["labels"]:
            if label["published"] in labels:
                raise _error(f"{name}: label {label['published']!r} is listed twice.")
            if label["standard"] not in standard:
                raise _error(f"{name}: {label['published']!r} maps to {label['standard']!r}, which is not in the standard set.")
            labels[label["published"]] = label["standard"]
        categories[name] = labels

    # Every publisher column is classified exactly once.
    kinds = {}
    for kind, names in (("identifier", [identifier]), ("code", codes), ("free_text", free_text),
                        ("category", categories), ("date", dates), ("decimal", [d.name for d in decimals]),
                        ("geometry", [geometry])):
        for name in names:
            if name in kinds:
                raise _error(f"column {name!r} is classified twice ({kinds[name]} and {kind}).")
            kinds[name] = kind
    published = source_columns(contract)
    unclassified = [c for c in published if c not in kinds]
    if unclassified:
        raise _error(f"columns {unclassified} have no Silver rule. A new publisher column needs a reviewed "
                     "entry in config/mappings/hdx_boundaries.json.")
    stray = sorted(set(kinds) - set(published))
    if stray:
        raise _error(f"the mapping names columns the contract does not have: {stray}.")
    for name in published:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
            raise _error(f"column {name!r} is not snake_case.")

    geometry_types = [t.upper() for t in mapping["geometry"]["allowed_types"]]
    literals = [mapping["identifier"]["pattern"], *codes.values(), *geometry_types,
                *[v for labels in categories.values() for pair in labels.items() for v in pair]]
    unsafe = [v for v in literals if not SAFE_LITERAL.match(v)]
    if unsafe:
        raise _error(f"patterns and labels may not contain quotes, backslashes or ';': {unsafe}.")
    percent = mapping.get("quarantine", {}).get("fail_above_percent", 1)
    if not isinstance(percent, (int, float)) or not 0 <= percent < 100:
        raise _error("quarantine.fail_above_percent must be a number from 0 to under 100.")

    reasons = [f"{identifier}_blank", f"{identifier}_malformed", f"{identifier}_duplicated"]
    reasons += [f"{d}_uncastable" for d in dates]
    for d in decimals:
        if d.reason not in reasons:
            reasons.append(d.reason)
        if d.positive:
            reasons.append(d.reason.replace("_uncastable", "") + "_not_positive")
    reasons += ["geometry_unparseable", "geometry_empty", "geometry_wrong_type"]

    return HdxSpec(
        source_id=source_id, bronze_table=contract["bronze_table"], clean_file=silver["clean_file"],
        clean_table=mapping["silver_table"], quarantine_table=mapping["quarantine_table"],
        clean_candidate=silver["candidate_table"], quarantine_candidate=silver["candidate_quarantine_table"],
        columns=[(c, kinds[c]) for c in published], identifier=identifier,
        identifier_pattern=mapping["identifier"]["pattern"], codes=codes, free_text=free_text,
        categories=categories, dates=dates, decimals=decimals, geometry=geometry, geometry_types=geometry_types,
        quarantine_reasons=tuple(reasons), quarantine_fail_percent=percent, mapping=mapping,
    )


# --- Shared SQL pieces -------------------------------------------------------------------

def _bronze_ref(spec):
    return f"edu_access.`02-bronze`.{spec.bronze_table}"


def _header(spec, what, command, path):
    return [
        f"-- {what} for {spec.source_id}. Generated from config/ingestion/{spec.source_id}.json",
        f"-- and config/mappings/{spec.source_id}.json by src/silver/hdx_boundaries.py:",
        f"--   python -m src.silver.cli {command} --source {spec.source_id} > {path}",
        "-- Do not edit by hand; tests/test_silver_hdx.py fails if it differs.",
    ]


def _number(value):
    return str(int(value)) if float(value).is_integer() else str(value)


def _blank(ref):
    return f"({ref} IS NULL OR {ref} = '')"


def _typed_date(ref):
    return f"CASE WHEN regexp_like({ref}, {lit(DATE_PATTERN)}) THEN TRY_CAST({ref} AS DATE) END"


def _date_uncastable(ref):
    return f"(NOT {_blank(ref)} AND {_typed_date(ref)} IS NULL)"


def _typed_decimal(d, ref):
    """The published number, typed only when it fits the type exactly: no digit is rounded away (D-023)."""
    return f"CASE WHEN regexp_like({ref}, {lit(d.pattern)}) THEN TRY_CAST({ref} AS {d.type}) END"


def _decimal_uncastable(d, ref):
    return f"(NOT {_blank(ref)} AND {_typed_decimal(d, ref)} IS NULL)"


def _geometry_type(geo):
    """POLYGON, MULTIPOLYGON, ... on both engines (Databricks: ST_Polygon, DuckDB: POLYGON)."""
    return f"upper(replace(CAST(st_geometrytype({geo}) AS STRING), 'ST_', ''))"


def _point(lon_ref, lat_ref):
    """The published centre as a GeoJSON point, parsed like the shape so both carry the same SRID."""
    return f"try_to_geometry(concat('{{\"type\": \"Point\", \"coordinates\": [', {lon_ref}, ', ', {lat_ref}, ']}}'))"


def _hierarchy(spec, ref):
    """TRUE when every parent code has its pattern and the chain adm3 -> adm2 -> adm1 holds; never NULL."""
    chain = [spec.identifier, *spec.codes]
    parts = [f"regexp_like({ref}.{c}, {lit(p)})" for c, p in spec.codes.items()]
    for child, parent in zip(chain, chain[1:]):
        if parent == chain[-1]:
            break  # the country code is checked by its pattern; it is not a prefix of the region code's digits
        parts.append(f"substr({ref}.{child}, 1, length({ref}.{parent})) = {ref}.{parent}")
    return "COALESCE(" + "\n        AND ".join(parts) + ", FALSE)"


# --- Build ---------------------------------------------------------------------------------

def build_sql(spec):
    source = spec.source_id
    view = f"{source}_classified"
    lineage = [name for name, _ in LINEAGE]
    stamp = [name for name, _ in RUN_STAMP]
    ident = spec.identifier
    lat = next(d.name for d in spec.decimals if d.name.endswith("lat"))
    lon = next(d.name for d in spec.decimals if d.name.endswith("lon"))

    # Text: identifier and codes exactly as published; free text and labels whitespace-normalized.
    normalized = [f"r.{bq(ident)}", "r.school_year",
                  f"COUNT(*) OVER (PARTITION BY r.school_year, r.{bq(ident)}) AS {ident}_rows"]
    for name, kind in spec.columns:
        if kind in ("free_text", "category"):
            normalized.append(f"NULLIF({whitespace('r.' + bq(name))}, '') AS {name}")
        elif kind != "identifier":
            normalized.append(f"r.{bq(name)} AS {name}")
    normalized.append(f"try_to_geometry(r.{bq(spec.geometry)}) AS geo")
    normalized += [f"r.{name}" for name in lineage]

    typed = []
    for name, kind in spec.columns:
        if kind == "category":
            cases = "\n".join(f"      WHEN {lit(p)} THEN {lit(s)}" for p, s in spec.categories[name].items())
            typed.append(f"CASE n.{name}\n{cases}\n    END AS {name}")
        elif kind == "date":
            typed.append(f"{_typed_date('n.' + name)} AS {name}")
        elif kind == "decimal":
            d = next(x for x in spec.decimals if x.name == name)
            typed.append(f"{_typed_decimal(d, 'n.' + name)} AS {name}")
        else:
            typed.append(f"n.{name}")

    # reason -> condition, written in the order of spec.quarantine_reasons.
    allowed = ", ".join(lit(t) for t in spec.geometry_types)
    conditions = {
        f"{ident}_blank": f"n.{ident} IS NULL OR n.{ident} = ''",
        f"{ident}_malformed": f"n.{ident} <> '' AND NOT regexp_like(n.{ident}, {lit(spec.identifier_pattern)})",
        f"{ident}_duplicated": f"n.{ident} <> '' AND n.{ident}_rows > 1",
        "geometry_unparseable": "n.geo IS NULL",
        "geometry_empty": "n.geo IS NOT NULL AND st_isempty(n.geo)",
        "geometry_wrong_type": (f"n.geo IS NOT NULL AND NOT st_isempty(n.geo)\n"
                                f"            AND {_geometry_type('n.geo')} NOT IN ({allowed})"),
    }
    conditions.update({f"{d}_uncastable": _date_uncastable("n." + d) for d in spec.dates})
    for d in spec.decimals:
        uncastable = _decimal_uncastable(d, "n." + d.name)
        conditions[d.reason] = f"{conditions[d.reason]}\n            OR {uncastable}" if d.reason in conditions else uncastable
        if d.positive:
            conditions[d.reason.replace("_uncastable", "") + "_not_positive"] = f"{_typed_decimal(d, 'n.' + d.name)} <= 0"
    reasons = [f"      CASE WHEN {conditions[r]} THEN {lit(r)} END" for r in spec.quarantine_reasons]
    typed += [
        f"{_hierarchy(spec, 'n')} AS hierarchy_consistent",
        "COALESCE(st_isvalid(n.geo), FALSE) AS geometry_is_valid",
        f"COALESCE(st_contains(n.geo, {_point('n.' + lon, 'n.' + lat)}), FALSE) AS center_inside_geometry",
        "concat_ws(',',\n" + ",\n".join(reasons) + "\n    ) AS quarantine_reasons",
    ]
    typed += [f"n.{name}" for name in lineage]

    final = [f"t.{name}" for name, _ in spec.columns] + [f"t.{f}" for f in FLAGS] + ["t.quarantine_reasons"]
    final += [f"t.{name}" for name in lineage] + [f"session.silver_{name} AS {name}" for name in stamp]

    clean_columns = [name for name, _ in spec.clean_columns()]
    quarantine_select = [ident, "split(quarantine_reasons, ',') AS quarantine_reasons", *lineage, *stamp]
    clean, quarantine = silver_ref(spec.clean_candidate), silver_ref(spec.quarantine_candidate)
    lines = _header(spec, "Silver build", "sql", f"etl/03_silver/{spec.clean_file}") + [
        "--",
        "-- Rebuilds the two candidate tables from the current Bronze batches only (01-control.current_batches:",
        "-- the latest succeeded delivery version of each reference date). Bronze is read, never changed.",
        "-- Every current Bronze feature ends in exactly one of the two tables:",
        f"--   {spec.clean_candidate}       one row per ADM3 unit, typed, geometry as published;",
        f"--   {spec.quarantine_candidate}  features that cannot be trusted, with their reasons.",
        f"-- The Silver tables ({spec.clean_table}, {spec.quarantine_table}) are never written here:",
        "-- the gate (the next task) checks the candidates and publishes them only if no check fails,",
        "-- so a failed build never replaces the last good one. It rebuilds on every run (D-025).",
        "--",
        "-- Parameters, supplied by the job (or src/job/local_run.py):",
        "--   :run_id         the job run; every row built here, and the gate's results, carry it",
        "--   :code_revision  the commit that ran, from the job parameter; never a literal",
        "--   :environment    the deploy target: local, dev, or prod",
        "",
        "-- One run stamp for the whole file, so both tables carry the same run and the same time.",
        "DECLARE OR REPLACE VARIABLE silver_run_id STRING;",
        "SET VARIABLE silver_run_id = :run_id;",
        "DECLARE OR REPLACE VARIABLE silver_code_revision STRING;",
        "SET VARIABLE silver_code_revision = COALESCE(NULLIF(:code_revision, ''), 'UNSET');",
        "DECLARE OR REPLACE VARIABLE silver_environment STRING;",
        "SET VARIABLE silver_environment = COALESCE(NULLIF(:environment, ''), 'UNSET');",
        "DECLARE OR REPLACE VARIABLE silver_cleaned_at_utc TIMESTAMP;",
        "SET VARIABLE silver_cleaned_at_utc = current_timestamp();",
        "",
        "-- The run starts. Its row stays 'running' until the gate records how it ended, so a",
        "-- build that dies is never mistaken for a good one. run_id and job_run_id are both the job run,",
        "-- so one filter on job_run_id finds a job run's Bronze loads and Silver builds (D-020).",
        f"MERGE INTO {CONTROL}.pipeline_runs AS t",
        "USING (SELECT session.silver_run_id AS run_id) AS s",
        f"ON t.run_id = s.run_id AND t.pipeline_name = 'silver_build' AND t.source_id = {lit(source)}",
        "WHEN MATCHED THEN UPDATE SET",
        "  status = 'running', started_at_utc = session.silver_cleaned_at_utc, finished_at_utc = NULL,",
        "  failure_stage = NULL, error_message = NULL, code_revision = session.silver_code_revision, job_run_id = s.run_id",
        "WHEN NOT MATCHED THEN INSERT (run_id, pipeline_name, source_id, environment, status, started_at_utc, code_revision, job_run_id)",
        f"  VALUES (s.run_id, 'silver_build', {lit(source)}, session.silver_environment, 'running',",
        "          session.silver_cleaned_at_utc, session.silver_code_revision, s.run_id);",
        "",
        f"CREATE SCHEMA IF NOT EXISTS edu_access.`{SCHEMA}`;",
        f"ALTER SCHEMA edu_access.`{SCHEMA}` OWNER TO `{OWNER_GROUP}`;",
        "",
        "-- Every current Bronze feature once, typed, with the reasons it would be quarantined. A reason is",
        "-- decided with explicit NULL handling, and concat_ws never returns NULL, so quarantine_reasons = ''",
        "-- and <> '' split the features without losing any. The geometry is parsed once, here, and only",
        "-- its checks are kept: Silver stores the published text.",
        f"CREATE OR REPLACE TEMPORARY VIEW {view} AS",
        "WITH bronze AS (",
        "  SELECT r.*",
        f"  FROM {_bronze_ref(spec)} AS r",
        f"  JOIN {CONTROL}.current_batches AS c ON r.batch_id = c.batch_id",
        f"  WHERE c.source_id = {lit(source)}",
        "),",
        "-- Free text and labels: whitespace normalized, blank to NULL. Codes, numbers, dates and the",
        "-- geometry stay as published here. The key is counted per reference date.",
        "normalized AS (",
        "  SELECT",
        joined(normalized, 4),
        "  FROM bronze AS r",
        "),",
        "-- Labels mapped to the standard set (unmapped: NULL, and the gate fails); dates and decimals typed",
        "-- only when the published text fits the type exactly, so no digit is rounded away (D-023).",
        "typed AS (",
        "  SELECT",
        joined(typed, 4),
        "  FROM normalized AS n",
        ")",
        "SELECT",
        joined(final, 2),
        "FROM typed AS t;",
        "",
        "-- One row per ADM3 unit, with the Bronze feature it came from.",
        f"CREATE OR REPLACE TABLE {clean} USING DELTA AS",
        "SELECT",
        joined(clean_columns, 2),
        f"FROM {view}",
        "WHERE quarantine_reasons = '';",
        "",
        candidate_comment(clean, spec.clean_table),
        f"ALTER TABLE {clean} OWNER TO `{OWNER_GROUP}`;",
        "",
        "-- Features set aside, never deleted: the Bronze feature, and why.",
        f"CREATE OR REPLACE TABLE {quarantine} USING DELTA AS",
        "SELECT",
        joined(quarantine_select, 2),
        f"FROM {view}",
        "WHERE quarantine_reasons <> '';",
        "",
        candidate_comment(quarantine, spec.quarantine_table),
        f"ALTER TABLE {quarantine} OWNER TO `{OWNER_GROUP}`;",
        "",
    ]
    return "\n".join(lines)


# --- Gate ----------------------------------------------------------------------------------

def gate_checks(spec):
    """[(check_name, scope, status)] in the order the gate writes them; scope: whole or batch."""
    whole = [("current_batches_present", "FAIL"), ("lineage_complete", "FAIL"),
             ("rows_resolve_to_current_bronze", "FAIL"), ("rows_built_by_this_run", "FAIL"),
             ("one_timestamp_per_run", "FAIL")]
    batch = [("rows_reconcile", "FAIL"), (f"{spec.identifier}_unique", "FAIL"), (f"{spec.identifier}_valid", "FAIL"),
             ("codes_as_published", "FAIL"), ("geometry_as_published", "FAIL"), ("values_kept", "FAIL"),
             ("valid_on_is_reference_date", "FAIL"), ("geometry_parsed", "FAIL"), ("geometry_type_allowed", "FAIL"),
             ("geometry_not_empty", "FAIL"), *[(f"{d.reason.replace('_uncastable', '')}_positive", "FAIL")
                                               for d in spec.decimals if d.positive],
             ("flags_consistent", "FAIL")]
    batch += [(f"labels_mapped_{c}", "FAIL") for c in spec.categories]
    batch += [("geometry_valid", "WARN"), ("center_inside_geometry", "WARN"), ("hierarchy_consistent", "WARN"),
              ("quarantine_rate", "WARN/FAIL")]
    batch += [(f"quarantine_reason_{r}", "WARN") for r in spec.quarantine_reasons]
    batch += [("rule_whitespace_normalized", "record"), ("rule_blank_text_to_null", "record")]
    return [(n, "whole", s) for n, s in whole] + [(n, "batch", s) for n, s in batch]


def gate_sql(spec):
    source = spec.source_id
    lineage = [name for name, _ in LINEAGE]
    stamp = [name for name, _ in RUN_STAMP]
    clean_name, quarantine_name = dq_table_name(spec.clean_candidate), dq_table_name(spec.quarantine_candidate)
    ident = spec.identifier
    lat = next(d.name for d in spec.decimals if d.name.endswith("lat"))
    lon = next(d.name for d in spec.decimals if d.name.endswith("lon"))
    text = [name for name, kind in spec.columns if kind in ("free_text", "category")]
    allowed = ", ".join(lit(t) for t in spec.geometry_types)

    def raw(name):
        return f"b.{bq(name)}"

    # Per batch, from Bronze: rows, and what the text rules would change.
    bronze_batches = [
        "b.batch_id",
        "COUNT(*) AS bronze_rows",
        "COUNT_IF(\n        " + "\n        OR ".join(f"{whitespace(raw(c))} <> {raw(c)}" for c in text)
        + "\n      ) AS whitespace_rows",
        "COUNT_IF(\n        " + "\n        OR ".join(f"{whitespace(raw(c))} = ''" for c in text)
        + "\n      ) AS blank_text_rows",
    ] + [
        f"COUNT_IF(b.in_quarantine AND {whitespace(raw(c))} <> ''\n"
        f"        AND {whitespace(raw(c))} NOT IN ({', '.join(lit(p) for p in labels)})) AS quarantined_unmapped_{c}"
        for c, labels in spec.categories.items()
    ]

    # A clean value is NULL only where Bronze is blank: nothing published is lost by typing.
    lost = []
    for name, kind in spec.columns:
        if kind in ("code", "date", "decimal"):
            lost.append(f"(c.{name} IS NULL AND NOT {_blank(raw(name))})")
        elif kind == "free_text":
            lost.append(f"(c.{name} IS NULL AND {whitespace(raw(name))} <> '')")
    positive = [d for d in spec.decimals if d.positive]
    clean_batches = [
        "c.batch_id",
        "COUNT(*) AS clean_rows",
        f"COUNT(DISTINCT c.{ident}) AS clean_ids",
        f"COUNT_IF(c.{ident} IS NULL OR NOT regexp_like(c.{ident}, {lit(spec.identifier_pattern)})) AS invalid_ids",
        "COUNT_IF(b.source_row_number IS NULL\n        OR "
        + "\n        OR ".join(f"c.{c} IS DISTINCT FROM {raw(c)}" for c in [ident, *spec.codes]) + "\n      ) AS changed_codes",
        f"COUNT_IF(b.source_row_number IS NULL OR c.{spec.geometry} IS DISTINCT FROM {raw(spec.geometry)}) AS changed_geometry",
        "COUNT_IF(\n        " + "\n        OR ".join(lost) + "\n      ) AS lost_values",
        "COUNT_IF(c.valid_on IS NULL OR c.valid_on <> TRY_CAST(b.school_year AS DATE)) AS off_reference_rows",
        "COUNT_IF(g.geo IS NULL) AS unparsed_rows",
        f"COUNT_IF(g.geo IS NOT NULL AND {_geometry_type('g.geo')} NOT IN ({allowed})) AS wrong_type_rows",
        "COUNT_IF(g.geo IS NOT NULL AND st_isempty(g.geo)) AS empty_rows",
        # A blank area stays NULL (D-023), as the build keeps it; only a published zero or negative fails.
        *[f"COUNT_IF(c.{d.name} <= 0) AS not_positive_{d.name}" for d in positive],
        "COUNT_IF(\n        "
        f"c.hierarchy_consistent IS DISTINCT FROM {_hierarchy(spec, 'c')}\n"
        "        OR c.geometry_is_valid IS DISTINCT FROM COALESCE(st_isvalid(g.geo), FALSE)\n"
        f"        OR c.center_inside_geometry IS DISTINCT FROM COALESCE(st_contains(g.geo, {_point(raw(lon), raw(lat))}), FALSE)\n"
        "      ) AS inconsistent_flags",
        *[f"COUNT_IF(c.{name} IS NULL AND {whitespace(raw(name))} <> '') AS unmapped_{name}" for name in spec.categories],
        "COUNT_IF(NOT c.geometry_is_valid) AS invalid_geometry_rows",
        "COUNT_IF(NOT c.center_inside_geometry) AS center_outside_rows",
        "COUNT_IF(NOT c.hierarchy_consistent) AS hierarchy_broken_rows",
    ]
    quarantine_batches = ["q.batch_id", "COUNT(*) AS quarantined_rows"] + [
        f"COUNT_IF(array_contains(q.quarantine_reasons, {lit(r)})) AS reason_{r}" for r in spec.quarantine_reasons]

    values = ["bronze_rows", "whitespace_rows", "blank_text_rows", "clean_rows", "clean_ids", "invalid_ids",
              "changed_codes", "changed_geometry", "lost_values", "off_reference_rows", "unparsed_rows",
              "wrong_type_rows", "empty_rows", *[f"not_positive_{d.name}" for d in positive], "inconsistent_flags",
              "invalid_geometry_rows", "center_outside_rows", "hierarchy_broken_rows", "quarantined_rows",
              *[f"reason_{r}" for r in spec.quarantine_reasons]]
    batch_columns = ["y.batch_id"] + [f"COALESCE({v}, 0) AS {v}" for v in values]
    # Unmapped labels: clean rows by what the build made of them, quarantined rows against the rules themselves.
    batch_columns += [f"COALESCE(unmapped_{c}, 0) + COALESCE(quarantined_unmapped_{c}, 0) AS unmapped_{c}"
                      for c in spec.categories]

    def check(name, table, status, expected, actual, source="batches", scope="batch"):
        batch = "CAST(NULL AS STRING)" if scope == "whole" else "batch_id"
        return (f"SELECT {batch} AS batch_id, {lit(table)} AS table_name, {lit(name)} AS check_name,\n"
                f"         {status} AS status,\n"
                f"         {expected} AS expected, {actual} AS actual FROM {source}")

    def must_equal(name, expected, actual, source="batches", scope="batch", table=clean_name):
        return check(name, table, f"CASE WHEN {actual} = {expected} THEN 'PASS' ELSE 'FAIL' END",
                     f"CAST({expected} AS STRING)", f"CAST({actual} AS STRING)", source, scope)

    def must_be_zero(name, actual, source="batches", scope="batch"):
        return must_equal(name, "0", actual, source, scope)

    def warn_if_any(name, actual, table=clean_name):
        return check(name, table, f"CASE WHEN {actual} = 0 THEN 'PASS' ELSE 'WARN' END", "'0'",
                     f"CAST({actual} AS STRING)")

    def record(name, actual):
        return check(name, clean_name, "'PASS'", "CAST(NULL AS STRING)", f"CAST({actual} AS STRING)")

    pct = _number(spec.quarantine_fail_percent)
    checks = [
        "-- The whole build",
        check("current_batches_present", clean_name, "CASE WHEN current_batches > 0 THEN 'PASS' ELSE 'FAIL' END",
              "'at least 1'", "CAST(current_batches AS STRING)", "found", "whole"),
        must_be_zero("lineage_complete", "missing_lineage", "whole", "whole"),
        must_be_zero("rows_resolve_to_current_bronze", "unresolved_rows", "unresolved", "whole"),
        must_be_zero("rows_built_by_this_run", "other_run_rows", "whole", "whole"),
        must_equal("one_timestamp_per_run", "1", "timestamps", "whole", "whole"),
        "-- Each current batch: reconciliation, the key, published values kept, geometry",
        must_equal("rows_reconcile", "bronze_rows", "clean_rows + quarantined_rows"),
        must_be_zero(f"{ident}_unique", "clean_rows - clean_ids"),
        must_be_zero(f"{ident}_valid", "invalid_ids"),
        must_be_zero("codes_as_published", "changed_codes"),
        must_be_zero("geometry_as_published", "changed_geometry"),
        must_be_zero("values_kept", "lost_values"),
        must_be_zero("valid_on_is_reference_date", "off_reference_rows"),
        must_be_zero("geometry_parsed", "unparsed_rows"),
        must_be_zero("geometry_type_allowed", "wrong_type_rows"),
        must_be_zero("geometry_not_empty", "empty_rows"),
        *[must_be_zero(f"{d.reason.replace('_uncastable', '')}_positive", f"not_positive_{d.name}") for d in positive],
        must_be_zero("flags_consistent", "inconsistent_flags"),
        "-- Each current batch: every label is in the reviewed rules",
        *[must_be_zero(f"labels_mapped_{c}", f"unmapped_{c}") for c in spec.categories],
        "-- Each current batch: flagged, never repaired (WARN)",
        warn_if_any("geometry_valid", "invalid_geometry_rows"),
        warn_if_any("center_inside_geometry", "center_outside_rows"),
        warn_if_any("hierarchy_consistent", "hierarchy_broken_rows"),
        f"-- Each current batch: quarantine (WARN above 0, FAIL above {pct}% of the batch's Bronze rows)",
        check("quarantine_rate", quarantine_name,
              f"CASE WHEN quarantined_rows = 0 THEN 'PASS' WHEN quarantined_rows * 100 > bronze_rows * {pct} "
              "THEN 'FAIL' ELSE 'WARN' END",
              # No ';' inside a string: store.split_statements splits files on it.
              f"'0 (FAIL above {pct}% of ' || CAST(bronze_rows AS STRING) || ')'", "CAST(quarantined_rows AS STRING)"),
        *[warn_if_any(f"quarantine_reason_{r}", f"reason_{r}", quarantine_name) for r in spec.quarantine_reasons],
        "-- Each current batch: how many rows each text rule changed (records, always PASS)",
        record("rule_whitespace_normalized", "whitespace_rows"),
        record("rule_blank_text_to_null", "blank_text_rows"),
    ]
    union = []
    for item in checks:
        if item.startswith("--"):
            union.append("  " + item)
        else:
            union.append(("  UNION ALL " if any(not u.lstrip().startswith("--") for u in union) else "  ") + item)

    silver_rows = (f"  SELECT {', '.join([*lineage, *stamp])} FROM clean\n"
                   f"  UNION ALL SELECT {', '.join([*lineage, *stamp])} FROM quarantined")
    missing_lineage = " OR ".join(f"{name} IS NULL" for name in [*lineage, *stamp])

    lines = _header(spec, "Silver gate", "gate", f"etl/03_silver/90_validate_{spec.clean_table}.sql") + [
        "--",
        "-- The job task after the Silver build. It checks the candidate tables the build wrote, one row",
        "-- per check in data_quality_results: the whole build, then each current batch. On any FAIL it",
        "-- records the run 'failed' and stops the task before publishing, so the Silver tables keep the",
        "-- last build that passed and nothing downstream runs. Otherwise it copies the candidates to the",
        "-- Silver tables and records the run 'succeeded'. PASS: as expected. WARN: recorded, the build is",
        "-- published (invalid shapes, centres outside their shape, broken code chains, quarantined rows).",
        "-- FAIL: the candidate cannot be trusted. Results hold counts, never row values.",
        "--",
        "-- Parameters, supplied by the job (or src/job/local_run.py):",
        "--   :run_id         the job run that built the tables",
        "--   :code_revision  the commit that ran, from the job parameter; never a literal",
        "",
        "-- Only this execution's results decide: a repaired job run keeps its run_id, and the",
        "-- results of an earlier attempt must not fail it again.",
        "DECLARE OR REPLACE VARIABLE silver_gate_started_at_utc TIMESTAMP;",
        "SET VARIABLE silver_gate_started_at_utc = current_timestamp();",
        "",
        f"INSERT INTO {CONTROL}.data_quality_results",
        "  (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)",
        f"SELECT :run_id, batch_id, {lit(source)}, 'silver', table_name, check_name, status, expected, actual,",
        "       current_timestamp(), :code_revision",
        "FROM (",
        "WITH cur AS (",
        f"  SELECT batch_id FROM {CONTROL}.current_batches WHERE source_id = {lit(source)}",
        "),",
        "bronze AS (",
        f"  SELECT r.* FROM {_bronze_ref(spec)} AS r JOIN cur ON r.batch_id = cur.batch_id",
        "),",
        f"clean AS (SELECT * FROM {silver_ref(spec.clean_candidate)}),",
        f"quarantined AS (SELECT * FROM {silver_ref(spec.quarantine_candidate)}),",
        "-- Current Bronze features, each marked if Silver set it aside.",
        "b AS (",
        "  SELECT bronze.*, q.source_row_number IS NOT NULL AS in_quarantine",
        "  FROM bronze",
        "  LEFT JOIN quarantined AS q",
        "    ON bronze.source_sha256 = q.source_sha256 AND bronze.source_row_number = q.source_row_number",
        "),",
        "-- A quarantined row has no clean value, so its labels are checked against the reviewed rules here:",
        "-- a row set aside for another reason must not let an unmapped label through.",
        "bronze_batches AS (",
        "  SELECT",
        joined(bronze_batches, 4),
        "  FROM b GROUP BY b.batch_id",
        "),",
        "-- Each clean row beside its Bronze feature, the geometry parsed again: the build is checked, not trusted.",
        "g AS (",
        f"  SELECT c.source_sha256, c.source_row_number, try_to_geometry(c.{spec.geometry}) AS geo FROM clean AS c",
        "),",
        "clean_batches AS (",
        "  SELECT",
        joined(clean_batches, 4),
        "  FROM clean AS c",
        "  LEFT JOIN b ON b.source_sha256 = c.source_sha256 AND b.source_row_number = c.source_row_number",
        "  LEFT JOIN g ON g.source_sha256 = c.source_sha256 AND g.source_row_number = c.source_row_number",
        "  GROUP BY c.batch_id",
        "),",
        "quarantine_batches AS (",
        "  SELECT",
        joined(quarantine_batches, 4),
        "  FROM quarantined AS q GROUP BY q.batch_id",
        "),",
        "batches AS (",
        "  SELECT",
        joined(batch_columns, 4),
        "  FROM cur AS y",
        "  LEFT JOIN bronze_batches ON bronze_batches.batch_id = y.batch_id",
        "  LEFT JOIN clean_batches ON clean_batches.batch_id = y.batch_id",
        "  LEFT JOIN quarantine_batches ON quarantine_batches.batch_id = y.batch_id",
        "),",
        "found AS (SELECT COUNT(*) AS current_batches FROM cur),",
        "silver_rows AS (",
        silver_rows,
        "),",
        "whole AS (",
        "  SELECT",
        f"    COUNT_IF({missing_lineage}) AS missing_lineage,",
        "    COUNT_IF(run_id IS NULL OR run_id <> :run_id) AS other_run_rows,",
        "    COUNT(DISTINCT cleaned_at_utc) AS timestamps",
        "  FROM silver_rows",
        "),",
        "-- Silver rows whose Bronze feature is not in a current batch (an old version, or gone).",
        "unresolved AS (",
        "  SELECT COUNT(*) AS unresolved_rows",
        "  FROM silver_rows AS s",
        "  LEFT JOIN bronze ON s.source_sha256 = bronze.source_sha256 AND s.source_row_number = bronze.source_row_number",
        "  WHERE bronze.source_row_number IS NULL",
        "),",
        "checks AS (",
        *union,
        ")",
        "SELECT * FROM checks",
        ") AS results;",
        "",
        "-- A failed build: record it before stopping. The Silver tables are not touched.",
        f"MERGE INTO {CONTROL}.pipeline_runs AS t",
        "USING (",
        "  SELECT :run_id AS run_id, COUNT_IF(status = 'FAIL') AS fails",
        f"  FROM {CONTROL}.data_quality_results",
        f"  WHERE run_id = :run_id AND source_id = {lit(source)} AND layer = 'silver'",
        "    AND checked_at_utc >= session.silver_gate_started_at_utc",
        ") AS s",
        f"ON t.run_id = s.run_id AND t.pipeline_name = 'silver_build' AND t.source_id = {lit(source)}",
        "WHEN MATCHED AND s.fails > 0 THEN UPDATE SET",
        "  status = 'failed', finished_at_utc = current_timestamp(), failure_stage = 'gate',",
        "  error_message = CAST(s.fails AS STRING) || ' FAIL result(s) in data_quality_results';",
        "",
        "-- Stop here, before publishing, if anything failed in this execution.",
        "SELECT CASE WHEN COUNT(*) > 0",
        f"            THEN raise_error('Silver gate failed for {source}: ' || CAST(COUNT(*) AS STRING)",
        "                             || ' FAIL result(s) in data_quality_results for run ' || :run_id)",
        "       END",
        f"FROM {CONTROL}.data_quality_results",
        f"WHERE run_id = :run_id AND source_id = {lit(source)} AND layer = 'silver' AND status = 'FAIL'",
        "  AND checked_at_utc >= session.silver_gate_started_at_utc;",
        "",
        "-- Every check passed: publish. Quarantine first, then clean, the table Gold reads. Each copy is",
        "-- one atomic Delta commit, but the pair is not, so the run is 'succeeded' only after both. If the",
        "-- task dies in between, the run stays 'running', and Gold trusts a Silver table only when the",
        "-- run_id its rows carry is a succeeded silver_build run (D-025).",
        f"CREATE OR REPLACE TABLE {silver_ref(spec.quarantine_table)} USING DELTA AS",
        f"SELECT * FROM {silver_ref(spec.quarantine_candidate)};",
        "",
        f"ALTER TABLE {silver_ref(spec.quarantine_table)} OWNER TO `{OWNER_GROUP}`;",
        "",
        f"CREATE OR REPLACE TABLE {silver_ref(spec.clean_table)} USING DELTA AS",
        f"SELECT * FROM {silver_ref(spec.clean_candidate)};",
        "",
        f"ALTER TABLE {silver_ref(spec.clean_table)} OWNER TO `{OWNER_GROUP}`;",
        "",
        "-- Published: the run succeeded.",
        f"MERGE INTO {CONTROL}.pipeline_runs AS t",
        "USING (SELECT :run_id AS run_id) AS s",
        f"ON t.run_id = s.run_id AND t.pipeline_name = 'silver_build' AND t.source_id = {lit(source)}",
        "WHEN MATCHED THEN UPDATE SET",
        "  status = 'succeeded', finished_at_utc = current_timestamp(), failure_stage = NULL, error_message = NULL;",
        "",
    ]
    return "\n".join(lines)


# --- Data dictionary ---------------------------------------------------------------------

LINEAGE_MEANING = {
    "batch_id": "The Bronze batch (one GeoJSON delivery); joins `01-control`.ingestion_batches",
    "delivery_version": "Which delivery of the reference date: 1, or 2+ after an approved revision",
    "schema_version": "Which property list the file had",
    "source_sha256": "SHA-256 of the GeoJSON file; with `source_row_number`, identifies the Bronze feature exactly",
    "source_row_number": "The feature's position in the file (1 = first feature)",
    "run_id": "The job run that built the row (`{{job.run_id}}`); every row of a build has the same one, as do the gate's results",
    "cleaned_at_utc": "When that build ran; one value for both tables, in UTC",
    "code_revision": "The commit that ran the build",
}

QUARANTINE_MEANING = {
    "_blank": "`{ident}` is NULL or blank",
    "_malformed": "`{ident}` does not match `{pattern}`",
    "_duplicated": "the same `{ident}` appears more than once for the reference date; every copy is set aside",
    "valid_on_uncastable": "`valid_on` is not blank and not a `YYYY-MM-DD` date",
    "valid_to_uncastable": "`valid_to` is not blank and not a `YYYY-MM-DD` date",
    "geometry_unparseable": "the geometry text is blank or is not a geometry",
    "geometry_empty": "the geometry parses but has no coordinates",
    "geometry_wrong_type": "the geometry is not one of {types}",
}

FLAG_MEANING = {
    "hierarchy_consistent": "TRUE when every parent code matches its pattern and the chain holds: `adm3_pcode` starts with "
                            "`adm2_pcode`, which starts with `adm1_pcode`. FALSE is a WARN; the row is kept",
    "geometry_is_valid": "TRUE when the parsed shape is valid (no self-intersection, closed rings). An invalid shape is "
                         "kept and never repaired; FALSE is a WARN",
    "center_inside_geometry": "TRUE when the published centre point (`center_lon`, `center_lat`) lies inside the published "
                              "shape. FALSE is a WARN",
}


def _reason_meaning(spec, reason):
    ident = spec.identifier
    for suffix in ("_blank", "_malformed", "_duplicated"):
        if reason == ident + suffix:
            return QUARANTINE_MEANING[suffix].format(ident=ident, pattern=spec.identifier_pattern)
    if reason in QUARANTINE_MEANING:
        return QUARANTINE_MEANING[reason].format(types=", ".join(spec.mapping["geometry"]["allowed_types"]))
    for d in spec.decimals:
        if reason == d.reason:
            names = [x.name for x in spec.decimals if x.reason == reason]
            return f"{', '.join(f'`{n}`' for n in names)} is not blank and does not fit its type exactly"
        if d.positive and reason == d.reason.replace("_uncastable", "") + "_not_positive":
            return f"`{d.name}` is zero or negative"
    return ""


def dictionary_markdown(spec):
    m = spec.mapping
    rows = []
    for name, kind in spec.columns:
        if kind == "identifier":
            rule, null, finding = m["identifier"]["note"], "Never", m["identifier"].get("finding", "")
        elif kind == "code":
            rule = f"Kept exactly as published; pattern `{spec.codes[name]}`. Part of `hierarchy_consistent`"
            null, finding = "Published blank", m["code_columns"].get("finding", "")
        elif kind == "free_text" and name in m["blank_columns"]["columns"]:
            rule, null, finding = m["blank_columns"]["note"], "Published blank (all rows in v03)", m["blank_columns"].get("finding", "")
        elif kind == "free_text":
            rule, null, finding = m["free_text_note"], "Published blank", ""
        elif kind == "category":
            entry = m["categories"][name]
            rule = (f"Whitespace normalized, mapped to the standard set ({len(entry['standard'])} value{'s' if len(entry['standard']) != 1 else ''}); an unmapped "
                    f"label fails the gate. {entry.get('rule', '')}")
            null, finding = "Published blank", entry.get("finding", "")
        elif kind == "date":
            rule = "`YYYY-MM-DD` text to DATE; anything else quarantines the row"
            null, finding = "Published blank", m["date_columns"].get("finding", "")
        elif kind == "decimal":
            d = next(x for x in spec.decimals if x.name == name)
            rule = (f"Published text to {d.type} only when it fits exactly (pattern `{d.pattern}`), so no digit is "
                    f"rounded; otherwise the row is quarantined ({d.reason}). {d.evidence}")
            null, finding = "Published blank", m["decimal_columns"].get("finding", "")
        else:
            rule = ("The published GeoJSON text, unchanged: never simplified, reprojected, or repaired. Parsed by the "
                    "build and the gate; parse with `try_to_geometry` (Databricks) or `ST_GeomFromGeoJSON` (DuckDB spatial)")
            null, finding = "Never (the row is quarantined)", m["geometry"].get("finding", "")
        rows.append((name, spec.silver_type(name).upper(), f"`{name}`", rule, null, finding))
    rows += [(f, "BOOLEAN", "computed", FLAG_MEANING[f], "Never", "") for f in FLAGS]
    rows += [(name, kind.upper(), "provenance" if name not in ("run_id", "cleaned_at_utc", "code_revision") else "Silver run",
              LINEAGE_MEANING[name], "Never", "") for name, kind in spec.clean_columns() if name in LINEAGE_MEANING]

    lines = [
        f"# `{spec.clean_table}`: Silver data dictionary",
        "",
        f"Generated by `python -m src.silver.cli dictionary --source {spec.source_id}` from "
        f"[the Bronze contract](../../../config/ingestion/{spec.source_id}.json) and "
        f"[the Silver rules](../../../config/mappings/{spec.source_id}.json). Do not edit by hand; "
        "`tests/test_silver_hdx.py` fails if it differs.",
        "",
        f"`` edu_access.`03-silver`.{spec.clean_table} ``: one row per COD-AB ADM3 unit (city or municipality) for the "
        "current delivery of each reference date only (`01-control`.current_batches). Key: "
        f"(`{spec.identifier}`, `valid_on`). Every row names the Bronze feature it came from (`source_sha256`, "
        "`source_row_number`), so each published value can be read back from Bronze.",
        "",
        f"`{spec.identifier}` is a COD-AB P-code, **not** a PSGC code: some code numbers name a different unit in PSGC. "
        "Matching to PSGC is Integration's job, by code and name together (docs/governance/limitations.md).",
        "",
        "**NULL** never means zero: a blank published value stays NULL.",
        "",
        "## Columns",
        "",
        "| Column | Type | Bronze source | Rule | NULL means | Finding |",
        "|---|---|---|---|---|---|",
    ]
    lines += [f"| `{name}` | {kind} | {source} | {rule} | {null} | {finding} |" for name, kind, source, rule, null, finding in rows]
    lines += [
        "",
        f"## `{spec.quarantine_table}`",
        "",
        "Features that cannot be trusted, set aside rather than deleted. Every feature of a current batch is in "
        "exactly one of the two tables. Read the published values from Bronze with `source_sha256` and "
        "`source_row_number`.",
        "",
        "| Column | Type | Meaning |",
        "|---|---|---|",
        f"| `{spec.identifier}` | STRING | As published |",
        "| `quarantine_reasons` | `ARRAY<STRING>` | Every reason that applies, never empty (below) |",
    ]
    lines += [f"| `{name}` | {kind.upper()} | {LINEAGE_MEANING[name]} |"
              for name, kind in spec.quarantine_columns() if name in LINEAGE_MEANING]
    lines += ["", "| Reason | Meaning |", "|---|---|"]
    lines += [f"| `{r}` | {_reason_meaning(spec, r)} |" for r in spec.quarantine_reasons]
    lines.append("")
    return "\n".join(lines)
