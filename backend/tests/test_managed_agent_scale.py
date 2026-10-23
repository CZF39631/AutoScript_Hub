import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event

from app.models import Agent, AuditLog, ManagedAgentBatch, ManagedAgentBatchItem, Run, User
from app.routers import managed as managed_router


FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _headers(token, key=None):
    result = {"Authorization": "Bearer {}".format(token)}
    if key:
        result["Idempotency-Key"] = key
    return result


def _register(client, token, uid, name):
    response = client.post(
        "/api/agents/register",
        json={"device_uid": uid, "machine_name": name, "mode": "managed"},
        headers=_headers(token),
    )
    assert response.status_code == 200
    return response.json()


def _upload(client, token):
    path = os.path.join(FIXTURE_DIR, "sample_script.py")
    with open(path, "rb") as file_obj:
        response = client.post(
            "/api/scripts/upload",
            files={"file": ("scale.py", file_obj, "text/x-python")},
            data={"changelog": "scale test"}, headers=_headers(token),
        )
    assert response.status_code == 200
    return response.json()["id"]


def test_paged_agents_stay_stable_for_more_than_one_thousand_devices(
    client, admin_token, fresh_db
):
    TestSession, _ = fresh_db
    db = TestSession()
    owner_id = db.query(User.id).filter(User.username == "admin").scalar()
    heartbeat = datetime.now(timezone.utc)
    db.bulk_save_objects([
        Agent(
            device_uid="scale-{:04d}".format(index),
            machine_name="工作站 {:04d}".format(index), user_id=owner_id,
            mode="managed", enabled=True,
            status="online" if index % 2 == 0 else "offline",
            last_heartbeat=heartbeat,
        )
        for index in range(1005)
    ])
    db.commit()
    db.close()

    first = client.get(
        "/api/admin/managed-agents/paged?page=1&page_size=100&sort=-last_heartbeat",
        headers=_headers(admin_token),
    )
    second = client.get(
        "/api/admin/managed-agents/paged?page=2&page_size=100&sort=-last_heartbeat",
        headers=_headers(admin_token),
    )
    filtered = client.get(
        "/api/admin/managed-agents/paged?query=工作站 099&status=offline&sort=name&page_size=20",
        headers=_headers(admin_token),
    )

    assert first.status_code == second.status_code == filtered.status_code == 200
    assert first.json()["total"] == 1005
    assert first.json()["pages"] == 11
    first_ids = [item["id"] for item in first.json()["items"]]
    second_ids = [item["id"] for item in second.json()["items"]]
    assert first_ids == sorted(first_ids)
    assert set(first_ids).isdisjoint(second_ids)
    assert filtered.json()["total"] == 5
    assert all(item["status"] == "offline" for item in filtered.json()["items"])


def test_device_group_crud_membership_and_filter(client, admin_token, dev_token):
    first = _register(client, dev_token, "group-first", "甲设备")
    second = _register(client, dev_token, "group-second", "乙设备")
    created = client.post(
        "/api/admin/managed-agent-groups",
        json={"name": "华东生产", "description": "生产设备"},
        headers=_headers(admin_token),
    )
    assert created.status_code == 200
    group_id = created.json()["id"]

    members = client.put(
        "/api/admin/managed-agent-groups/{}/members".format(group_id),
        json={"agent_ids": [first["id"], second["id"]]}, headers=_headers(admin_token),
    )
    renamed = client.patch(
        "/api/admin/managed-agent-groups/{}".format(group_id),
        json={"name": "华东核心"}, headers=_headers(admin_token),
    )
    filtered = client.get(
        "/api/admin/managed-agents/paged?group_id={}".format(group_id),
        headers=_headers(admin_token),
    )

    assert members.status_code == renamed.status_code == filtered.status_code == 200
    assert members.json()["member_count"] == 2
    assert renamed.json()["name"] == "华东核心"
    assert {item["id"] for item in filtered.json()["items"]} == {first["id"], second["id"]}
    assert all(item["groups"] == [{"id": group_id, "name": "华东核心"}] for item in filtered.json()["items"])

    deleted = client.delete(
        "/api/admin/managed-agent-groups/{}".format(group_id), headers=_headers(admin_token),
    )
    assert deleted.status_code == 200
    assert deleted.json()["members_removed"] == 2
    recreated = client.post(
        "/api/admin/managed-agent-groups", json={"name": "华东核心"},
        headers=_headers(admin_token),
    )
    assert recreated.status_code == 200
    assert recreated.json()["id"] != group_id


def test_scale_read_endpoints_group_assignment_batch_lookup_run_filter_and_permissions(
    client, admin_token, dev_token
):
    script_id = _upload(client, admin_token)
    failed_agent = _register(client, dev_token, "scale-api-failed", "失败设备")
    idle_agent = _register(client, dev_token, "scale-api-idle", "空闲设备")
    first_group = client.post(
        "/api/admin/managed-agent-groups", json={"name": "接口组甲"},
        headers=_headers(admin_token),
    ).json()
    second_group = client.post(
        "/api/admin/managed-agent-groups", json={"name": "接口组乙"},
        headers=_headers(admin_token),
    ).json()

    group_list = client.get(
        "/api/admin/managed-agent-groups", headers=_headers(admin_token),
    )
    assigned = client.put(
        "/api/admin/managed-agents/{}/groups".format(failed_agent["id"]),
        json={"group_ids": [second_group["id"], first_group["id"]]},
        headers=_headers(admin_token),
    )
    assert group_list.status_code == assigned.status_code == 200
    assert {item["id"] for item in group_list.json()} == {first_group["id"], second_group["id"]}
    assert {item["id"] for item in assigned.json()} == {first_group["id"], second_group["id"]}

    run = client.post(
        "/api/admin/managed-agents/{}/runs".format(failed_agent["id"]),
        json={"script_id": script_id, "params": {"url_file": "C:/scale-api.txt"}}, headers=_headers(admin_token),
    ).json()
    assert client.post(
        "/api/runs/{}/claim".format(run["id"]),
        json={"agent_id": failed_agent["id"]},
        headers={
            "Authorization": "Bearer {}".format(dev_token),
            "X-Agent-Token": failed_agent["agent_token"],
        },
    ).status_code == 200
    assert client.patch(
        "/api/runs/{}/status".format(run["id"]),
        json={"status": "failed", "agent_id": failed_agent["id"]},
        headers={
            "Authorization": "Bearer {}".format(dev_token),
            "X-Agent-Token": failed_agent["agent_token"],
        },
    ).status_code == 200
    failed = client.get(
        "/api/admin/managed-agents/paged?run_status=failed", headers=_headers(admin_token),
    )
    idle = client.get(
        "/api/admin/managed-agents/paged?run_status=idle", headers=_headers(admin_token),
    )
    assert {item["id"] for item in failed.json()["items"]} == {failed_agent["id"]}
    assert {item["id"] for item in idle.json()["items"]} == {failed_agent["id"], idle_agent["id"]}

    batch = client.post(
        "/api/admin/managed-agent-batches",
        json={
            "operation": "set_groups",
            "selection": {"mode": "explicit", "agent_ids": [idle_agent["id"]]},
            "group_ids": [first_group["id"]],
        },
        headers=_headers(admin_token, "scale-api-batch-0001"),
    )
    assert batch.status_code == 200
    batch_lookup = client.get(
        "/api/admin/managed-agent-batches/{}".format(batch.json()["batch_id"]),
        headers=_headers(admin_token),
    )
    assert batch_lookup.status_code == 200
    assert batch_lookup.json()["items"][0]["agent_id"] == idle_agent["id"]

    denied_requests = [
        client.get("/api/admin/managed-agent-groups", headers=_headers(dev_token)),
        client.put(
            "/api/admin/managed-agents/{}/groups".format(idle_agent["id"]),
            json={"group_ids": []}, headers=_headers(dev_token),
        ),
        client.get(
            "/api/admin/managed-agent-batches/{}".format(batch.json()["batch_id"]),
            headers=_headers(dev_token),
        ),
        client.get(
            "/api/admin/managed-agents/paged?run_status=failed",
            headers=_headers(dev_token),
        ),
    ]
    assert all(response.status_code == 403 for response in denied_requests)


def test_schedule_agent_ids_filter_is_bounded_to_requested_page_devices(
    client, admin_token, dev_token
):
    script_id = _upload(client, admin_token)
    first = _register(client, dev_token, "schedule-filter-a", "计划筛选甲")
    second = _register(client, dev_token, "schedule-filter-b", "计划筛选乙")
    for agent in (first, second):
        response = client.post(
            "/api/admin/managed-schedules",
            json={
                "name": "{}的计划".format(agent["machine_name"]),
                "agent_id": agent["id"], "script_id": script_id,
                "params": {"url_file": "C:/{}.txt".format(agent["id"])}, "interval_seconds": 3600,
            },
            headers=_headers(admin_token),
        )
        assert response.status_code == 200

    filtered = client.get(
        "/api/admin/managed-schedules?agent_ids={}".format(first["id"]),
        headers=_headers(admin_token),
    )
    invalid = client.get(
        "/api/admin/managed-schedules?agent_ids=bad-id",
        headers=_headers(admin_token),
    )
    assert filtered.status_code == 200
    assert [item["agent_id"] for item in filtered.json()] == [first["id"]]
    assert invalid.status_code == 422


def test_batch_preview_partial_success_idempotency_and_audit(
    client, admin_token, dev_token, fresh_db
):
    TestSession, _ = fresh_db
    script_id = _upload(client, admin_token)
    ready = _register(client, dev_token, "batch-ready", "可发布")
    disabled = _register(client, dev_token, "batch-disabled", "已暂停")
    busy = _register(client, dev_token, "batch-busy", "运行中")

    db = TestSession()
    disabled_row = db.query(Agent).filter(Agent.id == disabled["id"]).one()
    disabled_row.enabled = False
    db.add(Run(
        script_id=script_id, script_version=1, user_id=busy["user_id"], status="running",
        target_agent_id=busy["id"], agent_id=busy["id"], requested_by=busy["user_id"],
        dispatch_type="managed_manual", scheduled_for=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    ))
    db.commit()
    db.close()

    payload = {
        "operation": "dispatch_run",
        "selection": {"mode": "explicit", "agent_ids": [ready["id"], disabled["id"], busy["id"]]},
        "script_id": script_id,
        "params": {"url_file": "C:/batch.txt"},
        "expires_in_seconds": 3600,
    }
    preview = client.post(
        "/api/admin/managed-agent-batches/preview", json=payload, headers=_headers(admin_token),
    )
    executed = client.post(
        "/api/admin/managed-agent-batches", json=payload,
        headers=_headers(admin_token, "batch-dispatch-0001"),
    )
    replayed = client.post(
        "/api/admin/managed-agent-batches", json=payload,
        headers=_headers(admin_token, "batch-dispatch-0001"),
    )

    assert preview.status_code == executed.status_code == replayed.status_code == 200
    assert (preview.json()["success"], preview.json()["failed"]) == (1, 2)
    assert (executed.json()["success"], executed.json()["failed"]) == (1, 2)
    assert replayed.json()["batch_id"] == executed.json()["batch_id"]
    assert replayed.json()["replayed"] is True

    db = TestSession()
    assert db.query(ManagedAgentBatch).count() == 1
    assert db.query(ManagedAgentBatchItem).count() == 3
    assert db.query(Run).filter(
        Run.target_agent_id == ready["id"], Run.status == "pending"
    ).count() == 1
    assert db.query(AuditLog).filter(
        AuditLog.action == "managed_agent.batch.execute",
        AuditLog.target_id == executed.json()["batch_id"],
    ).count() == 1
    db.close()

    changed = dict(payload)
    changed["expires_in_seconds"] = 7200
    conflict = client.post(
        "/api/admin/managed-agent-batches", json=changed,
        headers=_headers(admin_token, "batch-dispatch-0001"),
    )
    assert conflict.status_code == 409


def test_batch_pause_resume_and_pause_schedules_return_per_device_results(
    client, admin_token, dev_token
):
    script_id = _upload(client, admin_token)
    agent = _register(client, dev_token, "batch-controls", "批量控制设备")
    schedule = client.post(
        "/api/admin/managed-schedules",
        json={
            "name": "待暂停计划", "agent_id": agent["id"], "script_id": script_id,
            "params": {"url_file": "C:/batch-schedule.txt"}, "interval_seconds": 3600,
        }, headers=_headers(admin_token),
    )
    assert schedule.status_code == 200
    selection = {"mode": "explicit", "agent_ids": [agent["id"]]}

    pause_schedules = client.post(
        "/api/admin/managed-agent-batches",
        json={"operation": "pause_schedules", "selection": selection},
        headers=_headers(admin_token, "pause-schedules-0001"),
    )
    pause_agent = client.post(
        "/api/admin/managed-agent-batches",
        json={"operation": "pause_agents", "selection": selection},
        headers=_headers(admin_token, "pause-agent-0000001"),
    )
    resume_agent = client.post(
        "/api/admin/managed-agent-batches",
        json={"operation": "resume_agents", "selection": selection},
        headers=_headers(admin_token, "resume-agent-000001"),
    )
    skipped_resume = client.post(
        "/api/admin/managed-agent-batches",
        json={"operation": "resume_agents", "selection": selection},
        headers=_headers(admin_token, "resume-agent-000002"),
    )

    assert pause_schedules.status_code == pause_agent.status_code == resume_agent.status_code == 200
    assert pause_schedules.json()["items"][0]["result"] == "success"
    assert pause_agent.json()["items"][0]["result"] == "success"
    assert resume_agent.json()["items"][0]["result"] == "success"
    assert skipped_resume.json()["items"][0]["result"] == "skipped"


def test_batch_all_filter_has_hard_limit(client, admin_token, fresh_db):
    TestSession, _ = fresh_db
    db = TestSession()
    owner_id = db.query(User.id).filter(User.username == "admin").scalar()
    db.bulk_save_objects([
        Agent(device_uid="limit-{}".format(index), machine_name="设备 {}".format(index),
              user_id=owner_id, mode="managed", enabled=True, status="offline")
        for index in range(201)
    ])
    db.commit()
    db.close()

    response = client.post(
        "/api/admin/managed-agent-batches/preview",
        json={"operation": "pause_schedules", "selection": {"mode": "all", "filters": {}}},
        headers=_headers(admin_token),
    )
    assert response.status_code == 413
    assert "200" in response.json()["detail"]


def test_interrupted_batch_exposes_partial_progress_and_resumes_once(
    client, admin_token, dev_token, fresh_db, monkeypatch
):
    TestSession, _ = fresh_db
    first = _register(client, dev_token, "resume-first", "续跑设备甲")
    second = _register(client, dev_token, "resume-second", "续跑设备乙")
    db = TestSession()
    db.query(Agent).filter(Agent.id.in_([first["id"], second["id"]])).update(
        {Agent.enabled: False}, synchronize_session=False,
    )
    db.commit()
    db.close()

    original = managed_router._execute_one_batch_item
    calls = []

    class SimulatedCrash(BaseException):
        pass

    def interrupt_second(*args, **kwargs):
        calls.append(args[2].agent_id)
        if len(calls) == 2:
            raise SimulatedCrash("service stopped")
        return original(*args, **kwargs)

    monkeypatch.setattr(managed_router, "_execute_one_batch_item", interrupt_second)
    payload = {
        "operation": "resume_agents",
        "selection": {"mode": "explicit", "agent_ids": [first["id"], second["id"]]},
    }
    with pytest.raises(SimulatedCrash):
        client.post(
            "/api/admin/managed-agent-batches", json=payload,
            headers=_headers(admin_token, "interrupted-resume-0001"),
        )

    db = TestSession()
    batch = db.query(ManagedAgentBatch).one()
    batch_id = batch.id
    assert batch.status == "stale"
    assert [item.result for item in batch.items] == ["success", "pending"]
    db.close()

    partial = client.get(
        "/api/admin/managed-agent-batches/{}".format(batch_id),
        headers=_headers(admin_token),
    )
    assert partial.status_code == 200
    assert partial.json()["status"] == "stale"
    assert partial.json()["pending"] == 1
    assert partial.json()["success"] == 1

    monkeypatch.setattr(managed_router, "_execute_one_batch_item", original)
    resumed = client.post(
        "/api/admin/managed-agent-batches", json=payload,
        headers=_headers(admin_token, "interrupted-resume-0001"),
    )
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "completed"
    assert resumed.json()["replayed"] is True
    assert resumed.json()["pending"] == 0
    assert resumed.json()["success"] == 2

    db = TestSession()
    assert db.query(AuditLog).filter(
        AuditLog.action == "managed_agent.enable",
        AuditLog.target_id == first["id"],
    ).count() == 1
    assert db.query(AuditLog).filter(
        AuditLog.action == "managed_agent.enable",
        AuditLog.target_id == second["id"],
    ).count() == 1
    assert db.query(ManagedAgentBatchItem).count() == 2
    db.close()


def test_managed_group_list_uses_constant_query_count(
    client, admin_token, fresh_db
):
    _, engine = fresh_db
    for index in range(12):
        response = client.post(
            "/api/admin/managed-agent-groups",
            json={"name": "聚合查询组 {:02d}".format(index)},
            headers=_headers(admin_token),
        )
        assert response.status_code == 200

    statements = []

    def record_statement(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", record_statement)
    try:
        response = client.get(
            "/api/admin/managed-agent-groups", headers=_headers(admin_token),
        )
    finally:
        event.remove(engine, "before_cursor_execute", record_statement)

    assert response.status_code == 200
    assert len(response.json()) == 12
    # Authentication plus the endpoint's group and aggregate-count selects stay
    # constant; the old implementation added one SELECT per group.
    assert len(statements) <= 5
