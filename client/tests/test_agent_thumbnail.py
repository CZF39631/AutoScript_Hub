from types import SimpleNamespace

import pytest

from client.agent import main as agent
from client.agent import thumbnail


def test_capture_fails_closed_when_desktop_is_locked_before_capture(monkeypatch):
    grabbed = []
    monkeypatch.setattr(thumbnail, "desktop_is_interactive", lambda: False)
    monkeypatch.setattr(thumbnail, "_grab_primary_screen", lambda: grabbed.append(True))

    with pytest.raises(thumbnail.DesktopUnavailable):
        thumbnail.capture_thumbnail()

    assert grabbed == []


def test_capture_discards_bytes_when_desktop_locks_during_capture(monkeypatch):
    states = iter([True, False])
    image = object()
    monkeypatch.setattr(thumbnail, "desktop_is_interactive", lambda: next(states))
    monkeypatch.setattr(thumbnail, "_grab_primary_screen", lambda: image)
    monkeypatch.setattr(thumbnail, "_encode_jpeg", lambda value: b"jpeg" if value is image else b"")

    with pytest.raises(thumbnail.DesktopUnavailable):
        thumbnail.capture_thumbnail()


def test_in_memory_encoder_resizes_and_bounds_jpeg_without_disk_io():
    from PIL import Image

    source = Image.new("RGB", (1600, 900), (24, 64, 96))
    payload = thumbnail._encode_jpeg(source)

    assert payload.startswith(b"\xff\xd8")
    assert len(payload) <= thumbnail.MAX_THUMBNAIL_BYTES
    with Image.open(__import__("io").BytesIO(payload)) as encoded:
        assert encoded.format == "JPEG"
        assert max(encoded.size) == thumbnail.MAX_THUMBNAIL_EDGE


def test_managed_thumbnail_upload_uses_both_credentials_and_raw_jpeg(monkeypatch):
    calls = []
    clock = iter([100.0, 101.0])

    class Response:
        status_code = 200

    monkeypatch.setattr(agent, "_client_config", {"client_mode": "managed"})
    monkeypatch.setattr(agent, "_agent_id", 17)
    monkeypatch.setattr(agent, "_token", "bearer-secret")
    monkeypatch.setattr(agent, "_agent_token", "device-secret")
    monkeypatch.setattr(agent, "_last_thumbnail_attempt_at", None)
    monkeypatch.setattr(agent, "_last_thumbnail_success_at", None)
    monkeypatch.setattr(agent.time, "time", lambda: next(clock))
    monkeypatch.setattr(agent, "capture_thumbnail", lambda: b"\xff\xd8mock-jpeg\xff\xd9")
    monkeypatch.setattr(
        agent.requests,
        "post",
        lambda url, **kwargs: calls.append((url, kwargs)) or Response(),
    )

    assert agent._attempt_thumbnail_upload() is True
    assert agent._last_thumbnail_attempt_at == 100.0
    assert agent._last_thumbnail_success_at == 101.0
    assert calls == [(
        "{}/api/agents/17/thumbnail".format(agent.BACKEND_URL),
        {
            "data": b"\xff\xd8mock-jpeg\xff\xd9",
            "headers": {
                "Authorization": "Bearer bearer-secret",
                "X-Agent-Token": "device-secret",
                "Content-Type": "image/jpeg",
            },
            "timeout": agent.THUMBNAIL_UPLOAD_TIMEOUT_SEC,
            "allow_redirects": False,
        },
    )]


def test_thumbnail_upload_failure_is_contained_and_preserves_last_success(monkeypatch):
    monkeypatch.setattr(agent, "_client_config", {"client_mode": "managed"})
    monkeypatch.setattr(agent, "_agent_id", 17)
    monkeypatch.setattr(agent, "_token", "bearer-secret")
    monkeypatch.setattr(agent, "_agent_token", "device-secret")
    monkeypatch.setattr(agent, "_last_thumbnail_success_at", 88.0)
    monkeypatch.setattr(agent, "capture_thumbnail", lambda: b"jpeg")
    monkeypatch.setattr(
        agent.requests,
        "post",
        lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("offline")),
    )

    assert agent._attempt_thumbnail_upload() is False
    assert agent._last_thumbnail_success_at == 88.0


def test_thumbnail_failure_is_contained_and_does_not_post(monkeypatch):
    posts = []
    monkeypatch.setattr(agent, "_client_config", {"client_mode": "managed"})
    monkeypatch.setattr(agent, "_agent_id", 17)
    monkeypatch.setattr(agent, "_token", "bearer-secret")
    monkeypatch.setattr(agent, "_agent_token", "device-secret")
    monkeypatch.setattr(agent, "_last_thumbnail_success_at", 88.0)
    monkeypatch.setattr(agent, "capture_thumbnail", lambda: (_ for _ in ()).throw(OSError("locked")))
    monkeypatch.setattr(agent.requests, "post", lambda *args, **kwargs: posts.append(True))

    assert agent._attempt_thumbnail_upload() is False
    assert agent._last_thumbnail_success_at == 88.0
    assert posts == []


def test_thumbnail_worker_is_managed_only_and_daemonized(monkeypatch):
    started = []

    class FakeThread:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def is_alive(self):
            return False

        def start(self):
            started.append(self.kwargs)

    monkeypatch.setattr(agent.threading, "Thread", FakeThread)
    monkeypatch.setattr(agent, "_thumbnail_worker", None)
    monkeypatch.setattr(agent, "_client_config", {"client_mode": "standard"})
    assert agent._start_thumbnail_worker() is None
    assert started == []

    monkeypatch.setattr(agent, "_client_config", {"client_mode": "managed"})
    worker = agent._start_thumbnail_worker()
    assert worker is agent._thumbnail_worker
    assert started[0]["daemon"] is True
    assert started[0]["name"] == "managed-thumbnail-worker"
    assert started[0]["target"] is agent._thumbnail_worker_loop


def test_thumbnail_worker_waits_sixty_seconds_between_attempts(monkeypatch):
    attempts = []
    waits = []
    stop_event = SimpleNamespace(wait=lambda seconds: waits.append(seconds) or True)
    monkeypatch.setattr(agent, "_attempt_thumbnail_upload", lambda: attempts.append(True))

    agent._thumbnail_worker_loop(stop_event)

    assert attempts == [True]
    assert waits == [60]
