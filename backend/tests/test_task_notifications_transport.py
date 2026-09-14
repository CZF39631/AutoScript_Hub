"""Real loopback Uvicorn/websocket-client transport; synthetic DB, no installed Agent."""
import hashlib
import json
import socket
import struct
import threading
import time
from uuid import uuid4

import requests
import uvicorn
import websocket
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth import create_access_token
from app.database import get_db
from app.models import Base, TaskDevice, User, Script, ScheduledTask, Run, TaskExecution
from app.routers import task_events, tasks
from client.runtime.task_notifications import NotificationSocket


def test_real_upgrade_committed_hint_and_revocation(tmp_path, monkeypatch):
    engine = create_engine('sqlite:///' + str(tmp_path / 'transport.db'), connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    secret = 'synthetic-device-secret-for-transport-only'
    with sessions() as db:
        user = User(username='transport-test', display_name='Synthetic', password_hash='unused', role='operator', status='active')
        db.add(user)
        db.flush()
        user_id = user.id
        device = TaskDevice(device_uuid='a0000000-0000-4000-8000-000000000001',
                            secret_hash=hashlib.sha256(secret.encode()).hexdigest(), user_id=user_id, name='synthetic')
        db.add(device)
        db.commit()
        device_id = device.id
        script = Script(name='Synthetic cancellation', latest_version=1)
        db.add(script)
        db.flush()
        task = ScheduledTask(name='Synthetic task', requester_id=user_id, device_id=device_id,
                             script_id=script.id, script_version=1, params='{}', trigger='{"kind":"manual"}')
        run = Run(script_id=script.id, script_version=1, user_id=user_id, status='running', params='{}')
        db.add_all([task, run])
        db.flush()
        attempt = str(uuid4())
        execution = TaskExecution(task_id=task.id, device_id=device_id, run_id=run.id,
                                  revision=1, state='running', attempt_id=attempt)
        db.add(execution)
        db.flush()
        execution_id = execution.id
        device.active_execution_id = execution_id
        db.commit()
    app = FastAPI()
    app.state.task_notifications_session_factory = sessions
    app.include_router(task_events.router)
    app.include_router(tasks.router)
    def dependency():
        with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = dependency
    monkeypatch.setattr(task_events, 'SCAN_INTERVAL', .05)
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen()
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level='error', lifespan='off', ws='websockets',
                                          ws_max_size=1024, ws_max_queue=4))
    thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    connection = NotificationSocket()
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and time.monotonic() < deadline:
            threading.Event().wait(.01)
        assert server.started
        token = create_access_token(user_id, 'operator')
        connection.connect(f'ws://127.0.0.1:{port}/api/task-devices/{device_id}/events',
                           header={'Authorization': 'Bearer ' + token, 'X-Device-Token': secret},
                           suppress_origin=True, redirect_limit=0, timeout=3,
                           http_no_proxy=['127.0.0.1', 'localhost'])
        assert connection.handshake_response.status == 101
        assert json.loads(connection.recv()) == {'type': 'ready', 'protocol': 1}
        assert json.loads(connection.recv()) == {'type': 'sync_required', 'protocol': 1}
        with requests.Session() as http:
            http.trust_env = False
            http.headers.update({'Authorization': 'Bearer ' + token, 'X-Device-Token': secret})
            response = http.post(f'http://127.0.0.1:{port}/api/tasks/executions/{execution_id}/cancel', timeout=3)
            assert response.status_code == 200
            assert response.json()['state'] == 'cancel_requested'
            assert json.loads(connection.recv()) == {'type': 'sync_required', 'protocol': 1}
            with sessions() as db:
                assert db.get(TaskDevice, device_id).active_execution_id == execution_id
            response = http.post(f'http://127.0.0.1:{port}/api/task-devices/{device_id}/executions/{execution_id}/report',
                                 json={'attempt_id': attempt, 'state': 'cancelled', 'stopped': True}, timeout=3)
            assert response.status_code == 200
            assert json.loads(connection.recv()) == {'type': 'sync_required', 'protocol': 1}
            with sessions() as db:
                assert db.get(TaskDevice, device_id).active_execution_id is None
                assert db.get(TaskExecution, execution_id).state == 'cancelled'
        with sessions() as db:
            db.get(TaskDevice, device_id).secret_hash = '0' * 64
            db.commit()
        frame = connection.recv_frame()
        assert frame.opcode == websocket.ABNF.OPCODE_CLOSE
        assert struct.unpack('!H', frame.data[:2])[0] == 1008
    finally:
        connection.shutdown()
        server.should_exit = True
        thread.join(5)
        listener.close()
        engine.dispose()
    assert not thread.is_alive()
