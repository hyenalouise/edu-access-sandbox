"""Silver for psa_school_age_population: the spec, the build SQL, the gate SQL, and the data dictionary.

Two reviewed files define it, and nothing else:

- `config/ingestion/psa_school_age_population.json`, the Bronze contract: the sheets
  (population concepts), the two layouts and their count columns, and the approved
  workbooks;
- `config/mappings/psa_school_age_population.json`, the Silver rules: grain, sexes,
  label parsing, how levels come from the sums, the level counts each approved
  workbook must give, and the count pattern.

The census workbooks have neither codes nor a level column (profile O-2), so this
source has its own generator (D-053). Silver turns every Bronze count cell into one
row per (census year, population concept, place, sex, age): the 2020 wide rows hold
60 counts, the 2024 `Total` / `Male` / `Female` rows 20 each, under the place row
above them. Each place's level and parent come from the sums: a place is an
aggregate when the places right after it add up to it in all 60 cells, each nested
aggregate counted once. The build finds the aggregates in passes, one per level of
the tree, from the bottom: a pass looks for places whose following places sum to
them, with the places inside an aggregate found by an earlier pass counted once (by
that aggregate). The gate then checks the tree independently: every aggregate
equals the sum of its children in every cell, and the counts per level are the ones
pinned for that workbook.

The SQL follows the same conventions as src/silver/sql.py: the build writes the
candidate tables, the gate checks them and publishes only if no check FAILs (D-025),
both run as SQL tasks, and only syntax both Databricks and DuckDB accept is used
(src/ingestion/store.py translates the rest).
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from src.ingestion.bronze import OWNER_GROUP
from src.ingestion.contract import load_source_config
from src.ingestion.errors import IngestionError
from src.silver.sql import CONTROL, bq, candidate_comment, dq_table_name, joined, lit, silver_ref, whitespace

SOURCE_ID = "psa_school_age_population"
SAFE_LITERAL = re.compile(r"^[^'\\;]*$")
SNAKE = re.compile(r"^[a-z][a-z0-9_]*$")
WIDE_COLUMN = re.compile(r"^(?P<prefix>[a-z_]+)_age_(?P<age>[0-9]+)$")
LONG_COLUMN = re.compile(r"^age_(?P<age>[0-9]+)$")

# Why a cell is set aside, in the order they are listed on a quarantined row. Any of them FAILs the gate.
QUARANTINE_REASONS = ("population_blank", "population_negative", "population_not_whole_number")

# Bronze provenance carried on every clean and quarantined row, then the Silver run's own stamp.
LINEAGE = (
    ("logical_dataset", "string"),
    ("batch_id", "string"),
    ("delivery_version", "int"),
    ("schema_version", "string"),
    ("source_sha256", "string"),
    ("source_sheet", "string"),
    ("source_row_number", "bigint"),
    ("place_row_number", "bigint"),
)
# place_status values besides 'standard' (D-053, #176 review): places at a province or city position that
# are not a PSGC province or LGU.
SPECIAL_STATUSES = ("special_geographic_area", "sga_cluster")
RUN_STAMP = (("run_id", "string"), ("cleaned_at_utc", "timestamp"), ("code_revision", "string"))
PLACE_COLUMNS = (
    ("place_label", "string"), ("place_name", "string"), ("footnote", "string"), ("old_name", "string"),
    ("is_capital", "boolean"), ("level", "string"), ("place_status", "string"), ("region_name", "string"),
    ("province_name", "string"),
    ("parent_name", "string"),
)


def _error(message):
    return IngestionError("config", "invalid_silver_mapping", message)


@dataclass
class SchoolAgeSpec:
    source_id: str
    bronze_table: str
    clean_file: str
    clean_table: str
    quarantine_table: str
    clean_candidate: str
    quarantine_candidate: str
    concepts: dict              # population_concept -> sheet suffix, in contract order
    ages: list
    sexes: list                 # Silver sex values, in band order
    wide: dict                  # schema version -> {(sex, age): Bronze column}
    long: dict                  # schema version -> {age: Bronze column}
    sex_row_kinds: dict         # long-layout row kind -> sex
    place_kind: str
    structural_kinds: list
    footnote_pattern: str
    bracket_pattern: str
    capital: str
    aggregate_levels: list      # level of an aggregate at depth 0, 1, 2, ...
    leaf_level: str
    leaf_depths: list
    expected_levels: list       # [{census_year, workbook_sha256, <level>: count, <status>: count}]
    sga_level: str              # place_status: the level and names of the Special Geographic Area,
    sga_names: list             # and the level and name pattern of its 2020 clusters
    cluster_level: str
    cluster_pattern: str
    count_pattern: str
    negative_pattern: str
    mapping: dict = field(repr=False)

    @property
    def cells_per_place(self):
        return len(self.sexes) * len(self.ages)

    @property
    def levels(self):
        return [*self.aggregate_levels, self.leaf_level]

    @property
    def passes(self):
        """One pass per level that has children: aggregates are found from the bottom up."""
        return len(self.aggregate_levels)

    @property
    def statuses(self):
        """place_status values other than standard, each with a count pinned per workbook."""
        return list(SPECIAL_STATUSES)

    @property
    def data_kinds(self):
        """Bronze row kinds that hold counts: a wide place row, or a long Total / Male / Female row."""
        return [self.place_kind, *self.sex_row_kinds]

    def clean_columns(self):
        """[(name, type)] of the clean table, in order."""
        return ([("census_year", "int"), ("population_concept", "string"), *PLACE_COLUMNS,
                 ("sex", "string"), ("age", "int"), ("population", "int")] + list(LINEAGE) + list(RUN_STAMP))

    def quarantine_columns(self):
        return ([("census_year", "int"), ("population_concept", "string"), ("place_label", "string"),
                 ("sex", "string"), ("age", "int"), ("quarantine_reasons", "array<string>")]
                + list(LINEAGE) + list(RUN_STAMP))


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

    sexes = mapping["sexes"]
    prefix_to_sex = {entry["wide_prefix"]: sex for sex, entry in sexes.items()}
    kind_to_sex = {entry["long_row_kind"]: sex for sex, entry in sexes.items()}
    if len(prefix_to_sex) != len(sexes) or len(kind_to_sex) != len(sexes):
        raise _error("two sexes share a wide prefix or a long row kind.")

    # Every count column of every schema version maps to exactly one (sex, age); nothing is left over.
    ages, wide, long = None, {}, {}
    for version, entry in contract["schema_versions"].items():
        counts = entry["columns"][1:]
        if entry["columns"][0] != "label":
            raise _error(f"schema {version}: the first column must be the place label.")
        version_ages = list(entry["ages"])
        if ages is None:
            ages = version_ages
        elif version_ages != ages:
            raise _error(f"schema {version} has ages {version_ages}, another version {ages}; Silver needs one age range.")
        if entry["layout"] == "wide":
            cells = {}
            for column in counts:
                found = WIDE_COLUMN.match(column)
                if not found or found.group("prefix") not in prefix_to_sex:
                    raise _error(f"schema {version}: column {column!r} has no sex in the mapping's wide prefixes.")
                cells[(prefix_to_sex[found.group("prefix")], int(found.group("age")))] = column
            if set(cells) != {(s, a) for s in sexes for a in ages} or len(cells) != len(counts):
                raise _error(f"schema {version}: the wide columns must hold every sex and age exactly once.")
            wide[version] = cells
        elif entry["layout"] == "long":
            cells = {}
            for column in counts:
                found = LONG_COLUMN.match(column)
                if not found:
                    raise _error(f"schema {version}: column {column!r} is not an age column.")
                cells[int(found.group("age"))] = column
            if sorted(cells) != sorted(ages) or len(cells) != len(counts):
                raise _error(f"schema {version}: the long columns must hold every age exactly once.")
            if set(entry["sex_labels"].values()) != set(kind_to_sex):
                raise _error(f"schema {version}: the sex rows {sorted(entry['sex_labels'].values())} differ from "
                             f"the mapping's long row kinds {sorted(kind_to_sex)}.")
            long[version] = cells
        else:
            raise _error(f"schema {version}: layout {entry['layout']!r} has no Silver rule.")

    levels = mapping["levels"]
    aggregate_levels, leaf = levels["by_depth"], levels["leaf"]
    if not aggregate_levels or len(set(aggregate_levels + [leaf])) != len(aggregate_levels) + 1:
        raise _error("levels must name each level once, with at least one aggregate level.")
    if not levels["leaf_depths"] or not all(isinstance(d, int) and 1 <= d <= len(aggregate_levels)
                                            for d in levels["leaf_depths"]):
        raise _error("levels.leaf_depths must be depths below the country, at most one below the deepest aggregate.")
    for name in [*aggregate_levels, leaf, *sexes, *contract["sheet_suffixes"]]:
        if not SNAKE.match(name):
            raise _error(f"value {name!r} is not snake_case.")

    approved = {d["workbook_sha256"]: d["census_year"] for d in contract["deliveries"]}
    pins = mapping["expected_levels"]
    for pin in pins:
        if approved.get(pin["workbook_sha256"]) != pin["census_year"]:
            raise _error(f"expected_levels pins {pin['census_year']} workbook {pin['workbook_sha256'][:12]}, "
                         "which is not an approved delivery of that census year in the Bronze contract.")
        counts = [pin.get(level) for level in [*aggregate_levels, leaf, *SPECIAL_STATUSES]]
        if not all(isinstance(n, int) and n >= 0 for n in counts):
            raise _error(f"expected_levels for {pin['workbook_sha256'][:12]} needs a count for every level "
                         f"and every place_status ({', '.join(SPECIAL_STATUSES)}).")
    if len({p["workbook_sha256"] for p in pins}) != len(pins):
        raise _error("expected_levels pins a workbook twice.")

    status = mapping["place_status"]
    sga, cluster = status["special_geographic_area"], status["sga_cluster"]
    for entry in (sga, cluster):
        if entry["level"] not in [*aggregate_levels, leaf]:
            raise _error(f"place_status level {entry['level']!r} is not a level.")
    if not sga["names"] or any(name != name.upper() for name in sga["names"]):
        raise _error("place_status.special_geographic_area.names must be upper-case place names.")

    label = mapping["label"]
    literals = [*sga["names"], cluster["pattern"], label["footnote_pattern"], label["bracket_pattern"], label["capital"], mapping["count"]["pattern"],
                mapping["count"]["negative_pattern"], mapping["place_row_kind"], *mapping["structural_row_kinds"],
                *kind_to_sex, *contract["sheet_suffixes"].values(), *approved]
    unsafe = [v for v in literals if not SAFE_LITERAL.match(v)]
    if unsafe:
        raise _error(f"patterns and labels may not contain quotes, backslashes or ';': {unsafe}.")
    if not re.fullmatch(r"[A-Z]+", label["capital"]):
        raise _error("label.capital must be upper-case letters.")

    return SchoolAgeSpec(
        source_id=source_id, bronze_table=contract["bronze_table"], clean_file=silver["clean_file"],
        clean_table=mapping["silver_table"], quarantine_table=mapping["quarantine_table"],
        clean_candidate=silver["candidate_table"], quarantine_candidate=silver["candidate_quarantine_table"],
        concepts=dict(contract["sheet_suffixes"]), ages=ages, sexes=list(sexes), wide=wide, long=long,
        sex_row_kinds=kind_to_sex, place_kind=mapping["place_row_kind"],
        structural_kinds=mapping["structural_row_kinds"], footnote_pattern=label["footnote_pattern"],
        bracket_pattern=label["bracket_pattern"], capital=label["capital"], aggregate_levels=aggregate_levels,
        leaf_level=leaf, leaf_depths=levels["leaf_depths"], expected_levels=pins,
        sga_level=sga["level"], sga_names=sga["names"], cluster_level=cluster["level"],
        cluster_pattern=cluster["pattern"],
        count_pattern=mapping["count"]["pattern"], negative_pattern=mapping["count"]["negative_pattern"],
        mapping=mapping,
    )


# --- Shared SQL pieces -------------------------------------------------------------------

def _bronze_ref(spec):
    return f"edu_access.`02-bronze`.{spec.bronze_table}"


def _header(spec, what, command, path):
    return [
        f"-- {what} for {spec.source_id}. Generated from config/ingestion/{spec.source_id}.json",
        f"-- and config/mappings/{spec.source_id}.json by src/silver/psa_school_age_population.py:",
        f"--   python -m src.silver.cli {command} --source {spec.source_id} > {path}",
        "-- Do not edit by hand; tests/test_silver_school_age.py fails if it differs.",
    ]


def _in(values):
    return "(" + ", ".join(lit(v) for v in values) + ")"


def _row_sex(spec, row):
    """The sex of a long-layout Total / Male / Female row."""
    return (f"CASE {row}.source_row_kind "
            + " ".join(f"WHEN {lit(kind)} THEN {lit(sex)}" for kind, sex in spec.sex_row_kinds.items()) + " END")


def _is_data_row(spec, row):
    """A Bronze row that holds counts: a place row of a wide schema, a sex row of a long one."""
    parts = []
    if spec.wide:
        parts.append(f"({row}.schema_version IN {_in(spec.wide)} AND {row}.source_row_kind = {lit(spec.place_kind)})")
    if spec.long:
        parts.append(f"({row}.schema_version IN {_in(spec.long)} AND {row}.source_row_kind IN {_in(spec.sex_row_kinds)})")
    return "(" + " OR ".join(parts) + ")"


def _cell(spec, row, sex, age, indent):
    """A count cell's published text, from its Bronze row, for a (sex, age): by column in the wide layout,
    by the row's own sex in the long one (NULL for another sex)."""
    pad = " " * indent
    lines = [f"CASE {row}.schema_version"]
    for version, cells in spec.wide.items():
        lines.append(f"{pad}  WHEN {lit(version)} THEN CASE {sex}")
        for s in spec.sexes:
            arms = " ".join(f"WHEN {a} THEN {row}.{bq(cells[(s, a)])}" for a in spec.ages)
            lines.append(f"{pad}    WHEN {lit(s)} THEN CASE {age} {arms} END")
        lines.append(f"{pad}  END")
    for version, cells in spec.long.items():
        arms = " ".join(f"WHEN {a} THEN {row}.{bq(cells[a])}" for a in spec.ages)
        lines.append(f"{pad}  WHEN {lit(version)} THEN CASE WHEN {sex} = {_row_sex(spec, row)} THEN CASE {age} {arms} END END")
    lines.append(f"{pad}END")
    return "\n".join(lines)


def _typed(spec, ref):
    return f"CASE WHEN regexp_like({ref}, {lit(spec.count_pattern)}) THEN TRY_CAST({ref} AS INT) END"


def _capital_pattern(spec):
    """'(Capital)' in any case, spaces allowed inside the brackets; character classes, as SQL literals may
    not hold a backslash or a case flag both engines read alike."""
    letters = "".join(f"[{c}{c.lower()}]" for c in spec.capital)
    return f"[(][ ]*{letters}[ ]*[)]"


def _label_parts(spec, label):
    """name -> expression over a whitespace-normalized place label."""
    no_footnote = f"regexp_replace({label}, {lit(spec.footnote_pattern)}, '')"
    others = f"regexp_replace({no_footnote}, {lit(' *' + _capital_pattern(spec))}, '')"
    return {
        "footnote": f"NULLIF(regexp_extract({label}, {lit(spec.footnote_pattern)}, 1), '')",
        "old_name": f"NULLIF(array_join(regexp_extract_all({others}, {lit(spec.bracket_pattern)}, 1), ', '), '')",
        "is_capital": f"COALESCE(regexp_like({label}, {lit(_capital_pattern(spec))}), FALSE)",
        "place_name": f"NULLIF(upper(TRIM(regexp_replace(regexp_replace({no_footnote}, ' *[(][^()]*[)]', ''), ' +', ' '))), '')",
    }


def _concept(spec, sheet, year):
    return ("CASE " + " ".join(f"WHEN {sheet} = {year} || {lit(' ' + suffix)} THEN {lit(concept)}"
                               for concept, suffix in spec.concepts.items()) + " END")


def _level(spec, ref):
    aggregates = " ".join(f"WHEN {ref}.is_aggregate AND {ref}.depth = {d} THEN {lit(level)}"
                          for d, level in enumerate(spec.aggregate_levels))
    depths = ", ".join(str(d) for d in spec.leaf_depths)
    return f"CASE {aggregates} WHEN NOT {ref}.is_aggregate AND {ref}.depth IN ({depths}) THEN {lit(spec.leaf_level)} END"


def _place_status(spec, level, name, parent):
    """standard, or one of SPECIAL_STATUSES, from a place's level, name and parent's name."""
    names = _in(spec.sga_names)
    return (f"CASE WHEN {level} = {lit(spec.sga_level)} AND {name} IN {names} THEN 'special_geographic_area' "
            f"WHEN {level} = {lit(spec.cluster_level)} AND {parent} IN {names} "
            f"AND regexp_like({name}, {lit(spec.cluster_pattern)}) THEN 'sga_cluster' ELSE 'standard' END")


def _same_sheet(a, b):
    return f"{a}.batch_id = {b}.batch_id AND {a}.source_sheet = {b}.source_sheet"


def _tree_passes(spec, cells, places, spans):
    """Statements that find every aggregate into the work table `spans`: pass k finds the aggregates whose
    children were all found by earlier passes (or are leaves). Places inside an aggregate already found
    count as 0, so its own value counts once. A candidate's span ends at the last place where the running
    sums, in all of its cells, have grown by exactly its own value since it. Each pass reads the work
    tables, never a view of an earlier pass: Spark would compute an earlier pass again for every place
    it is used (#158, a 40-minute build on Databricks)."""
    window = ("OVER (PARTITION BY c.batch_id, c.source_sheet, c.sex, c.age ORDER BY c.place_pos\n"
              "         ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)")
    statements = []
    for k in range(1, spec.passes + 1):
        if k == 1:
            head = [f"-- Pass 1: every place counts.", f"CREATE OR REPLACE TABLE {spans} USING DELTA AS", "WITH"]
            ctes = ["\n".join([
                f"c{k} AS (",
                f"  SELECT c.batch_id, c.source_sheet, c.sex, c.age, c.place_pos, c.population, FALSE AS covered,",
                f"         SUM(c.population) {window} AS running",
                f"  FROM {cells} AS c",
                "),",
            ])]
            done_join, done_where = "", ""
        else:
            head = [f"-- Pass {k}: places inside an aggregate already found count once, as that aggregate.",
                    f"INSERT INTO {spans} (batch_id, source_sheet, start_pos, end_pos, found_in_pass)", "WITH"]
            ctes = ["\n".join([
                f"in{k} AS (",
                "  SELECT DISTINCT p.batch_id, p.source_sheet, p.place_pos",
                f"  FROM {places} AS p JOIN {spans} AS s ON {_same_sheet('s', 'p')}",
                "   AND p.place_pos > s.start_pos AND p.place_pos <= s.end_pos",
                "),",
                f"c{k} AS (",
                f"  SELECT c.batch_id, c.source_sheet, c.sex, c.age, c.place_pos, c.population, n.place_pos IS NOT NULL AS covered,",
                f"         SUM(CASE WHEN n.place_pos IS NULL THEN c.population ELSE 0 END) {window} AS running",
                f"  FROM {cells} AS c",
                f"  LEFT JOIN in{k} AS n ON {_same_sheet('n', 'c')} AND n.place_pos = c.place_pos",
                "),",
            ])]
            done_join = f"\n  LEFT JOIN {spans} AS done ON {_same_sheet('done', 'i')} AND done.start_pos = i.place_pos"
            done_where = "\n  WHERE NOT i.covered AND done.start_pos IS NULL"
        ctes.append("\n".join([
            f"m{k} AS (",
            "  SELECT i.batch_id, i.source_sheet, i.place_pos AS start_pos, j.place_pos AS end_pos",
            f"  FROM c{k} AS i",
            f"  JOIN c{k} AS j ON {_same_sheet('j', 'i')} AND j.sex = i.sex AND j.age = i.age",
            "   AND j.place_pos > i.place_pos AND j.running = i.running + i.population" + done_join + done_where,
            "  GROUP BY i.batch_id, i.source_sheet, i.place_pos, j.place_pos",
            f"  HAVING COUNT(*) = {spec.cells_per_place}",
            ")",
            f"SELECT batch_id, source_sheet, start_pos, MAX(end_pos) AS end_pos, {k} AS found_in_pass",
            f"FROM m{k} GROUP BY batch_id, source_sheet, start_pos;",
            "",
        ]))
        if k == 1:
            ctes.append(f"ALTER TABLE {spans} OWNER TO `{OWNER_GROUP}`;\n")
        statements += head + ctes
    return statements


def _extended_spans(spec, spans):
    """CTEs over the found spans: an aggregate with a single child equals it, so its running sums are
    matched at the child's own row; its span then reaches to the end of the child's span (repeated for a
    chain of single children)."""
    ctes = ["-- An aggregate with a single child ends where that child's span ends.",
            f"e0 AS (SELECT * FROM {spans}),"]
    for k in range(1, spec.passes + 1):
        ctes.append("\n".join([
            f"e{k} AS (",
            "  SELECT s.batch_id, s.source_sheet, s.start_pos,",
            "         CASE WHEN t.end_pos > s.end_pos THEN t.end_pos ELSE s.end_pos END AS end_pos, s.found_in_pass",
            f"  FROM e{k - 1} AS s",
            f"  LEFT JOIN e{k - 1} AS t ON {_same_sheet('t', 's')} AND t.start_pos = s.end_pos",
            "),",
        ]))
    return ctes, f"e{spec.passes}"


# --- Build ---------------------------------------------------------------------------------

def build_sql(spec):
    source = spec.source_id
    # Work tables: each step of the tree reads the one before as a table, so Spark computes it once (#158).
    # They are rebuilt by every run and dropped once the candidates are written.
    work = {name: silver_ref(f"{source}_work_{name}") for name in ("cells", "places", "spans", "tree")}
    cells_table, tree_table, classified = work["cells"], work["tree"], f"{source}_classified"
    lineage = [name for name, _ in LINEAGE]
    stamp = [name for name, _ in RUN_STAMP]
    grid = ", ".join(f"({lit(s)}, {a})" for s in spec.sexes for a in spec.ages)
    published = "c.population_published"
    reasons = (
        "concat_ws(',',\n"
        f"      CASE WHEN {published} IS NULL OR {published} = '' THEN 'population_blank' END,\n"
        f"      CASE WHEN regexp_like({published}, {lit(spec.negative_pattern)}) THEN 'population_negative' END,\n"
        f"      CASE WHEN {published} <> '' AND NOT regexp_like({published}, {lit(spec.count_pattern)})\n"
        f"                AND NOT regexp_like({published}, {lit(spec.negative_pattern)}) THEN 'population_not_whole_number' END\n"
        "    ) AS quarantine_reasons")
    passes = _tree_passes(spec, cells_table, work["places"], work["spans"])
    extended, spans = _extended_spans(spec, work["spans"])
    parts = _label_parts(spec, "p.label_text")
    clean_columns = [name for name, _ in spec.clean_columns()]
    quarantine_select = ["census_year", "population_concept", "place_label", "sex", "age",
                         "split(quarantine_reasons, ',') AS quarantine_reasons", *lineage, *stamp]
    clean, quarantine = silver_ref(spec.clean_candidate), silver_ref(spec.quarantine_candidate)
    levels = ", ".join(spec.aggregate_levels)

    lines = _header(spec, "Silver build", "sql", f"etl/03_silver/{spec.clean_file}") + [
        "--",
        "-- Rebuilds the two candidate tables from the current Bronze batches only (01-control.current_batches:",
        "-- the latest succeeded delivery version of each census year). Bronze is read, never changed.",
        "-- Every count cell of a current batch becomes one candidate (census year, population concept, place,",
        f"-- sex, age), and ends in exactly one of the two tables:",
        f"--   {spec.clean_candidate}       one row per cell, typed, with the place's level and parents;",
        f"--   {spec.quarantine_candidate}  cells whose count is blank or not a whole number, with their reasons.",
        "-- Wide rows (2020) give 60 cells each; long rows (2024) give 20, under the place row above them. Title,",
        "-- header, note, source and blank rows stay in Bronze. Levels and parents come from the sums (D-053):",
        f"-- {spec.passes} passes over the places, one per level that has children ({levels}), from the bottom.",
        "-- The Silver tables are never written here: the gate (the next task) checks the candidates, the tree",
        "-- included, and publishes them only if no check fails (D-025). It rebuilds on every run.",
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
        "-- Every count cell of the current batches once, with its place, the published text, and the count",
        "-- typed. A reason is decided with explicit NULL handling, and concat_ws never returns NULL, so",
        "-- quarantine_reasons = '' and <> '' split the cells without losing any.",
        f"CREATE OR REPLACE TABLE {cells_table} USING DELTA AS",
        "WITH bronze AS (",
        "  SELECT r.*",
        f"  FROM {_bronze_ref(spec)} AS r",
        f"  JOIN {CONTROL}.current_batches AS c ON r.batch_id = c.batch_id",
        f"  WHERE c.source_id = {lit(source)}",
        "),",
        "-- Each place row and the rows that follow it until the next place row share place_pos, in Excel row",
        "-- order within the batch and sheet: a 2024 Total / Male / Female row belongs to the place above it.",
        "ordered AS (",
        "  SELECT r.*,",
        f"         SUM(CASE WHEN r.source_row_kind = {lit(spec.place_kind)} THEN 1 ELSE 0 END) OVER (",
        "           PARTITION BY r.batch_id, r.source_sheet ORDER BY r.source_row_number",
        "           ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS place_pos",
        "  FROM bronze AS r",
        f"  WHERE r.source_row_kind IN {_in(spec.data_kinds)}",
        "),",
        "places AS (",
        "  SELECT batch_id, source_sheet, place_pos, source_row_number AS place_row_number, label AS place_label",
        f"  FROM ordered WHERE source_row_kind = {lit(spec.place_kind)}",
        "),",
        f"grid AS (SELECT * FROM (VALUES {grid}) AS g(sex, age)),",
        "-- Unpivot: one candidate per cell, still as the published text.",
        "cells AS (",
        "  SELECT",
        "    r.census_year, r.source_sheet, r.place_pos, g.sex, g.age,",
        "    " + _cell(spec, "r", "g.sex", "g.age", 4) + " AS population_published,",
        joined([f"r.{name}" for name in lineage if name != "place_row_number"], 4),
        "  FROM ordered AS r",
        f"  JOIN grid AS g ON r.schema_version IN {_in(spec.wide)} OR g.sex = {_row_sex(spec, 'r')}" if spec.wide
        else f"  JOIN grid AS g ON g.sex = {_row_sex(spec, 'r')}",
        f"  WHERE {_is_data_row(spec, 'r')}",
        ")",
        "SELECT",
        joined([
            "CAST(c.census_year AS INT) AS census_year",
            f"{_concept(spec, 'c.source_sheet', 'c.census_year')} AS population_concept",
            "c.place_pos", "p.place_label", "c.sex", "c.age", "c.population_published",
            f"{_typed(spec, published)} AS population",
            reasons,
            *[f"c.{name}" for name in lineage if name != "place_row_number"],
            "p.place_row_number",
        ], 2),
        "FROM cells AS c",
        "LEFT JOIN places AS p ON p.batch_id = c.batch_id AND p.source_sheet = c.source_sheet AND p.place_pos = c.place_pos;",
        "",
        f"ALTER TABLE {cells_table} OWNER TO `{OWNER_GROUP}`;",
        "",
        "-- Each place once, in workbook order within its batch and sheet.",
        f"CREATE OR REPLACE TABLE {work['places']} USING DELTA AS",
        f"SELECT DISTINCT batch_id, source_sheet, place_pos, place_label FROM {cells_table};",
        "",
        f"ALTER TABLE {work['places']} OWNER TO `{OWNER_GROUP}`;",
        "",
        "-- The aggregates, from the sums: one pass per level that has children, from the bottom.",
        *passes,
        "-- Each place's level, parents and parsed label. The levels come from the sums (D-053): an aggregate's",
        "-- level is its depth, a place with no children is a city or municipality at a depth the rules allow.",
        "-- A place the sums do not explain gets no level, and the gate fails.",
        f"CREATE OR REPLACE TABLE {tree_table} USING DELTA AS",
        "WITH places AS (",
        f"  SELECT * FROM {work['places']}",
        "),",
        *extended,
        f"spans AS (SELECT * FROM {spans}),",
        "-- The aggregates around each place; the innermost (the last to start) is its parent.",
        "enclosing AS (",
        "  SELECT p.batch_id, p.source_sheet, p.place_pos, s.start_pos",
        f"  FROM places AS p JOIN spans AS s ON {_same_sheet('s', 'p')}",
        "   AND p.place_pos > s.start_pos AND p.place_pos <= s.end_pos",
        "),",
        "shaped AS (",
        "  SELECT p.batch_id, p.source_sheet, p.place_pos,",
        f"         NULLIF({whitespace('p.place_label')}, '') AS label_text,",
        "         COUNT(e.start_pos) AS depth, MAX(e.start_pos) AS parent_pos",
        "  FROM places AS p",
        f"  LEFT JOIN enclosing AS e ON {_same_sheet('e', 'p')} AND e.place_pos = p.place_pos",
        "  GROUP BY p.batch_id, p.source_sheet, p.place_pos, p.place_label",
        "),",
        "parsed AS (",
        "  SELECT",
        joined(["p.batch_id", "p.source_sheet", "p.place_pos", "p.depth", "p.parent_pos",
                "a.start_pos IS NOT NULL AS is_aggregate",
                *[f"{expr} AS {name}" for name, expr in parts.items()]], 4),
        "  FROM shaped AS p",
        f"  LEFT JOIN spans AS a ON {_same_sheet('a', 'p')} AND a.start_pos = p.place_pos",
        "),",
        "leveled AS (",
        f"  SELECT p.*, {_level(spec, 'p')} AS level",
        "  FROM parsed AS p",
        "),",
        "-- Region and province: the place itself or the aggregate around it at that level.",
        "named AS (",
        "  SELECT l.batch_id, l.source_sheet, l.place_pos,",
        f"         MAX(CASE WHEN a.level = {lit(spec.aggregate_levels[1])} THEN a.place_name END) AS region_name,"
        if len(spec.aggregate_levels) > 1 else "         CAST(NULL AS STRING) AS region_name,",
        f"         MAX(CASE WHEN a.level = {lit(spec.aggregate_levels[2])} THEN a.place_name END) AS province_name"
        if len(spec.aggregate_levels) > 2 else "         CAST(NULL AS STRING) AS province_name",
        "  FROM leveled AS l",
        "  JOIN (SELECT batch_id, source_sheet, place_pos, start_pos AS around_pos FROM enclosing",
        "        UNION ALL SELECT batch_id, source_sheet, place_pos, place_pos FROM places) AS x",
        f"    ON {_same_sheet('x', 'l')} AND x.place_pos = l.place_pos",
        f"  JOIN leveled AS a ON {_same_sheet('a', 'x')} AND a.place_pos = x.around_pos",
        "  GROUP BY l.batch_id, l.source_sheet, l.place_pos",
        ")",
        "SELECT",
        joined(["l.batch_id", "l.source_sheet", "l.place_pos", "l.place_name", "l.footnote", "l.old_name",
                "l.is_capital", "l.level",
                _place_status(spec, "l.level", "l.place_name", "par.place_name") + " AS place_status",
                "l.depth", "n.region_name", "n.province_name", "par.place_name AS parent_name"], 2),
        "FROM leveled AS l",
        f"LEFT JOIN leveled AS par ON {_same_sheet('par', 'l')} AND par.place_pos = l.parent_pos",
        f"LEFT JOIN named AS n ON {_same_sheet('n', 'l')} AND n.place_pos = l.place_pos;",
        "",
        f"ALTER TABLE {tree_table} OWNER TO `{OWNER_GROUP}`;",
        "",
        "-- Every cell with its place.",
        f"CREATE OR REPLACE TEMPORARY VIEW {classified} AS",
        "SELECT",
        joined(["c.census_year", "c.population_concept",
                f"NULLIF({whitespace('c.place_label')}, '') AS place_label",
                "t.place_name", "t.footnote", "t.old_name", "t.is_capital", "t.level", "t.place_status", "t.region_name",
                "t.province_name", "t.parent_name", "c.sex", "c.age", "c.population", "c.quarantine_reasons",
                *[f"c.{name}" for name in lineage],
                *[f"session.silver_{name} AS {name}" for name in stamp]], 2),
        f"FROM {cells_table} AS c",
        f"LEFT JOIN {tree_table} AS t ON {_same_sheet('t', 'c')} AND t.place_pos = c.place_pos;",
        "",
        "-- One row per cell, with the Bronze row it came from.",
        f"CREATE OR REPLACE TABLE {clean} USING DELTA AS",
        "SELECT",
        joined(clean_columns, 2),
        f"FROM {classified}",
        "WHERE quarantine_reasons = '';",
        "",
        candidate_comment(clean, spec.clean_table),
        f"ALTER TABLE {clean} OWNER TO `{OWNER_GROUP}`;",
        "",
        "-- Cells set aside, never deleted: the Bronze row, and why.",
        f"CREATE OR REPLACE TABLE {quarantine} USING DELTA AS",
        "SELECT",
        joined(quarantine_select, 2),
        f"FROM {classified}",
        "WHERE quarantine_reasons <> '';",
        "",
        candidate_comment(quarantine, spec.quarantine_table),
        f"ALTER TABLE {quarantine} OWNER TO `{OWNER_GROUP}`;",
        "",
        "-- The work tables are not needed after the build.",
        *[f"DROP TABLE IF EXISTS {ref};" for ref in work.values()],
        "",
    ]
    return "\n".join(lines)


# --- Gate ----------------------------------------------------------------------------------

def gate_checks(spec):
    """[(check_name, scope, status)] in the order the gate writes them; scope: whole, batch, or sheet.
    Sheet checks are written once per batch and population concept, named <check>_<concept>."""
    whole = [("current_batches_present", "FAIL"), ("one_current_batch_per_census_year", "FAIL"),
             ("lineage_complete", "FAIL"), ("rows_resolve_to_current_bronze_cells", "FAIL"),
             ("rows_built_by_this_run", "FAIL"), ("one_timestamp_per_run", "FAIL")]
    batch = [("bronze_rows_accounted", "FAIL"), ("sheets_are_concepts", "FAIL"),
             ("household_not_above_total", "FAIL"), ("concepts_pair_up", "FAIL"),
             ("places_with_equal_concepts", "record"), ("rule_structural_rows_not_counts", "record")]
    batch += [(f"rows_kind_{k}", "record") for k in [*spec.data_kinds, *spec.structural_kinds]]
    sheet = [("rows_reconcile", "FAIL"), ("population_matches_bronze", "FAIL"), ("population_not_null", "FAIL"),
             ("place_label_parsed", "FAIL"), ("key_unique", "FAIL"), ("place_levels_assigned", "FAIL"),
             ("one_country", "FAIL"), ("parents_resolve", "FAIL"), ("tree_closes", "FAIL"),
             ("no_all_zero_place", "FAIL"), ("levels_match_expected", "FAIL"),
             ("place_status_match_expected", "FAIL"), ("sexes_add_up", "FAIL"), ("quarantined_cells", "FAIL")]
    sheet += [(f"quarantine_reason_{r}", "record") for r in QUARANTINE_REASONS]
    sheet += [("zero_population_cells", "WARN"), ("national_both_sexes_by_age", "record"),
              ("rule_footnote_split", "record"), ("rule_old_name_split", "record"), ("rule_capital_flagged", "record")]
    return ([(n, "whole", s) for n, s in whole] + [(n, "batch", s) for n, s in batch]
            + [(n, "sheet", s) for n, s in sheet])


def _check(scope, table, name, status, expected, actual, source, concept=None):
    batch = "CAST(NULL AS STRING)" if scope == "whole" else "batch_id"
    check = lit(name) if concept is None else f"{lit(name + '_')} || population_concept"
    return (f"  UNION ALL SELECT {batch} AS batch_id, {lit(table)} AS table_name, {check} AS check_name,\n"
            f"         {status} AS status,\n"
            f"         {expected} AS expected, {actual} AS actual FROM {source}")


def _levels_text(levels, ref):
    """'country 1, region 17, ...': NULL when any count is NULL (a workbook with no pinned counts)."""
    return " || ', ' || ".join(f"{lit(level + ' ')} || CAST({ref(level)} AS STRING)" for level in levels)


def _pass(condition):
    return f"CASE WHEN {condition} THEN 'PASS' ELSE 'FAIL' END"


def _count(ref):
    return f"CAST({ref} AS STRING)"


def gate_sql(spec):
    source = spec.source_id
    lineage = [name for name, _ in LINEAGE]
    stamp = [name for name, _ in RUN_STAMP]
    table = dq_table_name(spec.clean_candidate)
    concepts = ", ".join(f"({lit(c)}, {lit(s)})" for c, s in spec.concepts.items())
    levels = spec.levels
    statuses = spec.statuses
    pins = ", ".join("(" + ", ".join([lit(p["workbook_sha256"]), *[str(p[k]) for k in [*levels, *statuses]]]) + ")"
                     for p in spec.expected_levels) or "(" + ", ".join(["CAST(NULL AS STRING)"] + ["0"] * (len(levels) + len(statuses))) + ")"
    pin_columns = ", ".join(["workbook_sha256", *levels, *statuses])
    recomputed_status = _place_status(spec, "c.level", "c.place_name", "c.parent_name")
    parts = _label_parts(spec, "c.place_label")
    reparsed = " OR ".join(f"NOT (c.{name} IS NOT DISTINCT FROM {expr})" for name, expr in parts.items())
    parent_level = ["CASE"]
    for d, level in enumerate(spec.aggregate_levels[1:], 1):
        parent_level.append(f"WHEN c.level = {lit(level)} THEN {lit(spec.aggregate_levels[d - 1])}")
    if len(spec.aggregate_levels) > 2:
        parent_level.append(f"WHEN c.level = {lit(spec.leaf_level)} AND c.province_name IS NOT NULL "
                            f"THEN {lit(spec.aggregate_levels[2])}")
    if len(spec.aggregate_levels) > 1:
        parent_level.append(f"WHEN c.level = {lit(spec.leaf_level)} THEN {lit(spec.aggregate_levels[1])}")
    parent_level.append("END")
    country = spec.aggregate_levels[0]
    region = spec.aggregate_levels[1] if len(spec.aggregate_levels) > 1 else None
    data_cells = ("CASE "
                  + (f"WHEN b.schema_version IN {_in(spec.wide)} AND b.source_row_kind = {lit(spec.place_kind)} "
                     f"THEN {spec.cells_per_place} " if spec.wide else "")
                  + (f"WHEN b.schema_version IN {_in(spec.long)} AND b.source_row_kind IN {_in(spec.sex_row_kinds)} "
                     f"THEN {len(spec.ages)} " if spec.long else "")
                  + "ELSE 0 END")
    known_kinds = [*spec.data_kinds, *spec.structural_kinds]
    ages_list = ", ".join(str(a) for a in spec.ages)
    national = " || ',' || ".join(
        f"COALESCE(CAST(SUM(CASE WHEN age = {a} THEN population END) AS STRING), '-')" for a in spec.ages)
    pair_key = ["batch_id", "place_name", "level", "sex", "age"]
    pair_on = " AND ".join(f"t.{k} = h.{k}" for k in pair_key) + " AND t.parent_name IS NOT DISTINCT FROM h.parent_name"
    total, household = list(spec.concepts)[:2] if len(spec.concepts) >= 2 else (None, None)

    union = []

    def add(scope, name, status, expected, actual, source_cte, per_concept=False):
        union.append(_check(scope, table, name, status, expected, actual, source_cte,
                            concept=True if per_concept else None))

    add("whole", "current_batches_present", _pass("current_batches > 0"), "'at least 1'", _count("current_batches"), "found")
    add("whole", "one_current_batch_per_census_year", _pass("repeated_years = 0"), "'0'", _count("repeated_years"), "found")
    add("whole", "lineage_complete", _pass("missing_lineage = 0"), "'0'", _count("missing_lineage"), "whole")
    add("whole", "rows_resolve_to_current_bronze_cells", _pass("unresolved_rows = 0"), "'0'", _count("unresolved_rows"), "unresolved")
    add("whole", "rows_built_by_this_run", _pass("other_run_rows = 0"), "'0'", _count("other_run_rows"), "whole")
    add("whole", "one_timestamp_per_run", _pass("timestamps = 1"), "'1'", _count("timestamps"), "whole")
    add("batch", "bronze_rows_accounted", _pass("other_rows = 0"), _count("bronze_rows"), _count("bronze_rows - other_rows"), "batches")
    add("batch", "sheets_are_concepts", _pass("unknown_sheet_rows = 0 AND concept_sheets = " + str(len(spec.concepts))),
        f"'{len(spec.concepts)} sheets, 0 rows elsewhere'",
        "CAST(concept_sheets AS STRING) || ' sheets, ' || CAST(unknown_sheet_rows AS STRING) || ' rows elsewhere'", "batches")
    add("batch", "household_not_above_total", _pass("household_above_total = 0"), "'0'", _count("household_above_total"), "pairs")
    add("batch", "concepts_pair_up", _pass("unpaired_cells = 0"), "'0'", _count("unpaired_cells"), "pairs")
    add("batch", "places_with_equal_concepts", "'PASS'", "CAST(NULL AS STRING)", _count("equal_places"), "pairs")
    add("batch", "rule_structural_rows_not_counts", "'PASS'", "CAST(NULL AS STRING)", _count("structural_rows"), "batches")
    for kind in known_kinds:
        add("batch", f"rows_kind_{kind}", "'PASS'", "CAST(NULL AS STRING)", _count(f"kind_{kind}"), "batches")
    add("sheet", "rows_reconcile", _pass("clean_cells + quarantined_cells = count_cells"), _count("count_cells"),
        _count("clean_cells + quarantined_cells"), "sheets", True)
    add("sheet", "population_matches_bronze", _pass("mismatched = 0"), "'0'", _count("mismatched"), "sheets", True)
    add("sheet", "population_not_null", _pass("null_population = 0"), "'0'", _count("null_population"), "sheets", True)
    add("sheet", "place_label_parsed", _pass("misparsed = 0"), "'0'", _count("misparsed"), "sheets", True)
    add("sheet", "key_unique", _pass("repeated_keys = 0"), "'0'", _count("repeated_keys"), "sheets", True)
    add("sheet", "place_levels_assigned", _pass("unleveled_places = 0"), "'0'", _count("unleveled_places"), "sheets", True)
    add("sheet", "one_country", _pass(f"places_{country} = 1"), "'1'", _count(f"places_{country}"), "sheets", True)
    add("sheet", "parents_resolve", _pass("unresolved_parents = 0"), "'0'", _count("unresolved_parents"), "sheets", True)
    add("sheet", "tree_closes", _pass("unclosed = 0"), "'0'", _count("unclosed"), "sheets", True)
    # A place of zeros adds nothing to any sum, so the sums cannot place it: it could sit in the span before it.
    add("sheet", "no_all_zero_place", _pass("all_zero_places = 0"), "'0'", _count("all_zero_places"), "sheets", True)
    add("sheet", "levels_match_expected", _pass("expected_levels IS NOT NULL AND expected_levels = actual_levels"),
        f"COALESCE(expected_levels, 'not pinned: add this workbook to expected_levels in config/mappings/{source}.json')",
        "actual_levels", "sheets", True)
    add("sheet", "place_status_match_expected",
        _pass("expected_statuses IS NOT NULL AND expected_statuses = actual_statuses AND misflagged_places = 0"),
        f"COALESCE(expected_statuses, 'not pinned: add this workbook to expected_levels in config/mappings/{source}.json')",
        "actual_statuses || CASE WHEN misflagged_places > 0 THEN ', misflagged ' || CAST(misflagged_places AS STRING) "
        "ELSE '' END", "sheets", True)
    add("sheet", "sexes_add_up", _pass("sex_problems = 0"), "'0'", _count("sex_problems"), "sheets", True)
    add("sheet", "quarantined_cells", _pass("quarantined_cells = 0"), "'0'", _count("quarantined_cells"), "sheets", True)
    for r in QUARANTINE_REASONS:
        add("sheet", f"quarantine_reason_{r}", "'PASS'", "CAST(NULL AS STRING)", _count(f"reason_{r}"), "sheets", True)
    add("sheet", "zero_population_cells", "CASE WHEN zero_cells = 0 THEN 'PASS' ELSE 'WARN' END", "'0'",
        _count("zero_cells"), "sheets", True)
    add("sheet", "national_both_sexes_by_age", "'PASS'", f"'ages {spec.ages[0]}-{spec.ages[-1]}, comma-separated'",
        "national_by_age", "sheets", True)
    add("sheet", "rule_footnote_split", "'PASS'", "CAST(NULL AS STRING)", _count("footnote_places"), "sheets", True)
    add("sheet", "rule_old_name_split", "'PASS'", "CAST(NULL AS STRING)", _count("old_name_places"), "sheets", True)
    add("sheet", "rule_capital_flagged", "'PASS'", "CAST(NULL AS STRING)", _count("capital_places"), "sheets", True)
    union[0] = union[0].replace("  UNION ALL SELECT", "  SELECT", 1)

    level_counts = [f"COUNT(DISTINCT CASE WHEN c.level = {lit(level)} THEN c.place_row_number END) AS places_{level}"
                    for level in levels]
    level_counts += [f"COUNT(DISTINCT CASE WHEN c.place_status = {lit(st)} THEN c.place_row_number END) AS status_{st}"
                     for st in statuses]
    level_counts.append(f"COUNT(DISTINCT CASE WHEN c.place_status IS DISTINCT FROM {recomputed_status} "
                        "THEN c.place_row_number END) AS misflagged_places")
    lines = _header(spec, "Silver gate", "gate", f"etl/03_silver/90_validate_{spec.clean_table}.sql") + [
        "--",
        "-- The job task after the Silver build. It checks the candidate tables the build wrote, one row",
        "-- per check in data_quality_results: the whole build, each current batch (one census year), and each",
        "-- batch and population concept (check names end in the concept). On any FAIL it records the run",
        "-- 'failed' and stops the task before publishing, so the Silver tables keep the last build that passed",
        "-- and nothing downstream runs. Otherwise it copies the candidates to the Silver tables and records",
        "-- the run 'succeeded'. PASS: as expected. WARN: recorded, the build is published (zero counts).",
        "-- FAIL: the candidate cannot be trusted. Results hold counts, never row values; the national totals",
        "-- by age are recorded so a rerun shows any change.",
        "--",
        "-- The tree is checked here independently of how the build found it: every place except the country",
        "-- resolves to exactly one parent by name (the region qualifying a province), every aggregate equals",
        "-- the sum of its children in every cell, no place is 0 in every cell (the sums cannot place it), and",
        "-- the places per level and per place_status are the counts pinned for the workbook in the Silver",
        "-- rules (D-053).",
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
        f"concepts AS (SELECT * FROM (VALUES {concepts}) AS v(population_concept, sheet_suffix)),",
        f"pins AS (SELECT * FROM (VALUES {pins}) AS v({pin_columns})),",
        "-- Every current batch and population concept: the grid every sheet check is written for.",
        "grid AS (SELECT cur.batch_id, k.population_concept FROM cur CROSS JOIN concepts AS k),",
        "-- Each current batch: its census year and workbook, and its Bronze rows by kind and sheet.",
        "batches AS (",
        "  SELECT cur.batch_id,",
        "         MAX(b.census_year) AS census_year,",
        "         MAX(b.source_sha256) AS source_sha256,",
        "         COUNT(b.source_row_number) AS bronze_rows,",
        f"         COUNT_IF(b.source_row_kind IS NULL OR b.source_row_kind NOT IN {_in(known_kinds)}) AS other_rows,",
        f"         COUNT_IF(b.source_row_kind IN {_in(spec.structural_kinds)}) AS structural_rows,",
        *[f"         COUNT_IF(b.source_row_kind = {lit(k)}) AS kind_{k}," for k in known_kinds],
        "         COUNT_IF(b.source_row_number IS NOT NULL AND k.population_concept IS NULL) AS unknown_sheet_rows,",
        "         COUNT(DISTINCT k.population_concept) AS concept_sheets",
        "  FROM cur",
        "  LEFT JOIN bronze AS b ON b.batch_id = cur.batch_id",
        "  LEFT JOIN concepts AS k ON b.source_sheet = b.census_year || ' ' || k.sheet_suffix",
        "  GROUP BY cur.batch_id",
        "),",
        "found AS (",
        "  SELECT COUNT(*) AS current_batches, COUNT(*) - COUNT(DISTINCT census_year) AS repeated_years FROM batches",
        "),",
        "-- Each Bronze sheet: how many count cells its rows hold.",
        "bronze_sheets AS (",
        f"  SELECT b.batch_id, k.population_concept, SUM({data_cells}) AS count_cells",
        "  FROM bronze AS b JOIN concepts AS k ON b.source_sheet = b.census_year || ' ' || k.sheet_suffix",
        "  GROUP BY b.batch_id, k.population_concept",
        "),",
        "-- Each clean cell beside its Bronze row and the place row above it: the value is the published",
        "-- cell, and the label is parsed as the rules say.",
        "clean_sheets AS (",
        "  SELECT",
        "    c.batch_id,",
        "    c.population_concept,",
        "    COUNT(*) AS clean_cells,",
        "    COUNT_IF(c.population IS NULL) AS null_population,",
        "    COUNT_IF(c.population = 0) AS zero_cells,",
        "    COUNT_IF(b.source_row_number IS NULL OR NOT (c.population IS NOT DISTINCT FROM "
        + _typed(spec, "(" + _cell(spec, "b", "c.sex", "c.age", 6) + ")") + ")) AS mismatched,",
        f"    COUNT_IF(pb.source_row_number IS NULL OR c.place_label IS DISTINCT FROM NULLIF({whitespace('pb.label')}, '')",
        f"        OR {reparsed}",
        "        OR c.place_name IS NULL OR regexp_like(c.place_name, '[()/]')) AS misparsed,",
        "    COUNT(DISTINCT CASE WHEN c.level IS NULL THEN c.place_row_number END) AS unleveled_places,",
        joined(level_counts, 4) + ",",
        "    COUNT(DISTINCT CASE WHEN c.footnote IS NOT NULL THEN c.place_row_number END) AS footnote_places,",
        "    COUNT(DISTINCT CASE WHEN c.old_name IS NOT NULL THEN c.place_row_number END) AS old_name_places,",
        "    COUNT(DISTINCT CASE WHEN c.is_capital THEN c.place_row_number END) AS capital_places",
        "  FROM clean AS c",
        "  LEFT JOIN bronze AS b ON b.source_sha256 = c.source_sha256 AND b.source_sheet = c.source_sheet",
        f"   AND b.source_row_number = c.source_row_number AND {_is_data_row(spec, 'b')}",
        "  LEFT JOIN bronze AS pb ON pb.source_sha256 = c.source_sha256 AND pb.source_sheet = c.source_sheet",
        f"   AND pb.source_row_number = c.place_row_number AND pb.source_row_kind = {lit(spec.place_kind)}",
        "  GROUP BY c.batch_id, c.population_concept",
        "),",
        "-- Places whose every cell is 0: the sums cannot say where such a place belongs.",
        "zero_places AS (",
        "  SELECT batch_id, population_concept, COUNT(*) AS all_zero_places FROM (",
        "    SELECT batch_id, population_concept, place_row_number",
        "    FROM clean GROUP BY batch_id, population_concept, place_row_number",
        "    HAVING COUNT_IF(population <> 0) = 0",
        "  ) AS z GROUP BY batch_id, population_concept",
        "),",
        "-- The key: one row per census year, concept, place name, parent, sex and age.",
        "repeated AS (",
        "  SELECT batch_id, population_concept, SUM(n - 1) AS repeated_keys FROM (",
        "    SELECT batch_id, population_concept, place_name, parent_name, sex, age, COUNT(*) AS n",
        "    FROM clean GROUP BY batch_id, population_concept, place_name, parent_name, sex, age",
        "  ) AS k WHERE n > 1 GROUP BY batch_id, population_concept",
        "),",
        "-- The tree, checked from the published names: each place's parent is the aggregate of the level above",
        "-- it with its parent_name (in the same region below the country).",
        "links AS (",
        "  SELECT c.batch_id, c.population_concept, c.place_row_number, c.sex, c.age, c.population, c.parent_name,",
        "         c.region_name, " + " ".join(parent_level) + " AS parent_level",
        f"  FROM clean AS c WHERE c.level IS NOT NULL AND c.level <> {lit(country)}",
        "),",
        "aggregates AS (",
        f"  SELECT * FROM clean WHERE level IN {_in(spec.aggregate_levels)}",
        "),",
        "resolved AS (",
        "  SELECT l.batch_id, l.population_concept, l.place_row_number, l.sex, l.age, l.population,",
        "         COUNT(p.place_row_number) AS parents, MAX(p.place_row_number) AS parent_row",
        "  FROM links AS l",
        "  LEFT JOIN aggregates AS p ON p.batch_id = l.batch_id AND p.population_concept = l.population_concept",
        "   AND p.sex = l.sex AND p.age = l.age AND p.place_name = l.parent_name AND p.level = l.parent_level",
        f"   AND (l.parent_level = {lit(country)} OR p.region_name = l.region_name)",
        "  GROUP BY l.batch_id, l.population_concept, l.place_row_number, l.sex, l.age, l.population",
        "),",
        "child_sums AS (",
        "  SELECT batch_id, population_concept, parent_row, sex, age, SUM(CAST(population AS BIGINT)) AS children",
        "  FROM resolved WHERE parents = 1",
        "  GROUP BY batch_id, population_concept, parent_row, sex, age",
        "),",
        "tree AS (",
        "  SELECT g.batch_id, g.population_concept,",
        "         COALESCE(u.unresolved_parents, 0) AS unresolved_parents, COALESCE(a.unclosed, 0) AS unclosed",
        "  FROM grid AS g",
        "  LEFT JOIN (SELECT batch_id, population_concept, COUNT_IF(parents <> 1) AS unresolved_parents",
        "             FROM resolved GROUP BY batch_id, population_concept) AS u",
        "    ON u.batch_id = g.batch_id AND u.population_concept = g.population_concept",
        "  LEFT JOIN (SELECT p.batch_id, p.population_concept,",
        "                    COUNT_IF(s.children IS NULL OR p.population IS NULL OR s.children <> p.population) AS unclosed",
        "             FROM aggregates AS p",
        "             LEFT JOIN child_sums AS s ON s.batch_id = p.batch_id AND s.population_concept = p.population_concept",
        "              AND s.parent_row = p.place_row_number AND s.sex = p.sex AND s.age = p.age",
        "             GROUP BY p.batch_id, p.population_concept) AS a",
        "    ON a.batch_id = g.batch_id AND a.population_concept = g.population_concept",
        "),",
        "-- Both sexes = male + female for every place and age (profile O-4).",
        "sex_sums AS (",
        "  SELECT batch_id, population_concept, COUNT_IF(both_sexes IS NULL OR male IS NULL OR female IS NULL",
        "                                                 OR both_sexes <> male + female OR n <> 3) AS sex_problems",
        "  FROM (",
        "    SELECT batch_id, population_concept, place_row_number, age, COUNT(*) AS n,",
        f"           SUM(CASE WHEN sex = {lit(spec.sexes[0])} THEN CAST(population AS BIGINT) END) AS both_sexes,",
        f"           SUM(CASE WHEN sex = {lit(spec.sexes[1])} THEN CAST(population AS BIGINT) END) AS male,",
        f"           SUM(CASE WHEN sex = {lit(spec.sexes[2])} THEN CAST(population AS BIGINT) END) AS female",
        "    FROM clean GROUP BY batch_id, population_concept, place_row_number, age",
        "  ) AS s",
        "  GROUP BY batch_id, population_concept",
        "),",
        "-- The national totals by age, both sexes, recorded so a rerun shows any change.",
        "national AS (",
        f"  SELECT batch_id, population_concept, {national} AS national_by_age",
        f"  FROM clean WHERE level = {lit(country)} AND sex = {lit(spec.sexes[0])} AND age IN ({ages_list})",
        "  GROUP BY batch_id, population_concept",
        "),",
        "quarantine_sheets AS (",
        "  SELECT q.batch_id, q.population_concept, COUNT(*) AS quarantined_cells,",
        joined([f"COUNT_IF(array_contains(q.quarantine_reasons, {lit(r)})) AS reason_{r}" for r in QUARANTINE_REASONS], 9),
        "  FROM quarantined AS q GROUP BY q.batch_id, q.population_concept",
        "),",
        "sheets AS (",
        "  SELECT",
        joined(["g.batch_id", "g.population_concept",
                "COALESCE(bs.count_cells, 0) AS count_cells",
                "COALESCE(cs.clean_cells, 0) AS clean_cells",
                "COALESCE(cs.null_population, 0) AS null_population",
                "COALESCE(cs.zero_cells, 0) AS zero_cells",
                "COALESCE(cs.mismatched, 0) AS mismatched",
                "COALESCE(cs.misparsed, 0) AS misparsed",
                "COALESCE(cs.unleveled_places, 0) AS unleveled_places",
                *[f"COALESCE(cs.places_{level}, 0) AS places_{level}" for level in levels],
                "COALESCE(cs.footnote_places, 0) AS footnote_places",
                "COALESCE(cs.old_name_places, 0) AS old_name_places",
                "COALESCE(cs.capital_places, 0) AS capital_places",
                "COALESCE(r.repeated_keys, 0) AS repeated_keys",
                "t.unresolved_parents", "t.unclosed",
                "COALESCE(z.all_zero_places, 0) AS all_zero_places",
                "COALESCE(cs.misflagged_places, 0) AS misflagged_places",
                "COALESCE(x.sex_problems, 0) AS sex_problems",
                "COALESCE(n.national_by_age, '') AS national_by_age",
                "COALESCE(q.quarantined_cells, 0) AS quarantined_cells",
                *[f"COALESCE(q.reason_{r}, 0) AS reason_{r}" for r in QUARANTINE_REASONS],
                _levels_text(levels, lambda level: f"p.{level}") + " AS expected_levels",
                _levels_text(levels, lambda level: f"COALESCE(cs.places_{level}, 0)") + " AS actual_levels",
                _levels_text(statuses, lambda st: f"p.{st}") + " AS expected_statuses",
                _levels_text(statuses, lambda st: f"COALESCE(cs.status_{st}, 0)") + " AS actual_statuses"], 4),
        "  FROM grid AS g",
        "  JOIN batches AS bt ON bt.batch_id = g.batch_id",
        "  LEFT JOIN pins AS p ON p.workbook_sha256 = bt.source_sha256",
        "  LEFT JOIN bronze_sheets AS bs ON bs.batch_id = g.batch_id AND bs.population_concept = g.population_concept",
        "  LEFT JOIN clean_sheets AS cs ON cs.batch_id = g.batch_id AND cs.population_concept = g.population_concept",
        "  LEFT JOIN repeated AS r ON r.batch_id = g.batch_id AND r.population_concept = g.population_concept",
        "  LEFT JOIN zero_places AS z ON z.batch_id = g.batch_id AND z.population_concept = g.population_concept",
        "  LEFT JOIN tree AS t ON t.batch_id = g.batch_id AND t.population_concept = g.population_concept",
        "  LEFT JOIN sex_sums AS x ON x.batch_id = g.batch_id AND x.population_concept = g.population_concept",
        "  LEFT JOIN national AS n ON n.batch_id = g.batch_id AND n.population_concept = g.population_concept",
        "  LEFT JOIN quarantine_sheets AS q ON q.batch_id = g.batch_id AND q.population_concept = g.population_concept",
        "),",
        "-- The two concepts of a census year, cell by cell: the same places, household never above total (O-5).",
        "concept_cells AS (",
        "  SELECT COALESCE(t.batch_id, h.batch_id) AS batch_id, t.place_name AS total_place, h.place_name AS household_place,",
        "         t.parent_name, t.level, t.population AS total, h.population AS household",
        f"  FROM (SELECT * FROM clean WHERE population_concept = {lit(total)}) AS t",
        f"  FULL OUTER JOIN (SELECT * FROM clean WHERE population_concept = {lit(household)}) AS h ON {pair_on}",
        "),",
        "equal_places AS (",
        "  SELECT batch_id, COUNT(*) AS equal_places FROM (",
        "    SELECT batch_id, total_place, parent_name, level",
        "    FROM concept_cells WHERE total_place IS NOT NULL AND household_place IS NOT NULL",
        "    GROUP BY batch_id, total_place, parent_name, level",
        "    HAVING COUNT_IF(total IS DISTINCT FROM household) = 0",
        "  ) AS e GROUP BY batch_id",
        "),",
        "pairs AS (",
        "  SELECT cur.batch_id,",
        "         COALESCE(SUM(CASE WHEN c.total_place IS NULL OR c.household_place IS NULL THEN 1 ELSE 0 END), 0) AS unpaired_cells,",
        "         COALESCE(SUM(CASE WHEN c.household > c.total THEN 1 ELSE 0 END), 0) AS household_above_total,",
        "         COALESCE(MAX(e.equal_places), 0) AS equal_places",
        "  FROM cur",
        "  LEFT JOIN concept_cells AS c ON c.batch_id = cur.batch_id",
        "  LEFT JOIN equal_places AS e ON e.batch_id = cur.batch_id",
        "  GROUP BY cur.batch_id",
        "),",
        "silver_rows AS (",
        f"  SELECT {', '.join(['census_year', 'population_concept', 'sex', 'age', *lineage, *stamp])} FROM clean",
        f"  UNION ALL SELECT {', '.join(['census_year', 'population_concept', 'sex', 'age', *lineage, *stamp])} FROM quarantined",
        "),",
        "whole AS (",
        "  SELECT",
        "    COUNT_IF(" + " OR ".join(f"{c} IS NULL" for c in ["census_year", "population_concept", "sex", "age",
                                                            *lineage, *stamp]) + ") AS missing_lineage,",
        "    COUNT_IF(run_id IS NULL OR run_id <> :run_id) AS other_run_rows,",
        "    COUNT(DISTINCT cleaned_at_utc) AS timestamps",
        "  FROM silver_rows",
        "),",
        "-- Silver rows whose Bronze row is not a count row of a current batch (an old version, a note, or gone).",
        "unresolved AS (",
        "  SELECT COUNT(*) AS unresolved_rows",
        "  FROM silver_rows AS s",
        "  LEFT JOIN bronze ON s.source_sha256 = bronze.source_sha256 AND s.source_sheet = bronze.source_sheet",
        "    AND s.source_row_number = bronze.source_row_number AND s.batch_id = bronze.batch_id",
        f"    AND {_is_data_row(spec, 'bronze')}",
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
    "logical_dataset": "The approved dataset the delivery belongs to (D-018): `school_age_population_2020` or `school_age_population_2024`",
    "batch_id": "The Bronze batch (one census workbook); joins `01-control`.ingestion_batches",
    "delivery_version": "Which delivery of the census year: 1, or 2+ after an approved revision",
    "schema_version": "Which layout the workbook had: `v1` wide (2020) or `v2` long (2024)",
    "source_sha256": "SHA-256 of the workbook; with `source_sheet` and `source_row_number`, identifies the Bronze row exactly",
    "source_sheet": "The sheet the count is on, e.g. `2024 Total Pop`; it gives `population_concept`",
    "source_row_number": "The Excel row of the count: the place row in 2020, the `Total`, `Male` or `Female` row in 2024",
    "place_row_number": "The Excel row of the place label; the same as `source_row_number` in 2020, the row above the three sex rows in 2024",
    "run_id": "The job run that built the row (`{{job.run_id}}`); every row of a build has the same one, as do the gate's results",
    "cleaned_at_utc": "When that build ran; one value for both tables, in UTC",
    "code_revision": "The commit that ran the build",
}

QUARANTINE_MEANING = {
    "population_blank": "the count cell is empty",
    "population_negative": "the count is a negative whole number",
    "population_not_whole_number": "the count is filled but not a whole number of up to nine digits (e.g. `1.5`, ` 12`)",
}


def dictionary_markdown(spec):
    m = spec.mapping
    levels = ", ".join(f"`{level}`" for level in spec.levels)
    concepts = ", ".join(f"`{c}` (sheet `<year> {s}`)" for c, s in spec.concepts.items())
    pins = "; ".join(f"{p['census_year']}: " + ", ".join(f"{level.replace('_', ' ')} {p[level]:,}" for level in spec.levels)
                     for p in spec.expected_levels)
    status_pins = "; ".join(f"{p['census_year']}: " + ", ".join(f"`{st}` {p[st]:,}" for st in spec.statuses)
                            for p in spec.expected_levels)
    status_rule = m["place_status"]
    rows = [
        ("census_year", "INT", "`census_year` of the delivery", "The census year (2020 CPH, 2024 POPCEN). Key", "Never", "O-1"),
        ("population_concept", "STRING", "`source_sheet`", f"{concepts}. {m['population_concept']['rule']} Key",
         "Never", m["population_concept"]["finding"]),
        ("place_label", "STRING", "`label` of the place row", "The published label, whitespace normalized (tabs and "
         "no-break spaces to spaces, runs of spaces to one, ends trimmed); footnote markers, brackets and case kept",
         "Never", "O-6"),
        ("place_name", "STRING", "`label`", "The label without its footnote marker and every bracketed part, upper case "
         "(`ALFONSO LISTA (POTIA)` becomes `ALFONSO LISTA`, `CITY OF MAKATI 1/` becomes `CITY OF MAKATI`). Not unique: "
         "114 city or municipality names repeat; key with `parent_name`", "Never (the gate fails otherwise)", "O-6"),
        ("footnote", "STRING", "`label`", "The trailing footnote marker, e.g. `1/` or `a/` (2024 only); the notes are in "
         "Bronze's `note` rows", "No marker", "O-6"),
        ("old_name", "STRING", "`label`", "The text of every bracket other than `(Capital)`, `, `-separated: mostly an old "
         "name (`POTIA`); for a region, its abbreviation (`CALABARZON`). Not a PSGC name", "No such bracket", "O-6"),
        ("is_capital", "BOOLEAN", "`label`", "TRUE when a bracket holds Capital in any case (`(Capital)`, `(CAPITAL)`). "
         "It follows the label only, and the workbooks mark capitals unevenly (2020 marks 81 places, 2024 marks 46; "
         "Tacloban is TRUE in 2020 and FALSE in 2024), so it is not a capital designation and a change between years "
         "is not a change of capital. Take capital status from PSGC", "Never", "O-6"),
        ("level", "STRING", "the counts", f"One of {levels}, from the sums (D-053): {m['levels']['rule']}",
         "Never (the gate fails otherwise)", m["levels"]["finding"]),
        ("place_status", "STRING", "the counts and `label`",
         f"`standard`, {', '.join(f'`{st}`' for st in spec.statuses)}. {status_rule['rule']} Pinned per workbook: "
         f"{status_pins}", "Never", status_rule["finding"]),
        ("region_name", "STRING", "the counts", "`place_name` of the region the place is in (itself for a region)",
         "The country", "O-2"),
        ("province_name", "STRING", "the counts", "`place_name` of the province the place is in (itself for a province)",
         "The country, a region, or a city or municipality directly under its region (the 16 NCR cities, Pateros, "
         "and the highly urbanized and independent cities)", "O-2"),
        ("parent_name", "STRING", "the counts", "`place_name` of the aggregate the place sums into; key, with `place_name`",
         "The country", "O-2, O-6"),
        ("sex", "STRING", "the band (2020) or the `Total` / `Male` / `Female` row (2024)",
         f"{', '.join(f'`{s}`' for s in spec.sexes)}; `both` is the published Both Sexes or Total, never recomputed "
         "(the gate checks it equals male + female). Key", "Never", "O-4"),
        ("age", "INT", "the age row", f"Single-year age, {spec.ages[0]} to {spec.ages[-1]}. Key", "Never", "O-1"),
        ("population", "INT", "the count cell", m["count"]["rule"], "Never (a blank cell is quarantined)",
         m["count"]["finding"]),
    ]
    rows += [(name, kind.upper(), "provenance" if name not in ("run_id", "cleaned_at_utc", "code_revision") else "Silver run",
              LINEAGE_MEANING[name], "Never", "") for name, kind in spec.clean_columns() if name in LINEAGE_MEANING]

    lines = [
        f"# `{spec.clean_table}`: Silver data dictionary",
        "",
        f"Generated by `python -m src.silver.cli dictionary --source {spec.source_id}` from "
        f"[the Bronze contract](../../../config/ingestion/{spec.source_id}.json) and "
        f"[the Silver rules](../../../config/mappings/{spec.source_id}.json). Do not edit by hand; "
        "`tests/test_silver_school_age.py` fails if it differs.",
        "",
        f"`` edu_access.`03-silver`.{spec.clean_table} ``: one row per count cell of the current census workbooks "
        "(`01-control`.current_batches): census year, population concept, place, sex and single-year age "
        f"{spec.ages[0]}-{spec.ages[-1]}. Key: (`census_year`, `population_concept`, `place_name`, `parent_name`, `sex`, "
        "`age`). Every row names the Bronze row it came from (`source_sha256`, `source_sheet`, `source_row_number`), "
        "so each count can be read back from Bronze. Rules, counts and the gate: "
        "[docs/operations/silver.md](../../operations/silver.md#psa-school-age-population).",
        "",
        "**Places are names only**, as published: no PSGC code. Their level and parent come from the sums, because the "
        "workbooks have neither (profile O-2). Matching the names to PSGC 2Q 2026 is the Integration map's job "
        "(`05_map_psa_school_age_population_psgc`), with the shared matching rules and reviewed aliases.",
        "",
        "**Never mix the two concepts** in one ratio: `total` is everyone, `household` leaves out people in "
        "institutional living quarters (D-029). AP4 uses `total`, both sexes, ages 5-17 (D-042). Every level is in the "
        "table, so filter `level` before summing: the country, regions and provinces are sums of the places below them.",
        "",
        f"**Levels per workbook**, pinned in the Silver rules and checked by the gate: {pins}. `level` is the "
        "place's position in the tree, not a verified PSGC level: `place_status` marks the places at a province or "
        "city position that are not a PSGC province or LGU (the Special Geographic Area and its 2020 clusters), "
        "for the Integration map (#159) to set aside.",
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
        "Cells whose count cannot be typed, set aside rather than deleted. Every count cell of a current batch is in "
        "exactly one of the two tables. Any quarantined cell fails the gate, so a published build has none: the "
        "profile found every count complete (O-3).",
        "",
        "| Column | Type | Meaning |",
        "|---|---|---|",
        "| `census_year`, `population_concept`, `place_label`, `sex`, `age` | | As in the clean table |",
        "| `quarantine_reasons` | `ARRAY<STRING>` | Every reason that applies, never empty (below) |",
    ]
    lines += [f"| `{name}` | {kind.upper()} | {LINEAGE_MEANING[name]} |"
              for name, kind in spec.quarantine_columns() if name in LINEAGE_MEANING]
    lines += ["", "| Reason | Meaning |", "|---|---|"]
    lines += [f"| `{r}` | {QUARANTINE_MEANING[r]} |" for r in QUARANTINE_REASONS]
    lines += ["", "## Not in Silver", "",
              "- Title, header, note and source rows: they stay in Bronze (`source_row_kind`).",
              "- No PSGC code, no 2023 estimate, no age-group totals: Integration and Gold choices (#158).",
              "- No row for a place the workbook does not list.", ""]
    return "\n".join(lines)
