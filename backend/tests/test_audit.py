from datetime import datetime, timezone

from app.models import Agent, AuditLog, User


def test_admin_can_list_non_empty_audit_log(client, fresh_db, admin_token):
    TestSession, _ = fresh_db
    db = TestSession()
    db.add(AuditLog(
        username="admin",
        action="login",
        detail="provider=local",
        created_at=datetime.now(timezone.utc),
    ))
    db.commit()
    db.close()

    response = client.get(
        "/api/audit",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200
    assert response.json()[0]["username"] == "admin"
    assert response.json()[0]["action"] == "login"


def test_audit_filters_by_target_type_and_id(client, fresh_db, admin_token):
    TestSession, _ = fresh_db
    db = TestSession()
    db.add_all([
        AuditLog(username="admin", action="managed_thumbnail.view", target_type="agent", target_id=7),
        AuditLog(username="admin", action="managed_thumbnail.view", target_type="agent", target_id=8),
        AuditLog(username="admin", action="managed_thumbnail.view", target_type="run", target_id=7),
    ])
    db.commit()
    db.close()

    response = client.get(
        "/api/audit?action=managed_thumbnail.view&target_type=agent&target_id=7",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["target_type"] == "agent"
    assert response.json()[0]["target_id"] == 7


def test_agent_audit_target_is_enriched_with_device_name(
    client, fresh_db, admin_token
):
    TestSession, _ = fresh_db
    db = TestSession()
    owner_id = db.query(User.id).filter(User.username == "admin").scalar()
    agent = Agent(
        device_uid="audit-device-name",
        machine_name="财务验收电脑",
        user_id=owner_id,
        mode="managed",
    )
    db.add(agent)
    db.flush()
    db.add(AuditLog(
        username="admin",
        action="managed_thumbnail.view",
        target_type="agent",
        target_id=agent.id,
    ))
    db.commit()
    agent_id = agent.id
    db.close()

    response = client.get(
        "/api/audit?target_type=agent&target_id={}".format(agent_id),
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200
    assert response.json()[0]["target_name"] == "财务验收电脑"
