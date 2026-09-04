"""Background GitHub release downloader for the server-side release cache."""

import hashlib
import inspect
import json
import logging
import re
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
from urllib.parse import unquote, urlsplit

import httpx
from packaging.version import InvalidVersion, Version

from app.config import RELEASE_CACHE_DIR, RELEASE_CACHE_RETENTION, UPDATE_PUBLIC_KEY_BYTES
from app.database import SessionLocal
from app.models import ServerSettings
from app.release_cache import MANIFEST_NAME, MANIFEST_SIG_NAME, ReleaseCache, ReleaseCacheError
from shared.update_manifest import InvalidManifest, UpdateManifest

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
DEFAULT_INTERVAL_HOURS = 6
MAX_RELEASES_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_SIGNATURE_BYTES = 16 * 1024
MAX_INSTALLER_BYTES = 2 * 1024 * 1024 * 1024
DOWNLOAD_ATTEMPTS = 3
_HTTPX_PROXY_PARAMETER = "proxy" if "proxy" in inspect.signature(httpx.Client).parameters else "proxies"
_REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")

_worker_lock = threading.Lock()
_worker_thread: Optional[threading.Thread] = None
_wake_event = threading.Event()


def _load_settings() -> Dict[str, Any]:
    db = SessionLocal()
    try:
        row = db.query(ServerSettings).filter(ServerSettings.id == 1).first()
        if row is None:
            return {
                "enabled": False,
                "outbound_proxy": None,
                "github_repository": "CZF39631/AutoScript_Hub",
                "interval_hours": DEFAULT_INTERVAL_HOURS,
            }
        return {
            "enabled": bool(row.enabled),
            "outbound_proxy": row.outbound_proxy,
            "github_repository": row.github_repository,
            "interval_hours": max(1, min(168, int(row.interval_hours))),
        }
    finally:
        db.close()


def _request_bytes(client: httpx.Client, url: str, limit: int) -> bytes:
    last_error: Optional[Exception] = None
    for attempt in range(DOWNLOAD_ATTEMPTS):
        try:
            chunks = []
            size = 0
            with client.stream("GET", url) as response:
                response.raise_for_status()
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > limit:
                        raise ReleaseCacheError("下载内容超过大小上限")
                    chunks.append(chunk)
            return b"".join(chunks)
        except (httpx.HTTPError, OSError, ReleaseCacheError) as exc:
            last_error = exc
            if attempt + 1 < DOWNLOAD_ATTEMPTS:
                time.sleep(0.25 * (2 ** attempt))
    raise ReleaseCacheError("下载失败") from last_error


def _download_installer(client: httpx.Client, url: str, target: Path, size: int, digest: str) -> None:
    if size <= 0 or size > MAX_INSTALLER_BYTES:
        raise ReleaseCacheError("安装包声明大小超过服务器上限")
    last_error: Optional[Exception] = None
    partial = target.with_suffix(target.suffix + ".part")
    for attempt in range(DOWNLOAD_ATTEMPTS):
        try:
            actual_size = 0
            actual_digest = hashlib.sha256()
            with client.stream("GET", url) as response, partial.open("wb") as output:
                response.raise_for_status()
                for chunk in response.iter_bytes():
                    actual_size += len(chunk)
                    if actual_size > size or actual_size > MAX_INSTALLER_BYTES:
                        raise ReleaseCacheError("安装包下载大小超过清单声明")
                    actual_digest.update(chunk)
                    output.write(chunk)
            if actual_size != size:
                raise ReleaseCacheError("安装包下载大小与清单不匹配")
            if actual_digest.hexdigest() != digest:
                raise ReleaseCacheError("安装包下载 SHA-256 与清单不匹配")
            partial.replace(target)
            return
        except (httpx.HTTPError, OSError, ReleaseCacheError) as exc:
            last_error = exc
            try:
                partial.unlink()
            except OSError:
                pass
            if attempt + 1 < DOWNLOAD_ATTEMPTS:
                time.sleep(0.25 * (2 ** attempt))
    raise ReleaseCacheError("安装包下载失败") from last_error


def _github_release_url(url: str, repository: str, expected_filename: str) -> bool:
    """Allow only a complete file URL under the configured GitHub release path."""
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or (parsed.hostname or "").lower() != "github.com"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        return False
    try:
        if parsed.port not in (None, 443):
            return False
    except ValueError:
        return False
    path_parts = [unquote(value) for value in parsed.path.split("/")]
    repo_parts = repository.split("/", 1)
    return (
        len(path_parts) == 7
        and path_parts[0] == ""
        and [value.casefold() for value in path_parts[1:3]] == [value.casefold() for value in repo_parts]
        and path_parts[3] == "releases"
        and path_parts[4] == "download"
        and bool(path_parts[5])
        and path_parts[6] == expected_filename
    )


def _release_asset_url(release: Dict[str, Any], repository: str, filename: str) -> str:
    for item in release.get("assets", []):
        if isinstance(item, dict) and item.get("name") == filename:
            url = item.get("browser_download_url")
            if isinstance(url, str) and _github_release_url(url, repository, filename):
                return url
    raise ReleaseCacheError(f"GitHub Release 缺少安全的 {filename} asset")


def _select_releases(releases: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    usable = []
    for item in releases:
        if not isinstance(item, dict) or item.get("draft"):
            continue
        try:
            version = Version(str(item.get("tag_name", "")).lstrip("v"))
        except InvalidVersion:
            continue
        usable.append((version, item))
    usable.sort(key=lambda entry: entry[0], reverse=True)
    stable = next((item for _, item in usable if not item.get("prerelease")), None)
    beta = usable[0][1] if usable else None
    selected = {}
    if stable is not None:
        selected["stable"] = stable
    if beta is not None:
        selected["beta"] = beta
    return selected


def _cache_release(
    client: httpx.Client,
    cache: ReleaseCache,
    repository: str,
    channel: str,
    release: Dict[str, Any],
) -> str:
    manifest_url = _release_asset_url(release, repository, MANIFEST_NAME)
    signature_url = _release_asset_url(release, repository, MANIFEST_SIG_NAME)
    manifest_bytes = _request_bytes(client, manifest_url, MAX_MANIFEST_BYTES)
    signature_bytes = _request_bytes(client, signature_url, MAX_SIGNATURE_BYTES)
    if UPDATE_PUBLIC_KEY_BYTES is None:
        raise ReleaseCacheError("服务器未配置更新验签公钥")
    try:
        manifest = UpdateManifest.from_bytes(manifest_bytes, signature_bytes, UPDATE_PUBLIC_KEY_BYTES)
    except InvalidManifest as exc:
        raise ReleaseCacheError("GitHub 更新清单验签失败") from exc
    if channel == "stable" and manifest.channel != "stable":
        raise ReleaseCacheError("stable Release 提供了非 stable 清单")
    asset = manifest.asset_for("windows-x86_64")
    # Deliberately ignore asset.parts: the server cache publishes only the complete EXE.
    installer_url = next(
        (
            url for url in asset.urls
            if _github_release_url(url, repository, asset.filename)
        ),
        None,
    )
    if installer_url is None:
        raise ReleaseCacheError("清单没有指向指定 GitHub 仓库的完整 EXE URL")

    work_dir = Path(tempfile.mkdtemp(prefix="server-update-", dir=str(cache.cache_dir)))
    try:
        manifest_path = work_dir / MANIFEST_NAME
        signature_path = work_dir / MANIFEST_SIG_NAME
        installer_path = work_dir / asset.filename
        manifest_path.write_bytes(manifest_bytes)
        signature_path.write_bytes(signature_bytes)
        _download_installer(client, installer_url, installer_path, asset.size, asset.sha256)
        return cache.publish_files(manifest_path, signature_path, installer_path, channel=channel)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def run_server_update_cycle() -> int:
    """Run one synchronous cache cycle in the downloader thread; return next interval."""
    settings = _load_settings()
    interval = settings["interval_hours"]
    if not settings["enabled"]:
        return interval
    repository = settings["github_repository"]
    if not isinstance(repository, str) or not _REPOSITORY_PATTERN.fullmatch(repository):
        logger.warning("Server update skipped: invalid repository setting")
        return interval

    cache = ReleaseCache(RELEASE_CACHE_DIR, UPDATE_PUBLIC_KEY_BYTES, RELEASE_CACHE_RETENTION)
    client_options: Dict[str, Any] = {
        "headers": {
            "Accept": "application/vnd.github+json",
            "User-Agent": "AutoScript-Hub-server-update-cache",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        "follow_redirects": True,
        "timeout": httpx.Timeout(30.0, connect=10.0, read=60.0),
    }
    if settings["outbound_proxy"]:
        # httpx renamed ``proxies`` to ``proxy`` in 0.26.
        client_options[_HTTPX_PROXY_PARAMETER] = settings["outbound_proxy"]
    try:
        with httpx.Client(**client_options) as client:
            api_url = f"{GITHUB_API}/repos/{repository}/releases?per_page=100"
            releases_bytes = _request_bytes(client, api_url, MAX_RELEASES_RESPONSE_BYTES)
            releases = json.loads(releases_bytes.decode("utf-8"))
            if not isinstance(releases, list):
                raise ReleaseCacheError("GitHub Releases API 响应格式无效")
            selected = _select_releases(releases)
            for channel in ("stable", "beta"):
                release = selected.get(channel)
                if release is None:
                    logger.info("No usable %s GitHub release found", channel)
                    continue
                try:
                    version = _cache_release(client, cache, repository, channel, release)
                    logger.info("Server update cache refreshed: channel=%s version=%s", channel, version)
                except Exception as exc:
                    # Do not format exception details: proxy errors can contain credentials.
                    logger.warning("Server update channel refresh failed: channel=%s error=%s", channel, type(exc).__name__)
    except Exception as exc:
        logger.warning("Server update cycle failed: error=%s", type(exc).__name__)
    return interval


def _worker_loop() -> None:
    while True:
        started = time.monotonic()
        interval = run_server_update_cycle()
        delay = max(1.0, interval * 3600 - (time.monotonic() - started))
        _wake_event.wait(delay)
        _wake_event.clear()


def start_server_update_cache() -> None:
    """Start one downloader daemon. Calling this repeatedly is safe."""
    global _worker_thread
    with _worker_lock:
        if _worker_thread is not None and _worker_thread.is_alive():
            return
        _worker_thread = threading.Thread(
            target=_worker_loop,
            daemon=True,
            name="autoscript-server-update-cache",
        )
        _worker_thread.start()
    logger.info("Server update cache worker started")


def wake_server_update_cache() -> None:
    _wake_event.set()
