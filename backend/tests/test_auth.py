import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.mark.real_db
def test_startup_seeds_admin_user_for_login(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from app import database as database_module
    from app import scheduler as scheduler_module
    from app import main as main_module
    import init_db as init_db_module

    db_path = tmp_path / "startup-login.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    monkeypatch.setattr(database_module, "engine", engine)
    monkeypatch.setattr(database_module, "SessionLocal", SessionLocal)
    monkeypatch.setattr(init_db_module, "engine", engine)
    monkeypatch.setattr(init_db_module, "SessionLocal", SessionLocal)
    monkeypatch.setattr(scheduler_module, "start_scheduler", lambda: None)

    try:
        with TestClient(main_module.app) as client:
            resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        assert resp.status_code == 200
        assert resp.json()["user"]["username"] == "admin"
    finally:
        engine.dispose()


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
