# 06 · An A/B test readout in SQL

**Question.** A checkout redesign ran for four weeks. Did it raise conversion, did it hurt
anything, and how sure are we? Can the whole readout be produced in the warehouse, without
exporting data to a notebook?

**Why it matters.** Most experiment readouts are a handful of aggregates and a few formulas.
Writing them in SQL makes the readout reproducible next to the data, and a known-truth check
shows the formulas are right before anyone relies on them.

**Data.** theLook eCommerce (synthetic). Logged-in visitors between 1 and 28 September 2025.

## The simulated test

theLook has no real experiment, so the test is simulated on real traffic and labelled as such:

* each visitor is assigned to control or treatment by a hash of their user id (`FARM_FINGERPRINT`
  with a salt), which is stable and independent of anything about the visitor;
* outcomes are the visitors' real orders;
* a **known effect is planted**: 2% of treatment visitors who did not buy are counted as buyers.
  The readout should recover that effect; the planted amount is reported next to the estimate.

## The readout ([`ab_readout.sql`](ab_readout.sql))

| Metric | Method |
|---|---|
| Sample ratio | share in treatment vs 50%, z-test (equivalent to the chi-square SRM check) |
| Conversion (primary) | difference in proportions, 95% interval, two-sided p-value |
| Conversion, CUPED-adjusted | pre-period purchase as covariate, one pooled θ |
| Revenue per visitor | Welch difference in means (no planted effect: should be null) |
| Guardrail: visitors with a cancelled order | difference in proportions |
| Minimum detectable effect | (z₀.₉₇₅ + z₀.₈) × standard error |

p-values use the normal distribution through an erfc approximation (Abramowitz & Stegun
7.1.26, error below 2 × 10⁻⁷), so no statistics library is needed.

## The A/A check ([`aa_check.sql`](aa_check.sql))

The same visitors are split 200 times with different salts and no planted effect. A sound
pipeline flags about 5% of splits at p < 0.05, with z-scores of mean about 0 and standard
deviation about 1.

**SQL techniques:** hashing for randomisation, conditional aggregation, `COVAR_SAMP` /
`VAR_SAMP` for CUPED, self-join of arm aggregates, statistics written as SQL expressions,
`GENERATE_ARRAY` to replicate an analysis 200 times in one query.

## Result

*Filled in from [`results/06_ab_readout/`](../../results/06_ab_readout/) after the BigQuery run.*

## Checks and pitfalls

* **The SQL matches an independent implementation.** The test recomputes every difference and
  standard error in pandas on 4,000 simulated visitors and requires agreement to 1e-9; p-values
  are checked against the exact normal p-value.
* **CUPED narrows the interval without moving the estimate** when the pre-period predicts the
  outcome; the test checks both.
* **Planting is a check of the method, not a result.** The conversion lift reported here is the
  one that was planted; the point is that the readout finds it, with the right uncertainty.
