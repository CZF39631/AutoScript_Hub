from datetime import datetime, timedelta, timezone

from app import scheduler
from app.models import ManagedSchedule

from test_managed_agents import _headers, _register_managed, _upload


def test_cron_schedule_fields_and_rule_changes_recalculate_future_cursor(
    client, admin_token, dev_token, fresh_db
):
    TestSession, _ = fresh_db
    script_id = _upload(client, admin_token)
    agent = _register_managed(client, dev_token, "cron-agent", "cron-agent")
    created = client.post(
        "/api/admin/managed-schedules",
        json={
            "name": "工作日计划",
            "agent_id": agent["id"],
            "script_id": script_id,
            "params": {"url_file": "C:/must-not-enter-audit.txt"},
            "schedule_type": "cron",
            "cron_expression": "*/5 * * * *",
            "timezone": "Asia/Shanghai",
        },
        headers=_headers(admin_token),
    )
    assert created.status_code == 200, created.text
    item = created.json()
    assert item["schedule_type"] == "cron"
    assert item["interval_seconds"] is None
    assert item["cron_expression"] == "*/5 * * * *"
    assert item["timezone"] == "Asia/Shanghai"

    old_cursor = datetime.fromisoformat(item["next_run_at"])
    updated = client.patch(
        "/api/admin/managed-schedules/{}".format(item["id"]),
        json={"cron_expression": "*/10 * * * *"},
        headers=_headers(admin_token),
    )
    assert updated.status_code == 200, updated.text
    new_cursor = datetime.fromisoformat(updated.json()["next_run_at"])
    assert new_cursor > datetime.now(timezone.utc).replace(tzinfo=None)
    assert new_cursor != old_cursor or new_cursor.minute % 10 == 0

    db = TestSession()
    schedule = db.query(ManagedSchedule).filter_by(id=item["id"]).one()
    assert schedule.next_run_at.tzinfo is None
    db.close()


def test_cron_cursor_skips_all_historical_occurrences():
    now = datetime(2030, 1, 1, 12, 34, 30, tzinfo=timezone.utc)
    schedule = ManagedSchedule(
        schedule_type="cron", cron_expression="* * * * *", timezone="UTC"
    )
    advanced = scheduler._next_schedule_run(
        schedule, now - timedelta(days=3650), now
    )
    assert advanced == datetime(2030, 1, 1, 12, 35, tzinfo=timezone.utc)


def test_cron_validation_rejects_six_fields_and_unknown_timezone(
    client, admin_token, dev_token, fresh_db
):
    script_id = _upload(client, admin_token)
    agent = _register_managed(client, dev_token, "cron-invalid", "cron-invalid")
    base = {
        "name": "坏计划", "agent_id": agent["id"], "script_id": script_id,
        "params": {"url_file": "C:/invalid.txt"},
        "schedule_type": "cron", "cron_expression": "0 * * * *", "timezone": "UTC",
    }
    for patch in (
        {"cron_expression": "0 0 * * * *"},
        {"timezone": "Not/A_Real_Zone"},
    ):
        payload = dict(base)
        payload.update(patch)
        response = client.post(
            "/api/admin/managed-schedules", json=payload, headers=_headers(admin_token)
        )
        assert response.status_code == 422
