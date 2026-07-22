#!/usr/bin/env python3
"""Anonymously verify that public release mirrors match local artifacts byte-for-byte."""

import argparse
from pathlib import Path
import time
from typing import Callable
from urllib.parse import quote
from urllib.request import Request, urlopen


CHECKSUM_NAME = "SHA256SUMS.txt"


def http_get_bytes(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "AutoScript-Hub-Release-Verifier/0.9"})
    with urlopen(request, timeout=60) as response:
        return response.read()


def _asset_names(checksum_file: Path) -> list[str]:
    names = []
    for line in checksum_file.read_text(encoding="utf-8").splitlines():
        try:
            digest, name = line.split("  ", 1)
        except ValueError as exc:
            raise ValueError(f"invalid checksum line: {line}") from exc
        if len(digest) != 64 or not name or Path(name).name != name:
            raise ValueError(f"invalid checksum entry: {line}")
        names.append(name)
    if not names:
        raise ValueError("checksum file contains no release assets")
    return names


def _download_expected(
    url: str,
    expected: bytes,
    attempts: int,
    delay: float,
    http_get: Callable[[str], bytes],
) -> None:
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            payload = http_get(url)
            if payload != expected:
                raise ValueError(f"byte mismatch for {url}")
            return
        except Exception as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(delay)
    raise RuntimeError(str(last_error)) from last_error


def verify_mirrors(
    directory: Path,
    base_urls: list[str],
    attempts: int = 12,
    delay: float = 5.0,
    http_get: Callable[[str], bytes] = http_get_bytes,
) -> None:
    directory = directory.resolve()
    checksum_file = directory / CHECKSUM_NAME
    names = [CHECKSUM_NAME, *_asset_names(checksum_file)]
    for name in names:
        local = directory / name
        if not local.is_file():
            raise FileNotFoundError(f"local release asset is missing: {name}")
        expected = local.read_bytes()
        for base_url in base_urls:
            url = f"{base_url.rstrip('/')}/{quote(name)}"
            _download_expected(url, expected, attempts, delay, http_get)
            print(f"verified {url}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--base-url", action="append", required=True)
    parser.add_argument("--attempts", type=int, default=12)
    parser.add_argument("--delay", type=float, default=5.0)
    args = parser.parse_args()
    if len(args.base_url) < 2:
        parser.error("at least two --base-url values are required")
    if args.attempts < 1 or args.delay < 0:
        parser.error("attempts must be positive and delay cannot be negative")
    verify_mirrors(args.directory, args.base_url, args.attempts, args.delay)


if __name__ == "__main__":
    main()
