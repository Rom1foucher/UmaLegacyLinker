from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class CurveCanvas(QWidget):
    pointMoved = Signal(int, float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(210)
        self.setMouseTracking(True)
        self._points: list[list[float]] = []
        self._x_max = 1.0
        self._y_max = 1.0
        self._drag_index = -1
        self._hover_index = -1
        self._pad_left = 48.0
        self._pad_right = 18.0
        self._pad_top = 16.0
        self._pad_bottom = 34.0

    def set_curve(self, points: Iterable[Iterable[float]], x_max: float, y_max: float) -> None:
        self._points = [[float(x), float(y)] for x, y in points]
        self._x_max = max(float(x_max), 1e-9)
        self._y_max = max(float(y_max), 1e-9)
        self.update()

    def _plot_rect(self) -> QRectF:
        return QRectF(
            self._pad_left,
            self._pad_top,
            max(1.0, self.width() - self._pad_left - self._pad_right),
            max(1.0, self.height() - self._pad_top - self._pad_bottom),
        )

    def _to_screen(self, x: float, y: float) -> QPointF:
        rect = self._plot_rect()
        return QPointF(
            rect.left() + (x / self._x_max) * rect.width(),
            rect.bottom() - (y / self._y_max) * rect.height(),
        )

    def _from_screen(self, point: QPointF) -> tuple[float, float]:
        rect = self._plot_rect()
        x = ((point.x() - rect.left()) / rect.width()) * self._x_max
        y = ((rect.bottom() - point.y()) / rect.height()) * self._y_max
        return max(0.0, min(self._x_max, x)), max(0.0, min(self._y_max, y))

    def _nearest(self, position: QPointF, radius: float = 11.0) -> int:
        best = -1
        best_distance = radius * radius
        for index, (x, y) in enumerate(self._points):
            screen = self._to_screen(x, y)
            distance = (screen.x() - position.x()) ** 2 + (screen.y() - position.y()) ** 2
            if distance <= best_distance:
                best = index
                best_distance = distance
        return best

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self._plot_rect()

        grid_pen = QPen(QColor("#26384d"), 1)
        painter.setPen(grid_pen)
        for step in range(6):
            ratio = step / 5.0
            x = rect.left() + ratio * rect.width()
            y = rect.bottom() - ratio * rect.height()
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))

        painter.setPen(QPen(QColor("#62758d"), 1))
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        painter.drawLine(rect.bottomLeft(), rect.topLeft())

        painter.setPen(QColor("#8ea1b7"))
        font = painter.font()
        font.setPointSize(max(7, font.pointSize() - 1))
        painter.setFont(font)
        painter.drawText(QRectF(0, rect.bottom() - 9, self._pad_left - 6, 18), Qt.AlignmentFlag.AlignRight, "0")
        painter.drawText(QRectF(rect.right() - 55, rect.bottom() + 5, 55, 20), Qt.AlignmentFlag.AlignRight, f"{self._x_max:g}")
        painter.drawText(QRectF(0, rect.top() - 8, self._pad_left - 6, 20), Qt.AlignmentFlag.AlignRight, f"{self._y_max:g}")

        if self._points:
            path = QPainterPath()
            first = self._to_screen(*self._points[0])
            path.moveTo(first)
            for point in self._points[1:]:
                path.lineTo(self._to_screen(*point))
            painter.setPen(QPen(QColor("#65c9ae"), 2.2))
            painter.drawPath(path)

        for index, point in enumerate(self._points):
            screen = self._to_screen(*point)
            radius = 6.0 if index in {self._hover_index, self._drag_index} else 4.5
            painter.setPen(QPen(QColor("#d7f7ee"), 1.2))
            painter.setBrush(QColor("#65c9ae") if index != self._drag_index else QColor("#f0c86a"))
            painter.drawEllipse(screen, radius, radius)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_index = self._nearest(event.position())
            self.update()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_index >= 0:
            x, y = self._from_screen(event.position())
            index = self._drag_index
            if index > 0:
                x = max(x, self._points[index - 1][0] + self._x_max * 0.001)
            if index + 1 < len(self._points):
                x = min(x, self._points[index + 1][0] - self._x_max * 0.001)
            if index > 0:
                y = max(y, self._points[index - 1][1])
            if index + 1 < len(self._points):
                y = min(y, self._points[index + 1][1])
            self._points[index] = [x, y]
            self.pointMoved.emit(index, x, y)
            self.update()
        else:
            hover = self._nearest(event.position())
            if hover != self._hover_index:
                self._hover_index = hover
                self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_index = -1
        self.update()
        super().mouseReleaseEvent(event)


class CurveEditor(QWidget):
    valueChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._points: list[list[float]] = []
        self._x_probability = False
        self._y_probability = False
        self._loading = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.canvas = CurveCanvas()
        layout.addWidget(self.canvas)
        self.hint = QLabel("")
        self.hint.setObjectName("muted")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

        self.table = QTableWidget(0, 2)
        # Placeholder headers only: pages_weights always calls set_labels()
        # with translated labels before the curve page becomes visible.
        self.table.setHorizontalHeaderLabels(["", ""])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setMaximumHeight(190)
        layout.addWidget(self.table)

        actions = QHBoxLayout()
        self.add_button = QPushButton("Ajouter un point")
        self.remove_button = QPushButton("Supprimer le point")
        actions.addWidget(self.add_button)
        actions.addWidget(self.remove_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.canvas.pointMoved.connect(self._canvas_moved)
        self.table.cellChanged.connect(self._table_changed)
        self.add_button.clicked.connect(self._add_point)
        self.remove_button.clicked.connect(self._remove_point)

    def set_labels(self, x_label: str, y_label: str, hint: str) -> None:
        self.table.setHorizontalHeaderLabels([x_label, y_label])
        self.hint.setText(hint)

    def set_value(self, points: list[list[float]], *, x_probability: bool, y_probability: bool) -> None:
        self._loading = True
        self._x_probability = x_probability
        self._y_probability = y_probability
        self._points = [[float(x), float(y)] for x, y in points]
        self._rebuild_table()
        self._sync_canvas()
        self._loading = False

    def value(self) -> list[list[float]]:
        return [[float(x), float(y)] for x, y in self._points]

    def _display(self, value: float, probability: bool) -> float:
        return value * 100.0 if probability else value

    def _storage(self, value: float, probability: bool) -> float:
        return value / 100.0 if probability else value

    def _rebuild_table(self) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(len(self._points))
        for row, (x, y) in enumerate(self._points):
            for column, (value, probability) in enumerate(((x, self._x_probability), (y, self._y_probability))):
                item = QTableWidgetItem(f"{self._display(value, probability):.2f}".rstrip("0").rstrip("."))
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(row, column, item)
        self.table.blockSignals(False)

    def _limits(self) -> tuple[float, float]:
        x_max = 1.0 if self._x_probability else max(1.0, max((p[0] for p in self._points), default=1.0))
        y_max = 1.0 if self._y_probability else max(100.0, max((p[1] for p in self._points), default=100.0))
        return x_max, y_max

    def _sync_canvas(self) -> None:
        x_max, y_max = self._limits()
        self.canvas.set_curve(self._points, x_max, y_max)

    def _canvas_moved(self, index: int, x: float, y: float) -> None:
        if index < 0 or index >= len(self._points):
            return
        self._points[index] = [round(x, 6), round(y, 6)]
        self._rebuild_table()
        self.valueChanged.emit()

    def _table_changed(self, row: int, column: int) -> None:
        if self._loading or row < 0 or row >= len(self._points):
            return
        item = self.table.item(row, column)
        try:
            displayed = float(item.text().replace(",", ".")) if item else 0.0
        except ValueError:
            self._rebuild_table()
            return
        probability = self._x_probability if column == 0 else self._y_probability
        value = self._storage(displayed, probability)
        value = max(0.0, min(1.0, value)) if probability else max(0.0, value)
        self._points[row][column] = value
        self._points.sort(key=lambda point: point[0])
        for index in range(1, len(self._points)):
            self._points[index][1] = max(self._points[index][1], self._points[index - 1][1])
        self._rebuild_table()
        self._sync_canvas()
        self.valueChanged.emit()

    def _add_point(self) -> None:
        if len(self._points) < 2:
            self._points.append([0.5, 0.5 if self._y_probability else 50.0])
        else:
            row = self.table.currentRow()
            left = max(0, min(row if row >= 0 else len(self._points) - 2, len(self._points) - 2))
            x1, y1 = self._points[left]
            x2, y2 = self._points[left + 1]
            self._points.insert(left + 1, [(x1 + x2) / 2.0, (y1 + y2) / 2.0])
        self._rebuild_table()
        self._sync_canvas()
        self.valueChanged.emit()

    def _remove_point(self) -> None:
        row = self.table.currentRow()
        if row < 0 or len(self._points) <= 2:
            return
        del self._points[row]
        self._rebuild_table()
        self._sync_canvas()
        self.valueChanged.emit()
