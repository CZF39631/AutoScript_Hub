# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_all


ROOT = Path.cwd()
GENERATED = ROOT / "release-output" / "autoscript-build"
webview_datas, webview_binaries, webview_hidden = collect_all("webview")
common_datas = [
    (str(ROOT / "frontend" / "dist"), "client/ui/static"),
    (str(ROOT / "client" / "update" / "update-public-key.b64"), "client/update"),  # client/update/update-public-key.b64
] + webview_datas
common_binaries = webview_binaries
common_hidden = webview_hidden + ["client.ui.wizard", "client.agent.notifier"]


def analysis(entry, include_ui_assets=True):
    return Analysis(
        [str(ROOT / "release" / "windows" / entry)],
        pathex=[str(GENERATED), str(ROOT)],
        binaries=common_binaries if include_ui_assets else [],
        datas=common_datas if include_ui_assets else [],
        hiddenimports=common_hidden if include_ui_assets else [],
        hookspath=[],
        hooksconfig={},
        runtime_hooks=[],
        excludes=[],
        noarchive=False,
    )


ui = analysis("entry_ui.py")
agent = analysis("entry_agent.py")
updater = analysis("entry_updater.py", include_ui_assets=False)
MERGE((ui, "AutoScriptHub", "AutoScriptHub"), (agent, "AutoScriptAgent", "AutoScriptAgent"))

ui_pyz = PYZ(ui.pure)
agent_pyz = PYZ(agent.pure)
updater_pyz = PYZ(updater.pure)

ui_exe = EXE(ui_pyz, ui.scripts, [], exclude_binaries=True, name="AutoScriptHub", console=False, disable_windowed_traceback=False)
agent_exe = EXE(agent_pyz, agent.scripts, [], exclude_binaries=True, name="AutoScriptAgent", console=False, disable_windowed_traceback=False)
updater_exe = EXE(
    updater_pyz,
    updater.scripts,
    updater.binaries,
    updater.datas,
    [],
    exclude_binaries=False,
    name="AutoScriptUpdater",
    console=False,
    disable_windowed_traceback=False,
)

bundle = COLLECT(
    ui_exe,
    agent_exe,
    updater_exe,
    ui.binaries,
    ui.datas,
    agent.binaries,
    agent.datas,
    strip=False,
    upx=True,
    name="AutoScriptHub",
)
