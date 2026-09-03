"""Non-blocking desktop notifications for Agent lifecycle events."""

import base64
import logging
import os
import subprocess
import threading

logger = logging.getLogger(__name__)


def _powershell_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _show_notification(title: str, message: str) -> bool:
    # Preferred backend in packaged clients. Plyer uses native platform APIs.
    try:
        from plyer import notification  # type: ignore[import]
        notification.notify(
            title=title,
            message=message,
            app_name="AutoScript Hub",
            timeout=10,
        )
        return True
    except Exception as exc:
        logger.debug("plyer 通知失败: %s", exc)

    # Keep compatibility with machines that already provide win10toast.
    try:
        from win10toast import ToastNotifier  # type: ignore[import]
        ToastNotifier().show_toast(title, message, duration=10, threaded=True)
        return True
    except Exception as exc:
        logger.debug("win10toast 通知失败: %s", exc)

    # Dependency-free Windows fallback. Use an argument array and encoded script;
    # no user-controlled value is interpreted as a shell command.
    if os.name == "nt":
        try:
            script = "\n".join([
                "$ErrorActionPreference = 'Stop'",
                "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null",
                "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null",
                "$template = [Windows.UI.Notifications.ToastTemplateType]::ToastText02",
                "$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent($template)",
                f"$title = {_powershell_quote(title)}",
                f"$message = {_powershell_quote(message)}",
                "$nodes = $xml.GetElementsByTagName('text')",
                "$nodes.Item(0).AppendChild($xml.CreateTextNode($title)) > $null",
                "$nodes.Item(1).AppendChild($xml.CreateTextNode($message)) > $null",
                "$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)",
                "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('AutoScript Hub').Show($toast)",
            ])
            encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
            subprocess.Popen(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-WindowStyle",
                    "Hidden",
                    "-EncodedCommand",
                    encoded,
                ],
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return True
        except Exception as exc:
            logger.debug("PowerShell 通知失败: %s", exc)

    logger.warning("无可用通知后端，跳过: %s", title)
    return False


def show_system_notification(title: str, message: str) -> bool:
    """Dispatch a notification without blocking task polling or status reporting."""
    try:
        thread = threading.Thread(
            target=_show_notification,
            args=(str(title), str(message)),
            name="autoscript-notification",
            daemon=True,
        )
        thread.start()
        return True
    except Exception as exc:
        logger.warning("通知线程启动失败: %s", exc)
        return False
