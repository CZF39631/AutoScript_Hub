import os
from datetime import datetime, timedelta, timezone

from app import scheduler
from app.models import Agent, AuditLog, ManagedSchedule, Run, User


FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _upload(client, token):
    path = os.path.join(FIXTURE_DIR, "sample_script.py")
    with open(path, "rb") as file_obj:
        response = client.post(
            "/api/scripts/upload",
            files={"file": ("managed.py", file_obj, "text/x-python")},
            data={"changelog": "managed test"},
            headers={"Authorization": "Bearer {}".format(token)},
        )
    assert response.status_code == 200
    return response.json()["id"]


def _headers(token, agent_token=None):
    headers = {"Authorization": "Bearer {}".format(token)}
    if agent_token:
        headers["X-Agent-Token"] = agent_token
    return headers


def _register_managed(client, token, uid, name, agent_token=None):
    response = client.post(
        "/api/agents/register",
        json={"device_uid": uid, "machine_name": name, "mode": "managed"},
        headers=_headers(token, agent_token),
    )
    assert response.status_code == 200
    return response.json()


def test_registration_uses_stable_device_uid_and_preserves_legacy_defaults(client, dev_token):
    first = _register_managed(client, dev_token, "device-stable-001", "old-name")
    second = _register_managed(
        client, dev_token, "device-stable-001", "new-name", first["agent_token"]
    )
    legacy = client.post(
        "/api/agents/register",
        json={"machine_name": "legacy-client"},
        headers={"Authorization": "Bearer {}".format(dev_token)},
    )

    assert first["id"] == second["id"]
    assert second["machine_name"] == "new-name"
    assert second["mode"] == "managed"
    assert second["enabled"] is True
    assert legacy.status_code == 200
    assert legacy.json()["device_uid"]
    assert legacy.json()["mode"] == "standard"


def test_admin_options_are_scoped_to_target_owner(client, admin_token, dev_token):
    script_id = _upload(client, admin_token)
    agent = _register_managed(client, dev_token, "options-device", "options-device")

    response = client.get(
        "/api/admin/managed-agents/{}/options".format(agent["id"]),
        headers={"Authorization": "Bearer {}".format(admin_token)},
    )
    denied = client.get(
        "/api/admin/managed-agents/{}/options".format(agent["id"]),
        headers={"Authorization": "Bearer {}".format(dev_token)},
    )

    assert response.status_code == 200
    assert response.json()["owner"]["id"] == agent["user_id"]
    assert script_id in {item["id"] for item in response.json()["scripts"]}
    assert denied.status_code == 403


def test_device_uid_cannot_be_rebound_and_disabled_agent_cannot_heartbeat(
    client, admin_token, dev_token
):
    agent = _register_managed(client, dev_token, "exclusive-device", "owned")
    rebound = client.post(
        "/api/agents/register",
        json={"device_uid": "exclusive-device", "machine_name": "hijack", "mode": "managed"},
        headers={"Authorization": "Bearer {}".format(admin_token)},
    )
    disabled = client.patch(
        "/api/admin/managed-agents/{}".format(agent["id"]),
        json={"enabled": False},
        headers={"Authorization": "Bearer {}".format(admin_token)},
    )
    heartbeat = client.post(
        "/api/agents/{}/heartbeat".format(agent["id"]),
        json={},
        headers=_headers(dev_token, agent["agent_token"]),
    )

    assert rebound.status_code == 409
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    assert heartbeat.status_code == 403


def test_managed_run_is_visible_and_claimable_only_by_target_device(
    client, admin_token, dev_token
):
    script_id = _upload(client, admin_token)
    target = _register_managed(client, dev_token, "managed-target", "target")
    other = _register_managed(client, dev_token, "managed-other", "other")

    denied = client.get(
        "/api/admin/managed-agents",
        headers={"Authorization": "Bearer {}".format(dev_token)},
    )
    dispatched = client.post(
        "/api/admin/managed-agents/{}/runs".format(target["id"]),
        json={"script_id": script_id, "params": {"url_file": "C:/managed.txt"}},
        headers={"Authorization": "Bearer {}".format(admin_token)},
    )
    assert denied.status_code == 403
    assert dispatched.status_code == 200
    run = dispatched.json()
    assert run["target_agent_id"] == target["id"]
    assert run["requested_by"] is not None
    assert run["dispatch_type"] == "managed_manual"
    assert run["scheduled_for"] is not None
    assert run["expires_at"] is not None

    legacy_pending = client.get(
        "/api/runs?status=pending&limit=1&mine_only=true",
        headers={"Authorization": "Bearer {}".format(dev_token)},
    )
    target_next = client.get(
        "/api/agents/{}/next".format(target["id"]),
        headers=_headers(dev_token, target["agent_token"]),
    )
    other_next = client.get(
        "/api/agents/{}/next".format(other["id"]),
        headers=_headers(dev_token, other["agent_token"]),
    )
    wrong_claim = client.post(
        "/api/runs/{}/claim".format(run["id"]),
        json={"agent_id": other["id"]},
        headers=_headers(dev_token, other["agent_token"]),
    )
    right_claim = client.post(
        "/api/runs/{}/claim".format(run["id"]),
        json={"agent_id": target["id"]},
        headers=_headers(dev_token, target["agent_token"]),
    )

    assert legacy_pending.status_code == 200
    assert legacy_pending.json() == []
    assert target_next.status_code == 200
    assert target_next.json()["id"] == run["id"]
    assert other_next.status_code == 204
    assert wrong_claim.status_code == 403
    assert right_claim.status_code == 200
    assert right_claim.json()["claimed_at"] is not None


def test_schedule_crud_toggle_and_run_now(client, admin_token, dev_token):
    script_id = _upload(client, admin_token)
    agent = _register_managed(client, dev_token, "schedule-agent", "schedule-agent")
    create = client.post(
        "/api/admin/managed-schedules",
        json={
            "name": "每分钟任务",
            "agent_id": agent["id"],
            "script_id": script_id,
            "params": {"url_file": "C:/schedule.txt"},
            "interval_seconds": 60,
        },
        headers={"Authorization": "Bearer {}".format(admin_token)},
    )
    assert create.status_code == 200
    schedule = create.json()
    schedule_id = schedule["id"]
    assert schedule["enabled"] is True
    assert schedule["params"]["url_file"] == "C:/schedule.txt"

    disabled = client.post(
        "/api/admin/managed-schedules/{}/disable".format(schedule_id),
        headers={"Authorization": "Bearer {}".format(admin_token)},
    )
    updated = client.patch(
        "/api/admin/managed-schedules/{}".format(schedule_id),
        json={"name": "更新后的计划", "interval_seconds": 120},
        headers={"Authorization": "Bearer {}".format(admin_token)},
    )
    run_now = client.post(
        "/api/admin/managed-schedules/{}/run-now".format(schedule_id),
        headers={"Authorization": "Bearer {}".format(admin_token)},
    )
    duplicate = client.post(
        "/api/admin/managed-schedules/{}/run-now".format(schedule_id),
        headers={"Authorization": "Bearer {}".format(admin_token)},
    )

    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    assert updated.status_code == 200
    assert updated.json()["name"] == "更新后的计划"
    assert updated.json()["interval_seconds"] == 120
    assert run_now.status_code == 200
    assert run_now.json()["schedule_id"] == schedule_id
    assert duplicate.status_code == 409

    deleted = client.delete(
        "/api/admin/managed-schedules/{}".format(schedule_id),
        headers={"Authorization": "Bearer {}".format(admin_token)},
    )
    assert deleted.status_code == 200


def test_scheduler_materializes_once_skips_backlog_and_expires_pending(
    client, admin_token, dev_token, fresh_db, monkeypatch
):
    TestSession, _ = fresh_db
    script_id = _upload(client, admin_token)
    agent = _register_managed(client, dev_token, "scheduler-agent", "scheduler-agent")
    now = datetime.now(timezone.utc)
    create = client.post(
        "/api/admin/managed-schedules",
        json={
            "name": "到期计划",
            "agent_id": agent["id"],
            "script_id": script_id,
            "params": {"url_file": "C:/due.txt"},
            "interval_seconds": 60,
            "expires_after_seconds": 60,
            "next_run_at": (now - timedelta(seconds=5)).isoformat(),
        },
        headers={"Authorization": "Bearer {}".format(admin_token)},
    )
    assert create.status_code == 200
    schedule_id = create.json()["id"]
    monkeypatch.setattr(scheduler, "SessionLocal", TestSession)

    scheduler._managed_schedule_scan(now)
    db = TestSession()
    runs = db.query(Run).filter(Run.schedule_id == schedule_id).all()
    assert len(runs) == 1
    assert runs[0].status == "pending"
    first_run_id = runs[0].id
    schedule = db.query(ManagedSchedule).filter(ManagedSchedule.id == schedule_id).one()
    schedule.next_run_at = now - timedelta(seconds=1)
    db.commit()
    db.close()

    scheduler._managed_schedule_scan(now + timedelta(seconds=1))
    db = TestSession()
    assert db.query(Run).filter(Run.schedule_id == schedule_id).count() == 1
    pending = db.query(Run).filter(Run.id == first_run_id).one()
    pending.expires_at = now - timedelta(seconds=1)
    schedule = db.query(ManagedSchedule).filter(ManagedSchedule.id == schedule_id).one()
    schedule.next_run_at = now + timedelta(hours=1)
    db.commit()
    db.close()

    scheduler._managed_schedule_scan(now + timedelta(seconds=2))
    db = TestSession()
    expired = db.query(Run).filter(Run.id == first_run_id).one()
    assert expired.status == "expired"
    assert expired.finished_at is not None
    assert db.query(Run).filter(Run.schedule_id == schedule_id).count() == 1
    db.close()


def test_managed_registration_requires_device_token_after_one_legacy_upgrade(
    client, dev_token, fresh_db
):
    TestSession, _ = fresh_db
    db = TestSession()
    owner_id = db.query(User).filter(User.username == "dev").one().id
    legacy = Agent(
        device_uid="pre-token-managed",
        machine_name="legacy-managed-pc",
        user_id=owner_id,
        mode="managed",
        enabled=True,
        status="offline",
        agent_token_issued_at=None,
    )
    db.add(legacy)
    db.commit()
    legacy_id = legacy.id
    db.close()

    upgraded = client.post(
        "/api/agents/register",
        json={
            "device_uid": "pre-token-managed",
            "machine_name": "legacy-managed-pc",
            "mode": "managed",
        },
        headers=_headers(dev_token),
    )
    assert upgraded.status_code == 200
    assert upgraded.json()["id"] == legacy_id
    device_token = upgraded.json()["agent_token"]

    denied = client.post(
        "/api/agents/register",
        json={
            "device_uid": "pre-token-managed",
            "machine_name": "legacy-managed-pc",
            "mode": "managed",
        },
        headers=_headers(dev_token),
    )
    renewed = client.post(
        "/api/agents/register",
        json={
            "device_uid": "pre-token-managed",
            "machine_name": "renamed-managed-pc",
            "mode": "managed",
        },
        headers=_headers(dev_token, device_token),
    )
    assert denied.status_code == 401
    assert renewed.status_code == 200
    assert renewed.json()["id"] == legacy_id


def test_new_uid_does_not_overwrite_nonlegacy_same_machine(client, dev_token):
    first = _register_managed(client, dev_token, "stable-a", "shared-hostname")
    second = _register_managed(client, dev_token, "stable-b", "shared-hostname")

    assert first["id"] != second["id"]
    assert first["device_uid"] == "stable-a"
    assert second["device_uid"] == "stable-b"


def test_same_account_other_device_cannot_impersonate_managed_agent(
    client, admin_token, dev_token, tmp_path, monkeypatch
):
    from app.routers import runs as runs_router

    monkeypatch.setattr(runs_router, "LOGS_DIR", str(tmp_path))
    script_id = _upload(client, admin_token)
    target = _register_managed(client, dev_token, "secure-target", "target")
    other = _register_managed(client, dev_token, "secure-other", "other")
    dispatched = client.post(
        "/api/admin/managed-agents/{}/runs".format(target["id"]),
        json={"script_id": script_id, "params": {"url_file": "C:/secure.txt"}},
        headers=_headers(admin_token),
    ).json()
    run_id = dispatched["id"]

    denied_next = client.get(
        "/api/agents/{}/next".format(target["id"]),
        headers=_headers(dev_token, other["agent_token"]),
    )
    denied_claim = client.post(
        "/api/runs/{}/claim".format(run_id),
        json={"agent_id": target["id"]},
        headers=_headers(dev_token, other["agent_token"]),
    )
    claimed = client.post(
        "/api/runs/{}/claim".format(run_id),
        json={"agent_id": target["id"]},
        headers=_headers(dev_token, target["agent_token"]),
    )
    denied_status = client.patch(
        "/api/runs/{}/status".format(run_id),
        json={"status": "success", "agent_id": target["id"]},
        headers=_headers(dev_token, other["agent_token"]),
    )
    denied_log = client.post(
        "/api/runs/{}/log/chunk".format(run_id),
        json={"offset": 0, "content": "secret", "agent_id": target["id"]},
        headers=_headers(dev_token, other["agent_token"]),
    )
    completed = client.patch(
        "/api/runs/{}/status".format(run_id),
        json={"status": "success", "agent_id": target["id"]},
        headers=_headers(dev_token, target["agent_token"]),
    )
    resurrect = client.patch(
        "/api/runs/{}/status".format(run_id),
        json={"status": "failed", "agent_id": target["id"]},
        headers=_headers(dev_token, target["agent_token"]),
    )
    token_as_user = client.get(
        "/api/agents/mine",
        headers={"Authorization": "Bearer {}".format(target["agent_token"])},
    )

    assert denied_next.status_code == 403
    assert denied_claim.status_code == 403
    assert claimed.status_code == 200
    assert denied_status.status_code == 403
    assert denied_log.status_code == 403
    assert completed.status_code == 200
    assert resurrect.status_code == 409
    assert token_as_user.status_code == 401


def test_disabling_managed_agent_terminates_directed_active_runs(
    client, admin_token, dev_token, fresh_db
):
    TestSession, _ = fresh_db
    script_id = _upload(client, admin_token)
    agent = _register_managed(client, dev_token, "disable-target", "disable-target")
    first = client.post(
        "/api/admin/managed-agents/{}/runs".format(agent["id"]),
        json={"script_id": script_id, "params": {"url_file": "C:/pending.txt"}},
        headers=_headers(admin_token),
    ).json()
    second = client.post(
        "/api/admin/managed-agents/{}/runs".format(agent["id"]),
        json={"script_id": script_id, "params": {"url_file": "C:/running.txt"}},
        headers=_headers(admin_token),
    ).json()
    client.post(
        "/api/runs/{}/claim".format(second["id"]),
        json={"agent_id": agent["id"]},
        headers=_headers(dev_token, agent["agent_token"]),
    )

    disabled = client.patch(
        "/api/admin/managed-agents/{}".format(agent["id"]),
        json={"enabled": False},
        headers=_headers(admin_token),
    )
    assert disabled.status_code == 200
    db = TestSession()
    pending = db.query(Run).filter(Run.id == first["id"]).one()
    running = db.query(Run).filter(Run.id == second["id"]).one()
    assert pending.status == "cancelled"
    assert running.status == "failed"
    assert pending.finished_at is not None
    assert running.finished_at is not None
    db.close()


def test_schedule_patch_rejects_explicit_null_and_normalizes_next_run_to_utc(
    client, admin_token, dev_token, fresh_db
):
    TestSession, _ = fresh_db
    script_id = _upload(client, admin_token)
    agent = _register_managed(client, dev_token, "utc-agent", "utc-agent")
    created = client.post(
        "/api/admin/managed-schedules",
        json={
            "name": "UTC 计划",
            "agent_id": agent["id"],
            "script_id": script_id,
            "params": {"url_file": "C:/utc.txt"},
            "interval_seconds": 60,
            "next_run_at": "2030-01-02T08:30:00+08:00",
        },
        headers=_headers(admin_token),
    )
    assert created.status_code == 200
    schedule_id = created.json()["id"]
    rejected = client.patch(
        "/api/admin/managed-schedules/{}".format(schedule_id),
        json={"name": None},
        headers=_headers(admin_token),
    )
    assert rejected.status_code == 422

    db = TestSession()
    schedule = db.query(ManagedSchedule).filter(ManagedSchedule.id == schedule_id).one()
    assert schedule.next_run_at == datetime(2030, 1, 2, 0, 30, 0)
    assert schedule.next_run_at.tzinfo is None
    db.close()


def test_scheduler_skips_and_audits_batches_already_past_original_expiry(
    client, admin_token, dev_token, fresh_db, monkeypatch
):
    TestSession, _ = fresh_db
    script_id = _upload(client, admin_token)
    agent = _register_managed(client, dev_token, "missed-agent", "missed-agent")
    now = datetime.now(timezone.utc)
    created = client.post(
        "/api/admin/managed-schedules",
        json={
            "name": "错过计划",
            "agent_id": agent["id"],
            "script_id": script_id,
            "params": {"url_file": "C:/missed.txt"},
            "interval_seconds": 60,
            "expires_after_seconds": 60,
            "next_run_at": (now - timedelta(hours=2)).isoformat(),
        },
        headers=_headers(admin_token),
    )
    schedule_id = created.json()["id"]
    monkeypatch.setattr(scheduler, "SessionLocal", TestSession)

    scheduler._managed_schedule_scan(now)

    db = TestSession()
    assert db.query(Run).filter(Run.schedule_id == schedule_id).count() == 0
    audit = db.query(AuditLog).filter(
        AuditLog.action == "managed_schedule.missed",
        AuditLog.target_id == schedule_id,
    ).one()
    assert "expired_at=" in audit.detail
    db.close()

    advanced = scheduler._advance_next_run(
        now - timedelta(days=3650), 60, now
    )
    assert advanced > now
    assert advanced <= now + timedelta(seconds=60)
