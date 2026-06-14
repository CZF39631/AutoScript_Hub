"""Start both Agent and UI processes."""
import json
import subprocess
import sys
import os

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(ROOT_DIR)
CLIENT_CONFIG_PATH = os.path.join(PROJECT_ROOT, "client_config.json")


def _load_config():
    if os.path.isfile(CLIENT_CONFIG_PATH):
        try:
            with open(CLIENT_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


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
        agent_proc.terminate()
        print("Agent 已停止")


if __name__ == "__main__":
    main()
