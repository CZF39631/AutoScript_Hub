"""仅独立 ASGI 应用与临时数据库，不加载主应用/调度器。"""
import asyncio
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.websockets import WebSocketDisconnect

from app.auth import create_access_token
from app.config import JWT_ALGORITHM, JWT_SECRET
from app.models import Base, TaskDevice, TaskExecution, User
from app.routers import task_events as events
from app.services import task_notifications as notifications
from app.services.task_service import digest


@pytest.fixture(autouse=True)
def fresh_db():
    # 覆盖父 conftest 的主应用数据库 fixture。
    yield


@pytest.fixture
def setup(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{(tmp_path / 'ws.db').as_posix()}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add(User(id=1, username="ws-test", display_name="test", password_hash="unused"))
        db.add(TaskDevice(id=1, device_uuid="ws-test-device", user_id=1, name="test", secret_hash=digest("device-secret")))
        db.add(TaskExecution(id=1, task_id=1, device_id=1, run_id=1, revision=1, state="running", attempt_id="attempt"))
        db.commit()
    monkeypatch.setattr(events, "SCAN_INTERVAL", 0.02)
    monkeypatch.setattr(notifications, "registry", notifications.ConnectionRegistry())
    app = FastAPI()
    app.state.task_notifications_session_factory = factory
    app.include_router(events.router)
    headers = {"Authorization": "Bearer " + create_access_token(1, "operator"), "X-Device-Token": "device-secret"}
    with TestClient(app) as client:
        yield client, factory, headers
    assert notifications.registry.count == 0
    engine.dispose()


PATH = "/api/task-devices/1/events"


def ready(ws):
    assert ws.receive_json() == {"type": "ready", "protocol": 1}
    assert ws.receive_json() == events.SYNC


@pytest.mark.parametrize("kind", ["jwt", "device", "missing", "origin", "query", "expired"])
def test_handshake_denied(setup, kind):
    client, _, headers = setup
    headers = headers.copy()
    path = PATH
    if kind == "jwt":
        headers["Authorization"] = "Bearer invalid"
    elif kind == "device":
        headers["X-Device-Token"] = "wrong"
    elif kind == "missing":
        headers.pop("Authorization")
    elif kind == "origin":
        headers["Origin"] = "http://localhost"
    elif kind == "query":
        path += "?token=invalid"
    else:
        headers["Authorization"] = "Bearer " + jwt.encode({"sub": "1", "exp": 1}, JWT_SECRET, algorithm=JWT_ALGORITHM)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(path, headers=headers):
            pass


def test_ready_commit_cancel_and_disconnect(setup):
    client, factory, headers = setup
    with client.websocket_connect(PATH, headers=headers) as ws:
        ready(ws)
        with factory() as db:
            db.get(TaskExecution, 1).state = "cancel_requested"
            db.commit()
        assert ws.receive_json() == events.SYNC
    # TestClient context waits for route cleanup.


def test_uncommitted_and_rollback_snapshot(setup):
    _, factory, headers = setup
    token = headers["Authorization"].split()[1]
    before = notifications.snapshot(1, token, "device-secret", factory)
    with factory() as db:
        db.get(TaskExecution, 1).state = "cancel_requested"
        db.flush()
        assert notifications.snapshot(1, token, "device-secret", factory) == before
        db.rollback()
    assert notifications.snapshot(1, token, "device-secret", factory) == before


@pytest.mark.parametrize("change", ["disabled", "deleted", "secret", "user_removed", "expiry"])
def test_live_auth_revocation(setup, change):
    client, factory, headers = setup
    if change == "expiry":
        headers["Authorization"] = "Bearer " + jwt.encode({"sub": "1", "exp": datetime.now(timezone.utc) + timedelta(seconds=2)}, JWT_SECRET, algorithm=JWT_ALGORITHM)
    with client.websocket_connect(PATH, headers=headers) as ws:
        ready(ws)
        with factory() as db:
            if change == "disabled":
                db.get(User, 1).status = "disabled"
            elif change == "deleted":
                db.get(User, 1).is_deleted = True
            elif change == "secret":
                db.get(TaskDevice, 1).secret_hash = digest("new-secret")
            elif change == "user_removed":
                db.delete(db.get(User, 1))
            db.commit()
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 1008


def test_limits_and_receive_bound(setup):
    client, _, headers = setup
    with client.websocket_connect(PATH, headers=headers) as first:
        ready(first)
        with client.websocket_connect(PATH, headers=headers) as second:
            ready(second)
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect(PATH, headers=headers):
                    pass
        first.send_text("x" * (events.MAX_RECEIVE_BYTES + 1))
        with pytest.raises(WebSocketDisconnect) as exc:
            first.receive_json()
        assert exc.value.code == 1009
    registry = notifications.ConnectionRegistry(total_limit=1)
    assert registry.acquire(1)
    assert not registry.acquire(2)
    registry.release(1)
    assert registry.acquire(2)


def test_forced_sync(setup, monkeypatch):
    client, _, headers = setup
    monkeypatch.setattr(events, "SYNC_INTERVAL", 0.05)
    with client.websocket_connect(PATH, headers=headers) as ws:
        ready(ws)
        assert ws.receive_json() == events.SYNC


def test_slow_send_timeout(monkeypatch):
    monkeypatch.setattr(events, "SEND_TIMEOUT", 0.01)

    class Slow:
        async def send_json(self, payload):
            await asyncio.sleep(10)

    async def exercise():
        with pytest.raises(asyncio.TimeoutError):
            await events.send(Slow(), events.SYNC)
    asyncio.run(exercise())
