# Isolated Windows regression. Run directly with Windows PowerShell 5.1 or newer.
# Never uses a real installation, registry entries, shortcuts or image-name kills.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Assert-True($Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}

$isccCandidates = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
)
$iscc = $isccCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
Assert-True ($null -ne $iscc) 'Inno Setup 6 ISCC.exe not found in standard installation paths.'
$csc = "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (-not (Test-Path -LiteralPath $csc)) { $csc = "$env:WINDIR\Microsoft.NET\Framework\v4.0.30319\csc.exe" }
Assert-True (Test-Path -LiteralPath $csc) '.NET Framework C# compiler not found.'
$include = Join-Path $PSScriptRoot 'installer_processes.iss'
Assert-True (Test-Path -LiteralPath $include) 'Production installer_processes.iss is missing.'
$root = Join-Path ([IO.Path]::GetTempPath()) ('ash-upgrade-smoke-' + [guid]::NewGuid().ToString('N'))
$target = Join-Path $root 'target installation'
$other = Join-Path $root 'other installation'
$records = Join-Path $root 'records'
$launched = New-Object 'System.Collections.Generic.List[System.Diagnostics.Process]'
$utf8 = New-Object System.Text.UTF8Encoding($true)

function Get-OwnedProcesses {
    foreach ($file in @(Get-ChildItem -LiteralPath $records -Filter '*.pid' -ErrorAction SilentlyContinue)) {
        $lines = [IO.File]::ReadAllLines($file.FullName)
        Assert-True ($lines.Length -eq 3) "Invalid process record: $($file.Name)"
        $processId = [int]$lines[0]
        $ticks = [long]$lines[1]
        $image = [IO.Path]::GetFullPath($lines[2])
        Assert-True ($image.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) 'Unsafe process record path.'
        $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
        if ($null -ne $process -and $process.StartTime.ToUniversalTime().Ticks -eq $ticks -and
            [string]::Equals($process.MainModule.FileName, $image, [StringComparison]::OrdinalIgnoreCase)) {
            [pscustomobject]@{ Process = $process; Image = $image; Id = $processId; Ticks = $ticks }
        }
    }
}

function Get-InstallationProcesses([string]$Directory) {
    @(Get-OwnedProcesses | Where-Object { [IO.Path]::GetDirectoryName($_.Image) -eq $Directory })
}

function Wait-ForPair([string]$Directory) {
    $deadline = [DateTime]::UtcNow.AddSeconds(15)
    do {
        $pair = @(Get-InstallationProcesses $Directory)
        if ($pair.Count -eq 2 -and @($pair | Where-Object { $_.Image.EndsWith('\AutoScriptHub.exe') }).Count -eq 1 -and
            @($pair | Where-Object { $_.Image.EndsWith('\AutoScriptAgent.exe') }).Count -eq 1) { return $pair }
        Start-Sleep -Milliseconds 100
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "UI/Agent pair did not start: $Directory"
}

function Assert-SamePair([string]$Directory, $Expected) {
    $actual = @(Get-InstallationProcesses $Directory)
    Assert-True ($actual.Count -eq 2) "Expected two live processes: $Directory"
    $before = ($Expected | ForEach-Object { "$($_.Id):$($_.Ticks)" } | Sort-Object) -join ','
    $after = ($actual | ForEach-Object { "$($_.Id):$($_.Ticks)" } | Sort-Object) -join ','
    Assert-True ($before -eq $after) "Original processes were killed or restarted: $Directory"
}

function Invoke-SmokeInstaller([string]$Name, [string[]]$Options) {
    $log = Join-Path $root ($Name + '.log')
    $arguments = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/SP-', '/NORESTART', ('/DIR="' + $target + '"'), ('/LOG="' + $log + '"')) + $Options
    $process = Start-Process -FilePath (Join-Path $root 'output\isolated-setup.exe') -ArgumentList $arguments -PassThru
    $launched.Add($process)
    if (-not $process.WaitForExit(60000)) { throw "Installer timed out: $Name (PID $($process.Id))" }
    $process.Refresh()
    Write-Host "$Name exit code: $($process.ExitCode)"
    return $process.ExitCode
}

try {
    foreach ($directory in @($root, $target, $other, $records)) { [void][IO.Directory]::CreateDirectory($directory) }
    $payload = Join-Path $root 'replacement.exe'
    $payloadSource = Join-Path $root 'replacement.cs'
    [IO.File]::WriteAllText($payloadSource, 'class Replacement { static void Main() { } }', $utf8)
    & $csc /nologo /target:winexe "/out:$payload" $payloadSource
    Assert-True ($LASTEXITCODE -eq 0) 'Synthetic payload compilation failed.'
    # Compile the actual shared Pascal include before launching any test process.
    $iss = @"
[Setup]
AppId={{360AFC8A-AD36-4787-B90E-7E7701D61B16}
AppName=AutoScript isolated process regression
AppVersion=0.0.0
DefaultDirName=$target
PrivilegesRequired=lowest
Uninstallable=no
CreateUninstallRegKey=no
UsePreviousAppDir=no
DisableWelcomePage=yes
DisableDirPage=yes
DisableReadyPage=yes
DisableFinishedPage=yes
DisableProgramGroupPage=yes
CloseApplications=no
RestartApplications=no
OutputDir=$root\output
OutputBaseFilename=isolated-setup
Compression=none
[Files]
Source: "$payload"; DestDir: "{app}"; DestName: "AutoScriptAgent.exe"; Flags: ignoreversion
[Code]
#include "$include"
function FixtureProcessId: LongWord;
  external 'GetCurrentProcessId@kernel32.dll stdcall';
function InitializeSetup: Boolean;
begin
  Result := SaveStringToFile('$root\setup.pid', IntToStr(FixtureProcessId), False);
end;
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := PrepareInstalledProcesses;
end;
"@
    $issPath = Join-Path $root 'isolated.iss'
    [IO.File]::WriteAllText($issPath, $iss, $utf8)
    & $iscc $issPath
    Assert-True ($LASTEXITCODE -eq 0) 'Inno compilation failed: production Pascal include was not changed.'
    Write-Host 'PASS: production Pascal include compiled by Inno Setup.'

    $source = @'
using System;
using System.Diagnostics;
using System.IO;
using System.Threading;
class WatchdogFixture {
    static void Main(string[] args) {
        var self = Process.GetCurrentProcess();
        string image = self.MainModule.FileName;
        string record = Path.Combine(args[0], self.Id + "-" + self.StartTime.ToUniversalTime().Ticks + ".pid");
        File.WriteAllLines(record + ".new", new [] { self.Id.ToString(), self.StartTime.ToUniversalTime().Ticks.ToString(), image });
        File.Move(record + ".new", record);
        if (Path.GetFileName(image).Equals("AutoScriptHub.exe", StringComparison.OrdinalIgnoreCase)) {
            Process agent = null;
            while (true) {
                if (agent == null || agent.HasExited) {
                    if (agent != null) agent.Dispose();
                    agent = Process.Start(new ProcessStartInfo(Path.Combine(Path.GetDirectoryName(image), "AutoScriptAgent.exe"), "\"" + args[0] + "\"") { UseShellExecute = false });
                }
                Thread.Sleep(50);
            }
        }
        while (true) Thread.Sleep(100);
    }
}
'@
    $sourcePath = Join-Path $root 'watchdog.cs'
    $fixture = Join-Path $root 'fixture.exe'
    [IO.File]::WriteAllText($sourcePath, $source, $utf8)
    & $csc /nologo /target:winexe "/out:$fixture" $sourcePath
    Assert-True ($LASTEXITCODE -eq 0) 'Watchdog fixture compilation failed.'
    foreach ($directory in @($target, $other)) {
        foreach ($name in @('AutoScriptHub.exe', 'AutoScriptAgent.exe')) {
            Copy-Item -LiteralPath $fixture -Destination (Join-Path $directory $name)
        }
        $ui = Start-Process -FilePath (Join-Path $directory 'AutoScriptHub.exe') -ArgumentList ('"' + $records + '"') -PassThru
        $launched.Add($ui)
        [void](Wait-ForPair $directory)
    }
    # Prove that the fixture actually respawns a stopped Agent.
    $initialPair = @(Get-InstallationProcesses $target)
    $initialAgent = $initialPair | Where-Object { $_.Image.EndsWith('\AutoScriptAgent.exe') }
    $initialAgent.Process.Kill()
    Assert-True ($initialAgent.Process.WaitForExit(5000)) 'Fixture Agent did not stop.'
    $targetPair = @(Wait-ForPair $target)
    $newAgent = $targetPair | Where-Object { $_.Image.EndsWith('\AutoScriptAgent.exe') }
    Assert-True ($newAgent.Id -ne $initialAgent.Id -or $newAgent.Ticks -ne $initialAgent.Ticks) 'Watchdog did not respawn Agent.'
    Write-Host 'PASS: synthetic UI watchdog respawned Agent.'
    $otherPair = @(Wait-ForPair $other)
    $targetFile = Join-Path $target 'AutoScriptAgent.exe'
    $oldHash = (Get-FileHash -LiteralPath $targetFile -Algorithm SHA256).Hash
    $newHash = (Get-FileHash -LiteralPath $payload -Algorithm SHA256).Hash
    Assert-True ($oldHash -ne $newHash) 'Fixture and replacement hashes must differ.'

    # Limit all window discovery and button messages to the PID written by our
    # own minimal installer, never titles or globally matching setup windows.
    Add-Type -TypeDefinition @'
using System;
using System.Text;
using System.Runtime.InteropServices;
public static class IsolatedSetupWindows {
    private delegate bool EnumProc(IntPtr window, IntPtr parameter);
    [DllImport("user32.dll")] private static extern bool EnumWindows(EnumProc callback, IntPtr parameter);
    [DllImport("user32.dll")] private static extern bool EnumChildWindows(IntPtr parent, EnumProc callback, IntPtr parameter);
    [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr window, out uint processId);
    [DllImport("user32.dll")] private static extern IntPtr GetDlgItem(IntPtr window, int id);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] private static extern int GetWindowText(IntPtr window, StringBuilder text, int count);
    [DllImport("user32.dll")] private static extern IntPtr SendMessage(IntPtr window, uint message, IntPtr wparam, IntPtr lparam);
    [DllImport("user32.dll")] private static extern bool PostMessage(IntPtr window, uint message, IntPtr wparam, IntPtr lparam);
    public static IntPtr FindConfirmation(int owner) {
        IntPtr found = IntPtr.Zero;
        EnumWindows(delegate(IntPtr window, IntPtr parameter) {
            uint pid; GetWindowThreadProcessId(window, out pid);
            if (pid == owner && GetDlgItem(window, 6) != IntPtr.Zero && GetDlgItem(window, 7) != IntPtr.Zero) found = window;
            return true;
        }, IntPtr.Zero);
        return found;
    }
    private static void CheckOwner(IntPtr window, int owner) {
        uint pid; GetWindowThreadProcessId(window, out pid);
        if (pid != owner) throw new InvalidOperationException("Refusing to interact with a foreign window.");
    }
    public static string Text(IntPtr window, int owner) {
        CheckOwner(window, owner);
        StringBuilder all = new StringBuilder();
        EnumChildWindows(window, delegate(IntPtr child, IntPtr parameter) {
            var text = new StringBuilder(4096); GetWindowText(child, text, text.Capacity);
            all.AppendLine(text.ToString()); return true;
        }, IntPtr.Zero);
        return all.ToString();
    }
    public static int DefaultButton(IntPtr window, int owner) {
        CheckOwner(window, owner);
        long result = SendMessage(window, 0x400, IntPtr.Zero, IntPtr.Zero).ToInt64();
        if (((result >> 16) & 0xffff) != 0x534b) throw new InvalidOperationException("Dialog has no default button.");
        return (int)(result & 0xffff);
    }
    public static void ClickNo(IntPtr window, int owner) {
        CheckOwner(window, owner);
        var button = GetDlgItem(window, 7);
        CheckOwner(button, owner);
        if (!PostMessage(button, 0xf5, IntPtr.Zero, IntPtr.Zero)) throw new InvalidOperationException("Could not click No.");
    }
}
'@
    $pidFile = Join-Path $root 'setup.pid'
    if (Test-Path -LiteralPath $pidFile) { Remove-Item -LiteralPath $pidFile }
    $guiLog = Join-Path $root 'gui-refusal.log'
    $gui = Start-Process -FilePath (Join-Path $root 'output\isolated-setup.exe') -ArgumentList @('/SP-', '/NORESTART', ('/DIR="' + $target + '"'), ('/LOG="' + $guiLog + '"')) -PassThru
    $launched.Add($gui)
    $deadline = [DateTime]::UtcNow.AddSeconds(20)
    while (-not (Test-Path -LiteralPath $pidFile) -and [DateTime]::UtcNow -lt $deadline) { Start-Sleep -Milliseconds 100 }
    Assert-True (Test-Path -LiteralPath $pidFile) 'GUI fixture did not record its own setup PID.'
    $setupId = [int]([IO.File]::ReadAllText($pidFile).Trim())
    $guiSetup = Get-Process -Id $setupId
    Assert-True ($guiSetup.StartTime -ge $gui.StartTime) 'GUI setup PID predates this test invocation.'
    Assert-True ($guiSetup.MainModule.FileName.StartsWith([IO.Path]::GetTempPath(), [StringComparison]::OrdinalIgnoreCase)) 'GUI setup is outside TEMP.'
    $launched.Add($guiSetup)
    $dialog = [IntPtr]::Zero
    do {
        $dialog = [IsolatedSetupWindows]::FindConfirmation($setupId)
        if ($dialog -ne [IntPtr]::Zero) { break }
        Start-Sleep -Milliseconds 100
    } while ([DateTime]::UtcNow -lt $deadline)
    Assert-True ($dialog -ne [IntPtr]::Zero) 'Custom interactive confirmation did not appear.'
    $dialogText = [IsolatedSetupWindows]::Text($dialog, $setupId)
    Assert-True ($dialogText.Contains('AutoScript Hub') -and $dialogText.Contains('Agent') -and $dialogText.Contains($target)) 'Unexpected confirmation dialog or missing installation path.'
    Assert-True ([IsolatedSetupWindows]::DefaultButton($dialog, $setupId) -eq 7) 'Interactive confirmation does not default to No.'
    Assert-SamePair $target $targetPair
    [IsolatedSetupWindows]::ClickNo($dialog, $setupId)
    do {
        Start-Sleep -Milliseconds 100
        $remaining = [IsolatedSetupWindows]::FindConfirmation($setupId)
    } while ($remaining -ne [IntPtr]::Zero -and [DateTime]::UtcNow -lt $deadline)
    Assert-True ($remaining -eq [IntPtr]::Zero) 'Clicking No did not dismiss confirmation.'
    Start-Sleep -Milliseconds 750
    Assert-SamePair $target $targetPair
    Assert-SamePair $other $otherPair
    Assert-True ((Get-FileHash -LiteralPath $targetFile -Algorithm SHA256).Hash -eq $oldHash) 'GUI refusal changed target payload.'
    # The wizard remains on the preparation error page after No. Terminate only
    # this recorded test setup, rather than clicking any global cancel dialog.
    if (-not $guiSetup.HasExited) { $guiSetup.Kill(); [void]$guiSetup.WaitForExit(5000) }
    if (-not $gui.WaitForExit(5000)) { $gui.Kill(); [void]$gui.WaitForExit(5000) }
    Write-Host 'PASS: interactive prompt appeared, defaulted to No, and clicking No preserved processes and payload.'

    foreach ($case in @(
        @{ Name = 'silent-no-consent'; Options = @() },
        @{ Name = 'silent-no-close'; Options = @('/NOCLOSEAPPLICATIONS') },
        @{ Name = 'silent-conflicting-options'; Options = @('/CLOSEAPPLICATIONS', '/NOCLOSEAPPLICATIONS') }
    )) {
        $exitCode = Invoke-SmokeInstaller $case.Name $case.Options
        Assert-True ($exitCode -eq 7) "Expected PrepareToInstall refusal (exit 7): $($case.Name), got $exitCode"
        Assert-SamePair $target $targetPair
        Assert-SamePair $other $otherPair
        Assert-True ((Get-FileHash -LiteralPath $targetFile -Algorithm SHA256).Hash -eq $oldHash) 'Refused install changed target payload.'
        Write-Host "PASS: $($case.Name), original processes and file preserved."
    }
    $exitCode = Invoke-SmokeInstaller 'silent-close-consent' @('/CLOSEAPPLICATIONS')
    Assert-True ($exitCode -eq 0) "Consented install failed: $exitCode"
    Start-Sleep -Milliseconds 750
    Assert-True (@(Get-InstallationProcesses $target).Count -eq 0) 'Target UI/Agent survived or respawned.'
    Assert-True ((Get-FileHash -LiteralPath $targetFile -Algorithm SHA256).Hash -eq $newHash) 'Target Agent payload was not replaced.'
    Assert-SamePair $other $otherPair
    Assert-True ((Get-FileHash -LiteralPath (Join-Path $other 'AutoScriptAgent.exe') -Algorithm SHA256).Hash -eq $oldHash) 'Other installation payload changed.'
    Write-Host 'PASS: explicit consent stopped target UI/Agent and replaced payload; other installation untouched.'
    $consentLog = [IO.File]::ReadAllText((Join-Path $root 'silent-close-consent.log'))
    $uiStop = $consentLog.IndexOf('Close AutoScriptHub.exe PID ')
    $agentStop = $consentLog.IndexOf('Close AutoScriptAgent.exe PID ')
    Assert-True ($uiStop -ge 0 -and $agentStop -gt $uiStop) 'Installer log does not prove UI-before-Agent stop ordering.'
    Write-Host 'PASS: real installer log confirms UI-before-Agent stop ordering via explicit silent consent. Interactive Yes was not automated.'
} catch {
    Write-Host "FAIL: $($_.Exception.Message)"
    foreach ($log in @(Get-ChildItem -LiteralPath $root -Filter '*.log' -ErrorAction SilentlyContinue)) {
        Write-Host "--- $($log.Name) ---"
        Write-Host ([IO.File]::ReadAllText($log.FullName))
    }
    throw
} finally {
    # Stop only owned, recorded PIDs. UI first, then freshly enumerate recorded
    # Agents so watchdog races cannot escape cleanup. Never kill by image name.
    if (Test-Path -LiteralPath $records) {
        foreach ($owned in @(Get-OwnedProcesses | Where-Object { $_.Image.EndsWith('\AutoScriptHub.exe') })) {
            $owned.Process.Kill()
            [void]$owned.Process.WaitForExit(5000)
        }
    }
    foreach ($process in $launched) {
        if (-not $process.HasExited) { $process.Kill(); [void]$process.WaitForExit(5000) }
    }
    if (Test-Path -LiteralPath $records) {
        foreach ($owned in @(Get-OwnedProcesses)) { $owned.Process.Kill(); [void]$owned.Process.WaitForExit(5000) }
        Assert-True (@(Get-OwnedProcesses).Count -eq 0) 'Owned processes remain; temp directory retained.'
    }
    if (Test-Path -LiteralPath $root) { Remove-Item -LiteralPath $root -Recurse -Force }
    Write-Host 'Cleanup complete: recorded test processes stopped and isolated TEMP directory removed.'
}
