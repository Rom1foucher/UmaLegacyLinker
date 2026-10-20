from __future__ import annotations

import itertools
import random

from uma_legacy_linker.transfer_portfolio import minimum_portfolio
from uma_legacy_linker.transfer_helper import _select_portfolio, classify_portfolio_records


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
