import math
import os
import tempfile
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from scipy.stats import fisher_exact as scipy_fisher_exact
from scipy.stats import norm
from statsmodels.stats.multitest import multipletests
from statsmodels.stats.proportion import proportions_ztest

from app import significance
from app.bucketing import assign_variant
from app.main import create_app


def make_client() -> tuple[TestClient, str]:
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    app = create_app(db_path)
    return TestClient(app), db_path


def create_experiment(client: TestClient, variants: list[dict]) -> tuple[str, list[dict]]:
    response = client.post("/experiments", json={"name": "exp", "variants": variants})
    assert response.status_code == 201
    body = response.json()
    return body["id"], body["variants"]


_user_counter = 0


def _next_user_id_for_variant(variants: list[dict], experiment_id: str, variant: str) -> str:
    global _user_counter
    while True:
        _user_counter += 1
        candidate = f"user_{_user_counter}"
        if assign_variant(variants, candidate, experiment_id) == variant:
            return candidate


def populate(
    client: TestClient,
    experiment_id: str,
    variants: list[dict],
    variant: str,
    users: int,
    conversions: int,
) -> None:
    for i in range(users):
        user_id = _next_user_id_for_variant(variants, experiment_id, variant)
        resp = client.get(f"/experiments/{experiment_id}/variant", params={"user_id": user_id})
        assert resp.json()["variant"] == variant
        if i < conversions:
            ev = client.post(
                "/events",
                json={"experiment_id": experiment_id, "user_id": user_id, "event_type": "conversion"},
            )
            assert ev.status_code == 201


def test_ztest_matches_statsmodels_reference():
    x1, n1, x2, n2 = 120, 1000, 160, 1000
    p_value = significance.two_proportion_ztest(x1, n1, x2, n2)
    _, ref_p_value = proportions_ztest([x1, x2], [n1, n2])
    assert abs(p_value - ref_p_value) < 0.001


def test_fisher_matches_scipy_reference():
    x1, n1, x2, n2 = 3, 5, 2, 5
    p_value = significance.fisher_exact_pvalue(x1, n1, x2, n2)
    _, ref_p_value = scipy_fisher_exact([[x1, n1 - x1], [x2, n2 - x2]], alternative="two-sided")
    assert abs(p_value - ref_p_value) < 0.001


def test_switches_to_fisher_for_small_samples():
    assert significance.should_use_fisher(3, 5, 2, 5) is True
    assert significance.should_use_fisher(120, 1000, 160, 1000) is False


def test_confidence_interval_is_wald_even_when_fisher_is_selected():
    # REQ-3: the CI formula must stay Wald regardless of which test picked
    # the p-value. Chosen so the sample-size gate passes (both groups well
    # above required_n for a 0.5 baseline) while the extreme treatment
    # conversion rate still triggers Fisher (failures=4 < MIN_CELL_COUNT).
    # If the CI method is ever made method-dependent (see ADR 0001), this
    # test must change along with it - it should not pass by accident.
    control = {"name": "control", "users": 1600, "conversions": 800, "conversion_rate": 0.5}
    treatment = {"name": "treatment", "users": 1600, "conversions": 1596, "conversion_rate": 1596 / 1600}
    assert significance.should_use_fisher(800, 1600, 1596, 1600) is True

    created_at = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
    result = significance.compute_significance([control, treatment], created_at)
    comparison = result["comparisons"][0]

    assert comparison["status"] == "ok"
    assert comparison["method"] == "fisher_exact"

    expected_lower, expected_upper = significance.wald_confidence_interval(800, 1600, 1596, 1600)
    assert comparison["confidence_interval"]["lower"] == pytest.approx(expected_lower)
    assert comparison["confidence_interval"]["upper"] == pytest.approx(expected_upper)


def test_benjamini_hochberg_matches_statsmodels_reference():
    p_values = [0.001, 0.02, 0.03, 0.4, 0.5, 0.75]
    adjusted = significance.benjamini_hochberg(p_values)
    _, ref_adjusted, _, _ = multipletests(p_values, method="fdr_bh")
    for a, ref in zip(adjusted, ref_adjusted):
        assert abs(a - ref) < 0.001


def test_api_warns_when_sample_size_insufficient():
    client, db_path = make_client()
    try:
        experiment_id, variants = create_experiment(
            client, [{"name": "control", "weight": 50}, {"name": "treatment", "weight": 50}]
        )
        populate(client, experiment_id, variants, "control", 10, 1)
        populate(client, experiment_id, variants, "treatment", 10, 2)

        response = client.get(f"/experiments/{experiment_id}/results")
        assert response.status_code == 200
        body = response.json()
        comparison = body["significance"]["comparisons"][0]
        assert comparison["status"] == "insufficient_data"
        assert comparison["required_users_per_group"] is not None
        assert comparison["additional_users_needed"] > 0
    finally:
        os.remove(db_path)


def test_control_with_zero_users_warns_with_reason_not_silently():
    # REQ-6: when the control has no observed users at all (not just 0
    # conversions), required_users_per_group can't be estimated - but the
    # comparison must still explain why, not return an empty warnings list.
    # Before this was fixed, this exact branch returned insufficient_data
    # with warnings == [].
    client, db_path = make_client()
    try:
        experiment_id, variants = create_experiment(
            client, [{"name": "control", "weight": 50}, {"name": "treatment", "weight": 50}]
        )
        populate(client, experiment_id, variants, "treatment", 10, 2)
        # control intentionally gets no users assigned at all.

        response = client.get(f"/experiments/{experiment_id}/results")
        assert response.status_code == 200
        comparison = response.json()["significance"]["comparisons"][0]

        assert comparison["status"] == "insufficient_data"
        assert comparison["required_users_per_group"] is None
        assert comparison["additional_users_needed"] is None
        assert comparison["warnings"] != []
        assert any("no observed users yet" in w for w in comparison["warnings"])
    finally:
        os.remove(db_path)


def test_api_computes_significance_with_enough_data():
    client, db_path = make_client()
    try:
        experiment_id, variants = create_experiment(
            client, [{"name": "control", "weight": 50}, {"name": "treatment", "weight": 50}]
        )
        populate(client, experiment_id, variants, "control", 1000, 800)
        populate(client, experiment_id, variants, "treatment", 1000, 850)

        response = client.get(f"/experiments/{experiment_id}/results")
        assert response.status_code == 200
        body = response.json()
        comparison = body["significance"]["comparisons"][0]
        assert comparison["status"] == "ok"
        assert comparison["method"] in ("z-test", "fisher_exact")
        assert isinstance(comparison["p_value"], float)
        assert isinstance(comparison["significant"], bool)
        assert "lower" in comparison["confidence_interval"]
        assert "upper" in comparison["confidence_interval"]
    finally:
        os.remove(db_path)


def test_zero_conversion_variant_does_not_crash_and_warns():
    client, db_path = make_client()
    try:
        experiment_id, variants = create_experiment(
            client, [{"name": "control", "weight": 50}, {"name": "treatment", "weight": 50}]
        )
        populate(client, experiment_id, variants, "control", 1000, 100)
        populate(client, experiment_id, variants, "treatment", 1000, 0)

        response = client.get(f"/experiments/{experiment_id}/results")
        assert response.status_code == 200
        body = response.json()

        treatment_result = next(v for v in body["variants"] if v["name"] == "treatment")
        assert treatment_result["conversion_rate"] == 0.0

        warnings = body["significance"]["zero_conversion_warnings"]
        assert any(w["variant"] == "treatment" for w in warnings)

        # REQ-5: the message must name both possible causes and must not
        # assert that it IS a technical problem (the system can't know that).
        message = next(w["message"] for w in warnings if w["variant"] == "treatment")
        assert "real result" in message
        assert "tracking/integration problem" in message
        assert "possible tracking problem" not in message
    finally:
        os.remove(db_path)


def test_single_variant_experiment_returns_error():
    client, db_path = make_client()
    try:
        experiment_id, _ = create_experiment(client, [{"name": "control", "weight": 100}])
        response = client.get(f"/experiments/{experiment_id}/results")
        assert response.status_code == 400
        assert "detail" in response.json()
    finally:
        os.remove(db_path)


def test_variant_order_is_creation_order_not_alphabetical_or_by_volume():
    client, db_path = make_client()
    try:
        # "zeta" is created first (so it's control) and gets fewer users than
        # "alpha", which sorts first alphabetically. If order were alphabetical
        # or driven by volume, "alpha" would end up as control instead.
        experiment_id, variants = create_experiment(
            client, [{"name": "zeta", "weight": 50}, {"name": "alpha", "weight": 50}]
        )
        populate(client, experiment_id, variants, "zeta", 10, 1)
        populate(client, experiment_id, variants, "alpha", 20, 2)

        response = client.get(f"/experiments/{experiment_id}/results")
        assert response.status_code == 200
        body = response.json()

        assert [v["name"] for v in body["variants"]] == ["zeta", "alpha"]

        comparison = body["significance"]["comparisons"][0]
        assert comparison["control"] == "zeta"
        assert comparison["variant"] == "alpha"
    finally:
        os.remove(db_path)


def test_multiple_treatments_get_bh_correction():
    client, db_path = make_client()
    try:
        experiment_id, variants = create_experiment(
            client,
            [
                {"name": "control", "weight": 34},
                {"name": "treatment_a", "weight": 33},
                {"name": "treatment_b", "weight": 33},
            ],
        )
        populate(client, experiment_id, variants, "control", 1000, 800)
        populate(client, experiment_id, variants, "treatment_a", 1000, 850)
        populate(client, experiment_id, variants, "treatment_b", 1000, 810)

        response = client.get(f"/experiments/{experiment_id}/results")
        assert response.status_code == 200
        comparisons = response.json()["significance"]["comparisons"]
        assert len(comparisons) == 2
        ok_comparisons = [c for c in comparisons if c["status"] == "ok"]
        assert len(ok_comparisons) == 2
        p_values = [c["p_value"] for c in ok_comparisons]
        adjusted_expected = significance.benjamini_hochberg(p_values)
        for c, expected in zip(ok_comparisons, adjusted_expected):
            assert abs(c["adjusted_p_value"] - expected) < 1e-9
            assert c["significant"] == (expected < 0.05)
    finally:
        os.remove(db_path)


def test_bh_family_excludes_insufficient_data_comparisons():
    # treatment_a has plenty of data (status "ok"); treatment_b has far too
    # little (status "insufficient_data"). The BH family (m) must be sized to
    # the "ok" comparisons only - treatment_b must not count toward m and
    # must not affect treatment_a's adjusted p-value.
    client, db_path = make_client()
    try:
        experiment_id, variants = create_experiment(
            client,
            [
                {"name": "control", "weight": 34},
                {"name": "treatment_a", "weight": 33},
                {"name": "treatment_b", "weight": 33},
            ],
        )
        populate(client, experiment_id, variants, "control", 1000, 800)
        populate(client, experiment_id, variants, "treatment_a", 1000, 850)
        populate(client, experiment_id, variants, "treatment_b", 5, 1)

        response = client.get(f"/experiments/{experiment_id}/results")
        assert response.status_code == 200
        comparisons = response.json()["significance"]["comparisons"]

        treatment_a = next(c for c in comparisons if c["variant"] == "treatment_a")
        treatment_b = next(c for c in comparisons if c["variant"] == "treatment_b")

        assert treatment_b["status"] == "insufficient_data"
        assert treatment_a["status"] == "ok"
        # m=1 (only treatment_a is "ok"): BH of a single p-value is itself.
        assert treatment_a["adjusted_p_value"] == pytest.approx(treatment_a["p_value"])
    finally:
        os.remove(db_path)


def test_required_sample_size_is_deterministic():
    a = significance.required_sample_size_per_group(0.1)
    b = significance.required_sample_size_per_group(0.1)
    assert a == b
    assert a > 0


def test_required_sample_size_none_when_baseline_zero():
    assert significance.required_sample_size_per_group(0.0) is None


def test_required_sample_size_uses_10_percent_relative_mde_and_80_percent_power():
    # REQ-2: pins the exact constants (not just "it's deterministic"). This
    # reconstructs the formula independently from scipy primitives, so it
    # fails if RELATIVE_MDE or POWER drift away from 10%/0.80.
    baseline = 0.2
    required_n = significance.required_sample_size_per_group(baseline)

    z_alpha = norm.ppf(1 - 0.05 / 2)
    z_beta = norm.ppf(0.80)
    target = baseline * 1.10
    effect = target - baseline
    variance = baseline * (1 - baseline) + target * (1 - target)
    expected = math.ceil(((z_alpha + z_beta) ** 2 * variance) / (effect**2))

    assert required_n == expected


def test_estimated_days_uses_observed_enrollment_rate():
    created_at = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    control = {"name": "control", "users": 20, "conversions": 2, "conversion_rate": 0.1}
    treatment = {"name": "treatment", "users": 20, "conversions": 3, "conversion_rate": 0.15}
    result = significance.compute_significance([control, treatment], created_at)
    comparison = result["comparisons"][0]
    assert comparison["status"] == "insufficient_data"
    assert comparison["estimated_days_needed"] is None or comparison["estimated_days_needed"] > 0


def test_estimated_days_is_none_when_experiment_too_young_to_measure_rate():
    created_at = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    control = {"name": "control", "users": 2000, "conversions": 200, "conversion_rate": 0.1}
    treatment = {"name": "treatment", "users": 2000, "conversions": 220, "conversion_rate": 0.11}
    result = significance.compute_significance([control, treatment], created_at)
    comparison = result["comparisons"][0]
    assert comparison["status"] == "insufficient_data"
    assert comparison["estimated_days_needed"] is None
    assert any("enrollment rate" in w for w in comparison["warnings"])


def test_estimated_days_scales_with_actual_elapsed_time_not_pinned_to_one_day():
    control = {"name": "control", "users": 2000, "conversions": 200, "conversion_rate": 0.1}
    treatment = {"name": "treatment", "users": 2000, "conversions": 220, "conversion_rate": 0.11}

    created_at_6h = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
    created_at_12h = (datetime.now(timezone.utc) - timedelta(hours=12)).isoformat()

    days_at_6h = significance.compute_significance([control, treatment], created_at_6h)["comparisons"][0][
        "estimated_days_needed"
    ]
    days_at_12h = significance.compute_significance([control, treatment], created_at_12h)["comparisons"][0][
        "estimated_days_needed"
    ]

    # Same user count observed over twice the elapsed time implies half the
    # enrollment rate, so the 12h estimate should be ~2x the 6h one, not equal.
    assert days_at_6h < days_at_12h
    assert days_at_12h == pytest.approx(2 * days_at_6h, rel=0.01)


def test_estimated_days_uses_each_variants_own_rate_not_averaged():
    # REQ-4: control has 10x the users of treatment. A regression to an
    # averaged/combined rate (total_users / elapsed_days applied to both
    # groups) would silently pass every OTHER estimated_days test, because
    # they all use symmetric populations where averaged == per-variant.
    now = datetime.now(timezone.utc)
    created_at = (now - timedelta(days=2)).isoformat()
    control = {"name": "control", "users": 1000, "conversions": 100, "conversion_rate": 0.1}
    treatment = {"name": "treatment", "users": 100, "conversions": 10, "conversion_rate": 0.1}

    result = significance.compute_significance([control, treatment], created_at, now=now)
    comparison = result["comparisons"][0]
    assert comparison["status"] == "insufficient_data"

    required_n = comparison["required_users_per_group"]
    assert required_n is not None
    assert required_n > control["users"] and required_n > treatment["users"]

    control_rate = control["users"] / 2  # users / elapsed_days (exactly 2 days, pinned via `now`)
    treatment_rate = treatment["users"] / 2
    expected = max(
        (required_n - control["users"]) / control_rate,
        (required_n - treatment["users"]) / treatment_rate,
    )
    # What a combined/averaged rate would have produced instead - used only
    # to prove the actual result is NOT this (wrong) number.
    combined_rate = (control["users"] + treatment["users"]) / 2
    wrong_if_averaged = max(required_n - control["users"], required_n - treatment["users"]) / combined_rate

    assert comparison["estimated_days_needed"] == pytest.approx(expected, rel=1e-9)
    assert comparison["estimated_days_needed"] > wrong_if_averaged * 3
