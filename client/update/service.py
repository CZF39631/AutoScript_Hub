"""Signed manifest check, mirrored download, and installer handoff state machine."""

import base64
import hashlib
import os
from pathlib import Path
import time
from typing import Callable, Iterable

from packaging.version import InvalidVersion, Version

from client.runtime.paths import ClientPaths
from client.update.download import download_verified_file, sha256_file
from client.update.sources import http_get_bytes
from client.update.state import UpdateResult, UpdateStateStore
from shared.update_manifest import UpdateManifest


def _default_is_pid_alive(pid: int) -> bool:
    """Best-effort cross-platform process-liveness check."""
    if pid <= 0:
        return False
    try:
        if os.name == "nt":
            import ctypes

            kernel32 = getattr(ctypes, "windll").kernel32
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                return False
            kernel32.CloseHandle(handle)
            return True
        else:
            os.kill(pid, 0)
            return True
    except OSError:
        return False


class UpdateService:
    def __init__(
        self,
        paths: ClientPaths,
        current_version: str,
        public_key: bytes,
        sources: Iterable,
        expected_channel: str = "beta",
        http_get: Callable[[str], bytes] = http_get_bytes,
        runtime_is_idle: Callable[[], bool] = lambda: True,
        handoff: Callable[[Path, str], None] | None = None,
        is_pid_alive: Callable[[int], bool] | None = None,
        http_download: Callable[[str, Path, int, str], None] | None = None,
    ):
        paths.ensure()
        self.paths = paths
        self.current_version = current_version
        self.public_key = public_key
        self.sources = list(sources)
        if expected_channel not in {"beta", "stable"}:
            raise ValueError("更新通道必须是 beta 或 stable")
        self.expected_channel = expected_channel
        self.http_get = http_get
        self.http_download = http_download or (
            download_verified_file if http_get is http_get_bytes else self._download_with_legacy_get
        )
        self.runtime_is_idle = runtime_is_idle
        self.handoff = handoff
        self.is_pid_alive = is_pid_alive or _default_is_pid_alive
        self.store = UpdateStateStore(paths.updates_dir)
        self.manifest = None
        self.installer = None
        self.pending_version = None
        self._manifest_payload: bytes | None = None
        self._manifest_signature: bytes | None = None
        self._recover_discovered_update()
        self._recover_staged_update()

    def _recover_discovered_update(self) -> None:
        state = self.store.read()
        if state.get("state") not in {"available", "downloading"}:
            return
        try:
            payload = base64.b64decode(state["manifest_payload_b64"], validate=True)
            signature = base64.b64decode(state["manifest_signature_b64"], validate=True)
            manifest = UpdateManifest.from_bytes(payload, signature, self.public_key)
            if manifest.version != state.get("version") or not manifest.is_newer_than(self.current_version):
                raise ValueError("缓存的更新版本无效")
            channel_matches = (
                manifest.channel == self.expected_channel
                or (self.expected_channel == "beta" and manifest.channel == "stable")
            )
            if not channel_matches:
                raise ValueError("缓存的更新通道不匹配")
            manifest.asset_for("windows-x86_64")
            self.manifest = manifest
            self.pending_version = manifest.version
            self._manifest_payload = payload
            self._manifest_signature = signature
            if state.get("state") == "downloading":
                self.store.transition(
                    "available",
                    version=manifest.version,
                    error="上次下载被中断，可继续复用已校验的分卷",
                    **self._manifest_cache(payload, signature),
                )
        except (KeyError, ValueError, TypeError):
            self.store.transition("idle", error="无法恢复已发现的更新，请重新检查")

    def _download_with_legacy_get(self, url: str, destination: Path, size: int, digest: str) -> None:
        """Compatibility adapter for callers that inject the former bytes API."""
        temporary = destination.with_name(destination.name + ".download")
        last_error = None
        for attempt in range(3):
            try:
                payload = self.http_get(url)
                if len(payload) != size or hashlib.sha256(payload).hexdigest() != digest:
                    raise ValueError("下载文件长度或 SHA-256 不匹配")
                with temporary.open("wb") as output:
                    for offset in range(0, len(payload), 1024 * 1024):
                        output.write(payload[offset:offset + 1024 * 1024])
                os.replace(temporary, destination)
                return
            except Exception as exc:
                last_error = exc
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass
                if attempt < 2:
                    time.sleep(0.01)
        raise RuntimeError(f"下载失败（已重试 3 次）: {last_error}") from last_error

    @staticmethod
    def _manifest_cache(payload: bytes, signature: bytes) -> dict:
        return {
            "manifest_payload_b64": base64.b64encode(payload).decode("ascii"),
            "manifest_signature_b64": base64.b64encode(signature).decode("ascii"),
        }

    def _recover_staged_update(self) -> None:
        state = self.store.read()
        if state.get("state") not in {"verified", "waiting-for-idle"}:
            return
        try:
            installer = Path(state["installer"])
            expected_size = int(state["size"])
            expected_hash = state["sha256"]
            if not installer.is_file() or installer.stat().st_size != expected_size:
                raise ValueError("已暂存安装包缺失或长度不匹配")
            if sha256_file(installer) != expected_hash:
                raise ValueError("已暂存安装包哈希不匹配")
            self.installer = installer
            self.pending_version = state["version"]
        except (KeyError, OSError, TypeError, ValueError):
            self.store.transition("idle", error="无法恢复已暂存更新，请重新下载")

    def _should_recover_installing(self, persisted: dict) -> bool:
        """Decide whether a persisted *installing* state is stale and safe to recover.

        Recovery conditions (never introduces ``installing -> idle`` directly;
        the caller drives ``installing -> rolled-back -> idle``):
        - ``updater_pid`` is recorded but that PID is no longer alive.
        - ``updater_pid`` is recorded but corrupt (non-integer).
        - Legacy state with **no** ``updater_pid`` whose target version is
          strictly older than the running client version.

        Conservative non-recovery:
        - ``updater_pid`` is alive (live detached updater owns the state).
        - Legacy state with no ``updater_pid`` whose version is equal or newer
          than current — could be a live updater that has not yet persisted
          its PID.
        """
        updater_pid = persisted.get("updater_pid")
        if updater_pid is not None:
            try:
                pid = int(updater_pid)
            except (TypeError, ValueError):
                return True
            if pid > 0 and self.is_pid_alive(pid):
                return False
            return True
        target_version = persisted.get("version")
        if target_version is not None:
            try:
                return Version(target_version) < Version(self.current_version)
            except InvalidVersion:
                pass
        return False

    def check(self) -> UpdateResult:
        persisted = self.store.read()
        current_state = persisted["state"]
        cached_manifest = self.manifest if current_state == "available" else None
        cached_details = {
            key: persisted[key]
            for key in ("manifest_payload_b64", "manifest_signature_b64")
            if key in persisted
        }
        if current_state == "installing" and self._should_recover_installing(persisted):
            self.store.transition(
                "rolled-back",
                error="检测到陈旧的安装中状态，已自动恢复",
            )
            self.store.transition("idle")
            current_state = "idle"
        if current_state in {"installing", "verifying-startup"}:
            return UpdateResult(current_state, version=persisted.get("version"))
        if current_state in {"verified", "waiting-for-idle"} and self.installer is not None:
            return UpdateResult(current_state, installer=self.installer, version=self.pending_version)
        if current_state in {"succeeded", "rolled-back"}:
            self.store.transition("idle")
            current_state = "idle"
        if current_state != "idle":
            self.store.transition("idle")
        self.store.transition("checking")
        errors = []
        matched_manifests = []
        candidates = []
        for source in self.sources:
            try:
                payload, signature = source.fetch()
                manifest = UpdateManifest.from_bytes(payload, signature, self.public_key)
                channel_matches = (
                    manifest.channel == self.expected_channel
                    or (self.expected_channel == "beta" and manifest.channel == "stable")
                )
                if not channel_matches:
                    raise RuntimeError(
                        f"更新通道不匹配: 期望 {self.expected_channel}，收到 {manifest.channel}"
                    )
                manifest.asset_for("windows-x86_64")
                matched_manifests.append(manifest)
                if manifest.is_newer_than(self.current_version):
                    if not manifest.supports(self.current_version):
                        raise RuntimeError("当前客户端低于该更新允许的最低版本")
                    candidates.append((manifest, payload, signature))
            except Exception as exc:
                errors.append(str(exc))
        if candidates:
            manifest, payload, signature = max(
                candidates,
                key=lambda item: Version(item[0].version),
            )
            self.manifest = manifest
            self.pending_version = manifest.version
            self._manifest_payload = payload
            self._manifest_signature = signature
            self.store.transition(
                "available",
                version=manifest.version,
                **self._manifest_cache(payload, signature),
            )
            return UpdateResult("available", version=manifest.version)
        error = "; ".join(errors) if not matched_manifests else ""
        if cached_manifest is not None and not matched_manifests:
            self.manifest = cached_manifest
            self.pending_version = cached_manifest.version
            self.store.transition(
                "available",
                version=cached_manifest.version,
                last_check_error=error,
                **cached_details,
            )
            return UpdateResult("available", version=cached_manifest.version)
        version = (
            max(matched_manifests, key=lambda item: Version(item.version)).version
            if matched_manifests
            else None
        )
        self.store.transition("idle", version=version, error=error)
        return UpdateResult("idle", version=version, error=error)

    def _cached_manifest_details(self) -> dict:
        if self._manifest_payload is None or self._manifest_signature is None:
            raise RuntimeError("缺少已验证的更新清单缓存")
        return self._manifest_cache(self._manifest_payload, self._manifest_signature)

    @staticmethod
    def _valid_file(path: Path, size: int, digest: str) -> bool:
        try:
            return path.is_file() and path.stat().st_size == size and sha256_file(path) == digest
        except OSError:
            return False

    def _download_from_urls(self, urls, destination: Path, size: int, digest: str) -> None:
        errors = []
        for url in urls:
            try:
                self.http_download(url, destination, size, digest)
                if not self._valid_file(destination, size, digest):
                    try:
                        destination.unlink()
                    except FileNotFoundError:
                        pass
                    raise ValueError("下载器返回的文件长度或 SHA-256 不匹配")
                return
            except Exception as exc:
                errors.append(f"{url}: {exc}")
        raise RuntimeError("; ".join(errors))

    def _download_parts(self, asset) -> Path:
        cache = self.paths.updates_dir / f"parts-{asset.sha256[:16]}"
        cache.mkdir(parents=True, exist_ok=True)
        completed = []
        for part in asset.parts:
            path = cache / part.filename
            if not self._valid_file(path, part.size, part.sha256):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
                self._download_from_urls(part.urls, path, part.size, part.sha256)
            completed.append(path)

        installer = self.paths.updates_dir / asset.filename
        temporary = installer.with_name(installer.name + ".merge")
        digest = hashlib.sha256()
        total = 0
        try:
            with temporary.open("wb") as output:
                for path in completed:
                    with path.open("rb") as source:
                        for chunk in iter(lambda: source.read(1024 * 1024), b""):
                            output.write(chunk)
                            digest.update(chunk)
                            total += len(chunk)
            if total != asset.size or digest.hexdigest() != asset.sha256:
                raise ValueError("分卷合并后的安装包长度或 SHA-256 不匹配")
            os.replace(temporary, installer)
            return installer
        except Exception:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            raise

    def download(self) -> UpdateResult:
        if self.manifest is None:
            raise RuntimeError("尚未检查到可用更新")
        cache_details = self._cached_manifest_details()
        self.store.transition(
            "downloading",
            version=self.manifest.version,
            **cache_details,
        )
        asset = self.manifest.asset_for("windows-x86_64")
        errors = []
        installer = None
        if asset.parts:
            try:
                installer = self._download_parts(asset)
            except Exception as exc:
                errors.append(f"分卷下载失败: {exc}")
        if installer is None:
            try:
                self._download_from_urls(
                    asset.urls,
                    self.paths.updates_dir / asset.filename,
                    asset.size,
                    asset.sha256,
                )
                installer = self.paths.updates_dir / asset.filename
            except Exception as exc:
                errors.append(f"完整安装包下载失败: {exc}")
        if installer is not None:
            self.installer = installer
            self.pending_version = self.manifest.version
            self.store.transition(
                "verified",
                version=self.manifest.version,
                installer=str(installer),
                size=asset.size,
                sha256=asset.sha256,
            )
            return UpdateResult("verified", installer=installer, version=self.manifest.version)

        error = "; ".join(errors)
        self.store.transition(
            "available",
            version=self.manifest.version,
            error=error,
            **cache_details,
        )
        return UpdateResult("available", version=self.manifest.version, error=error)

    def stage(self) -> UpdateResult:
        return self.download()

    def request_install(self) -> UpdateResult:
        if self.pending_version is None or self.installer is None:
            raise RuntimeError("没有已验证的安装包")
        if not self.runtime_is_idle():
            state = self.store.read()
            if state.get("state") != "waiting-for-idle":
                self.store.transition(
                    "waiting-for-idle",
                    version=self.pending_version,
                    installer=str(self.installer),
                    size=state.get("size"),
                    sha256=state.get("sha256"),
                )
            return UpdateResult("waiting-for-idle", self.installer, self.pending_version)
        current = self.store.read()["state"]
        if current not in {"verified", "waiting-for-idle"}:
            raise RuntimeError(f"当前状态不能安装: {current}")
        self.store.transition("installing", version=self.pending_version, installer=str(self.installer))
        if self.handoff:
            try:
                self.handoff(self.installer, self.pending_version)
            except Exception:
                self.store.transition("rolled-back", error="安装器启动失败，已回退到可检查状态")
                raise
        return UpdateResult("installing", self.installer, self.pending_version)
