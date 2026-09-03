"""Durable and validated update state transitions."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Optional


ALLOWED_TRANSITIONS = {
    "idle": {"checking"},
    "checking": {"idle", "available"},
    "available": {"downloading", "idle"},
    "downloading": {"verified", "available", "idle"},
    "verified": {"waiting-for-idle", "installing", "idle"},
    "waiting-for-idle": {"installing", "idle"},
    "installing": {"verifying-startup", "rolled-back"},
    "verifying-startup": {"succeeded", "rolled-back"},
    "succeeded": {"idle"},
    "rolled-back": {"idle"},
}


@dataclass(frozen=True)
class UpdateResult:
    state: str
    installer: Optional[Path] = None
    version: Optional[str] = None
    error: Optional[str] = None


class UpdateStateStore:
    def __init__(self, directory: Path):
        self.directory = directory
        self.path = directory / "state.json"
        directory.mkdir(parents=True, exist_ok=True)

    def read(self) -> dict:
        if not self.path.is_file():
            return {"state": "idle"}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return value if value.get("state") in ALLOWED_TRANSITIONS else {"state": "idle"}
        except (OSError, json.JSONDecodeError):
            return {"state": "idle"}

    def transition(self, state: str, **details) -> dict:
        current = self.read().get("state", "idle")
        if state not in ALLOWED_TRANSITIONS.get(current, set()):
            raise RuntimeError(f"非法更新状态转换: {current} -> {state}")
        value = {"state": state, **details}
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, self.path)
        return value

    def set_details(self, **details) -> dict:
        """Atomically merge metadata into the current state without transitioning.

        Used for supplemental fields like ``updater_pid`` that annotate the
        current state (e.g. recording which detached updater process owns an
        ``installing`` state) without changing the state-machine position.
        The write is still atomic (tmp + os.replace).
        """
        current = self.read()
        state = current.get("state", "idle")
        if state not in ALLOWED_TRANSITIONS:
            raise RuntimeError(f"无法在非法状态上写入细节: {state}")
        value = {**current, **details}
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, self.path)
        return value
