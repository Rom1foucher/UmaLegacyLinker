from __future__ import annotations

import json
import os
import copy
from functools import partial
from pathlib import Path
from typing import Any

from PySide6.QtCore import QItemSelection, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableView,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from i18n import profile_values
from course_presets import course_preset_conditions, load_course_preset_payload, ordered_course_presets
from parent_optimizer import OptimizerError, load_ace_options
from secret_store import SecretStoreError, load_api_key, save_api_key
from uma_moe import (
    DEFAULT_API_BASE,
    DISTANCE_FACTOR_NAMES,
    STYLE_FACTOR_NAMES,
    SURFACE_FACTOR_NAMES,
    OnlineParentSearchResult,
    UmaMoeError,
)
from ui_qt.components import (
    CollapsibleSection,
    PageHeader,
    PathPicker,
    SearchableComboBox,
    muted_label,
    section_label,
    sync_scroll_pane_height,
)
from ui_qt.context import AppContext
from ui_qt.core import (
    OnlineSearchRequest,
    VeteranOption,
    active_course_overrides_path,
    api_key_path,
    load_local_veteran_options,
    load_opposing_parent_candidates,
    open_path,
    run_online_search,
)
from ui_qt.lineage_view import LineageDialog
from ui_qt.models import Column, ResultTableModel, nested
from ui_qt.presentation import distance_status, online_detail_html, profile_summary


RIGHT = Qt.AlignmentFlag.AlignRight


def _integer(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _id_set(value: str) -> set[int]:
    result: set[int] = set()
    for part in value.replace(";", ",").split(","):
        try:
            candidate = int(part.strip())
        except ValueError:
            continue
        if candidate > 0:
            result.add(candidate)
    return result


class CardFilterDialog(QDialog):
    def __init__(
        self,
        context: AppContext,
        options: list[tuple[int, str]],
        selected: set[int],
        title: str,
        parent=None,
    ):
        super().__init__(parent)
        self.context = context
        self.setWindowTitle(title)
        self.resize(680, 620)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        self.search = QLineEdit()
        self.search.setPlaceholderText(context.t("Rechercher un costume…"))
        root.addWidget(self.search)
        self.list = QListWidget()
        self.list.setAlternatingRowColors(True)
        for card_id, display in options:
            item = QListWidgetItem(display)
            item.setData(Qt.ItemDataRole.UserRole, card_id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if card_id in selected else Qt.CheckState.Unchecked
            )
            self.list.addItem(item)
        root.addWidget(self.list, 1)
        selection = QHBoxLayout()
        all_button = QPushButton(context.t("Tout sélectionner"))
        clear_button = QPushButton(context.t("Tout effacer"))
        selection.addWidget(all_button)
        selection.addWidget(clear_button)
        selection.addStretch(1)
        root.addLayout(selection)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(context.t("Valider"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(context.t("Annuler"))
        root.addWidget(buttons)
        self.search.textChanged.connect(self._filter)
        all_button.clicked.connect(lambda: self._set_visible(Qt.CheckState.Checked))
        clear_button.clicked.connect(lambda: self._set_visible(Qt.CheckState.Unchecked))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

    def _filter(self, query: str) -> None:
        query = query.strip().casefold()
        for index in range(self.list.count()):
            item = self.list.item(index)
            item.setHidden(bool(query and query not in item.text().casefold()))

    def _set_visible(self, state: Qt.CheckState) -> None:
        for index in range(self.list.count()):
            item = self.list.item(index)
            if not item.isHidden():
                item.setCheckState(state)

    def selected_ids(self) -> set[int]:
        return {
            int(self.list.item(index).data(Qt.ItemDataRole.UserRole))
            for index in range(self.list.count())
            if self.list.item(index).checkState() == Qt.CheckState.Checked
        }


class OnlineResultsPane(QWidget):
    def __init__(self, context: AppContext, parent=None):
        super().__init__(parent)
        self.context = context
        self.mode = "parent"
        self.profile: dict[str, Any] = {}
        self.metadata: dict[str, Any] = {}
        self.ace: dict[str, Any] | None = None
        self.lineage_root: dict[str, Any] | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(7)
        head = QHBoxLayout()
        self.summary = muted_label("")
        self.lineage_button = QPushButton("")
        self.lineage_button.setEnabled(False)
        self.copy_button = QPushButton("")
        self.copy_button.setEnabled(False)
        head.addWidget(self.summary, 1)
        head.addWidget(self.lineage_button)
        head.addWidget(self.copy_button)
        root.addLayout(head)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.table = QTableView()
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.model = ResultTableModel([], [])
        self.table.setModel(self.model)
        self.table.setSortingEnabled(True)
        self.detail = QTextBrowser()
        self.detail.setMinimumWidth(520)
        splitter.addWidget(self.table)
        splitter.addWidget(self.detail)
        splitter.setChildrenCollapsible(False)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 4)
        splitter.setSizes([700, 560])
        root.addWidget(splitter, 1)
        self.table.selectionModel().selectionChanged.connect(self._selection_changed)
        self.table.doubleClicked.connect(self._double_clicked)
        self.copy_button.clicked.connect(self.copy_friend_id)
        self.lineage_button.clicked.connect(self.open_lineage)
        self.context.language_changed.connect(lambda _language: self.retranslate())
        self.retranslate()

    def _columns(self) -> list[Column]:
        t = self.context.t
        common = [
            Column("#", nested("_rank"), RIGHT),
            Column(t("Score"), nested("score"), RIGHT),
        ]
        if self.mode == "parent":
            return common + [
                Column(t("Parent local"), nested("fixed_parent", "card_name")),
                Column(t("Parent distant"), nested("candidate", "card_name")),
                Column(t("Trainer"), nested("candidate", "online", "trainer_name")),
                Column("Friend ID", nested("candidate", "online", "friend_code")),
                Column(t("Distance S"), lambda row: distance_status(row, self.context.language)),
                Column("P(S) %", lambda row: 100 * float((row.get("distance_s_summary") or {}).get("probability_reach_s") or 0), RIGHT),
                Column(t("Affinité"), nested("affinity", "total"), RIGHT),
                Column(t("Whites"), nested("components", "white_skill"), RIGHT),
                Column(t("Bleues"), nested("components", "blue"), RIGHT),
            ]
        return common + [
            Column(t("GP local"), nested("fixed_grandparent", "card_name")),
            Column(t("GP distant"), nested("candidate", "card_name")),
            Column(t("Trainer"), nested("candidate", "online", "trainer_name")),
            Column("Friend ID", nested("candidate", "online", "friend_code")),
            Column(t("Potentiel final"), lambda row: (row.get("final_parent_affinity") or row.get("final_branch_affinity") or {}).get("potential_total", 0), RIGHT),
            Column(t("G1 communes"), lambda row: (row.get("final_parent_affinity") or row.get("final_branch_affinity") or {}).get("common_g1_count", 0), RIGHT),
            Column(t("Roses"), nested("components", "pink"), RIGHT),
            Column(t("Whites"), nested("components", "white_skill"), RIGHT),
            Column(t("Bleues"), nested("components", "blue"), RIGHT),
        ]

    def _configure_header(self) -> None:
        header = self.table.horizontalHeader()
        header.setMinimumSectionSize(58)
        for index in range(self.model.columnCount()):
            header.setSectionResizeMode(index, QHeaderView.ResizeMode.ResizeToContents)
        for index in (2, 3):
            if index < self.model.columnCount():
                header.setSectionResizeMode(index, QHeaderView.ResizeMode.Stretch)

    def set_result(self, result: object, profile: dict[str, Any]) -> None:
        self.mode = "parent" if isinstance(result, OnlineParentSearchResult) else "grandparent"
        ace = getattr(result, "ace", None)
        self.ace = dict(ace) if isinstance(ace, dict) else None
        root = (
            ace
            if self.mode == "parent"
            else getattr(result, "target_parent", None)
        )
        self.lineage_root = dict(root) if isinstance(root, dict) else None
        self.profile = dict(profile)
        self.metadata = {
            "local_pool_count": getattr(result, "local_pool_count", 0),
            "remote_pool_count": getattr(result, "remote_pool_count", 0),
            "evaluated_pair_count": getattr(result, "evaluated_pair_count", 0),
        }
        self._set_rows(list(getattr(result, "top_results", ()) or ()))

    def set_payload(self, payload: dict[str, Any], mode: str) -> None:
        self.mode = mode
        ace = payload.get("ace")
        self.ace = dict(ace) if isinstance(ace, dict) else None
        root = ace if mode == "parent" else payload.get("target_parent")
        self.lineage_root = dict(root) if isinstance(root, dict) else None
        metadata = payload.get("metadata") or {}
        self.metadata = dict(metadata)
        self.profile = dict(metadata.get("profile") or {})
        self._set_rows(list(payload.get("results") or []))

    def _set_rows(self, rows: list[dict[str, Any]]) -> None:
        ranked = []
        for index, row in enumerate(rows, 1):
            copy = dict(row)
            copy["_rank"] = index
            ranked.append(copy)
        self.model.set_columns(self._columns())
        self.model.set_rows(ranked)
        self._configure_header()
        self.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        if ranked:
            self.table.selectRow(0)
        else:
            self.detail.setHtml(
                online_detail_html(
                    None, self.mode, self.context.language, self.profile
                )
            )
        self.retranslate()

    def selected_row(self) -> dict[str, Any] | None:
        indexes = self.table.selectionModel().selectedRows()
        return self.model.row(indexes[0].row()) if indexes else None

    def _selection_changed(self, _selected: QItemSelection, _deselected: QItemSelection) -> None:
        row = self.selected_row()
        self.detail.setHtml(
            online_detail_html(
                row, self.mode, self.context.language, self.profile
            )
        )
        friend = str((((row or {}).get("candidate") or {}).get("online") or {}).get("friend_code") or "")
        self.copy_button.setEnabled(bool(friend))
        self._update_lineage_button()

    def _double_clicked(self, index) -> None:
        if index.isValid() and "Friend ID" in str(self.model.headerData(index.column(), Qt.Orientation.Horizontal)):
            self.copy_friend_id()
        elif index.isValid():
            self.open_lineage()

    def _update_lineage_button(self) -> None:
        self.lineage_button.setEnabled(
            self.selected_row() is not None and self.lineage_root is not None
        )

    def open_lineage(self) -> None:
        row = self.selected_row()
        if row is None or self.lineage_root is None:
            return
        LineageDialog(
            self.context,
            self.lineage_root,
            row,
            mode=(
                "online_parent"
                if self.mode == "parent"
                else "online_grandparent"
            ),
            details_html=online_detail_html(
                row, self.mode, self.context.language, self.profile
            ),
            parent=self,
        ).exec()

    def copy_friend_id(self) -> None:
        row = self.selected_row() or {}
        friend = str(((row.get("candidate") or {}).get("online") or {}).get("friend_code") or "")
        if friend:
            QApplication.clipboard().setText(friend)
            self.copy_button.setText(self.context.t("Copié !"))
            QTimer.singleShot(1400, self.retranslate)

    def retranslate(self) -> None:
        t = self.context.t
        summary = t("{count} paires classées · tri par en-tête · double-clic sur Friend ID pour copier").replace(
            "{count}", str(self.model.rowCount())
        )
        local_count = int(self.metadata.get("local_pool_count") or 0)
        remote_count = int(self.metadata.get("remote_pool_count") or 0)
        evaluated = int(self.metadata.get("evaluated_pair_count") or 0)
        if local_count or remote_count:
            summary += f" · {local_count} × {remote_count} · {evaluated} {t('évaluées')}"
        self.summary.setText(summary)
        self.copy_button.setText(t("Copier le Friend ID"))
        self.lineage_button.setText(t("Voir la lignée"))
        selected = self.selected_row()
        selected_rank = selected.get("_rank") if selected else None
        self.model.set_columns(self._columns())
        self._configure_header()
        if selected_rank is not None:
            for index in range(self.model.rowCount()):
                row = self.model.row(index)
                if row and row.get("_rank") == selected_rank:
                    self.table.selectRow(index)
                    break
        self.detail.setHtml(
            online_detail_html(
                self.selected_row(),
                self.mode,
                self.context.language,
                self.profile,
            )
        )
        self._update_lineage_button()


class OnlinePage(QWidget):
    task_requested = Signal(object, str, object)

    def __init__(self, context: AppContext, parent=None):
        super().__init__(parent)
        self.context = context
        self._busy = False
        self._ace_options: list[Any] = []
        self._local_options: list[VeteranOption] = []
        self._card_to_chara: dict[int, int] = {}
        self._allowed_ids = _id_set(context.store.get("uma_moe_parent_allowed_card_ids"))
        self._excluded_ids = _id_set(context.store.get("uma_moe_parent_excluded_card_ids"))

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(12)
        self.header = PageHeader("", "")
        root.addWidget(self.header)
        self.context_strip = QFrame()
        self.context_strip.setObjectName("panel")
        context_layout = QHBoxLayout(self.context_strip)
        context_layout.setContentsMargins(13, 8, 13, 8)
        self.context_label = muted_label("")
        self.refresh_button = QPushButton("")
        context_layout.addWidget(self.context_label, 1)
        context_layout.addWidget(self.refresh_button)
        root.addWidget(self.context_strip)

        vertical = QSplitter(Qt.Orientation.Vertical)
        vertical.setChildrenCollapsible(False)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        config = QWidget()
        config_layout = QVBoxLayout(config)
        config_layout.setContentsMargins(0, 0, 4, 4)
        config_layout.setSpacing(10)

        objective = QFrame()
        objective.setObjectName("panel")
        form = QGridLayout(objective)
        form.setContentsMargins(17, 15, 17, 15)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        self.mode_label = QLabel("")
        self.mode_combo = QComboBox()
        self.ace_label = QLabel("")
        self.ace_combo = SearchableComboBox()
        self.target_label = QLabel("")
        self.target_combo = SearchableComboBox()
        self.surface_label = QLabel("")
        self.surface_combo = QComboBox()
        self.distance_label = QLabel("")
        self.distance_combo = QComboBox()
        self.style_label = QLabel("")
        self.style_combo = QComboBox()
        self.top_label = QLabel("")
        self.top_spin = QSpinBox()
        self.top_spin.setRange(5, 200)
        self.top_spin.setValue(_integer(context.store.get("optimizer_top_n", "30"), 30))
        self.top_spin.setMaximumWidth(160)
        form.addWidget(self.mode_label, 0, 0)
        form.addWidget(self.mode_combo, 1, 0)
        form.addWidget(self.ace_label, 0, 1)
        form.addWidget(self.ace_combo, 1, 1)
        form.addWidget(self.target_label, 0, 2)
        form.addWidget(self.target_combo, 1, 2)
        for column, (label, combo) in enumerate(
            ((self.surface_label, self.surface_combo), (self.distance_label, self.distance_combo), (self.style_label, self.style_combo))
        ):
            form.addWidget(label, 2, column)
            form.addWidget(combo, 3, column)
        form.addWidget(self.top_label, 4, 0)
        form.addWidget(self.top_spin, 5, 0)
        for column in range(3):
            form.setColumnStretch(column, 1)
        config_layout.addWidget(objective)

        pair_panel = QFrame()
        pair_panel.setObjectName("panel")
        pair = QGridLayout(pair_panel)
        pair.setContentsMargins(17, 14, 17, 14)
        pair.setHorizontalSpacing(12)
        self.auto_pairs = QCheckBox("")
        self.auto_pairs.setChecked(context.store.get("uma_moe_auto_pairs", "1") not in {"0", "false", "False"})
        self.fixed_label = QLabel("")
        self.fixed_combo = SearchableComboBox()
        self.local_pool_label = QLabel("")
        self.local_pool = QSpinBox()
        self.local_pool.setRange(1, 250)
        self.local_pool.setValue(_integer(context.store.get("uma_moe_local_pool", "100"), 100))
        self.remote_pool_label = QLabel("")
        self.remote_pool = QSpinBox()
        self.remote_pool.setRange(1, 500)
        self.remote_pool.setValue(_integer(context.store.get("uma_moe_remote_pool", "100"), 100))
        self.fetch_label = QLabel("")
        self.fetch_spin = QSpinBox()
        self.fetch_spin.setRange(100, 2000)
        self.fetch_spin.setSingleStep(100)
        self.fetch_spin.setValue(_integer(context.store.get("uma_moe_limit", "500"), 500))
        for widget in (self.local_pool, self.remote_pool, self.fetch_spin):
            widget.setMaximumWidth(160)
        pair.addWidget(self.auto_pairs, 0, 0, 1, 3)
        pair.addWidget(self.fixed_label, 1, 0, 1, 3)
        pair.addWidget(self.fixed_combo, 2, 0, 1, 3)
        for column, (label, spin) in enumerate(
            (
                (self.local_pool_label, self.local_pool),
                (self.remote_pool_label, self.remote_pool),
                (self.fetch_label, self.fetch_spin),
            )
        ):
            pair.addWidget(label, 3, column)
            pair.addWidget(spin, 4, column)
        for column in range(3):
            pair.setColumnStretch(column, 1)
        config_layout.addWidget(pair_panel)

        self.opposing_panel = QFrame()
        self.opposing_panel.setObjectName("panel")
        opposing = QGridLayout(self.opposing_panel)
        opposing.setContentsMargins(17, 14, 17, 14)
        opposing.setHorizontalSpacing(12)
        self._external_opposing: list[dict[str, Any]] = []
        self._opposing_entries: list[dict[str, Any]] = []
        self.opposing_label = QLabel("")
        self.opposing_combo = SearchableComboBox()
        self.opposing_hint = muted_label("")
        self.opposing_hint.setWordWrap(True)
        self.opposing_json_label = QLabel("")
        self.opposing_picker = PathPicker(
            context.store.get("uma_moe_opposing_path"),
            title="Sélectionner un JSON de parent opposé",
            file_filter="JSON (*.json);;Tous les fichiers (*)",
        )
        self.opposing_extract_button = QPushButton("")
        opposing.addWidget(self.opposing_label, 0, 0, 1, 3)
        opposing.addWidget(self.opposing_combo, 1, 0, 1, 3)
        opposing.addWidget(self.opposing_hint, 2, 0, 1, 3)
        opposing.addWidget(self.opposing_json_label, 3, 0, 1, 3)
        opposing.addWidget(self.opposing_picker, 4, 0, 1, 2)
        opposing.addWidget(self.opposing_extract_button, 4, 2)
        for column in range(3):
            opposing.setColumnStretch(column, 1)
        config_layout.addWidget(self.opposing_panel)

        self.advanced = CollapsibleSection("")
        advanced = QGridLayout()
        advanced.setHorizontalSpacing(12)
        advanced.setVerticalSpacing(8)
        self.prefer_profile = QCheckBox("")
        self.prefer_profile.setChecked(context.store.get("uql_prefer_whites", "1") not in {"0", "false", "False"})
        self.prefer_lineage = QCheckBox("")
        self.prefer_lineage.setChecked(context.store.get("uql_lineage_whites", "1") not in {"0", "false", "False"})
        self.surface_cohort = QCheckBox("")
        self.surface_cohort.setChecked(context.store.get("uql_surface_cohort", "1") not in {"0", "false", "False"})
        self.require_surface = QCheckBox("")
        self.require_distance = QCheckBox("")
        self.require_style = QCheckBox("")
        for widget, key in ((self.require_surface, "uql_require_surface"), (self.require_distance, "uql_require_distance"), (self.require_style, "uql_require_style")):
            widget.setChecked(context.store.get(key, "0") in {"1", "true", "True"})
        self.pink_label = QLabel("")
        self.pink_spin = QSpinBox()
        self.pink_spin.setRange(1, 3)
        self.pink_spin.setValue(_integer(context.store.get("uql_pink_min_stars", "1"), 1))
        self.soft_title = section_label("")
        self.soft_hint = muted_label("")
        self.soft_hint.setWordWrap(True)
        self.hard_title = section_label("")
        self.hard_hint = muted_label("")
        self.hard_hint.setWordWrap(True)
        self.pink_spin.setPrefix("≥ ")
        self.pink_spin.setSuffix("★")
        self.pink_spin.setMaximumWidth(120)
        advanced.addWidget(self.soft_title, 0, 0, 1, 3)
        advanced.addWidget(self.soft_hint, 1, 0, 1, 3)
        advanced.addWidget(self.prefer_profile, 2, 0)
        advanced.addWidget(self.prefer_lineage, 2, 1)
        advanced.addWidget(self.surface_cohort, 2, 2)
        advanced.addWidget(self.hard_title, 3, 0, 1, 3)
        advanced.addWidget(self.hard_hint, 4, 0, 1, 3)
        advanced.addWidget(self.require_surface, 5, 0)
        advanced.addWidget(self.require_distance, 5, 1)
        advanced.addWidget(self.require_style, 5, 2)
        advanced.addWidget(self.pink_label, 6, 0)
        advanced.addWidget(self.pink_spin, 6, 1)

        self.lineage_frame = QFrame()
        lineage = QGridLayout(self.lineage_frame)
        lineage.setContentsMargins(0, 8, 0, 4)
        lineage.setHorizontalSpacing(12)
        self.lineage_title = QLabel("")
        self.lineage_blue_label = QLabel("")
        self.lineage_blue_combo = QComboBox()
        self.lineage_blue_combo.addItem("—", None)
        for name in ("Speed", "Stamina", "Power", "Guts", "Wit"):
            self.lineage_blue_combo.addItem(name, name)
        self.lineage_blue_stars = QSpinBox()
        self.lineage_blue_stars.setRange(0, 9)
        self.lineage_pink_label = QLabel("")
        self.lineage_pink_combo = QComboBox()
        self.lineage_pink_combo.addItem("—", None)
        for name in (
            list(SURFACE_FACTOR_NAMES.values())
            + list(DISTANCE_FACTOR_NAMES.values())
            + list(STYLE_FACTOR_NAMES.values())
        ):
            self.lineage_pink_combo.addItem(name, name)
        self.lineage_pink_stars = QSpinBox()
        self.lineage_pink_stars.setRange(0, 9)
        saved_blue = context.store.get("uql_lineage_blue_name", "")
        saved_pink = context.store.get("uql_lineage_pink_name", "")
        blue_index = self.lineage_blue_combo.findData(saved_blue)
        pink_index = self.lineage_pink_combo.findData(saved_pink)
        self.lineage_blue_combo.setCurrentIndex(blue_index if blue_index >= 0 else 0)
        self.lineage_pink_combo.setCurrentIndex(pink_index if pink_index >= 0 else 0)
        self.lineage_blue_stars.setValue(_integer(context.store.get("uql_lineage_blue_stars", "0"), 0))
        self.lineage_pink_stars.setValue(_integer(context.store.get("uql_lineage_pink_stars", "0"), 0))
        self.lineage_hint = muted_label("")
        self.lineage_hint.setWordWrap(True)
        self.lineage_blue_stars.setPrefix("≥ ")
        self.lineage_blue_stars.setSuffix("★")
        self.lineage_blue_stars.setSpecialValueText(self.context.t("désactivé"))
        self.lineage_pink_stars.setPrefix("≥ ")
        self.lineage_pink_stars.setSuffix("★")
        self.lineage_pink_stars.setSpecialValueText(self.context.t("désactivé"))
        for widget in (self.lineage_blue_stars, self.lineage_pink_stars):
            widget.setMaximumWidth(120)
        for widget in (self.lineage_blue_combo, self.lineage_pink_combo):
            widget.setMaximumWidth(210)
        lineage.addWidget(self.lineage_title, 0, 0, 1, 3)
        lineage.addWidget(self.lineage_blue_label, 1, 0)
        lineage.addWidget(self.lineage_blue_combo, 1, 1)
        lineage.addWidget(self.lineage_blue_stars, 1, 2)
        lineage.addWidget(self.lineage_pink_label, 2, 0)
        lineage.addWidget(self.lineage_pink_combo, 2, 1)
        lineage.addWidget(self.lineage_pink_stars, 2, 2)
        lineage.addWidget(self.lineage_hint, 3, 0, 1, 3)
        advanced.addWidget(self.lineage_frame, 7, 0, 1, 3)

        self.parent_filters = QFrame()
        parent_filters_layout = QGridLayout(self.parent_filters)
        parent_filters_layout.setContentsMargins(0, 8, 0, 4)
        self.required_label = QLabel("")
        self.required_combo = SearchableComboBox()
        self.allowed_button = QPushButton("")
        self.excluded_button = QPushButton("")
        parent_filters_layout.addWidget(self.required_label, 0, 0, 1, 3)
        parent_filters_layout.addWidget(self.required_combo, 1, 0, 1, 3)
        parent_filters_layout.addWidget(self.allowed_button, 2, 1)
        parent_filters_layout.addWidget(self.excluded_button, 2, 2)
        parent_filters_layout.setColumnStretch(0, 1)
        advanced.addWidget(self.parent_filters, 8, 0, 1, 3)

        self.g1_options = QFrame()
        g1 = QGridLayout(self.g1_options)
        g1.setContentsMargins(0, 8, 0, 4)
        self.g1_budget_label = QLabel("")
        self.g1_budget = QSpinBox()
        self.g1_budget.setRange(0, 40)
        self.g1_budget.setValue(_integer(context.store.get("uma_moe_parent_g1_budget", "20"), 20))
        self.g1_weight_label = QLabel("")
        self.g1_weight = QDoubleSpinBox()
        self.g1_weight.setRange(0.0, 1.0)
        self.g1_weight.setSingleStep(0.1)
        self.g1_weight.setDecimals(2)
        try:
            self.g1_weight.setValue(float(context.store.get("uma_moe_single_g1_weight", "0.6")))
        except ValueError:
            self.g1_weight.setValue(0.6)
        g1.addWidget(self.g1_budget_label, 0, 0)
        g1.addWidget(self.g1_budget, 1, 0)
        g1.addWidget(self.g1_weight_label, 0, 1)
        g1.addWidget(self.g1_weight, 1, 1)
        g1.setColumnStretch(2, 1)
        advanced.addWidget(self.g1_options, 9, 0, 1, 3)

        self.uql_label = QLabel("")
        self.uql_edit = QPlainTextEdit()
        self.uql_edit.setReadOnly(True)
        self.uql_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.uql_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.uql_edit.setMaximumHeight(56)
        self._set_uql_text(context.store.get("uma_moe_query"))
        advanced.addWidget(self.uql_label, 10, 0, 1, 3)
        advanced.addWidget(self.uql_edit, 11, 0, 1, 3)
        self.api_label = QLabel("")
        self.api_base = QLineEdit(context.store.get("uma_moe_base", DEFAULT_API_BASE) or DEFAULT_API_BASE)
        self.key_label = QLabel("")
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.show_key = QPushButton("")
        self.remember_key = QCheckBox("")
        remembered = context.store.get("uma_moe_remember_api_key", "0") in {"1", "true", "True"}
        self.remember_key.setChecked(remembered and os.name == "nt")
        if remembered and os.name == "nt":
            self.key_edit.setText(load_api_key(api_key_path()))
        elif os.environ.get("UMA_MOE_API_KEY"):
            self.key_edit.setText(os.environ["UMA_MOE_API_KEY"])
        self.import_label = QLabel("")
        self.import_picker = PathPicker(
            context.store.get("uma_moe_response_path"),
            title="Sélectionner une réponse JSON de l’API uma.moe",
            file_filter="JSON (*.json);;Tous les fichiers (*)",
        )
        advanced.addWidget(self.api_label, 12, 0)
        advanced.addWidget(self.api_base, 13, 0, 1, 3)
        advanced.addWidget(self.key_label, 14, 0)
        key_row = QHBoxLayout()
        key_row.addWidget(self.key_edit, 1)
        key_row.addWidget(self.show_key)
        advanced.addLayout(key_row, 15, 0, 1, 3)
        advanced.addWidget(self.remember_key, 16, 0, 1, 3)
        advanced.addWidget(self.import_label, 17, 0, 1, 3)
        advanced.addWidget(self.import_picker, 18, 0, 1, 3)
        for column in range(3):
            advanced.setColumnStretch(column, 1)
        self.advanced.content_layout.addLayout(advanced)
        config_layout.addWidget(self.advanced)

        actions = QGridLayout()
        actions.setHorizontalSpacing(8)
        actions.setVerticalSpacing(8)
        self.live_button = QPushButton("")
        self.live_button.setObjectName("primary")
        self.import_button = QPushButton("")
        self.local_pairs_button = QPushButton("")
        self.load_button = QPushButton("")
        self.open_button = QPushButton("")
        actions.addWidget(self.live_button, 0, 0)
        actions.addWidget(self.import_button, 0, 1)
        actions.addWidget(self.local_pairs_button, 0, 2)
        actions.addWidget(self.load_button, 1, 0)
        actions.addWidget(self.open_button, 1, 1)
        actions.setColumnStretch(2, 1)
        config_layout.addLayout(actions)
        config_layout.addStretch(1)
        scroll.setWidget(config)

        result_widget = QWidget()
        result_layout = QVBoxLayout(result_widget)
        result_layout.setContentsMargins(0, 0, 0, 0)
        self.results_title = section_label("")
        self.results = OnlineResultsPane(context)
        result_layout.addWidget(self.results_title)
        result_layout.addWidget(self.results, 1)
        vertical.addWidget(scroll)
        vertical.addWidget(result_widget)
        vertical.setStretchFactor(0, 0)
        vertical.setStretchFactor(1, 1)
        self._config_scroll = scroll
        self._vertical_splitter = vertical
        self.advanced.toggle.toggled.connect(
            lambda _checked: QTimer.singleShot(0, self._sync_config_pane_height)
        )
        QTimer.singleShot(0, self._sync_config_pane_height)
        root.addWidget(vertical, 1)

        self.refresh_button.clicked.connect(lambda: self.refresh_options(show_errors=True))
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        self.auto_pairs.toggled.connect(self.fixed_combo.setDisabled)
        self.ace_combo.currentIndexChanged.connect(self._refresh_context)
        self.target_combo.currentIndexChanged.connect(self._refresh_context)
        self.surface_combo.currentIndexChanged.connect(self._refresh_context)
        self.distance_combo.currentIndexChanged.connect(self._refresh_context)
        self.style_combo.currentIndexChanged.connect(self._refresh_context)
        self.allowed_button.clicked.connect(lambda: self._pick_filter("allowed"))
        self.excluded_button.clicked.connect(lambda: self._pick_filter("excluded"))
        self.show_key.clicked.connect(self._toggle_key)
        self.remember_key.toggled.connect(self._remember_changed)
        self.live_button.clicked.connect(lambda: self.start_search(False))
        self.import_button.clicked.connect(lambda: self.start_search(True))
        self.local_pairs_button.clicked.connect(lambda: self.start_search(False, local_pairs=True))
        self.opposing_extract_button.clicked.connect(self._extract_opposing_candidates)
        self.load_button.clicked.connect(lambda: self.load_latest(show_errors=True))
        self.open_button.clicked.connect(self.open_output)
        self.context.configuration_changed.connect(self._schedule_sync)
        self.context.language_changed.connect(lambda _language: self.retranslate())
        self._sync_timer = QTimer(self)
        self._sync_timer.setSingleShot(True)
        self._sync_timer.timeout.connect(self.sync_context)
        self.retranslate()
        QTimer.singleShot(0, lambda: self.refresh_options(show_errors=False))
        QTimer.singleShot(80, lambda: self.load_latest(show_errors=False))

    def _schedule_sync(self) -> None:
        self._sync_timer.start(120)

    def _populate_profiles(self) -> None:
        for combo, kind, codes, fallback in (
            (self.surface_combo, "surface", ("turf", "dirt"), "turf"),
            (self.distance_combo, "distance", ("sprint", "mile", "medium", "long"), "medium"),
            (self.style_combo, "style", ("front_runner", "pace_chaser", "late_surger", "end_closer"), "pace_chaser"),
        ):
            selected = combo.currentData() or self.context.store.get(f"optimizer_{kind}", fallback)
            combo.blockSignals(True)
            combo.clear()
            for code, label in zip(codes, profile_values(kind, self.context.language)):
                combo.addItem(label, code)
            index = combo.findData(selected)
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.blockSignals(False)

    def retranslate(self) -> None:
        t = self.context.t
        self.header.set_text(
            t("Recherche uma.moe"),
            t("Associe ta collection locale aux profils publics, puis classe les paires avec le même moteur que l’optimiseur."),
        )
        selected_mode = self.mode_combo.currentData() or self.context.store.get("uma_moe_search_mode", "parent")
        self.mode_combo.blockSignals(True)
        self.mode_combo.clear()
        self.mode_combo.addItem(t("Parent distant pour l’Ace"), "parent")
        self.mode_combo.addItem(t("Grand-parent distant pour produire un parent"), "grandparent")
        self.mode_combo.setCurrentIndex(max(0, self.mode_combo.findData(selected_mode)))
        self.mode_combo.blockSignals(False)
        self.mode_label.setText(t("Type de recherche"))
        self.ace_label.setText(t("Ace visé"))
        self.target_label.setText(t("Parent à produire"))
        self.surface_label.setText(t("Surface"))
        self.distance_label.setText(t("Distance"))
        self.style_label.setText(t("Style"))
        self.top_label.setText(t("Résultats conservés"))
        self.auto_pairs.setText(t("Tester automatiquement toutes les paires local × distant"))
        self.local_pool_label.setText(t("Pool local"))
        self.remote_pool_label.setText(t("Pool distant"))
        self.fetch_label.setText(t("Fetch API"))
        self.advanced.set_title(t("Filtres, API et options avancées"))
        self.prefer_profile.setText(t("Favoriser les whites du profil"))
        self.prefer_lineage.setText(t("Favoriser leur répétition dans la lignée"))
        self.surface_cohort.setText(t("Cohorte Surface dédiée (récupération API)"))
        self.require_surface.setText(t("Exiger la surface cible"))
        self.require_distance.setText(t("Exiger la distance cible"))
        self.require_style.setText(t("Exiger le style cible"))
        self.pink_label.setText(t("Étoiles pink minimum"))
        self.soft_title.setText(t("Orientation de la recherche"))
        self.soft_hint.setText(
            t("Préférences souples : elles orientent le tri de l'API sans exclure personne.")
        )
        self.hard_title.setText(t("Filtres durs"))
        self.hard_hint.setText(
            t("Ils excluent réellement des candidats et réduisent le pool. À utiliser quand ta branche locale ne couvre pas l'aptitude.")
        )
        self.lineage_title.setText(t("Étoiles minimales sur la lignée distante (Main + ses deux parents)"))
        self.lineage_blue_label.setText(t("Stat Blue"))
        self.lineage_pink_label.setText(t("Aptitude Pink"))
        self.lineage_hint.setText(
            t("Comme les curseurs du site uma.moe. Appliqué après téléchargement : augmente le fetch API si trop de candidats sont éliminés.")
        )
        for spin in (self.lineage_blue_stars, self.lineage_pink_stars):
            spin.setSpecialValueText(t("désactivé"))
        self.lineage_blue_combo.setToolTip(
            t("Stat Blue dont les étoiles sont additionnées sur le Main distant et ses deux parents.")
        )
        self.lineage_pink_combo.setToolTip(
            t("Aptitude Pink (surface, distance ou style) dont les étoiles sont additionnées sur le Main distant et ses deux parents.")
        )
        self.opposing_label.setText(t("Parent opposé (contexte)"))
        self.opposing_hint.setText(
            t(
                "Avec un parent opposé fixé, chaque candidat GP est évalué par le moteur exact de la paire finale à six membres."
            )
        )
        self.opposing_json_label.setText(t("JSON du parent opposé (paires exportées ou réponse API)"))
        self.opposing_picker.dialog_title = t("Sélectionner un JSON de parent opposé")
        self.opposing_picker.file_filter = f"JSON (*.json);;{t('Tous les fichiers')} (*)"
        self.opposing_picker.set_button_text(t("Parcourir…"))
        self.opposing_extract_button.setText(t("Extraire les candidats"))
        self.local_pairs_button.setText(t("Paires de GP locales"))
        self.local_pairs_button.setToolTip(
            t("Classe toutes les paires de GP locales avec le moteur uma.moe exact, sans requête API.")
        )
        self.required_label.setText(t("Costume requis dans la paire"))
        self.g1_budget_label.setText(t("G1 prévues sur le parent"))
        self.g1_weight_label.setText(t("Valeur d’une G1 non commune"))
        self.uql_label.setText(t("UQL de référence — non envoyée comme texte libre à l’API"))
        self.api_label.setText(t("Base API"))
        self.key_label.setText(t("Clé API"))
        self.show_key.setText(t("Afficher"))
        self.remember_key.setText(t("Mémoriser la clé sur ce PC — chiffrée par Windows"))
        self.import_label.setText(t("Réponse JSON à classer hors ligne"))
        self.import_picker.dialog_title = t("Sélectionner une réponse JSON de l’API uma.moe")
        self.import_picker.file_filter = f"JSON (*.json);;{t('Tous les fichiers')} (*)"
        self.import_picker.set_button_text(t("Parcourir…"))
        self.live_button.setText(t("Chercher et classer les paires"))
        self.import_button.setText(t("Classer le JSON importé"))
        self.load_button.setText(t("Charger le dernier résultat"))
        self.open_button.setText(t("Ouvrir la sortie"))
        self.refresh_button.setText(t("Actualiser les listes"))
        self.results_title.setText(t("Résultats intégrés"))
        self._populate_profiles()
        self._refresh_filter_summaries()
        self._refresh_opposing_options()
        self._mode_changed()
        self._refresh_context()
        QTimer.singleShot(0, self._sync_config_pane_height)

    def _sync_config_pane_height(self, *_args: object) -> None:
        sync_scroll_pane_height(
            getattr(self, "_vertical_splitter", None),
            getattr(self, "_config_scroll", None),
        )

    def sync_context(self) -> None:
        self._populate_profiles()
        self.top_spin.setValue(_integer(self.context.store.get("optimizer_top_n", str(self.top_spin.value())), self.top_spin.value()))
        self._refresh_context()

    def refresh_options(self, _checked: bool = False, *, show_errors: bool = True) -> None:
        try:
            master = Path(self.context.master_path).expanduser()
            data = Path(self.context.veterans_json_path).expanduser()
            self._ace_options = list(load_ace_options(master))
            self._local_options = load_local_veteran_options(master, data)
        except Exception as exc:
            if show_errors:
                QMessageBox.warning(self, self.context.t("Configuration incomplète"), self.context.t(str(exc)))
            return
        self._card_to_chara = {item.card_id: item.chara_id for item in self._ace_options}
        saved_ace = _integer(self.context.store.get("optimizer_ace_card_id"))
        saved_target = _integer(self.context.store.get("optimizer_future_parent_card_id"))
        current_ace = self.ace_combo.currentData() or saved_ace
        current_target = self.target_combo.currentData() or saved_target
        for combo, selected in ((self.ace_combo, current_ace), (self.target_combo, current_target)):
            combo.blockSignals(True)
            combo.clear()
            for option in self._ace_options:
                combo.addItem(option.display_name, option.card_id)
            index = combo.findData(selected)
            combo.setCurrentIndex(index if index >= 0 else (0 if combo.count() else -1))
            combo.blockSignals(False)
        fixed_selected = _integer(self.context.store.get("uma_moe_fixed_gp_id"))
        self.fixed_combo.blockSignals(True)
        self.fixed_combo.clear()
        for option in self._local_options:
            self.fixed_combo.addItem(option.display_name, option.trained_chara_id)
        fixed_index = self.fixed_combo.findData(fixed_selected)
        self.fixed_combo.setCurrentIndex(fixed_index if fixed_index >= 0 else (0 if self.fixed_combo.count() else -1))
        self.fixed_combo.blockSignals(False)
        required = self.required_combo.currentData() or _integer(self.context.store.get("uma_moe_required_parent_card_id"))
        self.required_combo.clear()
        self.required_combo.addItem(self.context.t("Aucun costume requis"), None)
        for option in self._ace_options:
            self.required_combo.addItem(option.display_name, option.card_id)
        required_index = self.required_combo.findData(required)
        self.required_combo.setCurrentIndex(required_index if required_index >= 0 else 0)
        if not self._external_opposing:
            saved_path = str(self.context.store.get("uma_moe_opposing_path") or "").strip()
            if saved_path and Path(saved_path).expanduser().is_file():
                try:
                    candidates = load_opposing_parent_candidates(
                        master, Path(saved_path).expanduser()
                    )
                    self._external_opposing = [
                        {"member": member, "path": saved_path} for member in candidates
                    ]
                except Exception:
                    self._external_opposing = []
        self._refresh_opposing_options()
        self._mode_changed()

    def _mode_changed(self, _index: int = -1) -> None:
        parent_mode = self.mode_combo.currentData() == "parent"
        self.target_label.setVisible(not parent_mode)
        self.target_combo.setVisible(not parent_mode)
        self.parent_filters.setVisible(parent_mode)
        self.g1_options.setVisible(not parent_mode)
        self.opposing_panel.setVisible(not parent_mode)
        self.local_pairs_button.setVisible(not parent_mode)
        self.fixed_label.setText(self.context.t("Parent local fixé (manuel)" if parent_mode else "GP local fixé (manuel)"))
        self.fixed_combo.setDisabled(self.auto_pairs.isChecked())
        self._refresh_context()

    def _filter_options(self) -> list[tuple[int, str]]:
        return [(option.card_id, option.display_name) for option in self._ace_options]

    def _pick_filter(self, kind: str) -> None:
        selected = self._allowed_ids if kind == "allowed" else self._excluded_ids
        title = self.context.t("Costumes autorisés" if kind == "allowed" else "Costumes exclus")
        dialog = CardFilterDialog(self.context, self._filter_options(), set(selected), title, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if kind == "allowed":
            self._allowed_ids = dialog.selected_ids()
        else:
            self._excluded_ids = dialog.selected_ids()
        self._refresh_filter_summaries()

    def _refresh_filter_summaries(self) -> None:
        self.allowed_button.setText(f"{self.context.t('Autorisés')} ({len(self._allowed_ids)})")
        self.excluded_button.setText(f"{self.context.t('Exclus')} ({len(self._excluded_ids)})")

    def _current_profile(self) -> dict[str, Any]:
        return {
            "surface": str(self.surface_combo.currentData() or "turf"),
            "distance": str(self.distance_combo.currentData() or "medium"),
            "style": str(self.style_combo.currentData() or "pace_chaser"),
        }

    def _course_conditions(self) -> dict[str, object]:
        mapping: dict[str, dict[str, object]] = {
            "optimizer_rotation": {"Droite": 1, "Gauche": 2},
            "optimizer_season": {"Printemps": [1, 5], "Été": 2, "Automne": 3, "Hiver": 4},
            "optimizer_weather": {"Ensoleillé": 1, "Nuageux": 2, "Pluie": 3, "Neige": 4},
            "optimizer_ground": {"Firm": 1, "Good": 2, "Soft": 3, "Heavy": 4},
        }
        keys = {
            "optimizer_rotation": "rotation",
            "optimizer_season": "season",
            "optimizer_weather": "weather",
            "optimizer_ground": "ground_condition",
        }
        course_key = self.context.store.get("optimizer_course_key")
        definitions = dict(
            ordered_course_presets(
                load_course_preset_payload(
                    active_course_overrides_path(self.context.course_overrides_path)
                )
            )
        )
        result: dict[str, object] = dict(
            course_preset_conditions(definitions.get(course_key) or {})
        )
        track = _integer(self.context.store.get("optimizer_track_id"))
        if track:
            result["track_id"] = track
        for store_key, options in mapping.items():
            value = options.get(self.context.store.get(store_key))
            if value is not None:
                result[keys[store_key]] = value
        return result

    def _refresh_context(self, _index: int = -1) -> None:
        mode = self.context.t("Parent distant" if self.mode_combo.currentData() == "parent" else "GP distant")
        ace = self.ace_combo.currentText().split(" — ", 1)[0] or "—"
        target = self.target_combo.currentText().split(" — ", 1)[0] or "—"
        text = f"{self.context.t('Contexte actif')} · {mode} · Ace: {ace}"
        if self.mode_combo.currentData() != "parent":
            text += f" · {self.context.t('Parent à produire')}: {target}"
        text += f" · {profile_summary(self._current_profile(), self.context.language)}"
        self.context_label.setText(text)

    def _toggle_key(self) -> None:
        hidden = self.key_edit.echoMode() == QLineEdit.EchoMode.Password
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Normal if hidden else QLineEdit.EchoMode.Password)
        self.show_key.setText(self.context.t("Masquer" if hidden else "Afficher"))

    def _remember_changed(self, checked: bool) -> None:
        if checked and os.name != "nt":
            self.remember_key.blockSignals(True)
            self.remember_key.setChecked(False)
            self.remember_key.blockSignals(False)
            QMessageBox.information(self, self.context.t("Clé API"), self.context.t("Le stockage chiffré de la clé est disponible dans l’application Windows."))
        elif not checked and os.name == "nt":
            try:
                save_api_key(api_key_path(), "")
            except (OSError, SecretStoreError) as exc:
                QMessageBox.warning(self, self.context.t("Clé API"), str(exc))

    def _set_uql_text(self, text: object) -> None:
        """Show the reference UQL as flowing text.

        The generated file is written one factor per line, which turns the
        read-only preview into a tall vertical list. Collapse it so the box
        wraps horizontally instead.
        """
        flowed = " ".join(str(text or "").split())
        self.uql_edit.setPlainText(flowed)

    def _external_display(self, member: dict[str, Any]) -> str:
        online = member.get("online") if isinstance(member.get("online"), dict) else {}
        suffix = (
            online.get("trainer_name")
            or online.get("friend_code")
            or member.get("trained_chara_id")
            or f"card:{member.get('card_id')}"
        )
        return (
            f"{self.context.t('Externe')} — {member.get('uma_name') or '?'} — "
            f"{member.get('card_name') or member.get('card_id')} — {suffix}"
        )

    def _refresh_opposing_options(self) -> None:
        selected = self.opposing_combo.currentIndex()
        saved_local = _integer(self.context.store.get("uma_moe_opposing_id"))
        entries: list[dict[str, Any]] = [{"source": "none"}]
        labels: list[str] = [self.context.t("(aucun — recherche GP polyvalente)")]
        restore_index = 0
        for option in self._local_options:
            entries.append(
                {"source": "local", "trained_chara_id": option.trained_chara_id}
            )
            labels.append(f"{self.context.t('Local')} — {option.display_name}")
            if selected <= 0 and option.trained_chara_id == saved_local:
                restore_index = len(entries) - 1
        for record in self._external_opposing:
            member = record.get("member") if isinstance(record.get("member"), dict) else {}
            entries.append({"source": "external", "member": member})
            labels.append(self._external_display(member))
        if 0 < selected < len(entries):
            restore_index = selected
        self._opposing_entries = entries
        self.opposing_combo.blockSignals(True)
        self.opposing_combo.clear()
        for label in labels:
            self.opposing_combo.addItem(label)
        self.opposing_combo.setCurrentIndex(restore_index)
        self.opposing_combo.blockSignals(False)

    def _extract_opposing_candidates(self) -> None:
        text = self.opposing_picker.text().strip()
        if not text:
            QMessageBox.warning(
                self,
                self.context.t("Configuration incomplète"),
                self.context.t("Sélectionne d’abord un JSON de parent opposé."),
            )
            return
        path = Path(text).expanduser()
        try:
            candidates = load_opposing_parent_candidates(
                Path(self.context.master_path).expanduser(), path
            )
        except Exception as exc:
            QMessageBox.warning(
                self, self.context.t("Parent opposé (contexte)"), self.context.t(str(exc))
            )
            return
        if not candidates:
            QMessageBox.warning(
                self,
                self.context.t("Parent opposé (contexte)"),
                self.context.t(
                    "Aucune branche complète trouvée. Le JSON doit contenir un parent et ses deux grands-parents."
                ),
            )
            return
        self._external_opposing = [
            {"member": member, "path": str(path)} for member in candidates
        ]
        self.context.store.update({"uma_moe_opposing_path": str(path)})
        self._refresh_opposing_options()
        self.opposing_combo.setCurrentIndex(
            len(self._opposing_entries) - len(self._external_opposing)
        )

    def _opposing_selection(self) -> tuple[int | None, dict[str, Any] | None]:
        self.opposing_combo.resolve_current_text()
        index = self.opposing_combo.currentIndex()
        if not 0 <= index < len(self._opposing_entries):
            return None, None
        entry = self._opposing_entries[index]
        if entry.get("source") == "local":
            return int(entry.get("trained_chara_id") or 0) or None, None
        if entry.get("source") == "external":
            member = entry.get("member")
            return None, copy.deepcopy(member) if isinstance(member, dict) else None
        return None, None

    def _lineage_filter(
        self, combo: QComboBox, spin: QSpinBox
    ) -> tuple[str, int] | None:
        name = str(combo.currentData() or "").strip()
        stars = int(spin.value())
        if not name or stars <= 0:
            return None
        return (name, max(1, min(stars, 9)))

    def _validate_selection(self) -> tuple[int, int | None, int | None]:
        self.ace_combo.resolve_current_text()
        self.target_combo.resolve_current_text()
        self.fixed_combo.resolve_current_text()
        self.required_combo.resolve_current_text()
        ace = _integer(self.ace_combo.currentData())
        target = _integer(self.target_combo.currentData()) if self.mode_combo.currentData() != "parent" else None
        fixed = None if self.auto_pairs.isChecked() else _integer(self.fixed_combo.currentData())
        if not ace:
            raise UmaMoeError("Sélectionne l’Ace cible.")
        if self.mode_combo.currentData() != "parent":
            if not target:
                raise UmaMoeError("Sélectionne le parent à produire.")
            if self._card_to_chara.get(ace) == self._card_to_chara.get(target):
                raise UmaMoeError("L’Ace et le parent à produire doivent être différents.")
            if fixed:
                local = next((item for item in self._local_options if item.trained_chara_id == fixed), None)
                if local and local.chara_id == self._card_to_chara.get(target):
                    raise UmaMoeError("Un grand-parent ne peut pas être la même Uma que le parent à produire, quel que soit le costume.")
        if not self.auto_pairs.isChecked() and not fixed:
            raise UmaMoeError("Sélectionne un membre local ou active le test automatique des paires.")
        return ace, target, fixed

    def start_search(self, use_import: bool, *, local_pairs: bool = False) -> None:
        try:
            ace, target, fixed = self._validate_selection()
            response_text = self.import_picker.text()
            response = Path(response_text).expanduser() if response_text else None
            required = self.required_combo.currentData()
            if required in self._excluded_ids:
                raise UmaMoeError("Le costume requis est également exclu.")
            if self._allowed_ids and required is not None and int(required) not in self._allowed_ids:
                raise UmaMoeError("Le costume requis doit être présent dans les costumes autorisés.")
            priority_text = self.context.store.get("skill_priorities_path")
            opposing_id, opposing_payload = (
                self._opposing_selection()
                if self.mode_combo.currentData() != "parent"
                else (None, None)
            )
            lineage_blue = self._lineage_filter(
                self.lineage_blue_combo, self.lineage_blue_stars
            )
            lineage_pink = self._lineage_filter(
                self.lineage_pink_combo, self.lineage_pink_stars
            )
            request = OnlineSearchRequest(
                search_mode=str(self.mode_combo.currentData() or "parent"),
                master_path=Path(self.context.master_path).expanduser(),
                veterans_json_path=Path(self.context.veterans_json_path).expanduser(),
                output_dir=Path(self.context.output_dir).expanduser(),
                ace_card_id=ace,
                target_parent_card_id=target,
                fixed_local_id=fixed,
                automatic_pairs=self.auto_pairs.isChecked(),
                local_pool_size=self.local_pool.value(),
                remote_pool_size=self.remote_pool.value(),
                surface=str(self.surface_combo.currentData() or "turf"),
                distance=str(self.distance_combo.currentData() or "medium"),
                style=str(self.style_combo.currentData() or "pace_chaser"),
                course_overrides_path=active_course_overrides_path(self.context.course_overrides_path),
                course_key=self.context.store.get("optimizer_course_key") or None,
                course_conditions=self._course_conditions(),
                top_n=self.top_spin.value(),
                use_import=use_import,
                response_path=response,
                api_base=self.api_base.text().strip() or DEFAULT_API_BASE,
                uql="",
                auto_uql=True,
                uql_options={
                    "prefer_profile_whites": self.prefer_profile.isChecked(),
                    "prefer_lineage_whites": self.prefer_lineage.isChecked(),
                    "require_main_surface": self.require_surface.isChecked(),
                    "require_main_distance": self.require_distance.isChecked(),
                    "require_main_style": self.require_style.isChecked(),
                    "pink_min_stars": self.pink_spin.value(),
                    "enable_surface_retrieval": self.surface_cohort.isChecked(),
                },
                limit=self.fetch_spin.value(),
                planned_g1_budget=self.g1_budget.value(),
                single_g1_weight=self.g1_weight.value(),
                required_parent_card_id=(int(required) if required is not None else None),
                allowed_parent_card_ids=tuple(sorted(self._allowed_ids)),
                excluded_parent_card_ids=tuple(sorted(self._excluded_ids)),
                token=self.key_edit.text().strip(),
                use_custom_scoring=self.context.store.get("use_custom_scoring", "0") in {"1", "true", "True"},
                skill_priorities_path=(Path(priority_text).expanduser() if priority_text else None),
                opposing_parent_trained_id=opposing_id,
                opposing_parent_payload=opposing_payload,
                local_pair_mode=local_pairs,
                lineage_blue_filter=lineage_blue,
                lineage_pink_filter=lineage_pink,
            )
            if use_import and (response is None or not response.is_file()):
                raise UmaMoeError("Sélectionne une réponse JSON uma.moe à importer.")
        except (UmaMoeError, OptimizerError, ValueError) as exc:
            QMessageBox.warning(self, self.context.t("Configuration incomplète"), self.context.t(str(exc)))
            return
        if self.remember_key.isChecked() and os.name == "nt":
            try:
                save_api_key(api_key_path(), request.token)
            except (OSError, SecretStoreError) as exc:
                QMessageBox.warning(
                    self,
                    self.context.t("Clé API"),
                    self.context.t("La recherche va continuer, mais la clé n’a pas pu être mémorisée.")
                    + f"\n\n{exc}",
                )
        self.context.store.update(
            {
                "uma_moe_search_mode": request.search_mode,
                "optimizer_ace_card_id": request.ace_card_id,
                "optimizer_future_parent_card_id": request.target_parent_card_id or self.context.store.get("optimizer_future_parent_card_id", "0"),
                "optimizer_surface": request.surface,
                "optimizer_distance": request.distance,
                "optimizer_style": request.style,
                "uma_moe_auto_pairs": int(request.automatic_pairs),
                "uma_moe_fixed_gp_id": fixed or 0,
                "uma_moe_local_pool": request.local_pool_size,
                "uma_moe_remote_pool": request.remote_pool_size,
                "uma_moe_limit": request.limit,
                "uma_moe_base": request.api_base,
                "uma_moe_response_path": response_text,
                "uma_moe_parent_g1_budget": request.planned_g1_budget,
                "uma_moe_single_g1_weight": request.single_g1_weight,
                "uma_moe_required_parent_card_id": required or 0,
                "uma_moe_parent_allowed_card_ids": ",".join(map(str, sorted(self._allowed_ids))),
                "uma_moe_parent_excluded_card_ids": ",".join(map(str, sorted(self._excluded_ids))),
                "uma_moe_remember_api_key": int(self.remember_key.isChecked()),
                "uql_prefer_whites": int(self.prefer_profile.isChecked()),
                "uql_lineage_whites": int(self.prefer_lineage.isChecked()),
                "uql_surface_cohort": int(self.surface_cohort.isChecked()),
                "uql_require_surface": int(self.require_surface.isChecked()),
                "uql_require_distance": int(self.require_distance.isChecked()),
                "uql_require_style": int(self.require_style.isChecked()),
                "uql_pink_min_stars": self.pink_spin.value(),
                "uql_lineage_blue_name": str(self.lineage_blue_combo.currentData() or ""),
                "uql_lineage_blue_stars": self.lineage_blue_stars.value(),
                "uql_lineage_pink_name": str(self.lineage_pink_combo.currentData() or ""),
                "uql_lineage_pink_stars": self.lineage_pink_stars.value(),
                "uma_moe_opposing_id": opposing_id or 0,
            }
        )
        self.context.configuration_changed.emit()
        busy_label = (
            "Classement des paires de GP locales…"
            if local_pairs
            else "Recherche et classement uma.moe…"
        )
        self.task_requested.emit(
            partial(run_online_search, request),
            self.context.t(busy_label),
            lambda result: self._search_done(result, request),
        )

    def _search_done(self, result: object, request: OnlineSearchRequest) -> None:
        self.results.set_result(result, {"surface": request.surface, "distance": request.distance, "style": request.style})
        generated_uql = request.output_dir / "uma_moe_generated_uql.txt"
        if not request.local_pair_mode and generated_uql.is_file():
            self._set_uql_text(generated_uql.read_text(encoding="utf-8"))
        response = request.output_dir / "uma_moe_api_response.json"
        if not request.use_import and response.is_file():
            self.import_picker.set_text(str(response))

    def load_latest(self, *, show_errors: bool = True) -> None:
        output = Path(self.context.output_dir).expanduser()
        candidates = [
            (output / "uma_moe_parent_pairs.json", "parent"),
            (output / "uma_moe_grandparent_pairs.json", "grandparent"),
        ]
        existing = [(path, mode) for path, mode in candidates if path.is_file()]
        if not existing:
            if show_errors:
                QMessageBox.information(self, self.context.t("Dernier résultat"), self.context.t("Aucun résultat uma.moe n’a encore été généré."))
            return
        path, mode = max(existing, key=lambda item: item[0].stat().st_mtime)
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(payload, dict):
                raise ValueError("Le résultat doit être un objet JSON.")
            self.results.set_payload(payload, mode)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            if show_errors:
                QMessageBox.warning(self, self.context.t("Dernier résultat"), str(exc))

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        for widget in (self.live_button, self.import_button, self.load_button, self.refresh_button):
            widget.setEnabled(not busy)

    def open_output(self) -> None:
        output = Path(self.context.output_dir).expanduser()
        try:
            output.mkdir(parents=True, exist_ok=True)
            open_path(output)
        except OSError as exc:
            QMessageBox.critical(self, self.context.t("Erreur"), str(exc))
