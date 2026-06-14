"""System-level desktop notifications (design §5.5).

Cross-platform fallback chain: plyer → win10toast → tkinter messagebox → silent.

Used by the Agent process to bubble execution completion / failure / disconnect
alerts to the user even when the UI window is not focused.
"""
import logging

logger = logging.getLogger(__name__)


def show_system_notification(title: str, message: str) -> bool:
    """Show a desktop notification. Returns True if any backend succeeded.

    Tries richer backends first (Win10 toast), falls back to blocking tkinter
    dialog as a last resort. Silently gives up if nothing is available.
    """
    # 1) plyer (cross-platform, Win10 toast on Windows)
    try:
        from plyer import notification  # type: ignore[import]
        notification.notify(
            title=title,
            message=message,
            app_name="AutoScript Hub",
            timeout=10,
        )
        return True
    except Exception as e:
        logger.debug("plyer 通知失败: %s", e)

    # 2) win10toast
    try:
        from win10toast import ToastNotifier  # type: ignore[import]
        ToastNotifier().show_toast(title, message, duration=10, threaded=True)
        return True
    except Exception as e:
        logger.debug("win10toast 通知失败: %s", e)

    # 3) tkinter messagebox (always available where Python has Tk)
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        # Non-blocking: schedule auto-destroy
        root.after(15000, root.destroy)
        messagebox.showwarning(title, message)
        root.destroy()
        return True
    except Exception as e:
        logger.debug("tkinter 弹窗失败: %s", e)

    logger.warning("无可用通知后端,跳过: %s", title)
    return False
