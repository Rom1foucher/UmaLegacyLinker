from __future__ import annotations

import sqlite3
import unittest

from skill_catalog import direct_support_hint_sources


class SkillCatalogAcquisitionTests(unittest.TestCase):
    def test_direct_support_hint_sources_count_distinct_cards(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        self.addCleanup(connection.close)
        connection.execute(
            """
            CREATE TABLE single_mode_hint_gain (
                id INTEGER PRIMARY KEY,
                support_card_id INTEGER NOT NULL,
                hint_gain_type INTEGER NOT NULL,
                hint_value_1 INTEGER NOT NULL
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO single_mode_hint_gain
                (support_card_id, hint_gain_type, hint_value_1)
            VALUES (?, ?, ?)
            """,
            [
                (1001, 0, 2001),
                (1001, 0, 2001),
                (1002, 0, 2001),
                (1003, 1, 2001),
                (1004, 0, 2002),
            ],
        )

        available, sources = direct_support_hint_sources(connection)

        self.assertTrue(available)
        self.assertEqual(sources[2001]["direct_support_hint_card_count"], 2)
        self.assertEqual(sources[2001]["direct_support_hint_card_ids"], [1001, 1002])
        self.assertEqual(sources[2002]["direct_support_hint_card_count"], 1)

    def test_missing_hint_table_is_unknown_instead_of_zero(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        self.addCleanup(connection.close)

        available, sources = direct_support_hint_sources(connection)

        self.assertFalse(available)
        self.assertEqual(sources, {})


if __name__ == "__main__":
    unittest.main()
