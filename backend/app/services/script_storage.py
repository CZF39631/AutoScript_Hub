import os
import shutil
import tempfile
from typing import Optional
import uuid

from app.config import SCRIPTS_DIR
from shared.script_contract import extract_script_archive


def save_script_file(script_id, version, upload_path, script_type):
    """Save a script transactionally after safe extraction."""
    dest_dir = os.path.join(SCRIPTS_DIR, str(script_id), str(version))
    parent = os.path.dirname(dest_dir)
    os.makedirs(parent, exist_ok=True)
    staging_dir = tempfile.mkdtemp(prefix=f".{version}-", dir=parent)
    try:
        if script_type == "zip":
            main_path = extract_script_archive(upload_path, staging_dir)
            if os.path.dirname(str(main_path)) != staging_dir:
                legacy_root = os.path.dirname(str(main_path))
                for item in os.listdir(legacy_root):
                    shutil.move(os.path.join(legacy_root, item), os.path.join(staging_dir, item))
                shutil.rmtree(legacy_root)
        else:
            shutil.copy2(upload_path, os.path.join(staging_dir, "main.py"))
        previous_dir = ""
        if os.path.exists(dest_dir):
            previous_dir = f"{dest_dir}.previous-{uuid.uuid4().hex}"
            os.replace(dest_dir, previous_dir)
        try:
            os.replace(staging_dir, dest_dir)
            staging_dir = ""
        except Exception:
            if previous_dir and not os.path.exists(dest_dir):
                os.replace(previous_dir, dest_dir)
                previous_dir = ""
            raise
        if previous_dir:
            shutil.rmtree(previous_dir, ignore_errors=True)
        return dest_dir
    finally:
        if staging_dir:
            shutil.rmtree(staging_dir, ignore_errors=True)


def get_script_file_path(script_id, version):
    """Get the directory path for a script version."""
    dest_dir = os.path.join(SCRIPTS_DIR, str(script_id), str(version))
    if os.path.isdir(dest_dir):
        return dest_dir
    return None
