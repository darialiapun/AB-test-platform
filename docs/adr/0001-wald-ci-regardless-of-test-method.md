# Wald confidence interval regardless of which significance test is used

The service picks between a two-proportion z-test and Fisher's exact test based on cell counts (Fisher when `np < 5` or `n(1-p) < 5` in either group), specifically because the normal approximation is unreliable for small samples. The confidence interval for the difference in conversion rates, however, is always computed with the Wald formula — the same normal-approximation CI — even in the small-sample cases where Fisher was chosen for exactly that reason. We accept this inconsistency for v1: switching the CI method too (e.g. to Wilson or Clopper-Pearson for small samples) is a second, separate implementation effort, and the brief only specifies a method switch for the p-value test, not the interval.

**Status**: accepted

## Considered Options

- **Wald CI always** (chosen): one formula, one code path, matches the brief's explicit scope (only the point-estimate test method is required to switch). Known weakness: poor coverage near 0%/100% conversion rates, exactly where Fisher is also triggered — so the interval is least trustworthy precisely when the test is most carefully chosen.
- **Switch CI method alongside the test** (Wilson/Clopper-Pearson when Fisher is used): more statistically consistent, but doubles the methods to implement, test, and explain, for a requirement the brief doesn't ask for.

## Consequences

A comparison can report a statistically rigorous Fisher p-value sitting next to a CI that uses a known-weak approximation for the same small sample. If small-sample accuracy becomes a real complaint, revisit this ADR before changing the CI formula — don't just patch it silently, since `wald_confidence_interval` is called for every comparison regardless of method.
