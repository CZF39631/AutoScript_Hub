import json

from app.routers import settings as settings_router


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
            "gitee_update_repository": "chuzifeng/auto-script_-hub",
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
        "gitee_update_repository": "chuzifeng/auto-script_-hub",
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


def test_server_update_settings_are_persistent_and_admin_only(
    client, admin_token, dev_token, op_token, monkeypatch
):
    monkeypatch.setattr(settings_router, "write_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.server_update_cache.wake_server_update_cache", lambda: None)
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    defaults = client.get("/api/settings/server-update", headers=admin_headers)
    assert defaults.status_code == 200
    assert defaults.json() == {
        "enabled": False,
        "outbound_proxy": None,
        "github_repository": "CZF39631/AutoScript_Hub",
        "interval_hours": 6,
    }
    saved = client.put(
        "/api/settings/server-update",
        headers=admin_headers,
        json={
            "enabled": True,
            "outbound_proxy": "http://proxy.example:8080",
            "github_repository": "owner/repository",
            "interval_hours": 12,
        },
    )
    assert saved.status_code == 200
    assert client.get("/api/settings/server-update", headers=admin_headers).json() == saved.json()

    for token in (dev_token, op_token):
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/api/settings/server-update", headers=headers).status_code == 403
        assert client.put(
            "/api/settings/server-update", headers=headers, json={"enabled": False}
        ).status_code == 403


def test_server_update_settings_validate_proxy_and_interval(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    invalid_proxies = [
        "socks5://proxy.example:1080",
        "http://",
        "http://proxy.example/path\nInjected: yes",
        " https://proxy.example",
    ]
    for proxy in invalid_proxies:
        response = client.put(
            "/api/settings/server-update",
            headers=headers,
            json={"outbound_proxy": proxy},
        )
        assert response.status_code == 422
    for interval in (0, 169):
        response = client.put(
            "/api/settings/server-update",
            headers=headers,
            json={"interval_hours": interval},
        )
        assert response.status_code == 422


def test_proxy_password_is_never_written_to_audit(client, admin_token, monkeypatch):
    captured = []
    monkeypatch.setattr(
        settings_router,
        "write_audit",
        lambda *args, **kwargs: captured.append((args, kwargs)),
    )
    monkeypatch.setattr("app.server_update_cache.wake_server_update_cache", lambda: None)
    response = client.put(
        "/api/settings/server-update",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"outbound_proxy": "http://proxy-user:super-secret@proxy.example:8080"},
    )
    assert response.status_code == 200
    assert captured
    assert "super-secret" not in repr(captured)
    assert "outbound_proxy" in repr(captured)
