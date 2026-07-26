"""Borrowed veterans must never reach the collection analysis.

Both extractors report what the game reports, which includes the veterans
rented for an in-progress career. Filtering them is the consumer's job.
"""
from __future__ import annotations

import unittest

from legacy_linker import is_borrowed_veteran, normalize_json_root


def veteran(trained_chara_id: int, use_type: object = 0) -> dict[str, object]:
    return {"trained_chara_id": trained_chara_id, "use_type": use_type, "card_id": 100101}


class BorrowedVeteranTests(unittest.TestCase):
    def test_non_zero_use_type_marks_a_borrow(self) -> None:
        self.assertFalse(is_borrowed_veteran(veteran(1, 0)))
        self.assertTrue(is_borrowed_veteran(veteran(2, 1)))
        self.assertTrue(is_borrowed_veteran(veteran(3, 2)))

    def test_missing_or_invalid_use_type_keeps_the_veteran(self) -> None:
        # An older export without the field must not lose the whole collection.
        self.assertFalse(is_borrowed_veteran({"trained_chara_id": 1}))
        self.assertFalse(is_borrowed_veteran(veteran(1, None)))
        self.assertFalse(is_borrowed_veteran(veteran(1, "")))
        self.assertFalse(is_borrowed_veteran(veteran(1, "not-a-number")))

    def test_normalize_drops_borrowed_entries_from_every_root_shape(self) -> None:
        owned = [veteran(1), veteran(2)]
        borrowed = [veteran(90, 1), veteran(91, 3)]
        for payload in (
            owned + borrowed,
            {"trained_chara_array": owned + borrowed},
            {"veterans": owned + borrowed},
            {"data": owned + borrowed},
        ):
            with self.subTest(root=type(payload).__name__):
                kept = normalize_json_root(payload)
                self.assertEqual([v["trained_chara_id"] for v in kept], [1, 2])

    def test_include_borrowed_is_opt_in(self) -> None:
        payload = [veteran(1), veteran(90, 1)]
        self.assertEqual(len(normalize_json_root(payload)), 1)
        self.assertEqual(len(normalize_json_root(payload, include_borrowed=True)), 2)

    def test_string_use_type_is_honoured(self) -> None:
        # umadump and UmaExtractor both emit integers today, but a JSON
        # round-trip through some tooling can turn them into strings.
        self.assertTrue(is_borrowed_veteran(veteran(1, "1")))
        self.assertFalse(is_borrowed_veteran(veteran(1, "0")))


if __name__ == "__main__":
    unittest.main()
