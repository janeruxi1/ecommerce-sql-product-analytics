"""Draw the README figures from the BigQuery results in results/.

    python scripts/make_figures.py            # writes docs/figures/*.png

Reads only results/, so the figures always show the recorded run. CI runs this
script and checks every figure is produced and linked from the documents.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "results"
OUT = ROOT / "docs" / "figures"

# Palette roles (light surface); one hue for data, a second only to point at something.
SURFACE, INK, INK_2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
BLUE, ORANGE = "#2a78d6", "#eb6834"

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "font.size": 10, "axes.edgecolor": GRID, "axes.labelcolor": INK_2, "text.color": INK,
    "xtick.color": INK_2, "ytick.color": INK_2, "axes.spines.top": False, "axes.spines.right": False,
    "axes.titlesize": 12, "axes.titleweight": "bold", "axes.titlelocation": "left",
})


def save(fig, name: str) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    fig.savefig(path, dpi=150, bbox_inches="tight", metadata={"Software": None})
    plt.close(fig)
    return path


def funnel() -> Path:
    f = pd.read_csv(RES / "01_checkout_funnel" / "funnel.csv")
    f = f[f.device == "all devices"].sort_values("step_order")
    labels = ["Session", "View a product", "Add to cart", "Begin checkout", "Purchase"]
    fig, ax = plt.subplots(figsize=(7.5, 3.2))
    y = range(len(f))[::-1]
    ax.barh(list(y), f.reached, color=BLUE, height=0.6)
    for yi, (_, r) in zip(y, f.iterrows()):
        note = f"{int(r.reached):,}" + ("" if r.step_order == 0 else f"   ({r.rate_from_previous:.1%} of previous)")
        ax.text(r.reached + f.reached.max() * 0.01, yi, note, va="center", color=INK, fontsize=9)
    ax.set_yticks(list(y), labels)
    ax.set_xlim(0, f.reached.max() * 1.45)
    ax.xaxis.set_visible(False)
    ax.spines["bottom"].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.set_title("Most sessions are lost before checkout, not in it")
    fig.text(0.0, -0.04, "GA4 Merchandise Store sample, Nov 2020 – Jan 2021. Ordered funnel: a step counts only "
             "after the previous one in the same session.", color=INK_2, fontsize=8)
    return save(fig, "01_funnel.png")


def revenue_drop() -> Path:
    m = pd.read_csv(RES / "05_revenue_drop" / "monthly_overview.csv").set_index("month")
    jan, dec = m.loc["2021-01"], m.loc["2020-12"]

    def kept(r):
        return r.revenue / (r.purchases * (1 - r.share_purchases_without_revenue))

    basket_real = math.log(kept(jan) / kept(dec))
    missing = jan.ln_from_revenue_per_purchase - basket_real
    parts = pd.Series({
        "Lower conversion": jan.ln_from_conversion,
        "Purchases recorded\nwithout revenue": missing,
        "Fewer sessions": jan.ln_from_sessions,
        "Smaller baskets\n(purchases with revenue)": basket_real,
        "Fewer purchases\nper buying session": jan.ln_from_purchases_per_session,
    }) / jan.ln_revenue_ratio
    parts = parts.sort_values()
    fig, ax = plt.subplots(figsize=(7.5, 3.4))
    colors = [ORANGE if "without revenue" in k else BLUE for k in parts.index]
    ax.barh(parts.index, parts.values, color=colors, height=0.6)
    for i, v in enumerate(parts.values):
        ax.text(v + 0.01, i, f"{v:.0%}", va="center", color=INK, fontsize=9)
    ax.set_xlim(0, parts.max() * 1.2)
    ax.xaxis.set_visible(False)
    ax.spines["bottom"].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.set_title(f"January revenue fell {-jan.revenue_change:.1%}: what explains it")
    fig.text(0.0, -0.05, "Share of the December-to-January fall in log revenue. Orange: a tracking problem, "
             "not a business one.", color=INK_2, fontsize=8)
    return save(fig, "05_revenue_drop.png")


def north_star() -> Path:
    ns = pd.read_csv(RES / "04_north_star" / "north_star_weekly.csv", parse_dates=["week"])
    flags = ns[["cancellation_breach", "return_breach", "delivery_breach", "new_buyer_breach"]].fillna(False)
    ns["flagged"] = flags.any(axis=1)
    fig, ax = plt.subplots(figsize=(7.5, 3.2))
    ax.plot(ns.week, ns.active_buyers, color=BLUE, lw=2, label="Weekly active buyers")
    f = ns[ns.flagged]
    ax.scatter(f.week, f.active_buyers, s=64, color=ORANGE, edgecolor=SURFACE, linewidth=2, zorder=3,
               label="A guardrail flagged that week")
    for year, g in ns.groupby(ns.week.dt.year):
        mean = g.active_buyers.mean()
        ax.hlines(mean, g.week.min(), g.week.max(), color=INK_2, lw=1, ls=(0, (3, 3)))
        ax.text(g.week.min(), mean + 8, f"{year} average {mean:.0f}", color=INK_2, fontsize=8)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_ylim(0, ns.active_buyers.max() * 1.15)
    ax.set_ylabel("Buyers who kept an item")
    ax.legend(loc="lower right", frameon=False, fontsize=8)
    ax.set_title("North star: active buyers grew; guardrails rarely flagged")
    fig.text(0.0, -0.04, "theLook eCommerce (synthetic), weeks starting Monday, 2024–2025.", color=INK_2, fontsize=8)
    return save(fig, "04_north_star.png")


def ab_readout() -> Path:
    ab = pd.read_csv(RES / "06_ab_readout" / "ab_readout.csv").set_index("metric")
    rows = ["conversion", "conversion, CUPED-adjusted"]
    truth = ab.loc["conversion", "planted_truth"] * 100
    mde = ab.loc["conversion", "mde_80pct_power"] * 100
    fig, ax = plt.subplots(figsize=(7.5, 2.6))
    for i, metric in enumerate(rows[::-1]):
        r = ab.loc[metric]
        ax.plot([r.ci_low * 100, r.ci_high * 100], [i, i], color=BLUE, lw=2)
        ax.scatter([r["diff"] * 100], [i], s=64, color=BLUE, edgecolor=SURFACE, linewidth=2, zorder=3)
        ax.text(r.ci_high * 100 + 0.15, i, f"+{r['diff'] * 100:.1f} pts, p = {r.p_value:.3f}", va="center",
                fontsize=9, color=INK)
    ax.axvline(0, color=INK_2, lw=1)
    ax.axvline(truth, color=ORANGE, lw=2)
    ax.text(truth + 0.1, 1.45, f"planted truth +{truth:.2f}", color=INK, fontsize=8)
    ax.axvspan(-mde, mde, color=GRID, alpha=0.6, lw=0)
    ax.text(truth + 0.15, -0.55, f"shaded: within the {mde:.1f}-pt minimum detectable effect", color=INK_2,
            fontsize=8)
    ax.set_yticks([0, 1], ["CUPED-adjusted", "Conversion"])
    ax.tick_params(axis="y", length=0)
    ax.set_ylim(-0.8, 1.7)
    ax.set_xlim(-mde - 0.5, 10.5)
    ax.set_xlabel("Treatment minus control, percentage points (95% interval)")
    ax.set_title("A 'significant' win that misses the true effect")
    return save(fig, "06_ab_readout.png")


FIGURES = [funnel, revenue_drop, north_star, ab_readout]

if __name__ == "__main__":
    if len(sys.argv) > 1:
        OUT = Path(sys.argv[1]).resolve()
    for make in FIGURES:
        path = make()
        print(f"Saved {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}")
