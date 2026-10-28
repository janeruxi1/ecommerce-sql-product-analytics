"""Every number quoted in the write-ups matches the BigQuery results in results/.

Each check formats a value from a results file the way the documents quote it and looks for it,
so a re-run that changes a number fails CI until the text is updated.
"""
import json
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "results"
DOCS = {"readme": (ROOT / "README.md").read_text(encoding="utf-8")}
for case in sorted((ROOT / "cases").glob("0[1-6]_*")):
    DOCS[case.name[:2]] = (case / "README.md").read_text(encoding="utf-8")


def csv(name):
    return pd.read_csv(RES / name)


def pct(x, d=1):
    return f"{x * 100:.{d}f}%"


def n(x):
    return f"{int(x):,}"


funnel = csv("01_checkout_funnel/funnel.csv")
allf = funnel[funnel.device == "all devices"].set_index("step")
dev = funnel[funnel.step == "purchase"].set_index("device")
sess = csv("02_sessionization/sessions.csv").set_index("definition")
ga = sess.loc["GA4 ga_session_id", "sessions"]
cm = csv("03_cohort_retention/cohort_matrix.csv")
pooled = cm.groupby("months_since_first").apply(lambda g: g.active_customers.sum() / g.cohort_size.sum())
rbs = csv("03_cohort_retention/retention_by_source.csv").set_index(["channel", "months_since_first"])
ns = csv("04_north_star/north_star_weekly.csv")
ns["year"] = ns.week.str[:4]
yearly = ns.groupby("year").mean(numeric_only=True)
mo = csv("05_revenue_drop/monthly_overview.csv").set_index("month")
jan, dec, nov = mo.loc["2021-01"], mo.loc["2020-12"], mo.loc["2020-11"]
ss = csv("05_revenue_drop/segment_shift_share.csv")
mix = ss.groupby("dimension").mix_effect.sum()
ab = csv("06_ab_readout/ab_readout.csv").set_index("metric")
conv = ab.loc["conversion"]
aa = csv("06_ab_readout/aa_check.csv").iloc[0]
run = json.loads((RES / "run_record.json").read_text())


def kept_revenue_per_purchase(r):
    return r.revenue / (r.purchases * (1 - r.share_purchases_without_revenue))


CHECKS = [
    # 01 funnel
    ("01", n(allf.loc["session", "reached"])), ("01", n(allf.loc["view_item", "reached"])),
    ("01", n(allf.loc["add_to_cart", "reached"])), ("01", n(allf.loc["begin_checkout", "reached"])),
    ("01", n(allf.loc["purchase", "reached"])), ("01", n(allf.loc["purchase", "purchased_any_order"])),
    ("01", pct(allf.loc["view_item", "rate_from_previous"])), ("01", pct(allf.loc["purchase", "rate_from_previous"])),
    ("01", pct(1 - allf.loc["view_item", "rate_from_previous"])),
    ("01", pct(1 - allf.loc["add_to_cart", "rate_from_previous"])),
    ("readme", pct(1 - allf.loc["view_item", "rate_from_previous"])),
    ("01", pct(dev.loc["mobile", "rate_from_previous"])), ("01", pct(dev.loc["desktop", "rate_from_previous"])),
    ("01", pct(1 - allf.loc["purchase", "reached"] / allf.loc["purchase", "purchased_any_order"])),
    ("readme", pct(1 - allf.loc["purchase", "reached"] / allf.loc["purchase", "purchased_any_order"])),
    # 02 sessionization
    ("02", n(ga)), ("readme", n(ga)),
    *[("02", n(sess.loc[f"inactivity > {m} min", "sessions"])) for m in (15, 30, 60)],
    ("02", f"+{pct(sess.loc['inactivity > 15 min', 'sessions'] / ga - 1)}"),
    ("02", f"−{pct(1 - sess.loc['inactivity > 30 min', 'sessions'] / ga)}"),
    ("02", f"−{pct(1 - sess.loc['inactivity > 60 min', 'sessions'] / ga)}"),
    ("02", pct(sess.loc["inactivity > 30 min", "share_matching_one_ga_session"])),
    ("02", pct(sess.loc["inactivity > 30 min", "share_ga_sessions_kept_whole"], 2)),
    # 03 retention
    ("03", n(rbs.loc[("all channels", 1), "customers"])), ("03", n(rbs.loc[("Search", 1), "customers"])),
    *[("03", f"{pct(pooled[k])} in month {k}") for k in (3, 6, 12)],
    ("03", pct(rbs.loc[("Search", 1), "retention"])), ("03", pct(rbs.loc[("Display", 1), "retention"])),
    ("03", f"±{rbs.loc[('Display', 1), 'ci95_half_width'] * 100:.1f} point"),
    # 04 north star
    ("04", f"{yearly.loc['2024', 'active_buyers']:.1f}"), ("04", f"{yearly.loc['2025', 'active_buyers']:.1f}"),
    ("04", f"rose {yearly.loc['2025', 'active_buyers'] / yearly.loc['2024', 'active_buyers'] - 1:.0%}"),
    ("readme", f"+{yearly.loc['2025', 'active_buyers'] / yearly.loc['2024', 'active_buyers'] - 1:.0%}"),
    ("04", f"${yearly.loc['2024', 'net_revenue_per_order']:.2f}"),
    ("04", f"${yearly.loc['2025', 'net_revenue_per_order']:.2f}"),
    ("04", pct(yearly.loc["2024", "cancellation_rate"])), ("04", pct(yearly.loc["2024", "return_rate"])),
    ("04", pct(yearly.loc["2025", "new_buyer_share"])),
    ("04", f"flagged {int(ns[['cancellation_breach', 'return_breach', 'delivery_breach', 'new_buyer_breach']].fillna(False).sum().sum())} of {4 * len(ns)}"),  # noqa: E501
    # 05 revenue drop
    *[("05", f"${r.revenue:,.0f}") for r in (nov, dec, jan)],
    *[("05", pct(r.share_purchases_without_revenue)) for r in (nov, dec, jan)],
    ("05", pct(-jan.revenue_change)), ("readme", f"−{pct(-jan.revenue_change)}"),
    ("05", f"${kept_revenue_per_purchase(dec):.2f} to ${kept_revenue_per_purchase(jan):.2f}"),
    ("05", f"fell {pct(1 - kept_revenue_per_purchase(jan) / kept_revenue_per_purchase(dec))}"),
    ("05", f"conversion explains {jan.ln_from_conversion / jan.ln_revenue_ratio:.0%}"),
    ("05", f"revenue per purchase {jan.ln_from_revenue_per_purchase / jan.ln_revenue_ratio:.0%}"),
    ("05", f"sessions {jan.ln_from_sessions / jan.ln_revenue_ratio:.0%}"),
    ("05", f"{1 - jan.conversion_rate / nov.conversion_rate:.0%} below"),
    ("05", f"−${-mix['device']:,.0f} for device"), ("05", f"−${-mix['country']:,.0f} for country"),
    ("05", f"−${-mix['acquisition medium']:,.0f} for acquisition medium"),
    ("05", f"−${-ss.revenue_change_total.iloc[0]:,.0f}"),
    # 06 A/B
    ("06", n(conv.n_c + conv.n_t)), ("06", pct(conv.control)), ("06", pct(conv.treatment)),
    ("06", f"+{conv['diff'] * 100:.1f} pts (+{conv.ci_low * 100:.1f} to +{conv.ci_high * 100:.1f})"),
    ("readme", f"+{conv['diff'] * 100:.1f}-point"),
    ("06", f"{conv.p_value:.3f}"),
    ("06", f"+{conv.planted_truth * 100:.2f} points"), ("readme", f"+{conv.planted_truth * 100:.2f}"),
    ("06", f"{conv.mde_80pct_power * 100:.1f} points, {conv.mde_80pct_power / conv.planted_truth:.0f} times"),
    ("readme", f"MDE {conv.mde_80pct_power * 100:.1f}"),
    ("06", f"here {conv['diff'] / conv.planted_truth:.0f}-fold"),
    ("06", f"flagged {pct(aa.false_positive_rate)} of {int(aa.splits)}"), ("readme", pct(aa.false_positive_rate)),
    ("06", f"standard deviation\n  {aa.sd_z:.3f}"),
    # run record
    ("readme", f"{run['totals']['gb_processed']:.2f} GB"), ("readme", f"${run['totals']['on_demand_cost_usd']:.2f}"),
]


@pytest.mark.parametrize("doc,expected", CHECKS, ids=[f"{d}:{e}" for d, e in CHECKS])
def test_number_is_quoted(doc, expected):
    assert expected in DOCS[doc], f"{expected!r} not found in {doc}"


def test_results_are_complete():
    from casebook.sql import queries

    for q in queries():
        assert (RES / q.case / f"{q.name}.csv").exists(), q.key
        assert q.key in run["queries"], q.key
