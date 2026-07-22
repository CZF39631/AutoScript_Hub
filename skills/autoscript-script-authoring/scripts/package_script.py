#!/usr/bin/env python3
"""Strictly validate and package a root-normalized deterministic script ZIP."""

import argparse
from pathlib import Path
import zipfile

from validate_script import run as validate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    source = args.source.resolve()
    main_file = source / "main.py" if source.is_dir() else source
    if not main_file.is_file():
        raise SystemExit("source must be a .py file or directory with root main.py")
    if validate(str(main_file), strict=True):
        raise SystemExit(1)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    files = [main_file] if source.is_file() else sorted(
        path for path in source.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and not path.name.endswith((".pyc", ".pyo"))
    )
    with zipfile.ZipFile(args.output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for path in files:
            arcname = "main.py" if source.is_file() else path.relative_to(source).as_posix()
            info = zipfile.ZipInfo(arcname, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            bundle.writestr(info, path.read_bytes(), compresslevel=9)
    if validate(str(args.output), strict=True):
        args.output.unlink(missing_ok=True)
        raise SystemExit(1)
    print(args.output)


if __name__ == "__main__":
    main()
