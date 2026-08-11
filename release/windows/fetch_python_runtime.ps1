param(
    [string]$CacheDir = "$(Join-Path $PSScriptRoot 'cache')"
)
$ErrorActionPreference = 'Stop'
$WebViewUrl = 'https://go.microsoft.com/fwlink/p/?LinkId=2124703'
$SecurityModule = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\Modules\Microsoft.PowerShell.Security\Microsoft.PowerShell.Security.psd1'

if (-not (Get-Command Get-AuthenticodeSignature -ErrorAction SilentlyContinue) -and
    (Test-Path -LiteralPath $SecurityModule)) {
    Import-Module -Name $SecurityModule -ErrorAction Stop
}

New-Item -ItemType Directory -Force -Path $CacheDir | Out-Null
$WebViewInstaller = Join-Path $CacheDir 'MicrosoftEdgeWebview2Setup.exe'

if (-not (Test-Path -LiteralPath $WebViewInstaller)) {
    Invoke-WebRequest -Uri $WebViewUrl -OutFile $WebViewInstaller
}
$Signature = Get-AuthenticodeSignature -LiteralPath $WebViewInstaller
if ($Signature.Status -ne 'Valid' -or $Signature.SignerCertificate.Subject -notmatch 'Microsoft') {
    throw "MicrosoftEdgeWebview2Setup.exe does not have a valid Microsoft signature"
}

Write-Output $CacheDir
