from pathlib import Path

from PyInstaller.utils.hooks import copy_metadata


project_root = Path.cwd()
data_files = [
    (str(project_root / "default_course_overrides.json"), "."),
    (str(project_root / "default_manual_adjustments.json"), "."),
    (str(project_root / "default_parent_scoring.json"), "."),
    (str(project_root / "default_skill_priorities.json"), "."),
    (str(project_root / "docs" / "THIRD_PARTY.md"), "docs"),
    (str(project_root / "docs" / "QT_UI_PREVIEW.md"), "docs"),
    (str(project_root / "docs" / "WEIGHTS_UI_DESIGN.md"), "docs"),
]
for distribution in ("PySide6", "PySide6_Essentials", "shiboken6"):
    try:
        data_files += copy_metadata(distribution)
    except Exception:
        pass

a = Analysis(
    [str(project_root / "qt_app.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=data_files,
    hiddenimports=["PySide6.QtNetwork"],
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
    [],
    exclude_binaries=True,
    name="UmaLegacyLinkerQt",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=str(project_root / "windows_version_info_qt.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="UmaLegacyLinkerQt",
)
