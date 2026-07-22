"""Signed manifest check, mirrored download, and installer handoff state machine."""

import hashlib
import os
from pathlib import Path
from typing import Callable, Iterable

from packaging.version import Version

from client.runtime.paths import ClientPaths
from client.update.sources import http_get_bytes
from client.update.state import UpdateResult, UpdateStateStore
from shared.update_manifest import UpdateManifest


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
        self.runtime_is_idle = runtime_is_idle
        self.handoff = handoff
        self.store = UpdateStateStore(paths.updates_dir)
        self.manifest = None
        self.installer = None
        self.pending_version = None
        self._recover_staged_update()

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
            if hashlib.sha256(installer.read_bytes()).hexdigest() != expected_hash:
                raise ValueError("已暂存安装包哈希不匹配")
            self.installer = installer
            self.pending_version = state["version"]
        except (KeyError, OSError, TypeError, ValueError):
            self.store.transition("idle", error="无法恢复已暂存更新，请重新下载")

    def check(self) -> UpdateResult:
        persisted = self.store.read()
        current_state = persisted["state"]
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
                if manifest.channel != self.expected_channel:
                    raise RuntimeError(
                        f"更新通道不匹配: 期望 {self.expected_channel}，收到 {manifest.channel}"
                    )
                manifest.asset_for("windows-x86_64")
                matched_manifests.append(manifest)
                if manifest.is_newer_than(self.current_version):
                    if not manifest.supports(self.current_version):
                        raise RuntimeError("当前客户端低于该更新允许的最低版本")
                    candidates.append(manifest)
            except Exception as exc:
                errors.append(str(exc))
        if candidates:
            manifest = max(candidates, key=lambda item: Version(item.version))
            self.manifest = manifest
            self.pending_version = manifest.version
            self.store.transition("available", version=manifest.version)
            return UpdateResult("available", version=manifest.version)
        error = "; ".join(errors)
        version = (
            max(matched_manifests, key=lambda item: Version(item.version)).version
            if matched_manifests
            else None
        )
        self.store.transition("idle", error=error)
        return UpdateResult("idle", version=version, error=error)

    def download(self) -> UpdateResult:
        if self.manifest is None:
            raise RuntimeError("尚未检查到可用更新")
        self.store.transition("downloading", version=self.manifest.version)
        asset = self.manifest.asset_for("windows-x86_64")
        errors = []
        for url in asset.urls:
            part = self.paths.updates_dir / (asset.filename + ".part")
            try:
                payload = self.http_get(url)
                if len(payload) != asset.size:
                    raise ValueError("安装包长度不匹配")
                if hashlib.sha256(payload).hexdigest() != asset.sha256:
                    raise ValueError("安装包 SHA-256 不匹配")
                part.write_bytes(payload)
                installer = self.paths.updates_dir / asset.filename
                os.replace(part, installer)
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
            except Exception as exc:
                errors.append(f"{url}: {exc}")
                try:
                    part.unlink()
                except FileNotFoundError:
                    pass
        self.store.transition("idle", error="; ".join(errors))
        return UpdateResult("idle", error="; ".join(errors))

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
            self.handoff(self.installer, self.pending_version)
        return UpdateResult("installing", self.installer, self.pending_version)
