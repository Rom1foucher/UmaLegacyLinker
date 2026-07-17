from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import lineage_planner
from lineage_planner import _planner_factor, build_lineage_planner_export


def factor(group_id: int, stars: int, name: str, factor_type: str) -> dict[str, object]:
    return {
        "factor_id": group_id * 10 + stars,
        "factor_group_id": group_id,
        "name": name,
        "stars": stars,
        "type": factor_type,
    }


def member(card_id: int, name: str, *, lineage: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "card_id": card_id,
        "card_name": name,
        "factors": {
            "all": [
                factor(33, 2, "Medium", "red_aptitude"),
                factor(3, 3, "Power", "blue_stat"),
                factor(20046, 1, "Ramp Up", "white_skill"),
            ]
        },
        "when_used_as_parent": lineage or {},
    }


class FakeResolver:
    def __init__(self, _path) -> None:
        self.closed = False

    def resolve_card(self, card_id: int) -> dict[str, object]:
        return {
            "card_id": card_id,
            "chara_id": card_id // 100,
            "uma_name": f"Uma {card_id}",
            "card_name": f"Variant {card_id}",
            "costume_name": f"Variant {card_id}",
        }

    def resolve_factors(self, factors, _unresolved) -> dict[str, object]:
        resolved = []
        for raw in factors or []:
            factor_id = int(raw["factor_id"])
            resolved.append(
                factor(
                    factor_id // 10,
                    factor_id % 10,
                    f"Factor {factor_id // 10}",
                    "blue_stat",
                )
            )
        return {"all": resolved, "by_type": {"blue_stat": resolved}}

    def close(self) -> None:
        self.closed = True


def raw_veteran(trained_id: int, card_id: int) -> dict[str, object]:
    snapshots = []
    for position, suffix in ((10, 1), (20, 2), (11, 3), (12, 4), (21, 5), (22, 6)):
        snapshots.append(
            {
                "card_id": card_id + suffix,
                "position_id": position,
                "factor_info_array": [{"factor_id": 100 + suffix}],
                "win_saddle_id_array": [suffix],
            }
        )
    return {
        "trained_chara_id": trained_id,
        "card_id": card_id,
        "factor_info_array": [{"factor_id": 103}],
        "succession_chara_array": snapshots,
    }


class LineagePlannerTests(unittest.TestCase):
    def test_factor_id_uses_the_level_stripped_mdb_id(self) -> None:
        self.assertEqual(
            _planner_factor(
                {
                    "factor_id": 2004603,
                    "factor_group_id": 20046,
                    "name": "Ramp Up",
                    "stars": 3,
                    "type": "white_skill",
                }
            ),
            {"factorId": "200460", "level": 3, "name": "Ramp Up", "type": 3},
        )

    def test_builds_planner_v1_payload_from_normalized_pair(self) -> None:
        great_gp = member(100301, "Great GP")
        gp_1 = member(
            100201,
            "GP 1",
            lineage={"grandparent_1": great_gp, "grandparent_2": None},
        )
        gp_2 = member(100401, "GP 2")
        parent_1 = member(
            101001,
            "Parent 1",
            lineage={"grandparent_1": gp_1, "grandparent_2": gp_2},
        )
        parent_2 = member(102001, "Parent 2")

        payload = build_lineage_planner_export(
            {"card_id": 103001},
            parent_1,
            parent_2,
            exported_at=datetime(2026, 7, 17, 18, 42, 57, 313000, tzinfo=timezone.utc),
        )

        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["type"], "lineage-planner")
        self.assertEqual(payload["exportedAt"], "2026-07-17T18:42:57.313Z")
        self.assertEqual(
            [row["position"] for row in payload["payload"]],
            ["target", "p1", "p2", "p1-1", "p1-2", "p1-1-1"],
        )
        parent = payload["payload"][1]
        self.assertEqual(parent["characterId"], 101001)
        self.assertIsNone(parent["veteran"])
        self.assertIsNone(parent["succession"])
        self.assertEqual(parent["manualWinSaddleIds"], [])
        self.assertEqual(
            parent["sparks"],
            [
                {"factorId": "3", "level": 3, "name": "Power", "type": 0},
                {"factorId": "33", "level": 2, "name": "Medium", "type": 1},
                {"factorId": "20046", "level": 1, "name": "Ramp Up", "type": 3},
            ],
        )

    def test_local_veterans_include_complete_raw_lineages(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            raw_1 = raw_veteran(11, 101001)
            raw_2 = raw_veteran(22, 102001)
            data_path = root / "data.json"
            data_path.write_text(json.dumps([raw_1, raw_2]), encoding="utf-8")
            master_path = root / "master.mdb"
            master_path.touch()

            with patch.object(lineage_planner, "MasterResolver", FakeResolver):
                payload = build_lineage_planner_export(
                    103001,
                    {"trained_chara_id": 11, "card_id": 101001},
                    {"trained_chara_id": 22, "card_id": 102001},
                    master_path=master_path,
                    veterans_json_path=data_path,
                )

        rows = {row["position"]: row for row in payload["payload"]}
        self.assertEqual(list(rows), list(lineage_planner.POSITION_ORDER))
        self.assertEqual(rows["p1"]["veteran"], raw_1)
        self.assertEqual(rows["p2"]["veteran"], raw_2)
        self.assertEqual(rows["p1-1"]["succession"]["position_id"], 10)
        self.assertEqual(rows["p1-2-2"]["succession"]["position_id"], 22)
        self.assertEqual(rows["p2-1-1"]["characterId"], 102004)


if __name__ == "__main__":
    unittest.main()
