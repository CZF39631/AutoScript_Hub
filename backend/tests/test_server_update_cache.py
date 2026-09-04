import base64
import hashlib
import json
from datetime import datetime, timezone

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from app import server_update_cache as updater
from app.release_cache import MANIFEST_NAME, MANIFEST_SIG_NAME, ReleaseCache, ReleaseCacheError
from app.models import ServerSettings


def _generate_keypair(tmp_path):
    key = Ed25519PrivateKey.generate()
    public_raw = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return key, None, public_raw


def _make_manifest(version, installer_bytes, url):
    return {
        "schema_version": 1,
        "product": "autoscript-hub-client",
        "version": version,
        "channel": "stable" if version.startswith("1.") else "beta",
        "published_at": datetime.now(timezone.utc).isoformat(),
        "minimum_client_version": "0.9.0",
        "release_notes_url": "https://github.com/owner/repo/releases",
        "assets": {"windows-x86_64": {
            "filename": f"AutoScript-Hub-Setup-{version}.exe",
            "size": len(installer_bytes),
            "sha256": hashlib.sha256(installer_bytes).hexdigest(),
            "urls": [url],
        }},
    }


def _sign_manifest(manifest, key):
    raw = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    return raw, base64.b64encode(key.sign(raw))


def _github_url(repository, tag, filename):
    return f"https://github.com/{repository}/releases/download/{tag}/{filename}"


def test_release_selection_uses_latest_formal_for_stable_and_latest_any_for_beta():
    releases = [
        {"tag_name": "v2.0.0-beta.1", "draft": False, "prerelease": True},
        {"tag_name": "v1.9.0", "draft": False, "prerelease": False},
        {"tag_name": "v3.0.0", "draft": True, "prerelease": False},
    ]
    selected = updater._select_releases(releases)
    assert selected["beta"]["tag_name"] == "v2.0.0-beta.1"
    assert selected["stable"]["tag_name"] == "v1.9.0"


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/owner/repo/releases/download/v1/file.exe",
        "https://evil.example/owner/repo/releases/download/v1/file.exe",
        "https://github.com/other/repo/releases/download/v1/file.exe",
        "https://github.com/owner/repo/releases/download/v1/file.exe?token=x",
        "https://user:password@github.com/owner/repo/releases/download/v1/file.exe",
        "https://github.com/owner/repo/releases/download/v1/other.exe",
    ],
)
def test_complete_exe_url_is_restricted_to_configured_github_repository(url):
    assert not updater._github_release_url(url, "owner/repo", "file.exe")
    assert updater._github_release_url(
        "https://github.com/owner/repo/releases/download/v1/file.exe",
        "owner/repo",
        "file.exe",
    )


def test_cache_release_downloads_raw_signed_files_and_ignores_parts(tmp_path, monkeypatch):
    repository = "owner/repo"
    key, _, public_raw = _generate_keypair(tmp_path)
    installer = b"complete-installer"
    installer_name = "AutoScript-Hub-Setup-1.2.3.exe"
    installer_url = _github_url(repository, "v1.2.3", installer_name)
    manifest = _make_manifest("1.2.3", installer, installer_url)
    # Valid part metadata is deliberately unusable; the complete URL must be used.
    manifest["assets"]["windows-x86_64"]["parts"] = [
        {
            "filename": "ignored.part",
            "size": len(installer),
            "sha256": hashlib.sha256(b"not-downloaded").hexdigest(),
            "urls": [_github_url(repository, "v1.2.3", "ignored.part")],
        }
    ]
    raw_manifest, signature = _sign_manifest(manifest, key)
    manifest_url = _github_url(repository, "v1.2.3", MANIFEST_NAME)
    signature_url = _github_url(repository, "v1.2.3", MANIFEST_SIG_NAME)
    responses = {
        manifest_url: raw_manifest,
        signature_url: signature,
        installer_url: installer,
    }
    requested = []

    def handler(request):
        requested.append(str(request.url))
        return httpx.Response(200, content=responses[str(request.url)])

    monkeypatch.setattr(updater, "UPDATE_PUBLIC_KEY_BYTES", public_raw)
    cache = ReleaseCache(tmp_path / "cache", public_raw)
    release = {
        "assets": [
            {"name": MANIFEST_NAME, "browser_download_url": manifest_url},
            {"name": MANIFEST_SIG_NAME, "browser_download_url": signature_url},
        ]
    }
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert updater._cache_release(client, cache, repository, "stable", release) == "1.2.3"

    assert requested == [manifest_url, signature_url, installer_url]
    assert cache.get_channel_file("stable", MANIFEST_NAME).read_bytes() == raw_manifest
    assert cache.find_file(installer_name).read_bytes() == installer


def test_download_retries_and_enforces_size_limit(monkeypatch):
    monkeypatch.setattr(updater.time, "sleep", lambda seconds: None)
    attempts = []

    def handler(request):
        attempts.append(str(request.url))
        if len(attempts) < 3:
            return httpx.Response(503)
        return httpx.Response(200, content=b"ok")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert updater._request_bytes(client, "https://example.test/file", 2) == b"ok"
        with pytest.raises(ReleaseCacheError, match="下载失败"):
            updater._request_bytes(client, "https://example.test/file", 1)
    assert len(attempts) == 6


def test_invalid_download_keeps_previous_cache(tmp_path, monkeypatch):
    key, _, public_raw = _generate_keypair(tmp_path)
    cache = ReleaseCache(tmp_path / "cache", public_raw)
    repository = "owner/repo"
    installer = b"old-installer"
    installer_name = "AutoScript-Hub-Setup-1.0.0.exe"
    manifest = _make_manifest(
        "1.0.0", installer, _github_url(repository, "v1.0.0", installer_name)
    )
    raw, sig = _sign_manifest(manifest, key)
    source = tmp_path / "source"
    source.mkdir()
    (source / MANIFEST_NAME).write_bytes(raw)
    (source / MANIFEST_SIG_NAME).write_bytes(sig)
    (source / installer_name).write_bytes(installer)
    cache.publish_files(
        source / MANIFEST_NAME, source / MANIFEST_SIG_NAME, source / installer_name, "stable"
    )

    monkeypatch.setattr(updater, "UPDATE_PUBLIC_KEY_BYTES", public_raw)
    release = {
        "assets": [
            {
                "name": MANIFEST_NAME,
                "browser_download_url": _github_url(repository, "v2", MANIFEST_NAME),
            },
            {
                "name": MANIFEST_SIG_NAME,
                "browser_download_url": _github_url(repository, "v2", MANIFEST_SIG_NAME),
            },
        ]
    }
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(500))) as client:
        with pytest.raises(ReleaseCacheError):
            updater._cache_release(client, cache, repository, "stable", release)
    assert cache.latest_version("stable") == "1.0.0"
    assert cache.find_file(installer_name).read_bytes() == installer


def test_cycle_reads_current_proxy_each_time(fresh_db, monkeypatch):
    TestSession, _ = fresh_db
    db = TestSession()
    db.add(ServerSettings(
        id=1,
        enabled=True,
        outbound_proxy="http://user:password@proxy.example:8080",
        github_repository="owner/repo",
        interval_hours=9,
    ))
    db.commit()
    db.close()
    monkeypatch.setattr(updater, "SessionLocal", TestSession)
    monkeypatch.setattr(updater, "_request_bytes", lambda client, url, limit: b"[]")
    captured = {}

    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return None

    monkeypatch.setattr(updater.httpx, "Client", FakeClient)
    assert updater.run_server_update_cycle() == 9
    assert captured[updater._HTTPX_PROXY_PARAMETER] == "http://user:password@proxy.example:8080"


def test_start_worker_is_idempotent(monkeypatch):
    starts = []

    class FakeThread:
        def __init__(self, **kwargs):
            starts.append(kwargs)
            self.alive = False
        def start(self):
            self.alive = True
        def is_alive(self):
            return self.alive

    monkeypatch.setattr(updater.threading, "Thread", FakeThread)
    monkeypatch.setattr(updater, "_worker_thread", None)
    updater.start_server_update_cache()
    updater.start_server_update_cache()
    assert len(starts) == 1
