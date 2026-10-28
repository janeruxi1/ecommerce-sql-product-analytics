-- Case 01 · Checkout funnel by device (GA4 Merchandise Store sample)
--
-- Of all sessions, how many view a product, then add to cart, then begin
-- checkout, then purchase, in that order? Where is the biggest drop, and is
-- it different on mobile?
--
-- A step counts only if it happens at or after the previous step in the same
-- session (a "closed", ordered funnel). The last column counts sessions that
-- purchased without passing every tracked step in order, a tracking check.

WITH params AS (
  SELECT '20201101' AS start_date, '20210131' AS end_date
),

events AS (
  SELECT
    CONCAT(user_pseudo_id, '.',
           CAST((SELECT ep.value.int_value FROM UNNEST(event_params) AS ep
                 WHERE ep.key = 'ga_session_id') AS STRING)) AS session_key,
    device.category AS device,
    event_name,
    event_timestamp AS ts
  FROM {{ga4_events}}, params
  WHERE event_date BETWEEN params.start_date AND params.end_date
),

session_facts AS (
  SELECT
    session_key,
    MIN(device) AS device,                                   -- fixed within a session
    LOGICAL_OR(event_name = 'purchase') AS purchased_any_order
  FROM events
  WHERE session_key IS NOT NULL
  GROUP BY session_key
),

-- Each step: the first time it happens at or after the previous step.
step1 AS (
  SELECT s.session_key, s.device, s.purchased_any_order, MIN(e.ts) AS t1
  FROM session_facts AS s
  LEFT JOIN events AS e
    ON e.session_key = s.session_key AND e.event_name = 'view_item'
  GROUP BY 1, 2, 3
),
step2 AS (
  SELECT s.*, MIN(e.ts) AS t2
  FROM step1 AS s
  LEFT JOIN events AS e
    ON e.session_key = s.session_key AND e.event_name = 'add_to_cart' AND e.ts >= s.t1
  GROUP BY 1, 2, 3, 4
),
step3 AS (
  SELECT s.*, MIN(e.ts) AS t3
  FROM step2 AS s
  LEFT JOIN events AS e
    ON e.session_key = s.session_key AND e.event_name = 'begin_checkout' AND e.ts >= s.t2
  GROUP BY 1, 2, 3, 4, 5
),
step4 AS (
  SELECT s.*, MIN(e.ts) AS t4
  FROM step3 AS s
  LEFT JOIN events AS e
    ON e.session_key = s.session_key AND e.event_name = 'purchase' AND e.ts >= s.t3
  GROUP BY 1, 2, 3, 4, 5, 6
),

counts AS (
  SELECT
    COALESCE(device, 'all devices') AS device_group,
    COUNT(*) AS sessions,
    COUNTIF(t1 IS NOT NULL) AS viewed_item,
    COUNTIF(t2 IS NOT NULL) AS added_to_cart,
    COUNTIF(t3 IS NOT NULL) AS began_checkout,
    COUNTIF(t4 IS NOT NULL) AS purchased,
    COUNTIF(purchased_any_order) AS purchased_any_order
  FROM step4
  GROUP BY ROLLUP (device)
),

-- One row per device x step.
long AS (
  SELECT device_group AS device, 0 AS step_order, 'session' AS step, sessions AS reached, sessions AS previous, sessions AS base,
         purchased_any_order FROM counts
  UNION ALL SELECT device_group, 1, 'view_item', viewed_item, sessions, sessions, purchased_any_order FROM counts
  UNION ALL SELECT device_group, 2, 'add_to_cart', added_to_cart, viewed_item, sessions, purchased_any_order FROM counts
  UNION ALL SELECT device_group, 3, 'begin_checkout', began_checkout, added_to_cart, sessions, purchased_any_order FROM counts
  UNION ALL SELECT device_group, 4, 'purchase', purchased, began_checkout, sessions, purchased_any_order FROM counts
)

SELECT
  device,
  step_order,
  step,
  reached,
  SAFE_DIVIDE(reached, previous) AS rate_from_previous,
  SAFE_DIVIDE(reached, base) AS rate_from_session,
  -- standard error of the step rate, for comparing devices
  SQRT(SAFE_DIVIDE(SAFE_DIVIDE(reached, previous) * (1 - SAFE_DIVIDE(reached, previous)), previous))
    AS se_rate_from_previous,
  purchased_any_order
FROM long
ORDER BY device, step_order
