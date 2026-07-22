import hashlib
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from shared.update_manifest import InvalidManifestSignature, UpdateManifest, _decode_signature, _public_key


def _signed_manifest(installer=b"installer"):
    key = Ed25519PrivateKey.generate()
    payload = {
        "schema_version": 1,
        "product": "autoscript-hub-client",
        "version": "0.9.1",
        "channel": "beta",
        "published_at": "2026-07-21T00:00:00Z",
        "minimum_client_version": "0.9.0",
        "release_notes_url": "https://example.com/releases/0.9.1",
        "assets": {
            "windows-x86_64": {
                "filename": "AutoScript-Hub-Setup-0.9.1.exe",
                "size": len(installer),
                "sha256": hashlib.sha256(installer).hexdigest(),
                "urls": ["https://gitee.example/installer.exe", "https://github.example/installer.exe"],
            }
        },
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return raw, key.sign(raw), public


def test_signed_manifest_selects_windows_asset():
    raw, signature, public = _signed_manifest()

    manifest = UpdateManifest.from_bytes(raw, signature, public)

    assert manifest.asset_for("windows-x86_64").filename.endswith(".exe")
    assert manifest.is_newer_than("0.9.0") is True


def test_bad_signature_is_rejected_before_json_parsing():
    raw, _, public = _signed_manifest()

    with pytest.raises(InvalidManifestSignature):
        UpdateManifest.from_bytes(raw, b"bad", public)


def test_raw_binary_key_and_signature_are_not_whitespace_stripped():
    signature = b" " + (b"x" * 63)
    public = b" " + (b"y" * 31)

    assert _decode_signature(signature) == signature
    assert _public_key(public).public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    ) == public
