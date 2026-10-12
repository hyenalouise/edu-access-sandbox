"""Where tables live: a thin layer so the same pipeline runs on DuckDB and Databricks.

The SQL in `etl/` is written for Databricks and is the only definition of each
table. Locally, `DuckDBStore` runs those same files after translating the few
differences (backticks, STRING, Delta table properties).

A store does five things: run SQL, query, list a table's columns, stage rows
as a temporary table, and count. Everything else (what to load, MERGE
statements, checks) is shared, so a local test exercises the logic that runs on
Databricks.

DuckDB is not Delta. Each write here is its own statement and commit, never a
multi-table transaction, because Delta commits one table at a time; a test that
passed only because DuckDB wrapped two tables in one transaction would prove
nothing about Databricks. What local runs cannot show (Delta column mapping,
Unity Catalog, volume paths) is listed in docs/governance/decisions.md and confirmed on
Databricks.
"""

import datetime
import json
import re
import tempfile
from pathlib import Path

CATALOG = "edu_access"


def split_statements(sql):
    """Split a SQL file into statements. Our files have no ';' or '--' inside strings."""
    code = "\n".join(line.split("--", 1)[0] for line in sql.splitlines())
    return [s.strip() for s in code.split(";") if s.strip()]


OWNER_STATEMENT = re.compile(r"^\s*ALTER\s+(TABLE|VIEW|SCHEMA)\s+\S+\s+OWNER\s+TO\b", re.IGNORECASE)
DECLARE_VARIABLE = re.compile(r"^\s*DECLARE\s+(OR\s+REPLACE\s+)?VARIABLE\b", re.IGNORECASE)


def databricks_only(statement):
    """Skipped locally. Ownership is a Unity Catalog concept (DuckDB has no owners), and DuckDB
    needs no DECLARE: its SET VARIABLE creates the session variable."""
    return bool(OWNER_STATEMENT.match(statement) or DECLARE_VARIABLE.match(statement))


def to_duckdb(statement):
    """Translate our Databricks SQL to DuckDB. Only constructs used in etl/ are handled."""
    statement = statement.replace("`", '"')
    statement = re.sub(r"(?<![:\w]):([A-Za-z_]\w*)", r"$\1", statement)  # :name parameters
    statement = re.sub(r"\braise_error\(", "error(", statement)
    statement = re.sub(r"\bregexp_like\(", "regexp_matches(", statement)
    # Same name, different meaning: Spark replaces every match, DuckDB only the
    # first unless given 'g'. regexp_replace_all is a macro made in DuckDBStore.
    statement = re.sub(r"\bregexp_replace\(", "regexp_replace_all(", statement)
    statement = re.sub(r"\bsession\.([A-Za-z_]\w*)", r"getvariable('\1')", statement)  # session variables
    statement = re.sub(r"\bcurrent_timestamp\(\)", "(current_timestamp AT TIME ZONE 'UTC')", statement)
    statement = re.sub(r"\bSTRING\b", "VARCHAR", statement)
    statement = re.sub(r"\s+USING\s+DELTA\b", "", statement, flags=re.IGNORECASE)
    statement = re.sub(r"\s*TBLPROPERTIES\s*\((?:[^()']|'[^']*')*\)", "", statement, flags=re.IGNORECASE)
    return statement


# Geometry functions (Silver for hdx_boundaries). DuckDB has them only in its spatial extension, which
# is loaded the first time a statement uses one, so no other source needs it. try_to_geometry is the
# Databricks name (NULL when the text is not a geometry); DuckDB gets it as a macro over GeoJSON.
SPATIAL = re.compile(r"\b(st_[a-z]+|try_to_geometry)\(", re.IGNORECASE)


def table_name(schema, table):
    return f"{CATALOG}.`{schema}`.{table}"


def _json_value(value):
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    return value


class DuckDBStore:
    """Local and test store. `path=None` keeps everything in memory."""

    def __init__(self, path=None):
        import duckdb

        self.con = duckdb.connect()
        target = str(path) if path else ":memory:"
        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.con.execute(f"ATTACH '{target}' AS {CATALOG}")
        self.con.execute(f"USE {CATALOG}")
        self.con.execute("CREATE TEMP MACRO regexp_replace_all(s, p, r) AS regexp_replace(s, p, r, 'g')")
        self._tmp = tempfile.TemporaryDirectory()
        self._spatial = False

    def _load_spatial(self, statement):
        if self._spatial or not SPATIAL.search(statement):
            return
        self.con.execute("INSTALL spatial")
        self.con.execute("LOAD spatial")
        self.con.execute("CREATE TEMP MACRO try_to_geometry(s) AS TRY(ST_GeomFromGeoJSON(s))")
        self._spatial = True

    def close(self):
        self.con.close()
        self._tmp.cleanup()

    def run_file(self, path, params=None):
        for statement in split_statements(Path(path).read_text(encoding="utf-8")):
            used = {k: v for k, v in (params or {}).items() if f":{k}" in statement}
            self.sql(statement, used)

    def sql(self, statement, params=None):
        if databricks_only(statement):
            return
        self._load_spatial(statement)
        self.con.execute(to_duckdb(statement), params or None)

    def query(self, statement, params=None):
        self._load_spatial(statement)
        return self.con.execute(to_duckdb(statement), params or None).fetchall()

    def records(self, statement, params=None):
        self._load_spatial(statement)
        cursor = self.con.execute(to_duckdb(statement), params or None)
        names = [d[0] for d in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchall()]

    def columns(self, schema, table):
        rows = self.con.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_catalog = ? AND table_schema = ? AND table_name = ? ORDER BY ordinal_position",
            [CATALOG, schema, table],
        ).fetchall()
        return [(name, kind) for name, kind in rows]

    def stage(self, name, columns, rows):
        """Create temporary table `name` with `columns` [(name, type)] holding `rows` (dicts).

        Rows go through newline-delimited JSON, which keeps '' and NULL apart;
        CSV staging would blur them.
        """
        names = [c for c, _ in columns]
        if not rows:
            defs = ", ".join(f'"{c}" {kind}' for c, kind in columns)
            self.con.execute(f"CREATE OR REPLACE TEMP TABLE {name} ({defs})")
            return name
        path = Path(self._tmp.name) / f"{name}.json"
        with open(path, "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps({c: _json_value(row[c]) for c in names}, ensure_ascii=False) + "\n")
        spec = ", ".join(f"'{c.replace(chr(39), chr(39) * 2)}': '{kind}'" for c, kind in columns)
        select = ", ".join(f'"{c}"' for c in names)
        self.con.execute(
            f"CREATE OR REPLACE TEMP TABLE {name} AS SELECT {select} FROM "
            f"read_json('{path}', format = 'newline_delimited', maximum_object_size = 1073741824, "
            f"columns = {{{spec}}})"
        )
        return name


class SparkStore:
    """Databricks store: the same SQL through Spark, into Unity Catalog Delta tables.

    Not exercised by local tests (no Spark there); it is confirmed by the
    Databricks run (D-017). Kept to the same five operations as DuckDBStore so
    there is as little Databricks-only code as possible.
    """

    TYPES = {
        "string": "StringType", "int": "IntegerType", "bigint": "LongType",
        "double": "DoubleType", "timestamp": "TimestampType", "boolean": "BooleanType",
    }

    def __init__(self, spark):
        self.spark = spark
        # Timestamps are written as UTC wall-clock values; make Spark read them that way.
        self.spark.conf.set("spark.sql.session.timeZone", "UTC")

    def close(self):
        pass

    def run_file(self, path, params=None):
        for statement in split_statements(Path(path).read_text(encoding="utf-8")):
            used = {k: v for k, v in (params or {}).items() if f":{k}" in statement}
            self.sql(statement, used)

    def sql(self, statement, params=None):
        """Run a statement to completion. spark.sql() runs a SELECT only when its
        result is collected, and the Bronze gate ends with a SELECT that raises on
        FAIL: without collect() the gate would never fail."""
        self.spark.sql(statement, args=params or None).collect()

    def query(self, statement, params=None):
        return [tuple(r) for r in self.spark.sql(statement, args=params or None).collect()]

    def records(self, statement, params=None):
        return [r.asDict() for r in self.spark.sql(statement, args=params or None).collect()]

    def columns(self, schema, table):
        fields = self.spark.table(f"{CATALOG}.`{schema}`.{table}").schema.fields
        return [(f.name, f.dataType.simpleString()) for f in fields]

    def stage(self, name, columns, rows):
        from pyspark.sql import types

        schema = types.StructType([
            types.StructField(c, getattr(types, self.TYPES[kind])(), True) for c, kind in columns
        ])
        names = [c for c, _ in columns]
        frame = self.spark.createDataFrame([tuple(row[c] for c in names) for row in rows], schema)
        frame.createOrReplaceTempView(name)
        return name
