from pathlib import Path


project_root = Path.cwd()
data_files = [
    (str(project_root / "default_course_overrides.json"), "."),
    (str(project_root / "default_manual_adjustments.json"), "."),
    (str(project_root / "default_parent_scoring.json"), "."),
    (str(project_root / "default_skill_priorities.json"), "."),
]

a = Analysis(
    [str(project_root / "app.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=data_files,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="UmaLegacyLinker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=str(project_root / "windows_version_info.txt"),
)
