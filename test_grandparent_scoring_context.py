import json
from pathlib import Path

from parent_optimizer import (
    _future_grandparent_pink_score,
    _future_grandparent_white_score,
)
from uma_moe import _final_parent_affinity_potential, _full_production_affinity


class FakeResolver:
    def pair(self, a: int, b: int) -> int:
        return 0 if a == b else a + b

    def triple(self, a: int, b: int, c: int) -> int:
        return 0 if len({a, b, c}) < 3 else a + b + c


def member(chara_id: int, g1: list[str], gp1=None, gp2=None):
    return {
        "chara_id": chara_id,
        "g1_wins": {"names": g1},
        "when_used_as_parent": {
            "grandparent_1": gp1,
            "grandparent_2": gp2,
        },
    }


def scored_member(chara_id: int, *, pink_name: str = "Medium", pink_stars: int = 3):
    payload = member(chara_id, [])
    payload["factors"] = {
        "all": [
            {"type": "red_aptitude", "name": pink_name, "stars": pink_stars},
            {"type": "white_skill", "name": "Uma Stan", "stars": 3},
        ],
        "by_type": {
            "red_aptitude": [
                {"type": "red_aptitude", "name": pink_name, "stars": pink_stars}
            ],
            "white_skill": [
                {"type": "white_skill", "name": "Uma Stan", "stars": 3}
            ],
        },
    }
    return payload


def ace_payload():
    return {
        "target_aptitudes": {
            "surface": {"rank": 7, "label": "A"},
            "distance": {"rank": 7, "label": "A"},
            "style": {"rank": 7, "label": "A"},
        }
    }


def default_config():
    path = Path(__file__).resolve().parent / "default_parent_scoring.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_projected_final_and_production_affinity_remain_distinct_gp_diagnostics():
    gp1_parent_1 = member(5, ["A"])
    gp1_parent_2 = member(6, ["C"])
    gp2_parent_1 = member(7, ["B"])
    gp2_parent_2 = member(8, ["D"])
    gp1 = member(3, ["A", "B", "C"], gp1_parent_1, gp1_parent_2)
    gp2 = member(4, ["B", "D"], gp2_parent_1, gp2_parent_2)

    final = _final_parent_affinity_potential(
        FakeResolver(),
        ace_chara=1,
        target_parent_chara=2,
        gp1=gp1,
        gp2=gp2,
        g1_bonus_value=3,
        planned_g1_budget=3,
        single_g1_weight=0.5,
    )
    production = _full_production_affinity(
        FakeResolver(),
        target_parent_chara=2,
        gp1=gp1,
        gp2=gp2,
        g1_bonus_value=3,
    )

    gp1_final = final["projected_gp1_inheritance_modifier"]["total"]
    gp2_final = final["projected_gp2_inheritance_modifier"]["total"]
    gp1_production = production["gp1_inheritance_modifier"]["total"]
    gp2_production = production["gp2_inheritance_modifier"]["total"]

    # These values remain useful as separate affinity diagnostics even though the
    # simple future-GP factor score no longer converts either one into proc odds.
    assert gp1_final == 11.0
    assert gp2_final == 11.0
    assert gp1_production > gp1_final
    assert gp2_production > gp2_final


def test_future_gp_pink_uses_simple_quality_model_without_s_probability():
    candidate = scored_member(3)
    score, detail = _future_grandparent_pink_score(
        [(candidate, "grandparent", "candidate")],
        ace_payload(),
        "turf",
        "medium",
        "pace_chaser",
        default_config(),
    )

    assert score == 100.0
    assert detail["model"] == "future_grandparent_simple"
    assert detail["uses_proc_probability"] is False
    assert "distance_s" not in detail
    assert "probability_reach_s" not in detail


def test_future_gp_white_uses_star_and_position_heuristic_without_affinity():
    candidate = scored_member(3)
    score, detail = _future_grandparent_white_score(
        [(candidate, "grandparent", "candidate")],
        lambda key: 1.0 if key == "uma_stan" else 0.0,
        default_config(),
    )

    assert score > 0
    assert detail["model"] == "future_grandparent_simple"
    assert detail["uses_individual_affinity"] is False
    factor = detail["top_factors"][0]
    assert factor["star_quality"] == 1.8
    assert factor["position_weight"] == 0.5
    assert "proc_probability_per_event" not in factor


def test_future_gp_component_weights_do_not_expose_parent_probability_components():
    weights = default_config()["mode_weights"]["future_grandparent"]
    assert "pink" in weights
    assert "distance_s" not in weights
    assert "pink_other" not in weights


def test_future_gp_race_granted_skill_uses_simplified_proc_rate_ratio():
    direct = scored_member(10)
    race = member(11, [])
    race["factors"] = {
        "all": [{"type": "white_race", "name": "Tenno Sho (Autumn)", "stars": 3}],
        "by_type": {
            "white_race": [{"type": "white_race", "name": "Tenno Sho (Autumn)", "stars": 3}]
        },
    }
    cfg = default_config()
    _direct_score, direct_detail = _future_grandparent_white_score(
        [(direct, "grandparent", "direct")],
        lambda key: 1.0 if key in {"uma_stan", "fall_runner"} else 0.0,
        cfg,
        {"Tenno Sho (Autumn)": ["fall_runner"]},
    )
    _race_score, race_detail = _future_grandparent_white_score(
        [(race, "grandparent", "race")],
        lambda key: 1.0 if key in {"uma_stan", "fall_runner"} else 0.0,
        cfg,
        {"Tenno Sho (Autumn)": ["fall_runner"]},
    )
    direct_factor = direct_detail["top_factors"][0]
    race_factor = race_detail["top_factors"][0]
    assert race_factor["source_type"] == "white_race"
    assert abs(race_factor["proc_rate_ratio_vs_white"] - (1.0 / 3.0)) < 1e-8
    assert abs(race_factor["contribution"] - direct_factor["contribution"] / 3.0) < 1e-8
