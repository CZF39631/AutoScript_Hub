"""Signed update manifest parsing shared by release tools and clients."""

from dataclasses import dataclass
import base64
import json
import re
from typing import Any
from urllib.parse import urlparse
import ipaddress

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from packaging.version import InvalidVersion, Version


class InvalidManifest(ValueError):
    pass


class InvalidManifestSignature(InvalidManifest):
    pass


@dataclass(frozen=True)
class UpdateAsset:
    filename: str
    size: int
    sha256: str
    urls: tuple[str, ...]


def _valid_download_url(value: str) -> bool:
    parsed = urlparse(value)
    if parsed.scheme == "https" and parsed.hostname:
        return True
    if parsed.scheme != "http" or not parsed.hostname:
        return False
    if parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        address = ipaddress.ip_address(parsed.hostname)
        return address.is_private or address.is_loopback
    except ValueError:
        return parsed.hostname.endswith(".local")


def _decode_signature(value: bytes) -> bytes:
    if len(value) == 64:
        return value
    stripped = value.strip()
    try:
        decoded = base64.b64decode(stripped, validate=True)
    except ValueError as exc:
        raise InvalidManifestSignature("签名不是 Ed25519 原始值或 Base64") from exc
    if len(decoded) != 64:
        raise InvalidManifestSignature("Ed25519 签名长度错误")
    return decoded


def _public_key(value: bytes) -> Ed25519PublicKey:
    if len(value) == 32:
        return Ed25519PublicKey.from_public_bytes(value)
    stripped = value.strip()
    try:
        decoded = base64.b64decode(stripped, validate=True)
        if len(decoded) == 32:
            return Ed25519PublicKey.from_public_bytes(decoded)
    except ValueError:
        pass
    try:
        key = serialization.load_pem_public_key(stripped)
    except ValueError as exc:
        raise InvalidManifestSignature("无法读取更新公钥") from exc
    if not isinstance(key, Ed25519PublicKey):
        raise InvalidManifestSignature("更新公钥不是 Ed25519")
    return key


@dataclass(frozen=True)
class UpdateManifest:
    schema_version: int
    product: str
    version: str
    channel: str
    published_at: str
    minimum_client_version: str
    release_notes_url: str
    assets: dict[str, UpdateAsset]

    @classmethod
    def from_bytes(cls, payload: bytes, signature: bytes, public_key: bytes) -> "UpdateManifest":
        try:
            _public_key(public_key).verify(_decode_signature(signature), payload)
        except InvalidSignature as exc:
            raise InvalidManifestSignature("更新清单签名无效") from exc
        try:
            value = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InvalidManifest("更新清单不是 UTF-8 JSON") from exc
        return cls._from_dict(value)

    @classmethod
    def _from_dict(cls, value: Any) -> "UpdateManifest":
        if not isinstance(value, dict) or value.get("schema_version") != 1:
            raise InvalidManifest("不支持的更新清单版本")
        if value.get("product") != "autoscript-hub-client":
            raise InvalidManifest("更新清单产品不匹配")
        try:
            Version(value["version"])
            Version(value["minimum_client_version"])
        except (KeyError, TypeError, InvalidVersion) as exc:
            raise InvalidManifest("清单版本不是有效 SemVer") from exc
        if value.get("channel") not in {"beta", "stable"}:
            raise InvalidManifest("更新通道无效")
        raw_assets = value.get("assets")
        if not isinstance(raw_assets, dict) or not raw_assets:
            raise InvalidManifest("更新清单缺少资产")
        assets = {}
        for platform, item in raw_assets.items():
            if not isinstance(item, dict):
                raise InvalidManifest(f"资产定义无效: {platform}")
            filename = item.get("filename")
            size = item.get("size")
            digest = item.get("sha256")
            urls = item.get("urls")
            if not isinstance(filename, str) or not filename.lower().endswith(".exe") or "/" in filename or "\\" in filename:
                raise InvalidManifest(f"安装包文件名无效: {platform}")
            if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
                raise InvalidManifest(f"安装包大小无效: {platform}")
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise InvalidManifest(f"安装包 SHA-256 无效: {platform}")
            if not isinstance(urls, list) or not urls or not all(isinstance(url, str) and _valid_download_url(url) for url in urls):
                raise InvalidManifest(f"安装包 URL 无效: {platform}")
            assets[platform] = UpdateAsset(filename, size, digest, tuple(urls))
        return cls(
            schema_version=1,
            product=value["product"],
            version=value["version"],
            channel=value["channel"],
            published_at=str(value.get("published_at", "")),
            minimum_client_version=value["minimum_client_version"],
            release_notes_url=str(value.get("release_notes_url", "")),
            assets=assets,
        )

    def asset_for(self, platform: str) -> UpdateAsset:
        try:
            return self.assets[platform]
        except KeyError as exc:
            raise InvalidManifest(f"清单没有 {platform} 资产") from exc

    def is_newer_than(self, current_version: str) -> bool:
        try:
            return Version(self.version) > Version(current_version)
        except InvalidVersion:
            return False

    def supports(self, current_version: str) -> bool:
        try:
            return Version(current_version) >= Version(self.minimum_client_version)
        except InvalidVersion:
            return False
