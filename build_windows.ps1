$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

py -m pip install --upgrade pyinstaller pyyaml
py -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --windowed `
  --name UmaLegacyLinker `
  app.py

Copy-Item default_manual_adjustments.json dist\default_manual_adjustments.json -Force
Copy-Item default_course_overrides.json dist\default_course_overrides.json -Force
Copy-Item default_parent_scoring.json dist\default_parent_scoring.json -Force
Copy-Item default_skill_priorities.json dist\default_skill_priorities.json -Force

Write-Host "Build termine : $PSScriptRoot\dist\UmaLegacyLinker.exe"
