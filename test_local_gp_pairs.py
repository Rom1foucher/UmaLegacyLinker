from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from uma_moe import (
    _apply_lineage_factor_filters,
    _lineage_factor_type_stars,
    rank_online_grandparent_pairs,
)


def _factor(ftype: str, name: str, stars: int) -> dict:
    return {"type": ftype, "name": name, "stars": stars}


def _member(chara_id: int, name: str, *, factors=(), g1=(), gp1=None, gp2=None) -> dict:
    payload = {
        "trained_chara_id": chara_id * 10,
        "card_id": chara_id * 100,
        "chara_id": chara_id,
        "uma_name": name,
        "card_name": name,
        "rank_score": 1000 + chara_id,
        "factors": {"all": [], "by_type": {}},
        "g1_wins": {"count": len(g1), "names": list(g1), "details": []},
        "when_used_as_parent": {"grandparent_1": gp1, "grandparent_2": gp2},
    }
    for factor in factors:
        payload["factors"]["all"].append(factor)
        payload["factors"]["by_type"].setdefault(factor["type"], []).append(factor)
    return payload


def _complete_veteran(chara_id: int, name: str, *, factors=(), g1=()) -> dict:
    gp1 = _member(chara_id + 50, f"{name} GP1", factors=[_factor("blue_stat", "Stamina", 3)])
    gp2 = _member(chara_id + 60, f"{name} GP2", factors=[_factor("red_aptitude", "Medium", 3)])
    return _member(chara_id, name, factors=factors, g1=g1, gp1=gp1, gp2=gp2)


class LineageFilterTests(unittest.TestCase):
    def test_sums_stars_over_main_and_both_parents(self) -> None:
        veteran = _complete_veteran(
            1, "A", factors=[_factor("blue_stat", "Stamina", 3)]
        )
        # Main 3★ + GP1 3★ (GP2 has none) = 6★
        self.assertEqual(_lineage_factor_type_stars(veteran, "Stamina", "blue_stat"), 6)
        self.assertEqual(_lineage_factor_type_stars(veteran, "Speed", "blue_stat"), 0)
        self.assertEqual(_lineage_factor_type_stars(veteran, "Medium", "red_aptitude"), 3)

    def test_filter_keeps_only_matching_candidates(self) -> None:
        strong = _complete_veteran(1, "Strong", factors=[_factor("blue_stat", "Stamina", 3)])
        weak = _complete_veteran(2, "Weak")
        logs: list[str] = []
        kept = _apply_lineage_factor_filters(
            [strong, weak], ("Stamina", 5), None, logs.append
        )
        self.assertEqual([m["card_name"] for m in kept], ["Strong"])
        self.assertTrue(any("Stamina" in line for line in logs))

    def test_no_filter_is_identity(self) -> None:
        members = [_complete_veteran(1, "A"), _complete_veteran(2, "B")]
        self.assertEqual(
            _apply_lineage_factor_filters(members, None, None, lambda _m: None),
            members,
        )


def _build_fake_master(path: Path, chara_ids: list[int], ace_card_id: int) -> None:
    connection = sqlite3.connect(path)
    cur = connection.cursor()
    cur.execute("CREATE TABLE succession_relation (relation_type INTEGER, relation_point INTEGER)")
    cur.execute("CREATE TABLE succession_relation_member (relation_type INTEGER, chara_id INTEGER)")
    cur.execute("CREATE TABLE card_data (id INTEGER, chara_id INTEGER)")
    cur.execute(
        "CREATE TABLE card_rarity_data (card_id INTEGER, rarity INTEGER, "
        "proper_ground_turf INTEGER, proper_ground_dirt INTEGER, "
        "proper_distance_short INTEGER, proper_distance_mile INTEGER, "
        "proper_distance_middle INTEGER, proper_distance_long INTEGER, "
        "proper_running_style_nige INTEGER, proper_running_style_senko INTEGER, "
        "proper_running_style_sashi INTEGER, proper_running_style_oikomi INTEGER)"
    )
    cur.execute("CREATE TABLE text_data (category INTEGER, [index] INTEGER, text TEXT)")
    # One shared relation group so pair()/triple() return non-zero affinities.
    cur.execute("INSERT INTO succession_relation VALUES (1, 10)")
    for chara_id in chara_ids:
        cur.execute("INSERT INTO succession_relation_member VALUES (1, ?)", (chara_id,))
        cur.execute("INSERT INTO card_data VALUES (?, ?)", (chara_id * 100, chara_id))
        for category in (4, 5, 6):
            cur.execute(
                "INSERT INTO text_data VALUES (?, ?, ?)",
                (category, chara_id * 100 if category != 6 else chara_id, f"Chara {chara_id}"),
            )
    cur.execute(
        "INSERT INTO card_rarity_data VALUES (?, 3, 7, 1, 1, 1, 7, 1, 1, 7, 1, 1)",
        (ace_card_id,),
    )
    connection.commit()
    connection.close()


class LocalPairModeIntegrationTests(unittest.TestCase):
    def test_local_pair_mode_ranks_local_pairs_without_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ace_chara, parent_chara = 1, 2
            gp_charas = [3, 4, 5]
            all_charas = [ace_chara, parent_chara] + gp_charas + [
                c + 50 for c in gp_charas
            ] + [c + 60 for c in gp_charas]
            master = root / "master.mdb"
            _build_fake_master(master, all_charas, ace_card_id=ace_chara * 100)

            veterans = [
                _complete_veteran(chara, f"GP {chara}", g1=[f"G1 race {chara}"])
                for chara in gp_charas
            ]
            linked = root / "veterans_legacy_linked.json"
            linked.write_text(json.dumps({"veterans": veterans}), encoding="utf-8")
            weights = root / "manual_skill_weights.json"
            weights.write_text(json.dumps({"skills": {}}), encoding="utf-8")
            catalog = root / "skill_catalog.json"
            catalog.write_text(json.dumps({"skills": []}), encoding="utf-8")
            output = root / "out"

            result = rank_online_grandparent_pairs(
                master,
                linked,
                weights,
                catalog,
                output,
                ace_card_id=ace_chara * 100,
                target_parent_card_id=parent_chara * 100,
                exhaustive_pairs=True,
                surface="turf",
                distance="medium",
                style="pace_chaser",
                local_pair_mode=True,
                top_n=10,
            )

            self.assertTrue(result.pair_mode.startswith("local_"))
            # 3 GPs -> 3 unordered pairs, symmetric duplicates removed.
            self.assertEqual(result.evaluated_pair_count, 3)
            self.assertEqual(result.result_count, 3)
            seen_pairs = {
                frozenset(
                    (
                        row["fixed_grandparent"]["trained_chara_id"],
                        row["candidate"]["trained_chara_id"],
                    )
                )
                for row in result.top_results
            }
            self.assertEqual(len(seen_pairs), 3)
            self.assertTrue(result.rankings_json_path.is_file())
            raw = json.loads(result.raw_response_path.read_text(encoding="utf-8"))
            self.assertTrue(raw.get("local_pair_mode"))

    def test_local_pair_mode_applies_lineage_filter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gp_charas = [3, 4, 5]
            all_charas = [1, 2] + gp_charas + [c + 50 for c in gp_charas] + [
                c + 60 for c in gp_charas
            ]
            master = root / "master.mdb"
            _build_fake_master(master, all_charas, ace_card_id=100)

            veterans = [
                _complete_veteran(3, "Rich", factors=[_factor("blue_stat", "Stamina", 3)]),
                _complete_veteran(4, "Mid"),
                _complete_veteran(5, "Poor"),
            ]
            linked = root / "veterans_legacy_linked.json"
            linked.write_text(json.dumps({"veterans": veterans}), encoding="utf-8")
            (root / "w.json").write_text(json.dumps({"skills": {}}), encoding="utf-8")
            (root / "c.json").write_text(json.dumps({"skills": []}), encoding="utf-8")

            # "Rich" totals Stamina 6★ (main 3 + GP1 3); the two others 3★.
            result = rank_online_grandparent_pairs(
                master,
                linked,
                root / "w.json",
                root / "c.json",
                root / "out",
                ace_card_id=100,
                target_parent_card_id=200,
                exhaustive_pairs=True,
                surface="turf",
                distance="medium",
                style="pace_chaser",
                local_pair_mode=True,
                lineage_blue_filter=("Stamina", 5),
                top_n=10,
            )
            # Second pool filtered down to "Rich": pairs = Rich × {Mid, Poor}? No —
            # the FIRST pool (locals) stays unfiltered by design (it is the user's
            # own box); only the candidate pool is filtered, so pairs pass through
            # the filtered side once each.
            self.assertGreaterEqual(result.evaluated_pair_count, 1)
            for row in result.top_results:
                names = {
                    row["fixed_grandparent"]["card_name"],
                    row["candidate"]["card_name"],
                }
                self.assertIn("Rich", names)


if __name__ == "__main__":
    unittest.main()
