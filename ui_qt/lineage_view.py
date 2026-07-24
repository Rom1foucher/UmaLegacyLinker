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

from ui_qt.asset_catalog import skill_icon_url, trainee_image_url
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
    return SPARK_COLORS.get(str(factor.get("type") or "other"), SPARK_COLORS["other"])


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
        marker = "◆ " if factor.get("is_score_priority") else ""
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
        if abs(self.minimumHeight() - required) <= 1 or self._height_update_pending:
            return
        self._height_update_pending = True

        def apply_height() -> None:
            self._height_update_pending = False
            if abs(self.minimumHeight() - required) > 1:
                self.setMinimumHeight(required)
                self.updateGeometry()

        QTimer.singleShot(0, apply_height)

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
        painter.setPen(QPen(QColor(border), 1.8 if factor.get("is_score_priority") else 1.0))
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
        marker = "◆ " if factor.get("is_score_priority") else ""
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
            painter.setPen(QColor("#ffe9a3" if factor.get("is_score_priority") else "#f0f5fb"))
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
        self.resize(1480, 900)

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
        visual_page = QWidget()
        visual_layout = QVBoxLayout(visual_page)
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
        self.tabs.addTab(visual_page, "")

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
        self.repository.cache_changed.connect(self._update_cache_label)
        self.retranslate()

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
        self.tabs.setTabText(0, t("Vue de lignée"))
        self.tabs.setTabText(1, t("Diagnostic"))
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
                "de la run lorsqu’elle est disponible · contour doré = forte contribution au score de cette lignée."
            ).replace("{count}", str(event_count))
        )
        self.attribution.setText(
            t(
                'Illustrations de trainees et icônes de skills chargées à la demande depuis '
                '<a href="https://gametora.com/umamusume/characters">GameTora</a> et conservées uniquement '
                'dans le cache local. Visuels du jeu © Cygames, Inc.'
            )
        )
        self.close_button.setText(t("Fermer"))
        self.tree.retranslate()
        self._update_cache_label()

    def _toggle_online_images(self, enabled: bool) -> None:
        set_online_images_enabled(self.context, enabled)
        self.tree.refresh_images()
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
