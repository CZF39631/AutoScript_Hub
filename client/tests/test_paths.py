from pathlib import Path

from client.runtime.paths import ClientPaths
from client.runtime.python_runtime import PRIVATE_PYTHON_VERSION, private_python


def test_client_paths_live_below_local_app_data(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("AUTOSCRIPT_CLIENT_DATA_DIR", raising=False)

    paths = ClientPaths.from_environment(install_dir=tmp_path / "install")
    paths.ensure()

    assert paths.data_dir == tmp_path / "AutoScriptHub"
    assert paths.config_file == paths.config_dir / "client.json"
    for directory in paths.mutable_directories:
        assert paths.data_dir in directory.parents or directory == paths.data_dir
        assert directory.is_dir()


def test_explicit_data_root_is_supported_for_portable_testing(monkeypatch, tmp_path):
    custom = tmp_path / "custom-data"
    monkeypatch.setenv("AUTOSCRIPT_CLIENT_DATA_DIR", str(custom))

    paths = ClientPaths.from_environment(install_dir=tmp_path / "install")

    assert paths.data_dir == custom.resolve()


def test_private_python_is_owned_by_installation(tmp_path):
    paths = ClientPaths.from_environment(
        install_dir=tmp_path / "install",
        data_dir=tmp_path / "data",
    )
    executable = paths.runtime_dir / "python" / "python.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"placeholder")

    assert private_python(paths) == executable
    assert PRIVATE_PYTHON_VERSION == "3.11.9"
