#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif
; stable is the shared Stable/Beta/RC installation family, not the update channel.
; Only explicitly named Preview builds receive the isolated identity.
#ifndef InstallFlavor
  #define InstallFlavor "stable"
#endif
#if InstallFlavor == "preview"
  #define MyAppName "AutoScript Hub Preview"
  #define MyAppId "{{D67FAE91-F2B7-4C25-9A71-2646E46B7D90}"
  #define MyDataDir "AutoScriptHubPreview"
  #define OtherAppName "AutoScript Hub"
#elif InstallFlavor == "stable"
  #define MyAppName "AutoScript Hub"
  #define MyAppId "{{A77DCEAD-026B-4E4E-9796-821C117A61B8}"
  #define MyDataDir "AutoScriptHub"
  #define OtherAppName "AutoScript Hub Preview"
#else
  #error Unknown InstallFlavor
#endif
#define MyAppPublisher "AutoScript Hub"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\..\release-output
OutputBaseFilename=AutoScript-Hub-Setup-{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
SetupIconFile=app-icon.ico
UninstallDisplayIcon={app}\AutoScriptHub.exe
; Only our exact-{app} PID handler may stop applications. Excluding all files
; also prevents Restart Manager scanning if /CLOSEAPPLICATIONS overrides this flag.
CloseApplications=no
CloseApplicationsFilterExcludes=*
RestartApplications=no
LanguageDetectionMethod=none
LicenseFile=..\..\LICENSE

[Languages]
Name: "chinesesimplified"; MessagesFile: "cache\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Dirs]
Name: "{localappdata}\{#MyDataDir}"
Name: "{localappdata}\{#MyDataDir}\config"
Name: "{localappdata}\{#MyDataDir}\scripts"
Name: "{localappdata}\{#MyDataDir}\environments"
Name: "{localappdata}\{#MyDataDir}\logs"
Name: "{localappdata}\{#MyDataDir}\runs"
Name: "{localappdata}\{#MyDataDir}\updates"
Name: "{localappdata}\{#MyDataDir}\output"

[Files]
Source: "..\..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\release-output\windows\AutoScriptHub\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\release-output\windows-runtime\python\*"; DestDir: "{app}\runtime\python"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "cache\MicrosoftEdgeWebview2Setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\AutoScriptHub.exe"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\AutoScriptHub.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加快捷方式:"

[Run]
Filename: "{app}\AutoScriptHub.exe"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: files; Name: "{app}\autoscript-install-identity.txt"

[Code]
#include "installer_processes.iss"

function ValidateInstallIdentity: String;
var
  Target, OtherDefault, Marker: String;
  Identity: AnsiString;
begin
  Result := '';
  Target := RemoveBackslashUnlessRoot(ExpandFileName(ExpandConstant('{app}')));
  OtherDefault := RemoveBackslashUnlessRoot(ExpandFileName(
    ExpandConstant('{localappdata}\Programs\{#OtherAppName}')));
  if CompareText(Target, OtherDefault) = 0 then
  begin
    Result := '不能安装到另一安装身份的默认目录。请选择独立的安装目录。';
    Exit;
  end;
  Marker := AddBackslash(Target) + 'autoscript-install-identity.txt';
  if FileExists(Marker) then
  begin
    if not LoadStringFromFile(Marker, Identity) then
      Result := '无法读取安装身份，尚未关闭进程或替换文件。'
    else if Identity <> 'AutoScript Hub installation identity v1: {#InstallFlavor}' then
      Result := '安装身份不同或标记无效，不能覆盖此安装目录。';
  end
  else if FileExists(AddBackslash(Target) + 'AutoScriptHub.exe') or
          FileExists(AddBackslash(Target) + 'AutoScriptAgent.exe') or
          FileExists(AddBackslash(Target) + 'AutoScriptUpdater.exe') then
  begin
    { Legacy installations without a marker belong exclusively to stable. }
    if '{#InstallFlavor}' <> 'stable' then
      Result := '此目录包含旧正式客户端，Preview 必须使用独立目录。';
  end;
end;

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
  Result := ValidateInstallIdentity;
  if Result <> '' then Exit;
  Result := PrepareInstalledProcesses;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  PreviousInstaller: String;
  PrivatePython: String;
  WebViewInstaller: String;
  ResultCode: Integer;
begin
  if CurStep = ssInstall then
  begin
    if not ForceDirectories(ExpandConstant('{app}')) then
      RaiseException('Could not create installation directory');
    if not SaveStringToFile(ExpandConstant('{app}\autoscript-install-identity.txt'),
      'AutoScript Hub installation identity v1: {#InstallFlavor}', False) then
      RaiseException('Could not write installation identity');
  end;
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
#if InstallFlavor == "stable"
    PreviousInstaller := ExpandConstant('{localappdata}\{#MyDataDir}\updates\previous-installer.exe');
    if not FileExists(PreviousInstaller) then
      FileCopy(ExpandConstant('{srcexe}'), PreviousInstaller, False);
#endif
    { Preview has no online updater; leave empty data directories for runtime identity initialization. }
  end;
end;
