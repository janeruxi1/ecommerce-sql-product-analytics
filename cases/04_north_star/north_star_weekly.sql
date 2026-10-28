-- Case 04 · A north-star metric with guardrails (theLook eCommerce)
--
-- North star: weekly active buyers, the customers who placed an order that
-- week and kept at least one item (not cancelled, not returned). It grows only
-- when more people buy and keep what they buy, so it cannot be gamed by
-- discount-driven orders that come back.
--
-- It sits at the top of a metric tree that explains net revenue:
--   net revenue = active buyers x orders per buyer x net revenue per order
--
-- Guardrails: order cancellation rate, item return rate, days from order to
-- delivery, and the share of buyers who are new. A guardrail is flagged when
-- the week is more than 3 standard deviations above its own trailing 12-week
-- average (for new-buyer share, below it). Until a week has two prior weeks
-- there is no spread to compare with, and the flag is NULL (no verdict).
--
-- Techniques: item-level rollups joined to orders, first-order dating over the
-- full history, metric-tree ratios, trailing windows with ROWS BETWEEN, and a
-- maturity flag for recent weeks whose returns are still arriving.

WITH params AS (
  SELECT
    DATE '2024-01-01' AS first_week,           -- Mondays
    DATE '2025-12-22' AS last_week,
    DATE '2025-12-31' AS data_end,
    28 AS return_window_days                   -- weeks closer than this to data_end are immature
),

item_totals AS (
  SELECT
    order_id,
    COUNT(*) AS items,
    COUNTIF(status = 'Returned') AS returned_items,
    SUM(IF(status NOT IN ('Cancelled', 'Returned'), sale_price, 0)) AS net_revenue,
    COUNTIF(status NOT IN ('Cancelled', 'Returned')) AS kept_items
  FROM {{thelook.order_items}}
  GROUP BY order_id
),

order_facts AS (
  SELECT
    o.order_id,
    o.user_id,
    o.status,
    DATE(o.created_at) AS order_date,
    DATE_TRUNC(DATE(o.created_at), WEEK(MONDAY)) AS week,
    TIMESTAMP_DIFF(o.delivered_at, o.created_at, HOUR) / 24 AS days_to_deliver,
    i.items,
    i.returned_items,
    i.net_revenue,
    i.kept_items
  FROM {{thelook.orders}} AS o
  JOIN item_totals AS i ON i.order_id = o.order_id
),

first_purchase AS (                            -- over the whole history, not just the window
  SELECT user_id, MIN(week) AS first_week
  FROM order_facts
  WHERE status != 'Cancelled'
  GROUP BY user_id
),

weekly AS (
  SELECT
    o.week,
    COUNT(DISTINCT IF(o.kept_items > 0, o.user_id, NULL)) AS active_buyers,
    COUNTIF(o.kept_items > 0) AS kept_orders,
    SUM(o.net_revenue) AS net_revenue,
    COUNT(*) AS orders,
    SAFE_DIVIDE(COUNTIF(o.status = 'Cancelled'), COUNT(*)) AS cancellation_rate,
    SAFE_DIVIDE(SUM(IF(o.status != 'Cancelled', o.returned_items, 0)),
                SUM(IF(o.status != 'Cancelled', o.items, 0))) AS return_rate,
    AVG(o.days_to_deliver) AS avg_days_to_deliver,
    SAFE_DIVIDE(COUNT(DISTINCT IF(o.kept_items > 0 AND f.first_week = o.week, o.user_id, NULL)),
                COUNT(DISTINCT IF(o.kept_items > 0, o.user_id, NULL))) AS new_buyer_share
  FROM order_facts AS o
  LEFT JOIN first_purchase AS f ON f.user_id = o.user_id
  GROUP BY o.week
),

with_trailing AS (
  SELECT
    w.*,
    SAFE_DIVIDE(w.kept_orders, w.active_buyers) AS orders_per_buyer,
    SAFE_DIVIDE(w.net_revenue, w.kept_orders) AS net_revenue_per_order,
    SAFE_DIVIDE(w.active_buyers - LAG(w.active_buyers, 4) OVER (ORDER BY w.week),
                LAG(w.active_buyers, 4) OVER (ORDER BY w.week)) AS active_buyers_vs_4_weeks_ago,
    AVG(w.cancellation_rate) OVER trailing AS cancellation_rate_avg12,
    STDDEV_SAMP(w.cancellation_rate) OVER trailing AS cancellation_rate_sd12,
    AVG(w.return_rate) OVER trailing AS return_rate_avg12,
    STDDEV_SAMP(w.return_rate) OVER trailing AS return_rate_sd12,
    AVG(w.avg_days_to_deliver) OVER trailing AS days_to_deliver_avg12,
    STDDEV_SAMP(w.avg_days_to_deliver) OVER trailing AS days_to_deliver_sd12,
    AVG(w.new_buyer_share) OVER trailing AS new_buyer_share_avg12,
    STDDEV_SAMP(w.new_buyer_share) OVER trailing AS new_buyer_share_sd12
  FROM weekly AS w
  WINDOW trailing AS (ORDER BY w.week ROWS BETWEEN 12 PRECEDING AND 1 PRECEDING)
)

SELECT
  t.week,
  t.active_buyers,                                           -- north star
  t.orders_per_buyer,
  t.net_revenue_per_order,
  t.net_revenue,
  t.active_buyers_vs_4_weeks_ago,
  t.cancellation_rate,
  t.return_rate,
  t.avg_days_to_deliver,
  t.new_buyer_share,
  t.cancellation_rate > t.cancellation_rate_avg12 + 3 * t.cancellation_rate_sd12 AS cancellation_breach,
  t.return_rate > t.return_rate_avg12 + 3 * t.return_rate_sd12 AS return_breach,
  t.avg_days_to_deliver > t.days_to_deliver_avg12 + 3 * t.days_to_deliver_sd12 AS delivery_breach,
  t.new_buyer_share < t.new_buyer_share_avg12 - 3 * t.new_buyer_share_sd12 AS new_buyer_breach,
  DATE_ADD(t.week, INTERVAL 6 DAY) > DATE_SUB(p.data_end, INTERVAL p.return_window_days DAY)
    AS returns_immature
FROM with_trailing AS t
CROSS JOIN params AS p
WHERE t.week BETWEEN p.first_week AND p.last_week
ORDER BY t.week
