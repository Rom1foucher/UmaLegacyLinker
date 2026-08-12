param(
    [switch]$SkipInstall,
    [switch]$RunLayoutAudit
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

Invoke-Python -m pytest -q tests --ignore=tests/test_qt_runtime.py
Invoke-Python tests/check_i18n.py

Invoke-Python -c "from PySide6.QtWidgets import QApplication; from ui_qt.main_window import MainWindow; print('Qt import OK')"
$PreviousQtPlatform = $env:QT_QPA_PLATFORM
$PreviousQtFontDir = $env:QT_QPA_FONTDIR
try {
    $env:QT_QPA_PLATFORM = "offscreen"
    $WindowsFontDir = Join-Path $env:WINDIR "Fonts"
    if (Test-Path $WindowsFontDir) {
        $env:QT_QPA_FONTDIR = $WindowsFontDir
    }
    # Run every Qt smoke test in a fresh process. Some PySide6/Qt objects are
    # destroyed asynchronously and can trigger a native access violation during
    # interpreter teardown when several widget-heavy tests share one process.
    $DiscoveredQtTests = @(
        & $Python -c "import unittest; from tests.test_qt_runtime import QtRuntimeSmokeTests; suite = unittest.defaultTestLoader.loadTestsFromTestCase(QtRuntimeSmokeTests); print('\n'.join(test.id() for test in suite))"
    )
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to discover Qt runtime tests (exit code $LASTEXITCODE)."
    }
    $QtSmokeTests = @(
        $DiscoveredQtTests |
            Where-Object { $_ -match '^tests\.test_qt_runtime\.QtRuntimeSmokeTests\.test_' }
    )
    if ($QtSmokeTests.Count -eq 0) {
        throw "No Qt runtime tests were discovered."
    }
    foreach ($QtSmokeTest in $QtSmokeTests) {
        Invoke-Python -m unittest -v $QtSmokeTest
    }
    if ($RunLayoutAudit) {
        Invoke-Python -m ui_qt.layout_audit --output artifacts\ui-audit
    } else {
        Write-Host "Layout audit skipped (use -RunLayoutAudit to enable it)."
    }
} finally {
    if ($null -eq $PreviousQtPlatform) {
        Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
    } else {
        $env:QT_QPA_PLATFORM = $PreviousQtPlatform
    }
    if ($null -eq $PreviousQtFontDir) {
        Remove-Item Env:QT_QPA_FONTDIR -ErrorAction SilentlyContinue
    } else {
        $env:QT_QPA_FONTDIR = $PreviousQtFontDir
    }
}
Invoke-Python -m PyInstaller --noconfirm --clean UmaLegacyLinkerQt.spec

$Bundle = Join-Path $PSScriptRoot "dist\UmaLegacyLinkerQt"
$Executable = Join-Path $Bundle "UmaLegacyLinkerQt.exe"
$Archive = Join-Path $PSScriptRoot "dist\UmaLegacyLinkerQt-win64.zip"
$ChecksumFile = "$Archive.sha256"

if (Test-Path $Archive) {
    Remove-Item $Archive -Force
}
Compress-Archive -Path "$Bundle\*" -DestinationPath $Archive -CompressionLevel Optimal
$Checksum = (Get-FileHash $Archive -Algorithm SHA256).Hash.ToLowerInvariant()
"$Checksum  UmaLegacyLinkerQt-win64.zip" | Set-Content $ChecksumFile -Encoding ascii

Write-Host "Build termine : $Executable"
Write-Host "Archive : $Archive"
Write-Host "SHA-256 : $Checksum"
