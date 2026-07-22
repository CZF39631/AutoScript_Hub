"""Independent installer handoff and rollback executable entrypoint."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from typing import Callable, Iterable

from client.update.state import UpdateStateStore


EXIT_OK = 0
EXIT_INSTALL_FAILED = 10
EXIT_ROLLED_BACK = 20
EXIT_ROLLBACK_FAILED = 21


def installer_command(installer: Path) -> list[str]:
    return [
        str(installer),
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        "/CLOSEAPPLICATIONS",
    ]


def wait_for_processes(pids: Iterable[int], timeout_seconds: int = 300) -> bool:
    remaining = {pid for pid in pids if pid > 0 and pid != os.getpid()}
    deadline = time.monotonic() + timeout_seconds
    while remaining and time.monotonic() < deadline:
        stopped = set()
        for pid in remaining:
            try:
                os.kill(pid, 0)
            except OSError:
                stopped.add(pid)
        remaining -= stopped
        if remaining:
            time.sleep(0.25)
    return not remaining


def wait_for_startup_marker(marker: Path, expected_version: str, timeout_seconds: int = 90) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            value = json.loads(marker.read_text(encoding="utf-8"))
            if value.get("version") == expected_version and value.get("status") == "ok":
                return True
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            pass
        time.sleep(0.5)
    return False


def write_startup_marker(updates_dir: Path, version: str) -> Path:
    updates_dir.mkdir(parents=True, exist_ok=True)
    marker = updates_dir / "startup-ok.json"
    temporary = marker.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"status": "ok", "version": version, "pid": os.getpid()}) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, marker)
    return marker


def _default_run(command):
    return subprocess.run(command, check=False)


def _default_launch(command):
    subprocess.Popen(command, close_fds=True)


def run_update(
    installer: Path,
    previous_installer: Path,
    ui_executable: Path,
    expected_version: str,
    pids: Iterable[int],
    updates_dir: Path,
    run_command: Callable = _default_run,
    launch: Callable = _default_launch,
    wait_for_startup: Callable = wait_for_startup_marker,
) -> int:
    store = UpdateStateStore(updates_dir)
    marker = updates_dir / "startup-ok.json"
    try:
        marker.unlink()
    except FileNotFoundError:
        pass
    if not wait_for_processes(pids):
        store.transition("rolled-back", error="等待客户端进程退出超时")
        return EXIT_INSTALL_FAILED

    installed = run_command(installer_command(installer))
    if installed.returncode != 0:
        if previous_installer.is_file() and run_command(installer_command(previous_installer)).returncode == 0:
            launch([str(ui_executable)])
            store.transition("rolled-back", error=f"新安装器退出码 {installed.returncode}")
            return EXIT_ROLLED_BACK
        store.transition("rolled-back", error=f"新安装器退出码 {installed.returncode}，回退失败")
        return EXIT_ROLLBACK_FAILED

    store.transition("verifying-startup", version=expected_version)
    launch([str(ui_executable)])
    if wait_for_startup(marker, expected_version, 90):
        shutil.copy2(installer, previous_installer)
        store.transition("succeeded", version=expected_version)
        return EXIT_OK

    if previous_installer.is_file() and run_command(installer_command(previous_installer)).returncode == 0:
        launch([str(ui_executable)])
        store.transition("rolled-back", error="新版本未写入启动成功标记")
        return EXIT_ROLLED_BACK
    store.transition("rolled-back", error="新版本启动失败且上一安装包回退失败")
    return EXIT_ROLLBACK_FAILED


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--installer", type=Path, required=True)
    parser.add_argument("--previous-installer", type=Path, required=True)
    parser.add_argument("--ui", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--updates-dir", type=Path, required=True)
    parser.add_argument("--pid", action="append", type=int, default=[])
    args = parser.parse_args(argv)
    return run_update(
        args.installer,
        args.previous_installer,
        args.ui,
        args.version,
        args.pid,
        args.updates_dir,
    )


if __name__ == "__main__":
    raise SystemExit(main())
