from datetime import datetime, timedelta
import json
from pathlib import Path

from client.agent import main as agent


class Response:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


def _cached_script(root: Path, script_id: int):
    version = root / str(script_id) / "1"
    version.mkdir(parents=True)
    (version / "main.py").write_text(
        "def config():\n"
        f"    return {{'name': '脚本{script_id}', 'version': '1.0.0'}}\n",
        encoding="utf-8",
    )


def test_local_cache_only_exposes_last_authorized_scripts(tmp_path, monkeypatch):
    scripts = tmp_path / "scripts"
    _cached_script(scripts, 1)
    _cached_script(scripts, 2)
    manifest = tmp_path / "script_authorizations.json"
    manifest.write_text(json.dumps({
        "server_url": "http://server",
        "username": "member",
        "script_ids": [2],
        "synced_at": datetime.now().isoformat(),
    }), encoding="utf-8")
    monkeypatch.setattr(agent, "_SCRIPTS_DIR", str(scripts))
    monkeypatch.setattr(agent, "SCRIPT_AUTHORIZATIONS_FILE", str(manifest))
    monkeypatch.setattr(agent, "BACKEND_URL", "http://server")
    monkeypatch.setattr(agent, "_client_config", {"username": "member"})

    assert [item["id"] for item in agent.list_local_scripts()] == [2]
    assert agent.start_local_run({"script_id": 1}) == {
        "error": "脚本授权已失效，请联网刷新市场权限"
    }


def test_authorization_sync_is_atomic_and_scoped_to_server_and_user(tmp_path, monkeypatch):
    manifest = tmp_path / "config" / "script_authorizations.json"
    monkeypatch.setattr(agent, "SCRIPT_AUTHORIZATIONS_FILE", str(manifest))
    monkeypatch.setattr(agent, "BACKEND_URL", "http://server")
    monkeypatch.setattr(agent, "_client_config", {"username": "member"})
    monkeypatch.setattr(agent, "_token", "private-token")
    monkeypatch.setattr(agent, "_user_id", 9)
    monkeypatch.setattr(agent.requests, "get", lambda *args, **kwargs: Response([5, 3, 5]))

    assert agent._sync_script_authorizations() is True
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["server_url"] == "http://server"
    assert payload["username"] == "member"
    assert payload["script_ids"] == [3, 5]
    assert "private-token" not in manifest.read_text(encoding="utf-8")


def test_missing_or_expired_authorization_snapshot_fails_closed(tmp_path, monkeypatch):
    manifest = tmp_path / "script_authorizations.json"
    monkeypatch.setattr(agent, "SCRIPT_AUTHORIZATIONS_FILE", str(manifest))
    monkeypatch.setattr(agent, "BACKEND_URL", "http://server")
    monkeypatch.setattr(agent, "_client_config", {"username": "member"})

    assert agent._load_authorized_script_ids() == set()
    manifest.write_text(json.dumps({
        "server_url": "http://server",
        "username": "member",
        "script_ids": [1],
        "synced_at": (datetime.now() - timedelta(days=8)).isoformat(),
    }), encoding="utf-8")
    assert agent._load_authorized_script_ids() == set()


def test_login_rejection_clears_previous_authorizations(tmp_path, monkeypatch):
    manifest = tmp_path / "script_authorizations.json"
    manifest.write_text(json.dumps({
        "server_url": "http://server",
        "username": "member",
        "script_ids": [1],
        "synced_at": datetime.now().isoformat(),
    }), encoding="utf-8")
    monkeypatch.setattr(agent, "SCRIPT_AUTHORIZATIONS_FILE", str(manifest))
    monkeypatch.setattr(agent, "BACKEND_URL", "http://server")
    monkeypatch.setattr(agent, "_client_config", {"username": "member"})
    monkeypatch.setattr(agent.requests, "post", lambda *args, **kwargs: Response({}, status_code=403))

    assert agent.authenticate("member", "disabled-password") is False
    assert agent._load_authorized_script_ids() == set()


def test_explicit_auth_rejection_clears_previous_authorizations(tmp_path, monkeypatch):
    manifest = tmp_path / "script_authorizations.json"
    manifest.write_text(json.dumps({
        "server_url": "http://server",
        "username": "member",
        "script_ids": [1, 2],
        "synced_at": datetime.now().isoformat(),
    }), encoding="utf-8")
    monkeypatch.setattr(agent, "SCRIPT_AUTHORIZATIONS_FILE", str(manifest))
    monkeypatch.setattr(agent, "BACKEND_URL", "http://server")
    monkeypatch.setattr(agent, "_client_config", {"username": "member"})
    monkeypatch.setattr(agent, "_token", "expired-token")
    monkeypatch.setattr(agent, "_user_id", 9)
    monkeypatch.setattr(agent.requests, "get", lambda *args, **kwargs: Response({}, status_code=403))

    assert agent._sync_script_authorizations() is True
    assert agent._load_authorized_script_ids() == set()
