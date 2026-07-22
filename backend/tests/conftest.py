import sys
import os
import tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.models import Base
from app.database import get_db
from app.main import app
from app.auth import hash_password
from app.models import User


@pytest.fixture(autouse=True)
def fresh_db(request):
    """Create a fresh file-based SQLite DB for each test."""
    if request.node.get_closest_marker("real_db"):
        yield None
        return

    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    yield TestSession, engine

    app.dependency_overrides.clear()
    engine.dispose()
    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest.fixture
def client():
    return TestClient(app)


def _create_user(TestSession, username, password, role, display_name=None):
    db = TestSession()
    user = User(
        username=username,
        password_hash=hash_password(password),
        display_name=display_name or username,
        role=role,
        status="active",
    )
    db.add(user)
    db.commit()
    db.close()


@pytest.fixture
def admin_token(client, fresh_db):
    TestSession, _ = fresh_db
    _create_user(TestSession, "admin", "admin123", "admin", "Admin")
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    return resp.json()["token"]


@pytest.fixture
def dev_token(client, fresh_db):
    TestSession, _ = fresh_db
    _create_user(TestSession, "dev", "dev123", "developer", "Developer")
    resp = client.post("/api/auth/login", json={"username": "dev", "password": "dev123"})
    return resp.json()["token"]


@pytest.fixture
def op_token(client, fresh_db):
    TestSession, _ = fresh_db
    _create_user(TestSession, "operator1", "op123", "operator", "Operator")
    resp = client.post("/api/auth/login", json={"username": "operator1", "password": "op123"})
    return resp.json()["token"]
