"""Run every case query on BigQuery and save the results.

    python scripts/run_bigquery.py --project YOUR_PROJECT_ID              # all cases
    python scripts/run_bigquery.py --project YOUR_PROJECT_ID --only 03   # one case
    python scripts/run_bigquery.py --project YOUR_PROJECT_ID --dry-run   # bytes only, nothing runs

Each query is first dry-run to see how many bytes it would scan; anything above
--max-gb stops the run before a byte is billed. Results go to
results/<case>/<query>.csv, and results/run_record.json records when each query
ran, how much it scanned and how long it took. The queries only read public
tables, so they work in the free BigQuery sandbox (no billing account).
Setup: docs/RUN_ON_BIGQUERY.md.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from casebook.sql import bigquery_sql, queries  # noqa: E402

RESULTS = ROOT / "results"
RECORD = RESULTS / "run_record.json"
PRICE_PER_TIB = 6.25          # on-demand list price (USD); the sandbox's free 1 TiB a month covers this repo


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def check_coverage(rows: list[dict]) -> list[str]:
    """Warn when a source does not cover the windows the cases assume."""
    need = {"ga4 events": ("2020-11-01", "2021-01-31"),
            "thelook orders": ("2022-12-01", "2025-12-31"),
            "thelook events": ("2025-09-01", "2025-09-28")}
    problems = []
    for r in rows:
        if r["source"] in need:
            first, last = need[r["source"]]
            if r["first_date"] > first or r["last_date"] < last:
                problems.append(f"{r['source']} covers {r['first_date']} to {r['last_date']}, "
                                f"the cases need {first} to {last}")
    return problems


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True, help="your Google Cloud project id (queries are billed/metered here)")
    ap.add_argument("--only", help="run cases whose folder starts with this, e.g. 03")
    ap.add_argument("--max-gb", type=float, default=50.0, help="stop if any query would scan more than this")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from google.cloud import bigquery  # only needed here

    client = bigquery.Client(project=args.project)
    todo = [q for q in queries() if not args.only or q.case.startswith(args.only)]

    # 1. dry run everything first, so nothing is billed if one query is too big
    sizes, errors = {}, {}
    for q in todo:
        try:
            job = client.query(bigquery_sql(q),
                               job_config=bigquery.QueryJobConfig(dry_run=True, use_query_cache=False))
        except Exception as e:  # report every broken query at once, not just the first
            errors[q.key] = str(getattr(e, "message", e)).splitlines()[0]
            print(f"  {q.key}: ERROR {errors[q.key]}")
            continue
        sizes[q.key] = job.total_bytes_processed
        print(f"  {q.key}: would scan {job.total_bytes_processed / 1e9:.2f} GB")
    if errors:
        sys.exit(f"stopped: {len(errors)} quer{'y' if len(errors) == 1 else 'ies'} failed the dry run")
    too_big = [k for k, b in sizes.items() if b > args.max_gb * 1e9]
    if too_big:
        sys.exit(f"stopped: {too_big} would scan more than {args.max_gb} GB (raise --max-gb to allow)")
    print(f"dry run: {sum(sizes.values()) / 1e9:.2f} GB in total for {len(todo)} queries")
    if args.dry_run:
        return

    # 2. run
    record = json.loads(RECORD.read_text()) if RECORD.exists() else {"queries": {}}
    for q in todo:
        t0 = time.time()
        job = client.query(bigquery_sql(q), job_config=bigquery.QueryJobConfig(use_query_cache=False))
        rows = [dict(r.items()) for r in job.result()]
        out = RESULTS / q.case / f"{q.name}.csv"
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else [])
            w.writeheader()
            for r in rows:
                w.writerow({k: ("" if v is None else v) for k, v in r.items()})
        record["queries"][q.key] = {
            "run_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "rows": len(rows),
            "bytes_processed": job.total_bytes_processed,
            "bytes_billed": job.total_bytes_billed,
            "slot_seconds": round((job.slot_millis or 0) / 1000, 1),
            "elapsed_seconds": round(time.time() - t0, 1),
        }
        print(f"  {q.key}: {len(rows)} rows, {job.total_bytes_processed / 1e9:.2f} GB, "
              f"{time.time() - t0:.0f}s -> {rel(out)}")
        if q.case.startswith("00"):
            for problem in check_coverage(rows):
                print(f"  WARNING: {problem}")

    billed = sum(v["bytes_billed"] or 0 for v in record["queries"].values())
    record["totals"] = {
        "queries": len(record["queries"]),
        "gb_processed": round(sum(v["bytes_processed"] for v in record["queries"].values()) / 1e9, 2),
        "gb_billed": round(billed / 1e9, 2),
        "on_demand_cost_usd": round(billed / 1024 ** 4 * PRICE_PER_TIB, 3),
    }
    RECORD.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(f"Saved {rel(RECORD)}: {record['totals']}")


if __name__ == "__main__":
    main()
