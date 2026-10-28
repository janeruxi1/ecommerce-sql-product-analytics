"""Load the case queries and render them for BigQuery or DuckDB.

Every query is written once, in BigQuery Standard SQL, with two kinds of
placeholder for the source tables:

* ``{{ga4_events}}``  the Google Analytics 4 sample export (daily tables
  ``events_YYYYMMDD``, read through the ``events_*`` wildcard)
* ``{{thelook.<table>}}``  a table of the theLook eCommerce dataset

On BigQuery the placeholders become the public tables. In the tests they
become small DuckDB tables with hand-computed answers, and sqlglot
translates the query to DuckDB's dialect, so the SQL that runs on BigQuery is
the SQL that is tested.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import sqlglot

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "cases"

BIGQUERY_TABLES = {
    "ga4_events": "`bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`",
    "thelook": "`bigquery-public-data.thelook_ecommerce.{table}`",
}
DUCKDB_TABLES = {"ga4_events": "ga4_events", "thelook": "thelook.{table}"}

_PLACEHOLDER = re.compile(r"\{\{\s*(ga4_events|thelook\.(\w+))\s*\}\}")


@dataclass(frozen=True)
class Query:
    case: str          # e.g. "01_checkout_funnel"
    name: str          # file stem, e.g. "funnel_by_device"
    path: Path
    text: str          # BigQuery SQL with placeholders

    @property
    def key(self) -> str:
        return f"{self.case}/{self.name}"


def queries() -> list[Query]:
    """Every case query, in case and file order."""
    out = []
    for path in sorted(CASES.glob("*/*.sql")):
        out.append(Query(path.parent.name, path.stem, path, path.read_text(encoding="utf-8")))
    return out


def query(key: str) -> Query:
    """One query by '<case>/<name>'."""
    for q in queries():
        if q.key == key:
            return q
    raise KeyError(key)


def _render(text: str, tables: dict[str, str]) -> str:
    def sub(m: re.Match) -> str:
        if m.group(1) == "ga4_events":
            return tables["ga4_events"]
        return tables["thelook"].format(table=m.group(2))

    out = _PLACEHOLDER.sub(sub, text)
    if "{{" in out:
        raise ValueError(f"unknown placeholder in: {out[out.index('{{'):][:60]}")
    return out


def bigquery_sql(q: Query | str) -> str:
    """The query exactly as it runs on BigQuery."""
    return _render(q.text if isinstance(q, Query) else q, BIGQUERY_TABLES)


def duckdb_sql(q: Query | str) -> str:
    """The same query translated to DuckDB, against the test tables."""
    text = _render(q.text if isinstance(q, Query) else q, DUCKDB_TABLES)
    return sqlglot.transpile(text, read="bigquery", write="duckdb")[0]


def tables_read(q: Query) -> set[str]:
    """Source tables a query reads, e.g. {'ga4_events', 'thelook.orders'}."""
    return {m.group(1) for m in _PLACEHOLDER.finditer(q.text)}


def connect_duckdb():
    """A DuckDB connection that behaves like BigQuery where the queries rely on it."""
    import duckdb

    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")                      # BigQuery timestamps are UTC
    # BigQuery's FARM_FINGERPRINT has no DuckDB equivalent; any stable 64-bit hash
    # gives a valid (different) random split, which is all the tests rely on.
    con.execute("CREATE MACRO farm_fingerprint(s) AS (hash(s) % 9223372036854775807)::BIGINT")
    con.execute("CREATE SCHEMA thelook")
    return con
