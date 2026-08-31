import httpx


def _configure(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "EXTERNAL_AUTH_ENABLED", True)
    monkeypatch.setattr(config, "EXTERNAL_AUTH_METHOD", "http_form")
    monkeypatch.setattr(config, "EXTERNAL_AUTH_URL", "https://identity.example/api/login")
    monkeypatch.setattr(config, "EXTERNAL_AUTH_ROLE_MAP", {"member": "operator", "administrator": "admin"})


def test_external_auth_posts_form_and_extracts_identity(monkeypatch):
    from app.services import external_auth

    _configure(monkeypatch)
    captured = {}

    def fake_post(url, **kwargs):
        captured.update(url=url, kwargs=kwargs)
        return httpx.Response(200, json={
            "success": True,
            "data": {"user": {
                "id": "external-001",
                "username": "sample-user",
                "display_name": "示例用户",
                "role": "member",
            }},
        })

    monkeypatch.setattr(external_auth.httpx, "post", fake_post)
    identity = external_auth.authenticate("sample-user", "secret")

    assert captured["url"] == "https://identity.example/api/login"
    assert captured["kwargs"]["data"] == {"username": "sample-user", "password": "secret"}
    assert "json" not in captured["kwargs"]
    assert identity.subject == "external-001"
    assert identity.username == "sample-user"
    assert identity.display_name == "示例用户"
    assert identity.role == "operator"


def test_external_login_provisions_local_user_and_returns_local_token(client, fresh_db, monkeypatch):
    from app import config
    from app.models import User
    from app.routers import auth as auth_router
    from app.services.external_auth import ExternalIdentity

    _configure(monkeypatch)
    monkeypatch.setattr(
        auth_router,
        "authenticate_external",
        lambda username, password: ExternalIdentity("external-001", "sample-user", "示例用户", "operator"),
    )

    response = client.post("/api/auth/login", json={"username": "sample-user", "password": "secret"})
    assert response.status_code == 200
    assert response.json()["user"]["username"] == "sample-user"
    assert response.json()["user"]["role"] == "operator"

    TestSession, _ = fresh_db
    db = TestSession()
    try:
        user = db.query(User).filter(User.external_subject == "external-001").one()
        assert user.auth_source == "external"
        assert user.display_name == "示例用户"
    finally:
        db.close()

    monkeypatch.setattr(config, "EXTERNAL_AUTH_ENABLED", False)


def test_existing_external_user_keeps_locally_assigned_role(fresh_db):
    from app.models import User
    from app.services.external_auth import ExternalIdentity, resolve_local_user
    from app.auth import hash_password

    TestSession, _ = fresh_db
    db = TestSession()
    try:
        db.add(User(
            username="external-admin",
            password_hash=hash_password("unusable-password"),
            display_name="External Admin",
            role="admin",
            status="active",
            auth_source="external",
            external_subject="external-002",
        ))
        db.commit()

        user = resolve_local_user(
            db,
            ExternalIdentity("external-002", "external-admin", "新显示名", "operator"),
        )

        assert user.role == "admin"
        assert user.display_name == "新显示名"
    finally:
        db.close()


def test_external_login_does_not_take_over_local_username(client, fresh_db, monkeypatch):
    from tests.conftest import _create_user
    from app.routers import auth as auth_router
    from app.services.external_auth import ExternalIdentity

    TestSession, _ = fresh_db
    _create_user(TestSession, "admin", "local-password", "admin", "Admin")
    _configure(monkeypatch)
    monkeypatch.setattr(
        auth_router,
        "authenticate_external",
        lambda username, password: ExternalIdentity("remote-admin", "admin", "Remote Admin", "admin"),
    )

    response = client.post("/api/auth/login", json={"username": "admin", "password": "remote-password"})
    assert response.status_code == 403
