"""Optional WS hints only: HTTP remains the authoritative task transport."""
import json
import random
import ssl
import threading
import time
from urllib.parse import urlsplit, urlunsplit

import websocket
from websocket._abnf import frame_buffer

MAX_MESSAGE_BYTES = 4096
STALE_CONNECTION_SECONDS = 75


class _BoundedFrames(frame_buffer):
    def recv_length(self):
        super().recv_length()
        if self.length > MAX_MESSAGE_BYTES:
            raise websocket.WebSocketProtocolException('notification frame too large')


class NotificationSocket(websocket.WebSocket):
    def __init__(self):
        super().__init__(sslopt={'cert_reqs': ssl.CERT_REQUIRED, 'check_hostname': True},
                         enable_multithread=True)
        self.frame_buffer = _BoundedFrames(self._recv, False)


def notification_url(server, device_id):
    value = urlsplit(server)
    if (value.scheme not in ('http', 'https') or not value.hostname or value.username
            or value.password or value.query or value.fragment or type(device_id) is not int):
        raise ValueError('invalid notification origin')
    return urlunsplit(('wss' if value.scheme == 'https' else 'ws', value.netloc,
                      value.path.rstrip('/') + '/api/task-devices/' + str(device_id) + '/events', '', ''))


class TaskNotifications:
    def __init__(self, socket_factory=NotificationSocket):
        self._factory = socket_factory
        self._lock = threading.RLock()
        self._changed = threading.Event()
        self._wake = threading.Event()
        self._stop_event = threading.Event()
        self._snapshot = None
        self._generation = 0
        self._socket = None
        self._stopped = False
        self._thread = None

    def start(self):
        with self._lock:
            if self._thread is None and not self._stopped:
                self._thread = threading.Thread(target=self._run, name='task-notifications', daemon=True)
                self._thread.start()

    def configure(self, server=None, account=None, jwt=None, device_id=None, device_token=None):
        snapshot = (server, account, jwt, device_id, device_token) if jwt and device_id and device_token else None
        with self._lock:
            if snapshot == self._snapshot:
                return
            self._snapshot = snapshot
            self._generation += 1
            sock = self._socket
            self._changed.set()
            if sock is not None:
                sock.abort()  # Interrupt recv; never wait for a peer close handshake.

    def wake(self):
        with self._lock:
            self._wake.set()

    def wait(self, timeout, minimum=0.5):
        # Consume BEFORE the next HTTP iteration, never after it. A hint arriving
        # during HTTP is retained; bursts collapse into one iteration.
        started = time.monotonic()
        self._wake.wait(timeout)
        remaining = minimum - (time.monotonic() - started)
        if remaining > 0:
            self._stop_event.wait(remaining)
        with self._lock:
            self._wake.clear()

    def stop(self):
        with self._lock:
            self._stopped = True
            self._stop_event.set()
            self._generation += 1
            self._changed.set()
            self._wake.set()
            if self._socket is not None:
                self._socket.abort()
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=6)

    def _message(self, data, generation):
        if not isinstance(data, (str, bytes)) or len(data) > MAX_MESSAGE_BYTES:
            return
        try:
            message = json.loads(data)
        except (ValueError, UnicodeError):
            return
        if (not isinstance(message, dict) or type(message.get('protocol')) is not int
                or message['protocol'] != 1 or message.get('type') not in ('ready', 'sync_required')):
            return
        with self._lock:
            if not self._stopped and generation == self._generation:
                self._wake.set()

    def _run(self):
        backoff = 1.0
        previous_generation = -1
        while True:
            with self._lock:
                if self._stopped:
                    return
                snapshot, generation = self._snapshot, self._generation
                self._changed.clear()
            if generation != previous_generation:
                backoff = 1.0
                previous_generation = generation
            if snapshot is None:
                self._changed.wait()
                continue
            sock = None
            connected_at = None
            cooldown = False
            try:
                server, account, jwt, device_id, token = snapshot
                url = notification_url(server, device_id)
                if any(c in jwt + token for c in '\r\n'):
                    raise ValueError('invalid credential header')
                sock = self._factory()
                with self._lock:
                    if generation != self._generation or self._stopped:
                        continue
                    self._socket = sock
                sock.connect(url, header={'Authorization': 'Bearer ' + jwt, 'X-Device-Token': token},
                             timeout=5, redirect_limit=0, suppress_origin=True)
                # websocket-client considers an un-followed redirect connected.
                status = sock.handshake_response.status
                if status != 101:
                    cooldown = status in (404, 405, 426)
                    raise ValueError('notification upgrade rejected')
                connected_at = time.monotonic()
                last_received = connected_at
                while True:
                    with self._lock:
                        if self._stopped or generation != self._generation:
                            break
                    try:
                        frame = sock.recv_frame()
                    except websocket.WebSocketTimeoutException:
                        if time.monotonic() - last_received >= STALE_CONNECTION_SECONDS:
                            raise TimeoutError('notification connection stale')
                        continue
                    last_received = time.monotonic()
                    # No fragmented-message accumulation: hints are tiny JSON frames.
                    if not frame.fin or frame.opcode == websocket.ABNF.OPCODE_CONT:
                        raise ValueError('fragmented notification')
                    if frame.opcode == websocket.ABNF.OPCODE_CLOSE:
                        break
                    if frame.opcode == websocket.ABNF.OPCODE_PING:
                        sock.pong(frame.data)
                    elif frame.opcode == websocket.ABNF.OPCODE_TEXT:
                        self._message(frame.data, generation)
            except websocket.WebSocketBadStatusException as exc:
                cooldown = exc.status_code in (404, 405, 426)
            except Exception:
                pass  # Optional hints never change HTTP connectivity or expose secrets.
            finally:
                if sock is not None:
                    try:
                        sock.shutdown()
                    except Exception:
                        pass
                with self._lock:
                    if self._socket is sock:
                        self._socket = None
            if connected_at is not None and time.monotonic() - connected_at >= 30:
                backoff = 1.0
            delay = 300 if cooldown else random.uniform(backoff / 2, backoff)
            backoff = min(60, backoff * 2)
            self._changed.wait(delay)
