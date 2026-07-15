from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from parent_optimizer import load_ace_options


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


if __name__ == "__main__":
    unittest.main()
