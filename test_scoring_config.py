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
from uma_moe import (
    MAX_FETCH_CANDIDATES,
    UmaMoeApiClient,
    _select_diverse_parent_branch_pool,
    _future_gp_pair_g1_score,
    _future_gp_preselection_weights,
    _future_gp_scoring_weights,
    build_parent_retrieval_plan,
)


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_SCORING = PROJECT_DIR / "default_parent_scoring.json"
DEFAULT_SKILL_PRIORITIES = PROJECT_DIR / "default_skill_priorities.json"


class ScoringConfigTests(unittest.TestCase):
    def test_default_profile_is_valid(self) -> None:
        default, overrides, effective = load_effective_scoring_config(DEFAULT_SCORING)
        self.assertEqual(overrides, {})
        self.assertEqual(default, effective)
        validate_scoring_config(effective)

    def test_surface_cohort_toggle_is_a_boolean_setting(self) -> None:
        config = read_json_object(DEFAULT_SCORING)
        config["uma_moe_parent_search"]["retrieval"]["surface_cohort_enabled"] = False
        validate_scoring_config(config)

        config["uma_moe_parent_search"]["retrieval"]["surface_cohort_enabled"] = 0
        with self.assertRaises(ScoringConfigError):
            validate_scoring_config(config)

    def test_default_parent_pair_weights_match_high_roll_profile(self) -> None:
        config = read_json_object(DEFAULT_SCORING)
        self.assertEqual(
            config["mode_weights"]["parent_pair"],
            {
                "distance_s": 0.29,
                "surface_aptitude": 0.05,
                "pink_other": 0.02,
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
            + migrated["mode_weights"]["parent_branch"]["surface_aptitude"]
            + migrated["mode_weights"]["parent_branch"]["pink_other"],
            0.40,
        )
        self.assertAlmostEqual(
            migrated["mode_weights"]["parent_pair"]["distance_s"]
            + migrated["mode_weights"]["parent_pair"]["surface_aptitude"]
            + migrated["mode_weights"]["parent_pair"]["pink_other"],
            0.40,
        )

    def test_pre_v17_other_pink_override_is_split_without_changing_its_total(self) -> None:
        default = read_json_object(DEFAULT_SCORING)
        migrated = migrate_scoring_overrides(
            default,
            {
                "schema_version": 16,
                "mode_weights": {
                    "parent_pair": {"pink_other": 0.14},
                    "parent_branch": {"pink_other": 0.20},
                },
            },
        )

        pair = migrated["mode_weights"]["parent_pair"]
        branch = migrated["mode_weights"]["parent_branch"]
        self.assertAlmostEqual(pair["surface_aptitude"] + pair["pink_other"], 0.14)
        self.assertAlmostEqual(branch["surface_aptitude"] + branch["pink_other"], 0.20)

    def test_surface_rank_policy_is_validated(self) -> None:
        config = read_json_object(DEFAULT_SCORING)
        config["aptitude_inheritance"]["surface"]["minimum_initial_rank"] = 7
        config["aptitude_inheritance"]["surface"]["preferred_initial_rank"] = 6
        with self.assertRaises(ScoringConfigError):
            validate_scoring_config(config)

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

    def test_future_gp_weights_are_the_online_single_source_of_truth(self) -> None:
        config = read_json_object(DEFAULT_SCORING)
        config["mode_weights"]["future_grandparent"] = {
            "affinity": 0.12,
            "g1_potential": 0.09,
            "blue": 0.25,
            "pink": 0.20,
            "white_skill": 0.18,
            "white_generation": 0.15,
            "unique": 0.01,
        }
        self.assertEqual(
            _future_gp_scoring_weights(config),
            config["mode_weights"]["future_grandparent"],
        )
        self.assertEqual(
            _future_gp_preselection_weights(config),
            {
                "candidate_affinity": 0.12,
                "g1_potential": 0.09,
                "blue": 0.25,
                "pink": 0.20,
                "white_skill": 0.18,
                "white_generation": 0.15,
                "unique": 0.01,
            },
        )

    def test_legacy_online_gp_weights_are_migrated_and_removed(self) -> None:
        default = read_json_object(DEFAULT_SCORING)
        migrated = migrate_scoring_overrides(
            default,
            {
                "uma_moe_pair": {
                    "weights": {
                        "final_parent_affinity": 0.22,
                        "production_run_affinity": 0.04,
                        "pink": 0.24,
                        "white_skill": 0.26,
                        "white_generation": 0.18,
                        "blue": 0.06,
                    },
                    "preselection_weights": {"blue": 0.50},
                }
            },
        )
        self.assertNotIn("weights", migrated["uma_moe_pair"])
        self.assertNotIn("preselection_weights", migrated["uma_moe_pair"])
        future = migrated["mode_weights"]["future_grandparent"]
        self.assertEqual(future["affinity"], 0.22)
        self.assertEqual(future["g1_potential"], 0.04)
        self.assertEqual(future["blue"], 0.06)

    def test_online_gp_g1_score_is_normalized_against_the_planned_budget(self) -> None:
        self.assertEqual(
            _future_gp_pair_g1_score(
                {
                    "planned_g1_budget": 15,
                    "g1_bonus_per_link": 3,
                    "planned_g1_bonus": 90,
                }
            ),
            100.0,
        )
        self.assertEqual(
            _future_gp_pair_g1_score(
                {
                    "planned_g1_budget": 15,
                    "g1_bonus_per_link": 3,
                    "planned_g1_bonus": 45,
                }
            ),
            50.0,
        )

    def test_default_online_pair_section_has_no_independent_weights(self) -> None:
        config = read_json_object(DEFAULT_SCORING)
        self.assertNotIn("weights", config["uma_moe_pair"])
        self.assertNotIn("preselection_weights", config["uma_moe_pair"])

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

    def test_planned_parent_search_shares_the_same_global_2000_cap(self) -> None:
        class PlannedClient(UmaMoeApiClient):
            def __init__(self) -> None:
                super().__init__("https://example.invalid/api")
                self.budgets: list[int] = []

            def search_many(  # type: ignore[override]
                self, *, filters=None, desired_candidates=250, page_size=100, logger=None
            ):
                budget = int(desired_candidates)
                self.budgets.append(budget)
                marker = len(self.budgets) * 10000
                items = [
                    {"inheritance": {"inheritance_id": marker + index}}
                    for index in range(budget)
                ]
                return {"items": items}, {
                    "method": "GET",
                    "path": "/api/v3/search",
                    "requested_candidates": budget,
                    "filters": filters or {},
                }

        client = PlannedClient()
        plan = {
            "enabled": True,
            "cohorts": [
                {"name": "distance", "kind": "distance", "share": 0.45, "filters": {"pink_sparks": [3201]}},
                {"name": "surface", "kind": "surface", "share": 0.40, "filters": {"pink_sparks": [1105]}},
                {"name": "broad", "kind": "broad", "share": 0.15, "filters": {}},
            ],
        }
        payload, operation = client.search_many_planned(
            retrieval_plan=plan,
            desired_candidates=5000,
            page_size=100,
        )

        self.assertEqual(client.budgets, [900, 800, 300])
        self.assertEqual(sum(client.budgets), MAX_FETCH_CANDIDATES)
        self.assertEqual(len(payload["items"]), MAX_FETCH_CANDIDATES)
        self.assertTrue(operation["retrieval_plan_applied"])

    def test_parent_retrieval_plan_targets_balanced_turf_f_branches(self) -> None:
        config = read_json_object(DEFAULT_SCORING)
        plan = build_parent_retrieval_plan(
            ace_target_aptitudes={
                "surface": {"rank": 2, "label": "F"},
                "distance": {"rank": 7, "label": "A"},
            },
            surface="turf",
            distance="mile",
            config=config,
            pink_group_ids={"Turf": 110, "Mile": 320},
        )

        cohorts = {row["kind"]: row for row in plan["cohorts"]}
        self.assertEqual(plan["surface"]["final_pair_star_target"], 10)
        self.assertEqual(plan["surface"]["balanced_remote_branch_minimum"], 5)
        self.assertEqual(cohorts["surface"]["filters"]["pink_sparks"], [1105, 1106, 1107, 1108, 1109])
        self.assertEqual(cohorts["distance"]["filters"]["pink_sparks"][0], 3201)
        self.assertAlmostEqual(cohorts["distance"]["share"], 0.45)
        self.assertAlmostEqual(cohorts["surface"]["share"], 0.40)
        self.assertAlmostEqual(cohorts["broad"]["share"], 0.15)

    def test_diverse_branch_pool_keeps_surface_rich_candidates(self) -> None:
        config = read_json_object(DEFAULT_SCORING)
        rows = []
        for index in range(100):
            surface_stars = index // 10
            rows.append({
                "veteran": {"trained_chara_id": index + 1},
                "score": 100.0 - index,
                "affinity": {"total": 100 - index},
                "components": {"distance_s": 50, "surface_aptitude": surface_stars * 5},
                "distance_s_summary": {"total_stars": 1, "probability_any_proc": 0.1},
                "surface_aptitude_summary": {
                    "total_stars": surface_stars,
                    "probability_any_proc": surface_stars / 10,
                },
            })
        selected, diagnostics = _select_diverse_parent_branch_pool(
            rows,
            pool_size=10,
            ace_target_aptitudes={"surface": {"rank": 2}},
            config=config,
        )

        self.assertEqual(len(selected), 10)
        self.assertEqual(diagnostics["quotas"]["surface"], 4)
        self.assertGreaterEqual(
            max(row["surface_aptitude_summary"]["total_stars"] for row in selected),
            9,
        )


if __name__ == "__main__":
    unittest.main()
