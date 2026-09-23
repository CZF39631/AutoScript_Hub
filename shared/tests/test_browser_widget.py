import pytest

from shared.script_contract import PARAMETER_TYPES, SCRIPT_CONTRACT_VERSION, validate_params, validate_script


DEFINITION = {"key": "browser_path", "type": "text", "widget": "browser", "label": "浏览器", "default": ""}


def write_script(path, definition):
    config = dict(name="browser", version="1.0.0", description="test", category="test",
                  params=[definition], requirements=["requests>=2.31"], timeout=60)
    path.write_text(f"def config():\n    return {config!r}\n\ndef main(browser_path=''):\n    return None\n", encoding="utf-8")
    return path


def test_browser_metadata_is_backward_compatible(tmp_path):
    report = validate_script(write_script(tmp_path / "main.py", DEFINITION), strict=True)
    assert report.ok
    assert report.config["params"][0]["default"] == ""
    assert report.config["requirements"] == ["requests>=2.31"]
    assert SCRIPT_CONTRACT_VERSION == "1.1.0"
    assert PARAMETER_TYPES == {"text", "number", "file", "folder", "select", "checkbox"}


@pytest.mark.parametrize("widget", [None, "", "unknown", 1, True, [], {}])
def test_invalid_widget(tmp_path, widget):
    report = validate_script(write_script(tmp_path / "main.py", dict(DEFINITION, widget=widget)))
    assert [(issue.code, issue.path) for issue in report.errors] == [("params.widget", "params[0].widget")]


@pytest.mark.parametrize("param_type", ["number", "file", "folder", "select", "checkbox"])
def test_invalid_widget_type(tmp_path, param_type):
    definition = dict(DEFINITION, type=param_type)
    definition.pop("default")
    if param_type == "select":
        definition["options"] = ["a"]
    report = validate_script(write_script(tmp_path / "main.py", definition))
    assert [issue.code for issue in report.errors] == ["params.widget-type"]


@pytest.mark.parametrize("value", [1, True, [], {}])
def test_browser_values_follow_text_rules(tmp_path, value):
    report = validate_script(write_script(tmp_path / "main.py", dict(DEFINITION, default=value)))
    assert [issue.code for issue in report.errors] == ["params.text-default"]
    for check_paths in (False, True):
        errors = validate_params([DEFINITION], {"browser_path": value}, check_paths)
        assert len(errors) == 1 and "字符串" in errors[0]


@pytest.mark.parametrize("value", [None, ""])
def test_optional_empty_browser(value):
    for check_paths in (False, True):
        assert validate_params([DEFINITION], {"browser_path": value}, check_paths) == []
        assert validate_params([DEFINITION], {}, check_paths) == []
        assert validate_params([dict(DEFINITION, required=True)], {"browser_path": value}, check_paths)


def test_browser_paths_only_checked_on_client(tmp_path, monkeypatch):
    executable = tmp_path / "browser.exe"
    executable.write_text("not executable: validation must not launch it", encoding="utf-8")
    for path, valid in [(executable, True), (tmp_path, False), (tmp_path / "missing", False)]:
        values = {"browser_path": str(path)}
        assert validate_params([DEFINITION], values, False) == []
        assert bool(validate_params([DEFINITION], values, True)) is not valid
    def forbidden(*args):
        raise AssertionError("server must not inspect local paths")
    monkeypatch.setattr("shared.script_contract.os.path.isfile", forbidden)
    assert validate_params([DEFINITION], {"browser_path": str(executable)}, False) == []


def test_plain_text_has_no_path_check():
    definition = dict(DEFINITION)
    definition.pop("widget")
    assert validate_params([definition], {"browser_path": "ordinary text"}, True) == []
