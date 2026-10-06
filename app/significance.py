import math
from datetime import datetime, timezone
from typing import Optional

from scipy.stats import fisher_exact, norm

ALPHA = 0.05
POWER = 0.80
RELATIVE_MDE = 0.10
MIN_CELL_COUNT = 5
MIN_ELAPSED_DAYS_FOR_RATE_ESTIMATE = 1 / 24  # 1 hour

_Z_ALPHA = norm.ppf(1 - ALPHA / 2)
_Z_BETA = norm.ppf(POWER)


def required_sample_size_per_group(baseline_rate: float) -> Optional[int]:
    """Required users per group (power=0.8, alpha=0.05, two-sided) to detect a
    RELATIVE_MDE relative uplift over baseline_rate. None if not estimable
    (baseline_rate is 0, so the target effect size is undefined)."""
    if baseline_rate <= 0:
        return None
    target_rate = min(baseline_rate * (1 + RELATIVE_MDE), 1.0)
    effect = target_rate - baseline_rate
    if effect <= 0:
        return None
    variance = baseline_rate * (1 - baseline_rate) + target_rate * (1 - target_rate)
    n = ((_Z_ALPHA + _Z_BETA) ** 2 * variance) / (effect ** 2)
    return int(math.ceil(n))


def should_use_fisher(x1: int, n1: int, x2: int, n2: int) -> bool:
    for successes, n in ((x1, n1), (x2, n2)):
        if successes < MIN_CELL_COUNT or (n - successes) < MIN_CELL_COUNT:
            return True
    return False


def two_proportion_ztest(x1: int, n1: int, x2: int, n2: int) -> float:
    """Two-sided pooled two-proportion z-test p-value."""
    p_pool = (x1 + x2) / (n1 + n2)
    se = math.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
    if se == 0:
        return 1.0
    p1, p2 = x1 / n1, x2 / n2
    z = (p2 - p1) / se
    return float(2 * (1 - norm.cdf(abs(z))))


def fisher_exact_pvalue(x1: int, n1: int, x2: int, n2: int) -> float:
    table = [[x1, n1 - x1], [x2, n2 - x2]]
    _, p_value = fisher_exact(table, alternative="two-sided")
    return float(p_value)


def wald_confidence_interval(x1: int, n1: int, x2: int, n2: int, alpha: float = ALPHA) -> tuple[float, float]:
    """95% Wald CI for the difference in conversion rate (variant - control)."""
    p1, p2 = x1 / n1, x2 / n2
    diff = p2 - p1
    se = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    z = float(norm.ppf(1 - alpha / 2))
    margin = z * se
    return diff - margin, diff + margin


def benjamini_hochberg(p_values: list[float]) -> list[float]:
    """Benjamini-Hochberg FDR-adjusted p-values, in the same order as input."""
    m = len(p_values)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: p_values[i])
    adjusted_sorted = [0.0] * m
    running_min = 1.0
    for rank in range(m, 0, -1):
        idx = order[rank - 1]
        q = float(p_values[idx]) * m / rank
        running_min = min(running_min, q)
        adjusted_sorted[rank - 1] = min(running_min, 1.0)
    result = [0.0] * m
    for rank in range(m):
        result[order[rank]] = adjusted_sorted[rank]
    return result


def _rate_per_day(users: int, elapsed_days: float) -> float:
    if users > 0 and elapsed_days >= MIN_ELAPSED_DAYS_FOR_RATE_ESTIMATE:
        return users / elapsed_days
    return 0.0


def compute_significance(
    variant_results: list[dict],
    created_at: str,
    now: Optional[datetime] = None,
) -> dict:
    """variant_results[0] is treated as control; the rest are treatments
    compared only against it. Control is positional: whichever variant was
    first in the experiment's variant list at creation time, by name."""
    control = variant_results[0]
    treatments = variant_results[1:]

    elapsed = (now or datetime.now(timezone.utc)) - datetime.fromisoformat(created_at)
    elapsed_days = elapsed.total_seconds() / 86400
    rates_per_day = {v["name"]: _rate_per_day(v["users"], elapsed_days) for v in variant_results}

    zero_conversion_warnings = []
    for variant in variant_results:
        if variant["users"] > 0 and variant["conversions"] == 0:
            zero_conversion_warnings.append(
                {
                    "variant": variant["name"],
                    "message": (
                        f"Variant '{variant['name']}' has 0% conversions out of "
                        f"{variant['users']} users. This may be a real result or a "
                        f"tracking/integration problem - it does not by itself indicate which."
                    ),
                }
            )

    comparisons = []
    for treatment in treatments:
        comparisons.append(
            _compare_to_control(
                control,
                treatment,
                rates_per_day[control["name"]],
                rates_per_day[treatment["name"]],
            )
        )

    ok_indices = [i for i, c in enumerate(comparisons) if c["status"] == "ok"]
    ok_pvalues = [comparisons[i]["p_value"] for i in ok_indices]
    adjusted = benjamini_hochberg(ok_pvalues)
    for i, adj_p in zip(ok_indices, adjusted):
        comparisons[i]["adjusted_p_value"] = adj_p
        comparisons[i]["significant"] = bool(adj_p < ALPHA)

    return {
        "alpha": ALPHA,
        "comparisons": comparisons,
        "zero_conversion_warnings": zero_conversion_warnings,
    }


def _compare_to_control(
    control: dict, treatment: dict, control_rate_per_day: float, treatment_rate_per_day: float
) -> dict:
    control_users, control_conv = control["users"], control["conversions"]
    treatment_users, treatment_conv = treatment["users"], treatment["conversions"]
    warnings: list[str] = []

    base = {
        "variant": treatment["name"],
        "control": control["name"],
    }

    if control_users == 0 or treatment_users == 0:
        required_n = required_sample_size_per_group(control["conversion_rate"]) if control_users else None
        if required_n is None:
            reason = (
                "the control variant has no observed users yet"
                if control_users == 0
                else "the control variant has 0 observed conversions"
            )
            warnings.append(
                f"Cannot estimate the required sample size yet: {reason}, so the target "
                "effect size is undefined."
            )
        days_needed, days_warning = _estimated_days_needed(
            required_n,
            control["name"],
            control_users,
            treatment["name"],
            treatment_users,
            control_rate_per_day,
            treatment_rate_per_day,
        )
        if days_warning:
            warnings.append(days_warning)
        return {
            **base,
            "status": "insufficient_data",
            "required_users_per_group": required_n,
            "additional_users_needed": _additional_needed(required_n, control_users, treatment_users),
            "estimated_days_needed": days_needed,
            "warnings": warnings,
        }

    required_n = required_sample_size_per_group(control["conversion_rate"])
    if required_n is not None and (control_users < required_n or treatment_users < required_n):
        days_needed, days_warning = _estimated_days_needed(
            required_n,
            control["name"],
            control_users,
            treatment["name"],
            treatment_users,
            control_rate_per_day,
            treatment_rate_per_day,
        )
        if days_warning:
            warnings.append(days_warning)
        return {
            **base,
            "status": "insufficient_data",
            "required_users_per_group": required_n,
            "additional_users_needed": _additional_needed(required_n, control_users, treatment_users),
            "estimated_days_needed": days_needed,
            "warnings": warnings,
        }

    if required_n is None:
        warnings.append(
            "Could not estimate the required sample size because the control "
            "variant has 0 observed conversions; proceeding with the test anyway."
        )

    use_fisher = should_use_fisher(control_conv, control_users, treatment_conv, treatment_users)
    if use_fisher:
        p_value = fisher_exact_pvalue(control_conv, control_users, treatment_conv, treatment_users)
        method = "fisher_exact"
    else:
        p_value = two_proportion_ztest(control_conv, control_users, treatment_conv, treatment_users)
        method = "z-test"

    lower, upper = wald_confidence_interval(control_conv, control_users, treatment_conv, treatment_users)

    return {
        **base,
        "status": "ok",
        "method": method,
        "p_value": p_value,
        "confidence_interval": {"lower": lower, "upper": upper},
        "warnings": warnings,
    }


def _additional_needed(required_n: Optional[int], control_users: int, treatment_users: int) -> Optional[int]:
    if required_n is None:
        return None
    return max(required_n - control_users, required_n - treatment_users, 0)


def _estimated_days_needed(
    required_n: Optional[int],
    control_name: str,
    control_users: int,
    treatment_name: str,
    treatment_users: int,
    control_rate_per_day: float,
    treatment_rate_per_day: float,
) -> tuple[Optional[float], Optional[str]]:
    """Days until BOTH groups reach required_n, using each group's own observed
    enrollment rate. A shared rate would misestimate the lagging group whenever
    traffic is split unevenly between variants.

    Returns (days_needed, warning). warning is set instead of silently
    returning None when a lagging group's enrollment rate isn't measurable yet
    (too new, or no users observed at all) - consistent with how an
    unmeasurable baseline conversion rate is explained elsewhere."""
    if required_n is None:
        return None, None
    deficits = {
        control_name: max(required_n - control_users, 0),
        treatment_name: max(required_n - treatment_users, 0),
    }
    rates = {control_name: control_rate_per_day, treatment_name: treatment_rate_per_day}
    if all(deficit == 0 for deficit in deficits.values()):
        return None, None

    days_needed = []
    unmeasurable = []
    for name, deficit in deficits.items():
        if deficit == 0:
            continue
        rate = rates[name]
        if rate <= 0:
            unmeasurable.append(name)
            continue
        days_needed.append(deficit / rate)

    if unmeasurable:
        names = " and ".join(f"'{n}'" for n in unmeasurable)
        warning = (
            f"Cannot estimate days needed yet: enrollment rate for {names} is not "
            "yet measurable (too new, or no users observed yet)."
        )
        return None, warning

    return max(days_needed), None
