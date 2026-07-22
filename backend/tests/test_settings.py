import json


def test_user_settings_do_not_mutate_server_client_config(
    client, op_token, tmp_path, monkeypatch
):
    server_client_config = tmp_path / "client_config.json"
    server_client_config.write_text(
        json.dumps({"username": "server-local", "password": "keep"}),
        encoding="utf-8",
    )
    headers = {"Authorization": f"Bearer {op_token}"}

    saved = client.put(
        "/api/settings",
        json={
            "output_dir": r"D:\results",
            "browser_debug_port": 9333,
            "pip_index_url": "https://pypi.tuna.tsinghua.edu.cn/simple",
            "github_update_repository": "CZF39631/AutoScript_Hub",
            "update_channel": "beta",
            "update_manifest_urls": ["http://192.168.1.106:8080/autoscript-hub-update.json"],
        },
        headers=headers,
    )
    assert saved.status_code == 200
    assert json.loads(server_client_config.read_text(encoding="utf-8")) == {
        "username": "server-local",
        "password": "keep",
    }

    fetched = client.get("/api/settings", headers=headers)
    assert fetched.json() == {
        "output_dir": r"D:\results",
        "browser_debug_port": 9333,
        "pip_index_url": "https://pypi.tuna.tsinghua.edu.cn/simple",
        "github_update_repository": "CZF39631/AutoScript_Hub",
        "update_channel": "beta",
        "update_manifest_urls": ["http://192.168.1.106:8080/autoscript-hub-update.json"],
    }

    reset = client.delete("/api/settings", headers=headers)
    assert reset.status_code == 200
    assert server_client_config.is_file()


def test_obsolete_source_zip_update_endpoints_are_not_exposed(client):
    assert client.get("/api/agent/check-update?version=0.9.0").status_code == 404
    assert client.get("/api/agent/download/0.9.1").status_code == 404
