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

From [`results/06_ab_readout/`](../../results/06_ab_readout/) (2,341 logged-in visitors,
1–28 September 2025):

| Metric | Control | Treatment | Difference (95% CI) | p |
|---|---|---|---|---|
| Sample ratio (share in treatment) | 50% | 49.7% | | 0.76 |
| Conversion | 80.2% | 83.8% | +3.6 pts (+0.5 to +6.7) | 0.023 |
| Conversion, CUPED-adjusted | | | +3.6 pts (+0.6 to +6.7) | 0.019 |
| Revenue per visitor | $70.31 | $72.91 | +$2.60 (−$5.07 to +$10.28) | 0.51 |
| Guardrail: visitors with a cancelled order | 17.0% | 13.6% | −3.4 pts | 0.022 |

**The readout says "significant win". It is wrong, and the setup shows why.**

* **The planted truth is +0.26 points.** Only about 20% of these visitors had not bought, so
  planting conversions in 2% of them adds 0.26 points. The interval (+0.5 to +6.7) does not contain
  it: this split is a false positive.
* **The test could never have seen the planted effect.** Its minimum detectable effect at 80% power
  is 4.4 points, 17 times the true effect. When a test is this underpowered, a significant result
  is mostly noise and overstates the effect (here 14-fold). The power check should be read before
  the p-value.
* **The pipeline itself is sound.** The A/A check on the same visitors flagged 4.0% of 200 random
  splits at p < 0.05 (expected 5% ± 3.0), with z-scores of mean −0.002 and standard deviation
  1.005. So the false positive is the 1-in-20 chance any test carries, not a bug. The guardrail
  moving the other way by about the same amount is most likely the same chance imbalance seen
  twice, since a visitor whose order was cancelled is less likely to count as a buyer.
* **A data lesson:** 46% of theLook events have no user id, and the logged-in ones mostly belong to
  people who order, so 80% of "visitors" convert. A realistic test here would randomise sessions,
  including anonymous ones, which would also give it the sample size it lacks.
* **CUPED barely helped** (interval 2.5% narrower): whether a visitor bought in the 90 days before
  says little about whether they buy now in this data.

## Checks and pitfalls

* **The SQL matches an independent implementation.** The test recomputes every difference and
  standard error in pandas on 4,000 simulated visitors and requires agreement to 1e-9; p-values
  are checked against the exact normal p-value.
* **CUPED narrows the interval without moving the estimate** when the pre-period predicts the
  outcome; the test checks both.
* **Planting is a check of the method, not a result.** Here it showed something more useful than a
  clean recovery: a significant result that the known truth, the power calculation and the A/A
  check all mark as noise.
