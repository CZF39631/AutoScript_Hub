"""LAN release-cache API.

Anonymous read endpoints serve the latest manifest, signature, and installer
from ``/data/release-cache``.  An authenticated upload endpoint accepts a
complete release bundle ZIP and publishes it atomically.

Security model:
  - Reads are anonymous (no auth required) — this mirrors the public release.
  - Uploads require a Bearer token compared in constant time.
  - The server validates manifest signature, asset hash/size, and prevents
    path traversal before making any file visible to readers.
"""

import hmac
import logging
import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import FileResponse, JSONResponse

from app.config import (
    RELEASE_CACHE_DIR,
    RELEASE_CACHE_RETENTION,
    RELEASE_CACHE_SYNC_TOKEN,
    UPDATE_PUBLIC_KEY_BYTES,
)
from app.release_cache import (
    ReleaseCache,
    ReleaseCacheDisabled,
    ReleaseCacheError,
)

router = APIRouter(prefix="/api/release", tags=["release-cache"])
logger = logging.getLogger(__name__)


def _get_cache() -> ReleaseCache:
    """Build a ReleaseCache bound to the configured settings."""
    return ReleaseCache(
        cache_dir=RELEASE_CACHE_DIR,
        public_key=UPDATE_PUBLIC_KEY_BYTES,
        retention=RELEASE_CACHE_RETENTION,
    )


def _verify_token(authorization: str | None) -> None:
    """Constant-time Bearer token verification."""
    expected = RELEASE_CACHE_SYNC_TOKEN
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="发布缓存同步未启用：服务器未配置 RELEASE_CACHE_SYNC_TOKEN",
        )
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少 Authorization 头",
        )
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization 格式错误，应为 Bearer <token>",
        )
    provided = parts[1]
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="同步令牌无效",
        )


# ----------------------------------------------------------------------
# Anonymous read endpoints
# ----------------------------------------------------------------------

@router.get("/manifest/{channel}.sig")
async def get_channel_manifest_sig(channel: str):
    """Serve the cached signature selected for stable or beta."""
    if channel not in {"stable", "beta"}:
        raise HTTPException(status_code=404, detail="更新通道不存在")
    path = _get_cache().get_channel_file(channel, "autoscript-hub-update.json.sig")
    if path is None:
        raise HTTPException(status_code=404, detail="暂无缓存的更新签名")
    return FileResponse(path, media_type="application/octet-stream")


@router.get("/manifest/{channel}")
async def get_channel_manifest(channel: str):
    """Serve the cached manifest selected for stable or beta."""
    if channel not in {"stable", "beta"}:
        raise HTTPException(status_code=404, detail="更新通道不存在")
    path = _get_cache().get_channel_file(channel, "autoscript-hub-update.json")
    if path is None:
        raise HTTPException(status_code=404, detail="暂无缓存的更新清单")
    return FileResponse(path, media_type="application/json")


@router.get("/manifest")
async def get_latest_manifest():
    """Serve the latest cached manifest JSON (anonymous)."""
    cache = _get_cache()
    path = cache.get_file(None, "autoscript-hub-update.json")
    if path is None:
        raise HTTPException(status_code=404, detail="暂无缓存的更新清单")
    return FileResponse(path, media_type="application/json")


@router.get("/manifest.sig")
async def get_latest_manifest_sig():
    """Serve the latest cached manifest signature (anonymous)."""
    cache = _get_cache()
    path = cache.get_file(None, "autoscript-hub-update.json.sig")
    if path is None:
        raise HTTPException(status_code=404, detail="暂无缓存的更新签名")
    return FileResponse(path, media_type="application/octet-stream")


@router.get("/installer/{filename}")
async def get_installer(filename: str):
    """Serve a cached installer file by filename (anonymous)."""
    cache = _get_cache()
    path = cache.find_file(filename)
    if path is None:
        raise HTTPException(status_code=404, detail="安装包不存在")
    return FileResponse(path, media_type="application/octet-stream")


@router.get("/versions")
async def list_versions():
    """List all cached release versions, newest first (anonymous)."""
    cache = _get_cache()
    return {"versions": cache.list_versions(), "latest": cache.latest_version()}


# ----------------------------------------------------------------------
# Authenticated sync upload
# ----------------------------------------------------------------------

@router.post("/sync")
async def sync_bundle(
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Accept a ZIP bundle, validate it, and publish atomically.

    The request body must be the raw ZIP bytes (Content-Type: application/zip).
    Requires ``Authorization: Bearer <RELEASE_CACHE_SYNC_TOKEN>``.
    """
    _verify_token(authorization)

    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="请求体为空")

    # Write the uploaded bytes to a secure temporary file inside the cache
    # directory (same filesystem as the final destination).  mkstemp creates
    # the file atomically, avoiding the TOCTOU race of mktemp.
    cache = _get_cache()
    fd, tmp_path = tempfile.mkstemp(
        prefix="release-cache-upload-",
        suffix=".zip",
        dir=str(cache.cache_dir),
    )
    os.close(fd)
    bundle_file = Path(tmp_path)
    try:
        bundle_file.write_bytes(body)
        try:
            version = cache.publish_bundle(bundle_file)
        except ReleaseCacheDisabled as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        except ReleaseCacheError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        logger.info("Published LAN release cache version %s", version)
        return JSONResponse(
            status_code=201,
            content={"message": "发布成功", "version": version},
        )
    finally:
        try:
            bundle_file.unlink()
        except OSError:
            pass
