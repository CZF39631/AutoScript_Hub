"""先约束完成报告，再冻结重试载荷；输出过长不能阻止停止事实送达。"""
import json


def bounded_text(value, limit):
    if value is None:
        return None
    text = str(value)
    raw = text.encode('utf-8', errors='replace')
    if len(raw) <= limit:
        return raw.decode('utf-8')
    suffix = '\n[内容已截断]'
    return raw[:limit - len(suffix.encode('utf-8'))].decode('utf-8', errors='ignore') + suffix


def bounded_execution_output(error_msg, result_files, log_tail):
    files, truncated = [], False
    for path in result_files:
        if not isinstance(path, str):
            truncated = True
            continue
        candidate = files + [path]
        if len(candidate) > 100 or len(json.dumps(candidate, ensure_ascii=False).encode('utf-8')) > 65536:
            truncated = True
            break
        files = candidate
    if truncated:
        error_msg = '[结果文件列表已截断] ' + (str(error_msg) if error_msg else '')
    return {'error_msg': bounded_text(error_msg, 4096), 'result_files': files,
            'log_tail': bounded_text(log_tail or '', 65536)}
