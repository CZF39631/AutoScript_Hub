from pathlib import Path
import shutil
import os
import subprocess
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "autoscript-script-authoring"


def test_standalone_snapshot_matches_shared_contract():
    live = (ROOT / "shared" / "script_contract.py").read_text(encoding="utf-8")
    snapshot = (SKILL / "scripts" / "contract_snapshot.py").read_text(encoding="utf-8")
    assert snapshot == live + "\nvalidate = validate_script\n"


def test_standalone_browser_widget_strict_cli(tmp_path):
    from shared.tests.test_browser_widget import DEFINITION, write_script

    standalone = tmp_path / "standalone"
    shutil.copytree(SKILL / "scripts", standalone)
    candidate = write_script(tmp_path / "main.py", DEFINITION)
    env = dict(os.environ, PYTHONPATH="", PYTHONNOUSERSITE="1")
    for widget, expected in [("browser", 0), ("unknown", 1)]:
        write_script(candidate, dict(DEFINITION, widget=widget))
        result = subprocess.run(
            [sys.executable, str(standalone / "validate_script.py"), str(candidate), "--strict"],
            cwd=tmp_path, env=env, capture_output=True, text=True,
        )
        assert result.returncode == expected, result.stdout + result.stderr
        assert ("0 errors, 0 warnings" if expected == 0 else "params.widget") in result.stdout


def test_skill_has_complete_metadata_and_no_template_placeholders():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")

    assert "TODO" not in text
    assert "validate_script.py" in text
    assert "package_script.py" in text
    assert (SKILL / "agents" / "openai.yaml").is_file()


def test_skill_validator_accepts_repository_contract_fixture():
    completed = subprocess.run(
        [
            sys.executable,
            str(SKILL / "scripts" / "validate_script.py"),
            str(ROOT / "shared" / "tests" / "fixtures" / "valid_script.py"),
            "--strict",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "0 errors, 0 warnings" in completed.stdout


def test_skill_packager_creates_root_main_zip(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "main.py").write_text(
        (ROOT / "shared" / "tests" / "fixtures" / "valid_script.py").read_text("utf-8"),
        encoding="utf-8",
    )
    output = tmp_path / "script.zip"

    completed = subprocess.run(
        [sys.executable, str(SKILL / "scripts" / "package_script.py"), str(source), str(output)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    with zipfile.ZipFile(output) as bundle:
        assert "main.py" in bundle.namelist()
        assert not any(name.startswith("source/") for name in bundle.namelist())
