import subprocess
import sys
import os
import json


def execute_script(script_dir, params, log_path, timeout=600, env_vars=None, python_executable=None):
    """Run main() from script_dir/main.py in a subprocess. Returns dict with status/error/result."""
    params_file = os.path.join(os.path.dirname(log_path), "_params.json")
    with open(params_file, "w", encoding="utf-8") as f:
        json.dump(params, f, ensure_ascii=False)

    code = (
        "import sys, json, os; "
        "sys.path.insert(0, sys.argv[1]); "
        "_pf = os.path.join(os.path.dirname(sys.argv[2]), '_params.json'); "
        "_params = json.load(open(_pf, encoding='utf-8')); "
        "from main import main; "
        "result = main(**_params); "
        "sys.stdout.buffer.write(('__RESULT__:' + repr(result)).encode('utf-8'))"
    )

    # Build subprocess env: inherit current + overlay env_vars
    proc_env = os.environ.copy()
    if env_vars:
        proc_env.update(env_vars)

    python_bin = python_executable or sys.executable

    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    result_value = None

    try:
        with open(log_path, "w", encoding="utf-8") as log_file:
            proc = subprocess.run(
                [python_bin, "-c", code, script_dir, log_path],
                stdout=log_file,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                cwd=script_dir,
                env=proc_env,
            )

        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            log_content = f.read()

        for line in log_content.strip().splitlines():
            if line.startswith("__RESULT__:"):
                raw = line[len("__RESULT__:"):].strip()
                try:
                    result_value = eval(raw)
                except Exception:
                    result_value = raw
                break

        return {
            "status": "success" if proc.returncode == 0 else "failed",
            "error": None if proc.returncode == 0 else "Exit code: {}".format(proc.returncode),
            "result": result_value,
        }

    except subprocess.TimeoutExpired:
        return {"status": "failed", "error": "Timeout after {}s".format(timeout), "result": None}
    except Exception as e:
        return {"status": "failed", "error": str(e), "result": None}
    finally:
        try:
            os.remove(params_file)
        except OSError:
            pass
