"""Cases 03 (cohort retention) and 04 (north star) on hand-built theLook tables."""
import pandas as pd
import pytest
from conftest import load_thelook, run


@pytest.fixture
def cohort_data(con):
    load_thelook(con, "users", [
        {"id": 1, "traffic_source": "Search"}, {"id": 2, "traffic_source": "Search"},
        {"id": 3, "traffic_source": "Search"}, {"id": 4, "traffic_source": "Organic"},
        {"id": 5, "traffic_source": "Email"},
    ])
    load_thelook(con, "orders", [
        # user 1: cohort 2023-01, back in months 1 and 3
        {"order_id": 1, "user_id": 1, "status": "Complete", "created_at": "2023-01-15 10:00"},
        {"order_id": 2, "user_id": 1, "status": "Complete", "created_at": "2023-02-10 10:00"},
        {"order_id": 3, "user_id": 1, "status": "Returned", "created_at": "2023-04-01 10:00"},
        # user 2: first order in 2022-12 -> cohort outside the window
        {"order_id": 4, "user_id": 2, "status": "Complete", "created_at": "2022-12-20 10:00"},
        {"order_id": 5, "user_id": 2, "status": "Complete", "created_at": "2023-01-20 10:00"},
        # user 3: a cancelled order does not start a cohort -> cohort 2023-02
        {"order_id": 6, "user_id": 3, "status": "Cancelled", "created_at": "2023-01-05 10:00"},
        {"order_id": 7, "user_id": 3, "status": "Shipped", "created_at": "2023-02-03 10:00"},
        # user 4: cohort 2024-12, never back
        {"order_id": 8, "user_id": 4, "status": "Complete", "created_at": "2024-12-10 10:00"},
        # user 5: cohort 2023-01, two orders in the same month only
        {"order_id": 9, "user_id": 5, "status": "Complete", "created_at": "2023-01-25 10:00"},
        {"order_id": 10, "user_id": 5, "status": "Complete", "created_at": "2023-01-28 10:00"},
    ])


def test_cohort_matrix(con, cohort_data):
    out = run(con, "03_cohort_retention/cohort_matrix")
    out["cohort"] = out.cohort_month.astype(str).str[:7]
    assert sorted(out.cohort.unique()) == ["2023-01", "2023-02", "2024-12"]
    assert len(out) == 3 * 13                                   # all months observed to 2025-12
    jan = out[out.cohort == "2023-01"].set_index("months_since_first")
    assert jan.loc[0, "cohort_size"] == 2
    assert jan.loc[[0, 1, 2, 3], "retention"].tolist() == [1.0, 0.5, 0.0, 0.5]   # months with nobody show 0


def test_cohort_matrix_drops_unobserved_months(con, cohort_data):
    out = run(con, "03_cohort_retention/cohort_matrix",
              {"DATE '2025-12-31' AS data_end": "DATE '2025-06-30' AS data_end"})
    dec = out[out.cohort_month.astype(str).str[:7] == "2024-12"]
    assert dec.months_since_first.max() == 6                    # 2024-12 + 6 = 2025-06, the last full month


def test_retention_by_source(con, cohort_data):
    out = run(con, "03_cohort_retention/retention_by_source").set_index(["channel", "months_since_first"])
    assert out.loc[("all channels", 1), "customers"] == 4         # users 1, 3, 4, 5
    assert out.loc[("all channels", 1), "retention"] == pytest.approx(1 / 4)
    assert out.loc[("Search", 1), "retention"] == pytest.approx(1 / 2)   # user 1 of users 1 and 3
    assert out.loc[("Search", 3), "active_customers"] == 1
    assert out.loc[("Email", 1), "retention"] == 0
    half = out.loc[("all channels", 1), "ci95_half_width"]
    assert half == pytest.approx(1.96 * (0.25 * 0.75 / 4) ** 0.5)


@pytest.fixture
def ns_data(con):
    load_thelook(con, "orders", [
        # week of 2024-01-01
        {"order_id": 1, "user_id": 1, "status": "Complete", "created_at": "2024-01-01 10:00",
         "delivered_at": "2024-01-04 10:00"},
        {"order_id": 2, "user_id": 2, "status": "Cancelled", "created_at": "2024-01-02 10:00"},
        {"order_id": 3, "user_id": 1, "status": "Complete", "created_at": "2024-01-03 10:00",
         "delivered_at": "2024-01-05 10:00"},
        # week of 2024-01-08
        {"order_id": 4, "user_id": 3, "status": "Returned", "created_at": "2024-01-08 10:00",
         "delivered_at": "2024-01-10 10:00"},
        {"order_id": 5, "user_id": 4, "status": "Shipped", "created_at": "2024-01-09 10:00"},
        {"order_id": 6, "user_id": 1, "status": "Complete", "created_at": "2024-01-14 10:00",
         "delivered_at": "2024-01-20 10:00"},
        # week of 2024-01-15: a spike in cancellations
        {"order_id": 7, "user_id": 5, "status": "Cancelled", "created_at": "2024-01-15 10:00"},
    ])
    item = lambda i, o, u, status, price, ts: {"id": i, "order_id": o, "user_id": u, "status": status,  # noqa: E731
                                                "sale_price": price, "created_at": ts}
    load_thelook(con, "order_items", [
        item(1, 1, 1, "Complete", 50.0, "2024-01-01 10:00"), item(2, 1, 1, "Returned", 30.0, "2024-01-01 10:00"),
        item(3, 2, 2, "Cancelled", 20.0, "2024-01-02 10:00"),
        item(4, 3, 1, "Complete", 10.0, "2024-01-03 10:00"),
        item(5, 4, 3, "Returned", 40.0, "2024-01-08 10:00"),
        item(6, 5, 4, "Shipped", 25.0, "2024-01-09 10:00"),
        item(7, 6, 1, "Complete", 15.0, "2024-01-14 10:00"),
        item(8, 7, 5, "Cancelled", 5.0, "2024-01-15 10:00"),
    ])


def test_north_star_and_tree(con, ns_data):
    out = run(con, "04_north_star/north_star_weekly")
    out["w"] = out.week.astype(str).str[:10]
    w = out.set_index("w")
    w1, w2, w3 = w.loc["2024-01-01"], w.loc["2024-01-08"], w.loc["2024-01-15"]
    # week 1: user 1 kept items in two orders; user 2 only cancelled
    assert w1.active_buyers == 1 and w1.orders_per_buyer == 2 and w1.net_revenue == 60
    assert w1.net_revenue_per_order == 30
    assert w1.cancellation_rate == pytest.approx(1 / 3)
    assert w1.return_rate == pytest.approx(1 / 3)               # 1 of 3 items in non-cancelled orders
    assert w1.new_buyer_share == 1
    assert w1.avg_days_to_deliver == pytest.approx(2.5)          # 3 days and 2 days
    # week 2: user 3 returned everything, so is not an active buyer
    assert w2.active_buyers == 2 and w2.net_revenue == 40
    assert w2.new_buyer_share == pytest.approx(1 / 2)            # user 4 new, user 1 not
    # the metric tree multiplies back to net revenue
    for r in [w1, w2]:
        assert r.active_buyers * r.orders_per_buyer * r.net_revenue_per_order == pytest.approx(r.net_revenue)
    # week 3: cancellations jump far above the trailing average -> guardrail breach
    assert w3.cancellation_rate == 1 and bool(w3.cancellation_breach)
    assert pd.isna(w2.cancellation_breach)                      # one prior week: no spread yet, no verdict
    assert not w.returns_immature.any()


def test_north_star_maturity_flag(con, ns_data):
    out = run(con, "04_north_star/north_star_weekly",
              {"DATE '2025-12-31' AS data_end": "DATE '2024-02-08' AS data_end"})
    flags = dict(zip(out.week.astype(str).str[:10], out.returns_immature))
    # cutoff = 2024-02-08 - 28 days = 2024-01-11: weeks ending after it are immature
    assert flags == {"2024-01-01": False, "2024-01-08": True, "2024-01-15": True}
