import os
import tempfile
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from scipy.stats import fisher_exact as scipy_fisher_exact
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


def test_required_sample_size_is_deterministic():
    a = significance.required_sample_size_per_group(0.1)
    b = significance.required_sample_size_per_group(0.1)
    assert a == b
    assert a > 0


def test_required_sample_size_none_when_baseline_zero():
    assert significance.required_sample_size_per_group(0.0) is None


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
