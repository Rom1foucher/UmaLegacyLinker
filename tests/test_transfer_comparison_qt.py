from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication

from ui_qt.context import AppContext
from ui_qt.pages_transfer import STATE_LOADED, STATE_STALE, TransferPage
from uma_legacy_linker.application import SettingsStore


@pytest.fixture
def app_context(tmp_path):
    application = QApplication.instance() or QApplication([])
    store = SettingsStore(tmp_path / 'config.json')
    store.update({'output_dir': str(tmp_path / 'output'), 'ui_language': 'fr', 'online_images_enabled': 0})
    return application, AppContext(store)


def test_protected_copies_stay_on_the_keep_side(app_context):
    _, context = app_context
    page = TransferPage(context)
    records = [
        {'trained_chara_id': 1, 'card_name': 'Copy', 'rank_score': 13000,
         'status': 'protected', 'manual_protection_reasons': ['locked_in_game'],
         'transfer_reason': {'code': 'protected', 'subject': 'locked_in_game', 'refs': []}},
        {'trained_chara_id': 2, 'card_name': 'Copy', 'rank_score': 12000,
         'status': 'recommended_transfer', 'transfer_reason': {'code': 'outclassed', 'refs': []}},
        {'trained_chara_id': 3, 'card_name': 'Copy', 'rank_score': 11000,
         'status': 'keep', 'transfer_reason': {'code': 'holds_role', 'subject': 'Parent Turf', 'refs': []}},
    ]
    page.set_records(records)
    page.filter_buttons['transfer'].click()
    assert [page.model.row(i)['trained_chara_id'] for i in range(page.model.rowCount())] == [2]
    page.filter_buttons['keep'].click()
    assert {page.model.row(i)['trained_chara_id'] for i in range(page.model.rowCount())} == {1, 3}
    assert page._reason_label(records[0]) == 'Verrouillée'
    page.close()
def test_transfer_filter_keeps_game_score_order(app_context):
    _, context = app_context
    page = TransferPage(context)
    records = [
        {'trained_chara_id': 1, 'rank_score': 24426, 'status': 'keep'},
        {'trained_chara_id': 2, 'rank_score': 24312, 'status': 'protected'},
        {'trained_chara_id': 3, 'rank_score': 23595, 'status': 'recommended_transfer'},
        {'trained_chara_id': 4, 'rank_score': '23801', 'status': 'safe_transfer'},
        {'trained_chara_id': 5, 'rank_score': 25000, 'status': 'review'},
        {'trained_chara_id': 6, 'rank_score': None, 'status': 'recommended_transfer'},
        {'trained_chara_id': 7, 'rank_score': 'unknown', 'status': 'recommended_transfer'},
        {'trained_chara_id': 8, 'rank_score': 26000, 'status': 'protected'},
        {'trained_chara_id': 9, 'rank_score': 27000, 'status': 'keep'},
    ]
    for record in records:
        record.update(card_name='Opera', uma_name='Opera', comparison_group='opera')
    page.set_records(records)
    page.search.setText('no match')
    page.filter_buttons['transfer'].click()
    assert page.search.text() == 'no match'
    page.search.clear()
    assert [page.model.row(i)['trained_chara_id'] for i in range(page.model.rowCount())] == [4, 3, 6, 7]
    assert page.model.columnCount() == 4
    assert not page.table.isSortingEnabled()
    assert page.filter_buttons['transfer'].isChecked()
    page.search.setText('23595')
    assert page.model.rowCount() == 1
    page.search.clear()
    page.retranslate()
    assert page.filter_buttons['transfer'].isChecked()
    page.close()

def test_clicking_a_cited_score_selects_the_retained_copy(app_context):
    application, context = app_context
    page = TransferPage(context)
    page.set_records([
        {'trained_chara_id': 1, 'card_name': 'Opera O', 'uma_name': 'Opera O',
         'rank_score': 9000, 'status': 'recommended_transfer',
         'transfer_reason': {'code': 'covered_by', 'refs': [
             {'trained_chara_id': 2, 'rank_score': 11240, 'uma_name': 'Opera O'}]}},
        {'trained_chara_id': 2, 'card_name': 'Opera O', 'uma_name': 'Opera O',
         'rank_score': 11240, 'status': 'keep',
         'transfer_reason': {'code': 'holds_role', 'subject': 'Turf Medium Late', 'refs': []}},
    ])
    page.filter_buttons['transfer'].click()
    assert page.model.rowCount() == 1
    page._reason_cell_clicked(page.model.index(0, 3))
    assert page.filter_buttons['all'].isChecked()
    assert page.selected_row()['trained_chara_id'] == 2
    page.close()


def test_calendar_expiry_marks_an_open_report_stale_on_the_same_day(app_context):
    _, context = app_context
    page = TransferPage(context)
    now = datetime.now(timezone.utc)
    page._result_origin_state = STATE_LOADED
    page._reason_schema_supported = True
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


def test_empty_search_can_be_cleared_without_losing_records(app_context):
    _, context = app_context
    page = TransferPage(context)
    page.set_records([{'trained_chara_id': 1, 'card_name': 'Opera O',
                       'uma_name': 'Opera O', 'rank_score': 12345,
                       'rank': 12, 'status': 'keep'}])
    assert '12 345' in page._columns()[0].getter(page._records[0])
    page.search.setText('no matching veteran')
    assert page.model.rowCount() == 0
    page.search.clear()
    assert page.model.rowCount() == 1
    page.close()
