import json
from pathlib import Path

from parent_optimizer import (
    _future_grandparent_pink_score,
    _future_grandparent_white_score,
)
from uma_moe import (
    _final_parent_affinity_potential,
    _full_production_affinity,
    _opposing_white_coverage,
    _prune_locked_surface_hard_filter,
    _project_future_parent_branch,
    build_parent_retrieval_plan,
    build_contextual_grandparent_retrieval_plan,
    extract_opposing_parent_candidates,
)


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


def complete_parent(chara_id: int, *, surface_stars=(0, 0, 0), whites=()):
    parent = member(chara_id, ["Parent G1"])
    gp1 = member(chara_id + 1, ["Shared G1", "GP1 only"])
    gp2 = member(chara_id + 2, ["Shared G1", "GP2 only"])
    parent["when_used_as_parent"] = {"grandparent_1": gp1, "grandparent_2": gp2}
    for candidate, stars in zip((parent, gp1, gp2), surface_stars):
        factors = []
        if stars:
            factors.append({"type": "red_aptitude", "name": "Turf", "stars": stars})
        for name, white_stars in whites:
            factors.append({"type": "white_skill", "name": name, "stars": white_stars})
        by_type = {}
        for factor in factors:
            by_type.setdefault(factor["type"], []).append(factor)
        candidate.update({
            "card_id": 1000 + int(candidate["chara_id"]),
            "uma_name": f"Uma {candidate['chara_id']}",
            "card_name": f"Card {candidate['chara_id']}",
            "factors": {"all": factors, "by_type": by_type},
        })
    return parent


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


def test_contextual_retrieval_reallocates_most_covered_surface_budget_to_distance():
    opposing = complete_parent(20, surface_stars=(3, 2, 2))
    plan = build_contextual_grandparent_retrieval_plan(
        ace_target_aptitudes={
            "surface": {"rank": 2, "label": "F"},
            "distance": {"rank": 7, "label": "A"},
            "style": {"rank": 7, "label": "A"},
        },
        opposing_parent=opposing,
        surface="turf",
        distance="medium",
        config=default_config(),
        main_pink_factor_ids={
            "Turf": [1101, 1102, 1103],
            "Medium": [3201, 3202, 3203],
        },
    )
    shares = {row["kind"]: row["share"] for row in plan["cohorts"]}
    assert plan["surface"]["known_opposing_stars"] == 7
    assert plan["surface"]["remaining_stars"] == 3
    assert shares["distance"] > 0.60
    assert shares["surface"] < 0.15
    assert plan["cohorts"][0]["filters"].get("main_parent_pink_sparks")


def test_locked_parent_starting_surface_at_a_removes_surface_cohort():
    locked_parent = complete_parent(80, surface_stars=(3, 2, 2))
    plan = build_parent_retrieval_plan(
        ace_target_aptitudes={
            "surface": {"rank": 4, "label": "C"},
            "distance": {"rank": 7, "label": "A"},
            "style": {"rank": 7, "label": "A"},
        },
        surface="turf",
        distance="medium",
        config=default_config(),
        pink_group_ids={"Turf": 110, "Medium": 320},
        fixed_parent=locked_parent,
    )

    assert plan["surface"]["known_locked_parent_stars"] == 7
    assert plan["surface"]["initial_rank_with_locked_parent"] == 7
    assert plan["surface"]["remaining_stars"] == 0
    assert all(cohort["kind"] != "surface" for cohort in plan["cohorts"])


def test_locked_local_gp_is_counted_without_its_ancestors():
    opposing = complete_parent(90, surface_stars=(2, 1, 1))
    locked_gp = scored_member(100, pink_name="Turf", pink_stars=3)
    locked_gp["when_used_as_parent"] = {
        "grandparent_1": scored_member(101, pink_name="Turf", pink_stars=3),
        "grandparent_2": scored_member(102, pink_name="Turf", pink_stars=3),
    }
    plan = build_contextual_grandparent_retrieval_plan(
        ace_target_aptitudes={
            "surface": {"rank": 4, "label": "C"},
            "distance": {"rank": 7, "label": "A"},
            "style": {"rank": 7, "label": "A"},
        },
        opposing_parent=opposing,
        fixed_grandparent=locked_gp,
        surface="turf",
        distance="medium",
        config=default_config(),
        main_pink_factor_ids={
            "Turf": [1101, 1102, 1103],
            "Medium": [3201, 3202, 3203],
        },
    )

    assert plan["surface"]["known_opposing_stars"] == 4
    assert plan["surface"]["known_locked_local_stars"] == 3
    assert plan["surface"]["known_total_stars"] == 7
    assert plan["surface"]["initial_rank_with_known_branches"] == 7
    assert all(cohort["kind"] != "surface" for cohort in plan["cohorts"])


def test_surface_cohort_can_be_disabled_without_disabling_surface_scoring():
    config = default_config()
    config["uma_moe_parent_search"]["retrieval"]["surface_cohort_enabled"] = False
    plan = build_parent_retrieval_plan(
        ace_target_aptitudes={
            "surface": {"rank": 2, "label": "F"},
            "distance": {"rank": 7, "label": "A"},
            "style": {"rank": 7, "label": "A"},
        },
        surface="turf",
        distance="medium",
        config=config,
        pink_group_ids={"Turf": 110, "Medium": 320},
    )

    assert plan["surface"]["cohort_enabled"] is False
    assert plan["surface"]["remaining_stars"] == 10
    assert all(cohort["kind"] != "surface" for cohort in plan["cohorts"])


def test_redundant_explicit_surface_filter_is_removed_when_locked_context_starts_a():
    hard_filters = [
        {"slot": "main", "factor": "Dirt", "minimum_stars": 2, "uql": "Main Dirt >= 2"},
        {"slot": "main", "factor": "Mile", "minimum_stars": 2, "uql": "Main Mile >= 2"},
    ]
    kept, suppressed = _prune_locked_surface_hard_filter(
        hard_filters,
        {
            "surface": {
                "preferred_rank": 7,
                "initial_rank_with_locked_parent": 7,
            }
        },
        surface_name="Dirt",
        fixed_local_parent={"trained_chara_id": 123},
    )

    assert [item["factor"] for item in kept] == ["Mile"]
    assert [item["factor"] for item in suppressed] == ["Dirt"]


def test_explicit_surface_filter_remains_when_locked_context_is_only_b():
    hard_filters = [
        {"slot": "main", "factor": "Dirt", "minimum_stars": 2, "uql": "Main Dirt >= 2"}
    ]
    kept, suppressed = _prune_locked_surface_hard_filter(
        hard_filters,
        {
            "surface": {
                "preferred_rank": 7,
                "initial_rank_with_locked_parent": 6,
            }
        },
        surface_name="Dirt",
        fixed_local_parent={"trained_chara_id": 123},
    )

    assert kept == hard_filters
    assert suppressed == []


def test_projected_future_parent_keeps_unknown_own_sparks_empty():
    opposing = complete_parent(30)
    gp1 = scored_member(40)
    gp2 = scored_member(41)
    gp1["g1_wins"] = {"names": ["Shared", "A"]}
    gp2["g1_wins"] = {"names": ["Shared", "B"]}
    opposing["g1_wins"] = {"names": ["Shared", "C"]}
    target = {"card_id": 999, "chara_id": 99, "uma_name": "Target", "card_name": "Target Card"}
    projected, plan = _project_future_parent_branch(
        target,
        gp1,
        gp2,
        opposing,
        planned_g1_budget=10,
        single_g1_weight=0.5,
    )
    assert projected["factors"]["all"] == []
    assert projected["when_used_as_parent"]["grandparent_1"] is gp1
    assert projected["when_used_as_parent"]["grandparent_2"] is gp2
    assert "Shared" in projected["g1_wins"]["names"]
    assert plan["single_selected"] == 2


def test_known_whites_are_soft_coverage_not_a_binary_blacklist():
    opposing = complete_parent(50, whites=(("Uma Stan", 3),))
    coverage = _opposing_white_coverage(opposing)
    assert coverage["Uma Stan"] == 2.0
    assert "Tail Held High" not in coverage


def test_external_parent_pair_output_exposes_complete_selectable_branches():
    fixed = complete_parent(60)
    candidate = complete_parent(70)
    payload = {"results": [{"fixed_parent": fixed, "candidate": candidate}]}
    extracted = extract_opposing_parent_candidates("unused.mdb", payload)
    assert {row["chara_id"] for row in extracted} == {60, 70}
