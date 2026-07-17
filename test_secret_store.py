from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from secret_store import load_api_key, save_api_key


class SecretStoreTests(unittest.TestCase):
    def test_protected_secret_round_trip_uses_no_plaintext(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "api-key.dat"
            with (
                patch("secret_store.protect_secret", return_value="encrypted-value"),
                patch("secret_store.unprotect_secret", return_value="secret-value"),
            ):
                save_api_key(path, "secret-value")
                self.assertEqual(path.read_text(encoding="ascii"), "encrypted-value")
                self.assertEqual(load_api_key(path), "secret-value")

    def test_empty_secret_removes_saved_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "api-key.dat"
            path.write_text("encrypted-value", encoding="ascii")
            save_api_key(path, "")
            self.assertFalse(path.exists())

    def test_invalid_or_unreadable_secret_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "api-key.dat"
            path.write_text("not-DPAPI", encoding="ascii")
            self.assertEqual(load_api_key(path), "")


if __name__ == "__main__":
    unittest.main()
