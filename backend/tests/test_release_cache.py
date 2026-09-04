"""Tests for the LAN release-cache feature.

Covers: manifest signature validation, asset hash/size verification, token
authentication (constant-time), path traversal prevention, incomplete bundle
visibility, retention pruning, and anonymous router read behaviour.
"""

import base64
import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from app.routers import release_cache as rc_router


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _generate_keypair(tmp_path):
    key = Ed25519PrivateKey.generate()
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_raw = key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    private_path = tmp_path / "key.pem"
    private_path.write_bytes(private_pem)
    return key, private_path, public_raw


def _make_manifest(version, installer_bytes, url):
    digest = hashlib.sha256(installer_bytes).hexdigest()
    channel = "stable" if version.startswith("1.") else "beta"
    return {
        "schema_version": 1,
        "product": "autoscript-hub-client",
        "version": version,
        "channel": channel,
        "published_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "minimum_client_version": "0.9.0",
        "release_notes_url": "https://github.com/example/repo/releases",
        "assets": {
            "windows-x86_64": {
                "filename": f"AutoScript-Hub-Setup-{version}.exe",
                "size": len(installer_bytes),
                "sha256": digest,
                "urls": [url],
            }
        },
    }


def _sign_manifest(manifest_dict, key):
    raw = (json.dumps(manifest_dict, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    signature = base64.b64encode(key.sign(raw))
    return raw, signature


def _make_bundle(bundle_path, version, installer_bytes, url, key,
                 manifest_name="autoscript-hub-update.json",
                 sig_name="autoscript-hub-update.json.sig",
                 installer_name=None,
                 skip_manifest=False, skip_sig=False, skip_installer=False,
                 tamper_hash=False, tamper_size=False, extra_files=None):
    """Create a release bundle ZIP for testing.  Returns (raw_manifest, signature)."""
    manifest_dict = _make_manifest(version, installer_bytes, url)
    if installer_name:
        manifest_dict["assets"]["windows-x86_64"]["filename"] = installer_name
    if tamper_hash:
        manifest_dict["assets"]["windows-x86_64"]["sha256"] = "0" * 64
    if tamper_size:
        manifest_dict["assets"]["windows-x86_64"]["size"] = len(installer_bytes) + 999

    raw, signature = _sign_manifest(manifest_dict, key)
    actual_installer_name = installer_name or manifest_dict["assets"]["windows-x86_64"]["filename"]

    with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as archive:
        if not skip_manifest:
            archive.writestr(manifest_name, raw)
        if not skip_sig:
            archive.writestr(sig_name, signature)
        if not skip_installer:
            archive.writestr(actual_installer_name, installer_bytes)
        if extra_files:
            for name, content in extra_files.items():
                archive.writestr(name, content)
    return raw, signature


@pytest.fixture
def release_env(tmp_path, monkeypatch):
    """Set up isolated release-cache config for each test."""
    cache_dir = tmp_path / "release-cache"
    cache_dir.mkdir()
    key, private_path, public_raw = _generate_keypair(tmp_path)

    monkeypatch.setattr(rc_router, "RELEASE_CACHE_DIR", str(cache_dir))
    monkeypatch.setattr(rc_router, "RELEASE_CACHE_SYNC_TOKEN", "test-sync-secret")
    monkeypatch.setattr(rc_router, "RELEASE_CACHE_RETENTION", 3)
    monkeypatch.setattr(rc_router, "UPDATE_PUBLIC_KEY_BYTES", public_raw)
    return {
        "cache_dir": cache_dir,
        "key": key,
        "private_path": private_path,
        "public_raw": public_raw,
        "token": "test-sync-secret",
        "url": "http://127.0.0.1:8000/api/release/installer/AutoScript-Hub-Setup-0.9.1.exe",
    }


def _auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Unit tests: ReleaseCache core
# ---------------------------------------------------------------------------

class TestReleaseCacheCore:
    def test_valid_bundle_publishes_and_serves(self, release_env, tmp_path):
        from app.release_cache import ReleaseCache

        installer = b"fake-installer-content-0.9.1"
        bundle = tmp_path / "bundle.zip"
        _make_bundle(bundle, "0.9.1", installer, release_env["url"], release_env["key"])

        cache = ReleaseCache(release_env["cache_dir"], release_env["public_raw"], retention=3)
        version = cache.publish_bundle(bundle)

        assert version == "0.9.1"
        assert cache.latest_version() == "0.9.1"
        # All files should be present.
        manifest = cache.get_file(None, "autoscript-hub-update.json")
        assert manifest is not None and manifest.is_file()
        sig = cache.get_file(None, "autoscript-hub-update.json.sig")
        assert sig is not None and sig.is_file()
        installer_file = cache.get_file(None, "AutoScript-Hub-Setup-0.9.1.exe")
        assert installer_file is not None and installer_file.read_bytes() == installer

    def test_invalid_signature_is_rejected(self, release_env, tmp_path):
        from app.release_cache import ReleaseCache, ReleaseCacheError

        # Sign with a different key.
        other_key = Ed25519PrivateKey.generate()
        installer = b"installer"
        bundle = tmp_path / "bundle.zip"
        _make_bundle(bundle, "0.9.1", installer, release_env["url"], other_key)

        cache = ReleaseCache(release_env["cache_dir"], release_env["public_raw"], retention=3)
        with pytest.raises(ReleaseCacheError) as exc:
            cache.publish_bundle(bundle)
        assert "签名" in str(exc.value) or "signature" in str(exc.value).lower()
        # Nothing should be visible after failure.
        assert cache.latest_version() is None

    def test_tampered_hash_is_rejected(self, release_env, tmp_path):
        from app.release_cache import ReleaseCache, ReleaseCacheError

        installer = b"installer-bytes"
        bundle = tmp_path / "bundle.zip"
        _make_bundle(bundle, "0.9.1", installer, release_env["url"], release_env["key"], tamper_hash=True)

        cache = ReleaseCache(release_env["cache_dir"], release_env["public_raw"], retention=3)
        with pytest.raises(ReleaseCacheError) as exc:
            cache.publish_bundle(bundle)
        assert "SHA-256" in str(exc.value)
        assert cache.latest_version() is None

    def test_tampered_size_is_rejected(self, release_env, tmp_path):
        from app.release_cache import ReleaseCache, ReleaseCacheError

        installer = b"installer-bytes"
        bundle = tmp_path / "bundle.zip"
        _make_bundle(bundle, "0.9.1", installer, release_env["url"], release_env["key"], tamper_size=True)

        cache = ReleaseCache(release_env["cache_dir"], release_env["public_raw"], retention=3)
        with pytest.raises(ReleaseCacheError) as exc:
            cache.publish_bundle(bundle)
        assert "大小" in str(exc.value)
        assert cache.latest_version() is None

    def test_missing_manifest_rejected(self, release_env, tmp_path):
        from app.release_cache import ReleaseCache, ReleaseCacheError

        bundle = tmp_path / "bundle.zip"
        _make_bundle(bundle, "0.9.1", b"x", release_env["url"], release_env["key"], skip_manifest=True)

        cache = ReleaseCache(release_env["cache_dir"], release_env["public_raw"], retention=3)
        with pytest.raises(ReleaseCacheError):
            cache.publish_bundle(bundle)

    def test_missing_signature_rejected(self, release_env, tmp_path):
        from app.release_cache import ReleaseCache, ReleaseCacheError

        bundle = tmp_path / "bundle.zip"
        _make_bundle(bundle, "0.9.1", b"x", release_env["url"], release_env["key"], skip_sig=True)

        cache = ReleaseCache(release_env["cache_dir"], release_env["public_raw"], retention=3)
        with pytest.raises(ReleaseCacheError):
            cache.publish_bundle(bundle)

    def test_missing_installer_rejected(self, release_env, tmp_path):
        from app.release_cache import ReleaseCache, ReleaseCacheError

        bundle = tmp_path / "bundle.zip"
        _make_bundle(bundle, "0.9.1", b"x", release_env["url"], release_env["key"], skip_installer=True)

        cache = ReleaseCache(release_env["cache_dir"], release_env["public_raw"], retention=3)
        with pytest.raises(ReleaseCacheError):
            cache.publish_bundle(bundle)

    def test_corrupt_zip_rejected(self, release_env, tmp_path):
        from app.release_cache import ReleaseCache, ReleaseCacheError

        bundle = tmp_path / "not-a-zip.zip"
        bundle.write_bytes(b"this is not a zip file")

        cache = ReleaseCache(release_env["cache_dir"], release_env["public_raw"], retention=3)
        with pytest.raises(ReleaseCacheError):
            cache.publish_bundle(bundle)

    def test_zip_path_traversal_rejected(self, release_env, tmp_path):
        from app.release_cache import ReleaseCache, ReleaseCacheError

        installer = b"installer"
        bundle = tmp_path / "bundle.zip"
        _make_bundle(bundle, "0.9.1", installer, release_env["url"], release_env["key"],
                     extra_files={"../evil.txt": b"traversal"})

        cache = ReleaseCache(release_env["cache_dir"], release_env["public_raw"], retention=3)
        with pytest.raises(ReleaseCacheError):
            cache.publish_bundle(bundle)

    def test_no_public_key_raises_disabled(self, release_env, tmp_path):
        from app.release_cache import ReleaseCache, ReleaseCacheDisabled

        installer = b"installer"
        bundle = tmp_path / "bundle.zip"
        _make_bundle(bundle, "0.9.1", installer, release_env["url"], release_env["key"])

        cache = ReleaseCache(release_env["cache_dir"], None, retention=3)
        with pytest.raises(ReleaseCacheDisabled):
            cache.publish_bundle(bundle)


# ---------------------------------------------------------------------------
# Retention tests
# ---------------------------------------------------------------------------

class TestRetention:
    def test_retention_prunes_oldest_versions(self, release_env, tmp_path):
        from app.release_cache import ReleaseCache

        cache = ReleaseCache(release_env["cache_dir"], release_env["public_raw"], retention=3)
        for i in range(5):
            version = f"0.9.{i}"
            installer = f"installer-{version}".encode()
            url = f"http://127.0.0.1:8000/api/release/installer/AutoScript-Hub-Setup-{version}.exe"
            bundle = tmp_path / f"bundle-{version}.zip"
            _make_bundle(bundle, version, installer, url, release_env["key"])
            cache.publish_bundle(bundle)

        versions = cache.list_versions()
        assert len(versions) == 3
        # Latest 3 versions should be 0.9.4, 0.9.3, 0.9.2.
        version_numbers = [v["version"] for v in versions]
        assert "0.9.4" in version_numbers
        assert "0.9.3" in version_numbers
        assert "0.9.2" in version_numbers
        assert "0.9.1" not in version_numbers
        assert "0.9.0" not in version_numbers
        # Pruned directories should not exist.
        assert not (release_env["cache_dir"] / "0.9.0").exists()
        assert not (release_env["cache_dir"] / "0.9.1").exists()

    def test_republish_same_version_replaces_atomically(self, release_env, tmp_path):
        from app.release_cache import ReleaseCache

        cache = ReleaseCache(release_env["cache_dir"], release_env["public_raw"], retention=3)

        installer1 = b"installer-v1"
        bundle1 = tmp_path / "b1.zip"
        _make_bundle(bundle1, "0.9.1", installer1, release_env["url"], release_env["key"])
        cache.publish_bundle(bundle1)

        installer2 = b"installer-v2-different-content"
        url2 = release_env["url"]
        bundle2 = tmp_path / "b2.zip"
        _make_bundle(bundle2, "0.9.1", installer2, url2, release_env["key"])
        cache.publish_bundle(bundle2)

        # Should have exactly one 0.9.1 directory.
        assert len(cache.list_versions()) == 1
        actual_installer = cache.get_file(None, "AutoScript-Hub-Setup-0.9.1.exe")
        assert actual_installer.read_bytes() == installer2

    def test_republishing_older_version_keeps_newest_version_latest(self, release_env, tmp_path):
        from app.release_cache import ReleaseCache

        cache = ReleaseCache(release_env["cache_dir"], release_env["public_raw"], retention=3)
        for version in ("0.9.1", "0.9.3"):
            installer = f"installer-{version}".encode()
            bundle = tmp_path / f"bundle-{version}.zip"
            _make_bundle(bundle, version, installer, release_env["url"], release_env["key"])
            cache.publish_bundle(bundle)

        replacement = tmp_path / "replacement-0.9.1.zip"
        _make_bundle(replacement, "0.9.1", b"replacement", release_env["url"], release_env["key"])
        cache.publish_bundle(replacement)

        assert cache.latest_version() == "0.9.3"


# ---------------------------------------------------------------------------
# Traversal tests on get_file
# ---------------------------------------------------------------------------

class TestTraversalPrevention:
    def test_get_file_rejects_traversal_filename(self, release_env, tmp_path):
        from app.release_cache import ReleaseCache

        cache = ReleaseCache(release_env["cache_dir"], release_env["public_raw"])
        assert cache.get_file("0.9.1", "../../../etc/passwd") is None

    def test_get_file_rejects_absolute_path(self, release_env, tmp_path):
        from app.release_cache import ReleaseCache

        cache = ReleaseCache(release_env["cache_dir"], release_env["public_raw"])
        assert cache.get_file("0.9.1", "/etc/passwd") is None

    def test_get_file_rejects_backslash_in_filename(self, release_env, tmp_path):
        from app.release_cache import ReleaseCache

        cache = ReleaseCache(release_env["cache_dir"], release_env["public_raw"])
        assert cache.get_file("0.9.1", "..\\..\\evil") is None

    def test_get_file_rejects_traversal_version(self, release_env, tmp_path):
        from app.release_cache import ReleaseCache

        cache = ReleaseCache(release_env["cache_dir"], release_env["public_raw"])
        assert cache.get_file("../../../etc", "passwd") is None

    def test_get_file_rejects_invalid_version(self, release_env, tmp_path):
        from app.release_cache import ReleaseCache

        cache = ReleaseCache(release_env["cache_dir"], release_env["public_raw"])
        assert cache.get_file("not-a-version", "autoscript-hub-update.json") is None


# ---------------------------------------------------------------------------
# Router integration tests
# ---------------------------------------------------------------------------

class TestRouterAnonymousReads:
    def test_manifest_returns_404_when_empty(self, release_env, client):
        resp = client.get("/api/release/manifest")
        assert resp.status_code == 404

    def test_manifest_sig_returns_404_when_empty(self, release_env, client):
        resp = client.get("/api/release/manifest.sig")
        assert resp.status_code == 404

    def test_versions_returns_empty_when_no_cache(self, release_env, client):
        resp = client.get("/api/release/versions")
        assert resp.status_code == 200
        assert resp.json() == {"versions": [], "latest": None}

    def test_anonymous_read_after_publish(self, release_env, client, tmp_path):
        installer = b"real-installer-content"
        bundle = tmp_path / "bundle.zip"
        _make_bundle(bundle, "0.9.1", installer, release_env["url"], release_env["key"])

        resp = client.post(
            "/api/release/sync",
            content=bundle.read_bytes(),
            headers={**_auth_headers(release_env["token"]), "Content-Type": "application/zip"},
        )
        assert resp.status_code == 201

        # Anonymous manifest read.
        manifest_resp = client.get("/api/release/manifest")
        assert manifest_resp.status_code == 200
        assert manifest_resp.headers["content-type"] == "application/json"
        manifest_data = manifest_resp.json()
        assert manifest_data["version"] == "0.9.1"

        # Anonymous signature read.
        sig_resp = client.get("/api/release/manifest.sig")
        assert sig_resp.status_code == 200

        # Anonymous installer read.
        installer_resp = client.get("/api/release/installer/AutoScript-Hub-Setup-0.9.1.exe")
        assert installer_resp.status_code == 200
        assert installer_resp.content == installer

        # Versions listing.
        versions_resp = client.get("/api/release/versions")
        assert versions_resp.status_code == 200
        data = versions_resp.json()
        assert data["latest"] == "0.9.1"
        assert len(data["versions"]) == 1


class TestRouterSyncAuth:
    def test_sync_requires_token(self, release_env, client, tmp_path):
        bundle = tmp_path / "bundle.zip"
        _make_bundle(bundle, "0.9.1", b"x", release_env["url"], release_env["key"])
        resp = client.post("/api/release/sync", content=bundle.read_bytes())
        assert resp.status_code == 401

    def test_sync_rejects_wrong_token(self, release_env, client, tmp_path):
        bundle = tmp_path / "bundle.zip"
        _make_bundle(bundle, "0.9.1", b"x", release_env["url"], release_env["key"])
        resp = client.post(
            "/api/release/sync",
            content=bundle.read_bytes(),
            headers=_auth_headers("wrong-token"),
        )
        assert resp.status_code == 401

    def test_sync_rejects_malformed_auth_header(self, release_env, client, tmp_path):
        bundle = tmp_path / "bundle.zip"
        _make_bundle(bundle, "0.9.1", b"x", release_env["url"], release_env["key"])
        resp = client.post(
            "/api/release/sync",
            content=bundle.read_bytes(),
            headers={"Authorization": "Basic xyz"},
        )
        assert resp.status_code == 401

    def test_sync_returns_503_when_token_unset(self, release_env, client, tmp_path, monkeypatch):
        monkeypatch.setattr(rc_router, "RELEASE_CACHE_SYNC_TOKEN", "")
        bundle = tmp_path / "bundle.zip"
        _make_bundle(bundle, "0.9.1", b"x", release_env["url"], release_env["key"])
        resp = client.post(
            "/api/release/sync",
            content=bundle.read_bytes(),
            headers=_auth_headers("any"),
        )
        assert resp.status_code == 503

    def test_sync_rejects_empty_body(self, release_env, client):
        resp = client.post(
            "/api/release/sync",
            content=b"",
            headers=_auth_headers(release_env["token"]),
        )
        assert resp.status_code == 400


class TestRouterSyncValidation:
    def test_sync_publishes_valid_bundle(self, release_env, client, tmp_path):
        installer = b"valid-installer"
        bundle = tmp_path / "bundle.zip"
        _make_bundle(bundle, "0.9.1", installer, release_env["url"], release_env["key"])

        resp = client.post(
            "/api/release/sync",
            content=bundle.read_bytes(),
            headers={**_auth_headers(release_env["token"]), "Content-Type": "application/zip"},
        )
        assert resp.status_code == 201
        assert resp.json()["version"] == "0.9.1"

    def test_sync_rejects_bad_signature(self, release_env, client, tmp_path):
        other_key = Ed25519PrivateKey.generate()
        installer = b"installer"
        bundle = tmp_path / "bundle.zip"
        _make_bundle(bundle, "0.9.1", installer, release_env["url"], other_key)

        resp = client.post(
            "/api/release/sync",
            content=bundle.read_bytes(),
            headers=_auth_headers(release_env["token"]),
        )
        assert resp.status_code == 400
        # Nothing should be visible.
        assert client.get("/api/release/manifest").status_code == 404

    def test_sync_rejects_hash_mismatch(self, release_env, client, tmp_path):
        installer = b"installer"
        bundle = tmp_path / "bundle.zip"
        _make_bundle(bundle, "0.9.1", installer, release_env["url"], release_env["key"], tamper_hash=True)

        resp = client.post(
            "/api/release/sync",
            content=bundle.read_bytes(),
            headers=_auth_headers(release_env["token"]),
        )
        assert resp.status_code == 400
        assert client.get("/api/release/manifest").status_code == 404

    def test_sync_rejects_incomplete_bundle_no_installer(self, release_env, client, tmp_path):
        bundle = tmp_path / "bundle.zip"
        _make_bundle(bundle, "0.9.1", b"x", release_env["url"], release_env["key"], skip_installer=True)

        resp = client.post(
            "/api/release/sync",
            content=bundle.read_bytes(),
            headers=_auth_headers(release_env["token"]),
        )
        assert resp.status_code == 400
        assert client.get("/api/release/manifest").status_code == 404

    def test_incomplete_bundle_never_visible(self, release_env, client, tmp_path):
        """After a failed upload, no files should be readable."""
        bundle = tmp_path / "bad.zip"
        bundle.write_bytes(b"not-a-zip")

        resp = client.post(
            "/api/release/sync",
            content=bundle.read_bytes(),
            headers=_auth_headers(release_env["token"]),
        )
        assert resp.status_code == 400
        assert client.get("/api/release/manifest").status_code == 404
        assert client.get("/api/release/manifest.sig").status_code == 404
        assert client.get("/api/release/installer/anything.exe").status_code == 404

    def test_installer_endpoint_rejects_traversal(self, release_env, client):
        resp = client.get("/api/release/installer/..%2F..%2Fetc%2Fpasswd")
        assert resp.status_code == 404

    def test_multiple_publishes_serve_latest(self, release_env, client, tmp_path):
        for version in ("0.9.1", "0.9.2", "0.9.3"):
            installer = f"installer-{version}".encode()
            url = f"http://127.0.0.1:8000/api/release/installer/AutoScript-Hub-Setup-{version}.exe"
            bundle = tmp_path / f"bundle-{version}.zip"
            _make_bundle(bundle, version, installer, url, release_env["key"])
            resp = client.post(
                "/api/release/sync",
                content=bundle.read_bytes(),
                headers=_auth_headers(release_env["token"]),
            )
            assert resp.status_code == 201

        # Latest manifest should be 0.9.3.
        manifest_resp = client.get("/api/release/manifest")
        assert manifest_resp.json()["version"] == "0.9.3"

        versions_resp = client.get("/api/release/versions")
        assert versions_resp.json()["latest"] == "0.9.3"
        assert len(versions_resp.json()["versions"]) == 3


class TestChannelReadsAndRetainedInstaller:
    def test_channel_manifests_and_retained_installers(self, release_env, client, tmp_path):
        publications = [
            ("1.0.0", b"stable-installer"),
            ("0.9.9", b"beta-installer"),
        ]
        for version, content in publications:
            filename = f"AutoScript-Hub-Setup-{version}.exe"
            bundle = tmp_path / f"bundle-{version}.zip"
            _make_bundle(
                bundle,
                version,
                content,
                f"https://github.com/example/repo/releases/download/v{version}/{filename}",
                release_env["key"],
            )
            response = client.post(
                "/api/release/sync",
                content=bundle.read_bytes(),
                headers=_auth_headers(release_env["token"]),
            )
            assert response.status_code == 201

        stable = client.get("/api/release/manifest/stable")
        beta = client.get("/api/release/manifest/beta")
        assert stable.status_code == beta.status_code == 200
        assert stable.json()["version"] == "1.0.0"
        assert beta.json()["version"] == "0.9.9"
        assert client.get("/api/release/manifest/stable.sig").status_code == 200
        assert client.get("/api/release/manifest/beta.sig").status_code == 200
        # 1.0.0 is the legacy latest pointer; 0.9.9 must still be found by name.
        old_installer = client.get("/api/release/installer/AutoScript-Hub-Setup-0.9.9.exe")
        assert old_installer.status_code == 200
        assert old_installer.content == b"beta-installer"

    def test_unknown_channel_is_not_served(self, release_env, client):
        assert client.get("/api/release/manifest/nightly").status_code == 404
        assert client.get("/api/release/manifest/nightly.sig").status_code == 404


class TestRouterConstantTimeAuth:
    """Verify the auth uses constant-time comparison (hmac.compare_digest)."""

    def test_constant_time_comparison_is_used(self):
        import inspect
        from app.routers import release_cache

        source = inspect.getsource(release_cache)
        assert "hmac.compare_digest" in source


# ---------------------------------------------------------------------------
# Regression: secure upload temp-file handling (no tempfile.mktemp)
# ---------------------------------------------------------------------------

class TestSecureUploadTempHandling:
    """The router must never use the insecure tempfile.mktemp."""

    def test_router_does_not_use_mktemp(self):
        import inspect
        from app.routers import release_cache

        source = inspect.getsource(release_cache)
        assert "tempfile.mktemp" not in source
        assert "tempfile.mkstemp" in source

    def test_upload_temp_file_created_inside_cache_dir(self, release_env, client, tmp_path):
        """The uploaded bundle temp file must be inside the cache directory
        (same filesystem) and cleaned up after processing."""
        installer = b"installer-content"
        bundle = tmp_path / "bundle.zip"
        _make_bundle(bundle, "0.9.1", installer, release_env["url"], release_env["key"])

        resp = client.post(
            "/api/release/sync",
            content=bundle.read_bytes(),
            headers=_auth_headers(release_env["token"]),
        )
        assert resp.status_code == 201

        # No leftover upload temp files should remain in the cache dir.
        leftovers = list(release_env["cache_dir"].glob("release-cache-upload-*"))
        assert leftovers == []

    def test_upload_temp_file_cleaned_up_on_validation_failure(self, release_env, client, tmp_path):
        """Even when validation fails, the temp file must be removed."""
        bundle = tmp_path / "bad.zip"
        bundle.write_bytes(b"not-a-zip")

        resp = client.post(
            "/api/release/sync",
            content=bundle.read_bytes(),
            headers=_auth_headers(release_env["token"]),
        )
        assert resp.status_code == 400

        leftovers = list(release_env["cache_dir"].glob("release-cache-upload-*"))
        assert leftovers == []


# ---------------------------------------------------------------------------
# Regression: reject unexpected ZIP members
# ---------------------------------------------------------------------------

class TestRejectExtraZipMembers:
    """A valid bundle must contain exactly manifest, signature, and installer."""

    def test_extra_file_in_bundle_is_rejected(self, release_env, tmp_path):
        from app.release_cache import ReleaseCache, ReleaseCacheError

        installer = b"installer"
        bundle = tmp_path / "bundle.zip"
        _make_bundle(
            bundle, "0.9.1", installer, release_env["url"], release_env["key"],
            extra_files={"readme.txt": b"unauthorized extra file"},
        )

        cache = ReleaseCache(release_env["cache_dir"], release_env["public_raw"], retention=3)
        with pytest.raises(ReleaseCacheError) as exc:
            cache.publish_bundle(bundle)
        assert "多余文件" in str(exc.value) or "readme.txt" in str(exc.value)
        assert cache.latest_version() is None

    def test_multiple_extra_files_are_all_reported(self, release_env, tmp_path):
        from app.release_cache import ReleaseCache, ReleaseCacheError

        installer = b"installer"
        bundle = tmp_path / "bundle.zip"
        _make_bundle(
            bundle, "0.9.1", installer, release_env["url"], release_env["key"],
            extra_files={
                "extra1.txt": b"a",
                "extra2.txt": b"b",
            },
        )

        cache = ReleaseCache(release_env["cache_dir"], release_env["public_raw"], retention=3)
        with pytest.raises(ReleaseCacheError) as exc:
            cache.publish_bundle(bundle)
        msg = str(exc.value)
        assert "extra1.txt" in msg
        assert "extra2.txt" in msg

    def test_directory_entry_in_zip_is_rejected(self, release_env, tmp_path):
        from app.release_cache import ReleaseCache, ReleaseCacheError

        installer = b"installer"
        bundle = tmp_path / "bundle.zip"
        _make_bundle(
            bundle, "0.9.1", installer, release_env["url"], release_env["key"],
            extra_files={"subdir/": b""},
        )

        cache = ReleaseCache(release_env["cache_dir"], release_env["public_raw"], retention=3)
        with pytest.raises(ReleaseCacheError):
            cache.publish_bundle(bundle)

    def test_extra_file_rejected_via_router(self, release_env, client, tmp_path):
        installer = b"installer"
        bundle = tmp_path / "bundle.zip"
        _make_bundle(
            bundle, "0.9.1", installer, release_env["url"], release_env["key"],
            extra_files={"malware.exe": b"evil"},
        )

        resp = client.post(
            "/api/release/sync",
            content=bundle.read_bytes(),
            headers=_auth_headers(release_env["token"]),
        )
        assert resp.status_code == 400
        # Nothing should be visible.
        assert client.get("/api/release/manifest").status_code == 404


# ---------------------------------------------------------------------------
# Regression: atomic directory-level replacement, no partial visibility
# ---------------------------------------------------------------------------

class TestAtomicPublishNoPartialVisibility:
    """Verify readers never see a partially populated version directory."""

    def test_no_partial_files_during_new_publish(self, release_env, tmp_path):
        """After a successful publish, exactly the expected files exist —
        no staging artifacts, no partial directories."""
        from app.release_cache import ReleaseCache

        installer = b"installer-content"
        bundle = tmp_path / "bundle.zip"
        _make_bundle(bundle, "0.9.1", installer, release_env["url"], release_env["key"])

        cache = ReleaseCache(release_env["cache_dir"], release_env["public_raw"], retention=3)
        cache.publish_bundle(bundle)

        version_dir = release_env["cache_dir"] / "0.9.1"
        file_names = sorted(p.name for p in version_dir.iterdir())
        assert file_names == [
            "AutoScript-Hub-Setup-0.9.1.exe",
            "autoscript-hub-update.json",
            "autoscript-hub-update.json.sig",
        ]
        # No staging directories left behind.
        staging_dirs = list(release_env["cache_dir"].glob(".publish-staging-*"))
        assert staging_dirs == []
        old_dirs = list(release_env["cache_dir"].glob(".old-*"))
        assert old_dirs == []

    def test_republish_preserves_old_until_new_is_complete(self, release_env, tmp_path):
        """Replacing an existing version must keep old content intact until
        the new content is fully assembled, then atomically swap."""
        from app.release_cache import ReleaseCache

        cache = ReleaseCache(release_env["cache_dir"], release_env["public_raw"], retention=3)

        # Publish version 1.
        installer1 = b"installer-v1-original"
        bundle1 = tmp_path / "b1.zip"
        _make_bundle(bundle1, "0.9.1", installer1, release_env["url"], release_env["key"])
        cache.publish_bundle(bundle1)
        assert cache.get_file(None, "AutoScript-Hub-Setup-0.9.1.exe").read_bytes() == installer1

        # Publish replacement version 2.
        installer2 = b"installer-v2-replacement-content"
        bundle2 = tmp_path / "b2.zip"
        _make_bundle(bundle2, "0.9.1", installer2, release_env["url"], release_env["key"])
        cache.publish_bundle(bundle2)

        # After replacement: new content visible, exactly one version dir.
        assert cache.get_file(None, "AutoScript-Hub-Setup-0.9.1.exe").read_bytes() == installer2
        version_dir = release_env["cache_dir"] / "0.9.1"
        assert version_dir.is_dir()
        # No leftover backup directories.
        old_dirs = list(release_env["cache_dir"].glob(".old-*"))
        assert old_dirs == []
        staging_dirs = list(release_env["cache_dir"].glob(".publish-staging-*"))
        assert staging_dirs == []

    def test_version_directory_not_visible_until_complete(self, release_env, tmp_path):
        """get_file(None, ...) resolves via the index, so a stray directory
        without an index entry is never served to anonymous readers."""
        from app.release_cache import ReleaseCache

        cache = ReleaseCache(release_env["cache_dir"], release_env["public_raw"], retention=3)

        # Simulate a stray directory without index update.
        stray_dir = release_env["cache_dir"] / "0.9.5"
        stray_dir.mkdir()
        (stray_dir / "autoscript-hub-update.json").write_bytes(b"partial")

        # The index must not reference it, so latest_version is None.
        assert cache.latest_version() is None
        # Anonymous reads use get_file(None, ...) which resolves via the index.
        assert cache.get_file(None, "autoscript-hub-update.json") is None
        assert cache.get_file(None, "autoscript-hub-update.json.sig") is None

    def test_index_updated_only_after_complete_directory_exists(self, release_env, tmp_path):
        """After publish, the index must reference a directory that actually
        contains all expected files."""
        from app.release_cache import ReleaseCache

        installer = b"installer"
        bundle = tmp_path / "bundle.zip"
        _make_bundle(bundle, "0.9.2", installer, release_env["url"], release_env["key"])

        cache = ReleaseCache(release_env["cache_dir"], release_env["public_raw"], retention=3)
        cache.publish_bundle(bundle)

        index = cache.read_index()
        assert index["latest_version"] == "0.9.2"
        version_dir = release_env["cache_dir"] / "0.9.2"
        assert version_dir.is_dir()
        # All three expected files present.
        for name in ("autoscript-hub-update.json", "autoscript-hub-update.json.sig",
                      "AutoScript-Hub-Setup-0.9.2.exe"):
            assert (version_dir / name).is_file()
