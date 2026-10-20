from copy import deepcopy

import pytest

from tests.test_transfer_comparison import comparison_fixture
from ui_qt.transfer_explanation import comparison_explanation, explanation_html, fact_text
from uma_legacy_linker.transfer_comparison import comparison_evaluation


def saved_pair():
    _, candidate, model = comparison_fixture()
    candidate['comparison_veteran']['factors']['by_type']['blue_stat'][0]['stars'] = 1
    target = deepcopy(candidate)
    target['trained_chara_id'] = 2
    target['comparison_veteran']['factors']['by_type']['blue_stat'][0]['stars'] = 3
    target['comparison_veteran']['factors']['by_type']['white_skill'][0]['stars'] = 1
    model['config']['mode_weights']['parent_branch'] = {'blue': .9, 'white_skill': .1}
    model['skill_labels'] = {'uma_stan': 'Uma Stan'}
    for record in (candidate, target):
        record['comparison_profiles'] = {
            role: {'context': [comparison_evaluation(record, model, 'context', 0, role)['score']]}
            for role in ('parent', 'grandparent')}
    return candidate, target, model


def test_a_positive_total_still_exposes_a_skill_concession_in_the_same_case():
    candidate, target, model = saved_pair()
    result = comparison_explanation(candidate, target, model, 'context', 0, 'parent')
    assert result['available'] and result['delta'] > 0
    assert any(f['name'] == 'Stamina' and f['left'] == 1 and f['right'] == 3 for f in result['gains'])
    loss = next(f for f in result['losses'] if f['name'] == 'Uma Stan')
    assert loss['left'] > loss['right']
    assert sum(c['delta'] for c in result['components']) == pytest.approx(result['delta'])
    html = explanation_html(result, lambda s: s)
    assert 'Ce qu’on perd' in html and 'Uma Stan' in html
    assert 'chance dans le modèle' in fact_text(loss, lambda s: s)


@pytest.mark.parametrize('saved', [None, float('nan'), float('inf'), 999])
def test_missing_nonfinite_or_mismatched_saved_scores_cannot_support_a_reason(saved):
    candidate, target, model = saved_pair()
    target['comparison_profiles']['parent']['context'][0] = saved
    assert not comparison_explanation(candidate, target, model, 'context', 0, 'parent')['available']


def test_gp_evidence_excludes_the_farming_history_and_does_not_invent_inheritance_odds():
    candidate, target, model = saved_pair()
    grandparents = target['comparison_veteran']['when_used_as_parent']
    grandparents['grandparent_1']['factors']['by_type']['blue_stat'][0]['stars'] = 3
    target['comparison_profiles']['grandparent']['context'][0] = comparison_evaluation(
        target, model, 'context', 0, 'grandparent')['score']
    result = comparison_explanation(candidate, target, model, 'context', 0, 'grandparent')
    assert result['available']
    assert not any(f['name'] == 'Power' for f in result['gains'] + result['losses'])
    loss = next(f for f in result['losses'] if f['name'] == 'Uma Stan')
    text = fact_text(dict(loss, role='grandparent'), lambda s: s)
    assert '3★ → 1★' in text
    assert 'chance' not in text
    assert 'sources propres' in text


def test_unchanged_factors_are_not_used_as_fabricated_explanations():
    candidate, _, model = saved_pair()
    result = comparison_explanation(candidate, deepcopy(candidate), model, 'context', 0, 'parent')
    assert result['available'] and result['delta'] == 0
    assert result['gains'] == result['losses'] == []
    assert 'Aucune différence pertinente identifiée' in explanation_html(result, lambda s: s)
    assert 'Aucune perte' not in explanation_html(result, lambda s: s)


def test_without_frozen_factors_the_explanation_stays_explicitly_unavailable():
    candidate, target, model = saved_pair()
    del target['comparison_veteran']
    result = comparison_explanation(candidate, target, model, 'context', 0, 'parent')
    assert result == {'available': False}
    assert 'Décomposition indisponible' in explanation_html(result, lambda s: s)


def test_old_gp_models_that_weight_history_are_explicitly_identified():
    candidate, target, model = saved_pair()
    model['config']['mode_weights']['future_grandparent'] = {'white_generation': 1}
    for record in (candidate, target):
        record['comparison_profiles']['grandparent']['context'][0] = comparison_evaluation(
            record, model, 'context', 0, 'grandparent')['score']
    result = comparison_explanation(candidate, target, model, 'context', 0, 'grandparent')
    assert result['available'] and result['includes_history']
    html = explanation_html(result, lambda s: s)
    assert 'génération White historique contribue' in html
    assert 'seuls les facteurs propres comptent' not in html
