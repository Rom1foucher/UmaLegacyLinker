from __future__ import annotations

import math
from typing import Any

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QTextBrowser,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from ui_qt.asset_catalog import race_banner_url, skill_icon_url, trainee_image_url
from ui_qt.context import AppContext
from ui_qt.image_assets import (
    ImageRepository,
    image_repository,
    online_images_enabled,
    set_online_images_enabled,
)
from ui_qt.lineage_nodes import (
    GREAT_GRANDPARENT_POSITIONS,
    build_result_lineage_nodes,
)
from ui_qt.theme import COLORS, SPARK_COLORS


PARENT_POSITIONS = ("p1", "p2")
GRANDPARENT_POSITIONS = ("p1-1", "p1-2", "p2-1", "p2-2")
POSITION_ORDER = ("target",) + PARENT_POSITIONS + GRANDPARENT_POSITIONS + GREAT_GRANDPARENT_POSITIONS


def _number(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _optional_number(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _human_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _factor_style(factor: dict[str, Any]) -> tuple[str, str, str]:
    if factor.get("is_score_priority"):
        return SPARK_COLORS["white_priority"]
    if factor.get("is_score_useful"):
        return SPARK_COLORS["white_useful"]
    return SPARK_COLORS.get(str(factor.get("type") or "other"), SPARK_COLORS["other"])


def _factor_marker(factor: dict[str, Any]) -> str:
    if factor.get("is_score_priority"):
        return "◆ "
    if factor.get("is_score_useful"):
        return "◇ "
    return ""


def _run_probability(factor: dict[str, Any]) -> float | None:
    if str(factor.get("type") or "") not in {"white_skill", "white_race"}:
        return None
    probability = _optional_number(factor.get("proc_probability_over_run"))
    return None if probability is None else max(0.0, min(probability, 1.0))


def _probability_text(probability: float | None) -> str:
    return "" if probability is None else f"{100.0 * probability:.2f}%"


class LineageTree(QWidget):
    """Scrollable top-down lineage diagram with rich Spark cards."""

    BASE_WIDTH = 1560

    def __init__(
        self,
        context: AppContext,
        nodes: dict[str, dict[str, Any]],
        repository: ImageRepository,
        mode: str = "pair",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.context = context
        self.nodes = dict(nodes)
        self.repository = repository
        self.mode = mode
        self._pixmaps: dict[str, QPixmap] = {}
        self._node_urls: dict[str, str] = {}
        self._skill_urls: dict[tuple[str, int], str] = {}
        self._card_rects: dict[str, QRectF] = {}
        self._spark_rects: list[tuple[QRectF, str, dict[str, Any]]] = []
        self._role_labels: dict[str, str] = {}
        self._generation_labels: dict[str, str] = {}
        self._height_update_pending = False
        self._scheduled_minimum_height: int | None = None
        self._height_timer = QTimer(self)
        self._height_timer.setSingleShot(True)
        self._height_timer.timeout.connect(self._apply_scheduled_height)
        self.setMouseTracking(True)
        self.setMinimumSize(self.BASE_WIDTH, 1080)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.repository.image_ready.connect(self._image_ready)
        self.repository.image_failed.connect(self._image_failed)
        self.retranslate()
        self.refresh_images()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.BASE_WIDTH, max(1080, self.minimumHeight()))

    def retranslate(self) -> None:
        t = self.context.t
        if self.mode in {"grandparent_pair", "online_grandparent", "future"}:
            self._role_labels = {
                "target": t("Parent à produire"),
                "p1": t("GP local") if self.mode != "future" else t("GP candidat"),
                "p2": t("GP distant"),
                "p1-1": t("Parent actuel du GP 1A"),
                "p1-2": t("Parent actuel du GP 1B"),
                "p2-1": t("Parent actuel du GP 2A"),
                "p2-2": t("Parent actuel du GP 2B"),
            }
            self._generation_labels = {
                "target": t("Parent à produire"),
                "parent": t("Grands-parents sélectionnés"),
                "grandparent": t("Parents actuels des grands-parents"),
                "great": t("Historique antérieur"),
            }
        else:
            self._role_labels = {
                "target": t("Ace visé"),
                "p1": t("Parent candidat") if self.mode == "branch" else t("Parent 1"),
                "p2": t("Parent 2"),
                "p1-1": t("GP 1A"),
                "p1-2": t("GP 1B"),
                "p2-1": t("GP 2A"),
                "p2-2": t("GP 2B"),
            }
            self._generation_labels = {
                "target": t("Cible"),
                "parent": t("Parent candidat") if self.mode == "branch" else t("Parents directs"),
                "grandparent": t("Grands-parents"),
                "great": t("Arrière-grands-parents · historique visuel"),
            }
        for position in GREAT_GRANDPARENT_POSITIONS:
            self._role_labels.setdefault(position, t("Historique antérieur"))
        names = [str(node.get("card_name") or node.get("uma_name") or "") for node in self.nodes.values()]
        self.setAccessibleName(t("Vue de lignée"))
        self.setAccessibleDescription(" · ".join(name for name in names if name))
        self.update()

    def refresh_images(self) -> None:
        self._pixmaps.clear()
        self._node_urls.clear()
        self._skill_urls.clear()
        for position, node in self.nodes.items():
            trainee_url = trainee_image_url(node.get("card_id"))
            if trainee_url:
                self._node_urls[position] = trainee_url
                self._request_pixmap(trainee_url)
            for index, factor in enumerate(node.get("sparks") or []):
                if not isinstance(factor, dict):
                    continue
                icon_url = skill_icon_url(factor.get("skill_id"))
                if icon_url:
                    self._skill_urls[(position, index)] = icon_url
                    self._request_pixmap(icon_url)
        self.update()

    def _request_pixmap(self, url: str) -> None:
        pixmap = self.repository.pixmap(url)
        if pixmap is not None:
            self._pixmaps[url] = pixmap

    def _image_ready(self, url: str, pixmap: object) -> None:
        if isinstance(pixmap, QPixmap) and not pixmap.isNull():
            self._pixmaps[url] = pixmap
            self.update()

    def _image_failed(self, url: str) -> None:
        if url in self._node_urls.values() or url in self._skill_urls.values():
            self.update()

    def _spark_font(self) -> QFont:
        font = QFont(self.font())
        font.setPointSizeF(7.6)
        font.setBold(True)
        return font

    def _spark_chip_width(self, factor: dict[str, Any], maximum: float) -> float:
        metrics = QFontMetrics(self._spark_font())
        stars = max(0, int(factor.get("stars") or 0))
        marker = _factor_marker(factor)
        text = f"{marker}{stars}★  {factor.get('name') or '—'}"
        probability = _probability_text(_run_probability(factor))
        if probability:
            text += f"  {probability}"
        icon_width = 21 if factor.get("skill_id") else 0
        return min(maximum, max(92.0, float(metrics.horizontalAdvance(text) + 20 + icon_width)))

    def _spark_layout(
        self,
        position: str,
        node: dict[str, Any],
        area: QRectF,
    ) -> tuple[list[tuple[QRectF, dict[str, Any], int]], float]:
        x = area.left()
        y = area.top()
        row_height = 25.0
        gap = 5.0
        result: list[tuple[QRectF, dict[str, Any], int]] = []
        for index, factor in enumerate(node.get("sparks") or []):
            if not isinstance(factor, dict):
                continue
            width = self._spark_chip_width(factor, area.width())
            if x > area.left() and x + width > area.right() + 0.1:
                x = area.left()
                y += row_height + gap
            result.append((QRectF(x, y, width, row_height), factor, index))
            x += width + gap
        used = 0.0 if not result else result[-1][0].bottom() - area.top()
        return result, used

    def _card_height(self, position: str, width: float) -> float:
        if position == "target":
            return 104.0
        if position in GREAT_GRANDPARENT_POSITIONS:
            return 72.0
        node = self.nodes.get(position) or {}
        area = QRectF(0.0, 0.0, max(80.0, width - 24.0), 1000.0)
        _chips, used = self._spark_layout(position, node, area)
        return max(164.0, 143.0 + used)

    def _schedule_height(self, height: float) -> None:
        required = max(760, int(math.ceil(height)))
        if abs(self.minimumHeight() - required) <= 1:
            return
        self._scheduled_minimum_height = required
        if not self._height_update_pending:
            self._height_update_pending = True
            self._height_timer.start(0)

    def _apply_scheduled_height(self) -> None:
        required = self._scheduled_minimum_height
        self._scheduled_minimum_height = None
        self._height_update_pending = False
        if required is not None and abs(self.minimumHeight() - required) > 1:
            self.setMinimumHeight(required)
            self.updateGeometry()

    def _layout_rects(self) -> dict[str, QRectF]:
        width = max(float(self.width()), float(self.BASE_WIDTH))
        margin = 42.0
        direct_positions = (
            ("p1",)
            if self.mode in {"branch", "future"}
            else PARENT_POSITIONS
        )
        gp_positions = tuple(
            position
            for direct in direct_positions
            for position in (f"{direct}-1", f"{direct}-2")
        )

        target = QRectF((width - 470.0) / 2.0, 42.0, 470.0, self._card_height("target", 470.0))
        parent_y = target.bottom() + 94.0
        parent_width = 760.0 if len(direct_positions) == 1 else 600.0
        parent_gap = 86.0
        parent_heights = [self._card_height(position, parent_width) for position in direct_positions]
        parent_height = max(parent_heights, default=180.0)
        pair_width = parent_width * len(direct_positions) + parent_gap * (len(direct_positions) - 1)
        parent_x = (width - pair_width) / 2.0

        rects: dict[str, QRectF] = {"target": target}
        for index, position in enumerate(direct_positions):
            rects[position] = QRectF(
                parent_x + index * (parent_width + parent_gap),
                parent_y,
                parent_width,
                parent_height,
            )

        gp_y = parent_y + parent_height + 98.0
        gp_gap = 28.0 if len(gp_positions) == 2 else 22.0
        gp_width = min(
            520.0,
            (width - 2 * margin - max(0, len(gp_positions) - 1) * gp_gap)
            / max(1, len(gp_positions)),
        )
        gp_group_width = gp_width * len(gp_positions) + gp_gap * (len(gp_positions) - 1)
        gp_x = (width - gp_group_width) / 2.0
        gp_height = max(
            (self._card_height(position, gp_width) for position in gp_positions),
            default=180.0,
        )
        for index, position in enumerate(gp_positions):
            rects[position] = QRectF(
                gp_x + index * (gp_width + gp_gap), gp_y, gp_width, gp_height
            )

        great_positions = tuple(
            position
            for gp in gp_positions
            for position in (f"{gp}-1", f"{gp}-2")
        )
        great_present = any(position in self.nodes for position in great_positions)
        required_bottom = gp_y + gp_height + 44.0
        if great_present:
            great_gap = 10.0
            great_width = (
                width - 2 * margin - max(0, len(great_positions) - 1) * great_gap
            ) / max(1, len(great_positions))
            great_y = gp_y + gp_height + 78.0
            for index, position in enumerate(great_positions):
                rects[position] = QRectF(
                    margin + index * (great_width + great_gap),
                    great_y,
                    great_width,
                    self._card_height(position, great_width),
                )
            required_bottom = great_y + 72.0 + 42.0
        self._schedule_height(required_bottom)
        return rects

    @staticmethod
    def _draw_branch(
        painter: QPainter,
        source: QRectF,
        targets: list[QRectF],
        color: str,
    ) -> None:
        if not targets:
            return
        start = QPointF(source.center().x(), source.bottom() + 2.0)
        ends = [QPointF(target.center().x(), target.top() - 2.0) for target in targets]
        trunk_y = start.y() + max(24.0, (min(end.y() for end in ends) - start.y()) * 0.47)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(color), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(start, QPointF(start.x(), trunk_y))
        painter.drawLine(QPointF(min(end.x() for end in ends), trunk_y), QPointF(max(end.x() for end in ends), trunk_y))
        for end in ends:
            painter.drawLine(QPointF(end.x(), trunk_y), end)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.fillRect(self.rect(), QColor(COLORS["background"]))
        rects = self._layout_rects()
        self._card_rects = rects
        self._spark_rects = []

        direct_positions = [
            position for position in PARENT_POSITIONS if position in rects
        ]
        self._draw_branch(
            painter,
            rects["target"],
            [rects[position] for position in direct_positions],
            "#4d645f",
        )
        for direct, color in (("p1", "#426e65"), ("p2", "#46658f")):
            if direct not in rects:
                continue
            children = [
                rects[position]
                for position in (f"{direct}-1", f"{direct}-2")
                if position in rects
            ]
            self._draw_branch(painter, rects[direct], children, color)
        if any(position in rects for position in GREAT_GRANDPARENT_POSITIONS):
            for gp in GRANDPARENT_POSITIONS:
                if gp not in rects:
                    continue
                children = [rects[position] for position in (f"{gp}-1", f"{gp}-2") if position in rects]
                self._draw_branch(painter, rects[gp], children, "#394451")

        self._draw_generation_label(painter, rects["target"].top() - 30.0, self._generation_labels["target"])
        if "p1" in rects:
            self._draw_generation_label(painter, rects["p1"].top() - 31.0, self._generation_labels["parent"])
        if "p1-1" in rects:
            self._draw_generation_label(painter, rects["p1-1"].top() - 31.0, self._generation_labels["grandparent"])
        if "p1-1-1" in rects:
            self._draw_generation_label(painter, rects["p1-1-1"].top() - 31.0, self._generation_labels["great"])

        for position in POSITION_ORDER:
            rect = rects.get(position)
            if rect is None:
                continue
            self._draw_affinity_tag(painter, position, rect)
            self._draw_card(painter, position, rect, self.nodes.get(position))

    def _draw_generation_label(self, painter: QPainter, y: float, text: str) -> None:
        font = QFont(self.font())
        font.setPointSizeF(8.0)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#72849d"))
        painter.drawText(
            QRectF(0.0, y, float(self.width()), 22.0),
            Qt.AlignmentFlag.AlignCenter,
            text.upper(),
        )

    def _draw_affinity_tag(self, painter: QPainter, position: str, rect: QRectF) -> None:
        node = self.nodes.get(position) or {}
        affinity = _optional_number(node.get("inheritance_affinity"))
        if affinity is None or position == "target" or position in GREAT_GRANDPARENT_POSITIONS:
            return
        text = f"♥ {affinity:.0f}"
        font = QFont(self.font())
        font.setPointSizeF(10.0)
        font.setBold(True)
        metrics = QFontMetrics(font)
        width = metrics.horizontalAdvance(text) + 24.0
        tag = QRectF(rect.center().x() - width / 2.0, rect.top() - 29.0, width, 24.0)
        painter.setFont(font)
        painter.setBrush(QColor("#111923"))
        painter.setPen(QPen(QColor("#3d5675"), 1.0))
        painter.drawRoundedRect(tag, 11.0, 11.0)
        painter.setPen(QColor("#ff7ca5" if position in PARENT_POSITIONS else "#77b6ff"))
        painter.drawText(tag, Qt.AlignmentFlag.AlignCenter, text)

    def _draw_card(
        self,
        painter: QPainter,
        position: str,
        rect: QRectF,
        node: dict[str, Any] | None,
    ) -> None:
        compact = position in GREAT_GRANDPARENT_POSITIONS
        border = {
            "target": COLORS["accent"],
            "p1": "#4aa58c",
            "p2": "#4e82c4",
        }.get(position, "#3a4656" if compact else COLORS["border"])
        fill = {
            "target": "#162724",
            "p1": "#171f1e",
            "p2": "#171e29",
        }.get(position, "#171c24")
        painter.setBrush(QColor(fill))
        painter.setPen(QPen(QColor(border), 1.4 if position in {"target", "p1", "p2"} else 1.0))
        painter.drawRoundedRect(rect, 11.0, 11.0)

        if not node:
            self._draw_missing_card(painter, position, rect)
            return
        if compact:
            self._draw_compact_card(painter, position, rect, node)
            return

        role_font = QFont(self.font())
        role_font.setPointSizeF(7.2)
        role_font.setBold(True)
        painter.setFont(role_font)
        painter.setPen(QColor(border))
        painter.drawText(
            QRectF(rect.left() + 13.0, rect.top() + 7.0, rect.width() - 26.0, 17.0),
            Qt.AlignmentFlag.AlignVCenter,
            self._role_labels.get(position, position).upper(),
        )

        image_size = 68.0 if position in PARENT_POSITIONS else 60.0
        if position == "target":
            image_size = 70.0
        image_rect = QRectF(rect.left() + 13.0, rect.top() + 29.0, image_size, image_size)
        self._draw_node_image(painter, position, image_rect, node)

        text_left = image_rect.right() + 13.0
        text_width = max(60.0, rect.right() - text_left - 13.0)
        primary = str(node.get("card_name") or node.get("uma_name") or "—")
        secondary = str(node.get("uma_name") or "")
        name_font = QFont(self.font())
        name_font.setPointSizeF(10.2 if position in PARENT_POSITIONS else 9.4)
        name_font.setBold(True)
        painter.setFont(name_font)
        painter.setPen(QColor(COLORS["text"]))
        primary_visible = painter.fontMetrics().elidedText(
            primary, Qt.TextElideMode.ElideRight, max(20, int(text_width))
        )
        painter.drawText(
            QRectF(text_left, rect.top() + 31.0, text_width, 22.0),
            Qt.AlignmentFlag.AlignVCenter,
            primary_visible,
        )

        detail_font = QFont(self.font())
        detail_font.setPointSizeF(7.8)
        painter.setFont(detail_font)
        painter.setPen(QColor(COLORS["muted"]))
        if secondary and secondary.casefold() != primary.casefold():
            secondary_visible = painter.fontMetrics().elidedText(
                secondary, Qt.TextElideMode.ElideRight, max(20, int(text_width))
            )
        else:
            card_id = node.get("card_id")
            secondary_visible = f"#{card_id}" if card_id else self.context.t("Costume inconnu")
        painter.drawText(
            QRectF(text_left, rect.top() + 53.0, text_width, 18.0),
            Qt.AlignmentFlag.AlignVCenter,
            secondary_visible,
        )
        meta: list[str] = []
        if node.get("card_id") and not secondary_visible.startswith("#"):
            meta.append(f"#{node['card_id']}")
        if int(node.get("g1_count") or 0):
            meta.append(f"{int(node['g1_count'])} G1")
        if node.get("rank"):
            meta.append(str(node["rank"]))
        painter.drawText(
            QRectF(text_left, rect.top() + 73.0, text_width, 17.0),
            Qt.AlignmentFlag.AlignVCenter,
            painter.fontMetrics().elidedText(
                " · ".join(meta) or "—", Qt.TextElideMode.ElideRight, max(20, int(text_width))
            ),
        )

        if position == "target":
            return
        divider_y = rect.top() + 111.0
        painter.setPen(QPen(QColor("#283442"), 1.0))
        painter.drawLine(
            QPointF(rect.left() + 12.0, divider_y),
            QPointF(rect.right() - 12.0, divider_y),
        )
        section_font = QFont(self.font())
        section_font.setPointSizeF(7.0)
        section_font.setBold(True)
        painter.setFont(section_font)
        painter.setPen(QColor("#73839a"))
        painter.drawText(
            QRectF(rect.left() + 13.0, divider_y + 6.0, 100.0, 17.0),
            Qt.AlignmentFlag.AlignVCenter,
            self.context.t("Sparks").upper(),
        )
        chips, _used = self._spark_layout(
            position,
            node,
            QRectF(rect.left() + 12.0, divider_y + 29.0, rect.width() - 24.0, rect.height() - 145.0),
        )
        for chip_rect, factor, index in chips:
            self._draw_spark_chip(painter, position, index, chip_rect, factor)
            self._spark_rects.append((chip_rect, position, factor))

    def _draw_missing_card(self, painter: QPainter, position: str, rect: QRectF) -> None:
        role_font = QFont(self.font())
        role_font.setPointSizeF(7.2)
        role_font.setBold(True)
        painter.setFont(role_font)
        painter.setPen(QColor("#65758b"))
        painter.drawText(
            rect.adjusted(12.0, 8.0, -12.0, -8.0),
            Qt.AlignmentFlag.AlignCenter,
            self.context.t("Donnée indisponible"),
        )

    def _draw_compact_card(
        self,
        painter: QPainter,
        position: str,
        rect: QRectF,
        node: dict[str, Any],
    ) -> None:
        image_rect = QRectF(rect.left() + 9.0, rect.top() + 9.0, 52.0, 52.0)
        self._draw_node_image(painter, position, image_rect, node)
        left = image_rect.right() + 9.0
        width = rect.right() - left - 8.0
        name_font = QFont(self.font())
        name_font.setPointSizeF(8.0)
        name_font.setBold(True)
        painter.setFont(name_font)
        painter.setPen(QColor(COLORS["text"]))
        name = str(node.get("card_name") or node.get("uma_name") or "—")
        painter.drawText(
            QRectF(left, rect.top() + 12.0, width, 22.0),
            Qt.AlignmentFlag.AlignVCenter,
            painter.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, max(15, int(width))),
        )
        detail_font = QFont(self.font())
        detail_font.setPointSizeF(6.7)
        painter.setFont(detail_font)
        painter.setPen(QColor(COLORS["muted"]))
        painter.drawText(
            QRectF(left, rect.top() + 35.0, width, 18.0),
            Qt.AlignmentFlag.AlignVCenter,
            painter.fontMetrics().elidedText(
                self._role_labels.get(position, position),
                Qt.TextElideMode.ElideRight,
                max(15, int(width)),
            ),
        )

    def _draw_node_image(
        self,
        painter: QPainter,
        position: str,
        rect: QRectF,
        node: dict[str, Any],
    ) -> None:
        painter.setBrush(QColor("#0d131c"))
        painter.setPen(QPen(QColor("#303c4e"), 1.0))
        painter.drawRoundedRect(rect, 8.0, 8.0)
        url = self._node_urls.get(position)
        pixmap = self._pixmaps.get(url or "")
        if pixmap is None or pixmap.isNull():
            self._draw_placeholder(painter, rect, node, position)
            return
        scaled = pixmap.scaled(
            rect.size().toSize(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        target = QRectF(
            rect.center().x() - scaled.width() / 2.0,
            rect.center().y() - scaled.height() / 2.0,
            float(scaled.width()),
            float(scaled.height()),
        )
        clip = QPainterPath()
        clip.addRoundedRect(rect.adjusted(1.0, 1.0, -1.0, -1.0), 7.0, 7.0)
        painter.save()
        painter.setClipPath(clip)
        painter.drawPixmap(target, scaled, QRectF(scaled.rect()))
        painter.restore()

    def _draw_placeholder(
        self,
        painter: QPainter,
        rect: QRectF,
        node: dict[str, Any] | None,
        position: str,
    ) -> None:
        colors = ("#28584f", "#2d4d76", "#554467", "#735044")
        card_id = int((node or {}).get("card_id") or 0)
        color = colors[(card_id or sum(map(ord, position))) % len(colors)]
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0.0, QColor(color))
        gradient.setColorAt(1.0, QColor("#111a27"))
        painter.setBrush(gradient)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect.adjusted(1.0, 1.0, -1.0, -1.0), 7.0, 7.0)
        name = str((node or {}).get("uma_name") or (node or {}).get("card_name") or "?")
        initials = "".join(part[0] for part in name.split()[:2] if part)[:2].upper() or "?"
        font = QFont(self.font())
        font.setPointSizeF(max(10.0, min(16.0, rect.height() / 4.0)))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#edf4ff"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, initials)

    def _draw_spark_chip(
        self,
        painter: QPainter,
        position: str,
        index: int,
        rect: QRectF,
        factor: dict[str, Any],
    ) -> None:
        background, border, foreground = _factor_style(factor)
        painter.setBrush(QColor(background))
        border_width = (
            1.8
            if factor.get("is_score_priority")
            else 1.4
            if factor.get("is_score_useful")
            else 1.0
        )
        painter.setPen(QPen(QColor(border), border_width))
        painter.drawRoundedRect(rect, 5.0, 5.0)
        left = rect.left() + 7.0
        icon_url = self._skill_urls.get((position, index))
        icon = self._pixmaps.get(icon_url or "")
        if icon is not None and not icon.isNull():
            icon_rect = QRectF(left, rect.top() + 3.0, 19.0, 19.0)
            scaled = icon.scaled(
                icon_rect.size().toSize(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(icon_rect, scaled, QRectF(scaled.rect()))
            left = icon_rect.right() + 5.0

        font = self._spark_font()
        painter.setFont(font)
        probability_text = _probability_text(_run_probability(factor))
        probability_width = (
            painter.fontMetrics().horizontalAdvance(probability_text) + 12.0
            if probability_text
            else 0.0
        )
        stars = max(0, int(factor.get("stars") or 0))
        marker = _factor_marker(factor)
        name = f"{marker}{stars}★  {factor.get('name') or '—'}"
        available = max(12, int(rect.right() - left - 7.0 - probability_width))
        visible = painter.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, available)
        painter.setPen(QColor(foreground))
        painter.drawText(
            QRectF(left, rect.top(), float(available), rect.height()),
            Qt.AlignmentFlag.AlignVCenter,
            visible,
        )
        if probability_text:
            probability_rect = QRectF(
                rect.right() - probability_width,
                rect.top() + 3.0,
                probability_width - 4.0,
                rect.height() - 6.0,
            )
            painter.setBrush(QColor("#111821"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(probability_rect, 4.0, 4.0)
            if factor.get("is_score_priority"):
                probability_color = "#ffe9a3"
            elif factor.get("is_score_useful"):
                probability_color = "#bfe9ff"
            else:
                probability_color = "#f0f5fb"
            painter.setPen(QColor(probability_color))
            painter.drawText(probability_rect, Qt.AlignmentFlag.AlignCenter, probability_text)

    def _card_tooltip(self, position: str) -> str:
        node = self.nodes.get(position)
        if not node:
            return self.context.t("Donnée indisponible")
        lines = [
            self._role_labels.get(position, position),
            str(node.get("card_name") or node.get("uma_name") or "—"),
        ]
        if node.get("uma_name") and node.get("uma_name") != node.get("card_name"):
            lines.append(str(node["uma_name"]))
        if node.get("card_id"):
            lines.append(f"ID: {node['card_id']}")
        affinity = _optional_number(node.get("inheritance_affinity"))
        if affinity is not None:
            lines.append(f"{self.context.t('Affinité individuelle')}: {affinity:.0f}")
        return "\n".join(lines)

    def _spark_tooltip(self, factor: dict[str, Any]) -> str:
        lines = [
            str(factor.get("name") or "—"),
            f"{int(factor.get('stars') or 0)}★ · {factor.get('type') or 'other'}",
        ]
        probability = _run_probability(factor)
        if probability is not None:
            event_count = max(1, int(factor.get("inspiration_event_count") or 2))
            lines.append(
                self.context.t("Probabilité sur la run : {probability}")
                .replace("{probability}", _probability_text(probability))
            )
            lines.append(
                self.context.t("Au moins un proc parmi {count} Inspiration Events.")
                .replace("{count}", str(event_count))
            )
        if factor.get("is_score_priority"):
            rank = int(factor.get("score_priority_rank") or 0)
            lines.append(
                self.context.t("Priorité White #{rank} selon sa contribution au score de la lignée.")
                .replace("{rank}", str(rank))
            )
            skill_name = str(factor.get("priority_skill_name") or "")
            if skill_name and skill_name.casefold() != str(factor.get("name") or "").casefold():
                lines.append(
                    self.context.t("Skill valorisée : {skill}").replace("{skill}", skill_name)
                )
        elif factor.get("is_score_useful"):
            profile_weight = _optional_number(factor.get("profile_weight"))
            useful_text = self.context.t(
                "White compatible et utile pour ce profil, mise en avant même hors du top 3."
            )
            if profile_weight is not None:
                useful_text += " " + self.context.t("Poids effectif : {weight}.").replace(
                    "{weight}", f"{profile_weight:.2f}"
                )
            lines.append(useful_text)
        if factor.get("skill_id"):
            lines.append(f"Skill ID: {factor['skill_id']}")
        return "\n".join(lines)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        point = event.position()
        for rect, _position, factor in reversed(self._spark_rects):
            if rect.contains(point):
                QToolTip.showText(event.globalPosition().toPoint(), self._spark_tooltip(factor), self)
                return
        for position, rect in self._card_rects.items():
            if rect.contains(point):
                QToolTip.showText(event.globalPosition().toPoint(), self._card_tooltip(position), self)
                return
        QToolTip.hideText()

    def leaveEvent(self, event) -> None:  # noqa: N802
        QToolTip.hideText()
        super().leaveEvent(event)


class RaceCalendarWidget(QWidget):
    """Fixed, themed three-year calendar for race-affinity planning."""

    BASE_WIDTH = 1464
    YEAR_GAP = 18.0
    MONTHS = (
        "Jan.",
        "Fév.",
        "Mars",
        "Avr.",
        "Mai",
        "Juin",
        "Juil.",
        "Août",
        "Sept.",
        "Oct.",
        "Nov.",
        "Déc.",
    )
    YEAR_COLORS = {
        1: ("#17283a", COLORS["blue"]),
        2: ("#301a27", COLORS["warning"]),
        3: ("#17301D", COLORS["accent"]),
    }
    SOURCE_COLORS = {
        "shared": ("#3a3015", "#e6bd55", "#ffe5a0"),
        "local": ("#142943", "#5d9ee8", "#b9d9ff"),
        "remote": ("#29203f", "#9b7adb", "#ddceff"),
        "planned": ("#163039", "#55aebe", "#c1edf4"),
        "objective": ("#3a2025", "#d87b86", "#ffd1d6"),
        "other": ("#1b2736", "#63758d", "#d5dfeb"),
    }

    def __init__(
        self,
        context: AppContext,
        plan: dict[str, Any],
        repository: ImageRepository,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.context = context
        self.plan = dict(plan)
        self.repository = repository
        self._pixmaps: dict[str, QPixmap] = {}
        self._race_urls: dict[int, str] = {}
        self._race_rects: list[tuple[QRectF, dict[str, Any]]] = []
        self.setMouseTracking(True)
        # The calendar is a scrollable fixed canvas.  Letting a QScrollArea
        # stretch it both degraded the small race banners and used to make
        # sizeHint() mutate the minimum height, recursively triggering another
        # sizeHint() call until Python exhausted its stack.
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFixedSize(self.BASE_WIDTH, self._required_height())
        self.repository.image_ready.connect(self._image_ready)
        self.repository.image_failed.connect(self._image_failed)
        self.refresh_images()
        self.retranslate()

    def _races(self) -> list[dict[str, Any]]:
        return [
            race
            for race in self.plan.get("races") or []
            if isinstance(race, dict)
        ]

    def set_plan(self, plan: dict[str, Any]) -> None:
        """Swap a precomputed schedule variant without invoking the solver."""

        self.plan = dict(plan)
        self.refresh_images()
        self.setFixedSize(self.BASE_WIDTH, self._required_height())
        self.updateGeometry()
        self.update()

    def refresh_images(self) -> None:
        self._pixmaps.clear()
        self._race_urls.clear()
        for index, race in enumerate(self._races()):
            url = race_banner_url(race.get("race_id"), "en")
            if not url:
                continue
            self._race_urls[index] = url
            pixmap = self.repository.pixmap(url)
            if pixmap is not None:
                self._pixmaps[url] = pixmap
        self.update()

    def _image_ready(self, url: str, pixmap: object) -> None:
        if url not in self._race_urls.values():
            return
        if isinstance(pixmap, QPixmap) and not pixmap.isNull():
            self._pixmaps[url] = pixmap
            self.update()

    def _image_failed(self, url: str) -> None:
        if url in self._race_urls.values():
            self.update()

    def retranslate(self) -> None:
        self.setAccessibleName(self.context.t("Planning G1"))
        self.setAccessibleDescription(
            self.context.t(
                "G1 à gagner avec la nouvelle trainee : +6 si les deux parents l’ont gagnée, +3 si un seul parent l’a gagnée."
            )
        )
        self.update()

    def _calendar_entries(
        self,
    ) -> tuple[
        dict[tuple[int, int, int], list[tuple[int, dict[str, Any]]]],
        list[tuple[int, dict[str, Any]]],
    ]:
        scheduled: dict[tuple[int, int, int], list[tuple[int, dict[str, Any]]]] = {}
        unscheduled: list[tuple[int, dict[str, Any]]] = []
        for index, race in enumerate(self._races()):
            if "planned_slot" in race:
                planned = race.get("planned_slot")
                if isinstance(planned, dict):
                    try:
                        key = (
                            int(planned.get("year")),
                            int(planned.get("month")),
                            int(planned.get("half")),
                        )
                    except (TypeError, ValueError):
                        key = ()
                    if (
                        len(key) == 3
                        and key[0] in (1, 2, 3)
                        and 1 <= key[1] <= 12
                        and key[2] in (1, 2)
                    ):
                        scheduled.setdefault(key, []).append((index, race))
                else:
                    unscheduled.append((index, race))
                # Conflicts stay visible below the calendar. They remain useful
                # diagnostic data even though they are not in the executable
                # one-race-per-turn recommendation.
                continue
            valid_slots: set[tuple[int, int, int]] = set()
            for slot in race.get("schedule_slots") or []:
                if not isinstance(slot, dict):
                    continue
                try:
                    key = (
                        int(slot.get("year")),
                        int(slot.get("month")),
                        int(slot.get("half")),
                    )
                except (TypeError, ValueError):
                    continue
                if key[0] not in (1, 2, 3) or not 1 <= key[1] <= 12 or key[2] not in (1, 2):
                    continue
                valid_slots.add(key)
            if valid_slots:
                # A race available in both Classic and Senior still creates
                # only one race-affinity link. Plan it at its first available
                # occurrence instead of displaying (and suggesting) it twice.
                scheduled.setdefault(min(valid_slots), []).append((index, race))
            else:
                unscheduled.append((index, race))
        for items in scheduled.values():
            items.sort(
                key=lambda item: (
                    -int(item[1].get("affinity_bonus") or 0),
                    str(item[1].get("name") or "").casefold(),
                )
            )
        # Old diagnostics may not contain the solver's warning metadata.
        # Reconstruct it here so every 4+ run remains visible but is clearly
        # presented as a risky recommendation.
        for year in (1, 2, 3):
            current: list[tuple[int, int, int]] = []
            for month in range(1, 13):
                for half in (1, 2):
                    key = (year, month, half)
                    if key in scheduled:
                        current.append(key)
                        continue
                    self._mark_calendar_streak(scheduled, current)
                    current = []
            self._mark_calendar_streak(scheduled, current)
        return scheduled, unscheduled

    @staticmethod
    def _mark_calendar_streak(
        scheduled: dict[
            tuple[int, int, int],
            list[tuple[int, dict[str, Any]]],
        ],
        slots: list[tuple[int, int, int]],
    ) -> None:
        length = len(slots)
        for slot in slots:
            for _index, race in scheduled.get(slot, []):
                race["consecutive_race_count"] = length
                race["long_streak_warning"] = length >= 4

    def _layout_metrics(
        self,
    ) -> tuple[
        float,
        float,
        list[float],
        float,
        float,
        list[tuple[int, dict[str, Any]]],
        int,
    ]:
        """Return the immutable canvas metrics without changing widget geometry."""

        width = float(self.BASE_WIDTH)
        margin = 12.0
        column_width = (
            width - 2.0 * margin - 2.0 * self.YEAR_GAP
        ) / 12.0
        card_width = max(76.0, column_width - 10.0)
        card_height = min(50.0, max(38.0, card_width * 0.36))
        scheduled, unscheduled = self._calendar_entries()
        row_heights: list[float] = []
        for first_month in range(1, 13, 2):
            maximum = max(
                (
                    len(scheduled.get((year, month, half), []))
                    for year in (1, 2, 3)
                    for month in (first_month, first_month + 1)
                    for half in (1, 2)
                ),
                default=0,
            )
            card_rows = max(1, maximum)
            row_heights.append(max(78.0, 26.0 + card_rows * (card_height + 5.0) + 7.0))
        unknown_height = 0.0
        if unscheduled:
            unknown_height = 46.0 + math.ceil(len(unscheduled) / 4) * 31.0
        required = 52.0 + sum(row_heights) + unknown_height + 14.0
        required_int = max(200, int(math.ceil(required)))
        return (
            margin,
            column_width,
            row_heights,
            card_width,
            card_height,
            unscheduled,
            required_int,
        )

    def _required_height(self) -> int:
        return self._layout_metrics()[-1]

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.fillRect(self.rect(), QColor(COLORS["surface"]))
        (
            margin,
            column_width,
            row_heights,
            card_width,
            card_height,
            unscheduled,
            _required_height,
        ) = self._layout_metrics()
        scheduled, _ = self._calendar_entries()
        width = float(self.BASE_WIDTH)
        self._race_rects = []

        year_font = QFont(self.font())
        year_font.setPointSizeF(9.0)
        year_font.setBold(True)
        painter.setFont(year_font)
        year_names = {
            1: self.context.t("ANNÉE JUNIOR"),
            2: self.context.t("ANNÉE CLASSIQUE"),
            3: self.context.t("ANNÉE SENIOR"),
        }
        for year in (1, 2, 3):
            background, foreground = self.YEAR_COLORS[year]
            year_left = (
                margin
                + (year - 1) * (4.0 * column_width + self.YEAR_GAP)
            )
            rect = QRectF(
                year_left,
                7.0,
                4.0 * column_width - 3.0,
                30.0,
            )
            panel = QRectF(
                year_left - 4.0,
                3.0,
                4.0 * column_width + 5.0,
                42.0 + sum(row_heights),
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#101722"))
            painter.drawRoundedRect(panel, 10.0, 10.0)
            painter.setBrush(QColor(background))
            painter.drawRoundedRect(rect, 7.0, 7.0)
            painter.setPen(QColor(foreground))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, year_names[year])

        label_font = QFont(self.font())
        label_font.setPointSizeF(7.3)
        label_font.setBold(True)
        y = 45.0
        for row_index, row_height in enumerate(row_heights):
            first_month = row_index * 2 + 1
            for year in (1, 2, 3):
                for month_offset, month in enumerate((first_month, first_month + 1)):
                    for half in (1, 2):
                        column = (
                            month_offset * 2 + (half - 1)
                        )
                        year_left = (
                            margin
                            + (year - 1)
                            * (4.0 * column_width + self.YEAR_GAP)
                        )
                        cell = QRectF(
                            year_left + column * column_width,
                            y,
                            column_width - 3.0,
                            row_height - 3.0,
                        )
                        shade = "#111923" if (month + half) % 2 else "#131c27"
                        painter.setBrush(QColor(shade))
                        painter.setPen(QPen(QColor(COLORS["border"]), 0.75))
                        painter.drawRoundedRect(cell, 3.0, 3.0)
                        period = self.context.t("Début") if half == 1 else self.context.t("Fin")
                        header = f"{period} {self.context.t(self.MONTHS[month - 1])}"
                        painter.setFont(label_font)
                        painter.setPen(QColor(COLORS["muted"]))
                        painter.drawText(
                            QRectF(
                                cell.left() + 3.0,
                                cell.bottom() - 19.0,
                                cell.width() - 6.0,
                                16.0,
                            ),
                            Qt.AlignmentFlag.AlignCenter,
                            header,
                        )
                        for item_index, (race_index, race) in enumerate(
                            scheduled.get((year, month, half), [])
                        ):
                            card = QRectF(
                                cell.left() + 5.0,
                                cell.top() + 6.0 + item_index * (card_height + 5.0),
                                card_width,
                                card_height,
                            )
                            self._draw_race_card(painter, race_index, race, card)
            y += row_height

        if unscheduled:
            title_rect = QRectF(margin, y + 7.0, width - 2.0 * margin, 24.0)
            painter.setFont(year_font)
            painter.setPen(QColor(COLORS["muted"]))
            painter.drawText(
                title_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                self.context.t("COURSES NON PLACÉES DANS LE PLANNING OPTIMAL"),
            )
            chip_width = (width - 2.0 * margin - 3.0 * 8.0) / 4.0
            for index, (race_index, race) in enumerate(unscheduled):
                chip = QRectF(
                    margin + (index % 4) * (chip_width + 8.0),
                    y + 34.0 + (index // 4) * 30.0,
                    chip_width,
                    25.0,
                )
                self._draw_race_card(painter, race_index, race, chip, compact=True)

    def _draw_race_card(
        self,
        painter: QPainter,
        race_index: int,
        race: dict[str, Any],
        rect: QRectF,
        *,
        compact: bool = False,
    ) -> None:
        source_kind = self._source_kind(race)
        risky_streak = bool(race.get("long_streak_warning"))
        background, border, foreground = self.SOURCE_COLORS[source_kind]
        if risky_streak:
            background, border, foreground = ("#24282e", "#727b86", "#d2d7dd")
        painter.setBrush(QColor(background))
        painter.setPen(QPen(QColor(border), 1.5))
        painter.drawRoundedRect(rect, 5.0, 5.0)

        url = self._race_urls.get(race_index)
        pixmap = self._pixmaps.get(url or "")
        has_banner = pixmap is not None and not pixmap.isNull() and not compact
        if has_banner:
            target = rect.adjusted(2.0, 2.0, -2.0, -2.0)
            # Scale down to cover the card, but never enlarge a low-resolution
            # GameTora banner.  Any uncovered edge keeps the card background.
            cover_scale = max(
                target.width() / float(pixmap.width()),
                target.height() / float(pixmap.height()),
            )
            scale = min(1.0, cover_scale)
            scaled = pixmap.scaled(
                max(1, int(round(pixmap.width() * scale))),
                max(1, int(round(pixmap.height() * scale))),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            visible_width = min(target.width(), float(scaled.width()))
            visible_height = min(target.height(), float(scaled.height()))
            destination = QRectF(
                target.center().x() - visible_width / 2.0,
                target.center().y() - visible_height / 2.0,
                visible_width,
                visible_height,
            )
            source = QRectF(
                max(0.0, (scaled.width() - visible_width) / 2.0),
                max(0.0, (scaled.height() - visible_height) / 2.0),
                visible_width,
                visible_height,
            )
            painter.save()
            clip = QPainterPath()
            clip.addRoundedRect(target, 4.0, 4.0)
            painter.setClipPath(clip)
            painter.drawPixmap(destination, scaled, source)
            painter.restore()

        if risky_streak:
            painter.setBrush(QColor(77, 83, 92, 174))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rect.adjusted(1.0, 1.0, -1.0, -1.0), 4.0, 4.0)

        bonus_value = int(race.get("affinity_bonus") or 0)
        bonus = f"+{bonus_value}"
        badge_font = QFont(self.font())
        badge_font.setPointSizeF(7.2)
        badge_font.setBold(True)
        painter.setFont(badge_font)
        badge_width = 0.0
        if bonus_value > 0:
            badge_width = painter.fontMetrics().horizontalAdvance(bonus) + 10.0
            badge = QRectF(
                rect.right() - badge_width - 3.0,
                rect.top() + 3.0,
                badge_width,
                18.0,
            )
            painter.setBrush(QColor("#10221d"))
            painter.setPen(QPen(QColor(COLORS["accent"]), 1.0))
            painter.drawRoundedRect(badge, 7.0, 7.0)
            painter.setPen(QColor("#9aefd2"))
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, bonus)

        source_label = self._source_label(source_kind)
        source_width = painter.fontMetrics().horizontalAdvance(source_label) + 10.0
        source_badge = QRectF(
            rect.left() + 3.0,
            rect.top() + 3.0 if compact else rect.bottom() - 21.0,
            source_width,
            18.0,
        )
        painter.setBrush(QColor(background))
        painter.setPen(QPen(QColor(border), 1.0))
        painter.drawRoundedRect(source_badge, 7.0, 7.0)
        painter.setPen(QColor(foreground))
        painter.drawText(source_badge, Qt.AlignmentFlag.AlignCenter, source_label)

        name = str(race.get("name") or "G1")
        # The banner already contains the race title. Only render our own
        # label as a placeholder while the image is unavailable.
        if compact or not has_banner:
            text_font = QFont(self.font())
            text_font.setPointSizeF(7.6)
            text_font.setBold(True)
            painter.setFont(text_font)
            text_rect = rect.adjusted(
                source_width + 9.0 if compact else 7.0,
                2.0,
                -5.0,
                -2.0,
            )
            available = max(
                10,
                int(text_rect.width() - badge_width - 6.0),
            )
            visible = painter.fontMetrics().elidedText(
                name,
                Qt.TextElideMode.ElideRight,
                available,
            )
            painter.setPen(QColor("#f3f7fc"))
            painter.drawText(
                text_rect.adjusted(0.0, 0.0, -badge_width - 4.0, 0.0),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                visible,
            )
        self._race_rects.append((QRectF(rect), race))

    @staticmethod
    def _source_kind(race: dict[str, Any]) -> str:
        if race.get("objective_only"):
            return "objective"
        if race.get("shared"):
            return "shared"
        origins = {
            str(value or "").strip().casefold()
            for value in race.get("source_origins") or []
        }
        if origins & {"remote", "distant"}:
            return "remote"
        if "local" in origins:
            return "local"
        if "planned" in origins:
            return "planned"
        return "other"

    def _source_label(self, source_kind: str) -> str:
        labels = {
            "shared": "COMM.",
            "local": self.context.t("LOC."),
            "remote": self.context.t("DIST."),
            "planned": self.context.t("PROJ."),
            "objective": "OBJ.",
            "other": "G1",
        }
        return labels[source_kind]

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        point = event.position()
        for rect, race in reversed(self._race_rects):
            if not rect.contains(point):
                continue
            sources = ", ".join(str(value) for value in race.get("sources") or [])
            bonus = int(race.get("affinity_bonus") or 0)
            lines = [
                str(race.get("name") or "G1"),
                self.context.t("Bonus d’affinité planifié : +{bonus}")
                .replace("{bonus}", str(bonus)),
            ]
            if sources:
                lines.append(
                    self.context.t("Déjà gagnée par : {sources}")
                    .replace("{sources}", sources)
                )
            origins = {
                str(value or "").strip().casefold()
                for value in race.get("source_origins") or []
            }
            if len(origins) == 1:
                origin = next(iter(origins))
                if origin in {"local", "remote", "distant", "planned"}:
                    if origin == "local":
                        origin_label = self.context.t("locale")
                    elif origin == "planned":
                        origin_label = self.context.t("projetée")
                    else:
                        origin_label = self.context.t("distant")
                    lines.append(
                        self.context.t("Origine de la G1 : {origin}")
                        .replace("{origin}", origin_label)
                    )
            if race.get("mandatory_objective"):
                required = int(race.get("required_position") or 0)
                objective_line = self.context.t(
                    "Course d’objectif obligatoire du personnage visé."
                )
                if required > 0:
                    objective_line += " " + self.context.t(
                        "Position requise : {position} ou mieux."
                    ).replace("{position}", str(required))
                lines.append(objective_line)
            status = str(race.get("planning_status") or "")
            if status == "objective_conflict":
                lines.append(
                    self.context.t(
                        "G1 possible et utile pour l’affinité, mais non retenue : une course d’objectif obligatoire occupe ce tour."
                    )
                )
            elif status == "calendar_conflict":
                lines.append(
                    self.context.t(
                        "G1 possible et utile pour l’affinité, mais une course plus rentable occupe déjà ce tour."
                    )
                )
            elif status in {"missing_calendar", "unsupported_calendar"}:
                lines.append(
                    self.context.t(
                        "Cette course reste dans le diagnostic, mais sa date ne permet pas un placement fiable."
                    )
                )
            if race.get("long_streak_warning"):
                count = int(race.get("consecutive_race_count") or 4)
                lines.append(
                    self.context.t(
                        "Course possible et bonus d’affinité conservé. Elle fait partie d’une série de {count} courses consécutives, susceptible de réduire les chances de gagner."
                    ).replace("{count}", str(count))
                )
            QToolTip.showText(event.globalPosition().toPoint(), "\n".join(lines), self)
            return
        QToolTip.hideText()

    def leaveEvent(self, event) -> None:  # noqa: N802
        QToolTip.hideText()
        super().leaveEvent(event)


class GameRankGlyph(QWidget):
    """Small game-inspired rank letter with a gold fill and dark outline."""

    def __init__(self, rank: str = "S", parent=None) -> None:
        super().__init__(parent)
        self.rank = rank
        self.setFixedSize(42, 44)

    def set_rank(self, rank: str) -> None:
        self.rank = str(rank or "")
        self.setVisible(bool(self.rank))
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        if not self.rank:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont("Segoe UI Black")
        font.setPixelSize(34)
        font.setBold(True)
        path = QPainterPath()
        metrics = QFontMetrics(font)
        width = metrics.horizontalAdvance(self.rank)
        baseline = (self.height() + metrics.ascent() - metrics.descent()) / 2.0
        path.addText((self.width() - width) / 2.0, baseline, font, self.rank)
        painter.setBrush(QColor("#fff4a8"))
        painter.setPen(QPen(QColor("#7b5514"), 3.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawPath(path)
        painter.setPen(QPen(QColor("#f2bd31"), 1.0))
        painter.drawPath(path)


class GameMetricCard(QFrame):
    def __init__(self, *, accent: str = "#68d3b1", rank: str = "", parent=None) -> None:
        super().__init__(parent)
        self.accent = accent
        self.setObjectName("gameMetricCard")
        self.setMinimumWidth(126)
        self.setMinimumHeight(58)
        self.setStyleSheet(
            "QFrame#gameMetricCard {"
            " background:#121d2a; border:1px solid #30445e; border-radius:9px;"
            "}"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(9, 6, 10, 6)
        layout.setSpacing(5)
        self.rank_glyph = GameRankGlyph(rank)
        self.rank_glyph.setVisible(bool(rank))
        layout.addWidget(self.rank_glyph)
        text = QVBoxLayout()
        text.setSpacing(0)
        self.label = QLabel()
        self.label.setStyleSheet("color:#91a3bb; font-size:8pt; font-weight:650;")
        self.value = QLabel()
        self.value.setStyleSheet(
            f"color:{accent}; font-size:13pt; font-weight:750;"
        )
        text.addWidget(self.label)
        text.addWidget(self.value)
        layout.addLayout(text, 1)

    def set_metric(self, label: str, value: str, *, rank: str = "") -> None:
        self.label.setText(label)
        self.value.setText(value)
        self.value.setToolTip(f"{label}: {value}")
        self.rank_glyph.set_rank(rank)


class LineageDialog(QDialog):
    def __init__(
        self,
        context: AppContext,
        ace: dict[str, Any] | None,
        row: dict[str, Any],
        *,
        mode: str = "pair",
        details_html: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.context = context
        self.ace = dict(ace or {})
        self.row = dict(row)
        self.mode = mode
        self.repository = image_repository(context)
        self.setModal(True)
        self.setMinimumSize(980, 650)
        self.resize(1600, 930)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(10)

        heading = QHBoxLayout()
        heading_text = QVBoxLayout()
        self.title_label = QLabel()
        self.title_label.setObjectName("pageTitle")
        self.subtitle_label = QLabel()
        self.subtitle_label.setObjectName("muted")
        self.subtitle_label.setWordWrap(True)
        heading_text.addWidget(self.title_label)
        heading_text.addWidget(self.subtitle_label)
        heading.addLayout(heading_text, 1)
        self.score_badge = GameMetricCard(accent="#8af0d0")
        self.affinity_badge = GameMetricCard(accent="#ff82aa")
        self.distance_badge = GameMetricCard(accent="#f3ca59", rank="S")
        heading.addWidget(self.score_badge)
        heading.addWidget(self.affinity_badge)
        heading.addWidget(self.distance_badge)
        root.addLayout(heading)

        toolbar = QHBoxLayout()
        self.online_toggle = QCheckBox()
        self.online_toggle.setChecked(online_images_enabled(context))
        self.cache_label = QLabel()
        self.cache_label.setObjectName("muted")
        self.clear_cache_button = QPushButton()
        toolbar.addWidget(self.online_toggle)
        toolbar.addWidget(self.cache_label)
        toolbar.addStretch(1)
        toolbar.addWidget(self.clear_cache_button)
        root.addLayout(toolbar)

        self.nodes = build_result_lineage_nodes(self.ace, self.row, self.mode)
        self.tabs = QTabWidget()
        self.visual_page = QWidget()
        visual_layout = QVBoxLayout(self.visual_page)
        visual_layout.setContentsMargins(0, 0, 0, 0)
        self.spark_legend = QLabel()
        self.spark_legend.setObjectName("muted")
        self.spark_legend.setWordWrap(True)
        visual_layout.addWidget(self.spark_legend)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.tree = LineageTree(context, self.nodes, self.repository, self.mode)
        scroll.setWidget(self.tree)
        visual_layout.addWidget(scroll, 1)
        self.attribution = QLabel()
        self.attribution.setObjectName("muted")
        self.attribution.setOpenExternalLinks(True)
        self.attribution.setWordWrap(True)
        visual_layout.addWidget(self.attribution)
        self.tabs.addTab(self.visual_page, "")

        self.race_plan = (
            self.row.get("race_affinity_plan")
            or (self.row.get("affinity") or {}).get("race_affinity_plan")
            or (self.row.get("final_parent_affinity") or {}).get("race_affinity_plan")
            or (self.row.get("final_branch_affinity") or {}).get("race_affinity_plan")
            or {}
        )
        if not isinstance(self.race_plan, dict):
            self.race_plan = {}
        self.planning_page: QWidget | None = None
        self.calendar: RaceCalendarWidget | None = None
        self.planning_legend: QLabel | None = None
        self.planning_key: QLabel | None = None
        self.planning_title: QLabel | None = None
        self.trackblazer_toggle: QCheckBox | None = None
        if self.race_plan.get("races"):
            self.planning_page = QWidget()
            planning_layout = QVBoxLayout(self.planning_page)
            planning_layout.setContentsMargins(2, 4, 2, 0)
            planning_layout.setSpacing(8)
            planning_header = QFrame()
            planning_header.setObjectName("planningHeader")
            planning_header.setStyleSheet(
                "QFrame#planningHeader {"
                f" background:{COLORS['surface']};"
                f" border:1px solid {COLORS['border']};"
                " border-radius:10px;"
                "}"
                "QLabel#planningTitle {"
                f" color:{COLORS['text']}; font-size:12pt; font-weight:700;"
                "}"
                "QCheckBox#trackblazerToggle {"
                f" color:{COLORS['text']};"
                f" background:{COLORS['surface_alt']};"
                f" border:1px solid {COLORS['border']};"
                " border-radius:8px; padding:7px 11px;"
                "}"
                "QCheckBox#trackblazerToggle:checked {"
                f" color:{COLORS['accent']};"
                " background:#16342f; border-color:#34705f;"
                "}"
                "QCheckBox#trackblazerToggle:disabled { color:#647287; }"
            )
            header_layout = QVBoxLayout(planning_header)
            header_layout.setContentsMargins(13, 10, 13, 10)
            header_layout.setSpacing(5)
            mode_row = QHBoxLayout()
            self.planning_title = QLabel()
            self.planning_title.setObjectName("planningTitle")
            mode_row.addWidget(self.planning_title)
            mode_row.addStretch(1)
            self.trackblazer_toggle = QCheckBox()
            self.trackblazer_toggle.setObjectName("trackblazerToggle")
            variants = self.race_plan.get("schedule_variants") or {}
            has_trackblazer = isinstance(variants, dict) and isinstance(
                variants.get("trackblazer"),
                dict,
            )
            objective_count = int(self.race_plan.get("objective_race_count") or 0)
            self.trackblazer_toggle.setEnabled(
                has_trackblazer and objective_count > 0
            )
            mode_row.addWidget(self.trackblazer_toggle)
            header_layout.addLayout(mode_row)
            self.planning_key = QLabel()
            self.planning_key.setObjectName("muted")
            self.planning_key.setTextFormat(Qt.TextFormat.RichText)
            self.planning_key.setWordWrap(True)
            header_layout.addWidget(self.planning_key)
            self.planning_legend = QLabel()
            self.planning_legend.setObjectName("muted")
            self.planning_legend.setWordWrap(True)
            header_layout.addWidget(self.planning_legend)
            planning_layout.addWidget(planning_header)
            planning_scroll = QScrollArea()
            # The canvas keeps a stable banner size. At the default 1600×930
            # dialog size it fits without scrollbars; smaller windows can still
            # scroll instead of shrinking and pixelating the race artwork.
            planning_scroll.setWidgetResizable(False)
            planning_scroll.setFrameShape(QFrame.Shape.NoFrame)
            planning_scroll.setAlignment(
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
            )
            self.calendar = RaceCalendarWidget(
                context,
                self._active_race_plan(),
                self.repository,
            )
            planning_scroll.setWidget(self.calendar)
            planning_layout.addWidget(planning_scroll, 1)
            self.tabs.addTab(self.planning_page, "")

        self.details = QTextBrowser()
        self.details.setOpenExternalLinks(True)
        self.details.setHtml(details_html)
        self.tabs.addTab(self.details, "")
        root.addWidget(self.tabs, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        self.close_button = buttons.button(QDialogButtonBox.StandardButton.Close)
        root.addWidget(buttons)

        self.online_toggle.toggled.connect(self._toggle_online_images)
        self.clear_cache_button.clicked.connect(self._clear_cache)
        if self.trackblazer_toggle is not None:
            self.trackblazer_toggle.toggled.connect(
                self._toggle_trackblazer_schedule
            )
        self.repository.cache_changed.connect(self._update_cache_label)
        self.retranslate()

    def _active_race_plan(self) -> dict[str, Any]:
        variants = self.race_plan.get("schedule_variants") or {}
        mode = (
            "trackblazer"
            if self.trackblazer_toggle is not None
            and self.trackblazer_toggle.isChecked()
            else "standard"
        )
        if isinstance(variants, dict) and isinstance(variants.get(mode), dict):
            return variants[mode]
        return self.race_plan

    def _toggle_trackblazer_schedule(self, _enabled: bool) -> None:
        if self.calendar is not None:
            self.calendar.set_plan(self._active_race_plan())
        self._update_planning_copy()

    def _update_planning_copy(self) -> None:
        if self.planning_legend is None:
            return
        t = self.context.t
        plan = self._active_race_plan()
        shared_bonus = int(self.race_plan.get("shared_race_bonus") or 6)
        one_side_bonus = int(self.race_plan.get("one_side_race_bonus") or 3)
        optimal_bonus = int(
            plan.get("optimal_bonus")
            or self.race_plan.get("exact_bonus_if_all_won")
            or 0
        )
        affinity_count = int(
            plan.get("optimal_affinity_race_count")
            or plan.get("optimal_race_count")
            or self.race_plan.get("race_count")
            or 0
        )
        objective_count = int(plan.get("scheduled_objective_race_count") or 0)
        streaks = plan.get("streaks") or {}
        max_consecutive = int(streaks.get("max_consecutive") or 0)
        trackblazer = bool(
            self.trackblazer_toggle is not None
            and self.trackblazer_toggle.isChecked()
        )
        if trackblazer:
            summary = t(
                "Mode Trackblazer : objectifs ignorés · +{optimal} d’affinité · "
                "{affinity_count} G1 · série maximale {streak}."
            )
        else:
            summary = t(
                "Planning idéal : +{optimal} d’affinité · {affinity_count} G1 utiles · "
                "{objective_count} course(s) d’objectif · série maximale {streak}."
            )
        self.planning_legend.setText(
            (
                t(
                    "+{shared} commune · +{single} gagnée par un seul parent. "
                    "Une seule course par tour. "
                )
                + summary
            )
            .replace("{shared}", str(shared_bonus))
            .replace("{single}", str(one_side_bonus))
            .replace("{optimal}", str(optimal_bonus))
            .replace("{affinity_count}", str(affinity_count))
            .replace("{objective_count}", str(objective_count))
            .replace("{streak}", str(max_consecutive))
        )

    def retranslate(self) -> None:
        t = self.context.t
        if self.mode in {"grandparent_pair", "online_grandparent"}:
            left = self.row.get("fixed_grandparent") or {}
            right = self.row.get("candidate") or {}
        elif self.mode in {"branch", "future"}:
            left = self.row
            right = {}
        else:
            left = self.row.get("parent_1") or self.row.get("fixed_parent") or {}
            right = self.row.get("parent_2") or self.row.get("candidate") or {}
        ace_name = str(self.ace.get("uma_name") or self.ace.get("card_name") or "—")
        left_name = str((left if isinstance(left, dict) else {}).get("card_name") or "—")
        right_name = str((right if isinstance(right, dict) else {}).get("card_name") or "—")
        self.setWindowTitle(t("Vue de lignée"))
        if self.mode in {"grandparent_pair", "online_grandparent"}:
            self.title_label.setText(t("Paire de grands-parents"))
            self.subtitle_label.setText(
                t("{left} × {right} pour produire {target}")
                .replace("{left}", left_name)
                .replace("{right}", right_name)
                .replace("{target}", ace_name)
            )
        elif self.mode == "future":
            self.title_label.setText(t("Futur grand-parent"))
            self.subtitle_label.setText(
                t("{candidate} pour produire {target}")
                .replace("{candidate}", left_name)
                .replace("{target}", ace_name)
            )
        elif self.mode == "branch":
            self.title_label.setText(t("Lignée du parent candidat"))
            self.subtitle_label.setText(
                t("{candidate} pour {ace}")
                .replace("{candidate}", left_name)
                .replace("{ace}", ace_name)
            )
        else:
            self.title_label.setText(t("Vue de la paire"))
            self.subtitle_label.setText(
                t("{left} × {right} pour {ace}")
                .replace("{left}", left_name)
                .replace("{right}", right_name)
                .replace("{ace}", ace_name)
            )

        self.score_badge.set_metric(
            t("Score de lignée"),
            f"{_number(self.row.get('score')):.2f}",
        )
        if self.mode in {"grandparent_pair", "online_grandparent"}:
            final_affinity = (
                self.row.get("final_parent_affinity")
                or self.row.get("final_branch_affinity")
                or {}
            )
            potential = _number(
                final_affinity.get("potential_total", final_affinity.get("total"))
            )
            common = int(final_affinity.get("common_g1_count") or 0)
            self.affinity_badge.set_metric(t("Potentiel final"), f"{potential:.0f}")
            self.distance_badge.set_metric(t("G1 communes"), str(common), rank="")
        elif self.mode == "future":
            affinity = _number(self.row.get("affinity_raw"))
            self.affinity_badge.set_metric(t("Contribution affinité"), f"{affinity:.0f}")
            self.distance_badge.set_metric(
                t("G1 différentes"), str(int(self.row.get("g1_count") or 0)), rank=""
            )
        else:
            affinity = _number((self.row.get("affinity") or {}).get("total"))
            probability = 100.0 * _number(
                (self.row.get("distance_s_summary") or {}).get("probability_reach_s")
            )
            self.affinity_badge.set_metric(t("Affinité"), f"{affinity:.0f}")
            self.distance_badge.set_metric("P(S)", f"{probability:.1f}%", rank="S")
        self.online_toggle.setText(t("Illustrations en ligne (cache local)"))
        self.clear_cache_button.setText(t("Vider le cache d’images"))
        self.tabs.setTabText(self.tabs.indexOf(self.visual_page), t("Vue de lignée"))
        if self.planning_page is not None:
            self.tabs.setTabText(self.tabs.indexOf(self.planning_page), t("Planning G1"))
        if self.planning_title is not None:
            self.planning_title.setText(t("Planning optimal proposé"))
        if self.trackblazer_toggle is not None:
            self.trackblazer_toggle.setText(t("Planning pour Trackblazer"))
            if self.trackblazer_toggle.isEnabled():
                self.trackblazer_toggle.setToolTip(
                    t(
                        "Ignore les courses d’objectif du personnage visé et optimise uniquement les G1 d’affinité."
                    )
                )
            else:
                self.trackblazer_toggle.setToolTip(
                    t("Aucune course d’objectif fixe à ignorer pour ce personnage.")
                )
        if self.planning_key is not None:
            self.planning_key.setText(
                t(
                    '<span style="color:#e6bd55">● Commune</span> &nbsp; '
                    '<span style="color:#5d9ee8">● Locale</span> &nbsp; '
                    '<span style="color:#9b7adb">● Distante</span> &nbsp; '
                    '<span style="color:#55aebe">● Projetée</span> &nbsp; '
                    '<span style="color:#d87b86">● Objectif obligatoire</span> &nbsp; '
                    '<span style="color:#8a929d">● Série de 4+ (risquée)</span>'
                )
            )
        self.tabs.setTabText(self.tabs.indexOf(self.details), t("Diagnostic"))
        component_details = self.row.get("component_details") or {}
        if not isinstance(component_details, dict):
            component_details = {}
        white_details = component_details.get("white_skill") or {}
        if not isinstance(white_details, dict):
            white_details = {}
        event_count = max(1, int(white_details.get("inspiration_event_count") or 2))
        self.spark_legend.setText(
            t(
                "Whites : le % indique la chance d’au moins un proc sur les {count} Inspiration Events "
                "de la run lorsqu’elle est disponible · ◆ doré = priorité majeure · ◇ bleu = white compatible, utile ou rare pour le profil."
            ).replace("{count}", str(event_count))
        )
        self._update_planning_copy()
        self.attribution.setText(
            t(
                'Les bannières G1, illustrations de trainees et icônes de skills sont chargées à la demande depuis '
                '<a href="https://gametora.com/umamusume/races">GameTora</a> et conservées uniquement '
                'dans le cache local. Visuels du jeu © Cygames, Inc.'
            )
        )
        self.close_button.setText(t("Fermer"))
        self.tree.retranslate()
        if self.calendar is not None:
            self.calendar.retranslate()
        self._update_cache_label()

    def _toggle_online_images(self, enabled: bool) -> None:
        set_online_images_enabled(self.context, enabled)
        self.tree.refresh_images()
        if self.calendar is not None:
            self.calendar.refresh_images()
        self._update_cache_label()

    def _update_cache_label(self) -> None:
        count, size = self.repository.cache_stats()
        state = self.context.t("activées" if self.repository.enabled else "désactivées")
        self.cache_label.setText(
            self.context.t("{state} · {count} image(s) · {size}")
            .replace("{state}", state)
            .replace("{count}", str(count))
            .replace("{size}", _human_size(size))
        )
        self.cache_label.setToolTip(str(self.repository.cache_dir))

    def _clear_cache(self) -> None:
        answer = QMessageBox.question(
            self,
            self.context.t("Cache d’images"),
            self.context.t(
                "Supprimer les illustrations téléchargées ? Elles pourront être rechargées à la prochaine ouverture."
            ),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.repository.clear_cache()
        self.tree.refresh_images()
        if self.calendar is not None:
            self.calendar.refresh_images()
