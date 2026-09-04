from datetime import datetime, timezone

from app.models import AuditLog


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
