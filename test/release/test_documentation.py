from pathlib import Path
import re
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[2]


def _read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_bilingual_readmes_link_current_delivery_and_development_entrypoints():
    chinese, english = _read("README.md"), _read("README.en.md")
    assert "[English](README.en.md)" in chinese
    assert "[简体中文](README.md)" in english
    for readme in (chinese, english):
        for entry in (
            "docker compose", "/api/health/ready", "AutoScript-Hub-Setup-1.2.4.exe",
            "Python 3.11", "skills/autoscript-script-authoring", "docs/0.9-deployment-runbook.md",
            "docs/releases/v1.2.4-发布记录.md", "docs/Preview安装与数据隔离.md",
            "docs/多语言支持.md", "AUTOSCRIPT_CLIENT_DATA_DIR", "DATABASE_URL", "MIT",
        ):
            assert entry in readme
        assert "-m client.start <" not in readme  # Do not recommend password-bearing CLI arguments.
        assert "-AsSecureString" in readme


def test_bilingual_readme_links_exist_and_share_the_same_release_targets():
    release_targets = []
    for filename in ("README.md", "README.en.md"):
        links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", _read(filename))
        release_targets.append({link for link in links if "/releases/tag/" in link})
        for link in links:
            parsed = urlsplit(link)
            if parsed.scheme in ("https", "http"):
                continue
            assert not parsed.scheme and not parsed.netloc, link
            target = (ROOT / unquote(parsed.path)).resolve()
            assert target.is_relative_to(ROOT), link
            assert target.is_file(), link
    assert release_targets[0] and release_targets[0] == release_targets[1]


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
