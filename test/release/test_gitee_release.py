from pathlib import Path

import pytest

from release.scripts import gitee_release


class FakeResponse:
    def __init__(self, payload=None):
        self.payload = payload or {}
        self.content = b"{}" if payload is not None else b""

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_create_returns_numeric_release_id_and_followups_use_it(tmp_path, monkeypatch):
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if method == "POST" and url.endswith("/releases"):
            return FakeResponse({"id": 314, "tag_name": "v0.9.0"})
        return FakeResponse({})

    monkeypatch.setattr(gitee_release.requests, "request", fake_request)
    asset = tmp_path / "asset.zip"
    asset.write_bytes(b"asset")

    release_id = gitee_release.create_release("owner", "repo", "token", "v0.9.0", "body")
    gitee_release.upload_files("owner", "repo", "token", release_id, [asset])
    gitee_release.publish_release("owner", "repo", "token", release_id, prerelease=True)
    gitee_release.delete_release("owner", "repo", "token", release_id)

    assert release_id == "314"
    assert calls[1][0:2] == (
        "POST",
        "https://gitee.com/api/v5/repos/owner/repo/releases/314/attach_files",
    )
    assert calls[2][0:2] == (
        "PATCH",
        "https://gitee.com/api/v5/repos/owner/repo/releases/314",
    )
    assert calls[2][2]["data"]["prerelease"] == "true"
    assert calls[3][0:2] == (
        "DELETE",
        "https://gitee.com/api/v5/repos/owner/repo/releases/314",
    )
    assert all("/releases/v0.9.0" not in url for _, url, _ in calls)


def test_create_rejects_response_without_release_id(monkeypatch):
    monkeypatch.setattr(
        gitee_release.requests,
        "request",
        lambda *args, **kwargs: FakeResponse({"tag_name": "v0.9.0"}),
    )

    with pytest.raises(RuntimeError, match="release id"):
        gitee_release.create_release("owner", "repo", "token", "v0.9.0", "body")


def test_release_workflow_passes_created_gitee_release_id():
    workflow = (Path(__file__).resolve().parents[2] / ".github/workflows/release.yml").read_text("utf-8")

    assert "id: release_hosts" in workflow
    assert "gitee_release_id=" in workflow
    assert '--release-id "$GITEE_RELEASE_ID"' in workflow
    assert "steps.release_hosts.outputs.gitee_release_id" in workflow
    assert 'GH_PRERELEASE=(--prerelease)' in workflow
    assert '--prerelease "$GITEE_PRERELEASE"' in workflow
    assert "verify_release_mirrors.py" in workflow
    assert "if: failure()" in workflow
    assert "gitee_release.py delete" in workflow
    assert "gh release delete" in workflow


def test_release_workflow_allows_github_only_when_gitee_is_not_configured():
    workflow = (Path(__file__).resolve().parents[2] / ".github/workflows/release.yml").read_text("utf-8")

    assert "GITEE_ENABLED" in workflow
    assert 'if [[ "$GITEE_ENABLED" == "true" ]]' in workflow
    assert "Require signing secret" in workflow
    assert "Require release secrets" not in workflow
