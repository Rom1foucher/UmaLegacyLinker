from __future__ import annotations

import unittest

from transfer_helper import (
    DominanceAccumulator,
    _factor_snapshot,
    _update_group_dominance_for_scores,
    classify_transfer_records,
    comparison_group_key,
)


class TransferHelperClassificationTests(unittest.TestCase):
    @staticmethod
    def record(
        trained_id: int,
        *,
        parent_score: float,
        gp_score: float,
        parent_percentile: float,
        gp_percentile: float,
    ) -> dict:
        return {
            "trained_chara_id": trained_id,
            "card_name": f"Card {trained_id}",
            "uma_name": "Test Uma",
            "_best_parent_score": parent_score,
            "_best_grandparent_score": gp_score,
            "_best_parent_percentile": parent_percentile,
            "_best_grandparent_percentile": gp_percentile,
            "_parent_profiles": [
                {"score": parent_score, "percentile": parent_percentile, "utility": min(1.0, parent_score / 75.0), "course_key": "course_a"},
                {"score": parent_score, "percentile": parent_percentile, "utility": min(1.0, parent_score / 75.0), "course_key": "course_b"},
                {"score": parent_score, "percentile": parent_percentile, "utility": min(1.0, parent_score / 75.0), "course_key": "course_a"},
            ],
            "_grandparent_profiles": [
                {"score": gp_score, "percentile": gp_percentile, "utility": min(1.0, gp_score / 75.0), "course_key": "course_a"},
                {"score": gp_score, "percentile": gp_percentile, "utility": min(1.0, gp_score / 75.0), "course_key": "course_b"},
                {"score": gp_score, "percentile": gp_percentile, "utility": min(1.0, gp_score / 75.0), "course_key": "course_a"},
            ],
        }

    def test_strictly_dominated_copy_is_safe_transfer(self) -> None:
        records = [
            self.record(1, parent_score=70, gp_score=72, parent_percentile=10, gp_percentile=12),
            self.record(2, parent_score=75, gp_score=77, parent_percentile=5, gp_percentile=6),
        ]
        relation = DominanceAccumulator(
            parent_no_worse=True,
            grandparent_no_worse=True,
            pair_support_no_worse=True,
            parent_sum_delta=8,
            grandparent_sum_delta=12,
            parent_count=4,
            grandparent_count=4,
            minimum_delta=0.5,
            maximum_delta=5.0,
        )
        reverse = DominanceAccumulator(
            parent_no_worse=False,
            grandparent_no_worse=False,
            pair_support_no_worse=False,
            parent_count=4,
            grandparent_count=4,
        )
        classify_transfer_records(
            records,
            {(0, 1): relation, (1, 0): reverse},
            elite_utility_floor=0.92,
            competitive_utility_floor=0.82,
            competitive_score_floor=67.5,
            minimum_absolute_floor_ratio=0.80,
            minimum_competitive_contexts=3,
            minimum_distinct_profiles=2,
            dominance_mean_margin=1.0,
        )
        self.assertEqual(records[0]["status"], "safe_transfer")
        self.assertEqual(records[0]["dominated_by"]["trained_chara_id"], 2)
        self.assertEqual(records[1]["status"], "keep")


    def test_dominance_chain_points_to_final_surviving_copy(self) -> None:
        records = [
            self.record(1, parent_score=60, gp_score=60, parent_percentile=30, gp_percentile=30),
            self.record(2, parent_score=70, gp_score=70, parent_percentile=15, gp_percentile=15),
            self.record(3, parent_score=80, gp_score=80, parent_percentile=5, gp_percentile=5),
        ]

        def relation(mean_delta: float, minimum_delta: float) -> DominanceAccumulator:
            return DominanceAccumulator(
                parent_no_worse=True,
                grandparent_no_worse=True,
                pair_support_no_worse=True,
                parent_sum_delta=mean_delta * 2,
                grandparent_sum_delta=mean_delta * 2,
                parent_count=2,
                grandparent_count=2,
                minimum_delta=minimum_delta,
                maximum_delta=mean_delta + 1,
            )

        classify_transfer_records(
            records,
            {
                (0, 1): relation(3.0, 0.5),
                (0, 2): relation(7.0, 2.0),
                (1, 2): relation(4.0, 1.0),
            },
            elite_utility_floor=0.92,
            competitive_utility_floor=0.82,
            competitive_score_floor=67.5,
            minimum_absolute_floor_ratio=0.80,
            minimum_competitive_contexts=3,
            minimum_distinct_profiles=2,
            dominance_mean_margin=1.0,
        )
        self.assertEqual(records[0]["dominated_by"]["trained_chara_id"], 3)
        self.assertEqual(records[0]["dominated_by"]["mean_score_lead"], 7.0)
        self.assertEqual(records[1]["dominated_by"]["trained_chara_id"], 3)
        self.assertEqual(records[2]["status"], "keep")

    def test_bad_parent_but_good_grandparent_is_kept(self) -> None:
        records = [
            self.record(1, parent_score=20, gp_score=82, parent_percentile=90, gp_percentile=4)
        ]
        classify_transfer_records(
            records,
            {},
            elite_utility_floor=0.92,
            competitive_utility_floor=0.82,
            competitive_score_floor=67.5,
            minimum_absolute_floor_ratio=0.80,
            minimum_competitive_contexts=3,
            minimum_distinct_profiles=2,
            dominance_mean_margin=1.0,
        )
        self.assertEqual(records[0]["status"], "keep")
        self.assertEqual(records[0]["reason_code"], "strong_grandparent_value")

    def test_low_ceiling_without_replacement_is_review_only(self) -> None:
        records = [
            self.record(1, parent_score=35, gp_score=42, parent_percentile=70, gp_percentile=65)
        ]
        classify_transfer_records(
            records,
            {},
            elite_utility_floor=0.92,
            competitive_utility_floor=0.82,
            competitive_score_floor=67.5,
            minimum_absolute_floor_ratio=0.80,
            minimum_competitive_contexts=3,
            minimum_distinct_profiles=2,
            dominance_mean_margin=1.0,
        )
        self.assertEqual(records[0]["status"], "review")
        self.assertIsNone(records[0]["dominated_by"])


class TransferHelperGlobalViabilityTests(unittest.TestCase):
    def test_non_viable_context_does_not_preserve_least_bad_copy(self) -> None:
        relations = {
            (0, 1): DominanceAccumulator(),
            (1, 0): DominanceAccumulator(),
        }

        # Copy 0 is better on Dirt, but both copies are globally poor there.
        parent_viable, gp_viable = _update_group_dominance_for_scores(
            [0, 1],
            relations,
            {0: 25.0, 1: 15.0},
            {0: 20.0, 1: 10.0},
            {0: {"utility": 0.55}, 1: {"utility": 0.35}},
            {0: {"utility": 0.45}, 1: {"utility": 0.25}},
            competitive_score_floor=65.0,
            competitive_utility_floor=0.82,
            minimum_absolute_floor_ratio=0.80,
            dominance_tolerance=0.25,
        )
        self.assertFalse(parent_viable)
        self.assertFalse(gp_viable)
        self.assertEqual(relations[(0, 1)].combined_count, 0)
        self.assertEqual(relations[(1, 0)].combined_count, 0)

        # Copy 1 is clearly better in an actually viable Turf niche. Only this
        # context must decide dominance.
        parent_viable, gp_viable = _update_group_dominance_for_scores(
            [0, 1],
            relations,
            {0: 68.0, 1: 76.0},
            {0: 66.0, 1: 74.0},
            {0: {"utility": 0.84}, 1: {"utility": 0.95}},
            {0: {"utility": 0.83}, 1: {"utility": 0.93}},
            competitive_score_floor=65.0,
            competitive_utility_floor=0.82,
            minimum_absolute_floor_ratio=0.80,
            dominance_tolerance=0.25,
        )
        self.assertTrue(parent_viable)
        self.assertTrue(gp_viable)
        self.assertTrue(relations[(0, 1)].parent_no_worse)
        self.assertTrue(relations[(0, 1)].grandparent_no_worse)
        self.assertEqual(relations[(0, 1)].parent_count, 1)
        self.assertEqual(relations[(0, 1)].grandparent_count, 1)
        self.assertAlmostEqual(relations[(0, 1)].mean_delta, 8.0)

    def test_dominance_can_be_proven_in_only_one_viable_role(self) -> None:
        records = [
            TransferHelperClassificationTests.record(
                1, parent_score=25, gp_score=70, parent_percentile=80, gp_percentile=10
            ),
            TransferHelperClassificationTests.record(
                2, parent_score=30, gp_score=78, parent_percentile=75, gp_percentile=4
            ),
        ]
        relation = DominanceAccumulator(
            parent_no_worse=True,
            grandparent_no_worse=True,
            pair_support_no_worse=True,
            grandparent_sum_delta=8.0,
            grandparent_count=1,
            minimum_delta=8.0,
            maximum_delta=8.0,
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
        )
        self.assertEqual(records[0]["status"], "safe_transfer")
        self.assertEqual(records[0]["dominated_by"]["trained_chara_id"], 2)


    def test_single_narrow_niche_is_only_likely_keep(self) -> None:
        record = TransferHelperClassificationTests.record(1, parent_score=68, gp_score=40, parent_percentile=12, gp_percentile=80)
        record["_parent_profiles"] = [
            {"score": 68, "percentile": 12, "utility": 0.84, "course_key": "course_a"},
            {"score": 40, "percentile": 60, "utility": 0.55, "course_key": "course_b"},
        ]
        record["_grandparent_profiles"] = []
        classify_transfer_records(
            [record],
            {},
            elite_utility_floor=0.92,
            competitive_utility_floor=0.82,
            competitive_score_floor=67.5,
            minimum_absolute_floor_ratio=0.80,
            minimum_competitive_contexts=3,
            minimum_distinct_profiles=2,
            dominance_mean_margin=1.0,
        )
        self.assertEqual(record["status"], "likely_keep")





class TransferHelperSparkSnapshotTests(unittest.TestCase):
    def test_factor_snapshot_keeps_type_name_and_stars(self) -> None:
        snapshot = _factor_snapshot(
            {
                "factors": {
                    "all": [
                        {"type": "white_skill", "name": "Corner Adept", "stars": 2},
                        {"type": "blue_stat", "name": "Speed", "stars": 3},
                    ]
                }
            }
        )
        self.assertEqual(snapshot["all"][0]["name"], "Speed")
        self.assertEqual(snapshot["all"][1]["name"], "Corner Adept")
        self.assertIn("Blue: Speed 3★", snapshot["summary"])
        self.assertIn("White skill: Corner Adept 2★", snapshot["summary"])

class TransferHelperGroupingTests(unittest.TestCase):
    def test_alternate_costumes_are_not_interchangeable(self) -> None:
        base = {
            "chara_id": 101,
            "factors": {
                "by_type": {
                    "unique": [
                        {
                            "factor_group_id": 9001,
                            "name": "Inherited Unique",
                            "stars": 2,
                        }
                    ]
                }
            },
        }
        first = {**base, "card_id": 100101}
        second = {**base, "card_id": 100102}
        self.assertNotEqual(comparison_group_key(first), comparison_group_key(second))

    def test_same_card_ignores_unique_star_level(self) -> None:
        first = {
            "card_id": 100101,
            "chara_id": 101,
            "factors": {
                "by_type": {
                    "unique": [
                        {"factor_group_id": 9001, "name": "Unique", "stars": 1}
                    ]
                }
            },
        }
        second = {
            "card_id": 100101,
            "chara_id": 101,
            "factors": {
                "by_type": {
                    "unique": [
                        {"factor_group_id": 9001, "name": "Unique", "stars": 3}
                    ]
                }
            },
        }
        self.assertEqual(comparison_group_key(first), comparison_group_key(second))


if __name__ == "__main__":
    unittest.main()


def test_static_condition_comparison_accepts_scalar_preset_values():
    from parent_optimizer import _compare_condition, _static_condition_state

    assert _compare_condition(1, "==", 1)
    assert _compare_condition(2, ">=", 1)
    assert not _compare_condition(0, "==", 1)

    activations = [[[[{
        "variable": "rotation",
        "operator": "==",
        "value": 1,
    }]]]]
    assert _static_condition_state(activations, {"rotation": 1}) == "matched"
    assert _static_condition_state(activations, {"rotation": 2}) == "mismatched"
