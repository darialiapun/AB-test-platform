import os
import tempfile

from fastapi.testclient import TestClient

from app.main import create_app


def make_client() -> tuple[TestClient, str]:
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    app = create_app(db_path)
    return TestClient(app), db_path


def test_same_user_gets_same_variant_on_repeated_requests():
    client, db_path = make_client()
    try:
        response = client.post(
            "/experiments",
            json={
                "name": "button_color",
                "variants": [
                    {"name": "control", "weight": 50},
                    {"name": "treatment", "weight": 50},
                ],
            },
        )
        assert response.status_code == 201
        experiment_id = response.json()["id"]

        variants_seen = set()
        for _ in range(100):
            resp = client.get(
                f"/experiments/{experiment_id}/variant",
                params={"user_id": "u42"},
            )
            assert resp.status_code == 200
            variants_seen.add(resp.json()["variant"])

        assert len(variants_seen) == 1
    finally:
        os.remove(db_path)
