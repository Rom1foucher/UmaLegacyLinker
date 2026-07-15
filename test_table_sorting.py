from __future__ import annotations

import unittest

from app import Application


class TreeSortValueTests(unittest.TestCase):
    def test_numeric_values_sort_numerically(self) -> None:
        values = ["10", "2", "1 234", "42"]
        self.assertEqual(
            sorted(values, key=Application._tree_sort_value),
            ["2", "10", "42", "1 234"],
        )

    def test_percentile_and_star_values_are_numeric(self) -> None:
        self.assertLess(
            Application._tree_sort_value("top 5.5%"),
            Application._tree_sort_value("top 12.0%"),
        )
        self.assertLess(
            Application._tree_sort_value("3★/1"),
            Application._tree_sort_value("9★/3"),
        )

    def test_mixed_natural_values_do_not_compare_strings_with_numbers(self) -> None:
        values = ["Uma 10", "2nd Uma", "Uma 2", "Alpha"]
        self.assertEqual(
            sorted(values, key=Application._tree_sort_value),
            ["2nd Uma", "Alpha", "Uma 2", "Uma 10"],
        )

    def test_missing_values_have_a_dedicated_sort_bucket(self) -> None:
        self.assertEqual(Application._tree_sort_value("—")[0], 3)
        self.assertEqual(Application._tree_sort_value("")[0], 3)



if __name__ == "__main__":
    unittest.main()
