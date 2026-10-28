-- Case 06 · An A/B test readout written entirely in SQL (theLook eCommerce)
--
-- Scenario: a checkout redesign, tested for four weeks on logged-in visitors.
-- theLook has no real experiment, so the test is simulated on real traffic:
--   * every visitor in the window is split 50/50 by a hash of their user id;
--   * the outcomes are their real orders;
--   * a known effect is planted in the treatment arm: a fixed share of
--     treatment visitors who did not buy are counted as buyers
--     (planted_rate). The readout is then checked against that known truth.
-- The planted conversions are labelled in the output; nothing else is changed.
--
-- The readout: sample-ratio check, conversion with a 95% interval and p-value,
-- the same with CUPED (pre-period orders as the covariate), revenue per visitor
-- (real, no planted effect), a guardrail (visitors with a cancelled order), and
-- the minimum detectable effect the test could see. p-values come from the
-- normal distribution via an erfc approximation (Abramowitz & Stegun 7.1.26,
-- error < 2e-7), so no statistics library is needed.

WITH params AS (
  SELECT
    DATE '2025-09-01' AS start_date,
    DATE '2025-09-28' AS end_date,
    'checkout-redesign' AS salt,
    0.02 AS planted_rate,           -- 2% of treatment non-buyers become buyers
    90 AS pre_period_days
),

visitors AS (
  SELECT DISTINCT e.user_id
  FROM {{thelook.events}} AS e
  CROSS JOIN params
  WHERE e.user_id IS NOT NULL
    AND DATE(e.created_at) BETWEEN params.start_date AND params.end_date
),

assigned AS (
  SELECT
    v.user_id,
    IF(MOD(ABS(FARM_FINGERPRINT(CONCAT(params.salt, ':', CAST(v.user_id AS STRING)))), 2) = 1,
       'treatment', 'control') AS arm,
    -- an independent uniform draw in [0, 1) for planting the effect
    MOD(ABS(FARM_FINGERPRINT(CONCAT('plant:', CAST(v.user_id AS STRING)))), 10000) / 10000 AS u
  FROM visitors AS v
  CROSS JOIN params
),

order_facts AS (
  SELECT
    o.user_id,
    COUNTIF(DATE(o.created_at) BETWEEN p.start_date AND p.end_date AND o.status != 'Cancelled') AS orders_test,
    COUNTIF(DATE(o.created_at) BETWEEN p.start_date AND p.end_date AND o.status = 'Cancelled') AS cancelled_test,
    COUNTIF(DATE(o.created_at) BETWEEN DATE_SUB(p.start_date, INTERVAL p.pre_period_days DAY)
                                   AND DATE_SUB(p.start_date, INTERVAL 1 DAY)
            AND o.status != 'Cancelled') AS orders_pre
  FROM {{thelook.orders}} AS o
  CROSS JOIN params AS p
  GROUP BY o.user_id
),

revenue AS (
  SELECT oi.user_id, SUM(oi.sale_price) AS revenue_test
  FROM {{thelook.order_items}} AS oi
  CROSS JOIN params AS p
  WHERE DATE(oi.created_at) BETWEEN p.start_date AND p.end_date
    AND oi.status != 'Cancelled'
  GROUP BY oi.user_id
),

units AS (
  SELECT
    a.user_id,
    a.arm,
    IF(COALESCE(f.orders_test, 0) > 0, 1, 0) AS bought_real,
    IF(a.arm = 'treatment' AND COALESCE(f.orders_test, 0) = 0 AND a.u < p.planted_rate, 1, 0) AS planted,
    IF(COALESCE(f.cancelled_test, 0) > 0, 1, 0) AS had_cancellation,
    IF(COALESCE(f.orders_pre, 0) > 0, 1, 0) AS bought_pre,
    COALESCE(r.revenue_test, 0) AS revenue
  FROM assigned AS a
  CROSS JOIN params AS p
  LEFT JOIN order_facts AS f ON f.user_id = a.user_id
  LEFT JOIN revenue AS r ON r.user_id = a.user_id
),

units_y AS (
  SELECT *, bought_real + planted AS bought FROM units
),

-- CUPED: one pooled theta = cov(y, x) / var(x), with x = bought before the test
theta AS (
  SELECT SAFE_DIVIDE(COVAR_SAMP(bought, bought_pre), VAR_SAMP(bought_pre)) AS theta,
         AVG(bought_pre) AS mean_x
  FROM units_y
),

by_arm AS (
  SELECT
    u.arm,
    COUNT(*) AS n,
    AVG(u.bought) AS conv, VAR_SAMP(u.bought) AS conv_var,
    AVG(u.bought - t.theta * (u.bought_pre - t.mean_x)) AS cuped, VAR_SAMP(u.bought - t.theta * u.bought_pre) AS cuped_var,
    AVG(u.revenue) AS rev, VAR_SAMP(u.revenue) AS rev_var,
    AVG(u.had_cancellation) AS cancel, VAR_SAMP(u.had_cancellation) AS cancel_var,
    AVG(u.planted) AS planted_share
  FROM units_y AS u
  CROSS JOIN theta AS t
  GROUP BY u.arm
),

wide AS (
  SELECT
    c.n AS n_c, t.n AS n_t,
    c.conv AS conv_c, t.conv AS conv_t, c.conv_var AS conv_var_c, t.conv_var AS conv_var_t,
    c.cuped AS cuped_c, t.cuped AS cuped_t, c.cuped_var AS cuped_var_c, t.cuped_var AS cuped_var_t,
    c.rev AS rev_c, t.rev AS rev_t, c.rev_var AS rev_var_c, t.rev_var AS rev_var_t,
    c.cancel AS cancel_c, t.cancel AS cancel_t, c.cancel_var AS cancel_var_c, t.cancel_var AS cancel_var_t,
    t.planted_share AS planted_effect
  FROM by_arm AS c
  JOIN by_arm AS t ON c.arm = 'control' AND t.arm = 'treatment'
),

metrics AS (
  SELECT 'sample ratio (share in treatment)' AS metric, 1 AS metric_order,
         0.5 AS control, n_t / (n_c + n_t) AS treatment,
         n_t / (n_c + n_t) - 0.5 AS diff,
         SQRT(0.25 / (n_c + n_t)) AS se, CAST(NULL AS FLOAT64) AS planted_truth, n_c, n_t
  FROM wide
  UNION ALL
  SELECT 'conversion', 2, conv_c, conv_t, conv_t - conv_c,
         SQRT(conv_var_c / n_c + conv_var_t / n_t), planted_effect, n_c, n_t FROM wide
  UNION ALL
  SELECT 'conversion, CUPED-adjusted', 3, cuped_c, cuped_t, cuped_t - cuped_c,
         SQRT(cuped_var_c / n_c + cuped_var_t / n_t), planted_effect, n_c, n_t FROM wide
  UNION ALL
  SELECT 'revenue per visitor (USD)', 4, rev_c, rev_t, rev_t - rev_c,
         SQRT(rev_var_c / n_c + rev_var_t / n_t), 0, n_c, n_t FROM wide
  UNION ALL
  SELECT 'guardrail: visitors with a cancelled order', 5, cancel_c, cancel_t, cancel_t - cancel_c,
         SQRT(cancel_var_c / n_c + cancel_var_t / n_t), 0, n_c, n_t FROM wide
),

with_z AS (
  SELECT *, SAFE_DIVIDE(ABS(diff), se) / SQRT(2) AS x FROM metrics
),

with_t AS (
  SELECT *, 1 / (1 + 0.3275911 * x) AS t FROM with_z
)

SELECT
  metric,
  control,
  treatment,
  diff,
  diff - 1.96 * se AS ci_low,
  diff + 1.96 * se AS ci_high,
  SAFE_DIVIDE(diff, se) AS z,
  -- two-sided p = erfc(|z| / sqrt 2)
  t * (0.254829592 + t * (-0.284496736 + t * (1.421413741 + t * (-1.453152027 + t * 1.061405429))))
    * EXP(-x * x) AS p_value,
  planted_truth,
  -- smallest true difference this test would detect 80% of the time (alpha 0.05)
  (1.959964 + 0.841621) * se AS mde_80pct_power,
  n_c,
  n_t
FROM with_t
ORDER BY metric_order
