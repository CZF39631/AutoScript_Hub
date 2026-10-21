#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif
#ifndef MyEdition
  #define MyEdition "standard"
#endif
#if MyEdition == "managed"
  #define MyAppName "AutoScript Hub 被控端"
  #define MyOutputName "AutoScript-Hub-Managed-Preview"
  #define MyModeFile "client-mode-managed.txt"
#else
  #define MyAppName "AutoScript Hub 管理端"
  #define MyOutputName "AutoScript-Hub-Manager-Preview"
  #define MyModeFile "client-mode-standard.txt"
#endif
#define MyAppPublisher "AutoScript Hub"

[Setup]
AppId={{A77DCEAD-026B-4E4E-9796-821C117A61B8}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\AutoScript Hub
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\..\release-output
OutputBaseFilename={#MyOutputName}-{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
SetupIconFile=app-icon.ico
UninstallDisplayIcon={app}\AutoScriptHub.exe
CloseApplications=yes
RestartApplications=no
LanguageDetectionMethod=none
LicenseFile=..\..\LICENSE

[Languages]
Name: "chinesesimplified"; MessagesFile: "cache\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Dirs]
Name: "{localappdata}\AutoScriptHub"
Name: "{localappdata}\AutoScriptHub\config"
Name: "{localappdata}\AutoScriptHub\scripts"
Name: "{localappdata}\AutoScriptHub\environments"
Name: "{localappdata}\AutoScriptHub\logs"
Name: "{localappdata}\AutoScriptHub\runs"
Name: "{localappdata}\AutoScriptHub\updates"
Name: "{localappdata}\AutoScriptHub\output"

[Files]
Source: "..\..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\release-output\windows\AutoScriptHub\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\release-output\windows-runtime\python\*"; DestDir: "{app}\runtime\python"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "cache\MicrosoftEdgeWebview2Setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall
Source: "{#MyModeFile}"; DestDir: "{app}"; DestName: "client-mode.txt"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\AutoScriptHub.exe"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\AutoScriptHub.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加快捷方式:"

[Run]
Filename: "{app}\AutoScriptHub.exe"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
#include "installer_processes.iss"

function IsWebView2RuntimeInstalled: Boolean;
var
  Version: String;
  ClientKey: String;
begin
  ClientKey := 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  Result :=
    (RegQueryStringValue(HKLM32, ClientKey, 'pv', Version) and (Version <> '')) or
    (RegQueryStringValue(HKCU, ClientKey, 'pv', Version) and (Version <> ''));
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := PrepareInstalledProcesses;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  PreviousInstaller: String;
  PrivatePython: String;
  WebViewInstaller: String;
  ResultCode: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    if not FileExists(ExpandConstant('{app}\AutoScriptAgent.exe')) then
      RaiseException('AutoScriptAgent.exe was not installed');
    if not FileExists(ExpandConstant('{app}\AutoScriptUpdater.exe')) then
      RaiseException('AutoScriptUpdater.exe was not installed');
    PrivatePython := ExpandConstant('{app}\runtime\python\python.exe');
    if not FileExists(PrivatePython) then
      RaiseException('Private Python 3.11.9 was not installed');
    if (not Exec(PrivatePython, '--version', '', SW_HIDE, ewWaitUntilTerminated, ResultCode)) or
       (ResultCode <> 0) then
      RaiseException('Private Python 3.11.9 failed its startup check');
    if not IsWebView2RuntimeInstalled then
    begin
      WebViewInstaller := ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe');
      if (not Exec(WebViewInstaller, '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, ResultCode)) or
         ((ResultCode <> 0) and (ResultCode <> 3010)) then
        RaiseException('Microsoft Edge WebView2 Runtime installation failed');
      if not IsWebView2RuntimeInstalled then
        RaiseException('Microsoft Edge WebView2 Runtime was not detected after installation');
    end;
    PreviousInstaller := ExpandConstant('{localappdata}\AutoScriptHub\updates\previous-installer.exe');
    if not FileExists(PreviousInstaller) then
      FileCopy(ExpandConstant('{srcexe}'), PreviousInstaller, False);
  end;
end;
