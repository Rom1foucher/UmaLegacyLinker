from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from parent_optimizer import lineage_preview_for_pair
from ui_qt.asset_catalog import (
    image_cache_path,
    is_allowed_image_url,
    skill_icon_url,
    support_card_image_url,
    trainee_image_url,
)
from ui_qt.lineage_nodes import (
    build_pair_lineage_nodes,
    build_result_lineage_nodes,
    spark_badge_totals,
)


def member(card_id: int, name: str, *, blue: int = 0, pink: int = 0) -> dict:
    factors = []
    if blue:
        factors.append({"name": "Speed", "stars": blue, "type": "blue_stat"})
    if pink:
        factors.append({"name": "Medium", "stars": pink, "type": "red_aptitude"})
    return {
        "trained_chara_id": card_id + 10_000,
        "card_id": card_id,
        "chara_id": card_id // 100,
        "uma_name": name,
        "card_name": f"{name} — Costume",
        "factors": {"all": factors},
        "g1_wins": {"names": ["Race A"]},
        "when_used_as_parent": {},
    }


class VisualAssetTests(unittest.TestCase):
    def test_known_gametora_asset_urls_are_costume_aware(self) -> None:
        self.assertEqual(
            trainee_image_url(103101),
            "https://gametora.com/images/umamusume/characters/chara_stand_1031_103101.png",
        )
        self.assertEqual(
            support_card_image_url(30306),
            "https://media.gametora.com/umamusume/supports/full/small/30306.png",
        )
        self.assertEqual(
            skill_icon_url(10011),
            "https://media.gametora.com/umamusume/skills/icon/10011.png",
        )

    def test_remote_image_allowlist_rejects_non_https_and_lookalikes(self) -> None:
        self.assertTrue(is_allowed_image_url(str(trainee_image_url(100701))))
        self.assertTrue(is_allowed_image_url(str(support_card_image_url(10028))))
        self.assertFalse(is_allowed_image_url("http://gametora.com/image.png"))
        self.assertFalse(is_allowed_image_url("https://gametora.com.example/image.png"))
        self.assertFalse(is_allowed_image_url("https://example.com/image.png"))

    def test_cache_names_are_opaque_stable_and_confined(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = image_cache_path(root, "https://gametora.com/a.png?x=1")
            second = image_cache_path(root, "https://gametora.com/a.png?x=1")
            different = image_cache_path(root, "https://gametora.com/a.png?x=2")
            self.assertEqual(first, second)
            self.assertNotEqual(first, different)
            self.assertEqual(first.parent, root)
            self.assertEqual(first.suffix, ".img")

    def test_pair_snapshot_keeps_six_visible_members_without_full_veterans(self) -> None:
        p1 = member(101001, "Parent One", blue=3)
        p2 = member(102001, "Parent Two", pink=2)
        p1["when_used_as_parent"] = {
            "grandparent_1": member(103001, "Left A", blue=2),
            "grandparent_2": member(104001, "Left B", pink=1),
        }
        p2["when_used_as_parent"] = {
            "grandparent_1": member(105001, "Right A", blue=1),
            "grandparent_2": member(106001, "Right B", pink=3),
        }
        preview = lineage_preview_for_pair(p1, p2)
        self.assertEqual(
            set(preview),
            {"p1", "p2", "p1-1", "p1-2", "p2-1", "p2-2"},
        )
        self.assertNotIn("when_used_as_parent", preview["p1"])
        self.assertEqual(preview["p1"]["spark_totals"]["blue_stat"]["stars"], 3)

        nodes = build_pair_lineage_nodes(
            {"card_id": 100701, "uma_name": "Ace", "card_name": "Ace Costume"},
            {
                "parent_1": {"card_name": p1["card_name"]},
                "parent_2": {"card_name": p2["card_name"]},
                "lineage_preview": preview,
            },
        )
        self.assertEqual(len(nodes), 7)
        self.assertEqual(nodes["p2-2"]["card_id"], 106001)
        self.assertEqual(spark_badge_totals(nodes["p2-2"]), (0, 3, 0))

    def test_older_pair_rows_degrade_to_named_placeholders(self) -> None:
        nodes = build_pair_lineage_nodes(
            {"card_id": 100701, "card_name": "Ace"},
            {
                "parent_1": {
                    "card_id": 101001,
                    "card_name": "Parent 1",
                    "grandparent_1": "Old GP 1",
                    "grandparent_2": "Old GP 2",
                },
                "parent_2": {"card_id": 102001, "card_name": "Parent 2"},
            },
        )
        self.assertEqual(nodes["p1-1"]["card_name"], "Old GP 1")
        self.assertIsNone(nodes["p1-2"].get("card_id"))
        self.assertNotIn("p2-1", nodes)

    def test_branch_and_grandparent_results_use_the_correct_visual_root(self) -> None:
        single_preview = lineage_preview_for_pair(
            member(101001, "Candidate Parent", blue=3),
            {},
        )
        self.assertIn("p1", single_preview)
        self.assertNotIn("p2", single_preview)

        branch_preview = {
            "p1": {
                "card_name": "Candidate Parent",
                "sparks": [{"name": "Speed", "stars": 3, "type": "blue_stat"}],
            },
            "p1-1": {"card_name": "Branch GP 1", "sparks": []},
            "p1-2": {"card_name": "Branch GP 2", "sparks": []},
        }
        branch_nodes = build_result_lineage_nodes(
            {"card_name": "Target Ace"},
            {"card_name": "Candidate Parent", "lineage_preview": branch_preview},
            "branch",
        )
        self.assertEqual(branch_nodes["target"]["card_name"], "Target Ace")
        self.assertEqual(branch_nodes["p1"]["card_name"], "Candidate Parent")
        self.assertNotIn("p2", branch_nodes)

        gp_preview = {
            "p1": {"card_name": "Local GP", "sparks": []},
            "p2": {"card_name": "Remote GP", "sparks": []},
            "p1-1": {"card_name": "Local GP parent", "sparks": []},
            "p2-1": {"card_name": "Remote GP parent", "sparks": []},
        }
        gp_nodes = build_result_lineage_nodes(
            {"card_name": "Parent To Produce"},
            {
                "fixed_grandparent": {"card_name": "Local GP"},
                "candidate": {"card_name": "Remote GP"},
                "lineage_preview": gp_preview,
            },
            "online_grandparent",
        )
        self.assertEqual(gp_nodes["target"]["card_name"], "Parent To Produce")
        self.assertEqual(gp_nodes["p1"]["card_name"], "Local GP")
        self.assertEqual(gp_nodes["p2"]["card_name"], "Remote GP")
        self.assertEqual(gp_nodes["p2-1"]["card_name"], "Remote GP parent")

    def test_white_run_odds_and_score_priority_reach_the_visual_model(self) -> None:
        p1 = member(101001, "Parent One", pink=2)
        p2 = member(102001, "Parent Two")
        p1["factors"]["all"].append(
            {
                "factor_id": 771,
                "factor_group_id": 77,
                "name": "Corner Adept",
                "stars": 2,
                "type": "white_skill",
            }
        )
        preview = lineage_preview_for_pair(
            p1,
            p2,
            {
                "white_skill_spark_groups": [
                    {"factor_group_id": 77, "inherit_skill_id": 10011}
                ]
            },
        )
        row = {
            "parent_1": {"card_name": p1["card_name"]},
            "parent_2": {"card_name": p2["card_name"]},
            "lineage_preview": preview,
            "affinity": {
                "inheritance_affinities": {"values": {"parent_1": 120.0}}
            },
            "component_details": {
                "pink": {
                    "factors": [
                        {
                            "role": "parent_1",
                            "name": "Medium",
                            "stars": 2,
                            "proc_probability_per_event": 0.066,
                            "proc_probability_over_run": 0.127644,
                        }
                    ]
                },
                "white_skill": {
                    "inspiration_event_count": 2,
                    "top_skills": [
                        {
                            "name": "Corner Adept",
                            "catalog_key": "corner_adept",
                            "profile_weight": 0.8,
                            "contribution": 0.42,
                        }
                    ],
                    "top_factors": [
                        {
                            "role": "parent_1",
                            "source_type": "white_skill",
                            "source_factor_name": "Corner Adept",
                            "name": "Corner Adept",
                            "catalog_key": "corner_adept",
                            "stars": 2,
                            "proc_probability_per_event": 0.132,
                            "proc_probability_over_run": 0.246576,
                        }
                    ]
                },
            },
        }
        nodes = build_pair_lineage_nodes(
            {"card_id": 100701, "card_name": "Ace"}, row
        )
        white = next(
            factor
            for factor in nodes["p1"]["sparks"]
            if factor["type"] == "white_skill"
        )
        pink = next(
            factor
            for factor in nodes["p1"]["sparks"]
            if factor["type"] == "red_aptitude"
        )
        self.assertEqual(white["skill_id"], 10011)
        self.assertAlmostEqual(white["proc_probability_over_run"], 0.246576)
        self.assertEqual(white["inspiration_event_count"], 2)
        self.assertTrue(white["is_score_priority"])
        self.assertEqual(white["score_priority_rank"], 1)
        self.assertNotIn("proc_probability_per_event", white)
        self.assertNotIn("proc_probability_per_event", pink)
        self.assertEqual(nodes["p1"]["inheritance_affinity"], 120.0)

    def test_sparks_are_always_grouped_blue_pink_green_then_white(self) -> None:
        preview = {
            "p1": {
                "card_name": "Parent",
                "sparks": [
                    {"name": "White Skill", "stars": 3, "type": "white_skill"},
                    {"name": "Green Unique", "stars": 1, "type": "unique"},
                    {"name": "Pink Aptitude", "stars": 1, "type": "red_aptitude"},
                    {"name": "Blue Stat", "stars": 1, "type": "blue_stat"},
                    {"name": "Race White", "stars": 2, "type": "white_race"},
                    {"name": "Scenario White", "stars": 2, "type": "scenario"},
                ],
            }
        }
        nodes = build_pair_lineage_nodes(
            {"card_name": "Ace"},
            {
                "parent_1": {"card_name": "Parent"},
                "parent_2": {"card_name": "Other"},
                "lineage_preview": preview,
            },
        )
        self.assertEqual(
            [factor["type"] for factor in nodes["p1"]["sparks"]],
            [
                "blue_stat",
                "red_aptitude",
                "unique",
                "scenario",
                "white_race",
                "white_skill",
            ],
        )

    def test_missing_white_diagnostics_never_invents_a_probability(self) -> None:
        nodes = build_pair_lineage_nodes(
            {"card_name": "Ace"},
            {
                "parent_1": {
                    "card_name": "Parent",
                    "sparks": [
                        {"name": "Corner Adept", "stars": 2, "type": "white_skill"}
                    ],
                },
                "parent_2": {"card_name": "Other"},
            },
        )
        self.assertNotIn(
            "proc_probability_over_run", nodes["p1"]["sparks"][0]
        )

    def test_three_strongest_whites_are_major_and_other_useful_whites_stay_visible(self) -> None:
        names = ["Priority One", "Priority Two", "Priority Three", "Priority Four"]
        nodes = build_pair_lineage_nodes(
            {"card_name": "Ace"},
            {
                "parent_1": {"card_name": "Parent"},
                "parent_2": {"card_name": "Other"},
                "lineage_preview": {
                    "p1": {
                        "card_name": "Parent",
                        "sparks": [
                            {"name": name, "stars": 2, "type": "white_skill"}
                            for name in reversed(names)
                        ],
                    }
                },
                "component_details": {
                    "white_skill": {
                        "inspiration_event_count": 2,
                        "top_skills": [
                            {
                                "name": name,
                                "catalog_key": name.lower().replace(" ", "_"),
                                "profile_weight": 1.0,
                                "contribution": 1.0 / rank,
                            }
                            for rank, name in enumerate(names, 1)
                        ],
                        "factors": [
                            {
                                "role": "parent_1",
                                "source_type": "white_skill",
                                "source_factor_name": name,
                                "catalog_key": name.lower().replace(" ", "_"),
                                "stars": 2,
                                "proc_probability_over_run": 0.12,
                            }
                            for name in names
                        ],
                    }
                },
            },
        )
        whites = nodes["p1"]["sparks"]
        self.assertEqual([factor["name"] for factor in whites], names)
        self.assertEqual(
            [bool(factor.get("is_score_priority")) for factor in whites],
            [True, True, True, False],
        )
        self.assertEqual(
            [bool(factor.get("is_score_useful")) for factor in whites],
            [False, False, False, True],
        )

    def test_available_local_history_adds_optional_great_grandparents(self) -> None:
        left_gp = member(103001, "Left GP", blue=2)
        left_gp_history = member(107001, "Great Left A", pink=1)
        full_left_gp = dict(left_gp)
        full_left_gp["when_used_as_parent"] = {
            "grandparent_1": left_gp_history,
            "grandparent_2": member(108001, "Great Left B", blue=1),
        }
        p1 = member(101001, "Parent One")
        p1["when_used_as_parent"] = {
            "grandparent_1": left_gp,
            "grandparent_2": member(104001, "Left GP B"),
        }
        p2 = member(102001, "Parent Two")
        preview = lineage_preview_for_pair(
            p1,
            p2,
            veteran_by_trained_id={
                str(full_left_gp["trained_chara_id"]): full_left_gp,
            },
        )
        self.assertEqual(preview["p1-1-1"]["card_name"], "Great Left A — Costume")
        self.assertEqual(preview["p1-1-2"]["card_id"], 108001)


if __name__ == "__main__":
    unittest.main()
