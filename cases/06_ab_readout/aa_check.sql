-- Case 06 · A/A check: does the readout cry wolf? (theLook eCommerce)
--
-- Before trusting a readout, run it where there is nothing to find. The same
-- visitors are split 200 times with 200 different salts, with no planted
-- effect, and the conversion test is run on each split. A sound pipeline
-- flags about 5% of them at p < 0.05, and the z-scores have mean about 0 and
-- standard deviation about 1. Many more false alarms would mean the unit of
-- randomisation, the variance formula or the data is wrong.
--
-- Techniques: GENERATE_ARRAY to replicate the analysis 200 times in one
-- query, conditional aggregation per arm, and the same erfc p-value as
-- ab_readout.sql.

WITH params AS (
  SELECT DATE '2025-09-01' AS start_date, DATE '2025-09-28' AS end_date
),

test_visitors AS (
  SELECT DISTINCT e.user_id
  FROM {{thelook.events}} AS e
  CROSS JOIN params
  WHERE e.user_id IS NOT NULL
    AND DATE(e.created_at) BETWEEN params.start_date AND params.end_date
),

buyers AS (
  SELECT
    v.user_id,
    IF(COUNTIF(DATE(o.created_at) BETWEEN p.start_date AND p.end_date
               AND o.status != 'Cancelled') > 0, 1, 0) AS bought
  FROM test_visitors AS v
  CROSS JOIN params AS p
  LEFT JOIN {{thelook.orders}} AS o ON o.user_id = v.user_id
  GROUP BY v.user_id
),

split_units AS (
  SELECT
    s AS split,
    b.bought,
    MOD(ABS(FARM_FINGERPRINT(CONCAT('aa-', CAST(s AS STRING), ':', CAST(b.user_id AS STRING)))), 2) AS arm
  FROM buyers AS b
  CROSS JOIN UNNEST(GENERATE_ARRAY(1, 200)) AS s
),

per_split AS (
  SELECT
    split,
    COUNTIF(arm = 0) AS n_c,
    COUNTIF(arm = 1) AS n_t,
    AVG(IF(arm = 0, bought, NULL)) AS conv_c,
    AVG(IF(arm = 1, bought, NULL)) AS conv_t
  FROM split_units
  GROUP BY split
),

with_z AS (
  SELECT
    *,
    SAFE_DIVIDE(conv_t - conv_c,
                SQRT(conv_c * (1 - conv_c) / n_c + conv_t * (1 - conv_t) / n_t)) AS z
  FROM per_split
),

with_t AS (
  SELECT *, 1 / (1 + 0.3275911 * ABS(z) / SQRT(2)) AS t FROM with_z
),

p_values AS (
  SELECT
    *,
    t * (0.254829592 + t * (-0.284496736 + t * (1.421413741 + t * (-1.453152027 + t * 1.061405429))))
      * EXP(-z * z / 2) AS p_value
  FROM with_t
)

SELECT
  COUNT(*) AS splits,
  AVG(n_c + n_t) AS visitors,
  AVG(conv_c) AS mean_conversion,
  AVG(IF(p_value < 0.05, 1, 0)) AS false_positive_rate,
  -- binomial 95% half-width around 5% for this many splits
  1.96 * SQRT(0.05 * 0.95 / COUNT(*)) AS expected_band_half_width,
  AVG(z) AS mean_z,
  STDDEV_SAMP(z) AS sd_z,
  AVG(IF(p_value < 0.01, 1, 0)) AS share_p_below_01
FROM p_values
