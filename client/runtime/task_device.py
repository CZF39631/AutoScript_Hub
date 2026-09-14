"""Independent TaskDevice identity; secrets never cross the local API boundary."""
import json
import os
import secrets
import socket
import uuid
import threading
from functools import wraps


def _locked(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return call
from pathlib import Path

from client.runtime.credentials import _crypt_protect, _crypt_unprotect


class TaskDevice:
    def __init__(self, path, request, version, scope):
        self._lock = threading.RLock()
        self.path = Path(path)
        self.request = request
        self.version = version
        self.scope = scope
        self.identity = None
        self.registered = None
        self.grants_cache = []
        self.grants_online = False

    @_locked
    def load(self):
        if self.identity is not None:
            return
        if self.path.exists():
            self.identity = json.loads(_crypt_unprotect(self.path.read_bytes()))
        else:
            self.identity = {'device_uuid': str(uuid.uuid4()), 'device_secret': secrets.token_urlsafe(48), 'scope': self.scope}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix('.new')
            temp.write_bytes(_crypt_protect(json.dumps(self.identity).encode()))
            os.replace(temp, self.path)
        if self.identity.get('scope') != self.scope:
            raise ValueError('设备凭据绑定另一服务端或账号，拒绝自动迁移')

    def public(self):
        self.load()
        registered = self.registered or {}
        return {'id': registered.get('id'), 'name': registered.get('name', socket.gethostname()),
                'status': registered.get('status', 'unregistered'), 'device_uuid': self.identity['device_uuid'],
                'registered': self.registered is not None, 'wakes_sleeping_machine': False,
                'grants_online': self.grants_online}

    @_locked
    def register(self):
        self.load()
        result = self.request('POST', '/api/task-devices/register',
                              {k: self.identity[k] for k in ('device_uuid', 'device_secret')} |
                              {'name': socket.gethostname(), 'agent_version': self.version})
        if not isinstance(result, dict) or type(result.get('id')) is not int:
            raise ValueError('设备注册响应无效')
        self.registered = result
        return result

    @property
    def prefix(self):
        if not self.registered:
            raise ValueError('任务设备尚未注册')
        return '/api/task-devices/' + str(self.registered['id'])

    @_locked
    def notification_identity(self, scope):
        """Internal immutable snapshot; never expose this through the local API."""
        if scope != self.scope or not self.registered or not self.identity:
            return None
        return self.registered['id'], self.identity['device_secret']

    @_locked
    def call(self, method, suffix, body=None):
        self.load()
        return self.request(method, self.prefix + suffix, body,
                            {'X-Device-Token': self.identity['device_secret']})

    def grants(self):
        try:
            value = self.call('GET', '/grants')
            if not isinstance(value, list):
                raise ValueError('授权列表响应无效')
            self.grants_cache = value
            self.grants_online = True
        except Exception:
            self.grants_online = False
        return list(self.grants_cache)

    def decision(self, ident, body):
        if body.get('decision') not in ('accept', 'reject', 'revoke'):
            raise ValueError('无效设备授权决策')
        return self.call('POST', '/grants/' + str(int(ident)) + '/decision', {'decision': body['decision']})
