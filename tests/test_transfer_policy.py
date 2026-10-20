from copy import deepcopy

import pytest

from tests.test_transfer_comparison import comparison_fixture
from tests.test_transfer_portfolio import record
from uma_legacy_linker.transfer_comparison import comparison_evaluation, frozen_veteran
from uma_legacy_linker.transfer_helper import _select_portfolio
from uma_legacy_linker.transfer_policy import transfer_scoring_config, restrict_heritage
from uma_legacy_linker.veteran_identity import game_rank_label, game_veteran_label


def test_local_g1_pairs_do_not_drive_default_retention():
    records = [record(1, [80.]), record(2, [90.]), record(3, [70.])]
    veterans = [{'chara_id': chara, 'g1_wins': {'names': names}, 'factors': {'by_type': {}}}
                for chara, names in [(1, ['A']), (1, ['B']), (2, ['A'])]]
    chosen, requirements = _select_portfolio({'group': [0, 1], 'partner': [2]}, records, veterans,
        competitive_score_floor=67.5, competitive_utility_floor=.78,
        minimum_absolute_floor_ratio=.8, regret_tolerance=2.5, spark_protection_config={})
    assert chosen == {1, 2}
    assert all(item['kind'] != 'g1_pair' for item in requirements['group'].values())


def test_ordinary_white_protection_is_removed_but_score_factors_are_retained():
    heritage = {'skills': {key: {'protection_signals': [{'reason_code': 'rare'}], 'total_stars': 3}
                          for key in ('straightaway_adept', 'all_ive_got', 'straight_descent', 'uma_stan')},
                'packages': [{'key': 'generic_core', 'protection_rank': 2}]}
    restricted = restrict_heritage(heritage, {})
    assert restricted['skills']['straight_descent']['protection_signals']
    for key in ('straightaway_adept', 'all_ive_got', 'uma_stan'):
        assert not restricted['skills'][key]['protection_signals']
        assert restricted['skills'][key]['total_stars'] == 3
    assert not restricted['packages']
    assert heritage['packages']  # Policy must not mutate upstream data.


def test_gp_ancestry_cannot_improve_retention_score():
    veteran, candidate, model = comparison_fixture()
    model['config'] = transfer_scoring_config(model['config'])
    first = comparison_evaluation(candidate, model, 'context', 0, 'grandparent')
    revised = deepcopy(veteran)
    revised['when_used_as_parent'] = {}
    other = dict(candidate, comparison_veteran=frozen_veteran(revised))
    second = comparison_evaluation(other, model, 'context', 0, 'grandparent')
    assert first['score'] == pytest.approx(second['score'])
    assert first['contributions']['affinity'] == 0
    assert first['contributions']['white_generation'] == 0
    assert model['config']['mode_weights']['parent_branch']['blue'] == .20


def test_transfer_policy_does_not_change_other_optimizers():
    _, _, model = comparison_fixture()
    original = deepcopy(model['config'])
    transfer_scoring_config(model['config'])
    assert model['config'] == original


@pytest.mark.parametrize('rank,label', [(12, 'B+'), (13, 'A'), (14, 'A+'), (19, 'UG'), (21, 'UG2'), (22, 'UG3'), (29, 'UF'), (None, '—')])
def test_actual_game_ranks(rank, label):
    assert game_rank_label(rank) == label


def test_frozen_game_identity_and_alternative_branch_scope():
    pytest.importorskip("PySide6")
    from ui_qt.transfer_lineage import comparison_nodes
    veteran, candidate, _ = comparison_fixture()
    veteran.update(rank=21, rank_score=20507)
    candidate['comparison_veteran'] = frozen_veteran(veteran)
    alternative = deepcopy(candidate)
    assert 'UG2 · 20 507' in game_veteran_label(candidate['comparison_veteran'])
    nodes = comparison_nodes((candidate, alternative), 'grandparent')
    assert set(nodes) == {'p1', 'p2'}
    assert not any(n.get('historical') for n in nodes.values())
    nodes = comparison_nodes((candidate, alternative), 'grandparent', history=True)
    assert nodes['p1-1']['historical']
    assert nodes['p1-1']['rank_score'] is None  # Snapshot has no game score.
    assert 'target' not in comparison_nodes((candidate, alternative), 'parent')
