"""No live Agent/server: fake sockets and OS temporary client paths only."""
import json
import queue
import ssl
import threading
from types import SimpleNamespace

import pytest
import websocket

from client.runtime.task_notifications import TaskNotifications, NotificationSocket, notification_url
from client.tests.test_task_agent import agent


class FakeSocket:
    def __init__(self, status=101):
        self.handshake_response = SimpleNamespace(status=status)
        self.frames = queue.Queue()
        self.connected = threading.Event()
        self.closed = threading.Event()
        self.options = None

    def connect(self, url, **options):
        self.url, self.options = url, options
        self.connected.set()

    def recv_frame(self):
        frame = self.frames.get(timeout=2)
        if frame is None:
            raise OSError('closed')
        return frame

    def hint(self, kind='ready'):
        self.frames.put(SimpleNamespace(fin=True, opcode=websocket.ABNF.OPCODE_TEXT,
                                        data=json.dumps({'type': kind, 'protocol': 1})))

    def abort(self):
        self.frames.put(None)

    def shutdown(self):
        self.closed.set()


def configure(client, jwt='test-jwt'):
    client.configure('https://example.invalid', 'test-account', jwt, 42, 'test-device-token')


def test_ready_headers_generation_reconnect_and_close():
    first, second = FakeSocket(), FakeSocket()
    sockets = iter([first, second])
    client = TaskNotifications(lambda: next(sockets))
    configure(client)
    client.start()
    try:
        assert first.connected.wait(1)
        assert first.url == 'wss://example.invalid/api/task-devices/42/events'
        assert first.options['header'] == {'Authorization': 'Bearer test-jwt', 'X-Device-Token': 'test-device-token'}
        assert first.options['redirect_limit'] == 0
        assert first.options['suppress_origin'] is True
        assert first.options['timeout'] == 5
        assert 'subprotocols' not in first.options
        first.hint()
        assert client._wake.wait(1)
        client.wait(0, minimum=0)
        old = client._generation
        configure(client, jwt='replacement')
        assert first.closed.wait(1)
        assert second.connected.wait(1)
        client._message('{"type":"ready","protocol":1}', old)
        assert not client._wake.is_set()
        second.hint('sync_required')
        assert client._wake.wait(1)
    finally:
        client.stop()
    assert not client._thread.is_alive()
    assert second.closed.is_set()


@pytest.mark.parametrize('message', ['[]', 'invalid', '{"type":"execute","protocol":1}',
    '{"type":"ready","protocol":true}', '{"type":"ready","protocol":2}', 'x' * 4097])
def test_unknown_messages_do_nothing(message):
    client = TaskNotifications()
    client._message(message, 0)
    assert not client._wake.is_set()


def test_notifications_never_execute_or_mark_online(agent, monkeypatch):
    client = TaskNotifications()
    monkeypatch.setattr(agent, 'poll_and_execute', lambda: pytest.fail('WS cannot execute'))
    client._message('{"type":"ready","protocol":1}', 0)
    assert client._wake.is_set()
    assert agent._last_online_time is None
    assert agent._controller.active is None
    assert agent._next_poll_interval() == 5
    monkeypatch.setattr(agent, '_running_proc', object())
    assert agent._next_poll_interval() == 1
    client.stop()
    client.wait(5)


@pytest.mark.parametrize('index,value', [(0, 'https://other.invalid'), (1, 'other-account'),
                                        (2, 'new-jwt'), (3, 43), (4, 'new-device-token')])
def test_every_identity_change_invalidates_old_callbacks(index, value):
    client = TaskNotifications()
    values = ['https://example.invalid', 'test-account', 'test-jwt', 42, 'test-device-token']
    client.configure(*values)
    old = client._generation
    sock = FakeSocket()
    client._socket = sock
    values[index] = value
    client.configure(*values)
    assert sock.frames.get_nowait() is None  # Old recv was interrupted.
    assert client._generation == old + 1
    client._message('{"type":"ready","protocol":1}', old)
    assert not client._wake.is_set()


def test_device_snapshot_requires_matching_account_and_origin(agent, monkeypatch):
    device = agent._task_device
    device.identity = {'device_secret': 'test-secret', 'scope': device.scope}
    device.registered = {'id': 42}
    assert device.notification_identity('different-scope') is None
    assert device.notification_identity(device.scope) == (42, 'test-secret')
    client = TaskNotifications()
    monkeypatch.setattr(agent, '_task_notifications', client)
    monkeypatch.setattr(agent, '_token', 'test-jwt')
    monkeypatch.setattr(agent, '_restart_requested', False)
    agent._sync_task_notifications()
    assert client._snapshot is not None
    monkeypatch.setattr(agent, '_token', None)
    agent._sync_task_notifications()
    assert client._snapshot is None


def test_tls_and_frame_allocation_limit():
    sock = NotificationSocket()
    assert sock.sock_opt.sslopt['cert_reqs'] == ssl.CERT_REQUIRED
    assert sock.sock_opt.sslopt['check_hostname'] is True
    # Frame advertises 8192 bytes; reject before reading any payload.
    chunks = iter([b'\x81\x7e', b'\x20\x00'])
    sock.frame_buffer.recv = lambda length: next(chunks)
    with pytest.raises(websocket.WebSocketProtocolException):
        sock.recv_frame()


@pytest.mark.parametrize('server', ['https://user:secret@example.invalid', 'https://example.invalid?token=secret',
                                      'file:///etc/passwd', 'https://example.invalid/#secret'])
def test_reject_credential_urls(server):
    with pytest.raises(ValueError):
        notification_url(server, 1)


@pytest.mark.parametrize('status', [302, 404, 405, 426])
def test_redirect_or_unsupported_does_not_break_fallback(status):
    sock = FakeSocket(status)
    client = TaskNotifications(lambda: sock)
    configure(client)
    client.start()
    try:
        assert sock.connected.wait(1)
        assert sock.closed.wait(1)
        assert not client._wake.is_set()
        assert sock.options['redirect_limit'] == 0
    finally:
        client.stop()
    assert not client._thread.is_alive()


def test_bounded_pending_batches_and_log_bytes(agent, monkeypatch, tmp_path):
    monkeypatch.setattr(agent, '_save_pending_reports', lambda: None)
    monkeypatch.setattr(agent, '_save_pending_log_uploads', lambda: None)
    monkeypatch.setattr(agent, '_pending_reports', [{'run_id': i} for i in range(20)])
    calls = []
    monkeypatch.setattr(agent.requests, 'patch', lambda *a, **kw: calls.append(kw) or SimpleNamespace(status_code=200))
    agent._flush_pending_reports()
    assert len(calls) == agent.PENDING_RETRY_BATCH == 1
    assert len(agent._pending_reports) == 19
    monkeypatch.setattr(agent, '_pending_log_uploads', {i: 'fake' for i in range(20)})
    monkeypatch.setattr(agent, '_upload_log_delta', lambda *a, **kw: calls.append(a) or True)
    agent._flush_pending_log_uploads()
    assert len(calls) == 2
    assert len(agent._pending_log_uploads) == 19


def test_log_delta_bounded_and_retained_until_complete(agent, monkeypatch, tmp_path):
    path = tmp_path / 'large.log'
    path.write_bytes(b'a' * (agent.LOG_CHUNK_BYTES + 20))
    monkeypatch.setattr(agent, '_log_upload_offsets', {})
    chunks = []
    def post(*args, **kw):
        payload = kw['json']
        chunks.append(payload['content'])
        return SimpleNamespace(status_code=200, json=lambda: {'offset': payload['offset'] + len(payload['content'])})
    monkeypatch.setattr(agent.requests, 'post', post)
    assert agent._upload_log_delta(1, path, force=True) is False
    assert len(chunks[0]) == agent.LOG_CHUNK_BYTES
    assert agent._upload_log_delta(1, path, force=True) is True
    assert chunks[1] == 'a' * 20


def test_business_heartbeat_precedes_retries_and_failure_is_not_online(agent, monkeypatch):
    order = []
    monkeypatch.setattr(agent, '_token', 'mock')
    monkeypatch.setattr(agent, '_last_update_check_time', 10**12)
    monkeypatch.setattr(agent, '_last_settings_sync_time', 10**12)
    monkeypatch.setattr(agent, '_last_script_access_sync_time', 10**12)
    monkeypatch.setattr(agent, 'send_heartbeat', lambda: order.append('heartbeat') or False)
    for name in ('_flush_pending_reports', '_flush_pending_log_uploads', 'poll_and_execute'):
        monkeypatch.setattr(agent, name, lambda name=name: order.append(name))
    assert agent.agent_iteration('isolated', 'mock') is False
    assert order[0] == 'heartbeat'
    assert agent._last_online_time is None


@pytest.mark.parametrize('status,expected', [(404, 300), (405, 300), (426, 300), (302, 1)])
def test_capability_cooldown(status, expected, monkeypatch):
    from client.runtime import task_notifications as notifications
    client = TaskNotifications(lambda: FakeSocket(status))
    configure(client)
    delays = []
    def wait(delay=None):
        delays.append(delay)
        client.stop()
    monkeypatch.setattr(client._changed, 'wait', wait)
    monkeypatch.setattr(notifications.random, 'uniform', lambda low, high: high)
    client._run()
    assert delays == [expected]


def test_disconnect_backoff_is_jittered_capped_and_stability_resets(monkeypatch):
    from client.runtime import task_notifications as notifications
    sockets = []
    def factory():
        sock = FakeSocket()
        sock.abort()
        sockets.append(sock)
        return sock
    client = TaskNotifications(factory)
    configure(client)
    delays, bounds = [], []
    def jitter(low, high):
        bounds.append((low, high))
        return high
    def wait(delay=None):
        delays.append(delay)
        if len(delays) == 9:
            assert not client._wake.is_set()
            client.stop()
    ticks = iter([value for i in range(9) for value in (i * 100, i * 100 + (31 if i == 7 else 0))])
    monkeypatch.setattr(notifications.time, 'monotonic', lambda: next(ticks))
    monkeypatch.setattr(notifications.random, 'uniform', jitter)
    monkeypatch.setattr(client._changed, 'wait', wait)
    client._run()
    assert delays == [1, 2, 4, 8, 16, 32, 60, 1, 2]
    assert all(low == high / 2 and high <= 60 for low, high in bounds)
    assert all(sock.closed.is_set() for sock in sockets)


def test_silent_half_open_connection_reconnects(monkeypatch):
    from client.runtime import task_notifications as notifications
    sock = FakeSocket()
    def timeout():
        raise websocket.WebSocketTimeoutException('silent')
    monkeypatch.setattr(sock, 'recv_frame', timeout)
    client = TaskNotifications(lambda: sock)
    configure(client)
    ticks = iter([0, 76, 76])
    monkeypatch.setattr(notifications.time, 'monotonic', lambda: next(ticks))
    delays = []
    monkeypatch.setattr(client._changed, 'wait', lambda delay: (delays.append(delay), client.stop()))
    client._run()
    assert sock.closed.is_set()
    assert len(delays) == 1


def test_wait_consumes_burst_before_http_and_retains_hint_during_http():
    client = TaskNotifications()
    for _ in range(100):
        client.wake()
    client.wait(0, minimum=0)
    assert not client._wake.is_set()
    client.wake()  # HTTP work has begun: retained until the following wait.
    assert client._wake.is_set()
    client.wait(0, minimum=0)
    assert not client._wake.is_set()
