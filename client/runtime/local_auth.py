"""Shared authentication secret for the loopback Agent API."""

import os
import secrets
from pathlib import Path

from client.runtime.paths import ClientPaths


_TOKEN_BYTES = 32


def token_path() -> Path:
    paths = ClientPaths.from_environment()
    paths.ensure()
    return paths.config_dir / "agent-api.token"


def get_or_create_agent_token() -> str:
    """Load or atomically create the per-installation loopback API token."""
    path = token_path()
    try:
        token = path.read_text(encoding="ascii").strip()
        if len(token) >= 43:
            return token
    except OSError:
        pass

    token = secrets.token_urlsafe(_TOKEN_BYTES)
    try:
        with path.open("x", encoding="ascii") as stream:
            stream.write(token)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return token
    except FileExistsError:
        # Another process won the startup race.
        existing = path.read_text(encoding="ascii").strip()
        if len(existing) < 43:
            raise RuntimeError("Agent API token file is invalid")
        return existing
