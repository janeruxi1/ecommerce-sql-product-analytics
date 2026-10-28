# 03 · Cohort retention

**Question.** Of the customers who placed their first order in a given month, what share
ordered again 1, 3, 6 and 12 months later? Does it depend on the channel they came from?

**Why it matters.** Repeat purchase is what makes acquisition spend pay back. Retention by
acquisition channel shows whether a cheap channel brings customers who never return, which an
acquisition-cost report alone would miss.

**Data.** theLook eCommerce (synthetic). First-order cohorts January 2023 – December 2024,
followed to December 2025. Cancelled orders do not count as purchases.

## Approach

1. Cohort = month of the customer's first non-cancelled order (`MIN` over all history, so a
   customer who first bought in 2022 is not mistaken for a 2023 newcomer).
2. Activity = months in which the customer ordered, as `DATE_DIFF(..., MONTH)` from the cohort
   month.
3. A cohort × month grid from `GENERATE_ARRAY(0, 12)`, so months with no returning customer show
   0 instead of disappearing, and only cohort-months fully inside the data are reported.
4. By channel: pooled retention at months 1, 3, 6 and 12 with a 95% interval, using only the
   cohorts observed at that month.

**SQL techniques:** `MIN` for first-touch dating, `DATE_TRUNC`, `DATE_DIFF` in months,
`GENERATE_ARRAY` grids, `LEFT JOIN` to keep zero cells, `GROUPING SETS` for a subtotal row.

## Result

From [`results/03_cohort_retention/`](../../results/03_cohort_retention/) (24 monthly cohorts,
20,195 customers):

* **Few customers come back, and the rate barely changes with time.** Pooled over cohorts, 1.7%
  of customers order again in month 1, 1.6% in month 3, 1.6% in month 6 and 1.8% in month 12. A
  real store's curve usually falls steeply after the first month; this flat curve is a sign of
  theLook's generator, which draws repeat orders at a constant rate.
* **No channel retains detectably better.** Month-1 retention ranges from 1.5% (Search) to 2.4%
  (Display), but Display's 95% interval is ±1.0 point on 826 customers, so every channel overlaps
  the all-channel 1.7%. Search brings 69% of new customers (14,001 of 20,195), so any retention
  programme is mostly a Search-customer programme.
* **What I'd tell a team:** with repeat purchase this rare, growth here comes from acquisition;
  test a second-order incentive before investing in retention by channel.

## Checks and pitfalls

* **Right-censoring.** A December 2024 cohort cannot have a month-12 value before January 2026.
  The test moves the data end to June 2025 and checks that cohort stops at month 6.
* **Cancelled first orders.** A customer whose first order was cancelled joins the cohort of
  their first real purchase; the test covers this.
* **Synthetic data.** theLook is generated, so the level of retention says little about real
  shoppers; the method and the checks are the point.
