#!/usr/bin/env python3
"""Create and Ed25519-sign the raw client update manifest."""

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.parse import quote

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def _file_digest(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def _part_records(installer: Path, directory: Path, url_bases: list[str]) -> list[dict]:
    paths = sorted(directory.glob(installer.name + ".part[0-9][0-9][0-9][0-9]"))
    if not paths:
        raise SystemExit("parts directory contains no installer parts")
    combined = hashlib.sha256()
    total = 0
    records = []
    for expected_index, path in enumerate(paths, 1):
        expected_name = f"{installer.name}.part{expected_index:04d}"
        if path.name != expected_name:
            raise SystemExit(f"parts are not contiguous: expected {expected_name}")
        size, digest = _file_digest(path)
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                combined.update(chunk)
        total += size
        records.append({
            "filename": path.name,
            "size": size,
            "sha256": digest,
            "urls": [base.rstrip("/") + "/" + quote(path.name) for base in url_bases],
        })
    installer_size, installer_digest = _file_digest(installer)
    if total != installer_size or combined.hexdigest() != installer_digest:
        raise SystemExit("parts do not reconstruct the installer")
    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--installer", type=Path, required=True)
    parser.add_argument("--private-key", type=Path, required=True)
    parser.add_argument("--url", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--parts-dir", "--parts-directory", dest="parts_dir", type=Path)
    parser.add_argument("--parts-url-base", "--part-url-base", dest="parts_url_bases", action="append", default=[])
    parser.add_argument("--minimum-client-version", default="0.9.0")
    parser.add_argument("--release-notes-url", default="https://github.com/CZF39631/AutoScript_Hub/releases")
    args = parser.parse_args()
    if bool(args.parts_dir) != bool(args.parts_url_bases):
        parser.error("--parts-dir and --parts-url-base must be used together")
    installer_size, installer_digest = _file_digest(args.installer)
    channel = "stable" if args.version.startswith("1.") and "-" not in args.version else "beta"
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
                "size": installer_size,
                "sha256": installer_digest,
                "urls": args.url,
            }
        },
    }
    if args.parts_dir:
        manifest["assets"]["windows-x86_64"]["parts"] = _part_records(
            args.installer,
            args.parts_dir,
            args.parts_url_bases,
        )
    raw = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    key = serialization.load_pem_private_key(args.private_key.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise SystemExit("update private key must be Ed25519")
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "autoscript-hub-update.json").write_bytes(raw)
    (args.output / "autoscript-hub-update.json.sig").write_bytes(base64.b64encode(key.sign(raw)) + b"\n")


if __name__ == "__main__":
    main()
