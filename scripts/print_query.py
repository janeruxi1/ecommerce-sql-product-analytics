"""Print a case query as it runs on BigQuery, ready to paste into the console.

    python scripts/print_query.py 03_cohort_retention/cohort_matrix
    python scripts/print_query.py --list
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from casebook.sql import bigquery_sql, queries, query  # noqa: E402

if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    if sys.argv[1] == "--list":
        print("\n".join(q.key for q in queries()))
    else:
        print(bigquery_sql(query(sys.argv[1])))
