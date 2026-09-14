"""隔离验证冻结 1.2.4 Agent 与新服务的真实 HTTP 协议；不启动安装客户端。

配置同目录 legacy-acceptance.json 的 source/legacy，分别指向隔离的新服务源码和旧源码。
自动验收也可用 ASH_COMPAT_SOURCE / ASH_COMPAT_LEGACY 覆盖。不提供真实环境默认值。
使用独立 venv/Scripts/python.exe 直接运行。输出和合成数据保留在新 OS 临时目录。
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import traceback
from urllib.parse import urlsplit

_configuration = Path(__file__).with_name('legacy-acceptance.json')
_settings = json.loads(_configuration.read_text(encoding='utf-8')) if _configuration.is_file() else {}
_source = os.environ.get('ASH_COMPAT_SOURCE') or _settings.get('source')
_legacy = os.environ.get('ASH_COMPAT_LEGACY') or _settings.get('legacy')
SOURCE = Path(_source).resolve() if _source else None
LEGACY = Path(_legacy).resolve() if _legacy else None
TAG = '461c7c1519bfc6946a171f7f1fce689330dfaed5'


def guard_http(origin=None, evidence=None):
    import requests
    original = requests.sessions.Session.send

    def send(session, request, **kwargs):
        url = urlsplit(request.url)
        assert url.scheme == 'http' and url.hostname == '127.0.0.1', 'non-loopback HTTP blocked'
        assert origin is None or f'{url.scheme}://{url.netloc}' in origin, 'unexpected listener blocked'
        session.trust_env = False
        kwargs['proxies'] = {}
        response = original(session, request, **kwargs)
        if evidence is not None:
            evidence.append({'method': request.method, 'path': url.path, 'status': response.status_code,
                             'request_bytes': len(request.body or b'')})
        return response

    requests.sessions.Session.send = send
    # Prevent environment proxy and netrc lookup before request preparation, too.
    original_init = requests.sessions.Session.__init__
    def init(session):
        original_init(session)
        session.trust_env = False
    requests.sessions.Session.__init__ = init


def server(root):
    sys.path[:0] = [str(SOURCE), str(SOURCE / 'backend')]
    assert not (SOURCE / 'config.json').exists()
    guard_http(set())  # This synthetic server must not make outbound HTTP requests.
    from app.main import app
    from app.database import SessionLocal
    from app.models import Script, ScriptVersion, User
    from app.config import SCRIPTS_DIR

    @app.on_event('startup')
    def seed():
        config = {'name': '兼容验收合成脚本', 'version': '1.0.0', 'params': [], 'requirements': [], 'timeout': 30}
        script_dir = Path(SCRIPTS_DIR) / '1' / '1'
        script_dir.mkdir(parents=True)
        (script_dir / 'main.py').write_text('def config():\n    return ' + repr(config) + '\n\ndef main(**kwargs):\n    return None\n', encoding='utf-8')
        with SessionLocal() as db:
            user = db.query(User).filter_by(username='compat_operator').one_or_none()
            if user is None:
                from app.auth import hash_password
                admin = db.query(User).filter_by(username='compat_admin').one()
                user = User(username='compat_operator', display_name='合成用户', role='operator', password_hash=hash_password(os.environ['ADMIN_PASSWORD']), groups=list(admin.groups))
                db.add(user)
                db.flush()
            item = Script(id=1, name=config['name'], latest_version=1, config_json=json.dumps(config), groups=list(user.groups))
            db.add(item)
            db.add(ScriptVersion(script_id=1, version=1, file_path=str(script_dir), config_json=json.dumps(config)))
            db.commit()

    import uvicorn
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    listener.bind(('127.0.0.1', 0))
    listener.listen(128)
    (root / 'endpoint.json').write_text(json.dumps({'url': f'http://127.0.0.1:{listener.getsockname()[1]}'}))
    try:
        uvicorn.Server(uvicorn.Config(app, log_level='warning')).run(sockets=[listener])
    finally:
        listener.close()


def client(root):
    sys.path.insert(0, str(LEGACY))
    origin = json.loads((root / 'endpoint.json').read_text())['url']
    os.environ['BACKEND_URL'] = origin
    os.environ['AUTOSCRIPT_CLIENT_DATA_DIR'] = str(root / 'client')
    events = []
    allowed_origins = {origin}
    guard_http(allowed_origins, events)
    import requests
    from client.agent import main as old
    assert Path(old.__file__).resolve().is_relative_to(LEGACY.resolve())
    assert old._CLIENT_PATHS.data_dir == (root / 'client').resolve()
    old._detect_machine_info = lambda: ('compat-synthetic-device', '127.0.0.1')
    old._notify_execution_result = lambda *a, **kw: None
    old.prepare_script_environment = lambda *a, **kw: (sys.executable, None)
    old._client_config['username'] = 'compat_operator'
    results = {'tag': TAG, 'legacy_module': str(Path(old.__file__)), 'checks': [], 'http': events}

    def check(name, condition):
        results['checks'].append({'name': name, 'passed': bool(condition)})
        assert condition, name

    def api(method, path, payload=None):
        response = requests.request(method, origin + path, json=payload, headers=old._headers(), timeout=15)
        assert response.status_code == 200, f'{method} {path}: {response.status_code}'
        return response.json()

    class FakeProcess:
        pid = 424242
        def __init__(self, log_path, code):
            self.code = code
            self._params_file = str(root / 'synthetic-params.json')
            Path(self._params_file).write_text('{}')
            Path(log_path).parent.mkdir(parents=True, exist_ok=True)
            Path(log_path).write_bytes(('合成执行日志\n' + ('__RESULT__:None\n' if code == 0 else '合成失败\n')).encode())
            self._log_file = open(log_path, 'ab')
        def poll(self):
            return self.code

    try:
        check('authenticate', old.authenticate('compat_operator', os.environ['ADMIN_PASSWORD']))
        check('register_agent', old.register_agent() is not None)
        check('heartbeat', old.send_heartbeat())
        check('script_authorizations', old._sync_script_authorizations() and 1 in old._load_authorized_script_ids())
        check('client_settings', old._sync_client_settings())
        for code, status in [(0, 'success'), (7, 'failed')]:
            old._start_script_subprocess = lambda script_dir, params, log_path, timeout, **kw: FakeProcess(log_path, code)
            run = api('POST', '/api/runs/execute', {'script_id': 1, 'params': {}})
            old._poll_and_execute_locked()
            check(f'{status}_claimed', old._running_proc is not None)
            old._poll_and_execute_locked()
            check(f'{status}_terminal', api('GET', f'/api/runs/{run["id"]}')['status'] == status)
        check('real_zip_download', any(e['path'] == '/api/scripts/1/download' and e['status'] == 200 for e in events))
        run = api('POST', '/api/runs/execute', {'script_id': 1, 'params': {}})
        rid = run['id']
        api('POST', f'/api/runs/{rid}/claim', {'agent_id': old._agent_id})
        log = root / 'large.log'
        content = ('中文大日志兼容验收\n' * 60000).encode('utf-8')
        log.write_bytes(content)
        check('large_log_over_1MiB', len(content) > 1024 * 1024)
        check('large_log_upload', old._upload_log_delta(rid, str(log), agent_id=old._agent_id))
        check('utf8_byte_offset', old._log_upload_offsets[rid] == len(content))
        old._log_upload_offsets[rid] = 0
        duplicate = old._upload_log_delta(rid, str(log), agent_id=old._agent_id)
        check('duplicate_offset_ack', old._log_upload_offsets[rid] == len(content))
        check('duplicate_retry', old._upload_log_delta(rid, str(log), agent_id=old._agent_id))
        extra = '追加中文\n'.encode()
        with log.open('ab') as stream:
            stream.write(extra)
        check('append_delta', old._upload_log_delta(rid, str(log), force=True, agent_id=old._agent_id))
        check('append_offset', old._log_upload_offsets[rid] == len(content + extra))
        # Real offline transport failure: a dedicated bound but non-listening socket.
        with socket.socket() as offline:
            offline.bind(('127.0.0.1', 0))
            offline_origin = f'http://127.0.0.1:{offline.getsockname()[1]}'
            allowed_origins.add(offline_origin)
            old.BACKEND_URL = offline_origin
            try:
                check('pending_report_cached', not old._report_run_status(rid, {'status': 'success'}) and len(old._pending_reports) == 1)
            finally:
                old.BACKEND_URL = origin
                allowed_origins.remove(offline_origin)
        old._flush_pending_reports()
        check('pending_report_flushed', not old._pending_reports and api('GET', f'/api/runs/{rid}')['status'] == 'success')
        old._flush_pending_reports()
        old._last_online_time = None
        local = old._start_local_run_locked({'script_id': 1, 'params': {}})
        check('offline_local_started', 'local_run_id' in local)
        old._check_local_runs()
        old.send_heartbeat()
        old._sync_local_runs_locked()
        check('offline_import', local['synced'] and local['backend_run_id'] is not None)
        before = len(api('GET', '/api/runs?mine_only=true&limit=100'))
        mutations = sum(e['method'] in ('POST', 'PATCH') for e in events)
        old._sync_local_runs_locked()
        check('offline_import_no_duplicate', before == len(api('GET', '/api/runs?mine_only=true&limit=100')) and mutations == sum(e['method'] in ('POST', 'PATCH') for e in events))
        issue = api('POST', '/api/issues', {'run_id': rid, 'title': '旧界面三字段工单', 'description': '合成兼容验收'})
        check('legacy_issue_no_automatic_diagnostics', issue['diagnostic_state'] == 'not_collected' and not issue['log_snapshot_available'])
        rejected = requests.post(origin + '/api/issues', json={'run_id': rid, 'title': '长' * 201, 'description': '合成'}, headers=old._headers(), timeout=10)
        check('legacy_issue_validation_string', rejected.status_code == 422 and isinstance(rejected.json().get('detail'), str))
        consent = requests.post(origin + '/api/issues', json={'run_id': rid, 'title': '合成', 'description': '合成', 'include_run_log': True}, headers=old._headers(), timeout=10)
        check('diagnostic_consent_required', consent.status_code == 422 and isinstance(consent.json().get('detail'), str))
        check('rejected_issues_not_created', len(api('GET', '/api/issues')) == 1)
        server_log = root / 'server' / 'logs' / f'{rid}.log'
        check('server_log_exact_bytes', server_log.read_bytes() == content + extra)
        results['large_log'] = {'utf8_bytes': len(content + extra), 'sha256': hashlib.sha256(content + extra).hexdigest(), 'duplicate_return': duplicate}
        results['passed'] = True
    except Exception as exc:
        results['passed'] = False
        results['error'] = f'{type(exc).__name__}: {exc}'
        traceback.print_exc()
    finally:
        results['loaded_legacy_modules'] = {name: str(Path(module.__file__)) for name, module in sys.modules.items() if (name.startswith('client.') or name.startswith('shared.')) and getattr(module, '__file__', None)}
        (root / 'evidence.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if results['passed'] else 1


def main():
    if len(sys.argv) == 3:
        root = Path(sys.argv[2])
        return server(root) if sys.argv[1] == '_server' else client(root)
    root = Path(tempfile.mkdtemp(prefix='ash-legacy-compat-'))
    env = {k: v for k, v in os.environ.items() if k.upper() in {'SYSTEMROOT', 'WINDIR', 'PATH', 'COMSPEC', 'TEMP', 'TMP'}}
    env.update(PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1', PYTHONDONTWRITEBYTECODE='1',
               ASH_COMPAT_SOURCE=str(SOURCE), ASH_COMPAT_LEGACY=str(LEGACY), DATA_DIR=str(root / 'server'),
               ADMIN_USERNAME='compat_admin', ADMIN_PASSWORD=secrets.token_urlsafe(24),
               JWT_SECRET=secrets.token_urlsafe(48), EXTERNAL_AUTH_ENABLED='false')
    proc = None
    try:
        assert SOURCE is not None and LEGACY is not None, 'configure isolated source and legacy paths first'
        assert SOURCE.is_dir() and LEGACY.is_dir(), 'missing safe source snapshots'
        temporary = Path(tempfile.gettempdir()).resolve()
        for path in (SOURCE, LEGACY):
            assert path != temporary and path.is_relative_to(temporary), 'only isolated OS temporary snapshots are allowed'
            assert 'tmp' not in path.relative_to(temporary).parts, 'repository tmp must never be used'
        assert not (SOURCE / 'config.json').exists() and not (LEGACY / 'client_config.json').exists()
        repository = Path(__file__).resolve().parents[2]
        tree = subprocess.check_output(['git', 'ls-tree', '-r', TAG, '--', 'client', 'shared'], cwd=repository).decode()
        blobs = {line.split('\t', 1)[1]: line.split()[2] for line in tree.splitlines()}
        verified = {}
        for package in ('client', 'shared'):
            for file in (LEGACY / package).rglob('*'):
                if not file.is_file() or '__pycache__' in file.parts:
                    continue
                relative = file.relative_to(LEGACY).as_posix()
                raw = file.read_bytes()
                normalized = raw.replace(b'\r\n', b'\n')
                blob = hashlib.sha1(b'blob ' + str(len(normalized)).encode() + b'\0' + normalized).hexdigest()
                assert blobs.get(relative) == blob, f'legacy source differs from frozen tag beyond CRLF: {relative}'
                verified[relative] = {'lf_git_blob': blob, 'raw_sha256': hashlib.sha256(raw).hexdigest(), 'crlf_normalized': raw != normalized}
        assert len(verified) == 31, 'expected 31 frozen client/shared files'
        tracked = ['backend/app/routers/runs.py', 'backend/app/request_limits.py', 'backend/app/routers/issues.py']
        (root / 'source-evidence.json').write_text(json.dumps({'tag': TAG, 'legacy_blob_hashes': verified, 'server_sha256': {name: hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() for name in tracked}}, indent=2), encoding='utf-8')
        (root / 'server').mkdir()
        with (root / 'server-output.log').open('wb') as output:
            proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '_server', str(root)], env=env, cwd=root, stdout=output, stderr=subprocess.STDOUT)
            import requests
            guard_http()
            for _ in range(180):
                assert proc.poll() is None, 'isolated server exited; see server-output.log'
                if (root / 'endpoint.json').exists():
                    url = json.loads((root / 'endpoint.json').read_text())['url']
                    try:
                        if requests.get(url + '/api/health/ready', timeout=1).status_code == 200:
                            break
                    except requests.RequestException:
                        pass
                time.sleep(.25)
            else:
                raise RuntimeError('isolated server readiness timeout')
            with (root / 'client-output.log').open('wb') as client_output:
                result = subprocess.run([sys.executable, str(Path(__file__).resolve()), '_client', str(root)], env=env, cwd=root, stdout=client_output, stderr=subprocess.STDOUT, timeout=150)
            print(json.dumps({'passed': result.returncode == 0, 'output_root': str(root), 'evidence': str(root / 'evidence.json')}, ensure_ascii=False))
            return result.returncode
    except Exception as exc:
        print(json.dumps({'passed': False, 'error': str(exc), 'output_root': str(root)}, ensure_ascii=False))
        return 1
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)


if __name__ == '__main__':
    raise SystemExit(main())
