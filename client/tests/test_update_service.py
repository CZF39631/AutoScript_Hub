from dataclasses import dataclass
import hashlib
import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from client.runtime.paths import ClientPaths
from client.update.service import UpdateService
from client.update.state import UpdateStateStore


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
    assert attempts == []
    result = service.stage()

    assert result.state == "verified"
    assert attempts == [
        "https://gitee.example/installer",
        "https://gitee.example/installer",
        "https://gitee.example/installer",
        "https://github.example/installer",
    ]
    assert result.installer.is_file()


def _chunked_service(tmp_path, downloader):
    chunks = (b"part-one", b"part-two")
    installer = b"".join(chunks)
    key = Ed25519PrivateKey.generate()
    asset = {
        "filename": "AutoScript-Hub-Setup-0.9.1.exe",
        "size": len(installer),
        "sha256": hashlib.sha256(installer).hexdigest(),
        "urls": ["https://github.example/full.exe"],
        "parts": [
            {
                "filename": f"installer.exe.part{index:04d}",
                "size": len(chunk),
                "sha256": hashlib.sha256(chunk).hexdigest(),
                "urls": [f"https://gitee.example/part{index}"],
            }
            for index, chunk in enumerate(chunks, 1)
        ],
    }
    payload = {
        "schema_version": 1,
        "product": "autoscript-hub-client",
        "version": "0.9.1",
        "channel": "beta",
        "published_at": "2026-07-21T00:00:00Z",
        "minimum_client_version": "0.9.0",
        "release_notes_url": "https://example.com/release",
        "assets": {"windows-x86_64": asset},
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    paths = ClientPaths.from_environment(install_dir=tmp_path / "install", data_dir=tmp_path / "data")
    return UpdateService(
        paths=paths,
        current_version="0.9.0",
        public_key=public,
        sources=[_Source(raw, key.sign(raw))],
        http_download=downloader,
    ), chunks, installer


def test_chunked_download_is_preferred_and_combined(tmp_path):
    calls = []
    payloads = {
        "https://gitee.example/part1": b"part-one",
        "https://gitee.example/part2": b"part-two",
    }

    def download(url, destination, size, digest):
        calls.append(url)
        destination.write_bytes(payloads[url])

    service, _, installer = _chunked_service(tmp_path, download)
    service.check()
    result = service.download()

    assert result.state == "verified"
    assert result.installer.read_bytes() == installer
    assert calls == ["https://gitee.example/part1", "https://gitee.example/part2"]


def test_failed_download_returns_available_preserves_manifest_and_reuses_safe_parts(tmp_path):
    calls = []

    def failing(url, destination, size, digest):
        calls.append(url)
        if url.endswith("part1"):
            destination.write_bytes(b"part-one")
            return
        raise OSError("offline")

    service, _, installer = _chunked_service(tmp_path, failing)
    service.check()
    failed = service.download()

    assert failed.state == "available"
    persisted = service.store.read()
    assert persisted["state"] == "available"
    assert persisted["manifest_payload_b64"]
    assert persisted["manifest_signature_b64"]

    resumed_calls = []
    payloads = {
        "https://gitee.example/part2": b"part-two",
        "https://github.example/full.exe": installer,
    }

    def resumed(url, destination, size, digest):
        resumed_calls.append(url)
        destination.write_bytes(payloads[url])

    service.http_download = resumed
    result = service.download()
    assert result.state == "verified"
    assert resumed_calls == ["https://gitee.example/part2"]


def test_invalid_part_falls_back_to_streamed_full_installer(tmp_path):
    calls = []

    def download(url, destination, size, digest):
        calls.append(url)
        if "gitee" in url:
            destination.write_bytes(b"corrupt")
        else:
            destination.write_bytes(b"part-onepart-two")

    service, _, _ = _chunked_service(tmp_path, download)
    service.check()

    assert service.download().state == "verified"
    assert calls == ["https://gitee.example/part1", "https://github.example/full.exe"]


def test_running_script_defers_install(tmp_path):
    service, _ = _service(tmp_path, idle=False)
    service.check()
    service.stage()

    result = service.request_install()

    assert result.state == "waiting-for-idle"
    service.runtime_is_idle = lambda: True
    assert service.request_install().state == "installing"


def test_discovered_update_manifest_is_reused_after_agent_restart(tmp_path):
    service, _ = _service(tmp_path, idle=True)
    assert service.check().state == "available"

    resumed = UpdateService(
        paths=service.paths,
        current_version="0.9.0",
        public_key=service.public_key,
        sources=[],
        http_get=lambda url: b"signed-installer",
    )

    assert resumed.manifest is not None
    assert resumed.manifest.version == "0.9.1"
    assert resumed.download().state == "verified"


def test_source_failure_preserves_previously_discovered_update(tmp_path):
    service, _ = _service(tmp_path, idle=True)
    assert service.check().state == "available"
    service.sources = [type("OfflineSource", (), {"fetch": lambda self: (_ for _ in ()).throw(OSError("offline"))})()]

    result = service.check()

    assert result.state == "available"
    assert result.version == "0.9.1"
    assert service.store.read()["last_check_error"] == "offline"


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


def test_successful_fallback_does_not_report_an_earlier_source_error(tmp_path):
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    paths = ClientPaths.from_environment(install_dir=tmp_path / "install", data_dir=tmp_path / "data")
    offline = type("OfflineSource", (), {"fetch": lambda self: (_ for _ in ()).throw(OSError("SSL EOF"))})()
    service = UpdateService(
        paths=paths,
        current_version="0.9.1",
        public_key=public,
        sources=[offline, _signed_source(key, "0.9.1")],
        expected_channel="beta",
    )

    result = service.check()

    assert result.state == "idle"
    assert result.version == "0.9.1"
    assert result.error == ""
    assert service.store.read()["error"] == ""
    assert service.store.read()["version"] == "0.9.1"


def test_review_build_can_discover_a_published_beta_update(tmp_path):
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    paths = ClientPaths.from_environment(install_dir=tmp_path / "install", data_dir=tmp_path / "data")
    service = UpdateService(
        paths=paths,
        current_version="1.2.2-review.1",
        public_key=public,
        sources=[_signed_source(key, "1.2.3-beta.1")],
        expected_channel="beta",
    )

    result = service.check()

    assert result.state == "available"
    assert result.version == "1.2.3-beta.1"
    assert service.store.read()["version"] == "1.2.3-beta.1"


def test_beta_channel_accepts_stable_manifest(tmp_path):
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    paths = ClientPaths.from_environment(install_dir=tmp_path / "install", data_dir=tmp_path / "data")
    service = UpdateService(
        paths=paths,
        current_version="1.0.0",
        public_key=public,
        sources=[_signed_source(key, "1.1.0", channel="stable")],
        expected_channel="beta",
    )

    result = service.check()

    assert result.state == "available"
    assert result.version == "1.1.0"


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


# ---------------------------------------------------------------------------
# Stale installing-state recovery (regression: legacy installing 0.9.1 stuck
# while running 0.9.3-dev.3; detached updater PID ownership).
# ---------------------------------------------------------------------------


def _seed_installing(paths, version, **extra):
    """Drive the state store through legal transitions to *installing*."""
    store = UpdateStateStore(paths.updates_dir)
    store.transition("checking")
    store.transition("available")
    store.transition("downloading")
    store.transition("verified")
    store.transition("installing", version=version, **extra)
    return store


def test_legacy_installing_targeting_older_version_recovers_and_checks(tmp_path):
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    paths = ClientPaths.from_environment(install_dir=tmp_path / "install", data_dir=tmp_path / "data")
    paths.ensure()
    _seed_installing(paths, version="0.9.1")

    service = UpdateService(
        paths=paths,
        current_version="0.9.3-dev.3",
        public_key=public,
        sources=[_signed_source(key, "0.9.5")],
        is_pid_alive=lambda pid: False,
    )

    result = service.check()

    assert result.state == "available"
    assert result.version == "0.9.5"
    # Recovery path went through rolled-back -> idle -> checking -> available
    assert service.store.read()["state"] == "available"


def test_installing_with_dead_updater_pid_recovers(tmp_path):
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    paths = ClientPaths.from_environment(install_dir=tmp_path / "install", data_dir=tmp_path / "data")
    paths.ensure()
    _seed_installing(paths, version="0.9.5", updater_pid=88888)

    service = UpdateService(
        paths=paths,
        current_version="0.9.3-dev.3",
        public_key=public,
        sources=[_signed_source(key, "0.9.6")],
        is_pid_alive=lambda pid: False,  # PID is dead
    )

    result = service.check()

    assert result.state == "available"
    assert result.version == "0.9.6"


def test_installing_with_live_updater_pid_is_not_recovered(tmp_path):
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    paths = ClientPaths.from_environment(install_dir=tmp_path / "install", data_dir=tmp_path / "data")
    paths.ensure()
    _seed_installing(paths, version="0.9.5", updater_pid=99999)

    service = UpdateService(
        paths=paths,
        current_version="0.9.3-dev.3",
        public_key=public,
        sources=[_signed_source(key, "0.9.6")],
        is_pid_alive=lambda pid: pid == 99999,  # PID is alive
    )

    result = service.check()

    assert result.state == "installing"
    assert result.version == "0.9.5"
    assert service.store.read()["state"] == "installing"


def test_legacy_installing_with_newer_version_is_conservative(tmp_path):
    """No updater_pid but target version >= current: do NOT recover (could be live)."""
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    paths = ClientPaths.from_environment(install_dir=tmp_path / "install", data_dir=tmp_path / "data")
    paths.ensure()
    _seed_installing(paths, version="0.9.5")

    service = UpdateService(
        paths=paths,
        current_version="0.9.3-dev.3",
        public_key=public,
        sources=[_signed_source(key, "0.9.6")],
        is_pid_alive=lambda pid: False,
    )

    result = service.check()

    assert result.state == "installing"
    assert result.version == "0.9.5"
    assert service.store.read()["state"] == "installing"


def test_handoff_exception_transitions_to_rolled_back_not_installing(tmp_path):
    service, _ = _service(tmp_path, idle=True)
    service.check()
    service.stage()

    def boom(installer, version):
        raise FileNotFoundError("updater binary missing")

    service.handoff = boom

    try:
        service.request_install()
        assert False, "handoff should have raised"
    except FileNotFoundError:
        pass

    persisted = service.store.read()
    assert persisted["state"] == "rolled-back"
    # Next check() can proceed normally via rolled-back -> idle -> checking
    result = service.check()
    assert result.state in {"idle", "available"}


def test_installing_with_invalid_updater_pid_recovers(tmp_path):
    """A corrupt updater_pid (non-integer) should be treated as dead."""
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    paths = ClientPaths.from_environment(install_dir=tmp_path / "install", data_dir=tmp_path / "data")
    paths.ensure()
    _seed_installing(paths, version="0.9.5", updater_pid="not-a-number")

    service = UpdateService(
        paths=paths,
        current_version="0.9.3-dev.3",
        public_key=public,
        sources=[_signed_source(key, "0.9.6")],
        is_pid_alive=lambda pid: True,  # even if is_pid_alive says True, invalid PID recovers
    )

    result = service.check()

    assert result.state == "available"
    assert result.version == "0.9.6"
