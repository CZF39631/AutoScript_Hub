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
from pathlib import Path
from typing import Any, Dict, List, Optional
from zipfile import BadZipFile, ZipFile

from packaging.version import InvalidVersion, Version

from shared.update_manifest import InvalidManifest, UpdateManifest

logger = logging.getLogger(__name__)

MANIFEST_NAME = "autoscript-hub-update.json"
MANIFEST_SIG_NAME = "autoscript-hub-update.json.sig"
INDEX_NAME = "index.json"


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
        """Return the current index, or an empty default if absent."""
        try:
            return json.loads(self._index_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {"latest_version": None, "versions": []}

    def _write_index(self, latest: Optional[str], versions: List[str]) -> None:
        data = {"latest_version": latest, "versions": versions}
        tmp = self._index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self._index_path)

    # ------------------------------------------------------------------
    # Public read helpers
    # ------------------------------------------------------------------

    def latest_version(self) -> Optional[str]:
        return self.read_index().get("latest_version")

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

    def get_file(self, version: Optional[str], filename: str) -> Optional[Path]:
        """Safely resolve a cached file path.

        Returns ``None`` if the version or file does not exist.
        Rejects traversal attempts via ``_is_safe_name``.
        """
        if not _is_safe_name(filename):
            return None
        resolved_version = version or self.latest_version()
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

        manifest_path = staging / MANIFEST_NAME
        sig_path = staging / MANIFEST_SIG_NAME
        if not manifest_path.is_file():
            raise ReleaseCacheError("压缩包缺少清单文件")
        if not sig_path.is_file():
            raise ReleaseCacheError("压缩包缺少签名文件")

        payload = manifest_path.read_bytes()
        signature = sig_path.read_bytes()

        try:
            manifest = UpdateManifest.from_bytes(payload, signature, self.public_key)
        except InvalidManifest as exc:
            raise ReleaseCacheError(f"清单签名或格式无效: {exc}") from exc

        asset = manifest.asset_for("windows-x86_64")
        installer_path = staging / asset.filename
        if not installer_path.is_file():
            raise ReleaseCacheError(f"压缩包缺少安装包: {asset.filename}")
        if installer_path.stat().st_size != asset.size:
            raise ReleaseCacheError("安装包大小与清单不匹配")
        actual_hash = _sha256_file(installer_path)
        if actual_hash != asset.sha256:
            raise ReleaseCacheError("安装包 SHA-256 与清单不匹配")

        # Reject unexpected extra files: the bundle must contain exactly the
        # manifest, its signature, and the manifest-declared installer.
        expected_names = {MANIFEST_NAME, MANIFEST_SIG_NAME, asset.filename}
        actual_names = {p.name for p in staging.iterdir() if p.is_file()}
        extra = actual_names - expected_names
        if extra:
            raise ReleaseCacheError(f"压缩包包含多余文件: {', '.join(sorted(extra))}")

        # Validate version is usable as a directory name.
        try:
            Version(manifest.version)
        except InvalidVersion as exc:
            raise ReleaseCacheError(f"清单版本不是有效 SemVer: {exc}") from exc

        files = {
            MANIFEST_NAME: manifest_path,
            MANIFEST_SIG_NAME: sig_path,
            asset.filename: installer_path,
        }
        return {
            "staging_dir": staging,
            "version": manifest.version,
            "manifest": manifest,
            "files": files,
        }

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
        # Unique sibling directory for assembling the complete file set.
        publish_staging = self.cache_dir / f".publish-staging-{version}-{os.getpid()}"

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
            except OSError:
                # The rename of staging into target failed.  Restore the
                # backup so the previous version remains visible.
                if backup is not None and backup.exists():
                    os.replace(backup, target)
                raise

            # 3. Clean up the old version directory if we swapped one out.
            if backup is not None and backup.exists():
                shutil.rmtree(backup, ignore_errors=True)

            # 4. Update the index now that a complete version directory exists.
            index = self.read_index()
            versions = [v for v in index.get("versions", []) if v != version]
            versions.append(version)
            versions.sort(key=lambda v: Version(v), reverse=True)
            self._write_index(versions[0] if versions else None, versions)

            self._prune()
            return version
        finally:
            # Always clean up both staging directories on exit.
            shutil.rmtree(staging, ignore_errors=True)
            shutil.rmtree(publish_staging, ignore_errors=True)

    def publish_bundle(self, bundle_path: Path) -> str:
        """Validate and publish in one call.  Returns the version string."""
        validated = self.validate_bundle(bundle_path)
        return self.publish(validated)

    def _prune(self) -> None:
        """Remove oldest versions exceeding the retention count."""
        index = self.read_index()
        versions: List[str] = index.get("versions", [])
        versions.sort(key=lambda v: Version(v), reverse=True)
        pruned = False
        while len(versions) > self.retention:
            old = versions.pop()
            old_dir = self._version_dir(old)
            shutil.rmtree(old_dir, ignore_errors=True)
            pruned = True
        if pruned:
            latest = versions[0] if versions else None
            self._write_index(latest, versions)
