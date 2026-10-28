-- Case 05 · Why did revenue fall in January? Part 2: which segments (GA4 sample)
--
-- The month-over-month revenue change, split by segment into three parts that
-- add up exactly to the total change:
--   volume: fewer or more sessions overall, at last month's mix and rates
--   mix:    sessions shifting toward segments that earn less per session
--   rate:   segments earning less per session than they did last month
-- For a segment i with session share w and revenue per session r, and total
-- sessions S (0 = base month, 1 = comparison month):
--   volume = (S1 - S0) x sum(w0 r0)      mix_i = S1 (w1_i - w0_i) r0_i      rate_i = S1 w1_i (r1_i - r0_i)
-- Run once per dimension (device, acquisition medium, country), so each
-- dimension's rows add up to the same total.
--
-- Note: traffic_source in the GA4 export is the channel that first acquired the
-- user, not the source of this session.

WITH params AS (
  SELECT '20201201' AS base_start, '20201231' AS base_end,
         '20210101' AS comp_start, '20210131' AS comp_end,
         10 AS top_countries
),

events AS (
  SELECT
    IF(event_date <= params.base_end, 'base', 'comp') AS period,
    CONCAT(user_pseudo_id, '.',
           CAST((SELECT ep.value.int_value FROM UNNEST(event_params) AS ep
                 WHERE ep.key = 'ga_session_id') AS STRING)) AS session_key,
    device.category AS device,
    traffic_source.medium AS medium,
    geo.country AS country,
    IF(event_name = 'purchase', COALESCE(ecommerce.purchase_revenue_in_usd, 0), 0) AS revenue
  FROM {{ga4_events}}, params
  WHERE event_date BETWEEN params.base_start AND params.comp_end
),

sessions AS (                                  -- one row per session, attributes from its first event
  SELECT
    period,
    session_key,
    MIN(device) AS device,
    MIN(medium) AS medium,
    MIN(country) AS country,
    SUM(revenue) AS revenue
  FROM events
  WHERE session_key IS NOT NULL
  GROUP BY 1, 2
),

top_country AS (
  SELECT country
  FROM sessions, params
  WHERE period = 'base'
  GROUP BY country, params.top_countries
  QUALIFY ROW_NUMBER() OVER (ORDER BY SUM(revenue) DESC, country) <= params.top_countries
),

segmented AS (
  SELECT period, 'device' AS dimension, device AS segment, revenue FROM sessions
  UNION ALL
  SELECT period, 'acquisition medium', medium, revenue FROM sessions
  UNION ALL
  SELECT s.period, 'country',
         IF(t.country IS NULL, 'other countries', s.country), s.revenue
  FROM sessions AS s
  LEFT JOIN top_country AS t ON t.country = s.country
),

by_segment AS (
  SELECT
    dimension,
    COALESCE(segment, '(missing)') AS segment,
    COUNTIF(period = 'base') AS sessions_base,
    COUNTIF(period = 'comp') AS sessions_comp,
    SUM(IF(period = 'base', revenue, 0)) AS revenue_base,
    SUM(IF(period = 'comp', revenue, 0)) AS revenue_comp
  FROM segmented
  GROUP BY 1, 2
),

with_totals AS (
  SELECT
    b.*,
    SUM(sessions_base) OVER (PARTITION BY dimension) AS total_sessions_base,
    SUM(sessions_comp) OVER (PARTITION BY dimension) AS total_sessions_comp,
    SUM(revenue_base) OVER (PARTITION BY dimension) AS total_revenue_base,
    SUM(revenue_comp) OVER (PARTITION BY dimension) AS total_revenue_comp
  FROM by_segment AS b
),

parts AS (
  SELECT
    *,
    SAFE_DIVIDE(sessions_base, total_sessions_base) AS share_base,
    SAFE_DIVIDE(sessions_comp, total_sessions_comp) AS share_comp,
    COALESCE(SAFE_DIVIDE(revenue_base, sessions_base), 0) AS rps_base,
    COALESCE(SAFE_DIVIDE(revenue_comp, sessions_comp), 0) AS rps_comp
  FROM with_totals
)

SELECT
  dimension,
  segment,
  sessions_base,
  sessions_comp,
  revenue_base,
  revenue_comp,
  revenue_comp - revenue_base AS revenue_change,
  share_base,
  share_comp,
  rps_base,
  rps_comp,
  total_sessions_comp * (share_comp - share_base) * rps_base AS mix_effect,
  total_sessions_comp * share_comp * (rps_comp - rps_base) AS rate_effect,
  -- the volume effect belongs to the dimension, not a segment: repeated on each row
  (total_sessions_comp - total_sessions_base) * SAFE_DIVIDE(total_revenue_base, total_sessions_base)
    AS volume_effect_total,
  total_revenue_comp - total_revenue_base AS revenue_change_total
FROM parts
ORDER BY dimension, revenue_change
