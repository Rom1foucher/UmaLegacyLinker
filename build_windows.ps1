param(
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$Python = (Get-Command python -ErrorAction Stop).Source

function Invoke-Python {
    & $Python @args
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed with exit code $LASTEXITCODE."
    }
}

if (-not $SkipInstall) {
    Invoke-Python -m pip install --upgrade -r requirements-build.txt
}

Invoke-Python -m unittest discover -v
Invoke-Python -m PyInstaller --noconfirm --clean UmaLegacyLinker.spec

$Executable = Join-Path $PSScriptRoot "dist\UmaLegacyLinker.exe"
$Checksum = (Get-FileHash $Executable -Algorithm SHA256).Hash.ToLowerInvariant()
"$Checksum  UmaLegacyLinker.exe" | Set-Content `
    (Join-Path $PSScriptRoot "dist\UmaLegacyLinker.exe.sha256") `
    -Encoding ascii

Write-Host "Build termine : $Executable"
Write-Host "SHA-256 : $Checksum"
