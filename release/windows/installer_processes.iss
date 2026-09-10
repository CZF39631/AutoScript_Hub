{ Shared by the production installer and the isolated upgrade smoke test. }
function FindInstalledProcesses(const ImageName: String; var Pids: TArrayOfString): String;
var
  Locator, Services, Processes, Process, PathValue: Variant;
  I, Count: Integer;
  Target, ImagePath: String;
begin
  Result := '';
  SetArrayLength(Pids, 0);
  Target := ExpandFileName(AddBackslash(ExpandConstant('{app}')) + ImageName);
  try
    Locator := CreateOleObject('WbemScripting.SWbemLocator');
    Services := Locator.ConnectServer('', 'root\CIMV2');
    Processes := Services.ExecQuery(
      'SELECT ProcessId, ExecutablePath FROM Win32_Process WHERE Name = ''' + ImageName + '''', 'WQL', 0);
    for I := 0 to Processes.Count - 1 do
    begin
      Process := Processes.ItemIndex(I);
      PathValue := Process.Properties_.Item('ExecutablePath').Value;
      if VarIsNull(PathValue) or VarIsEmpty(PathValue) then
      begin
        Result := '无法确认运行中 ' + ImageName + ' 的安装目录。请先退出该程序，或使用与旧程序相同的权限重新安装。';
        Exit;
      end;
      ImagePath := PathValue;
      if CompareText(ExpandFileName(ImagePath), Target) = 0 then
      begin
        Count := GetArrayLength(Pids);
        SetArrayLength(Pids, Count + 1);
        Pids[Count] := IntToStr(Process.Properties_.Item('ProcessId').Value);
      end;
    end;
  except
    Result := '无法检查旧客户端进程，尚未替换文件。请退出旧客户端后重试。';
    Log('Process discovery failed: ' + GetExceptionMessage);
  end;
end;

function HasSetupOption(const Option: String): Boolean;
var
  I: Integer;
begin
  Result := False;
  for I := 1 to ParamCount do
    if CompareText(ParamStr(I), Option) = 0 then
    begin
      Result := True;
      Exit;
    end;
end;

function StopInstalledImage(const ImageName: String; const IncludeChildren: Boolean): String;
var
  Pids: TArrayOfString;
  Attempt, I, ResultCode: Integer;
  Arguments: String;
  Launched: Boolean;
begin
  Result := '';
  for Attempt := 1 to 20 do
  begin
    Result := FindInstalledProcesses(ImageName, Pids);
    if Result <> '' then Exit;
    if GetArrayLength(Pids) = 0 then Exit;
    for I := 0 to GetArrayLength(Pids) - 1 do
    begin
      Arguments := '/F /PID ' + Pids[I];
      if IncludeChildren then Arguments := Arguments + ' /T';
      Launched := Exec(ExpandConstant('{sys}\taskkill.exe'), Arguments,
        '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
      Log(Format('Close %s PID %s: launched=%d, result=%d', [ImageName, Pids[I], Ord(Launched), ResultCode]));
      { A process can exit between enumeration and taskkill; verify by querying
        again instead of treating an exit code alone as proof of success. }
    end;
    Sleep(250);
  end;
  Result := FindInstalledProcesses(ImageName, Pids);
  if (Result = '') and (GetArrayLength(Pids) <> 0) then
    Result := '无法关闭旧版 ' + ImageName + '，尚未替换文件。请确认没有任务运行，退出旧客户端后重试；不要跳过文件。';
end;

function PrepareInstalledProcesses: String;
var
  UiPids, AgentPids: TArrayOfString;
begin
  Result := FindInstalledProcesses('AutoScriptHub.exe', UiPids);
  if Result <> '' then Exit;
  Result := FindInstalledProcesses('AutoScriptAgent.exe', AgentPids);
  if Result <> '' then Exit;
  if (GetArrayLength(UiPids) = 0) and (GetArrayLength(AgentPids) = 0) then Exit;

  if HasSetupOption('/NOCLOSEAPPLICATIONS') then
  begin
    Result := '旧客户端仍在运行，安装参数禁止自动关闭。请退出旧客户端后重试。';
    Exit;
  end;
  if WizardSilent then
  begin
    if not (HasSetupOption('/CLOSEAPPLICATIONS') or HasSetupOption('/FORCECLOSEAPPLICATIONS')) then
    begin
      Result := '旧客户端仍在运行。静默安装需要明确指定 /CLOSEAPPLICATIONS，或先退出旧客户端。';
      Exit;
    end;
  end
  else if MsgBox(
    '检测到此安装目录的 AutoScript Hub 或 Agent 正在运行：' + #13#10 +
    ExpandConstant('{app}') + #13#10#13#10 +
    '是否关闭旧客户端、Agent 及其脚本子进程后继续安装？' + #13#10 +
    '关闭会中断正在执行的脚本，请先保存工作并确认任务已经结束。' + #13#10#13#10 +
    '选择“否”不会替换文件，可退出旧客户端后重试。',
    mbConfirmation, MB_YESNO or MB_DEFBUTTON2) <> IDYES then
  begin
    Result := '已取消关闭旧客户端，尚未替换文件。请退出旧客户端后重试，或取消安装。';
    Exit;
  end;

  { Stop the UI/watchdog first. Do not kill its whole process tree: a detached
    updater can be a descendant. Then stop Agent and its script children. }
  Result := StopInstalledImage('AutoScriptHub.exe', False);
  if Result <> '' then Exit;
  Result := StopInstalledImage('AutoScriptAgent.exe', True);
  if Result <> '' then Exit;

  { A concurrent relaunch must block replacement, never silently skip a file. }
  Result := FindInstalledProcesses('AutoScriptHub.exe', UiPids);
  if Result <> '' then Exit;
  Result := FindInstalledProcesses('AutoScriptAgent.exe', AgentPids);
  if Result <> '' then Exit;
  if (GetArrayLength(UiPids) <> 0) or (GetArrayLength(AgentPids) <> 0) then
    Result := '旧客户端重新启动，尚未替换文件。请关闭旧客户端后重试。';
end;
