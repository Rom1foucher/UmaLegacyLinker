from __future__ import annotations

import copy
import json
import math
import unittest
from pathlib import Path

from spark_protection import build_spark_heritage, compare_spark_heritage
from transfer_helper import DominanceAccumulator, classify_transfer_records


PROJECT_DIR = Path(__file__).resolve().parents[1]


def factor(name: str, stars: int) -> dict:
    return {"name": name, "stars": stars}


def member(
    *,
    whites: list[tuple[str, int]] | None = None,
    races: list[tuple[str, int]] | None = None,
) -> dict:
    return {
        "factors": {
            "by_type": {
                "white_skill": [factor(name, stars) for name, stars in whites or []],
                "white_race": [factor(name, stars) for name, stars in races or []],
            }
        }
    }


def veteran(
    *,
    whites: list[tuple[str, int]] | None = None,
    races: list[tuple[str, int]] | None = None,
    gp1: dict | None = None,
    gp2: dict | None = None,
) -> dict:
    result = member(whites=whites, races=races)
    result["when_used_as_parent"] = {
        key: value
        for key, value in (("grandparent_1", gp1), ("grandparent_2", gp2))
        if value is not None
    }
    return result


class SparkProtectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = json.loads(
            (PROJECT_DIR / "default_parent_scoring.json").read_text(encoding="utf-8")
        )
        self.protection = self.config["transfer_helper"]["spark_protection"]
        self.catalog = {
            "white_skill_spark_groups": [
                {
                    "catalog_key": key,
                    "spark_name": name,
                    "direct_support_hint_card_count": count,
                }
                for key, name, count in (
                    ("nimble_navigator", "Nimble Navigator", 3),
                    ("ramp_up", "Ramp Up", 2),
                    ("uma_stan", "Uma Stan", 0),
                    ("slipstream", "Slipstream", 4),
                )
            ]
        }
        self.active = {
            key: {
                "weight": weight,
                "context": {
                    "context_key": "course:test:late_surger",
                    "profile": "Test course · late_surger",
                },
            }
            for key, weight in (
                ("nimble_navigator", 1.10),
                ("ramp_up", 0.78),
                ("uma_stan", 1.18),
                ("slipstream", 0.82),
            )
        }

    def heritage(self, value: dict, race_map: dict[str, list[str]] | None = None) -> dict:
        return build_spark_heritage(
            value,
            race_map or {},
            self.catalog,
            self.active,
            self.config,
        )

    def test_direct_white_and_race_spark_share_one_effective_skill(self) -> None:
        heritage = self.heritage(
            veteran(
                whites=[("Nimble Navigator", 3)],
                gp1=member(races=[("Example Race", 2)]),
            ),
            {"Example Race": ["nimble_navigator"]},
        )
        nimble = heritage["skills"]["nimble_navigator"]
        expected = 1.0 - (1.0 - 0.09) ** 2 * (1.0 - 0.02) ** 2
        self.assertEqual(nimble["carrier_count"], 2)
        self.assertEqual(nimble["total_stars"], 5)
        self.assertEqual(nimble["source_types"], ["white_race", "white_skill"])
        self.assertTrue(nimble["direct"])
        self.assertTrue(
            math.isclose(nimble["neutral_probability"], expected, abs_tol=1e-8)
        )

    def test_two_two_star_carriers_are_not_replaced_by_one_three_star_carrier(self) -> None:
        candidate = self.heritage(
            veteran(
                whites=[("Slipstream", 2)],
                gp1=member(whites=[("Slipstream", 2)]),
            )
        )
        replacement = self.heritage(veteran(whites=[("Slipstream", 3)]))
        result = compare_spark_heritage(candidate, replacement, self.protection)
        self.assertTrue(result["applied"])
        self.assertEqual(result["verdict_floor"], "review")
        self.assertIn("protected_repeated_white_spark", result["reason_codes"])
        skill = next(
            deficit for deficit in result["deficits"] if deficit["kind"] == "skill"
        )
        self.assertGreater(
            skill["candidate"]["neutral_probability"],
            skill["replacement"]["neutral_probability"],
        )

    def test_preserved_repeated_coverage_stays_safe(self) -> None:
        candidate = self.heritage(
            veteran(
                whites=[("Slipstream", 2)],
                gp1=member(whites=[("Slipstream", 2)]),
            )
        )
        replacement = self.heritage(
            veteran(
                whites=[("Slipstream", 2)],
                gp1=member(whites=[("Slipstream", 2)]),
            )
        )
        result = compare_spark_heritage(candidate, replacement, self.protection)
        self.assertFalse(result["applied"])
        self.assertIsNone(result["verdict_floor"])

    def test_direct_three_star_future_gp_source_sets_likely_keep_floor(self) -> None:
        candidate = self.heritage(
            veteran(
                whites=[("Nimble Navigator", 3)],
                gp1=member(whites=[("Nimble Navigator", 2)]),
            )
        )
        replacement = self.heritage(
            veteran(gp1=member(whites=[("Nimble Navigator", 2)]))
        )
        result = compare_spark_heritage(candidate, replacement, self.protection)
        self.assertTrue(result["applied"])
        self.assertEqual(result["verdict_floor"], "likely_keep")
        self.assertIn("protected_direct_future_gp_spark", result["reason_codes"])

    def test_package_quality_degradation_sets_review_without_changing_scores(self) -> None:
        shared_gp = member(
            whites=[("Nimble Navigator", 2), ("Ramp Up", 1), ("Uma Stan", 1)]
        )
        candidate = self.heritage(
            veteran(
                whites=[("Ramp Up", 2), ("Uma Stan", 2)],
                gp1=shared_gp,
            )
        )
        replacement = self.heritage(
            veteran(
                whites=[("Ramp Up", 1), ("Uma Stan", 1)],
                gp1=shared_gp,
            )
        )
        result = compare_spark_heritage(candidate, replacement, self.protection)
        self.assertTrue(result["applied"])
        self.assertEqual(result["verdict_floor"], "review")
        self.assertIn("protected_important_skill_set", result["reason_codes"])
        package = next(
            deficit for deficit in result["deficits"] if deficit["kind"] == "package"
        )
        self.assertEqual(package["key"], "general_backliner")
        self.assertEqual(set(package["degraded_skills"]), {"ramp_up", "uma_stan"})

    def test_zero_support_count_does_not_protect_a_contextually_useless_skill(self) -> None:
        catalog = {
            "white_skill_spark_groups": [
                {
                    "catalog_key": "rare_but_bad",
                    "spark_name": "Rare But Bad",
                    "direct_support_hint_card_count": 0,
                }
            ]
        }
        heritage = build_spark_heritage(
            veteran(whites=[("Rare But Bad", 3)]),
            {},
            catalog,
            {"rare_but_bad": {"weight": 0.05, "context": {"profile": "Test"}}},
            self.config,
        )
        self.assertEqual(
            heritage["skills"]["rare_but_bad"]["protection_signals"], []
        )

    def test_zero_support_count_protects_a_useful_skill(self) -> None:
        candidate = self.heritage(veteran(whites=[("Uma Stan", 2)]))
        replacement = self.heritage(veteran())

        result = compare_spark_heritage(candidate, replacement, self.protection)

        self.assertTrue(result["applied"])
        self.assertEqual(result["verdict_floor"], "review")
        self.assertIn("protected_hard_to_obtain_spark", result["reason_codes"])
        skill = next(
            deficit for deficit in result["deficits"] if deficit["kind"] == "skill"
        )
        self.assertEqual(
            skill["candidate"]["direct_support_hint_card_count"], 0
        )

    def test_support_hint_override_replaces_unknown_catalog_metadata(self) -> None:
        config = copy.deepcopy(self.config)
        config["transfer_helper"]["spark_protection"][
            "support_hint_count_overrides"
        ] = {"nimble_navigator": 0}
        heritage = build_spark_heritage(
            veteran(whites=[("Nimble Navigator", 2)]),
            {},
            {"white_skill_spark_groups": []},
            self.active,
            config,
        )
        nimble = heritage["skills"]["nimble_navigator"]
        self.assertEqual(nimble["direct_support_hint_card_count"], 0)
        self.assertEqual(
            nimble["support_hint_count_source"], "configuration_override"
        )
        self.assertIn(
            "protected_hard_to_obtain_spark",
            [signal["reason_code"] for signal in nimble["protection_signals"]],
        )

    def test_classification_keeps_dominator_but_applies_protection_floor(self) -> None:
        candidate_heritage = self.heritage(
            veteran(
                whites=[("Nimble Navigator", 3)],
                gp1=member(whites=[("Nimble Navigator", 2)]),
            )
        )
        replacement_heritage = self.heritage(
            veteran(gp1=member(whites=[("Nimble Navigator", 2)]))
        )

        def record(trained_id: int, heritage: dict) -> dict:
            return {
                "trained_chara_id": trained_id,
                "card_name": f"Card {trained_id}",
                "uma_name": "Test Uma",
                "sparks": {},
                "_spark_heritage": heritage,
                "_parent_profiles": [
                    {
                        "score": 70.0,
                        "percentile": 10.0,
                        "utility": 0.90,
                        "course_key": "course_a",
                    }
                ],
                "_grandparent_profiles": [],
            }

        records = [record(1, candidate_heritage), record(2, replacement_heritage)]
        relation = DominanceAccumulator(
            parent_sum_delta=4.0,
            parent_count=1,
            minimum_delta=4.0,
            maximum_delta=4.0,
        )
        classify_transfer_records(
            records,
            {(0, 1): relation},
            elite_utility_floor=0.92,
            competitive_utility_floor=0.82,
            competitive_score_floor=67.5,
            minimum_absolute_floor_ratio=0.80,
            minimum_competitive_contexts=3,
            minimum_distinct_profiles=2,
            dominance_mean_margin=1.0,
            spark_protection_config=self.protection,
        )
        self.assertEqual(records[0]["status"], "likely_keep")
        self.assertEqual(records[0]["dominated_by"]["trained_chara_id"], 2)
        self.assertTrue(records[0]["spark_protection"]["applied"])


if __name__ == "__main__":
    unittest.main()
