"""Deletion retains history and serializes against creation of pending runs."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event

import pytest
from fastapi import HTTPException

from app.models import AuditLog, Group, Issue, Run, Script, ScriptVersion, User, UserPreset, UserScript
from app.routers import runs, scripts
from app.schemas import ExecuteRequest
from app.services.script_lifecycle import lock_script_for_lifecycle


def headers(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def seeded(fresh_db, admin_token, tmp_path):
    factory, _ = fresh_db
    artifact = tmp_path / "script.py"
    artifact.write_text("# retained artifact", encoding="utf-8")
    with factory() as db:
        admin = db.query(User).filter_by(role="admin").one()
        script = Script(name="secret-name", config_json='{"params": []}', latest_version=1)
        script.groups = db.query(Group).all()
        db.add(script)
        db.flush()
        sid = script.id
        db.add_all([
            ScriptVersion(script_id=sid, version=1, file_path=str(artifact)),
            UserScript(user_id=admin.id, script_id=sid),
            UserPreset(user_id=admin.id, script_id=sid, name="saved", values_json='{"secret":"value"}'),
        ])
        run = Run(script_id=sid, script_version=1, user_id=admin.id, status="success")
        db.add(run)
        db.flush()
        issue = Issue(script_id=sid, run_id=run.id, user_id=admin.id, title="history")
        db.add(issue)
        db.commit()
        return sid, run.id, issue.id, artifact


def test_delete_roles(client, seeded, dev_token, op_token, fresh_db):
    sid = seeded[0]
    for token in (dev_token, op_token):
        assert client.delete(f"/api/scripts/{sid}", headers=headers(token)).status_code == 403
    with fresh_db[0]() as db:
        assert not db.get(Script, sid).is_deleted
        assert db.query(AuditLog).filter_by(action="delete_script").count() == 0


def test_delete_preserves_history_and_is_idempotent(client, seeded, admin_token, fresh_db):
    sid, rid, iid, artifact = seeded
    auth = headers(admin_token)
    for _ in range(2):
        assert client.delete(f"/api/scripts/{sid}", headers=auth).status_code == 200
    assert client.delete("/api/scripts/999999", headers=auth).status_code == 404
    with fresh_db[0]() as db:
        script = db.get(Script, sid)
        assert script.is_deleted and script.groups
        assert db.get(Run, rid).status == "success"
        assert db.get(Issue, iid).title == "history"
        assert db.query(ScriptVersion).filter_by(script_id=sid).count() == 1
        assert db.query(UserScript).filter_by(script_id=sid).count() == 1
        assert db.query(UserPreset).filter_by(script_id=sid).count() == 1
        audit = db.query(AuditLog).filter_by(action="delete_script").one()
        assert audit.target_id == sid and audit.target_type == "script"
        assert audit.detail is None
    assert artifact.read_text(encoding="utf-8") == "# retained artifact"
    assert client.get(f"/api/runs/{rid}", headers=auth).status_code == 200
    issues = client.get("/api/issues", headers=auth)
    assert issues.status_code == 200
    assert any(item["id"] == iid for item in issues.json())


@pytest.mark.parametrize("status", ["pending", "running"])
@pytest.mark.parametrize("hidden", [False, True])
def test_active_runs_block_delete(client, seeded, admin_token, fresh_db, status, hidden):
    sid, rid, *_ = seeded
    with fresh_db[0]() as db:
        run = db.get(Run, rid)
        run.status, run.is_deleted = status, hidden
        db.commit()
    assert client.delete(f"/api/scripts/{sid}", headers=headers(admin_token)).status_code == 409
    with fresh_db[0]() as db:
        assert not db.get(Script, sid).is_deleted
        assert db.get(Run, rid).status == status
        assert db.query(AuditLog).filter_by(action="delete_script").count() == 0


def test_deleted_script_inaccessible(client, seeded, admin_token, dev_token, op_token):
    sid = seeded[0]
    assert client.delete(f"/api/scripts/{sid}", headers=headers(admin_token)).status_code == 200
    for token in (admin_token, dev_token, op_token):
        auth = headers(token)
        for suffix in ("", "/marketplace", "/authorized-ids"):
            response = client.get("/api/scripts" + suffix, headers=auth)
            assert response.status_code == 200
            assert response.json() == []
        if token != op_token:
            assert client.get("/api/scripts/manageable", headers=auth).json() == []
        for suffix in ("", "/download", "/versions"):
            assert client.get(f"/api/scripts/{sid}{suffix}", headers=auth).status_code == 404
        assert client.post(f"/api/scripts/{sid}/install", headers=auth).status_code == 404
        assert client.post("/api/runs/execute", json={"script_id": sid, "params": {}}, headers=auth).status_code == 404
        if token != op_token:
            for action in ("enable", "disable"):
                assert client.post(f"/api/scripts/{sid}/{action}", headers=auth).status_code == 404
            assert client.post(f"/api/scripts/{sid}/upload-version", headers=auth,
                               files={"file": ("new.py", b"# test")}).status_code == 404
    assert client.put(f"/api/scripts/{sid}/groups", json={"group_ids": []}, headers=headers(admin_token)).status_code == 404


@pytest.mark.parametrize("change", ["deleted", "disabled", "config"])
@pytest.mark.parametrize("stale", [False, True])
def test_execute_refreshes_after_lock(client, seeded, admin_token, fresh_db, monkeypatch, change, stale):
    sid, rid, *_ = seeded
    factory = fresh_db[0]
    if stale:
        with factory() as db:
            run = db.get(Run, rid)
            run.status = "pending"
            run.created_at = datetime.now(timezone.utc) - timedelta(minutes=10)
            db.commit()

    def change_then_lock(db, script_id):
        # Simulate another transaction winning after initial permission check.
        with factory() as other:
            script = other.get(Script, script_id)
            if change == "deleted":
                script.is_deleted = True
            elif change == "disabled":
                script.status = "disabled"
            else:
                script.config_json = '{"params":[{"key":"required","type":"text","required":true}]}'
            other.commit()
        lock_script_for_lifecycle(db, script_id)

    monkeypatch.setattr(runs, "lock_script_for_lifecycle", change_then_lock)
    response = client.post("/api/runs/execute", json={"script_id": sid, "params": {}}, headers=headers(admin_token))
    assert response.status_code == (422 if change == "config" else 404)
    with factory() as db:
        assert db.query(Run).count() == 1
        assert db.get(Run, rid).status == ("cancelled" if stale else "success")


@pytest.mark.parametrize("winner", ["delete", "execute"])
def test_delete_execute_serialized(seeded, fresh_db, monkeypatch, winner):
    sid = seeded[0]
    factory = fresh_db[0]
    locked, release, attempted = Event(), Event(), Event()
    winner_module = scripts if winner == "delete" else runs
    loser_module = runs if winner == "delete" else scripts

    def hold_lock(db, script_id):
        lock_script_for_lifecycle(db, script_id)
        locked.set()
        assert release.wait(10)

    def contend(db, script_id):
        attempted.set()
        lock_script_for_lifecycle(db, script_id)

    monkeypatch.setattr(winner_module, "lock_script_for_lifecycle", hold_lock)
    monkeypatch.setattr(loser_module, "lock_script_for_lifecycle", contend)
    monkeypatch.setattr(runs, "write_audit", lambda *args, **kwargs: None)

    def invoke(action):
        with factory() as db:
            user = db.query(User).filter_by(role="admin").one()
            try:
                if action == "delete":
                    scripts.delete_script(sid, user, db)
                else:
                    runs.execute_script(ExecuteRequest(script_id=sid, params={}), user, db)
                return 200
            except HTTPException as exc:
                return exc.status_code

    loser = "execute" if winner == "delete" else "delete"
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(invoke, winner)
        try:
            assert locked.wait(5)
            second = pool.submit(invoke, loser)
            assert attempted.wait(5)
            assert not second.done()
        finally:
            release.set()
        assert first.result(timeout=10) == 200
        assert second.result(timeout=10) == (404 if winner == "delete" else 409)
    with factory() as db:
        assert db.get(Script, sid).is_deleted == (winner == "delete")
        assert db.query(Run).filter_by(status="pending").count() == (winner == "execute")


def test_initial_denial_does_not_acquire_write_lock(client, seeded, op_token, fresh_db, monkeypatch):
    with fresh_db[0]() as db:
        db.query(User).filter_by(role="operator").one().groups = []
        db.commit()

    def forbidden_lock(*args):
        pytest.fail("unauthorized execution acquired a write lock")

    monkeypatch.setattr(runs, "lock_script_for_lifecycle", forbidden_lock)
    response = client.post("/api/runs/execute", json={"script_id": seeded[0], "params": {}}, headers=headers(op_token))
    assert response.status_code == 404


def test_lifecycle_lock_does_not_change_timestamp(seeded, fresh_db):
    with fresh_db[0]() as db:
        script = db.get(Script, seeded[0])
        before = script.updated_at
        lock_script_for_lifecycle(db, script.id)
        db.commit()
        assert script.updated_at == before
