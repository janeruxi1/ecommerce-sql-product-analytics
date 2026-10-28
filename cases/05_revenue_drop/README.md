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

![Share of the January revenue fall explained by each driver; a quarter is purchases recorded without revenue](../../docs/figures/05_revenue_drop.png)

From [`results/05_revenue_drop/`](../../results/05_revenue_drop/):

| | November 2020 | December 2020 | January 2021 |
|---|---|---|---|
| Sessions | 108,401 | 133,368 | 118,380 |
| Conversion (purchasing sessions / sessions) | 1.49% | 1.59% | 0.94% |
| Revenue per purchase | $70.23 | $65.96 | $47.63 |
| **Revenue** | **$144,260** | **$160,555** | **$57,350** |
| Purchases with no revenue recorded | 2.7% | 3.9% | **24.9%** |

* **Check tracking first.** In January a quarter of purchases (24.9%) carry no revenue, against
  3.9% in December. Counting only purchases with revenue recorded, revenue per purchase fell 7.5%
  ($68.61 to $63.44), not the 28% the raw numbers show. Most of the drop in basket size is a data
  problem, and the first action is to confirm the purchase tag, not to change prices.
* **The real drop is conversion.** Revenue fell 64.3% from December. Split exactly on a log scale,
  conversion explains 51% of the fall, revenue per purchase 32% (24 points of it the missing revenue above),
  sessions 12% and purchases per purchasing session 6%. January's conversion is also 37% below
  November's, so this is more than the end of holiday shopping.
* **It is everywhere, not in one segment.** In the shift-share split the mix effect is close to
  zero in every dimension (−$15 for device, −$22 for country, −$1,626 for acquisition medium, out
  of −$103,205); the rate effect carries the drop in every device, channel and country. A
  site-wide cause (tracking, pricing, or the end of a promotion) is more likely than a problem in
  one segment.

## Checks and pitfalls

* **Is January low, or December high?** Comparing January with November as well as December
  separates the end of holiday shopping from a real decline.
* **The parts add up.** The tests check that the four log terms sum to the log revenue ratio and
  that volume + mix + rate equals the revenue change in every dimension, with hand-computed values
  for a small example.
* **Acquisition, not session, source.** `traffic_source` in the GA4 export is the channel that
  first acquired the user, so the medium split is by acquisition channel.
