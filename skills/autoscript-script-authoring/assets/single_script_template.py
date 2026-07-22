"""AutoScript Hub single-file template."""


def config():
    return {
        "name": "示例脚本",
        "version": "1.0.0",
        "description": "说明脚本完成的任务",
        "category": "通用",
        "params": [
            {"key": "source_file", "type": "file", "label": "源文件", "required": True},
            {"key": "output_dir", "type": "folder", "label": "输出目录", "required": True},
        ],
        "requirements": [],
        "timeout": 600,
        "presets": [],
    }


def main(source_file, output_dir):
    # Import third-party dependencies here, not at module scope.
    # Produce local files below output_dir and return their paths.
    return None
