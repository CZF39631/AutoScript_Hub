from client.agent import notifier


def test_powershell_quote_escapes_single_quotes():
    assert notifier._powershell_quote("部门 A's 脚本") == "'部门 A''s 脚本'"


def test_notification_dispatch_is_non_blocking(monkeypatch):
    calls = []

    class FakeThread:
        def __init__(self, *, target, args, name, daemon):
            calls.append((target, args, name, daemon))

        def start(self):
            calls.append("started")

    monkeypatch.setattr(notifier.threading, "Thread", FakeThread)

    assert notifier.show_system_notification("AutoScript Hub", "执行完成") is True
    assert calls[0][1] == ("AutoScript Hub", "执行完成")
    assert calls[0][2:] == ("autoscript-notification", True)
    assert calls[1] == "started"
