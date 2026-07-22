"""Compatibility facade for the signed installer update subsystem."""

import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
from typing import Dict

from client.runtime.paths import ClientPaths
from client.update.service import UpdateService
from client.update.sources import DirectManifestSource, GitHubReleaseSource
from client.update.state import UpdateStateStore
from client.update.trust import load_update_public_key


logger = logging.getLogger(__name__)
_lock = threading.Lock()
_active_service = None


def _detached_flags() -> int:
    if sys.platform != "win32":
        return 0
    return 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP


def _handoff(paths: ClientPaths, installer: Path, version: str) -> None:
    updater_executable = paths.install_dir / "AutoScriptUpdater.exe"
    ui_executable = paths.install_dir / "AutoScriptHub.exe"
    if updater_executable.is_file():
        bootstrap = paths.updates_dir / f"updater-bootstrap-{version}.exe"
        temporary = bootstrap.with_suffix(".tmp")
        shutil.copy2(updater_executable, temporary)
        os.replace(temporary, bootstrap)
        command = [str(bootstrap)]
        working_directory = paths.updates_dir
    elif not getattr(sys, "frozen", False):
        command = [sys.executable, "-m", "client.updater_main"]
        ui_executable = Path(sys.executable)
        working_directory = paths.install_dir
    else:
        raise FileNotFoundError("AutoScriptUpdater.exe 不存在")
    command.extend(
        [
            "--installer", str(installer),
            "--previous-installer", str(paths.updates_dir / "previous-installer.exe"),
            "--ui", str(ui_executable),
            "--version", version,
            "--updates-dir", str(paths.updates_dir),
            "--pid", str(os.getpid()),
        ]
    )
    subprocess.Popen(
        command,
        cwd=str(working_directory),
        creationflags=_detached_flags(),
        close_fds=True,
    )


def _sources(config: dict):
    sources = [
        DirectManifestSource(url)
        for url in config.get("update_manifest_urls", [])
        if isinstance(url, str) and url.strip()
    ]
    repository = config.get("github_update_repository", "CZF39631/AutoScript_Hub")
    if repository:
        sources.append(GitHubReleaseSource(repository, channel=config.get("update_channel", "beta")))
    return sources


def _service(
    current_version: str,
    runtime_is_idle=lambda: True,
) -> UpdateService:
    paths = ClientPaths.from_environment()
    from client.ui.config_manager import load_config
    config = load_config()
    return UpdateService(
        paths=paths,
        current_version=current_version,
        public_key=load_update_public_key(),
        sources=_sources(config),
        expected_channel=config.get("update_channel") or "beta",
        runtime_is_idle=runtime_is_idle,
        handoff=lambda installer, version: _handoff(paths, installer, version),
    )


def check_and_stage_update(current_version: str, runtime_is_idle=lambda: True) -> dict:
    """Check signed public sources and download a verified installer for manual approval."""
    global _active_service
    try:
        with _lock:
            service = _service(current_version, runtime_is_idle)
            checked = service.check()
            if checked.state == "available":
                checked = service.stage()
            _active_service = service
            return service.store.read()
    except Exception:
        logger.exception("签名更新检查失败，继续运行当前版本")
        return get_update_status()


def get_update_status() -> dict:
    paths = ClientPaths.from_environment()
    paths.ensure()
    return UpdateStateStore(paths.updates_dir).read()


def install_staged_update(current_version: str, runtime_is_idle=lambda: True) -> dict:
    """Install only after an explicit local UI request."""
    global _active_service
    try:
        with _lock:
            service = _active_service or _service(current_version, runtime_is_idle)
            service.runtime_is_idle = runtime_is_idle
            result = service.request_install()
            _active_service = service
            return service.store.read() | {"state": result.state}
    except Exception as exc:
        logger.exception("无法启动已暂存更新")
        return get_update_status() | {"error": str(exc)}


def check_and_apply_update(
    backend_url: str,
    headers: Dict[str, str],
    current_version: str,
    project_root: str,
    username: str = "",
    password: str = "",
    runtime_is_idle=lambda: True,
) -> bool:
    """Backward-compatible check that now stages only; installation is user-controlled."""
    del backend_url, headers, project_root, username, password
    check_and_stage_update(current_version, runtime_is_idle)
    return False
