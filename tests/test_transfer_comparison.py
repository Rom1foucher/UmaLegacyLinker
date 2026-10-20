from __future__ import annotations

import json
from pathlib import Path

import pytest

from uma_legacy_linker.transfer_comparison import comparison_evaluation, frozen_veteran, factor_inventory
from uma_legacy_linker.solver_pairs import PairPreparation
from uma_legacy_linker.parent_optimizer import _white_score, _lineage_members


def comparison_fixture():
    config = json.loads((Path(__file__).resolve().parents[1] / 'resources/default_parent_scoring.json').read_text())
    veteran = {
        'trained_chara_id': 1, 'card_id': 100101, 'chara_id': 1001, 'card_name': 'Test Uma',
        'factors': {'by_type': {
            'blue_stat': [{'name': 'Stamina', 'stars': 3, 'factor_group_id': 2}],
            'red_aptitude': [{'name': 'Long', 'stars': 3, 'factor_group_id': 34}],
            'white_skill': [{'name': 'Uma Stan', 'stars': 3, 'factor_group_id': 2001}],
            'scenario': [{'name': 'Scenario with MDB effects', 'stars': 2, 'factor_group_id': 901,
                          'effects': [{'target_label': 'stamina'}, {'target_label': 'power'}]}],
        }},
        'g1_wins': {'names': ['A', 'B']},
        'when_used_as_parent': {'grandparent_1': {
            'chara_id': 1002, 'factors': {'by_type': {
                'blue_stat': [{'name': 'Power', 'stars': 2, 'factor_group_id': 3}],
                'white_skill': [{'name': 'Uma Stan', 'stars': 2, 'factor_group_id': 2001}],
            }}, 'g1_wins': {'names': ['A']},
        }},
    }
    ace = {'chara_id': 1003, 'card_id': 100301, 'card_name': 'Ace',
           'target_aptitudes': {dimension: {'rank': 7, 'label': 'A'}
                                for dimension in ['surface', 'distance', 'style']}}
    model = {'config': config, 'race_skills': {}, 'contexts': {'context': {
        'surface': 'turf', 'distance': 'long', 'style': 'late_surger',
        'label': 'Long · Late', 'aces': [ace], 'skill_weights': {'uma_stan': 1.},
    }}}
    record = {'trained_chara_id': 1, 'card_name': 'Test Uma', 'comparison_veteran': frozen_veteran(veteran),
              'comparison_affinities': {'1003': [130., 90., 0., 160.]}}
    return veteran, record, model


@pytest.mark.parametrize('role', ['parent', 'grandparent'])
def test_frozen_report_reconstructs_the_original_score_and_scenario_effects(role):
    veteran, record, model = comparison_fixture()
    frozen = comparison_evaluation(record, model, 'context', 0, role)
    original = comparison_evaluation(dict(record, comparison_veteran=veteran), model, 'context', 0, role)
    assert frozen['score'] == original['score']
    assert frozen['components'] == original['components']
    assert frozen['details']['blue']['scenario_inheritance']['factors'][0]['stat_targets']
    assert abs(sum(frozen['contributions'].values()) - frozen['score']) < 1e-9


def test_white_preparation_matches_canonical_scoring():
    veteran, _, model = comparison_fixture()
    lookup = lambda key: .9 if key == 'uma_stan' else 0.
    prep = PairPreparation(None, {}, model['config'], lookup, {})
    for affinity in [0., 50., 99., 150., 500.]:
        values = {'parent': affinity, 'grandparent_1': affinity / 2.}
        reference = _white_score(_lineage_members(veteran), lookup, model['config'], 'parent_branch', values)[0]
        prepared = prep.white_score(_lineage_members(veteran), values, 'parent_branch', lambda: None)[0]
        assert abs(prepared - reference) < 1e-12


def test_factor_inventory_separates_direct_and_branch_sources():
    _, record, _ = comparison_fixture()
    branch = factor_inventory(record, 'parent')['white_skill', '2001']
    direct = factor_inventory(record, 'grandparent')['white_skill', '2001']
    assert branch['stars'] == 5
    assert branch['direct_stars'] == 3
    assert branch['carriers'] == [('parent', 3), ('grandparent_1', 2)]
    assert direct['stars'] == 3


def test_same_character_parent_is_not_comparable():
    _, record, model = comparison_fixture()
    model['contexts']['context']['aces'][0]['chara_id'] = 1001
    assert comparison_evaluation(record, model, 'context', 0, 'parent')['score'] is None
