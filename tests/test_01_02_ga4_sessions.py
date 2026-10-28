"""Cases 01 (funnel) and 02 (sessionization) on hand-built GA4 events."""
import pandas as pd
import pytest
from conftest import ga4_event as ev
from conftest import load_ga4, run


@pytest.fixture
def funnel_events(con):
    d = "2020-12-15 10:"
    rows = [
        # A, desktop: every step in order -> reaches purchase
        ev("a", 1, d + "00", "view_item"), ev("a", 1, d + "01", "add_to_cart"),
        ev("a", 1, d + "02", "begin_checkout"), ev("a", 1, d + "03", "purchase", revenue=50),
        # B, desktop: view then cart
        ev("b", 1, d + "00", "view_item"), ev("b", 1, d + "01", "add_to_cart"),
        # C, mobile: cart BEFORE view, never after -> reaches view_item only
        ev("c", 1, d + "00", "add_to_cart", device="mobile"), ev("c", 1, d + "05", "view_item", device="mobile"),
        # D, mobile: view, cart, checkout
        ev("d", 1, d + "00", "view_item", device="mobile"), ev("d", 1, d + "01", "add_to_cart", device="mobile"),
        ev("d", 1, d + "02", "begin_checkout", device="mobile"),
        # E, mobile: a purchase with no tracked steps before it
        ev("e", 1, d + "00", "purchase", device="mobile", revenue=20),
        # F, desktop: browsing only
        ev("f", 1, d + "00", "page_view"),
        # an event without a session id is ignored
        ev("g", None, d + "00", "view_item"),
        # outside the date window
        ev("h", 1, "2021-02-01 10:00", "view_item"),
    ]
    load_ga4(con, rows)


def test_ordered_funnel_counts(con, funnel_events):
    out = run(con, "01_checkout_funnel/funnel")
    reached = {(r.device, r.step): r.reached for r in out.itertuples()}
    assert [reached[("all devices", s)] for s in
            ["session", "view_item", "add_to_cart", "begin_checkout", "purchase"]] == [6, 4, 3, 2, 1]
    assert [reached[("desktop", s)] for s in
            ["session", "view_item", "add_to_cart", "begin_checkout", "purchase"]] == [3, 2, 2, 1, 1]
    assert [reached[("mobile", s)] for s in
            ["session", "view_item", "add_to_cart", "begin_checkout", "purchase"]] == [3, 2, 1, 1, 0]
    total = out[out.device == "all devices"].set_index("step")
    assert total.loc["add_to_cart", "rate_from_previous"] == pytest.approx(3 / 4)
    assert total.loc["purchase", "rate_from_session"] == pytest.approx(1 / 6)
    assert total.loc["purchase", "purchased_any_order"] == 2      # A, and E with no steps
    se = total.loc["add_to_cart", "se_rate_from_previous"]
    assert se == pytest.approx((0.75 * 0.25 / 4) ** 0.5)


@pytest.fixture
def session_events(con):
    rows = []
    # u1: gaps of 10, 40, 5 and 65 minutes; GA sessions s1 = {0, 10}, s2 = {50, 55}, s3 = {120}
    for minute, sid in [(0, 1), (10, 1), (50, 2), (55, 2), (120, 3)]:
        rows.append(ev("u1", sid, pd.Timestamp("2020-12-01 08:00") + pd.Timedelta(minutes=minute)))
    # u2: three events with the SAME timestamp, then one 100 minutes later
    for minute, sid in [(0, 7), (0, 7), (0, 7), (100, 8)]:
        rows.append(ev("u2", sid, pd.Timestamp("2020-12-01 09:00") + pd.Timedelta(minutes=minute)))
    # u3: one GA session with a 40-minute pause inside it
    for minute in [0, 40]:
        rows.append(ev("u3", 9, pd.Timestamp("2020-12-01 10:00") + pd.Timedelta(minutes=minute)))
    load_ga4(con, rows)


def reference_sessions(events: pd.DataFrame, gap_minutes: int) -> pd.DataFrame:
    """Independent pandas implementation: session number per event."""
    e = events.sort_values(["user", "ts"]).copy()
    gap = e.groupby("user")["ts"].diff()
    e["new"] = gap.isna() | (gap > pd.Timedelta(minutes=gap_minutes))
    # ties: an event at the same time as the previous one is never a new session
    e["session"] = e.groupby("user")["new"].cumsum()
    return e


def test_sessionization_by_threshold(con, session_events):
    out = run(con, "02_sessionization/sessions").set_index("definition")
    t30 = out.loc["inactivity > 30 min"]
    t60 = out.loc["inactivity > 60 min"]
    # 30 min: u1 -> 3, u2 -> 2 (the tied events stay together), u3 -> 2 (split by the 40-min pause)
    assert t30.sessions == 7
    assert out.loc["inactivity > 15 min"].sessions == 7
    # 60 min: u1 -> 2 (the 40-min gap no longer splits), u2 -> 2, u3 -> 1
    assert t60.sessions == 5
    assert t60.events_per_session == pytest.approx(11 / 5)
    # u1's first 60-min session holds two GA sessions; every other derived session holds one
    assert t60.share_matching_one_ga_session == pytest.approx(4 / 5)
    # at 30 min, u3's GA session is split in two: 5 of the 6 GA sessions stay whole
    assert t30.share_ga_sessions_kept_whole == pytest.approx(5 / 6)
    assert t60.share_ga_sessions_kept_whole == pytest.approx(1.0)
    # durations at 30 min: 600 s, 300 s and five single-instant sessions
    assert t30.avg_duration_s == pytest.approx(900 / 7)
    assert t30.share_one_event == pytest.approx(4 / 7)
    ga = out.loc["GA4 ga_session_id"]
    assert ga.sessions == 6
    assert ga.avg_duration_s == pytest.approx((600 + 300 + 0 + 0 + 0 + 2400) / 6)


def test_sessionization_matches_reference(con, session_events):
    events = con.execute("SELECT user_pseudo_id AS user, make_timestamp(event_timestamp) AS ts "
                         "FROM ga4_events").df()
    out = run(con, "02_sessionization/sessions").set_index("gap_minutes")
    for gap in [15, 30, 60]:
        ref = reference_sessions(events, gap)
        assert out.loc[gap, "sessions"] == ref.groupby(["user", "session"]).ngroups
