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
    Invoke-Python -m pip install --upgrade -r requirements-build-qt.txt
}

Invoke-Python -m unittest discover -v
Invoke-Python -c "from PySide6.QtWidgets import QApplication; from ui_qt.main_window import MainWindow; print('Qt import OK')"
$PreviousQtPlatform = $env:QT_QPA_PLATFORM
$env:QT_QPA_PLATFORM = "offscreen"
Invoke-Python -m ui_qt.layout_audit --output artifacts\ui-audit
if ($null -eq $PreviousQtPlatform) {
    Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
} else {
    $env:QT_QPA_PLATFORM = $PreviousQtPlatform
}
Invoke-Python -m PyInstaller --noconfirm --clean UmaLegacyLinkerQt.spec

$Bundle = Join-Path $PSScriptRoot "dist\UmaLegacyLinkerQt"
$Executable = Join-Path $Bundle "UmaLegacyLinkerQt.exe"
$Archive = Join-Path $PSScriptRoot "dist\UmaLegacyLinkerQt-preview-win64.zip"
$ChecksumFile = "$Archive.sha256"

if (Test-Path $Archive) {
    Remove-Item $Archive -Force
}
Compress-Archive -Path "$Bundle\*" -DestinationPath $Archive -CompressionLevel Optimal
$Checksum = (Get-FileHash $Archive -Algorithm SHA256).Hash.ToLowerInvariant()
"$Checksum  UmaLegacyLinkerQt-preview-win64.zip" | Set-Content $ChecksumFile -Encoding ascii

Write-Host "Build termine : $Executable"
Write-Host "Archive : $Archive"
Write-Host "SHA-256 : $Checksum"
