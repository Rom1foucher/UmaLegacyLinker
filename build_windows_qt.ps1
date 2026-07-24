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

$NonQtTestModules = @(
    Get-ChildItem -Path $PSScriptRoot -Filter "test_*.py" -File |
        Where-Object { $_.Name -ne "test_qt_runtime.py" } |
        Sort-Object Name |
        ForEach-Object { $_.BaseName }
)
Invoke-Python -m unittest -v @NonQtTestModules

Invoke-Python -c "from PySide6.QtWidgets import QApplication; from ui_qt.main_window import MainWindow; print('Qt import OK')"
$PreviousQtPlatform = $env:QT_QPA_PLATFORM
$env:QT_QPA_PLATFORM = "offscreen"
# Run every Qt smoke test in a fresh process. Some PySide6/Qt objects are
# destroyed asynchronously and can trigger a native access violation during
# interpreter teardown when several widget-heavy tests share one process.
$QtSmokeTests = @(
    "test_qt_runtime.QtRuntimeSmokeTests.test_distribution_chart_renders_at_editor_width",
    "test_qt_runtime.QtRuntimeSmokeTests.test_every_page_constructs_and_retranslates",
    "test_qt_runtime.QtRuntimeSmokeTests.test_grandparent_dialog_uses_target_parent_as_root",
    "test_qt_runtime.QtRuntimeSmokeTests.test_lineage_dialog_renders_complete_pair_without_network",
    "test_qt_runtime.QtRuntimeSmokeTests.test_result_panes_do_not_refresh_before_the_detail_browser_exists",
    "test_qt_runtime.QtRuntimeSmokeTests.test_searchable_combo_resolves_text_without_stale_item_data",
    "test_qt_runtime.QtRuntimeSmokeTests.test_weight_page_uses_categories_and_typed_controls"
)
foreach ($QtSmokeTest in $QtSmokeTests) {
    Invoke-Python -m unittest -v $QtSmokeTest
}
if ($RunLayoutAudit) {
    Invoke-Python -m ui_qt.layout_audit --output artifacts\ui-audit
} else {
    Write-Host "Layout audit skipped (use -RunLayoutAudit to enable it)."
}
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
