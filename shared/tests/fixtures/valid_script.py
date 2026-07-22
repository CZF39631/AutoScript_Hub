def config():
    return {
        "name": "契约样例",
        "version": "1.0.0",
        "description": "覆盖全部参数类型的样例",
        "category": "测试",
        "params": [
            {"key": "title", "type": "text", "label": "标题", "required": True},
            {"key": "count", "type": "number", "label": "数量", "default": 2, "min": 1, "max": 5},
            {"key": "source", "type": "file", "label": "源文件"},
            {"key": "output", "type": "folder", "label": "输出目录"},
            {"key": "mode", "type": "select", "label": "模式", "options": ["fast", "safe"], "default": "safe"},
            {"key": "verbose", "type": "checkbox", "label": "详细日志", "default": False},
        ],
        "requirements": ["requests>=2.31"],
        "timeout": 300,
        "presets": [{"name": "快速", "values": {"count": 1, "mode": "fast"}}],
    }


def main(title, count, source, output, mode, verbose):
    return {"files": [], "summary": title}
