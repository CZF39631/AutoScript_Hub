#!/usr/bin/env python3
"""Write SHA-256 checksums for every final release asset in a directory."""

import argparse
from fnmatch import fnmatchcase
import hashlib
from pathlib import Path


CHECKSUM_NAME = "SHA256SUMS.txt"
RELEASE_PATTERNS = (
    "AutoScript-Hub-Setup-*.exe",
    "autoscript-script-authoring-*.zip",
    "autoscript-hub-server-deploy-*.zip",
    "autoscript-hub-update.json",
    "autoscript-hub-update.json.sig",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_release_asset(path: Path) -> bool:
    return path.is_file() and any(fnmatchcase(path.name, pattern) for pattern in RELEASE_PATTERNS)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    directory = args.directory.resolve()
    if not directory.is_dir():
        raise SystemExit(f"release directory does not exist: {directory}")

    assets = sorted(
        path for path in directory.iterdir()
        if is_release_asset(path)
    )
    if not assets:
        raise SystemExit("release directory contains no assets")
    output = directory / CHECKSUM_NAME
    output.write_text(
        "".join(f"{sha256(path)}  {path.name}\n" for path in assets),
        encoding="utf-8",
    )
    print(output)


if __name__ == "__main__":
    main()
