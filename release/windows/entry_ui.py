"""PyInstaller entrypoint for the desktop UI."""

import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import urllib.request

from autoscript_build_info import CHANNEL, VERSION

os.environ["AUTOSCRIPT_VERSION"] = VERSION
os.environ["AUTOSCRIPT_CHANNEL"] = CHANNEL

from client.runtime.paths import ClientPaths
from client.ui.config_manager import is_setup_complete
from client.ui.main import start_ui
from client.updater_main import write_startup_marker
from shared.version import get_version


logger = logging.getLogger(__name__)


def _agent_is_running() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:18080/status", timeout=1) as response:
            return response.status == 200
    except Exception:
        return False


def _agent_has_version(expected_version: str) -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:18080/status", timeout=1) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return response.status == 200 and payload.get("version") == expected_version
    except (OSError, ValueError, json.JSONDecodeError):
        return False


def _wait_for_agent(expected_version: str, timeout_seconds: int = 30) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _agent_has_version(expected_version):
            return True
        time.sleep(0.25)
    return False


def _start_agent(paths: ClientPaths) -> None:
    if _agent_is_running():
        return
    agent = paths.install_dir / "AutoScriptAgent.exe"
    if not agent.is_file():
        raise FileNotFoundError(f"AutoScriptAgent.exe 不存在: {agent}")
    flags = 0x00000008 | 0x00000200 if sys.platform == "win32" else 0
    subprocess.Popen(
        [str(agent)],
        cwd=str(paths.install_dir),
        creationflags=flags,
        close_fds=True,
    )


def _confirm_startup(
    paths: ClientPaths,
    version: str,
    start_agent=_start_agent,
    wait_for_agent=_wait_for_agent,
    marker_writer=write_startup_marker,
) -> bool:
    try:
        start_agent(paths)
        if not wait_for_agent(version):
            logger.error("Agent did not report expected version %s", version)
            return False
        marker_writer(paths.updates_dir, version)
        return True
    except Exception:
        logger.exception("Client startup confirmation failed")
        return False


def main():
    paths = ClientPaths.from_environment()

    def started():
        threading.Thread(
            target=_confirm_startup,
            args=(paths, get_version()),
            daemon=True,
        ).start()

    if not start_ui(on_started=started) and is_setup_complete():
        subprocess.Popen([sys.executable], cwd=str(paths.install_dir), close_fds=True)


if __name__ == "__main__":
    main()
