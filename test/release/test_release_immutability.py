"""正式发布失败时保留资产，不允许自动删除或覆盖。"""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_release_workflow_preserves_existing_assets_on_failure():
    workflow = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text("utf-8"))
    steps = workflow["jobs"]["publish"]["steps"]
    commands = "\n".join(step.get("run", "") for step in steps)
    assert "gh release delete" not in commands
    assert "gitee_release.py delete" not in commands
    assert "--clobber" not in commands
    failure_steps = [step for step in steps if step.get("if") == "failure()"]
    assert len(failure_steps) == 1
    assert "preserved" in failure_steps[0]["run"]
    assert "::error::" in failure_steps[0]["run"]


def test_windows_builder_installs_yaml_test_dependency():
    build = (ROOT / "release/windows/build.ps1").read_text("utf-8")
    assert build.index("'PyYAML==6.0.2'") < build.index("-m pytest -q")


def test_124_recovery_preserves_source_images_and_original_bundles():
    source = (ROOT / ".github/workflows/release-1.2.4-recovery.yml").read_text("utf-8")
    workflow = yaml.safe_load(source)
    sha = "461c7c1519bfc6946a171f7f1fce689330dfaed5"
    assert workflow["env"] == {"RELEASE_TAG": "v1.2.4", "RELEASE_SHA": sha}
    assert "packages" not in workflow["permissions"]
    assert workflow["permissions"]["actions"] == "read"
    assert "image" not in workflow["jobs"]
    assert "gh release delete" not in source
    assert "gitee_release.py delete" not in source
    assert "--clobber" not in source
    assert "GITHUB_REF_NAME" not in source
    assert "github.ref_name" not in source
    for job in workflow["jobs"].values():
        for step in job.get("steps", []):
            if step.get("uses") == "actions/checkout@v4":
                assert step["with"]["ref"] == sha
    windows = workflow["jobs"]["windows"]
    assert set(windows["needs"]) == {"ci", "verify"}
    commands = "\n".join(step.get("run", "") for step in windows["steps"])
    assert commands.index("pip install PyYAML==6.0.2") < commands.index("build.ps1 -Version 1.2.4")
    assert "smoke_installed_client.py" in commands
    downloads = [s["with"] for s in workflow["jobs"]["publish"]["steps"] if s.get("uses") == "actions/download-artifact@v4"]
    bundles = next(s for s in downloads if s["name"] == "portable-bundles")
    assert bundles["run-id"] == 34449318112
    assert "github-token" in bundles
