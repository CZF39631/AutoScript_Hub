from client.agent import updater


class _Store:
    def __init__(self, state):
        self.state = state

    def read(self):
        return dict(self.state)


class _Service:
    def __init__(self, state="idle"):
        self.store = _Store({"state": state, "version": "0.9.1"})
        self.runtime_is_idle = None
        self.calls = []
        self.manifest = object() if state == "available" else None
        self.installer = None

    def check(self):
        self.calls.append("check")
        self.store.state["state"] = "available"
        self.manifest = object()
        return type("Result", (), {"state": "available"})()

    def download(self):
        self.calls.append("download")
        self.store.state["state"] = "verified"
        return type("Result", (), {"state": "verified"})()

    def request_install(self):
        self.calls.append("request_install")
        self.store.state["state"] = "installing"
        return type("Result", (), {"state": "installing"})()


def test_check_update_only_discovers_manifest(monkeypatch):
    service = _Service()
    monkeypatch.setattr(updater, "_service", lambda *args, **kwargs: service)
    monkeypatch.setattr(updater, "get_update_status", lambda: service.store.read())

    result = updater.check_and_stage_update("0.9.0")

    assert result["state"] == "available"
    assert service.calls == ["check"]


def test_explicit_install_downloads_then_requests_install(monkeypatch):
    service = _Service(state="available")
    monkeypatch.setattr(updater, "_active_service", service)
    monkeypatch.setattr(updater, "get_update_status", lambda: service.store.read())

    result = updater.install_staged_update("0.9.0")

    assert result["state"] == "installing"
    assert service.calls == ["download", "request_install"]


def test_explicit_install_recovers_available_manifest_before_download(monkeypatch):
    service = _Service(state="available")
    service.manifest = None
    monkeypatch.setattr(updater, "_active_service", None)
    monkeypatch.setattr(updater, "_service", lambda *args, **kwargs: service)
    monkeypatch.setattr(updater, "get_update_status", lambda: service.store.read())

    result = updater.install_staged_update("0.9.0")

    assert result["state"] == "installing"
    assert service.calls == ["check", "download", "request_install"]
