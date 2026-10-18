"""Integration for hdx_boundaries: the HDX ADM3 to PSGC crosswalk, its build SQL and its gate SQL.

Two reviewed inputs define it:

- `config/integration/hdx_adm3_psgc.json`: the rules' order, the PSGC levels matched, and every
  reviewed override, with its reason and evidence;
- the published Silver tables `hdx_adm3_clean` (D-040) and `psa_psgc_clean` (D-035).

One map row per HDX ADM3 feature, none dropped, with the D-029 match columns. The rules are
#74's (HB-2), in order: an override; the P-code as a PSGC code, only if the names agree; the
old 9-digit form against PSGC's Correspondence Code (D-030); Sulu's region 19 read as 09; the
name inside the PSGC province; else unmatched or ambiguous. A code is never enough on its own:
COD-AB reuses some PSGC code numbers for different units.

The SQL follows src/silver/sql.py: the build writes a candidate table, the gate checks it and
publishes only if no check FAILs (D-025), and only syntax both Databricks and DuckDB accept is
used (src/ingestion/store.py translates regexp_replace, regexp_like and session variables). No
literal holds a quote, a backslash, ';' or '--'.

    python -m src.integration.hdx_adm3_psgc sql  > etl/04_integration/03_map_hdx_adm3_psgc.sql
    python -m src.integration.hdx_adm3_psgc gate > etl/04_integration/90_validate_hdx_adm3_psgc_map.sql
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
from src.silver.sql import CONTROL, joined, lit  # noqa: E402

SCHEMA = "04-integration"
SILVER = "03-silver"
CONFIG = Path("config") / "integration" / "hdx_adm3_psgc.json"
BUILD_FILE = "03_map_hdx_adm3_psgc.sql"
PIPELINE = "integration_build"
LAYER = "integration"
SAFE_LITERAL = re.compile(r"^[^'\\;]*$")
PCODE = re.compile(r"^PH[0-9]{7}$")
PSGC_CODE = re.compile(r"^[0-9]{10}$")
ISO_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")

# D-029's values, as this map uses them.
MATCH_STATUSES = ("matched", "unmatched", "ambiguous")
MATCH_METHODS = ("code", "code_renamed", "code_region_moved", "correspondence_code", "name_exact", "name_old",
                 "name_normalized", "reviewed_alias", "spatial")
REVIEW_STATUSES = ("rule", "reviewed", "pending")
# #74's name tiers, in order: (name in the reason, PSGC field compared, key, D-029 method).
TIERS = (
    ("exact", "name", "k_exact", "name_exact"),
    ("old name", "old", "k_exact", "name_old"),
    ("folded", "name", "k_fold", "name_normalized"),
    ("folded old name", "old", "k_fold", "name_old"),
    ("brackets dropped", "name", "k_brackets", "name_normalized"),
    ("word City ignored", "name", "k_city", "name_normalized"),
)
# Written as code points so the generated SQL stays ASCII: Windows reads files as cp1252 by default.
ACCENTED = "".join(chr(c) for c in (209, 193, 201, 205, 211, 218, 220, 192, 200, 204, 210, 217, 194, 202, 206, 212, 219))
PLAIN = "NAEIOUUAEIOUAEIOU"
ACCENTED_SQL = " || ".join(f"chr({ord(c)})" for c in ACCENTED)
LINEAGE = (("batch_id", "string"), ("source_sha256", "string"), ("source_row_number", "bigint"),
           ("psgc_batch_id", "string"), ("psgc_source_row_number", "bigint"))
RUN_STAMP = (("run_id", "string"), ("built_at_utc", "timestamp"), ("code_revision", "string"))


def _error(message):
    return IngestionError("config", "invalid_integration_rules", message)


@dataclass
class Override:
    adm3_pcode: str
    source_reference_date: str  # the HDX release it was reviewed for: it applies to that release only
    psgc_code: str          # None: reviewed as unmatched
    match_method: str
    reason: str


@dataclass
class MapSpec:
    map_table: str
    hdx_table: str
    psgc_table: str
    levels: list
    overrides: list
    rules: dict = field(repr=False)

    @property
    def candidate(self):
        return f"{self.map_table}_candidate"

    def columns(self):
        return [
            ("source_id", "string"), ("source_row_ref", "string"), ("adm3_pcode", "string"), ("adm3_name", "string"), ("adm2_pcode", "string"),
            ("adm2_name", "string"), ("adm1_pcode", "string"), ("source_reference_date", "date"),
            ("code_candidate", "string"), ("psgc_version", "string"), ("psgc_code", "string"), ("psgc_name", "string"),
            ("geographic_level", "string"), ("match_status", "string"), ("match_method", "string"),
            ("review_status", "string"), ("reason", "string"),
        ] + list(LINEAGE) + list(RUN_STAMP)


def load_spec(repo_root=REPO_ROOT):
    path = Path(repo_root) / CONFIG
    if not path.is_file():
        raise _error(f"{path} does not exist.")
    return build_spec(json.loads(path.read_text(encoding="utf-8")))


def build_spec(rules):
    levels = list(rules["psgc"]["levels"])
    overrides, seen = [], set()
    for entry in rules.get("overrides", []):
        pcode, code, method = entry.get("adm3_pcode"), entry.get("psgc_code"), entry.get("match_method")
        released = entry.get("source_reference_date")
        if not pcode or not PCODE.match(pcode):
            raise _error(f"override {entry!r}: adm3_pcode must match {PCODE.pattern}.")
        if not released or not ISO_DATE.match(released):
            raise _error(f"override for {pcode}: source_reference_date must be the HDX release date, YYYY-MM-DD.")
        if (pcode, released) in seen:
            raise _error(f"override for {pcode} on {released} is listed twice.")
        seen.add((pcode, released))
        if code is not None and not PSGC_CODE.match(code):
            raise _error(f"override for {pcode}: psgc_code must be ten digits or null.")
        if code is None and method is not None:
            raise _error(f"override for {pcode}: a reviewed unmatched feature has no match_method (null).")
        if code is not None and method not in MATCH_METHODS:
            raise _error(f"override for {pcode}: match_method {method!r} is not one of D-029's {MATCH_METHODS}.")
        if not entry.get("reason") or not entry.get("evidence"):
            raise _error(f"override for {pcode} needs a reason and evidence.")
        overrides.append(Override(pcode, released, code, method, entry["reason"]))
    literals = [*levels, *[v for o in overrides for v in (o.adm3_pcode, o.source_reference_date, o.psgc_code or "",
                                                          o.match_method or "", o.reason)]]
    unsafe = [v for v in literals if not SAFE_LITERAL.match(v) or "--" in v]
    if unsafe:
        raise _error(f"rules may not contain quotes, backslashes, ';' or '--': {unsafe}.")
    return MapSpec(rules["map_table"], rules["source"]["silver_table"], rules["psgc"]["silver_table"], levels,
                   overrides, rules)


# --- Shared SQL pieces -------------------------------------------------------------------

def ref(schema, table):
    return f"edu_access.`{schema}`.{table}"


def _spaces(expr):
    return f"TRIM(regexp_replace(translate({expr}, chr(9) || chr(160), '  '), ' +', ' '))"


def name_keys(expr, prefix=""):
    """#74's name keys, as columns: k_exact (base), k_fold, k_brackets, k_city."""
    upper = _spaces(f"upper({expr})")
    capital = f"regexp_replace({upper}, ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', '')"
    base = f"CASE WHEN {capital} LIKE 'CITY OF %' THEN substr({capital}, 9) || ' CITY' ELSE {capital} END"
    return [f"{base} AS {prefix}k_exact"], base


def _fold(expr):
    return _spaces(f"translate(translate({expr}, {ACCENTED_SQL}, {lit(PLAIN)}), '.-' || chr(39), '   ')")


def _brackets(expr):
    return _spaces(f"regexp_replace({expr}, '[(][^)]*[)]?', ' ')")


def _no_city(expr):
    once = f"regexp_replace(' ' || {expr} || ' ', ' (CITY|OF) ', ' ')"
    return _spaces(f"regexp_replace({once}, ' (CITY|OF) ', ' ')")


def _header(what, command, path):
    return [
        f"-- {what} for hdx_boundaries. Generated from {CONFIG.as_posix()} by src/integration/hdx_adm3_psgc.py:",
        f"--   python -m src.integration.hdx_adm3_psgc {command} > {path}",
        "-- Do not edit by hand; tests/test_integration_hdx.py fails if it differs.",
    ]


def _keys_select(alias, name, prefix):
    """SELECT items giving k_exact; the folded keys are derived from it in the next CTE."""
    return name_keys(f"{alias}.{name}", prefix)[0]


def _derived(alias, prefix):
    k = f"{alias}.{prefix}k_exact"
    return [f"{_fold(k)} AS {prefix}k_fold"]


def _derived2(alias, prefix):
    k = f"{alias}.{prefix}k_fold"
    return [f"{_brackets(k)} AS {prefix}k_brackets"]


def _derived3(alias, prefix):
    k = f"{alias}.{prefix}k_brackets"
    return [f"{_no_city(k)} AS {prefix}k_city"]


def _pair_tier(s, u):
    """The first of #74's tiers at which the HDX name s matches PSGC unit u, as 1..6, or NULL."""
    whens = []
    for i, (_, fld, key, _) in enumerate(TIERS, 1):
        side = f"{u}.{key}" if fld == "name" else f"{u}.o{key}"
        whens.append(f"WHEN {s}.{key} = {side} THEN {i}")
    return "CASE " + " ".join(whens) + " END"


def _tier_method(expr):
    return "CASE " + " ".join(f"WHEN {expr} = {i} THEN {lit(m)}" for i, (_, _, _, m) in enumerate(TIERS, 1)) + " END"


def _tier_name(expr):
    return "CASE " + " ".join(f"WHEN {expr} = {i} THEN {lit(n)}" for i, (n, _, _, _) in enumerate(TIERS, 1)) + " END"


def _overrides_values(spec):
    if not spec.overrides:
        return ("SELECT CAST(NULL AS STRING) AS adm3_pcode, CAST(NULL AS DATE) AS source_reference_date, "
                "CAST(NULL AS STRING) AS psgc_code, CAST(NULL AS STRING) AS match_method, CAST(NULL AS STRING) AS reason "
                "WHERE 1 = 0")
    null = "CAST(NULL AS STRING)"
    rows = ", ".join(f"({lit(o.adm3_pcode)}, DATE {lit(o.source_reference_date)}, {lit(o.psgc_code) if o.psgc_code else null}, "
                     f"{lit(o.match_method) if o.match_method else null}, {lit(o.reason)})" for o in spec.overrides)
    return f"SELECT * FROM (VALUES {rows}) AS v(adm3_pcode, source_reference_date, psgc_code, match_method, reason)"


# --- Build ---------------------------------------------------------------------------------

def build_sql(spec):
    hdx, psgc = ref(SILVER, spec.hdx_table), ref(SILVER, spec.psgc_table)
    candidate = ref(SCHEMA, spec.candidate)
    levels = ", ".join(lit(x) for x in spec.levels)
    columns = [name for name, _ in spec.columns()]
    lines = _header("Integration build", "sql", f"etl/04_integration/{BUILD_FILE}") + [
        "--",
        f"-- Rebuilds {spec.candidate}: one row per HDX ADM3 feature of the published {spec.hdx_table},",
        f"-- matched to the cities and municipalities of the master PSGC quarter in {spec.psgc_table}.",
        "-- No feature is dropped: a feature no rule matches is kept as unmatched or ambiguous. The map table",
        f"-- ({spec.map_table}) is never written here: the gate checks the candidate and publishes it",
        "-- only if no check fails (as D-025 does for Silver). Rules and overrides: the rules file above.",
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
        f"ON t.run_id = s.run_id AND t.pipeline_name = {lit(PIPELINE)} AND t.source_id = 'hdx_boundaries'",
        "WHEN MATCHED THEN UPDATE SET",
        "  status = 'running', started_at_utc = session.integration_built_at_utc, finished_at_utc = NULL,",
        "  failure_stage = NULL, error_message = NULL, code_revision = session.integration_code_revision, job_run_id = s.run_id",
        "WHEN NOT MATCHED THEN INSERT (run_id, pipeline_name, source_id, environment, status, started_at_utc, code_revision, job_run_id)",
        f"  VALUES (s.run_id, {lit(PIPELINE)}, 'hdx_boundaries', session.integration_environment, 'running',",
        "          session.integration_built_at_utc, session.integration_code_revision, s.run_id);",
        "",
        f"CREATE SCHEMA IF NOT EXISTS edu_access.`{SCHEMA}`;",
        f"ALTER SCHEMA edu_access.`{SCHEMA}` OWNER TO `{OWNER_GROUP}`;",
        "",
        f"CREATE OR REPLACE TEMPORARY VIEW hdx_adm3_psgc_matched AS",
        "-- The master PSGC quarter: every row (for provinces), and its cities and municipalities (the candidates).",
        "WITH psgc AS (",
        "  SELECT psgc_code, name, old_names, correspondence_code, geographic_level, publication_period,",
        "         batch_id, source_row_number",
        f"  FROM {psgc} WHERE is_master_reference",
        "),",
        "u0 AS (",
        "  SELECT p.*,",
        joined(_keys_select("p", "name", "") + [f"CASE WHEN p.old_names IS NULL THEN NULL ELSE ({name_keys('p.old_names')[1]}) END AS ok_exact"], 9),
        f"  FROM psgc AS p WHERE p.geographic_level IN ({levels})",
        "),",
        "u1 AS (SELECT u0.*, " + _derived("u0", "")[0] + ", " + _derived("u0", "o")[0] + " FROM u0),",
        "u2 AS (SELECT u1.*, " + _derived2("u1", "")[0] + ", " + _derived2("u1", "o")[0] + " FROM u1),",
        "units AS (SELECT u2.*, " + _derived3("u2", "")[0] + ", " + _derived3("u2", "o")[0] + " FROM u2),",
        "-- HDX features: the P-code's digits padded to ten (code10), its old 9-digit form (old9), the province's.",
        "s0 AS (",
        "  SELECT h.adm3_pcode, h.adm3_name, h.adm2_pcode, h.adm2_name, h.adm1_pcode, h.valid_on,",
        "         h.batch_id, h.source_sha256, h.source_row_number,",
        "         rpad(substr(h.adm3_pcode, 3), 10, '0') AS code10,",
        "         rpad(substr(h.adm2_pcode, 3), 10, '0') AS prov10,",
        joined(_keys_select("h", "adm3_name", ""), 9),
        f"  FROM {hdx} AS h",
        "),",
        "s1 AS (SELECT s0.*, " + _derived("s0", "")[0] + ",",
        "              substr(code10, 1, 2) || substr(code10, 4, 2) || substr(code10, 6, 2) || substr(code10, 8, 3) AS old9,",
        "              substr(prov10, 1, 2) || substr(prov10, 4, 2) || substr(prov10, 6, 2) || substr(prov10, 8, 3) AS prov_old9",
        "       FROM s0),",
        "s2 AS (SELECT s1.*, " + _derived2("s1", "")[0] + " FROM s1),",
        "s AS (SELECT s2.*, " + _derived3("s2", "")[0] + " FROM s2),",
        "-- Code rules, in order (1 code, 2 Correspondence Code, 3 Sulu), each with the name tier at which",
        "-- the names agree (NULL: they do not).",
        "by_code AS (",
        f"  SELECT s.adm3_pcode, s.valid_on, 1 AS rule, u.psgc_code, {_pair_tier('s', 'u')} AS tier",
        "  FROM s JOIN units AS u ON u.psgc_code = s.code10",
        f"  UNION ALL SELECT s.adm3_pcode, s.valid_on, 2, u.psgc_code, {_pair_tier('s', 'u')}",
        "  FROM s JOIN units AS u ON substr(s.code10, 3, 1) = '0' AND u.correspondence_code = s.old9",
        f"  UNION ALL SELECT s.adm3_pcode, s.valid_on, 3, u.psgc_code, {_pair_tier('s', 'u')}",
        "  FROM s JOIN units AS u ON s.code10 LIKE '19%' AND u.psgc_code = '09' || substr(s.code10, 3)",
        "),",
        "-- The first code rule whose names agree, and how many units it names: more than one (two units",
        "-- sharing a Correspondence Code) is not one-to-one (D-030), so the feature stays ambiguous.",
        "code_hits AS (",
        "  SELECT adm3_pcode, valid_on, rule, COUNT(DISTINCT psgc_code) AS hits, MIN(psgc_code) AS psgc_code",
        "  FROM by_code WHERE tier IS NOT NULL GROUP BY adm3_pcode, valid_on, rule",
        "),",
        "code_agreed AS (",
        "  SELECT adm3_pcode, valid_on, MIN_BY(psgc_code, rule) AS psgc_code, MIN(rule) AS rule, MIN_BY(hits, rule) AS hits",
        "  FROM code_hits GROUP BY adm3_pcode, valid_on",
        "),",
        "code_any AS (",
        "  SELECT adm3_pcode, valid_on, MIN_BY(psgc_code, rule) AS psgc_code FROM by_code GROUP BY adm3_pcode, valid_on",
        "),",
        "-- The PSGC province for adm2_pcode: by code, else by Correspondence Code. Its first five digits",
        "-- scope the name search. A feature whose province is not found, or has no city or municipality,",
        "-- gets no name match: names are matched only inside a matched parent (D-029); a reviewed",
        "-- override is the way to match it.",
        "province AS (",
        "  SELECT s.adm3_pcode, s.valid_on,",
        "         substr(COALESCE(MIN(p1.psgc_code), MIN(p2.psgc_code)), 1, 5) AS prov5",
        "  FROM s",
        "  LEFT JOIN psgc AS p1 ON p1.psgc_code = s.prov10",
        "  LEFT JOIN psgc AS p2 ON substr(s.prov10, 3, 1) = '0' AND p2.correspondence_code = s.prov_old9",
        "  GROUP BY s.adm3_pcode, s.valid_on",
        "),",
        "scope AS (",
        "  SELECT pr.adm3_pcode, pr.valid_on, pr.prov5, pc.n IS NOT NULL AS has_units",
        "  FROM province AS pr",
        "  LEFT JOIN (SELECT substr(psgc_code, 1, 5) AS prov5, COUNT(*) AS n FROM units GROUP BY 1) AS pc ON pc.prov5 = pr.prov5",
        "),",
        "by_name AS (",
        f"  SELECT s.adm3_pcode, s.valid_on, u.psgc_code, {_pair_tier('s', 'u')} AS tier",
        "  FROM s JOIN scope AS sc ON sc.adm3_pcode = s.adm3_pcode AND sc.valid_on = s.valid_on",
        "  JOIN units AS u ON sc.has_units AND substr(u.psgc_code, 1, 5) = sc.prov5",
        "),",
        "best AS (",
        "  SELECT adm3_pcode, valid_on, MIN(tier) AS tier FROM by_name WHERE tier IS NOT NULL GROUP BY adm3_pcode, valid_on",
        "),",
        "name_hit AS (",
        "  SELECT b.adm3_pcode, b.valid_on, b.tier, COUNT(*) AS hits, MIN(n.psgc_code) AS psgc_code",
        "  FROM best AS b JOIN by_name AS n ON n.adm3_pcode = b.adm3_pcode AND n.valid_on = b.valid_on AND n.tier = b.tier",
        "  GROUP BY b.adm3_pcode, b.valid_on, b.tier",
        "),",
        f"overrides AS ({_overrides_values(spec)}),",
        "-- One decision per feature, in the rules' order.",
        "decided AS (",
        "  SELECT s.*,",
        "    CASE WHEN o.adm3_pcode IS NOT NULL THEN o.psgc_code",
        "         WHEN ca.hits = 1 THEN ca.psgc_code",
        "         WHEN ca.hits > 1 THEN NULL",
        "         WHEN nh.hits = 1 THEN nh.psgc_code",
        "         ELSE NULL END AS psgc_code,",
        "    CASE WHEN o.adm3_pcode IS NOT NULL THEN CASE WHEN o.psgc_code IS NULL THEN 'unmatched' ELSE 'matched' END",
        "         WHEN ca.hits = 1 THEN 'matched'",
        "         WHEN ca.hits > 1 THEN 'ambiguous'",
        "         WHEN nh.hits = 1 THEN 'matched'",
        "         WHEN nh.hits > 1 OR cy.psgc_code IS NOT NULL THEN 'ambiguous'",
        "         ELSE 'unmatched' END AS match_status,",
        "    CASE WHEN o.adm3_pcode IS NOT NULL THEN o.match_method",
        "         WHEN ca.hits > 1 THEN NULL",
        "         WHEN ca.rule = 1 THEN 'code' WHEN ca.rule = 2 THEN 'correspondence_code' WHEN ca.rule = 3 THEN 'code_region_moved'",
        f"         WHEN nh.hits = 1 THEN {_tier_method('nh.tier')}",
        "         END AS match_method,",
        "    CASE WHEN o.adm3_pcode IS NOT NULL THEN 'reviewed'",
        "         WHEN ca.hits = 1 OR (ca.hits IS NULL AND nh.hits = 1) THEN 'rule'",
        "         ELSE 'pending' END AS review_status,",
        "    CASE WHEN o.adm3_pcode IS NOT NULL THEN o.reason",
        "         WHEN ca.hits = 1 THEN NULL",
        ("         WHEN ca.hits > 1 THEN CAST(ca.hits AS STRING) || ' units share this code under the ' || "
         "CASE ca.rule WHEN 1 THEN 'code' WHEN 2 THEN 'Correspondence Code' ELSE 'Sulu' END || "
         "' rule: not one-to-one (D-030), review'"),
        f"         WHEN nh.hits = 1 THEN 'name in province, ' || {_tier_name('nh.tier')}",
        "              || CASE WHEN cy.psgc_code IS NOT NULL THEN ', the code names another unit' ELSE '' END",
        f"         WHEN nh.hits > 1 THEN CAST(nh.hits AS STRING) || ' units match at tier ' || {_tier_name('nh.tier')}",
        "         WHEN cy.psgc_code IS NOT NULL THEN 'the code points to ' || cy.psgc_code || ' but the names differ: review, then confirm by override'",
        "         WHEN NOT COALESCE(sc.has_units, FALSE) THEN 'no PSGC province found for adm2_pcode, so no name match was tried'",
        "         ELSE 'no code or name match' END AS reason",
        "  FROM s",
        "  LEFT JOIN overrides AS o ON o.adm3_pcode = s.adm3_pcode AND o.source_reference_date = s.valid_on",
        "  LEFT JOIN code_agreed AS ca ON ca.adm3_pcode = s.adm3_pcode AND ca.valid_on = s.valid_on",
        "  LEFT JOIN code_any AS cy ON cy.adm3_pcode = s.adm3_pcode AND cy.valid_on = s.valid_on",
        "  LEFT JOIN name_hit AS nh ON nh.adm3_pcode = s.adm3_pcode AND nh.valid_on = s.valid_on",
        "  LEFT JOIN scope AS sc ON sc.adm3_pcode = s.adm3_pcode AND sc.valid_on = s.valid_on",
        ")",
        "SELECT",
        joined([
            "'hdx_boundaries' AS source_id", "d.adm3_pcode || '/' || CAST(d.valid_on AS STRING) AS source_row_ref", "d.adm3_pcode", "d.adm3_name", "d.adm2_pcode", "d.adm2_name", "d.adm1_pcode",
            "d.valid_on AS source_reference_date", "d.code10 AS code_candidate",
            "(SELECT MIN(publication_period) FROM psgc) AS psgc_version", "d.psgc_code", "p.name AS psgc_name",
            "'city_mun' AS geographic_level",
            "d.match_status", "d.match_method", "d.review_status", "d.reason",
            "d.batch_id", "d.source_sha256", "d.source_row_number",
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
        "FROM hdx_adm3_psgc_matched;",
        "",
        (f"COMMENT ON TABLE {candidate} IS 'Unpublished build for the Integration gate, which may have failed. "
         f"Do not read: use {spec.map_table}.';"),
        f"ALTER TABLE {candidate} OWNER TO `{OWNER_GROUP}`;",
        "",
    ]
    return "\n".join(lines)


# --- Gate ----------------------------------------------------------------------------------

def gate_checks(spec):
    """[(check_name, status)] in the order the gate writes them."""
    fails = ["inputs_present", "rows_reconcile", "one_row_per_feature", "psgc_code_taken_once", "matched_has_psgc_unit",
             "unmatched_has_no_psgc", "status_valid", "method_valid", "review_status_valid", "status_combination_valid",
             "code_is_the_pcode",
             "correspondence_is_the_old_code", "region_moved_is_sulu", "overrides_applied", "one_psgc_version",
             "lineage_complete", "rows_built_by_this_run"]
    warns = ["review_pending", "unmatched", "ambiguous", "override_feature_missing", "psgc_units_without_feature"]
    records = [f"method_{m}" for m in MATCH_METHODS] + ["match_rate_percent"]
    return [(n, "FAIL") for n in fails] + [(n, "WARN") for n in warns] + [(n, "record") for n in records]


def gate_sql(spec):
    hdx, psgc = ref(SILVER, spec.hdx_table), ref(SILVER, spec.psgc_table)
    candidate, published = ref(SCHEMA, spec.candidate), ref(SCHEMA, spec.map_table)
    table = f"edu_access.{SCHEMA}.{spec.candidate}"
    levels = ", ".join(lit(x) for x in spec.levels)
    o_count = len(spec.overrides)
    overrides = _overrides_values(spec)

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

    stats = [
        "COUNT(*) AS map_rows",
        "COUNT(DISTINCT m.source_row_ref) AS map_features",
        "COUNT_IF(m.match_status = 'matched') AS matched_rows",
        ("COUNT(DISTINCT CASE WHEN m.match_status = 'matched' THEN m.psgc_code || '/' || CAST(m.source_reference_date AS STRING) "
         "END) AS matched_codes"),
        "COUNT_IF(m.match_status = 'matched' AND (m.psgc_code IS NULL OR u.psgc_code IS NULL)) AS matched_without_unit",
        "COUNT_IF(m.match_status <> 'matched' AND m.psgc_code IS NOT NULL) AS unmatched_with_code",
        f"COUNT_IF(m.match_status IS NULL OR m.match_status NOT IN ({', '.join(lit(x) for x in MATCH_STATUSES)})) AS bad_status",
        (f"COUNT_IF((m.match_status = 'matched' AND (m.match_method IS NULL OR m.match_method NOT IN "
         f"({', '.join(lit(x) for x in MATCH_METHODS)}))) OR (m.match_status = 'ambiguous' AND m.match_method IS NOT NULL)) AS bad_method"),
        f"COUNT_IF(m.review_status IS NULL OR m.review_status NOT IN ({', '.join(lit(x) for x in REVIEW_STATUSES)})) AS bad_review",
        # D-052: only rule-based or reviewed rows are matched, and only matched rows carry a method and a code.
        ("COUNT_IF(NOT COALESCE("
         "(m.match_status = 'matched' AND m.review_status IN ('rule', 'reviewed') AND m.match_method IS NOT NULL "
         "AND m.psgc_code IS NOT NULL) OR "
         "(m.match_status = 'ambiguous' AND m.review_status = 'pending' AND m.match_method IS NULL AND m.psgc_code IS NULL) OR "
         "(m.match_status = 'unmatched' AND m.review_status IN ('pending', 'reviewed') AND m.match_method IS NULL "
         "AND m.psgc_code IS NULL), FALSE)) AS bad_combination"),
        "COUNT_IF(m.match_method = 'code' AND m.review_status = 'rule' AND m.psgc_code <> m.code_candidate) AS code_mismatch",
        ("COUNT_IF(m.match_method = 'correspondence_code' AND m.review_status = 'rule' AND (u.correspondence_code IS NULL OR "
         "u.correspondence_code <> substr(m.code_candidate, 1, 2) || substr(m.code_candidate, 4, 2) || "
         "substr(m.code_candidate, 6, 2) || substr(m.code_candidate, 8, 3))) AS correspondence_mismatch"),
        ("COUNT_IF(m.match_method = 'code_region_moved' AND m.review_status = 'rule' AND "
         "(m.code_candidate NOT LIKE '19%' OR m.psgc_code <> '09' || substr(m.code_candidate, 3))) AS region_mismatch"),
        "COUNT_IF(m.review_status = 'reviewed') AS overrides_used",
        ("COUNT_IF(m.source_row_ref IS NULL OR m.batch_id IS NULL OR m.source_sha256 IS NULL OR m.source_row_number IS NULL OR m.run_id IS NULL "
         "OR m.built_at_utc IS NULL OR m.code_revision IS NULL OR (m.psgc_code IS NOT NULL AND m.psgc_batch_id IS NULL)) AS missing_lineage"),
        "COUNT_IF(m.run_id IS NULL OR m.run_id <> :run_id) AS other_run_rows",
        "COUNT_IF(m.review_status = 'pending') AS pending_rows",
        "COUNT_IF(m.match_status = 'unmatched') AS unmatched_rows",
        "COUNT_IF(m.match_status = 'ambiguous') AS ambiguous_rows",
    ] + [f"COUNT_IF(m.match_status = 'matched' AND m.match_method = {lit(x)}) AS method_{x}" for x in MATCH_METHODS]

    checks = [
        check("inputs_present", "CASE WHEN hdx_rows > 0 AND psgc_units > 0 THEN 'PASS' ELSE 'FAIL' END",
              "'HDX rows and PSGC units'", "CAST(hdx_rows AS STRING) || ' / ' || CAST(psgc_units AS STRING)"),
        equal("rows_reconcile", "hdx_rows", "map_rows"),
        equal("one_row_per_feature", "map_rows", "map_features"),
        equal("psgc_code_taken_once", "matched_rows", "matched_codes"),
        zero("matched_has_psgc_unit", "matched_without_unit"),
        zero("unmatched_has_no_psgc", "unmatched_with_code"),
        zero("status_valid", "bad_status"),
        zero("method_valid", "bad_method"),
        zero("review_status_valid", "bad_review"),
        zero("status_combination_valid", "bad_combination"),
        zero("code_is_the_pcode", "code_mismatch"),
        zero("correspondence_is_the_old_code", "correspondence_mismatch"),
        zero("region_moved_is_sulu", "region_mismatch"),
        equal("overrides_applied", "overrides_present", "overrides_used"),
        equal("one_psgc_version", "1", "master_periods"),
        zero("lineage_complete", "missing_lineage"),
        zero("rows_built_by_this_run", "other_run_rows"),
        warn("review_pending", "pending_rows"),
        warn("unmatched", "unmatched_rows"),
        warn("ambiguous", "ambiguous_rows"),
        warn("override_feature_missing", "overrides_missing"),
        warn("psgc_units_without_feature", "units_without_feature"),
        *[record(f"method_{x}", f"method_{x}") for x in MATCH_METHODS],
        record("match_rate_percent", "CASE WHEN map_rows = 0 THEN 0 ELSE ROUND(100.0 * matched_rows / map_rows, 2) END"),
    ]
    assert [c for c, _ in gate_checks(spec)] == [re.search(r"SELECT '([a-z0-9_]+)' AS check_name", c).group(1) for c in checks]
    union = ["  " + checks[0]] + ["  UNION ALL " + c for c in checks[1:]]

    lines = _header("Integration gate", "gate", f"etl/04_integration/90_validate_{spec.map_table}.sql") + [
        "--",
        f"-- The job task after the build. It checks {spec.candidate}, one row per check in",
        "-- data_quality_results (layer 'integration'). On any FAIL it records the run 'failed' and stops",
        f"-- before publishing, so {spec.map_table} keeps the last map that passed. Otherwise it copies",
        "-- the candidate to the map table and records the run 'succeeded'. WARN (pending reviews, unmatched,",
        "-- ambiguous, an override whose P-code is not in the HDX release it was reviewed for, PSGC cities and municipalities",
        "-- no feature matched, counted per HDX release) is recorded and the map is",
        "-- published. Results hold counts, never row values.",
        "",
        "DECLARE OR REPLACE VARIABLE integration_gate_started_at_utc TIMESTAMP;",
        "SET VARIABLE integration_gate_started_at_utc = current_timestamp();",
        "",
        f"INSERT INTO {CONTROL}.data_quality_results",
        "  (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)",
        f"SELECT :run_id, CAST(NULL AS STRING), 'hdx_boundaries', {lit(LAYER)}, {lit(table)}, check_name, status, expected, actual,",
        "       current_timestamp(), :code_revision",
        "FROM (",
        f"WITH hdx AS (SELECT adm3_pcode, valid_on FROM {hdx}),",
        f"units AS (SELECT psgc_code, correspondence_code FROM {psgc} WHERE is_master_reference AND geographic_level IN ({levels})),",
        f"overrides AS ({overrides}),",
        "totals AS (",
        "  SELECT (SELECT COUNT(*) FROM hdx) AS hdx_rows, (SELECT COUNT(*) FROM units) AS psgc_units,",
        ("         (SELECT COUNT(*) FROM overrides AS o JOIN hdx AS h ON h.adm3_pcode = o.adm3_pcode "
         "AND h.valid_on = o.source_reference_date) AS overrides_present,"),
        ("         (SELECT COUNT(*) FROM overrides AS o LEFT JOIN hdx AS h ON h.adm3_pcode = o.adm3_pcode "
         "AND h.valid_on = o.source_reference_date"),
        "          WHERE h.adm3_pcode IS NULL) AS overrides_missing,",
        f"         (SELECT COUNT(DISTINCT publication_period) FROM {psgc} WHERE is_master_reference) AS master_periods,",
        "         -- Per HDX release: each (release, PSGC unit) pair with no matched feature in that release.",
        "         (SELECT COUNT(*) FROM (SELECT DISTINCT valid_on FROM hdx) AS r CROSS JOIN units AS u",
        f"          LEFT JOIN (SELECT DISTINCT source_reference_date, psgc_code FROM {candidate} WHERE match_status = 'matched') AS mm",
        "            ON mm.psgc_code = u.psgc_code AND mm.source_reference_date = r.valid_on",
        "          WHERE mm.psgc_code IS NULL) AS units_without_feature",
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
        f"  WHERE run_id = :run_id AND source_id = 'hdx_boundaries' AND layer = {lit(LAYER)}",
        "    AND checked_at_utc >= session.integration_gate_started_at_utc",
        ") AS s",
        f"ON t.run_id = s.run_id AND t.pipeline_name = {lit(PIPELINE)} AND t.source_id = 'hdx_boundaries'",
        "WHEN MATCHED AND s.fails > 0 THEN UPDATE SET",
        "  status = 'failed', finished_at_utc = current_timestamp(), failure_stage = 'gate',",
        "  error_message = CAST(s.fails AS STRING) || ' FAIL result(s) in data_quality_results';",
        "",
        "SELECT CASE WHEN COUNT(*) > 0",
        "            THEN raise_error('Integration gate failed for hdx_boundaries: ' || CAST(COUNT(*) AS STRING)",
        "                             || ' FAIL result(s) in data_quality_results for run ' || :run_id)",
        "       END",
        f"FROM {CONTROL}.data_quality_results",
        f"WHERE run_id = :run_id AND source_id = 'hdx_boundaries' AND layer = {lit(LAYER)} AND status = 'FAIL'",
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
        f"ON t.run_id = s.run_id AND t.pipeline_name = {lit(PIPELINE)} AND t.source_id = 'hdx_boundaries'",
        "WHEN MATCHED THEN UPDATE SET",
        "  status = 'succeeded', finished_at_utc = current_timestamp(), failure_stage = NULL, error_message = NULL;",
        "",
    ]
    return "\n".join(lines)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv not in (["sql"], ["gate"]):
        sys.stderr.write("usage: python -m src.integration.hdx_adm3_psgc sql|gate\n")
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
