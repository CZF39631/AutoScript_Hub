"""安装身份必须在任何更新副作用之前检查。"""

import base64
import hashlib
import json
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from client.agent import updater
from client import updater_main
from client.runtime.paths import ClientPaths
from client.update.service import UpdateService


def _forbidden(*args, **kwargs):
    pytest.fail("Preview 不应触发更新副作用")


@pytest.mark.parametrize("operation", ["check_and_stage_update", "install_staged_update", "get_update_status"])
def test_preview_facade_returns_disabled_without_paths_or_service(monkeypatch, operation):
    monkeypatch.setenv("AUTOSCRIPT_INSTALL_FLAVOR", "preview")
    monkeypatch.setattr(updater, "_service", _forbidden)
    monkeypatch.setattr(updater.ClientPaths, "from_environment", _forbidden)
    monkeypatch.setattr(updater, "_active_service", SimpleNamespace(
        check=_forbidden, download=_forbidden, request_install=_forbidden,
    ))
    args = () if operation == "get_update_status" else ("1.2.4",)
    result = getattr(updater, operation)(*args)
    assert result["state"] == "idle"
    assert result["updates_enabled"] is False
    assert "手动安装独立 Preview" in result["error"]


def test_preview_handoff_and_service_factory_reject_before_copy_or_config(monkeypatch):
    monkeypatch.setenv("AUTOSCRIPT_INSTALL_FLAVOR", "preview")
    monkeypatch.setattr(updater.shutil, "copy2", _forbidden)
    monkeypatch.setattr(updater.subprocess, "Popen", _forbidden)
    monkeypatch.setattr(updater.ClientPaths, "from_environment", _forbidden)
    with pytest.raises(RuntimeError, match="手动安装独立 Preview"):
        updater._handoff(None, None, "1.2.5")
    with pytest.raises(RuntimeError, match="手动安装独立 Preview"):
        updater._service("1.2.4")


def test_preview_service_constructor_rejects_before_paths(monkeypatch):
    monkeypatch.setenv("AUTOSCRIPT_INSTALL_FLAVOR", "preview")
    with pytest.raises(RuntimeError, match="手动安装独立 Preview"):
        UpdateService(None, "1.2.4", b"", [])


@pytest.mark.parametrize("operation", ["check", "download", "stage", "request_install"])
def test_preview_existing_service_rejects_before_state_network_or_handoff(monkeypatch, operation):
    monkeypatch.setenv("AUTOSCRIPT_INSTALL_FLAVOR", "preview")
    # Missing attributes deliberately prove the identity guard is first.
    service = object.__new__(UpdateService)
    with pytest.raises(RuntimeError, match="手动安装独立 Preview"):
        getattr(service, operation)()


def test_preview_independent_updater_refuses_install_and_rollback(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("AUTOSCRIPT_INSTALL_FLAVOR", "preview")
    monkeypatch.setattr(updater_main, "UpdateStateStore", _forbidden)
    monkeypatch.setattr(updater_main, "wait_for_processes", _forbidden)
    monkeypatch.setattr(updater_main.shutil, "copy2", _forbidden)
    assert updater_main.run_update(
        tmp_path / "new.exe", tmp_path / "old.exe", tmp_path / "ui.exe",
        "1.2.5", [123], tmp_path / "updates", run_command=_forbidden,
        launch=_forbidden, wait_for_startup=_forbidden,
    ) == updater_main.EXIT_UPDATES_DISABLED
    # Identity is checked even before argument parsing and direct invocation.
    monkeypatch.setattr(updater_main, "run_update", _forbidden)
    assert updater_main.main([]) == updater_main.EXIT_UPDATES_DISABLED
    assert "手动安装独立 Preview" in capsys.readouterr().err
    assert not (tmp_path / "updates").exists()


def test_formal_handoff_refuses_preview_target_before_copy(monkeypatch):
    monkeypatch.setenv("AUTOSCRIPT_INSTALL_FLAVOR", "stable")
    monkeypatch.setattr(updater.shutil, "copy2", _forbidden)
    monkeypatch.setattr(updater.subprocess, "Popen", _forbidden)
    with pytest.raises(RuntimeError, match="不能安装 Preview"):
        updater._handoff(None, None, "1.3.0-preview.1")


def test_formal_independent_updater_refuses_preview_target(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("AUTOSCRIPT_INSTALL_FLAVOR", "stable")
    monkeypatch.setattr(updater_main, "UpdateStateStore", _forbidden)
    monkeypatch.setattr(updater_main, "wait_for_processes", _forbidden)
    assert updater_main.run_update(
        tmp_path / "new.exe", tmp_path / "old.exe", tmp_path / "ui.exe",
        "1.3.0-preview.1", [], tmp_path / "updates", run_command=_forbidden,
        launch=_forbidden, wait_for_startup=_forbidden,
    ) == updater_main.EXIT_UPDATES_DISABLED
    assert "不能安装 Preview" in capsys.readouterr().err
    assert not (tmp_path / "updates").exists()


def test_frozen_preview_updater_cannot_be_downgraded_by_environment(monkeypatch, capsys):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setitem(sys.modules, "autoscript_build_info", SimpleNamespace(
        INSTALL_FLAVOR="preview", CHANNEL="stable", VERSION="1.2.5",
    ))
    monkeypatch.setenv("AUTOSCRIPT_INSTALL_FLAVOR", "stable")
    monkeypatch.setattr(updater_main, "run_update", _forbidden)
    assert updater_main.main([]) == updater_main.EXIT_UPDATES_DISABLED
    assert "手动安装独立 Preview" in capsys.readouterr().err


@pytest.mark.parametrize("channel", ["stable", "beta"])
def test_formal_facade_preserves_selected_channel(monkeypatch, channel):
    monkeypatch.setenv("AUTOSCRIPT_INSTALL_FLAVOR", "stable")
    from client.ui import config_manager
    config = {"update_channel": channel, "server_url": "https://example.com"}
    monkeypatch.setattr(config_manager, "load_config", lambda: config)
    monkeypatch.setattr(updater.ClientPaths, "from_environment", lambda: object())
    monkeypatch.setattr(updater, "load_update_public_key", lambda: b"key")
    factory = Mock()
    monkeypatch.setattr(updater, "UpdateService", factory)
    updater._service("1.2.4")
    kwargs = factory.call_args.kwargs
    assert kwargs["expected_channel"] == channel
    assert kwargs["sources"][0].manifest_url.endswith(f"/manifest/{channel}")
    assert kwargs["sources"][-1].channel == channel
    assert config["update_channel"] == channel


def _formal_service(tmp_path, version, channel="stable", http_get=_forbidden, handoff=_forbidden):
    key = Ed25519PrivateKey.generate()
    installer = b"signed installer"
    payload = {
        "schema_version": 1, "product": "autoscript-hub-client",
        "version": version, "channel": channel,
        "published_at": "2026-07-21T00:00:00Z",
        "minimum_client_version": "1.2.4",
        "release_notes_url": "https://example.com/release",
        "assets": {"windows-x86_64": {
            "filename": f"Setup-{version}.exe", "size": len(installer),
            "sha256": hashlib.sha256(installer).hexdigest(),
            "urls": ["https://example.com/installer.exe"],
        }},
    }
    raw = json.dumps(payload).encode()
    signature = key.sign(raw)
    paths = ClientPaths.from_environment(install_dir=tmp_path / "install", data_dir=tmp_path / "data")
    service = UpdateService(
        paths, "1.2.4",
        key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw),
        [SimpleNamespace(fetch=lambda: (raw, signature))], expected_channel=channel,
        http_get=http_get, handoff=handoff,
    )
    return service, raw, signature, installer


@pytest.mark.parametrize("channel", ["stable", "beta"])
@pytest.mark.parametrize("version", ["1.3.0-preview.1", "1.3.0-PREVIEW1", "v1.3.0-preview-1+build.1"])
def test_formal_rejects_signed_explicit_preview(monkeypatch, tmp_path, version, channel):
    monkeypatch.setenv("AUTOSCRIPT_INSTALL_FLAVOR", "stable")
    service, raw, signature, _ = _formal_service(tmp_path, version, channel)
    result = service.check()
    assert result.state == "idle"
    assert "不能安装 Preview" in result.error
    assert service.manifest is None
    service.store.transition("checking")
    service.store.transition("available", version=version,
        manifest_payload_b64=base64.b64encode(raw).decode(),
        manifest_signature_b64=base64.b64encode(signature).decode())
    service._recover_discovered_update()
    assert service.store.read()["state"] == "idle"
    assert service.manifest is None


@pytest.mark.parametrize("channel", ["stable", "beta"])
def test_formal_rejects_recovered_preview_installer(monkeypatch, tmp_path, channel):
    monkeypatch.setenv("AUTOSCRIPT_INSTALL_FLAVOR", "stable")
    service, _, _, installer = _formal_service(tmp_path, "1.3.0-preview.1", channel)
    path = service.paths.updates_dir / "setup.exe"
    path.write_bytes(installer)
    for state in ("checking", "available", "downloading"):
        service.store.transition(state)
    service.store.transition("verified", version="1.3.0-preview.1", installer=str(path),
        size=len(installer), sha256=hashlib.sha256(installer).hexdigest())
    service._recover_staged_update()
    assert service.store.read()["state"] == "idle"
    assert service.installer is None


@pytest.mark.parametrize("operation", ["download", "request_install"])
@pytest.mark.parametrize("channel", ["stable", "beta"])
def test_preview_target_guard_runs_before_download_or_install(monkeypatch, operation, channel):
    monkeypatch.setenv("AUTOSCRIPT_INSTALL_FLAVOR", "stable")
    service = object.__new__(UpdateService)
    service.expected_channel = channel
    service.manifest = SimpleNamespace(version="1.3.0-preview.1")
    service.pending_version = "1.3.0-preview.1"
    service.installer = object()
    with pytest.raises(ValueError, match="不能安装 Preview"):
        getattr(service, operation)()


@pytest.mark.parametrize("channel", ["stable", "beta"])
@pytest.mark.parametrize("version", ["1.3.0", "1.3.0-beta.1", "1.3.0a1", "1.3.0rc1", "1.3.0.dev1"])
def test_formal_family_keeps_non_preview_updates(monkeypatch, tmp_path, channel, version):
    monkeypatch.setenv("AUTOSCRIPT_INSTALL_FLAVOR", "stable")
    handoff = Mock()
    service, _, _, installer = _formal_service(
        tmp_path, version, channel, http_get=lambda url: b"signed installer", handoff=handoff,
    )
    assert service.check().state == "available"
    assert service.download().state == "verified"
    assert service.installer.read_bytes() == installer
    assert service.request_install().state == "installing"
    handoff.assert_called_once_with(service.installer, version)


def test_beta_channel_still_accepts_stable_release(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOSCRIPT_INSTALL_FLAVOR", "stable")
    service, _, _, _ = _formal_service(tmp_path, "1.3.0", "stable")
    service.expected_channel = "beta"
    assert service.check().state == "available"
