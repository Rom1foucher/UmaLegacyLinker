from __future__ import annotations

import os
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
pytest.importorskip('PySide6')
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from tests.test_transfer_comparison import comparison_fixture
from ui_qt.context import AppContext
from ui_qt.pages_transfer import GAME_SCORE_COLUMN, TRANSFER_CANDIDATES, STATE_LOADED, STATE_STALE, TransferPage
from ui_qt.transfer_comparison_dialog import TransferComparisonDialog
from uma_legacy_linker.application import SettingsStore
from uma_legacy_linker.transfer_comparison import comparison_evaluation


@pytest.fixture
def app_context(tmp_path):
    application = QApplication.instance() or QApplication([])
    store = SettingsStore(tmp_path / 'config.json')
    store.update({'output_dir': str(tmp_path / 'output'), 'ui_language': 'fr', 'online_images_enabled': 0})
    return application, AppContext(store)


def test_protected_redundant_copies_are_filterable_but_badged(app_context):
    _, context = app_context
    page = TransferPage(context)
    records = [
        {'trained_chara_id': 1, 'card_name': 'Copy', 'comparison_group': 'group',
         'status': 'protected', 'analysis_status': 'recommended_transfer',
         'manual_protection_reasons': ['is_locked'], 'transfer_eligible': False},
        {'trained_chara_id': 2, 'card_name': 'Copy', 'comparison_group': 'group',
         'status': 'recommended_transfer', 'analysis_status': 'recommended_transfer'},
        {'trained_chara_id': 3, 'card_name': 'Copy', 'comparison_group': 'group',
         'status': 'keep', 'analysis_status': 'keep'},
    ]
    page.set_records(records)
    page.status_combo.setCurrentIndex(page.status_combo.findData('recommended_transfer'))
    assert {page.model.row(i)['trained_chara_id'] for i in range(page.model.rowCount())} == {1, 2}
    assert page._columns()[0].getter(records[0]) == 'Protégé · Redondant'
    assert {r['trained_chara_id'] for r in page._comparison_targets(records[0])} == {2, 3}
    page.status_combo.setCurrentIndex(page.status_combo.findData('protected'))
    assert page.model.rowCount() == 1
    page.close()


def test_transfer_selection_matches_game_order_and_excludes_retained_copies(app_context):
    _, context = app_context
    page = TransferPage(context)
    records = [
        {'trained_chara_id': 1, 'rank_score': 24426, 'status': 'keep'},
        {'trained_chara_id': 2, 'rank_score': 24312, 'status': 'protected',
         'analysis_status': 'recommended_transfer'},
        {'trained_chara_id': 3, 'rank_score': 23595, 'status': 'recommended_transfer'},
        {'trained_chara_id': 4, 'rank_score': '23801', 'status': 'safe_transfer'},
        {'trained_chara_id': 5, 'rank_score': 25000, 'status': 'review'},
        {'trained_chara_id': 6, 'rank_score': None, 'status': 'recommended_transfer'},
        {'trained_chara_id': 7, 'rank_score': 'unknown', 'status': 'recommended_transfer'},
        {'trained_chara_id': 8, 'rank_score': 26000, 'status': 'safe_transfer',
         'manual_protection_reasons': ['is_locked']},
        {'trained_chara_id': 9, 'rank_score': 27000, 'status': 'recommended_transfer',
         'selected_in_portfolio': True},
    ]
    for record in records:
        record.update(card_name='Opera', comparison_group='opera')
    page.set_records(records)
    page.search.setText('no match')
    page.selection_button.click()
    assert page.status_combo.currentData() == TRANSFER_CANDIDATES
    assert page.search.text() == ''
    assert [page.model.row(i)['trained_chara_id'] for i in range(page.model.rowCount())] == [4, 3, 6, 7]
    assert not page.table.isColumnHidden(GAME_SCORE_COLUMN)
    assert page.table.horizontalHeader().visualIndex(GAME_SCORE_COLUMN) == 0
    assert page.table.horizontalHeader().sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
    page.search.setText('23595')
    assert page.model.rowCount() == 1
    page.search.clear()
    page.retranslate()
    assert page.status_combo.currentData() == TRANSFER_CANDIDATES
    assert context.store.get('ui_transfer_status_filter') == TRANSFER_CANDIDATES
    page._reset_filters()
    assert page.model.rowCount() == len(records)
    page.close()


def test_component_dialog_handles_roles_history_and_long_names(app_context):
    application, context = app_context
    _, candidate, model = comparison_fixture()
    candidate.update(card_name='Very long costume ' * 30, comparison_group='group',
                     status='protected', analysis_status='recommended_transfer',
                     manual_protection_reasons=['is_locked'])
    alternative = deepcopy(candidate)
    alternative.update(trained_chara_id=2, manual_protection_reasons=[], selected_in_portfolio=True)
    alternative['comparison_veteran']['factors']['by_type']['white_skill'] = []
    model['contexts']['context']['scope'] = 'permanent'
    for record in (candidate, alternative):
        record['comparison_profiles'] = {
            role: {'context': [comparison_evaluation(record, model, 'context', 0, role)['score']]}
            for role in ('parent', 'grandparent')
        }
    dialog = TransferComparisonDialog(context, candidate, [alternative], model)
    dialog.resize(960, 700)
    dialog.show()
    application.processEvents()
    assert dialog.width() <= 960
    assert 'Protégé' in dialog.identity.text()
    assert dialog.matrix.rowCount() == 1
    assert 'Turf' in dialog.course.currentText()
    assert 'Total' in dialog.browsers[0].toPlainText()
    assert 'Uma Stan' in dialog.browsers[1].toPlainText()
    assert 'P candidat' in dialog.browsers[1].toPlainText()
    dialog.role.setCurrentIndex(dialog.role.findData('grandparent'))
    assert 'Potentiel G1' in dialog.browsers[0].toPlainText()
    assert 'Génération White' in dialog.browsers[0].toPlainText()
    assert 'probabilité d’héritage' in dialog.browsers[0].toPlainText()
    alternative['comparison_profiles']['grandparent']['context'][0] += 2
    dialog._render()
    assert 'score historique' in dialog.summary.text()
    assert not dialog.browsers[0].toPlainText()
    dialog.close()


def test_calendar_expiry_marks_an_open_report_stale_on_the_same_day(app_context):
    _, context = app_context
    page = TransferPage(context)
    now = datetime.now(timezone.utc)
    page._result_origin_state = STATE_LOADED
    page._result_fingerprint = page._current_fingerprint()
    page._capture_report_context({'settings': {'cm_calendar': {
        'as_of_utc': now.isoformat(),
        'next_transition_utc': (now - timedelta(seconds=1)).isoformat(),
    }}})
    page._refresh_freshness()
    assert page._result_state == STATE_STALE
    page._capture_report_context({'settings': {'cm_calendar': {
        'as_of_utc': now.isoformat(),
        'next_transition_utc': (now + timedelta(hours=1)).isoformat(),
    }}})
    page._refresh_freshness()
    assert page._result_state == STATE_LOADED
    page.close()


def test_empty_search_can_be_reset_without_losing_records(app_context):
    _, context = app_context
    page = TransferPage(context)
    page.set_records([{'trained_chara_id': 1, 'card_name': 'Opera O',
                       'rank_score': 12345, 'rank': 12, 'status': 'keep'}])
    assert '12 345' in page._columns()[1].getter(page._records[0]).split('\n')[1]
    page.search.setText('no matching veteran')
    assert page.model.rowCount() == 0
    assert not page.compare_button.isEnabled()
    assert not page.empty_results.isHidden()
    assert not page.reset_filters.isHidden()
    page.reset_filters.click()
    assert page.model.rowCount() == 1
    assert page.empty_results.isHidden()
    page.close()


def test_target_change_preserves_ace_and_context_and_marks_inspected_node(app_context):
    application, context = app_context
    _, candidate, model = comparison_fixture()
    other = deepcopy(candidate)
    other['trained_chara_id'] = 2
    third = deepcopy(candidate)
    third['trained_chara_id'] = 3
    model['contexts']['second'] = deepcopy(model['contexts']['context'])
    model['contexts']['second']['aces'].append(deepcopy(model['contexts']['second']['aces'][0]))
    model['contexts']['second']['aces'][1]['card_id'] += 1
    dialog = TransferComparisonDialog(context, candidate, [other, third], model)
    dialog.show()
    application.processEvents()
    dialog.course.setCurrentIndex(dialog.course.findData('second'))
    dialog.ace.setCurrentIndex(1)
    dialog.target.setCurrentIndex(1)
    assert dialog.course.currentData() == 'second'
    assert dialog.ace.currentData() == 1
    assert dialog.score_labels[0].text() != '—'
    assert 'Indices équivalents' in dialog.score_labels[2].text()
    dialog.node_picker.setCurrentIndex(dialog.node_picker.findData('p2'))
    assert dialog.tree.selected_node == 'p2'
    assert dialog.inspector_section.toggle.isChecked()
    dialog.inspector_section.toggle.setChecked(False)
    dialog.tabs.setCurrentIndex(1)
    dialog.resize(960, 700)
    application.processEvents()
    application.processEvents()
    assert dialog.tree.minimumWidth() <= dialog.tree_scroll.viewport().width()
    dialog._manual_zoom(1.2)
    dialog.resize(1100, 750)
    application.processEvents()
    assert dialog.tree.zoom_level() == 1.2
    dialog.fit_button.click()
    application.processEvents()
    assert dialog.tree.minimumWidth() <= dialog.tree_scroll.viewport().width()
    dialog.close()


def test_comparison_uses_english_labels_and_keeps_game_score_visible(app_context):
    _, context = app_context
    context.set_language('en')
    _, candidate, model = comparison_fixture()
    other = deepcopy(candidate)
    other.update(rank=12, rank_score=12345)
    dialog = TransferComparisonDialog(context, candidate, [other], model)
    assert dialog.target.currentText().startswith('B+ · 12 345')
    assert dialog.tree._role_labels['p1'] == 'Studied copy'
    assert 'Equivalent indices' in dialog.score_labels[2].text()
    assert not dialog.inspector_section.toggle.isChecked()
    dialog._select_node('p1')
    assert dialog.inspector_section.toggle.isChecked()
    dialog.close()


def test_decision_example_opens_the_exact_saved_comparison(app_context, monkeypatch):
    from PySide6.QtCore import QUrl
    _, context = app_context
    _, candidate, model = comparison_fixture()
    candidate.update(trained_chara_id=1, comparison_group='same', status='recommended_transfer')
    target = deepcopy(candidate)
    target.update(trained_chara_id=2, selected_in_portfolio=True, rank_score=12000)
    for record in (candidate, target):
        record['comparison_profiles'] = {
            role: {'context': [comparison_evaluation(record, model, 'context', 0, role)['score']]}
            for role in ('parent', 'grandparent')}
    candidate['portfolio_comparison'] = {'context_deltas': [
        {'role': role, 'context_key': 'context', 'ace_card_id': model['contexts']['context']['aces'][0]['card_id'],
         'candidate_score': candidate['comparison_profiles'][role]['context'][0],
         'replacement_score': target['comparison_profiles'][role]['context'][0],
         'retained_by': [{'trained_chara_id': 2}]}
        for role in ('parent', 'grandparent')]}
    page = TransferPage(context)
    page._comparison_model = model
    page.set_records([candidate, target])
    assert 'Copie conservée' in page.detail.toPlainText()
    assert 'Ce qu’on perd avec ce remplacement' in page.detail.toPlainText()
    assert 'Preuves du verdict' not in page.detail.toPlainText()
    opened = []

    def inspect_dialog(dialog):
        opened.append((dialog.role.currentData(), dialog.course.currentData(),
                       dialog.ace.currentData(), dialog.alternatives[0]['trained_chara_id']))
        dialog.close()
        return 0

    monkeypatch.setattr(TransferComparisonDialog, 'exec', inspect_dialog)
    page._decision_link(QUrl('example:0'))
    assert opened == [('parent', 'context', 0, 2)]
    page.decision_panel.examples.setCurrentIndex(1)
    page.decision_panel.verify_button.click()
    assert opened[-1] == ('grandparent', 'context', 0, 2)
    page._decision_link(QUrl('details:toggle'))
    assert page._detail_expanded
    assert 'Masquer les détails avancés' in page.detail.toPlainText()
    page.close()


def test_the_compact_workbench_keeps_filters_and_protection_diagnoses_usable(app_context):
    application, context = app_context
    page = TransferPage(context)
    page.set_records([
        {'trained_chara_id': 1, 'card_name': 'Opera', 'uma_name': 'Opera', 'rank_score': 12000,
         'comparison_group': 'opera', 'status': 'protected', 'analysis_status': 'recommended_transfer',
         'selected_in_portfolio': True, 'manual_protection_reasons': ['is_locked']},
        {'trained_chara_id': 2, 'card_name': 'Opera', 'uma_name': 'Opera', 'rank_score': 9000,
         'comparison_group': 'opera', 'status': 'recommended_transfer', 'selected_in_portfolio': False},
        {'trained_chara_id': 3, 'card_name': 'Other', 'comparison_group': 'other', 'status': 'keep',
         'selected_in_portfolio': True}])
    page.family_combo.setCurrentIndex(page.family_combo.findData('opera'))
    page.status_combo.setCurrentIndex(page.status_combo.findData('recommended_transfer'))
    page.resize(960, 700)
    page.show()
    application.processEvents()
    assert page.width() == 960
    assert page.model.rowCount() == 2
    assert page.decision_panel.family_summary.text().startswith('1 copies conservées sur 2')
    assert 'diagnostic seulement' in page.decision_panel.badge.text()
    assert page.family_combo.geometry().left() > page.status_combo.geometry().right()
    assert page.status_combo.width() >= 160 and page.family_combo.width() >= 160
    assert not page.scope_section.toggle.isChecked()
    assert page.table.isColumnHidden(3) and page.table.isColumnHidden(5)
    page.scope_section.toggle.setChecked(True)
    assert not page.mode_combo.isHidden() and page.safe_card.isVisible()
    page.close()


def test_legacy_family_data_does_not_invent_a_retained_count(app_context):
    _, context = app_context
    page = TransferPage(context)
    page.set_records([{'trained_chara_id': 1, 'comparison_group': 'group', 'card_name': 'Uma', 'status': 'keep'}])
    assert '0 copies conservées' not in page.decision_panel.family_summary.text()
    assert page.decision_panel.family_summary.text() == '1 copies de ce costume.'
    page.close()


def test_the_scope_summary_and_stale_state_survive_collapsed_settings_and_translation(app_context):
    application, context = app_context
    page = TransferPage(context)
    page._result_origin_state = STATE_LOADED
    page._result_fingerprint = page._current_fingerprint()
    page.team_trials_check.setChecked(True)
    page.generic_profiles_check.setChecked(True)
    page.upcoming_cm_limit.setValue(7)
    assert page._result_state == STATE_STALE
    assert '7 CM max.' in page.scope_section.toggle.text()
    assert 'Team Trials' in page.scope_section.toggle.text()
    assert 'Profils génériques' in page.scope_section.toggle.text()
    context.set_language('en')
    assert 'Generic profiles' in page.scope_section.toggle.text()
    assert page.collection_summary.text() == 'Collection summary'
    page.resize(960, 700)
    page.show()
    application.processEvents()
    assert page.width() == 960
    page.close()


def test_general_exploration_starts_on_the_actual_witness_even_when_another_target_comes_first(app_context, monkeypatch):
    _, context = app_context
    _, candidate, model = comparison_fixture()
    candidate.update(comparison_group='same', status='recommended_transfer')
    target, other = deepcopy(candidate), deepcopy(candidate)
    target.update(trained_chara_id=2, selected_in_portfolio=True, rank=12, rank_score=12000)
    other.update(trained_chara_id=3, selected_in_portfolio=True)
    for record in (candidate, target, other):
        record['comparison_profiles'] = {'parent': {'context': [comparison_evaluation(
            record, model, 'context', 0, 'parent')['score']]}}
    score = candidate['comparison_profiles']['parent']['context'][0]
    candidate['portfolio_comparison'] = {'context_deltas': [{
        'role': 'parent', 'context_key': 'context', 'ace_card_id': model['contexts']['context']['aces'][0]['card_id'],
        'candidate_score': score, 'replacement_score': score, 'retained_by': [{'trained_chara_id': 2}]}]}
    candidate['covered_by_portfolio'] = [{'trained_chara_id': 3}, {'trained_chara_id': 2}]
    page = TransferPage(context)
    page._comparison_model = model
    page.set_records([candidate, target, other])
    opened = []

    def inspect(dialog):
        actual = dialog.alternatives[dialog.target.currentData()]
        opened.append(actual['trained_chara_id'])
        assert dialog.tabs.currentIndex() == 0
        assert not dialog.case_section.toggle.isChecked()
        assert '12 000' in dialog.score_identity_labels[1].text()
        dialog.close()
        return 0

    monkeypatch.setattr(TransferComparisonDialog, 'exec', inspect)
    page.compare_selected_veteran()
    assert opened == [2]
    page.close()


def test_an_empty_comparison_model_displays_an_unavailable_state(app_context):
    _, context = app_context
    dialog = TransferComparisonDialog(context, {'card_name': 'Uma'}, [{'card_name': 'Other'}], {})
    assert 'Aucun Ace disponible' in dialog.summary.text()
    assert not dialog.explanation.toPlainText()
    dialog.close()
