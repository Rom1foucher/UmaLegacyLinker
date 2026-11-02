from __future__ import annotations

from collections import defaultdict
from typing import Any

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
    QScrollArea, QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)

from ui_qt.image_assets import image_repository
from ui_qt.lineage_view import ZoomControl
from ui_qt.spark_chip import paint_spark_chip
from ui_qt.theme import COLORS
from ui_qt.typography import css_point_size
from ui_qt.transfer_explanation import spark_duel
from ui_qt.transfer_lineage import TransferLineageTree, comparison_nodes
from uma_legacy_linker.i18n import profile_label
from uma_legacy_linker.veteran_identity import canonical_veteran_label

TRANSFER_TREE_ZOOM_KEY = "transfer_helper_tree_zoom"


class CoverageBand(QWidget):
    """Common point-distance grammar for every transfer explanation."""
    def __init__(self, context, parent=None):
        super().__init__(parent)
        self.context = context
        self.data: dict[str, Any] = {}
        self.setMinimumHeight(82)
        self.setAccessibleName(context.t("Écart à la meilleure copie et zone de tolérance"))

    def set_data(self, data: dict[str, Any]) -> None:
        self.data = data or {}
        self.update()

    def sizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(620, 82)

    def paintEvent(self, _event):
        if not self.data:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(14, 8, -14, -8)
        tolerance = max(0.0, float(self.data.get("regret_tolerance") or 0.0))
        gap = max(0.0, float(self.data.get("gap") or 0.0))
        target_score = self.data.get("counterpart_score")
        counterpart_label = self.context.t(str(self.data.get("counterpart_label") or "Copie comparée"))
        best = float(self.data.get("best") or 0.0)
        target_gap = max(0.0, best - float(target_score)) if target_score is not None else None
        scale = max(6.0, float(self.data.get("scale_max") or 6.0), gap * 1.2)
        x0, x1 = rect.left() + 8, rect.right() - 8
        y = rect.center().y() + 8
        width = max(1.0, x1 - x0)
        top_end = x0 + width * min(1.0, tolerance / scale)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#203e38"))
        painter.drawRoundedRect(QRectF(x0, y - 7, max(1.0, top_end - x0), 14), 6, 6)
        painter.setBrush(QColor("#273342"))
        painter.drawRoundedRect(QRectF(x0, y - 4, width, 8), 4, 4)
        painter.setPen(QPen(QColor("#88a59f"), 1))
        painter.drawLine(int(top_end), int(y - 12), int(top_end), int(y + 14))
        points = [(gap, COLORS["accent"], self.context.t("Cette copie"))]
        if target_gap is not None:
            points.append((target_gap, "#79aaff", counterpart_label))
        for distance, color, label in points:
            x = x0 + width * min(1.0, distance / scale)
            painter.setBrush(QColor(color))
            painter.setPen(QPen(QColor("#f5f7fa"), 1.5))
            painter.drawEllipse(int(x - 5), int(y - 5), 10, 10)
            painter.setPen(QColor("#dce5ef"))
            painter.drawText(int(max(x0, min(x - 60, x1 - 120))), int(rect.top() + 18),
                             f"{label} · −{distance:.2f}")
        painter.setPen(QColor("#a9b8c8"))
        painter.drawText(int(x0), int(y + 26), "0 · " + self.context.t("meilleure copie"))
        painter.drawText(int(top_end - 36), int(y + 26), f"{tolerance:g} {self.context.t('top')}")
        painter.drawText(int(x1 - 45), int(y + 26), f"{scale:.1f}")


class RoleList(QListWidget):
    def __init__(self, context, parent=None):
        super().__init__(parent)
        self.context = context
        self.setAccessibleName(context.t("Rôles et contextes de course"))
        self.setMinimumWidth(250)
        self.setWordWrap(True)

    def set_roles(self, roles: list[dict[str, Any]]) -> None:
        self.clear()
        for role in roles:
            axes = " · ".join(profile_label(k, str(role[k]), self.context.language)
                              for k in ("surface", "distance", "style") if role.get(k))
            name = self.context.t("Parent") if role.get("role") == "parent" else self.context.t("Futur grand-parent")
            line = f"{name} · {axes or role.get('profile') or '—'}"
            courses = []
            for context_key in role.get("contexts") or []:
                context = getattr(self, "comparison_model", {}).get("contexts", {}).get(context_key, {})
                if context.get("course_key"):
                    courses.append(str(context.get("label") or context["course_key"]))
            courses = sorted(set(courses))
            if courses:
                line += "\n" + self.context.t("CMs") + " · " + ", ".join(map(str, courses))
            item = QListWidgetItem(line)
            if courses:
                item.setSizeHint(QSize(250, 54))
            contexts = role.get("contexts") or []
            item.setData(Qt.ItemDataRole.UserRole, role)
            item.setToolTip("\n".join(str(value) for value in contexts))
            self.addItem(item)


class SparkDuel(QWidget):
    def __init__(self, context, parent=None):
        super().__init__(parent)
        self.context = context
        self.result: dict[str, Any] = {"available": False}
        self.expanded = False
        self.setMinimumHeight(44)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

    def set_result(self, result: dict[str, Any], expanded=False):
        self.result = result or {"available": False}
        self.expanded = expanded
        visible = self.result.get("all_factors", []) if expanded else self.result.get("factors", [])
        self.setMinimumHeight(max(44, len(visible) * 58 + 8))
        self.updateGeometry()
        self.update()

    def sizeHint(self):
        from PySide6.QtCore import QSize
        rows = self.result.get("all_factors", []) if self.expanded else self.result.get("factors", [])
        return QSize(640, max(44, len(rows) * 58 + 8))

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.result.get("available"):
            painter.setPen(QColor(COLORS["muted"]))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             self.context.t(str(self.result.get("message") or
                                                "Comparaison indisponible : les scores recalculés ne correspondent pas au rapport.")))
            return
        items = self.result.get("all_factors", []) if self.expanded else self.result.get("factors", [])
        if not items:
            painter.setPen(QColor(COLORS["muted"]))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             self.context.t("Aucun spark pondéré pour ce rôle."))
            return
        midpoint = self.width() // 2
        for index, factor in enumerate(items):
            top = index * 58 + 3
            row = factor
            for side, x, stars_key, carriers_key in (
                ("left", 4, "left_stars", "left_carriers"),
                ("right", midpoint + 18, "right_stars", "right_carriers"),
            ):
                chip = dict(row, stars=row.get(stars_key, 0))
                chip_rect = QRectF(x, top, max(80, midpoint - 30), 32)
                paint_spark_chip(self.context, painter, chip_rect, chip, self.font())
                carriers = defaultdict(int)
                for name, stars in row.get(carriers_key) or []:
                    carriers[name] += int(stars or 0)
                carrier_order = (("parent", "#72d8b1"), ("grandparent_1", "#82b5ff"),
                                 ("grandparent_2", "#c79bff")) if row.get("role") == "parent" else (("self", "#72d8b1"),)
                marker_x = int(x + 7)
                painter.setPen(QColor("#b8c5d4"))
                for carrier, color in carrier_order:
                    painter.setBrush(QColor(color))
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.drawEllipse(marker_x, top + 43, 6, 6)
                    painter.setPen(QColor("#b8c5d4"))
                    text = f"{self._carrier_name(carrier)} {carriers.get(carrier, 0)}★"
                    painter.drawText(marker_x + 9, top + 50, text)
                    marker_x += painter.fontMetrics().horizontalAdvance(text) + 25
            painter.setPen(QColor("#718096"))
            painter.drawText(midpoint - 12, top + 22, "↔")

    def _carrier_name(self, carrier):
        return self.context.t({"self": "Soi", "candidate": "Soi", "parent": "Soi",
                               "grandparent_1": "GP A", "grandparent_2": "GP B"}.get(carrier, str(carrier)))


class TransferReasonPanel(QDialog):
    """Non-modal explanation panel that follows the selected transfer row."""
    def __init__(self, context, records, comparison_model, settings, parent=None):
        super().__init__(parent)
        self.context = context
        self.records = records
        self.comparison_model = comparison_model or {}
        self.settings = settings or {}
        self.candidate: dict[str, Any] = {}
        self.target: dict[str, Any] = {}
        self.role_data: dict[str, Any] = {}
        self.setWindowTitle(context.t("Pourquoi cette copie ?"))
        self.resize(1120, 740)
        self.escape_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self.escape_shortcut.activated.connect(self.close)
        root = QHBoxLayout(self)
        self.roles = RoleList(context)
        self.roles.comparison_model = self.comparison_model
        root.addWidget(self.roles, 1)
        right = QVBoxLayout()
        root.addLayout(right, 3)
        self.title = QLabel("")
        self.title.setWordWrap(True)
        self.title.setStyleSheet(
            f"font-weight:700;font-size:{css_point_size('heading')}"
        )
        right.addWidget(self.title)
        self.verdict = QLabel("")
        self.verdict.setWordWrap(True)
        self.verdict.setObjectName("muted")
        right.addWidget(self.verdict)
        self.subtitle = QLabel("")
        self.subtitle.setWordWrap(True)
        right.addWidget(self.subtitle)
        self.band = CoverageBand(context)
        right.addWidget(self.band)
        self.empty_roles = QLabel("")
        self.empty_roles.setWordWrap(True)
        self.empty_roles.setObjectName("muted")
        self.empty_roles.setVisible(False)
        right.addWidget(self.empty_roles)
        self.spark_summary = QLabel("")
        right.addWidget(self.spark_summary)
        self.spark_duel = SparkDuel(context)
        self.spark_scroll = QScrollArea()
        self.spark_scroll.setWidgetResizable(True)
        self.spark_scroll.setWidget(self.spark_duel)
        right.addWidget(self.spark_scroll, 1)
        self.more = QToolButton()
        self.more.setCheckable(True)
        self.more.toggled.connect(self._toggle_more)
        right.addWidget(self.more)
        tree_zoom = context.store.get(TRANSFER_TREE_ZOOM_KEY, "0.75")
        self.tree = TransferLineageTree(
            context, image_repository(context), self, zoom=tree_zoom
        )
        tree_controls = QHBoxLayout()
        self.tree_toggle = QPushButton(context.t("Arbre"))
        self.tree_toggle.setCheckable(True)
        self.tree_toggle.setChecked(True)
        tree_controls.addWidget(self.tree_toggle, 1)
        self.tree_zoom_control = ZoomControl(context, tree_zoom)
        self.tree_zoom_control.retranslate(context.t("Zoom de l’arbre"))
        tree_controls.addWidget(self.tree_zoom_control)
        right.addLayout(tree_controls)
        self.tree_scroll = QScrollArea()
        self.tree_scroll.setWidgetResizable(True)
        self.tree_scroll.setWidget(self.tree)
        self.tree_scroll.setMaximumHeight(380)
        right.addWidget(self.tree_scroll, 1)
        self.tree_toggle.toggled.connect(self.tree_scroll.setVisible)
        self.tree_zoom_control.zoom_requested.connect(self.tree.set_zoom)
        self.tree.zoom_changed.connect(self.tree_zoom_control.set_zoom)
        self.tree.zoom_changed.connect(
            lambda value: context.store.update({TRANSFER_TREE_ZOOM_KEY: value})
        )
        self.roles.currentItemChanged.connect(self._role_selected)
        self.tree.node_selected.connect(self._select_tree_node)
        self._visible_sparks: dict[str, Any] = {}

    def _fallback_target(self, candidate: dict[str, Any]) -> dict[str, Any]:
        reason = candidate.get("transfer_reason") or {}
        references = list(reason.get("refs") or [])
        if not references and candidate.get("dominated_by"):
            references.append(candidate["dominated_by"])
        for reference in references:
            target_id = reference.get("trained_chara_id")
            if target_id is None:
                continue
            target = next(
                (row for row in self.records
                 if str(row.get("trained_chara_id")) == str(target_id)),
                None,
            )
            if target is not None and target is not candidate:
                return target
        return {}

    def _show_fallback_tree(
        self, candidate: dict[str, Any], role: str = "parent",
        target: dict[str, Any] | None = None,
    ) -> None:
        self.target = target if target is not None else self._fallback_target(candidate)
        nodes = comparison_nodes((candidate, self.target), role)
        self.tree.retranslate()
        self.tree.set_nodes(nodes)
        self.tree_scroll.setVisible(bool(nodes) and self.tree_toggle.isChecked())

    def set_candidate(self, candidate: dict[str, Any]):
        if not candidate:
            return
        self.candidate = candidate
        self.roles.comparison_model = self.comparison_model
        roles = list((candidate.get("transfer_reason") or {}).get("roles") or [])
        code = (candidate.get("transfer_reason") or {}).get("code")
        if code == "holds_role":
            roles = [item for item in roles if item.get("held")]
        elif code in {"outclassed", "covered_by"}:
            roles = sorted(roles, key=lambda item: (item.get("gap", 1e9), item.get("profile", "")))[:3]
        self.roles.set_roles(roles)
        has_roles = bool(roles)
        self.band.setVisible(has_roles)
        self.empty_roles.setVisible(not has_roles)
        self.empty_roles.setText(
            self.context.t("Aucun rôle scoré n’est disponible dans ce rapport.")
            if not has_roles else ""
        )
        self.spark_scroll.setVisible(has_roles)
        self.spark_summary.setVisible(has_roles)
        self.more.setVisible(False)
        self.setWindowTitle(f"{self.context.t('Pourquoi cette copie ?')} — {canonical_veteran_label(candidate)}")
        self.title.setText(canonical_veteran_label(candidate))
        reason = candidate.get("transfer_reason") or {}
        subject = str(reason.get("subject") or "").replace("_", " ")
        code = str(reason.get("code") or "").replace("_", " ")
        self.verdict.setText(self.context.t(code) + (" · " + self.context.t(subject) if subject else ""))
        self.more.blockSignals(True)
        self.more.setChecked(False)
        self.more.blockSignals(False)
        if self.roles.count():
            self.roles.setCurrentRow(0)
            self.tree_scroll.setVisible(self.tree_toggle.isChecked())
        else:
            self.role_data = {}
            self.subtitle.clear()
            self.band.set_data({})
            self.spark_duel.set_result({
                "available": False,
                "message": "Aucun rôle scoré n’est disponible dans ce rapport.",
            })
            self.spark_summary.clear()
            self._show_fallback_tree(candidate)

    def _role_selected(self, current, _previous=None):
        if current is None:
            return
        self.more.blockSignals(True)
        self.more.setChecked(False)
        self.more.blockSignals(False)
        item = current.data(Qt.ItemDataRole.UserRole) or {}
        self.role_data = item
        reason = self.candidate.get("transfer_reason") or {}
        protected = bool(self.candidate.get("manual_protection_reasons"))
        status = str(self.candidate.get("status") or "")
        ref = item.get("challenger") if status in {"keep", "protected"} or protected else item.get("holder")
        target_id = (ref or {}).get("trained_chara_id")
        self.target = next((row for row in self.records if str(row.get("trained_chara_id")) == str(target_id)), {})
        key, ace_index = item.get("context_key"), item.get("ace_index")
        context = self.comparison_model.get("contexts", {}).get(key, {})
        aces = context.get("aces") or []
        ace = aces[ace_index] if isinstance(ace_index, int) and ace_index < len(aces) else {}
        course = context.get("course_key") or context.get("label") or key or "—"
        self.subtitle.setText(f"{item.get('profile') or '—'} · {course} · {self.context.t('Ace cible')} : {ace.get('card_name') or ace.get('uma_name') or '—'}")
        try:
            tolerance = float(self.settings.get("portfolio_regret_tolerance", item.get("regret_tolerance", 2.5)))
        except (TypeError, ValueError):
            tolerance = float(item.get("regret_tolerance") or 2.5)
        keeping = status in {"keep", "protected"} or protected
        self.band.set_data({**item, "regret_tolerance": tolerance,
                            "counterpart_score": item.get("other_holder_score") if keeping else item.get("holder_score"),
                            "counterpart_label": "Meilleure autre copie gardée" if keeping else "Copie qui tient le rôle"})
        if not self.target or not self.comparison_model or ace_index is None:
            self.spark_duel.set_result({
                "available": False,
                "message": "Le porteur ou le contexte de comparaison manque dans le rapport.",
            })
            self.spark_summary.clear()
            self._show_fallback_tree(self.candidate, str(item.get("role") or "parent"))
            return
        role = str(item.get("role") or "parent")
        try:
            duel = spark_duel(self.candidate, self.target, self.comparison_model, key, ace_index, role)
            spark_filter = {tuple(factor["key"]) for factor in duel.get("all_factors", [])}
            spark_annotations = {
                tuple(factor["key"]): {
                    key: factor[key]
                    for key in ("is_inactive", "inactive_reason")
                    if key in factor
                }
                for factor in duel.get("all_factors", [])
                if factor.get("is_inactive")
            }
            nodes = comparison_nodes((self.candidate, self.target), role,
                                     skill_weights=context.get("skill_weights"),
                                     spark_filter=spark_filter,
                                     spark_annotations=spark_annotations)
            self.tree.retranslate()
            self.tree.set_nodes(nodes)
        except (KeyError, TypeError, ValueError, IndexError):
            duel = {"available": False, "factors": [], "folded": 0}
            self._show_fallback_tree(self.candidate, role, self.target)
        self._visible_sparks = duel
        count = int(duel.get("folded") or 0)
        self.more.setText(self.context.t("Masquer les autres sparks") if self.more.isChecked() else
                          self.context.t("Autres sparks ({count})").replace("{count}", str(count)))
        self.more.setVisible(bool(duel.get("folded")))
        if duel.get("available"):
            self.spark_summary.setText(
                f"{canonical_veteran_label(self.candidate)}  ↔  {canonical_veteran_label(self.target)}"
                + (" · " + self.context.t("Branche entière · soi / GP A / GP B") if role == "parent"
                   else " · " + self.context.t("Facteurs propres de la copie"))
            )
        else:
            self.spark_summary.setText("")
        self.spark_duel.set_result(duel, self.more.isChecked())

    def _toggle_more(self, checked):
        count = int(self._visible_sparks.get("folded") or 0)
        self.more.setText(self.context.t("Masquer les autres sparks") if checked else
                          self.context.t("Autres sparks ({count})").replace("{count}", str(count)))
        self.spark_duel.set_result(self._visible_sparks, checked)

    def _select_tree_node(self, position):
        self.tree.set_selected_node(position)
