"""本机白名单诊断；调用方仅在可信服务器认证成功后更新有效策略。"""
import logging
import os
import stat
from logging.handlers import RotatingFileHandler
from pathlib import Path
import platform
import re
import threading
from shared.diagnostics import redact_text
from shared.version import get_version

_lock = threading.RLock()
_policy = {'enabled': True, 'redact_logs': True, 'redact_params': True, 'redact_summary': True, 'custom_sensitive_fields': [], 'retention_days': 30}
MAX_LOG_BYTES = 32 * 1024
MAX_LOG_LINES = 200


def update_effective_policy(value: dict):
    """只接收已认证服务器 /api/settings/diagnostics/effective 的完整响应；无效值恢复安全默认。"""
    defaults = {'enabled': True, 'redact_logs': True, 'redact_params': True, 'redact_summary': True, 'custom_sensitive_fields': [], 'retention_days': 30}
    valid = isinstance(value, dict) and all(type(value.get(k)) is bool for k in ('enabled', 'redact_logs', 'redact_params', 'redact_summary'))
    fields = value.get('custom_sensitive_fields') if isinstance(value, dict) else None
    valid = valid and type(value.get('retention_days', 30)) is int and 1 <= value.get('retention_days', 30) <= 365
    valid = valid and isinstance(fields, list) and len(fields) <= 50 and all(isinstance(v, str) and 0 < len(v) <= 64 and not any(ord(c) < 32 for c in v) for v in fields)
    with _lock:
        _policy.clear()
        _policy.update({**defaults, **{k: list(value[k]) if isinstance(value[k], list) else value[k] for k in defaults if k in value}} if valid else defaults)


def _private_paths(text):
    return re.sub(r'(?:[A-Za-z]:[\\/]|/(?:home|Users|root)/)[^\s\"\'<>]+', '[本机路径]', text)


class _SafeFormatter(logging.Formatter):
    def format(self, record):
        # Never persist credentials/private paths, even when diagnostic upload protection is disabled.
        text = _private_paths(redact_text(super().format(record)))
        return text.encode('utf-8')[:MAX_LOG_BYTES].decode('utf-8', errors='ignore')


class _ByteRotatingFileHandler(RotatingFileHandler):
    """stdlib 使用字符长度估算轮转；这里按实际 UTF-8 / Windows 换行字节计算。"""
    def shouldRollover(self, record):
        if self.stream is None:
            self.stream = self._open()
        self.stream.seek(0, 2)
        message = self.format(record) + self.terminator
        if os.linesep != '\n':
            message = message.replace('\n', os.linesep)
        return self.stream.tell() + len(message.encode('utf-8')) >= self.maxBytes


def configure_application_logging(kind, paths):
    if kind not in ('agent', 'desktop'):
        raise ValueError('unsupported application kind')
    directory = Path(paths.logs_dir)
    directory.mkdir(parents=True, exist_ok=True)
    if directory.is_symlink() or any((directory / (kind + '.log' + suffix)).is_symlink() for suffix in ('', '.1', '.2')):
        raise ValueError('unsafe application log path')
    target = str((directory / (kind + '.log')).resolve())
    with _lock:
        root = logging.getLogger()
        for handler in root.handlers:
            if isinstance(handler, RotatingFileHandler) and handler.baseFilename == target:
                return handler
        handler = _ByteRotatingFileHandler(target, maxBytes=256 * 1024, backupCount=2, encoding='utf-8')
        handler.setFormatter(_SafeFormatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
        root.addHandler(handler)
        if root.level > logging.INFO:
            root.setLevel(logging.INFO)
        return handler


def collect_diagnostics(paths, agent_id, online):
    """不联网。返回平面白名单摘要和 application_logs={agent,desktop}；不含路径/env。"""
    with _lock:
        policy = dict(_policy) if online else {'enabled': True, 'redact_logs': True, 'custom_sensitive_fields': []}
    logs = {}
    states = []
    for kind in ('agent', 'desktop'):
        path = Path(paths.logs_dir) / (kind + '.log')
        try:
            if path.is_symlink() or Path(paths.logs_dir).is_symlink() or not path.is_file():
                raise OSError('unsafe log file')
            fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0))
            with os.fdopen(fd, 'rb') as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise OSError('not a regular file')
                size = stream.seek(0, 2)
                start = max(0, size - MAX_LOG_BYTES)
                stream.seek(start)
                raw = stream.read(MAX_LOG_BYTES)
            if start:
                raw = raw.split(b'\n', 1)[1] if b'\n' in raw else b''
            text = '\n'.join(raw.decode('utf-8', errors='replace').splitlines()[-MAX_LOG_LINES:])
            # Upload protection follows the effective policy. Application logging itself
            # always protects credentials before persistence; disabling cannot restore them.
            if policy['enabled'] and policy['redact_logs']:
                text = _private_paths(redact_text(text, custom_fields=policy['custom_sensitive_fields']))
            logs[kind] = text.encode('utf-8')[:MAX_LOG_BYTES].decode('utf-8', errors='ignore')
            states.append('collected')
        except OSError:
            states.append('unavailable')
    return {'client_version': get_version(), 'agent_version': get_version(), 'agent_id': str(agent_id or '')[:128], 'online': bool(online), 'system': platform.system(), 'machine': platform.machine(), 'python_version': platform.python_version(), 'collection_state': 'collected' if all(s == 'collected' for s in states) else 'partial', 'application_logs': logs}
