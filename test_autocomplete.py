import unittest

from autocomplete import filter_suggestions, normalize_search_text


class AutocompleteFilterTests(unittest.TestCase):
    def test_normalizes_case_accents_and_spaces(self):
        self.assertEqual(normalize_search_text("  TôKAI   Teiô "), "tokai teio")

    def test_matches_all_tokens_in_any_position(self):
        values = [
            "Tokai Teio — Beyond the Horizon",
            "Special Week — Special Dreamer",
            "Teio Tokai — Alternative",
        ]
        self.assertEqual(
            filter_suggestions("teio horizon", values),
            ["Tokai Teio — Beyond the Horizon"],
        )

    def test_prefix_matches_are_ranked_before_contains_matches(self):
        values = ["Mejiro McQueen", "Oguri Cap — Mejiro reference", "Mejiro Dober"]
        self.assertEqual(
            filter_suggestions("mejiro", values),
            ["Mejiro Dober", "Mejiro McQueen", "Oguri Cap — Mejiro reference"],
        )

    def test_empty_query_returns_alphabetical_limited_suggestions(self):
        self.assertEqual(filter_suggestions("", ["C", "A", "B"], limit=2), ["A", "B"])

    def test_deduplicates_values(self):
        self.assertEqual(filter_suggestions("rice", ["Rice Shower", "Rice Shower"]), ["Rice Shower"])


if __name__ == "__main__":
    unittest.main()
