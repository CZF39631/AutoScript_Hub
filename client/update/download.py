"""Streaming, verified and resumable update-asset downloads."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import time
from typing import Callable
from urllib.request import Request, urlopen


CHUNK_SIZE = 1024 * 1024
_STRONG_ETAG = re.compile(r'^"[^"\r\n]*"$')
_CONTENT_RANGE = re.compile(r"^bytes (\d+)-(\d+)/(\d+)$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _strong_etag(value: str | None) -> bool:
    return bool(value and _STRONG_ETAG.fullmatch(value.strip()))


def _remove(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _resume_offset(temporary: Path, etag_path: Path, expected_size: int) -> tuple[int, str | None]:
    if not temporary.is_file() or not etag_path.is_file():
        return 0, None
    try:
        offset = temporary.stat().st_size
        etag = etag_path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError):
        return 0, None
    if offset <= 0 or offset >= expected_size or not _strong_etag(etag):
        return 0, None
    return offset, etag


def _response_status(response) -> int:
    status = getattr(response, "status", None)
    return int(status if status is not None else response.getcode())


def _valid_partial_response(response, offset: int, etag: str, expected_size: int) -> bool:
    if _response_status(response) != 206:
        return False
    response_etag = (response.headers.get("ETag") or "").strip()
    if response_etag != etag or not _strong_etag(response_etag):
        return False
    match = _CONTENT_RANGE.fullmatch(response.headers.get("Content-Range", "").strip())
    if not match:
        return False
    start, end, total = map(int, match.groups())
    if (start, end, total) != (offset, expected_size - 1, expected_size):
        return False
    content_length = response.headers.get("Content-Length")
    return content_length is not None and content_length.isdigit() and int(content_length) == expected_size - offset


def download_verified_file(
    url: str,
    destination: Path,
    expected_size: int,
    expected_sha256: str,
    *,
    attempts: int = 3,
    timeout: int = 30,
    retry_delay: float = 0.2,
    opener: Callable = urlopen,
) -> None:
    """Download to a sibling temporary file and atomically publish after verification.

    A partial body is retained only when accompanied by a strong ETag. It is
    appended only after an exact 206/ETag/Content-Range/Content-Length match.
    Any weaker or ambiguous response resets the current file before retrying.
    """
    if attempts < 1:
        raise ValueError("attempts must be positive")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".download")
    etag_path = temporary.with_name(temporary.name + ".etag")
    last_error: Exception | None = None

    for attempt in range(attempts):
        offset, etag = _resume_offset(temporary, etag_path, expected_size)
        if not etag:
            _remove(temporary)
            _remove(etag_path)
            offset = 0
        headers = {
            "User-Agent": "AutoScript-Hub-Updater/1.0",
            "Accept-Encoding": "identity",
        }
        if offset and etag:
            headers.update({"Range": f"bytes={offset}-", "If-Range": etag})
        request = Request(url, headers=headers)
        response = None
        response_etag = None
        try:
            response = opener(request, timeout=timeout)
            status = _response_status(response)
            response_etag = (response.headers.get("ETag") or "").strip()
            append = bool(offset and etag and _valid_partial_response(response, offset, etag, expected_size))
            if offset and not append:
                # A 200 response is a legitimate full redownload (for example,
                # If-Range detected a changed object). Other responses are not.
                _remove(temporary)
                _remove(etag_path)
                offset = 0
                if status != 200:
                    raise ValueError("续传响应不满足严格的 206/Content-Range/ETag 校验")
            elif not offset and status != 200:
                raise ValueError(f"完整下载响应状态无效: {status}")

            if _strong_etag(response_etag):
                etag_path.write_text(response_etag, encoding="ascii")
            else:
                _remove(etag_path)
            with temporary.open("ab" if append else "wb") as output:
                while True:
                    chunk = response.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    output.write(chunk)
            if temporary.stat().st_size != expected_size:
                raise ValueError("下载文件长度不匹配")
            if sha256_file(temporary) != expected_sha256:
                raise ValueError("下载文件 SHA-256 不匹配")
            os.replace(temporary, destination)
            _remove(etag_path)
            return
        except Exception as exc:
            last_error = exc
            # An interrupted response without a stable object validator cannot
            # be safely resumed. A hash/length failure is also not reusable.
            safe_partial = False
            if temporary.is_file() and etag_path.is_file():
                try:
                    partial_size = temporary.stat().st_size
                    saved_etag = etag_path.read_text(encoding="ascii").strip()
                    safe_partial = 0 < partial_size < expected_size and _strong_etag(saved_etag)
                except (OSError, UnicodeError):
                    pass
            if not safe_partial:
                _remove(temporary)
                _remove(etag_path)
        finally:
            if response is not None:
                response.close()
        if attempt + 1 < attempts and retry_delay:
            time.sleep(retry_delay)

    raise RuntimeError(f"下载失败（已重试 {attempts} 次）: {last_error}") from last_error
