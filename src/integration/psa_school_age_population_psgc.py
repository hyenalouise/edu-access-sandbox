"""Integration for psa_school_age_population: the map of census places to PSGC, its build SQL and its gate SQL.

Two reviewed inputs define it:

- `config/integration/psa_school_age_population_psgc.json`: the rules' order, the PSGC regions each
  census region covers today, the reviewed province aliases, and every reviewed override, with its
  reason and evidence;
- the published Silver tables `psa_school_age_population_clean` (D-053) and `psa_psgc_clean` (D-035).

One map row per city or municipality of each census year, none dropped, with the columns of the HDX
map (D-052). The workbooks have no codes (profile O-2), so every match is by name, and only inside a
PSGC parent: the province found for the place's province (by a reviewed alias, else by name or old
name inside the listed regions), or, for a place directly under its region, the region's cities and
municipalities that have no PSGC province. The name tiers are #154's: exact, folded, the word City
ignored, then old names. A name is never searched across provinces.

The SQL follows src/integration/hdx_adm3_psgc.py and src/silver/sql.py: the build writes a candidate
table, the gate checks it and publishes only if no check FAILs (D-025), and only syntax both
Databricks and DuckDB accept is used. No literal holds a quote, a backslash, ';', '--' or a
non-ASCII letter (Windows reads files as cp1252 by default).

    python -m src.integration.psa_school_age_population_psgc sql  > etl/04_integration/05_map_psa_school_age_population_psgc.sql
    python -m src.integration.psa_school_age_population_psgc gate > etl/04_integration/90_validate_psa_school_age_population_psgc_map.sql
"""

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.ingestion.bronze import OWNER_GROUP  # noqa: E402
from src.ingestion.errors import IngestionError  # noqa: E402
from src.integration.hdx_adm3_psgc import _fold, _no_city, name_keys, ref  # noqa: E402
from src.silver.sql import CONTROL, joined, lit  # noqa: E402

SOURCE_ID = "psa_school_age_population"
SCHEMA = "04-integration"
SILVER = "03-silver"
CONFIG = Path("config") / "integration" / "psa_school_age_population_psgc.json"
BUILD_FILE = "05_map_psa_school_age_population_psgc.sql"
PIPELINE = "integration_build"
LAYER = "integration"
SAFE_LITERAL = re.compile(r"^[^'\\;]*$")
PSGC_CODE = re.compile(r"^[0-9]{10}$")
REGION_CODE = re.compile(r"^[0-9]{2}0{8}$")

# D-029's values, as this map uses them.
MATCH_STATUSES = ("matched", "unmatched", "ambiguous")
MATCH_METHODS = ("name_exact", "name_normalized", "name_old", "reviewed_alias")
REVIEW_STATUSES = ("rule", "reviewed", "pending")
# How the PSGC parent the name was searched in was found.
PARENT_MATCHES = ("province_name", "province_old_name", "province_alias", "region")
# #154's name tiers, in order: (name in the reason, D-029 method).
TIERS = (("exact", "name_exact"), ("folded", "name_normalized"), ("word City ignored", "name_normalized"),
         ("old name", "name_old"))
# AP4's slice (D-042), recorded per census year as the share of its population that is matched.
AP4_CONCEPT, AP4_SEX, AP4_AGES = "total", "both", (5, 17)
SOURCE_LINEAGE = (("batch_id", "string"), ("source_sha256", "string"), ("source_sheet", "string"),
                  ("place_row_number", "bigint"))
PSGC_LINEAGE = (("psgc_batch_id", "string"), ("psgc_source_row_number", "bigint"))
RUN_STAMP = (("run_id", "string"), ("built_at_utc", "timestamp"), ("code_revision", "string"))


def _error(message):
    return IngestionError("config", "invalid_integration_rules", message)


@dataclass
class Region:
    census_year: int
    region_name: str
    codes: list             # PSGC region codes (ten digits) the census region covers today


@dataclass
class Alias:
    census_year: int
    province_name: str
    codes: list             # PSGC province codes searched for the province's places


@dataclass
class Override:
    census_year: int
    parent_name: str
    place_name: str
    psgc_code: str          # None: reviewed as unmatched
    match_method: str
    reason: str


@dataclass
class MapSpec:
    map_table: str
    source_table: str
    psgc_table: str
    place_level: str
    lineage_concept: str
    levels: list
    regions: list
    aliases: list
    overrides: list
    rules: dict = field(repr=False)

    @property
    def candidate(self):
        return f"{self.map_table}_candidate"

    @property
    def census_years(self):
        return sorted({r.census_year for r in self.regions})

    def columns(self):
        return [
            ("source_id", "string"), ("source_row_ref", "string"), ("census_year", "int"), ("place_label", "string"),
            ("place_name", "string"), ("old_name", "string"), ("parent_name", "string"), ("province_name", "string"),
            ("region_name", "string"), ("place_status", "string"),
            ("psgc_version", "string"), ("psgc_code", "string"), ("psgc_name", "string"), ("geographic_level", "string"),
            ("match_status", "string"), ("match_method", "string"), ("review_status", "string"),
            ("parent_match", "string"), ("reason", "string"),
        ] + list(SOURCE_LINEAGE) + list(PSGC_LINEAGE) + list(RUN_STAMP)


def load_spec(repo_root=REPO_ROOT):
    path = Path(repo_root) / CONFIG
    if not path.is_file():
        raise _error(f"{path} does not exist.")
    return build_spec(json.loads(path.read_text(encoding="utf-8")))


def _year(entry, what):
    year = entry.get("census_year")
    if not isinstance(year, int) or isinstance(year, bool):
        raise _error(f"{what} {entry!r}: census_year must be a whole number.")
    return year


def build_spec(rules):
    regions, seen = [], set()
    for entry in rules.get("regions", []):
        year, name, codes = _year(entry, "region"), entry.get("region_name"), entry.get("psgc_region_codes") or []
        if not name or (year, name) in seen:
            raise _error(f"region {entry!r}: needs a region_name, once per census year.")
        seen.add((year, name))
        if not codes or not all(isinstance(c, str) and REGION_CODE.match(c) for c in codes):
            raise _error(f"region {name} ({year}): psgc_region_codes must be PSGC region codes (two digits and eight zeros).")
        regions.append(Region(year, name, list(codes)))
    aliases, seen = [], set()
    for entry in rules.get("province_aliases", []):
        year, name, codes = _year(entry, "province alias"), entry.get("province_name"), entry.get("psgc_province_codes") or []
        if not name or (year, name) in seen:
            raise _error(f"province alias {entry!r}: needs a province_name, once per census year.")
        seen.add((year, name))
        if not codes or not all(isinstance(c, str) and PSGC_CODE.match(c) for c in codes):
            raise _error(f"province alias {name} ({year}): psgc_province_codes must be ten-digit PSGC codes.")
        if not entry.get("reason") or not entry.get("evidence"):
            raise _error(f"province alias {name} ({year}) needs a reason and evidence.")
        aliases.append(Alias(year, name, list(codes)))
    overrides, seen = [], set()
    for entry in rules.get("overrides", []):
        year = _year(entry, "override")
        parent, place, code, method = (entry.get(k) for k in ("parent_name", "place_name", "psgc_code", "match_method"))
        if not parent or not place:
            raise _error(f"override {entry!r}: needs the place's parent_name and place_name as in Silver.")
        if (year, parent, place) in seen:
            raise _error(f"override for {place} ({parent}, {year}) is listed twice.")
        seen.add((year, parent, place))
        if code is not None and not PSGC_CODE.match(code):
            raise _error(f"override for {place} ({parent}, {year}): psgc_code must be ten digits or null.")
        if code is None and method is not None:
            raise _error(f"override for {place} ({parent}, {year}): a reviewed unmatched place has no match_method (null).")
        if code is not None and method not in MATCH_METHODS:
            raise _error(f"override for {place} ({parent}, {year}): match_method {method!r} is not one of {MATCH_METHODS}.")
        if not entry.get("reason") or not entry.get("evidence"):
            raise _error(f"override for {place} ({parent}, {year}) needs a reason and evidence.")
        overrides.append(Override(year, parent, place, code, method, entry["reason"]))
    levels = list(rules["psgc"]["levels"])
    literals = [*levels, rules["source"]["place_level"], rules["source"]["lineage_concept"],
                *[r.region_name for r in regions], *[a.province_name for a in aliases],
                *[v for o in overrides for v in (o.parent_name, o.place_name, o.match_method or "", o.reason)]]
    unsafe = [v for v in literals if not SAFE_LITERAL.match(v) or "--" in v or not v.isascii()]
    if unsafe:
        raise _error(f"rules may not contain quotes, backslashes, ';', '--' or non-ASCII letters: {unsafe}.")
    return MapSpec(rules["map_table"], rules["source"]["silver_table"], rules["psgc"]["silver_table"],
                   rules["source"]["place_level"], rules["source"]["lineage_concept"], levels, regions, aliases,
                   overrides, rules)


# --- Shared SQL pieces -------------------------------------------------------------------

def _header(what, command, path):
    return [
        f"-- {what} for {SOURCE_ID}. Generated from {CONFIG.as_posix()} by src/integration/psa_school_age_population_psgc.py:",
        f"--   python -m src.integration.psa_school_age_population_psgc {command} > {path}",
        "-- Do not edit by hand; tests/test_integration_school_age.py fails if it differs.",
    ]


def _values(columns, rows):
    """A VALUES query with typed columns; an empty list gives no rows."""
    if not rows:
        nulls = ", ".join(f"CAST(NULL AS {t}) AS {n}" for n, t in columns)
        return f"SELECT {nulls} WHERE 1 = 0"
    names = ", ".join(n for n, _ in columns)
    return f"SELECT * FROM (VALUES {', '.join(rows)}) AS v({names})"


def _sql(value, kind="STRING"):
    if value is None:
        return f"CAST(NULL AS {kind})"
    return str(value) if kind == "INT" else lit(value)


def _regions_values(spec):
    rows = [f"({r.census_year}, {lit(r.region_name)}, {lit(c[:2])})" for r in spec.regions for c in r.codes]
    return _values((("census_year", "INT"), ("region_name", "STRING"), ("region2", "STRING")), rows)


def _region_codes_values(spec):
    rows = sorted({f"({lit(c)})" for r in spec.regions for c in r.codes})
    return _values((("psgc_code", "STRING"),), rows)


def _aliases_values(spec):
    rows = [f"({a.census_year}, {lit(a.province_name)}, {lit(c)})" for a in spec.aliases for c in a.codes]
    return _values((("census_year", "INT"), ("province_name", "STRING"), ("psgc_code", "STRING")), rows)


def _overrides_values(spec):
    rows = [f"({o.census_year}, {lit(o.parent_name)}, {lit(o.place_name)}, {_sql(o.psgc_code)}, {_sql(o.match_method)}, "
            f"{lit(o.reason)})" for o in spec.overrides]
    return _values((("census_year", "INT"), ("parent_name", "STRING"), ("place_name", "STRING"), ("psgc_code", "STRING"),
                    ("match_method", "STRING"), ("reason", "STRING")), rows)


def _keys(alias, column, prefix):
    """k_exact, k_fold and k_city for a name column, NULL when the column is."""
    base = name_keys(f"{alias}.{column}")[1]
    return f"CASE WHEN {alias}.{column} IS NULL THEN NULL ELSE ({base}) END AS {prefix}k_exact"


def _pair_tier(s, u):
    """The first of #154's tiers at which place s matches PSGC unit u, as 1..4, or NULL."""
    return ("CASE "
            f"WHEN {s}.k_exact = {u}.k_exact THEN 1 "
            f"WHEN {s}.k_fold = {u}.k_fold THEN 2 "
            f"WHEN {s}.k_city = {u}.k_city THEN 3 "
            f"WHEN {s}.k_fold = {u}.ok_fold OR {s}.ok_fold = {u}.k_fold OR {s}.ok_fold = {u}.ok_fold THEN 4 END")


def _tier_case(expr, index):
    return "CASE " + " ".join(f"WHEN {expr} = {i} THEN {lit(t[index])}" for i, t in enumerate(TIERS, 1)) + " END"


def _parents_ctes():
    """The PSGC parents a place can be searched in, with the keys of their name and old name: provinces, and the
    blank-level containers that stand for one (the Special Geographic Area, City of Isabela). Reads a CTE psgc."""
    return [
        "p0 AS (",
        "  SELECT p.psgc_code, p.level_blank,",
        joined([_keys("p", "name", ""), _keys("p", "old_names", "o")], 9),
        "  FROM psgc AS p WHERE p.geographic_level = 'Prov' OR (p.level_blank AND p.province_code = p.psgc_code)",
        "),",
        f"parents AS (SELECT p0.*, {_fold('p0.k_exact')} AS k_fold, {_fold('p0.ok_exact')} AS ok_fold FROM p0),",
    ]


def _source_row_ref(alias):
    return f"CAST({alias}.census_year AS STRING) || '/' || {alias}.parent_name || '/' || {alias}.place_name"


# --- Build ---------------------------------------------------------------------------------

def build_sql(spec):
    source, psgc = ref(SILVER, spec.source_table), ref(SILVER, spec.psgc_table)
    candidate = ref(SCHEMA, spec.candidate)
    levels = ", ".join(lit(x) for x in spec.levels)
    columns = [name for name, _ in spec.columns()]
    lines = _header("Integration build", "sql", f"etl/04_integration/{BUILD_FILE}") + [
        "--",
        f"-- Rebuilds {spec.candidate}: one row per city or municipality of each census year in the published",
        f"-- {spec.source_table}, matched by name to the cities and municipalities of the master PSGC quarter in",
        f"-- {spec.psgc_table}, only inside the PSGC parent found for the place. No place is dropped: a place no rule",
        f"-- matches is kept as unmatched or ambiguous. The map table ({spec.map_table}) is never written here: the",
        "-- gate checks the candidate and publishes it only if no check fails (as D-025 does for Silver).",
        "-- Rules, regions, aliases and overrides: the rules file above.",
        "--",
        "-- Parameters, supplied by the job (or src/job/local_run.py):",
        "--   :run_id, :code_revision, :environment",
        "",
        "DECLARE OR REPLACE VARIABLE integration_run_id STRING;",
        "SET VARIABLE integration_run_id = :run_id;",
        "DECLARE OR REPLACE VARIABLE integration_code_revision STRING;",
        "SET VARIABLE integration_code_revision = COALESCE(NULLIF(:code_revision, ''), 'UNSET');",
        "DECLARE OR REPLACE VARIABLE integration_environment STRING;",
        "SET VARIABLE integration_environment = COALESCE(NULLIF(:environment, ''), 'UNSET');",
        "DECLARE OR REPLACE VARIABLE integration_built_at_utc TIMESTAMP;",
        "SET VARIABLE integration_built_at_utc = current_timestamp();",
        "",
        "-- The run starts; the gate records how it ended (D-020).",
        f"MERGE INTO {CONTROL}.pipeline_runs AS t",
        "USING (SELECT session.integration_run_id AS run_id) AS s",
        f"ON t.run_id = s.run_id AND t.pipeline_name = {lit(PIPELINE)} AND t.source_id = {lit(SOURCE_ID)}",
        "WHEN MATCHED THEN UPDATE SET",
        "  status = 'running', started_at_utc = session.integration_built_at_utc, finished_at_utc = NULL,",
        "  failure_stage = NULL, error_message = NULL, code_revision = session.integration_code_revision, job_run_id = s.run_id",
        "WHEN NOT MATCHED THEN INSERT (run_id, pipeline_name, source_id, environment, status, started_at_utc, code_revision, job_run_id)",
        f"  VALUES (s.run_id, {lit(PIPELINE)}, {lit(SOURCE_ID)}, session.integration_environment, 'running',",
        "          session.integration_built_at_utc, session.integration_code_revision, s.run_id);",
        "",
        f"CREATE SCHEMA IF NOT EXISTS edu_access.`{SCHEMA}`;",
        f"ALTER SCHEMA edu_access.`{SCHEMA}` OWNER TO `{OWNER_GROUP}`;",
        "",
        "CREATE OR REPLACE TEMPORARY VIEW psa_school_age_population_psgc_matched AS",
        "-- The master PSGC quarter.",
        "WITH psgc AS (",
        "  SELECT psgc_code, name, old_names, geographic_level, level_blank, province_code, publication_period,",
        "         batch_id, source_row_number",
        f"  FROM {psgc} WHERE is_master_reference",
        "),",
        "-- Parents: provinces, and the blank-level containers that stand for one (the Special Geographic Area,",
        "-- City of Isabela), each with the keys of its name and old name.",
        *_parents_ctes(),
        "-- The cities and municipalities, with the keys of their name and old name. no_province: not inside a",
        "-- PSGC province (the highly urbanized cities, Pateros, and the units of a blank-level container).",
        "u0 AS (",
        "  SELECT u.psgc_code, u.province_code, substr(u.psgc_code, 1, 2) AS region2,",
        "         u.province_code IS NULL OR bp.psgc_code IS NOT NULL AS no_province,",
        joined([_keys("u", "name", ""), _keys("u", "old_names", "o")], 9),
        "  FROM psgc AS u LEFT JOIN parents AS bp ON bp.level_blank AND bp.psgc_code = u.province_code",
        f"  WHERE u.geographic_level IN ({levels})",
        "),",
        f"u1 AS (SELECT u0.*, {_fold('u0.k_exact')} AS k_fold, {_fold('u0.ok_exact')} AS ok_fold FROM u0),",
        f"units AS (SELECT u1.*, {_no_city('u1.k_fold')} AS k_city FROM u1),",
        "-- The census places: one per (census year, place, parent), with the lineage of its row on the",
        f"-- {spec.lineage_concept} sheet (the other concept lists the same places; the gate checks it).",
        "s0 AS (",
        "  SELECT census_year, place_name, parent_name,",
        "         MIN(place_label) AS place_label, MIN(old_name) AS old_name, MIN(province_name) AS province_name,",
        "         MIN(region_name) AS region_name, MIN(place_status) AS place_status,",
        "         MIN(batch_id) AS batch_id, MIN(source_sha256) AS source_sha256, MIN(source_sheet) AS source_sheet,",
        "         MIN(place_row_number) AS place_row_number",
        f"  FROM {source}",
        f"  WHERE level = {lit(spec.place_level)} AND population_concept = {lit(spec.lineage_concept)}",
        "  GROUP BY census_year, place_name, parent_name",
        "),",
        "s1 AS (",
        "  SELECT s0.*,",
        joined([_keys("s0", "place_name", ""), _keys("s0", "old_name", "o")], 9),
        "  FROM s0",
        "),",
        f"s2 AS (SELECT s1.*, {_fold('s1.k_exact')} AS k_fold, {_fold('s1.ok_exact')} AS ok_fold FROM s1),",
        f"s AS (SELECT s2.*, {_no_city('s2.k_fold')} AS k_city FROM s2),",
        f"regions AS ({_regions_values(spec)}),",
        f"aliases AS ({_aliases_values(spec)}),",
        f"overrides AS ({_overrides_values(spec)}),",
        "-- Each census province: its keys, then the PSGC parent(s) found for it. A reviewed alias first;",
        "-- else the one parent inside the listed regions whose name (1) or old name (2) matches, exact or folded.",
        "pp0 AS (",
        "  SELECT DISTINCT census_year, region_name, province_name FROM s0 WHERE province_name IS NOT NULL",
        "),",
        "pp1 AS (SELECT pp0.*, " + _keys("pp0", "province_name", "") + " FROM pp0),",
        f"pp AS (SELECT pp1.*, {_fold('pp1.k_exact')} AS k_fold FROM pp1),",
        "by_province_name AS (",
        "  SELECT pp.census_year, pp.province_name, pa.psgc_code,",
        "         CASE WHEN pp.k_exact = pa.k_exact OR pp.k_fold = pa.k_fold THEN 1",
        "              WHEN pp.k_exact = pa.ok_exact OR pp.k_fold = pa.ok_fold THEN 2 END AS tier",
        "  FROM pp",
        "  JOIN regions AS r ON r.census_year = pp.census_year AND r.region_name = pp.region_name",
        "  JOIN parents AS pa ON substr(pa.psgc_code, 1, 2) = r.region2",
        "),",
        "province_best AS (",
        "  SELECT census_year, province_name, MIN(tier) AS tier FROM by_province_name WHERE tier IS NOT NULL",
        "  GROUP BY census_year, province_name",
        "),",
        "province_hit AS (",
        "  SELECT b.census_year, b.province_name, b.tier, COUNT(DISTINCT n.psgc_code) AS hits, MIN(n.psgc_code) AS psgc_code",
        "  FROM province_best AS b JOIN by_province_name AS n",
        "    ON n.census_year = b.census_year AND n.province_name = b.province_name AND n.tier = b.tier",
        "  GROUP BY b.census_year, b.province_name, b.tier",
        "),",
        "province_scope AS (",
        "  SELECT census_year, province_name, psgc_code AS province_code, 'province_alias' AS parent_match FROM aliases",
        "  UNION ALL",
        "  SELECT h.census_year, h.province_name, h.psgc_code,",
        "         CASE WHEN h.tier = 1 THEN 'province_name' ELSE 'province_old_name' END",
        "  FROM province_hit AS h",
        "  LEFT JOIN aliases AS a ON a.census_year = h.census_year AND a.province_name = h.province_name",
        "  WHERE h.hits = 1 AND a.province_name IS NULL",
        "),",
        "-- Each place's parent: its province's scope, or, directly under its region, the region's units with no",
        "-- province. A place with neither gets no name match (names are matched only inside a matched parent).",
        "scope AS (",
        "  SELECT s.census_year, s.place_name, s.parent_name, MIN(ps.parent_match) AS parent_match",
        "  FROM s JOIN province_scope AS ps ON ps.census_year = s.census_year AND ps.province_name = s.province_name",
        "  GROUP BY s.census_year, s.place_name, s.parent_name",
        "  UNION ALL",
        "  SELECT DISTINCT s.census_year, s.place_name, s.parent_name, 'region'",
        "  FROM s JOIN regions AS r ON r.census_year = s.census_year AND r.region_name = s.region_name",
        "  WHERE s.province_name IS NULL",
        "),",
        "by_name AS (",
        f"  SELECT s.census_year, s.place_name, s.parent_name, u.psgc_code, {_pair_tier('s', 'u')} AS tier",
        "  FROM s JOIN province_scope AS ps ON ps.census_year = s.census_year AND ps.province_name = s.province_name",
        "  JOIN units AS u ON u.province_code = ps.province_code",
        "  UNION ALL",
        f"  SELECT s.census_year, s.place_name, s.parent_name, u.psgc_code, {_pair_tier('s', 'u')}",
        "  FROM s JOIN regions AS r ON r.census_year = s.census_year AND r.region_name = s.region_name",
        "  JOIN units AS u ON s.province_name IS NULL AND u.no_province AND u.region2 = r.region2",
        "),",
        "best AS (",
        "  SELECT census_year, place_name, parent_name, MIN(tier) AS tier FROM by_name WHERE tier IS NOT NULL",
        "  GROUP BY census_year, place_name, parent_name",
        "),",
        "name_hit AS (",
        "  SELECT b.census_year, b.place_name, b.parent_name, b.tier, COUNT(DISTINCT n.psgc_code) AS hits,",
        "         MIN(n.psgc_code) AS psgc_code",
        "  FROM best AS b JOIN by_name AS n ON n.census_year = b.census_year AND n.place_name = b.place_name",
        "    AND n.parent_name = b.parent_name AND n.tier = b.tier",
        "  GROUP BY b.census_year, b.place_name, b.parent_name, b.tier",
        "),",
        "-- One decision per place, in the rules' order.",
        "decided AS (",
        "  SELECT s.*, sc.parent_match,",
        "    CASE WHEN o.place_name IS NOT NULL THEN o.psgc_code",
        "         WHEN nh.hits = 1 THEN nh.psgc_code",
        "         ELSE NULL END AS psgc_code,",
        "    CASE WHEN o.place_name IS NOT NULL THEN CASE WHEN o.psgc_code IS NULL THEN 'unmatched' ELSE 'matched' END",
        "         WHEN nh.hits = 1 THEN 'matched'",
        "         WHEN nh.hits > 1 THEN 'ambiguous'",
        "         ELSE 'unmatched' END AS match_status,",
        "    CASE WHEN o.place_name IS NOT NULL THEN o.match_method",
        f"         WHEN nh.hits = 1 THEN {_tier_case('nh.tier', 1)}",
        "         END AS match_method,",
        "    CASE WHEN o.place_name IS NOT NULL THEN 'reviewed'",
        "         WHEN nh.hits = 1 THEN 'rule'",
        "         ELSE 'pending' END AS review_status,",
        "    CASE WHEN o.place_name IS NOT NULL THEN o.reason",
        f"         WHEN nh.hits = 1 THEN 'name in parent, ' || {_tier_case('nh.tier', 0)}",
        f"         WHEN nh.hits > 1 THEN CAST(nh.hits AS STRING) || ' units match at tier ' || {_tier_case('nh.tier', 0)}",
        "         WHEN sc.parent_match IS NULL AND s.province_name IS NULL THEN 'region not listed in the rules, so no name match was tried'",
        "         WHEN sc.parent_match IS NULL THEN 'no PSGC province found for the province name, so no name match was tried'",
        "         ELSE 'no name match in the parent' END AS reason",
        "  FROM s",
        "  LEFT JOIN overrides AS o ON o.census_year = s.census_year AND o.parent_name = s.parent_name AND o.place_name = s.place_name",
        "  LEFT JOIN scope AS sc ON sc.census_year = s.census_year AND sc.place_name = s.place_name AND sc.parent_name = s.parent_name",
        "  LEFT JOIN name_hit AS nh ON nh.census_year = s.census_year AND nh.place_name = s.place_name",
        "    AND nh.parent_name = s.parent_name",
        ")",
        "SELECT",
        joined([
            lit(SOURCE_ID) + " AS source_id", _source_row_ref("d") + " AS source_row_ref", "d.census_year",
            "d.place_label", "d.place_name", "d.old_name", "d.parent_name", "d.province_name", "d.region_name",
            "d.place_status",
            "(SELECT MIN(publication_period) FROM psgc) AS psgc_version", "d.psgc_code", "p.name AS psgc_name",
            "'city_mun' AS geographic_level",
            "d.match_status", "d.match_method", "d.review_status", "d.parent_match", "d.reason",
            "d.batch_id", "d.source_sha256", "d.source_sheet", "d.place_row_number",
            "p.batch_id AS psgc_batch_id", "p.source_row_number AS psgc_source_row_number",
            "session.integration_run_id AS run_id", "session.integration_built_at_utc AS built_at_utc",
            "session.integration_code_revision AS code_revision",
        ], 2),
        "FROM decided AS d",
        "LEFT JOIN psgc AS p ON p.psgc_code = d.psgc_code;",
        "",
        f"CREATE OR REPLACE TABLE {candidate} USING DELTA AS",
        "SELECT",
        joined(columns, 2),
        "FROM psa_school_age_population_psgc_matched;",
        "",
        (f"COMMENT ON TABLE {candidate} IS 'Unpublished build for the Integration gate, which may have failed. "
         f"Do not read: use {spec.map_table}.';"),
        f"ALTER TABLE {candidate} OWNER TO `{OWNER_GROUP}`;",
        "",
    ]
    return "\n".join(lines)


# --- Gate ----------------------------------------------------------------------------------

FAILS = ("inputs_present", "rows_reconcile", "one_row_per_place", "psgc_code_taken_once", "matched_has_psgc_unit",
         "unmatched_has_no_psgc", "status_valid", "method_valid", "review_status_valid", "status_combination_valid",
         "psgc_name_matches_unit", "name_match_inside_province", "parent_match_valid", "overrides_applied",
         "rule_codes_in_psgc", "one_psgc_version", "lineage_complete", "rows_built_by_this_run", "population_reconciles")
WARNS = ("review_pending", "unmatched", "ambiguous", "override_place_missing", "region_not_listed",
         "province_without_psgc_parent", "psgc_units_without_place")


def gate_checks(spec):
    """[(check_name, status)] in the order the gate writes them."""
    records = [f"method_{m}_{y}" for y in spec.census_years for m in MATCH_METHODS]
    records += [f"{r}_{y}" for y in spec.census_years for r in ("match_rate_percent", "ap4_population_matched_percent")]
    return [(n, "FAIL") for n in FAILS] + [(n, "WARN") for n in WARNS] + [(n, "record") for n in records]


def gate_sql(spec):
    source, psgc = ref(SILVER, spec.source_table), ref(SILVER, spec.psgc_table)
    candidate, published = ref(SCHEMA, spec.candidate), ref(SCHEMA, spec.map_table)
    table = f"edu_access.{SCHEMA}.{spec.candidate}"
    levels = ", ".join(lit(x) for x in spec.levels)
    place = lit(spec.place_level)

    def check(name, status, expected, actual):
        return (f"SELECT {lit(name)} AS check_name, {status} AS status, {expected} AS expected, "
                f"CAST({actual} AS STRING) AS actual FROM stats")

    def zero(name, actual):
        return check(name, f"CASE WHEN {actual} = 0 THEN 'PASS' ELSE 'FAIL' END", "'0'", actual)

    def equal(name, expected, actual):
        return check(name, f"CASE WHEN {actual} = {expected} THEN 'PASS' ELSE 'FAIL' END", f"CAST({expected} AS STRING)", actual)

    def warn(name, actual):
        return check(name, f"CASE WHEN {actual} = 0 THEN 'PASS' ELSE 'WARN' END", "'0'", actual)

    def record(name, actual):
        return check(name, "'PASS'", "CAST(NULL AS STRING)", actual)

    def in_year(year, condition):
        return f"m.census_year = {year} AND {condition}"

    stats = [
        "COUNT(*) AS map_rows",
        "COUNT(DISTINCT m.source_row_ref) AS map_places",
        "COUNT_IF(m.match_status = 'matched') AS matched_rows",
        ("COUNT(DISTINCT CASE WHEN m.match_status = 'matched' THEN CAST(m.census_year AS STRING) || '/' || m.psgc_code "
         "END) AS matched_codes"),
        "COUNT_IF(m.match_status = 'matched' AND (m.psgc_code IS NULL OR u.psgc_code IS NULL)) AS matched_without_unit",
        "COUNT_IF(m.match_status <> 'matched' AND m.psgc_code IS NOT NULL) AS unmatched_with_code",
        f"COUNT_IF(m.match_status IS NULL OR m.match_status NOT IN ({', '.join(lit(x) for x in MATCH_STATUSES)})) AS bad_status",
        (f"COUNT_IF((m.match_status = 'matched' AND (m.match_method IS NULL OR m.match_method NOT IN "
         f"({', '.join(lit(x) for x in MATCH_METHODS)}))) OR (m.match_status <> 'matched' AND m.match_method IS NOT NULL)) AS bad_method"),
        f"COUNT_IF(m.review_status IS NULL OR m.review_status NOT IN ({', '.join(lit(x) for x in REVIEW_STATUSES)})) AS bad_review",
        # D-052: only rule-based or reviewed rows are matched, and only matched rows carry a method and a code.
        ("COUNT_IF(NOT COALESCE("
         "(m.match_status = 'matched' AND m.review_status IN ('rule', 'reviewed') AND m.match_method IS NOT NULL "
         "AND m.psgc_code IS NOT NULL) OR "
         "(m.match_status = 'ambiguous' AND m.review_status = 'pending' AND m.match_method IS NULL AND m.psgc_code IS NULL) OR "
         "(m.match_status = 'unmatched' AND m.review_status IN ('pending', 'reviewed') AND m.match_method IS NULL "
         "AND m.psgc_code IS NULL), FALSE)) AS bad_combination"),
        # #181 (D-052): the stored name is the master name of the code.
        ("COUNT_IF(m.match_status = 'matched' AND (m.psgc_name IS NULL OR u.name IS NULL OR "
         "m.psgc_name <> u.name)) AS psgc_name_mismatch"),
        # A rule match was searched in a parent; the parent's code prefix holds the unit.
        (f"COUNT_IF((m.parent_match IS NOT NULL AND m.parent_match NOT IN ({', '.join(lit(x) for x in PARENT_MATCHES)})) "
         "OR (m.review_status = 'rule' AND m.parent_match IS NULL)) AS bad_parent_match"),
        "COUNT_IF(m.review_status = 'reviewed') AS overrides_used",
        ("COUNT_IF(m.source_row_ref IS NULL OR m.batch_id IS NULL OR m.source_sha256 IS NULL OR m.source_sheet IS NULL "
         "OR m.place_row_number IS NULL OR m.run_id IS NULL OR m.built_at_utc IS NULL OR m.code_revision IS NULL "
         "OR (m.psgc_code IS NOT NULL AND (m.psgc_batch_id IS NULL OR m.psgc_source_row_number IS NULL))) AS missing_lineage"),
        "COUNT_IF(m.run_id IS NULL OR m.run_id <> :run_id) AS other_run_rows",
        "COUNT_IF(m.review_status = 'pending') AS pending_rows",
        "COUNT_IF(m.match_status = 'unmatched') AS unmatched_rows",
        "COUNT_IF(m.match_status = 'ambiguous') AS ambiguous_rows",
    ]
    for y in spec.census_years:
        stats += [f"COUNT_IF({in_year(y, 'TRUE')}) AS rows_{y}",
                  "COUNT_IF(" + in_year(y, "m.match_status = 'matched'") + f") AS matched_{y}"]
        stats += [f"COUNT_IF({in_year(y, 'm.match_status = ' + lit('matched') + ' AND m.match_method = ' + lit(x))}) "
                  f"AS method_{x}_{y}" for x in MATCH_METHODS]

    checks = [
        check("inputs_present", "CASE WHEN source_places > 0 AND psgc_units > 0 THEN 'PASS' ELSE 'FAIL' END",
              "'census places and PSGC units'", "CAST(source_places AS STRING) || ' / ' || CAST(psgc_units AS STRING)"),
        equal("rows_reconcile", "source_places", "map_rows"),
        equal("one_row_per_place", "map_rows", "map_places"),
        equal("psgc_code_taken_once", "matched_rows", "matched_codes"),
        zero("matched_has_psgc_unit", "matched_without_unit"),
        zero("unmatched_has_no_psgc", "unmatched_with_code"),
        zero("status_valid", "bad_status"),
        zero("method_valid", "bad_method"),
        zero("review_status_valid", "bad_review"),
        zero("status_combination_valid", "bad_combination"),
        zero("psgc_name_matches_unit", "psgc_name_mismatch"),
        zero("name_match_inside_province", "name_scope_mismatch"),
        zero("parent_match_valid", "bad_parent_match"),
        equal("overrides_applied", "overrides_present", "overrides_used"),
        # Review on #187: a region or alias code is reviewed configuration, so one missing from the master
        # quarter at its level is an error to fix, not a reason to publish a map with that geography unmatched.
        zero("rule_codes_in_psgc", "bad_rule_codes"),
        equal("one_psgc_version", "1", "master_periods"),
        zero("lineage_complete", "missing_lineage"),
        zero("rows_built_by_this_run", "other_run_rows"),
        zero("population_reconciles", "population_cells_off"),
        warn("review_pending", "pending_rows"),
        warn("unmatched", "unmatched_rows"),
        warn("ambiguous", "ambiguous_rows"),
        warn("override_place_missing", "overrides_missing"),
        warn("region_not_listed", "regions_missing"),
        warn("province_without_psgc_parent", "provinces_unresolved"),
        warn("psgc_units_without_place", "units_without_place"),
        *[record(f"method_{x}_{y}", f"method_{x}_{y}") for y in spec.census_years for x in MATCH_METHODS],
        *[record(f"match_rate_percent_{y}", f"CASE WHEN rows_{y} = 0 THEN 0 ELSE ROUND(100.0 * matched_{y} / rows_{y}, 2) END")
          for y in spec.census_years],
        *[record(f"ap4_population_matched_percent_{y}",
                 f"CASE WHEN ap4_total_{y} = 0 THEN 0 ELSE ROUND(100.0 * ap4_matched_{y} / ap4_total_{y}, 2) END")
          for y in spec.census_years],
    ]
    # Records come in the order gate_checks lists them.
    order = {n: i for i, (n, _) in enumerate(gate_checks(spec))}
    checks.sort(key=lambda c: order[re.search(r"SELECT '([a-z0-9_]+)' AS check_name", c).group(1)])
    assert [c for c, _ in gate_checks(spec)] == [re.search(r"SELECT '([a-z0-9_]+)' AS check_name", c).group(1) for c in checks]
    union = ["  " + checks[0]] + ["  UNION ALL " + c for c in checks[1:]]

    ap4 = (f"c.population_concept = {lit(AP4_CONCEPT)} AND c.sex = {lit(AP4_SEX)} "
           f"AND c.age BETWEEN {AP4_AGES[0]} AND {AP4_AGES[1]}")
    ap4_totals = []
    for y in spec.census_years:
        ap4_totals += [
            f"         (SELECT COALESCE(SUM(c.population), 0) FROM {source} AS c WHERE c.level = 'country' "
            f"AND c.census_year = {y} AND {ap4}) AS ap4_total_{y},",
            f"         (SELECT COALESCE(SUM(c.population), 0) FROM {source} AS c JOIN {candidate} AS m",
            "            ON m.census_year = c.census_year AND m.place_name = c.place_name AND m.parent_name = c.parent_name",
            f"          WHERE c.level = {place} AND m.match_status = 'matched' AND c.census_year = {y} AND {ap4}) AS ap4_matched_{y},",
        ]

    lines = _header("Integration gate", "gate", f"etl/04_integration/90_validate_{spec.map_table}.sql") + [
        "--",
        f"-- The job task after the build. It checks {spec.candidate}, one row per check in",
        "-- data_quality_results (layer 'integration'). On any FAIL it records the run 'failed' and stops",
        f"-- before publishing, so {spec.map_table} keeps the last map that passed. Otherwise it copies",
        "-- the candidate to the map table and records the run 'succeeded'. WARN (pending reviews, unmatched,",
        "-- ambiguous, an override whose place is not in the data, a census region the rules do not list, a",
        "-- census province with no PSGC parent, PSGC cities and municipalities no place matched, counted per",
        "-- census year) is recorded and the map is published. Results hold counts, never row values.",
        "",
        "DECLARE OR REPLACE VARIABLE integration_gate_started_at_utc TIMESTAMP;",
        "SET VARIABLE integration_gate_started_at_utc = current_timestamp();",
        "",
        f"INSERT INTO {CONTROL}.data_quality_results",
        "  (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)",
        f"SELECT :run_id, CAST(NULL AS STRING), {lit(SOURCE_ID)}, {lit(LAYER)}, {lit(table)}, check_name, status, expected, actual,",
        "       current_timestamp(), :code_revision",
        "FROM (",
        "-- Every place of either concept: a place only one concept lists still needs its map row.",
        f"WITH places AS (SELECT DISTINCT census_year, place_name, parent_name, region_name, province_name FROM {source}",
        f"                WHERE level = {place}),",
        f"psgc AS (SELECT * FROM {psgc} WHERE is_master_reference),",
        *_parents_ctes(),
        "units AS (",
        "  SELECT u.psgc_code, u.name, u.province_code, substr(u.psgc_code, 1, 2) AS region2,",
        "         u.province_code IS NULL OR bp.psgc_code IS NOT NULL AS no_province",
        "  FROM psgc AS u LEFT JOIN parents AS bp ON bp.level_blank AND bp.psgc_code = u.province_code",
        f"  WHERE u.geographic_level IN ({levels})",
        "),",
        f"regions AS ({_regions_values(spec)}),",
        f"region_codes AS ({_region_codes_values(spec)}),",
        f"aliases AS ({_aliases_values(spec)}),",
        f"overrides AS ({_overrides_values(spec)}),",
        "-- #181 (D-052): every name-rule match lies inside the parent the rules give, recomputed here from the",
        "-- place's region and province, not read from the build: a listed region of its census year, then the",
        "-- province's reviewed alias, else a PSGC parent in that region whose name or old name is the province's;",
        "-- a place directly under its region only among the units with no PSGC province.",
        "named AS (",
        "  SELECT m.source_row_ref, m.census_year, m.region_name, m.province_name, m.psgc_code,",
        joined([_keys("m", "province_name", "")], 9),
        f"  FROM {candidate} AS m WHERE m.match_method IN ({', '.join(lit(m) for m in sorted({t[1] for t in TIERS}))})",
        "),",
        f"named_keys AS (SELECT named.*, {_fold('named.k_exact')} AS k_fold FROM named),",
        "in_scope AS (",
        "  SELECT DISTINCT n.source_row_ref",
        "  FROM named_keys AS n JOIN units AS u ON u.psgc_code = n.psgc_code",
        "  JOIN regions AS r ON r.census_year = n.census_year AND r.region_name = n.region_name AND r.region2 = u.region2",
        "  LEFT JOIN (SELECT DISTINCT census_year, province_name FROM aliases) AS aa",
        "    ON aa.census_year = n.census_year AND aa.province_name = n.province_name",
        "  LEFT JOIN aliases AS a ON a.census_year = n.census_year AND a.province_name = n.province_name AND a.psgc_code = u.province_code",
        "  LEFT JOIN parents AS pa ON pa.psgc_code = u.province_code",
        "  WHERE (n.province_name IS NULL AND u.no_province)",
        "     OR (n.province_name IS NOT NULL AND aa.province_name IS NOT NULL AND a.psgc_code IS NOT NULL)",
        "     OR (n.province_name IS NOT NULL AND aa.province_name IS NULL AND substr(pa.psgc_code, 1, 2) = r.region2",
        "         AND (n.k_exact = pa.k_exact OR n.k_exact = pa.ok_exact OR n.k_fold = pa.k_fold OR n.k_fold = pa.ok_fold))",
        "),",
        "-- Each (census year, sex, age, concept) cell of the country against the sum over the mapped places.",
        "national AS (",
        f"  SELECT census_year, population_concept, sex, age, population FROM {source} WHERE level = 'country'",
        "),",
        "mapped AS (",
        "  SELECT c.census_year, c.population_concept, c.sex, c.age, SUM(c.population) AS population",
        f"  FROM {source} AS c JOIN {candidate} AS m",
        "    ON m.census_year = c.census_year AND m.place_name = c.place_name AND m.parent_name = c.parent_name",
        f"  WHERE c.level = {place}",
        "  GROUP BY c.census_year, c.population_concept, c.sex, c.age",
        "),",
        "totals AS (",
        "  SELECT (SELECT COUNT(*) FROM places) AS source_places, (SELECT COUNT(*) FROM units) AS psgc_units,",
        ("         (SELECT COUNT(*) FROM overrides AS o JOIN places AS p ON p.census_year = o.census_year "
         "AND p.parent_name = o.parent_name AND p.place_name = o.place_name) AS overrides_present,"),
        ("         (SELECT COUNT(*) FROM overrides AS o LEFT JOIN places AS p ON p.census_year = o.census_year "
         "AND p.parent_name = o.parent_name AND p.place_name = o.place_name"),
        "          WHERE p.place_name IS NULL) AS overrides_missing,",
        "         (SELECT COUNT(*) FROM (SELECT DISTINCT census_year, region_name FROM places) AS pr",
        "          LEFT JOIN (SELECT DISTINCT census_year, region_name FROM regions) AS r",
        "            ON r.census_year = pr.census_year AND r.region_name = pr.region_name",
        "          WHERE r.region_name IS NULL) AS regions_missing,",
        "         -- A census province whose places all have no PSGC parent (no alias, no single name match).",
        "         (SELECT COUNT(*) FROM (SELECT DISTINCT m.census_year, m.province_name FROM",
        f"            {candidate} AS m WHERE m.province_name IS NOT NULL",
        "            GROUP BY m.census_year, m.province_name HAVING COUNT(m.parent_match) = 0) AS x) AS provinces_unresolved,",
        "         -- A region or alias code that is not a region or province row of the master quarter.",
        f"         (SELECT COUNT(*) FROM region_codes AS rc LEFT JOIN {psgc} AS p ON p.psgc_code = rc.psgc_code",
        "            AND p.is_master_reference AND p.geographic_level = 'Reg' WHERE p.psgc_code IS NULL)",
        f"         + (SELECT COUNT(*) FROM aliases AS a LEFT JOIN {psgc} AS p ON p.psgc_code = a.psgc_code",
        "            AND p.is_master_reference AND (p.geographic_level = 'Prov' OR (p.level_blank AND p.province_code = p.psgc_code))",
        "            WHERE p.psgc_code IS NULL) AS bad_rule_codes,",
        "         (SELECT COUNT(DISTINCT publication_period) FROM psgc) AS master_periods,",
        "         (SELECT COUNT(*) FROM named) - (SELECT COUNT(*) FROM in_scope) AS name_scope_mismatch,",
        "         -- Per census year: each (year, PSGC unit) pair with no matched place in that year.",
        "         (SELECT COUNT(*) FROM (SELECT DISTINCT census_year FROM places) AS y CROSS JOIN units AS u",
        f"          LEFT JOIN (SELECT DISTINCT census_year, psgc_code FROM {candidate} WHERE match_status = 'matched') AS mm",
        "            ON mm.psgc_code = u.psgc_code AND mm.census_year = y.census_year",
        "          WHERE mm.psgc_code IS NULL) AS units_without_place,",
        *ap4_totals,
        "         (SELECT COUNT(*) FROM national AS n LEFT JOIN mapped AS s ON s.census_year = n.census_year",
        "            AND s.population_concept = n.population_concept AND s.sex = n.sex AND s.age = n.age",
        "          WHERE s.population IS NULL OR s.population <> n.population) AS population_cells_off",
        "),",
        "agg AS (",
        "  SELECT",
        joined(stats, 4),
        f"  FROM {candidate} AS m",
        "  LEFT JOIN units AS u ON u.psgc_code = m.psgc_code",
        "),",
        "stats AS (SELECT * FROM agg CROSS JOIN totals),",
        "checks AS (",
        *union,
        ")",
        "SELECT * FROM checks",
        ") AS results;",
        "",
        "-- A failed build: record it before stopping. The map table is not touched.",
        f"MERGE INTO {CONTROL}.pipeline_runs AS t",
        "USING (",
        "  SELECT :run_id AS run_id, COUNT_IF(status = 'FAIL') AS fails",
        f"  FROM {CONTROL}.data_quality_results",
        f"  WHERE run_id = :run_id AND source_id = {lit(SOURCE_ID)} AND layer = {lit(LAYER)}",
        "    AND checked_at_utc >= session.integration_gate_started_at_utc",
        ") AS s",
        f"ON t.run_id = s.run_id AND t.pipeline_name = {lit(PIPELINE)} AND t.source_id = {lit(SOURCE_ID)}",
        "WHEN MATCHED AND s.fails > 0 THEN UPDATE SET",
        "  status = 'failed', finished_at_utc = current_timestamp(), failure_stage = 'gate',",
        "  error_message = CAST(s.fails AS STRING) || ' FAIL result(s) in data_quality_results';",
        "",
        "SELECT CASE WHEN COUNT(*) > 0",
        f"            THEN raise_error('Integration gate failed for {SOURCE_ID}: ' || CAST(COUNT(*) AS STRING)",
        "                             || ' FAIL result(s) in data_quality_results for run ' || :run_id)",
        "       END",
        f"FROM {CONTROL}.data_quality_results",
        f"WHERE run_id = :run_id AND source_id = {lit(SOURCE_ID)} AND layer = {lit(LAYER)} AND status = 'FAIL'",
        "  AND checked_at_utc >= session.integration_gate_started_at_utc;",
        "",
        "-- Every check passed: publish, then record the run 'succeeded'.",
        f"CREATE OR REPLACE TABLE {published} USING DELTA AS",
        f"SELECT * FROM {candidate};",
        "",
        f"ALTER TABLE {published} OWNER TO `{OWNER_GROUP}`;",
        "",
        f"MERGE INTO {CONTROL}.pipeline_runs AS t",
        "USING (SELECT :run_id AS run_id) AS s",
        f"ON t.run_id = s.run_id AND t.pipeline_name = {lit(PIPELINE)} AND t.source_id = {lit(SOURCE_ID)}",
        "WHEN MATCHED THEN UPDATE SET",
        "  status = 'succeeded', finished_at_utc = current_timestamp(), failure_stage = NULL, error_message = NULL;",
        "",
    ]
    return "\n".join(lines)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv not in (["sql"], ["gate"]):
        sys.stderr.write("usage: python -m src.integration.psa_school_age_population_psgc sql|gate\n")
        return 2
    try:
        spec = load_spec()
    except IngestionError as e:
        sys.stderr.write(f"{e}\n")
        return 2
    sys.stdout.write(build_sql(spec) if argv == ["sql"] else gate_sql(spec))
    return 0


if __name__ == "__main__":
    sys.exit(main())
