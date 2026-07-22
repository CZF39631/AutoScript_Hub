"""AutoScript Hub 安装引导 - 服务端 & 客户端模式

用法:
  python setup.py --server   # 配置并安装服务端（后端 + 前端）
  python setup.py --client   # 配置并安装客户端（Agent + 桌面UI）
"""
import json
import os
import secrets
import shutil
import subprocess
import sys
import winreg

from shared.version import RELEASE_VERSION

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.json")
CLIENT_CONFIG_PATH = os.path.join(PROJECT_ROOT, "client_config.json")
VENV_DIR = os.path.join(PROJECT_ROOT, ".venv")


# ── 工具函数 ──────────────────────────────────────────────────────────

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
        print("[错误] 未检测到 Python 安装。")
        sys.exit(1)
    print("检测到的 Python 版本:")
    for i, p in enumerate(pythons, 1):
        print("  {}. Python {} ({})".format(i, p["version"], p["path"]))
    idx = int(_input("请选择 Python 版本 (1-{})".format(len(pythons)), "1"))
    idx = max(1, min(idx, len(pythons))) - 1
    return pythons[idx]


def _ensure_venv(selected_python=None):
    venv_python = os.path.join(VENV_DIR, "Scripts", "python.exe")
    if os.path.isfile(venv_python):
        print("[OK] 虚拟环境已存在: {}".format(VENV_DIR))
        return venv_python

    if not selected_python:
        selected_python = _select_python()

    print("正在创建虚拟环境 {} (Python {})...".format(VENV_DIR, selected_python["version"]))
    proc = subprocess.run(
        [selected_python["path"], "-m", "venv", VENV_DIR],
        capture_output=True, text=True, timeout=120,
    )
    if proc.returncode != 0:
        print("[错误] 虚拟环境创建失败: {}".format(proc.stderr))
        sys.exit(1)
    print("[OK] 虚拟环境创建成功。")
    return os.path.join(VENV_DIR, "Scripts", "python.exe")


def _install_deps(venv_python, *req_files):
    for req_file in req_files:
        if not os.path.isfile(req_file):
            continue
        label = os.path.basename(os.path.dirname(req_file))
        if label == "backend":
            label = "后端"
        elif label == "client":
            label = "客户端"
        print("正在安装{}依赖...".format(label))
        proc = subprocess.run(
            [venv_python, "-m", "pip", "install", "-r", req_file, "-q"],
            capture_output=True, text=True, timeout=300,
        )
        if proc.returncode != 0:
            print("[警告] {}依赖安装遇到问题: {}".format(label, proc.stderr[:200]))
        else:
            print("[OK] {}依赖安装完成。".format(label))


def _build_frontend_assets():
    """Install, build, and deploy the React application for server and desktop UI."""
    frontend_dir = os.path.join(PROJECT_ROOT, "frontend")
    dist_dir = os.path.join(frontend_dir, "dist")
    targets = (
        os.path.join(PROJECT_ROOT, "backend", "static"),
        os.path.join(PROJECT_ROOT, "client", "ui", "static"),
    )

    npm_executable = shutil.which("npm")
    if not npm_executable:
        print("[错误] 未找到 npm。请先安装 Node.js。")
        return False

    try:
        for command, label in (
            ([npm_executable, "ci"], "前端依赖安装"),
            ([npm_executable, "run", "build"], "前端构建"),
        ):
            proc = subprocess.run(
                command,
                cwd=frontend_dir,
                capture_output=True,
                text=True,
                timeout=300,
                shell=False,
            )
            if proc.returncode != 0:
                print("[错误] {}失败: {}".format(label, (proc.stderr or proc.stdout)[:500]))
                return False
    except (OSError, subprocess.TimeoutExpired) as e:
        print("[错误] 前端构建失败: {}".format(e))
        return False

    if not os.path.isfile(os.path.join(dist_dir, "index.html")):
        print("[错误] 前端构建完成后未找到 dist/index.html")
        return False

    for target in targets:
        if os.path.isdir(target):
            shutil.rmtree(target)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copytree(dist_dir, target)

    print("[OK] 前端已部署到服务端和桌面客户端。")
    return True


# ── 服务端安装 ─────────────────────────────────────────────────────

def setup_server():
    print("=" * 50)
    print("  AutoScript Hub - 服务端安装")
    print("=" * 50)
    print()

    # 1. 虚拟环境
    print("--- 第1步: 虚拟环境 ---")
    venv_python = _ensure_venv()

    # 2. 安装依赖
    print("\n--- 第2步: 安装依赖 ---")
    _install_deps(
        venv_python,
        os.path.join(PROJECT_ROOT, "backend", "requirements.txt"),
        os.path.join(PROJECT_ROOT, "client", "requirements.txt"),
    )

    # 3. 构建前端
    print("\n--- 第3步: 构建前端 ---")
    if not _build_frontend_assets():
        sys.exit(1)

    # 4. 服务端配置
    print("\n--- 第4步: 服务端配置 ---")
    existing = {}
    if os.path.isfile(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            existing = json.load(f)

    config = {
        "storage_dir": _input("存储目录", existing.get("storage_dir", "backend/storage")),
        "scripts_dir": _input("脚本目录", existing.get("scripts_dir", "backend/storage/scripts")),
        "logs_dir": _input("日志目录", existing.get("logs_dir", "backend/storage/logs")),
        "admin_username": _input("管理员用户名", existing.get("admin_username", "admin")),
        "admin_password": _input("管理员密码", existing.get("admin_password", "admin123")),
        "jwt_secret": _input("JWT 密钥 (回车自动生成)", existing.get("jwt_secret", "")) or secrets.token_hex(32),
        "backend_host": _input("后端地址", existing.get("backend_host", "127.0.0.1")),
        "backend_port": int(_input("后端端口", str(existing.get("backend_port", 8000)))),
        "client_version": _input("客户端版本号", existing.get("client_version", RELEASE_VERSION)),
    }

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    print("[OK] 配置已保存到 config.json")

    # 5. 初始化数据库
    print("\n--- 第5步: 初始化数据库 ---")
    subprocess.run([venv_python, "backend/init_db.py"], cwd=PROJECT_ROOT)

    # 6. 生成启动脚本
    _generate_server_start_bat(config)

    # 总结
    print("\n" + "=" * 50)
    print("  服务端安装完成!")
    print("=" * 50)
    print("  管理员: {} / {}".format(config["admin_username"], config["admin_password"]))
    print("  后端地址: http://{}:{}".format(config["backend_host"], config["backend_port"]))
    print("  配置文件: {}".format(CONFIG_PATH))
    print("\n  运行 start.bat 启动服务端。")
    print("=" * 50)


def _generate_server_start_bat(config):
    bat_path = os.path.join(PROJECT_ROOT, "start.bat")
    bat_content = (
        '@echo off\r\n'
        'chcp 65001 >nul\r\n'
        '\r\n'
        'set "ROOT=%~dp0"\r\n'
        'if "%ROOT:~-1%"=="\\" set "ROOT=%ROOT:~0,-1%"\r\n'
        'set "PYTHON=%ROOT%\\.venv\\Scripts\\python.exe"\r\n'
        '\r\n'
        'if not exist "%PYTHON%" (\r\n'
        '    echo [错误] 未找到虚拟环境，请先运行 python setup.py --server\r\n'
        '    pause\r\n'
        '    exit /b 1\r\n'
        ')\r\n'
        '\r\n'
        'if not exist "%ROOT%\\config.json" (\r\n'
        '    echo [错误] 未找到配置文件，请先运行 python setup.py --server\r\n'
        '    pause\r\n'
        '    exit /b 1\r\n'
        ')\r\n'
        '\r\n'
        'echo ========================================\r\n'
        'echo   AutoScript Hub 服务端\r\n'
        'echo ========================================\r\n'
        'echo.\r\n'
        '"%PYTHON%" backend\\app\\main.py\r\n'
        'pause\r\n'
    )
    with open(bat_path, "wb") as f:
        f.write(bat_content.encode("utf-8"))
    print("[OK] start.bat 已生成")


# ── 客户端安装 ─────────────────────────────────────────────────────

def setup_client():
    print("=" * 50)
    print("  AutoScript Hub - 客户端安装")
    print("=" * 50)
    print()

    # 1. 虚拟环境
    print("--- 第1步: 虚拟环境 ---")
    venv_python = _ensure_venv()

    # 2. 安装客户端依赖
    print("\n--- 第2步: 安装依赖 ---")
    _install_deps(venv_python, os.path.join(PROJECT_ROOT, "client", "requirements.txt"))

    # 3. 构建桌面 UI
    print("\n--- 第3步: 构建桌面 UI ---")
    if not _build_frontend_assets():
        sys.exit(1)

    # 4. 客户端配置
    print("\n--- 第4步: 客户端配置 ---")
    existing = {}
    if os.path.isfile(CLIENT_CONFIG_PATH):
        with open(CLIENT_CONFIG_PATH, "r", encoding="utf-8") as f:
            existing = json.load(f)

    server_url = _input(
        "服务器地址 (例: http://192.168.1.100:8000)",
        existing.get("server_url", "http://127.0.0.1:8000"),
    )
    username = _input("Agent 用户名", existing.get("username", ""))
    password = _input("Agent 密码", existing.get("password", ""))
    script_download_dir = _input(
        "本地脚本下载目录",
        existing.get("script_download_dir", os.path.join(PROJECT_ROOT, "storage", "scripts")),
    )
    output_dir = _input(
        "本地输出目录",
        existing.get("output_dir", os.path.join(PROJECT_ROOT, "storage", "output")),
    )
    default_browser_path = _input(
        "浏览器路径 (留空自动检测)",
        existing.get("default_browser_path", ""),
    )
    browser_debug_port = _input(
        "浏览器调试端口",
        str(existing.get("browser_debug_port", 9222)),
    )
    proxy = _input("代理地址 (无代理留空)", existing.get("proxy", ""))

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
        "version": existing.get("version", RELEASE_VERSION),
    }
    config = {k: v for k, v in config.items() if v is not None}

    with open(CLIENT_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    print("[OK] 配置已保存到 client_config.json")

    # 5. 生成启动脚本
    _generate_client_start_script()

    # 总结
    print("\n" + "=" * 50)
    print("  客户端安装完成!")
    print("=" * 50)
    print("  服务器: {}".format(server_url))
    print("  用户: {}".format(username))
    print("  脚本目录: {}".format(script_download_dir))
    print("  输出目录: {}".format(output_dir))
    print("  配置文件: {}".format(CLIENT_CONFIG_PATH))
    print("\n  运行 start_client.bat 启动客户端。")
    print("=" * 50)


def _generate_client_start_script():
    bat_path = os.path.join(PROJECT_ROOT, "start_client.bat")
    bat_content = (
        '@echo off\r\n'
        'chcp 65001 >nul\r\n'
        '\r\n'
        'set "ROOT=%~dp0"\r\n'
        'if "%ROOT:~-1%"=="\\" set "ROOT=%ROOT:~0,-1%"\r\n'
        'set "PYTHON=%ROOT%\\.venv\\Scripts\\python.exe"\r\n'
        '\r\n'
        'if not exist "%PYTHON%" (\r\n'
        '    echo [错误] 未找到虚拟环境，请先运行 python setup.py --client\r\n'
        '    pause\r\n'
        '    exit /b 1\r\n'
        ')\r\n'
        '\r\n'
        'if not exist "%ROOT%\\client_config.json" (\r\n'
        '    echo [错误] 未找到配置文件，请先运行 python setup.py --client\r\n'
        '    pause\r\n'
        '    exit /b 1\r\n'
        ')\r\n'
        '\r\n'
        'echo ========================================\r\n'
        'echo   AutoScript Hub 客户端\r\n'
        'echo ========================================\r\n'
        'echo.\r\n'
        '"%PYTHON%" client\\start.py\r\n'
        'pause\r\n'
    )
    with open(bat_path, "wb") as f:
        f.write(bat_content.encode("utf-8"))
    print("[OK] start_client.bat 已生成")


# ── 入口 ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else None

    if mode == "--server":
        setup_server()
    elif mode == "--client":
        setup_client()
    else:
        print("AutoScript Hub 安装引导")
        print()
        print("用法:")
        print("  python setup.py --server   # 配置服务端（后端 + 前端）")
        print("  python setup.py --client   # 配置客户端（Agent + 桌面UI）")
        print()
        if mode:
            print("未知选项: {}".format(mode))
        sys.exit(1)
