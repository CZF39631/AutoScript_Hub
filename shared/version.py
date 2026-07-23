"""Single source of truth for release versions and update channels."""

import json
import os
from pathlib import Path
import re


RELEASE_VERSION = "0.9.1"
DEV_VERSION = RELEASE_VERSION + "-dev"
_SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
_CHANNELS = {"beta", "stable"}
_BUILD_INFO_PATH = Path("/app/autoscript-build.json")


def _baked_value(key: str) -> str:
    try:
        payload = json.loads(_BUILD_INFO_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError, TypeError):
        return ""
    value = payload.get(key, "") if isinstance(payload, dict) else ""
    return str(value).strip()


def get_version() -> str:
    """Return the build-injected SemVer value or the development fallback."""
    value = (_baked_value("version") or os.getenv("AUTOSCRIPT_VERSION", DEV_VERSION)).strip().lstrip("v")
    return value if _SEMVER.fullmatch(value) else DEV_VERSION


def get_channel() -> str:
    """Return an explicit supported channel or derive it from the version."""
    explicit = (_baked_value("channel") or os.getenv("AUTOSCRIPT_CHANNEL", "")).strip().lower()
    if explicit in _CHANNELS:
        return explicit
    return "stable" if get_version().startswith("1.") else "beta"
