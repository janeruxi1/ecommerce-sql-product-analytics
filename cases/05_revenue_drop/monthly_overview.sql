-- Case 05 · Why did revenue fall in January? Part 1: the overview (GA4 sample)
--
-- Revenue = sessions x conversion rate x purchases per purchasing session x
-- revenue per purchase. Each month is compared with the month before, and the
-- change is split exactly into the four drivers using logs:
--   ln(R1 / R0) = ln(S1 / S0) + ln(C1 / C0) + ln(P1 / P0) + ln(A1 / A0)
-- Data-quality columns come first in the reading: a "drop" caused by broken
-- tracking (purchases without revenue, missing session ids) is not a business
-- problem.

WITH params AS (
  SELECT '20201101' AS start_date, '20210131' AS end_date
),

events AS (
  SELECT
    FORMAT_DATE('%Y-%m', PARSE_DATE('%Y%m%d', event_date)) AS month,
    CONCAT(user_pseudo_id, '.',
           CAST((SELECT ep.value.int_value FROM UNNEST(event_params) AS ep
                 WHERE ep.key = 'ga_session_id') AS STRING)) AS session_key,
    event_name,
    ecommerce.purchase_revenue_in_usd AS revenue
  FROM {{ga4_events}}, params
  WHERE event_date BETWEEN params.start_date AND params.end_date
),

monthly AS (
  SELECT
    month,
    COUNT(DISTINCT session_key) AS sessions,
    COUNT(DISTINCT IF(event_name = 'purchase', session_key, NULL)) AS purchasing_sessions,
    COUNTIF(event_name = 'purchase') AS purchases,
    SUM(IF(event_name = 'purchase', revenue, 0)) AS revenue,
    SAFE_DIVIDE(COUNTIF(event_name = 'purchase' AND (revenue IS NULL OR revenue = 0)),
                COUNTIF(event_name = 'purchase')) AS share_purchases_without_revenue,
    SAFE_DIVIDE(COUNTIF(session_key IS NULL), COUNT(*)) AS share_events_without_session
  FROM events
  GROUP BY month
),

ratios AS (
  SELECT
    *,
    SAFE_DIVIDE(purchasing_sessions, sessions) AS conversion_rate,
    SAFE_DIVIDE(revenue, purchases) AS revenue_per_purchase,
    SAFE_DIVIDE(purchases, purchasing_sessions) AS purchases_per_purchasing_session
  FROM monthly
)

SELECT
  month,
  sessions,
  purchasing_sessions,
  purchases,
  revenue,
  conversion_rate,
  revenue_per_purchase,
  purchases_per_purchasing_session,
  share_purchases_without_revenue,
  share_events_without_session,
  SAFE_DIVIDE(revenue, LAG(revenue) OVER (ORDER BY month)) - 1 AS revenue_change,
  -- exact log split of the revenue change (the four terms add up to ln_revenue_ratio)
  LN(SAFE_DIVIDE(revenue, LAG(revenue) OVER (ORDER BY month))) AS ln_revenue_ratio,
  LN(SAFE_DIVIDE(sessions, LAG(sessions) OVER (ORDER BY month))) AS ln_from_sessions,
  LN(SAFE_DIVIDE(conversion_rate, LAG(conversion_rate) OVER (ORDER BY month))) AS ln_from_conversion,
  LN(SAFE_DIVIDE(purchases_per_purchasing_session,
                 LAG(purchases_per_purchasing_session) OVER (ORDER BY month))) AS ln_from_purchases_per_session,
  LN(SAFE_DIVIDE(revenue_per_purchase, LAG(revenue_per_purchase) OVER (ORDER BY month))) AS ln_from_revenue_per_purchase
FROM ratios
ORDER BY month
