"""Generate the DepEd school-to-PSGC crosswalk's Silver build, gate, and data dictionary (D-049, #163).

The EMISD workbook (`deped_enrollment_psgc`) is used only for DepEd's own PSGC code per school. Silver
keeps one row per `school_id` from the Bronze rows of kind `unit`: the codes padded to 10 digits, a
reason wherever a code is missing, Sulu's Q4 2024 codes recoded to PSGC 2Q 2026, and the coordinates
typed and flagged. It carries none of the workbook's enrollment counts, and it makes no check against
psa_psgc: the code match is Integration's (#44).
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from src.ingestion.bronze import OWNER_GROUP, source_columns
from src.ingestion.contract import load_source_config
from src.ingestion.errors import IngestionError
from src.silver.generators import REPO_ROOT
from src.silver.sql import CONTROL, candidate_comment, dq_table_name, joined, lit, silver_ref

SOURCE_ID = "deped_enrollment_psgc"
LINEAGE = ("batch_id", "delivery_version", "schema_version", "source_sha256", "source_row_number")
STAMP = ("run_id", "cleaned_at_utc", "code_revision")
REASONS = ("school_id_malformed", "school_id_duplicated", "school_id_identical_copy")
LEVELS = ("region", "province", "city_municipality", "barangay")
FLAGS = ("missing", "zero", "outside_philippines")
# Profiled counts recorded by the gate: PASS at the count, WARN when it changes, never FAIL.
PROFILED_BASE = ("bronze_unit_rows", "bronze_other_rows", "barangay_codes_padded", "city_source_na", "city_not_in_workbook",
                 "barangay_source_na", "barangay_not_in_workbook", "recoded", "barangay_outside_city",
                 "coordinate_missing", "coordinate_zero", "coordinate_outside_philippines")
PROFILED = (*PROFILED_BASE, *[f"quarantine_{r}" for r in REASONS])


def _error(message):
    return IngestionError("config", "invalid_silver_mapping", message)


@dataclass
class CrosswalkSpec:
    source_id: str
    bronze_table: str
    clean_file: str
    clean_table: str
    quarantine_table: str
    clean_candidate: str
    quarantine_candidate: str
    row_kind: str
    identifier: str
    identifier_pattern: str
    codes: dict
    recode: dict
    coordinates: dict
    published_text: list
    quarantine_max_percent: float
    profiled: dict
    content_columns: list
    mapping: dict = field(repr=False)
    # Optional scope (deped_psgc_coordinates): rows whose column is not one of the values are quarantined
    # with the rule's reason, never dropped. Empty for a source that keeps every unit row.
    scope: list = field(default_factory=list)
    # Optional columns (deped_psgc_coordinates). combined_null_reason: one psgc_null_reason instead of one per
    # level; the gate fails if the levels' reasons ever differ, so nothing is lost. keep_published_coordinates:
    # False leaves the exact coordinate text in Bronze only; the gate still recomputes each number from Bronze.
    combined_null_reason: bool = False
    keep_published_coordinates: bool = True

    @property
    def value_columns(self):
        reasons = (("psgc_null_reason",) if self.combined_null_reason
                   else ("psgc_city_municipality_null_reason", "psgc_barangay_null_reason"))
        published = ("longitude_published", "latitude_published") if self.keep_published_coordinates else ()
        return ("school_year", "school_id", *[f"psgc_{level}" for level in LEVELS], "psgc_recoded", *reasons,
                "barangay_outside_city", "longitude", "latitude", *published, "coordinate_flag")

    @property
    def reasons(self):
        return (*REASONS, *[rule["reason"] for rule in self.scope])

    @property
    def profiled_names(self):
        return (*PROFILED_BASE, *[f"quarantine_{r}" for r in self.reasons])


def load_spec(repo_root=REPO_ROOT, source_id=SOURCE_ID):
    root = Path(repo_root)
    mapping = json.loads((root / "config" / "mappings" / f"{source_id}.json").read_text(encoding="utf-8"))
    contract, _ = load_source_config(root, source_id)
    registry = yaml.safe_load((root / "config" / "tables.yml").read_text(encoding="utf-8"))
    entry = next((s for s in registry["source_tables"] if s["source_id"] == source_id), None)
    silver = (entry or {}).get("silver", {})
    columns = source_columns(contract)
    if mapping.get("source_id") != contract["source_id"]:
        raise _error("source_id differs from the Bronze contract.")
    if silver.get("table") != mapping["silver_table"] or silver.get("quarantine_table") != mapping["quarantine_table"]:
        raise _error("Silver tables must match config/tables.yml.")
    codes, coords = mapping["codes"], mapping["coordinates"]
    if codes["columns"] != [f"psgc_{level}" for level in LEVELS]:
        raise _error("codes.columns must be the four PSGC levels, region to barangay.")
    named = [mapping["identifier"]["column"], *codes["columns"], coords["longitude"], coords["latitude"], *mapping["published_text"]]
    missing = [c for c in named if c not in columns]
    if missing:
        raise _error(f"the mapping names columns that are not in the Bronze contract: {missing}.")
    scope = mapping.get("scope", [])
    for rule in scope:
        if set(rule) != {"column", "values", "reason"} or not rule["values"]:
            raise _error("each scope rule must give column, a non-empty list of values, and reason.")
        if rule["column"] != "school_year" and rule["column"] not in columns:
            raise _error(f"scope column {rule['column']!r} is not in the Bronze contract.")
        if rule["reason"] in REASONS:
            raise _error(f"scope reason {rule['reason']!r} repeats a built-in reason.")
    names = (*PROFILED_BASE, *[f"quarantine_{r}" for r in (*REASONS, *[rule["reason"] for rule in scope])])
    if sorted(mapping["profiled"]) != sorted(names):
        raise _error(f"profiled must give a count for exactly {sorted(names)}.")
    if set(codes["null_markers"].values()) != {"source_na", "not_in_workbook"}:
        raise _error("codes.null_markers must map to the reasons source_na and not_in_workbook.")
    return CrosswalkSpec(source_id, contract["bronze_table"], silver["clean_file"], mapping["silver_table"],
                         mapping["quarantine_table"], silver["candidate_table"], silver["candidate_quarantine_table"],
                         mapping["row_kind"], mapping["identifier"]["column"], mapping["identifier"]["pattern"],
                         codes, mapping["recode"], coords, mapping["published_text"],
                         mapping["quarantine_max_percent"], mapping["profiled"], columns, mapping, scope,
                         bool(mapping.get("combined_null_reason", False)), bool(mapping.get("keep_published_coordinates", True)))


def _header(spec, name, command, path):
    return [f"-- {name} for {spec.source_id}. Generated from config/ingestion/{spec.source_id}.json",
            f"-- and config/mappings/{spec.source_id}.json:",
            f"--   python -m src.silver.cli {command} --source {spec.source_id} > etl/03_silver/{path}",
            "-- Do not edit by hand; tests/test_silver.py fails if it differs."]


def _null_reason(spec, column, alias="r"):
    """The reason a code is NULL: a listed marker's reason, or 'unrecognized' (which fails the gate)."""
    cases = " ".join(f"WHEN {alias}.{column} = {lit(marker)} THEN {lit(reason)}" for marker, reason in spec.codes["null_markers"].items())
    return f"CASE WHEN {alias}.{column} IS NULL THEN 'not_in_workbook' {cases} ELSE 'unrecognized' END"


def _padded(spec, column, alias="r"):
    return (f"CASE WHEN regexp_like({alias}.{column}, {lit(spec.codes['stored_pattern'])}) "
            f"THEN lpad({alias}.{column}, {spec.codes['length']}, '0') END")


def _number(spec, column, alias="r"):
    return f"CASE WHEN regexp_like({alias}.{column}, {lit(spec.coordinates['number_pattern'])}) THEN TRY_CAST({alias}.{column} AS DOUBLE) END"


# Value columns of a clean row, in table order. The build writes them; the gate recomputes each from its
# Bronze row with the same expressions and fails on any difference (values_reconcile).
VALUE_COLUMNS = ("school_year", "school_id", *[f"psgc_{level}" for level in LEVELS], "psgc_recoded",
                 "psgc_city_municipality_null_reason", "psgc_barangay_null_reason", "barangay_outside_city",
                 "longitude", "latitude", "longitude_published", "latitude_published", "coordinate_flag")


def _out_of_scope(rule, ref):
    """TRUE when a row is outside one scope rule: its value is missing or not one of the rule's values."""
    return f"({ref} IS NULL OR {ref} NOT IN ({', '.join(lit(v) for v in rule['values'])}))"


def _stage_padded(spec):
    """From a Bronze row (alias r): the codes padded, the null reasons, the coordinates typed and as published."""
    lon, lat = spec.coordinates["longitude"], spec.coordinates["latitude"]
    return ["r.school_year", f"r.{spec.identifier} AS school_id",
            *[f"{_padded(spec, 'psgc_' + level)} AS {level}_padded" for level in LEVELS],
            f"{_null_reason(spec, 'psgc_city_municipality')} AS city_reason_if_null",
            f"{_null_reason(spec, 'psgc_barangay')} AS barangay_reason_if_null",
            f"{_number(spec, lon)} AS longitude", f"{_number(spec, lat)} AS latitude",
            *([f"r.{lon} AS longitude_published", f"r.{lat} AS latitude_published"] if spec.keep_published_coordinates else []),
            *[f"r.{c}" for c in spec.published_text]]


def _stage_recoded(spec):
    """The Sulu flag, from the padded province code (alias c)."""
    recode = spec.recode
    return f"COALESCE(substr(c.province_padded, 1, {len(recode['province_prefix'])}) = {lit(recode['province_prefix'])}, FALSE) AS psgc_recoded"


def _stage_final(spec):
    """The clean row's value columns (alias c), in VALUE_COLUMNS order, then the published text."""
    recode, box = spec.recode, spec.coordinates["box"]
    prefix, n = recode["province_prefix"], len(recode["province_prefix"])

    def swap(ref):
        # Only a code that itself starts with the Sulu prefix is recoded, so a code pointing elsewhere is kept.
        return (f"CASE WHEN c.psgc_recoded AND substr({ref}, 1, {n}) = {lit(prefix)} "
                f"THEN concat({lit(recode['to_prefix'])}, substr({ref}, {n + 1})) ELSE {ref} END")
    return [
        "c.school_year", "c.school_id",
        f"CASE WHEN c.psgc_recoded AND c.region_padded = {lit(recode['from_region'])} THEN {lit(recode['region'])} ELSE c.region_padded END AS psgc_region",
        f"{swap('c.province_padded')} AS psgc_province",
        f"{swap('c.city_municipality_padded')} AS psgc_city_municipality",
        f"{swap('c.barangay_padded')} AS psgc_barangay",
        "c.psgc_recoded",
        *(["CASE WHEN c.city_municipality_padded IS NULL THEN c.city_reason_if_null "
           "WHEN c.barangay_padded IS NULL THEN c.barangay_reason_if_null END AS psgc_null_reason"]
          if spec.combined_null_reason else
          ["CASE WHEN c.city_municipality_padded IS NULL THEN c.city_reason_if_null END AS psgc_city_municipality_null_reason",
           "CASE WHEN c.barangay_padded IS NULL THEN c.barangay_reason_if_null END AS psgc_barangay_null_reason"]),
        "COALESCE(substr(c.barangay_padded, 1, 7) <> substr(c.city_municipality_padded, 1, 7), FALSE) AS barangay_outside_city",
        "c.longitude", "c.latitude", *(["c.longitude_published", "c.latitude_published"] if spec.keep_published_coordinates else []),
        "CASE WHEN c.longitude IS NULL OR c.latitude IS NULL THEN 'missing' WHEN c.longitude = 0 AND c.latitude = 0 THEN 'zero' "
        f"WHEN NOT (c.longitude BETWEEN {box['longitude_min']} AND {box['longitude_max']} AND c.latitude BETWEEN {box['latitude_min']} AND {box['latitude_max']}) "
        "THEN 'outside_philippines' END AS coordinate_flag",
        *[f"c.{p}" for p in spec.published_text],
    ]


def build_sql(spec):
    source = spec.source_id
    clean, quarantine = silver_ref(spec.clean_candidate), silver_ref(spec.quarantine_candidate)
    content = "md5(concat_ws('|', " + ", ".join(f"COALESCE(r.{c}, '')" for c in spec.content_columns) + "))"
    coded = [
        *_stage_padded(spec),
        "g.id_rows", "g.id_versions",
        f"ROW_NUMBER() OVER (PARTITION BY r.school_year, r.{spec.identifier} ORDER BY r.source_row_number) AS id_copy",
        *[f"r.{c}" for c in LINEAGE],
        *[f"r.{rule['column']} AS scope_{rule['column']}" for rule in spec.scope],
    ]
    typed = [
        *_stage_final(spec),
        "concat_ws(',',\n" + joined([
            f"CASE WHEN NOT regexp_like(c.school_id, {lit(spec.identifier_pattern)}) THEN 'school_id_malformed' END",
            "CASE WHEN c.id_rows > 1 AND c.id_versions > 1 THEN 'school_id_duplicated' END",
            "CASE WHEN c.id_rows > 1 AND c.id_versions = 1 AND c.id_copy > 1 THEN 'school_id_identical_copy' END",
            *[f"CASE WHEN {_out_of_scope(rule, 'c.scope_' + rule['column'])} THEN {lit(rule['reason'])} END" for rule in spec.scope],
        ], 6) + "\n    ) AS quarantine_reasons",
        *[f"c.{x}" for x in LINEAGE],
    ]
    recoded = _stage_recoded(spec)
    clean_columns = [*spec.value_columns, *spec.published_text, *LINEAGE,
                     *[f"session.silver_{c} AS {c}" for c in STAMP]]
    quarantine_columns = ["school_year", "school_id", "split(quarantine_reasons, ',') AS quarantine_reasons",
                          *LINEAGE, *[f"session.silver_{c} AS {c}" for c in STAMP]]
    lines = _header(spec, "Silver build", "sql", spec.clean_file) + [
        "-- Builds unpublished candidate tables. The gate publishes them only after every FAIL check is zero.", "",
        "DECLARE OR REPLACE VARIABLE silver_run_id STRING;", "SET VARIABLE silver_run_id = :run_id;",
        "DECLARE OR REPLACE VARIABLE silver_code_revision STRING;", "SET VARIABLE silver_code_revision = COALESCE(NULLIF(:code_revision, ''), 'UNSET');",
        "DECLARE OR REPLACE VARIABLE silver_environment STRING;", "SET VARIABLE silver_environment = COALESCE(NULLIF(:environment, ''), 'UNSET');",
        "DECLARE OR REPLACE VARIABLE silver_cleaned_at_utc TIMESTAMP;", "SET VARIABLE silver_cleaned_at_utc = current_timestamp();", "",
        f"MERGE INTO {CONTROL}.pipeline_runs AS t", "USING (SELECT session.silver_run_id AS run_id) AS s",
        f"ON t.run_id = s.run_id AND t.pipeline_name = 'silver_build' AND t.source_id = {lit(source)}",
        "WHEN MATCHED THEN UPDATE SET status = 'running', started_at_utc = session.silver_cleaned_at_utc, finished_at_utc = NULL, failure_stage = NULL, error_message = NULL, code_revision = session.silver_code_revision, job_run_id = s.run_id",
        "WHEN NOT MATCHED THEN INSERT (run_id, pipeline_name, source_id, environment, status, started_at_utc, code_revision, job_run_id)",
        f"  VALUES (s.run_id, 'silver_build', {lit(source)}, session.silver_environment, 'running', session.silver_cleaned_at_utc, session.silver_code_revision, s.run_id);", "",
        "CREATE SCHEMA IF NOT EXISTS edu_access.`03-silver`;", f"ALTER SCHEMA edu_access.`03-silver` OWNER TO `{OWNER_GROUP}`;", "",
        "-- Only rows of kind unit are schools; blank and no_identifier rows stay in Bronze (D-049).",
        f"CREATE OR REPLACE TEMPORARY VIEW {source}_classified AS", "WITH bronze AS (",
        f"  SELECT r.* FROM edu_access.`02-bronze`.{spec.bronze_table} AS r JOIN {CONTROL}.current_batches AS b ON r.batch_id = b.batch_id",
        f"  WHERE b.source_id = {lit(source)} AND r.source_row_kind = {lit(spec.row_kind)}",
        "), ids AS (",
        "  -- How many rows share a school_id, and how many different versions of the row there are.",
        f"  SELECT r.school_year, r.{spec.identifier}, COUNT(*) AS id_rows, COUNT(DISTINCT {content}) AS id_versions",
        f"  FROM bronze AS r GROUP BY r.school_year, r.{spec.identifier}",
        "), coded AS (", "  SELECT", joined(coded, 4),
        f"  FROM bronze AS r JOIN ids AS g ON g.school_year = r.school_year AND g.{spec.identifier} = r.{spec.identifier}",
        "), recoded AS (",
        f"  SELECT c.*, {recoded} FROM coded AS c",
        ")", "SELECT", joined(typed, 2), "FROM recoded AS c;", "",
        f"CREATE OR REPLACE TABLE {clean} USING DELTA AS", "SELECT", joined(clean_columns, 2),
        f"FROM {source}_classified WHERE quarantine_reasons = '';", "",
        candidate_comment(clean, spec.clean_table), f"ALTER TABLE {clean} OWNER TO `{OWNER_GROUP}`;", "",
        f"CREATE OR REPLACE TABLE {quarantine} USING DELTA AS", "SELECT", joined(quarantine_columns, 2),
        f"FROM {source}_classified WHERE quarantine_reasons <> '';", "",
        candidate_comment(quarantine, spec.quarantine_table), f"ALTER TABLE {quarantine} OWNER TO `{OWNER_GROUP}`;", ""]
    return "\n".join(lines)


def _checks(spec):
    """(check name, status on failure, actual column, condition) in the order the gate writes them."""
    p = spec.profiled
    fail = [
        ("current_batch_present", "FAIL", "current_batches", "> 0"),
        ("rows_reconcile", "FAIL", "clean_rows + quarantine_rows", "= bronze_unit_rows"),
        ("rows_resolve_to_current_bronze", "FAIL", "unresolved_rows", "= 0"),
        ("values_reconcile", "FAIL", "value_mismatches", "= 0"),
        ("coordinates_reconcile", "FAIL", "coordinate_mismatches", "= 0"),
        ("school_id_unique", "FAIL", "duplicate_clean_ids", "= 0"),
        ("school_id_format", "FAIL", "malformed_clean_ids", "= 0"),
        ("codes_ten_digits", "FAIL", "codes_not_ten_digits", "= 0"),
        ("code_values_recognized", "FAIL", "unrecognized_code_values", "= 0"),
        ("region_province_values_recognized", "FAIL", "unrecognized_region_province", "= 0"),
        ("null_reason_matches_code", "FAIL", "null_reason_mismatches", "= 0"),
        *([("null_reasons_agree", "FAIL", "null_reasons_differ", "= 0")] if spec.combined_null_reason else []),
        ("levels_null_together", "FAIL", "levels_not_null_together", "= 0"),
        ("coordinates_in_pairs", "FAIL", "coordinates_not_in_pairs", "= 0"),
        ("coordinate_values_recognized", "FAIL", "unrecognized_coordinates", "= 0"),
        ("lineage_complete", "FAIL", "missing_lineage", "= 0"),
        ("rows_built_by_this_run", "FAIL", "other_run_rows", "= 0"),
        *([("rows_in_scope", "FAIL", "out_of_scope_clean_rows", "= 0")] if spec.scope else []),
    ]
    profiled = [(f"profiled_{name}", "WARN", name, f"= {p[name]}") for name in spec.profiled_names]
    return fail + profiled


def _null_safe(item):
    """COUNT_IF over rows whose condition is NULL in every row gives NULL in DuckDB, so a check comparing it
    with 0 would fail on a clean build; every single-subquery count reads 0 instead."""
    start = "(SELECT COUNT_IF("
    if not item.startswith(start):
        return item
    head, _, tail = item.rpartition(") FROM ")
    return "(SELECT COALESCE(COUNT_IF(" + head[len(start):] + "), 0) FROM " + tail


def _level_reason(spec, level):
    """The reason a level's code is NULL, read from the clean row: its own column, or the combined one."""
    if spec.combined_null_reason:
        return f"CASE WHEN psgc_{level} IS NULL THEN psgc_null_reason END"
    return f"psgc_{level}_null_reason"


def _reason_counts(spec):
    """unrecognized_code_values, null_reason_mismatches and, with a combined reason, null_reasons_differ."""
    unrecognized = " OR ".join(f"{_level_reason(spec, level)} = 'unrecognized'" for level in ("city_municipality", "barangay"))
    if spec.combined_null_reason:
        mismatch = ("(psgc_city_municipality IS NULL OR psgc_barangay IS NULL) <> (psgc_null_reason IS NOT NULL)")
    else:
        mismatch = ("(psgc_city_municipality IS NULL) <> (psgc_city_municipality_null_reason IS NOT NULL) "
                    "OR (psgc_barangay IS NULL) <> (psgc_barangay_null_reason IS NOT NULL)")
    counts = [f"(SELECT COUNT_IF({unrecognized}) FROM c) AS unrecognized_code_values",
              f"(SELECT COUNT_IF({mismatch}) FROM c) AS null_reason_mismatches"]
    if spec.combined_null_reason:
        # Both levels NULL for different reasons (e.g. city '#N/A', barangay blank): one column could not say both.
        counts.append(f"(SELECT COUNT_IF({_padded(spec, 'psgc_city_municipality', 'u')} IS NULL AND {_padded(spec, 'psgc_barangay', 'u')} IS NULL "
                      f"AND {_null_reason(spec, 'psgc_city_municipality', 'u')} <> {_null_reason(spec, 'psgc_barangay', 'u')}) FROM unit AS u) AS null_reasons_differ")
    return counts


def gate_sql(spec):
    source = spec.source_id
    clean, quarantine = silver_ref(spec.clean_candidate), silver_ref(spec.quarantine_candidate)
    summary = silver_ref(f"{source}_gate_summary_candidate")
    clean_name, quarantine_name = dq_table_name(spec.clean_candidate), dq_table_name(spec.quarantine_candidate)
    lon, lat = spec.coordinates["longitude"], spec.coordinates["latitude"]
    markers = ", ".join(lit(m) for m in spec.coordinates["missing_markers"])
    number = lit(spec.coordinates["number_pattern"])
    stored = lit(spec.codes["stored_pattern"])
    codes = [f"psgc_{level}" for level in LEVELS]
    every_lineage = " OR ".join(f"x.{v} IS NULL" for v in [*LINEAGE, *STAMP])
    code_markers = ", ".join(lit(m) for m in spec.codes["null_markers"])
    keys = ("batch_id", "source_sha256", "source_row_number")

    def unrecognized(column):
        return f"(u.{column} IS NOT NULL AND u.{column} NOT IN ({code_markers}) AND NOT regexp_like(u.{column}, {stored}))"
    value_differs = " OR ".join(f"c.{x} IS DISTINCT FROM e.{x}" for x in [*spec.value_columns, *spec.published_text])
    unions = []
    for name, failure, actual, condition in _checks(spec):
        table = quarantine_name if name.startswith("profiled_quarantine_") else clean_name
        status = f"CASE WHEN {actual} {condition} THEN 'PASS' ELSE '{failure}' END"
        unions.append(f"SELECT batch_id, {lit(table)} AS table_name, {lit(name)} AS check_name, {status} AS status, "
                      f"{lit(condition.lstrip('= ') if failure == 'WARN' else condition)} AS expected, CAST({actual} AS STRING) AS actual FROM {summary}")
    unions.append(f"SELECT batch_id, {lit(quarantine_name)}, 'quarantine_rate', CASE WHEN quarantine_rows = 0 THEN 'PASS' "
                  f"WHEN quarantine_rows * 100 > bronze_unit_rows * {spec.quarantine_max_percent} THEN 'FAIL' ELSE 'WARN' END, "
                  f"'0 (FAIL above {spec.quarantine_max_percent}% of ' || CAST(bronze_unit_rows AS STRING) || ')', CAST(quarantine_rows AS STRING) FROM {summary}")
    union_sql = ("\n  UNION ALL ").join(unions)
    counts = [
        "(SELECT COUNT(*) FROM cur) AS current_batches",
        "(SELECT COUNT(*) FROM s LEFT JOIN unit AS u ON u.batch_id = s.batch_id AND u.source_sha256 = s.source_sha256 "
        "AND u.source_row_number = s.source_row_number WHERE u.source_row_number IS NULL) "
        "+ (SELECT COUNT(*) - COUNT(DISTINCT (source_sha256, source_row_number)) FROM s) AS unresolved_rows",
        f"(SELECT COUNT(*) FROM c JOIN expected AS e ON e.source_sha256 = c.source_sha256 AND e.source_row_number = c.source_row_number "
        f"WHERE {value_differs}) AS value_mismatches",
        f"(SELECT COUNT(*) FROM c JOIN unit AS b ON b.source_sha256 = c.source_sha256 AND b.source_row_number = c.source_row_number "
        "WHERE " + (f"c.longitude_published IS DISTINCT FROM b.{lon} OR c.latitude_published IS DISTINCT FROM b.{lat} OR "
                    if spec.keep_published_coordinates else "") +
        f"c.longitude IS DISTINCT FROM {_number(spec, lon, 'b')} OR c.latitude IS DISTINCT FROM {_number(spec, lat, 'b')}) AS coordinate_mismatches",
        f"(SELECT COUNT_IF({unrecognized('psgc_region')} OR {unrecognized('psgc_province')}) FROM unit AS u) AS unrecognized_region_province",
        f"(SELECT COUNT_IF(source_row_kind = {lit(spec.row_kind)}) FROM bronze) AS bronze_unit_rows",
        f"(SELECT COUNT_IF(source_row_kind <> {lit(spec.row_kind)}) FROM bronze) AS bronze_other_rows",
        "(SELECT COUNT(*) FROM c) AS clean_rows",
        "(SELECT COUNT(*) FROM q) AS quarantine_rows",
        "(SELECT COUNT(*) - COUNT(DISTINCT (school_year, school_id)) FROM c) AS duplicate_clean_ids",
        f"(SELECT COUNT_IF(NOT regexp_like(school_id, {lit(spec.identifier_pattern)})) FROM c) AS malformed_clean_ids",
        "(SELECT COUNT_IF(" + " OR ".join(f"({x} IS NOT NULL AND NOT regexp_like({x}, '^[0-9]{{{spec.codes['length']}}}$'))" for x in codes) + ") FROM c) AS codes_not_ten_digits",
        *(_reason_counts(spec)),
        "(SELECT COUNT_IF((psgc_region IS NULL) <> (psgc_city_municipality IS NULL) OR (psgc_province IS NULL) <> (psgc_city_municipality IS NULL)) FROM c) AS levels_not_null_together",
        "(SELECT COUNT_IF((longitude IS NULL) <> (latitude IS NULL)) FROM c) AS coordinates_not_in_pairs",
        f"(SELECT COUNT_IF(source_row_kind = {lit(spec.row_kind)} AND ("
        f"(b.{lon} NOT IN ({markers}) AND NOT regexp_like(b.{lon}, {number})) OR (b.{lat} NOT IN ({markers}) AND NOT regexp_like(b.{lat}, {number})))) FROM bronze AS b) AS unrecognized_coordinates",
        f"(SELECT COALESCE(COUNT_IF({every_lineage}), 0) FROM c AS x) + (SELECT COALESCE(COUNT_IF({every_lineage}), 0) FROM q AS x) AS missing_lineage",
        "(SELECT COALESCE(COUNT_IF(run_id <> :run_id), 0) FROM c) + (SELECT COALESCE(COUNT_IF(run_id <> :run_id), 0) FROM q) AS other_run_rows",
        f"(SELECT COUNT_IF(source_row_kind = {lit(spec.row_kind)} AND regexp_like(b.psgc_barangay, {stored}) AND length(b.psgc_barangay) < {spec.codes['length']}) FROM bronze AS b) AS barangay_codes_padded",
        *[f"(SELECT COUNT_IF({_level_reason(spec, level)} = {lit(reason)}) FROM c) AS {prefix}_{reason}"
          for level, prefix in (("city_municipality", "city"), ("barangay", "barangay")) for reason in ("source_na", "not_in_workbook")],
        "(SELECT COUNT_IF(psgc_recoded) FROM c) AS recoded",
        "(SELECT COUNT_IF(barangay_outside_city) FROM c) AS barangay_outside_city",
        *[f"(SELECT COUNT_IF(coordinate_flag = {lit(f)}) FROM c) AS coordinate_{f}" for f in FLAGS],
        *[f"(SELECT COUNT_IF(array_contains(quarantine_reasons, {lit(r)})) FROM q) AS quarantine_{r}" for r in spec.reasons],
        *([f"(SELECT COUNT(*) FROM c JOIN unit AS b ON b.source_sha256 = c.source_sha256 AND b.source_row_number = c.source_row_number "
           "WHERE " + " OR ".join(_out_of_scope(rule, 'b.' + rule['column']) for rule in spec.scope) + ") AS out_of_scope_clean_rows"]
          if spec.scope else []),
    ]
    counts = [_null_safe(item) for item in counts]
    lines = _header(spec, "Silver gate", "gate", f"90_validate_{spec.clean_table}.sql") + [
        "-- Records every rule count, stops before publishing on FAIL, then publishes quarantine before clean.", "",
        "DECLARE OR REPLACE VARIABLE silver_gate_started_at_utc TIMESTAMP;", "SET VARIABLE silver_gate_started_at_utc = current_timestamp();", "",
        "-- Materialize the aggregates once so every check reads the same one-row result.",
        f"CREATE OR REPLACE TABLE {summary} USING DELTA AS", "WITH cur AS (",
        f"  SELECT batch_id FROM {CONTROL}.current_batches WHERE source_id = {lit(source)}", "), bronze AS (",
        f"  SELECT b.* FROM edu_access.`02-bronze`.{spec.bronze_table} AS b JOIN cur ON b.batch_id = cur.batch_id",
        f"), unit AS (", f"  SELECT * FROM bronze WHERE source_row_kind = {lit(spec.row_kind)}",
        "), expected_padded AS (",
        "  -- Every value recomputed from its Bronze row with the build's own expressions.",
        "  SELECT", joined([*_stage_padded(spec), *[f"r.{k}" for k in keys]], 4), "  FROM unit AS r",
        f"), expected_recoded AS (", f"  SELECT c.*, {_stage_recoded(spec)} FROM expected_padded AS c",
        "), expected AS (", "  SELECT", joined([*_stage_final(spec), *[f"c.{k}" for k in keys]], 4), "  FROM expected_recoded AS c",
        "), c AS (", f"  SELECT * FROM {clean}", "), q AS (", f"  SELECT * FROM {quarantine}",
        "), s AS (", f"  SELECT {', '.join(keys)} FROM c UNION ALL SELECT {', '.join(keys)} FROM q",
        "), counts AS (", "  SELECT", joined(counts, 4), ")",
        "-- One row even when no batch is current, so current_batch_present can FAIL and nothing is published.",
        "SELECT (SELECT MIN(batch_id) FROM cur) AS batch_id, counts.* FROM counts;", "",
        f"ALTER TABLE {summary} OWNER TO `{OWNER_GROUP}`;", "",
        f"INSERT INTO {CONTROL}.data_quality_results (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)",
        f"SELECT :run_id, batch_id, {lit(source)}, 'silver', table_name, check_name, status, expected, actual, current_timestamp(), :code_revision FROM (",
        union_sql, ") AS results;", "",
        f"MERGE INTO {CONTROL}.pipeline_runs AS t USING (SELECT :run_id AS run_id, COUNT_IF(status = 'FAIL') AS fails FROM {CONTROL}.data_quality_results WHERE run_id = :run_id AND source_id = {lit(source)} AND layer = 'silver' AND checked_at_utc >= session.silver_gate_started_at_utc) AS s",
        f"ON t.run_id = s.run_id AND t.pipeline_name = 'silver_build' AND t.source_id = {lit(source)} WHEN MATCHED AND s.fails > 0 THEN UPDATE SET status = 'failed', finished_at_utc = current_timestamp(), failure_stage = 'gate', error_message = CAST(s.fails AS STRING) || ' FAIL result(s) in data_quality_results';", "",
        f"SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Silver gate failed for {source}: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s)') END FROM {CONTROL}.data_quality_results WHERE run_id = :run_id AND source_id = {lit(source)} AND layer = 'silver' AND status = 'FAIL' AND checked_at_utc >= session.silver_gate_started_at_utc;", "",
        f"CREATE OR REPLACE TABLE {silver_ref(spec.quarantine_table)} USING DELTA AS SELECT * FROM {quarantine};",
        f"ALTER TABLE {silver_ref(spec.quarantine_table)} OWNER TO `{OWNER_GROUP}`;", "",
        f"CREATE OR REPLACE TABLE {silver_ref(spec.clean_table)} USING DELTA AS SELECT * FROM {clean};",
        f"ALTER TABLE {silver_ref(spec.clean_table)} OWNER TO `{OWNER_GROUP}`;", "",
        f"MERGE INTO {CONTROL}.pipeline_runs AS t USING (SELECT :run_id AS run_id) AS s ON t.run_id = s.run_id AND t.pipeline_name = 'silver_build' AND t.source_id = {lit(source)} WHEN MATCHED THEN UPDATE SET status = 'succeeded', finished_at_utc = current_timestamp(), failure_stage = NULL, error_message = NULL;", "",
        f"DROP TABLE IF EXISTS {summary};", ""]
    return "\n".join(lines)


def gate_checks(spec):
    """Return every data-quality check written by the crosswalk gate."""
    return [name for name, _, _, _ in _checks(spec)] + ["quarantine_rate"]


def dictionary_markdown(spec):
    p = spec.profiled
    rows = ["| Column | Type | Meaning |", "|---|---|---|",
            "| `school_year` | `STRING` | School year of the approved Bronze batch (`2023-24`) |",
            "| `school_id` | `STRING` | Six-digit DepEd school ID; one row per school and school year |"]
    rows += [f"| `psgc_{level}` | `STRING` | DepEd's {level.replace('_', ' or ')} PSGC code for the school, left-padded to 10 digits; Sulu recoded to 2Q 2026 (see `psgc_recoded`). `NULL` when the workbook has none |"
             for level in LEVELS]
    rows += ["| `psgc_recoded` | `BOOLEAN` | `TRUE` when the province is Sulu's Q4 2024 code (`19066…`): each code that starts with `19066` became `09066…`, and region `1900000000` became `0900000000` |",
             "| `psgc_city_municipality_null_reason` | `STRING` | Why region, province, and city/municipality are `NULL`: `source_na` (`#N/A` in the workbook) or `not_in_workbook` (no value). `NULL` when the code is present |",
             "| `psgc_barangay_null_reason` | `STRING` | Why the barangay code is `NULL`, as above |",
             "| `barangay_outside_city` | `BOOLEAN` | The barangay code's first 7 digits differ from the city or municipality code (profile O-7). Kept as published |",
             "| `longitude`, `latitude` | `DOUBLE` | The published value as a number (NSBI, 2025-07-07), for maps and distances. `NULL` for `#N/A` or blank. Not corrected; Excel's float noise (e.g. `120.79600000000001`) reads as `120.796` |",
             "| `longitude_published`, `latitude_published` | `STRING` | The exact Bronze text, including `#N/A` and blank. The gate fails unless it equals Bronze and the `DOUBLE` equals its cast |",
             "| `coordinate_flag` | `STRING` | `missing`, `zero` (0, 0), `outside_philippines`, or `NULL`. Coordinates feed no Gold measure until the boundary test (S-1) |"]
    rows += [f"| `{c}` | `STRING` | Published `{c}` (Q4 2024 PSGC names; Sulu's still say BARMM after the code recode), unchanged. For PSGC names, use psa_psgc through the code |"
             if c.startswith("psgc_") else f"| `{c}` | `STRING` | Published `{c}`, unchanged |" for c in spec.published_text]
    rows += [f"| `{c}` | `{'INT' if c == 'delivery_version' else 'BIGINT' if c == 'source_row_number' else 'STRING'}` | Bronze lineage |" for c in LINEAGE]
    rows += ["| `run_id`, `cleaned_at_utc`, `code_revision` | `STRING`, `TIMESTAMP`, `STRING` | The Silver run that built the row |"]
    profiled = [f"| `{name}` | {p[name]:,} |" for name in PROFILED]
    return "\n".join([
        "# `deped_enrollment_psgc_clean`", "",
        "Generated from the reviewed contract and mapping (`config/mappings/deped_enrollment_psgc.json`):",
        "`python -m src.silver.cli dictionary --source deped_enrollment_psgc`. Do not edit by hand.", "",
        "DepEd's own PSGC code per school, from the EMISD workbook, for Integration to match DepEd schools by code first (D-049, #44). "
        "It is a crosswalk, not an enrollment table: enrollment counts come only from `deped_enrollment_clean`. "
        "Only Bronze rows of kind `unit` are read. Licensing is unverified: published outputs use the codes only to place schools in their city or municipality (D-049).", "",
        *rows, "",
        "## Quarantine", "",
        "`deped_enrollment_psgc_quarantine` keeps each school row Silver does not carry, with its reasons and Bronze lineage:", "",
        "- `school_id_malformed`: not 6 digits.",
        "- `school_id_identical_copy`: a repeated `school_id` whose rows are identical in every published column; the first copy (lowest Excel row) stays in Silver.",
        "- `school_id_duplicated`: a repeated `school_id` whose rows differ; every copy is quarantined.", "",
        "## Profiled counts", "",
        "The gate records each count: PASS at the profiled value, WARN when it changes, never FAIL.", "",
        "| Check | Profiled |", "|---|---|", *profiled, ""])
