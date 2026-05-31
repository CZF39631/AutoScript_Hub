def config():
    return {
        "name": "测试脚本",
        "version": "1.0.0",
        "description": "一个示例脚本",
        "category": "测试",
        "params": [
            {"key": "url_file", "type": "file", "label": "URL文件", "required": True},
            {"key": "timeout", "type": "number", "label": "超时(秒)", "default": 30, "min": 1, "max": 600},
            {"key": "method", "type": "select", "label": "方式", "options": ["GET", "HEAD"], "default": "HEAD"},
            {"key": "verbose", "type": "checkbox", "label": "详细输出", "default": False},
        ],
        "requirements": ["DrissionPage>=4.0"],
        "timeout": 300,
    }


def main(url_file, timeout, method, verbose):
    print(f"Checking {url_file} with {method}, timeout={timeout}")
    return "/tmp/result.xlsx"
