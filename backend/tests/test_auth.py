def test_login_success(client, admin_token):
    assert admin_token is not None
    assert len(admin_token) > 10


def test_login_wrong_password(client, fresh_db):
    from tests.conftest import _create_user
    TestSession, _ = fresh_db
    _create_user(TestSession, "admin", "admin123", "admin", "Admin")
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert resp.status_code == 401


def test_login_disabled_user(client, fresh_db):
    from tests.conftest import _create_user
    from app.models import User
    TestSession, _ = fresh_db
    _create_user(TestSession, "disabled_user", "pass", "operator", "Disabled")
    db = TestSession()
    user = db.query(User).filter(User.username == "disabled_user").first()
    user.status = "disabled"
    db.commit()
    db.close()
    resp = client.post("/api/auth/login", json={"username": "disabled_user", "password": "pass"})
    assert resp.status_code == 403


def test_protected_endpoint_no_token(client):
    resp = client.post("/api/auth/logout")
    assert resp.status_code == 401


def test_protected_endpoint_with_token(client, admin_token):
    resp = client.post("/api/auth/logout", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200
