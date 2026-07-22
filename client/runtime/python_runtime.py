"""Discovery and diagnostics for the installer-owned Python runtime."""

from pathlib import Path
import subprocess

from client.runtime.paths import ClientPaths


PRIVATE_PYTHON_VERSION = "3.11.9"


class PrivatePythonUnavailable(RuntimeError):
    pass


def private_python(paths: ClientPaths) -> Path:
    executable = paths.runtime_dir / "python" / "python.exe"
    if not executable.is_file():
        raise PrivatePythonUnavailable(f"私有 Python 不存在: {executable}")
    return executable


def python_runtime_info(paths: ClientPaths) -> dict:
    executable = private_python(paths)
    completed = subprocess.run(
        [str(executable), "--version"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    output = (completed.stdout or completed.stderr).strip()
    actual = output.removeprefix("Python ")
    return {
        "path": str(executable),
        "expected_version": PRIVATE_PYTHON_VERSION,
        "actual_version": actual,
        "ready": completed.returncode == 0 and actual == PRIVATE_PYTHON_VERSION,
    }
