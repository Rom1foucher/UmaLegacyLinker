from __future__ import annotations

import unittest

from manual_weights import _profile_weight


class ManualProfileWeightTests(unittest.TestCase):
    def test_explicit_zero_is_a_hard_incompatibility(self) -> None:
        entry = {
            "base": 0.03,
            "distance": {"mile": 0.0, "medium": 0.42},
            "style": {"pace_chaser": 0.42},
        }
        weight, reasons = _profile_weight(entry, "turf", "mile", "pace_chaser")
        self.assertEqual(weight, 0.0)
        self.assertIn("combined_dimensions=0.000", reasons)

    def test_nonzero_dimensions_are_averaged(self) -> None:
        entry = {
            "base": 0.05,
            "distance": {"medium": 1.06},
            "style": {"late_surger": 1.08},
        }
        weight, _reasons = _profile_weight(entry, "turf", "medium", "late_surger")
        self.assertAlmostEqual(weight, 1.07)

    def test_profile_cap_preserves_a_strong_style_penalty(self) -> None:
        entry = {
            "base": 1.02,
            "distance": {"long": 1.10},
            "style": {"front_runner": 0.02},
            "profiles": [
                {
                    "match": {"style": "front_runner"},
                    "operation": "cap",
                    "value": 0.08,
                }
            ],
        }
        weight, reasons = _profile_weight(entry, "turf", "long", "front_runner")
        self.assertEqual(weight, 0.08)
        self.assertIn("rule:cap(0.080)", reasons)


if __name__ == "__main__":
    unittest.main()
