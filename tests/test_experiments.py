import os
import tempfile

from fastapi.testclient import TestClient

from app.main import create_app


def make_client() -> tuple[TestClient, str]:
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    app = create_app(db_path)
    return TestClient(app), db_path


def test_create_experiment_rejects_fewer_than_two_variants():
    client, db_path = make_client()
    try:
        response = client.post(
            "/experiments",
            json={"name": "exp", "variants": [{"name": "control", "weight": 100}]},
        )
        assert response.status_code == 400
        assert "variant" in response.json()["detail"].lower()

        response = client.post("/experiments", json={"name": "exp", "variants": []})
        assert response.status_code == 400
        assert "variant" in response.json()["detail"].lower()
    finally:
        os.remove(db_path)
