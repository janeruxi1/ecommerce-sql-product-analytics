"""Every query is valid BigQuery, read-only, and runnable; the runner works end to end (with a fake client)."""
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest
import sqlglot
from conftest import ga4_event, load_ga4, load_thelook, run

from casebook.sql import bigquery_sql, queries, tables_read

ROOT = Path(__file__).resolve().parents[1]


def test_every_case_has_queries_and_a_write_up():
    cases = sorted({q.case for q in queries()})
    assert cases == ["00_data_profile", "01_checkout_funnel", "02_sessionization", "03_cohort_retention",
                     "04_north_star", "05_revenue_drop", "06_ab_readout"]
    for case in cases[1:]:
        assert (ROOT / "cases" / case / "README.md").exists(), case


@pytest.mark.parametrize("q", queries(), ids=lambda q: q.key)
def test_query_is_one_read_only_bigquery_select(q):
    sql = bigquery_sql(q)
    parsed = sqlglot.parse(sql, read="bigquery")
    assert len(parsed) == 1, "one statement per file"
    assert isinstance(parsed[0], (sqlglot.exp.Select, sqlglot.exp.Union)), "SELECT only (the sandbox has no DML)"
    assert "bigquery-public-data" in sql and tables_read(q), "reads only the public tables, via placeholders"
    assert "`" not in q.text, "table names come from placeholders, not hard-coded"


@pytest.mark.parametrize("q", [q for q in queries() if "ga4_events" in tables_read(q)], ids=lambda q: q.key)
def test_ga4_unnests_are_aliased(q):
    """UNNEST(event_params) AS ep: the aliased form is the one that translates to other engines."""
    for unnest in sqlglot.parse_one(bigquery_sql(q), read="bigquery").find_all(sqlglot.exp.Unnest):
        assert unnest.alias or unnest.args.get("alias"), unnest.sql()


def test_profile_runs(con):
    load_ga4(con, [ga4_event("a", 1, "2020-11-01 10:00"), ga4_event("b", None, "2021-01-31 10:00")])
    for table in ["users", "orders", "order_items", "events"]:
        load_thelook(con, table, [{"id": 1, "order_id": 1, "user_id": 1, "created_at": "2023-01-01 00:00",
                                   "sale_price": 1.0, "traffic_source": "Search"}])
    out = run(con, "00_data_profile/profile").set_index("source")
    assert out.loc["ga4 events", "row_count"] == 2
    assert out.loc["ga4 events", "share_null_key"] == 0.5
    assert (out.loc["ga4 events", "first_date"], out.loc["ga4 events", "last_date"]) == ("2020-11-01", "2021-01-31")


class FakeJob:
    def __init__(self, sql, dry_run):
        self.total_bytes_processed = 3 * 10**9 if "ga4" in sql else 10**8
        self.total_bytes_billed = 0 if dry_run else self.total_bytes_processed
        self.slot_millis = 1500

    def result(self):
        row = types.SimpleNamespace(items=lambda: [("source", "ga4 events"), ("first_date", "2020-11-01"),
                                                   ("last_date", "2021-01-31"), ("value", None)])
        return [row]


def load_runner(monkeypatch, tmp_path, max_gb_fail=False):
    calls = []

    class Client:
        def __init__(self, project):
            self.project = project

        def query(self, sql, job_config):
            calls.append(job_config.dry_run)
            return FakeJob(sql, job_config.dry_run)

    class QueryJobConfig:
        def __init__(self, dry_run=False, use_query_cache=True):
            self.dry_run = dry_run

    bq = types.ModuleType("google.cloud.bigquery")
    bq.Client, bq.QueryJobConfig = Client, QueryJobConfig
    google = types.ModuleType("google")
    cloud = types.ModuleType("google.cloud")
    cloud.bigquery = bq
    google.cloud = cloud
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.cloud", cloud)
    monkeypatch.setitem(sys.modules, "google.cloud.bigquery", bq)
    spec = importlib.util.spec_from_file_location("run_bigquery", ROOT / "scripts" / "run_bigquery.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.RESULTS, mod.RECORD = tmp_path, tmp_path / "run_record.json"
    return mod, calls


def test_runner_writes_results_and_record(monkeypatch, tmp_path):
    mod, calls = load_runner(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "argv", ["run_bigquery.py", "--project", "p", "--only", "0"])
    mod.main()
    n = len([q for q in queries() if q.case.startswith("0")])
    assert calls == [True] * n + [False] * n                    # every dry run happens before any real run
    rec = json.loads((tmp_path / "run_record.json").read_text())
    assert rec["totals"]["queries"] == n
    assert (tmp_path / "01_checkout_funnel" / "funnel.csv").read_text().splitlines()[1] == \
        "ga4 events,2020-11-01,2021-01-31,"


def test_runner_stops_before_running_a_too_large_query(monkeypatch, tmp_path):
    mod, calls = load_runner(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "argv", ["run_bigquery.py", "--project", "p", "--max-gb", "1"])
    with pytest.raises(SystemExit):
        mod.main()
    assert False not in calls                                    # nothing ran for real


def test_coverage_warning():
    spec = importlib.util.spec_from_file_location("rb", ROOT / "scripts" / "run_bigquery.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    rows = [{"source": "thelook orders", "first_date": "2019-01-06", "last_date": "2025-06-30"}]
    assert "2025-06-30" in mod.check_coverage(rows)[0]
