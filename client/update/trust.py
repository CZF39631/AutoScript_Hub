"""Load the release public key shipped inside the installed client."""

import base64
from pathlib import Path


def load_update_public_key() -> bytes:
    encoded = Path(__file__).with_name("update-public-key.b64").read_text(encoding="ascii").strip()
    value = base64.b64decode(encoded, validate=True)
    if len(value) != 32:
        raise RuntimeError("内置更新公钥长度无效")
    return value
