"""Managed Agent screen thumbnail validation and filesystem storage."""

import io
import os
import tempfile
import warnings
from pathlib import Path
from typing import Tuple

from fastapi import HTTPException, Request, status
from PIL import Image, UnidentifiedImageError

from app.config import THUMBNAILS_DIR


MAX_THUMBNAIL_BYTES = 1024 * 1024
MAX_THUMBNAIL_DIMENSION = 1280


def thumbnail_path(agent_id: int) -> Path:
    """Return a server-controlled path; Agent input never becomes a filename."""
    return Path(THUMBNAILS_DIR) / "{}.jpg".format(agent_id)


async def read_bounded_jpeg(request: Request) -> Tuple[bytes, int, int]:
    """Read at most 1 MiB and fully validate a bounded, genuine JPEG."""
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "image/jpeg":
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="缩略图必须使用 image/jpeg",
        )

    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_size = int(content_length)
        except ValueError:
            raise HTTPException(status_code=400, detail="无效的 Content-Length")
        if declared_size < 0:
            raise HTTPException(status_code=400, detail="无效的 Content-Length")
        if declared_size > MAX_THUMBNAIL_BYTES:
            raise HTTPException(status_code=413, detail="缩略图不得超过 1 MiB")

    payload = bytearray()
    async for chunk in request.stream():
        if len(payload) + len(chunk) > MAX_THUMBNAIL_BYTES:
            raise HTTPException(status_code=413, detail="缩略图不得超过 1 MiB")
        payload.extend(chunk)
    data = bytes(payload)
    if not data:
        raise HTTPException(status_code=400, detail="缩略图不能为空")

    # Pillow accepts some data after JPEG's EOI marker. Refuse such polyglot-like
    # payloads instead of merely trusting the extension or request media type.
    if not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9"):
        raise HTTPException(status_code=415, detail="文件不是有效的 JPEG")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format != "JPEG":
                    raise HTTPException(status_code=415, detail="文件不是 JPEG")
                width, height = image.size
                if (
                    width < 1
                    or height < 1
                    or width > MAX_THUMBNAIL_DIMENSION
                    or height > MAX_THUMBNAIL_DIMENSION
                ):
                    raise HTTPException(status_code=400, detail="缩略图宽高不得超过 1280 像素")
                image.verify()
            # verify() validates the structure without decoding pixels. Reopen and
            # decode once so truncated/corrupt scan data cannot be persisted.
            with Image.open(io.BytesIO(data)) as image:
                image.load()
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError,
            Image.DecompressionBombWarning, ValueError):
        raise HTTPException(status_code=415, detail="文件不是有效的 JPEG")
    return data, width, height


def replace_thumbnail(agent_id: int, data: bytes) -> Path:
    """Atomically replace the only thumbnail retained for an Agent."""
    directory = Path(THUMBNAILS_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    destination = thumbnail_path(agent_id)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=str(directory), prefix=".thumbnail-{}-".format(agent_id), delete=False
        ) as temp_file:
            temp_path = Path(temp_file.name)
            temp_file.write(data)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(str(temp_path), str(destination))
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
    return destination


def delete_thumbnail(agent_id: int) -> None:
    try:
        thumbnail_path(agent_id).unlink()
    except FileNotFoundError:
        pass
