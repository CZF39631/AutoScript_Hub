"""PyInstaller entrypoint for the independent background Agent."""

import os
import multiprocessing

# 冻结包中的准备进程须先分流到 multiprocessing worker，不能再次启动 Agent。
if __name__ == "__main__":
    multiprocessing.freeze_support()

import autoscript_build_info
from autoscript_build_info import CHANNEL, VERSION
from shared.version import is_preview_version

os.environ["AUTOSCRIPT_VERSION"] = VERSION
os.environ["AUTOSCRIPT_CHANNEL"] = CHANNEL
os.environ["AUTOSCRIPT_INSTALL_FLAVOR"] = getattr(
    autoscript_build_info, "INSTALL_FLAVOR", "preview" if is_preview_version(VERSION) else "stable"
)

from client.agent.main import run_agent
from client.ui.config_manager import load_config


def main():
    config = load_config()
    username = config.get("username", "")
    password = config.get("password", "")
    if not username or not password:
        raise SystemExit("客户端尚未配置登录信息；请先打开 AutoScriptHub.exe")
    run_agent(username, password)


if __name__ == "__main__":
    main()
