"""PyInstaller entrypoint for the independent background Agent."""

import os

from autoscript_build_info import CHANNEL, VERSION

os.environ["AUTOSCRIPT_VERSION"] = VERSION
os.environ["AUTOSCRIPT_CHANNEL"] = CHANNEL

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
