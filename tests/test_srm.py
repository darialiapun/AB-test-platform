import os
import tempfile

from fastapi.testclient import TestClient

from app import storage
from app.main import create_app
from app.srm import MIN_USERS_FOR_VALID_SRM_TEST, detect_srm


def make_client() -> tuple[TestClient, str]:
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    app = create_app(db_path)
    return TestClient(app), db_path


def create_experiment(client: TestClient, variants: list[dict]) -> str:
    response = client.post("/experiments", json={"name": "exp", "variants": variants})
    assert response.status_code == 201
    return response.json()["id"]


def populate_assignments(db_path: str, experiment_id: str, variant: str, count: int) -> None:
    for i in range(count):
        storage.create_assignment(db_path, experiment_id, f"{variant}_user_{i}", variant)


# --- REQ-12: direct unit tests for app.srm.detect_srm ---

def test_detect_srm_flags_large_skew_from_configured_weights():
    variant_results = [
        {"name": "control", "users": 600, "conversions": 0, "conversion_rate": 0.0},
        {"name": "treatment", "users": 400, "conversions": 0, "conversion_rate": 0.0},
    ]
    weights = [50, 50]
    result = detect_srm(variant_results, weights)
    assert result is not None
    assert result["detected"] is True
    assert result["p_value"] < 0.01


def test_detect_srm_not_flagged_when_observed_matches_weights_within_noise():
    variant_results = [
        {"name": "control", "users": 520, "conversions": 0, "conversion_rate": 0.0},
        {"name": "treatment", "users": 480, "conversions": 0, "conversion_rate": 0.0},
    ]
    weights = [50, 50]
    result = detect_srm(variant_results, weights)
    assert result is not None
    assert result["detected"] is False
    assert result["p_value"] >= 0.01


# --- REQ-13: floor below which the test is not valid ---

def test_detect_srm_returns_none_when_any_variant_has_too_few_users():
    variant_results = [
        {"name": "control", "users": MIN_USERS_FOR_VALID_SRM_TEST - 1, "conversions": 0, "conversion_rate": 0.0},
        {"name": "treatment", "users": 100, "conversions": 0, "conversion_rate": 0.0},
    ]
    weights = [50, 50]
    assert detect_srm(variant_results, weights) is None


# --- API-level tests wiring REQ-12 / REQ-13 into /results ---

def test_results_endpoint_includes_srm_when_check_srm_requested():
    client, db_path = make_client()
    try:
        experiment_id = create_experiment(
            client, [{"name": "control", "weight": 50}, {"name": "treatment", "weight": 50}]
        )
        populate_assignments(db_path, experiment_id, "control", 600)
        populate_assignments(db_path, experiment_id, "treatment", 400)

        resp = client.get(f"/experiments/{experiment_id}/results", params={"check_srm": True})
        assert resp.status_code == 200
        body = resp.json()
        assert body["srm"] is not None
        assert body["srm"]["detected"] is True
        assert body["srm_warning"] is None
    finally:
        os.remove(db_path)


def test_results_endpoint_srm_null_with_warning_when_insufficient_data():
    client, db_path = make_client()
    try:
        experiment_id = create_experiment(
            client, [{"name": "control", "weight": 50}, {"name": "treatment", "weight": 50}]
        )
        populate_assignments(db_path, experiment_id, "control", 3)
        populate_assignments(db_path, experiment_id, "treatment", 100)

        resp = client.get(f"/experiments/{experiment_id}/results", params={"check_srm": True})
        assert resp.status_code == 200
        body = resp.json()
        assert body["srm"] is None
        assert body["srm_warning"] is not None
        assert "valid" in body["srm_warning"].lower()
    finally:
        os.remove(db_path)


def test_results_endpoint_omits_srm_by_default():
    client, db_path = make_client()
    try:
        experiment_id = create_experiment(
            client, [{"name": "control", "weight": 50}, {"name": "treatment", "weight": 50}]
        )
        populate_assignments(db_path, experiment_id, "control", 3)
        populate_assignments(db_path, experiment_id, "treatment", 3)

        resp = client.get(f"/experiments/{experiment_id}/results")
        assert resp.status_code == 200
        body = resp.json()
        assert body["srm"] is None
        assert body["srm_warning"] is None
    finally:
        os.remove(db_path)
