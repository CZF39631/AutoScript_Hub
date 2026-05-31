import os
from app.services.script_parser import parse_script_config

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def test_parse_sample_script():
    path = os.path.join(FIXTURE_DIR, "sample_script.py")
    result = parse_script_config(path)
    assert result["name"] == "测试脚本"
    assert result["description"] == "一个示例脚本"
    assert result["category"] == "测试"
    assert len(result["params"]) == 4
    assert result["params"][0]["key"] == "url_file"
    assert result["params"][0]["type"] == "file"
    assert result["params"][1]["default"] == 30
    assert result["requirements"] == ["DrissionPage>=4.0"]


def test_parse_nonexistent_file():
    try:
        parse_script_config("/nonexistent/file.py")
        assert False, "Should have raised"
    except FileNotFoundError:
        pass


def test_parse_script_missing_config():
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".py")
    try:
        with os.fdopen(fd, "w") as f:
            f.write("def main():\n    pass\n")
        result = parse_script_config(path)
        assert result is None
    finally:
        os.unlink(path)
