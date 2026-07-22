"""AutoScript Hub multi-file root entrypoint template."""


def config():
    return {
        "name": "多文件示例",
        "version": "1.0.0",
        "description": "说明多文件脚本完成的任务",
        "category": "通用",
        "params": [{"key": "value", "type": "text", "label": "输入", "required": True}],
        "requirements": [],
        "timeout": 600,
        "presets": [],
    }


def main(value):
    from worker import run
    return run(value)
