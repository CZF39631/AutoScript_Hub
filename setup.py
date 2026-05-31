"""AutoScript Hub Setup - Server & Client modes.

Usage:
  python setup.py --server   # Configure & install server (backend + frontend)
  python setup.py --client   # Configure & install client (agent + UI)
"""
import json
import os
import secrets
import subprocess
import sys
import winreg

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.json")
CLIENT_CONFIG_PATH = os.path.join(PROJECT_ROOT, "client_config.json")
VENV_DIR = os.path.join(PROJECT_ROOT, ".venv")


# ── Helpers ──────────────────────────────────────────────────────────

def _input(prompt, default=None):
    if default is not None:
        line = input("{} [{}]: ".format(prompt, default)).strip()
    else:
        line = input("{}: ".format(prompt)).strip()
    return line if line else default


def _detect_python_versions():
    results = []
    seen = set()

    try:
        proc = subprocess.run(
            ["py", "--list"], capture_output=True, text=True, timeout=10
        )
        if proc.returncode == 0:
            for line in proc.stdout.strip().splitlines():
                line = line.strip()
                if not line:
                    continue
                version = None
                path = None
                for p in line.split():
                    if p.startswith("-V:"):
                        version = p[3:]
                    if "python" in p.lower():
                        path = p
                if path and path.lower() not in seen and os.path.isfile(path):
                    seen.add(path.lower())
                    results.append({"version": version or "unknown", "path": os.path.normpath(path)})
    except Exception:
        pass

    for hive, flags in [
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY),
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY),
        (winreg.HKEY_CURRENT_USER, 0),
    ]:
        try:
            key = winreg.OpenKey(hive, r"SOFTWARE\Python\PythonCore", 0, winreg.KEY_READ | flags)
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(key, i)
                    i += 1
                    try:
                        ik = winreg.OpenKey(key, sub + r"\InstallPath", 0, winreg.KEY_READ)
                        ipath, _ = winreg.QueryValueEx(ik, "")
                        winreg.CloseKey(ik)
                    except OSError:
                        continue
                    exe = os.path.join(ipath, "python.exe")
                    if os.path.isfile(exe) and exe.lower() not in seen:
                        seen.add(exe.lower())
                        results.append({"version": sub, "path": os.path.normpath(exe)})
                except OSError:
                    break
            winreg.CloseKey(key)
        except OSError:
            pass

    return results


def _select_python():
    pythons = _detect_python_versions()
    if not pythons:
        print("ERROR: No Python installations found.")
        sys.exit(1)
    print("Detected Python versions:")
    for i, p in enumerate(pythons, 1):
        print("  {}. Python {} ({})".format(i, p["version"], p["path"]))
    idx = int(_input("Select Python version (1-{})".format(len(pythons)), "1"))
    idx = max(1, min(idx, len(pythons))) - 1
    return pythons[idx]


def _ensure_venv(selected_python=None):
    venv_python = os.path.join(VENV_DIR, "Scripts", "python.exe")
    if os.path.isfile(venv_python):
        print("[OK] Virtual environment exists: {}".format(VENV_DIR))
        return venv_python

    if not selected_python:
        selected_python = _select_python()

    print("Creating venv at {} with Python {}...".format(VENV_DIR, selected_python["version"]))
    proc = subprocess.run(
        [selected_python["path"], "-m", "venv", VENV_DIR],
        capture_output=True, text=True, timeout=120,
    )
    if proc.returncode != 0:
        print("ERROR: venv creation failed: {}".format(proc.stderr))
        sys.exit(1)
    print("[OK] Virtual environment created.")
    return os.path.join(VENV_DIR, "Scripts", "python.exe")


def _install_deps(venv_python, *req_files):
    for req_file in req_files:
        if not os.path.isfile(req_file):
            continue
        label = os.path.basename(os.path.dirname(req_file)).title()
        print("Installing {} dependencies...".format(label))
        proc = subprocess.run(
            [venv_python, "-m", "pip", "install", "-r", req_file, "-q"],
            capture_output=True, text=True, timeout=300,
        )
        if proc.returncode != 0:
            print("WARNING: {} deps had issues: {}".format(label, proc.stderr[:200]))
        else:
            print("[OK] {} dependencies installed.".format(label))


# ── Server Setup ─────────────────────────────────────────────────────

def setup_server():
    print("=" * 50)
    print("  AutoScript Hub - Server Setup")
    print("=" * 50)
    print()

    # 1. Venv
    print("--- Step 1: Virtual Environment ---")
    venv_python = _ensure_venv()

    # 2. Install all deps
    print("\n--- Step 2: Install Dependencies ---")
    _install_deps(
        venv_python,
        os.path.join(PROJECT_ROOT, "backend", "requirements.txt"),
        os.path.join(PROJECT_ROOT, "client", "requirements.txt"),
    )

    # 3. Build frontend
    print("\n--- Step 3: Build Frontend ---")
    frontend_dir = os.path.join(PROJECT_ROOT, "frontend")
    static_dir = os.path.join(PROJECT_ROOT, "backend", "static")
    if os.path.isdir(os.path.join(frontend_dir, "node_modules")):
        print("Building frontend...")
        proc = subprocess.run(
            ["npm", "run", "build"],
            cwd=frontend_dir, capture_output=True, text=True, timeout=120,
        )
        if proc.returncode != 0:
            print("WARNING: Frontend build failed: {}".format(proc.stderr[:300]))
            print("  You can build manually: cd frontend && npm run build")
        else:
            # Copy dist to backend/static
            import shutil
            dist_dir = os.path.join(frontend_dir, "dist")
            if os.path.isdir(static_dir):
                shutil.rmtree(static_dir)
            if os.path.isdir(dist_dir):
                shutil.copytree(dist_dir, static_dir)
                print("[OK] Frontend built and copied to backend/static/")
            else:
                print("WARNING: dist/ not found after build")
    else:
        print("SKIP: node_modules not found. Run 'cd frontend && npm install' first.")

    # 4. Configuration
    print("\n--- Step 4: Server Configuration ---")
    existing = {}
    if os.path.isfile(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            existing = json.load(f)

    config = {
        "storage_dir": _input("Storage directory", existing.get("storage_dir", "backend/storage")),
        "scripts_dir": _input("Scripts directory", existing.get("scripts_dir", "backend/storage/scripts")),
        "logs_dir": _input("Logs directory", existing.get("logs_dir", "backend/storage/logs")),
        "admin_username": _input("Admin username", existing.get("admin_username", "admin")),
        "admin_password": _input("Admin password", existing.get("admin_password", "admin123")),
        "jwt_secret": _input("JWT secret (enter to auto-generate)", existing.get("jwt_secret", "")) or secrets.token_hex(32),
        "backend_host": _input("Backend host", existing.get("backend_host", "127.0.0.1")),
        "backend_port": int(_input("Backend port", str(existing.get("backend_port", 8000)))),
        "client_version": _input("Client version", existing.get("client_version", "1.0.0")),
    }

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    print("[OK] Configuration saved to config.json")

    # 5. Init database
    print("\n--- Step 5: Initialize Database ---")
    subprocess.run([venv_python, "backend/init_db.py"], cwd=PROJECT_ROOT)

    # 6. Generate start.bat
    _generate_server_start_bat(config)

    # Summary
    print("\n" + "=" * 50)
    print("  Server Setup Complete!")
    print("=" * 50)
    print("  Admin: {} / {}".format(config["admin_username"], config["admin_password"]))
    print("  Backend: http://{}:{}".format(config["backend_host"], config["backend_port"]))
    print("  Config: {}".format(CONFIG_PATH))
    print("\n  Run start.bat to launch the server.")
    print("=" * 50)


def _generate_server_start_bat(config):
    bat_path = os.path.join(PROJECT_ROOT, "start.bat")
    bat_content = '@echo off\nchcp 65001 >nul\n\nset "ROOT=%~dp0"\nif "%ROOT:~-1%"=="\\" set "ROOT=%ROOT:~0,-1%"\nset "PYTHON=%ROOT%\\.venv\\Scripts\\python.exe"\n\nif not exist "%PYTHON%" (\n    echo [ERROR] venv not found. Please run setup.py first.\n    pause\n    exit /b 1\n)\n\nif not exist "%ROOT%\\config.json" (\n    echo [ERROR] config.json not found. Please run setup.py first.\n    pause\n    exit /b 1\n)\n\necho Starting AutoScript Hub Server...\n"%PYTHON%" backend\\app\\main.py\n'
    with open(bat_path, "w", encoding="utf-8") as f:
        f.write(bat_content)
    print("[OK] start.bat generated (server-only mode)")


# ── Client Setup ─────────────────────────────────────────────────────

def setup_client():
    print("=" * 50)
    print("  AutoScript Hub - Client Setup")
    print("=" * 50)
    print()

    # 1. Venv
    print("--- Step 1: Virtual Environment ---")
    venv_python = _ensure_venv()

    # 2. Install client deps only
    print("\n--- Step 2: Install Dependencies ---")
    _install_deps(venv_python, os.path.join(PROJECT_ROOT, "client", "requirements.txt"))

    # 3. Configuration
    print("\n--- Step 3: Client Configuration ---")
    existing = {}
    if os.path.isfile(CLIENT_CONFIG_PATH):
        with open(CLIENT_CONFIG_PATH, "r", encoding="utf-8") as f:
            existing = json.load(f)

    server_url = _input(
        "Server URL (e.g. http://192.168.1.100:8000)",
        existing.get("server_url", "http://127.0.0.1:8000"),
    )
    username = _input("Agent username", existing.get("username", ""))
    password = _input("Agent password", existing.get("password", ""))
    script_download_dir = _input(
        "Local script download directory",
        existing.get("script_download_dir", os.path.join(PROJECT_ROOT, "storage", "scripts")),
    )
    output_dir = _input(
        "Local output directory",
        existing.get("output_dir", os.path.join(PROJECT_ROOT, "storage", "output")),
    )
    default_browser_path = _input(
        "Default browser path (leave empty to auto-detect)",
        existing.get("default_browser_path", ""),
    )
    browser_debug_port = _input(
        "Browser debug port",
        str(existing.get("browser_debug_port", 9222)),
    )
    proxy = _input("Proxy (leave empty if none)", existing.get("proxy", ""))

    # Construct frontend URL from server URL
    frontend_url = server_url

    config = {
        "server_url": server_url,
        "frontend_url": frontend_url,
        "username": username,
        "password": password,
        "script_download_dir": script_download_dir,
        "output_dir": output_dir,
        "default_browser_path": default_browser_path,
        "browser_debug_port": int(browser_debug_port),
        "proxy": proxy or None,
        "version": existing.get("version", "1.0.0"),
    }
    # Remove None values
    config = {k: v for k, v in config.items() if v is not None}

    with open(CLIENT_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    print("[OK] Configuration saved to client_config.json")

    # 4. Generate client start script
    _generate_client_start_script()

    # Summary
    print("\n" + "=" * 50)
    print("  Client Setup Complete!")
    print("=" * 50)
    print("  Server: {}".format(server_url))
    print("  User: {}".format(username))
    print("  Scripts: {}".format(script_download_dir))
    print("  Output: {}".format(output_dir))
    print("  Config: {}".format(CLIENT_CONFIG_PATH))
    print("\n  Run start_client.bat to launch the client.")
    print("=" * 50)


def _generate_client_start_script():
    bat_path = os.path.join(PROJECT_ROOT, "start_client.bat")
    bat_content = '@echo off\nchcp 65001 >nul\n\nset "ROOT=%~dp0"\nif "%ROOT:~-1%"=="\\" set "ROOT=%ROOT:~0,-1%"\nset "PYTHON=%ROOT%\\.venv\\Scripts\\python.exe"\n\nif not exist "%PYTHON%" (\n    echo [ERROR] venv not found. Please run setup.py --client first.\n    pause\n    exit /b 1\n)\n\nif not exist "%ROOT%\\client_config.json" (\n    echo [ERROR] client_config.json not found. Please run setup.py --client first.\n    pause\n    exit /b 1\n)\n\necho Starting AutoScript Hub Client...\n"%PYTHON%" client\\start.py\n'
    with open(bat_path, "w", encoding="utf-8") as f:
        f.write(bat_content)
    print("[OK] start_client.bat generated")


# ── Entry Point ──────────────────────────────────────────────────────

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else None

    if mode == "--server":
        setup_server()
    elif mode == "--client":
        setup_client()
    else:
        print("AutoScript Hub Setup")
        print()
        print("Usage:")
        print("  python setup.py --server   # Configure server (backend + frontend)")
        print("  python setup.py --client   # Configure client (agent + desktop UI)")
        print()
        if mode:
            print("Unknown option: {}".format(mode))
        sys.exit(1)
