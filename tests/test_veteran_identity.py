from __future__ import annotations

from pathlib import Path

from uma_legacy_linker.veteran_identity import (
    canonical_veteran_label,
    canonical_veteran_labels,
    format_rank_score,
    technical_veteran_tooltip,
)


def test_canonical_label_keeps_zero_and_never_promotes_the_technical_id() -> None:
    identity = {
        "card_name": "Tach-nology",
        "rank_score": 0,
        "trained_chara_id": 918273,
    }
    assert canonical_veteran_label(identity) == "Tach-nology · 0"
    assert technical_veteran_tooltip(identity) == "#918273"
    assert "918273" not in canonical_veteran_label(identity)


def test_rank_scores_use_a_stable_grouped_format() -> None:
    assert format_rank_score(12345) == "12 345"
    assert canonical_veteran_label(
        {"card_name": "Tach-nology", "rank_score": 12345}
    ) == "Tach-nology · 12 345"
    assert canonical_veteran_label({"card_name": "Remote candidate"}) == (
        "Remote candidate"
    )


def test_collisions_use_rank_then_blue_stars_instead_of_ids() -> None:
    ranked = [
        {
            "card_name": "Same costume",
            "rank_score": 9000,
            "rank": "S",
            "trained_chara_id": 1,
        },
        {
            "card_name": "Same costume",
            "rank_score": 9000,
            "rank": "A",
            "trained_chara_id": 2,
        },
    ]
    assert canonical_veteran_labels(ranked, rank_label="rang") == [
        "Same costume · 9 000 · rang S",
        "Same costume · 9 000 · rang A",
    ]

    blue = [
        {
            "card_name": "Same costume",
            "rank_score": 9000,
            "sparks": {"by_type": {"blue_stat": [{"stars": 3}]}},
        },
        {
            "card_name": "Same costume",
            "rank_score": 9000,
            "sparks": {"by_type": {"blue_stat": [{"stars": 6}]}},
        },
    ]
    labels = canonical_veteran_labels(blue, blue_label="bleues")
    assert labels == [
        "Same costume · 9 000 · 3★ bleues",
        "Same costume · 9 000 · 6★ bleues",
    ]
    assert all("#" not in label for label in labels)


def test_internal_ids_are_hidden_and_absent_from_transfer_search() -> None:
    transfer_source = Path("ui_qt/pages_transfer.py").read_text(encoding="utf-8")
    result_source = Path("ui_qt/result_panes.py").read_text(encoding="utf-8")
    assert 'default_hidden=()' in transfer_source
    assert 'default_hidden=(8,) if self.kind == "future" else ()' in result_source
    search_source = transfer_source[
        transfer_source.index("def _search_text") : transfer_source.index("def apply_filters")
    ]
    assert '"trained_chara_id"' not in search_source
    assert '"rank_score"' in search_source
    assert "Rechercher par nom ou score…" in transfer_source
