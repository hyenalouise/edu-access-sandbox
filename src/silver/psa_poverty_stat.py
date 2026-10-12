"""Silver for psa_poverty_stat: the spec, the build SQL, the gate SQL, and the data dictionary.

Two reviewed files define it, and nothing else:

- `config/ingestion/psa_poverty_stat.json`, the Bronze contract: which publisher
  columns exist in which schema version, and so which estimate years exist;
- `config/mappings/psa_poverty_stat.json`, the Silver rules: grain, identifier,
  text columns, measures, numeric pattern, bounds, flags, and quarantine.

PSA's shape differs from DepEd's (D-021), so it has its own generator rather than
the DepEd mapping format (D-034): one Bronze `unit` row holds 2018, 2021 and 2023
side by side, and Silver unpivots it to one row per unit and estimate year, with
that year's estimate, CV, SE and both 90% limits together. Region banner rows give
each unit its region label and never become estimate rows. The SQL follows the same
conventions as src/silver/sql.py: the build writes the candidate tables, the gate
checks them and publishes only if no check FAILs (D-025), both run as SQL tasks,
and only syntax both Databricks and DuckDB accept is used (src/ingestion/store.py
translates the rest).
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from src.ingestion.bronze import OWNER_GROUP, source_columns
from src.ingestion.contract import load_source_config
from src.ingestion.errors import IngestionError
from src.silver.sql import CONTROL, bq, candidate_comment, dq_table_name, joined, lit, silver_ref, whitespace

SOURCE_ID = "psa_poverty_stat"
SAFE_LITERAL = re.compile(r"^[^'\\;]*$")
YEAR = re.compile(r"^[0-9]{4}$")

# Why a candidate row is set aside, in the order they are listed on a quarantined row.
QUARANTINE_REASONS = (
    "psgc_id_blank",
    "psgc_id_malformed",
    "psgc_id_duplicated",
    "measure_uncastable",
    "incidence_out_of_range",
    "cv_negative",
    "se_negative",
    "ci_inconsistent",
)
ESTIMATE_STATUSES = ("estimated", "no_estimate", "partial_estimate")

# Bronze provenance carried on every clean and quarantined row, then the Silver run's own stamp.
LINEAGE = (
    ("logical_dataset", "string"),
    ("estimate_years_covered", "string"),
    ("batch_id", "string"),
    ("delivery_version", "int"),
    ("schema_version", "string"),
    ("source_sha256", "string"),
    ("source_row_number", "bigint"),
)
RUN_STAMP = (("run_id", "string"), ("cleaned_at_utc", "timestamp"), ("code_revision", "string"))


def _error(message):
    return IngestionError("config", "invalid_silver_mapping", message)


@dataclass
class Measure:
    name: str             # Silver column
    published: str        # Bronze column name with {year}
    unit: str
    finding: str

    def source(self, year):
        return self.published.format(year=year)


@dataclass
class PsaSpec:
    source_id: str
    bronze_table: str
    clean_file: str
    clean_table: str
    quarantine_table: str
    clean_candidate: str
    quarantine_candidate: str
    years: list                 # every estimate year the contract's columns hold, sorted
    year_columns: dict          # year -> {measure name: Bronze column, or None if no schema publishes it}
    measures: list
    identifier: str
    identifier_pattern: str
    id_to: str                  # Silver name of the padded identifier
    id_width: int
    correspondence_to: str
    correspondence_suffix: str
    text_columns: dict          # Bronze column -> (Silver column, rule)
    banner_column: str
    banner_to: str
    unit_kind: str
    banner_kind: str
    structural_kinds: list
    numeric_pattern: str
    incidence_min: float
    incidence_max: float
    cv_threshold: float
    se_tolerance: float
    quarantine_fail_percent: float
    absent: dict                # schema version -> [(year, measure)] columns that version does not publish
    mapping: dict = field(repr=False)

    @property
    def cv_flag(self):
        return f"cv_over_{_number(self.cv_threshold)}"

    @property
    def flags(self):
        return (self.cv_flag, "se_cv_inconsistent", "lower_limit_not_positive")

    def identity_columns(self):
        return [("estimate_year", "int"), (self.id_to, "string"), (self.correspondence_to, "string")]

    def clean_columns(self):
        """[(name, type)] of the clean table, in order."""
        columns = self.identity_columns()
        columns += [(self.banner_to, "string")] + [(to, "string") for to, _ in self.text_columns.values()]
        columns += [(m.name, "double") for m in self.measures]
        columns += [("estimate_status", "string")] + [(f, "boolean") for f in self.flags]
        return columns + list(LINEAGE) + list(RUN_STAMP)

    def quarantine_columns(self):
        return (self.identity_columns()[:2] + [(self.banner_to, "string"), ("quarantine_reasons", "array<string>")]
                + list(LINEAGE) + list(RUN_STAMP))


def _number(value):
    return str(int(value)) if float(value).is_integer() else str(value)


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

    published = source_columns(contract)
    measures = [Measure(m["name"], m["published"], m["unit"], m.get("finding", "")) for m in mapping["measures"]]
    if len({m.name for m in measures}) != len(measures):
        raise _error("two measures share a Silver name.")

    # Estimate years: every year a measure column of any schema version carries.
    years = set()
    for column in published:
        for m in measures:
            pattern = re.escape(m.published).replace(re.escape("{year}"), "([0-9]{4})")
            found = re.fullmatch(pattern, column)
            if found:
                years.add(found.group(1))
    years = sorted(years)
    if not years:
        raise _error("no measure column of the contract matches the mapping's measures.")
    year_columns = {y: {m.name: (m.source(y) if m.source(y) in published else None) for m in measures} for y in years}

    identifier = mapping["identifier"]["column"]
    text = {src: (entry["to"], entry["rule"]) for src, entry in mapping["text_columns"].items()}
    banner = mapping["region_banner"]
    not_carried = mapping.get("not_carried", {})
    classified = {identifier, *text, banner["column"], *not_carried,
                  *(c for cols in year_columns.values() for c in cols.values() if c)}
    unclassified = sorted(set(published) - classified)
    if unclassified:
        raise _error(f"columns {unclassified} have no Silver rule. A new publisher column needs a reviewed "
                     "entry in config/mappings/psa_poverty_stat.json.")
    stray = sorted({identifier, *text, banner["column"], *not_carried} - set(published))
    if stray:
        raise _error(f"the mapping names columns the contract does not have: {stray}.")
    names = ([m.name for m in measures] + [to for to, _ in text.values()] + [banner["to"]]
             + [mapping["identifier"]["to"], mapping["identifier"]["correspondence_to"]])
    for name in names:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
            raise _error(f"Silver column {name!r} is not snake_case.")

    flags = mapping["flags"]
    literals = [mapping["identifier"]["pattern"], mapping["numeric"]["pattern"], mapping["identifier"]["correspondence_suffix"],
                mapping["unit_row_kind"], mapping["banner_row_kind"], *mapping["structural_row_kinds"], *years]
    unsafe = [v for v in literals if not SAFE_LITERAL.match(v)]
    if unsafe:
        raise _error(f"patterns and labels may not contain quotes, backslashes or ';': {unsafe}.")
    if not all(YEAR.match(y) for y in years):
        raise _error("estimate years must be four digits.")
    for key in ("cv_threshold", "se_cv_tolerance"):
        if not isinstance(flags[key], (int, float)) or flags[key] < 0:
            raise _error(f"flags.{key} must be a non-negative number.")
    percent = mapping["quarantine"]["fail_above_percent"]
    if not isinstance(percent, (int, float)) or not 0 <= percent < 100:
        raise _error("quarantine.fail_above_percent must be a number from 0 to under 100.")

    absent = {}
    for version, entry in contract["schema_versions"].items():
        missing = [(y, m.name) for y in years for m in measures if year_columns[y][m.name] not in entry["columns"]]
        if missing:
            absent[version] = missing

    return PsaSpec(
        source_id=source_id, bronze_table=contract["bronze_table"], clean_file=silver["clean_file"],
        clean_table=mapping["silver_table"], quarantine_table=mapping["quarantine_table"],
        clean_candidate=silver["candidate_table"], quarantine_candidate=silver["candidate_quarantine_table"],
        years=years, year_columns=year_columns, measures=measures, identifier=identifier,
        identifier_pattern=mapping["identifier"]["pattern"], id_to=mapping["identifier"]["to"],
        id_width=mapping["identifier"]["width"], correspondence_to=mapping["identifier"]["correspondence_to"],
        correspondence_suffix=mapping["identifier"]["correspondence_suffix"],
        text_columns=text, banner_column=banner["column"], banner_to=banner["to"],
        unit_kind=mapping["unit_row_kind"], banner_kind=mapping["banner_row_kind"],
        structural_kinds=mapping["structural_row_kinds"], numeric_pattern=mapping["numeric"]["pattern"],
        incidence_min=mapping["bounds"]["poverty_incidence_min"], incidence_max=mapping["bounds"]["poverty_incidence_max"],
        cv_threshold=flags["cv_threshold"], se_tolerance=flags["se_cv_tolerance"],
        quarantine_fail_percent=percent, absent=absent, mapping=mapping,
    )


# --- Shared SQL pieces -------------------------------------------------------------------

def _bronze_ref(spec):
    return f"edu_access.`02-bronze`.{spec.bronze_table}"


def _header(spec, what, command, path):
    return [
        f"-- {what} for {spec.source_id}. Generated from config/ingestion/{spec.source_id}.json",
        f"-- and config/mappings/{spec.source_id}.json by src/silver/psa_poverty_stat.py:",
        f"--   python -m src.silver.cli {command} --source {spec.source_id} > {path}",
        "-- Do not edit by hand; tests/test_silver_psa.py fails if it differs.",
    ]


# estimate_year is INT in the Silver tables; Bronze's year columns and estimate_years_covered hold
# the year as text, so the gate compares the text form (and check names keep '_2018').
YEAR_TEXT = "CAST({}.estimate_year AS STRING)"


def _covers(years_ref, year):
    return _covers_expr(years_ref, lit(year))


def _covers_expr(years_ref, year_expr):
    return f"array_contains(split({years_ref}, ','), {year_expr})"


def _blank(ref):
    return f"({ref} IS NULL OR {ref} = '')"


def _typed(spec, ref):
    """The number a published cell holds, or NULL for blank, absent, or not a number."""
    return f"CASE WHEN regexp_like({ref}, {lit(spec.numeric_pattern)}) THEN TRY_CAST({ref} AS DOUBLE) END"


def _uncastable(spec, ref):
    return (f"({ref} <> '' AND (NOT regexp_like({ref}, {lit(spec.numeric_pattern)}) "
            f"OR TRY_CAST({ref} AS DOUBLE) IS NULL))")


def _year_cell(spec, measure, year_ref, table):
    """A measure's published cell for the row's estimate year, from the wide Bronze row."""
    cases = [f"WHEN {lit(y)} THEN {table}.{bq(spec.year_columns[y][measure.name])}"
             for y in spec.years if spec.year_columns[y][measure.name]]
    return f"CASE {year_ref} " + " ".join(cases) + " END"


def _flag_exprs(spec, ref):
    """name -> expression over the typed measures (ref.<measure>); never NULL."""
    pi, cv, se, lower = (f"{ref}.poverty_incidence", f"{ref}.coefficient_of_variation", f"{ref}.standard_error",
                         f"{ref}.ci90_lower_limit")
    return {
        spec.cv_flag: f"COALESCE({cv} > {_number(spec.cv_threshold)}, FALSE)",
        "se_cv_inconsistent": f"COALESCE(abs({se} - {pi} * {cv} / 100) > {_number(spec.se_tolerance)}, FALSE)",
        "lower_limit_not_positive": f"COALESCE({lower} <= 0, FALSE)",
    }


def _status_expr(spec, ref):
    values = [f"{ref}.{m.name}" for m in spec.measures]
    all_null = " AND ".join(f"{v} IS NULL" for v in values)
    none_null = " AND ".join(f"{v} IS NOT NULL" for v in values)
    return (f"CASE WHEN {none_null} THEN 'estimated'\n"
            f"         WHEN {all_null} THEN 'no_estimate'\n"
            "         ELSE 'partial_estimate' END")


def _range_problems(spec, ref):
    """reason -> condition over typed measures; NULL-safe (a NULL measure never trips a reason)."""
    pi, cv, se = f"{ref}.poverty_incidence", f"{ref}.coefficient_of_variation", f"{ref}.standard_error"
    lower, upper = f"{ref}.ci90_lower_limit", f"{ref}.ci90_upper_limit"
    return {
        "incidence_out_of_range": f"COALESCE({pi} < {_number(spec.incidence_min)} OR {pi} > {_number(spec.incidence_max)}, FALSE)",
        "cv_negative": f"COALESCE({cv} < 0, FALSE)",
        "se_negative": f"COALESCE({se} < 0, FALSE)",
        "ci_inconsistent": (f"COALESCE({lower} > {upper}, FALSE) OR COALESCE({pi} < {lower}, FALSE) "
                            f"OR COALESCE({pi} > {upper}, FALSE)"),
    }


# --- Build ---------------------------------------------------------------------------------

def build_sql(spec):
    source = spec.source_id
    view = f"{source}_classified"
    lineage = [name for name, _ in LINEAGE]
    stamp = [name for name, _ in RUN_STAMP]
    ident = bq(spec.identifier)
    text_select = [f"NULLIF({whitespace('u.' + bq(src))}, '') AS {to}" for src, (to, _) in spec.text_columns.items()]

    branches = []
    for y in spec.years:
        cells = [(f"u.{bq(col)}" if col else "CAST(NULL AS STRING)") + f" AS {m.name}_published"
                 for m in spec.measures for col in [spec.year_columns[y][m.name]]]
        branches.append("\n".join([
            "  SELECT",
            joined([f"{lit(y)} AS estimate_year", f"u.{ident} AS psgc_id_published", f"u.{spec.banner_to}",
                    *text_select, *cells, *[f"u.{name}" for name in lineage]], 4),
            "  FROM units AS u",
            f"  WHERE {_covers('u.estimate_years_covered', y)}",
        ]))

    padded = (f"CASE WHEN regexp_like(c.psgc_id_published, {lit(spec.identifier_pattern)}) "
              f"THEN lpad(c.psgc_id_published, {spec.id_width}, '0') END")
    pid, cc = spec.id_to, spec.correspondence_to
    keyed = ["c.*", f"{padded} AS {pid}"]
    typed = ["k.estimate_year", f"k.{pid}",
             f"k.{pid} || {lit(spec.correspondence_suffix)} AS {cc}",
             f"k.{spec.banner_to}", *[f"k.{to}" for to, _ in spec.text_columns.values()],
             *[f"{_typed(spec, f'k.{m.name}_published')} AS {m.name}" for m in spec.measures],
             f"COUNT(*) OVER (PARTITION BY k.estimate_year, k.{pid}) AS key_rows",
             "COALESCE(\n      " + "\n      OR ".join(_uncastable(spec, f"k.{m.name}_published") for m in spec.measures)
             + ",\n      FALSE) AS any_uncastable",
             "(k.psgc_id_published IS NULL OR k.psgc_id_published = '') AS id_blank",
             *[f"k.{name}" for name in lineage]]
    problems = _range_problems(spec, "t")
    reasons = (
        "concat_ws(',',\n"
        "      CASE WHEN t.id_blank THEN 'psgc_id_blank'\n"
        f"           WHEN t.{pid} IS NULL THEN 'psgc_id_malformed' END,\n"
        f"      CASE WHEN t.{pid} IS NOT NULL AND t.key_rows > 1 THEN 'psgc_id_duplicated' END,\n"
        "      CASE WHEN t.any_uncastable THEN 'measure_uncastable' END,\n"
        + ",\n".join(f"      CASE WHEN {cond} THEN {lit(reason)} END" for reason, cond in problems.items())
        + "\n    ) AS quarantine_reasons")
    flags = _flag_exprs(spec, "t")
    final = (["CAST(t.estimate_year AS INT) AS estimate_year", f"t.{pid}", f"t.{cc}", f"t.{spec.banner_to}", *[f"t.{to}" for to, _ in spec.text_columns.values()],
              *[f"t.{m.name}" for m in spec.measures], f"{_status_expr(spec, 't')} AS estimate_status",
              *[f"{expr} AS {name}" for name, expr in flags.items()], reasons]
             + [f"t.{name}" for name in lineage] + [f"session.silver_{name} AS {name}" for name in stamp])

    clean_columns = [name for name, _ in spec.clean_columns()]
    quarantine_select = ["estimate_year", pid, spec.banner_to,
                         "split(quarantine_reasons, ',') AS quarantine_reasons", *lineage, *stamp]
    clean, quarantine = silver_ref(spec.clean_candidate), silver_ref(spec.quarantine_candidate)
    lines = _header(spec, "Silver build", "sql", f"etl/03_silver/{spec.clean_file}") + [
        "--",
        "-- Rebuilds the two candidate tables from the current Bronze batches only (01-control.current_batches:",
        "-- the latest succeeded delivery version of each logical dataset). Bronze is read, never changed.",
        f"-- Each current Bronze '{spec.unit_kind}' row becomes one candidate per estimate year its delivery covers",
        f"-- ({', '.join(spec.years)} in the contract), and every candidate ends in exactly one of the two tables:",
        f"--   {spec.clean_candidate}       one row per unit per estimate year, typed;",
        f"--   {spec.quarantine_candidate}  candidates that cannot be trusted, with their reasons.",
        "-- Title, header, region banner, blank and footer rows stay in Bronze; banners only give each unit its",
        "-- region label. The Silver tables are never written here: the gate (the next task) checks the",
        "-- candidates and publishes them only if no check fails (D-025). It rebuilds on every run.",
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
        "CREATE SCHEMA IF NOT EXISTS edu_access.`03-silver`;",
        f"ALTER SCHEMA edu_access.`03-silver` OWNER TO `{OWNER_GROUP}`;",
        "",
        "-- Every candidate once, typed, with the reasons it would be quarantined. A reason is decided with",
        "-- explicit NULL handling, and concat_ws never returns NULL, so quarantine_reasons = '' and <> ''",
        "-- split the candidates without losing any.",
        f"CREATE OR REPLACE TEMPORARY VIEW {view} AS",
        "WITH bronze AS (",
        "  SELECT r.*",
        f"  FROM {_bronze_ref(spec)} AS r",
        f"  JOIN {CONTROL}.current_batches AS c ON r.batch_id = c.batch_id",
        f"  WHERE c.source_id = {lit(source)}",
        "),",
        "-- Region context: number the banner rows in Excel row order within each batch and sheet, so every",
        "-- unit gets the banner above it, and nothing is carried from one delivery to another.",
        "ordered AS (",
        "  SELECT r.*,",
        f"         SUM(CASE WHEN r.source_row_kind = {lit(spec.banner_kind)} THEN 1 ELSE 0 END) OVER (",
        "           PARTITION BY r.batch_id, r.source_sheet ORDER BY r.source_row_number",
        "           ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS banner_seq",
        "  FROM bronze AS r",
        f"  WHERE r.source_row_kind IN ({lit(spec.unit_kind)}, {lit(spec.banner_kind)})",
        "),",
        "banners AS (",
        f"  SELECT batch_id, source_sheet, banner_seq, NULLIF({whitespace('o.' + bq(spec.banner_column))}, '') AS {spec.banner_to}",
        f"  FROM ordered AS o WHERE o.source_row_kind = {lit(spec.banner_kind)}",
        "),",
        "units AS (",
        f"  SELECT o.*, b.{spec.banner_to}",
        "  FROM ordered AS o",
        "  LEFT JOIN banners AS b",
        "    ON b.batch_id = o.batch_id AND b.source_sheet = o.source_sheet AND b.banner_seq = o.banner_seq",
        f"  WHERE o.source_row_kind = {lit(spec.unit_kind)}",
        "),",
        "-- Unpivot: one candidate per unit and estimate year the delivery covers, the year's five measures",
        "-- still as the published text.",
        "candidates AS (",
        "\n  UNION ALL\n".join(branches),
        "),",
        "-- The padded ID (O-2). A malformed ID gets no padded form, so it can never match another row.",
        "keyed AS (",
        "  SELECT",
        joined(keyed, 4),
        "  FROM candidates AS c",
        "),",
        "-- Measures typed only when they are numbers (DOUBLE, no rounding); the key counted per year.",
        "typed AS (",
        "  SELECT",
        joined(typed, 4),
        "  FROM keyed AS k",
        ")",
        "SELECT",
        joined(final, 2),
        "FROM typed AS t;",
        "",
        "-- One row per unit per estimate year, with the Bronze row it came from.",
        f"CREATE OR REPLACE TABLE {clean} USING DELTA AS",
        "SELECT",
        joined(clean_columns, 2),
        f"FROM {view}",
        "WHERE quarantine_reasons = '';",
        "",
        candidate_comment(clean, spec.clean_table),
        f"ALTER TABLE {clean} OWNER TO `{OWNER_GROUP}`;",
        "",
        "-- Candidates set aside, never deleted: the Bronze row, and why.",
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
    """[(check_name, scope, status)] in the order the gate writes them; scope: whole, batch, or year.
    Year checks are written once per batch and estimate year, named <check>_<year>."""
    year = [("rows_reconcile", "FAIL"), ("psgc_id_unique", "FAIL"), ("psgc_id_valid", "FAIL"),
            ("estimate_year_covered", "FAIL")]
    year += [(f"{m.name}_matches_bronze", "FAIL") for m in spec.measures]
    year += [("missing_measures_stay_null", "FAIL"), ("estimate_status_valid", "FAIL"),
             ("poverty_incidence_within_bounds", "FAIL"), ("cv_non_negative", "FAIL"), ("se_non_negative", "FAIL"),
             ("ci_contains_estimate", "FAIL"), ("flags_consistent", "FAIL"), ("region_banner_assigned", "FAIL"),
             ("quarantine_rate", "WARN/FAIL")]
    year += [(f"quarantine_reason_{r}", "WARN") for r in QUARANTINE_REASONS]
    year += [(f"flag_{f}", "WARN") for f in spec.flags] + [("flag_partial_estimate", "WARN")]
    year += [("rule_no_estimate", "record"), ("rule_psgc_id_padded", "record"),
             ("rule_text_whitespace_normalized", "record"), ("rule_blank_measures_to_null", "record")]
    whole = [("current_batches_present", "FAIL"), ("estimate_years_known", "FAIL"), ("lineage_complete", "FAIL"),
             ("rows_resolve_to_current_bronze_units", "FAIL"), ("rows_built_by_this_run", "FAIL"),
             ("one_timestamp_per_run", "FAIL")]
    batch = [("bronze_rows_accounted", "FAIL"), ("rule_structural_rows_not_estimates", "record")]
    batch += [(f"rows_kind_{k}", "record") for k in spec.structural_kinds]
    return ([(n, "whole", s) for n, s in whole] + [(n, "batch", s) for n, s in batch]
            + [(n, "year", s) for n, s in year])


def gate_sql(spec):
    source = spec.source_id
    lineage = [name for name, _ in LINEAGE]
    stamp = [name for name, _ in RUN_STAMP]
    clean_name, quarantine_name = dq_table_name(spec.clean_candidate), dq_table_name(spec.quarantine_candidate)
    years_values = ", ".join(f"({lit(y)})" for y in spec.years)
    pid, cc = spec.id_to, spec.correspondence_to
    pattern = spec.identifier_pattern

    # Per batch and estimate year: Bronze units (each covers every year of its batch), clean, quarantine.
    bronze_units = [
        "u.batch_id", "y.estimate_year",
        "COUNT(*) AS unit_rows",
        f"COUNT_IF(length(u.{bq(spec.identifier)}) < {spec.id_width}) AS padded_ids",
        "COUNT_IF(\n        " + "\n        OR ".join(
            f"{whitespace('u.' + bq(c))} <> u.{bq(c)}" for c in spec.text_columns) + "\n      ) AS whitespace_rows",
    ]
    blank_cells = " + ".join(
        f"CASE WHEN {_blank(_year_cell(spec, m, 'y.estimate_year', 'u'))} THEN 1 ELSE 0 END" for m in spec.measures)
    bronze_units.append(f"SUM(CASE WHEN q.source_row_number IS NULL THEN\n        {blank_cells}\n      ELSE 0 END) AS kept_blank_cells")

    mismatch = {m.name: (f"NOT (c.{m.name} IS NOT DISTINCT FROM "
                         f"{_typed(spec, _year_cell(spec, m, YEAR_TEXT.format('c'), 'b'))})") for m in spec.measures}
    flags = _flag_exprs(spec, "c")
    problems = _range_problems(spec, "c")
    clean_null_cells = " + ".join(f"CASE WHEN c.{m.name} IS NULL THEN 1 ELSE 0 END" for m in spec.measures)
    all_null = " AND ".join(f"c.{m.name} IS NULL" for m in spec.measures)
    clean_years = [
        "c.batch_id", f"{YEAR_TEXT.format('c')} AS estimate_year",
        "COUNT(*) AS clean_rows",
        f"COUNT(DISTINCT c.{pid}) AS clean_ids",
        # The padded ID must be the published Bronze ID, left-padded: the published value is not kept in Silver.
        (f"COUNT_IF(c.{pid} IS NULL OR NOT regexp_like(c.{pid}, '^[0-9]{{{spec.id_width}}}$')\n"
         f"        OR b.source_row_number IS NULL OR c.{pid} <> lpad(b.{bq(spec.identifier)}, {spec.id_width}, '0')\n"
         f"        OR c.{cc} IS NULL OR c.{cc} <> c.{pid} || {lit(spec.correspondence_suffix)}"
         ") AS invalid_ids"),
        f"COUNT_IF(NOT {_covers_expr('c.estimate_years_covered', YEAR_TEXT.format('c'))}) AS uncovered_rows",
        *[f"COUNT_IF(b.source_row_number IS NULL OR {mismatch[m.name]}) AS mismatched_{m.name}" for m in spec.measures],
        f"SUM({clean_null_cells}) AS clean_null_cells",
        (f"COUNT_IF(c.estimate_status IS NULL OR c.estimate_status NOT IN ({', '.join(lit(s) for s in ESTIMATE_STATUSES)})\n"
         f"        OR c.estimate_status <> {_status_expr(spec, 'c')}) AS invalid_status_rows"),
        f"COUNT_IF({problems['incidence_out_of_range']}) AS incidence_out_of_bounds",
        f"COUNT_IF({problems['cv_negative']}) AS negative_cv",
        f"COUNT_IF({problems['se_negative']}) AS negative_se",
        f"COUNT_IF({problems['ci_inconsistent']}) AS ci_problems",
        "COUNT_IF(\n        " + "\n        OR ".join(
            f"c.{name} IS NULL OR c.{name} <> ({expr})" for name, expr in flags.items()) + "\n      ) AS inconsistent_flags",
        f"COUNT_IF(c.{spec.banner_to} IS NULL) AS no_banner_rows",
        *[f"COUNT_IF(c.{name}) AS flagged_{name}" for name in spec.flags],
        "COUNT_IF(c.estimate_status = 'partial_estimate') AS partial_rows",
        f"COUNT_IF(c.estimate_status = 'no_estimate' AND {all_null}) AS no_estimate_rows",
    ]
    quarantine_years = ["q.batch_id", f"{YEAR_TEXT.format('q')} AS estimate_year", "COUNT(*) AS quarantined_rows"] + [
        f"COUNT_IF(array_contains(q.quarantine_reasons, {lit(r)})) AS reason_{r}" for r in QUARANTINE_REASONS]

    grid_values = ["unit_rows", "padded_ids", "whitespace_rows", "kept_blank_cells", "clean_rows", "clean_ids",
                   "invalid_ids", "uncovered_rows", *[f"mismatched_{m.name}" for m in spec.measures], "clean_null_cells",
                   "invalid_status_rows", "incidence_out_of_bounds", "negative_cv", "negative_se", "ci_problems",
                   "inconsistent_flags", "no_banner_rows", *[f"flagged_{f}" for f in spec.flags], "partial_rows",
                   "no_estimate_rows", "quarantined_rows", *[f"reason_{r}" for r in QUARANTINE_REASONS]]
    grid = ["g.batch_id", "g.estimate_year"] + [f"COALESCE({v}, 0) AS {v}" for v in grid_values]

    def check(name, table, status, expected, actual, source, scope):
        batch = "CAST(NULL AS STRING)" if scope == "whole" else "batch_id"
        check_name = lit(name) if scope != "year" else f"{lit(name + '_')} || estimate_year"
        return (f"SELECT {batch} AS batch_id, {lit(table)} AS table_name, {check_name} AS check_name,\n"
                f"         {status} AS status,\n"
                f"         {expected} AS expected, {actual} AS actual FROM {source}")

    def must_equal(name, expected, actual, source="years", scope="year", table=clean_name):
        return check(name, table, f"CASE WHEN {actual} = {expected} THEN 'PASS' ELSE 'FAIL' END",
                     f"CAST({expected} AS STRING)", f"CAST({actual} AS STRING)", source, scope)

    def must_be_zero(name, actual, source="years", scope="year"):
        return must_equal(name, "0", actual, source, scope)

    def warn_if_any(name, actual, table=clean_name):
        return check(name, table, f"CASE WHEN {actual} = 0 THEN 'PASS' ELSE 'WARN' END", "'0'",
                     f"CAST({actual} AS STRING)", "years", "year")

    def record(name, actual, source="years", scope="year"):
        return check(name, clean_name, "'PASS'", "CAST(NULL AS STRING)", f"CAST({actual} AS STRING)", source, scope)

    rate_status = ("CASE WHEN quarantined_rows = 0 THEN 'PASS' "
                   + (f"WHEN quarantined_rows * {_number(100)} > unit_rows * {_number(spec.quarantine_fail_percent)} "
                      "THEN 'FAIL' ")
                   + "ELSE 'WARN' END")
    checks = [
        "-- The whole build",
        check("current_batches_present", clean_name, "CASE WHEN current_batches > 0 THEN 'PASS' ELSE 'FAIL' END",
              "'at least 1'", "CAST(current_batches AS STRING)", "found", "whole"),
        must_be_zero("estimate_years_known", "unknown_year_batches", "found", "whole"),
        must_be_zero("lineage_complete", "missing_lineage", "whole", "whole"),
        must_be_zero("rows_resolve_to_current_bronze_units", "unresolved_rows", "unresolved", "whole"),
        must_be_zero("rows_built_by_this_run", "other_run_rows", "whole", "whole"),
        must_equal("one_timestamp_per_run", "1", "timestamps", "whole", "whole"),
        "-- Each current batch: every Bronze row is a unit or a known structural row",
        check("bronze_rows_accounted", clean_name, "CASE WHEN other_rows = 0 THEN 'PASS' ELSE 'FAIL' END",
              "CAST(bronze_rows AS STRING)", "CAST(unit_rows + structural_rows AS STRING)", "batches", "batch"),
        record("rule_structural_rows_not_estimates", "structural_rows", "batches", "batch"),
        *[record(f"rows_kind_{k}", f"{k}_rows", "batches", "batch") for k in spec.structural_kinds],
        "-- Each batch and estimate year: reconciliation, keys, values against Bronze, ranges, NULLs",
        must_equal("rows_reconcile", "unit_rows", "clean_rows + quarantined_rows"),
        must_be_zero("psgc_id_unique", "clean_rows - clean_ids"),
        must_be_zero("psgc_id_valid", "invalid_ids"),
        must_be_zero("estimate_year_covered", "uncovered_rows"),
        *[must_be_zero(f"{m.name}_matches_bronze", f"mismatched_{m.name}") for m in spec.measures],
        must_equal("missing_measures_stay_null", "kept_blank_cells", "clean_null_cells"),
        must_be_zero("estimate_status_valid", "invalid_status_rows"),
        must_be_zero("poverty_incidence_within_bounds", "incidence_out_of_bounds"),
        must_be_zero("cv_non_negative", "negative_cv"),
        must_be_zero("se_non_negative", "negative_se"),
        must_be_zero("ci_contains_estimate", "ci_problems"),
        must_be_zero("flags_consistent", "inconsistent_flags"),
        must_be_zero("region_banner_assigned", "no_banner_rows"),
        f"-- Each batch and estimate year: quarantine (WARN above 0, FAIL above {_number(spec.quarantine_fail_percent)}% of the units)",
        check("quarantine_rate", quarantine_name, rate_status,
              # No ';' inside a string: store.split_statements splits files on it.
              f"'0 (FAIL above {_number(spec.quarantine_fail_percent)}% of ' || CAST(unit_rows AS STRING) || ')'",
              "CAST(quarantined_rows AS STRING)", "years", "year"),
        *[warn_if_any(f"quarantine_reason_{r}", f"reason_{r}", quarantine_name) for r in QUARANTINE_REASONS],
        "-- Each batch and estimate year: statistical warnings, flagged on the row and never corrected (WARN)",
        *[warn_if_any(f"flag_{f}", f"flagged_{f}") for f in spec.flags],
        warn_if_any("flag_partial_estimate", "partial_rows"),
        "-- Each batch and estimate year: how many rows each rule changed or marked (records, always PASS)",
        record("rule_no_estimate", "no_estimate_rows"),
        record("rule_psgc_id_padded", "padded_ids"),
        record("rule_text_whitespace_normalized", "whitespace_rows"),
        record("rule_blank_measures_to_null", "kept_blank_cells"),
    ]
    union = []
    for item in checks:
        if item.startswith("--"):
            union.append("  " + item)
        else:
            union.append(("  UNION ALL " if any(not u.lstrip().startswith("--") for u in union) else "  ") + item)

    silver_rows = (f"  SELECT {', '.join(['estimate_year', *lineage, *stamp])} FROM clean\n"
                   f"  UNION ALL SELECT {', '.join(['estimate_year', *lineage, *stamp])} FROM quarantined")
    missing_lineage = " OR ".join(f"{name} IS NULL" for name in ["estimate_year", *lineage, *stamp])
    known = " + ".join(f"CASE WHEN {_covers('estimate_years_covered', y)} THEN 1 ELSE 0 END" for y in spec.years)
    kinds = ", ".join(lit(k) for k in spec.structural_kinds)

    lines = _header(spec, "Silver gate", "gate", f"etl/03_silver/90_validate_{spec.clean_table}.sql") + [
        "--",
        "-- The job task after the Silver build. It checks the candidate tables the build wrote, one row",
        "-- per check in data_quality_results: the whole build, each current batch, and each batch and",
        "-- estimate year (check names end in the year). On any FAIL it records the run 'failed' and stops",
        "-- the task before publishing, so the Silver tables keep the last build that passed and nothing",
        "-- downstream runs. Otherwise it copies the candidates to the Silver tables and records the run",
        "-- 'succeeded'. PASS: as expected. WARN: recorded, the build is published (statistical flags,",
        "-- quarantined rows). FAIL: the candidate cannot be trusted. Results hold counts, never row values.",
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
        f"  SELECT batch_id, estimate_years_covered FROM {CONTROL}.current_batches WHERE source_id = {lit(source)}",
        "),",
        "bronze AS (",
        f"  SELECT r.* FROM {_bronze_ref(spec)} AS r JOIN cur ON r.batch_id = cur.batch_id",
        "),",
        f"clean AS (SELECT * FROM {silver_ref(spec.clean_candidate)}),",
        f"quarantined AS (SELECT * FROM {silver_ref(spec.quarantine_candidate)}),",
        f"known_years AS (SELECT * FROM (VALUES {years_values}) AS v(estimate_year)),",
        "-- Every batch and estimate year the current batches cover: the grid every year check is written for.",
        "grid AS (",
        "  SELECT cur.batch_id, y.estimate_year FROM cur",
        f"  JOIN known_years AS y ON {_covers_expr('cur.estimate_years_covered', 'y.estimate_year')}",
        "),",
        "-- Each Bronze unit row once per estimate year its batch covers, marked if Silver set it aside.",
        "bronze_units AS (",
        "  SELECT",
        joined(bronze_units, 4),
        "  FROM bronze AS u",
        "  JOIN cur ON u.batch_id = cur.batch_id",
        f"  JOIN known_years AS y ON {_covers_expr('cur.estimate_years_covered', 'y.estimate_year')}",
        "  LEFT JOIN quarantined AS q",
        "    ON q.source_sha256 = u.source_sha256 AND q.source_row_number = u.source_row_number",
        f"   AND {YEAR_TEXT.format('q')} = y.estimate_year",
        f"  WHERE u.source_row_kind = {lit(spec.unit_kind)}",
        "  GROUP BY u.batch_id, y.estimate_year",
        "),",
        "-- Each clean row beside its Bronze row: every value is the published cell, typed.",
        "clean_years AS (",
        "  SELECT",
        joined(clean_years, 4),
        "  FROM clean AS c",
        "  LEFT JOIN bronze AS b ON b.source_sha256 = c.source_sha256 AND b.source_row_number = c.source_row_number",
        "  GROUP BY c.batch_id, c.estimate_year",
        "),",
        "quarantine_years AS (",
        "  SELECT",
        joined(quarantine_years, 4),
        "  FROM quarantined AS q GROUP BY q.batch_id, q.estimate_year",
        "),",
        "years AS (",
        "  SELECT",
        joined(grid, 4),
        "  FROM grid AS g",
        "  LEFT JOIN bronze_units AS bu ON bu.batch_id = g.batch_id AND bu.estimate_year = g.estimate_year",
        "  LEFT JOIN clean_years AS cy ON cy.batch_id = g.batch_id AND cy.estimate_year = g.estimate_year",
        "  LEFT JOIN quarantine_years AS qy ON qy.batch_id = g.batch_id AND qy.estimate_year = g.estimate_year",
        "),",
        "-- Each current batch: its Bronze rows by kind. Structural rows stay in Bronze, never as estimates.",
        "batches AS (",
        "  SELECT cur.batch_id,",
        "         COUNT(r.source_row_number) AS bronze_rows,",
        f"         COUNT_IF(r.source_row_kind = {lit(spec.unit_kind)}) AS unit_rows,",
        f"         COUNT_IF(r.source_row_kind IN ({kinds})) AS structural_rows,",
        *[f"         COUNT_IF(r.source_row_kind = {lit(k)}) AS {k}_rows," for k in spec.structural_kinds],
        f"         COUNT_IF(r.source_row_kind IS NULL OR r.source_row_kind NOT IN ({lit(spec.unit_kind)}, {kinds})) AS other_rows",
        "  FROM cur LEFT JOIN bronze AS r ON r.batch_id = cur.batch_id",
        "  GROUP BY cur.batch_id",
        "),",
        "-- A batch covering a year the contract's columns do not hold could not be unpivoted.",
        "found AS (",
        "  SELECT COUNT(*) AS current_batches,",
        f"         COUNT_IF(({known}) <> length(estimate_years_covered) - length(replace(estimate_years_covered, ',', '')) + 1)",
        "           AS unknown_year_batches",
        "  FROM cur",
        "),",
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
        "-- Silver rows whose Bronze row is not a unit row of a current batch (an old version, a banner, or gone).",
        "unresolved AS (",
        "  SELECT COUNT(*) AS unresolved_rows",
        "  FROM silver_rows AS s",
        "  LEFT JOIN bronze ON s.source_sha256 = bronze.source_sha256 AND s.source_row_number = bronze.source_row_number",
        f"    AND s.batch_id = bronze.batch_id AND bronze.source_row_kind = {lit(spec.unit_kind)}",
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
    "logical_dataset": "The approved dataset the delivery belongs to (D-018), e.g. `sae_city_municipal_2018_2021_2023`",
    "estimate_years_covered": "Every estimate year the delivery covers, comma-separated, as Bronze recorded it",
    "batch_id": "The Bronze batch (one workbook delivery); joins `01-control`.ingestion_batches",
    "delivery_version": "Which delivery of the logical dataset: 1, or 2+ after an approved revision",
    "schema_version": "Which header the workbook had; tells a measure no schema publishes (NULL) from a published blank (NULL)",
    "source_sha256": "SHA-256 of the workbook; with `source_row_number`, identifies the Bronze row exactly",
    "source_row_number": "The Excel row number of the unit row; open the workbook (or Bronze) at this row to see every published cell, the unpadded ID included",
    "run_id": "The job run that built the row (`{{job.run_id}}`); every row of a build has the same one, as do the gate's results",
    "cleaned_at_utc": "When that build ran; one value for both tables, in UTC",
    "code_revision": "The commit that ran the build",
}

QUARANTINE_MEANING = {
    "psgc_id_blank": "`PSGC ID` is NULL or blank",
    "psgc_id_malformed": "`PSGC ID` is not five or six digits, so it has no padded form",
    "psgc_id_duplicated": "the same padded ID appears more than once in the estimate year among current batches (also two datasets sharing a year); every copy is set aside",
    "measure_uncastable": "a measure is not blank and not a plain or scientific-notation number (e.g. `n.a.`, ` 5`)",
    "incidence_out_of_range": "poverty incidence is below {min} or above {max} percent",
    "cv_negative": "the coefficient of variation is negative",
    "se_negative": "the standard error is negative",
    "ci_inconsistent": "the lower limit is above the upper limit, or the estimate lies outside its own 90% interval",
}


def dictionary_markdown(spec):
    m = spec.mapping
    id_rule = m["identifier"]
    rows = [
        ("estimate_year", "INT", f"the year in the column names ({', '.join(spec.years)})",
         f"One row per estimate year the delivery covers (`estimate_years_covered`); key, with `{spec.id_to}`. "
         "A calendar year, so typed as a number (filter `estimate_year = 2023`, no quotes). "
         "Named for what it is, so it is never confused with DepEd's `school_year`", "Never", "O-1"),
        (spec.id_to, "STRING", f"`{spec.identifier}`",
         f"The published ID left-padded with zeros to {spec.id_width} digits (Excel dropped the leading zero of "
         "1,073 IDs: `12801` becomes `012801`). Key, with `estimate_year`. The old 6-digit PSA code "
         "(region 2 + province 2 + city or municipality 2), not the 10-digit PSGC code. The unpadded value stays in Bronze",
         "Never", "O-2"),
        (spec.correspondence_to, "STRING", f"`{spec.identifier}`",
         f"`{spec.id_to}` followed by `{spec.correspondence_suffix}`: the 9-digit code PSGC keeps in its own "
         "`correspondence_code` column (same name). It is the key Integration joins to PSGC 2Q 2026 (D-012) to get "
         "the 10-digit `psgc_code`, the official province and region, and the link to DepEd and HDX; `psgc_id` "
         "cannot join PSGC directly, because PSGC has no 6-digit column. Matched 1,612 of 1,612 in the profile",
         "Never", "O-2, X-1"),
        (spec.banner_to, "STRING", f"`{spec.banner_column}` of the region banner rows", m["region_banner"]["rule"],
         "Never (the gate fails otherwise)", m["region_banner"]["finding"]),
    ]
    rows += [(to, "STRING", f"`{src}`", rule, "Published blank", "O-3, O-10") for src, (to, rule) in spec.text_columns.items()]
    for measure in spec.measures:
        published = ", ".join(f"`{spec.year_columns[y][measure.name]}`" for y in spec.years if spec.year_columns[y][measure.name])
        rows.append((measure.name, "DOUBLE", published, f"{m['numeric']['rule']} Unit: {measure.unit}",
                     "Published blank (or a column the schema does not have). Never 0", measure.finding))
    rows += [
        ("estimate_status", "STRING", "the five measures",
         "`estimated`: all five published; `no_estimate`: none published (Kalayaan, footnote 3); `partial_estimate`: some "
         "published, some not (WARN). Missing is not zero poverty", "Never", "O-5"),
        (spec.cv_flag, "BOOLEAN", "`coefficient_of_variation`",
         f"TRUE when CV is above {_number(spec.cv_threshold)}: the estimate is imprecise. Flag only, the value is kept",
         "Never", m["flags"]["finding_cv"].split(":")[0]),
        ("se_cv_inconsistent", "BOOLEAN", "`standard_error`, `poverty_incidence`, `coefficient_of_variation`",
         f"TRUE when |SE - incidence x CV / 100| > {_number(spec.se_tolerance)}. SE is kept as published, never recomputed",
         "Never", m["flags"]["finding_se"].split(":")[0]),
        ("lower_limit_not_positive", "BOOLEAN", "`ci90_lower_limit`",
         "TRUE when the lower limit is 0 or below: a known statistical warning, not clipped or replaced",
         "Never", m["flags"]["finding_lower"].split(":")[0]),
    ]
    rows += [(name, kind.upper(), "provenance" if name not in ("run_id", "cleaned_at_utc", "code_revision") else "Silver run",
              LINEAGE_MEANING[name], "Never", "") for name, kind in spec.clean_columns() if name in LINEAGE_MEANING]

    lines = [
        f"# `{spec.clean_table}`: Silver data dictionary",
        "",
        f"Generated by `python -m src.silver.cli dictionary --source {spec.source_id}` from "
        f"[the Bronze contract](../../../config/ingestion/{spec.source_id}.json) and "
        f"[the Silver rules](../../../config/mappings/{spec.source_id}.json). Do not edit by hand; "
        "`tests/test_silver_psa.py` fails if it differs.",
        "",
        f"`` edu_access.`03-silver`.{spec.clean_table} ``: one row per city or municipality row of the workbook per "
        "estimate year, for the current delivery of each logical dataset only (`01-control`.current_batches). "
        f"Key: (`{spec.id_to}`, `estimate_year`). The wide year columns are unpivoted (D-034), so each row holds one "
        "year's estimate with its CV, SE and 90% limits. Every row names the Bronze row it came from "
        "(`source_sha256`, `source_row_number`), so each published cell can be read back from Bronze. "
        "Rules, counts and the gate: [docs/operations/silver.md](../../operations/silver.md#psa-poverty-stat).",
        "",
        "**Poverty incidence** is the percentage of **persons** whose per capita income is below the poverty "
        "threshold (PSA press release 2026-43): not families, not students, and not a count of people. Never sum it "
        "across places; never average it without population weights.",
        "",
        "**NULL** never means zero. A blank cell stays NULL, and so does a measure a schema version does not publish; "
        "`schema_version` and `estimate_years_covered` tell them apart. Cities and municipalities absent from the "
        "workbook have no row at all (not a row of NULLs); finding them against PSGC is Integration's job.",
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
        "Candidates that cannot be trusted, set aside rather than deleted. Every unit row of a current batch is in "
        "exactly one of the two tables for each estimate year its delivery covers. Read the published values "
        "from Bronze with `source_sha256` and `source_row_number`.",
        "",
        "| Column | Type | Meaning |",
        "|---|---|---|",
        "| `estimate_year` | INT | As in the clean table |",
        f"| `{spec.id_to}` | STRING | The padded ID, or NULL when the published ID is blank or malformed "
        "(read the published value from Bronze) |",
        f"| `{spec.banner_to}` | STRING | As in the clean table |",
        "| `quarantine_reasons` | `ARRAY<STRING>` | Every reason that applies, never empty (below) |",
    ]
    lines += [f"| `{name}` | {kind.upper()} | {LINEAGE_MEANING[name]} |"
              for name, kind in spec.quarantine_columns() if name in LINEAGE_MEANING]
    lines += ["", "| Reason | Meaning |", "|---|---|"]
    lines += [f"| `{r}` | {QUARANTINE_MEANING[r].format(min=_number(spec.incidence_min), max=_number(spec.incidence_max))} |"
              for r in QUARANTINE_REASONS]
    lines += ["", "## Published columns not carried into Silver", "", "| Bronze column | Why |", "|---|---|"]
    lines += [f"| `{c}` (unit rows) | {why} |" for c, why in m.get("not_carried", {}).items()]
    lines += [f"| `{spec.identifier}` as published | Replaced by the padded `{spec.id_to}`; the published value stays in Bronze |"]
    lines += ["", "## Numbers", "", m["numeric"]["why_double"], "",
              f"Pattern a published measure must match: `{spec.numeric_pattern}`.", ""]
    if spec.absent:
        lines += ["## Measures a schema version does not publish", "", "| Schema | Estimate year, measure |", "|---|---|"]
        lines += [f"| `{v}` | {', '.join(f'{y} `{n}`' for y, n in pairs)} |" for v, pairs in spec.absent.items()]
        lines.append("")
    return "\n".join(lines)
