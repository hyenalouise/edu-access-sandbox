"""Silver for psa_psgc: the spec, the build SQL, the gate SQL, and the data dictionary.

Two reviewed files define it, and nothing else:

- `config/ingestion/psa_psgc.json`, the Bronze contract: the publisher columns
  and the master reference quarter (`master_reference_period`, D-012);
- `config/mappings/psa_psgc.json`, the Silver rules: identifier and codes, text
  columns, population, the income class split, every accepted category label,
  the derived parent codes, and quarantine.

The grain stays the source's (D-021): one row per PSGC code per publication
quarter, for the current delivery version of every quarter (D-015). Silver
changes types, names, labels and missing values only, and adds the parent codes
the code itself encodes (O-10). The SQL follows src/silver/sql.py and
src/silver/psa_poverty_stat.py: the build writes the candidate tables, the gate
checks them and publishes only if no check FAILs (D-025), both run as SQL tasks,
and only syntax both Databricks and DuckDB accept is used.

A repeated code quarantines every copy and FAILs the gate on its own, so a
build with one is never published: PSGC is what Integration joins to, and a
repeated code would multiply joined rows (D-019, D-035).
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

SOURCE_ID = "psa_psgc"
SAFE_LITERAL = re.compile(r"^[^'\\;]*$")
SNAKE = re.compile(r"^[a-z][a-z0-9_]*$")
POPULATION_PATTERN = "^[0-9]{1,9}$"   # nine digits always fit INT

# Why a row is set aside, in the order they are listed on a quarantined row.
QUARANTINE_REASONS = (
    "psgc_code_blank",
    "psgc_code_malformed",
    "psgc_code_duplicated",
    "correspondence_code_malformed",
    "population_uncastable",
)
FLAGS = ("level_blank", "population_is_zero", "has_population_footnote")
CATEGORY_COLUMNS = ("geographic_level", "city_class", "urban_rural", "status")

# Bronze provenance carried on every clean and quarantined row, then the Silver run's own stamp.
LINEAGE = (
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
class Label:
    published: str
    standard: str            # NULL (None) for a published placeholder such as '-'
    null_reason: str = None
    retained: bool = None    # income class only: TRUE for a starred class


@dataclass
class PsgcSpec:
    source_id: str
    bronze_table: str
    clean_file: str
    clean_table: str
    quarantine_table: str
    clean_candidate: str
    quarantine_candidate: str
    master_period: str
    identifier: str
    identifier_pattern: str
    correspondence: str
    correspondence_pattern: str
    text_columns: dict          # Bronze column -> Silver column (whitespace rule, blank to NULL)
    population: str
    population_markers: dict    # published marker -> null reason
    income: str
    income_labels: list
    categories: dict            # Bronze column -> [Label]
    levels: dict                # region, province, city, municipality, barangay -> published level
    no_province_city_class: str  # a city of this class has no province above it (HUC)
    no_province_codes: list      # cities or municipalities listed as having no province (Pateros)
    population_blank_reason: str
    quarantine_fail_percent: float
    mapping: dict = field(repr=False)

    def reason_columns(self):
        """Category columns whose placeholder labels carry a null reason."""
        return [c for c, labels in self.categories.items() if any(l.null_reason for l in labels)]

    def clean_columns(self):
        """[(name, type)] of the clean table, in order."""
        columns = [("publication_period", "string"), ("publication_date", "date"), ("is_master_reference", "boolean"),
                   ("psgc_code", "string"), (self.text_columns["name"], "string"), ("correspondence_code", "string"),
                   ("geographic_level", "string"), ("region_code", "string"), ("province_code", "string"),
                   ("city_municipality_code", "string")]
        columns += [(self.text_columns["old_names"], "string"), ("city_class", "string"),
                    ("income_class", "string"), ("income_class_retained_after_downgrade", "boolean"),
                    ("income_class_null_reason", "string"), ("urban_rural", "string"),
                    ("urban_rural_null_reason", "string"), ("population", "int"), ("population_null_reason", "string"),
                    (self.text_columns["column_j_footnote"], "string"), ("status", "string")]
        columns += [(f, "boolean") for f in FLAGS]
        return columns + list(LINEAGE) + list(RUN_STAMP)

    def quarantine_columns(self):
        return ([("publication_period", "string"), ("psgc_code", "string"), (self.text_columns["name"], "string"),
                 ("quarantine_reasons", "array<string>")] + list(LINEAGE) + list(RUN_STAMP))


def load_spec(repo_root, source_id=SOURCE_ID):
    path = Path(repo_root) / "config" / "mappings" / f"{source_id}.json"
    if not path.is_file():
        raise _error(f"{path} does not exist; {source_id} has no Silver rules.")
    mapping = json.loads(path.read_text(encoding="utf-8"))
    contract, _ = load_source_config(repo_root, source_id)
    registry = yaml.safe_load((Path(repo_root) / "config" / "tables.yml").read_text(encoding="utf-8"))
    entry = next((s for s in registry["source_tables"] if s["source_id"] == source_id), None)
    return build_spec(mapping, contract, entry)


def _labels(entries, column):
    labels = []
    for e in entries:
        published = e["published"]
        standard = e.get("standard", e.get("income_class"))
        labels.append(Label(published, standard, e.get("null_reason"), e.get("retained_after_downgrade")))
        if (standard is None) != bool(e.get("null_reason")):
            raise _error(f"{column}: label {published!r} must have a standard value or a null_reason, not both or neither.")
    keys = [" ".join(l.published.split()) for l in labels]
    if len(set(keys)) != len(keys):
        raise _error(f"{column}: two labels are the same after whitespace is normalized.")
    return labels


def build_spec(mapping, contract, registry_entry):
    source_id = contract["source_id"]
    if mapping.get("source_id") != source_id:
        raise _error("source_id differs from the Bronze contract.")
    silver = (registry_entry or {}).get("silver", {})
    if registry_entry is None or silver.get("table") != mapping["silver_table"] \
            or silver.get("quarantine_table") != mapping["quarantine_table"] \
            or silver.get("candidate_table") != mapping["candidate_table"] \
            or silver.get("candidate_quarantine_table") != mapping["candidate_quarantine_table"]:
        raise _error("the Silver, quarantine and candidate table names must match config/tables.yml.")

    identifier = mapping["identifier"]["column"]
    correspondence = "correspondence_code"
    text = {c: c for c in mapping["free_text_columns"]}
    text.update({c: entry["to"] for c, entry in mapping["renames"].items()})
    population = mapping["population"]["column"]
    income = mapping["income_classification"]["column"]
    categories = {c: _labels(entry["labels"], c) for c, entry in mapping["categories"].items()}
    income_labels = _labels(mapping["income_classification"]["labels"], income)

    published = source_columns(contract)
    classified = {identifier, *mapping["codes"], *text, population, income, *categories}
    unclassified = sorted(set(published) - classified)
    if unclassified:
        raise _error(f"columns {unclassified} have no Silver rule. A new publisher column needs a reviewed "
                     "entry in config/mappings/psa_psgc.json.")
    stray = sorted(classified - set(published))
    if stray:
        raise _error(f"the mapping names columns the contract does not have: {stray}.")
    if set(categories) != set(CATEGORY_COLUMNS) or set(text) != {"name", "old_names", "column_j_footnote"} \
            or list(mapping["codes"]) != [correspondence]:
        raise _error(f"the mapping must describe exactly the columns {list(CATEGORY_COLUMNS)}, name, old_names, "
                     "column_j_footnote and correspondence_code; a new one needs a change to src/silver/psa_psgc.py.")
    if not all(SNAKE.match(to) for to in text.values()):
        raise _error("renamed Silver columns must be snake_case.")

    markers = {k: v["reason"] for k, v in mapping["population"]["null_markers"].items()}
    levels = mapping["hierarchy"]["levels"]
    literals = [mapping["identifier"]["pattern"], mapping["codes"][correspondence]["pattern"], *markers, *markers.values(),
                *levels.values(), contract["master_reference_period"] or "",
                *(v for labels in [*categories.values(), income_labels] for l in labels
                  for v in (l.published, l.standard or "", l.null_reason or ""))]
    unsafe = [v for v in literals if not SAFE_LITERAL.match(v)]
    if unsafe:
        raise _error(f"patterns and labels may not contain quotes, backslashes or ';': {unsafe}.")
    level_labels = {l.standard for l in categories["geographic_level"]}
    if not set(levels.values()) <= level_labels:
        raise _error("hierarchy.levels must name accepted geographic_level labels.")
    if not {"region", "province", "city", "municipality", "barangay"} <= set(levels):
        raise _error("hierarchy.levels must name the region, province, city, municipality and barangay labels.")
    huc = mapping["hierarchy"]["no_province_city_class"]
    if huc not in {l.standard for l in categories["city_class"]}:
        raise _error("hierarchy.no_province_city_class must be an accepted city_class label.")
    exceptions = [e["code"] for e in mapping["hierarchy"].get("no_province_exceptions", [])]
    if any(not re.fullmatch(mapping["identifier"]["pattern"], c) for c in exceptions) or len(set(exceptions)) != len(exceptions):
        raise _error("hierarchy.no_province_exceptions must list distinct, valid PSGC codes.")
    blank_reason = mapping["population"]["blank_reason"]
    if not SAFE_LITERAL.match(blank_reason):
        raise _error("population.blank_reason may not contain quotes, backslashes or ';'.")
    percent = mapping["quarantine"]["fail_above_percent"]
    if not isinstance(percent, (int, float)) or not 0 <= percent < 100:
        raise _error("quarantine.fail_above_percent must be a number from 0 to under 100.")

    return PsgcSpec(
        source_id=source_id, bronze_table=contract["bronze_table"], clean_file=silver["clean_file"],
        clean_table=mapping["silver_table"], quarantine_table=mapping["quarantine_table"],
        clean_candidate=silver["candidate_table"], quarantine_candidate=silver["candidate_quarantine_table"],
        master_period=contract["master_reference_period"], identifier=identifier,
        identifier_pattern=mapping["identifier"]["pattern"], correspondence=correspondence,
        correspondence_pattern=mapping["codes"][correspondence]["pattern"], text_columns=text,
        population=population, population_markers=markers, income=income, income_labels=income_labels,
        categories=categories, levels=levels, no_province_city_class=huc, no_province_codes=exceptions,
        population_blank_reason=blank_reason, quarantine_fail_percent=percent, mapping=mapping,
    )


# --- Shared SQL pieces -------------------------------------------------------------------

def _bronze_ref(spec):
    return f"edu_access.`02-bronze`.{spec.bronze_table}"


def _header(spec, what, command, path):
    return [
        f"-- {what} for {spec.source_id}. Generated from config/ingestion/{spec.source_id}.json",
        f"-- and config/mappings/{spec.source_id}.json by src/silver/psa_psgc.py:",
        f"--   python -m src.silver.cli {command} --source {spec.source_id} > {path}",
        "-- Do not edit by hand; tests/test_silver_psgc.py fails if it differs.",
    ]


def _number(value):
    return str(int(value)) if float(value).is_integer() else str(value)


def _norm(ref):
    """Whitespace normalized, blank as NULL: how every label and free-text value is read (D-022, D-023)."""
    return f"NULLIF({whitespace(ref)}, '')"


def _case(ref, pairs, default="NULL"):
    """CASE ref WHEN published THEN value ... END; values are SQL expressions."""
    whens = " ".join(f"WHEN {lit(p)} THEN {v}" for p, v in pairs)
    return f"CASE {ref} {whens} ELSE {default} END"


def _value(v):
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    return lit(v)


def _category(spec, column, ref):
    return _case(ref, [(l.published, _value(l.standard)) for l in spec.categories[column]])


def _category_reason(spec, column, ref):
    return _case(ref, [(l.published, _value(l.null_reason)) for l in spec.categories[column] if l.null_reason])


def _unmapped(labels, ref):
    return f"({ref} IS NOT NULL AND {ref} NOT IN ({', '.join(lit(l.published) for l in labels)}))"


def _income_class(spec, ref):
    return _case(ref, [(l.published, _value(l.standard)) for l in spec.income_labels])


def _income_retained(spec, ref):
    return _case(ref, [(l.published, _value(l.retained)) for l in spec.income_labels if l.retained is not None])


def _income_reason(spec, ref):
    return _case(ref, [(l.published, _value(l.null_reason)) for l in spec.income_labels if l.null_reason])


def _population(ref):
    return f"CASE WHEN regexp_like({ref}, {lit(POPULATION_PATTERN)}) THEN CAST({ref} AS INT) END"


def _population_reason(spec, ref):
    """A published marker's reason, or the blank reason: a NULL population always says why."""
    return _case(ref, [*[(m, lit(r)) for m, r in spec.population_markers.items()], ("", lit(spec.population_blank_reason))])


def _population_uncastable(spec, ref):
    markers = ", ".join(lit(m) for m in spec.population_markers)
    return f"({ref} <> '' AND NOT regexp_like({ref}, {lit(POPULATION_PATTERN)}) AND {ref} NOT IN ({markers}))"


def _master(spec, ref):
    return f"COALESCE({ref} = {lit(spec.master_period)}, FALSE)" if spec.master_period else "FALSE"


# --- Build ---------------------------------------------------------------------------------

def build_sql(spec):
    source = spec.source_id
    view = f"{source}_classified"
    lineage = [name for name, _ in LINEAGE]
    stamp = [name for name, _ in RUN_STAMP]
    ident, cc = bq(spec.identifier), bq(spec.correspondence)
    name_to, old_to, foot_to = (spec.text_columns[c] for c in ("name", "old_names", "column_j_footnote"))
    pattern = lit(spec.identifier_pattern)
    region, province, barangay = (lit(spec.levels[k]) for k in ("region", "province", "barangay"))

    normalized = ["r.*",
                  *[f"{_norm('r.' + bq(c))} AS n_{c}" for c in [*spec.text_columns, *spec.categories, spec.income]],
                  f"NULLIF(r.{cc}, '') AS n_correspondence",
                  f"COUNT(*) OVER (PARTITION BY r.batch_id, r.{ident}) AS code_rows"]
    final = [
        "n.publication_period", "CAST(n.publication_date AS DATE) AS publication_date",
        f"{_master(spec, 'n.publication_period')} AS is_master_reference",
        f"n.{ident} AS psgc_code", f"n.n_name AS {name_to}", "n.n_correspondence AS correspondence_code",
        f"{_category(spec, 'geographic_level', 'n.n_geographic_level')} AS geographic_level",
        f"CASE WHEN regexp_like(n.{ident}, {pattern}) THEN substr(n.{ident}, 1, 2) || '00000000' END AS region_code",
        "CASE WHEN p.is_province_position = 1 THEN p.psgc_code END AS province_code",
        (f"CASE WHEN regexp_like(n.{ident}, {pattern}) AND n.n_geographic_level = {barangay} "
         f"THEN substr(n.{ident}, 1, 7) || '000' END AS city_municipality_code"),
        f"n.n_old_names AS {old_to}",
        f"{_category(spec, 'city_class', 'n.n_city_class')} AS city_class",
        f"{_income_class(spec, 'n.n_' + spec.income)} AS income_class",
        f"{_income_retained(spec, 'n.n_' + spec.income)} AS income_class_retained_after_downgrade",
        f"{_income_reason(spec, 'n.n_' + spec.income)} AS income_class_null_reason",
        f"{_category(spec, 'urban_rural', 'n.n_urban_rural')} AS urban_rural",
        f"{_category_reason(spec, 'urban_rural', 'n.n_urban_rural')} AS urban_rural_null_reason",
        f"{_population('n.' + bq(spec.population))} AS population",
        f"{_population_reason(spec, 'n.' + bq(spec.population))} AS population_null_reason",
        f"n.n_column_j_footnote AS {foot_to}",
        f"{_category(spec, 'status', 'n.n_status')} AS status",
        "(n.n_geographic_level IS NULL) AS level_blank",
        f"COALESCE({_population('n.' + bq(spec.population))} = 0, FALSE) AS population_is_zero",
        "(n.n_column_j_footnote IS NOT NULL) AS has_population_footnote",
        ("concat_ws(',',\n"
         f"      CASE WHEN n.{ident} IS NULL OR n.{ident} = '' THEN 'psgc_code_blank'\n"
         f"           WHEN NOT regexp_like(n.{ident}, {pattern}) THEN 'psgc_code_malformed' END,\n"
         f"      CASE WHEN regexp_like(n.{ident}, {pattern}) AND n.code_rows > 1 THEN 'psgc_code_duplicated' END,\n"
         f"      CASE WHEN n.n_correspondence IS NOT NULL AND NOT regexp_like(n.n_correspondence, "
         f"{lit(spec.correspondence_pattern)}) THEN 'correspondence_code_malformed' END,\n"
         f"      CASE WHEN {_population_uncastable(spec, 'n.' + bq(spec.population))} THEN 'population_uncastable' END\n"
         "    ) AS quarantine_reasons"),
        *[f"n.{name}" for name in lineage], *[f"session.silver_{name} AS {name}" for name in stamp],
    ]
    clean_columns = [name for name, _ in spec.clean_columns()]
    quarantine_select = ["publication_period", "psgc_code", name_to, "split(quarantine_reasons, ',') AS quarantine_reasons",
                         *lineage, *stamp]
    clean, quarantine = silver_ref(spec.clean_candidate), silver_ref(spec.quarantine_candidate)
    lines = _header(spec, "Silver build", "sql", f"etl/03_silver/{spec.clean_file}") + [
        "--",
        "-- Rebuilds the two candidate tables from the current Bronze batches only (01-control.current_batches:",
        "-- the latest succeeded delivery version of each publication quarter). Bronze is read, never changed.",
        "-- Every current Bronze row ends in exactly one of the two tables:",
        f"--   {spec.clean_candidate}       one row per PSGC code per quarter, typed;",
        f"--   {spec.quarantine_candidate}  rows that cannot be trusted, with their reasons.",
        "-- The Silver tables are never written here: the gate (the next task) checks the candidates and",
        "-- publishes them only if no check fails (D-025). It rebuilds on every run.",
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
        "-- Every current row once, typed, with the reasons it would be quarantined. Labels and free text are",
        "-- read with whitespace normalized and blank as NULL (D-022, D-023); codes are read exactly as",
        "-- published. concat_ws never returns NULL, so quarantine_reasons = '' and <> '' split the rows.",
        f"CREATE OR REPLACE TEMPORARY VIEW {view} AS",
        "WITH bronze AS (",
        "  SELECT r.*",
        f"  FROM {_bronze_ref(spec)} AS r",
        f"  JOIN {CONTROL}.current_batches AS c ON r.batch_id = c.batch_id",
        f"  WHERE c.source_id = {lit(source)}",
        "),",
        "normalized AS (",
        "  SELECT",
        joined(normalized, 4),
        "  FROM bronze AS r",
        "),",
        "-- The codes of each delivery, once each: a code at the province position is a province, or one of",
        "-- the blank-level containers (City of Isabela, Special Geographic Area), when it is a Prov or",
        "-- blank-level row of the same delivery (O-10).",
        "positions AS (",
        f"  SELECT batch_id, {ident} AS psgc_code,",
        f"         MAX(CASE WHEN n_geographic_level = {province} OR n_geographic_level IS NULL THEN 1 ELSE 0 END) AS is_province_position",
        "  FROM normalized",
        f"  WHERE regexp_like({ident}, {pattern})",
        f"  GROUP BY batch_id, {ident}",
        ")",
        "SELECT",
        joined(final, 2),
        "FROM normalized AS n",
        "-- positions holds valid codes only; a row with a malformed code is quarantined, so its match never",
        "-- reaches the clean table. (A pattern test in this join made it a slow nested loop on DuckDB.)",
        "LEFT JOIN positions AS p",
        f"  ON p.batch_id = n.batch_id AND p.psgc_code = substr(n.{ident}, 1, 5) || '00000';",
        "",
        "-- One row per PSGC code per quarter, with the Bronze row it came from.",
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


# --- Gate ----------------------------------------------------------------------------------

def _value_checks(spec):
    """Silver column -> (expression over the clean row c, expression over its Bronze row b) that must agree."""
    ident = bq(spec.identifier)
    name_to, old_to, foot_to = (spec.text_columns[c] for c in ("name", "old_names", "column_j_footnote"))
    nb = {c: _norm("b." + bq(c)) for c in [*spec.categories, spec.income]}
    pop = "b." + bq(spec.population)
    return {
        "psgc_code": ("c.psgc_code", f"b.{ident}"),
        name_to: (f"c.{name_to}", _norm("b.name")),
        old_to: (f"c.{old_to}", _norm("b.old_names")),
        foot_to: (f"c.{foot_to}", _norm("b.column_j_footnote")),
        "correspondence_code": ("c.correspondence_code", f"NULLIF(b.{bq(spec.correspondence)}, '')"),
        "publication_period": ("c.publication_period", "b.publication_period"),
        "publication_date": ("c.publication_date", "CAST(b.publication_date AS DATE)"),
        "is_master_reference": ("c.is_master_reference", _master(spec, "b.publication_period")),
        **{c: (f"c.{c}", _category(spec, c, nb[c])) for c in spec.categories},
        "urban_rural_null_reason": ("c.urban_rural_null_reason", _category_reason(spec, "urban_rural", nb["urban_rural"])),
        "income_class": ("c.income_class", _income_class(spec, nb[spec.income])),
        "income_class_retained_after_downgrade": ("c.income_class_retained_after_downgrade",
                                                  _income_retained(spec, nb[spec.income])),
        "income_class_null_reason": ("c.income_class_null_reason", _income_reason(spec, nb[spec.income])),
        "population": ("c.population", _population(pop)),
        "population_null_reason": ("c.population_null_reason", _population_reason(spec, pop)),
    }


def gate_checks(spec):
    """[(check_name, scope, status)] in the order the gate writes them; scope: whole or batch."""
    whole = [("current_batches_present", "FAIL"), ("master_reference_current", "FAIL"), ("lineage_complete", "FAIL"),
             ("rows_resolve_to_current_bronze", "FAIL"), ("rows_built_by_this_run", "FAIL"),
             ("one_timestamp_per_run", "FAIL")]
    batch = [("rows_reconcile", "FAIL"), ("psgc_code_unique", "FAIL"), ("psgc_code_valid", "FAIL"),
             ("psgc_code_duplicates_absent", "FAIL")]
    batch += [(f"{c}_matches_bronze", "FAIL") for c in _value_checks(spec)]
    batch += [(f"labels_mapped_{c}", "FAIL") for c in [*spec.categories, spec.income]]
    batch += [("region_code_exists", "FAIL"), ("province_code_exists", "FAIL"),
              ("province_code_missing_only_where_listed", "FAIL"), ("city_municipality_code_exists", "FAIL"),
              ("flags_consistent", "FAIL"), ("quarantine_rate", "WARN/FAIL")]
    batch += [(f"quarantine_reason_{r}", "WARN") for r in QUARANTINE_REASONS]
    batch += [(f"flag_{f}", "record") for f in FLAGS]
    batch += [("rule_text_whitespace_normalized", "record"), ("rule_population_marker_to_null", "record"),
              ("rule_population_blank_to_null", "record"),
              ("rule_income_class_star_split", "record"), ("rule_placeholder_to_null", "record")]
    return [(n, "whole", s) for n, s in whole] + [(n, "batch", s) for n, s in batch]


def gate_sql(spec):
    source = spec.source_id
    lineage = [name for name, _ in LINEAGE]
    stamp = [name for name, _ in RUN_STAMP]
    clean_name, quarantine_name = dq_table_name(spec.clean_candidate), dq_table_name(spec.quarantine_candidate)
    ident = bq(spec.identifier)
    name_to = spec.text_columns["name"]
    values = _value_checks(spec)
    region, barangay = lit(spec.levels["region"]), lit(spec.levels["barangay"])
    star = [l.published for l in spec.income_labels if l.retained]
    placeholders = {c: [l.published for l in labels if l.null_reason] for c, labels in
                    [*spec.categories.items(), (spec.income, spec.income_labels)]}

    text_changed = " OR ".join(f"{whitespace('b.' + bq(c))} <> b.{bq(c)}" for c in spec.text_columns)
    placeholder_cells = " + ".join(
        f"CASE WHEN {_norm('b.' + bq(c))} IN ({', '.join(lit(p) for p in ps)}) THEN 1 ELSE 0 END"
        for c, ps in placeholders.items() if ps)
    bronze_agg = [
        "b.batch_id", "COUNT(*) AS bronze_rows",
        f"COUNT_IF({text_changed}) AS whitespace_rows",
        f"COUNT_IF(b.{bq(spec.population)} IN ({', '.join(lit(m) for m in spec.population_markers)})) AS marker_rows",
        f"COUNT_IF(b.{bq(spec.population)} = '') AS blank_population_rows",
        f"COUNT_IF({_norm('b.' + bq(spec.income))} IN ({', '.join(lit(s) for s in star)})) AS starred_rows",
        f"SUM({placeholder_cells}) AS placeholder_cells",
    ]
    clean_agg = [
        "c.batch_id", "COUNT(*) AS clean_rows", "COUNT(DISTINCT c.psgc_code) AS clean_codes",
        f"COUNT_IF(c.psgc_code IS NULL OR NOT regexp_like(c.psgc_code, {lit(spec.identifier_pattern)})) AS invalid_codes",
        *[f"COUNT_IF(b.source_row_number IS NULL OR NOT ({c_expr} IS NOT DISTINCT FROM {b_expr})) AS mismatched_{col}"
          for col, (c_expr, b_expr) in values.items()],
        *[f"COUNT_IF({_unmapped(labels, _norm('b.' + bq(col)))}) AS unmapped_{col}"
          for col, labels in [*spec.categories.items(), (spec.income, spec.income_labels)]],
        "COUNT_IF(reg.psgc_code IS NULL) AS missing_region",
        "COUNT_IF(c.province_code IS NOT NULL AND prov.psgc_code IS NULL) AS missing_province",
        # A city or municipality with no province must be an HUC or a listed exception, else a province row is missing.
        (f"COUNT_IF(c.geographic_level IN ({lit(spec.levels['city'])}, {lit(spec.levels['municipality'])})\n"
         f"        AND c.province_code IS NULL AND COALESCE(c.city_class, '') <> {lit(spec.no_province_city_class)}\n"
         f"        AND c.psgc_code NOT IN ({', '.join(lit(x) for x in spec.no_province_codes) or lit('')})"
         ") AS unexplained_no_province"),
        (f"COUNT_IF((c.geographic_level = {barangay} OR c.city_municipality_code IS NOT NULL)\n"
         "        AND cm.psgc_code IS NULL) AS missing_city_municipality"),
        (f"COUNT_IF(c.level_blank IS DISTINCT FROM ({_norm('b.geographic_level')} IS NULL)\n"
         "        OR c.population_is_zero IS DISTINCT FROM COALESCE(c.population = 0, FALSE)\n"
         f"        OR c.has_population_footnote IS DISTINCT FROM (c.{spec.text_columns['column_j_footnote']} IS NOT NULL)"
         ") AS inconsistent_flags"),
        *[f"COUNT_IF(c.{f}) AS flagged_{f}" for f in FLAGS],
    ]
    quarantine_agg = ["q.batch_id", "COUNT(*) AS quarantined_rows"] + [
        f"COUNT_IF(array_contains(q.quarantine_reasons, {lit(r)})) AS reason_{r}" for r in QUARANTINE_REASONS]
    batch_values = ["bronze_rows", "whitespace_rows", "marker_rows", "blank_population_rows", "starred_rows",
                    "placeholder_cells", "clean_rows",
                    "clean_codes", "invalid_codes", *[f"mismatched_{c}" for c in values],
                    *[f"unmapped_{c}" for c in [*spec.categories, spec.income]], "missing_region", "missing_province",
                    "unexplained_no_province", "missing_city_municipality", "inconsistent_flags", *[f"flagged_{f}" for f in FLAGS],
                    "quarantined_rows", *[f"reason_{r}" for r in QUARANTINE_REASONS]]
    batches = ["cur.batch_id"] + [f"COALESCE({v}, 0) AS {v}" for v in batch_values]

    def check(name, table, status, expected, actual, source_cte, scope):
        batch = "CAST(NULL AS STRING)" if scope == "whole" else "batch_id"
        return (f"SELECT {batch} AS batch_id, {lit(table)} AS table_name, {lit(name)} AS check_name,\n"
                f"         {status} AS status,\n"
                f"         {expected} AS expected, {actual} AS actual FROM {source_cte}")

    def must_equal(name, expected, actual, source_cte="batches", scope="batch", table=clean_name):
        return check(name, table, f"CASE WHEN {actual} = {expected} THEN 'PASS' ELSE 'FAIL' END",
                     f"CAST({expected} AS STRING)", f"CAST({actual} AS STRING)", source_cte, scope)

    def must_be_zero(name, actual, source_cte="batches", scope="batch", table=clean_name):
        return must_equal(name, "0", actual, source_cte, scope, table)

    def warn_if_any(name, actual, table=quarantine_name):
        return check(name, table, f"CASE WHEN {actual} = 0 THEN 'PASS' ELSE 'WARN' END", "'0'",
                     f"CAST({actual} AS STRING)", "batches", "batch")

    def record(name, actual):
        return check(name, clean_name, "'PASS'", "CAST(NULL AS STRING)", f"CAST({actual} AS STRING)", "batches", "batch")

    rate_status = ("CASE WHEN quarantined_rows = 0 THEN 'PASS' "
                   f"WHEN quarantined_rows * 100 > bronze_rows * {_number(spec.quarantine_fail_percent)} THEN 'FAIL' "
                   "ELSE 'WARN' END")
    master = lit(spec.master_period) if spec.master_period else "NULL"
    checks = [
        "-- The whole build",
        check("current_batches_present", clean_name, "CASE WHEN current_batches > 0 THEN 'PASS' ELSE 'FAIL' END",
              "'at least 1'", "CAST(current_batches AS STRING)", "found", "whole"),
        check("master_reference_current", clean_name, "CASE WHEN master_batches = 1 THEN 'PASS' ELSE 'FAIL' END",
              f"'1 current batch of ' || {master}", "CAST(master_batches AS STRING)", "found", "whole"),
        must_be_zero("lineage_complete", "missing_lineage", "whole", "whole"),
        must_be_zero("rows_resolve_to_current_bronze", "unresolved_rows", "unresolved", "whole"),
        must_be_zero("rows_built_by_this_run", "other_run_rows", "whole", "whole"),
        must_equal("one_timestamp_per_run", "1", "timestamps", "whole", "whole"),
        "-- Each current batch: reconciliation, keys, values against Bronze, labels, parents",
        must_equal("rows_reconcile", "bronze_rows", "clean_rows + quarantined_rows"),
        must_be_zero("psgc_code_unique", "clean_rows - clean_codes"),
        must_be_zero("psgc_code_valid", "invalid_codes"),
        must_be_zero("psgc_code_duplicates_absent", "reason_psgc_code_duplicated", table=quarantine_name),
        *[must_be_zero(f"{c}_matches_bronze", f"mismatched_{c}") for c in values],
        *[must_be_zero(f"labels_mapped_{c}", f"unmapped_{c}") for c in [*spec.categories, spec.income]],
        must_be_zero("region_code_exists", "missing_region"),
        must_be_zero("province_code_exists", "missing_province"),
        must_be_zero("province_code_missing_only_where_listed", "unexplained_no_province"),
        must_be_zero("city_municipality_code_exists", "missing_city_municipality"),
        must_be_zero("flags_consistent", "inconsistent_flags"),
        f"-- Each current batch: quarantine (WARN above 0, FAIL above {_number(spec.quarantine_fail_percent)}% of its rows)",
        check("quarantine_rate", quarantine_name, rate_status,
              # No ';' inside a string: store.split_statements splits files on it.
              f"'0 (FAIL above {_number(spec.quarantine_fail_percent)}% of ' || CAST(bronze_rows AS STRING) || ')'",
              "CAST(quarantined_rows AS STRING)", "batches", "batch"),
        *[warn_if_any(f"quarantine_reason_{r}", f"reason_{r}") for r in QUARANTINE_REASONS],
        "-- Each current batch: rows flagged and rows each rule changed (records, always PASS)",
        *[record(f"flag_{f}", f"flagged_{f}") for f in FLAGS],
        record("rule_text_whitespace_normalized", "whitespace_rows"),
        record("rule_population_marker_to_null", "marker_rows"),
        record("rule_population_blank_to_null", "blank_population_rows"),
        record("rule_income_class_star_split", "starred_rows"),
        record("rule_placeholder_to_null", "placeholder_cells"),
    ]
    union = []
    for item in checks:
        if item.startswith("--"):
            union.append("  " + item)
        else:
            union.append(("  UNION ALL " if any(not u.lstrip().startswith("--") for u in union) else "  ") + item)
    silver_rows = (f"  SELECT {', '.join(['publication_period', *lineage, *stamp])} FROM clean\n"
                   f"  UNION ALL SELECT {', '.join(['publication_period', *lineage, *stamp])} FROM quarantined")
    missing_lineage = " OR ".join(f"{name} IS NULL" for name in ["publication_period", *lineage, *stamp])
    lines = _header(spec, "Silver gate", "gate", f"etl/03_silver/90_validate_{spec.clean_table}.sql") + [
        "--",
        "-- The job task after the Silver build. It checks the candidate tables the build wrote, one row",
        "-- per check in data_quality_results: the whole build, then each current batch (one per quarter).",
        "-- On any FAIL it records the run 'failed' and stops the task before publishing, so the Silver",
        "-- tables keep the last build that passed and nothing downstream runs. Otherwise it copies the",
        "-- candidates to the Silver tables and records the run 'succeeded'. PASS: as expected. WARN:",
        "-- recorded, the build is published (quarantined rows). FAIL: the candidate cannot be trusted,",
        "-- including any repeated PSGC code (D-019). Results hold counts, never row values.",
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
        f"  SELECT batch_id, school_year AS publication_period FROM {CONTROL}.current_batches WHERE source_id = {lit(source)}",
        "),",
        "bronze AS (",
        f"  SELECT r.* FROM {_bronze_ref(spec)} AS r JOIN cur ON r.batch_id = cur.batch_id",
        "),",
        f"clean AS (SELECT * FROM {silver_ref(spec.clean_candidate)}),",
        f"quarantined AS (SELECT * FROM {silver_ref(spec.quarantine_candidate)}),",
        "-- The codes Silver publishes, per batch: a parent must be one of them.",
        f"regions AS (SELECT batch_id, psgc_code FROM clean WHERE geographic_level = {region}),",
        "codes AS (SELECT batch_id, psgc_code FROM clean),",
        "bronze_batches AS (",
        "  SELECT",
        joined(bronze_agg, 4),
        "  FROM bronze AS b",
        "  GROUP BY b.batch_id",
        "),",
        "-- Each clean row beside its Bronze row and its parents.",
        "clean_batches AS (",
        "  SELECT",
        joined(clean_agg, 4),
        "  FROM clean AS c",
        "  LEFT JOIN bronze AS b ON b.source_sha256 = c.source_sha256 AND b.source_row_number = c.source_row_number",
        "  LEFT JOIN regions AS reg ON reg.batch_id = c.batch_id AND reg.psgc_code = c.region_code",
        "  LEFT JOIN codes AS prov ON prov.batch_id = c.batch_id AND prov.psgc_code = c.province_code",
        "  LEFT JOIN codes AS cm ON cm.batch_id = c.batch_id AND cm.psgc_code = c.city_municipality_code",
        "  GROUP BY c.batch_id",
        "),",
        "quarantine_batches AS (",
        "  SELECT",
        joined(quarantine_agg, 4),
        "  FROM quarantined AS q",
        "  GROUP BY q.batch_id",
        "),",
        "batches AS (",
        "  SELECT",
        joined(batches, 4),
        "  FROM cur",
        "  LEFT JOIN bronze_batches AS bb ON bb.batch_id = cur.batch_id",
        "  LEFT JOIN clean_batches AS cb ON cb.batch_id = cur.batch_id",
        "  LEFT JOIN quarantine_batches AS qb ON qb.batch_id = cur.batch_id",
        "),",
        "found AS (",
        "  SELECT COUNT(*) AS current_batches,",
        f"         COUNT_IF(publication_period = {master}) AS master_batches",
        "  FROM cur",
        "),",
        "silver_rows AS (",
        silver_rows,
        "),",
        "whole AS (",
        "  SELECT",
        f"    COUNT_IF({missing_lineage}) AS missing_lineage,",
        "    COUNT_IF(run_id <> :run_id) AS other_run_rows,",
        "    COUNT(DISTINCT cleaned_at_utc) AS timestamps",
        "  FROM silver_rows",
        "),",
        "unresolved AS (",
        "  SELECT COUNT(*) AS unresolved_rows",
        "  FROM silver_rows AS s",
        "  LEFT JOIN bronze AS b ON b.source_sha256 = s.source_sha256 AND b.source_row_number = s.source_row_number",
        "    AND b.batch_id = s.batch_id",
        "  WHERE b.source_row_number IS NULL",
        ")",
        *union,
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

def dictionary_markdown(spec):
    m = spec.mapping
    name_to, old_to, foot_to = (spec.text_columns[c] for c in ("name", "old_names", "column_j_footnote"))
    labels = lambda column: ", ".join(f"`{l.published}`" for l in spec.categories[column])  # noqa: E731
    income = ", ".join(f"`{l.published}`" for l in spec.income_labels)
    rows = [
        ("publication_period", "STRING", "provenance `publication_period`", "The quarter of the delivery, e.g. `2026-Q2`", "Never", "D-019"),
        ("publication_date", "DATE", "provenance `publication_date`", "The `Metadata` publication date", "Never", "D-019"),
        ("is_master_reference", "BOOLEAN", "contract `master_reference_period`",
         f"TRUE for the quarter the team uses as the master reference ({spec.master_period}); every current quarter is kept", "Never", "D-012"),
        ("psgc_code", "STRING", "`psgc_code`", "Ten digits, leading zeros kept, exactly as published. Unique per quarter", "Never", "O-1"),
        (name_to, "STRING", "`name`", m["free_text_columns"]["name"]["rule"], "Never in 2Q 2026", "O-9"),
        ("correspondence_code", "STRING", "`correspondence_code`", m["codes"]["correspondence_code"]["rule"],
         "No code published (50 rows in 2Q 2026)", "O-3, D-030"),
        ("geographic_level", "STRING", "`geographic_level`", f"Accepted labels: {labels('geographic_level')}",
         "Blank in the workbook (`level_blank`)", "O-2"),
        ("region_code", "STRING", "`psgc_code`", "First 2 digits + 8 zeros: the region the code belongs to. A region row points to itself. The gate asserts it is a published region row", "Code not valid (never in Silver)", "O-10"),
        ("province_code", "STRING", "`psgc_code`", "First 5 digits + 5 zeros, when that code is a province row or a blank-level container of the same quarter. "
         "Province and container rows point to themselves, so a province's own row is in its own group", "No province above the unit: "
         f"regions, sub-municipalities, HUCs and the listed exceptions ({', '.join(spec.no_province_codes)}); the gate FAILs any other", "O-10"),
        ("city_municipality_code", "STRING", "`psgc_code`", "Barangays only: first 7 digits + 3 zeros, the city, municipality or sub-municipality holding it. Manila's barangays point "
         "to its 14 sub-municipalities, which roll up to the City of Manila by their first 5 digits + `00000`", "Not a barangay", "O-10"),
        (old_to, "STRING", "`old_names`", m["free_text_columns"]["old_names"]["rule"], "No former name published", "O-11"),
        ("city_class", "STRING", "`city_class`", f"Accepted labels: {labels('city_class')}", "Not a city", "Bronze counts"),
        ("income_class", "STRING", "`income_classification`", f"The class without the star. Accepted labels: {income}",
         "Not classified at that level, or `-` (`income_class_null_reason`)", "O-7"),
        ("income_class_retained_after_downgrade", "BOOLEAN", "`income_classification`",
         "TRUE when the published class has a star (UNVERIFIED meaning, open decision)", "No class", "O-7"),
        ("income_class_null_reason", "STRING", "`income_classification`", "`not_classified` for the published `-`", "A class is published, or none at that level", "O-7"),
        ("urban_rural", "STRING", "`urban_rural`", f"Accepted labels: {labels('urban_rural')}. `-` is never folded into rural",
         "Not a barangay, or `-` (`urban_rural_null_reason`)", "O-8"),
        ("urban_rural_null_reason", "STRING", "`urban_rural`", "`unknown` for the published `-`", "U or R published, or not a barangay", "O-8"),
        ("population", "INT", "`population`", m["population"]["rule"], "`#N/A` (`population_null_reason`) or blank", "O-4, D-033"),
        ("population_null_reason", "STRING", "`population`", "`publisher_na` for the published `#N/A`; `blank` for a blank cell", "A number is published", "O-4"),
        (foot_to, "STRING", "`column_j_footnote`", m["renames"]["column_j_footnote"]["rule"], "No footnote", "O-6"),
        ("status", "STRING", "`status`", f"Accepted labels: {labels('status')}", "No status", "O-12, S-5"),
        ("level_blank", "BOOLEAN", "`geographic_level`", "TRUE when the level was blank in the workbook", "Never", "O-2"),
        ("population_is_zero", "BOOLEAN", "`population`", "TRUE for a published 0 (kept as 0)", "Never", "O-4"),
        ("has_population_footnote", "BOOLEAN", "`column_j_footnote`", "TRUE when a footnote is published: the population then excludes the named cities", "Never", "O-6"),
    ]
    lineage = [
        ("batch_id", "STRING", "The Bronze batch: the quarter and the delivery's checksum"),
        ("delivery_version", "INT", "Which delivery of the quarter (a re-issue is 2)"),
        ("schema_version", "STRING", "Which header the workbook had: the DOF order and census behind the values"),
        ("source_sha256", "STRING", "The workbook's SHA-256"),
        ("source_row_number", "BIGINT", "The Excel row of sheet `PSGC`: open the workbook (or Bronze) at this row"),
        ("run_id", "STRING", "The job run that built the row; Gold trusts it only if that `silver_build` run succeeded (D-025)"),
        ("cleaned_at_utc", "TIMESTAMP", "When the build ran"),
        ("code_revision", "STRING", "The commit that built the row"),
    ]
    lines = [
        f"# Silver data dictionary: `{spec.clean_table}`",
        "",
        "Generated by `src/silver/psa_psgc.py` from `config/ingestion/psa_psgc.json` and "
        "`config/mappings/psa_psgc.json`:",
        "",
        "```bash",
        f"python -m src.silver.cli dictionary --source {spec.source_id} > docs/data/silver/psa-psgc-clean.md",
        "```",
        "",
        "Do not edit by hand; `tests/test_silver_psgc.py` fails if it differs.",
        "",
        f"One row per PSGC code per publication quarter, for the current delivery version of every quarter "
        f"(`01-control.current_batches`). Every current Bronze row is in exactly one of `{spec.clean_table}` and "
        f"`{spec.quarantine_table}`, with its Bronze lineage (`source_sha256`, `source_row_number`), so each value "
        "can be read back from Bronze as published. **NULL** never means zero.",
        "",
        "| Column | Type | From Bronze | Rule | NULL means | Finding |",
        "|---|---|---|---|---|---|",
        *[f"| `{c}` | {t} | {s} | {r} | {n} | {f} |" for c, t, s, r, n, f in rows],
        "",
        "## Lineage and run stamp",
        "",
        "| Column | Type | Meaning |",
        "|---|---|---|",
        *[f"| `{c}` | {t} | {d} |" for c, t, d in lineage],
        "",
        f"## `{spec.quarantine_table}`",
        "",
        f"`publication_period`, `psgc_code` (as published), `{name_to}`, `quarantine_reasons` (ARRAY of reasons), "
        "the lineage and the run stamp. A row is never deleted.",
        "",
        "| Reason | When |",
        "|---|---|",
        "| `psgc_code_blank` | The code is blank |",
        f"| `psgc_code_malformed` | The code does not match `{spec.identifier_pattern}` as published |",
        "| `psgc_code_duplicated` | The code appears twice in the quarter: every copy is quarantined, and the gate FAILs (D-019) |",
        f"| `correspondence_code_malformed` | A filled correspondence code does not match `{spec.correspondence_pattern}` |",
        f"| `population_uncastable` | The population is not 1 to 9 digits and not a known marker ({', '.join(f'`{k}`' for k in spec.population_markers)}) |",
        "",
        f"Quarantine above 0 rows of a quarter is WARN, above {_number(spec.quarantine_fail_percent)}% is FAIL (D-024).",
        "",
    ]
    return "\n".join(lines)
