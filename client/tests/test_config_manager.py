import importlib
import json
import uuid
from dataclasses import replace
from pathlib import Path


def test_default_update_source_prefers_public_gitee_mirror(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOSCRIPT_CLIENT_DATA_DIR", str(tmp_path / "data"))
    from client.ui import config_manager
    config_manager = importlib.reload(config_manager)

    config = config_manager.load_config()

    assert config["gitee_update_repository"] == "chuzifeng/auto-script_-hub"
    assert config["github_update_repository"] == "CZF39631/AutoScript_Hub"
    assert config["update_channel"] == "stable"
    assert config["pip_index_url"] == "https://pypi.tuna.tsinghua.edu.cn/simple"


def test_legacy_config_gets_standard_mode_and_stable_device_uid(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOSCRIPT_CLIENT_DATA_DIR", str(tmp_path / "data"))
    from client.ui import config_manager
    config_manager = importlib.reload(config_manager)
    path = Path(config_manager.CONFIG_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"server_url": "https://example.test"}), encoding="utf-8")

    first = config_manager.load_config()
    second = config_manager.load_config()
    config_manager.save_config({"output_dir": r"D:\results"})
    third = config_manager.load_config()
    persisted = json.loads(path.read_text(encoding="utf-8"))

    assert first["client_mode"] == "standard"
    assert second["device_uid"] == first["device_uid"]
    assert third["device_uid"] == first["device_uid"]
    assert persisted["device_uid"] == first["device_uid"]
    assert persisted["client_mode"] == "standard"
    assert str(uuid.UUID(first["device_uid"])) == first["device_uid"]
    assert not Path(str(path) + ".tmp").exists()


def test_installer_edition_overrides_saved_client_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOSCRIPT_CLIENT_DATA_DIR", str(tmp_path / "data"))
    from client.ui import config_manager
    config_manager = importlib.reload(config_manager)
    install_dir = tmp_path / "install"
    install_dir.mkdir()
    (install_dir / "client-mode.txt").write_text("managed\n", encoding="utf-8")
    monkeypatch.setattr(config_manager, "_PATHS", replace(config_manager._PATHS, install_dir=install_dir))
    config_manager.save_config({"client_mode": "standard"})

    assert config_manager.load_config()["client_mode"] == "managed"


def test_blank_saved_pip_source_uses_the_default_mirror(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOSCRIPT_CLIENT_DATA_DIR", str(tmp_path / "data"))
    from client.ui import config_manager
    config_manager = importlib.reload(config_manager)
    config_manager.save_config({"pip_index_url": ""})

    assert config_manager.load_config()["pip_index_url"] == "https://pypi.tuna.tsinghua.edu.cn/simple"


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


def test_remembered_password_is_not_written_to_client_json(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOSCRIPT_CLIENT_DATA_DIR", str(tmp_path / "data"))
    from client.ui import config_manager
    config_manager = importlib.reload(config_manager)
    remembered = {}
    monkeypatch.setattr(
        config_manager,
        "save_credentials",
        lambda server, username, password: remembered.update(
            server=server, username=username, password=password
        ),
    )
    monkeypatch.setattr(config_manager, "load_credentials", lambda *_: remembered.get("password", ""))

    config_manager.save_config({
        "server_url": "https://example.test",
        "username": "operator",
        "password": "top-secret",
        "remember_credentials": True,
        "setup_completed": True,
    })

    persisted = json.loads(Path(config_manager.CONFIG_PATH).read_text(encoding="utf-8"))
    assert "password" not in persisted
    assert persisted["remember_credentials"] is True
    assert config_manager.load_config()["password"] == "top-secret"


def test_disabling_remember_credentials_deletes_saved_password(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOSCRIPT_CLIENT_DATA_DIR", str(tmp_path / "data"))
    from client.ui import config_manager
    config_manager = importlib.reload(config_manager)
    deleted = []
    monkeypatch.setattr(config_manager, "delete_credentials", lambda server, username: deleted.append((server, username)))

    config_manager.save_config({
        "server_url": "https://example.test",
        "username": "operator",
        "password": "entered-password",
        "remember_credentials": False,
    })

    assert deleted == [("https://example.test", "operator")]
    assert "password" not in json.loads(Path(config_manager.CONFIG_PATH).read_text(encoding="utf-8"))


def test_plaintext_password_is_migrated_on_load(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOSCRIPT_CLIENT_DATA_DIR", str(tmp_path / "data"))
    from client.ui import config_manager
    config_manager = importlib.reload(config_manager)
    path = Path(config_manager.CONFIG_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "server_url": "https://example.test",
        "username": "legacy-user",
        "password": "legacy-secret",
    }), encoding="utf-8")
    remembered = {}
    monkeypatch.setattr(
        config_manager,
        "save_credentials",
        lambda server, username, password: remembered.update(password=password),
    )
    monkeypatch.setattr(config_manager, "load_credentials", lambda *_: remembered.get("password", ""))

    loaded = config_manager.load_config()

    assert loaded["password"] == "legacy-secret"
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert "password" not in persisted
    assert persisted["remember_credentials"] is True


def test_legacy_plaintext_config_is_removed_after_secure_migration(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOSCRIPT_CLIENT_DATA_DIR", str(tmp_path / "data"))
    from client.ui import config_manager
    config_manager = importlib.reload(config_manager)
    legacy = tmp_path / "client_config.json"
    legacy.write_text(json.dumps({
        "server_url": "https://example.test",
        "username": "legacy-user",
        "password": "legacy-secret",
    }), encoding="utf-8")
    monkeypatch.setattr(config_manager, "LEGACY_CONFIG_PATH", str(legacy))
    remembered = {}
    monkeypatch.setattr(
        config_manager,
        "save_credentials",
        lambda server, username, password: remembered.update(password=password),
    )
    monkeypatch.setattr(config_manager, "load_credentials", lambda *_: remembered.get("password", ""))

    assert config_manager.load_config()["password"] == "legacy-secret"
    assert not legacy.exists()
    assert "password" not in json.loads(Path(config_manager.CONFIG_PATH).read_text(encoding="utf-8"))
