"""Windows 安装身份源码契约；只在隔离源码快照中运行。"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WINDOWS = ROOT / "release" / "windows"


def read(name):
    return (WINDOWS / name).read_text(encoding="utf-8-sig")


def test_installer_has_fixed_separate_identities_and_stable_default():
    source = read("installer.iss")
    assert '#ifndef InstallFlavor\n  #define InstallFlavor "stable"' in source
    preview = source.split('#if InstallFlavor == "preview"', 1)[1].split('#elif', 1)[0]
    stable = source.split('#elif InstallFlavor == "stable"', 1)[1].split('#else', 1)[0]
    assert '#define MyAppName "AutoScript Hub Preview"' in preview
    assert '#define MyDataDir "AutoScriptHubPreview"' in preview
    assert '{{D67FAE91-F2B7-4C25-9A71-2646E46B7D90}' in preview
    assert '#define MyAppName "AutoScript Hub"' in stable
    assert '#define MyDataDir "AutoScriptHub"' in stable
    assert '{{A77DCEAD-026B-4E4E-9796-821C117A61B8}' in stable
    for directive in (
        'AppId={#MyAppId}',
        'AppName={#MyAppName}',
        'DefaultDirName={localappdata}\\Programs\\{#MyAppName}',
        'DefaultGroupName={#MyAppName}',
        'Name: "{group}\\{#MyAppName}"',
        'Name: "{userdesktop}\\{#MyAppName}"',
        "{localappdata}\\{#MyDataDir}\\updates\\previous-installer.exe",
    ):
        assert directive in source
    assert '#error Unknown InstallFlavor' in source


def test_identity_guard_precedes_process_shutdown_and_rejects_legacy_preview():
    source = read("installer.iss")
    prepare = source.split('function PrepareToInstall', 1)[1].split('procedure CurStepChanged', 1)[0]
    assert prepare.index('ValidateInstallIdentity') < prepare.index("if Result <> '' then Exit;") < prepare.index('PrepareInstalledProcesses')
    guard = source.split('function ValidateInstallIdentity', 1)[1].split('function IsWebView2RuntimeInstalled', 1)[0]
    assert "CompareText(Target, OtherDefault) = 0" in guard
    assert "{localappdata}\\Programs\\{#OtherAppName}" in guard
    assert "if FileExists(Marker) then" in guard
    assert "if not LoadStringFromFile(Marker, Identity) then" in guard
    assert "Identity <> 'AutoScript Hub installation identity v1: {#InstallFlavor}'" in guard
    assert "if '{#InstallFlavor}' <> 'stable' then" in guard
    for exe in ('AutoScriptHub.exe', 'AutoScriptAgent.exe', 'AutoScriptUpdater.exe'):
        assert "FileExists(AddBackslash(Target) + '" + exe + "')" in guard
    assert "SaveStringToFile(ExpandConstant('{app}\\autoscript-install-identity.txt')" in source
    assert "'AutoScript Hub installation identity v1: {#InstallFlavor}', False)" in source
    assert source.index('if CurStep = ssInstall then') < source.index('if CurStep = ssPostInstall then')
    assert 'Type: files; Name: "{app}\\autoscript-install-identity.txt"' in source


def test_restart_manager_cannot_close_another_instance_even_with_cli_override():
    source = read('installer.iss')
    assert re.search(r'^CloseApplications=no$', source, re.M)
    assert re.search(r'^CloseApplicationsFilterExcludes=\*$', source, re.M)
    assert 'RestartApplications=no' in source
    assert 'RegisterExtraCloseApplicationsResource' not in source
    processes = read('installer_processes.iss')
    assert 'CompareText(ExpandFileName(ImagePath), Target) = 0' in processes
    assert not re.search(r'/IM\b', processes, re.I)


def test_build_passes_one_install_flavor_to_frozen_payload_and_iscc():
    source = read('build.ps1')
    assert "INSTALL_FLAVOR = '$InstallFlavor'`n" in source
    assert '"/DInstallFlavor=$InstallFlavor"' in source
    assert r"$InstallFlavor = if ($Version.Split('+')[0] -match '(?i)(?:^|[.-])preview(?:\d+)?(?:[.-]|$)')" in source
    assert "$Channel = if ($Version.Split('+')[0].Contains('-'))" in source
    spec = read('autoscript_hub.spec')
    assert 'build_info.get("INSTALL_FLAVOR") != expected_flavor' in spec
    assert 'hiddenimports=["autoscript_build_info"] + (common_hidden if include_ui_assets else [])' in spec


@pytest.mark.parametrize(('version', 'flavor', 'channel'), [
    ('1.3.0', 'stable', 'stable'),
    ('1.3.0-beta.1', 'stable', 'beta'),
    ('1.3.0-rc.1+build.9', 'stable', 'beta'),
    ('2.0.0-alpha', 'stable', 'beta'),
    ('1.3.0-preview.1', 'preview', 'beta'),
    ('1.3.0-preview1', 'preview', 'beta'),
    ('1.3.0-preview-1+build.1', 'preview', 'beta'),
    ('1.3.0-preview', 'preview', 'beta'),
    ('1.3.0-PREVIEW.1+build.9', 'preview', 'beta'),
    ('1.3.0-beta.preview.1', 'preview', 'beta'),
    ('1.3.0-beta-preview.1', 'preview', 'beta'),
    ('1.3.0-previewish.1', 'stable', 'beta'),
    ('1.3.0-beta.1+preview', 'stable', 'beta'),
    ('1.3.0+preview', 'stable', 'stable'),
    ('2.0.0', 'stable', 'beta'),  # CHANNEL is not installation identity.
    ('1.3.0+build-with-hyphen', 'stable', 'stable'),
])
def test_actual_powershell_version_classification_without_running_build(version, flavor, channel):
    powershell = shutil.which('pwsh') or shutil.which('powershell')
    if not powershell:
        pytest.skip('PowerShell unavailable')
    source = read('build.ps1')
    # Execute only validation/classification: never pip, pytest, npm, PyInstaller,
    # ISCC, runtime staging, client entrypoints, or filesystem setup.
    classification = source[source.index('if ($Version -notmatch'):source.index('Push-Location $RepoRoot')]
    command = f"$ErrorActionPreference = 'Stop'; $Version = '{version}';\n" + classification
    command += '\nWrite-Output "$InstallFlavor/$Channel"'
    result = subprocess.run([powershell, '-NoProfile', '-NonInteractive', '-Command', command], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == f'{flavor}/{channel}'

    # Execute the actual spec identity expression, without importing PyInstaller,
    # executing build_info, or collecting any real client files.
    spec = read('autoscript_hub.spec')
    expression = spec[spec.index('expected_flavor ='):spec.index('if build_info.get')]
    namespace = {'re': re, 'build_info': {'VERSION': version}}
    exec(expression, namespace)
    assert namespace['expected_flavor'] == flavor
    from shared.version import is_preview_version
    assert is_preview_version(version) == (flavor == 'preview')

    # Follow the flavor into the installer defines: Beta and RC must keep the
    # original AppId, program name, and data root, not just a stable string.
    installer = read('installer.iss')
    if flavor == 'stable':
        defines = installer.split('#elif InstallFlavor == "stable"', 1)[1].split('#else', 1)[0]
        assert '{{A77DCEAD-026B-4E4E-9796-821C117A61B8}' in defines
        assert '#define MyAppName "AutoScript Hub"' in defines
        assert '#define MyDataDir "AutoScriptHub"' in defines
    else:
        defines = installer.split('#if InstallFlavor == "preview"', 1)[1].split('#elif', 1)[0]
        assert '{{D67FAE91-F2B7-4C25-9A71-2646E46B7D90}' in defines
        assert '#define MyAppName "AutoScript Hub Preview"' in defines
        assert '#define MyDataDir "AutoScriptHubPreview"' in defines
