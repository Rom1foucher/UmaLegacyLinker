from __future__ import annotations

import itertools
import random
from copy import deepcopy

from uma_legacy_linker.transfer_portfolio import minimum_portfolio
from uma_legacy_linker.transfer_helper import (
    _loop_protection_report,
    _resolve_loop_presets,
    _select_portfolio,
    classify_portfolio_records,
)


def test_exact_search_improves_a_greedy_cover():
    result = minimum_portfolio(range(5), [{0, 1}, {0, 2}, {1, 3}, {2, 4}],
                               priorities={0: (100,), 1: (70,), 2: (60,)})
    assert result.greedy_count == 3
    assert result.selected == {1, 2}
    assert result.optimal


def test_solver_matches_exhaustive_oracle_on_small_portfolios():
    rng = random.Random(715)
    for _ in range(150):
        pool = set(range(7))
        requirements = [{i for i in pool if rng.random() < .4} for _ in range(9)]
        requirements = [v or {rng.randrange(7)} for v in requirements]
        mandatory = {0} if rng.random() < .5 else set()
        oracle = min(len(mandatory | set(choice))
                     for n in range(8) for choice in itertools.combinations(pool, n)
                     if all(v & (mandatory | set(choice)) for v in requirements))
        actual = minimum_portfolio(pool, requirements, mandatory)
        assert actual.optimal
        assert len(actual.selected) == oracle
        assert mandatory <= actual.selected


def test_node_budget_never_relaxes_requirements():
    constraints = [{0, 1}, {0, 2}, {1, 3}, {2, 4}]
    result = minimum_portfolio(range(5), constraints, priorities={0: (100,)}, node_budget=1)
    assert not result.optimal
    assert all(set(result.selected) & values for values in constraints)


def record(trained_id, scores, *, locked=False):
    return {
        "trained_chara_id": trained_id, "rank_score": 1000, "is_locked": locked,
        "_parent_profiles": [{"context_key": "turf:long", "profile": "Long",
                              "score": max(scores), "utility": 1., "ace_scores": scores,
                              "ace_competitive": [True] * len(scores), "ace_ids": [100 + i for i in range(len(scores))]}],
        "_grandparent_profiles": [],
    }


def select(records, veterans=None):
    return _select_portfolio({"group": list(range(len(records)))}, records,
                             veterans or [{"factors": {"by_type": {}}} for _ in records],
                             competitive_score_floor=67.5, competitive_utility_floor=.78,
                             minimum_absolute_floor_ratio=.8, regret_tolerance=2.5,
                             spark_protection_config={})


def test_best_envelopes_do_not_hide_cross_ace_losses():
    records = [record(1, [85., 65.]), record(2, [70., 90.])]
    chosen, requirements = select(records)
    assert chosen == {0, 1}
    assert len([r for r in requirements['group'].values() if r['kind'] == 'performance']) == 2


def test_protected_redundancy_is_reported_without_transfer_eligibility():
    records = [record(1, [70., 68.], locked=True), record(2, [80., 85.])]
    chosen, requirements = select(records)
    classify_portfolio_records(records, {"group": [0, 1]}, chosen, requirements, {},
                               dominance_mean_margin=1., spark_protection_config={})
    assert records[0]['status'] == 'protected'
    assert records[0]['analysis_status'] == 'recommended_transfer'
    assert records[0]['transfer_eligible'] is False
    assert records[0]['portfolio_comparison']['worst_context']['ace_card_id'] == 100
    assert records[1]['status'] == 'keep'
    assert records[1]['transfer_eligible'] is False


def test_three_star_stat_specialists_are_preserved():
    records = [record(1, [80.]), record(2, [90.])]
    veterans = [{"factors": {"by_type": {"blue_stat": [{"name": name, "stars": 3}]}}}
                for name in ("Stamina", "Power")]
    chosen, _ = select(records, veterans)
    assert chosen == {0, 1}


def test_g1_pair_support_is_preserved_collectively():
    records = [record(1, [80.]), record(2, [90.]), record(3, [70.])]
    veterans = [{"chara_id": chara, "g1_wins": {"names": names}, "factors": {"by_type": {}}}
                for chara, names in [(1, ['A']), (1, ['B']), (2, ['A'])]]
    chosen, requirements = _select_portfolio({'group': [0, 1], 'partner': [2]}, records, veterans,
                                            competitive_score_floor=67.5, competitive_utility_floor=.78,
                                            minimum_absolute_floor_ratio=.8, regret_tolerance=2.5,
                                            spark_protection_config={'preserve_local_g1_pair_support': True})
    assert chosen == {0, 1, 2}
    assert any(r['kind'] == 'g1_pair' for r in requirements['group'].values())


def test_active_loop_carrier_remains_mandatory():
    records = [record(1, [60.]), record(2, [90.])]
    records[0]['active_loop_project'] = True
    chosen, _ = select(records)
    assert 0 in chosen
    assert records[0]['manual_protection_reasons'] == ['active_loop_project']


def test_empty_loop_protection_preserves_the_existing_portfolio():
    records = [record(1, [84.]), record(2, [81.]), record(3, [75.])]
    veterans = [{"factors": {"by_type": {}}} for _ in records]
    baseline_records = deepcopy(records)
    empty_records = deepcopy(records)
    kwargs = dict(
        competitive_score_floor=67.5,
        competitive_utility_floor=.78,
        minimum_absolute_floor_ratio=.8,
        regret_tolerance=2.5,
        spark_protection_config={},
    )
    baseline = _select_portfolio({"group": [0, 1, 2]}, baseline_records, veterans, **kwargs)
    empty = _select_portfolio(
        {"group": [0, 1, 2]}, empty_records, veterans,
        loop_protection_config={"skills": [], "carriers_per_skill": 2}, **kwargs
    )
    assert empty == baseline


def test_loop_carriers_are_ranked_globally_and_added_as_singletons():
    records = [record(1, [84.]), record(2, [81.]), record(3, [75.])]
    records[0]["_spark_heritage"] = {"skills": {"white_one": {
        "white_generation_carrier_count": 1, "direct": True,
        "direct_white_max_stars": 3, "name": "White One",
    }}}
    records[1]["_spark_heritage"] = {"skills": {"white_one": {
        "white_generation_carrier_count": 3, "direct": False,
        "direct_white_max_stars": 0, "name": "White One",
    }}}
    records[2]["_spark_heritage"] = {"skills": {"white_one": {
        "white_generation_carrier_count": 3, "direct": True,
        "direct_white_max_stars": 2, "name": "White One",
    }}}
    veterans = [{"factors": {"by_type": {}}} for _ in records]
    chosen, requirements = _select_portfolio(
        {"group": [0, 1, 2]}, records, veterans,
        competitive_score_floor=67.5,
        competitive_utility_floor=.78,
        minimum_absolute_floor_ratio=.8,
        regret_tolerance=2.5,
        spark_protection_config={},
        loop_protection_config={"skills": ["white_one"], "carriers_per_skill": 2},
    )
    loop_requirements = [
        item for item in requirements["group"].values() if item["kind"] == "loop_skill"
    ]
    assert [next(iter(item["covered_by"])) for item in loop_requirements] == [2, 1]
    assert {1, 2} <= chosen
    assert all(len(item["covered_by"]) == 1 for item in loop_requirements)


def test_loop_protection_report_counts_additional_copies_once():
    report = _loop_protection_report(
        {"skills": ["one", "two", "three"], "carriers_per_skill": 2},
        [
            {"trained_chara_id": 10, "_spark_heritage": {"skills": {
                "one": {"white_generation_carrier_count": 3},
                "two": {"white_generation_carrier_count": 2},
            }}},
            {"trained_chara_id": 11, "_spark_heritage": {"skills": {
                "one": {"white_generation_carrier_count": 1},
            }}},
        ],
        {"group": {
            "loop:one:1": {
                "kind": "loop_skill", "skill_key": "one", "covered_by": {0},
                "loop_presence_count": 3, "was_previously_selected": False,
            },
            "loop:two:1": {
                "kind": "loop_skill", "skill_key": "two", "covered_by": {0},
                "loop_presence_count": 2, "was_previously_selected": False,
            },
            "loop:one:2": {
                "kind": "loop_skill", "skill_key": "one", "covered_by": {1},
                "loop_presence_count": 1, "was_previously_selected": True,
            },
        }},
    )
    assert report["additional_retained_copy_count"] == 1
    assert report["skills_without_carriers"] == ["three"]
    assert len(report["selected_carriers"]["one"]) == 2


def test_loop_presets_include_the_common_package():
    presets = _resolve_loop_presets({
        "presets": ["front", "late"],
        "preset_skills": {
            "common": ["stamina"],
            "front": ["groundwork", "dodging_danger"],
            "pace": ["groundwork", "nimble_navigator", "uma_stan"],
            "late": ["uma_stan", "pedal_to_the_metal", "tail_held_high", "nimble_navigator"],
            "end": ["uma_stan", "restraint", "tail_held_high", "nimble_navigator"],
        },
    })
    assert presets["front"] == ["stamina", "groundwork", "dodging_danger"]
    assert presets["late"] == [
        "stamina", "uma_stan", "pedal_to_the_metal", "tail_held_high", "nimble_navigator"
    ]


def _loop_records(skills_by_index):
    rows = [record(index + 1, [score]) for index, score in enumerate([90., 85., 70.])]
    for index, skills in enumerate(skills_by_index):
        rows[index]["rank_score"] = 1000 - index
        rows[index]["_spark_heritage"] = {"skills": skills}
    return rows


def _select_with_front_loop(records):
    veterans = [{"factors": {"by_type": {}}} for _ in records]
    return _select_portfolio(
        {"group": list(range(len(records)))}, records, veterans,
        competitive_score_floor=67.5,
        competitive_utility_floor=.78,
        minimum_absolute_floor_ratio=.8,
        regret_tolerance=2.5,
        spark_protection_config={},
        loop_protection_config={
            "skills": [], "presets": ["front"],
            "preset_skills": {"common": ["a"], "front": ["b"]},
        },
    )


def test_preset_package_tie_breaks_by_direct_skill_count_before_performance():
    records = _loop_records([
        {"a": {"white_generation_carrier_count": 3}, "b": {"white_generation_carrier_count": 2}},
        {"a": {"white_generation_carrier_count": 3, "direct": True},
         "b": {"white_generation_carrier_count": 2, "direct": True}},
        {"a": {"white_generation_carrier_count": 2, "direct": True},
         "b": {"white_generation_carrier_count": 3}},
    ])
    records[0]["rank_score"] = 10000
    chosen, requirements = _select_with_front_loop(records)
    branches = [item for item in requirements["group"].values() if item["kind"] == "loop_preset"]
    assert [next(iter(item["covered_by"])) for item in branches] == [1, 2]
    assert {1, 2} <= chosen


def test_preset_floor_keeps_a_best_skill_source_missing_from_top_branches():
    records = _loop_records([
        {"a": {"white_generation_carrier_count": 2}, "b": {"white_generation_carrier_count": 3}},
        {"a": {"white_generation_carrier_count": 2}, "b": {"white_generation_carrier_count": 3}},
        {"a": {"white_generation_carrier_count": 3}, "b": {"white_generation_carrier_count": 0}},
    ])
    chosen, requirements = _select_with_front_loop(records)
    floors = [item for item in requirements["group"].values() if item["kind"] == "loop_floor"]
    assert [item["skill_key"] for item in floors] == ["a"]
    assert next(iter(floors[0]["covered_by"])) == 2
    assert 2 in chosen


def test_preset_floor_is_skipped_when_a_top_branch_keeps_the_best_presence():
    records = _loop_records([
        {"a": {"white_generation_carrier_count": 3}, "b": {"white_generation_carrier_count": 2}},
        {"a": {"white_generation_carrier_count": 2}, "b": {"white_generation_carrier_count": 3}},
        {"a": {"white_generation_carrier_count": 1}, "b": {"white_generation_carrier_count": 1}},
    ])
    _chosen, requirements = _select_with_front_loop(records)
    assert not [item for item in requirements["group"].values() if item["kind"] == "loop_floor"]


def test_overlapping_presets_reuse_the_same_retained_copy():
    records = _loop_records([
        {key: {"white_generation_carrier_count": 2} for key in ("common", "late", "end")},
        {key: {"white_generation_carrier_count": 2} for key in ("common", "late", "end")},
        {"common": {"white_generation_carrier_count": 1}},
    ])
    veterans = [{"factors": {"by_type": {}}} for _ in records]
    chosen, requirements = _select_portfolio(
        {"group": [0, 1, 2]}, records, veterans,
        competitive_score_floor=67.5, competitive_utility_floor=.78,
        minimum_absolute_floor_ratio=.8, regret_tolerance=2.5,
        spark_protection_config={},
        loop_protection_config={
            "skills": [], "presets": ["late", "end"],
            "preset_skills": {
                "common": ["common"], "late": ["late"], "end": ["end"],
            },
        },
    )
    selected_branches = [
        next(iter(item["covered_by"]))
        for item in requirements["group"].values() if item["kind"] == "loop_preset"
    ]
    assert len(selected_branches) == 4
    assert set(selected_branches) == {0, 1}
    assert len(chosen) == len(set(chosen))
