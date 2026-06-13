import json
from typing import Any, Dict

REQUIRED_KEYS = ["employee_id", "track_id"]


def validate_request(request: Dict[str, Any]) -> None:
    """Raise ValueError if the request is missing required top‑level keys.
    This simple guard ensures the pipeline receives the minimal data it expects.
    """
    missing = [k for k in REQUIRED_KEYS if k not in request]
    if missing:
        raise ValueError(f"Request is missing required keys: {', '.join(missing)}")
    # Optional: quick type checks
    if not isinstance(request.get("employee_id"), str):
        raise ValueError("employee_id must be a string")
    if not isinstance(request.get("track_id"), str):
        raise ValueError("track_id must be a string")
