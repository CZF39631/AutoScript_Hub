#!/usr/bin/env python3
"""Smoke-test an installed Windows client and clean up only processes it starts."""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen


def _image_pids(image_name: str) -> set[int]:
    completed = subprocess.run(
        ["tasklist.exe", "/FI", f"IMAGENAME eq {image_name}", "/FO", "CSV", "/NH"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    pids: set[int] = set()
    for row in csv.reader(io.StringIO(completed.stdout)):
        if len(row) >= 2 and row[0].lower() == image_name.lower():
            try:
                pids.add(int(row[1]))
            except ValueError:
                pass
    return pids


def _wait_json(url: str, timeout: float = 30) -> dict:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return json.loads(response.read().decode("utf-8"))
        except (OSError, URLError, ValueError, json.JSONDecodeError) as exc:
            last_error = exc
        time.sleep(0.25)
    raise RuntimeError(f"timed out waiting for {url}: {last_error}")


def _wait_http(url: str, timeout: float = 30) -> bytes:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return response.read()
        except (OSError, URLError) as exc:
            last_error = exc
        time.sleep(0.25)
    raise RuntimeError(f"timed out waiting for {url}: {last_error}")


def _wait_port_closed(url: str, timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=1):
                time.sleep(0.2)
        except (OSError, URLError):
            return
    raise RuntimeError(f"process stopped but endpoint is still serving: {url}")


def _terminate_pid(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        return
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        all_pids = _image_pids("AutoScriptHub.exe") | _image_pids("AutoScriptAgent.exe")
        if pid not in all_pids:
            return
        time.sleep(0.2)
    subprocess.run(
        ["taskkill.exe", "/PID", str(pid), "/F"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _assert_runtime(payload: dict) -> None:
    if payload.get("version") != "3.11.9" or payload.get("managed") is not True:
        raise RuntimeError(f"managed Python 3.11.9 was not reported: {payload}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--install-dir", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--expected-version", default="0.9.1")
    args = parser.parse_args()

    install_dir = args.install_dir.resolve()
    data_dir = args.data_dir.resolve()
    ui = install_dir / "AutoScriptHub.exe"
    agent = install_dir / "AutoScriptAgent.exe"
    for executable in (ui, agent, install_dir / "runtime" / "python" / "python.exe"):
        if not executable.is_file():
            parser.error(f"installed file is missing: {executable}")

    baseline = _image_pids(ui.name) | _image_pids(agent.name)
    if baseline:
        parser.error(f"refusing to interfere with existing AutoScript processes: {sorted(baseline)}")

    config_dir = data_dir / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "client.json").write_text(
        json.dumps(
            {
                "server_url": "http://127.0.0.1:65534",
                "username": "acceptance-user",
                "password": "acceptance-only",
                "github_update_repository": "",
                "update_channel": "beta",
                "update_manifest_urls": [],
                "setup_completed": True,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["AUTOSCRIPT_CLIENT_DATA_DIR"] = str(data_dir)
    system_root = environment.get("SystemRoot", r"C:\Windows")
    environment["PATH"] = os.pathsep.join(
        [system_root, str(Path(system_root) / "System32")]
    )
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    started_pids: set[int] = set()

    try:
        standalone = subprocess.Popen(
            [str(agent)],
            cwd=install_dir,
            env=environment,
            startupinfo=startup,
        )
        started_pids.add(standalone.pid)
        status = _wait_json("http://127.0.0.1:18080/status")
        runtime = _wait_json("http://127.0.0.1:18080/local/runtime")
        if status.get("version") != args.expected_version:
            raise RuntimeError(f"unexpected installed Agent version: {status}")
        _assert_runtime(runtime)
        print("standalone_agent_status=" + json.dumps(status, ensure_ascii=False, sort_keys=True))
        print("standalone_runtime=" + json.dumps(runtime, ensure_ascii=False, sort_keys=True))
        _terminate_pid(standalone.pid)
        started_pids.discard(standalone.pid)
        _wait_port_closed("http://127.0.0.1:18080/status")

        ui_process = subprocess.Popen(
            [str(ui)],
            cwd=install_dir,
            env=environment,
            startupinfo=startup,
        )
        started_pids.add(ui_process.pid)
        html = _wait_http("http://127.0.0.1:18081/")
        status = _wait_json("http://127.0.0.1:18080/status")
        runtime = _wait_json("http://127.0.0.1:18080/local/runtime")
        new_agents = _image_pids(agent.name) - baseline
        started_pids.update(new_agents)
        if b'id="root"' not in html:
            raise RuntimeError("installed UI did not serve the packaged frontend root")
        if status.get("version") != args.expected_version:
            raise RuntimeError(f"UI-started Agent version mismatch: {status}")
        _assert_runtime(runtime)
        print(f"ui_pid={ui_process.pid}")
        print("ui_started_agent_status=" + json.dumps(status, ensure_ascii=False, sort_keys=True))
        print("ui_started_runtime=" + json.dumps(runtime, ensure_ascii=False, sort_keys=True))
        _terminate_pid(ui_process.pid)
        started_pids.discard(ui_process.pid)
        _wait_port_closed("http://127.0.0.1:18081/")
        status_after_ui_close = _wait_json("http://127.0.0.1:18080/status", timeout=10)
        if status_after_ui_close.get("version") != args.expected_version:
            raise RuntimeError(f"Agent stopped when the UI closed: {status_after_ui_close}")
        print("agent_after_ui_close=" + json.dumps(status_after_ui_close, ensure_ascii=False, sort_keys=True))
        print(f"isolated_path={environment['PATH']}")
        print("installed_ui_agent_smoke=true")
        return 0
    finally:
        started_pids.update((_image_pids(ui.name) | _image_pids(agent.name)) - baseline)
        for pid in sorted(started_pids, reverse=True):
            _terminate_pid(pid)


if __name__ == "__main__":
    raise SystemExit(main())
