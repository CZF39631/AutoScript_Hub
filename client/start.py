"""Start both Agent and UI processes."""
import json
import subprocess
import sys
import os
import urllib.request

from client.runtime.local_auth import get_or_create_agent_token
from client.runtime.paths import ClientPaths

_PATHS = ClientPaths.from_environment()
_PATHS.ensure()
PROJECT_ROOT = str(_PATHS.install_dir)
CLIENT_CONFIG_PATH = str(_PATHS.config_file)
LEGACY_CLIENT_CONFIG_PATH = os.path.join(PROJECT_ROOT, "client_config.json")


def _load_config():
    source = CLIENT_CONFIG_PATH if os.path.isfile(CLIENT_CONFIG_PATH) else LEGACY_CLIENT_CONFIG_PATH
    if os.path.isfile(source):
        try:
            with open(source, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _request_agent_shutdown():
    request = urllib.request.Request(
        "http://127.0.0.1:18080/lifecycle/shutdown",
        data=b"{}",
        method="POST",
        headers={"Authorization": "Bearer " + get_or_create_agent_token()},
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        return response.status == 202


def main():
    config = _load_config()

    if len(sys.argv) >= 3:
        username = sys.argv[1]
        password = sys.argv[2]
    else:
        username = config.get("username", "")
        password = config.get("password", "")

    if not username or not password:
        print("未找到凭据。请先运行 setup.py --client,")
        print("或使用:python -m client.start <用户名> <密码>")
        sys.exit(1)

    # Start Agent in background
    agent_proc = subprocess.Popen(
        [sys.executable, "-m", "client.agent.main", username, password],
        cwd=PROJECT_ROOT,
    )
    print("Agent 已启动 (PID {})".format(agent_proc.pid))

    # Start UI (blocking) — UI manages its own local frontend server
    try:
        subprocess.run(
            [sys.executable, "-m", "client.ui.main"],
            cwd=PROJECT_ROOT,
        )
    finally:
        try:
            _request_agent_shutdown()
            print("已通知 Agent 完成当前任务后退出")
            agent_proc.wait()
        except Exception:
            agent_proc.terminate()
            agent_proc.wait(timeout=5)
        print("Agent 已停止")


if __name__ == "__main__":
    main()
