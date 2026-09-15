"""Preview is a separate app; beta deliberately remains in the stable family."""
import sys
import os
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from client.runtime.paths import ClientPaths
from client.runtime.profile import agent_ports, get_install_flavor, ui_ports
from client.runtime.local_auth import get_or_create_agent_token
from shared.version import is_preview_version


@pytest.mark.parametrize('version,expected', [
    ('1.3.0-preview.1', True), ('1.3.0-preview.2+local', True),
    ('1.3.0-beta.1', False), ('1.3.0-rc.1', False), ('1.3.0', False),
    ('1.3.0-review.1', False), ('1.3.0+preview', False),
])
def test_only_explicit_preview_selects_isolation(version, expected):
    assert is_preview_version(version) is expected


def test_preview_defaults_do_not_share_data_or_token(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    monkeypatch.delenv('AUTOSCRIPT_CLIENT_DATA_DIR', raising=False)
    monkeypatch.setenv('AUTOSCRIPT_INSTALL_FLAVOR', 'stable')
    stable = ClientPaths.from_environment(install_dir=tmp_path/'stable-app')
    stable.ensure()
    stable.config_file.write_text('{"synthetic":true}')
    token = get_or_create_agent_token()
    stable_ports, stable_ui = set(agent_ports()), set(ui_ports())
    before = {p.relative_to(stable.data_dir): p.read_bytes() for p in stable.data_dir.rglob('*') if p.is_file()}
    monkeypatch.setenv('AUTOSCRIPT_INSTALL_FLAVOR', 'preview')
    preview = ClientPaths.from_environment(install_dir=tmp_path/'preview-app')
    preview.ensure()
    assert preview.data_dir == tmp_path/'AutoScriptHubPreview'
    assert get_or_create_agent_token() != token
    assert not preview.config_file.exists()
    assert set(agent_ports()).isdisjoint(stable_ports | stable_ui)
    assert set(ui_ports()).isdisjoint(stable_ports | stable_ui | set(agent_ports()))
    assert before == {p.relative_to(stable.data_dir): p.read_bytes() for p in stable.data_dir.rglob('*') if p.is_file()}


def test_preview_rejects_stable_default_override(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    monkeypatch.setenv('AUTOSCRIPT_INSTALL_FLAVOR', 'preview')
    monkeypatch.setenv('AUTOSCRIPT_CLIENT_DATA_DIR', str(tmp_path/'AutoScriptHub'))
    with pytest.raises(ValueError, match='另一安装身份'):
        ClientPaths.from_environment()
    assert not (tmp_path/'AutoScriptHub').exists()


def test_preview_does_not_adopt_unmarked_existing_data(tmp_path, monkeypatch):
    monkeypatch.setenv('AUTOSCRIPT_INSTALL_FLAVOR', 'preview')
    root = tmp_path/'existing'
    (root/'config').mkdir(parents=True)
    (root/'config/client.json').write_text('{"synthetic":true}')
    paths = ClientPaths.from_environment(data_dir=root)
    with pytest.raises(ValueError, match='拒绝接管'):
        paths.ensure()
    assert not (root/'.install-flavor').exists()


def test_stable_cannot_adopt_preview_marked_root(tmp_path, monkeypatch):
    monkeypatch.setenv('AUTOSCRIPT_INSTALL_FLAVOR', 'preview')
    ClientPaths.from_environment(data_dir=tmp_path/'isolated').ensure()
    monkeypatch.setenv('AUTOSCRIPT_INSTALL_FLAVOR', 'stable')
    with pytest.raises(ValueError, match='另一安装身份'):
        ClientPaths.from_environment(data_dir=tmp_path/'isolated').ensure()


def test_preview_ignores_legacy_config_and_inherited_storage(tmp_path):
    install = tmp_path / 'install'
    install.mkdir()
    legacy = install / 'client_config.json'
    legacy.write_text(json.dumps({'username': 'synthetic-legacy', 'server_url': 'http://127.0.0.1:1'}))
    env = {k: v for k, v in os.environ.items() if k.upper() in {'SYSTEMROOT', 'WINDIR', 'PATH', 'TEMP', 'TMP'}}
    env.update(LOCALAPPDATA=str(tmp_path/'profile'), AUTOSCRIPT_INSTALL_FLAVOR='preview',
               BACKEND_URL='http://127.0.0.1:1', SCRIPTS_DIR=str(tmp_path/'formal-scripts'),
               LOGS_DIR=str(tmp_path/'formal-logs'))
    code = f'''
import sys, builtins
from pathlib import Path
sys.path.insert(0, {str(Path(__file__).resolve().parents[2])!r})
from client.runtime.paths import ClientPaths
paths = ClientPaths.from_environment(install_dir={str(install)!r})
ClientPaths.from_environment = classmethod(lambda cls, *args, **kwargs: paths)
original = builtins.open
def guarded(file, *args, **kwargs):
    if str(file) == {str(legacy)!r}:
        raise AssertionError('Preview attempted to read legacy config')
    return original(file, *args, **kwargs)
builtins.open = guarded
from client.agent import main as agent
from client.ui.config_manager import load_config
assert agent._client_config == {{}}
assert agent.BACKEND_URL == 'http://127.0.0.1:8765'
assert agent._SCRIPTS_DIR == str(paths.scripts_dir)
assert agent._LOGS_DIR == str(paths.logs_dir)
assert load_config()['username'] == ''
'''
    subprocess.run([sys.executable, '-I', '-c', code], env=env, cwd=tmp_path, check=True,
                   capture_output=True, timeout=30)
    assert not (tmp_path/'formal-scripts').exists()
    assert not (tmp_path/'formal-logs').exists()


def test_preview_update_route_does_not_start_download_worker(monkeypatch):
    from client.agent import main as agent
    class ForbiddenLock:
        def __enter__(self):
            raise AssertionError('Preview must not enter update worker setup')
        def __exit__(self, *args):
            pass
    disabled = {'state': 'idle', 'updates_enabled': False, 'error': 'Preview disabled'}
    monkeypatch.setattr(agent, 'is_preview', lambda: True)
    monkeypatch.setattr(agent, '_get_update_status', lambda: dict(disabled))
    monkeypatch.setattr(agent, '_update_worker_lock', ForbiddenLock())
    assert agent._install_staged_update() == disabled


@pytest.mark.parametrize('version,flavor', [('1.3.0-beta.1', 'stable'), ('1.3.0-preview.1', 'preview')])
def test_frozen_build_identity_cannot_be_overridden(monkeypatch, version, flavor):
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setitem(sys.modules, 'autoscript_build_info', SimpleNamespace(VERSION=version, CHANNEL='beta', INSTALL_FLAVOR=flavor))
    monkeypatch.setenv('AUTOSCRIPT_INSTALL_FLAVOR', 'stable' if flavor == 'preview' else 'preview')
    assert get_install_flavor() == flavor
