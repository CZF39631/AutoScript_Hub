"""Frozen/source-safe immutable and mutable client path ownership."""

from dataclasses import dataclass
import os
from pathlib import Path
import sys
from typing import Optional


@dataclass(frozen=True)
class ClientPaths:
    install_dir: Path
    data_dir: Path
    runtime_dir: Path
    config_dir: Path
    scripts_dir: Path
    environments_dir: Path
    logs_dir: Path
    runs_dir: Path
    updates_dir: Path
    output_dir: Path

    @classmethod
    def from_environment(
        cls,
        install_dir: Optional[os.PathLike[str] | str] = None,
        data_dir: Optional[os.PathLike[str] | str] = None,
    ) -> "ClientPaths":
        if install_dir is None:
            if getattr(sys, "frozen", False):
                install = Path(sys.executable).resolve().parent
            else:
                install = Path(__file__).resolve().parents[2]
        else:
            install = Path(install_dir).expanduser().resolve()

        configured_data = data_dir or os.environ.get("AUTOSCRIPT_CLIENT_DATA_DIR")
        if configured_data:
            root = Path(configured_data).expanduser().resolve()
        else:
            local_app_data = os.environ.get("LOCALAPPDATA")
            base = Path(local_app_data) if local_app_data else Path.home() / ".local" / "share"
            root = (base / "AutoScriptHub").resolve()

        return cls(
            install_dir=install,
            data_dir=root,
            runtime_dir=install / "runtime",
            config_dir=root / "config",
            scripts_dir=root / "scripts",
            environments_dir=root / "environments",
            logs_dir=root / "logs",
            runs_dir=root / "runs",
            updates_dir=root / "updates",
            output_dir=root / "output",
        )

    @property
    def config_file(self) -> Path:
        return self.config_dir / "client.json"

    @property
    def mutable_directories(self) -> tuple[Path, ...]:
        return (
            self.data_dir,
            self.config_dir,
            self.scripts_dir,
            self.environments_dir,
            self.logs_dir,
            self.runs_dir,
            self.updates_dir,
            self.output_dir,
        )

    def ensure(self) -> None:
        for directory in self.mutable_directories:
            directory.mkdir(parents=True, exist_ok=True)
