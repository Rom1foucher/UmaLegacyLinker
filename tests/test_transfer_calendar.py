from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from uma_legacy_linker.course_presets import upcoming_cm_presets
from uma_legacy_linker.transfer_helper import _build_profile_contexts


def fixture(tmp_path):
    path = tmp_path / 'master.mdb'
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE champions_schedule(id INTEGER, start_date INTEGER, end_date INTEGER)')
        connection.executemany('INSERT INTO champions_schedule VALUES (?,?,?)', [
            (19, datetime(2026, 9, 16, tzinfo=timezone.utc).timestamp(), datetime(2026, 9, 26, tzinfo=timezone.utc).timestamp()),
            (20, datetime(2026, 10, 8, tzinfo=timezone.utc).timestamp(), datetime(2026, 10, 17, tzinfo=timezone.utc).timestamp()),
        ])
    payload = {'courses': {f'cm{n}_test': {
        'sequence': n, 'category': 'champions_meeting_upcoming',
        'label': f'CM{n}', 'profile': {'surface': 'turf', 'distance': 'long'},
        'event_window': {'start': '13 Aug 2022, 05:00', 'end': '19 Aug 2022, 04:59'},
    } for n in range(16, 25)}}
    return path, payload


def test_current_global_cm_and_unknown_future_dates(tmp_path):
    master, payload = fixture(tmp_path)
    selected, audit = upcoming_cm_presets(payload, master, as_of=datetime(2026, 10, 10, tzinfo=timezone.utc))
    assert [course['sequence'] for _, course in selected] == [20, 21, 22, 23, 24]
    assert selected[0][1]['calendar_status'] == 'current'
    assert audit['unknown_date_count'] == 4
    assert audit['next_transition_utc'] == '2026-10-17T00:00:01+00:00'
    assert all('global_event_window' not in c for _, c in selected[1:])


def test_cm_expiry_boundary_is_inclusive(tmp_path):
    master, payload = fixture(tmp_path)
    at_end = datetime(2026, 10, 17, tzinfo=timezone.utc)
    assert upcoming_cm_presets(payload, master, as_of=at_end)[0][0][1]['sequence'] == 20
    after_end = datetime(2026, 10, 17, 0, 0, 1, tzinfo=timezone.utc)
    assert upcoming_cm_presets(payload, master, as_of=after_end)[0][0][1]['sequence'] == 21


def test_global_dates_override_stale_category_and_jp_window(tmp_path):
    _, payload = fixture(tmp_path)
    payload['courses']['cm20_test']['category'] = 'champions_meeting_archive'
    payload['courses']['cm20_test']['global_event_window'] = {'start': '2026-10-08T00:00:00Z', 'end': '2026-10-17T00:00:00Z'}
    selected, audit = upcoming_cm_presets(payload, as_of=datetime(2026, 10, 10, tzinfo=timezone.utc), limit=1)
    assert selected[0][1]['sequence'] == 20
    assert audit['source'] == 'global_event_window'


def test_date_selection_does_not_shrink_permanent_baseline(tmp_path):
    master, payload = fixture(tmp_path)
    contexts = _build_profile_contexts(payload, analysis_mode='exhaustive', include_upcoming_cm_context=True,
                                       upcoming_cm_limit=1, master_path=master,
                                       as_of=datetime(2026, 10, 10, tzinfo=timezone.utc))
    assert sum(c.scope == 'permanent' for c in contexts) == 28
    assert {c.course_key for c in contexts if c.scope == 'upcoming_cm'} == {'cm20_test'}


def test_empty_or_unknown_calendar_is_explicit(tmp_path):
    _, payload = fixture(tmp_path)
    selected, audit = upcoming_cm_presets(payload, tmp_path / 'missing.mdb', limit=1)
    assert selected[0][1]['calendar_status'] == 'legacy_category_unverified'
    assert audit['source'] == 'unavailable'
    assert upcoming_cm_presets(payload, limit=0)[0] == []


def test_preparation_stops_at_final_team_registration_not_league_selection(tmp_path):
    master, payload = fixture(tmp_path)
    league_end = datetime(2026, 10, 10, tzinfo=timezone.utc).timestamp()
    registration_end = datetime(2026, 10, 15, 9, 59, 59, tzinfo=timezone.utc).timestamp()
    with sqlite3.connect(master) as connection:
        connection.execute('CREATE TABLE champions_round_schedule(champions_id INTEGER, round INTEGER, round_detail INTEGER, end_date INTEGER)')
        connection.executemany('INSERT INTO champions_round_schedule VALUES (?,?,?,?)',
                               [(20, 0, 0, league_end), (20, 3, 1, registration_end)])
    selected, audit = upcoming_cm_presets(payload, master, as_of=datetime(2026, 10, 11, tzinfo=timezone.utc))
    assert selected[0][1]['sequence'] == 20
    assert selected[0][1]['preparation_cutoff_utc'] == '2026-10-15T09:59:59+00:00'
    assert audit['next_transition_utc'] == '2026-10-15T10:00:00+00:00'
    selected, _ = upcoming_cm_presets(payload, master, as_of=datetime(2026, 10, 15, 10, tzinfo=timezone.utc))
    assert selected[0][1]['sequence'] == 21
