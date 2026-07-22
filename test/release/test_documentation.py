from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_readme_links_all_09_entrypoints():
    readme = _read("README.md")

    assert "docker compose" in readme
    assert "192.168" in readme
    assert "AutoScript-Hub-Setup-<version>.exe" in readme
    assert "Python 3.11.9" in readme
    assert "skills/autoscript-script-authoring" in readme
    assert "docs/0.9-deployment-runbook.md" in readme
    assert "docs/0.9-release-guide.md" in readme


def test_deployment_runbook_covers_operations_and_health():
    runbook = _read("docs/0.9-deployment-runbook.md")

    for command in ("backup.sh", "restore.sh", "upgrade.sh", "rollback.sh", "docker compose logs", "/api/health/ready"):
        assert command in runbook
    assert "linux/arm64" in runbook
    assert "linux/amd64" in runbook
    assert "AUTOSCRIPT_BASE_REGISTRY" in runbook
    assert "AUTOSCRIPT_SKIP_PULL" in runbook
    assert "完整源码仓库" in runbook


def test_release_guide_covers_assets_signing_hosts_and_promotion():
    guide = _read("docs/0.9-release-guide.md")

    for item in (
        "UPDATE_PRIVATE_KEY_B64",
        "GITEE_TOKEN",
        "AutoScript-Hub-Setup-<version>.exe",
        "autoscript-hub-update.json.sig",
        "SHA256SUMS.txt",
        "v0.9.0",
        "v1.0.0",
    ):
        assert item in guide
