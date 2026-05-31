import webview
import sys
import os


class Api:
    """JS bridge for pywebview2 native dialogs."""

    def openFileDialog(self, file_types=("All files (*.*)",)):
        result = webview.windows[0].create_file_dialog(
            webview.FileDialog.OPEN, file_types=file_types
        )
        return result[0] if result else None

    def openFolderDialog(self):
        result = webview.windows[0].create_file_dialog(
            webview.FileDialog.FOLDER
        )
        return result[0] if result else None


def start_ui(url="http://localhost:5173"):
    from client.ui.config_manager import load_config, is_setup_complete

    # Show wizard on first run
    if not is_setup_complete():
        from client.ui.wizard import run_wizard
        run_wizard()

    config = load_config()
    frontend_url = config.get("frontend_url") or url

    api = Api()
    window = webview.create_window(
        "AutoScript Hub",
        frontend_url,
        js_api=api,
        width=1200,
        height=800,
        min_size=(800, 600),
    )
    webview.start()


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5173"
    start_ui(url)
