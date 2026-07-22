#!/usr/bin/env python3
"""Generate an Ed25519 release key; only the public key belongs in the repository."""

import argparse
import base64
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private", type=Path, required=True)
    parser.add_argument("--public", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if not args.force and (args.private.exists() or args.public.exists()):
        raise SystemExit("Refusing to replace an existing update key; pass --force explicitly")
    key = Ed25519PrivateKey.generate()
    private_bytes = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_bytes = key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    args.private.parent.mkdir(parents=True, exist_ok=True)
    args.public.parent.mkdir(parents=True, exist_ok=True)
    args.private.write_bytes(private_bytes)
    try:
        os.chmod(args.private, 0o600)
    except OSError:
        pass
    args.public.write_text(base64.b64encode(public_bytes).decode("ascii") + "\n", encoding="ascii")


if __name__ == "__main__":
    main()
