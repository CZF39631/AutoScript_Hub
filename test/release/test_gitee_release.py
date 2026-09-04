from pathlib import Path

import pytest
import requests

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
        if method == "GET" and url.endswith("/releases/314"):
            return FakeResponse({"tag_name": "v0.9.0", "name": "v0.9.0", "body": "body"})
        return FakeResponse({})

    monkeypatch.setattr(gitee_release.requests, "request", fake_request)
    asset = tmp_path / "asset.zip"
    asset.write_bytes(b"asset")

    release_id = gitee_release.create_release(
        "owner", "repo", "token", "v0.9.0", "body", "commit-sha"
    )
    gitee_release.upload_files("owner", "repo", "token", release_id, [asset])
    gitee_release.publish_release("owner", "repo", "token", release_id, prerelease=True)
    gitee_release.delete_release("owner", "repo", "token", release_id)

    assert release_id == "314"
    assert calls[0][2]["data"]["target_commitish"] == "commit-sha"
    upload_calls = [call for call in calls if call[0] == "POST" and call[1].endswith("/attach_files")]
    assert len(upload_calls) == 1
    assert upload_calls[0][2]["timeout"] == 180
    release_gets = [call for call in calls if call[0] == "GET" and call[1].endswith("/releases/314")]
    assert release_gets
    assert all(call[2]["params"]["access_token"] == "token" for call in release_gets)
    patch = next(call for call in calls if call[0] == "PATCH")
    assert patch[2]["data"]["prerelease"] == "true"
    assert patch[2]["data"]["tag_name"] == "v0.9.0"
    assert patch[2]["data"]["body"] == "body"
    assert any(call[0] == "DELETE" and call[1].endswith("/releases/314") for call in calls)
    assert all("/releases/v0.9.0" not in url for _, url, _ in calls)


def test_upload_timeout_is_treated_as_success_when_asset_appears(tmp_path, monkeypatch):
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if method == "POST":
            raise requests.Timeout("response lost")
        uploaded = any(call[0] == "POST" for call in calls)
        return FakeResponse({"assets": [{"name": "asset.bin"}]} if uploaded else {"assets": []})

    monkeypatch.setattr(gitee_release.requests, "request", fake_request)
    asset = tmp_path / "asset.bin"
    asset.write_bytes(b"asset")

    gitee_release.upload_files("owner", "repo", "token", "314", [asset], retry_delay=0)

    assert len([call for call in calls if call[0] == "POST"]) == 1


def test_create_rejects_response_without_release_id(monkeypatch):
    monkeypatch.setattr(
        gitee_release.requests,
        "request",
        lambda *args, **kwargs: FakeResponse({"tag_name": "v0.9.0"}),
    )

    with pytest.raises(RuntimeError, match="release id"):
        gitee_release.create_release(
            "owner", "repo", "token", "v0.9.0", "body", "commit-sha"
        )


def test_release_workflow_passes_created_gitee_release_id():
    workflow = (Path(__file__).resolve().parents[2] / ".github/workflows/release.yml").read_text("utf-8")

    assert "id: release_hosts" in workflow
    assert 'gh release create "$GITHUB_REF_NAME" release-output/*.exe release-output/*.zip' in workflow
    assert "gitee_release_id=" in workflow
    assert '--target-commitish "$GITEE_TARGET_COMMIT"' in workflow
    assert 'for file in release-output/*.zip' in workflow
    assert "release-output/parts/*" not in workflow
    assert 'GITEE_FILES+=(--file "$file")' in workflow
    assert '"${GITEE_FILES[@]}"' in workflow
    assert "release-output/*.exe release-output/*.zip)" not in workflow
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
