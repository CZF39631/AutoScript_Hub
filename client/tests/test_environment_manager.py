import json
from pathlib import Path

import pytest

from client.runtime.environment_manager import (
    EnvironmentUnavailable,
    ensure_environment,
    environment_fingerprint,
)
from client.runtime.paths import ClientPaths


def _paths(tmp_path):
    paths = ClientPaths.from_environment(
        install_dir=tmp_path / "install",
        data_dir=tmp_path / "data",
    )
    paths.ensure()
    private = paths.runtime_dir / "python" / "python.exe"
    private.parent.mkdir(parents=True, exist_ok=True)
    private.write_bytes(b"python")
    return paths, private


def test_environment_fingerprint_is_stable_and_input_sensitive():
    first = environment_fingerprint(["Requests>=2.31", "openpyxl==3.1.5"], "3.11.9", "https://pypi.org/simple")
    reordered = environment_fingerprint(["openpyxl==3.1.5", "requests>=2.31"], "3.11.9", "https://pypi.org/simple/")
    mirror = environment_fingerprint(["requests>=2.31", "openpyxl==3.1.5"], "3.11.9", "https://pypi.tuna.tsinghua.edu.cn/simple")

    assert first == reordered
    assert first != mirror
    assert len(first) == 32


def test_offline_mode_rejects_a_missing_environment(tmp_path):
    paths, private = _paths(tmp_path)

    with pytest.raises(EnvironmentUnavailable, match="离线"):
        ensure_environment(["requests>=2.31"], paths, offline=True, python_executable=private)


def test_environment_build_is_transactional_and_reused(tmp_path, monkeypatch):
    paths, private = _paths(tmp_path)
    builds = []

    def fake_build(staging, python_executable, requirements, index_url):
        builds.append(staging)
        environment_python = staging / "Scripts" / "python.exe"
        environment_python.parent.mkdir(parents=True)
        environment_python.write_bytes(b"venv-python")

    monkeypatch.setattr("client.runtime.environment_manager._build_environment", fake_build)

    created = ensure_environment(["requests>=2.31"], paths, python_executable=private)
    reused = ensure_environment(["requests>=2.31"], paths, python_executable=private)

    assert created.created is True
    assert reused.created is False
    assert created.path == reused.path
    assert len(builds) == 1
    assert json.loads((created.path / "environment.json").read_text("utf-8"))["status"] == "ready"
    assert not list(paths.environments_dir.glob("*.tmp-*"))


def test_failed_build_removes_staging_directory(tmp_path, monkeypatch):
    paths, private = _paths(tmp_path)

    def fail_build(staging, python_executable, requirements, index_url):
        (staging / "partial.txt").write_text("partial", encoding="utf-8")
        raise RuntimeError("pip failed")

    monkeypatch.setattr("client.runtime.environment_manager._build_environment", fail_build)

    with pytest.raises(RuntimeError, match="pip failed"):
        ensure_environment(["broken-package"], paths, python_executable=private)

    assert not list(paths.environments_dir.glob("*.tmp-*"))
