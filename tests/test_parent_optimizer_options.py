from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from parent_optimizer import (
    _serialize_top_results,
    _valid_grandparent_for_target_parent,
    load_ace_options,
)


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


class LocalLineageSerializationTests(unittest.TestCase):
    def test_local_rows_receive_full_spark_lineage_from_veteran_index(self) -> None:
        ancestor = {
            "trained_chara_id": "ancestor",
            "card_name": "Ancestor",
            "sparks": [{"name": "Power", "stars": 2, "type": "blue_stat"}],
        }
        grandparent = {
            "trained_chara_id": "grandparent",
            "card_name": "Grandparent",
            "sparks": [{"name": "Stamina", "stars": 3, "type": "blue_stat"}],
            "when_used_as_parent": {
                "grandparent_1": {"trained_chara_id": "ancestor"}
            },
        }
        parent = {
            "trained_chara_id": "parent",
            "card_name": "Parent",
            "sparks": [{"name": "Speed", "stars": 3, "type": "blue_stat"}],
            "when_used_as_parent": {
                "grandparent_1": {"trained_chara_id": "grandparent"}
            },
        }
        other_parent = {
            "trained_chara_id": "other",
            "card_name": "Other parent",
            "sparks": [{"name": "Guts", "stars": 1, "type": "blue_stat"}],
        }
        veterans = [parent, other_parent, grandparent, ancestor]
        branches, pairs, future = _serialize_top_results(
            [{"score": 90.0, "veteran": parent}],
            [
                {
                    "score": 95.0,
                    "parent_1": {"trained_chara_id": "parent"},
                    "parent_2": {"trained_chara_id": "other"},
                }
            ],
            [{"score": 85.0, "trained_chara_id": "parent"}],
            veterans,
            top_n=10,
            search_kind="all",
        )

        self.assertNotIn("veteran", branches[0])
        for row in (branches[0], pairs[0], future[0]):
            preview = row["lineage_preview"]
            self.assertEqual(preview["p1"]["sparks"][0]["name"], "Speed")
            self.assertEqual(preview["p1-1"]["sparks"][0]["name"], "Stamina")
            self.assertEqual(preview["p1-1-1"]["sparks"][0]["name"], "Power")
        self.assertEqual(
            pairs[0]["lineage_preview"]["p2"]["sparks"][0]["name"], "Guts"
        )

    def test_serialization_only_returns_the_requested_local_result_kind(self) -> None:
        parent = {"trained_chara_id": "parent", "card_name": "Parent"}
        branches, pairs, future = _serialize_top_results(
            [{"score": 1.0, "veteran": parent}],
            [
                {
                    "score": 2.0,
                    "parent_1": {"trained_chara_id": "parent"},
                    "parent_2": {"trained_chara_id": "parent"},
                }
            ],
            [{"score": 3.0, "trained_chara_id": "parent"}],
            [parent],
            top_n=10,
            search_kind="pairs",
        )
        self.assertEqual(branches, [])
        self.assertEqual(len(pairs), 1)
        self.assertEqual(future, [])


if __name__ == "__main__":
    unittest.main()
