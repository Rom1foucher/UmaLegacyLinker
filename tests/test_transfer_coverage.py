from __future__ import annotations

import unittest
from itertools import combinations

from uma_legacy_linker.transfer_coverage import build_transfer_reason


def _record(
    trained_id: int,
    score: int,
    *,
    status: str = "keep",
    profiles: dict[str, dict[str, float]] | None = None,
) -> dict:
    row = {
        "trained_chara_id": trained_id,
        "rank_score": score,
        "uma_name": "Opera O",
        "card_name": "Opera O - Costume",
        "comparison_group": "costume:1",
        "status": status,
        "_parent_profiles": [],
        "_grandparent_profiles": [],
    }
    for role, entries in (profiles or {}).items():
        row[f"_{role}_profiles"] = [
            {"context_key": key, "score": value, "profile": key}
            for key, value in entries.items()
        ]
    return row


class TransferCoverageTests(unittest.TestCase):
    def test_recommended_reason_uses_a_deterministic_minimum_cover(self) -> None:
        records = [
            _record(1, 9000, status="recommended_transfer", profiles={
                "parent": {"a": 90.0, "b": 80.0, "c": 70.0},
            }),
            _record(2, 12000, profiles={"parent": {"a": 89.0, "b": 79.0}}),
            _record(3, 11000, profiles={"parent": {"c": 69.5}}),
            _record(4, 10500, profiles={"parent": {"a": 88.0, "b": 78.0, "c": 68.0}}),
        ]
        requirements = {
            "identity": {"kind": "identity", "covered_by": {0, 1, 2, 3}},
            "a": {"kind": "performance", "role": "parent", "context_key": "a", "label": "parent A", "covered_by": {0, 1}},
            "b": {"kind": "performance", "role": "parent", "context_key": "b", "label": "parent B", "covered_by": {0, 1}},
            "c": {"kind": "performance", "role": "parent", "context_key": "c", "label": "parent C", "covered_by": {0, 2}},
        }

        first = build_transfer_reason(0, [0, 1, 2, 3], {1, 2, 3}, requirements, records)
        second = build_transfer_reason(0, [0, 1, 2, 3], {1, 2, 3}, requirements, records)

        self.assertEqual(first, second)
        self.assertEqual(first["code"], "covered_by")
        self.assertEqual(
            [reference["trained_chara_id"] for reference in first["refs"]],
            [2, 3],
        )
        self.assertEqual(len(first["refs"]), 2)
        self.assertTrue(
            all(records[index]["comparison_group"] == "costume:1" for index in (1, 2))
        )
        covered = set()
        for reference in first["refs"]:
            index = next(
                index for index, row in enumerate(records)
                if row["trained_chara_id"] == reference["trained_chara_id"]
            )
            covered.update(
                key for key, requirement in requirements.items()
                if key != "identity" and index in requirement["covered_by"]
            )
        self.assertEqual(covered, {"a", "b", "c"})
        eligible = {1, 2, 3}
        minimum_size = min(
            len(subset)
            for size in range(1, len(eligible) + 1)
            for subset in combinations(eligible, size)
            if all(
                set(subset) & set(requirement["covered_by"])
                for key, requirement in requirements.items()
                if key != "identity"
            )
        )
        self.assertEqual(len(first["refs"]), minimum_size)

    def test_minimum_cover_prefers_one_copy_that_covers_every_requirement(self) -> None:
        records = [
            _record(1, 9000, status="recommended_transfer"),
            _record(2, 15000),
            _record(3, 14000),
            _record(4, 13000),
        ]
        requirements = {
            "identity": {"kind": "identity", "covered_by": {0, 1, 2, 3}},
            "a": {"kind": "performance", "covered_by": {0, 1, 3}},
            "b": {"kind": "performance", "covered_by": {0, 2, 3}},
        }

        reason = build_transfer_reason(0, [0, 1, 2, 3], {1, 2, 3}, requirements, records)

        self.assertEqual(reason["code"], "covered_by")
        self.assertEqual(
            [reference["trained_chara_id"] for reference in reason["refs"]],
            [4],
        )

    def test_strict_transfer_cites_its_exact_dominator_and_worst_gap(self) -> None:
        records = [
            _record(1, 9000, status="safe_transfer"),
            _record(2, 12000),
        ]
        records[0]["dominated_by"] = {
            "trained_chara_id": 2,
            "rank_score": 12000,
            "uma_name": "Opera O",
            "card_name": "Opera O - Costume",
            "context_deltas": [
                {
                    "role": "parent",
                    "context_key": "turf-mile",
                    "profile": "Parent Turf Mile",
                    "candidate_score": 80.0,
                    "replacement_score": 80.8,
                },
                {
                    "role": "grandparent",
                    "context_key": "turf-long",
                    "profile": "Grandparent Turf Long",
                    "candidate_score": 81.0,
                    "replacement_score": 81.2,
                },
            ],
        }

        reason = build_transfer_reason(0, [0, 1], {1}, {}, records)

        self.assertEqual(reason["code"], "replaced_by")
        self.assertEqual(reason["refs"][0]["trained_chara_id"], 2)
        self.assertAlmostEqual(reason["worst_gap"], -0.8)
        self.assertEqual(reason["gap_role"]["profile"], "Parent Turf Mile")

    def test_kept_reason_prioritizes_assets_then_roles_then_last_copy(self) -> None:
        records = [
            _record(1, 12000, profiles={
                "parent": {"mile": 95.0},
                "grandparent": {"long": 98.0},
            }),
            _record(2, 11000, profiles={
                "parent": {"mile": 94.0},
                "grandparent": {"long": 80.0},
            }),
        ]
        records[0]["portfolio_required_for"] = [
            {"kind": "performance", "role": "parent", "context_key": "mile", "label": "parent Turf Mile", "best_score": 95.0},
            {"kind": "performance", "role": "grandparent", "context_key": "long", "label": "grandparent Turf Long", "best_score": 98.0},
        ]
        requirements = {
            "mile": {"kind": "performance", "role": "parent", "context_key": "mile", "label": "parent Turf Mile", "best_score": 95.0, "covered_by": {0}},
            "long": {"kind": "performance", "role": "grandparent", "context_key": "long", "label": "grandparent Turf Long", "best_score": 98.0, "covered_by": {0}},
        }

        role_reason = build_transfer_reason(0, [0, 1], {0, 1}, requirements, records)
        self.assertEqual(role_reason["code"], "holds_role")
        self.assertEqual(role_reason["subject"], "grandparent Turf Long")
        self.assertEqual(role_reason["more"], 1)
        self.assertAlmostEqual(role_reason["worst_gap"], -18.0)

        records[0]["portfolio_required_for"].insert(
            0,
            {"kind": "protected_skill", "label": "Straight Descent"},
        )
        asset_reason = build_transfer_reason(0, [0, 1], {0, 1}, requirements, records)
        self.assertEqual(asset_reason["code"], "carries_asset")
        self.assertEqual(asset_reason["subject"], "Straight Descent")

        only_copy = _record(9, 5000, status="keep")
        last_copy_reason = build_transfer_reason(
            0,
            [0],
            {0},
            {"identity": {"kind": "identity", "covered_by": {0}}},
            [only_copy],
        )
        self.assertEqual(last_copy_reason["code"], "last_copy")

    def test_kept_reason_exposes_preset_and_floor_evidence(self) -> None:
        kept = _record(7, 13000)
        kept["portfolio_required_for"] = [
            {
                "kind": "loop_preset", "label": "Boucle Late 11/15",
                "preset_key": "late", "package_score": 11, "package_max": 15,
                "was_previously_selected": False,
            },
            {
                "kind": "loop_floor", "label": "Seule source Uma Stan (3/3)",
                "skill_key": "uma_stan", "loop_presence_count": 3,
                "best_presence_count": 3, "sole_source": True,
                "was_previously_selected": False,
            },
        ]

        reason = build_transfer_reason(0, [0], {0}, {}, [kept])

        self.assertEqual(reason["code"], "loop_carrier")
        self.assertEqual(reason["loop_packages"][0]["score"], 11)
        self.assertEqual(reason["loop_packages"][0]["preset"], "late")
        self.assertTrue(reason["loop_floors"][0]["sole_source"])

    def test_protected_reason_keeps_model_diagnosis(self) -> None:
        protected = _record(1, 10000, status="protected")
        protected["manual_protection_reasons"] = ["memo_present"]
        protected["analysis_status"] = "recommended_transfer"
        protected["analysis_reason_code"] = "redundant_in_collection_portfolio"
        reason = build_transfer_reason(0, [0], set(), {}, [protected])
        self.assertEqual(reason["code"], "protected")
        self.assertEqual(reason["model_status"], "recommended_transfer")
        self.assertEqual(reason["model_reason"], "redundant_in_collection_portfolio")

    def test_kept_role_gap_uses_the_same_ace_variant(self) -> None:
        records = [
            _record(1, 12000),
            _record(2, 11000),
        ]
        records[0]["_parent_profiles"] = [{
            "context_key": "mile", "score": 50.0, "ace_scores": [100.0, 95.0],
        }]
        records[1]["_parent_profiles"] = [{
            "context_key": "mile", "score": 50.0, "ace_scores": [98.0, 90.0],
        }]
        requirements = {
            "ace-a": {"kind": "performance", "role": "parent", "context_key": "mile",
                      "ace_index": 0, "best_score": 100.0, "label": "parent: Turf Mile",
                      "covered_by": {0, 1}},
            "ace-b": {"kind": "performance", "role": "parent", "context_key": "mile",
                      "ace_index": 1, "best_score": 95.0, "label": "parent: Turf Mile",
                      "covered_by": {0}},
        }
        reason = build_transfer_reason(0, [0, 1], {0, 1}, requirements, records)
        self.assertEqual(reason["code"], "holds_role")
        self.assertEqual(reason["subject"], "Turf Mile")
        self.assertAlmostEqual(reason["worst_gap"], -5.0)
        self.assertEqual(reason["gap_count"], 1)

    def test_locked_and_uncertain_copies_are_never_marked_for_transfer(self) -> None:
        protected = _record(1, 10000, status="protected")
        protected["manual_protection_reasons"] = ["locked_in_game", "memo_present"]
        reason = build_transfer_reason(0, [0], {0}, {}, [protected])
        self.assertEqual(reason["code"], "protected")
        self.assertEqual(reason["subject"], "locked_in_game")
        self.assertEqual(reason["model_reasons"], ["locked_in_game", "memo_present"])

        review = _record(2, 9000, status="review", profiles={})
        review["reason_code"] = "portfolio_coverage_incomplete"
        reason = build_transfer_reason(0, [0], set(), {}, [review])
        self.assertEqual(reason["code"], "insufficient")

        outclassed = _record(3, 8000, status="recommended_transfer")
        reason = build_transfer_reason(
            0,
            [0],
            set(),
            {"identity": {"kind": "identity", "covered_by": {0}}},
            [outclassed],
        )
        self.assertEqual(reason["code"], "outclassed")

        outclassed["_parent_profiles"] = [
            {"context_key": "mile", "score": 50.0, "profile": "mile"}
        ]
        reason = build_transfer_reason(
            0,
            [0, 1],
            {1},
            {
                "identity": {"kind": "identity", "covered_by": {0, 1}},
                "mile": {
                    "kind": "performance",
                    "role": "parent",
                    "context_key": "mile",
                    "label": "parent Turf Mile",
                    "best_score": 55.0,
                    "covered_by": {1},
                },
            },
            [outclassed, _record(4, 11000)],
        )
        self.assertEqual(reason["code"], "outclassed")
        self.assertEqual(reason["closest_top_gap"], 5.0)
        self.assertEqual(reason["gap_role"]["profile"], "parent Turf Mile")


if __name__ == "__main__":
    unittest.main()
