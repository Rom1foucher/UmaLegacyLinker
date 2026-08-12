from __future__ import annotations

import unittest

from uma_moe import _extract_record_list


class ExtractRecordListTests(unittest.TestCase):
    def test_picks_items_over_embedded_retrieval_plan_factor_lists(self) -> None:
        """Regression test for a real crash: a contextual GP search embeds a
        full resolved opposing-parent branch (with its own small, uniformly
        well-formed factor lists) under retrieval_plan purely for audit
        purposes. That metadata must never be mistaken for the actual
        uma.moe candidate list, even when it would otherwise out-score it
        under the heuristic (see uma_moe_api_response.json from 2026-07-22:
        20 factor objects out-scored 1742 real candidates and made
        rank_online_grandparent_pairs reject every candidate)."""
        real_candidate = {
            "account_id": "1",
            "trainer_name": "Someone",
            "follower_num": 0,
            "borrow_view_count": 0,
            "borrow_copy_count": 0,
            "last_updated": "2026-07-22",
            "inheritance": {"main_parent_id": 100601, "parent_left_id": 1, "parent_right_id": 2},
            "support_card": {"card_id": 30001},
        }
        factor_object = {
            "description": "x", "effect_group_id": 1, "factor_group_id": 1,
            "factor_id": 1, "name": "Some Spark", "source": "main",
            "source_uma": "x", "stars": 3, "stars_text": "★★★", "type": "white_skill",
        }
        payload = {
            "items": [real_candidate] * 50,
            "retrieval_plan": {
                "enabled": True,
                "opposing_parent": {
                    "when_used_as_parent": {
                        "lineage_summary": {
                            "factors_by_type": {"white_skill": [factor_object] * 20},
                        },
                    },
                },
            },
        }
        records = _extract_record_list(payload)
        self.assertEqual(len(records), 50)
        self.assertEqual(records[0], real_candidate)

    def test_still_finds_items_without_retrieval_plan(self) -> None:
        payload = {"items": [{"card_id": 1, "factor": "x"}] * 5}
        records = _extract_record_list(payload)
        self.assertEqual(len(records), 5)


if __name__ == "__main__":
    unittest.main()
