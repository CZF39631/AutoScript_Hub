"""Fingerprint, build, and atomically reuse per-script virtual environments."""

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from typing import Iterable, Optional
import uuid

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from client.runtime.paths import ClientPaths
from client.runtime.python_runtime import PRIVATE_PYTHON_VERSION, private_python


class EnvironmentUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class EnvironmentResult:
    fingerprint: str
    path: Path
    python_executable: Path
    created: bool


def _canonical_requirement(value: str) -> str:
    requirement = Requirement(value)
    result = canonicalize_name(requirement.name)
    if requirement.extras:
        result += "[{}]".format(",".join(sorted(canonicalize_name(item) for item in requirement.extras)))
    if requirement.url:
        result += " @ " + requirement.url
    else:
        result += str(requirement.specifier)
    if requirement.marker:
        result += "; " + str(requirement.marker)
    return result


def normalized_requirements(requirements: Iterable[str]) -> list[str]:
    return sorted({_canonical_requirement(value) for value in requirements}, key=str.casefold)


def environment_fingerprint(
    requirements: Iterable[str],
    python_version: str,
    index_url: Optional[str],
) -> str:
    payload = {
        "contract": 1,
        "python": python_version,
        "platform": "windows-x86_64",
        "requirements": normalized_requirements(requirements),
        "index_url": (index_url or "https://pypi.org/simple").rstrip("/"),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:32]


def _environment_python(directory: Path) -> Path:
    return directory / "Scripts" / "python.exe"


def _environment_ready(directory: Path) -> bool:
    metadata = directory / "environment.json"
    executable = _environment_python(directory)
    if not metadata.is_file() or not executable.is_file():
        return False
    try:
        return json.loads(metadata.read_text(encoding="utf-8")).get("status") == "ready"
    except (OSError, json.JSONDecodeError):
        return False


@contextmanager
def _fingerprint_lock(lock_path: Path, timeout_seconds: int = 300):
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            descriptor = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(json.dumps({"pid": os.getpid(), "created_at": time.time()}))
            break
        except FileExistsError:
            try:
                if time.time() - lock_path.stat().st_mtime > 1800:
                    lock_path.unlink()
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() >= deadline:
                raise EnvironmentUnavailable(f"等待环境锁超时: {lock_path.name}")
            time.sleep(0.1)
    try:
        yield
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def _run(command: list[str], timeout: int) -> None:
    completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()[-1000:]
        raise RuntimeError(f"环境命令失败 ({completed.returncode}): {detail}")


def _build_environment(
    staging: Path,
    python_executable: Path,
    requirements: list[str],
    index_url: Optional[str],
) -> None:
    _run([str(python_executable), "-m", "venv", str(staging)], timeout=180)
    environment_python = _environment_python(staging)
    if requirements:
        install = [str(environment_python), "-m", "pip", "install"]
        if index_url:
            install.extend(["--index-url", index_url.rstrip("/")])
        install.extend(requirements)
        _run(install, timeout=900)
    _run([str(environment_python), "-m", "pip", "check"], timeout=120)
    _run([str(environment_python), "-c", "import sys; print(sys.executable)"], timeout=30)


def ensure_environment(
    requirements: Iterable[str],
    paths: ClientPaths,
    index_url: Optional[str] = None,
    offline: bool = False,
    python_executable: Optional[os.PathLike[str] | str] = None,
) -> EnvironmentResult:
    paths.ensure()
    normalized = normalized_requirements(requirements)
    fingerprint = environment_fingerprint(normalized, PRIVATE_PYTHON_VERSION, index_url)
    target = paths.environments_dir / fingerprint
    executable = _environment_python(target)
    if _environment_ready(target):
        return EnvironmentResult(fingerprint, target, executable, created=False)
    if offline:
        raise EnvironmentUnavailable(
            "离线状态缺少所需脚本环境；请联网后先准备依赖: {}".format(", ".join(normalized) or "无")
        )

    source_python = Path(python_executable) if python_executable else private_python(paths)
    lock_path = paths.environments_dir / f"{fingerprint}.lock"
    with _fingerprint_lock(lock_path):
        if _environment_ready(target):
            return EnvironmentResult(fingerprint, target, executable, created=False)
        if target.exists():
            shutil.rmtree(target)
        staging = paths.environments_dir / f"{fingerprint}.tmp-{os.getpid()}-{uuid.uuid4().hex}"
        staging.mkdir(parents=True)
        try:
            _build_environment(staging, source_python, normalized, index_url)
            staging_python = _environment_python(staging)
            if not staging_python.is_file():
                raise RuntimeError("虚拟环境未生成 Scripts/python.exe")
            metadata = {
                "status": "ready",
                "fingerprint": fingerprint,
                "python_version": PRIVATE_PYTHON_VERSION,
                "requirements": normalized,
                "index_url": (index_url or "https://pypi.org/simple").rstrip("/"),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            (staging / "environment.json").write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            os.replace(staging, target)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
    return EnvironmentResult(fingerprint, target, executable, created=True)
