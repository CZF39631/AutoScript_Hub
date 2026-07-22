#!/usr/bin/env python3
import argparse
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("path", type=Path)
parser.add_argument("--max-mb", type=int, default=95)
args = parser.parse_args()
size = args.path.stat().st_size
if size >= args.max_mb * 1024 * 1024:
    raise SystemExit(f"{args.path.name} is {size} bytes, above the {args.max_mb}MB gate")
print(size)
