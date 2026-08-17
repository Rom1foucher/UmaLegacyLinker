"""Result tables and their diagnostics, shared by every Search family.

Extracted from the former per-source pages so one workspace can hold several
live panes at once. The pages themselves are gone: the Search workspace owns
the context, the actions and the result families.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import QItemSelection, Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableView,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from lineage_planner import (
    LineagePlannerError,
    build_lineage_planner_export,
    write_lineage_planner_export,
)
from uma_moe import OnlineParentSearchResult
from ui_qt.components import muted_label
from ui_qt.context import AppContext
from ui_qt.lineage_view import LineageDialog
from ui_qt.models import Column, ResultTableModel, nested
from ui_qt.presentation import (
    distance_status,
    online_detail_html,
    result_detail_html,
)

RIGHT = Qt.AlignmentFlag.AlignRight


def _integer(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class ResultPane(QWidget):
    def __init__(self, kind: str, context: AppContext, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.context = context
        self.profile: dict[str, Any] = {}
        self.lineage_root: dict[str, Any] | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(7)
        self.summary = muted_label("")
        head = QHBoxLayout()
        self.lineage_button = QPushButton("")
        self.lineage_button.setEnabled(False)
        head.addWidget(self.summary, 1)
        head.addWidget(self.lineage_button)
        root.addLayout(head)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.table = QTableView()
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.detail = QTextBrowser()
        self.detail.setOpenExternalLinks(True)
        self.detail.setMinimumWidth(520)
        self.model = ResultTableModel([], self._columns())
        self.table.setModel(self.model)
        self.model.layoutChanged.connect(self._model_reordered)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setMinimumSectionSize(58)
        splitter.addWidget(self.table)
        splitter.addWidget(self.detail)
        splitter.setChildrenCollapsible(False)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 4)
        splitter.setSizes([700, 560])
        root.addWidget(splitter, 1)
        self.table.selectionModel().selectionChanged.connect(self._selection_changed)
        self.table.doubleClicked.connect(self._double_clicked)
        self.lineage_button.clicked.connect(self.open_lineage)
        self._configure_header()
        self.retranslate()

    def _columns(self) -> list[Column]:
        t = self.context.t
        rank = Column("#", nested("_rank"), RIGHT)
        score = Column(t("Score"), nested("score"), RIGHT)
        if self.kind == "pair":
            return [
                rank,
                score,
                Column(t("Parent 1"), nested("parent_1", "card_name")),
                Column(t("Parent 2"), nested("parent_2", "card_name")),
                Column(t("Distance"), lambda row: distance_status(row, self.context.language)),
                Column("P(S) %", lambda row: 100 * float((row.get("distance_s_summary") or {}).get("probability_reach_s") or 0), RIGHT),
                Column(t("Affinité"), nested("affinity", "total"), RIGHT),
                Column(t("Whites"), nested("components", "white_skill"), RIGHT),
                Column(t("Bleues"), nested("components", "blue"), RIGHT),
            ]
        if self.kind == "branch":
            return [
                rank,
                score,
                Column(t("Parent"), nested("card_name")),
                Column(t("Grand-parent 1"), nested("grandparent_1")),
                Column(t("Grand-parent 2"), nested("grandparent_2")),
                Column(t("Distance"), lambda row: distance_status(row, self.context.language)),
                Column("P(S) %", lambda row: 100 * float((row.get("distance_s_summary") or {}).get("probability_reach_s") or 0), RIGHT),
                Column(t("Whites"), nested("components", "white_skill"), RIGHT),
            ]
        return [
            rank,
            score,
            Column(t("Candidat"), nested("card_name")),
            Column(t("ID entraînement"), nested("trained_chara_id"), RIGHT),
            Column(t("Contribution affinité"), nested("affinity_raw"), RIGHT),
            Column(t("G1"), nested("g1_count"), RIGHT),
            Column(t("Whites"), nested("components", "white_skill"), RIGHT),
            Column(t("Bleues"), nested("components", "blue"), RIGHT),
            Column(t("Roses"), nested("components", "pink"), RIGHT),
        ]

    def _configure_header(self) -> None:
        header = self.table.horizontalHeader()
        for index in range(self.model.columnCount()):
            header.setSectionResizeMode(index, QHeaderView.ResizeMode.ResizeToContents)
        if self.kind == "pair":
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        elif self.kind == "branch":
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        else:
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)

    def set_rows(
        self,
        rows: list[dict[str, Any]],
        profile: dict[str, Any] | None = None,
        *,
        lineage_root: dict[str, Any] | None = None,
    ) -> None:
        self.profile = dict(profile or {})
        self.lineage_root = (
            dict(lineage_root) if isinstance(lineage_root, dict) else None
        )
        ranked = []
        for index, row in enumerate(rows, 1):
            copy = dict(row)
            copy["_rank"] = index
            ranked.append(copy)
        self.model.set_rows(ranked)
        sort_column = self.table.horizontalHeader().sortIndicatorSection()
        if sort_column >= 0:
            self.model.sort(
                sort_column, self.table.horizontalHeader().sortIndicatorOrder()
            )
        self.retranslate()
        if ranked:
            self.table.selectRow(0)
        else:
            self.detail.setHtml(result_detail_html(None, self.kind, self.context.language, self.profile))
        self._update_lineage_button()

    def selected_row(self) -> dict[str, Any] | None:
        indexes = self.table.selectionModel().selectedRows()
        return self.model.row(indexes[0].row()) if indexes else None

    def _selection_changed(self, _selected: QItemSelection, _deselected: QItemSelection) -> None:
        self.detail.setHtml(
            result_detail_html(
                self.selected_row(), self.kind, self.context.language, self.profile
            )
        )
        self._update_lineage_button()

    def _model_reordered(self, *_args: object) -> None:
        self.detail.setHtml(
            result_detail_html(
                self.selected_row(), self.kind, self.context.language, self.profile
            )
        )
        self._update_lineage_button()

    def _double_clicked(self, index) -> None:
        if index.isValid():
            self.open_lineage()

    def _update_lineage_button(self) -> None:
        self.lineage_button.setEnabled(
            self.selected_row() is not None and self.lineage_root is not None
        )

    def open_lineage(self) -> None:
        row = self.selected_row()
        if row is None or self.lineage_root is None:
            return
        details = result_detail_html(row, self.kind, self.context.language, self.profile)
        LineageDialog(
            self.context,
            self.lineage_root,
            row,
            mode=self.kind,
            details_html=details,
            parent=self,
        ).exec()

    def retranslate(self) -> None:
        t = self.context.t
        selected = self.selected_row()
        selected_rank = selected.get("_rank") if selected else None
        names = {
            "pair": t("paires finales"),
            "branch": t("lignées candidates"),
            "future": t("futurs grands-parents"),
        }
        self.summary.setText(
            t("{count} {name} · clique sur un en-tête pour trier")
            .replace("{count}", str(self.model.rowCount()))
            .replace("{name}", names[self.kind])
        )
        self.lineage_button.setText(t("Voir la lignée"))
        self.model.set_columns(self._columns())
        self._configure_header()
        if selected_rank is not None:
            for index in range(self.model.rowCount()):
                row = self.model.row(index)
                if row and row.get("_rank") == selected_rank:
                    self.table.selectRow(index)
                    break
        self.detail.setHtml(
            result_detail_html(
                self.selected_row(), self.kind, self.context.language, self.profile
            )
        )
        self._update_lineage_button()


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
        self.export_button = QPushButton("")
        self.export_button.setEnabled(False)
        self.copy_export_button = QPushButton("")
        self.copy_export_button.setEnabled(False)
        self.copy_button = QPushButton("")
        self.copy_button.setEnabled(False)
        head.addWidget(self.summary, 1)
        head.addWidget(self.lineage_button)
        head.addWidget(self.export_button)
        head.addWidget(self.copy_export_button)
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
        self.export_button.clicked.connect(self.export_selected_pair)
        self.copy_export_button.clicked.connect(self.copy_selected_pair_export)
        self.context.language_changed.connect(self._language_changed)
        self.retranslate()

    def _language_changed(self, _language: str) -> None:
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
        self._update_export_button()

    def _double_clicked(self, index) -> None:
        if index.isValid() and "Friend ID" in str(self.model.headerData(index.column(), Qt.Orientation.Horizontal)):
            self.copy_friend_id()
        elif index.isValid():
            self.open_lineage()

    def _update_lineage_button(self) -> None:
        self.lineage_button.setEnabled(
            self.selected_row() is not None and self.lineage_root is not None
        )

    def _update_export_button(self) -> None:
        enabled = (
            self.mode == "parent"
            and self.selected_row() is not None
            and self.ace is not None
        )
        self.export_button.setEnabled(enabled)
        self.copy_export_button.setEnabled(enabled)

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

    def _selected_export_pair(
        self,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None:
        row = self.selected_row()
        if self.mode != "parent" or row is None or self.ace is None:
            return None
        parent_1 = row.get("fixed_parent")
        parent_2 = row.get("candidate")
        if not isinstance(parent_1, dict) or not isinstance(parent_2, dict):
            QMessageBox.warning(
                self,
                self.context.t("Erreur d’export"),
                self.context.t("Sélectionne d'abord une paire à exporter."),
            )
            return None
        return self.ace, parent_1, parent_2

    def export_selected_pair(self) -> None:
        selected = self._selected_export_pair()
        if selected is None:
            return
        ace, parent_1, parent_2 = selected
        ace_id = _integer(ace.get("card_id"))
        p1_id = _integer(parent_1.get("card_id"))
        p2_id = _integer(parent_2.get("card_id"))
        suggested = (
            Path(self.context.output_dir).expanduser()
            / f"uma_moe_lineage_{ace_id}_{p1_id}_{p2_id}.json"
        )
        filename, _ = QFileDialog.getSaveFileName(
            self,
            self.context.t("Exporter la paire vers uma.moe Lineage Planner"),
            str(suggested),
            "JSON (*.json)",
        )
        if not filename:
            return
        try:
            path = write_lineage_planner_export(
                filename,
                ace,
                parent_1,
                parent_2,
                master_path=self.context.master_path,
                veterans_json_path=self.context.veterans_json_path,
            )
        except (OSError, ValueError, LineagePlannerError) as exc:
            QMessageBox.critical(
                self,
                self.context.t("Erreur d’export"),
                self.context.t(str(exc)),
            )
            return
        QMessageBox.information(
            self,
            self.context.t("Export terminé"),
            self.context.t(
                "Fichier créé : {path}\n\nDans Lineage Planner, ouvre Save / Load puis importe ce JSON."
            ).replace("{path}", str(path)),
        )

    def copy_selected_pair_export(self) -> None:
        selected = self._selected_export_pair()
        if selected is None:
            return
        ace, parent_1, parent_2 = selected
        try:
            payload = build_lineage_planner_export(
                ace,
                parent_1,
                parent_2,
                master_path=self.context.master_path,
                veterans_json_path=self.context.veterans_json_path,
            )
        except (OSError, ValueError, LineagePlannerError) as exc:
            QMessageBox.critical(
                self,
                self.context.t("Erreur d’export"),
                self.context.t(str(exc)),
            )
            return
        QApplication.clipboard().setText(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        )
        self.copy_export_button.setText(self.context.t("Export copié !"))
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
        self.export_button.setText(t("Enregistrer JSON…"))
        self.export_button.setToolTip(
            t("Enregistrer la paire sélectionnée pour uma.moe Lineage Planner.")
        )
        self.copy_export_button.setText(t("Copier JSON"))
        self.copy_export_button.setToolTip(
            t("Copier l’export de la paire sélectionnée dans le presse-papiers.")
        )
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
        self._update_export_button()
