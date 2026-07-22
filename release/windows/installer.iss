#ifndef MyAppVersion
  #define MyAppVersion "0.9.0-dev"
#endif
#define MyAppName "AutoScript Hub"
#define MyAppPublisher "AutoScript Hub"

[Setup]
AppId={{A77DCEAD-026B-4E4E-9796-821C117A61B8}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\AutoScript Hub
DefaultGroupName=AutoScript Hub
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\..\release-output
OutputBaseFilename=AutoScript-Hub-Setup-{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
UninstallDisplayIcon={app}\AutoScriptHub.exe
CloseApplications=yes
RestartApplications=no

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
Source: "..\..\release-output\windows\AutoScriptHub\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\release-output\windows-runtime\python\*"; DestDir: "{app}\runtime\python"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "cache\MicrosoftEdgeWebview2Setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall

[Icons]
Name: "{group}\AutoScript Hub"; Filename: "{app}\AutoScriptHub.exe"
Name: "{userdesktop}\AutoScript Hub"; Filename: "{app}\AutoScriptHub.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加快捷方式:"

[Run]
Filename: "{app}\AutoScriptHub.exe"; Description: "启动 AutoScript Hub"; Flags: nowait postinstall skipifsilent

[Code]
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
