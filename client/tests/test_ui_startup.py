import errno

from client.ui import main as ui


def test_local_server_uses_next_port_when_default_is_unavailable(monkeypatch):
    attempts = []

    class FakeServer:
        def __init__(self, address, _handler):
            attempts.append(address[1])
            if address[1] == 18081:
                raise OSError(errno.EACCES, "port unavailable")

        def serve_forever(self):
            pass

    class FakeThread:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            pass

    monkeypatch.setattr(ui, "HTTPServer", FakeServer)
    monkeypatch.setattr(ui.threading, "Thread", FakeThread)
    monkeypatch.setattr(ui, "get_or_create_agent_token", lambda: "token")

    assert ui.start_local_server("http://lan:8000") == 18082
    assert attempts == [18081, 18082]


def test_first_run_finishes_wizard_before_starting_the_main_webview(monkeypatch):
    events = []
    monkeypatch.setattr(ui, "is_setup_complete", lambda: False)
    monkeypatch.setattr("client.ui.wizard.run_wizard", lambda: events.append("wizard"))
    monkeypatch.setattr(ui, "start_local_server", lambda *_: events.append("server"))
    monkeypatch.setattr(ui.webview, "start", lambda: events.append("main-webview"))

    assert ui.start_ui() is False
    assert events == ["wizard"]


def test_configured_client_starts_one_main_webview(monkeypatch):
    events = []
    loaded_callbacks = []

    class LoadedEvent:
        def __iadd__(self, callback):
            loaded_callbacks.append(callback)
            return self

    class Window:
        class Events:
            loaded = LoadedEvent()

        events = Events()

    window = Window()
    monkeypatch.setattr(ui, "is_setup_complete", lambda: True)
    monkeypatch.setattr(ui, "load_config", lambda: {"server_url": "http://lan:8000"})
    monkeypatch.setattr(
        ui, "start_local_server", lambda url: events.append(("server", url)) or 18082
    )
    monkeypatch.setattr(
        ui.webview,
        "create_window",
        lambda *args, **kwargs: events.append(("window", args[1])) or window,
    )

    def start_webview():
        events.append("main-webview")
        assert len(loaded_callbacks) == 1
        loaded_callbacks[0]()

    monkeypatch.setattr(ui.webview, "start", start_webview)

    assert ui.start_ui(
        on_started=lambda: events.append("loaded"),
        on_closed=lambda: events.append("closed"),
    ) is True
    assert events == [
        ("server", "http://lan:8000"),
        ("window", "http://127.0.0.1:18082/"),
        "main-webview",
        "loaded",
        "closed",
    ]
