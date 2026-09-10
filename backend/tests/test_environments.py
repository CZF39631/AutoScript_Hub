import json

import pytest

from app.models import Environment, User
from app.routers.environments import _parse_extra


@pytest.fixture(autouse=True)
def isolated_audit(fresh_db, monkeypatch):
    # Audit writes use their own session rather than the get_db dependency.
    Session, _ = fresh_db
    monkeypatch.setattr("app.services.audit.SessionLocal", Session)


def _bearer(token):
    return {"Authorization": "Bearer " + token}


def _assert_reads(client, headers, env_id, expected):
    for path in (f"/{env_id}", "/default", ""):
        response = client.get("/api/environments" + path, headers=headers)
        assert response.status_code == 200, response.text
        payload = response.json()
        if path == "":
            payload = next(item for item in payload if item["id"] == env_id)
        assert payload["id"] == env_id
        assert payload["extra_env"] == expected


def test_create_update_and_read_extra_env(client, fresh_db, op_token):
    headers = _bearer(op_token)
    extra = {"LANG": "中文", "nested": {"enabled": True}, "items": [1, None]}
    response = client.post("/api/environments", headers=headers, json={
        "name": "测试环境", "extra_env": extra, "is_default": True,
    })
    assert response.status_code == 200, response.text
    env_id = response.json()["id"]
    assert response.json()["extra_env"] == extra
    _assert_reads(client, headers, env_id, extra)

    Session, _ = fresh_db
    with Session() as db:
        stored = db.get(Environment, env_id).extra_env
        assert isinstance(stored, str)
        assert json.loads(stored) == extra

    # Updating another field must not lose existing environment variables.
    response = client.put(f"/api/environments/{env_id}", headers=headers,
                          json={"name": "重命名"})
    assert response.status_code == 200, response.text
    assert response.json()["extra_env"] == extra
    with Session() as db:
        assert db.get(Environment, env_id).extra_env == stored

    replacement = {"NEW_KEY": "更新值"}
    response = client.put(f"/api/environments/{env_id}", headers=headers,
                          json={"extra_env": replacement})
    assert response.status_code == 200, response.text
    assert response.json()["extra_env"] == replacement
    _assert_reads(client, headers, env_id, replacement)
    with Session() as db:
        assert json.loads(db.get(Environment, env_id).extra_env) == replacement

    response = client.put(f"/api/environments/{env_id}", headers=headers,
                          json={"extra_env": {}})
    assert response.status_code == 200, response.text
    assert response.json()["extra_env"] == {}
    _assert_reads(client, headers, env_id, {})
    with Session() as db:
        assert db.get(Environment, env_id).extra_env == "{}"


@pytest.mark.parametrize("stored,expected", [
    (None, None), ("{}", {}), ('{"KEY":"值"}', {"KEY": "值"}),
    ("", {}), ("{broken", {}), ("[]", {}), ('[1,"x"]', {}),
    ('"text"', {}), ("42", {}), ("true", {}), ("null", {}),
])
def test_legacy_extra_env_safe_reads_without_mutation(
    client, fresh_db, op_token, stored, expected,
):
    Session, _ = fresh_db
    with Session() as db:
        owner = db.query(User).filter_by(username="operator1").one()
        env = Environment(user_id=owner.id, name="历史环境", extra_env=stored,
                          is_default=True)
        db.add(env)
        db.commit()
        env_id = env.id
        assert _parse_extra(env).extra_env == expected
        assert env.extra_env == stored
        assert env not in db.dirty
    _assert_reads(client, _bearer(op_token), env_id, expected)
    with Session() as db:
        assert db.get(Environment, env_id).extra_env == stored


@pytest.mark.parametrize("extra", [{}, {"KEY": "value"}])
def test_parse_already_decoded_object(extra):
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    env = Environment(id=1, user_id=1, name="decoded", extra_env=extra,
                      is_default=False, created_at=now, updated_at=now)
    assert _parse_extra(env).extra_env == extra
    assert env.extra_env is extra


def test_environment_ownership_and_authentication(client, fresh_db, op_token, admin_token):
    owner_headers = _bearer(op_token)
    response = client.post("/api/environments", headers=owner_headers, json={
        "name": "私有环境", "extra_env": {"PRIVATE": "owner-only"}, "is_default": True,
    })
    assert response.status_code == 200, response.text
    env_id = response.json()["id"]
    for headers, expected_status in (({}, 401), (_bearer(admin_token), 404)):
        for method, payload in (("get", None), ("put", {"extra_env": {}}), ("delete", None)):
            kwargs = {"headers": headers}
            if payload is not None:
                kwargs["json"] = payload
            result = getattr(client, method)(f"/api/environments/{env_id}", **kwargs)
            assert result.status_code == expected_status, result.text
        result = client.get("/api/environments/default", headers=headers)
        assert result.status_code == expected_status, result.text
    assert client.get("/api/environments").status_code == 401
    assert client.post("/api/environments", json={"name": "unauthorized"}).status_code == 401
    result = client.get("/api/environments", headers=_bearer(admin_token))
    assert result.status_code == 200
    assert result.json() == []
    _assert_reads(client, owner_headers, env_id, {"PRIVATE": "owner-only"})
    Session, _ = fresh_db
    with Session() as db:
        assert json.loads(db.get(Environment, env_id).extra_env) == {"PRIVATE": "owner-only"}
