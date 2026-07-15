from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scoring_config import (
    ScoringConfigError,
    build_overrides,
    deep_merge,
    load_effective_scoring_config,
    materialize_effective_scoring_config,
    migrate_scoring_overrides,
    read_json_object,
    validate_scoring_config,
    validate_skill_priorities_config,
    write_json_object,
)
from uma_moe import MAX_FETCH_CANDIDATES, UmaMoeApiClient


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_SCORING = PROJECT_DIR / "default_parent_scoring.json"
DEFAULT_SKILL_PRIORITIES = PROJECT_DIR / "default_skill_priorities.json"


class ScoringConfigTests(unittest.TestCase):
    def test_default_profile_is_valid(self) -> None:
        default, overrides, effective = load_effective_scoring_config(DEFAULT_SCORING)
        self.assertEqual(overrides, {})
        self.assertEqual(default, effective)
        validate_scoring_config(effective)

    def test_default_parent_pair_weights_match_high_roll_profile(self) -> None:
        config = read_json_object(DEFAULT_SCORING)
        self.assertEqual(
            config["mode_weights"]["parent_pair"],
            {
                "distance_s": 0.29,
                "pink_other": 0.07,
                "white_skill": 0.35,
                "race_scenario": 0.04,
                "blue": 0.20,
                "unique": 0.05,
            },
        )

    def test_minimal_overrides_round_trip(self) -> None:
        default = read_json_object(DEFAULT_SCORING)
        current = deep_merge(
            default,
            {
                "blue_stat_weights_by_distance": {"long": {"Stamina": 2.5}},
                "aptitude_inheritance": {
                    "dimension_weights_by_mode": {"parent_pair": {"style": 0.2}}
                },
            },
        )
        overrides = build_overrides(default, current)
        self.assertEqual(overrides["blue_stat_weights_by_distance"]["long"]["Stamina"], 2.5)
        self.assertEqual(
            overrides["aptitude_inheritance"]["dimension_weights_by_mode"]["parent_pair"]["style"],
            0.2,
        )
        self.assertNotIn("mode_weights", overrides)

        with tempfile.TemporaryDirectory() as directory:
            override_path = Path(directory) / "overrides.json"
            effective_path = Path(directory) / "effective.json"
            write_json_object(override_path, overrides)
            materialize_effective_scoring_config(DEFAULT_SCORING, override_path, effective_path)
            reloaded = read_json_object(effective_path)
        self.assertEqual(reloaded, current)

    def test_transfer_helper_scope_is_validated(self) -> None:
        config = read_json_object(DEFAULT_SCORING)
        config["transfer_helper"]["upcoming_cm_limit"] = 2.5
        with self.assertRaises(ScoringConfigError):
            validate_scoring_config(config)

        config = read_json_object(DEFAULT_SCORING)
        config["transfer_helper"]["include_team_trials"] = "yes"
        with self.assertRaises(ScoringConfigError):
            validate_scoring_config(config)

    def test_negative_weight_is_rejected(self) -> None:
        default = read_json_object(DEFAULT_SCORING)
        invalid = deep_merge(
            default,
            {"aptitude_inheritance": {"dimension_weights_by_mode": {"parent_pair": {"distance": -1}}}},
        )
        with self.assertRaises(ScoringConfigError):
            validate_scoring_config(invalid)

    def test_probability_curve_is_bounded(self) -> None:
        config = read_json_object(DEFAULT_SCORING)
        config["aptitude_inheritance"]["distance"]["s_probability_curve"][-1][0] = 1.2
        with self.assertRaises(ScoringConfigError):
            validate_scoring_config(config)

        config = read_json_object(DEFAULT_SCORING)
        config["aptitude_inheritance"]["distance"]["s_probability_curve"][-1][1] = 120
        with self.assertRaises(ScoringConfigError):
            validate_scoring_config(config)

    def test_white_distinct_skill_curve_is_bounded(self) -> None:
        config = read_json_object(DEFAULT_SCORING)
        config["white_inheritance"]["distinct_skill_probability_curve"][-1][0] = 1.2
        with self.assertRaises(ScoringConfigError):
            validate_scoring_config(config)

        config = read_json_object(DEFAULT_SCORING)
        config["white_inheritance"]["distinct_skill_probability_curve"][-1][1] = 1.2
        with self.assertRaises(ScoringConfigError):
            validate_scoring_config(config)

    def test_blue_influence_requires_every_distance(self) -> None:
        config = read_json_object(DEFAULT_SCORING)
        del config["blue_score_influence_by_distance"]["mile"]
        with self.assertRaises(ScoringConfigError):
            validate_scoring_config(config)

    def test_legacy_parent_final_weights_are_migrated_to_both_parent_roles(self) -> None:
        default = read_json_object(DEFAULT_SCORING)
        migrated = migrate_scoring_overrides(
            default,
            {
                "mode_weights": {
                    "parent_final": {
                        "affinity": 0.10,
                        "pink": 0.40,
                        "white_skill": 0.50,
                    }
                }
            },
        )

        self.assertNotIn("parent_final", migrated["mode_weights"])
        self.assertNotIn("affinity", migrated["mode_weights"]["parent_branch"])
        self.assertEqual(migrated["mode_weights"]["parent_pair"]["white_skill"], 0.50)
        self.assertAlmostEqual(
            migrated["mode_weights"]["parent_branch"]["distance_s"]
            + migrated["mode_weights"]["parent_branch"]["pink_other"],
            0.40,
        )
        self.assertAlmostEqual(
            migrated["mode_weights"]["parent_pair"]["distance_s"]
            + migrated["mode_weights"]["parent_pair"]["pink_other"],
            0.40,
        )

    def test_v35_future_gp_probability_weights_migrate_back_to_single_pink(self) -> None:
        default = read_json_object(DEFAULT_SCORING)
        migrated = migrate_scoring_overrides(
            default,
            {
                "mode_weights": {
                    "future_grandparent": {
                        "distance_s": 0.14,
                        "pink_other": 0.11,
                        "white_skill": 0.20,
                    }
                },
                "aptitude_inheritance": {
                    "dimension_weights_by_mode": {
                        "future_grandparent": {
                            "distance": 0.55,
                            "surface": 0.27,
                            "style": 0.18,
                        }
                    },
                    "partial_scoring": {
                        "future_grandparent": {"full_star_reference": 3}
                    },
                },
            },
        )

        future = migrated["mode_weights"]["future_grandparent"]
        self.assertAlmostEqual(future["pink"], 0.25)
        self.assertEqual(future["white_skill"], 0.20)
        self.assertNotIn("distance_s", future)
        self.assertNotIn("pink_other", future)
        self.assertNotIn(
            "future_grandparent",
            migrated["aptitude_inheritance"]["dimension_weights_by_mode"],
        )
        self.assertNotIn(
            "future_grandparent",
            migrated["aptitude_inheritance"]["partial_scoring"],
        )

    def test_default_white_skill_priorities_are_valid(self) -> None:
        validate_skill_priorities_config(read_json_object(DEFAULT_SKILL_PRIORITIES))


class FakeUmaMoeClient(UmaMoeApiClient):
    def __init__(self) -> None:
        super().__init__("https://example.invalid/api")
        self.requested_pages: list[int] = []

    def search(self, *, filters=None, limit: int = 100, page: int = 0):  # type: ignore[override]
        self.requested_pages.append(page)
        items = [
            {"inheritance": {"inheritance_id": page * limit + index + 1}}
            for index in range(limit)
        ]
        return {"items": items, "total_pages": 100}, {
            "method": "GET",
            "path": "/api/v3/search",
            "page": page,
            "limit": limit,
        }


class UmaMoeFetchLimitTests(unittest.TestCase):
    def test_search_many_hard_caps_at_2000_candidates(self) -> None:
        client = FakeUmaMoeClient()
        payload, operation = client.search_many(desired_candidates=5000, page_size=100)
        self.assertEqual(len(payload["items"]), MAX_FETCH_CANDIDATES)
        self.assertEqual(operation["requested_candidates"], MAX_FETCH_CANDIDATES)
        self.assertEqual(len(client.requested_pages), 20)


if __name__ == "__main__":
    unittest.main()
