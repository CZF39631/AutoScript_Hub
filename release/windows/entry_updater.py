"""PyInstaller entrypoint for the independent installer helper."""

import os

from autoscript_build_info import CHANNEL, VERSION

os.environ["AUTOSCRIPT_VERSION"] = VERSION
os.environ["AUTOSCRIPT_CHANNEL"] = CHANNEL

from client.updater_main import main


if __name__ == "__main__":
    raise SystemExit(main())
