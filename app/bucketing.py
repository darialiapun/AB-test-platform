import hashlib


def get_bucket(user_id: str, experiment_id: str) -> int:
    """Deterministic bucket in [0, 100) derived from user_id + experiment_id."""
    digest = hashlib.sha256(f"{user_id}:{experiment_id}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 100


def assign_variant(variants: list[dict], user_id: str, experiment_id: str) -> str:
    bucket = get_bucket(user_id, experiment_id)
    cumulative = 0
    for variant in variants:
        cumulative += variant["weight"]
        if bucket < cumulative:
            return variant["name"]
    # Fallback in case weights don't sum exactly to 100 due to floating point/rounding.
    return variants[-1]["name"]
