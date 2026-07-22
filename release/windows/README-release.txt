AutoScript Hub Windows x86-64 release build

Requirements:
- Windows runner with Python 3.11, Node.js 20, and Inno Setup 6
- Run from a clean checkout: powershell -File release/windows/build.ps1 -Version 0.9.0

The build runs Python/frontend tests, builds one PyInstaller onedir containing
AutoScriptHub.exe, AutoScriptAgent.exe, and AutoScriptUpdater.exe, downloads and
verifies the official Python 3.11.9 installer and Microsoft WebView2 bootstrapper,
then creates a per-user Inno Setup installer below release-output/.

The installer does not require system Python, Node.js, or Git. Mutable user data
stays under %LOCALAPPDATA%\AutoScriptHub and is preserved by upgrades/uninstall.
