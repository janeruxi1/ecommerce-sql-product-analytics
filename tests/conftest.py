"""Small tables shaped like the real sources, and helpers to run a case on them.

GA4 events are nested (event_params is an array of key/value structs, device,
geo, traffic_source and ecommerce are structs), so they are built with pyarrow
to get the same shape as the BigQuery export.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from casebook.sql import connect_duckdb, duckdb_sql, query  # noqa: E402

EPOCH = dt.datetime(1970, 1, 1)

PARAM_VALUE = pa.struct([("string_value", pa.string()), ("int_value", pa.int64()),
                         ("float_value", pa.float64()), ("double_value", pa.float64())])
GA4_SCHEMA = pa.schema([
    ("event_date", pa.string()),
    ("event_timestamp", pa.int64()),
    ("event_name", pa.string()),
    ("event_params", pa.list_(pa.struct([("key", pa.string()), ("value", PARAM_VALUE)]))),
    ("user_pseudo_id", pa.string()),
    ("device", pa.struct([("category", pa.string())])),
    ("geo", pa.struct([("country", pa.string())])),
    ("traffic_source", pa.struct([("name", pa.string()), ("medium", pa.string()), ("source", pa.string())])),
    ("ecommerce", pa.struct([("purchase_revenue_in_usd", pa.float64()), ("transaction_id", pa.string())])),
])


def ga4_event(user: str, session: int | None, when: str | dt.datetime, name: str = "page_view", *,
              device: str = "desktop", medium: str = "organic", country: str = "United States",
              revenue: float | None = None) -> dict:
    """One GA4 export row. `when` is 'YYYY-MM-DD HH:MM[:SS[.ffffff]]'."""
    t = pd.Timestamp(when).to_pydatetime() if isinstance(when, str) else when
    params = [{"key": "page_title", "value": {"string_value": "Home", "int_value": None,
                                              "float_value": None, "double_value": None}}]
    if session is not None:
        params.append({"key": "ga_session_id", "value": {"string_value": None, "int_value": session,
                                                         "float_value": None, "double_value": None}})
    return {
        "event_date": t.strftime("%Y%m%d"),
        "event_timestamp": int((t - EPOCH).total_seconds() * 1_000_000),
        "event_name": name,
        "event_params": params,
        "user_pseudo_id": user,
        "device": {"category": device},
        "geo": {"country": country},
        "traffic_source": {"name": "(direct)", "medium": medium, "source": "google"},
        "ecommerce": {"purchase_revenue_in_usd": revenue,
                      "transaction_id": f"T{user}{session}" if name == "purchase" else None},
    }


def load_ga4(con, rows: list[dict]) -> None:
    table = pa.Table.from_pylist(rows, schema=GA4_SCHEMA)
    con.register("ga4_arrow", table)
    con.execute("CREATE OR REPLACE TABLE ga4_events AS SELECT * FROM ga4_arrow")
    con.unregister("ga4_arrow")


THELOOK_COLUMNS = {
    "users": ["id", "first_name", "last_name", "email", "age", "gender", "state", "street_address",
              "postal_code", "city", "country", "latitude", "longitude", "traffic_source", "created_at"],
    "orders": ["order_id", "user_id", "status", "gender", "created_at", "returned_at", "shipped_at",
               "delivered_at", "num_of_item"],
    "order_items": ["id", "order_id", "user_id", "product_id", "inventory_item_id", "status", "created_at",
                    "shipped_at", "delivered_at", "returned_at", "sale_price"],
    "events": ["id", "user_id", "sequence_number", "session_id", "created_at", "ip_address", "city", "state",
               "postal_code", "browser", "traffic_source", "uri", "event_type"],
}
TIMESTAMPS = {"created_at", "returned_at", "shipped_at", "delivered_at"}
INTEGERS = {"id", "user_id", "order_id", "product_id", "inventory_item_id", "sequence_number", "age",
            "num_of_item"}


def load_thelook(con, table: str, rows: list[dict]) -> None:
    """A theLook table with every real column; columns not given are NULL."""
    cols = THELOOK_COLUMNS[table]
    df = pd.DataFrame([{c: r.get(c) for c in cols} for r in rows], columns=cols)
    for c in cols:
        if c in TIMESTAMPS:
            df[c] = pd.to_datetime(df[c])
        elif c in INTEGERS:
            df[c] = df[c].astype("Int64")          # INT64 in BigQuery, NULL-able
    con.register("tl_df", df)
    con.execute(f"CREATE OR REPLACE TABLE thelook.{table} AS SELECT * FROM tl_df")
    con.unregister("tl_df")


@pytest.fixture
def con():
    c = connect_duckdb()
    yield c
    c.close()


def run(con, key: str, replace: dict[str, str] | None = None) -> pd.DataFrame:
    """Run a case query (BigQuery SQL translated to DuckDB) on the test tables.

    `replace` swaps text in the query first, to test with other parameters."""
    text = query(key).text
    for old, new in (replace or {}).items():
        assert old in text, f"{old!r} not in {key}"
        text = text.replace(old, new)
    return con.execute(duckdb_sql(text)).df()
