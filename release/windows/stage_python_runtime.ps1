param(
    [string]$PythonExe = 'python',
    [Parameter(Mandatory = $true)]
    [string]$Destination
)

$ErrorActionPreference = 'Stop'

$MetadataJson = & $PythonExe -c "import json, platform, sys; print(json.dumps({'version': platform.python_version(), 'bits': platform.architecture()[0], 'implementation': platform.python_implementation(), 'base_prefix': sys.base_prefix}))"
if ($LASTEXITCODE -ne 0) { throw 'Unable to inspect the Python runtime selected for packaging' }
$Metadata = $MetadataJson | ConvertFrom-Json
if ($Metadata.version -ne '3.11.9' -or $Metadata.bits -ne '64bit' -or $Metadata.implementation -ne 'CPython') {
    throw "The private runtime must be CPython 3.11.9 64-bit; got $($Metadata.implementation) $($Metadata.version) $($Metadata.bits)"
}

$SourceRoot = (Resolve-Path -LiteralPath $Metadata.base_prefix).Path
$DestinationPath = [System.IO.Path]::GetFullPath($Destination)
if ($DestinationPath -eq $SourceRoot -or $DestinationPath.StartsWith($SourceRoot + [System.IO.Path]::DirectorySeparatorChar)) {
    throw 'The staged runtime destination must not be inside the source Python installation'
}
if (Test-Path -LiteralPath $DestinationPath) {
    if ((Get-ChildItem -LiteralPath $DestinationPath -Force | Measure-Object).Count -ne 0) {
        throw "The staged runtime destination must be empty: $DestinationPath"
    }
} else {
    New-Item -ItemType Directory -Path $DestinationPath | Out-Null
}

$RequiredRootFiles = @(
    'python.exe',
    'pythonw.exe',
    'python3.dll',
    'python311.dll',
    'vcruntime140.dll',
    'vcruntime140_1.dll',
    'LICENSE.txt'
)
foreach ($Name in $RequiredRootFiles) {
    $Source = Join-Path $SourceRoot $Name
    if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) {
        throw "Required Python runtime file is missing: $Source"
    }
    Copy-Item -LiteralPath $Source -Destination (Join-Path $DestinationPath $Name)
}

$DllExit = Start-Process -FilePath 'robocopy.exe' -ArgumentList @(
    (Join-Path $SourceRoot 'DLLs'),
    (Join-Path $DestinationPath 'DLLs'),
    '/E', '/R:2', '/W:1', '/NFL', '/NDL', '/NJH', '/NJS', '/NP',
    '/XF', '*.pyc', '*.pyo'
) -Wait -PassThru -NoNewWindow
if ($DllExit.ExitCode -gt 7) { throw "Unable to copy Python DLLs; robocopy exit code $($DllExit.ExitCode)" }

$ExcludedSitePackages = Join-Path $SourceRoot 'Lib\site-packages'
$LibExit = Start-Process -FilePath 'robocopy.exe' -ArgumentList @(
    (Join-Path $SourceRoot 'Lib'),
    (Join-Path $DestinationPath 'Lib'),
    '/E', '/R:2', '/W:1', '/NFL', '/NDL', '/NJH', '/NJS', '/NP',
    '/XD', $ExcludedSitePackages, (Join-Path $SourceRoot 'Lib\__pycache__'), (Join-Path $SourceRoot 'Lib\test'),
    '/XF', '*.pyc', '*.pyo'
) -Wait -PassThru -NoNewWindow
if ($LibExit.ExitCode -gt 7) { throw "Unable to copy the Python standard library; robocopy exit code $($LibExit.ExitCode)" }

$StagedPython = Join-Path $DestinationPath 'python.exe'
& $StagedPython -c "import ensurepip, sqlite3, ssl, sys, venv; assert sys.version_info[:3] == (3, 11, 9)"
if ($LASTEXITCODE -ne 0) { throw 'The staged private Python cannot load its required standard-library modules' }

$Probe = Join-Path (Split-Path -Parent $DestinationPath) ('.python-runtime-probe-' + [System.Guid]::NewGuid().ToString('N'))
try {
    $VenvArguments = @("-m", "venv", $Probe)
    & $StagedPython @VenvArguments
    if ($LASTEXITCODE -ne 0) { throw 'The staged private Python cannot create a virtual environment' }
    $ProbePython = Join-Path $Probe 'Scripts\python.exe'
    $PipArguments = @("-m", "pip", "--version")
    & $ProbePython @PipArguments
    if ($LASTEXITCODE -ne 0) { throw 'The staged private Python virtual environment does not contain pip' }
} finally {
    if (Test-Path -LiteralPath $Probe) {
        [System.IO.Directory]::Delete($Probe, $true)
    }
}

$RuntimeBytes = (Get-ChildItem -LiteralPath $DestinationPath -Recurse -File | Measure-Object -Property Length -Sum).Sum
Write-Output "Staged CPython 3.11.9 runtime: $DestinationPath ($RuntimeBytes bytes)"
