"""LAN release-cache core: validate, stage, atomically publish, and prune bundles.

A release bundle is a ZIP containing:
  - autoscript-hub-update.json       (signed LAN manifest)
  - autoscript-hub-update.json.sig   (Ed25519 signature)
  - AutoScript-Hub-Setup-<ver>.exe   (installer matching the manifest asset)

On upload the bundle is extracted to a temporary staging directory, every
component is validated against the public key and the manifest's declared
hash/size, and only then is the version directory atomically renamed into
place.  An incomplete or invalid upload leaves zero visible files.

Storage layout::

    RELEASE_CACHE_DIR/
        index.json                # {"latest_version": "0.9.1", "versions": [...]}
        0.9.1/
            autoscript-hub-update.json
            autoscript-hub-update.json.sig
            AutoScript-Hub-Setup-0.9.1.exe
"""

import hashlib
import json
import logging
import os
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional
from zipfile import BadZipFile, ZipFile

from packaging.version import InvalidVersion, Version

from shared.update_manifest import InvalidManifest, UpdateManifest

logger = logging.getLogger(__name__)

MANIFEST_NAME = "autoscript-hub-update.json"
MANIFEST_SIG_NAME = "autoscript-hub-update.json.sig"
INDEX_NAME = "index.json"
CHANNELS = {"stable", "beta"}
_PUBLISH_LOCK = threading.RLock()


class ReleaseCacheError(ValueError):
    """Base error for release-cache validation failures."""


class ReleaseCacheDisabled(ReleaseCacheError):
    """Raised when the feature is not configured (no sync token or public key)."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_safe_name(name: str) -> bool:
    """Reject path separators, drive letters, and traversal segments."""
    if not name or name in (".", ".."):
        return False
    if "/" in name or "\\" in name or "\x00" in name:
        return False
    if Path(name).name != name:
        return False
    return True


class ReleaseCache:
    """Manages the on-disk release-cache store with atomic publication."""

    def __init__(self, cache_dir: str, public_key: Optional[bytes], retention: int = 3):
        self.cache_dir = Path(cache_dir)
        self.public_key = public_key
        self.retention = max(1, retention)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Index management
    # ------------------------------------------------------------------

    @property
    def _index_path(self) -> Path:
        return self.cache_dir / INDEX_NAME

    def read_index(self) -> Dict[str, Any]:
        """Return a normalized index, including per-channel latest pointers."""
        default = {
            "latest_version": None,
            "versions": [],
            "channels": {"stable": None, "beta": None},
            "version_channels": {},
        }
        try:
            raw = json.loads(self._index_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return default
        if not isinstance(raw, dict):
            return default
        versions = raw.get("versions") if isinstance(raw.get("versions"), list) else []
        versions = [value for value in versions if isinstance(value, str)]
        mappings = raw.get("version_channels")
        mappings = dict(mappings) if isinstance(mappings, dict) else {}
        # Transparently adopt indexes written before channel support.
        for version in versions:
            if version in mappings:
                continue
            try:
                manifest = json.loads(
                    (self._version_dir(version) / MANIFEST_NAME).read_text(encoding="utf-8")
                )
                channel = manifest.get("channel")
                if channel in CHANNELS:
                    mappings[version] = [channel]
            except (FileNotFoundError, json.JSONDecodeError, OSError):
                pass
        normalized_mappings = {
            version: [channel for channel in channels if channel in CHANNELS]
            for version, channels in mappings.items()
            if version in versions and isinstance(channels, list)
        }
        channels = raw.get("channels") if isinstance(raw.get("channels"), dict) else {}
        channel_latest = {}
        for channel in CHANNELS:
            candidates = [v for v in versions if channel in normalized_mappings.get(v, [])]
            candidates.sort(key=Version, reverse=True)
            requested = channels.get(channel)
            channel_latest[channel] = requested if requested in candidates else (candidates[0] if candidates else None)
        return {
            "latest_version": raw.get("latest_version") if raw.get("latest_version") in versions else (versions[0] if versions else None),
            "versions": versions,
            "channels": channel_latest,
            "version_channels": normalized_mappings,
        }

    def _write_index(self, data: Dict[str, Any]) -> None:
        tmp = self._index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self._index_path)

    # ------------------------------------------------------------------
    # Public read helpers
    # ------------------------------------------------------------------

    def latest_version(self, channel: Optional[str] = None) -> Optional[str]:
        index = self.read_index()
        if channel is None:
            return index.get("latest_version")
        if channel not in CHANNELS:
            return None
        return index.get("channels", {}).get(channel)

    def list_versions(self) -> List[Dict[str, Any]]:
        """Return version metadata sorted newest-first."""
        index = self.read_index()
        result = []
        for version in index.get("versions", []):
            entry = self._version_dir(version)
            if entry.is_dir():
                result.append({"version": version})
        result.sort(key=lambda item: Version(item["version"]), reverse=True)
        return result

    def _version_dir(self, version: str) -> Path:
        return self.cache_dir / version

    def get_file(self, version: Optional[str], filename: str, channel: Optional[str] = None) -> Optional[Path]:
        """Safely resolve a cached file path.

        Returns ``None`` if the version or file does not exist.
        Rejects traversal attempts via ``_is_safe_name``.
        """
        if not _is_safe_name(filename):
            return None
        resolved_version = version or self.latest_version(channel)
        if resolved_version is None or not _is_safe_name(resolved_version):
            return None
        try:
            Version(resolved_version)
        except InvalidVersion:
            return None
        candidate = self._version_dir(resolved_version) / filename
        # Double-check the resolved path stays inside the version directory.
        try:
            candidate.resolve().relative_to(self._version_dir(resolved_version).resolve())
        except ValueError:
            return None
        return candidate if candidate.is_file() else None

    def get_channel_file(self, channel: str, filename: str) -> Optional[Path]:
        return self.get_file(None, filename, channel=channel)

    def find_file(self, filename: str) -> Optional[Path]:
        """Find a file by exact safe name in any retained version, newest first."""
        if not _is_safe_name(filename):
            return None
        for item in self.list_versions():
            path = self.get_file(item["version"], filename)
            if path is not None:
                return path
        return None

    # ------------------------------------------------------------------
    # Upload validation + atomic publish
    # ------------------------------------------------------------------

    def validate_bundle(self, bundle_path: Path) -> Dict[str, Any]:
        """Extract and validate a ZIP bundle in a staging directory.

        Returns a dict with keys: ``staging_dir``, ``version``, ``manifest``,
        ``files`` (mapping logical name -> staged Path).

        Raises :class:`ReleaseCacheError` on any validation failure.
        The caller is responsible for cleaning up ``staging_dir``.
        """
        if self.public_key is None:
            raise ReleaseCacheDisabled("缺少更新公钥，无法验证 LAN 清单签名")

        staging = Path(tempfile.mkdtemp(prefix="release-cache-stage-", dir=str(self.cache_dir)))
        try:
            return self._validate_inner(bundle_path, staging)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    def _validate_inner(self, bundle_path: Path, staging: Path) -> Dict[str, Any]:
        try:
            with ZipFile(bundle_path) as archive:
                members = archive.namelist()
                # Reject absolute paths and traversal in archive members.
                for member in members:
                    if member.startswith("/") or ".." in Path(member).parts:
                        raise ReleaseCacheError(f"压缩包包含不安全路径: {member}")
                    # Reject directory entries — the bundle must be flat files only.
                    if member.endswith("/"):
                        raise ReleaseCacheError(f"压缩包包含目录条目: {member}")
                archive.extractall(staging)
        except (BadZipFile, OSError) as exc:
            raise ReleaseCacheError(f"无效的 ZIP 压缩包: {exc}") from exc

        return self._validate_staged(staging)

    def _validate_staged(
        self,
        staging: Path,
        expected_channel: Optional[str] = None,
        publication_channel: Optional[str] = None,
    ) -> Dict[str, Any]:
        manifest_path = staging / MANIFEST_NAME
        sig_path = staging / MANIFEST_SIG_NAME
        if not manifest_path.is_file():
            raise ReleaseCacheError("缺少清单文件")
        if not sig_path.is_file():
            raise ReleaseCacheError("缺少签名文件")
        if self.public_key is None:
            raise ReleaseCacheDisabled("缺少更新公钥，无法验证 LAN 清单签名")
        try:
            manifest = UpdateManifest.from_bytes(
                manifest_path.read_bytes(), sig_path.read_bytes(), self.public_key
            )
        except (InvalidManifest, OSError) as exc:
            raise ReleaseCacheError(f"清单签名或格式无效: {exc}") from exc
        if expected_channel == "stable" and manifest.channel != "stable":
            raise ReleaseCacheError("stable 通道不能发布预发布清单")
        if expected_channel not in (None, "stable", "beta"):
            raise ReleaseCacheError("更新通道无效")

        asset = manifest.asset_for("windows-x86_64")
        installer_path = staging / asset.filename
        if not installer_path.is_file():
            raise ReleaseCacheError(f"缺少安装包: {asset.filename}")
        if installer_path.stat().st_size != asset.size:
            raise ReleaseCacheError("安装包大小与清单不匹配")
        if _sha256_file(installer_path) != asset.sha256:
            raise ReleaseCacheError("安装包 SHA-256 与清单不匹配")

        expected_names = {MANIFEST_NAME, MANIFEST_SIG_NAME, asset.filename}
        actual_names = {p.name for p in staging.iterdir() if p.is_file()}
        extra = actual_names - expected_names
        if extra:
            raise ReleaseCacheError(f"发布目录包含多余文件: {', '.join(sorted(extra))}")
        try:
            Version(manifest.version)
        except InvalidVersion as exc:
            raise ReleaseCacheError(f"清单版本不是有效 SemVer: {exc}") from exc

        return {
            "staging_dir": staging,
            "version": manifest.version,
            "manifest": manifest,
            "publication_channel": publication_channel or manifest.channel,
            "files": {
                MANIFEST_NAME: manifest_path,
                MANIFEST_SIG_NAME: sig_path,
                asset.filename: installer_path,
            },
        }

    def validate_files(
        self,
        manifest_path: Path,
        signature_path: Path,
        installer_path: Path,
        channel: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Validate three already-downloaded files using the normal publish path."""
        if not _is_safe_name(installer_path.name):
            raise ReleaseCacheError("安装包文件名不安全")
        staging = Path(tempfile.mkdtemp(prefix="release-cache-stage-", dir=str(self.cache_dir)))
        try:
            shutil.copy2(manifest_path, staging / MANIFEST_NAME)
            shutil.copy2(signature_path, staging / MANIFEST_SIG_NAME)
            shutil.copy2(installer_path, staging / installer_path.name)
            return self._validate_staged(staging, expected_channel=channel, publication_channel=channel)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    def publish(self, validated: Dict[str, Any]) -> str:
        """Atomically publish a validated bundle into the cache directory.

        The complete file set is assembled in a **publish-staging** directory
        inside ``cache_dir`` (same filesystem).  Only when every file is in
        place do we swap the staging directory into the final version slot
        via ``os.replace`` (atomic rename).  The previously published version
        directory is kept intact until the replacement is fully ready, and is
        removed only after the swap succeeds.

        This guarantees readers never see a partially populated version
        directory, even during concurrent reads or replacement of an existing
        version.

        Returns the published version string.
        """
        staging: Path = validated["staging_dir"]
        version: str = validated["version"]
        files: Dict[str, Path] = validated["files"]

        target = self._version_dir(version)
        publish_staging = Path(tempfile.mkdtemp(prefix=f".publish-staging-{version}-", dir=str(self.cache_dir)))
        shutil.rmtree(publish_staging)
        _PUBLISH_LOCK.acquire()
        try:
            # 1. Build the complete version directory in publish_staging.
            publish_staging.mkdir(parents=True, exist_ok=False)
            for logical_name, source in files.items():
                if not _is_safe_name(logical_name):
                    raise ReleaseCacheError(f"不安全的文件名: {logical_name}")
                shutil.copy2(source, publish_staging / logical_name)

            # 2. Swap the complete staging directory into place.
            backup: Optional[Path] = None
            if target.exists():
                # Move the existing version aside (rename to a unique backup).
                backup = self.cache_dir / f".old-{version}-{os.getpid()}"
                if backup.exists():
                    shutil.rmtree(backup, ignore_errors=True)
                os.replace(target, backup)

            try:
                os.replace(publish_staging, target)
                # Update pointers only after the complete directory exists.  If
                # writing the index fails, restore the previous directory too.
                index = self.read_index()
                publication_channel = validated.get("publication_channel", validated["manifest"].channel)
                mappings = index.get("version_channels", {})
                mapped_channels = set(mappings.get(version, []))
                mapped_channels.add(publication_channel)
                mappings[version] = sorted(mapped_channels)
                index["version_channels"] = mappings
                self._prune(index)
            except Exception:
                if target.exists():
                    shutil.rmtree(target, ignore_errors=True)
                if backup is not None and backup.exists():
                    os.replace(backup, target)
                raise

            if backup is not None and backup.exists():
                shutil.rmtree(backup, ignore_errors=True)
            return version
        finally:
            shutil.rmtree(staging, ignore_errors=True)
            shutil.rmtree(publish_staging, ignore_errors=True)
            _PUBLISH_LOCK.release()

    def publish_bundle(self, bundle_path: Path) -> str:
        """Validate and publish in one call.  Returns the version string."""
        return self.publish(self.validate_bundle(bundle_path))

    def publish_files(
        self,
        manifest_path: Path,
        signature_path: Path,
        installer_path: Path,
        channel: Optional[str] = None,
    ) -> str:
        """Validate and atomically publish a manifest, signature and complete EXE."""
        return self.publish(self.validate_files(manifest_path, signature_path, installer_path, channel))

    def _prune(self, index: Optional[Dict[str, Any]] = None) -> None:
        """Apply the global retention limit while preferring each channel's latest."""
        index = index or self.read_index()
        mappings: Dict[str, List[str]] = index.get("version_channels", {})
        candidates = [version for version, channels in mappings.items() if channels]
        candidates.sort(key=Version, reverse=True)
        required = set()
        for channel in CHANNELS:
            channel_versions = [version for version in candidates if channel in mappings[version]]
            if channel_versions:
                required.add(channel_versions[0])
        retained = sorted(required, key=Version, reverse=True)[:self.retention]
        for version in candidates:
            if len(retained) >= self.retention:
                break
            if version not in retained:
                retained.append(version)
        retained.sort(key=Version, reverse=True)
        removed = (set(index.get("versions", [])) | set(mappings)) - set(retained)
        for old in removed:
            mappings.pop(old, None)
        channel_latest = {}
        for channel in CHANNELS:
            available = [version for version in retained if channel in mappings.get(version, [])]
            channel_latest[channel] = available[0] if available else None
        index.update({
            "latest_version": retained[0] if retained else None,
            "versions": retained,
            "channels": channel_latest,
            "version_channels": mappings,
        })
        # Publish the new index before deleting files that it no longer references.
        self._write_index(index)
        for old in removed:
            shutil.rmtree(self._version_dir(old), ignore_errors=True)
