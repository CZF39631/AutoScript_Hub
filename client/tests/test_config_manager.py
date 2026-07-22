import importlib
from pathlib import Path


def test_config_manager_uses_mutable_client_data_root(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOSCRIPT_CLIENT_DATA_DIR", str(tmp_path / "data"))
    from client.ui import config_manager
    config_manager = importlib.reload(config_manager)

    config_manager.save_config({"server_url": "http://192.168.1.10:8000"})

    assert Path(config_manager.CONFIG_PATH) == tmp_path / "data" / "config" / "client.json"
    assert config_manager.load_config()["server_url"] == "http://192.168.1.10:8000"
    assert not Path(str(config_manager.CONFIG_PATH) + ".tmp").exists()


def test_saved_config_cannot_override_the_embedded_client_version(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOSCRIPT_CLIENT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUTOSCRIPT_VERSION", "0.9.7")
    from client.ui import config_manager
    config_manager = importlib.reload(config_manager)
    config_manager.save_config({"version": "0.0.1", "setup_completed": True})

    assert config_manager.load_config()["version"] == "0.9.7"
