#!/usr/bin/env python3
"""Validate a script with the live repository contract or standalone snapshot."""

import argparse
from pathlib import Path
import sys


def _live_validator():
    for candidate in [Path.cwd(), *Path(__file__).resolve().parents]:
        if (candidate / "shared" / "script_contract.py").is_file():
            sys.path.insert(0, str(candidate))
            from shared.script_contract import validate_script
            return validate_script
    from contract_snapshot import validate
    return validate


def _console_text(value):
    """Keep standalone diagnostics printable on legacy Windows code pages."""
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    return str(value).encode(encoding, errors="backslashreplace").decode(encoding)


def run(path, strict=False):
    report = _live_validator()(path, strict=strict)
    for issue in report.errors:
        print(f"ERROR {issue.code}: {_console_text(issue.message)}")
    for issue in report.warnings:
        print(f"WARNING {issue.code}: {_console_text(issue.message)}")
    print(f"{len(report.errors)} errors, {len(report.warnings)} warnings")
    return 0 if not report.errors and (not strict or not report.warnings) else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    raise SystemExit(run(args.path, args.strict))


if __name__ == "__main__":
    main()
