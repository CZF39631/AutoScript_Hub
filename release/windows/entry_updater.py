"""PyInstaller entrypoint for the independent installer helper."""

import os

import autoscript_build_info
from autoscript_build_info import CHANNEL, VERSION
from shared.version import is_preview_version

os.environ["AUTOSCRIPT_VERSION"] = VERSION
os.environ["AUTOSCRIPT_CHANNEL"] = CHANNEL
os.environ["AUTOSCRIPT_INSTALL_FLAVOR"] = getattr(
    autoscript_build_info, "INSTALL_FLAVOR", "preview" if is_preview_version(VERSION) else "stable"
)

from client.updater_main import main


if __name__ == "__main__":
    raise SystemExit(main())
