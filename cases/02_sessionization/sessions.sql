-- Case 02 · Sessionization from raw events (GA4 Merchandise Store sample)
--
-- Rebuild sessions from event timestamps alone: a new session starts when a
-- user has been inactive for longer than a threshold. Compare the result with
-- the session id GA4 assigns (ga_session_id), and show how the session count
-- moves with the threshold (15, 30, 60 minutes).
--
-- Techniques: LAG to find the gap to the previous event, a running SUM of
-- "new session" flags to number sessions, CROSS JOIN UNNEST to run several
-- thresholds in one pass, and a two-way mapping to measure agreement.
--
-- The running SUM uses a RANGE frame, not ROWS: many GA4 events share a
-- timestamp, and with ROWS the order among ties is arbitrary, so tied events
-- could land in different sessions. RANGE gives every tied event the same
-- session number.

WITH params AS (
  SELECT '20201101' AS start_date, '20210131' AS end_date
),

ga4 AS (
  SELECT
    user_pseudo_id,
    event_timestamp AS ts,                                   -- microseconds
    (SELECT ep.value.int_value FROM UNNEST(event_params) AS ep
     WHERE ep.key = 'ga_session_id') AS ga_session_id
  FROM {{ga4_events}}, params
  WHERE event_date BETWEEN params.start_date AND params.end_date
),

with_gap AS (
  SELECT
    *,
    ts - LAG(ts) OVER (PARTITION BY user_pseudo_id ORDER BY ts) AS gap_us
  FROM ga4
),

derived AS (
  SELECT
    gap_minutes,
    e.user_pseudo_id,
    e.ts,
    e.ga_session_id,
    SUM(IF(e.gap_us IS NULL OR e.gap_us > CAST(gap_minutes AS INT64) * 60 * 1000000, 1, 0))
      OVER (PARTITION BY gap_minutes, e.user_pseudo_id ORDER BY e.ts
            RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS session_n
  FROM with_gap AS e
  CROSS JOIN UNNEST([15, 30, 60]) AS gap_minutes
),

derived_session_facts AS (
  SELECT
    gap_minutes,
    user_pseudo_id,
    session_n,
    COUNT(*) AS events,
    (MAX(ts) - MIN(ts)) / 1000000 AS duration_s,
    COUNT(DISTINCT ga_session_id) AS ga_sessions_inside
  FROM derived
  GROUP BY 1, 2, 3
),

-- For each GA session: how many derived sessions does it fall into?
ga_split AS (
  SELECT gap_minutes, user_pseudo_id, ga_session_id, COUNT(DISTINCT session_n) AS derived_sessions
  FROM derived
  WHERE ga_session_id IS NOT NULL
  GROUP BY 1, 2, 3
),

ga_sessions AS (
  SELECT
    user_pseudo_id,
    ga_session_id,
    COUNT(*) AS events,
    (MAX(ts) - MIN(ts)) / 1000000 AS duration_s
  FROM ga4
  WHERE ga_session_id IS NOT NULL
  GROUP BY 1, 2
),

by_threshold AS (
  SELECT
    d.gap_minutes,
    COUNT(*) AS sessions,
    AVG(d.events) AS events_per_session,
    AVG(d.duration_s) AS avg_duration_s,
    AVG(IF(d.events = 1, 1, 0)) AS share_one_event,
    AVG(IF(d.ga_sessions_inside = 1, 1, 0)) AS share_matching_one_ga_session,
    ANY_VALUE(g.share_ga_in_one) AS share_ga_sessions_kept_whole
  FROM derived_session_facts AS d
  JOIN (SELECT gap_minutes, AVG(IF(derived_sessions = 1, 1, 0)) AS share_ga_in_one
        FROM ga_split GROUP BY 1) AS g
    ON g.gap_minutes = d.gap_minutes
  GROUP BY 1
)

SELECT
  CONCAT('inactivity > ', CAST(gap_minutes AS STRING), ' min') AS definition,
  gap_minutes,
  sessions,
  events_per_session,
  avg_duration_s,
  share_one_event,
  share_matching_one_ga_session,
  share_ga_sessions_kept_whole
FROM by_threshold
UNION ALL
SELECT
  'GA4 ga_session_id' AS definition,
  NULL AS gap_minutes,
  COUNT(*) AS sessions,
  AVG(events) AS events_per_session,
  AVG(duration_s) AS avg_duration_s,
  AVG(IF(events = 1, 1, 0)) AS share_one_event,
  NULL AS share_matching_one_ga_session,
  NULL AS share_ga_sessions_kept_whole
FROM ga_sessions
ORDER BY gap_minutes NULLS FIRST
