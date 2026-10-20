from __future__ import annotations

import sys
from pathlib import Path

import pytest

from uma_legacy_linker.application import active_white_loop_ids


def test_explicit_protections_are_preserved_without_a_project_file(tmp_path):
    assert active_white_loop_ids(tmp_path, (7, 3, 7)) == (3, 7)


@pytest.mark.parametrize("contents", [
    '{',
    '{"schema_version": 2, "projects": []}',
    '{"schema_version": 1, "projects": [{"carriers": '
    '[{"trained_chara_id": 8, "status": "active"}]}]}',
])
def test_unsupported_sidecar_is_ignored_and_unchanged(tmp_path, monkeypatch, contents):
    path = tmp_path / "white_loop_projects.json"
    path.write_text(contents, encoding="utf-8")
    monkeypatch.setitem(sys.modules, "uma_legacy_linker.loop_repository", None)
    assert active_white_loop_ids(tmp_path, (7, 3, 7)) == (3, 7)
    assert active_white_loop_ids(tmp_path) == ()
    assert path.read_text(encoding="utf-8") == contents


def test_no_project_file_access_is_attempted(tmp_path, monkeypatch):
    def unexpected_access(*args, **kwargs):
        raise AssertionError("Transfer analysis must not inspect White Loop files")

    monkeypatch.setattr(Path, "exists", unexpected_access)
    monkeypatch.setattr(Path, "read_text", unexpected_access)
    assert active_white_loop_ids(tmp_path, (7,)) == (7,)
