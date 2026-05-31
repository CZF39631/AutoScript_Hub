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
        except Exception:
            pass
    return {}


def main():
    config = _load_config()

    if len(sys.argv) >= 3:
        username = sys.argv[1]
        password = sys.argv[2]
        frontend_url = sys.argv[3] if len(sys.argv) > 3 else config.get("frontend_url", "")
    else:
        username = config.get("username", "")
        password = config.get("password", "")
        frontend_url = config.get("frontend_url", "")

    if not username or not password:
        print("No credentials found. Run setup.py --client first,")
        print("or provide: python -m client.start <username> <password>")
        sys.exit(1)

    if not frontend_url:
        frontend_url = config.get("server_url", "http://127.0.0.1:8000")

    # Start Agent in background
    agent_proc = subprocess.Popen(
        [sys.executable, "-m", "client.agent.main", username, password],
        cwd=PROJECT_ROOT,
    )
    print("Agent started (PID {})".format(agent_proc.pid))

    # Start UI (blocking)
    try:
        ui_script = os.path.join(ROOT_DIR, "ui", "main.py")
        subprocess.run(
            [sys.executable, ui_script, frontend_url],
            cwd=PROJECT_ROOT,
        )
    finally:
        agent_proc.terminate()
        print("Agent stopped")


if __name__ == "__main__":
    main()
