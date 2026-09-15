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

import autoscript_build_info
from autoscript_build_info import CHANNEL, VERSION
from shared.version import is_preview_version

os.environ["AUTOSCRIPT_VERSION"] = VERSION
os.environ["AUTOSCRIPT_CHANNEL"] = CHANNEL
os.environ["AUTOSCRIPT_INSTALL_FLAVOR"] = getattr(
    autoscript_build_info, "INSTALL_FLAVOR", "preview" if is_preview_version(VERSION) else "stable"
)

from client.runtime.local_auth import get_or_create_agent_token
from client.runtime.paths import ClientPaths
from client.runtime.profile import agent_ports, get_install_flavor
from client.ui.config_manager import is_setup_complete
from client.ui.main import start_ui
from client.updater_main import write_startup_marker
from shared.version import get_version


logger = logging.getLogger(__name__)
AGENT_PORTS = agent_ports()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _agent_request(path: str, *, method: str = "GET", data=None):
    last_error = None
    for port in AGENT_PORTS:
        request = urllib.request.Request(
            "http://127.0.0.1:{}{}".format(port, path),
            data=data,
            method=method,
            headers={"Authorization": "Bearer " + get_or_create_agent_token()},
        )
        try:
            return urllib.request.build_opener(
                urllib.request.ProxyHandler({}), _NoRedirect()
            ).open(request, timeout=1)
        except Exception as exc:
            last_error = exc
    raise last_error or ConnectionError("本地 Agent 不可用")


def _agent_is_running() -> bool:
    try:
        with _agent_request("/status") as response:
            payload = json.loads(response.read().decode("utf-8"))
            return response.status == 200 and payload.get("install_flavor", "stable") == get_install_flavor()
    except Exception:
        return False


def _agent_has_version(expected_version: str) -> bool:
    try:
        with _agent_request("/status") as response:
            payload = json.loads(response.read().decode("utf-8"))
        return (response.status == 200 and payload.get("version") == expected_version
                and payload.get("install_flavor", "stable") == get_install_flavor())
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


def _request_agent_shutdown() -> bool:
    try:
        with _agent_request("/lifecycle/shutdown", method="POST", data=b"{}") as response:
            return response.status == 202
    except Exception:
        logger.exception("Failed to request Agent shutdown")
        return False


def _watch_agent(paths: ClientPaths, stop_event: threading.Event) -> None:
    """Restart the packaged Agent when it exits and reconnect when it returns."""
    while not stop_event.wait(5):
        if not _agent_is_running():
            try:
                _start_agent(paths)
            except Exception:
                logger.exception("Failed to restart Agent")


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
    stop_event = threading.Event()

    def started():
        threading.Thread(
            target=_confirm_startup,
            args=(paths, get_version()),
            daemon=True,
        ).start()
        threading.Thread(target=_watch_agent, args=(paths, stop_event), daemon=True).start()

    def closed():
        stop_event.set()
        _request_agent_shutdown()

    if not start_ui(on_started=started, on_closed=closed) and is_setup_complete():
        subprocess.Popen([sys.executable], cwd=str(paths.install_dir), close_fds=True)


if __name__ == "__main__":
    main()
