param(
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$Python = if (Get-Command py -ErrorAction SilentlyContinue) { "py" } else { "python" }

if (-not $SkipInstall) {
    & $Python -m pip install --upgrade -r requirements-build.txt
}

& $Python -m unittest discover -v
& $Python -m PyInstaller --noconfirm --clean UmaLegacyLinker.spec

$Executable = Join-Path $PSScriptRoot "dist\UmaLegacyLinker.exe"
$Checksum = (Get-FileHash $Executable -Algorithm SHA256).Hash.ToLowerInvariant()
"$Checksum  UmaLegacyLinker.exe" | Set-Content `
    (Join-Path $PSScriptRoot "dist\UmaLegacyLinker.exe.sha256") `
    -Encoding ascii

Write-Host "Build termine : $Executable"
Write-Host "SHA-256 : $Checksum"
