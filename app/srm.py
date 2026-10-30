from typing import Optional

from scipy.stats import chisquare

# Floor below which the chi-square goodness-of-fit approximation is not
# mathematically valid (standard rule of thumb: expected/observed count >=5
# per cell). This is NOT a claim that 5 users is "enough to reliably detect
# a mismatch" - it only means the test statistic can be computed at all.
# A proper power analysis (how many users are needed to reliably catch a
# given relative skew, mirroring required_sample_size_per_group in
# significance.py) is deliberately out of scope here - see spec.md REQ-13.
MIN_USERS_FOR_VALID_SRM_TEST = 5

# SRM checks conventionally use a stricter alpha than ordinary significance
# testing (0.01, not 0.05): a false "detected" here means distrusting an
# otherwise-valid experiment, which is costlier than an ordinary false
# positive.
SRM_ALPHA = 0.01


def detect_srm(variant_results: list[dict], weights: list[int]) -> Optional[dict]:
    """Sample Ratio Mismatch check: compares observed per-variant user counts
    against the experiment's configured weights via a chi-square
    goodness-of-fit test.

    variant_results and weights must be in the same variant order (as
    returned by storage.get_results / experiment["variants"]).

    Returns None when any variant has fewer than MIN_USERS_FOR_VALID_SRM_TEST
    observed users - below that floor the test isn't valid, so no p_value
    is trustworthy either way (see REQ-13 in spec.md).
    """
    if any(v["users"] < MIN_USERS_FOR_VALID_SRM_TEST for v in variant_results):
        return None

    total_users = sum(v["users"] for v in variant_results)
    observed = [v["users"] for v in variant_results]
    expected = [total_users * w / 100 for w in weights]

    _, p_value = chisquare(f_obs=observed, f_exp=expected)
    return {"detected": bool(p_value < SRM_ALPHA), "p_value": float(p_value)}
