#!/usr/bin/env python3
"""Frozen prepare acceptance; Windows only, temporary artifacts only, never an installer.

Run from the matching source snapshot. Current Agent has no port-discovery file:
use the Windows TCP owner table (only the exact child PID), never probe fallback
ports. A private token proves API identity as a second independent check.
"""
from __future__ import annotations

import argparse
import ctypes
from datetime import datetime
import json
import os
from pathlib import Path
import secrets
import socket
import struct
import sys
import tempfile
import time
from urllib.request import ProxyHandler, Request, build_opener
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[2]


def validate_paths(install: Path, data: Path, temp: Path | None = None) -> tuple[Path, Path]:
    temp = (temp or Path(tempfile.gettempdir())).resolve()
    # Reject junctions/symlinks before resolution, including ancestors.
    for path in (install, data):
        if not path.is_absolute():
            raise ValueError('absolute paths required')
        for part in (path, *path.parents):
            if part.exists() and (part.is_symlink() or getattr(part.stat(), 'st_file_attributes', 0) & 0x400):
                raise ValueError('reparse paths are forbidden')
    install, data = install.resolve(), data.resolve()
    forbidden = [ROOT / 'tmp', Path.home() / '.local' / 'share' / 'AutoScriptHub']
    if os.environ.get('LOCALAPPDATA'):
        forbidden += [Path(os.environ['LOCALAPPDATA']) / 'AutoScriptHub',
                      Path(os.environ['LOCALAPPDATA']) / 'Programs' / 'AutoScriptHub']
    for path in (install, data):
        if path == temp or not path.is_relative_to(temp):
            raise ValueError('only OS temporary artifacts are permitted')
        if any(path == p.resolve() or path.is_relative_to(p.resolve()) for p in forbidden):
            raise ValueError('real client or repository tmp path forbidden')
    if data == install or data.is_relative_to(install) or install.is_relative_to(data):
        raise ValueError('install and data must be disjoint')
    if data.exists() and (not data.is_dir() or any(data.iterdir())):
        raise ValueError('data directory must be empty')
    for relative in ('AutoScriptAgent.exe', 'runtime/python/python.exe'):
        executable = install / relative
        if not executable.is_file() or executable.resolve() != executable:
            raise ValueError('missing or redirected artifact: ' + relative)
        for part in (executable, *executable.parents):
            if getattr(part.stat(), 'st_file_attributes', 0) & 0x400:
                raise ValueError('reparse artifact forbidden')
    return install, data


def child_environment(data: Path, backend: str) -> dict[str, str]:
    # Allowlist: no inherited backend, credentials, proxies, pip config or loader paths.
    env = {k: os.environ[k] for k in ('SystemRoot', 'WINDIR', 'COMSPEC') if k in os.environ}
    system = env.get('SystemRoot', r'C:\Windows')
    env.update(PATH=system + os.pathsep + str(Path(system) / 'System32'),
               AUTOSCRIPT_CLIENT_DATA_DIR=str(data), AUTOSCRIPT_INSTALL_FLAVOR='preview', BACKEND_URL=backend,
               LOCALAPPDATA=str(data / 'profile'), APPDATA=str(data / 'profile'),
               USERPROFILE=str(data / 'profile'), HOME=str(data / 'profile'),
               TEMP=str(data / 'scratch'), TMP=str(data / 'scratch'),
               PIP_CONFIG_FILE=os.devnull, PIP_NO_INDEX='1', PIP_DISABLE_PIP_VERSION_CHECK='1',
               PYTHONNOUSERSITE='1')
    return env


def owned_listener(pid: int) -> int:
    """Read TCP ownership; no requests to another process, no port scan."""
    from ctypes import wintypes as w
    api = ctypes.WinDLL('iphlpapi', use_last_error=True).GetExtendedTcpTable
    api.argtypes = [ctypes.c_void_p, ctypes.POINTER(w.ULONG), w.BOOL, w.ULONG, w.ULONG, w.ULONG]
    api.restype = w.ULONG
    size = w.ULONG()
    if api(None, ctypes.byref(size), False, 2, 3, 0) != 122:
        raise RuntimeError('TCP ownership sizing failed')
    buffer = ctypes.create_string_buffer(size.value)
    if api(buffer, ctypes.byref(size), False, 2, 3, 0):
        raise RuntimeError('TCP ownership lookup failed')
    raw = buffer.raw
    ports = []
    listeners = []
    for offset in range(4, 4 + struct.unpack_from('<I', raw)[0] * 24, 24):
        state, address, port, _, _, owner = struct.unpack_from('<6I', raw, offset)
        if state == 2:
            listeners.append((owner, address, socket.ntohs(port & 0xffff)))
        if owner == pid and state == 2 and address == struct.unpack('<I', socket.inet_aton('127.0.0.1'))[0]:
            ports.append(socket.ntohs(port & 0xffff))
    if len(ports) != 1:
        raise RuntimeError('exact child must own exactly one loopback listener')
    loopback = struct.unpack('<I', socket.inet_aton('127.0.0.1'))[0]
    if any(owner != pid and address in (0, loopback) and port == ports[0] for owner, address, port in listeners):
        raise RuntimeError('ambiguous listener ownership; no request sent')
    return ports[0]


def request(port: int, token: str, route: str, body=None):
    req = Request(f'http://127.0.0.1:{port}' + route,
                  data=None if body is None else json.dumps(body).encode(),
                  headers={'Authorization': 'Bearer ' + token,
                           'Origin': 'http://127.0.0.1:18181', 'Content-Type': 'application/json'})
    try:
        with build_opener(ProxyHandler({})).open(req, timeout=2) as response:
            return json.load(response)
    except HTTPError as exc:
        raise RuntimeError('isolated API ' + route + ' returned HTTP ' + str(exc.code)) from exc


def wait_for(callback, timeout=45):
    deadline = time.monotonic() + timeout
    error = None
    while time.monotonic() < deadline:
        try:
            value = callback()
            if value:
                return value
        except (OSError, ValueError, RuntimeError) as exc:
            error = exc
        time.sleep(.2)
    raise RuntimeError('bounded acceptance wait expired') from error


def seed(data: Path, backend: str, marker: str):
    for name in ('config', 'scripts', 'environments', 'profile', 'scratch', 'logs'):
        (data / name).mkdir(parents=True, exist_ok=True)
    (data / '.install-flavor').write_text('preview\n', encoding='ascii')
    config = {'server_url': backend, 'username': 'synthetic-prepare-smoke',
              'password': 'synthetic-not-a-real-password', 'setup_completed': True,
              'github_update_repository': '', 'gitee_update_repository': '',
              'update_manifest_urls': [], 'update_channel': 'preview', 'pip_index_url': backend}
    (data / 'config/client.json').write_text(json.dumps(config), encoding='utf-8')
    (data / 'config/script_authorizations.json').write_text(json.dumps({
        'server_url': backend, 'username': config['username'], 'user_id': 1,
        'script_ids': [1, 2], 'synced_at': datetime.now().isoformat()}), encoding='utf-8')
    for ident, requirements in ((1, []), (2, ['autoscript-smoke-never-install==0.0.1'])):
        directory = data / 'scripts' / str(ident) / '1'
        directory.mkdir(parents=True)
        payload = {'name': 'synthetic prepare', 'description': 'isolated acceptance',
                   'version': '1.0.0', 'author': 'synthetic', 'category': 'test', 'requirements': requirements,
                   'params': [], 'timeout': 30}
        source = ('def config():\n    return ' + repr(payload) + '\n\n'
                  'def main():\n    print(' + repr(marker if ident == 1 else marker + '-FORBIDDEN') + ', flush=True)\n'
                  '\nif __name__ == "__main__":\n    main()\n')
        (directory / 'main.py').write_text(source, encoding='utf-8')


def run(install: Path, data: Path, expected: str) -> dict:
    if os.name != 'nt':
        raise RuntimeError('Windows acceptance only')
    if expected != '1.3.0-preview.1':
        raise ValueError('this acceptance contract requires 1.3.0-preview.1')
    install, data = validate_paths(install, data)
    sys.path.insert(0, str(ROOT))
    # Only containment utilities are imported; never import Agent/config modules.
    from client.runtime.process_tree import spawn_contained, stop_process_tree
    children = []
    marker = 'PREPARE_SMOKE_' + secrets.token_hex(16)
    with socket.socket() as reserved:
        reserved.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        reserved.bind(('127.0.0.1', 0))  # Bound, not listening: nobody can impersonate a backend.
        backend = 'http://127.0.0.1:' + str(reserved.getsockname()[1])
        seed(data, backend, marker)
        env = child_environment(data, backend)
        private = install / 'runtime/python/python.exe'
        def command(args, timeout=120):
            with (data / 'logs/prewarm.log').open('ab') as log:
                proc = spawn_contained(args, cwd=install, env=env, stdout=log, stderr=log)
                children.append(proc)
                try:
                    if proc.wait(timeout=timeout):
                        raise RuntimeError('private Python prewarm command failed')
                finally:
                    stop_process_tree(proc)
                    children.remove(proc)
        try:
            # venv/ensurepip use the private distribution's bundled wheels only.
            command([str(private), '-I', '-c', 'import sys; assert sys.version_info[:3] == (3,11,9)'])
            # Use the real environment builder; never synthesize ready metadata.
            prewarm = (
                'import sys; sys.path.insert(0, ' + repr(str(ROOT)) + '); '
                'from client.runtime.paths import ClientPaths; '
                'from client.runtime.environment_manager import ensure_environment; '
                'paths = ClientPaths.from_environment(install_dir=' + repr(str(install)) + ', data_dir=' + repr(str(data)) + '); '
                'result = ensure_environment([], paths, index_url=' + repr(backend) + ', offline=False, python_executable=' + repr(str(private)) + '); '
                'assert result.python_executable.is_file()'
            )
            command([sys.executable, '-I', '-c', prewarm])
            with (data / 'logs/frozen-agent.log').open('wb') as log:
                agent = spawn_contained([str(install / 'AutoScriptAgent.exe')], cwd=install,
                                        env=env, stdout=log, stderr=log)
                children.append(agent)
                def discover():
                    if agent.poll() is not None:
                        raise RuntimeError('owned Agent exited')
                    token = (data / 'config/agent-api.token').read_text(encoding='ascii').strip()
                    if len(token) < 43:
                        raise RuntimeError('invalid isolated token')
                    return owned_listener(agent.pid), token
                port, token = wait_for(discover)
                def api(route, body=None):
                    if agent.poll() is not None or owned_listener(agent.pid) != port:
                        raise RuntimeError('lost process/endpoint ownership')
                    return request(port, token, route, body)
                status = api('/status')
                runtime = api('/local/runtime')
                if status.get('version') != expected or runtime.get('version') != '3.11.9' or runtime.get('managed') is not True:
                    raise RuntimeError('frozen version/private runtime mismatch')
                if api('/local/connection').get('online') is not False:
                    raise RuntimeError('synthetic client unexpectedly online')
                results = []
                for ident in (1, 2):
                    rec = api('/local/execute', {'script_id': ident, 'script_version': 1,
                                               'params': {}, 'timeout_seconds': 30})
                    run_id = rec.get('local_run_id')
                    if not isinstance(run_id, str) or not run_id.startswith('L') or '/' in run_id:
                        raise RuntimeError('local execution was not accepted')
                    def finished():
                        record = api('/local/runs/' + run_id)
                        return record if record.get('finished_at') else None
                    result = wait_for(finished, 45)
                    logs = api('/local/runs/' + run_id + '/log').get('log', '')
                    if ident == 1 and (result.get('status') != 'success' or marker not in logs):
                        raise RuntimeError('frozen prepare did not execute marker')
                    if ident == 2 and (result.get('status') != 'failed' or
                                       '离线状态缺少所需脚本环境' not in str(result.get('error_msg')) or marker in logs):
                        raise RuntimeError('uncached offline dependency did not fail closed')
                    results.append({'script_id': ident, 'status': result['status']})
                evidence = {'ok': True, 'version': expected, 'python': '3.11.9',
                            'agent_pid': agent.pid, 'discovery': 'exact-pid-tcp-owner-table',
                            'marker': marker, 'runs': results}
        finally:
            cleanup_errors = []
            for proc in reversed(children):
                try:
                    stop_process_tree(proc)
                except Exception as exc:
                    proc._process_tree.close()  # kill-on-close remains the last safety net
                    cleanup_errors.append(str(exc))
            if cleanup_errors:
                raise RuntimeError('owned process cleanup unconfirmed: ' + '; '.join(cleanup_errors))
    evidence['cleanup_confirmed'] = True
    return evidence


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install-dir', type=Path, required=True)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--expected-version', required=True)
    args = parser.parse_args(argv)
    try:
        evidence = run(args.install_dir, args.data_dir, args.expected_version)
    except Exception as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=True))
        return 1
    print(json.dumps(evidence, ensure_ascii=True, separators=(',', ':')))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
