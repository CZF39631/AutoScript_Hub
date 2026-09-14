"""Isolated loopback TLS and background reconnect acceptance; no Agent or task HTTP."""
import datetime
import ipaddress
import json
import socket
import ssl
import threading
import time
from contextlib import contextmanager

import pytest
import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from client.runtime.task_notifications import NotificationSocket, TaskNotifications


@pytest.fixture
def tls_files(tmp_path):
    now = datetime.datetime.now(datetime.timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Loopback test CA')])
    ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name)
          .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(now - datetime.timedelta(minutes=1))
          .not_valid_after(now + datetime.timedelta(days=1))
          .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
          .sign(ca_key, hashes.SHA256()))
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Loopback test')]))
            .issuer_name(ca_name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=1))
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.SubjectAlternativeName([
                x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), critical=False)
            .sign(ca_key, hashes.SHA256()))
    paths = [tmp_path / name for name in ('ca.pem', 'server.pem', 'server-key.pem')]
    paths[0].write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    paths[1].write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    paths[2].write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                         serialization.PrivateFormat.PKCS8,
                                         serialization.NoEncryption()))
    return paths


@contextmanager
def loopback_server(app, tls_files):
    _, cert, key = tls_files
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen()
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(
        app, log_level='error', lifespan='off', ws='websockets',
        ssl_certfile=str(cert), ssl_keyfile=str(key), timeout_graceful_shutdown=2))
    thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and time.monotonic() < deadline:
            threading.Event().wait(.01)
        assert server.started, 'loopback TLS server failed to start'
        yield f'https://127.0.0.1:{port}'
    finally:
        server.should_exit = True
        thread.join(5)
        listener.close()
        assert not thread.is_alive(), 'loopback TLS server leaked a thread'


def trusted_socket(ca):
    connection = NotificationSocket()
    connection.sock_opt.sslopt['ca_certs'] = str(ca)
    assert connection.sock_opt.sslopt['cert_reqs'] == ssl.CERT_REQUIRED
    assert connection.sock_opt.sslopt['check_hostname'] is True
    return connection


def test_wss_unknown_ca_rejected_and_explicit_ca_accepted(tls_files, monkeypatch):
    monkeypatch.setenv('NO_PROXY', '127.0.0.1,localhost')
    monkeypatch.setenv('no_proxy', '127.0.0.1,localhost')
    accepted = []

    async def app(scope, receive, send):
        assert scope['type'] == 'websocket'
        assert (await receive())['type'] == 'websocket.connect'
        accepted.append(scope['path'])
        await send({'type': 'websocket.accept'})
        await send({'type': 'websocket.send', 'text': '{"type":"ready","protocol":1}'})
        await receive()

    with loopback_server(app, tls_files) as origin:
        url = origin.replace('https:', 'wss:') + '/events'
        untrusted = NotificationSocket()
        try:
            with pytest.raises(ssl.SSLCertVerificationError):
                untrusted.connect(url, timeout=3, suppress_origin=True, redirect_limit=0,
                                  http_no_proxy=['127.0.0.1', 'localhost'])
        finally:
            untrusted.shutdown()
        assert accepted == [], 'untrusted TLS must fail before ASGI upgrade'
        wrong_host = trusted_socket(tls_files[0])
        try:
            with pytest.raises(ssl.SSLCertVerificationError):
                wrong_host.connect(url.replace('127.0.0.1', 'localhost'), timeout=3,
                                   suppress_origin=True, redirect_limit=0,
                                   http_no_proxy=['127.0.0.1', 'localhost'])
        finally:
            wrong_host.shutdown()
        assert accepted == [], 'trusted CA does not waive hostname verification'
        trusted = trusted_socket(tls_files[0])
        try:
            trusted.connect(url, timeout=3, suppress_origin=True, redirect_limit=0,
                            http_no_proxy=['127.0.0.1', 'localhost'])
            assert trusted.handshake_response.status == 101
            assert json.loads(trusted.recv()) == {'type': 'ready', 'protocol': 1}
            assert accepted == ['/events']
        finally:
            trusted.shutdown()


def test_background_wss_reconnect_after_1012_and_stop(tls_files, monkeypatch):
    monkeypatch.setenv('NO_PROXY', '127.0.0.1,localhost')
    monkeypatch.setenv('no_proxy', '127.0.0.1,localhost')
    first_ready, second_ready = threading.Event(), threading.Event()
    accepted, received, http_requests, closed = [], [], [], []

    async def app(scope, receive, send):
        if scope['type'] == 'http':
            http_requests.append(scope['path'])
            await send({'type': 'http.response.start', 'status': 405})
            await send({'type': 'http.response.body', 'body': b''})
            return
        assert scope['type'] == 'websocket'
        assert (await receive())['type'] == 'websocket.connect'
        accepted.append(scope['path'])
        await send({'type': 'websocket.accept'})
        await send({'type': 'websocket.send', 'text': '{"type":"ready","protocol":1}'})
        if len(accepted) == 1:
            await send({'type': 'websocket.close', 'code': 1012})
            closed.append(1012)
        else:
            assert (await receive())['type'] == 'websocket.disconnect'

    class ObservedNotifications(TaskNotifications):
        def _message(self, data, generation):
            super()._message(data, generation)
            received.append(json.loads(data))
            if len(received) == 1:
                first_ready.set()
            elif len(received) == 2:
                second_ready.set()

    sockets = []

    def factory():
        connection = trusted_socket(tls_files[0])
        sockets.append(connection)
        return connection

    notifications = ObservedNotifications(socket_factory=factory)
    with loopback_server(app, tls_files) as origin:
        try:
            notifications.configure(server=origin, account='synthetic', jwt='synthetic-jwt',
                                    device_id=17, device_token='synthetic-device-token')
            notifications.start()
            assert first_ready.wait(5), 'first ready not consumed by background thread'
            assert second_ready.wait(8), 'no automatic reconnect ready after close 1012'
            assert notifications._wake.is_set()
            assert received == [{'type': 'ready', 'protocol': 1}] * 2
            assert accepted == ['/api/task-devices/17/events'] * 2
            assert closed == [1012]
            assert len(sockets) == 2
            assert all(item.handshake_response.status == 101 for item in sockets)
        finally:
            notifications.stop()
            assert notifications._thread is not None
            assert not notifications._thread.is_alive(), 'notification worker leaked a thread'
            assert notifications._socket is None
            assert all(item.sock is None for item in sockets)
    assert http_requests == [], 'notification reconnect must not issue task HTTP actions'
