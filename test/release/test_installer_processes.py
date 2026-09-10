"""安装器进程关闭契约；真实 Windows 回归见 smoke_upgrade_processes.ps1。"""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WINDOWS = ROOT / "release" / "windows"


def _read(name: str) -> str:
    return (WINDOWS / name).read_text(encoding="utf-8-sig")


def _function(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^function {name}\b.*?(?=^function |\Z)", source
    )
    assert match, f"缺少函数 {name}"
    return match.group()


def test_production_and_smoke_share_process_include():
    assert (WINDOWS / "installer_processes.iss").is_file()
    installer = _read("installer.iss")
    assert '#include "installer_processes.iss"' in installer
    prepare = _function(installer, "PrepareToInstall")
    assert "Result := PrepareInstalledProcesses;" in prepare
    smoke = _read("smoke_upgrade_processes.ps1")
    assert "$include = Join-Path $PSScriptRoot 'installer_processes.iss'" in smoke
    assert '#include "$include"' in smoke
    assert "& $iscc $issPath" in smoke
    assert "Result := PrepareInstalledProcesses;" in smoke


def test_lookup_uses_wmi_and_exact_installation_path():
    lookup = _function(_read("installer_processes.iss"), "FindInstalledProcesses")
    assert "WbemScripting.SWbemLocator" in lookup
    assert "Win32_Process WHERE Name =" in lookup
    assert "ProcessId, ExecutablePath" in lookup
    assert "ExpandFileName(AddBackslash(ExpandConstant('{app}')) + ImageName)" in lookup
    assert "CompareText(ExpandFileName(ImagePath), Target) = 0" in lookup
    assert "PathValue := Process.Properties_.Item('ExecutablePath').Value" in lookup
    assert "VarIsNull(PathValue)" in lookup
    assert "VarIsEmpty(PathValue)" in lookup
    assert "'WQL', 0" in lookup
    assert "Pids[Count] := IntToStr(Process.Properties_.Item('ProcessId').Value)" in lookup
    assert "except" in lookup


def test_process_kills_use_pids_never_image_names():
    source = _read("installer_processes.iss")
    for name in ("installer.iss", "installer_processes.iss", "smoke_upgrade_processes.ps1"):
        assert not re.search(r"/IM\b", _read(name), re.IGNORECASE)
    stop = _function(source, "StopInstalledImage")
    assert "Arguments := '/F /PID ' + Pids[I]" in stop
    assert "if IncludeChildren then Arguments := Arguments + ' /T'" in stop
    assert "{sys}\\taskkill.exe" in stop
    assert "ewWaitUntilTerminated" in stop


def test_confirmation_defaults_to_no_and_silent_requires_consent():
    source = _read("installer_processes.iss")
    prepare = _function(source, "PrepareInstalledProcesses")
    assert "MB_YESNO or MB_DEFBUTTON2) <> IDYES" in prepare
    assert "关闭会中断正在执行的脚本" in prepare
    assert "Agent 及其脚本子进程" in prepare
    assert "ExpandConstant('{app}') + #13#10" in prepare
    assert "选择“否”不会替换文件" in prepare
    deny = prepare.index("HasSetupOption('/NOCLOSEAPPLICATIONS')")
    silent = prepare.index("if WizardSilent then")
    consent = prepare.index("HasSetupOption('/CLOSEAPPLICATIONS')")
    prompt = prepare.index("else if MsgBox(")
    first_kill = prepare.index("StopInstalledImage(")
    assert deny < silent < consent < prompt < first_kill
    assert "Exit;" in prepare[deny:silent]
    assert "if not (HasSetupOption('/CLOSEAPPLICATIONS')" in prepare[silent:prompt]
    assert "Exit;" in prepare[consent:prompt]
    assert "Exit;" in prepare[prompt:first_kill]
    option = _function(source, "HasSetupOption")
    assert "CompareText(ParamStr(I), Option) = 0" in option


def test_ui_stops_before_agent_and_both_are_rechecked():
    source = _read("installer_processes.iss")
    prepare = _function(source, "PrepareInstalledProcesses")
    ui = prepare.index("Result := StopInstalledImage('AutoScriptHub.exe', False);")
    agent = prepare.index("Result := StopInstalledImage('AutoScriptAgent.exe', True);")
    assert ui < agent
    assert "if Result <> '' then Exit;" in prepare[ui:agent]
    verify = prepare[agent:]
    assert "if Result <> '' then Exit;" in verify
    assert "FindInstalledProcesses('AutoScriptHub.exe', UiPids)" in verify
    assert "FindInstalledProcesses('AutoScriptAgent.exe', AgentPids)" in verify
    assert "(GetArrayLength(UiPids) <> 0) or (GetArrayLength(AgentPids) <> 0)" in verify
    assert "旧客户端重新启动，尚未替换文件" in verify
    stop = _function(source, "StopInstalledImage")
    assert stop.count("FindInstalledProcesses(ImageName, Pids)") >= 2
    assert "if GetArrayLength(Pids) = 0 then Exit;" in stop
    assert "(GetArrayLength(Pids) <> 0)" in stop


def test_shared_pascal_has_no_lines_that_inno_parses_as_section_headers():
    # Inno treats a line starting with '[' as a section even inside [Code].
    # Format's open-array arguments must not start their own physical line.
    source = _read("installer_processes.iss")
    bad = [(number, line.strip()) for number, line in enumerate(source.splitlines(), 1)
           if line.lstrip().startswith("[")]
    assert not bad, f"Inno 会把以下 Pascal 续行解析为节标题：{bad}"


def test_smoke_is_isolated_and_covers_real_process_and_payload_outcomes():
    smoke = _read("smoke_upgrade_processes.ps1")
    assert "[IO.Path]::GetTempPath()" in smoke
    assert "[guid]::NewGuid()" in smoke
    assert "AppId={{360AFC8A-AD36-4787-B90E-7E7701D61B16}" in smoke
    for directive in ("Uninstallable=no", "CreateUninstallRegKey=no", "CloseApplications=no",
                      "RestartApplications=no", "PrivilegesRequired=lowest"):
        assert directive in smoke
    assert "[Icons]" not in smoke
    assert "[Run]" not in smoke
    assert "[Registry]" not in smoke
    assert "/target:winexe" in smoke
    assert "agent == null || agent.HasExited" in smoke
    assert "silent-no-consent" in smoke
    assert "silent-no-close" in smoke
    assert "silent-conflicting-options" in smoke
    assert "silent-close-consent" in smoke
    assert "Assert-SamePair $target $targetPair" in smoke
    assert "Assert-SamePair $other $otherPair" in smoke
    assert "Get-FileHash" in smoke
    assert "@(Get-InstallationProcesses $target).Count -eq 0" in smoke
    assert "[IsolatedSetupWindows]::DefaultButton($dialog, $setupId) -eq 7" in smoke
    assert "[IsolatedSetupWindows]::ClickNo($dialog, $setupId)" in smoke
    assert "GetWindowThreadProcessId" in smoke
    assert "CheckOwner(button, owner)" in smoke
    assert "gui-refusal.log" in smoke
    assert "StartTime.ToUniversalTime().Ticks -eq $ticks" in smoke
    assert "[string]::Equals($process.MainModule.FileName, $image" in smoke
    assert "Get-OwnedProcesses" in smoke
    assert "Remove-Item -LiteralPath $root -Recurse -Force" in smoke
