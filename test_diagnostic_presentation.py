from __future__ import annotations

import unittest

from ui_qt.lineage_nodes import build_result_lineage_nodes
from ui_qt.presentation import online_detail_html, result_detail_html


class DiagnosticPresentationTests(unittest.TestCase):
    def test_future_gp_shows_per_skill_generation_gains_and_affinity_context(self) -> None:
        row = {
            "score": 73.2,
            "card_name": "Candidate GP",
            "affinity_raw": 24,
            "future_parent_base_affinity": 18,
            "future_branch_base_total": 42,
            "g1_count": 11,
            "components": {"white_generation": 61.5},
            "score_breakdown": {
                "components": {
                    "white_generation": {
                        "component_score": 61.5,
                        "weight": 0.21,
                        "points": 12.915,
                    }
                }
            },
            "component_details": {
                "white_generation": {
                    "bonus_per_lineage_copy": 0.025,
                    "skill_count": 2,
                    "skills": [
                        {
                            "name": "Uma Stan",
                            "lineage_copy_count": 3,
                            "lineage_generation_bonus": 0.075,
                            "contribution": 0.06,
                        },
                        {
                            "name": "Tail Held High",
                            "lineage_copy_count": 1,
                            "lineage_generation_bonus": 0.025,
                            "contribution": 0.02,
                        },
                    ],
                }
            },
        }

        html = result_detail_html(row, "future", "fr")

        self.assertIn("Base Ace × parent ciblé", html)
        self.assertIn("Total de branche projeté", html)
        self.assertIn("Gains de génération des White Sparks", html)
        self.assertIn("Uma Stan", html)
        self.assertIn("+7.50 pts", html)
        self.assertIn("+2.50 points par porteur", html)
        self.assertIn("ni la probabilité totale", html)

    def test_scenario_proc_probability_reaches_the_visual_spark(self) -> None:
        row = {
            "parent_1": {"card_name": "Parent"},
            "parent_2": {"card_name": "Other"},
            "lineage_preview": {
                "p1": {
                    "card_name": "Parent",
                    "sparks": [
                        {"name": "Grand Live", "stars": 2, "type": "scenario"}
                    ],
                }
            },
            "component_details": {
                "blue": {
                    "scenario_inheritance": {
                        "inspiration_event_count": 2,
                        "factors": [
                            {
                                "role": "parent_1",
                                "name": "Grand Live",
                                "stars": 2,
                                "proc_probability_over_run": 0.1891,
                            }
                        ],
                    }
                }
            },
        }

        nodes = build_result_lineage_nodes(None, row, "pair")
        scenario = nodes["p1"]["sparks"][0]

        self.assertAlmostEqual(scenario["proc_probability_over_run"], 0.1891)
        self.assertEqual(scenario["inspiration_event_count"], 2)

    def test_contextual_gp_diagnostic_exposes_final_pair_and_production_run(self) -> None:
        row = {
            "score": 81.0,
            "fixed_grandparent": {"card_name": "Local GP"},
            "candidate": {"card_name": "Remote GP"},
            "final_parent_affinity": {
                "base": 45,
                "planned_g1_bonus": 18,
                "potential_total": 63,
                "common_g1_count": 3,
            },
            "projected_future_parent": {"card_name": "Target Parent"},
            "opposing_parent": {"card_name": "Opposing Parent"},
            "aptitude_summaries": {
                "surface": {
                    "base_rank_label": "B",
                    "initial_rank_label": "A",
                    "probability_reach_s": 0.22,
                },
                "style": {
                    "base_rank_label": "A",
                    "initial_rank_label": "A",
                    "probability_reach_s": 0.0,
                },
            },
            "distance_s_summary": {
                "base_rank_label": "A",
                "initial_rank_label": "A",
                "probability_reach_s": 0.48,
                "total_stars": 8,
                "carrier_count": 3,
                "parent_carrier_count": 1,
                "procs_required_for_a": 0,
                "procs_required_for_s": 1,
            },
            "distance_viability": {"key": "ready_for_s", "tier": 4},
            "production_affinity": {
                "total": 156,
                "scored_value": 72,
                "gp1_inheritance_modifier": {"total": 70},
                "gp2_inheritance_modifier": {"total": 74},
            },
            "components": {"white_generation": 35.0},
            "score_breakdown": {"components": {}},
            "component_details": {
                "white_generation": {
                    "bonus_per_lineage_copy": 0.025,
                    "included_in_weighted_score": False,
                    "skill_count": 1,
                    "skills": [
                        {
                            "name": "Tail Held High",
                            "lineage_copy_count": 2,
                            "lineage_generation_bonus": 0.05,
                            "contribution": 0.04,
                        }
                    ],
                }
            },
        }

        html = online_detail_html(
            row,
            "grandparent",
            "fr",
            {"surface": "turf", "distance": "medium", "style": "pace_chaser"},
        )

        self.assertIn("Projection de la paire finale", html)
        self.assertIn("Opposing Parent", html)
        self.assertIn("48.0%", html)
        self.assertIn("Affinité de la run de production", html)
        self.assertIn("156.0", html)
        self.assertIn("+5.00 pts", html)
        self.assertIn(">Non<", html)


if __name__ == "__main__":
    unittest.main()
