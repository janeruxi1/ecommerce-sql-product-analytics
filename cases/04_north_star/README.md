# 04 · A north-star metric with guardrails

**Question.** What single weekly number should an e-commerce team steer by, what explains its
movements, and what must not get worse while it grows?

**Why it matters.** Revenue alone can be pushed up by discounting into orders that come back or
get cancelled. A north star that only grows when customers buy *and keep* what they buy, with
guardrails watched every week, keeps growth honest.

**Data.** theLook eCommerce (synthetic), weekly (Monday-start), January 2024 – December 2025.

## The metric

* **North star: weekly active buyers**, customers who placed an order that week and kept at
  least one item (not cancelled, not returned).
* **Metric tree:** net revenue = active buyers × orders per buyer × net revenue per order. Each
  week's change can be read off the three factors.
* **Guardrails:** cancellation rate, item return rate, days from order to delivery, and the
  share of buyers who are new. A week is flagged when a guardrail is more than 3 standard
  deviations worse than its own trailing 12-week average (no verdict until there are two prior
  weeks).

**SQL techniques:** item-level rollups joined to orders, first-purchase dating over the full
history, `DATE_TRUNC(..., WEEK(MONDAY))`, `LAG` for 4-week change, a named `WINDOW` with
`ROWS BETWEEN 12 PRECEDING AND 1 PRECEDING`, and a maturity flag.

## Result

*Filled in from [`results/04_north_star/north_star_weekly.csv`](../../results/04_north_star/) after
the BigQuery run.*

## Checks and pitfalls

* **Returns arrive late.** The latest weeks look better than they will once returns come in, so
  weeks ending within 28 days of the data end are flagged `returns_immature`; the test checks the
  cutoff.
* **The tree multiplies back.** The test checks active buyers × orders per buyer × net revenue
  per order equals net revenue, week by week, and that a buyer whose whole order was returned is
  not counted as active.
* **Trailing windows exclude the current week**, so a spike cannot hide itself by raising its own
  baseline.
