import json
import subprocess
import sys
import os


def parse_script_config(file_path):
    """Import script in subprocess, call config(), return dict."""
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"Script not found: {file_path}")

    code = (
        "import importlib.util, json, sys\n"
        "spec = importlib.util.spec_from_file_location('_script', sys.argv[1])\n"
        "mod = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(mod)\n"
        "if not hasattr(mod, 'config'):\n"
        "    sys.stdout.buffer.write(b'null')\n"
        "    sys.exit(0)\n"
        "result = mod.config()\n"
        "sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", code, file_path],
        capture_output=True, timeout=10,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""
        raise RuntimeError(f"Config parse failed: {stderr}")

    output = result.stdout.decode("utf-8").strip()
    if output == "null":
        return None
    return json.loads(output)
