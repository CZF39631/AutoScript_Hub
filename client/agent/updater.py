"""Client auto-update flow (design §5.8).

Steps performed when a newer client version is published on the server:
  1. GET /api/agent/check-update?version=X.X.X → check if update available
  2. If available + package present → download zip
  3. Extract to staging dir
  4. Spawn a detached updater batch script that:
     a. Waits for current process to exit
     b. Copies new files over the project root
     c. Restarts the agent
  5. Current process exits cleanly

Windows-specific (project targets Windows per design §1.4: Python 3.8.10 +
pywebview desktop client). The delayed-copy via batch script is the standard
Windows pattern for replacing files locked by a running process.
"""
import logging
import os
import shutil
import subprocess
import sys
import time
import zipfile
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)


def check_and_apply_update(
    backend_url: str,
    headers: Dict[str, str],
    current_version: str,
    project_root: str,
    username: str = "",
    password: str = "",
) -> bool:
    """Check for client update; if available, download, stage, and trigger restart.

    Returns True if an update was triggered (process will exit).
    Returns False if no update available or staging failed (caller continues).
    """
    try:
        resp = requests.get(
            "{}/api/agent/check-update".format(backend_url),
            params={"version": current_version},
            headers=headers,
            timeout=10,
        )
        if resp.status_code != 200:
            return False
        data = resp.json()
        if not data.get("update_available") or not data.get("package_available"):
            return False

        latest = data["latest_version"]
        print("=" * 60)
        print("  AUTO-UPDATE: {} -> {}".format(current_version, latest))
        print("=" * 60)

        # 1) Download the package
        zip_path = _download_package(backend_url, headers, latest, project_root)
        if not zip_path:
            print("更新下载失败,中止更新")
            return False

        # 2) Extract to staging
        extract_dir = _extract_package(zip_path, project_root)
        if not extract_dir:
            print("更新解压失败,中止更新")
            return False

        # 3) Spawn detached updater script
        if not _spawn_updater_script(extract_dir, project_root, username, password):
            print("启动更新脚本失败,中止更新")
            return False

        print("更新已就绪,Agent 将在 3 秒后退出并重启...")
        time.sleep(3)
        return True

    except Exception:
        logger.exception("自动更新失败")
        return False


def _download_package(backend_url: str, headers: Dict[str, str], version: str, project_root: str) -> Optional[str]:
    """Download the client package zip. Returns local path or None."""
    staging = os.path.join(project_root, ".update_staging")
    os.makedirs(staging, exist_ok=True)
    zip_path = os.path.join(staging, "client-{}.zip".format(version))

    try:
        resp = requests.get(
            "{}/api/agent/download/{}".format(backend_url, version),
            headers=headers,
            stream=True,
            timeout=120,
        )
        if resp.status_code != 200:
            return None
        with open(zip_path, "wb") as f:
            for chunk in resp.iter_content(8192):
                f.write(chunk)
        return zip_path
    except (requests.RequestException, OSError) as e:
        logger.warning("下载失败: %s", e)
        return None


def _extract_package(zip_path: str, project_root: str) -> Optional[str]:
    """Extract package to staging/extracted/. Returns extract dir or None."""
    staging = os.path.join(project_root, ".update_staging")
    extract_dir = os.path.join(staging, "extracted")
    try:
        if os.path.isdir(extract_dir):
            shutil.rmtree(extract_dir, ignore_errors=True)
        os.makedirs(extract_dir, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)
        return extract_dir
    except (OSError, zipfile.BadZipFile) as e:
        logger.warning("解压失败: %s", e)
        return None


def _spawn_updater_script(staged_src: str, project_root: str, username: str, password: str) -> bool:
    """Create + spawn a detached batch script that replaces files and restarts.

    Uses `ping 127.0.0.1` as a portable Windows sleep, `xcopy /E /Y` to overwrite
    project files, then `start python client/start.py` to relaunch the client.
    Passes credentials via environment variables to avoid leaking on command line.
    """
    bat_path = os.path.join(project_root, ".update_staging", "updater.bat")

    # Wrap paths in quotes to survive spaces
    lines = [
        "@echo off",
        "title AutoScript Hub Updater",
        "ping 127.0.0.1 -n 4 > nul",
        "echo Applying update...",
        'xcopy /E /Y /I "{}" "{}"'.format(staged_src, project_root),
        "echo Restarting client...",
        'cd /d "{}"'.format(project_root),
        "set AUTOSCRIPT_RESTART_USER={}".format(username),
        "set AUTOSCRIPT_RESTART_PASS={}".format(password),
        'start "" python "{}"'.format(os.path.join(project_root, "client", "start.py")),
        "echo Update complete.",
        "del \"%~f0\"",
    ]
    try:
        with open(bat_path, "w", encoding="utf-8") as f:
            f.write("\r\n".join(lines))
    except OSError as e:
        logger.warning("写入 updater.bat 失败: %s", e)
        return False

    try:
        creationflags = 0
        if sys.platform == "win32":
            # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
            creationflags = 0x00000008 | 0x00000200
        subprocess.Popen(
            ["cmd", "/c", bat_path],
            creationflags=creationflags,
            close_fds=True,
            cwd=project_root,
        )
        return True
    except OSError as e:
        logger.warning("启动 updater.bat 失败: %s", e)
        return False
