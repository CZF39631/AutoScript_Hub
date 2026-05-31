import os
import shutil
import zipfile
from typing import Optional

from app.config import SCRIPTS_DIR


def save_script_file(script_id, version, upload_path, script_type):
    """Save uploaded script file to storage. Returns relative storage path."""
    dest_dir = os.path.join(SCRIPTS_DIR, str(script_id), str(version))
    os.makedirs(dest_dir, exist_ok=True)

    if script_type == "zip":
        with zipfile.ZipFile(upload_path, "r") as zf:
            zf.extractall(dest_dir)
        if not os.path.exists(os.path.join(dest_dir, "main.py")):
            names = zf.namelist()
            top_dirs = set(n.split("/")[0] for n in names if "/" in n)
            if len(top_dirs) == 1:
                sub = os.path.join(dest_dir, top_dirs.pop())
                for item in os.listdir(sub):
                    shutil.move(os.path.join(sub, item), os.path.join(dest_dir, item))
                shutil.rmtree(sub)
            if not os.path.exists(os.path.join(dest_dir, "main.py")):
                raise ValueError("ZIP must contain main.py with config() and main()")
        return dest_dir
    else:
        dest = os.path.join(dest_dir, "main.py")
        shutil.copy2(upload_path, dest)
        return dest_dir


def get_script_file_path(script_id, version):
    """Get the directory path for a script version."""
    dest_dir = os.path.join(SCRIPTS_DIR, str(script_id), str(version))
    if os.path.isdir(dest_dir):
        return dest_dir
    return None
