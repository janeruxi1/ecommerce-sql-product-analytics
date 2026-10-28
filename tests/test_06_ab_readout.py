"""Case 06: the SQL A/B readout and A/A check, against a pandas re-implementation."""
import math

import numpy as np
import pytest
from conftest import load_thelook, run

N_USERS = 4000


@pytest.fixture
def ab_data(con):
    rng = np.random.default_rng(7)
    events, orders, items = [], [], []
    oid = iid = 0
    for u in range(1, N_USERS + 1):
        events.append({"id": u, "user_id": u, "session_id": f"s{u}", "event_type": "home",
                       "created_at": f"2025-09-{rng.integers(1, 29):02d} 12:00"})
        bought_before = rng.random() < 0.3
        if bought_before:
            oid += 1
            orders.append({"order_id": oid, "user_id": u, "status": "Complete", "created_at": "2025-07-15 10:00"})
        p_buy = 0.40 if bought_before else 0.10           # the pre-period predicts the outcome: CUPED helps
        if rng.random() < p_buy:
            oid += 1
            status = "Cancelled" if rng.random() < 0.05 else "Complete"
            orders.append({"order_id": oid, "user_id": u, "status": status, "created_at": "2025-09-20 10:00"})
            for _ in range(rng.integers(1, 3)):
                iid += 1
                items.append({"id": iid, "order_id": oid, "user_id": u, "status": status,
                              "sale_price": float(rng.integers(10, 200)), "created_at": "2025-09-20 10:00"})
    # a visitor outside the window and an anonymous event are not in the test
    events.append({"id": 10**6, "user_id": N_USERS + 1, "created_at": "2025-10-05 12:00"})
    events.append({"id": 10**6 + 1, "user_id": None, "created_at": "2025-09-10 12:00"})
    load_thelook(con, "events", events)
    load_thelook(con, "orders", orders)
    load_thelook(con, "order_items", items)


def reference(con) -> dict:
    """The same readout computed in pandas (only the hash comes from the database)."""
    units = con.execute("""
        SELECT u AS user_id,
               ABS(farm_fingerprint('checkout-redesign:' || CAST(u AS VARCHAR))) % 2 AS arm1,
               (ABS(farm_fingerprint('plant:' || CAST(u AS VARCHAR))) % 10000) / 10000 AS draw
        FROM range(1, ?) t(u)""", [N_USERS + 1]).df()
    o = con.execute("SELECT * FROM thelook.orders").df()
    it = con.execute("SELECT * FROM thelook.order_items").df()
    test = o[(o.created_at >= "2025-09-01") & (o.created_at < "2025-09-29")]
    pre = o[(o.created_at >= "2025-06-03") & (o.created_at < "2025-09-01") & (o.status != "Cancelled")]
    units["treat"] = units.arm1 == 1
    units["bought_real"] = units.user_id.isin(test[test.status != "Cancelled"].user_id).astype(int)
    units["planted"] = (units.treat & (units.bought_real == 0) & (units.draw < 0.02)).astype(int)
    units["y"] = units.bought_real + units.planted
    units["x"] = units.user_id.isin(pre.user_id).astype(int)
    rev = it[it.status != "Cancelled"].groupby("user_id").sale_price.sum()
    units["rev"] = units.user_id.map(rev).fillna(0)
    units["cancel"] = units.user_id.isin(test[test.status == "Cancelled"].user_id).astype(int)
    theta = units[["y", "x"]].cov().loc["y", "x"] / units.x.var()
    units["y_adj"] = units.y - theta * (units.x - units.x.mean())
    c, t = units[~units.treat], units[units.treat]

    def diff(col):
        d = t[col].mean() - c[col].mean()
        se = math.sqrt(c[col].var() / len(c) + t[col].var() / len(t))
        return d, se

    return {"n_c": len(c), "n_t": len(t), "conversion": diff("y"), "cuped": diff("y_adj"),
            "revenue": diff("rev"), "cancel": diff("cancel"), "planted": t.planted.mean()}


def test_readout_matches_reference(con, ab_data):
    out = run(con, "06_ab_readout/ab_readout").set_index("metric")
    ref = reference(con)
    assert (out.n_c.iloc[0], out.n_t.iloc[0]) == (ref["n_c"], ref["n_t"])
    for metric, key in [("conversion", "conversion"), ("conversion, CUPED-adjusted", "cuped"),
                        ("revenue per visitor (USD)", "revenue"),
                        ("guardrail: visitors with a cancelled order", "cancel")]:
        d, se = ref[key]
        assert out.loc[metric, "diff"] == pytest.approx(d, abs=1e-12)
        assert out.loc[metric, "ci_high"] - out.loc[metric, "diff"] == pytest.approx(1.96 * se, rel=1e-9)
    assert out.loc["conversion", "planted_truth"] == pytest.approx(ref["planted"])


def test_readout_statistics(con, ab_data):
    out = run(con, "06_ab_readout/ab_readout").set_index("metric")
    # p-values: the erfc approximation agrees with the exact normal p-value
    for z, p in zip(out.z, out.p_value):
        assert p == pytest.approx(math.erfc(abs(z) / math.sqrt(2)), abs=2e-7)
    conv, cuped = out.loc["conversion"], out.loc["conversion, CUPED-adjusted"]
    # CUPED keeps the estimate unbiased but narrows the interval when the pre-period predicts the outcome
    assert (cuped.ci_high - cuped.ci_low) < 0.95 * (conv.ci_high - conv.ci_low)
    # both intervals contain the planted truth (true for this seed; a 95% interval misses 1 time in 20)
    for r in [conv, cuped]:
        assert r.ci_low <= r.planted_truth <= r.ci_high
    # the split is close to 50/50 and the sample-ratio check does not fire
    assert out.loc["sample ratio (share in treatment)", "p_value"] > 0.01
    assert conv.mde_80pct_power == pytest.approx(2.801585 * (conv.ci_high - conv["diff"]) / 1.96, rel=1e-6)


def test_aa_check(con, ab_data):
    out = run(con, "06_ab_readout/aa_check").iloc[0]
    assert out.splits == 200 and out.visitors == N_USERS
    assert 0.0 <= out.false_positive_rate <= 0.05 + 2.5 * out.expected_band_half_width
    assert abs(out.mean_z) < 0.3 and 0.75 < out.sd_z < 1.25
