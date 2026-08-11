import os
from pathlib import Path

from client.updater_main import (
    EXIT_ROLLED_BACK,
    installer_command,
    run_update,
    wait_for_processes,
)
from client.update.state import UpdateStateStore


class _Completed:
    def __init__(self, returncode=0):
        self.returncode = returncode


def test_installer_command_is_silent_and_non_restarting(tmp_path):
    command = installer_command(tmp_path / "setup.exe")

    assert command[0].endswith("setup.exe")
    assert command[1:] == ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"]


def test_wait_for_processes_treats_windows_kill_race_as_stopped(monkeypatch):
    monkeypatch.setattr("client.updater_main.os.kill", lambda pid, signal: (_ for _ in ()).throw(SystemError("kill race")))

    assert wait_for_processes([123], timeout_seconds=1) is True


def test_startup_timeout_reinstalls_previous_version(tmp_path):
    updates = tmp_path / "updates"
    updates.mkdir()
    installer = updates / "new.exe"
    previous = updates / "previous-installer.exe"
    ui = tmp_path / "AutoScriptHub.exe"
    for path in (installer, previous, ui):
        path.write_bytes(b"file")
    store = UpdateStateStore(updates)
    store.transition("checking")
    store.transition("available")
    store.transition("downloading")
    store.transition("verified")
    store.transition("installing")
    commands = []
    launches = []

    result = run_update(
        installer=installer,
        previous_installer=previous,
        ui_executable=ui,
        expected_version="0.9.1",
        pids=[],
        updates_dir=updates,
        run_command=lambda command: commands.append(command) or _Completed(0),
        launch=lambda command: launches.append(command),
        wait_for_startup=lambda *args, **kwargs: False,
    )

    assert result == EXIT_ROLLED_BACK
    assert commands == [installer_command(installer), installer_command(previous)]
    assert launches == [[str(ui)], [str(ui)]]
    assert store.read()["state"] == "rolled-back"


def test_run_update_persists_updater_pid(tmp_path):
    """New updater processes write their PID into the installing state."""
    updates = tmp_path / "updates"
    updates.mkdir()
    installer = updates / "new.exe"
    previous = updates / "previous-installer.exe"
    ui = tmp_path / "AutoScriptHub.exe"
    for path in (installer, previous, ui):
        path.write_bytes(b"file")
    store = UpdateStateStore(updates)
    store.transition("checking")
    store.transition("available")
    store.transition("downloading")
    store.transition("verified")
    store.transition("installing", version="0.9.1")
    assert "updater_pid" not in store.read()

    # Capture the updater_pid that is visible while the installer runs
    # (i.e. before any transition away from "installing").
    seen_pids = []

    def spy_run_command(command):
        seen_pids.append(store.read().get("updater_pid"))
        return _Completed(0)

    run_update(
        installer=installer,
        previous_installer=previous,
        ui_executable=ui,
        expected_version="0.9.1",
        pids=[],
        updates_dir=updates,
        run_command=spy_run_command,
        launch=lambda command: None,
        wait_for_startup=lambda *args, **kwargs: True,
    )

    assert seen_pids == [os.getpid()]
