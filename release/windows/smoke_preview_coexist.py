#!/usr/bin/env python3
"""仅 OS temp 的冻结 Preview 并存验收；不运行 Setup 或真实旧 Agent。

父端调用 run(install, legacy, private_runtime=None)。可直接运行本文件，读取同目录
smoke_preview_coexist.json 的 install、legacy、可选 private_runtime 绝对路径。
结果和合成数据保留于新 OS temp 根。legacy 只是冻结 API 代码，不是旧安装器。
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location('_prepare_smoke', Path(__file__).with_name('smoke_task_prepare.py'))
_prepare = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_prepare)
validate_paths = _prepare.validate_paths
owned_listener = _prepare.owned_listener
wait_for = _prepare.wait_for
VERSION = '1.3.0-preview.1'
FROZEN = '461c7c1519bfc6946a171f7f1fce689330dfaed5'
PREVIEW_PORTS = {18180, *range(18191, 18200)}
FORMAL_PORTS = {18080, *range(18091, 18100)}
PREVIEW_ORIGIN = 'http://127.0.0.1:18181'
FORMAL_ORIGIN = 'http://127.0.0.1:18081'


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def temporary_input(path: Path) -> Path:
    """Reject redirected inputs recursively before copying/executing anything."""
    path = Path(path)
    if not path.is_absolute():
        raise ValueError('absolute temporary input required')
    temp = Path(tempfile.gettempdir()).resolve()
    for item in (path, *path.parents):
        if item.is_symlink() or (item.exists() and getattr(item.stat(), 'st_file_attributes', 0) & 0x400):
            raise ValueError('reparse input forbidden')
    path = path.resolve()
    if path == temp or not path.is_relative_to(temp) or not path.exists():
        raise ValueError('input must exist beneath OS temp')
    if path.is_dir():
        for item in path.rglob('*'):
            if item.is_symlink() or getattr(item.stat(), 'st_file_attributes', 0) & 0x400:
                raise ValueError('reparse descendant forbidden')
    return path


def verified_legacy(legacy: Path) -> bytes:
    source = temporary_input(Path(legacy) / 'client/agent/local_server.py').read_bytes()
    blob = subprocess.run(['git', '-C', str(ROOT), 'show', FROZEN + ':client/agent/local_server.py'],
                          check=True, capture_output=True, timeout=15).stdout
    # Git exports/checkouts can legitimately have CRLF; execute the exact frozen blob.
    if source.replace(b'\r\n', b'\n') != blob.replace(b'\r\n', b'\n'):
        raise ValueError('legacy local_server.py differs from frozen Git blob')
    return blob


def manifest(directory: Path) -> dict:
    return {str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else '<directory>'
            for p in sorted(directory.rglob('*')) if p.is_file() or p.is_dir()}


def frozen_environment(root: Path, backend: str) -> dict:
    env = _prepare.child_environment(root, backend)
    env.pop('AUTOSCRIPT_CLIENT_DATA_DIR', None)
    # Do not force Preview identity: the EXE must supply its frozen flavor too.
    env.pop('AUTOSCRIPT_INSTALL_FLAVOR', None)
    return env


def request(port, token, route='/status', origin=PREVIEW_ORIGIN, body=None):
    req = Request(f'http://127.0.0.1:{port}{route}',
                  data=None if body is None else json.dumps(body).encode(),
                  headers={'Authorization': 'Bearer ' + token, 'Origin': origin,
                           'Content-Type': 'application/json'})
    try:
        with build_opener(ProxyHandler({})).open(req, timeout=3) as response:
            return response.status, json.load(response)
    except HTTPError as exc:
        with exc:
            return exc.code, json.load(exc)


def run(install: Path, legacy: Path, private_runtime: Path | None = None) -> dict:
    if os.name != 'nt':
        raise RuntimeError('Windows acceptance only')
    install = temporary_input(install)
    runtime = temporary_input(private_runtime) if private_runtime is not None else None
    blob = verified_legacy(legacy)
    root = Path(tempfile.mkdtemp(prefix='ash-preview-coexist-'))
    evidence = {'ok': False, 'root': str(root), 'legacy_kind': 'synthetic API, not installed 1.2.4',
                'legacy_commit': FROZEN, 'legacy_blob_sha256': hashlib.sha256(blob).hexdigest()}
    sys.path.insert(0, str(ROOT))
    from client.runtime.process_tree import spawn_contained, stop_process_tree
    children, logs = [], []
    formal = root / 'profile/AutoScriptHub'
    before = None
    try:
        if runtime is not None:
            require((runtime / 'python.exe').is_file(), 'private_runtime must be Python directory')
            layout = root / 'install'
            shutil.copytree(install, layout)
            require(not (layout / 'runtime/python').exists(), 'use embedded runtime or separate runtime, not both')
            shutil.copytree(runtime, layout / 'runtime/python')
            install = layout
        install, _ = validate_paths(install, root / 'validation-unused')
        with socket.socket() as reserved:
            reserved.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            reserved.bind(('127.0.0.1', 0))  # deliberately never listen
            backend = 'http://127.0.0.1:' + str(reserved.getsockname()[1])
            env = frozen_environment(root, backend)
            for key in ('LOCALAPPDATA', 'TEMP'):
                Path(env[key]).mkdir(parents=True, exist_ok=True)
            preview = Path(env['LOCALAPPDATA']) / 'AutoScriptHubPreview'
            formal.mkdir(parents=True)
            (formal / 'config').mkdir()
            formal_token = secrets.token_urlsafe(48)
            (formal / 'config/agent-api.token').write_text(formal_token, encoding='ascii')
            (formal / 'config/client.json').write_text(json.dumps({'server_url': backend,
                'username': 'synthetic-formal', 'setup_completed': True}), encoding='utf-8')
            (formal / 'sentinel.bin').write_bytes(secrets.token_bytes(1024))
            (formal / '.install-flavor').write_bytes(b'stable\n')
            before = manifest(formal)
            evidence['formal_before'] = before
            # Simulate inherited stable storage settings; Preview must ignore them.
            env['SCRIPTS_DIR'] = str(formal / 'scripts')
            env['LOGS_DIR'] = str(formal / 'logs')
            # Seed only synthetic configuration; no token or scripts in Preview.
            (preview / 'config').mkdir(parents=True)
            (preview / '.install-flavor').write_bytes(b'preview\n')
            (preview / 'config/client.json').write_text(json.dumps({'server_url': backend,
                'username': 'synthetic-preview', 'password': 'synthetic-only', 'setup_completed': True,
                'github_update_repository': '', 'gitee_update_repository': '', 'update_manifest_urls': [],
                'update_channel': 'preview', 'pip_index_url': backend}), encoding='utf-8')
            token_path = preview / 'config/agent-api.token'
            require(not token_path.exists(), 'Preview token must be created by EXE')
            (root / 'legacy_api.py').write_bytes(blob)
            callback = root / 'legacy-shutdown-called'
            wrapper = root / 'synthetic_formal.py'
            wrapper.write_text("import importlib.util, pathlib, time, socket\n"
                "s = importlib.util.spec_from_file_location('legacy_api', 'legacy_api.py')\n"
                "m = importlib.util.module_from_spec(s); s.loader.exec_module(m)\n"
                "class ExclusiveServer(m.ThreadingHTTPServer):\n"
                "    allow_reuse_address = False\n"
                "    def server_bind(self):\n"
                "        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)\n"
                "        super().server_bind()\n"
                "m.ThreadingHTTPServer = ExclusiveServer\n"
                "token = pathlib.Path('profile/AutoScriptHub/config/agent-api.token').read_text()\n"
                "t = m.start_local_server(0, lambda: None, get_version_fn=lambda: '1.2.4', api_token=token, "
                "request_shutdown_fn=lambda: pathlib.Path('legacy-shutdown-called').write_text('called'))\n"
                "t.start()\nwhile True: time.sleep(1)\n", encoding='utf-8')

            def launch(args, name, cwd):
                log = (root / (name + '.log')).open('wb')
                logs.append(log)
                proc = spawn_contained(args, cwd=cwd, env=env, stdout=log, stderr=log)
                children.append(proc)
                return proc

            old = launch([str(install / 'runtime/python/python.exe'), '-I', str(wrapper)], 'synthetic-formal', root)
            old_port = wait_for(lambda: owned_listener(old.pid))

            def call(proc, port, token, route='/status', origin=PREVIEW_ORIGIN, body=None):
                require(proc.poll() is None and owned_listener(proc.pid) == port, 'lost exact PID listener ownership')
                return request(port, token, route, origin, body)

            require(call(old, old_port, formal_token, origin=FORMAL_ORIGIN) ==
                    (200, {'running': False, 'run_id': None, 'version': '1.2.4'}), 'synthetic formal API failed')
            agent = launch([str(install / 'AutoScriptAgent.exe')], 'preview-agent', install)
            def discover():
                require(agent.poll() is None, 'Preview exited before discovery')
                token = token_path.read_text(encoding='ascii').strip()
                require(len(token) >= 43 and token != formal_token, 'Preview token not independent')
                return owned_listener(agent.pid), token
            port, token = wait_for(discover)
            require(port in PREVIEW_PORTS and port not in FORMAL_PORTS, 'wrong Preview port family')
            code, status = call(agent, port, token)
            require(code == 200 and status.get('version') == VERSION and status.get('install_flavor') == 'preview',
                    'frozen identity mismatch')
            require(call(agent, port, formal_token)[0] == 401, 'formal token accepted by Preview')
            require(call(agent, port, token, origin=FORMAL_ORIGIN)[0] == 403, 'formal Origin accepted by Preview')
            require(call(old, old_port, token, origin=FORMAL_ORIGIN)[0] == 401, 'Preview token accepted by formal API')
            updates = []
            for route, body, expected_code in (('/local/update', None, 200),
                    ('/local/update/check', {}, 200), ('/local/update/install', {}, 409)):
                code, value = call(agent, port, token, route, body=body)
                require(code == expected_code and value.get('updates_enabled') is False and
                        value.get('state') == 'idle' and 'Preview 暂不支持在线更新' in value.get('error', ''),
                        'online update did not fail closed')
                updates.append({'route': route, 'http': code, 'response': value})
            require(call(agent, port, token, '/lifecycle/shutdown', body={})[0] == 202, 'Preview shutdown rejected')
            agent.wait(timeout=45)
            agent._process_tree.confirm_stopped()
            stop_process_tree(agent)
            children.remove(agent)
            require(call(old, old_port, formal_token, origin=FORMAL_ORIGIN)[0] == 200,
                    'Preview shutdown affected synthetic formal API')
            require(not callback.exists(), 'formal shutdown callback invoked')
            require(manifest(formal) == before, 'synthetic formal data mutated')
            evidence.update(version=VERSION, install_flavor='preview', preview_port=port, formal_api_port=old_port,
                default_data=str(preview), preview_pid=agent.pid, formal_pid=old.pid,
                preview_graceful_shutdown=True, formal_shutdown_called=False, updates=updates,
                token_isolation=True, origin_isolation=True,
                limitations=['No Setup execution or real installation tested',
                             'Formal peer is frozen API code with synthetic callbacks and exclusive socket adapter, not a real old Agent',
                             'Update API refusal tested; no production network or installer invoked'])
    except BaseException as exc:
        evidence['error'] = str(exc)
        raise
    finally:
        errors = []
        for proc in reversed(children):
            try:
                stop_process_tree(proc)
            except Exception as exc:
                proc._process_tree.close()
                errors.append(str(exc))
        for log in logs:
            log.close()
        if before is not None:
            evidence['formal_after'] = manifest(formal)
            evidence['formal_unchanged'] = evidence['formal_after'] == before
            if not evidence['formal_unchanged']:
                errors.append('synthetic formal bytes changed')
        evidence['cleanup_confirmed'] = not errors
        evidence['cleanup_errors'] = errors
        evidence['ok'] = not errors and 'error' not in evidence and evidence.get('preview_graceful_shutdown', False)
        (root / 'result.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
        if errors:
            raise RuntimeError('cleanup/isolation unconfirmed: ' + '; '.join(errors))
    return evidence


def main():
    config = json.loads(Path(__file__).with_suffix('.json').read_text(encoding='utf-8'))
    result = run(Path(config['install']), Path(config['legacy']),
                 Path(config['private_runtime']) if config.get('private_runtime') else None)
    print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__':
    main()
