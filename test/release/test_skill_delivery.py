from pathlib import Path
import subprocess
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "autoscript-script-authoring"


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
