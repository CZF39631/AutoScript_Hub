#!/usr/bin/env python3
"""Create and Ed25519-sign the raw client update manifest."""

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--installer", type=Path, required=True)
    parser.add_argument("--private-key", type=Path, required=True)
    parser.add_argument("--url", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minimum-client-version", default="0.9.0")
    parser.add_argument("--release-notes-url", default="https://github.com/CZF39631/AutoScript_Hub/releases")
    args = parser.parse_args()
    installer_bytes = args.installer.read_bytes()
    channel = "stable" if args.version.startswith("1.") else "beta"
    manifest = {
        "schema_version": 1,
        "product": "autoscript-hub-client",
        "version": args.version,
        "channel": channel,
        "published_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "minimum_client_version": args.minimum_client_version,
        "release_notes_url": args.release_notes_url,
        "assets": {
            "windows-x86_64": {
                "filename": args.installer.name,
                "size": len(installer_bytes),
                "sha256": hashlib.sha256(installer_bytes).hexdigest(),
                "urls": args.url,
            }
        },
    }
    raw = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    key = serialization.load_pem_private_key(args.private_key.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise SystemExit("update private key must be Ed25519")
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "autoscript-hub-update.json").write_bytes(raw)
    (args.output / "autoscript-hub-update.json.sig").write_bytes(base64.b64encode(key.sign(raw)) + b"\n")


if __name__ == "__main__":
    main()
