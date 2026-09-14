"""任务时区与冻结准备进程的打包契约；不构建或启动安装版客户端。"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_frozen_agent_dispatches_multiprocessing_before_importing_application():
    source = (ROOT / 'release/windows/entry_agent.py').read_text(encoding='utf-8')
    tree = ast.parse(source)
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'freeze_support']
    imports = [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module == 'client.agent.main']
    assert len(calls) == len(imports) == 1
    assert calls[0].lineno < imports[0].lineno


def test_timezone_database_is_declared_and_bundled_for_windows():
    for path in ('backend/requirements.txt', 'client/requirements.txt'):
        assert 'tzdata==2026.3' in (ROOT / path).read_text(encoding='utf-8').splitlines()
    spec = (ROOT / 'release/windows/autoscript_hub.spec').read_text(encoding='utf-8')
    assert 'collect_data_files("tzdata")' in spec
    assert 'copy_metadata("websocket-client")' in spec
    assert '"websocket"' in spec


def test_preview_one_version_is_upgradable_to_stable():
    from shared.version import parse_update_version
    assert parse_update_version('1.2.4') < parse_update_version('1.3.0-preview.1') < parse_update_version('1.3.0')
    # preview 是 packaging 的 rc 别名，不能当作低于 beta 的版本。
    assert parse_update_version('1.3.0-preview.1') == parse_update_version('1.3.0-rc.1')
