from typing import Any, Dict

REQUIRED_KEYS = ["employee_id", "track_id"]
PII_KEYWORDS = (
    "email",
    "e-mail",
    "mail",
    "ssn",
    "social",
    "password",
    "secret",
    "token",
    "dob",
    "date_of_birth",
    "phone",
    "mobile",
    "address",
)


def _looks_like_pii_key(key: str) -> bool:
    lowered = key.lower()
    return any(keyword in lowered for keyword in PII_KEYWORDS)


def sanitize_input(data: Any) -> Any:
    """Recursively strip keys that look like direct identifiers or secrets."""
    if isinstance(data, dict):
        return {
            key: sanitize_input(value)
            for key, value in data.items()
            if not _looks_like_pii_key(str(key))
        }
    if isinstance(data, list):
        return [sanitize_input(item) for item in data]
    return data


def ensure_json_schema(payload: Any, schema: Dict[str, Any]) -> bool:
    """Perform a small JSON-schema style validation for the supported shapes."""

    def _validate(value: Any, node: Dict[str, Any]) -> bool:
        expected_type = node.get("type")

        if expected_type == "object":
            if not isinstance(value, dict):
                return False

            required = node.get("required", [])
            if any(key not in value for key in required):
                return False

            properties = node.get("properties", {})
            for key, child_schema in properties.items():
                if key in value and not _validate(value[key], child_schema):
                    return False

            if node.get("additionalProperties") is False:
                allowed_keys = set(properties.keys())
                if any(key not in allowed_keys for key in value.keys()):
                    return False
            return True

        if expected_type == "array":
            if not isinstance(value, list):
                return False

            min_items = node.get("minItems")
            max_items = node.get("maxItems")
            if min_items is not None and len(value) < min_items:
                return False
            if max_items is not None and len(value) > max_items:
                return False

            item_schema = node.get("items")
            if isinstance(item_schema, dict):
                return all(_validate(item, item_schema) for item in value)
            return True

        if expected_type == "string":
            return isinstance(value, str)
        if expected_type == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if expected_type == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if expected_type == "boolean":
            return isinstance(value, bool)
        if expected_type == "null":
            return value is None

        # Unknown schema fragments are treated as pass-through so this helper
        # stays useful without becoming brittle.
        return True

    if not isinstance(schema, dict):
        return False
    return _validate(payload, schema)


def validate_request(request: Dict[str, Any]) -> None:
    """Raise ValueError if the request is missing required top-level keys."""
    missing = [k for k in REQUIRED_KEYS if k not in request]
    if missing:
        raise ValueError(f"Request is missing required keys: {', '.join(missing)}")
    if not isinstance(request.get("employee_id"), str):
        raise ValueError("employee_id must be a string")
    if not isinstance(request.get("track_id"), str):
        raise ValueError("track_id must be a string")
