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
