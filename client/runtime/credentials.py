"""Windows-user-bound storage for desktop login credentials."""

import base64
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path

from client.runtime.paths import ClientPaths


class CredentialStorageError(RuntimeError):
    pass


_PATHS = ClientPaths.from_environment()
_CREDENTIAL_FILE = _PATHS.config_dir / "credentials.json"
_ENTROPY = b"AutoScriptHub desktop credentials v1"


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


if os.name == "nt":
    _crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob), wintypes.LPCWSTR, ctypes.POINTER(_DataBlob),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DataBlob),
    ]
    _crypt32.CryptProtectData.restype = wintypes.BOOL
    _crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.POINTER(_DataBlob),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DataBlob),
    ]
    _crypt32.CryptUnprotectData.restype = wintypes.BOOL
    _kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    _kernel32.LocalFree.restype = ctypes.c_void_p
else:
    _crypt32 = None
    _kernel32 = None


def _blob(data: bytes):
    buffer = ctypes.create_string_buffer(data)
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def _crypt_protect(data: bytes) -> bytes:
    if os.name != "nt":
        raise CredentialStorageError("系统不支持 Windows DPAPI")
    source, source_buffer = _blob(data)
    entropy, entropy_buffer = _blob(_ENTROPY)
    output = _DataBlob()
    if not _crypt32.CryptProtectData(
        ctypes.byref(source), None, ctypes.byref(entropy), None, None, 0x01, ctypes.byref(output)
    ):
        raise CredentialStorageError("保存登录凭据失败")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        _kernel32.LocalFree(output.pbData)
        del source_buffer, entropy_buffer


def _crypt_unprotect(data: bytes) -> bytes:
    if os.name != "nt":
        raise CredentialStorageError("系统不支持 Windows DPAPI")
    source, source_buffer = _blob(data)
    entropy, entropy_buffer = _blob(_ENTROPY)
    output = _DataBlob()
    if not _crypt32.CryptUnprotectData(
        ctypes.byref(source), None, ctypes.byref(entropy), None, None, 0x01, ctypes.byref(output)
    ):
        raise CredentialStorageError("读取登录凭据失败")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        _kernel32.LocalFree(output.pbData)
        del source_buffer, entropy_buffer


def _key(server_url: str, username: str) -> str:
    return server_url.rstrip("/").strip().lower() + "\n" + username.strip().lower()


def _read_store() -> dict:
    try:
        payload = json.loads(_CREDENTIAL_FILE.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}


def _write_store(payload: dict) -> None:
    _PATHS.ensure()
    temporary = Path(str(_CREDENTIAL_FILE) + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(temporary, _CREDENTIAL_FILE)


def save_credentials(server_url: str, username: str, password: str) -> None:
    if not server_url or not username or not password:
        raise CredentialStorageError("账号、密码和服务端地址不能为空")
    payload = _read_store()
    encrypted = _crypt_protect(password.encode("utf-8"))
    payload[_key(server_url, username)] = base64.b64encode(encrypted).decode("ascii")
    _write_store(payload)


def load_credentials(server_url: str, username: str) -> str:
    encoded = _read_store().get(_key(server_url, username))
    if not isinstance(encoded, str) or not encoded:
        return ""
    try:
        encrypted = base64.b64decode(encoded, validate=True)
        return _crypt_unprotect(encrypted).decode("utf-8")
    except (ValueError, UnicodeDecodeError, CredentialStorageError):
        return ""


def delete_credentials(server_url: str, username: str) -> None:
    payload = _read_store()
    if payload.pop(_key(server_url, username), None) is None:
        return
    if payload:
        _write_store(payload)
    else:
        try:
            _CREDENTIAL_FILE.unlink()
        except FileNotFoundError:
            pass
