import os
from datetime import datetime, timedelta, timezone

from app import scheduler
from app.models import Agent, AuditLog, ManagedSchedule, Run, User
from sqlalchemy import event


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


def _impact(client, token, agent_id, action):
    response = client.get(
        "/api/admin/managed-agents/{}/impact?action={}".format(agent_id, action),
        headers=_headers(token),
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
    preview = _impact(client, admin_token, agent["id"], "disable")
    disabled = client.patch(
        "/api/admin/managed-agents/{}".format(agent["id"]),
        json={"enabled": False, "impact_version": preview["version"]},
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


def test_manual_dispatch_is_blocked_while_device_is_running(
    client, admin_token, dev_token
):
    script_id = _upload(client, admin_token)
    agent = _register_managed(client, dev_token, "busy-manual-target", "busy-target")
    first = client.post(
        "/api/admin/managed-agents/{}/runs".format(agent["id"]),
        json={"script_id": script_id, "params": {"url_file": "C:/first.txt"}},
        headers=_headers(admin_token),
    )
    assert first.status_code == 200
    claimed = client.post(
        "/api/runs/{}/claim".format(first.json()["id"]),
        json={"agent_id": agent["id"]},
        headers=_headers(dev_token, agent["agent_token"]),
    )
    assert claimed.status_code == 200

    listed = client.get(
        "/api/admin/managed-agents",
        headers=_headers(admin_token),
    )
    busy_agent = next(item for item in listed.json() if item["id"] == agent["id"])
    blocked = client.post(
        "/api/admin/managed-agents/{}/runs".format(agent["id"]),
        json={"script_id": script_id, "params": {"url_file": "C:/second.txt"}},
        headers=_headers(admin_token),
    )

    assert busy_agent["running_run_id"] == first.json()["id"]
    assert busy_agent["running_dispatch_type"] == "managed_manual"
    assert blocked.status_code == 409
    assert "正在执行任务" in blocked.json()["detail"]


def test_managed_agent_list_aggregates_device_work_without_n_plus_one_or_result_paths(
    client, admin_token, dev_token, fresh_db
):
    TestSession, engine = fresh_db
    script_id = _upload(client, admin_token)
    agent = _register_managed(client, dev_token, "aggregate-device", "aggregate-device")
    headers = _headers(admin_token)

    pending = client.post(
        "/api/admin/managed-agents/{}/runs".format(agent["id"]),
        json={"script_id": script_id, "params": {"url_file": "C:/pending.txt"}},
        headers=headers,
    ).json()
    expired = client.post(
        "/api/admin/managed-agents/{}/runs".format(agent["id"]),
        json={"script_id": script_id, "params": {"url_file": "C:/expired.txt"}},
        headers=headers,
    ).json()
    failed = client.post(
        "/api/admin/managed-agents/{}/runs".format(agent["id"]),
        json={"script_id": script_id, "params": {"url_file": "C:/failed.txt"}},
        headers=headers,
    ).json()
    current = client.post(
        "/api/admin/managed-agents/{}/runs".format(agent["id"]),
        json={"script_id": script_id, "params": {"url_file": "C:/current.txt"}},
        headers=headers,
    ).json()

    db = TestSession()
    expired_row = db.query(Run).filter(Run.id == expired["id"]).one()
    expired_row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    db.close()

    claimed_failed = client.post(
        "/api/runs/{}/claim".format(failed["id"]),
        json={"agent_id": agent["id"]},
        headers=_headers(dev_token, agent["agent_token"]),
    )
    assert claimed_failed.status_code == 200
    completed = client.patch(
        "/api/runs/{}/status".format(failed["id"]),
        json={
            "status": "failed",
            "agent_id": agent["id"],
            "error_msg": "输出文件生成失败\n请检查磁盘",
            "result_files": '[{"path":"C:/private/results/report.xlsx"}]',
        },
        headers=_headers(dev_token, agent["agent_token"]),
    )
    assert completed.status_code == 200
    claimed_current = client.post(
        "/api/runs/{}/claim".format(current["id"]),
        json={"agent_id": agent["id"]},
        headers=_headers(dev_token, agent["agent_token"]),
    )
    assert claimed_current.status_code == 200

    statements = []

    def record_statement(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", record_statement)
    try:
        response = client.get("/api/admin/managed-agents", headers=headers)
    finally:
        event.remove(engine, "before_cursor_execute", record_statement)

    assert response.status_code == 200
    item = next(row for row in response.json() if row["id"] == agent["id"])
    assert item["pending_count"] == 1
    assert item["earliest_pending"]["id"] == pending["id"]
    assert item["current_run"]["id"] == current["id"]
    assert item["latest_run"]["id"] == failed["id"]
    assert item["latest_run"]["error_summary"] == "输出文件生成失败 请检查磁盘"
    assert item["latest_run"]["has_result_files"] is True
    assert "C:/private" not in response.text
    detail = client.get(
        "/api/runs/{}".format(failed["id"]), headers=headers
    )
    assert detail.json()["result_files"] is None
    assert detail.json()["has_result_files"] is True
    assert detail.json()["target_agent_name"] == "aggregate-device"
    assert "C:/private" not in detail.text
    run_selects = [sql for sql in statements if " runs" in sql.lower()]
    assert len(run_selects) == 3


def test_failed_expired_and_cancelled_managed_runs_can_retry_without_mutation(
    client, admin_token, dev_token, fresh_db
):
    TestSession, _ = fresh_db
    script_id = _upload(client, admin_token)
    agent = _register_managed(client, dev_token, "retry-device", "retry-device")
    originals = []
    for status in ("failed", "expired", "cancelled"):
        run = client.post(
            "/api/admin/managed-agents/{}/runs".format(agent["id"]),
            json={"script_id": script_id, "params": {"url_file": "C:/{}.txt".format(status)}},
            headers=_headers(admin_token),
        ).json()
        originals.append((run, status))

    finished_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db = TestSession()
    for run, status in originals:
        row = db.query(Run).filter(Run.id == run["id"]).one()
        row.status = status
        row.finished_at = finished_at
        row.error_msg = "original {}".format(status)
    db.commit()
    db.close()

    retry_ids = []
    for original, status in originals:
        retried = client.post(
            "/api/admin/managed-runs/{}/retry".format(original["id"]),
            headers=_headers(admin_token),
        )
        assert retried.status_code == 200
        payload = retried.json()
        retry_ids.append(payload["id"])
        assert payload["retry_of_run_id"] == original["id"]
        assert payload["status"] == "pending"
        assert payload["target_agent_id"] == agent["id"]
        assert payload["dispatch_type"] == "managed_manual"

    db = TestSession()
    for original, status in originals:
        saved = db.query(Run).filter(Run.id == original["id"]).one()
        assert saved.status == status
        assert saved.error_msg == "original {}".format(status)
        assert saved.retry_of_run_id is None
    assert db.query(Run).filter(Run.id.in_(retry_ids), Run.retry_of_run_id.is_not(None)).count() == 3
    db.close()

    not_terminal = client.post(
        "/api/admin/managed-runs/{}/retry".format(retry_ids[0]),
        headers=_headers(admin_token),
    )
    denied = client.post(
        "/api/admin/managed-runs/{}/retry".format(originals[0][0]["id"]),
        headers=_headers(dev_token),
    )
    assert not_terminal.status_code == 409
    assert denied.status_code == 403


def test_failed_schedule_run_retry_preserves_schedule_lineage(
    client, admin_token, dev_token, fresh_db
):
    TestSession, _ = fresh_db
    script_id = _upload(client, admin_token)
    agent = _register_managed(client, dev_token, "schedule-retry-agent", "schedule-retry-agent")
    schedule = client.post(
        "/api/admin/managed-schedules",
        json={
            "name": "可重试计划", "agent_id": agent["id"], "script_id": script_id,
            "params": {"url_file": "C:/schedule-retry.txt"}, "interval_seconds": 3600,
        },
        headers=_headers(admin_token),
    ).json()
    original = client.post(
        "/api/admin/managed-schedules/{}/run-now".format(schedule["id"]),
        headers=_headers(admin_token),
    ).json()
    db = TestSession()
    row = db.query(Run).filter(Run.id == original["id"]).one()
    row.status = "failed"
    row.finished_at = datetime.now(timezone.utc)
    db.commit()
    db.close()

    retried = client.post(
        "/api/admin/managed-runs/{}/retry".format(original["id"]),
        headers=_headers(admin_token),
    )

    assert retried.status_code == 200
    assert retried.json()["dispatch_type"] == "managed_schedule"
    assert retried.json()["schedule_id"] == schedule["id"]
    assert retried.json()["retry_of_run_id"] == original["id"]


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


def test_schedule_list_filters_latest_run_and_delete_cancels_only_pending(
    client, admin_token, dev_token, fresh_db
):
    TestSession, _ = fresh_db
    script_id = _upload(client, admin_token)
    first_agent = _register_managed(client, dev_token, "filter-agent-1", "filter-agent-1")
    second_agent = _register_managed(client, dev_token, "filter-agent-2", "filter-agent-2")
    first = client.post(
        "/api/admin/managed-schedules",
        json={
            "name": "启用计划", "agent_id": first_agent["id"], "script_id": script_id,
            "params": {"url_file": "C:/enabled.txt"}, "interval_seconds": 60,
        },
        headers=_headers(admin_token),
    ).json()
    second = client.post(
        "/api/admin/managed-schedules",
        json={
            "name": "暂停计划", "agent_id": second_agent["id"], "script_id": script_id,
            "params": {"url_file": "C:/paused.txt"}, "interval_seconds": 60,
            "enabled": False,
        },
        headers=_headers(admin_token),
    ).json()

    completed = client.post(
        "/api/admin/managed-schedules/{}/run-now".format(first["id"]),
        headers=_headers(admin_token),
    ).json()
    claimed = client.post(
        "/api/runs/{}/claim".format(completed["id"]),
        json={"agent_id": first_agent["id"]},
        headers=_headers(dev_token, first_agent["agent_token"]),
    )
    assert claimed.status_code == 200
    finished = client.patch(
        "/api/runs/{}/status".format(completed["id"]),
        json={"status": "success", "agent_id": first_agent["id"]},
        headers=_headers(dev_token, first_agent["agent_token"]),
    )
    assert finished.status_code == 200
    pending = client.post(
        "/api/admin/managed-schedules/{}/run-now".format(first["id"]),
        headers=_headers(admin_token),
    ).json()

    enabled = client.get(
        "/api/admin/managed-schedules?agent_id={}&enabled=true".format(first_agent["id"]),
        headers=_headers(admin_token),
    )
    paused = client.get(
        "/api/admin/managed-schedules?enabled=false",
        headers=_headers(admin_token),
    )
    assert enabled.status_code == 200
    assert [item["id"] for item in enabled.json()] == [first["id"]]
    assert enabled.json()[0]["latest_run_id"] == pending["id"]
    assert enabled.json()[0]["latest_run_status"] == "pending"
    assert [item["id"] for item in paused.json()] == [second["id"]]

    deleted = client.delete(
        "/api/admin/managed-schedules/{}".format(first["id"]),
        headers=_headers(admin_token),
    )
    assert deleted.status_code == 200
    db = TestSession()
    saved_completed = db.query(Run).filter(Run.id == completed["id"]).one()
    saved_pending = db.query(Run).filter(Run.id == pending["id"]).one()
    assert saved_completed.status == "success"
    assert saved_pending.status == "cancelled"
    assert saved_pending.finished_at is not None
    assert saved_pending.is_deleted is False
    assert "计划已删除" in saved_pending.error_msg
    db.close()


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

    preview = _impact(client, admin_token, agent["id"], "disable")
    disabled = client.patch(
        "/api/admin/managed-agents/{}".format(agent["id"]),
        json={"enabled": False, "impact_version": preview["version"]},
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


def test_lifecycle_preview_conflict_side_effects_history_identity_and_audit(
    client, admin_token, dev_token, fresh_db, tmp_path, monkeypatch
):
    from app.services import agent_thumbnails

    TestSession, _ = fresh_db
    monkeypatch.setattr(agent_thumbnails, "THUMBNAILS_DIR", str(tmp_path / "thumbnails"))
    script_id = _upload(client, admin_token)
    agent = _register_managed(client, dev_token, "lifecycle-device", "受控工作站")
    enabled_schedule = client.post(
        "/api/admin/managed-schedules",
        json={
            "name": "启用计划", "agent_id": agent["id"], "script_id": script_id,
            "params": {"url_file": "C:/enabled.txt"}, "interval_seconds": 3600,
        },
        headers=_headers(admin_token),
    ).json()
    paused_schedule = client.post(
        "/api/admin/managed-schedules",
        json={
            "name": "暂停计划", "agent_id": agent["id"], "script_id": script_id,
            "params": {"url_file": "C:/paused.txt"}, "interval_seconds": 3600,
            "enabled": False,
        },
        headers=_headers(admin_token),
    ).json()
    pending = client.post(
        "/api/admin/managed-agents/{}/runs".format(agent["id"]),
        json={"script_id": script_id, "params": {"url_file": "C:/pending.txt"}},
        headers=_headers(admin_token),
    ).json()
    running = client.post(
        "/api/admin/managed-agents/{}/runs".format(agent["id"]),
        json={"script_id": script_id, "params": {"url_file": "C:/running.txt"}},
        headers=_headers(admin_token),
    ).json()
    claimed = client.post(
        "/api/runs/{}/claim".format(running["id"]),
        json={"agent_id": agent["id"]},
        headers=_headers(dev_token, agent["agent_token"]),
    )
    assert claimed.status_code == 200

    thumbnail = agent_thumbnails.thumbnail_path(agent["id"])
    thumbnail.parent.mkdir(parents=True)
    thumbnail.write_bytes(b"retained-screen")
    db = TestSession()
    row = db.query(Agent).filter(Agent.id == agent["id"]).one()
    row.thumbnail_updated_at = datetime.now(timezone.utc)
    row.thumbnail_size = thumbnail.stat().st_size
    db.commit()
    db.close()

    first_preview = _impact(client, admin_token, agent["id"], "disable")
    repeated_preview = _impact(client, admin_token, agent["id"], "disable")
    assert repeated_preview == first_preview
    assert first_preview["pending_count"] == 1
    assert first_preview["running_count"] == 1
    assert first_preview["enabled_schedule_count"] == 1
    assert first_preview["paused_schedule_count"] == 1
    assert first_preview["thumbnail_exists"] is True
    assert first_preview["history_policy"] == {
        "runs_retained": True,
        "schedules_retained": True,
        "message": "任务运行历史和计划记录均会保留，关联启用计划将暂停。",
    }
    assert first_preview["identity_recovery"]["can_restore"] is True
    assert first_preview["identity_recovery"]["automatic_restore"] is False
    wrong_action_confirmation = client.delete(
        "/api/admin/managed-agents/{}?impact_version={}".format(
            agent["id"], first_preview["version"]
        ),
        headers=_headers(admin_token),
    )
    assert wrong_action_confirmation.status_code == 409

    late_schedule = client.post(
        "/api/admin/managed-schedules",
        json={
            "name": "预览后新增计划", "agent_id": agent["id"], "script_id": script_id,
            "params": {"url_file": "C:/late.txt"}, "interval_seconds": 3600,
        },
        headers=_headers(admin_token),
    ).json()
    stale = client.patch(
        "/api/admin/managed-agents/{}".format(agent["id"]),
        json={"enabled": False, "impact_version": first_preview["version"]},
        headers=_headers(admin_token),
    )
    assert stale.status_code == 409
    assert "状态已变化" in stale.json()["detail"]

    current_preview = _impact(client, admin_token, agent["id"], "disable")
    assert current_preview["pending_count"] == 1
    assert current_preview["enabled_schedule_count"] == 2
    disabled = client.patch(
        "/api/admin/managed-agents/{}".format(agent["id"]),
        json={"enabled": False, "impact_version": current_preview["version"]},
        headers=_headers(admin_token),
    )
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False

    db = TestSession()
    assert db.query(Run).filter(Run.id == pending["id"], Run.status == "cancelled").count() == 1
    saved_running = db.query(Run).filter(Run.id == running["id"]).one()
    assert saved_running.status == "failed"
    assert saved_running.is_deleted is False
    saved_schedules = db.query(ManagedSchedule).filter(
        ManagedSchedule.id.in_([
            enabled_schedule["id"], paused_schedule["id"], late_schedule["id"],
        ])
    ).all()
    assert all(not item.enabled and not item.is_deleted for item in saved_schedules)
    disabled_audit = db.query(AuditLog).filter(
        AuditLog.action == "managed_agent.disable", AuditLog.target_id == agent["id"]
    ).one()
    assert "pending=1" in disabled_audit.detail
    assert "enabled_schedules=2" in disabled_audit.detail
    db.close()

    restored = client.patch(
        "/api/admin/managed-agents/{}".format(agent["id"]),
        json={"enabled": True},
        headers=_headers(admin_token),
    )
    assert restored.status_code == 200
    assert restored.json()["enabled"] is True
    assert restored.json()["status"] == "offline"

    delete_preview = _impact(client, admin_token, agent["id"], "delete")
    assert delete_preview["pending_count"] == 0
    assert delete_preview["running_count"] == 0
    assert delete_preview["enabled_schedule_count"] == 0
    assert delete_preview["paused_schedule_count"] == 3
    assert delete_preview["identity_recovery"]["can_restore"] is False
    assert "device_uid" in delete_preview["identity_recovery"]["message"]

    changed_after_preview = client.post(
        "/api/agents/register",
        json={
            "device_uid": "lifecycle-device",
            "machine_name": "受控工作站已改名",
            "mode": "managed",
        },
        headers=_headers(dev_token, agent["agent_token"]),
    )
    assert changed_after_preview.status_code == 200
    stale_delete = client.delete(
        "/api/admin/managed-agents/{}?impact_version={}".format(
            agent["id"], delete_preview["version"]
        ),
        headers=_headers(admin_token),
    )
    assert stale_delete.status_code == 409

    delete_preview = _impact(client, admin_token, agent["id"], "delete")
    deleted = client.delete(
        "/api/admin/managed-agents/{}?impact_version={}".format(
            agent["id"], delete_preview["version"]
        ),
        headers=_headers(admin_token),
    )
    assert deleted.status_code == 200
    assert deleted.json()["identity_recovery"]["automatic_restore"] is False
    assert not thumbnail.exists()

    db = TestSession()
    saved_agent = db.query(Agent).filter(Agent.id == agent["id"]).one()
    assert saved_agent.is_deleted is True
    assert saved_agent.enabled is False
    assert db.query(Run).filter(Run.id.in_([pending["id"], running["id"]]), Run.is_deleted == False).count() == 2
    assert db.query(ManagedSchedule).filter(
        ManagedSchedule.id.in_([
            enabled_schedule["id"], paused_schedule["id"], late_schedule["id"],
        ]),
        ManagedSchedule.is_deleted == False,
    ).count() == 3
    assert db.query(AuditLog).filter(
        AuditLog.action == "managed_agent.enable", AuditLog.target_id == agent["id"]
    ).count() == 1
    assert db.query(AuditLog).filter(
        AuditLog.action == "managed_agent.delete", AuditLog.target_id == agent["id"]
    ).count() == 1
    db.close()

    rejected_registration = client.post(
        "/api/agents/register",
        json={
            "device_uid": "lifecycle-device",
            "machine_name": "受控工作站",
            "mode": "managed",
        },
        headers=_headers(dev_token, agent["agent_token"]),
    )
    assert rejected_registration.status_code == 403
    assert "管理员移除" in rejected_registration.json()["detail"]


def test_legacy_agent_delete_uses_unified_lifecycle_service(
    client, admin_token, dev_token, fresh_db
):
    TestSession, _ = fresh_db
    script_id = _upload(client, admin_token)
    agent = _register_managed(client, dev_token, "legacy-delete-device", "旧入口设备")
    schedule = client.post(
        "/api/admin/managed-schedules",
        json={
            "name": "旧入口计划", "agent_id": agent["id"], "script_id": script_id,
            "params": {"url_file": "C:/legacy.txt"}, "interval_seconds": 3600,
        },
        headers=_headers(admin_token),
    ).json()
    run = client.post(
        "/api/admin/managed-agents/{}/runs".format(agent["id"]),
        json={"script_id": script_id, "params": {"url_file": "C:/legacy.txt"}},
        headers=_headers(admin_token),
    ).json()

    deleted = client.delete(
        "/api/agents/{}".format(agent["id"]), headers=_headers(admin_token)
    )
    assert deleted.status_code == 200

    db = TestSession()
    assert db.query(Agent).filter(Agent.id == agent["id"]).one().is_deleted is True
    saved_schedule = db.query(ManagedSchedule).filter(ManagedSchedule.id == schedule["id"]).one()
    saved_run = db.query(Run).filter(Run.id == run["id"]).one()
    assert saved_schedule.enabled is False
    assert saved_schedule.is_deleted is False
    assert saved_run.status == "cancelled"
    assert saved_run.is_deleted is False
    assert db.query(AuditLog).filter(
        AuditLog.action == "managed_agent.delete", AuditLog.target_id == agent["id"]
    ).count() == 1
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
