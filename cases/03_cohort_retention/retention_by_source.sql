-- Case 03 · Repeat-purchase retention by acquisition channel (theLook eCommerce)
--
-- The same cohorts as cohort_matrix.sql, pooled across cohorts and split by
-- the channel the customer signed up through. Pooled retention at month k uses
-- only cohorts observed at month k, so later months rest on fewer cohorts.
-- Includes a 95% interval, so small channels are not over-read.

WITH params AS (
  SELECT
    DATE '2023-01-01' AS first_cohort,
    DATE '2024-12-01' AS last_cohort,
    DATE '2025-12-31' AS data_end
),

orders AS (
  SELECT user_id, DATE_TRUNC(DATE(created_at), MONTH) AS order_month
  FROM {{thelook.orders}}
  WHERE status != 'Cancelled'
),

cohorts AS (
  SELECT user_id, MIN(order_month) AS cohort_month
  FROM orders
  GROUP BY user_id
),

in_scope AS (
  SELECT c.user_id, c.cohort_month, u.traffic_source
  FROM cohorts AS c
  JOIN {{thelook.users}} AS u ON u.id = c.user_id
  CROSS JOIN params
  WHERE c.cohort_month BETWEEN params.first_cohort AND params.last_cohort
),

returned AS (
  SELECT DISTINCT
    c.user_id,
    DATE_DIFF(o.order_month, c.cohort_month, MONTH) AS months_since_first
  FROM in_scope AS c
  JOIN orders AS o ON o.user_id = c.user_id
),

customer_months AS (                       -- one row per customer x observed month
  SELECT
    c.traffic_source,
    k AS months_since_first,
    IF(r.user_id IS NULL, 0, 1) AS active
  FROM in_scope AS c
  CROSS JOIN UNNEST([1, 3, 6, 12]) AS k
  CROSS JOIN params
  LEFT JOIN returned AS r
    ON r.user_id = c.user_id AND r.months_since_first = k
  WHERE DATE_ADD(c.cohort_month, INTERVAL k MONTH) <= DATE_TRUNC(params.data_end, MONTH)
)

SELECT
  COALESCE(traffic_source, 'all channels') AS channel,
  months_since_first,
  COUNT(*) AS customers,
  SUM(active) AS active_customers,
  AVG(active) AS retention,
  1.96 * SQRT(AVG(active) * (1 - AVG(active)) / COUNT(*)) AS ci95_half_width
FROM customer_months
GROUP BY GROUPING SETS ((traffic_source, months_since_first), (months_since_first))
ORDER BY channel, months_since_first
