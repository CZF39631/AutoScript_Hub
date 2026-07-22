import json

from shared import version
from shared.version import DEV_VERSION, RELEASE_VERSION, get_channel, get_version


def test_release_and_development_versions_share_the_0_9_base():
    assert RELEASE_VERSION == "0.9.0"
    assert DEV_VERSION == RELEASE_VERSION + "-dev"


def test_version_comes_from_environment_and_strips_tag_prefix(monkeypatch):
    monkeypatch.setenv("AUTOSCRIPT_VERSION", "v0.9.1")

    assert get_version() == "0.9.1"


def test_invalid_version_falls_back_to_development_version(monkeypatch):
    monkeypatch.setenv("AUTOSCRIPT_VERSION", "release-candidate")

    assert get_version() == DEV_VERSION


def test_channel_can_be_explicit_or_derived(monkeypatch):
    monkeypatch.setenv("AUTOSCRIPT_VERSION", "1.0.0")
    monkeypatch.delenv("AUTOSCRIPT_CHANNEL", raising=False)
    assert get_channel() == "stable"

    monkeypatch.setenv("AUTOSCRIPT_CHANNEL", "beta")
    assert get_channel() == "beta"

    monkeypatch.setenv("AUTOSCRIPT_CHANNEL", "nightly")
    assert get_channel() == "stable"


def test_baked_server_build_identity_wins_over_runtime_environment(monkeypatch, tmp_path):
    build_info = tmp_path / "autoscript-build.json"
    build_info.write_text(
        json.dumps({"version": "0.9.1", "channel": "beta"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(version, "_BUILD_INFO_PATH", build_info, raising=False)
    monkeypatch.setenv("AUTOSCRIPT_VERSION", "0.9.0")
    monkeypatch.setenv("AUTOSCRIPT_CHANNEL", "stable")

    assert get_version() == "0.9.1"
    assert get_channel() == "beta"
