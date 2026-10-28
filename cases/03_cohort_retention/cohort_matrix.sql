-- Case 03 · Cohort retention matrix (theLook eCommerce)
--
-- Customers are grouped by the month of their first order (not cancelled).
-- For each cohort, what share ordered again 1, 2, ... 12 months later?
--
-- Only cohort-months that are fully observed are reported: a January 2024
-- cohort is not shown at month 12 unless January 2025 is complete in the data.
-- Techniques: first-touch cohorting with MIN, DATE_DIFF in months, a
-- cohort x month grid from GENERATE_ARRAY so that months with no returning
-- customer show 0 instead of disappearing.

WITH params AS (
  SELECT
    DATE '2023-01-01' AS first_cohort,
    DATE '2024-12-01' AS last_cohort,
    DATE '2025-12-31' AS data_end              -- last day of the last complete month
),

orders AS (
  SELECT
    user_id,
    DATE_TRUNC(DATE(created_at), MONTH) AS order_month
  FROM {{thelook.orders}}
  WHERE status != 'Cancelled'
),

cohorts AS (
  SELECT user_id, MIN(order_month) AS cohort_month
  FROM orders
  GROUP BY user_id
),

in_scope AS (
  SELECT c.*
  FROM cohorts AS c, params
  WHERE c.cohort_month BETWEEN params.first_cohort AND params.last_cohort
),

activity AS (
  SELECT DISTINCT
    c.user_id,
    c.cohort_month,
    DATE_DIFF(o.order_month, c.cohort_month, MONTH) AS months_since_first
  FROM in_scope AS c
  JOIN orders AS o ON o.user_id = c.user_id
),

sizes AS (
  SELECT cohort_month, COUNT(*) AS cohort_size
  FROM in_scope
  GROUP BY cohort_month
),

grid AS (
  SELECT s.cohort_month, s.cohort_size, k AS months_since_first
  FROM sizes AS s
  CROSS JOIN UNNEST(GENERATE_ARRAY(0, 12)) AS k
  CROSS JOIN params
  WHERE DATE_ADD(s.cohort_month, INTERVAL k MONTH) <= DATE_TRUNC(params.data_end, MONTH)
)

SELECT
  g.cohort_month,
  g.months_since_first,
  g.cohort_size,
  COUNT(a.user_id) AS active_customers,
  SAFE_DIVIDE(COUNT(a.user_id), g.cohort_size) AS retention
FROM grid AS g
LEFT JOIN activity AS a
  ON a.cohort_month = g.cohort_month AND a.months_since_first = g.months_since_first
GROUP BY 1, 2, 3
ORDER BY 1, 2
