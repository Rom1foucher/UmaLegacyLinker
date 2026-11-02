from __future__ import annotations

from typing import Any

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QListWidget, QStyledItemDelegate, QStyle, QStyleOptionViewItem

from ui_qt.avatar import AsyncAvatarProvider
from ui_qt.theme import COLORS
from ui_qt.typography import point_size
from uma_legacy_linker.veteran_identity import format_rank_score


CARD_SIZE = QSize(174, 196)


def _painter_font(role: str, weight: QFont.Weight) -> QFont:
    font = QFont("Segoe UI")
    font.setPointSizeF(point_size(role))
    font.setWeight(weight)
    return font


class TransferRosterDelegate(QStyledItemDelegate):
    """Paint a compact game-roster card for each Transfer Helper veteran."""

    def __init__(self, context, avatars: AsyncAvatarProvider, parent=None):
        super().__init__(parent)
        self.context = context
        self.avatars = avatars
        self.card_size = QSize(CARD_SIZE)

    def set_card_size(self, size: QSize) -> None:
        self.card_size = QSize(size)

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:  # noqa: N802
        return self.card_size

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        row = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(row, dict):
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = option.rect.adjusted(5, 5, -5, -5)
        status = str(row.get("status") or "")
        status_color = (
            COLORS["danger"] if status in {"safe_transfer", "recommended_transfer"}
            else COLORS["warning"] if status == "review"
            else COLORS["accent"]
        )
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        border = QColor(COLORS["focus"] if selected else status_color)
        border.setAlpha(240 if selected else 150)
        painter.setPen(QPen(border, 2.2 if selected else 1.25))
        painter.setBrush(QColor(COLORS["surface_alt"]))
        painter.drawRoundedRect(rect, 13, 13)

        portrait_size = min(92, max(48, int(rect.width() * 0.5)))
        portrait_rect = QRect(
            rect.center().x() - portrait_size // 2,
            rect.top() + 10,
            portrait_size,
            portrait_size,
        )
        portrait = self.avatars.avatar(row.get("card_id"))
        if portrait is not None and not portrait.isNull():
            painter.drawPixmap(portrait_rect, portrait)
        else:
            painter.setBrush(QColor(COLORS["surface"]))
            painter.setPen(QPen(QColor(COLORS["border"]), 1))
            painter.drawEllipse(portrait_rect)
            initials = str(row.get("uma_name") or row.get("card_name") or "?")[:1].upper()
            painter.setPen(QColor(COLORS["muted"]))
            painter.setFont(_painter_font("display", QFont.Weight.DemiBold))
            painter.drawText(portrait_rect, Qt.AlignmentFlag.AlignCenter, initials)

        rank = str(row.get("rank") or "—")
        badge = QRect(portrait_rect.right() - 25, portrait_rect.top() + 1, 48, 26)
        painter.setPen(QPen(QColor("#6b55c8"), 1))
        painter.setBrush(QColor("#392c74"))
        painter.drawRoundedRect(badge, 8, 8)
        painter.setPen(QColor("#f4eaff"))
        painter.setFont(_painter_font("body", QFont.Weight.Bold))
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, rank)

        name = str(row.get("uma_name") or row.get("card_name") or "—")
        painter.setPen(QColor(COLORS["text"]))
        painter.setFont(_painter_font("caption", QFont.Weight.DemiBold))
        name_rect = QRect(rect.left() + 7, portrait_rect.bottom() + 6, rect.width() - 14, 20)
        painter.drawText(
            name_rect,
            Qt.AlignmentFlag.AlignCenter,
            painter.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, name_rect.width()),
        )

        score_rect = QRect(rect.left() + 19, name_rect.bottom() + 4, rect.width() - 38, 27)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(COLORS["surface"]))
        painter.drawRoundedRect(score_rect, 13, 13)
        painter.setPen(QColor(COLORS["text"]))
        painter.setFont(_painter_font("section", QFont.Weight.Bold))
        painter.drawText(
            score_rect,
            Qt.AlignmentFlag.AlignCenter,
            format_rank_score(row.get("rank_score")),
        )

        label = (
            "Transférer" if status in {"safe_transfer", "recommended_transfer"}
            else "À vérifier" if status == "review"
            else "Garder"
        )
        status_rect = QRect(rect.left() + 8, score_rect.bottom() + 5, rect.width() - 16, 24)
        tint = QColor(status_color)
        tint.setAlpha(38)
        painter.setPen(QPen(QColor(status_color), 1))
        painter.setBrush(tint)
        painter.drawRoundedRect(status_rect, 8, 8)
        painter.setPen(QColor(status_color))
        painter.setFont(_painter_font("caption", QFont.Weight.Bold))
        painter.drawText(
            status_rect,
            Qt.AlignmentFlag.AlignCenter,
            self.context.t(label),
        )
        painter.restore()


class TransferRosterView(QListWidget):
    """Flowing roster that keeps the configured number of columns on resize."""

    columns_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.fixed_columns = 5
        self._cell_size = QSize(CARD_SIZE.width(), CARD_SIZE.height() + 8)
        self.setSpacing(0)

    def set_fixed_columns(self, columns: int) -> None:
        columns = max(1, int(columns))
        if columns == self.fixed_columns:
            self._update_cell_size()
            return
        self.fixed_columns = columns
        self._update_cell_size()
        self.columns_changed.emit(columns)

    def cell_size(self) -> QSize:
        return QSize(self._cell_size)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._update_cell_size()

    def _update_cell_size(self) -> None:
        available = max(1, self.viewport().width())
        columns = max(1, self.fixed_columns)
        # QListView reserves a few pixels per cell for its flow geometry even
        # with spacing set to zero. Leave a small per-column gutter so an exact
        # viewport/columns quotient does not wrap the last card to the next row.
        width = max(76, available // columns - 4)
        self._cell_size = QSize(width, CARD_SIZE.height() + 8)
        self.setGridSize(self._cell_size)
        delegate = self.itemDelegate()
        if isinstance(delegate, TransferRosterDelegate):
            delegate.set_card_size(self._cell_size)
        for index in range(self.count()):
            self.item(index).setSizeHint(self._cell_size)
