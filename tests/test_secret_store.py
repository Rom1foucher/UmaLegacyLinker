from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from secret_store import load_api_key, resolve_api_key, save_api_key


class SecretStoreTests(unittest.TestCase):
    def test_dpapi_round_trip_uses_versioned_payload_without_plaintext(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "api-key.dat"
            with (
                patch("secret_store._uses_windows_dpapi", return_value=True),
                patch("secret_store.protect_secret", return_value="encrypted-value"),
                patch("secret_store.unprotect_secret", return_value="secret-value"),
            ):
                save_api_key(path, "secret-value")
                self.assertEqual(
                    path.read_text(encoding="ascii"),
                    "dpapi-v1:encrypted-value",
                )
                self.assertEqual(load_api_key(path), "secret-value")

    def test_plaintext_posix_round_trip_uses_versioned_base64_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "api-key.dat"
            with (
                patch("secret_store._uses_windows_dpapi", return_value=False),
                patch(
                    "secret_store.os.fchmod",
                    side_effect=AssertionError("plaintext storage must not require os.fchmod"),
                    create=True,
                ),
            ):
                save_api_key(path, "clé-secrète")
                self.assertEqual(
                    path.read_text(encoding="ascii"),
                    "plain-v1:Y2zDqS1zZWNyw6h0ZQ==",
                )
                self.assertEqual(load_api_key(path), "clé-secrète")

    def test_legacy_unversioned_dpapi_payload_is_still_readable_on_windows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "api-key.dat"
            path.write_text("legacy-encrypted-value", encoding="ascii")
            with (
                patch("secret_store._uses_windows_dpapi", return_value=True),
                patch("secret_store.unprotect_secret", return_value="secret-value") as unprotect,
            ):
                self.assertEqual(load_api_key(path), "secret-value")
                unprotect.assert_called_once_with("legacy-encrypted-value")

    def test_environment_key_has_priority_over_a_remembered_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "api-key.dat"
            with (
                patch.dict(os.environ, {"UMA_MOE_API_KEY": "environment-value"}),
                patch("secret_store.load_api_key", return_value="remembered-value") as load,
            ):
                self.assertEqual(
                    resolve_api_key(path, remembered=True),
                    "environment-value",
                )
                load.assert_not_called()

    @unittest.skipUnless(os.name == "posix", "POSIX permissions are required")
    def test_posix_directory_and_files_use_strict_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "UmaLegacyLinker" / "api-key.dat"
            save_api_key(path, "secret-value")
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

            path.parent.chmod(0o755)
            path.chmod(0o644)
            save_api_key(path, "secret-value")
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_empty_secret_removes_saved_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "api-key.dat"
            path.write_text("plain-v1:c2VjcmV0", encoding="ascii")
            save_api_key(path, "")
            self.assertFalse(path.exists())

    def test_invalid_secret_is_ignored_and_can_be_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "api-key.dat"
            path.write_text("plain-v1:not-valid-base64!", encoding="ascii")
            with patch("secret_store._uses_windows_dpapi", return_value=False):
                self.assertEqual(load_api_key(path), "")
                save_api_key(path, "replacement")
                self.assertEqual(load_api_key(path), "replacement")


if __name__ == "__main__":
    unittest.main()
