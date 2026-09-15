"""Static/mock acceptance-harness tests: never start Agent, Python children or installer."""
import ast
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('task_prepare_smoke', ROOT / 'release/windows/smoke_task_prepare.py')
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


@pytest.fixture
def layout(tmp_path):
    install = tmp_path / 'install'
    (install / 'runtime/python').mkdir(parents=True)
    (install / 'AutoScriptAgent.exe').write_bytes(b'synthetic fixture, never executable')
    (install / 'runtime/python/python.exe').write_bytes(b'synthetic fixture')
    return install, tmp_path / 'data'


def test_only_empty_disjoint_temporary_paths(layout, tmp_path):
    install, data = layout
    assert smoke.validate_paths(install, data, tmp_path) == (install, data)
    data.mkdir()
    (data / 'existing-user-file').write_text('do not touch')
    with pytest.raises(ValueError, match='empty'):
        smoke.validate_paths(install, data, tmp_path)
    assert (data / 'existing-user-file').read_text() == 'do not touch'


def test_reject_non_temporary_overlap_and_default(layout, tmp_path, monkeypatch):
    install, data = layout
    with pytest.raises(ValueError, match='temporary'):
        smoke.validate_paths(install, data, tmp_path / 'other')
    with pytest.raises(ValueError, match='disjoint'):
        smoke.validate_paths(install, install / 'data', tmp_path)
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    with pytest.raises(ValueError, match='real client'):
        smoke.validate_paths(install, tmp_path / 'AutoScriptHub', tmp_path)
    with pytest.raises(ValueError, match='absolute'):
        smoke.validate_paths(Path('relative'), data, tmp_path)


def test_reject_repository_tmp(layout, tmp_path, monkeypatch):
    install, _ = layout
    monkeypatch.setattr(smoke, 'ROOT', tmp_path)
    with pytest.raises(ValueError, match='repository tmp'):
        smoke.validate_paths(install, tmp_path / 'tmp/data', tmp_path)


def test_environment_does_not_inherit_secrets_or_loader_settings(tmp_path, monkeypatch):
    for name in ('BACKEND_URL', 'PYTHONPATH', 'HTTP_PROXY', 'HTTPS_PROXY', 'USERNAME', 'TOKEN', 'PIP_INDEX_URL'):
        monkeypatch.setenv(name, 'REAL-USER-SENTINEL')
    env = smoke.child_environment(tmp_path, 'http://127.0.0.1:12345')
    assert 'REAL-USER-SENTINEL' not in json.dumps(env)
    assert env['PIP_NO_INDEX'] == '1'
    assert env['AUTOSCRIPT_CLIENT_DATA_DIR'] == str(tmp_path)
    assert env['BACKEND_URL'] == 'http://127.0.0.1:12345'


def test_seed_matches_script_contract(tmp_path):
    from shared.script_contract import validate_script
    backend = 'http://127.0.0.1:12345'
    smoke.seed(tmp_path, backend, 'UNIQUE_SYNTHETIC_MARKER')
    for ident in (1, 2):
        report = validate_script(tmp_path / f'scripts/{ident}/1/main.py', strict=False)
        assert report.ok, report.errors
        assert report.config['requirements'] == ([] if ident == 1 else ['autoscript-smoke-never-install==0.0.1'])
    config = json.loads((tmp_path / 'config/client.json').read_text())
    auth = json.loads((tmp_path / 'config/script_authorizations.json').read_text())
    assert auth['server_url'] == config['server_url'] == backend
    assert auth['username'] == config['username']
    assert auth['script_ids'] == [1, 2]
    assert config['update_manifest_urls'] == []
    assert config['github_update_repository'] == config['gitee_update_repository'] == ''
    assert not (tmp_path / 'config/agent-api.token').exists()


def test_request_uses_token_origin_and_disables_proxy(monkeypatch):
    calls = []
    class Response:
        def __enter__(self):
            import io
            return io.StringIO('{"ok": true}')
        def __exit__(self, *args):
            pass
    class Opener:
        def open(self, req, timeout):
            calls.append((req, timeout))
            return Response()
    def opener(handler):
        assert handler.proxies == {}
        return Opener()
    monkeypatch.setattr(smoke, 'build_opener', opener)
    assert smoke.request(12345, 'synthetic-token', '/local/execute', {'script_id': 1}) == {'ok': True}
    req, timeout = calls[0]
    assert req.full_url == 'http://127.0.0.1:12345/local/execute'
    assert req.get_header('Authorization') == 'Bearer synthetic-token'
    assert req.get_header('Origin') == 'http://127.0.0.1:18181'
    assert timeout == 2


def test_wait_is_bounded(monkeypatch):
    ticks = iter([0, 0, 50])
    monkeypatch.setattr(smoke.time, 'monotonic', lambda: next(ticks))
    monkeypatch.setattr(smoke.time, 'sleep', lambda _: None)
    with pytest.raises(RuntimeError, match='bounded'):
        smoke.wait_for(lambda: None, timeout=1)


def test_main_reports_failure_json_without_launch(monkeypatch, capsys):
    def fail(*args):
        raise RuntimeError('ownership unavailable')
    monkeypatch.setattr(smoke, 'run', fail)
    assert smoke.main(['--install-dir', 'unused', '--data-dir', 'unused',
                       '--expected-version', '1.3.0-preview.1']) == 1
    assert json.loads(capsys.readouterr().out) == {'ok': False, 'error': 'ownership unavailable'}


def test_static_no_global_process_cleanup_or_port_probe():
    source = Path(smoke.__file__).read_text(encoding='utf-8')
    ast.parse(source)
    for forbidden in ('taskkill', 'tasklist', '_image_pids', '_wait_agent', 'smoke_installed_client',
                      'AutoScriptHub.exe', 'requests.get', 'os.kill', 'pip install'):
        assert forbidden not in source
    assert 'spawn_contained' in source and 'stop_process_tree' in source
    assert 'owned_listener(agent.pid) != port' in source
    assert 'SO_EXCLUSIVEADDRUSE' in source
    assert "'cleanup_confirmed'" in source
    assert 'ensure_environment([], paths' in source
    assert "'environment.json'" not in source
