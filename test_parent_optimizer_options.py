from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from parent_optimizer import _valid_grandparent_for_target_parent, load_ace_options


class AceOptionTests(unittest.TestCase):
    def test_options_are_sorted_by_uma_and_display_uma_first(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "master.mdb"
            connection = sqlite3.connect(database)
            try:
                connection.execute("CREATE TABLE text_data (category INTEGER, `index` INTEGER, text TEXT)")
                connection.execute("CREATE TABLE card_data (id INTEGER, chara_id INTEGER)")
                connection.executemany(
                    "INSERT INTO text_data(category, `index`, text) VALUES (?, ?, ?)",
                    [
                        (4, 20, "Wild Top Gear"),
                        (4, 10, "Tach-nology"),
                        (5, 20, "Costume B"),
                        (5, 10, "Costume A"),
                        (6, 2, "Vodka"),
                        (6, 1, "Agnes Tachyon"),
                    ],
                )
                connection.executemany(
                    "INSERT INTO card_data(id, chara_id) VALUES (?, ?)",
                    [(20, 2), (10, 1)],
                )
                connection.commit()
            finally:
                connection.close()

            options = load_ace_options(database)
            self.assertEqual([option.uma_name for option in options], ["Agnes Tachyon", "Vodka"])
            self.assertEqual(options[0].display_name, "Agnes Tachyon — Tach-nology (10)")


class GrandparentConstraintTests(unittest.TestCase):
    def test_target_parent_is_rejected_across_costume_variants(self) -> None:
        target_parent_chara_id = 1032
        alternate_costume_gp = {"card_id": 103299, "chara_id": 1032}
        self.assertFalse(
            _valid_grandparent_for_target_parent(
                alternate_costume_gp, target_parent_chara_id
            )
        )

    def test_target_ace_remains_a_valid_grandparent(self) -> None:
        target_parent_chara_id = 1032
        target_ace_as_gp = {"card_id": 100602, "chara_id": 1006}
        self.assertTrue(
            _valid_grandparent_for_target_parent(
                target_ace_as_gp, target_parent_chara_id
            )
        )


if __name__ == "__main__":
    unittest.main()
