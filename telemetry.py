import os
import json
import datetime

LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "telemetry.log")


def log_event(event_name: str, payload: dict | None = None) -> None:
    """Append a JSON‑line log entry with a timestamp.
    Args:
        event_name: Short identifier for the event.
        payload: Optional dictionary with extra data.
    """
    entry = {
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "event": event_name,
        "payload": payload or {},
    }
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
