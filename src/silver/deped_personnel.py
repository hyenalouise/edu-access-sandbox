"""Generate DepEd personnel Silver build, gate, and data dictionary files."""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from src.ingestion.bronze import OWNER_GROUP, source_columns
from src.ingestion.contract import load_source_config
from src.ingestion.errors import IngestionError
from src.silver.generators import REPO_ROOT
from src.silver.sql import CONTROL, bq, candidate_comment, dq_table_name, joined, lit, silver_ref
from src.silver.spec import load_spec as load_deped_spec

SOURCE_ID = "deped_personnel"
LINEAGE = ("batch_id", "delivery_version", "schema_version", "source_sha256", "source_row_number")
STAMP = ("run_id", "cleaned_at_utc", "code_revision")
REASONS = ("school_id_blank", "school_id_malformed", "school_id_duplicated", "measure_negative",
           "measure_uncastable", "measure_above_int_max", "measure_outside_public_scope",
           "measure_outside_offered_level")


def _error(message):
    return IngestionError("config", "invalid_silver_mapping", message)


@dataclass
class PersonnelSpec:
    source_id: str
    bronze_table: str
    clean_file: str
    clean_table: str
    quarantine_table: str
    clean_candidate: str
    quarantine_candidate: str
    identifier: str
    identifier_pattern: str
    dimensions: list
    measures: list
    public_sector: str
    boolean_true: list
    boolean_false: list
    categories: dict
    integer_max: int
    all_blank_measure: str
    principal_total: str
    principal_components: list
    mapping: dict = field(repr=False)


def load_spec(repo_root=REPO_ROOT, source_id=SOURCE_ID):
    root = Path(repo_root)
    mapping = json.loads((root / "config" / "mappings" / f"{source_id}.json").read_text(encoding="utf-8"))
    contract, _ = load_source_config(root, source_id)
    registry = yaml.safe_load((root / "config" / "tables.yml").read_text(encoding="utf-8"))
    entry = next((s for s in registry["source_tables"] if s["source_id"] == source_id), None)
    columns = source_columns(contract)
    identifier, dimensions = mapping["identifier"]["column"], mapping["dimensions"]
    measures = [c for c in columns if c not in {identifier, *dimensions}]
    silver_measures = [_name(c) for c in measures]
    silver = (entry or {}).get("silver", {})
    if mapping.get("source_id") != contract["source_id"]:
        raise _error("source_id differs from the Bronze contract.")
    if silver.get("table") != mapping["silver_table"] or silver.get("quarantine_table") != mapping["quarantine_table"]:
        raise _error("Silver tables must match config/tables.yml.")
    if columns[:6] != [identifier, *dimensions] or len(measures) != 321:
        raise _error("the Personnel contract must contain its six identity columns followed by 321 measures.")
    if len(set(silver_measures)) != len(silver_measures):
        raise _error("two publisher measures normalize to the same Silver column name.")
    named = [mapping["all_blank_measure"], mapping["principal_total"], *mapping["principal_components"]]
    if any(c not in measures for c in named):
        raise _error("a reviewed Personnel rule names a column outside the contract's measures.")
    enrollment = load_deped_spec(root, "deped_enrollment")
    categories = mapping["categories"]
    for name in ("sector", "school_management"):
        if categories[name]["standard"] != enrollment.categories[name].standard:
            raise _error(f"{name} must use the deped_enrollment standard set.")
        if any(value not in categories[name]["standard"] for value in categories[name]["labels"].values()):
            raise _error(f"{name} maps a label outside its standard set.")
    return PersonnelSpec(source_id, contract["bronze_table"], silver["clean_file"], mapping["silver_table"],
                         mapping["quarantine_table"], silver["candidate_table"], silver["candidate_quarantine_table"],
                         identifier, mapping["identifier"]["pattern"], dimensions, measures, mapping["public_sector"],
                         mapping["boolean_true"], mapping["boolean_false"], categories, mapping["integer_max"],
                         mapping["all_blank_measure"],
                         mapping["principal_total"], mapping["principal_components"], mapping)


def _header(spec, name, command, path):
    return [f"-- {name} for {spec.source_id}. Generated from config/ingestion/{spec.source_id}.json",
            f"-- and config/mappings/{spec.source_id}.json:",
            f"--   python -m src.silver.cli {command} --source {spec.source_id} > etl/03_silver/{path}",
            "-- Do not edit by hand; tests/test_silver.py fails if it differs."]


def _any(expressions, indent=8):
    return ("\n" + " " * indent + "OR ").join(expressions)


def _sum(expressions):
    return " + ".join(f"COALESCE(CAST({x} AS BIGINT), 0)" for x in expressions)


def _typed(ref, maximum):
    as_bigint = f"TRY_CAST(TRY_CAST({ref} AS DECIMAL(38, 10)) AS BIGINT)"
    return f"CASE WHEN regexp_like({ref}, '^[0-9]+([.]0+)?$') AND {as_bigint} <= {maximum} THEN TRY_CAST({as_bigint} AS INT) END"


def _name(source):
    """Return a legal, stable Silver name for a publisher column."""
    return re.sub("_+", "_", re.sub("[^a-z0-9]+", "_", source.lower())).strip("_")


def build_sql(spec):
    source = spec.source_id
    clean, quarantine = silver_ref(spec.clean_candidate), silver_ref(spec.quarantine_candidate)
    raw_measures = [f"r.{bq(c)} AS {_name(c)}" for c in spec.measures]
    duplicated = f"COUNT(*) OVER (PARTITION BY r.school_year, r.{spec.identifier})"
    category_sql = []
    for name in ("sector", "school_management"):
        cases = " ".join(f"WHEN n.{name} = {lit(published)} THEN {lit(standard)}"
                         for published, standard in spec.categories[name]["labels"].items())
        category_sql.append(f"CASE {cases} END AS {name}")
    typed = ["n.school_year", f"n.{spec.identifier}", *category_sql,
             *[f"CASE WHEN n.{c} IN ({', '.join(lit(v) for v in spec.boolean_true)}) THEN TRUE "
               f"WHEN n.{c} IN ({', '.join(lit(v) for v in spec.boolean_false)}) THEN FALSE END AS {c}"
               for c in ("offers_es", "offers_jhs", "offers_shs")],
             *[f"{_typed('n.' + _name(c), spec.integer_max)} AS {_name(c)}" for c in spec.measures],
             "n.school_id_rows", *[f"n.{c}" for c in LINEAGE]]
    invalid = {
        "measure_negative": _any([f"regexp_like(n.{_name(c)}, '^-[0-9]+([.]0+)?$')" for c in spec.measures]),
        "measure_uncastable": _any([f"n.{_name(c)} <> '' AND NOT regexp_like(n.{_name(c)}, '^-?[0-9]+([.]0+)?$')" for c in spec.measures]),
        "measure_above_int_max": _any([f"regexp_like(n.{_name(c)}, '^[0-9]+([.]0+)?$') AND (TRY_CAST(TRY_CAST(n.{_name(c)} AS DECIMAL(38, 10)) AS BIGINT) IS NULL OR TRY_CAST(TRY_CAST(n.{_name(c)} AS DECIMAL(38, 10)) AS BIGINT) > {spec.integer_max})" for c in spec.measures]),
        "measure_outside_public_scope": f"n.sector <> {lit(spec.public_sector)} AND (" + _any([f"n.{_name(c)} <> ''" for c in spec.measures]) + ")",
        "measure_outside_offered_level": _any([f"(n.offers_{level} IN ({', '.join(lit(v) for v in spec.boolean_false)}) AND (" +
                                               _any([f"n.{_name(c)} <> ''" for c in spec.measures if c.startswith(level + "_")], 10) + "))"
                                               for level in ("es", "jhs", "shs")]),
    }
    reason_parts = [f"CASE WHEN n.{spec.identifier} IS NULL OR n.{spec.identifier} = '' THEN 'school_id_blank' END",
                    f"CASE WHEN n.{spec.identifier} <> '' AND NOT regexp_like(n.{spec.identifier}, {lit(spec.identifier_pattern)}) THEN 'school_id_malformed' END",
                    f"CASE WHEN n.{spec.identifier} <> '' AND n.school_id_rows > 1 THEN 'school_id_duplicated' END"]
    reason_parts += [f"CASE WHEN {invalid[r]} THEN {lit(r)} END" for r in REASONS[3:]]
    typed.append("concat_ws(',',\n" + joined(reason_parts, 6) + "\n    ) AS quarantine_reasons")
    component_sum = _sum(["t." + c for c in spec.principal_components])
    status = (f"CASE WHEN t.sector <> {lit(spec.public_sector)} THEN 'out_of_scope' "
              f"WHEN COALESCE({', '.join('t.' + _name(c) for c in spec.measures)}) IS NULL THEN 'no_counts' "
              f"WHEN {_sum(['t.' + _name(c) for c in spec.measures])} = 0 THEN 'all_zero' ELSE 'has_personnel' END")
    final = ["t.school_year", f"t.{spec.identifier}", "t.sector", "t.school_management", "t.offers_es", "t.offers_jhs", "t.offers_shs",
             *[f"t.{_name(c)}" for c in spec.measures], f"{component_sum} AS shs_school_principal_calculated",
             f"CASE WHEN t.{spec.principal_total} IS NULL THEN FALSE ELSE t.{spec.principal_total} <> {component_sum} END AS shs_principal_total_discrepancy",
             f"COALESCE(t.{spec.all_blank_measure} IS NULL, TRUE) AS shs_master_teacher_iv_unavailable",
             f"{status} AS personnel_reporting_status",
             "t.quarantine_reasons", *[f"t.{c}" for c in LINEAGE], *[f"session.silver_{c} AS {c}" for c in STAMP]]
    clean_columns = ["school_year", spec.identifier, *spec.dimensions, *[_name(c) for c in spec.measures], "shs_school_principal_calculated",
                     "shs_principal_total_discrepancy", "shs_master_teacher_iv_unavailable", "personnel_reporting_status",
                     *LINEAGE, *STAMP]
    quarantine_columns = ["school_year", spec.identifier, "split(quarantine_reasons, ',') AS quarantine_reasons",
                          *LINEAGE, *STAMP]
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
        f"CREATE OR REPLACE TEMPORARY VIEW {source}_classified AS", "WITH bronze AS (",
        f"  SELECT r.* FROM edu_access.`02-bronze`.{spec.bronze_table} AS r JOIN {CONTROL}.current_batches AS c ON r.batch_id = c.batch_id WHERE c.source_id = {lit(source)}",
        "), normalized AS (", "  SELECT",
        joined(["r.school_year", f"r.{spec.identifier}", "r.sector", "r.school_management", "r.offers_es", "r.offers_jhs", "r.offers_shs",
                *raw_measures, f"{duplicated} AS school_id_rows", *[f"r.{c}" for c in LINEAGE]], 4),
        "  FROM bronze AS r", "), typed AS (", "  SELECT",
        joined(typed, 4), "  FROM normalized AS n", ")", "SELECT", joined(final, 2), "FROM typed AS t;", "",
        f"CREATE OR REPLACE TABLE {clean} USING DELTA AS", "SELECT", joined(clean_columns, 2), f"FROM {source}_classified WHERE quarantine_reasons = '';", "",
        candidate_comment(clean, spec.clean_table), f"ALTER TABLE {clean} OWNER TO `{OWNER_GROUP}`;", "",
        f"CREATE OR REPLACE TABLE {quarantine} USING DELTA AS", "SELECT", joined(quarantine_columns, 2), f"FROM {source}_classified WHERE quarantine_reasons <> '';", "",
        candidate_comment(quarantine, spec.quarantine_table), f"ALTER TABLE {quarantine} OWNER TO `{OWNER_GROUP}`;", ""]
    return "\n".join(lines)


def gate_sql(spec):
    source = spec.source_id
    clean, quarantine = silver_ref(spec.clean_candidate), silver_ref(spec.quarantine_candidate)
    summary = silver_ref(f"{source}_gate_summary_candidate")
    clean_name, quarantine_name = dq_table_name(spec.clean_candidate), dq_table_name(spec.quarantine_candidate)
    reason_counts = [f"COALESCE(COUNT_IF(array_contains(q.quarantine_reasons, {lit(r)})), 0) AS {r}" for r in REASONS]
    check_rows = [
        ("current_batch_present", "FAIL", "current_batches", "> 0", clean_name),
        ("rows_reconcile", "FAIL", "clean_rows + quarantine_rows", "= bronze_rows", clean_name),
        ("school_id_unique", "FAIL", "duplicate_clean_ids", "= 0", clean_name),
        ("lineage_complete", "FAIL", "missing_lineage", "= 0", clean_name),
        ("rows_built_by_this_run", "FAIL", "other_run_rows", "= 0", clean_name),
        ("blank_measures_stay_null", "FAIL", "silver_null_measures", "= bronze_blank_measures", clean_name),
        ("recorded_zero_preserved", "FAIL", "silver_zero_measures", "= bronze_zero_measures", clean_name),
        ("all_blank_measure_retained", "FAIL", "all_blank_measure_non_null", "= 0", clean_name),
        ("all_blank_measure_flagged", "FAIL", "all_blank_measure_unflagged", "= 0", clean_name),
        ("principal_total_discrepancies", "PASS", "principal_discrepancies", ">= 0", clean_name),
    ]
    for name in ("sector", "school_management", "offers_es", "offers_jhs", "offers_shs"):
        check_rows.append((f"labels_mapped_{name}", "FAIL", f"unmapped_{name}", "= 0", clean_name))
    unions = []
    for name, failure, actual, condition, table in check_rows:
        status = f"CASE WHEN {actual} {condition} THEN 'PASS' ELSE '{failure}' END"
        unions.append(f"SELECT batch_id, {lit(table)} AS table_name, {lit(name)} AS check_name, {status} AS status, {lit(condition)} AS expected, CAST({actual} AS STRING) AS actual FROM {summary}")
    for reason in REASONS:
        unions.append(f"SELECT batch_id, {lit(quarantine_name)}, {lit('quarantine_reason_' + reason)}, CASE WHEN {reason} = 0 THEN 'PASS' ELSE 'WARN' END, '0', CAST({reason} AS STRING) FROM {summary}")
    unions.append(f"SELECT batch_id, {lit(quarantine_name)}, 'quarantine_rate', CASE WHEN quarantine_rows = 0 THEN 'PASS' WHEN quarantine_rows * 100 > bronze_rows THEN 'FAIL' ELSE 'WARN' END, '0 (FAIL above 1% of ' || CAST(bronze_rows AS STRING) || ')', CAST(quarantine_rows AS STRING) FROM {summary}")
    union_sql = ("\n  UNION ALL ").join(unions)
    blank_bronze = " + ".join(f"CASE WHEN b.{bq(x)} IS NULL OR b.{bq(x)} = '' THEN 1 ELSE 0 END" for x in spec.measures)
    blank_silver = " + ".join(f"CASE WHEN c.{_name(x)} IS NULL THEN 1 ELSE 0 END" for x in spec.measures)
    zero_bronze = " + ".join(f"CASE WHEN {_typed('b.' + bq(x), spec.integer_max)} = 0 THEN 1 ELSE 0 END" for x in spec.measures)
    zero_silver = " + ".join(f"CASE WHEN c.{_name(x)} = 0 THEN 1 ELSE 0 END" for x in spec.measures)
    accepted = {name: list(spec.categories[name]["labels"]) for name in ("sector", "school_management")}
    accepted.update({name: spec.boolean_true + spec.boolean_false for name in ("offers_es", "offers_jhs", "offers_shs")})
    unmapped = [f"    (SELECT COUNT_IF(b.{name} IS NOT NULL AND b.{name} <> '' AND b.{name} NOT IN ({', '.join(lit(v) for v in values)})) FROM bronze AS b) AS unmapped_{name}"
                for name, values in accepted.items()]
    lines = _header(spec, "Silver gate", "gate", f"90_validate_{spec.clean_table}.sql") + [
        "-- Records every rule count, stops before publishing on FAIL, then publishes quarantine before clean.", "",
        "DECLARE OR REPLACE VARIABLE silver_gate_started_at_utc TIMESTAMP;", "SET VARIABLE silver_gate_started_at_utc = current_timestamp();", "",
        "-- Materialize the wide aggregates once so every check reads the same one-row result.",
        f"CREATE OR REPLACE TABLE {summary} USING DELTA AS", "WITH cur AS (",
        f"  SELECT batch_id FROM {CONTROL}.current_batches WHERE source_id = {lit(source)}", "), bronze AS (",
        f"  SELECT b.* FROM edu_access.`02-bronze`.{spec.bronze_table} AS b JOIN cur ON b.batch_id = cur.batch_id", "), c AS (", f"  SELECT * FROM {clean}", "), q AS (", f"  SELECT * FROM {quarantine}", "), counts AS (", "  SELECT",
        "    (SELECT COUNT(*) FROM cur) AS current_batches,", "    (SELECT COUNT(*) FROM bronze) AS bronze_rows,",
        "    (SELECT COUNT(*) FROM c) AS clean_rows,", "    (SELECT COUNT(*) FROM q) AS quarantine_rows,",
        f"    (SELECT COUNT(*) - COUNT(DISTINCT (school_year, school_id)) FROM c) AS duplicate_clean_ids,",
        f"    (SELECT COALESCE(COUNT_IF({' OR '.join('x.' + v + ' IS NULL' for v in [*LINEAGE, *STAMP])}), 0) FROM c AS x) + (SELECT COALESCE(COUNT_IF({' OR '.join('x.' + v + ' IS NULL' for v in [*LINEAGE, *STAMP])}), 0) FROM q AS x) AS missing_lineage,",
        "    (SELECT COALESCE(COUNT_IF(run_id <> :run_id), 0) FROM c) + (SELECT COALESCE(COUNT_IF(run_id <> :run_id), 0) FROM q) AS other_run_rows,",
        f"    (SELECT SUM({blank_bronze}) FROM bronze AS b LEFT JOIN q ON q.source_sha256 = b.source_sha256 AND q.source_row_number = b.source_row_number WHERE q.source_row_number IS NULL) AS bronze_blank_measures,",
        f"    (SELECT SUM({blank_silver}) FROM c) AS silver_null_measures,",
        f"    (SELECT SUM({zero_bronze}) FROM bronze AS b LEFT JOIN q ON q.source_sha256 = b.source_sha256 AND q.source_row_number = b.source_row_number WHERE q.source_row_number IS NULL) AS bronze_zero_measures,",
        f"    (SELECT SUM({zero_silver}) FROM c) AS silver_zero_measures,",
        f"    (SELECT COUNT_IF({spec.all_blank_measure} IS NOT NULL) FROM c) AS all_blank_measure_non_null,",
        "    (SELECT COUNT_IF(NOT shs_master_teacher_iv_unavailable) FROM c) AS all_blank_measure_unflagged,",
        "    (SELECT COUNT_IF(shs_principal_total_discrepancy) FROM c) AS principal_discrepancies,",
        joined(unmapped, 4), "), quarantine_counts AS (", "  SELECT", joined(reason_counts, 4), "  FROM q", ")",
        "SELECT cur.batch_id, counts.*, quarantine_counts.* FROM cur CROSS JOIN counts CROSS JOIN quarantine_counts;", "",
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
    """Return every data-quality check written by the Personnel gate."""
    return (["current_batch_present", "rows_reconcile", "school_id_unique", "lineage_complete",
             "rows_built_by_this_run", "blank_measures_stay_null", "recorded_zero_preserved",
             "all_blank_measure_retained", "all_blank_measure_flagged", "principal_total_discrepancies",
             "labels_mapped_sector", "labels_mapped_school_management", "labels_mapped_offers_es",
             "labels_mapped_offers_jhs", "labels_mapped_offers_shs", "quarantine_rate"]
            + [f"quarantine_reason_{reason}" for reason in REASONS])


def dictionary_markdown(spec):
    rows = ["| Column | Type | Meaning |", "|---|---|---|",
            "| `school_year` | `STRING` | School year from the approved Bronze batch |",
            "| `school_id` | `STRING` | Six-digit school identifier |",
            "| `sector` / `school_management` | `STRING` | Publisher school classifications mapped to the DepEd enrollment standard sets |",
            "| `offers_es` / `offers_jhs` / `offers_shs` | `BOOLEAN` | Published offering flags |"]
    rows += [f"| `{_name(c)}` | `INT` | Published `{c}` working-personnel count. Blank is `NULL`, recorded zero is `0`. |" for c in spec.measures]
    rows += ["| `shs_school_principal_calculated` | `BIGINT` | Sum of the four published SHS principal grade fields; separate from the publisher total |",
             "| `shs_principal_total_discrepancy` | `BOOLEAN` | Publisher total differs from the calculated total |",
             "| `shs_master_teacher_iv_unavailable` | `BOOLEAN` | The retained publisher field is unavailable in this delivery |",
             "| `personnel_reporting_status` | `STRING` | `out_of_scope`, `no_counts`, `all_zero`, or `has_personnel` |"]
    return "\n".join(["# `deped_personnel_clean`", "", "Generated from the reviewed Personnel contract and mapping. Counts are personnel actually working in public schools, not plantilla positions. Blank values are never changed to zero.", "", *rows, "", "## Quarantine", "", "Invalid identifiers, invalid integers, and values outside the documented public or offered-level scope are retained in `deped_personnel_quarantine` with every reason and the Bronze `batch_id`. Cross-source checks against enrollment belong to Integration (#91), not this source's Silver lane.", ""])
