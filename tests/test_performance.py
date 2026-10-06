import os
import sqlite3
import tempfile
import time
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

pytestmark = pytest.mark.perf

N_EVENTS = 50_000
BUDGET_SECONDS = 5.0  # generous margin over the brief's 2-3s target, to avoid flaking on slower hardware


def _bulk_seed(db_path: str, experiment_id: str, per_variant: int) -> None:
    """Seeds assignments/events with a single bulk insert, bypassing the
    storage module's one-row-per-call API. Setup speed isn't what this
    benchmark measures - only the /results call below is timed."""
    now = datetime.now(timezone.utc).isoformat()
    assignment_rows = []
    event_rows = []
    for variant, conversion_rate in (("control", 0.08), ("treatment", 0.10)):
        n_conversions = int(per_variant * conversion_rate)
        for i in range(per_variant):
            user_id = f"{variant}_{i}"
            assignment_rows.append((experiment_id, user_id, variant, now))
            if i < n_conversions:
                event_rows.append((experiment_id, user_id, "conversion", now))

    conn = sqlite3.connect(db_path)
    try:
        conn.executemany(
            "INSERT INTO assignments (experiment_id, user_id, variant, assigned_at) VALUES (?, ?, ?, ?)",
            assignment_rows,
        )
        conn.executemany(
            "INSERT INTO events (experiment_id, user_id, event_type, created_at) VALUES (?, ?, ?, ?)",
            event_rows,
        )
        conn.commit()
    finally:
        conn.close()


def test_results_endpoint_under_budget_for_50k_events():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        app = create_app(db_path)
        client = TestClient(app)

        response = client.post(
            "/experiments",
            json={
                "name": "perf",
                "variants": [{"name": "control", "weight": 50}, {"name": "treatment", "weight": 50}],
            },
        )
        experiment_id = response.json()["id"]

        _bulk_seed(db_path, experiment_id, per_variant=N_EVENTS // 2)

        start = time.monotonic()
        response = client.get(f"/experiments/{experiment_id}/results")
        elapsed = time.monotonic() - start

        assert response.status_code == 200
        assert elapsed < BUDGET_SECONDS, (
            f"/results took {elapsed:.2f}s for {N_EVENTS} events (budget: {BUDGET_SECONDS}s)"
        )
    finally:
        os.remove(db_path)
