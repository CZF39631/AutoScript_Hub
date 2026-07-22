import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace


def _load_entry(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "autoscript_build_info",
        SimpleNamespace(CHANNEL="beta", VERSION="0.9.0"),
    )
    path = Path(__file__).resolve().parents[2] / "release" / "windows" / "entry_ui.py"
    spec = importlib.util.spec_from_file_location("autoscript_entry_ui_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_startup_confirmation_does_not_write_marker_until_matching_agent_is_ready(
    tmp_path, monkeypatch
):
    entry = _load_entry(monkeypatch)
    events = []
    paths = SimpleNamespace(updates_dir=tmp_path, install_dir=tmp_path)

    result = entry._confirm_startup(
        paths,
        "0.9.0",
        start_agent=lambda _: events.append("agent-started"),
        wait_for_agent=lambda version: events.append(("agent-wait", version)) or False,
        marker_writer=lambda *_: events.append("marker"),
    )

    assert result is False
    assert events == ["agent-started", ("agent-wait", "0.9.0")]


def test_startup_confirmation_writes_marker_after_matching_agent_is_ready(tmp_path, monkeypatch):
    entry = _load_entry(monkeypatch)
    events = []
    paths = SimpleNamespace(updates_dir=tmp_path, install_dir=tmp_path)

    result = entry._confirm_startup(
        paths,
        "0.9.0",
        start_agent=lambda _: events.append("agent-started"),
        wait_for_agent=lambda version: events.append(("agent-wait", version)) or True,
        marker_writer=lambda _, version: events.append(("marker", version)),
    )

    assert result is True
    assert events == ["agent-started", ("agent-wait", "0.9.0"), ("marker", "0.9.0")]
