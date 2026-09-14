import json

import pytest

from app.models import Issue, Run, Script, ServerSettings, User
from app.services.issue_diagnostics import MAX_LOG_BYTES
from shared.diagnostics import REDACTED


def headers(token):
    return {"Authorization": "Bearer " + token}


@pytest.fixture
def diagnostics(client, fresh_db, op_token, tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.LOGS_DIR", str(tmp_path))
    monkeypatch.setattr("app.routers.issues.write_audit", lambda *a, **k: None)
    monkeypatch.setattr("app.routers.settings.write_audit", lambda *a, **k: None)
    Session, _ = fresh_db
    with Session() as db:
        owner = db.query(User).filter(User.username == "operator1").one()
        script = Script(name="diagnostics", type="py", latest_version=9, status="active",
                        created_by=owner.id, updated_by=owner.id)
        db.add(script)
        db.flush()
        run = Run(script_id=script.id, script_version=2, user_id=owner.id, status="failed",
                  params=json.dumps({"password": "private-value", "count": 3}),
                  error_msg="failed: private-value")
        db.add(run)
        db.commit()
        run_id = run.id
    path = tmp_path / f"{run_id}.log"
    path.write_text("before\npassword=private-value\n", encoding="utf-8")
    return run_id, path, headers(op_token)


def create(client, diagnostics, **extra):
    run_id, _, auth = diagnostics
    return client.post("/api/issues", headers=auth,
                       json={"run_id": run_id, "title": "failure", "include_run_summary": True,
                             "include_run_log": True, "diagnostics_consent": True, **extra})


def test_snapshot_survives_log_removal_and_pins_executed_version(client, diagnostics, fresh_db):
    response = create(client, diagnostics, description="private-value")
    assert response.status_code == 200
    issue = response.json()
    assert issue["script_version"] == 2
    assert issue["log_snapshot_available"] is True
    assert "private-value" not in response.text
    assert json.loads(issue["run_params"])["count"] == 3
    _, path, auth = diagnostics
    path.unlink()
    log = client.get(f"/api/issues/{issue['id']}/log", headers=auth).json()["log"]
    assert "before" in log and "private-value" not in log
    Session, _ = fresh_db
    with Session() as db:
        stored = db.get(Issue, issue["id"])
        assert "private-value" not in stored.log_snapshot
        assert stored.description == REDACTED


def test_empty_snapshot_does_not_fall_back_to_future_log(client, diagnostics):
    _, path, auth = diagnostics
    path.unlink()
    issue = create(client, diagnostics).json()
    path.write_text("future log", encoding="utf-8")
    assert client.get(f"/api/issues/{issue['id']}/log", headers=auth).json() == {"log": ""}


def test_legacy_log_is_bounded_and_redacted(client, diagnostics, fresh_db):
    run_id, path, auth = diagnostics
    Session, _ = fresh_db
    with Session() as db:
        run = db.get(Run, run_id)
        issue = Issue(run_id=run_id, script_id=run.script_id, user_id=run.user_id, title="legacy")
        db.add(issue)
        db.commit()
        issue_id = issue.id
    path.write_text("x" * (MAX_LOG_BYTES * 2) + "\npassword=private-value\nlast line", encoding="utf-8")
    response = client.get(f"/api/issues/{issue_id}/log", headers=auth)
    assert response.status_code == 200
    log = response.json()["log"]
    assert len(log.encode("utf-8")) <= MAX_LOG_BYTES
    assert "private-value" not in log and "last line" in log


def test_policy_admin_only_requires_risk_confirmation(client, diagnostics, admin_token, dev_token):
    _, _, auth = diagnostics
    for unauthorized in (auth, headers(dev_token)):
        assert client.get("/api/settings/diagnostics", headers=unauthorized).status_code == 403
        assert client.put("/api/settings/diagnostics", headers=unauthorized, json={"enabled": False}).status_code == 403
    admin = headers(admin_token)
    assert client.get("/api/settings/diagnostics", headers=admin).json()["enabled"] is True
    assert client.put("/api/settings/diagnostics", headers=admin, json={"enabled": False}).status_code == 409
    response = client.put("/api/settings/diagnostics", headers=admin,
                          json={"enabled": False, "acknowledge_risk": True})
    assert response.status_code == 200 and response.json()["enabled"] is False
    assert "acknowledge_risk" not in response.json()
    issue = create(client, diagnostics).json()
    assert json.loads(issue["run_params"])["password"] == "private-value"
    assert "private-value" in client.get(f"/api/issues/{issue['id']}/log", headers=auth).json()["log"]


def test_sections_custom_fields_and_irreversible_snapshot(client, diagnostics, admin_token):
    admin = headers(admin_token)
    first = create(client, diagnostics).json()
    response = client.put("/api/settings/diagnostics", headers=admin,
                          json={"redact_logs": False, "custom_sensitive_fields": ["count"], "acknowledge_risk": True})
    assert response.status_code == 200
    second = create(client, diagnostics).json()
    assert json.loads(second["run_params"])["count"] == REDACTED
    assert "private-value" not in second["error_msg"]
    auth = diagnostics[2]
    assert "private-value" in client.get(f"/api/issues/{second['id']}/log", headers=auth).json()["log"]
    assert "private-value" not in client.get(f"/api/issues/{first['id']}/log", headers=auth).json()["log"]
    # 重新开启保护时，已存原文的快照在读取时也受当前策略控制。
    assert client.put("/api/settings/diagnostics", headers=admin, json={"custom_sensitive_fields": ["count"]}).status_code == 200
    assert "private-value" not in client.get(f"/api/issues/{second['id']}/log", headers=auth).json()["log"]


def test_invalid_policy_fails_closed_and_client_cannot_override(client, diagnostics, fresh_db, admin_token):
    admin = headers(admin_token)
    for payload in ({"enabled": "false"}, {"custom_sensitive_fields": ["\n"]}, {"unexpected": True}):
        assert client.put("/api/settings/diagnostics", headers=admin, json=payload).status_code == 422
    Session, _ = fresh_db
    with Session() as db:
        db.add(ServerSettings(id=1, diagnostic_policy_json='{"enabled":"false"}'))
        db.commit()
    assert create(client, diagnostics, enabled=False).status_code == 422
    response = create(client, diagnostics)
    assert response.status_code == 200 and "private-value" not in response.text


def test_disabling_redaction_never_bypasses_log_authorization_or_size_limit(client, diagnostics, admin_token):
    admin = headers(admin_token)
    assert client.put("/api/settings/diagnostics", headers=admin,
                      json={"enabled": False, "acknowledge_risk": True}).status_code == 200
    run_id, path, operator = diagnostics
    path.write_text("large line\n" * 20000, encoding="utf-8")
    issue = client.post("/api/issues", headers=admin,
                        json={"run_id": run_id, "title": "admin report", "include_run_summary": True,
                              "include_run_log": True, "diagnostics_consent": True}).json()
    assert client.get(f"/api/issues/{issue['id']}/log", headers=operator).status_code == 404
    log = client.get(f"/api/issues/{issue['id']}/log", headers=admin).json()["log"]
    assert len(log.encode("utf-8")) <= MAX_LOG_BYTES


def test_policy_audit_records_names_not_custom_values(client, diagnostics, admin_token, monkeypatch):
    records = []
    monkeypatch.setattr("app.routers.settings.write_audit", lambda *a, **k: records.append((a, k)))
    admin = headers(admin_token)
    response = client.put("/api/settings/diagnostics", headers=admin,
                          json={"custom_sensitive_fields": ["privateFieldName"]})
    assert response.status_code == 200
    assert "privateFieldName" not in repr(records)
    assert "custom_sensitive_fields" in repr(records)
    assert client.get("/api/settings/diagnostics", headers=admin).json() == response.json()
    assert client.put("/api/settings/diagnostics", headers=admin, json={}).status_code == 409


def test_policy_concurrent_change_is_not_overwritten(client, diagnostics, fresh_db, admin_token, monkeypatch):
    from app.routers import settings
    original_load = settings.load_diagnostic_policy
    Session, _ = fresh_db

    def concurrent_change(db):
        previous = original_load(db)
        with Session() as other:
            row = other.get(ServerSettings, 1)
            row.diagnostic_policy_json = '{"custom_sensitive_fields":["protectedField"]}'
            other.commit()
        return previous

    monkeypatch.setattr(settings, "load_diagnostic_policy", concurrent_change)
    response = client.put("/api/settings/diagnostics", headers=headers(admin_token),
                          json={"redact_params": False, "acknowledge_risk": True})
    assert response.status_code == 409
    with Session() as db:
        assert "protectedField" in db.get(ServerSettings, 1).diagnostic_policy_json


def test_deleted_run_and_oversized_issue_are_rejected(client, diagnostics, fresh_db):
    invalid_title = create(client, diagnostics, title="x" * 201)
    assert invalid_title.status_code == 422
    assert isinstance(invalid_title.json()['detail'], str)  # Legacy UI cannot render error objects.
    assert create(client, diagnostics, description="x" * 8001).status_code == 422
    Session, _ = fresh_db
    with Session() as db:
        db.get(Run, diagnostics[0]).is_deleted = True
        db.commit()
    assert create(client, diagnostics).status_code == 404
