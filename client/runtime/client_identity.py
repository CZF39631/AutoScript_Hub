"""Stable client identity and operating-mode helpers."""
import json
import os
import uuid


VALID_CLIENT_MODES = {"standard", "managed"}
DEFAULT_CLIENT_MODE = "standard"


def normalize_client_identity(config):
    """Return a copy containing a valid mode and a stable device identifier."""
    normalized = dict(config or {})
    mode = str(normalized.get("client_mode") or DEFAULT_CLIENT_MODE).strip().lower()
    if mode not in VALID_CLIENT_MODES:
        mode = DEFAULT_CLIENT_MODE
    normalized["client_mode"] = mode

    device_uid = str(normalized.get("device_uid") or "").strip()
    if not device_uid:
        device_uid = str(uuid.uuid4())
    normalized["device_uid"] = device_uid
    return normalized


def ensure_client_identity(config, config_path):
    """Normalize identity and atomically persist it when missing or invalid."""
    original = dict(config or {})
    normalized = normalize_client_identity(original)
    if normalized == original:
        return normalized

    parent = os.path.dirname(config_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    temporary = config_path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as stream:
        json.dump(normalized, stream, indent=2, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, config_path)
    return normalized
