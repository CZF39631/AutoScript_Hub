"""可配置诊断脱敏原语；不是任意敏感信息识别器或执行安全边界。"""

import json
import re
from urllib.parse import urlsplit, urlunsplit

REDACTED = "[已脱敏]"
MAX_PARAM_BYTES = 64 * 1024
MAX_DEPTH = 12
_KEY_PART = (
    r"password|passwd|pwd|secret|token|credential|authorization|cookie|api[-_]?key|"
    r"private[-_]?key|access[-_]?key|密码|口令|密钥|令牌"
)
_SECRET_KEY = re.compile(_KEY_PART, re.IGNORECASE)
_URL = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
_AUTH = re.compile(r"\b(Bearer|Basic)\s+[^\s\"',;]+", re.IGNORECASE)
_HEADERS = re.compile(r"(?im)^(\s*(?:authorization|proxy-authorization|cookie|set-cookie)\s*:)[^\r\n]*")
_PEM = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)",
    re.DOTALL,
)
_ORPHAN_PEM = re.compile(r"\A.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL)


def is_sensitive_key(key, custom_fields=()):
    return bool(_SECRET_KEY.search(str(key))) or str(key).casefold() in {
        field.casefold() for field in custom_fields
    }


def _redact_url(match):
    try:
        url = urlsplit(match.group())
        # 查询参数和 fragment 一律去除，不猜测签名参数名称。
        host = url.netloc.rsplit("@", 1)[-1]
        return urlunsplit((url.scheme, host, url.path, "", ""))
    except ValueError:
        return "[已脱敏链接]"


def redact_text(text, secrets=(), custom_fields=()):
    """去除常见凭据、URL 用户信息和已知敏感参数值。"""
    text = str(text)
    for secret in sorted(set(secrets), key=len, reverse=True):
        if secret:
            text = text.replace(secret, REDACTED)
    text = _PEM.sub(REDACTED, text)
    text = _ORPHAN_PEM.sub(REDACTED, text)
    text = _URL.sub(_redact_url, text)
    text = _AUTH.sub(lambda match: match.group(1) + " " + REDACTED, text)
    text = _HEADERS.sub(lambda match: match.group(1) + " " + REDACTED, text)
    key_pattern = r"[\w.-]*(?:" + _KEY_PART + r")[\w.-]*"
    if custom_fields:
        key_pattern += "|" + "|".join(re.escape(field) for field in custom_fields)
    assignment = re.compile(
        r"(?<![\w.-])(?P<key>" + key_pattern + r")(?P<sep>[\"']?\s*[:=]\s*)"
        r"(?:\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\r\n,;}]+)",
        re.IGNORECASE,
    )
    return assignment.sub(lambda match: match.group("key") + match.group("sep") + REDACTED, text)


def sensitive_values(value, custom_fields=()):
    """提取敏感键下的字符串，用于清理其他诊断字段。"""
    found = []

    def visit(item, sensitive=False, depth=0):
        if depth > MAX_DEPTH:
            return
        if isinstance(item, dict):
            for key, child in item.items():
                visit(child, sensitive or is_sensitive_key(key, custom_fields), depth + 1)
        elif isinstance(item, list):
            for child in item:
                visit(child, sensitive, depth + 1)
        elif sensitive and isinstance(item, (str, int, float)) and not isinstance(item, bool):
            if str(item):
                found.append(str(item))

    visit(value)
    return found


def redact_data(value, secrets=(), custom_fields=(), _depth=0):
    if _depth > MAX_DEPTH:
        return "[已省略深层数据]"
    if isinstance(value, dict):
        return {
            redact_text(key, secrets, custom_fields): REDACTED if is_sensitive_key(key, custom_fields)
            else redact_data(item, secrets, custom_fields, _depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_data(item, secrets, custom_fields, _depth + 1) for item in value]
    if isinstance(value, str):
        return redact_text(value, secrets, custom_fields)
    return value


def _reject_nonfinite(value):
    raise ValueError("诊断参数不能包含非有限数字")


def parse_diagnostic_params(raw):
    """畸形或过大历史参数不原样回传，限制与脱敏开关无关。"""
    if not raw:
        return {}
    if not isinstance(raw, str) or len(raw) > MAX_PARAM_BYTES or len(raw.encode("utf-8")) > MAX_PARAM_BYTES:
        return {"诊断提示": "参数超过采集上限，已省略"}
    try:
        result = json.loads(raw, parse_constant=_reject_nonfinite)
        if not isinstance(result, dict):
            raise ValueError("not an object")
        stack = [(result, 0)]
        while stack:
            item, depth = stack.pop()
            if depth > MAX_DEPTH:
                return {"诊断提示": "参数嵌套过深，已省略"}
            if isinstance(item, dict):
                stack.extend((child, depth + 1) for child in item.values())
            elif isinstance(item, list):
                stack.extend((child, depth + 1) for child in item)
        return result
    except (ValueError, TypeError, RecursionError):
        return {"诊断提示": "历史参数格式无效，已省略"}
