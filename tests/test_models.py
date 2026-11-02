from __future__ import annotations

from PySide6.QtCore import Qt

from ui_qt.models import Column, ResultTableModel, number


def test_formatted_percentile_column_sorts_by_its_numeric_key() -> None:
    percentile = number("percentile", default=100.0)
    rows = [
        {"id": "twenty", "percentile": "20.5"},
        {"id": "four", "percentile": 4.2},
        {"id": "missing", "percentile": None},
        {"id": "zero", "percentile": 0},
    ]
    model = ResultTableModel(
        rows,
        [
            Column(
                "Rank",
                lambda row: f"top {percentile(row):.1f}%",
                sort_getter=percentile,
            )
        ],
    )

    model.sort(0, Qt.SortOrder.AscendingOrder)

    assert [model.row(index)["id"] for index in range(model.rowCount())] == [
        "zero",
        "four",
        "twenty",
        "missing",
    ]
    assert model.data(model.index(0, 0)) == "top 0.0%"
    assert model.data(model.index(1, 0)) == "top 4.2%"


def test_column_foreground_getter_exposes_verdict_color() -> None:
    from PySide6.QtGui import QColor

    expected = QColor("#123456")
    model = ResultTableModel(
        [{"status": "protected"}],
        [Column("Verdict", lambda row: row["status"], foreground_getter=lambda _row: expected)],
    )

    assert model.data(model.index(0, 0), Qt.ItemDataRole.ForegroundRole) == expected
