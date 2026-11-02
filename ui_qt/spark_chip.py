"""Shared painted spark chips for lineage canvases and aligned duels."""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap

from ui_qt.theme import SPARK_COLORS, spark_semantic_label, spark_style_key


def run_probability(factor: dict[str, Any]) -> float | None:
    if str(factor.get("type") or "") not in {"white_skill", "white_race"}:
        return None
    try:
        value = float(factor.get("proc_probability_over_run"))
    except (TypeError, ValueError):
        return None
    return max(0.0, min(value, 1.0))


def probability_text(value: float | None) -> str:
    return "" if value is None else f"{100.0 * value:.2f}%"


def paint_spark_chip(
    context,
    painter: QPainter,
    rect: QRectF,
    factor: dict[str, Any],
    font: QFont,
    icon: QPixmap | None = None,
) -> None:
    background, border, foreground = SPARK_COLORS[spark_style_key(factor)]
    painter.setBrush(QColor(background))
    border_width = 1.8 if factor.get("is_score_priority") else 1.4 if factor.get("is_score_useful") else 1.0
    painter.setPen(QPen(QColor(border), border_width))
    painter.drawRoundedRect(rect, 5.0, 5.0)
    left = rect.left() + 7.0
    if icon is not None and not icon.isNull():
        icon_rect = QRectF(left, rect.top() + 3.0, 19.0, 19.0)
        scaled = icon.scaled(icon_rect.size().toSize(), Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        painter.drawPixmap(icon_rect, scaled, QRectF(scaled.rect()))
        left = icon_rect.right() + 5.0
    painter.setFont(font)
    probability = probability_text(run_probability(factor))
    probability_width = painter.fontMetrics().horizontalAdvance(probability) + 12.0 if probability else 0.0
    stars = max(0, int(factor.get("stars") or 0))
    category = spark_semantic_label(dict(factor, is_inactive=False))
    status = " · " + context.t("Inactif") if factor.get("is_inactive") else ""
    label = f"[{context.t(category)}{status}] {stars}★  {factor.get('name') or '—'}"
    available = max(12, int(rect.right() - left - 7.0 - probability_width))
    painter.setPen(QColor(foreground))
    painter.drawText(
        QRectF(left, rect.top(), float(available), rect.height()),
        Qt.AlignmentFlag.AlignVCenter,
        painter.fontMetrics().elidedText(label, Qt.TextElideMode.ElideRight, available),
    )
    if probability:
        probability_rect = QRectF(rect.right() - probability_width, rect.top() + 3.0,
                                  probability_width - 4.0, rect.height() - 6.0)
        painter.setBrush(QColor("#111821"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(probability_rect, 4.0, 4.0)
        color = "#ffe9a3" if factor.get("is_score_priority") else "#bfe9ff" if factor.get("is_score_useful") else "#f0f5fb"
        painter.setPen(QColor(color))
        painter.drawText(probability_rect, Qt.AlignmentFlag.AlignCenter, probability)
