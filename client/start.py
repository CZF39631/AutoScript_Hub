"""Start both Agent and UI processes."""
import subprocess
import sys
import urllib.request

from client.runtime.local_auth import get_or_create_agent_token
from client.runtime.paths import ClientPaths
from client.ui.config_manager import load_config

_PATHS = ClientPaths.from_environment()
_PATHS.ensure()
PROJECT_ROOT = str(_PATHS.install_dir)


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
    config = load_config()

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
