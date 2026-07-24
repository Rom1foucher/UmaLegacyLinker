from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt


Getter = Callable[[dict[str, Any]], Any]


@dataclass(frozen=True)
class Column:
    title: str
    getter: Getter
    alignment: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft


def nested(*keys: str, default: Any = "—") -> Getter:
    def read(row: dict[str, Any]) -> Any:
        value: Any = row
        for key in keys:
            if not isinstance(value, dict):
                return default
            value = value.get(key)
        return default if value is None or value == "" else value

    return read


class ResultTableModel(QAbstractTableModel):
    RawValueRole = Qt.ItemDataRole.UserRole + 1
    RowRole = Qt.ItemDataRole.UserRole + 2

    def __init__(
        self,
        rows: list[dict[str, Any]] | None = None,
        columns: list[Column] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._rows = list(rows or [])
        self._columns = list(columns or [])

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._columns)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        column = self._columns[index.column()]
        value = column.getter(row)
        if role == Qt.ItemDataRole.DisplayRole:
            if isinstance(value, float):
                return f"{value:.2f}"
            return str(value)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(column.alignment | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ToolTipRole:
            return row.get("_tooltip")
        if role == self.RawValueRole:
            return value
        if role == self.RowRole:
            return row
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal and 0 <= section < len(self._columns):
            return self._columns[section].title
        if orientation == Qt.Orientation.Vertical:
            return section + 1
        return None

    @staticmethod
    def _sort_value(value: Any) -> tuple[int, Any]:
        if value is None or value in {"", "—", "-"}:
            return (2, "")
        if isinstance(value, bool):
            return (0, int(value))
        if isinstance(value, (int, float)):
            return (0, float(value))
        return (1, str(value).casefold())

    def sort(self, column: int, order=Qt.SortOrder.AscendingOrder) -> None:
        if not 0 <= column < len(self._columns):
            return
        getter = self._columns[column].getter
        self.layoutAboutToBeChanged.emit()
        self._rows.sort(
            key=lambda row: self._sort_value(getter(row)),
            reverse=order == Qt.SortOrder.DescendingOrder,
        )
        self.layoutChanged.emit()

    def row(self, index: int) -> dict[str, Any] | None:
        return self._rows[index] if 0 <= index < len(self._rows) else None

    def set_rows(self, rows: list[dict[str, Any]]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def set_columns(self, columns: list[Column]) -> None:
        self.beginResetModel()
        self._columns = list(columns)
        self.endResetModel()
