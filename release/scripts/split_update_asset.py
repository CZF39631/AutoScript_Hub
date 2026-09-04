#!/usr/bin/env python3
"""Deterministically split an installer into fixed-size release assets."""

import argparse
from pathlib import Path


# Gitee 跨境附件上传对较大请求容易长时间无响应；小分卷降低单次重传成本。
PART_SIZE = 2 * 1024 * 1024


def split_asset(installer: Path, output: Path, part_size: int = PART_SIZE) -> list[Path]:
    if part_size <= 0:
        raise ValueError("part_size must be positive")
    if not installer.is_file():
        raise FileNotFoundError(installer)
    output.mkdir(parents=True, exist_ok=True)
    prefix = installer.name + ".part"
    for stale in output.glob(prefix + "[0-9][0-9][0-9][0-9]"):
        stale.unlink()

    parts = []
    with installer.open("rb") as source:
        index = 1
        while True:
            payload = source.read(part_size)
            if not payload:
                break
            path = output / f"{prefix}{index:04d}"
            path.write_bytes(payload)
            parts.append(path)
            index += 1
    if not parts:
        raise ValueError("installer must not be empty")
    return parts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--installer", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--part-size", type=int, default=PART_SIZE)
    args = parser.parse_args()
    for path in split_asset(args.installer, args.output, args.part_size):
        print(path)


if __name__ == "__main__":
    main()
