from client.agent import updater
from client.runtime.paths import ClientPaths


def test_handoff_runs_atomic_updater_copy_outside_install_tree(tmp_path, monkeypatch):
    paths = ClientPaths.from_environment(
        install_dir=tmp_path / "install",
        data_dir=tmp_path / "data",
    )
    paths.ensure()
    paths.install_dir.mkdir(parents=True)
    source = paths.install_dir / "AutoScriptUpdater.exe"
    source.write_bytes(b"self-contained-updater")
    (paths.install_dir / "AutoScriptHub.exe").write_bytes(b"ui")
    installer = paths.updates_dir / "AutoScript-Hub-Setup-0.9.1.exe"
    installer.write_bytes(b"installer")
    calls = []
    monkeypatch.setattr(updater.subprocess, "Popen", lambda command, **kwargs: calls.append((command, kwargs)))
    monkeypatch.setattr(updater, "_detached_flags", lambda: 0)

    updater._handoff(paths, installer, "0.9.1")

    assert len(calls) == 1
    command, kwargs = calls[0]
    bootstrap = paths.updates_dir / "updater-bootstrap-0.9.1.exe"
    assert command[0] == str(bootstrap)
    assert bootstrap.read_bytes() == source.read_bytes()
    assert paths.install_dir not in bootstrap.parents
    assert kwargs["cwd"] == str(paths.updates_dir)
