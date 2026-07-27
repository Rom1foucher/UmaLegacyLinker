"""Keep the Qt-only release surfaces in sync."""

from __future__ import annotations

import unittest
from pathlib import Path

from ui_qt.core import APP_VERSION


ROOT = Path(__file__).resolve().parent


class ReleaseConsistencyTests(unittest.TestCase):
    def test_windows_metadata_matches_application_version(self) -> None:
        metadata = (ROOT / "windows_version_info_qt.txt").read_text(encoding="utf-8")
        version = tuple(int(part) for part in APP_VERSION.split(".")) + (0,)

        self.assertIn(f"filevers={version}", metadata)
        self.assertIn(f"prodvers={version}", metadata)
        self.assertIn(f"StringStruct('FileVersion', '{APP_VERSION}')", metadata)
        self.assertIn(f"StringStruct('ProductVersion', '{APP_VERSION}')", metadata)
        self.assertIn("flags=0x0", metadata)
        self.assertNotIn("preview", metadata.lower())

    def test_release_workflow_runs_the_visual_layout_audit(self) -> None:
        workflow = (
            ROOT / ".github" / "workflows" / "release-windows.yml"
        ).read_text(encoding="utf-8")
        self.assertIn(
            r".\build_windows_qt.ps1 -SkipInstall -RunLayoutAudit",
            workflow,
        )
        self.assertIn("actions/checkout@v7", workflow)
        self.assertIn("actions/setup-python@v7", workflow)
        self.assertIn("actions/upload-artifact@v7", workflow)

    def test_windows_build_restores_qt_audit_environment(self) -> None:
        script = (ROOT / "build_windows_qt.ps1").read_text(encoding="utf-8-sig")

        self.assertIn("$env:QT_QPA_PLATFORM = \"offscreen\"", script)
        self.assertIn("$env:QT_QPA_FONTDIR = $WindowsFontDir", script)
        self.assertIn("} finally {", script)
        self.assertIn("$env:QT_QPA_PLATFORM = $PreviousQtPlatform", script)
        self.assertIn("$env:QT_QPA_FONTDIR = $PreviousQtFontDir", script)

    def test_removed_tkinter_interface_is_not_packaged_or_advertised(self) -> None:
        spec = (ROOT / "UmaLegacyLinkerQt.spec").read_text(encoding="utf-8")
        package = (ROOT / "ui_qt" / "__init__.py").read_text(encoding="utf-8")
        home = (ROOT / "ui_qt" / "pages_home_data.py").read_text(encoding="utf-8")

        self.assertNotIn('"app"', spec)
        self.assertNotIn("QT_UI_VERSION", package)
        self.assertNotIn("Tkinter reste disponible", home)

    def test_release_docs_and_dependencies_are_qt_only(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        spec = (ROOT / "UmaLegacyLinkerQt.spec").read_text(encoding="utf-8")

        self.assertTrue((ROOT / "docs" / "QT_UI.md").is_file())
        self.assertFalse((ROOT / "docs" / "QT_UI_PREVIEW.md").exists())
        self.assertNotIn("QT_UI_PREVIEW.md", readme)
        self.assertNotIn("QT_UI_PREVIEW.md", spec)
        self.assertFalse((ROOT / "requirements-build.txt").exists())


if __name__ == "__main__":
    unittest.main()
