from copy import deepcopy

from ui_qt.transfer_decision import decision_examples, decision_html, preserved_reasons


def fixture():
    candidate = {'trained_chara_id': 1, 'comparison_group': 'same',
                 'status': 'recommended_transfer', 'rank_score': 9000,
                 'card_name': 'Opera', 'comparison_profiles': {
                     'parent': {'a': [50], 'b': [60]}, 'grandparent': {'a': [40]}}}
    target = {'trained_chara_id': 2, 'comparison_group': 'same',
              'selected_in_portfolio': True, 'rank_score': 12000, 'card_name': 'Opera',
              'comparison_profiles': {
                  'parent': {'a': [49], 'b': [80]}, 'grandparent': {'a': [45]}}}
    model = {'contexts': {key: {'scope': 'permanent', 'aces': [{'card_id': 3, 'card_name': 'Ace'}]}
                           for key in ('a', 'b')}}
    candidate['portfolio_comparison'] = {'context_deltas': [
        {'role': role, 'context_key': key, 'ace_card_id': 3,
         'candidate_score': left, 'replacement_score': right,
         'retained_by': [{'trained_chara_id': 2}]}
        for role, key, left, right in [('parent', 'a', 50, 49), ('parent', 'b', 60, 80),
                                      ('grandparent', 'a', 40, 45)]]}
    return candidate, target, model


def test_examples_prioritise_actual_losses_and_retained_copies():
    candidate, target, model = fixture()
    examples = decision_examples(candidate, [candidate, target], model)
    assert [e['delta'] for e in examples] == [-1, 5]
    assert all(e['target'] is target for e in examples)
    html = decision_html(candidate, examples, 'fr', lambda text: text)
    assert '12 000' in html
    assert 'conserve un avantage ici' in html
    assert 'example:0' in html
    assert '#2' not in html


def test_unretained_copy_or_mismatched_saved_scores_cannot_be_used_as_proof():
    candidate, target, model = fixture()
    target['selected_in_portfolio'] = False
    assert decision_examples(candidate, [candidate, target], model) == []
    target['selected_in_portfolio'] = True
    target['comparison_profiles']['parent']['a'][0] = 99
    examples = decision_examples(candidate, [candidate, target], model)
    assert not any(e['role'] == 'parent' and e['context_key'] == 'a' for e in examples)
    target['comparison_group'] = 'other costume'
    assert decision_examples(candidate, [candidate, target], model) == []


def test_protected_diagnosis_is_never_presented_as_a_transfer_proposal():
    candidate, target, model = fixture()
    candidate.update(status='protected', analysis_status='recommended_transfer')
    html = decision_html(candidate, [], 'fr', lambda text: text)
    assert 'ne constitue pas une proposition de transfert' in html
    assert 'Pourquoi cette copie est proposée' not in html


def test_strict_replacement_uses_its_own_witnesses_not_portfolio_scores():
    candidate, target, model = fixture()
    candidate['dominated_by'] = deepcopy(candidate['portfolio_comparison'])
    candidate['portfolio_comparison']['context_deltas'] = []
    assert len(decision_examples(candidate, [candidate, target], model)) == 2


def test_a_report_without_costume_identity_does_not_get_a_comparison_witness():
    candidate, target, model = fixture()
    del candidate['comparison_group']
    del target['comparison_group']
    assert decision_examples(candidate, [candidate, target], model) == []


def test_retention_explanation_prioritises_the_strategic_asset_and_localises_roles():
    candidate, _, model = fixture()
    candidate.update(status='keep', portfolio_required_for=[
        {'kind': 'performance', 'role': 'grandparent', 'context_key': 'a',
         'label': 'grandparent: a'},
        {'kind': 'protected_skill', 'label': 'Straight Descent'},
        {'kind': 'blue_3star', 'label': '3★ Wit'}])
    model['contexts']['a'].update(surface='turf', distance='long', style='late_surger')
    reasons = preserved_reasons(candidate, model, 'fr', lambda s: s)
    assert reasons[0] == 'Skill stratégique protégé : Straight Descent'
    assert reasons[-1].startswith('Futur grand-parent · Permanent')
    html = decision_html(candidate, [], 'fr', lambda s: s, model=model, show_identity=False)
    assert 'Straight Descent' in html
    assert 'grandparent: a' not in html


def test_the_short_explanation_identifies_an_exploratory_ace():
    candidate, target, model = fixture()
    for context in model['contexts'].values():
        context['aces'][0]['target_aptitudes'] = {d: {'rank': 3, 'label': 'E'}
                                                for d in ('surface', 'distance', 'style')}
    examples = decision_examples(candidate, [candidate, target], model)
    html = decision_html(candidate, examples, 'fr', lambda s: s, focus=0, show_identity=False)
    assert 'Profil exploratoire : aptitudes à relever' in html


def test_practical_examples_are_preferred_without_hiding_a_negative_exploratory_case():
    candidate, target, model = fixture()
    model['contexts']['a']['aces'][0]['target_aptitudes'] = {d: {'rank': 3}
        for d in ('surface', 'distance', 'style')}
    model['contexts']['b']['aces'][0]['target_aptitudes'] = {d: {'rank': 7}
        for d in ('surface', 'distance', 'style')}
    # Even though the practical case is stronger, an actual loss stays first.
    example = next(e for e in decision_examples(candidate, [candidate, target], model) if e['role']=='parent')
    assert example['context_key'] == 'a' and example['selection_kind'] == 'loss'
    target['comparison_profiles']['parent']['a'][0] = 51
    candidate['portfolio_comparison']['context_deltas'][0]['replacement_score'] = 51
    example = next(e for e in decision_examples(candidate, [candidate, target], model) if e['role']=='parent')
    assert example['context_key'] == 'b' and example['selection_kind'] == 'practical'
