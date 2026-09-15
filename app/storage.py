import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional


@contextmanager
def _connect(db_path: str):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: str) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS experiments (
                numeric_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                variants TEXT NOT NULL,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS assignments (
                experiment_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                variant TEXT NOT NULL,
                assigned_at TEXT NOT NULL,
                PRIMARY KEY (experiment_id, user_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                experiment_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )


def _experiment_id(numeric_id: int) -> str:
    return f"exp_{numeric_id}"


def _numeric_id(experiment_id: str) -> Optional[int]:
    prefix = "exp_"
    if not experiment_id.startswith(prefix):
        return None
    try:
        return int(experiment_id[len(prefix):])
    except ValueError:
        return None


def create_experiment(db_path: str, name: str, variants: list[dict]) -> dict:
    created_at = datetime.now(timezone.utc).isoformat()
    with _connect(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO experiments (name, variants, created_at, status) VALUES (?, ?, ?, ?)",
            (name, json.dumps(variants), created_at, "running"),
        )
        numeric_id = cursor.lastrowid
    return {
        "id": _experiment_id(numeric_id),
        "name": name,
        "variants": variants,
        "status": "running",
    }


def get_experiment(db_path: str, experiment_id: str) -> Optional[dict]:
    numeric_id = _numeric_id(experiment_id)
    if numeric_id is None:
        return None
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT numeric_id, name, variants, status FROM experiments WHERE numeric_id = ?",
            (numeric_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": _experiment_id(row["numeric_id"]),
        "name": row["name"],
        "variants": json.loads(row["variants"]),
        "status": row["status"],
    }


def get_assignment(db_path: str, experiment_id: str, user_id: str) -> Optional[str]:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT variant FROM assignments WHERE experiment_id = ? AND user_id = ?",
            (experiment_id, user_id),
        ).fetchone()
    return row["variant"] if row else None


def create_assignment(db_path: str, experiment_id: str, user_id: str, variant: str) -> None:
    assigned_at = datetime.now(timezone.utc).isoformat()
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO assignments (experiment_id, user_id, variant, assigned_at) "
            "VALUES (?, ?, ?, ?)",
            (experiment_id, user_id, variant, assigned_at),
        )


def create_event(db_path: str, experiment_id: str, user_id: str, event_type: str) -> None:
    created_at = datetime.now(timezone.utc).isoformat()
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO events (experiment_id, user_id, event_type, created_at) VALUES (?, ?, ?, ?)",
            (experiment_id, user_id, event_type, created_at),
        )


def get_results(db_path: str, experiment_id: str, variant_names: list[str]) -> list[dict]:
    with _connect(db_path) as conn:
        users_rows = conn.execute(
            "SELECT variant, COUNT(*) AS users FROM assignments WHERE experiment_id = ? GROUP BY variant",
            (experiment_id,),
        ).fetchall()
        conversions_rows = conn.execute(
            """
            SELECT a.variant AS variant, COUNT(DISTINCT a.user_id) AS conversions
            FROM assignments a
            JOIN events e ON e.experiment_id = a.experiment_id AND e.user_id = a.user_id
            WHERE a.experiment_id = ? AND e.event_type = 'conversion'
            GROUP BY a.variant
            """,
            (experiment_id,),
        ).fetchall()

    users_by_variant = {row["variant"]: row["users"] for row in users_rows}
    conversions_by_variant = {row["variant"]: row["conversions"] for row in conversions_rows}

    results = []
    for name in variant_names:
        users = users_by_variant.get(name, 0)
        conversions = conversions_by_variant.get(name, 0)
        conversion_rate = conversions / users if users else 0.0
        results.append(
            {
                "name": name,
                "users": users,
                "conversions": conversions,
                "conversion_rate": conversion_rate,
            }
        )
    return results
