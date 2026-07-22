from dataclasses import dataclass
import hashlib
import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from client.runtime.paths import ClientPaths
from client.update.service import UpdateService


@dataclass
class _Source:
    raw: bytes
    signature: bytes

    def fetch(self):
        return self.raw, self.signature


def _signed_source(key, version, channel="beta"):
    installer = f"installer-{version}".encode()
    payload = {
        "schema_version": 1,
        "product": "autoscript-hub-client",
        "version": version,
        "channel": channel,
        "published_at": "2026-07-21T00:00:00Z",
        "minimum_client_version": "0.9.0",
        "release_notes_url": "https://example.com/release",
        "assets": {"windows-x86_64": {
            "filename": f"AutoScript-Hub-Setup-{version}.exe",
            "size": len(installer),
            "sha256": hashlib.sha256(installer).hexdigest(),
            "urls": [f"https://example.com/{version}.exe"],
        }},
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return _Source(raw, key.sign(raw))


def _service(tmp_path, idle):
    installer = b"signed-installer"
    key = Ed25519PrivateKey.generate()
    payload = {
        "schema_version": 1,
        "product": "autoscript-hub-client",
        "version": "0.9.1",
        "channel": "beta",
        "published_at": "2026-07-21T00:00:00Z",
        "minimum_client_version": "0.9.0",
        "release_notes_url": "https://example.com/release",
        "assets": {"windows-x86_64": {
            "filename": "AutoScript-Hub-Setup-0.9.1.exe",
            "size": len(installer),
            "sha256": hashlib.sha256(installer).hexdigest(),
            "urls": ["https://gitee.example/installer", "https://github.example/installer"],
        }},
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    attempts = []

    def http_get(url):
        attempts.append(url)
        if "gitee" in url:
            raise OSError("mirror unavailable")
        return installer

    paths = ClientPaths.from_environment(install_dir=tmp_path / "install", data_dir=tmp_path / "data")
    return (
        UpdateService(
            paths=paths,
            current_version="0.9.0",
            public_key=public,
            sources=[_Source(raw, key.sign(raw))],
            http_get=http_get,
            runtime_is_idle=lambda: idle,
        ),
        attempts,
    )


def test_download_tries_gitee_then_github_and_persists_verified_state(tmp_path):
    service, attempts = _service(tmp_path, idle=True)

    assert service.check().state == "available"
    result = service.stage()

    assert result.state == "verified"
    assert attempts == ["https://gitee.example/installer", "https://github.example/installer"]
    assert result.installer.is_file()


def test_running_script_defers_install(tmp_path):
    service, _ = _service(tmp_path, idle=False)
    service.check()
    service.stage()

    result = service.request_install()

    assert result.state == "waiting-for-idle"
    service.runtime_is_idle = lambda: True
    assert service.request_install().state == "installing"


def test_verified_update_can_be_resumed_after_agent_restart(tmp_path):
    service, _ = _service(tmp_path, idle=True)
    service.check()
    staged = service.stage()
    handoffs = []

    resumed = UpdateService(
        paths=service.paths,
        current_version="0.9.0",
        public_key=service.public_key,
        sources=[],
        runtime_is_idle=lambda: True,
        handoff=lambda installer, version: handoffs.append((installer, version)),
    )
    result = resumed.request_install()

    assert result.state == "installing"
    assert handoffs == [(staged.installer, "0.9.1")]


def test_scheduled_check_preserves_verified_update_while_offline(tmp_path):
    service, _ = _service(tmp_path, idle=True)
    service.check()
    staged = service.stage()

    resumed = UpdateService(
        paths=service.paths,
        current_version="0.9.0",
        public_key=service.public_key,
        sources=[],
        runtime_is_idle=lambda: True,
    )
    result = resumed.check()

    assert result.state == "verified"
    assert result.installer == staged.installer
    assert result.version == "0.9.1"
    assert resumed.store.read()["state"] == "verified"


def test_check_does_not_reset_an_update_owned_by_updater_process(tmp_path):
    service, _ = _service(tmp_path, idle=True)
    service.check()
    service.stage()
    service.request_install()

    result = service.check()

    assert result.state == "installing"


def test_check_uses_newer_later_source_when_first_valid_manifest_is_stale(tmp_path):
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    paths = ClientPaths.from_environment(install_dir=tmp_path / "install", data_dir=tmp_path / "data")
    service = UpdateService(
        paths=paths,
        current_version="0.9.0",
        public_key=public,
        sources=[_signed_source(key, "0.9.0"), _signed_source(key, "0.9.2")],
        expected_channel="beta",
    )

    result = service.check()

    assert result.state == "available"
    assert result.version == "0.9.2"
    assert service.manifest.version == "0.9.2"


def test_check_ignores_manifest_from_another_update_channel(tmp_path):
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    paths = ClientPaths.from_environment(install_dir=tmp_path / "install", data_dir=tmp_path / "data")
    service = UpdateService(
        paths=paths,
        current_version="0.9.0",
        public_key=public,
        sources=[_signed_source(key, "0.9.2", channel="beta")],
        expected_channel="stable",
    )

    result = service.check()

    assert result.state == "idle"
    assert service.manifest is None
    assert "通道" in result.error
