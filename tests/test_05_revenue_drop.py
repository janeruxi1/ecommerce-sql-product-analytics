"""Case 05: the revenue-drop overview and the shift-share split, on hand-built GA4 events."""
import math

import pytest
from conftest import ga4_event as ev
from conftest import load_ga4, run


@pytest.fixture
def drop_events(con):
    rows = [
        # November: 2 desktop sessions, one purchase of 100
        ev("n1", 1, "2020-11-10 10:00"), ev("n1", 1, "2020-11-10 10:05", "purchase", revenue=100),
        ev("n2", 1, "2020-11-11 10:00"),
        # December: desktop 2 sessions (one buys 200), mobile 2 sessions (one buys 100, one purchase lost its revenue)
        ev("d1", 1, "2020-12-10 10:00"), ev("d1", 1, "2020-12-10 10:05", "purchase", revenue=200),
        ev("d2", 1, "2020-12-11 10:00", country="Canada"),
        ev("m1", 1, "2020-12-12 10:00", device="mobile", medium="cpc"),
        ev("m1", 1, "2020-12-12 10:05", "purchase", device="mobile", medium="cpc", revenue=100),
        ev("m2", 1, "2020-12-13 10:00", device="mobile", medium="cpc"),
        ev("m2", 1, "2020-12-13 10:05", "purchase", device="mobile", medium="cpc", revenue=None),
        # January: desktop 1 session (buys 100), mobile 2 sessions (one buys 50)
        ev("j1", 1, "2021-01-10 10:00"), ev("j1", 1, "2021-01-10 10:05", "purchase", revenue=100),
        ev("j2", 1, "2021-01-11 10:00", device="mobile", medium="cpc"),
        ev("j2", 1, "2021-01-11 10:05", "purchase", device="mobile", medium="cpc", revenue=50),
        ev("j3", 1, "2021-01-12 10:00", device="mobile", medium="cpc", country="Canada"),
    ]
    load_ga4(con, rows)


def test_monthly_overview(con, drop_events):
    out = run(con, "05_revenue_drop/monthly_overview").set_index("month")
    dec, jan = out.loc["2020-12"], out.loc["2021-01"]
    assert (dec.sessions, dec.purchases, dec.revenue) == (4, 3, 300)
    assert dec.share_purchases_without_revenue == pytest.approx(1 / 3)
    assert (jan.sessions, jan.purchasing_sessions, jan.revenue) == (3, 2, 150)
    assert jan.revenue_change == pytest.approx(-0.5)
    # the four log terms add up exactly to the log revenue ratio
    parts = jan.ln_from_sessions + jan.ln_from_conversion + jan.ln_from_purchases_per_session \
        + jan.ln_from_revenue_per_purchase
    assert parts == pytest.approx(jan.ln_revenue_ratio) and jan.ln_revenue_ratio == pytest.approx(math.log(0.5))
    assert math.isnan(out.loc["2020-11"].revenue_change)            # no month before November


def test_shift_share_by_device(con, drop_events):
    out = run(con, "05_revenue_drop/segment_shift_share")
    dev = out[out.dimension == "device"].set_index("segment")
    assert dev.loc["desktop", "mix_effect"] == pytest.approx(-50)
    assert dev.loc["mobile", "mix_effect"] == pytest.approx(25)
    assert dev.loc["desktop", "rate_effect"] == pytest.approx(0)
    assert dev.loc["mobile", "rate_effect"] == pytest.approx(-50)
    assert dev.volume_effect_total.iloc[0] == pytest.approx(-75)
    assert dev.revenue_change_total.iloc[0] == pytest.approx(-150)


def test_shift_share_adds_up_in_every_dimension(con, drop_events):
    out = run(con, "05_revenue_drop/segment_shift_share")
    assert set(out.dimension) == {"device", "acquisition medium", "country"}
    for _, g in out.groupby("dimension"):
        total = g.mix_effect.sum() + g.rate_effect.sum() + g.volume_effect_total.iloc[0]
        assert total == pytest.approx(g.revenue_change_total.iloc[0])
        assert g.revenue_change.sum() == pytest.approx(g.revenue_change_total.iloc[0])
