"""Single source of truth for release versions and update channels."""

import json
import os
from pathlib import Path
import re

from packaging.version import InvalidVersion, Version


RELEASE_VERSION = "1.0.0"
DEV_VERSION = RELEASE_VERSION + "-dev"
_SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
_REVIEW_VERSION = re.compile(
    r"^(?P<base>\d+\.\d+\.\d+)"
    r"(?:-(?P<pre>alpha|beta|rc)\.(?P<pre_num>\d+))?"
    r"-review\.(?P<review_num>\d+)$",
    re.IGNORECASE,
)
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


def parse_update_version(value: str) -> Version:
    """Parse release versions plus local-only ``review`` preview versions.

    Review builds are ordered immediately before the release or prerelease they
    preview, so they can exercise the real updater without publishing a tag.
    """
    normalized = value.strip().lstrip("v")
    try:
        return Version(normalized)
    except InvalidVersion:
        match = _REVIEW_VERSION.fullmatch(normalized)
        if not match:
            raise
        pre = match.group("pre")
        pre_num = match.group("pre_num")
        review_num = match.group("review_num")
        pre_value = "" if pre is None else {"alpha": "a", "beta": "b", "rc": "rc"}[pre.lower()] + pre_num
        return Version(f"{match.group('base')}{pre_value}.dev{review_num}")


def get_channel() -> str:
    """Return an explicit supported channel or derive it from the version."""
    explicit = (_baked_value("channel") or os.getenv("AUTOSCRIPT_CHANNEL", "")).strip().lower()
    if explicit in _CHANNELS:
        return explicit
    version = get_version()
    return "stable" if version.startswith("1.") and "-" not in version else "beta"
