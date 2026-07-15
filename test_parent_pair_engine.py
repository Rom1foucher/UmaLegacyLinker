from parent_optimizer import (
    _aptitude_pair_score,
    _blue_score,
    _race_scenario_score,
    _white_score,
    evaluate_parent_branch,
    evaluate_parent_pair,
    parent_pair_sort_key,
)


class FakeResolver:
    def pair(self, a: int, b: int) -> int:
        return a + b

    def triple(self, a: int, b: int, c: int) -> int:
        return a + b + c


def member(chara_id: int, name: str, g1: list[str], gp1=None, gp2=None):
    return {
        "trained_chara_id": chara_id * 10,
        "card_id": chara_id * 100,
        "chara_id": chara_id,
        "uma_name": name,
        "card_name": name,
        "rank_score": 1000 + chara_id,
        "factors": {"all": [], "by_type": {}},
        "g1_wins": {"count": len(g1), "names": g1, "details": []},
        "when_used_as_parent": {
            "grandparent_1": gp1,
            "grandparent_2": gp2,
        },
    }


def add_red(member_payload, name: str, stars: int):
    factor = {"type": "red_aptitude", "name": name, "stars": stars}
    member_payload["factors"]["all"].append(factor)
    member_payload["factors"]["by_type"].setdefault("red_aptitude", []).append(factor)
    return member_payload


def add_blue(member_payload, name: str, stars: int):
    factor = {"type": "blue_stat", "name": name, "stars": stars}
    member_payload["factors"]["all"].append(factor)
    member_payload["factors"]["by_type"].setdefault("blue_stat", []).append(factor)
    return member_payload




def add_white(member_payload, name: str, stars: int):
    factor = {"type": "white_skill", "name": name, "stars": stars}
    member_payload["factors"]["all"].append(factor)
    member_payload["factors"]["by_type"].setdefault("white_skill", []).append(factor)
    return member_payload


def add_race(member_payload, name: str, stars: int):
    factor = {"type": "white_race", "name": name, "stars": stars}
    member_payload["factors"]["all"].append(factor)
    member_payload["factors"]["by_type"].setdefault("white_race", []).append(factor)
    return member_payload

def base_config():
    return {
        "affinity": {
            "g1_common_bonus": 3,
            "parent_branch_thresholds": [[0, 0], [100, 100]],
            "parent_pair_thresholds": [[0, 0], [100, 100]],
        },
        "mode_weights": {
            "parent_final": {
                "affinity": 1.0,
                "pink": 0.0,
                "white_skill": 0.0,
                "race_scenario": 0.0,
                "blue": 0.0,
                "unique": 0.0,
            }
        },
        "position_transmission": {"parent": 1.0, "grandparent": 0.7},
        "pink_dimension_weights": {"surface": 1.0, "distance": 1.0, "style": 1.0},
        "pink_need_multiplier": {"below_a": 1.0, "a_or_s": 1.0},
        "white_saturation": {"parent_branch": 1.0, "parent_pair": 1.0},
        "race_saturation": {"parent_branch": 1.0, "parent_pair": 1.0},
    }


def ace(distance_rank: int = 7, surface_rank: int = 7, style_rank: int = 7):
    labels = {5: "C", 6: "B", 7: "A"}
    return {
        "chara_id": 1,
        "target_aptitudes": {
            "surface": {"rank": surface_rank, "label": labels.get(surface_rank, str(surface_rank))},
            "distance": {"rank": distance_rank, "label": labels.get(distance_rank, str(distance_rank))},
            "style": {"rank": style_rank, "label": labels.get(style_rank, str(style_rank))},
        },
    }


def test_parent_pair_engine_scores_all_six_members_and_five_g1_links():
    local_gp1 = member(4, "Local GP1", ["A"])
    local_gp2 = member(5, "Local GP2", ["B"])
    remote_gp1 = member(6, "Remote GP1", ["C"])
    remote_gp2 = member(7, "Remote GP2", ["D"])
    local = member(2, "Local Parent", ["A", "B", "Z"], local_gp1, local_gp2)
    remote = member(3, "Remote Parent", ["C", "D", "Z"], remote_gp1, remote_gp2)

    resolver = FakeResolver()
    config = base_config()
    local_branch = evaluate_parent_branch(
        resolver,
        ace(),
        local,
        surface="turf",
        distance="medium",
        style="pace_chaser",
        weight_lookup=lambda _key: 0.0,
        race_skills={},
        config=config,
    )
    remote_branch = evaluate_parent_branch(
        resolver,
        ace(),
        remote,
        surface="turf",
        distance="medium",
        style="pace_chaser",
        weight_lookup=lambda _key: 0.0,
        race_skills={},
        config=config,
    )
    pair = evaluate_parent_pair(
        resolver,
        ace(),
        local,
        remote,
        surface="turf",
        distance="medium",
        style="pace_chaser",
        weight_lookup=lambda _key: 0.0,
        race_skills={},
        config=config,
        parent_1_branch=local_branch,
        parent_2_branch=remote_branch,
    )

    # base = local branch (3 + 7 + 8) + remote branch (4 + 10 + 11)
    #        + parent-parent pair (5)
    assert pair["affinity"]["base"] == 48
    # G1 links: local↔GP1, local↔GP2, remote↔GP1, remote↔GP2,
    # and local parent↔remote parent = 5 matches × 3.
    assert pair["affinity"]["g1_bonus"] == 15
    assert pair["affinity"]["total"] == 63
    assert pair["affinity"]["parent_parent_common_g1"] == ["Z"]
    assert pair["affinity"]["parent_1_branch"]["details"]["parent_gp1_common_g1"] == ["A"]
    assert pair["affinity"]["parent_2_branch"]["details"]["parent_gp2_common_g1"] == ["D"]
    assert pair["component_details"]["blue"]["slot_count"] == 6
    assert pair["component_details"]["pink"]["slot_count"] == 6
    assert pair["component_details"]["unique"]["slot_count"] == 6


def test_parent_pair_reuses_precomputed_branch_results():
    gp1 = member(4, "GP1", [])
    gp2 = member(5, "GP2", [])
    gp3 = member(6, "GP3", [])
    gp4 = member(7, "GP4", [])
    local = member(2, "Local", [], gp1, gp2)
    remote = member(3, "Remote", [], gp3, gp4)
    resolver = FakeResolver()
    config = base_config()

    left = evaluate_parent_branch(
        resolver, ace(), local,
        surface="turf", distance="medium", style="pace_chaser",
        weight_lookup=lambda _key: 0.0, race_skills={}, config=config,
    )
    right = evaluate_parent_branch(
        resolver, ace(), remote,
        surface="turf", distance="medium", style="pace_chaser",
        weight_lookup=lambda _key: 0.0, race_skills={}, config=config,
    )
    pair = evaluate_parent_pair(
        resolver, ace(), local, remote,
        surface="turf", distance="medium", style="pace_chaser",
        weight_lookup=lambda _key: 0.0, race_skills={}, config=config,
        parent_1_branch=left, parent_2_branch=right,
    )

    assert pair["affinity"]["parent_1_branch"] is left["affinity"]
    assert pair["affinity"]["parent_2_branch"] is right["affinity"]


def test_distance_s_viability_is_separate_from_other_pinks():
    local_gp1 = add_red(member(4, "Local GP1", []), "Medium", 3)
    local_gp2 = add_red(member(5, "Local GP2", []), "Turf", 3)
    remote_gp1 = add_red(member(6, "Remote GP1", []), "Turf", 3)
    remote_gp2 = add_red(member(7, "Remote GP2", []), "Pace Chaser", 3)
    local = add_red(member(2, "Local", [], local_gp1, local_gp2), "Medium", 3)
    remote = add_red(member(3, "Remote", [], remote_gp1, remote_gp2), "Turf", 3)

    config = base_config()
    config["mode_weights"] = {
        "parent_branch": {"distance_s": 1.0},
        "parent_pair": {"distance_s": 1.0},
    }
    pair = evaluate_parent_pair(
        FakeResolver(), ace(), local, remote,
        surface="turf", distance="medium", style="pace_chaser",
        weight_lookup=lambda _key: 0.0, race_skills={}, config=config,
    )

    assert pair["distance_viability"]["key"] == "ready_for_s"
    assert pair["distance_s_summary"]["total_stars"] == 6
    assert pair["distance_s_summary"]["carrier_count"] == 2
    assert pair["components"]["distance_s"] > 0
    assert pair["components"]["pink_other"] > 0


def test_surface_and_style_pinks_cannot_make_pair_distance_viable():
    local_gp1 = add_red(member(4, "Local GP1", []), "Turf", 3)
    local_gp2 = add_red(member(5, "Local GP2", []), "Pace Chaser", 3)
    remote_gp1 = add_red(member(6, "Remote GP1", []), "Turf", 3)
    remote_gp2 = add_red(member(7, "Remote GP2", []), "Pace Chaser", 3)
    local = add_red(member(2, "Local", [], local_gp1, local_gp2), "Turf", 3)
    remote = add_red(member(3, "Remote", [], remote_gp1, remote_gp2), "Pace Chaser", 3)

    config = base_config()
    config["mode_weights"] = {
        "parent_branch": {"pink_other": 1.0},
        "parent_pair": {"pink_other": 1.0},
    }
    pair = evaluate_parent_pair(
        FakeResolver(), ace(), local, remote,
        surface="turf", distance="medium", style="pace_chaser",
        weight_lookup=lambda _key: 0.0, race_skills={}, config=config,
    )

    assert pair["components"]["pink_other"] > 0
    assert pair["components"]["distance_s"] == 0
    assert pair["distance_viability"]["key"] == "no_s_support"


def test_pair_sort_prioritizes_distance_viability_over_additive_score():
    non_viable = {
        "score": 99.0,
        "distance_viability": {"sort_priority": 0},
        "distance_s_summary": {"weighted_support": 0.0},
        "affinity": {"total": 250},
    }
    viable = {
        "score": 10.0,
        "distance_viability": {"sort_priority": 2},
        "distance_s_summary": {"weighted_support": 1.5},
        "affinity": {"total": 80},
    }

    ranked = sorted([non_viable, viable], key=parent_pair_sort_key, reverse=True)
    assert ranked[0] is viable


def test_pair_sort_uses_weighted_quality_before_small_probability_s_difference():
    higher_probability = {
        "score": 70.0,
        "distance_viability": {"sort_priority": 4},
        "distance_s_summary": {"probability_reach_s": 0.60},
        "components": {"white_skill": 50.0, "blue": 50.0},
    }
    better_lineage = {
        "score": 74.0,
        "distance_viability": {"sort_priority": 4},
        "distance_s_summary": {"probability_reach_s": 0.50},
        "components": {"white_skill": 70.0, "blue": 70.0},
    }

    ranked = sorted([higher_probability, better_lineage], key=parent_pair_sort_key, reverse=True)
    assert ranked[0] is better_lineage


def test_distance_s_probability_curve_has_diminishing_returns_near_sixty_percent():
    config = {
        "aptitude_inheritance": {
            "distance": {
                "start_a_base_score": 70,
                "start_a_s_probability_weight": 30,
                "s_probability_curve": [
                    [0.0, 0.0],
                    [0.4, 70.0],
                    [0.5, 90.0],
                    [0.6, 100.0],
                ],
            }
        }
    }
    score_40 = _aptitude_pair_score("distance", 7, 1.0, 0.40, config)
    score_50 = _aptitude_pair_score("distance", 7, 1.0, 0.50, config)
    score_60 = _aptitude_pair_score("distance", 7, 1.0, 0.60, config)

    assert score_40 == 91.0
    assert score_50 == 97.0
    assert score_60 == 100.0
    assert score_50 - score_40 > score_60 - score_50


def test_blue_relevance_and_influence_change_with_distance():
    stamina_members = [
        (add_blue(member(index, f"S{index}", []), "Stamina", 3), "parent", f"s{index}")
        for index in range(2, 8)
    ]
    power_members = [
        (add_blue(member(index, f"P{index}", []), "Power", 3), "parent", f"p{index}")
        for index in range(8, 14)
    ]
    config = {
        "blue_star_quality": {"1": 0.12, "2": 0.78, "3": 1.0},
        "blue_neutral_score": 50.0,
        "blue_score_influence_by_distance": {
            "sprint": 0.45,
            "mile": 0.65,
            "medium": 0.90,
            "long": 1.0,
        },
        "blue_stat_weights_by_distance": {
            "sprint": {"Speed": 0.65, "Stamina": 0.05, "Power": 1.0, "Guts": 0.35, "Wit": 0.45},
            "mile": {"Speed": 0.65, "Stamina": 0.25, "Power": 1.0, "Guts": 0.40, "Wit": 0.50},
            "medium": {"Speed": 0.65, "Stamina": 1.0, "Power": 0.80, "Guts": 0.45, "Wit": 0.50},
            "long": {"Speed": 0.65, "Stamina": 1.0, "Power": 0.75, "Guts": 0.45, "Wit": 0.50},
        },
    }

    sprint_stamina, _ = _blue_score(stamina_members, "sprint", config)
    sprint_power, sprint_detail = _blue_score(power_members, "sprint", config)
    long_stamina, _ = _blue_score(stamina_members, "long", config)
    long_power, _ = _blue_score(power_members, "long", config)

    assert sprint_power > sprint_stamina
    assert long_stamina > long_power
    assert sprint_detail["distance_influence"] == 0.45
    assert sprint_detail["uncompressed_score"] == 100.0
    assert sprint_power < 100.0  # Sprint compresses blue-score differences.


def test_distance_b_compensation_uses_intrinsic_blue_quality_not_compressed_rank_score():
    gp1 = add_blue(member(4, "GP1", []), "Power", 3)
    gp2 = add_blue(member(5, "GP2", []), "Power", 3)
    gp3 = add_blue(member(6, "GP3", []), "Power", 3)
    gp4 = add_blue(member(7, "GP4", []), "Power", 3)
    local = add_blue(add_red(member(2, "Local", [], gp1, gp2), "Sprint", 3), "Power", 3)
    remote = add_blue(member(3, "Remote", [], gp3, gp4), "Power", 3)
    config = base_config()
    config.update({
        "blue_star_quality": {"1": 0.12, "2": 0.78, "3": 1.0},
        "blue_neutral_score": 50.0,
        "blue_score_influence_by_distance": {"sprint": 0.45},
        "blue_stat_weights_by_distance": {
            "sprint": {"Speed": 0.65, "Stamina": 0.05, "Power": 1.0, "Guts": 0.35, "Wit": 0.45}
        },
        "aptitude_inheritance": {
            "distance": {
                "b_compensation": {
                    "minimum_probability_a": 0.0,
                    "minimum_probability_s": 0.0,
                    "minimum_white_score": 0.0,
                    "minimum_blue_score": 75.0,
                }
            }
        },
    })

    pair = evaluate_parent_pair(
        FakeResolver(), ace(distance_rank=5), local, remote,
        surface="turf", distance="sprint", style="pace_chaser",
        weight_lookup=lambda _key: 0.0, race_skills={}, config=config,
    )

    assert pair["components"]["blue"] < 75.0
    assert pair["distance_viability"]["blue_score"] == 100.0
    assert pair["distance_viability"]["key"] == "distance_b_compensated"




def test_pair_exposes_modern_individual_inheritance_affinities():
    local_gp1 = member(4, "Local GP1", ["A"])
    local_gp2 = member(5, "Local GP2", ["B"])
    remote_gp1 = member(6, "Remote GP1", ["C"])
    remote_gp2 = member(7, "Remote GP2", ["D"])
    local = member(2, "Local", ["A", "B", "Z"], local_gp1, local_gp2)
    remote = member(3, "Remote", ["C", "D", "Z"], remote_gp1, remote_gp2)

    pair = evaluate_parent_pair(
        FakeResolver(), ace(), local, remote,
        surface="turf", distance="medium", style="pace_chaser",
        weight_lookup=lambda _key: 0.0, race_skills={}, config=base_config(),
    )
    values = pair["affinity"]["inheritance_affinities"]["values"]
    assert values == {
        "parent_1": 32.0,
        "parent_1_grandparent_1": 10.0,
        "parent_1_grandparent_2": 11.0,
        "parent_2": 39.0,
        "parent_2_grandparent_1": 13.0,
        "parent_2_grandparent_2": 14.0,
    }


def test_distance_c_with_four_stars_starts_at_a_and_needs_one_proc_for_s():
    gp1 = add_red(member(4, "GP1", []), "Medium", 1)
    local = add_red(member(2, "Local", [], gp1, member(5, "GP2", [])), "Medium", 3)
    remote = member(3, "Remote", [], member(6, "GP3", []), member(7, "GP4", []))
    pair = evaluate_parent_pair(
        FakeResolver(), ace(distance_rank=5), local, remote,
        surface="turf", distance="medium", style="pace_chaser",
        weight_lookup=lambda _key: 0.0, race_skills={}, config=base_config(),
    )
    detail = pair["distance_s_summary"]
    assert detail["total_stars"] == 4
    assert detail["initial_rank_label"] == "A"
    assert detail["procs_required_for_a"] == 0
    assert detail["procs_required_for_s"] == 1
    assert pair["distance_viability"]["key"] == "ready_for_s"


def test_distance_c_with_three_stars_starts_at_b_and_needs_two_procs_for_s():
    local = add_red(
        member(2, "Local", [], member(4, "GP1", []), member(5, "GP2", [])),
        "Medium", 3,
    )
    remote = member(3, "Remote", [], member(6, "GP3", []), member(7, "GP4", []))
    pair = evaluate_parent_pair(
        FakeResolver(), ace(distance_rank=5), local, remote,
        surface="turf", distance="medium", style="pace_chaser",
        weight_lookup=lambda _key: 0.0, race_skills={}, config=base_config(),
    )
    detail = pair["distance_s_summary"]
    assert detail["initial_rank_label"] == "B"
    assert detail["procs_required_for_a"] == 1
    assert detail["procs_required_for_s"] == 2
    assert detail["probability_reach_s"] < detail["probability_reach_a"]
    assert pair["distance_viability"]["key"] == "distance_b_uncompensated"


def test_distance_b_can_only_be_promoted_by_all_compensation_checks():
    local = add_red(
        member(2, "Local", [], member(4, "GP1", []), member(5, "GP2", [])),
        "Medium", 3,
    )
    remote = member(3, "Remote", [], member(6, "GP3", []), member(7, "GP4", []))
    config = base_config()
    config["aptitude_inheritance"] = {
        "distance": {
            "b_compensation": {
                "minimum_probability_a": 0.0,
                "minimum_probability_s": 0.0,
                "minimum_white_score": 0.0,
                "minimum_blue_score": 0.0,
            }
        }
    }
    pair = evaluate_parent_pair(
        FakeResolver(), ace(distance_rank=5), local, remote,
        surface="turf", distance="medium", style="pace_chaser",
        weight_lookup=lambda _key: 0.0, race_skills={}, config=config,
    )
    assert pair["distance_viability"]["key"] == "distance_b_compensated"


def test_surface_and_style_b_are_scored_more_softly_than_distance_b():
    local = member(2, "Local", [], member(4, "GP1", []), member(5, "GP2", []))
    remote = member(3, "Remote", [], member(6, "GP3", []), member(7, "GP4", []))
    pair = evaluate_parent_pair(
        FakeResolver(), ace(distance_rank=6, surface_rank=6, style_rank=6), local, remote,
        surface="turf", distance="medium", style="pace_chaser",
        weight_lookup=lambda _key: 0.0, race_skills={}, config=base_config(),
    )
    aptitudes = pair["aptitude_summaries"]
    assert aptitudes["surface"]["score"] > aptitudes["distance"]["score"]
    assert aptitudes["style"]["score"] > aptitudes["surface"]["score"]


def test_online_parent_search_exports_canonical_pair_results(tmp_path, monkeypatch):
    import json
    import uma_moe

    local_gp1 = member(4, "Local GP1", ["A"])
    local_gp2 = member(5, "Local GP2", ["B"])
    remote_gp1 = member(6, "Remote GP1", ["C"])
    remote_gp2 = member(7, "Remote GP2", ["D"])
    local = member(2, "Local Parent", ["A", "B", "Z"], local_gp1, local_gp2)
    remote = member(3, "Remote Parent", ["C", "D", "Z"], remote_gp1, remote_gp2)
    remote["online"] = {
        "inheritance_id": 987,
        "friend_code": "123456789",
        "trainer_name": "Tester",
        "updated_at": "2026-07-14T00:00:00Z",
        "follow_status": "available",
    }
    incomplete_remote = member(8, "Incomplete Remote", [], None, None)
    incomplete_remote["online"] = {
        "inheritance_id": 988,
        "friend_code": "987654321",
        "trainer_name": "Incomplete",
    }

    linked_path = tmp_path / "linked.json"
    weights_path = tmp_path / "weights.json"
    race_path = tmp_path / "race.json"
    skill_path = tmp_path / "skills.json"
    config_path = tmp_path / "config.json"
    master_path = tmp_path / "master.mdb"
    master_path.write_bytes(b"fake")
    linked_path.write_text(json.dumps({"veterans": [local]}), encoding="utf-8")
    weights_path.write_text(json.dumps({"skills": {}}), encoding="utf-8")
    race_path.write_text(json.dumps({"race_factors": []}), encoding="utf-8")
    skill_path.write_text(json.dumps({"skills": []}), encoding="utf-8")
    config_path.write_text(json.dumps(base_config()), encoding="utf-8")

    class FakeNormalizer:
        def __init__(self, _master):
            pass

        def close(self):
            pass

        def normalize_records(self, _payload):
            return [remote, incomplete_remote], {"normalized_count": 2}

    class SearchResolver(FakeResolver):
        def __init__(self, _master):
            pass

        def ace_details(self, _card_id, _surface, _distance, _style):
            return {"card_id": 100, "card_name": "Ace", **ace()}

        def close(self):
            pass

    monkeypatch.setattr(uma_moe, "OnlineRecordNormalizer", FakeNormalizer)
    monkeypatch.setattr(uma_moe, "AffinityResolver", SearchResolver)

    result = uma_moe.rank_online_parent_pairs(
        master_path,
        linked_path,
        weights_path,
        race_path,
        skill_path,
        tmp_path,
        ace_card_id=100,
        fixed_parent_trained_id=20,
        surface="turf",
        distance="medium",
        style="pace_chaser",
        raw_payload={"items": []},
        scoring_config_path=config_path,
        top_n=10,
    )

    assert result.result_count == 1
    assert result.pair_mode == "fixed_local_parent"
    assert result.top_results[0]["affinity"]["total"] == 63
    assert result.top_results[0]["fixed_parent"]["card_name"] == "Local Parent"
    assert result.top_results[0]["candidate"]["online"]["friend_code"] == "123456789"
    payload = json.loads(result.rankings_json_path.read_text(encoding="utf-8"))
    assert payload["metadata"]["scoring_engine"] == "parent_optimizer.evaluate_parent_pair"
    assert payload["metadata"]["complete_branch_validation"]["remote_incomplete_excluded"] == 1
    assert payload["results"][0]["component_details"]["blue"]["slot_count"] == 6
    assert result.rankings_csv_path.is_file()
    assert result.diagnostics_path.is_file()


def test_white_skill_score_uses_individual_affinity_and_combines_duplicate_carriers():
    parent = add_white(member(2, "Parent", []), "Uma Stan", 3)
    grandparent = add_white(member(3, "Grandparent", []), "Uma Stan", 3)
    score, detail = _white_score(
        [
            (parent, "parent", "parent"),
            (grandparent, "grandparent", "grandparent"),
        ],
        lambda key: 1.0 if key == "uma_stan" else 0.0,
        {
            "white_inheritance": {
                "base_proc_rates": {"1": 0.03, "2": 0.06, "3": 0.09},
                "inspiration_event_count": 2,
                "per_event_probability_cap": 1.0,
            },
            "white_saturation": {"parent_pair": 1.0},
        },
        "parent_pair",
        inheritance_affinities={"parent": 100.0, "grandparent": 0.0},
    )

    skill = detail["top_skills"][0]
    factors = {row["role"]: row for row in detail["top_factors"]}
    expected = 1.0 - (1.0 - 0.18) ** 2 * (1.0 - 0.09) ** 2

    assert abs(skill["probability_at_least_once"] - expected) < 1e-8
    assert factors["parent"]["proc_probability_per_event"] == 0.18
    assert factors["grandparent"]["proc_probability_per_event"] == 0.09
    assert factors["parent"]["standalone_contribution"] > factors["grandparent"]["standalone_contribution"]
    assert abs(skill["probability_contribution"] - expected) < 1e-8
    assert skill["probability_utility"] > skill["probability_at_least_once"]
    assert score > 0.0



def test_white_diversity_curve_prefers_several_meaningful_rare_skills_over_one_concentrated_skill():
    diversified_members = [
        (add_white(member(20, "D1", []), "Slipstream", 1), "parent", "d1"),
        (add_white(member(21, "D2", []), "Playtime's Over!", 1), "parent", "d2"),
        (add_white(member(22, "D3", []), "Uma Stan", 1), "parent", "d3"),
    ]
    concentrated_members = [
        (add_white(member(23, "C1", []), "Uma Stan", 3), "parent", "c1"),
    ]
    config = {
        "white_inheritance": {
            "base_proc_rates": {"1": 0.20, "2": 0.40, "3": 0.80},
            "inspiration_event_count": 1,
            "per_event_probability_cap": 1.0,
            "distinct_skill_probability_curve": [
                [0.0, 0.0],
                [0.10, 0.10],
                [0.20, 0.30],
                [0.40, 0.52],
                [0.60, 0.64],
                [0.80, 0.70],
                [1.0, 0.73],
            ],
        },
        "white_saturation": {"parent_pair": 10.0},
    }
    diversified_score, diversified = _white_score(
        diversified_members,
        lambda _key: 1.0,
        config,
        "parent_pair",
        inheritance_affinities={"d1": 0.0, "d2": 0.0, "d3": 0.0},
    )
    concentrated_score, concentrated = _white_score(
        concentrated_members,
        lambda _key: 1.0,
        config,
        "parent_pair",
        inheritance_affinities={"c1": 0.0},
    )

    assert abs(diversified["probability_raw"] - 0.60) < 1e-12
    assert abs(concentrated["probability_raw"] - 0.80) < 1e-12
    assert abs(diversified["raw"] - 0.90) < 1e-12
    assert abs(concentrated["raw"] - 0.70) < 1e-12
    assert diversified_score > concentrated_score
    assert diversified["skill_count"] == 3
    assert concentrated["skill_count"] == 1

def test_parent_pair_white_score_receives_exact_six_member_affinities():
    local_gp1 = add_white(member(4, "Local GP1", ["A"]), "Uma Stan", 3)
    local_gp2 = member(5, "Local GP2", [])
    remote_gp1 = member(6, "Remote GP1", [])
    remote_gp2 = member(7, "Remote GP2", [])
    local = add_white(member(2, "Local", ["A", "Z"], local_gp1, local_gp2), "Uma Stan", 3)
    remote = member(3, "Remote", ["Z"], remote_gp1, remote_gp2)
    config = base_config()
    config["mode_weights"] = {"parent_branch": {"white_skill": 1.0}, "parent_pair": {"white_skill": 1.0}}
    config["white_inheritance"] = {
        "base_proc_rates": {"1": 0.03, "2": 0.06, "3": 0.09},
        "inspiration_event_count": 2,
        "per_event_probability_cap": 1.0,
    }

    pair = evaluate_parent_pair(
        FakeResolver(), ace(), local, remote,
        surface="turf", distance="medium", style="pace_chaser",
        weight_lookup=lambda key: 1.0 if key == "uma_stan" else 0.0,
        race_skills={}, config=config,
    )

    factors = {row["role"]: row for row in pair["component_details"]["white_skill"]["top_factors"]}
    affinities = pair["affinity"]["inheritance_affinities"]["values"]
    assert factors["parent_1"]["inheritance_affinity"] == affinities["parent_1"]
    assert factors["parent_1_grandparent_1"]["inheritance_affinity"] == affinities["parent_1_grandparent_1"]
    assert factors["parent_1"]["proc_probability_per_event"] > factors["parent_1_grandparent_1"]["proc_probability_per_event"]


def test_parent_white_score_combines_race_and_direct_white_using_actual_base_rates():
    direct = add_white(member(30, "Direct", []), "Fall Runner ○", 3)
    race = add_race(member(31, "Race", []), "Tenno Sho (Autumn)", 3)
    score, detail = _white_score(
        [(direct, "parent", "direct"), (race, "grandparent", "race")],
        lambda key: 1.0 if key == "fall_runner" else 0.0,
        {
            "white_inheritance": {
                "base_proc_rates": {"1": 0.03, "2": 0.06, "3": 0.09},
                "race_base_proc_rates": {"1": 0.01, "2": 0.02, "3": 0.03},
                "inspiration_event_count": 2,
                "per_event_probability_cap": 1.0,
            },
            "white_saturation": {"parent_pair": 1.0},
        },
        "parent_pair",
        inheritance_affinities={"direct": 0.0, "race": 0.0},
        race_skill_map={"Tenno Sho (Autumn)": ["fall_runner"]},
    )

    skill = detail["top_skills"][0]
    expected = 1.0 - (1.0 - 0.09) ** 2 * (1.0 - 0.03) ** 2
    assert abs(skill["probability_at_least_once"] - expected) < 1e-8
    assert skill["source_types"] == ["white_race", "white_skill"]
    factors = {row["source_type"]: row for row in detail["top_factors"]}
    assert factors["white_skill"]["proc_probability_per_event"] == 0.09
    assert factors["white_race"]["proc_probability_per_event"] == 0.03
    assert score > 0.0


def test_race_scenario_component_no_longer_scores_granted_skill_weight():
    race = add_race(member(32, "Race", []), "Tenno Sho (Autumn)", 3)
    config = {
        "position_transmission": {"parent": 1.0},
        "star_quality": {"1": 0.33, "2": 0.67, "3": 1.0},
        "race_factor": {
            "base_per_star_quality": 0.025,
            "granted_skill_multiplier": 99.0,
            "scenario_per_star_quality": 0.06,
        },
        "race_saturation": {"parent_pair": 1.0},
    }
    high_weight, detail_high = _race_scenario_score(
        [(race, "parent", "parent")],
        lambda _key: 100.0,
        {"Tenno Sho (Autumn)": ["fall_runner"]},
        config,
        "parent_pair",
    )
    zero_weight, _ = _race_scenario_score(
        [(race, "parent", "parent")],
        lambda _key: 0.0,
        {"Tenno Sho (Autumn)": ["fall_runner"]},
        config,
        "parent_pair",
    )
    assert high_weight == zero_weight
    assert detail_high["top_factors"][0]["granted_skills_scored_in"] == "white_skill"
