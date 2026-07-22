from pathlib import Path
import zipfile

import pytest

from shared.script_contract import validate_params, validate_script


FIXTURES = Path(__file__).parent / "fixtures"


def _issue_codes(issues):
    return [issue.code for issue in issues]


def test_valid_script_has_no_issues():
    report = validate_script(FIXTURES / "valid_script.py", strict=True)

    assert report.ok is True
    assert report.errors == []
    assert report.warnings == []
    assert report.config["version"] == "1.0.0"


def test_main_signature_must_cover_parameter_keys():
    report = validate_script(FIXTURES / "invalid_signature.py", strict=True)

    assert _issue_codes(report.errors) == ["main.signature"]


@pytest.mark.parametrize(
    ("replacement", "expected_code"),
    [
        ('"version": "latest"', "config.version"),
        ('"requirements": ["not a req ???"]', "requirements.invalid"),
        ('"timeout": 0', "config.timeout"),
        ('"params": [{"key": "class", "type": "text", "label": "x"}]', "params.key"),
        ('"params": [{"key": "x", "type": "select", "label": "x", "options": []}]', "params.select-options"),
        ('"params": [{"key": "x", "type": "checkbox", "label": "x", "default": "yes"}]', "params.checkbox-default"),
    ],
)
def test_invalid_config_fields_are_reported(tmp_path, replacement, expected_code):
    source = """
def config():
    return {
        "name": "invalid",
        "version": "1.0.0",
        "description": "invalid case",
        "category": "test",
        "params": [],
        "requirements": [],
        "timeout": 60,
    }

def main(**kwargs):
    return None
"""
    key = replacement.split(":", 1)[0].strip()
    lines = [line for line in source.splitlines() if line.strip().split(":", 1)[0] != key]
    insert_at = lines.index("    }")
    lines.insert(insert_at, f"        {replacement},")
    script = tmp_path / "invalid.py"
    script.write_text("\n".join(lines), encoding="utf-8")

    report = validate_script(script, strict=True)

    assert expected_code in _issue_codes(report.errors)


def test_legacy_single_directory_zip_is_warning(tmp_path):
    archive = tmp_path / "legacy.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.write(FIXTURES / "valid_script.py", "legacy/main.py")

    report = validate_script(archive, strict=False)

    assert report.ok is True
    assert _issue_codes(report.warnings) == ["zip.legacy-root"]


def test_strict_mode_rejects_legacy_zip_warning(tmp_path):
    archive = tmp_path / "legacy.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.write(FIXTURES / "valid_script.py", "legacy/main.py")

    report = validate_script(archive, strict=True)

    assert report.ok is False
    assert _issue_codes(report.errors) == ["zip.legacy-root"]


def test_zip_path_traversal_is_rejected_without_writing_outside(tmp_path):
    archive = tmp_path / "malicious.zip"
    escaped = tmp_path / "escaped.py"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../escaped.py", "raise RuntimeError('should not run')")
        bundle.write(FIXTURES / "valid_script.py", "main.py")

    report = validate_script(archive)

    assert "zip.unsafe-path" in _issue_codes(report.errors)
    assert escaped.exists() is False


def test_validation_never_executes_candidate_top_level_code(tmp_path):
    marker = tmp_path / "executed.txt"
    script = tmp_path / "candidate.py"
    script.write_text(
        f'''from pathlib import Path
Path({str(marker)!r}).write_text("executed", encoding="utf-8")

def config():
    return {{
        "name": "static",
        "version": "1.0.0",
        "description": "static config",
        "category": "test",
        "params": [],
        "requirements": [],
        "timeout": 60,
    }}

def main():
    return None
''',
        encoding="utf-8",
    )

    report = validate_script(script, strict=True)

    assert report.ok is True
    assert marker.exists() is False


def test_dynamic_config_expression_is_rejected_without_execution(tmp_path):
    script = tmp_path / "dynamic.py"
    script.write_text(
        '''def make_config():
    raise RuntimeError("must not run")

def config():
    return make_config()

def main():
    return None
''',
        encoding="utf-8",
    )

    report = validate_script(script, strict=True)

    assert "config.static" in _issue_codes(report.errors)


def test_validate_params_separates_server_and_client_path_checks(tmp_path):
    definitions = [
        {"key": "source", "type": "file", "label": "源文件", "required": True},
        {"key": "count", "type": "number", "label": "数量", "min": 1, "max": 3},
        {"key": "mode", "type": "select", "label": "模式", "options": ["a", "b"]},
    ]
    values = {"source": str(tmp_path / "missing.txt"), "count": 4, "mode": "c"}

    server_errors = validate_params(definitions, values, check_paths=False)
    client_errors = validate_params(definitions, values, check_paths=True)

    assert not any("不存在" in error for error in server_errors)
    assert any("不存在" in error for error in client_errors)
    assert any("最大值" in error for error in server_errors)
    assert any("可选项" in error for error in server_errors)
