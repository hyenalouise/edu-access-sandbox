"""Generate the DepEd school-to-PSGC Integration map and validation gate (#91, D-049).

The build reads only published Silver tables.  It matches distinct DepEd place-name tuples once,
then joins those decisions back to schools; this avoids comparing every school with all 42,000 PSGC
barangays and keeps the job suitable for a small SQL warehouse.  The build writes a candidate and
the gate publishes it only when every structural check passes.

    python -m src.integration.deped_school_psgc sql  > etl/04_integration/01_map_deped_school_psgc.sql
    python -m src.integration.deped_school_psgc gate > etl/04_integration/90_validate_deped_school_psgc_map.sql
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
from src.silver.sql import CONTROL, lit  # noqa: E402

SCHEMA = "04-integration"
SILVER = "03-silver"
CONFIG = Path("config/mappings/integration/deped_school_psgc.json")
BUILD_FILE = "01_map_deped_school_psgc.sql"
GATE_FILE = "90_validate_deped_school_psgc_map.sql"
PIPELINE = "integration_build"
SOURCE = "deped_enrollment"
SAFE = re.compile(r"^[^\\;]*$")
CODE = re.compile(r"^[0-9]{10}$")
LEVELS = ("city_mun", "bgy")
STATUSES = ("matched", "unmatched", "ambiguous", "excluded")
METHODS = ("code", "code_name_differs", "code_region_moved", "rollup", "name_exact", "name_old",
           "name_normalized", "reviewed_alias")
ACCENTED = "".join(chr(c) for c in (209, 193, 201, 205, 211, 218, 220, 192, 200, 204, 210, 217, 194, 202, 206, 212, 219))
PLAIN = "NAEIOUUAEIOUAEIOU"
ACCENTED_SQL = " || ".join(f"chr({ord(c)})" for c in ACCENTED)


def _error(message):
    return IngestionError("config", "invalid_integration_rules", message)


@dataclass
class Alias:
    deped_name: str
    psgc_code: str
    reason: str


@dataclass
class Override:
    level: str
    province: str
    municipality: str
    barangay: str
    use: str
    reason: str
    reviewer: str


@dataclass
class MapSpec:
    map_table: str
    enrollment_table: str
    crosswalk_table: str
    psgc_table: str
    aliases: list[Alias]
    overrides: list[Override]
    rules: dict = field(repr=False)

    @property
    def candidate(self):
        return f"{self.map_table}_candidate"


def load_spec(repo_root=REPO_ROOT):
    path = Path(repo_root) / CONFIG
    if not path.is_file():
        raise _error(f"{path} does not exist.")
    return build_spec(json.loads(path.read_text(encoding="utf-8")))


def build_spec(rules):
    inputs = rules.get("inputs", {})
    aliases, alias_names = [], set()
    for item in rules.get("locality_aliases", []):
        name, code = item.get("deped_name"), item.get("psgc_code")
        if not name or name in alias_names:
            raise _error(f"locality alias {name!r} is blank or repeated.")
        if not code or not CODE.match(code):
            raise _error(f"locality alias {name!r} needs a ten-digit PSGC code.")
        if not item.get("reason") or not item.get("evidence"):
            raise _error(f"locality alias {name!r} needs reason and evidence.")
        alias_names.add(name)
        aliases.append(Alias(name, code, item["reason"]))
    overrides, override_keys = [], set()
    for item in rules.get("overrides", []):
        key = (item.get("level"), item.get("deped_province"), item.get("deped_municipality"), item.get("deped_barangay"))
        if key in override_keys or key[0] not in LEVELS:
            raise _error(f"override {key!r} is repeated or has an invalid level.")
        if item.get("use") not in ("code", "name"):
            raise _error(f"override {key!r} must use code or name.")
        if not item.get("reason") or not item.get("evidence") or not item.get("reviewer"):
            raise _error(f"override {key!r} needs reason, evidence, and reviewer.")
        override_keys.add(key)
        overrides.append(Override(*key, item["use"], item["reason"], item["reviewer"]))
    literals = [a.deped_name for a in aliases] + [a.reason for a in aliases]
    literals += [v for o in overrides for v in (o.level, o.province, o.municipality, o.barangay, o.use, o.reason, o.reviewer)]
    if any(not SAFE.match(v) or "--" in v for v in literals):
        raise _error("aliases and overrides may not contain backslashes, semicolons, or SQL comments.")
    required = ("enrollment", "crosswalk", "psgc")
    if not rules.get("map_table") or any(not inputs.get(k) for k in required):
        raise _error("map_table and all three inputs are required.")
    return MapSpec(rules["map_table"], inputs["enrollment"], inputs["crosswalk"], inputs["psgc"], aliases, overrides, rules)


def ref(schema, table):
    return f"edu_access.`{schema}`.{table}"


def _spaces(expr):
    return f"TRIM(regexp_replace(translate({expr}, chr(9) || chr(160), '  '), ' +', ' '))"


def _base(expr):
    upper = _spaces(f"upper({expr})")
    dropped = f"regexp_replace({upper}, ' ?[(](CAPITAL|NOT A PROVINCE)[)]$', '')"
    return f"CASE WHEN {dropped} LIKE 'CITY OF %' THEN substr({dropped}, 9) || ' CITY' ELSE {dropped} END"


def _fold(expr):
    return _spaces(f"translate(translate({expr}, {ACCENTED_SQL}, {lit(PLAIN)}), '.-' || chr(39), '   ')")


def _brackets(expr):
    return _spaces(f"regexp_replace({expr}, '[(][^)]*[)]?', ' ')")


def _no_city(expr):
    once = f"regexp_replace(' ' || {expr} || ' ', ' (CITY|OF) ', ' ')"
    return _spaces(f"regexp_replace({once}, ' (CITY|OF) ', ' ')")


def _key_ctes(source, name_expr, prefix=""):
    return (
        f"{source}0 AS (SELECT x.*, {_base(name_expr)} AS {prefix}k_exact FROM {source}_input AS x),\n"
        f"{source}1 AS (SELECT x.*, {_fold(f'x.{prefix}k_exact')} AS {prefix}k_fold FROM {source}0 AS x),\n"
        f"{source}2 AS (SELECT x.*, {_brackets(f'x.{prefix}k_fold')} AS {prefix}k_brackets FROM {source}1 AS x),\n"
        f"{source}3 AS (SELECT x.*, {_no_city(f'x.{prefix}k_brackets')} AS {prefix}k_city FROM {source}2 AS x)"
    )


def _tier(src="s", unit="u", old=False, truncated=False):
    p = "o" if old else ""
    cases = [
        f"WHEN {src}.k_exact = {unit}.{p}k_exact THEN 1",
        f"WHEN {src}.k_fold = {unit}.{p}k_fold THEN 3" if not old else f"WHEN {src}.k_fold = {unit}.{p}k_fold THEN 4",
        f"WHEN {src}.k_brackets = {unit}.{p}k_brackets THEN 5",
        f"WHEN {src}.k_city = {unit}.{p}k_city THEN 6",
    ]
    if old:
        cases[0] = f"WHEN {src}.k_exact = {unit}.ok_exact THEN 2"
        cases[1] = f"WHEN {src}.k_fold = {unit}.ok_fold THEN 4"
        cases = cases[:2]
    if truncated:
        cases.append(f"WHEN {src}.barangay_possibly_truncated AND {unit}.k_fold LIKE {src}.k_fold || '%' THEN 7")
    return "CASE " + " ".join(cases) + " END"


def _method(tier):
    return (f"CASE WHEN {tier} IN (1, 8, 9) THEN 'name_exact' WHEN {tier} IN (2, 4) THEN 'name_old' "
            f"WHEN {tier} IN (3, 5, 6, 7) THEN 'name_normalized' WHEN {tier} = 10 THEN 'reviewed_alias' END")


def _values(rows, columns):
    if not rows:
        casts = ", ".join(f"CAST(NULL AS STRING) AS {c}" for c in columns)
        return f"SELECT {casts} WHERE FALSE"
    quote = lambda value: "'" + value.replace("'", "''") + "'"
    body = ", ".join("(" + ", ".join(quote(v) for v in row) + ")" for row in rows)
    return f"SELECT * FROM (VALUES {body}) AS v({', '.join(columns)})"


def _header(what, command, path):
    return [
        f"-- {what} for {SOURCE}. Generated from {CONFIG.as_posix()} by src/integration/deped_school_psgc.py:",
        f"--   python -m src.integration.deped_school_psgc {command} > {path}",
        "-- Do not edit by hand; tests/test_integration_deped_school_psgc.py fails if it differs.",
    ]


def build_sql(spec):
    aliases = _values([(a.deped_name, a.psgc_code, a.reason) for a in spec.aliases], ("deped_name", "psgc_code", "reason"))
    overrides = _values([(o.level, o.province, o.municipality, o.barangay, o.use, o.reason, o.reviewer)
                         for o in spec.overrides],
                        ("geographic_level", "province", "municipality", "barangay", "use_side", "reason", "reviewer"))
    enr, cross, psgc = ref(SILVER, spec.enrollment_table), ref(SILVER, spec.crosswalk_table), ref(SILVER, spec.psgc_table)
    candidate = ref(SCHEMA, spec.candidate)
    keys_p = _key_ctes("p", "x.name").replace("FROM p_input", "FROM psgc_input")
    # Old-name keys are separate because a NULL old name must remain NULL through every key.
    sql = f"""
DECLARE OR REPLACE VARIABLE integration_run_id STRING;
SET VARIABLE integration_run_id = :run_id;
DECLARE OR REPLACE VARIABLE integration_code_revision STRING;
SET VARIABLE integration_code_revision = COALESCE(NULLIF(:code_revision, ''), 'UNSET');
DECLARE OR REPLACE VARIABLE integration_environment STRING;
SET VARIABLE integration_environment = COALESCE(NULLIF(:environment, ''), 'UNSET');
DECLARE OR REPLACE VARIABLE integration_built_at_utc TIMESTAMP;
SET VARIABLE integration_built_at_utc = current_timestamp();

MERGE INTO {CONTROL}.pipeline_runs AS t
USING (SELECT session.integration_run_id AS run_id) AS s
ON t.run_id = s.run_id AND t.pipeline_name = '{PIPELINE}' AND t.source_id = '{SOURCE}'
WHEN MATCHED THEN UPDATE SET status = 'running', started_at_utc = session.integration_built_at_utc,
  finished_at_utc = NULL, failure_stage = NULL, error_message = NULL,
  code_revision = session.integration_code_revision, job_run_id = s.run_id
WHEN NOT MATCHED THEN INSERT (run_id, pipeline_name, source_id, environment, status, started_at_utc, code_revision, job_run_id)
  VALUES (s.run_id, '{PIPELINE}', '{SOURCE}', session.integration_environment, 'running',
          session.integration_built_at_utc, session.integration_code_revision, s.run_id);

CREATE SCHEMA IF NOT EXISTS edu_access.`{SCHEMA}`;
ALTER SCHEMA edu_access.`{SCHEMA}` OWNER TO `{OWNER_GROUP}`;

CREATE OR REPLACE TEMPORARY VIEW deped_school_psgc_matched AS
WITH
psgc_input AS (
  SELECT psgc_code, name, old_names, geographic_level, region_code, province_code,
         city_municipality_code, publication_period, batch_id, source_row_number
  FROM {psgc} WHERE is_master_reference
),
{keys_p},
p4 AS (
  SELECT x.*,
    CASE WHEN x.old_names IS NULL THEN NULL ELSE {_base('x.old_names')} END AS ok_exact
  FROM p3 AS x
),
p5 AS (SELECT x.*, CASE WHEN x.ok_exact IS NULL THEN NULL ELSE {_fold('x.ok_exact')} END AS ok_fold FROM p4 AS x),
units AS (SELECT * FROM p5),
source_input AS (
  SELECT DISTINCT province, municipality, COALESCE(barangay, '') AS barangay, barangay_possibly_truncated
  FROM {enr} WHERE NOT is_overseas
),
source0 AS (SELECT x.*, {_base('x.province')} AS prov_exact, {_base('x.municipality')} AS k_exact,
                  {_base('x.barangay')} AS b_exact FROM source_input AS x),
source1 AS (SELECT x.*, {_fold('x.prov_exact')} AS prov_fold, {_fold('x.k_exact')} AS k_fold,
                  {_fold('x.b_exact')} AS b_fold FROM source0 AS x),
source2 AS (SELECT x.*, {_brackets('x.k_fold')} AS k_brackets, {_brackets('x.b_fold')} AS b_brackets FROM source1 AS x),
source3 AS (SELECT x.*, {_no_city('x.k_brackets')} AS k_city, {_no_city('x.b_brackets')} AS b_city FROM source2 AS x),
aliases AS ({aliases}),
overrides AS ({overrides}),
province_pairs AS (
  SELECT s.province, s.municipality, s.barangay, s.barangay_possibly_truncated, u.psgc_code,
    CASE WHEN s.prov_exact = u.k_exact THEN 1 WHEN s.prov_exact = u.ok_exact THEN 2
         WHEN s.prov_fold = u.k_fold THEN 3 WHEN s.prov_fold = u.ok_fold THEN 4 END AS tier
  FROM source3 AS s JOIN units AS u ON (u.geographic_level = 'Prov' OR u.psgc_code = '0990100000')
    AND (s.prov_exact = u.k_exact OR s.prov_exact = u.ok_exact OR s.prov_fold = u.k_fold OR s.prov_fold = u.ok_fold)
  UNION ALL
  SELECT s.province, s.municipality, s.barangay, s.barangay_possibly_truncated, u.psgc_code, 1
  FROM source3 AS s JOIN units AS u ON upper(s.province) = 'MAGUINDANAO'
    AND u.geographic_level = 'Prov' AND u.name IN ('Maguindanao del Norte', 'Maguindanao del Sur')
),
province_best AS (
  SELECT province, municipality, barangay, barangay_possibly_truncated, MIN(tier) AS tier
  FROM province_pairs WHERE tier IS NOT NULL GROUP BY 1,2,3,4
),
province_hits AS (
  SELECT b.province, b.municipality, b.barangay, b.barangay_possibly_truncated,
         COUNT(DISTINCT p.psgc_code) AS hits, MIN(p.psgc_code) AS psgc_code
  FROM province_best AS b JOIN province_pairs AS p USING (province, municipality, barangay, barangay_possibly_truncated, tier)
  GROUP BY 1,2,3,4
),
province_scope AS (
  SELECT DISTINCT b.province, b.municipality, b.barangay, b.barangay_possibly_truncated,
         substr(p.psgc_code, 1, 5) AS province_prefix
  FROM province_best AS b
  JOIN province_pairs AS p USING (province, municipality, barangay, barangay_possibly_truncated, tier)
),
city_pairs AS (
  SELECT s.province, s.municipality, s.barangay, s.barangay_possibly_truncated, u.psgc_code, u.geographic_level,
         CASE WHEN regexp_like(upper(s.province), 'NCR') AND u.psgc_code LIKE '13%' THEN 1
              WHEN ps.province_prefix IS NOT NULL THEN 1
              WHEN u.geographic_level = 'City' AND (ph.hits IS NULL OR substr(u.psgc_code, 6) = '00000') THEN 2 ELSE 9 END AS scope_rank,
         LEAST(COALESCE({_tier('s', 'u')}, 99), COALESCE({_tier('s', 'u', old=True)}, 99)) AS tier
  FROM source3 AS s
  LEFT JOIN province_hits AS ph USING (province, municipality, barangay, barangay_possibly_truncated)
  JOIN units AS u ON u.geographic_level IN ('City', 'Mun', 'SubMun')
    AND (s.k_exact = u.k_exact OR s.k_exact = u.ok_exact OR s.k_fold = u.k_fold OR s.k_fold = u.ok_fold
         OR s.k_brackets = u.k_brackets OR s.k_city = u.k_city)
  LEFT JOIN province_scope AS ps ON ps.province IS NOT DISTINCT FROM s.province
    AND ps.municipality IS NOT DISTINCT FROM s.municipality AND ps.barangay IS NOT DISTINCT FROM s.barangay
    AND ps.barangay_possibly_truncated = s.barangay_possibly_truncated
    AND ps.province_prefix = substr(u.psgc_code, 1, 5)
),
city_scope AS (
  SELECT province, municipality, barangay, barangay_possibly_truncated, MIN(scope_rank) AS scope_rank
  FROM city_pairs WHERE scope_rank < 9 AND tier < 99 GROUP BY 1,2,3,4
),
city_best AS (
  SELECT s.province, s.municipality, s.barangay, s.barangay_possibly_truncated, s.scope_rank, MIN(c.tier) AS tier
  FROM city_scope AS s JOIN city_pairs AS c USING (province, municipality, barangay, barangay_possibly_truncated, scope_rank)
  WHERE c.tier < 99 GROUP BY 1,2,3,4,5
),
city_hits AS (
  SELECT b.province, b.municipality, b.barangay, b.barangay_possibly_truncated,
         COUNT(DISTINCT c.psgc_code) AS hits, MIN(c.psgc_code) AS psgc_code,
         MIN(c.geographic_level) AS geographic_level, b.scope_rank, b.tier
  FROM city_best AS b JOIN city_pairs AS c USING (province, municipality, barangay, barangay_possibly_truncated, scope_rank, tier)
  GROUP BY 1,2,3,4,8,9
),
city_named AS (
  SELECT s.*, COALESCE(a.psgc_code, CASE WHEN c.hits = 1 THEN c.psgc_code END) AS name_city_code,
         COALESCE(au.geographic_level, c.geographic_level) AS name_city_level,
         CASE WHEN a.psgc_code IS NOT NULL THEN 'reviewed_alias'
              WHEN c.scope_rank = 2 THEN 'name_exact' ELSE {_method('c.tier')} END AS name_city_method,
         COALESCE(a.reason, CASE WHEN c.hits > 1 THEN CAST(c.hits AS STRING) || ' PSGC localities match the best name tier' END) AS name_city_reason
  FROM source3 AS s
  LEFT JOIN province_hits AS ph USING (province, municipality, barangay, barangay_possibly_truncated)
  LEFT JOIN aliases AS a ON a.deped_name = s.k_exact AND
    (regexp_like(upper(s.province), 'NCR') AND a.psgc_code LIKE '13%'
     OR ph.hits = 1 AND substr(a.psgc_code, 1, 5) = substr(ph.psgc_code, 1, 5)
     OR substr(a.psgc_code, 6) = '00000')
  LEFT JOIN units AS au ON au.psgc_code = a.psgc_code
  LEFT JOIN city_hits AS c USING (province, municipality, barangay, barangay_possibly_truncated)
),
barangay_pairs AS (
  SELECT s.province, s.municipality, s.barangay, s.barangay_possibly_truncated, u.psgc_code,
         LEAST(COALESCE(CASE WHEN s.b_exact = u.k_exact THEN 1 WHEN s.b_fold = u.k_fold THEN 3
                            WHEN s.b_brackets = u.k_brackets THEN 5 WHEN s.b_city = u.k_city THEN 6
                            WHEN s.barangay_possibly_truncated AND u.k_fold LIKE s.b_fold || '%' THEN 7 END, 99),
               COALESCE(CASE WHEN s.b_exact = u.ok_exact THEN 2 WHEN s.b_fold = u.ok_fold THEN 4 END, 99)) AS tier
  FROM city_named AS s JOIN units AS u ON u.geographic_level = 'Bgy'
   AND u.city_municipality_code = s.name_city_code
),
barangay_best AS (
  SELECT province, municipality, barangay, barangay_possibly_truncated, MIN(tier) AS tier
  FROM barangay_pairs WHERE tier < 99 GROUP BY 1,2,3,4
),
barangay_hits AS (
  SELECT b.province, b.municipality, b.barangay, b.barangay_possibly_truncated,
         COUNT(DISTINCT p.psgc_code) AS hits, MIN(p.psgc_code) AS psgc_code, b.tier
  FROM barangay_best AS b JOIN barangay_pairs AS p USING (province, municipality, barangay, barangay_possibly_truncated, tier)
  GROUP BY 1,2,3,4,7
),
places AS (
  SELECT c.*, CASE WHEN b.hits = 1 THEN b.psgc_code END AS name_bgy_code,
         {_method('b.tier')} AS name_bgy_method,
         CASE WHEN b.hits > 1 THEN CAST(b.hits AS STRING) || ' PSGC barangays match the best name tier' END AS name_bgy_reason
  FROM city_named AS c LEFT JOIN barangay_hits AS b USING (province, municipality, barangay, barangay_possibly_truncated)
),
school_input AS (
  SELECT e.school_year, e.school_id, e.school_name, e.region, e.province, e.municipality, e.barangay,
         e.barangay_possibly_truncated, e.is_overseas,
         e.batch_id, e.source_sha256, e.source_row_number,
         x.psgc_city_municipality AS code_city, x.psgc_barangay AS code_bgy, x.psgc_recoded,
         x.batch_id AS crosswalk_batch_id, x.source_row_number AS crosswalk_source_row_number,
         pl.name_city_code, pl.name_city_level, pl.name_city_method, pl.name_city_reason,
         pl.name_bgy_code, pl.name_bgy_method, pl.name_bgy_reason,
         pl.b_exact, pl.b_fold, pl.b_brackets, pl.b_city
  FROM {enr} AS e
  LEFT JOIN {cross} AS x ON x.school_id = e.school_id
  LEFT JOIN places AS pl ON pl.province IS NOT DISTINCT FROM e.province
    AND pl.municipality IS NOT DISTINCT FROM e.municipality AND pl.barangay = COALESCE(e.barangay, '')
    AND pl.barangay_possibly_truncated = e.barangay_possibly_truncated
),
school_units AS (
  SELECT s.*, cc.geographic_level AS code_city_level, cb.name AS code_bgy_name,
         CASE WHEN cc.geographic_level = 'SubMun' THEN substr(cc.psgc_code, 1, 5) || '00000' ELSE cc.psgc_code END AS code_city_roll,
         CASE WHEN nc.geographic_level = 'SubMun' THEN substr(nc.psgc_code, 1, 5) || '00000' ELSE nc.psgc_code END AS name_city_roll,
         CASE WHEN s.barangay IS NOT NULL AND
              (s.b_exact = cb.k_exact OR s.b_exact = cb.ok_exact
               OR s.b_fold = cb.k_fold OR s.b_fold = cb.ok_fold
               OR s.b_brackets = cb.k_brackets OR s.b_city = cb.k_city
               OR (s.barangay_possibly_truncated AND cb.k_fold LIKE s.b_fold || '%'))
              THEN TRUE ELSE FALSE END AS code_bgy_name_agrees,
         cb.city_municipality_code AS code_bgy_parent,
         o.use_side AS bgy_override_side, o.reason AS bgy_override_reason, o.reviewer AS bgy_override_reviewer
  FROM school_input AS s
  LEFT JOIN units AS cc ON cc.psgc_code = s.code_city AND cc.geographic_level IN ('City', 'Mun', 'SubMun')
  LEFT JOIN units AS cb ON cb.psgc_code = s.code_bgy AND cb.geographic_level = 'Bgy'
  LEFT JOIN units AS nc ON nc.psgc_code = s.name_city_code
  LEFT JOIN overrides AS o ON o.geographic_level = 'bgy' AND o.province = s.province
    AND o.municipality = s.municipality AND o.barangay = s.barangay
),
city_decided AS (
  SELECT s.*,
    CASE WHEN s.is_overseas THEN 'excluded'
         WHEN upper(s.region) = 'BARMM' AND upper(s.province) = 'NORTH COTABATO'
           THEN CASE WHEN s.code_bgy_name_agrees AND s.code_bgy_parent = s.code_city THEN 'matched' ELSE 'excluded' END
         WHEN s.code_city_roll IS NOT NULL AND s.code_city_roll = s.name_city_roll THEN 'matched'
         WHEN s.code_city_roll IS NOT NULL AND s.name_city_roll IS NOT NULL
           THEN CASE WHEN s.code_bgy_name_agrees AND s.code_bgy_parent = s.code_city THEN 'matched' ELSE 'ambiguous' END
         WHEN COALESCE(s.code_city_roll, s.name_city_roll) IS NOT NULL THEN 'matched' ELSE 'unmatched' END AS city_status,
    CASE WHEN s.is_overseas THEN NULL
         WHEN upper(s.region) = 'BARMM' AND upper(s.province) = 'NORTH COTABATO'
           THEN CASE WHEN s.code_bgy_name_agrees AND s.code_bgy_parent = s.code_city THEN s.code_city_roll END
         WHEN s.code_city_roll IS NOT NULL AND s.name_city_roll IS NOT NULL AND s.code_city_roll <> s.name_city_roll
           THEN CASE WHEN s.code_bgy_name_agrees AND s.code_bgy_parent = s.code_city THEN s.code_city_roll END
         ELSE COALESCE(s.code_city_roll, s.name_city_roll) END AS city_code,
    CASE WHEN s.is_overseas THEN NULL
         WHEN s.code_city_level = 'SubMun' OR (s.code_city_roll IS NULL AND s.name_city_level = 'SubMun') THEN 'rollup'
         WHEN s.code_city_roll IS NOT NULL THEN CASE WHEN s.psgc_recoded THEN 'code_region_moved'
              WHEN s.name_city_roll = s.code_city_roll THEN 'code' ELSE 'code_name_differs' END
         ELSE s.name_city_method END AS city_method,
    CASE WHEN s.is_overseas THEN 'Philippine Schools Overseas'
         WHEN upper(s.region) = 'BARMM' AND upper(s.province) = 'NORTH COTABATO'
              AND NOT (s.code_bgy_name_agrees AND s.code_bgy_parent = s.code_city) THEN 'Special Geographic Area (D-031)'
         WHEN s.code_city_roll IS NOT NULL AND s.name_city_roll IS NOT NULL AND s.code_city_roll <> s.name_city_roll
              AND NOT (s.code_bgy_name_agrees AND s.code_bgy_parent = s.code_city) THEN 'code and name differ'
         WHEN s.code_city_roll IS NOT NULL AND s.name_city_roll IS NULL THEN 'code only'
         WHEN s.code_city_roll IS NULL AND s.name_city_roll IS NOT NULL THEN 'name only'
         WHEN s.code_city_roll IS NULL AND s.name_city_roll IS NULL THEN COALESCE(s.name_city_reason, 'no code or name match')
         ELSE 'code and name agree' END AS city_reason
  FROM school_units AS s
),
bgy_pre AS (
  SELECT c.*,
    CASE WHEN c.city_status <> 'matched' THEN c.city_status
         WHEN c.bgy_override_side = 'code' THEN CASE WHEN c.code_bgy IS NOT NULL THEN 'matched' ELSE 'unmatched' END
         WHEN c.bgy_override_side = 'name' THEN CASE WHEN c.name_bgy_code IS NOT NULL THEN 'matched' ELSE 'unmatched' END
         WHEN c.code_bgy IS NOT NULL AND c.code_bgy = c.name_bgy_code THEN 'matched'
         WHEN c.code_bgy IS NOT NULL AND c.code_bgy_name_agrees THEN 'matched'
         WHEN c.code_bgy IS NOT NULL AND c.name_bgy_code IS NOT NULL THEN 'ambiguous'
         WHEN COALESCE(c.code_bgy, c.name_bgy_code) IS NOT NULL THEN 'matched' ELSE 'unmatched' END AS bgy_status0,
    CASE WHEN c.city_status <> 'matched' THEN NULL
         WHEN c.bgy_override_side = 'code' THEN c.code_bgy
         WHEN c.bgy_override_side = 'name' THEN c.name_bgy_code
         WHEN c.code_bgy IS NOT NULL AND (c.name_bgy_code IS NULL OR c.code_bgy = c.name_bgy_code OR c.code_bgy_name_agrees) THEN c.code_bgy
         WHEN c.code_bgy IS NULL THEN c.name_bgy_code END AS bgy_code0,
    CASE WHEN c.city_status <> 'matched' THEN NULL
         WHEN (c.bgy_override_side = 'code' AND c.code_bgy IS NOT NULL)
           OR (c.bgy_override_side IS NULL AND c.code_bgy IS NOT NULL) THEN CASE WHEN c.psgc_recoded THEN 'code_region_moved'
              WHEN c.name_bgy_code = c.code_bgy OR c.code_bgy_name_agrees THEN 'code' ELSE 'code_name_differs' END
         WHEN (c.bgy_override_side = 'name' AND c.name_bgy_code IS NOT NULL)
           OR (c.bgy_override_side IS NULL AND c.code_bgy IS NULL) THEN c.name_bgy_method END AS bgy_method0,
    CASE WHEN c.city_status <> 'matched' THEN 'city or municipality ' || c.city_status
         WHEN c.bgy_override_side IS NOT NULL AND COALESCE(CASE WHEN c.bgy_override_side = 'code' THEN c.code_bgy ELSE c.name_bgy_code END, '') <> '' THEN 'reviewed override'
         WHEN c.bgy_override_side IS NOT NULL THEN 'reviewed override: no unit'
         WHEN c.code_bgy IS NOT NULL AND c.name_bgy_code IS NOT NULL AND c.code_bgy <> c.name_bgy_code AND NOT c.code_bgy_name_agrees THEN 'code and name differ'
         WHEN c.code_bgy IS NOT NULL AND c.name_bgy_code IS NULL THEN 'code only'
         WHEN c.code_bgy IS NULL AND c.name_bgy_code IS NOT NULL THEN 'name only'
         WHEN c.code_bgy IS NULL AND c.name_bgy_code IS NULL THEN COALESCE(c.name_bgy_reason, 'no code or name match')
         ELSE 'code and name agree' END AS bgy_reason0
  FROM city_decided AS c
),
bgy_decided AS (
  SELECT b.*,
    CASE WHEN b.bgy_status0 = 'matched' AND NOT (u.city_municipality_code = b.city_code
          OR (u.city_municipality_code LIKE '13806%' AND b.city_code = '1380600000')) THEN 'ambiguous' ELSE b.bgy_status0 END AS bgy_status,
    CASE WHEN b.bgy_status0 <> 'matched' THEN NULL
         WHEN b.bgy_status0 = 'matched' AND NOT (u.city_municipality_code = b.city_code
          OR (u.city_municipality_code LIKE '13806%' AND b.city_code = '1380600000')) THEN NULL ELSE b.bgy_code0 END AS bgy_code,
    CASE WHEN b.bgy_status0 <> 'matched' THEN NULL
         WHEN b.bgy_status0 = 'matched' AND NOT (u.city_municipality_code = b.city_code
          OR (u.city_municipality_code LIKE '13806%' AND b.city_code = '1380600000')) THEN NULL ELSE b.bgy_method0 END AS bgy_method,
    CASE WHEN b.bgy_status0 = 'matched' AND NOT (u.city_municipality_code = b.city_code
          OR (u.city_municipality_code LIKE '13806%' AND b.city_code = '1380600000')) THEN 'barangay outside the accepted city or municipality' ELSE b.bgy_reason0 END AS bgy_reason
  FROM bgy_pre AS b LEFT JOIN units AS u ON u.psgc_code = b.bgy_code0
),
decisions AS (
  SELECT b.*, 'city_mun' AS geographic_level, b.code_city AS code_candidate, b.city_code AS psgc_code,
         b.city_status AS match_status, CASE WHEN b.city_code IS NULL THEN NULL ELSE b.city_method END AS match_method, b.city_reason AS reason,
         CAST(NULL AS STRING) AS override_reason, CAST(NULL AS STRING) AS override_reviewer
  FROM bgy_decided AS b
  UNION ALL
  SELECT b.*, 'bgy', b.code_bgy, b.bgy_code, b.bgy_status, b.bgy_method, b.bgy_reason,
         b.bgy_override_reason, b.bgy_override_reviewer
  FROM bgy_decided AS b
)
SELECT
  '{SOURCE}' AS source_id,
  d.school_year || '/' || d.school_id || '/' || d.geographic_level AS source_row_ref,
  d.school_year, d.school_id, d.school_name,
  d.region AS source_region, d.province AS source_province,
  d.municipality AS source_city_municipality, d.barangay AS source_barangay,
  d.geographic_level, d.code_candidate,
  (SELECT MIN(publication_period) FROM psgc_input) AS psgc_version,
  d.psgc_code, p.name AS psgc_name,
  d.match_status, d.match_method,
  CASE WHEN d.override_reviewer IS NOT NULL THEN 'reviewed' WHEN d.match_status = 'matched' THEN 'rule' ELSE 'pending' END AS review_status,
  d.reason, d.override_reason, d.override_reviewer,
  d.batch_id, d.source_sha256, d.source_row_number,
  d.crosswalk_batch_id, d.crosswalk_source_row_number,
  p.batch_id AS psgc_batch_id, p.source_row_number AS psgc_source_row_number,
  session.integration_run_id AS run_id, session.integration_built_at_utc AS built_at_utc,
  session.integration_code_revision AS code_revision
FROM decisions AS d LEFT JOIN psgc_input AS p ON p.psgc_code = d.psgc_code;

CREATE OR REPLACE TABLE {candidate} USING DELTA AS
SELECT * FROM deped_school_psgc_matched;

COMMENT ON TABLE {candidate} IS 'Unpublished build for the Integration gate. Do not read: use {spec.map_table}.';
ALTER TABLE {candidate} OWNER TO `{OWNER_GROUP}`;
"""
    return "\n".join(_header("Integration build", "sql", f"etl/04_integration/{BUILD_FILE}")) + "\n--\n-- Distinct place tuples are matched once, then reused by every school-year row.\n" + sql.lstrip()


def gate_sql(spec):
    enr = ref(SILVER, spec.enrollment_table)
    psgc = ref(SILVER, spec.psgc_table)
    candidate, published = ref(SCHEMA, spec.candidate), ref(SCHEMA, spec.map_table)
    status_list = ", ".join(lit(v) for v in STATUSES)
    method_list = ", ".join(lit(v) for v in METHODS)
    sql = f"""
DECLARE OR REPLACE VARIABLE integration_gate_started_at_utc TIMESTAMP;
SET VARIABLE integration_gate_started_at_utc = current_timestamp();

INSERT INTO {CONTROL}.data_quality_results
  (run_id, batch_id, source_id, layer, table_name, check_name, status, expected, actual, checked_at_utc, code_revision)
SELECT :run_id, CAST(NULL AS STRING), '{SOURCE}', 'integration', 'edu_access.{SCHEMA}.{spec.candidate}',
       check_name, status, expected, actual, current_timestamp(), :code_revision
FROM (
WITH e AS (SELECT school_year, school_id FROM {enr}),
p AS (SELECT psgc_code, geographic_level, city_municipality_code, publication_period FROM {psgc} WHERE is_master_reference),
m AS (SELECT * FROM {candidate}),
stats AS (
  SELECT
    (SELECT COUNT(*) FROM e) AS enrollment_rows,
    (SELECT COUNT(*) FROM p) AS psgc_rows,
    (SELECT COUNT(DISTINCT publication_period) FROM p) AS psgc_periods,
    COUNT(*) AS map_rows,
    COUNT(DISTINCT m.school_year || '/' || m.school_id || '/' || m.geographic_level) AS map_keys,
    COUNT_IF(m.geographic_level = 'city_mun') AS city_rows,
    COUNT_IF(m.geographic_level = 'bgy') AS bgy_rows,
    COUNT_IF(m.geographic_level NOT IN ('city_mun', 'bgy')) AS bad_level,
    COUNT_IF(m.match_status NOT IN ({status_list}) OR m.match_status IS NULL) AS bad_status,
    COUNT_IF((m.match_status = 'matched' AND (m.psgc_code IS NULL OR m.match_method NOT IN ({method_list})))
             OR (m.match_status <> 'matched' AND (m.psgc_code IS NOT NULL OR m.match_method IS NOT NULL))) AS bad_combination,
    COUNT_IF(m.match_status = 'matched' AND p.psgc_code IS NULL) AS matched_without_psgc,
    COALESCE(COUNT_IF((m.geographic_level = 'city_mun' AND p.geographic_level NOT IN ('City', 'Mun'))
             OR (m.geographic_level = 'bgy' AND p.geographic_level <> 'Bgy')), 0) AS wrong_psgc_level,
    COUNT_IF(m.source_row_ref IS NULL OR m.batch_id IS NULL OR m.source_sha256 IS NULL OR m.source_row_number IS NULL
             OR m.run_id IS NULL OR m.built_at_utc IS NULL OR m.code_revision IS NULL
             OR (m.psgc_code IS NOT NULL AND m.psgc_batch_id IS NULL)) AS missing_lineage,
    COUNT_IF(m.run_id <> :run_id OR m.run_id IS NULL) AS other_run_rows,
    COUNT_IF(m.match_status = 'unmatched') AS unmatched_rows,
    COUNT_IF(m.match_status = 'ambiguous') AS ambiguous_rows,
    COUNT_IF(m.match_status = 'excluded') AS excluded_rows,
    COUNT_IF(m.review_status = 'pending') AS pending_rows
  FROM m LEFT JOIN p ON p.psgc_code = m.psgc_code
),
hierarchy AS (
  SELECT COUNT_IF(NOT (b.psgc_code IS NULL OR c.psgc_code IS NULL OR pb.city_municipality_code = c.psgc_code
                       OR (pb.city_municipality_code LIKE '13806%' AND c.psgc_code = '1380600000'))) AS bad_parent
  FROM m AS b JOIN m AS c ON c.school_year = b.school_year AND c.school_id = b.school_id
    AND b.geographic_level = 'bgy' AND c.geographic_level = 'city_mun'
  LEFT JOIN p AS pb ON pb.psgc_code = b.psgc_code
),
s AS (SELECT * FROM stats CROSS JOIN hierarchy),
checks AS (
  SELECT 'inputs_present' AS check_name, CASE WHEN enrollment_rows > 0 AND psgc_rows > 0 THEN 'PASS' ELSE 'FAIL' END AS status,
         'enrollment and master PSGC rows' AS expected, CAST(enrollment_rows AS STRING) || ' / ' || CAST(psgc_rows AS STRING) AS actual FROM s
  UNION ALL SELECT 'rows_reconcile', CASE WHEN map_rows = enrollment_rows * 2 THEN 'PASS' ELSE 'FAIL' END, CAST(enrollment_rows * 2 AS STRING), CAST(map_rows AS STRING) FROM s
  UNION ALL SELECT 'one_row_per_school_year_level', CASE WHEN map_keys = map_rows THEN 'PASS' ELSE 'FAIL' END, CAST(map_rows AS STRING), CAST(map_keys AS STRING) FROM s
  UNION ALL SELECT 'both_levels_present', CASE WHEN city_rows = enrollment_rows AND bgy_rows = enrollment_rows AND bad_level = 0 THEN 'PASS' ELSE 'FAIL' END,
                   CAST(enrollment_rows AS STRING) || ' / ' || CAST(enrollment_rows AS STRING) || ' / 0',
                   CAST(city_rows AS STRING) || ' / ' || CAST(bgy_rows AS STRING) || ' / ' || CAST(bad_level AS STRING) FROM s
  UNION ALL SELECT 'status_valid', CASE WHEN bad_status = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_status AS STRING) FROM s
  UNION ALL SELECT 'status_combination_valid', CASE WHEN bad_combination = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_combination AS STRING) FROM s
  UNION ALL SELECT 'matched_has_psgc_unit', CASE WHEN matched_without_psgc = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(matched_without_psgc AS STRING) FROM s
  UNION ALL SELECT 'psgc_level_valid', CASE WHEN wrong_psgc_level = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(wrong_psgc_level AS STRING) FROM s
  UNION ALL SELECT 'barangay_inside_city', CASE WHEN bad_parent = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(bad_parent AS STRING) FROM s
  UNION ALL SELECT 'one_psgc_version', CASE WHEN psgc_periods = 1 THEN 'PASS' ELSE 'FAIL' END, '1', CAST(psgc_periods AS STRING) FROM s
  UNION ALL SELECT 'lineage_complete', CASE WHEN missing_lineage = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(missing_lineage AS STRING) FROM s
  UNION ALL SELECT 'rows_built_by_this_run', CASE WHEN other_run_rows = 0 THEN 'PASS' ELSE 'FAIL' END, '0', CAST(other_run_rows AS STRING) FROM s
  UNION ALL SELECT 'unmatched', CASE WHEN unmatched_rows = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(unmatched_rows AS STRING) FROM s
  UNION ALL SELECT 'ambiguous', CASE WHEN ambiguous_rows = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(ambiguous_rows AS STRING) FROM s
  UNION ALL SELECT 'excluded', CASE WHEN excluded_rows = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(excluded_rows AS STRING) FROM s
  UNION ALL SELECT 'review_pending', CASE WHEN pending_rows = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST(pending_rows AS STRING) FROM s
),
rates AS (
  SELECT 'match_rate_' || school_year || '_' || geographic_level AS check_name, 'PASS' AS status,
         CAST(NULL AS STRING) AS expected,
         CAST(ROUND(100.0 * COUNT_IF(match_status = 'matched') / COUNT(*), 2) AS STRING) AS actual
  FROM m GROUP BY school_year, geographic_level
)
SELECT * FROM checks UNION ALL SELECT * FROM rates
) AS results;

MERGE INTO {CONTROL}.pipeline_runs AS t
USING (SELECT :run_id AS run_id, COUNT_IF(status = 'FAIL') AS fails FROM {CONTROL}.data_quality_results
       WHERE run_id = :run_id AND source_id = '{SOURCE}' AND layer = 'integration'
         AND checked_at_utc >= session.integration_gate_started_at_utc) AS s
ON t.run_id = s.run_id AND t.pipeline_name = '{PIPELINE}' AND t.source_id = '{SOURCE}'
WHEN MATCHED AND s.fails > 0 THEN UPDATE SET status = 'failed', finished_at_utc = current_timestamp(),
  failure_stage = 'gate', error_message = CAST(s.fails AS STRING) || ' FAIL result(s) in data_quality_results';

SELECT CASE WHEN COUNT(*) > 0 THEN raise_error('Integration gate failed for {SOURCE}: ' || CAST(COUNT(*) AS STRING) || ' FAIL result(s)') END
FROM {CONTROL}.data_quality_results
WHERE run_id = :run_id AND source_id = '{SOURCE}' AND layer = 'integration' AND status = 'FAIL'
  AND checked_at_utc >= session.integration_gate_started_at_utc;

CREATE OR REPLACE TABLE {published} USING DELTA AS SELECT * FROM {candidate};
ALTER TABLE {published} OWNER TO `{OWNER_GROUP}`;

MERGE INTO {CONTROL}.pipeline_runs AS t USING (SELECT :run_id AS run_id) AS s
ON t.run_id = s.run_id AND t.pipeline_name = '{PIPELINE}' AND t.source_id = '{SOURCE}'
WHEN MATCHED THEN UPDATE SET status = 'succeeded', finished_at_utc = current_timestamp(), failure_stage = NULL, error_message = NULL;
"""
    return "\n".join(_header("Integration gate", "gate", f"etl/04_integration/{GATE_FILE}")) + "\n" + sql.lstrip()


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args not in (["sql"], ["gate"]):
        sys.stderr.write("usage: python -m src.integration.deped_school_psgc sql|gate\n")
        return 2
    spec = load_spec()
    sys.stdout.write(build_sql(spec) if args[0] == "sql" else gate_sql(spec))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
