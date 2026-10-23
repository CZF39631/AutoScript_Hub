"""Fail-closed screen thumbnail capture for managed Windows Agents."""

import ctypes
import io
import sys


MAX_THUMBNAIL_BYTES = 1024 * 1024
MAX_THUMBNAIL_EDGE = 1280
JPEG_QUALITY = 82
_DESKTOP_SWITCHDESKTOP = 0x0100


class DesktopUnavailable(RuntimeError):
    """The interactive desktop cannot safely be captured."""


def desktop_is_interactive():
    """Return whether this process can access the visible, unlocked desktop.

    ``SwitchDesktop`` fails for secure desktops (including the Windows lock
    screen) and for desktops attached to an invisible/non-interactive window
    station. Any Win32 error is treated as unavailable.
    """
    if sys.platform != "win32":
        return False

    desktop = None
    try:
        user32 = ctypes.windll.user32
        user32.OpenInputDesktop.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong]
        user32.OpenInputDesktop.restype = ctypes.c_void_p
        user32.SwitchDesktop.argtypes = [ctypes.c_void_p]
        user32.SwitchDesktop.restype = ctypes.c_bool
        user32.CloseDesktop.argtypes = [ctypes.c_void_p]
        user32.CloseDesktop.restype = ctypes.c_bool

        desktop = user32.OpenInputDesktop(0, False, _DESKTOP_SWITCHDESKTOP)
        if not desktop:
            return False
        return bool(user32.SwitchDesktop(desktop))
    except (AttributeError, OSError, ValueError):
        return False
    finally:
        if desktop:
            try:
                ctypes.windll.user32.CloseDesktop(desktop)
            except (AttributeError, OSError, ValueError):
                pass


def _grab_primary_screen():
    """Capture the primary monitor as a Pillow RGB image, without writing a file."""
    import mss
    from PIL import Image

    with mss.mss() as capture:
        if len(capture.monitors) < 2:
            raise DesktopUnavailable("未检测到主屏幕")
        screenshot = capture.grab(capture.monitors[1])
        return Image.frombytes("RGB", screenshot.size, screenshot.rgb)


def _encode_jpeg(image):
    """Resize and encode a bounded JPEG entirely in memory."""
    from PIL import Image

    rgb = image.convert("RGB")
    rgb.thumbnail((MAX_THUMBNAIL_EDGE, MAX_THUMBNAIL_EDGE), Image.Resampling.LANCZOS)

    # Quality 82 keeps desktop text readable in the enlarged preview. Lower
    # values and dimensions are only a hard-size fallback for noisy captures.
    for quality in (JPEG_QUALITY, 75, 68, 60, 50, 40):
        stream = io.BytesIO()
        rgb.save(stream, format="JPEG", quality=quality, optimize=True)
        payload = stream.getvalue()
        if len(payload) <= MAX_THUMBNAIL_BYTES:
            return payload

    while max(rgb.size) > 160:
        width, height = rgb.size
        rgb = rgb.resize(
            (max(1, width * 3 // 4), max(1, height * 3 // 4)),
            Image.Resampling.LANCZOS,
        )
        stream = io.BytesIO()
        rgb.save(stream, format="JPEG", quality=40, optimize=True)
        payload = stream.getvalue()
        if len(payload) <= MAX_THUMBNAIL_BYTES:
            return payload

    raise ValueError("缩略图编码后仍超过 1 MiB")


def capture_thumbnail():
    """Capture one thumbnail only while the desktop remains interactive.

    The checks intentionally bracket capture and encoding. If Windows locks or
    switches to a non-interactive desktop during the operation, no bytes are
    returned to the caller and therefore nothing can be uploaded.
    """
    if not desktop_is_interactive():
        raise DesktopUnavailable("桌面已锁定或不可交互")

    image = _grab_primary_screen()
    payload = _encode_jpeg(image)

    if not desktop_is_interactive():
        raise DesktopUnavailable("捕获期间桌面已锁定或切换")
    if not payload or len(payload) > MAX_THUMBNAIL_BYTES:
        raise ValueError("缩略图大小无效")
    return payload
