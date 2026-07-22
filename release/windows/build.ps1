param(
    [string]$Version = $(if ($env:AUTOSCRIPT_VERSION) { $env:AUTOSCRIPT_VERSION } else { '0.9.0-dev' }),
    [string]$PythonExe = 'python'
)
$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$OutputRoot = Join-Path $RepoRoot 'release-output'
$WindowsOutput = Join-Path $OutputRoot 'windows'
$GeneratedRoot = Join-Path $OutputRoot 'autoscript-build'
$RuntimeRoot = Join-Path $OutputRoot 'windows-runtime'
$RuntimePython = Join-Path $RuntimeRoot 'python'

if ($Version -notmatch '^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$') {
    throw "Version must be SemVer without a leading v: $Version"
}
$Channel = if ($Version.StartsWith('1.')) { 'stable' } else { 'beta' }

Push-Location $RepoRoot
try {
    & $PythonExe -m pip install -r backend/requirements.txt -r client/requirements.txt 'pytest==7.4.3' 'pyinstaller==6.11.1'
    if ($LASTEXITCODE -ne 0) { throw 'build dependency install failed' }
    & $PythonExe -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw 'pytest failed' }
    Push-Location (Join-Path $RepoRoot 'frontend')
    try {
        & npm ci
        if ($LASTEXITCODE -ne 0) { throw 'npm ci failed' }
        & npm test
        if ($LASTEXITCODE -ne 0) { throw 'npm test failed' }
        & npm run build
        if ($LASTEXITCODE -ne 0) { throw 'npm build failed' }
    } finally { Pop-Location }

    & $PSScriptRoot\fetch_python_runtime.ps1
    if (Test-Path -LiteralPath $RuntimePython) {
        $ExpectedRuntimeParent = [System.IO.Path]::GetFullPath($RuntimeRoot) + [System.IO.Path]::DirectorySeparatorChar
        $ResolvedRuntime = [System.IO.Path]::GetFullPath($RuntimePython)
        if (-not $ResolvedRuntime.StartsWith($ExpectedRuntimeParent)) {
            throw "Refusing to replace a runtime outside the release output: $ResolvedRuntime"
        }
        [System.IO.Directory]::Delete($ResolvedRuntime, $true)
    }
    New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null
    & $PSScriptRoot\stage_python_runtime.ps1 -PythonExe $PythonExe -Destination $RuntimePython
    if ($LASTEXITCODE -ne 0) { throw 'private Python runtime staging failed' }

    New-Item -ItemType Directory -Force -Path $WindowsOutput | Out-Null
    New-Item -ItemType Directory -Force -Path $GeneratedRoot | Out-Null
    $BuildInfo = "VERSION = '$Version'`nCHANNEL = '$Channel'`n"
    [System.IO.File]::WriteAllText(
        (Join-Path $GeneratedRoot 'autoscript_build_info.py'),
        $BuildInfo,
        [System.Text.UTF8Encoding]::new($false)
    )
    & $PythonExe -m PyInstaller --noconfirm --clean --distpath $WindowsOutput --workpath (Join-Path $OutputRoot 'pyinstaller-work') (Join-Path $PSScriptRoot 'autoscript_hub.spec')
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }

    $ISCC = (Get-Command iscc.exe -ErrorAction SilentlyContinue).Source
    if (-not $ISCC) {
        $Candidates = @(
            (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'),
            (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
            (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe')
        )
        $ISCC = $Candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    }
    if (-not $ISCC) { throw 'ISCC.exe (Inno Setup 6) was not found' }
    & $ISCC "/DMyAppVersion=$Version" (Join-Path $PSScriptRoot 'installer.iss')
    if ($LASTEXITCODE -ne 0) { throw 'ISCC failed' }

    $Installer = Join-Path $OutputRoot "AutoScript-Hub-Setup-$Version.exe"
    $Limit = 95MB
    if ((Get-Item -LiteralPath $Installer).Length -ge $Limit) {
        throw "Installer exceeds the 95MB Gitee release gate"
    }
    Write-Output $Installer
} finally {
    Pop-Location
}
