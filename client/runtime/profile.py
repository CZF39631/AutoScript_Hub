"""Installation identity is separate from the update channel."""
import os
import sys

from shared.version import is_preview_version


def get_install_flavor() -> str:
    if getattr(sys, "frozen", False):
        import autoscript_build_info
        # Frozen builds never trust an inherited environment to select identity.
        flavor = getattr(autoscript_build_info, "INSTALL_FLAVOR", None)
        if flavor is None:
            flavor = "preview" if is_preview_version(autoscript_build_info.VERSION) else "stable"
    else:
        flavor = os.environ.get("AUTOSCRIPT_INSTALL_FLAVOR", "stable")
    if flavor not in ("stable", "preview"):
        raise ValueError("无效的客户端安装身份")
    return flavor


def is_preview() -> bool:
    return get_install_flavor() == "preview"


def data_directory_name() -> str:
    return "AutoScriptHubPreview" if is_preview() else "AutoScriptHub"


def application_name() -> str:
    return "AutoScript Hub Preview" if is_preview() else "AutoScript Hub"


def agent_ports() -> tuple[int, ...]:
    return (18180, *range(18191, 18200)) if is_preview() else (18080, *range(18091, 18100))


def ui_ports() -> range:
    return range(18181, 18191) if is_preview() else range(18081, 18091)
