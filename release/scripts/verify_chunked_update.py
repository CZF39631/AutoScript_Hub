#!/usr/bin/env python3
"""Anonymously verify a signed update manifest and reconstruct its chunked asset."""

import argparse
import hashlib
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.update_manifest import UpdateManifest


BUFFER_SIZE = 1024 * 1024


def _fetch(url: str, attempts: int = 6) -> bytes:
    error = None
    for attempt in range(attempts):
        try:
            request = Request(url, headers={"User-Agent": "AutoScript-Hub-Release-Verifier/1.0"})
            with urlopen(request, timeout=60) as response:
                return response.read()
        except Exception as exc:
            error = exc
            if attempt + 1 < attempts:
                time.sleep(5)
    raise RuntimeError(f"无法匿名读取 {url}: {error}") from error


def verify(manifest_url: str, signature_url: str, public_key: bytes) -> None:
    manifest = UpdateManifest.from_bytes(
        _fetch(manifest_url),
        _fetch(signature_url),
        public_key,
    )
    asset = manifest.asset_for("windows-x86_64")
    if not asset.parts:
        raise RuntimeError("签名更新清单没有 Gitee 分卷")

    combined = hashlib.sha256()
    total = 0
    for part in asset.parts:
        payload = _fetch(part.urls[0])
        digest = hashlib.sha256(payload).hexdigest()
        if len(payload) != part.size or digest != part.sha256:
            raise RuntimeError(f"分卷校验失败: {part.filename}")
        combined.update(payload)
        total += len(payload)

    if total != asset.size or combined.hexdigest() != asset.sha256:
        raise RuntimeError("Gitee 分卷无法重建签名清单指定的完整安装包")
    print(f"verified {len(asset.parts)} parts, {total} bytes, sha256={asset.sha256}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest-url", required=True)
    parser.add_argument("--signature-url", required=True)
    parser.add_argument("--public-key", type=Path, required=True)
    args = parser.parse_args()
    verify(args.manifest_url, args.signature_url, args.public_key.read_bytes())


if __name__ == "__main__":
    main()
