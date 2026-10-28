# 01 · Checkout funnel by device

**Question.** Of all sessions on the Google Merchandise Store, how many view a product, add to
cart, begin checkout and purchase, in that order? Where is the biggest drop, and does mobile
lose more shoppers than desktop?

**Why it matters.** A funnel tells a product team which step to work on. The step with the
largest absolute loss is not always the one with the worst rate, and a device gap points to a
specific fix (for example a mobile checkout form) instead of a general one.

**Data.** GA4 sample export, 1 November 2020 – 31 January 2021. One session = one
`user_pseudo_id` + `ga_session_id` pair.

## Approach

1. Pull `ga_session_id` out of the nested `event_params` array with a scalar subquery over
   `UNNEST(event_params)`.
2. Build an **ordered (closed) funnel**: each step counts only if it happens at or after the
   previous step in the same session. A chain of CTEs finds, for each session, the first
   `view_item`, then the first `add_to_cart` after it, and so on.
3. Count sessions at each step per device, with `ROLLUP` adding the all-devices row, and report
   the step rate, the rate from session start, and a standard error for comparing devices.
4. Count sessions that purchased **without** passing every tracked step: a tracking check, since
   GA4 can record a purchase whose earlier steps were not sent.

**SQL techniques:** `UNNEST` of an array of structs, `LEFT JOIN` with an inequality condition,
`GROUP BY ROLLUP`, `COUNTIF`, `SAFE_DIVIDE`, wide-to-long with `UNION ALL`.

## Result

*Filled in from [`results/01_checkout_funnel/funnel.csv`](../../results/01_checkout_funnel/) after
the BigQuery run.*

## Checks and pitfalls

* **Open versus closed funnel.** Counting any `add_to_cart` in a session (open funnel) overstates
  step 2 when shoppers add to cart from a list page without viewing a product. The test
  ([`tests/test_01_02_ga4_sessions.py`](../../tests/test_01_02_ga4_sessions.py)) includes a
  session that adds to cart *before* viewing a product and checks it stops at step 1.
* **Session key.** `ga_session_id` is only unique within a user; the key is the pair.
* **Obfuscated sample.** Google notes the sample's internal consistency is limited, so the
  purchase step is cross-checked against all sessions with a purchase.
