from app.auth import hash_password
from app.models import Run, Script, User


def _bearer(token):
    return {"Authorization": "Bearer " + token}


def _second_operator_and_run(client, fresh_db):
    Session, _ = fresh_db
    db = Session()
    user = User(
        username="operator2", password_hash=hash_password("op456"),
        display_name="Second Operator", role="operator", status="active",
    )
    owner = db.query(User).filter(User.username == "operator1").one()
    script = Script(
        name="private-script", type="py", latest_version=1, status="active",
        created_by=owner.id, updated_by=owner.id,
    )
    db.add_all([user, script]); db.flush()
    run = Run(
        script_id=script.id, script_version=1, user_id=user.id,
        status="failed", params='{"secret":"owner-data"}', error_msg="owner-error",
    )
    db.add(run); db.commit()
    result = (user.id, run.id)
    db.close()
    token = client.post("/api/auth/login", json={"username": "operator2", "password": "op456"}).json()["token"]
    return result + (token,)


def test_operator_cannot_cancel_another_users_run(client, fresh_db, op_token):
    _, run_id, _ = _second_operator_and_run(client, fresh_db)
    response = client.post(f"/api/runs/{run_id}/cancel", headers=_bearer(op_token))
    assert response.status_code == 403


def test_operator_cannot_create_issue_for_another_users_run(client, fresh_db, op_token):
    _, run_id, _ = _second_operator_and_run(client, fresh_db)
    response = client.post(
        "/api/issues", json={"run_id": run_id, "title": "cross-user"}, headers=_bearer(op_token)
    )
    assert response.status_code == 403


def test_operator_dashboard_excludes_other_users_sensitive_runs(client, fresh_db, op_token):
    _second_operator_and_run(client, fresh_db)
    response = client.get("/api/dashboard/stats", headers=_bearer(op_token))
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_runs"] == 0
    assert payload["total_users"] == 1
    assert payload["recent_failed"] == []
