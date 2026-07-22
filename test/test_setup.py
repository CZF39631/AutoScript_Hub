import importlib.util
import os
import subprocess
from pathlib import Path


def _load_installer():
    setup_path = Path(__file__).resolve().parents[1] / "setup.py"
    spec = importlib.util.spec_from_file_location("autoscript_installer", setup_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _prepare_frontend(root: Path):
    frontend = root / "frontend"
    frontend.mkdir(parents=True)
    (frontend / "package-lock.json").write_text("{}", encoding="utf-8")
    return frontend


def test_build_frontend_assets_runs_clean_install_and_deploys_both_targets(tmp_path, monkeypatch):
    installer = _load_installer()
    frontend = _prepare_frontend(tmp_path)
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        if command[1:] == ["run", "build"]:
            dist = frontend / "dist"
            dist.mkdir()
            (dist / "index.html").write_text("<main>ready</main>", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(installer, "PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(installer.shutil, "which", lambda name: r"C:\\Node\\npm.cmd")
    monkeypatch.setattr(installer.subprocess, "run", fake_run)

    assert installer._build_frontend_assets() is True
    assert [call[0] for call in calls] == [
        [r"C:\\Node\\npm.cmd", "ci"],
        [r"C:\\Node\\npm.cmd", "run", "build"],
    ]
    assert all(call[1]["shell"] is False for call in calls)
    assert (tmp_path / "backend" / "static" / "index.html").read_text(encoding="utf-8") == "<main>ready</main>"
    assert (tmp_path / "client" / "ui" / "static" / "index.html").read_text(encoding="utf-8") == "<main>ready</main>"


def test_build_frontend_assets_fails_when_npm_is_missing(tmp_path, monkeypatch):
    installer = _load_installer()
    _prepare_frontend(tmp_path)
    monkeypatch.setattr(installer, "PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(installer.shutil, "which", lambda name: None)

    assert installer._build_frontend_assets() is False


def test_build_frontend_assets_stops_after_failed_dependency_install(tmp_path, monkeypatch):
    installer = _load_installer()
    _prepare_frontend(tmp_path)
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="install failed")

    monkeypatch.setattr(installer, "PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(installer.shutil, "which", lambda name: "npm")
    monkeypatch.setattr(installer.subprocess, "run", fake_run)

    assert installer._build_frontend_assets() is False
    assert calls == [["npm", "ci"]]
    assert not os.path.exists(tmp_path / "backend" / "static")


def test_new_development_configs_default_to_the_current_release_version():
    installer = _load_installer()
    source = Path(installer.__file__).read_text(encoding="utf-8")

    assert installer.RELEASE_VERSION == "0.9.0"
    assert 'existing.get("client_version", RELEASE_VERSION)' in source
    assert 'existing.get("version", RELEASE_VERSION)' in source
