"""Both extraction backends must be driven correctly.

umadump reads the game memory and writes its exports relative to the working
directory; UmaExtractor intercepts a cached API response and writes a single
data.json next to itself. The tool is picked by name, so no extra switch has
to be kept in sync with the user's choice.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ui_qt.core import (
    UMADUMP_COLLECTION_FILE,
    UMAEXTRACTOR_COLLECTION_FILE,
    extractor_backend,
    run_extractor,
)


def fake_tool(directory: Path, name: str, writes: str) -> Path:
    """A stand-in tool that just drops the export its real counterpart would."""
    directory.mkdir(parents=True, exist_ok=True)
    tool = directory / name
    tool.write_text(
        "import json, pathlib, sys\n"
        f"pathlib.Path({writes!r}).write_text(json.dumps("
        "[{'trained_chara_id': 1, 'card_id': 100101, 'use_type': 0}]"
        "), encoding='utf-8')\n"
        "print('ARGS ' + ' '.join(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    return tool


class ExtractorBackendTests(unittest.TestCase):
    def test_backend_is_detected_from_the_tool_or_its_folder(self) -> None:
        self.assertEqual(extractor_backend(Path("C:/t/umadump.exe")), "umadump")
        self.assertEqual(extractor_backend(Path("C:/umadump/main.py")), "umadump")
        self.assertEqual(extractor_backend(Path("C:/t/UmaDump.exe")), "umadump")
        self.assertEqual(extractor_backend(Path("C:/t/umaextractor.exe")), "umaextractor")
        self.assertEqual(extractor_backend(Path("C:/t/UmaExtractor.exe")), "umaextractor")

    def test_umadump_runs_in_the_output_folder_and_returns_its_export(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            tool = fake_tool(root / "umadump", "main.py", UMADUMP_COLLECTION_FILE)
            output = root / "output"
            logs: list[str] = []
            result = run_extractor(tool, output_dir=output, logger=logs.append)

            # Written to the output folder, not next to the tool.
            self.assertEqual(result, output / UMADUMP_COLLECTION_FILE)
            self.assertTrue(result.is_file())
            self.assertFalse((tool.parent / UMADUMP_COLLECTION_FILE).exists())
            self.assertEqual(
                json.loads(result.read_text(encoding="utf-8"))[0]["card_id"], 100101
            )
            # Run once and without the startup release lookup.
            args = next(line for line in logs if "ARGS" in line)
            self.assertIn("--rerun-mode once", args)
            self.assertIn("--no-update-check", args)

    def test_umaextractor_keeps_its_cli_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            tool = fake_tool(root / "tools", "umaextractor.py", UMAEXTRACTOR_COLLECTION_FILE)
            logs: list[str] = []
            result = run_extractor(tool, output_dir=root / "output", logger=logs.append)

            self.assertEqual(result, tool.parent / UMAEXTRACTOR_COLLECTION_FILE)
            args = next(line for line in logs if "ARGS" in line)
            self.assertIn("--cli", args)
            self.assertNotIn("--rerun-mode", args)

    def test_a_missing_tool_is_reported_before_launching_anything(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(Exception):
                run_extractor(
                    Path(temp) / "umadump.exe",
                    output_dir=Path(temp),
                    logger=lambda _message: None,
                )


if __name__ == "__main__":
    unittest.main()
