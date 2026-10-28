# 05 · Why did revenue fall in January?

**Question.** Revenue in January 2021 was well below December 2020. Was it fewer visitors, lower
conversion, smaller baskets, a shift in where traffic came from, or broken tracking?

**Why it matters.** "Revenue is down" is the most common question an analytics team gets. The
answer should say how much each driver contributed, in numbers that add up to the total, and rule
out a data problem before anyone changes the product.

**Data.** GA4 sample export, November 2020 – January 2021.

## Approach

1. **Data quality first** ([`monthly_overview.sql`](monthly_overview.sql)): purchases without
   revenue and events without a session id, per month.
2. **Driver split:** revenue = sessions × conversion × purchases per purchasing session × revenue
   per purchase. The month-over-month change splits exactly into those four with logs.
3. **Segment split** ([`segment_shift_share.sql`](segment_shift_share.sql)): for device,
   acquisition medium and country, the change splits into a **volume** effect (fewer sessions
   overall), a **mix** effect (sessions moving to segments that earn less per session) and a
   **rate** effect (segments earning less than before). The three add up exactly to the total
   change in every dimension.

**SQL techniques:** `FORMAT_DATE`/`PARSE_DATE` on GA4's string dates, `LAG` for month-over-month,
`LN` for an additive split, shift-share with `SUM(...) OVER (PARTITION BY ...)`, `QUALIFY` for a
top-10 list, `UNION ALL` to stack dimensions.

## Result

*Filled in from [`results/05_revenue_drop/`](../../results/05_revenue_drop/) after the BigQuery
run.*

## Checks and pitfalls

* **Is January low, or December high?** Comparing January with November as well as December
  separates the end of holiday shopping from a real decline.
* **The parts add up.** The tests check that the four log terms sum to the log revenue ratio and
  that volume + mix + rate equals the revenue change in every dimension, with hand-computed values
  for a small example.
* **Acquisition, not session, source.** `traffic_source` in the GA4 export is the channel that
  first acquired the user, so the medium split is by acquisition channel.
