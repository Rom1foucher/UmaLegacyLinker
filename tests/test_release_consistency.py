"""Keep the Qt-only release surfaces in sync."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from ui_qt.core import APP_VERSION


ROOT = Path(__file__).resolve().parents[1]


class ReleaseConsistencyTests(unittest.TestCase):
    def test_release_version_is_current_across_public_surfaces(self) -> None:
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        releasing = (ROOT / "docs" / "RELEASING.md").read_text(encoding="utf-8")
        release_headings = re.findall(r"^## (\d+\.\d+\.\d+)\b", changelog, re.MULTILINE)

        self.assertTrue(release_headings)
        self.assertEqual(release_headings[0], APP_VERSION)
        self.assertIn(f"git tag v{APP_VERSION}", readme)
        self.assertIn(f"git push origin v{APP_VERSION}", readme)
        self.assertIn(f"git tag v{APP_VERSION}", releasing)
        self.assertIn(f"git push origin v{APP_VERSION}", releasing)

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

        self.assertIn("-m pytest -q tests --ignore=tests/test_qt_runtime.py", script)
        self.assertIn("tests/check_i18n.py", script)
        self.assertIn("from tests.test_qt_runtime import QtRuntimeSmokeTests", script)
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

    def test_run_bat_launches_without_a_lingering_console(self) -> None:
        script = (ROOT / "run.bat").read_text(encoding="utf-8")
        self.assertIn("where pyw", script)
        self.assertIn('start "" pyw qt_app.py', script)

    def test_release_docs_and_dependencies_are_qt_only(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        spec = (ROOT / "UmaLegacyLinkerQt.spec").read_text(encoding="utf-8")

        self.assertTrue((ROOT / "docs" / "QT_UI.md").is_file())
        self.assertFalse((ROOT / "docs" / "QT_UI_PREVIEW.md").exists())
        self.assertNotIn("QT_UI_PREVIEW.md", readme)
        self.assertNotIn("QT_UI_PREVIEW.md", spec)
        self.assertFalse((ROOT / "requirements-build.txt").exists())

    def test_tests_are_grouped_and_release_dependencies_cover_pytest(self) -> None:
        requirements = (ROOT / "requirements-build-qt.txt").read_text(encoding="utf-8")

        self.assertFalse(list(ROOT.glob("test_*.py")))
        self.assertFalse((ROOT / "check_i18n.py").exists())
        self.assertTrue((ROOT / "tests" / "__init__.py").is_file())
        self.assertTrue((ROOT / "tests" / "check_i18n.py").is_file())
        self.assertGreaterEqual(len(list((ROOT / "tests").glob("test_*.py"))), 20)
        self.assertRegex(requirements, r"(?m)^pytest(?:\[.*?\])?[<>=]")

    def test_local_markdown_links_resolve(self) -> None:
        markdown_files = [ROOT / "README.md", *(ROOT / "docs").glob("*.md")]
        missing: list[str] = []
        for document in markdown_files:
            text = document.read_text(encoding="utf-8")
            for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
                target = target.strip().split("#", 1)[0]
                if not target or re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE):
                    continue
                resolved = (document.parent / target).resolve()
                if not resolved.exists():
                    missing.append(f"{document.relative_to(ROOT)} -> {target}")
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
