"""DepEd facilities Silver: the spec, build, gate, and data dictionary (named by "generator" in its mapping).

Facilities has the same identifier, labels, and quarantine reasons as enrollment
(src/silver/spec.py, sql.py), but a different shape: no free text, counts in
named groups each with its own plausible maximum, sixty facility yes/no columns,
measures for public schools only, and location only through enrollment. So it
has its own module, reusing the shared SQL helpers (D-037).

Two reviewed files define it: config/ingestion/deped_facilities.json (the Bronze
contract) and config/mappings/deped_facilities.json (the Silver mapping). Every
publisher column must be classified exactly once, so a new column stops the
generator until the mapping is reviewed.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from src.ingestion.bronze import OWNER_GROUP, source_columns
from src.ingestion.contract import load_source_config
from src.ingestion.errors import IngestionError
from src.silver.spec import (
    BOOLEAN, CATEGORY, COUNT, IDENTIFIER, LINEAGE, QUARANTINE_REASONS, RUN_STAMP, SAFE_LITERAL, SCHEMA, TYPES,
    Category, Column,
)
from src.silver.sql import (
    CONTROL, NEGATIVE, any_of, as_bigint, bq, bronze_ref, candidate_comment, cleaned_text, dq_table_name, header,
    in_list, joined, lit, null_safe_sum, silver_ref, typed_count, whitespace, whole_number,
)

SOURCE_ID = "deped_facilities"
FLAGS = (("is_overseas", "boolean"), ("has_facility_data", "boolean"), ("es_classrooms_missing", "boolean"))
# Enrollment's reasons, then one of its own: a school enrollment Silver cannot place (O-2, D-037).
REASONS = (*QUARANTINE_REASONS, "school_id_not_in_enrollment")


def _error(message):
    return IngestionError("config", "invalid_silver_mapping", message)


@dataclass
class CountGroup:
    name: str
    plausible_max: int
    columns: list


@dataclass
class FacilitiesSpec:
    source_id: str
    bronze_table: str
    clean_file: str
    clean_table: str
    quarantine_table: str
    clean_candidate: str
    quarantine_candidate: str
    identifier: str
    identifier_pattern: str
    max_digits: int
    columns: list                      # publisher columns, in published order
    categories: dict                   # Silver column -> Category
    groups: list                       # [CountGroup]
    offering: list                     # the offers_* booleans
    boolean_true: list
    boolean_false: list
    overseas: dict                     # category column -> standard value meaning overseas
    public_column: str
    public_value: str
    missing_classrooms: str            # the count that is flagged when blank at a school offering its level
    missing_offered_by: str
    levels: dict                       # column prefix -> offers_* columns, any of which offers that level
    enrollment_table: str
    mapping: dict = field(repr=False)

    def of_kind(self, *kinds):
        return [c for c in self.columns if c.kind in kinds]

    @property
    def counts(self):
        return self.of_kind(COUNT)

    @property
    def text(self):
        """Columns cleaned as text before mapping: categories and booleans."""
        return self.of_kind(CATEGORY, BOOLEAN)

    @property
    def facility_booleans(self):
        return [c for c in self.of_kind(BOOLEAN) if c.name not in self.offering]

    @property
    def facility_columns(self):
        """The measures: every count and every facility yes/no column."""
        return [c for c in self.columns if c.kind == COUNT or c in self.facility_booleans]

    def column(self, name):
        return next(c for c in self.columns if c.name == name)

    def cap(self, name):
        return next(g.plausible_max for g in self.groups if name in g.columns)

    def level_columns(self, prefix):
        return [c for c in self.facility_columns if c.name.startswith(prefix)]

    def clean_columns(self):
        return [("school_year", "string"), *[(c.name, c.type) for c in self.columns], *FLAGS, *LINEAGE, *RUN_STAMP]

    def quarantine_columns(self):
        return ([("school_year", "string"), (self.identifier, "string"), ("quarantine_reasons", "array<string>")]
                + list(LINEAGE) + list(RUN_STAMP))


def load_spec(repo_root, source_id=SOURCE_ID):
    path = Path(repo_root) / "config" / "mappings" / f"{source_id}.json"
    mapping = json.loads(path.read_text(encoding="utf-8"))
    contract, _ = load_source_config(repo_root, source_id)
    registry = yaml.safe_load((Path(repo_root) / "config" / "tables.yml").read_text(encoding="utf-8"))
    entries = {s["source_id"]: s for s in registry["source_tables"]}
    return build_spec(mapping, contract, entries.get(source_id), entries.get(mapping["enrollment_reference"]["source_id"]))


def build_spec(mapping, contract, registry_entry, enrollment_entry):
    source_id = contract["source_id"]
    if mapping.get("source_id") != source_id:
        raise _error("source_id differs from the Bronze contract.")
    if registry_entry is None or registry_entry["silver"]["table"] != mapping["silver_table"] \
            or registry_entry["silver"]["quarantine_table"] != mapping["quarantine_table"]:
        raise _error("silver_table and quarantine_table must match config/tables.yml.")
    if enrollment_entry is None:
        raise _error("enrollment_reference names a source that is not in config/tables.yml.")
    published = source_columns(contract)
    for version, entry in contract["schema_versions"].items():
        if entry["columns"] != published:
            raise _error(f"schema {version} lacks columns another version has; facilities Silver does not "
                         "handle absent columns yet, so a new header needs a reviewed change to this generator.")
    for name in published:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
            raise _error(f"column {name!r} is not snake_case.")

    identifier = mapping["identifier"]["column"]
    categories = mapping["categories"]
    booleans = mapping["booleans"]
    offering = booleans["columns"]
    pattern = re.compile(booleans["facility_column_pattern"])
    groups = [CountGroup(name, g["plausible_max"], g["columns"]) for name, g in mapping["count_groups"]["groups"].items()]
    grouped = [c for g in groups for c in g.columns]
    max_digits = mapping["count_groups"]["max_digits"]

    kinds = {}
    for name in published:
        found = [kind for kind, member in (
            (IDENTIFIER, name == identifier), (CATEGORY, name in categories),
            (BOOLEAN, name in offering or bool(pattern.match(name))), (COUNT, name in grouped)) if member]
        if len(found) != 1 or grouped.count(name) > 1:
            raise _error(f"column {name!r} must be classified exactly once; found {found or 'none'}. "
                         "A new publisher column needs a reviewed entry in the Silver mapping.")
        kinds[name] = found[0]
    stray = sorted({identifier, *categories, *offering, *grouped} - set(published))
    if stray:
        raise _error(f"the mapping lists columns the contract does not have: {stray}.")
    for g in groups:
        if not (isinstance(g.plausible_max, int) and 0 < g.plausible_max < 10 ** max_digits):
            raise _error(f"{g.name}: plausible_max must be a whole number from 1 to {10 ** max_digits - 1}.")

    parsed = {}
    for name, entry in categories.items():
        standard, labels = entry["standard"], {}
        for label in entry["labels"]:
            if label["published"] in labels:
                raise _error(f"{name}: label {label['published']!r} is listed twice.")
            if label["standard"] not in standard:
                raise _error(f"{name}: {label['published']!r} maps to {label['standard']!r}, which is not in the standard set.")
            labels[label["published"]] = label["standard"]
        parsed[name] = Category(name, standard, labels, entry.get("finding", ""), entry.get("rule", ""))
    true, false = booleans["true"], booleans["false"]
    if set(true) & set(false):
        raise _error("a boolean label cannot be both true and false.")
    overseas = mapping["overseas"]["markers"]
    for column, value in overseas.items():
        if column not in parsed or value not in parsed[column].standard:
            raise _error(f"overseas marker {column}={value!r} is not a standard value of a category column.")
    scope = mapping["public_scope"]
    if scope["column"] not in parsed or scope["value"] not in parsed[scope["column"]].standard:
        raise _error("public_scope must name a standard value of a category column.")
    missing = mapping["missing_classrooms"]
    if kinds.get(missing["column"]) != COUNT or missing["offered_by"] not in offering:
        raise _error("missing_classrooms must name a count and an offers_* column.")
    levels = mapping["levels"]["prefixes"]
    if any(c not in offering for cs in levels.values() for c in cs):
        raise _error("levels may name only offers_* columns.")

    literals = [mapping["identifier"]["pattern"], *true, *false,
                *[v for c in parsed.values() for v in (*c.standard, *c.labels)]]
    unsafe = [v for v in literals if not SAFE_LITERAL.match(v)]
    if unsafe:
        raise _error(f"labels may not contain quotes or backslashes: {unsafe}.")

    columns = []
    for name in published:
        kind = kinds[name]
        if kind == IDENTIFIER:
            rule, finding = "Kept as published; a blank, malformed, or repeated value quarantines the row", mapping["identifier"].get("finding", "")
        elif kind == CATEGORY:
            rule = f"Whitespace normalized, mapped to the standard set; an unmapped label fails the gate. {parsed[name].rule}"
            finding = parsed[name].finding
        elif kind == BOOLEAN:
            rule = f"{'/'.join(true)} to TRUE, {'/'.join(false)} to FALSE, blank to NULL; any other label fails the gate"
            finding = booleans.get("finding", "")
        else:
            group = next(g for g in groups if name in g.columns)
            rule = (f"Whole number to INT; blank to NULL, never 0; negative, not castable, or above {group.plausible_max:,} "
                    f"({group.name}) quarantines the row")
            finding = mapping["count_groups"].get("finding", "")
        columns.append(Column(name, name, kind, rule, finding))

    spec = FacilitiesSpec(
        source_id=source_id, bronze_table=contract["bronze_table"], clean_file=registry_entry["silver"]["clean_file"],
        clean_table=mapping["silver_table"], quarantine_table=mapping["quarantine_table"],
        clean_candidate=registry_entry["silver"]["candidate_table"],
        quarantine_candidate=registry_entry["silver"]["candidate_quarantine_table"],
        identifier=identifier, identifier_pattern=mapping["identifier"]["pattern"], max_digits=max_digits,
        columns=columns, categories=parsed, groups=groups, offering=offering, boolean_true=true, boolean_false=false,
        overseas=overseas, public_column=scope["column"], public_value=scope["value"],
        missing_classrooms=missing["column"], missing_offered_by=missing["offered_by"], levels=levels,
        enrollment_table=enrollment_entry["silver"]["table"], mapping=mapping,
    )
    unlevelled = [c.name for c in spec.facility_columns
                  if sum(c.name.startswith(p) for p in levels) != 1 and not c.name.startswith("buildings_")]
    if unlevelled:
        raise _error(f"facility columns must start with exactly one level prefix (or buildings_): {unlevelled}.")
    return spec


def _filled(refs):
    return "(" + " OR ".join(f"{r} IS NOT NULL" for r in refs) + ")"


def _outside_levels(spec, alias):
    """A level's facility column holds a value, but no offers_* column for that level is TRUE."""
    parts = []
    for prefix, offered_by in spec.levels.items():
        offered = " OR ".join(f"{alias}.{c}" for c in offered_by)
        values = _filled([f"{alias}.{c.name}" for c in spec.level_columns(prefix)])
        parts.append(f"(COALESCE({offered}, FALSE) = FALSE AND {values})")
    return parts


# --- Build ------------------------------------------------------------------------

def build_sql(spec):
    source = spec.source_id
    view = f"{source}_classified"
    clean, quarantine = silver_ref(spec.clean_candidate), silver_ref(spec.quarantine_candidate)
    lineage = [name for name, _ in LINEAGE]
    run_stamp = [name for name, _ in RUN_STAMP]
    counts = spec.counts
    ident = f"n.{spec.identifier}"

    normalized = ["r.school_year", f"r.{bq(spec.identifier)}",
                  f"COUNT(*) OVER (PARTITION BY r.school_year, r.{bq(spec.identifier)}) AS {spec.identifier}_rows",
                  "r.in_enrollment"]
    normalized += [f"{cleaned_text(spec, c, 'r.' + bq(c.source))} AS {c.name}" for c in spec.text]
    normalized += [f"r.{bq(c.source)} AS {c.name}" for c in counts]
    normalized += [f"r.{name}" for name in lineage]

    typed = ["n.school_year", ident]
    for c in spec.columns:
        if c.kind == CATEGORY:
            cases = "\n".join(f"      WHEN {lit(published)} THEN {lit(standard)}"
                              for published, standard in spec.categories[c.name].labels.items())
            typed.append(f"CASE n.{c.name}\n{cases}\n    END AS {c.name}")
        elif c.kind == BOOLEAN:
            typed.append(f"CASE WHEN n.{c.name} IN {in_list(spec.boolean_true)} THEN TRUE "
                         f"WHEN n.{c.name} IN {in_list(spec.boolean_false)} THEN FALSE END AS {c.name}")
        elif c.kind == COUNT:
            typed.append(f"{typed_count(spec, 'n.' + c.name)} AS {c.name}")
    negative = any_of([f"regexp_like(n.{c.name}, {lit(NEGATIVE)})" for c in counts], 9)
    uncastable = any_of([f"(n.{c.name} <> '' AND NOT regexp_like(n.{c.name}, {lit(whole_number(spec))}) "
                         f"AND NOT regexp_like(n.{c.name}, {lit(NEGATIVE)}))" for c in counts], 9)
    implausible = any_of([f"{typed_count(spec, 'n.' + c.name, 'BIGINT')} > {spec.cap(c.name)}" for c in counts], 9)
    typed.append(
        "concat_ws(',',\n"
        f"      CASE WHEN {ident} IS NULL OR {ident} = '' THEN 'school_id_blank'\n"
        f"           WHEN NOT regexp_like({ident}, {lit(spec.identifier_pattern)}) THEN 'school_id_malformed' END,\n"
        f"      CASE WHEN {ident} <> '' AND n.{spec.identifier}_rows > 1 THEN 'school_id_duplicated' END,\n"
        f"      CASE WHEN {negative}\n      THEN 'count_negative' END,\n"
        f"      CASE WHEN {uncastable}\n      THEN 'count_uncastable' END,\n"
        f"      CASE WHEN {implausible}\n      THEN 'count_above_plausible_max' END,\n"
        "      CASE WHEN NOT n.in_enrollment THEN 'school_id_not_in_enrollment' END\n"
        "    ) AS quarantine_reasons")
    typed += [f"n.{name}" for name in lineage]

    overseas = " OR ".join(f"t.{column} = {lit(value)}" for column, value in spec.overseas.items())
    facility = "\n" + joined([f"t.{c.name} IS NOT NULL" for c in spec.facility_columns], 8, " OR")
    final = ["t.school_year"] + [f"t.{c.name}" for c in spec.columns] + [
        f"COALESCE({overseas}, FALSE) AS is_overseas",
        f"({facility}\n  ) AS has_facility_data",
        f"COALESCE(t.{spec.public_column} = {lit(spec.public_value)} AND t.{spec.missing_offered_by}\n"
        f"    AND t.{spec.missing_classrooms} IS NULL, FALSE) AS es_classrooms_missing",
        "t.quarantine_reasons",
    ] + [f"t.{name}" for name in lineage] + [f"session.silver_{name} AS {name}" for name in run_stamp]

    clean_columns = [name for name, _ in spec.clean_columns()]
    quarantine_select = ["school_year", spec.identifier, "split(quarantine_reasons, ',') AS quarantine_reasons",
                         *lineage, *run_stamp]
    lines = header(spec, "Silver build", "sql", spec.clean_file) + [
        "--",
        "-- Rebuilds the two candidate tables from the current Bronze batches only (01-control.current_batches:",
        "-- the latest succeeded delivery version of each school year). Bronze is read, never changed.",
        "-- Every current Bronze row ends in exactly one of the two tables:",
        f"--   {spec.clean_candidate}       one row per school per school year, typed and standardized;",
        f"--   {spec.quarantine_candidate}  rows that cannot be trusted, with their reasons.",
        "-- Every school is kept, public or not: facility measures exist for public schools only (O-3), and",
        "-- Gold scopes to them. Location is not in this file; it comes from enrollment through school_id, so",
        f"-- a school missing from the published {spec.enrollment_table} for its school year is quarantined",
        "-- (O-2, D-037). This task therefore runs after the enrollment Silver gate.",
        f"-- The Silver tables ({spec.clean_table}, {spec.quarantine_table}) are never written here:",
        "-- the gate (the next task) checks the candidates and publishes them only if every check passes,",
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
        "-- Every current Bronze row once, cleaned, with the reasons it would be quarantined.",
        "-- A reason is decided with explicit NULL handling, and concat_ws never returns NULL, so",
        "-- quarantine_reasons = '' and <> '' split the rows without losing any.",
        f"CREATE OR REPLACE TEMPORARY VIEW {view} AS",
        "WITH enrollment AS (",
        f"  SELECT DISTINCT school_year, school_id FROM {silver_ref(spec.enrollment_table)}",
        "),",
        "bronze AS (",
        "  SELECT r.*, e.school_id IS NOT NULL AS in_enrollment",
        f"  FROM {bronze_ref(spec)} AS r",
        f"  JOIN {CONTROL}.current_batches AS c ON r.batch_id = c.batch_id",
        "  LEFT JOIN enrollment AS e ON e.school_year = r.school_year AND e.school_id = r.school_id",
        f"  WHERE c.source_id = {lit(source)}",
        "),",
        "-- Labels: whitespace normalized, blank to NULL. Counts stay as published here.",
        "normalized AS (",
        "  SELECT",
        joined(normalized, 4),
        "  FROM bronze AS r",
        "),",
        "-- Labels mapped to the standard set (unmapped: NULL, and the gate fails), booleans, and counts",
        "-- typed only when they are whole numbers (TRY_CAST alone accepts '5.0' in DuckDB), each against",
        "-- its group's plausible maximum.",
        "typed AS (",
        "  SELECT",
        joined(typed, 4),
        "  FROM normalized AS n",
        ")",
        "SELECT",
        joined(final, 2),
        "FROM typed AS t;",
        "",
        "-- One row per school per school year, with the Bronze row it came from.",
        f"CREATE OR REPLACE TABLE {clean} USING DELTA AS",
        "SELECT",
        joined(clean_columns, 2),
        f"FROM {view}",
        "WHERE quarantine_reasons = '';",
        "",
        candidate_comment(clean, spec.clean_table),
        f"ALTER TABLE {clean} OWNER TO `{OWNER_GROUP}`;",
        "",
        "-- Rows set aside, never deleted: the Bronze row, and why.",
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


# --- Gate ---------------------------------------------------------------------------

def gate_checks(spec):
    """Every check the gate writes, with what decides its status, for tests and the runbook."""
    labels = [f"labels_mapped_{c.name}" for c in (*spec.of_kind(CATEGORY), *[spec.column(o) for o in spec.offering])]
    return (["current_batches_present", "lineage_complete", "rows_resolve_to_current_bronze", "rows_built_by_this_run",
             "one_timestamp_per_run", "rows_reconcile", "school_id_unique", "school_id_valid", "counts_non_negative",
             "counts_within_plausible_max", "counts_reconcile", "missing_counts_stay_null", "true_values_reconcile",
             "missing_booleans_stay_null", "school_id_in_enrollment", *labels, "labels_mapped_facility_booleans",
             "facility_data_public_only", "facility_values_within_offered_levels", "quarantine_rate"]
            + [f"quarantine_reason_{r}" for r in REASONS]
            + ["rule_whitespace_normalized", "rule_blank_counts_to_null", "rule_blank_booleans_to_null",
               "rule_labels_standardized", "flag_is_overseas", "flag_has_facility_data",
               "flag_public_without_facility_data", "flag_es_classrooms_missing"])


def gate_sql(spec):
    source = spec.source_id
    counts = spec.counts
    booleans = spec.of_kind(BOOLEAN)
    facility_booleans = spec.facility_booleans
    clean_name, quarantine_name = dq_table_name(spec.clean_candidate), dq_table_name(spec.quarantine_candidate)
    lineage = [name for name, _ in LINEAGE]
    stamp = [name for name, _ in RUN_STAMP]
    categories = spec.of_kind(CATEGORY)
    accepted_booleans = spec.boolean_true + spec.boolean_false

    def raw(c):
        return f"b.{bq(c.source)}"

    def accepted(c):
        return list(spec.categories[c.name].labels) if c.kind == CATEGORY else accepted_booleans

    def unmapped_raw(c):
        return f"({whitespace(raw(c))} <> '' AND {whitespace(raw(c))} NOT IN {in_list(accepted(c))})"

    named = [*categories, *[spec.column(o) for o in spec.offering]]
    public = f"{lit(spec.public_value)}"
    bronze_counts = null_safe_sum(typed_count(spec, raw(c), "BIGINT") for c in counts)
    bronze_missing = " + ".join(f"CASE WHEN {raw(c)} IS NULL OR {raw(c)} = '' THEN 1 ELSE 0 END" for c in counts)
    bronze_true = " + ".join(f"CASE WHEN {whitespace(raw(c))} IN {in_list(spec.boolean_true)} THEN 1 ELSE 0 END" for c in booleans)
    bronze_blank_booleans = " + ".join(f"CASE WHEN {raw(c)} IS NULL OR {whitespace(raw(c))} = '' THEN 1 ELSE 0 END"
                                       for c in booleans)
    bronze_years = [
        "b.school_year",
        "COUNT(*) AS bronze_rows",
        f"SUM(CASE WHEN b.in_quarantine THEN 0 ELSE\n        {bronze_counts}\n      END) AS kept_counts",
        f"SUM(CASE WHEN b.in_quarantine THEN 0 ELSE\n        {bronze_missing}\n      END) AS kept_missing_counts",
        f"SUM(CASE WHEN b.in_quarantine THEN 0 ELSE\n        {bronze_true}\n      END) AS kept_true_values",
        f"SUM(CASE WHEN b.in_quarantine THEN 0 ELSE\n        {bronze_blank_booleans}\n      END) AS kept_blank_booleans",
        "COUNT_IF(\n        " + any_of([f"{whitespace(raw(c))} <> {raw(c)}" for c in spec.text], 8) + "\n      ) AS whitespace_rows",
        "COUNT_IF(\n        " + any_of([f"{raw(c)} = ''" for c in counts], 8) + "\n      ) AS blank_count_rows",
        "COUNT_IF(\n        " + any_of([f"{raw(c)} = ''" for c in booleans], 8) + "\n      ) AS blank_boolean_rows",
    ] + [
        f"COUNT_IF(b.in_quarantine AND {unmapped_raw(x)}) AS quarantined_unmapped_{x.name}" for x in named
    ] + [
        "COUNT_IF(b.in_quarantine AND (\n        " + any_of([unmapped_raw(x) for x in facility_booleans], 8)
        + "\n      )) AS quarantined_unmapped_facility_booleans"
    ]
    clean_counts = null_safe_sum(as_bigint(f"c.{x.name}") for x in counts)
    clean_missing = " + ".join(f"CASE WHEN c.{x.name} IS NULL THEN 1 ELSE 0 END" for x in counts)
    clean_true = " + ".join(f"CASE WHEN c.{x.name} THEN 1 ELSE 0 END" for x in booleans)
    clean_blank_booleans = " + ".join(f"CASE WHEN c.{x.name} IS NULL THEN 1 ELSE 0 END" for x in booleans)
    clean_years = [
        "c.school_year",
        "COUNT(*) AS clean_rows",
        f"COUNT(DISTINCT c.{spec.identifier}) AS clean_ids",
        f"COUNT_IF(c.{spec.identifier} IS NULL OR NOT regexp_like(c.{spec.identifier}, {lit(spec.identifier_pattern)})) AS invalid_ids",
        "COUNT_IF(\n        " + any_of([f"c.{x.name} < 0" for x in counts], 8) + "\n      ) AS negative_rows",
        "COUNT_IF(\n        " + any_of([f"c.{x.name} > {spec.cap(x.name)}" for x in counts], 8) + "\n      ) AS implausible_rows",
        f"SUM(\n        {clean_counts}\n      ) AS clean_counts",
        f"SUM(\n        {clean_missing}\n      ) AS clean_missing_counts",
        f"SUM(\n        {clean_true}\n      ) AS clean_true_values",
        f"SUM(\n        {clean_blank_booleans}\n      ) AS clean_blank_booleans",
        f"COUNT_IF(c.{spec.public_column} IS DISTINCT FROM {public} AND c.has_facility_data) AS non_public_facility_rows",
        "COUNT_IF(\n        " + any_of(_outside_levels(spec, "c"), 8) + "\n      ) AS outside_level_rows",
        "COUNT_IF(c.is_overseas) AS overseas_rows",
        "COUNT_IF(c.has_facility_data) AS facility_data_rows",
        f"COUNT_IF(c.{spec.public_column} = {public} AND NOT c.has_facility_data) AS public_without_data_rows",
        "COUNT_IF(c.es_classrooms_missing) AS classrooms_missing_rows",
    ]
    matched_years = ["c.school_year"] + [
        f"COUNT_IF(c.{x.name} IS NULL AND {whitespace(raw(x))} <> '') AS unmapped_{x.name}" for x in named
    ] + [
        "COUNT_IF(\n        " + any_of([f"(c.{x.name} IS NULL AND {whitespace(raw(x))} <> '')" for x in facility_booleans], 8)
        + "\n      ) AS unmapped_facility_booleans",
        "COUNT_IF(\n        " + any_of([f"{whitespace(raw(x))} <> c.{x.name}" for x in categories], 8) + "\n      ) AS relabelled_rows",
    ]
    reference_years = [
        "c.school_year",
        "COUNT_IF(e.school_id IS NULL) AS orphan_rows",
    ]
    quarantine_years = ["q.school_year", "COUNT(*) AS quarantined_rows"] + [
        f"COUNT_IF(array_contains(q.quarantine_reasons, {lit(r)})) AS reason_{r}" for r in REASONS]

    year_columns = ["y.school_year", "y.batch_id", "COALESCE(bronze_rows, 0) AS bronze_rows",
                    "COALESCE(clean_rows, 0) AS clean_rows", "COALESCE(clean_ids, 0) AS clean_ids",
                    "COALESCE(quarantined_rows, 0) AS quarantined_rows"]
    passthrough = ["kept_counts", "clean_counts", "kept_missing_counts", "clean_missing_counts", "kept_true_values",
                   "clean_true_values", "kept_blank_booleans", "clean_blank_booleans", "whitespace_rows",
                   "blank_count_rows", "blank_boolean_rows", "invalid_ids", "negative_rows", "implausible_rows",
                   "non_public_facility_rows", "outside_level_rows", "overseas_rows", "facility_data_rows",
                   "public_without_data_rows", "classrooms_missing_rows", "relabelled_rows", "orphan_rows",
                   *[f"reason_{r}" for r in REASONS]]
    year_columns += [f"COALESCE({name}, 0) AS {name}" for name in passthrough]
    # Unmapped labels: clean rows by what the build made of them, quarantined rows against the mapping itself.
    year_columns += [f"COALESCE(unmapped_{x}, 0) + COALESCE(quarantined_unmapped_{x}, 0) AS unmapped_{x}"
                     for x in [*[c.name for c in named], "facility_booleans"]]

    def check(name, table, status, expected, actual, source="years"):
        batch = "batch_id" if source == "years" else "CAST(NULL AS STRING)"
        return (f"SELECT {batch} AS batch_id, {lit(table)} AS table_name, {lit(name)} AS check_name,\n"
                f"         {status} AS status,\n"
                f"         {expected} AS expected, {actual} AS actual FROM {source}")

    def must_equal(name, table, expected, actual, source="years"):
        return check(name, table, f"CASE WHEN {actual} = {expected} THEN 'PASS' ELSE 'FAIL' END",
                     f"CAST({expected} AS STRING)", f"CAST({actual} AS STRING)", source)

    def must_be_zero(name, table, actual, source="years"):
        return must_equal(name, table, "0", actual, source)

    def warn_if_any(name, table, actual):
        return check(name, table, f"CASE WHEN {actual} = 0 THEN 'PASS' ELSE 'WARN' END", "'0'",
                     f"CAST({actual} AS STRING)")

    def record(name, actual):
        return check(name, clean_name, "'PASS'", "CAST(NULL AS STRING)", f"CAST({actual} AS STRING)")

    checks = [
        "-- The whole table, both tables together",
        check("current_batches_present", clean_name, "CASE WHEN current_batches > 0 THEN 'PASS' ELSE 'FAIL' END",
              "'at least 1'", "CAST(current_batches AS STRING)", "found"),
        must_be_zero("lineage_complete", clean_name, "missing_lineage", "whole"),
        must_be_zero("rows_resolve_to_current_bronze", clean_name, "unresolved_rows", "unresolved"),
        must_be_zero("rows_built_by_this_run", clean_name, "other_run_rows", "whole"),
        must_equal("one_timestamp_per_run", clean_name, "1", "timestamps", "whole"),
        "-- Each school year: reconciliation, keys, ranges, NULLs",
        must_equal("rows_reconcile", clean_name, "bronze_rows", "clean_rows + quarantined_rows"),
        must_be_zero("school_id_unique", clean_name, "clean_rows - clean_ids"),
        must_be_zero("school_id_valid", clean_name, "invalid_ids"),
        must_be_zero("counts_non_negative", clean_name, "negative_rows"),
        must_be_zero("counts_within_plausible_max", clean_name, "implausible_rows"),
        must_equal("counts_reconcile", clean_name, "kept_counts", "clean_counts"),
        must_equal("missing_counts_stay_null", clean_name, "kept_missing_counts", "clean_missing_counts"),
        must_equal("true_values_reconcile", clean_name, "kept_true_values", "clean_true_values"),
        must_equal("missing_booleans_stay_null", clean_name, "kept_blank_booleans", "clean_blank_booleans"),
        "-- Each school year: every clean school is in the published enrollment Silver (the build quarantines the rest)",
        must_be_zero("school_id_in_enrollment", clean_name, "orphan_rows"),
        "-- Each school year: every label is in the reviewed mapping",
        *[must_be_zero(f"labels_mapped_{x.name}", clean_name, f"unmapped_{x.name}") for x in named],
        must_be_zero("labels_mapped_facility_booleans", clean_name, "unmapped_facility_booleans"),
        "-- Each school year: scope the planners rely on (WARN: published, but Gold's reading may need review)",
        warn_if_any("facility_data_public_only", clean_name, "non_public_facility_rows"),
        warn_if_any("facility_values_within_offered_levels", clean_name, "outside_level_rows"),
        "-- Each school year: quarantine (WARN above 0, FAIL above 1% of the year's Bronze rows)",
        check("quarantine_rate", quarantine_name,
              "CASE WHEN quarantined_rows = 0 THEN 'PASS' WHEN quarantined_rows * 100 > bronze_rows THEN 'FAIL' ELSE 'WARN' END",
              # No ';' inside a string: store.split_statements splits files on it.
              "'0 (FAIL above 1% of ' || CAST(bronze_rows AS STRING) || ')'", "CAST(quarantined_rows AS STRING)"),
        *[warn_if_any(f"quarantine_reason_{r}", quarantine_name, f"reason_{r}") for r in REASONS],
        "-- Each school year: how many rows each cleaning rule changed or flagged (records, always PASS)",
        record("rule_whitespace_normalized", "whitespace_rows"),
        record("rule_blank_counts_to_null", "blank_count_rows"),
        record("rule_blank_booleans_to_null", "blank_boolean_rows"),
        record("rule_labels_standardized", "relabelled_rows"),
        record("flag_is_overseas", "overseas_rows"),
        record("flag_has_facility_data", "facility_data_rows"),
        record("flag_public_without_facility_data", "public_without_data_rows"),
        record("flag_es_classrooms_missing", "classrooms_missing_rows"),
    ]
    union = []
    for item in checks:
        if item.startswith("--"):
            union.append("  " + item)
        else:
            union.append(("  UNION ALL " if any(not u.lstrip().startswith("--") for u in union) else "  ") + item)

    silver_rows = (f"  SELECT {', '.join(['school_year', *lineage, *stamp])} FROM clean\n"
                   f"  UNION ALL SELECT {', '.join(['school_year', *lineage, *stamp])} FROM quarantined")
    missing_lineage = " OR ".join(f"{name} IS NULL" for name in ["school_year", *lineage, *stamp])
    lines = header(spec, "Silver gate", "gate", f"90_validate_{spec.clean_table}.sql") + [
        "--",
        "-- The job task after the Silver build, which runs after the enrollment Silver gate. It checks the",
        "-- candidate tables the build wrote, one row per check in data_quality_results, and reads the",
        "-- published enrollment Silver to confirm every clean school is there. On any FAIL it records the run 'failed' and stops the task before",
        "-- publishing, so the Silver tables keep the last build that passed and nothing downstream runs.",
        "-- Otherwise it copies the candidates to the Silver tables and records the run 'succeeded'.",
        "-- PASS: as expected. WARN: recorded, the build is published (quarantined rows, or a scope change).",
        "-- FAIL: the candidate cannot be trusted and is not published. Results hold counts, never row values.",
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
        f"  SELECT batch_id, school_year FROM {CONTROL}.current_batches WHERE source_id = {lit(source)}",
        "),",
        "bronze AS (",
        f"  SELECT r.* FROM {bronze_ref(spec)} AS r JOIN cur ON r.batch_id = cur.batch_id",
        "),",
        f"clean AS (SELECT * FROM {silver_ref(spec.clean_candidate)}),",
        f"quarantined AS (SELECT * FROM {silver_ref(spec.quarantine_candidate)}),",
        f"enrollment AS (SELECT school_year, school_id FROM {silver_ref(spec.enrollment_table)}),",
        "-- Current Bronze rows, each marked if Silver set it aside.",
        "b AS (",
        "  SELECT bronze.*, q.source_row_number IS NOT NULL AS in_quarantine",
        "  FROM bronze",
        "  LEFT JOIN quarantined AS q",
        "    ON bronze.source_sha256 = q.source_sha256 AND bronze.source_row_number = q.source_row_number",
        "),",
        "-- A quarantined row has no clean value, so its labels are checked against the reviewed mapping here:",
        "-- a row set aside for another reason must not let an unmapped label through.",
        "bronze_years AS (",
        "  SELECT",
        joined(bronze_years, 4),
        "  FROM b GROUP BY b.school_year",
        "),",
        "clean_years AS (",
        "  SELECT",
        joined(clean_years, 4),
        "  FROM clean AS c GROUP BY c.school_year",
        "),",
        "-- Each clean row beside its Bronze row: is every published label mapped?",
        "matched_years AS (",
        "  SELECT",
        joined(matched_years, 4),
        "  FROM clean AS c",
        "  JOIN b ON c.source_sha256 = b.source_sha256 AND c.source_row_number = b.source_row_number",
        "  GROUP BY c.school_year",
        "),",
        "-- Each clean row beside the same school in the same school year of enrollment Silver.",
        "reference_years AS (",
        "  SELECT",
        joined(reference_years, 4),
        "  FROM clean AS c",
        "  LEFT JOIN enrollment AS e ON e.school_year = c.school_year AND e.school_id = c.school_id",
        "  GROUP BY c.school_year",
        "),",
        "quarantine_years AS (",
        "  SELECT",
        joined(quarantine_years, 4),
        "  FROM quarantined AS q GROUP BY q.school_year",
        "),",
        "years AS (",
        "  SELECT",
        joined(year_columns, 4),
        "  FROM cur AS y",
        "  LEFT JOIN bronze_years ON bronze_years.school_year = y.school_year",
        "  LEFT JOIN clean_years ON clean_years.school_year = y.school_year",
        "  LEFT JOIN matched_years ON matched_years.school_year = y.school_year",
        "  LEFT JOIN reference_years ON reference_years.school_year = y.school_year",
        "  LEFT JOIN quarantine_years ON quarantine_years.school_year = y.school_year",
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
        "-- Silver rows whose Bronze row is not in a current batch (an old version, or gone).",
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


# --- Data dictionary -------------------------------------------------------------------

LINEAGE_MEANING = {
    "batch_id": "The Bronze batch (one delivery of one school year) the row came from; joins `01-control`.ingestion_batches",
    "delivery_version": "Which delivery of the school year: 1, or 2+ after a publisher revision",
    "schema_version": "Which header the file had",
    "source_sha256": "SHA-256 of the publisher's CSV; with `source_row_number`, identifies the Bronze row exactly",
    "source_row_number": "The row's position in that CSV (data rows from 1)",
    "run_id": "The job run that built the row (`{{job.run_id}}`); every row of a build has the same one, as do the gate's results",
    "cleaned_at_utc": "When that build ran; one value for both tables, in UTC",
    "code_revision": "The commit that ran the build",
}

QUARANTINE_MEANING = {
    "school_id_blank": "`school_id` is NULL or blank",
    "school_id_malformed": "`school_id` is not exactly six digits",
    "school_id_duplicated": "the same `school_id` appears more than once in the school year; every copy is set aside",
    "count_negative": "a count is a negative whole number",
    "count_uncastable": "a count is not blank and not a whole number of at most nine digits (e.g. `5.0`, `abc`)",
    "count_above_plausible_max": "a count is above its group's reviewed plausible maximum, e.g. a count with an extra digit",
    "school_id_not_in_enrollment": "the school is not in the published enrollment Silver for its school year, so it cannot be placed "
                                   "(it is missing from enrollment, or enrollment set it aside)",
}


def dictionary_markdown(spec):
    m = spec.mapping
    rows = [("school_year", "STRING", "`school_year` (provenance)",
             "From the file names, as Bronze recorded it (key, with `school_id`)", "Never", "")]
    for c in spec.columns:
        if c.kind == IDENTIFIER:
            null = "Never (the gate fails otherwise)"
        elif c.kind in (CATEGORY, BOOLEAN):
            null = "Published blank (an unmapped label fails the gate)"
        else:
            null = "Published blank. Never 0"
        if c.name == spec.missing_classrooms:
            null += "; at a public school offering the level, also flagged `es_classrooms_missing`"
        rows.append((c.name, TYPES[c.kind].upper(), f"`{c.source}`", c.rule, null, c.finding))
    rows += [
        ("is_overseas", "BOOLEAN", " ".join(f"`{c}`" for c in spec.overseas),
         "TRUE when any of them is `PSO` after mapping (Philippine Schools Overseas)", "Never", m["overseas"]["finding"]),
        ("has_facility_data", "BOOLEAN", "every count and facility yes/no column",
         "TRUE when at least one of them is published. Facility data covers public schools only, so Gold scopes "
         f"to `{spec.public_column} = '{spec.public_value}'`; this flag shows the rare public school with none",
         "Never", m["public_scope"]["finding"]),
        ("es_classrooms_missing", "BOOLEAN", f"`{spec.public_column}`, `{spec.missing_offered_by}`, `{spec.missing_classrooms}`",
         f"TRUE for a public school offering elementary whose `{spec.missing_classrooms}` is blank. Never read as 0: "
         "the blank may mean zero permanent rooms or a missing report (S-2, open)", "Never", m["missing_classrooms"]["finding"]),
    ]
    rows += [(name, typ.upper(), "Bronze", LINEAGE_MEANING[name], "Never", "") for name, typ in LINEAGE]
    rows += [(name, typ.upper(), "This build", LINEAGE_MEANING[name], "Never", "") for name, typ in RUN_STAMP]

    def cell(value):
        return str(value).replace("|", "\\|")

    table = ["| Column | Type | Source | Rule | NULL means | Finding |", "|---|---|---|---|---|---|"]
    table += ["| " + " | ".join([f"`{name}`", typ, source, cell(rule), null, finding]) + " |"
              for name, typ, source, rule, null, finding in rows]
    groups = ["| Group | Plausible maximum | Columns | Evidence |", "|---|---|---|---|"]
    groups += [f"| {g.name} | {g.plausible_max:,} | {', '.join(f'`{c}`' for c in g.columns)} | "
               f"{m['count_groups']['groups'][g.name]['evidence']} |" for g in spec.groups]
    reasons = [f"- `{r}`: {QUARANTINE_MEANING[r]}" for r in REASONS]
    return "\n".join([
        f"# `{spec.clean_table}`: Silver data dictionary",
        "",
        f"Generated by `python -m src.silver.cli dictionary --source {spec.source_id}` from "
        f"[the Bronze contract](../../../config/ingestion/{spec.source_id}.json) and "
        f"[the Silver mapping](../../../config/mappings/{spec.source_id}.json). Do not edit by hand; "
        "`tests/test_silver.py` fails if it differs.",
        "",
        f"`` edu_access.`{SCHEMA}`.{spec.clean_table} ``: one row per school per school year, for the current delivery "
        "of each school year only (`01-control`.current_batches). Key: (`school_id`, `school_year`). Every school in "
        "the file is kept, public or not; facility measures exist for public schools only. Location is not here: "
        f"join `{spec.enrollment_table}` on (`school_id`, `school_year`); a school missing there is quarantined. Every "
        "row names the Bronze row it came from (`source_sha256`, `source_row_number`). Rules, counts, and the gate: "
        "[docs/operations/silver.md](../../operations/silver.md#deped-facilities).",
        "",
        "**NULL** never means zero. A blank count for a level the school does not offer means not applicable; a blank "
        "elementary classroom count at a public school offering elementary is flagged `es_classrooms_missing`.",
        "",
        "## Columns",
        "",
        *table,
        "",
        "## Count groups",
        "",
        *groups,
        "",
        f"## Quarantine: `{spec.quarantine_table}`",
        "",
        "One row per Bronze row set aside, never deleted: `school_year`, `school_id` as published, "
        "`quarantine_reasons` (every reason that applies), and the lineage and run columns above.",
        "",
        *reasons,
        "",
    ])
