#!/usr/bin/env python3
"""Build deterministic standalone Skill and Linux deployment bundles."""

import argparse
import hashlib
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parents[2]
FIXED_TIME = (2026, 1, 1, 0, 0, 0)


def _zip(output, entries):
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for source, archive_name in sorted(entries, key=lambda item: item[1]):
            info = zipfile.ZipInfo(archive_name, date_time=FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            bundle.writestr(info, source.read_bytes(), compresslevel=9)


def _tree_entries(source, prefix):
    return [
        (path, f"{prefix}/{path.relative_to(source).as_posix()}")
        for path in source.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"}
    ]


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    skill_source = ROOT / "skills" / "autoscript-script-authoring"
    skill_zip = args.output / f"autoscript-script-authoring-{args.version}.zip"
    _zip(skill_zip, _tree_entries(skill_source, "autoscript-script-authoring"))

    deployment_entries = []
    for relative in ["deploy/compose.yaml", "deploy/compose.local.yaml", "deploy/.env.example", "README.md"]:
        deployment_entries.append((ROOT / relative, f"autoscript-hub-server/{relative}"))
    deployment_entries.extend(_tree_entries(ROOT / "ops" / "server", "autoscript-hub-server/ops/server"))
    for document in (ROOT / "docs").glob("*deployment*.md"):
        deployment_entries.append((document, f"autoscript-hub-server/docs/{document.name}"))
    deploy_zip = args.output / f"autoscript-hub-server-deploy-{args.version}.zip"
    _zip(deploy_zip, deployment_entries)

    checksum = args.output / "SHA256SUMS.txt"
    artifacts = [skill_zip, deploy_zip]
    checksum.write_text(
        "".join(f"{_sha256(path)}  {path.name}\n" for path in artifacts),
        encoding="utf-8",
    )
    print(skill_zip)
    print(deploy_zip)
    print(checksum)


if __name__ == "__main__":
    main()
