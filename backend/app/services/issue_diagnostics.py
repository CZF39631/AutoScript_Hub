"""工单只保存服务端已有执行日志的有界、脱敏快照，不采集客户端文件。"""

from pathlib import Path

from app.services.diagnostic_policy import DiagnosticPolicy

MAX_LOG_BYTES = 64 * 1024
MAX_LOG_LINES = 500
TRUNCATED = "[日志已截断，仅保留末尾片段]\n"


def bounded_log(text, secrets=(), policy=None):
    policy = policy if policy is not None else DiagnosticPolicy()
    cleaned = policy.text(text, "logs", secrets)
    lines = cleaned.splitlines(keepends=True)
    truncated = len(lines) > MAX_LOG_LINES
    cleaned = "".join(lines[-MAX_LOG_LINES:])
    encoded = cleaned.encode("utf-8")
    limit = MAX_LOG_BYTES - len(TRUNCATED.encode("utf-8"))
    if len(encoded) > limit:
        # 从完整行开始，避免返回被截断的凭据或私钥标记。
        tail = encoded[-limit:]
        cleaned = tail.split(b"\n", 1)[1].decode("utf-8", errors="replace") if b"\n" in tail else ""
        truncated = True
    return (TRUNCATED if truncated else "") + cleaned


def capture_run_log(run_id, secrets=(), policy=None):
    from app.config import LOGS_DIR

    path = Path(LOGS_DIR) / f"{int(run_id)}.log"
    try:
        with path.open("rb") as stream:
            size = stream.seek(0, 2)
            start = max(0, size - MAX_LOG_BYTES)
            stream.seek(start)
            raw = stream.read(MAX_LOG_BYTES)
    except OSError:
        return ""
    if start:
        # 丢弃尾部读取切中的首行，不把半截密码作为普通文字返回。
        raw = raw.split(b"\n", 1)[1] if b"\n" in raw else b""
    text = raw.decode("utf-8", errors="replace")
    return bounded_log((TRUNCATED if start else "") + text, secrets, policy)
