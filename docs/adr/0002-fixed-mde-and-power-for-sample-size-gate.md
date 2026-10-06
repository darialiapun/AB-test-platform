# Fixed MDE and power for the "enough data" sample-size gate

Before computing a p-value, the service gates on whether each group has reached a required sample size, so it can report "insufficient data" instead of a falsely confident result. That required size depends on an assumed minimum detectable effect (MDE) and statistical power — numbers the brief never specifies, only that alpha is fixed at 0.05. We fixed **relative MDE = 10%** of the control's observed conversion rate and **power = 0.80**, matching the project's existing pattern of hard-coding a single fixed statistical parameter (alpha) rather than making it configurable for v1.

**Status**: accepted

## Considered Options

- **Fixed constants (10% relative MDE, 80% power)** (chosen): deterministic, matches the brief's "fixed alpha" precedent, no API surface for the caller to get wrong.
- **Configurable MDE/power per experiment**: more correct (different experiments care about different effect sizes), but adds a parameter the brief never asked for and that the single-user-type scope (brief.md) doesn't need yet.

## Consequences

The "insufficient data" gate is tuned to detect a 10% relative uplift, not whatever effect size a given experiment owner actually cares about. An experiment designed to detect a 3% uplift will be told it has "enough data" well before it actually does for that smaller effect, because the gate's target is fixed at 10% regardless of what the owner is really looking for. If per-experiment MDE ever becomes a real ask, this constant needs to become a parameter — don't quietly retune it, since `required_sample_size_per_group` is the single source of truth for every "insufficient data" decision in the system.
