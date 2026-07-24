from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget


SEGMENT_COLORS = (
    "#68d3b1",
    "#70a8ff",
    "#f2c166",
    "#ff7b88",
    "#b596ff",
    "#59c9e8",
    "#ec9360",
    "#91a3bb",
)


class DistributionDonut(QWidget):
    """Small dependency-free donut chart with an elided, accessible legend."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[tuple[str, float]] = []
        self._selected_index = -1
        self._center_caption = ""
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(156)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(360, max(156, 22 + len(self._items) * 23))

    def set_distribution(
        self,
        items: list[tuple[str, float]],
        selected_index: int,
        center_caption: str,
    ) -> None:
        total = sum(max(0.0, float(value)) for _label, value in items)
        if total > 0:
            self._items = [
                (label, max(0.0, float(value)) / total) for label, value in items
            ]
        else:
            self._items = list(items)
        self._selected_index = selected_index
        self._center_caption = center_caption
        self.setFixedHeight(max(156, 22 + len(self._items) * 23))
        self.setToolTip(
            "\n".join(f"{label} : {value * 100:.1f} %" for label, value in self._items)
        )
        self.setAccessibleDescription(self.toolTip())
        self.updateGeometry()
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._items:
            return

        diameter = min(118.0, max(88.0, float(self.width()) * 0.34))
        chart_x = 4.0
        chart_y = max(6.0, (self.height() - diameter) / 2.0)
        chart_rect = QRectF(chart_x, chart_y, diameter, diameter)
        start_angle = 90 * 16
        for index, (_label, share) in enumerate(self._items):
            span = int(round(max(0.0, share) * 360.0 * 16.0))
            painter.setBrush(QColor(SEGMENT_COLORS[index % len(SEGMENT_COLORS)]))
            painter.setPen(
                QPen(QColor("#edf4ff"), 2.0)
                if index == self._selected_index
                else QPen(QColor("#101824"), 1.0)
            )
            painter.drawPie(chart_rect, start_angle, -span)
            start_angle -= span

        inner_margin = diameter * 0.27
        inner_rect = chart_rect.adjusted(
            inner_margin, inner_margin, -inner_margin, -inner_margin
        )
        painter.setBrush(QColor("#101824"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(inner_rect)

        selected_share = (
            self._items[self._selected_index][1]
            if 0 <= self._selected_index < len(self._items)
            else 0.0
        )
        center_font = QFont(self.font())
        center_font.setPointSizeF(13.0)
        center_font.setBold(True)
        painter.setFont(center_font)
        painter.setPen(QColor("#edf4ff"))
        center_top = QRectF(inner_rect.left(), inner_rect.top() + 5, inner_rect.width(), 25)
        painter.drawText(center_top, Qt.AlignmentFlag.AlignCenter, f"{selected_share * 100:.1f}%")
        caption_font = QFont(self.font())
        caption_font.setPointSizeF(7.5)
        painter.setFont(caption_font)
        painter.setPen(QColor("#91a3bb"))
        caption_rect = QRectF(
            inner_rect.left() - 5,
            inner_rect.center().y() + 5,
            inner_rect.width() + 10,
            18,
        )
        painter.drawText(caption_rect, Qt.AlignmentFlag.AlignCenter, self._center_caption)

        legend_x = chart_rect.right() + 16.0
        legend_width = max(80.0, self.width() - legend_x - 4.0)
        row_height = 23.0
        legend_y = max(4.0, (self.height() - len(self._items) * row_height) / 2.0)
        normal_font = QFont(self.font())
        selected_font = QFont(normal_font)
        selected_font.setBold(True)
        for index, (label, share) in enumerate(self._items):
            y = legend_y + index * row_height
            painter.setBrush(QColor(SEGMENT_COLORS[index % len(SEGMENT_COLORS)]))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(QRectF(legend_x, y + 5, 10, 10), 3, 3)

            painter.setFont(selected_font if index == self._selected_index else normal_font)
            painter.setPen(QColor("#edf4ff") if index == self._selected_index else QColor("#b7c6d9"))
            percentage_width = 50.0
            label_rect = QRectF(
                legend_x + 17,
                y,
                max(20.0, legend_width - percentage_width - 20),
                row_height,
            )
            metrics = painter.fontMetrics()
            visible_label = metrics.elidedText(
                label, Qt.TextElideMode.ElideRight, int(label_rect.width())
            )
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignVCenter, visible_label)
            percentage_rect = QRectF(
                legend_x + legend_width - percentage_width,
                y,
                percentage_width,
                row_height,
            )
            painter.drawText(
                percentage_rect,
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                f"{share * 100:.1f}%",
            )
