# 02 · Sessionization from raw events

**Question.** If the event log had no session id, could sessions be rebuilt from timestamps
alone? How close does a 30-minute inactivity rule get to GA4's own sessions, and how much does
the session count depend on that threshold?

**Why it matters.** Many event logs (server logs, app events, theLook's clickstream) do not come
with sessions. Every per-session metric (conversion rate, session length, bounce rate) depends on
the definition, so the definition should be checked rather than assumed.

**Data.** GA4 sample export, 1 November 2020 – 31 January 2021.

## Approach

1. `LAG(event_timestamp)` per user gives the gap to the previous event.
2. A gap above the threshold starts a new session; a running `SUM` of those flags numbers the
   sessions.
3. `CROSS JOIN UNNEST([15, 30, 60])` runs the three thresholds in one pass.
4. Agreement with GA4, both ways: the share of rebuilt sessions that contain exactly one GA4
   session, and the share of GA4 sessions that stay within one rebuilt session.

**SQL techniques:** `LAG`, running `SUM` with a `RANGE` frame, `CROSS JOIN UNNEST` of an array
literal, `COUNT(DISTINCT ...)` inside a mapping table, `UNION ALL` of two definitions.

## Result

*Filled in from [`results/02_sessionization/sessions.csv`](../../results/02_sessionization/) after
the BigQuery run.*

## Checks and pitfalls

* **Ties.** Many GA4 events share a timestamp. With a `ROWS` frame the order among ties is
  arbitrary, so tied events could be split across two sessions. The query uses a `RANGE` frame,
  and the test has three events at the same instant that must stay together.
* **Reference implementation.** The test also rebuilds sessions in pandas and checks the session
  counts match for every threshold.
* **GA4's own rules differ.** GA4 also starts a new session on some campaign changes, and its
  session id is the session start time in seconds, so perfect agreement is not expected.
