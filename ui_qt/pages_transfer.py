from __future__ import annotations

import json
from functools import partial
from pathlib import Path
from typing import Any

from PySide6.QtCore import QItemSelection, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableView,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ui_qt.components import PageHeader, StatusCard, muted_label
from ui_qt.context import AppContext
from ui_qt.core import (
    TransferRequest,
    active_course_overrides_path,
    open_path,
    run_transfer_analysis,
)
from ui_qt.models import Column, ResultTableModel, nested
from ui_qt.presentation import transfer_detail_html


RIGHT = Qt.AlignmentFlag.AlignRight


class TransferPage(QWidget):
    task_requested = Signal(object, str, object)

    def __init__(self, context: AppContext, parent=None):
        super().__init__(parent)
        self.context = context
        self._busy = False
        self._records: list[dict[str, Any]] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(12)
        self.header = PageHeader("", "")
        root.addWidget(self.header)

        safety = QFrame()
        safety.setObjectName("panel")
        safety_layout = QHBoxLayout(safety)
        safety_layout.setContentsMargins(16, 12, 16, 12)
        self.safety_text = muted_label("")
        self.run_button = QPushButton("")
        self.run_button.setObjectName("primary")
        self.load_button = QPushButton("")
        self.open_button = QPushButton("")
        safety_layout.addWidget(self.safety_text, 1)
        safety_layout.addWidget(self.run_button)
        safety_layout.addWidget(self.load_button)
        safety_layout.addWidget(self.open_button)
        root.addWidget(safety)

        cards = QGridLayout()
        cards.setHorizontalSpacing(10)
        self.safe_card = StatusCard("", "0", "")
        self.review_card = StatusCard("", "0", "")
        self.likely_card = StatusCard("", "0", "")
        self.keep_card = StatusCard("", "0", "")
        for index, card in enumerate((self.safe_card, self.review_card, self.likely_card, self.keep_card)):
            cards.addWidget(card, 0, index)
            cards.setColumnStretch(index, 1)
        root.addLayout(cards)

        filters = QFrame()
        filters.setObjectName("panel")
        filter_layout = QHBoxLayout(filters)
        filter_layout.setContentsMargins(12, 8, 12, 8)
        self.filter_label = QLabel("")
        self.status_combo = QComboBox()
        self.search = QLineEdit()
        self.search.setClearButtonEnabled(True)
        self.count_label = muted_label("")
        filter_layout.addWidget(self.filter_label)
        filter_layout.addWidget(self.status_combo)
        filter_layout.addWidget(self.search, 1)
        filter_layout.addWidget(self.count_label)
        root.addWidget(filters)

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
        splitter.addWidget(self.table)
        splitter.addWidget(self.detail)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([780, 430])
        root.addWidget(splitter, 1)

        self.run_button.clicked.connect(self.start_analysis)
        self.load_button.clicked.connect(lambda: self.load_latest(show_errors=True))
        self.open_button.clicked.connect(self.open_output)
        self.status_combo.currentIndexChanged.connect(self.apply_filters)
        self.search.textChanged.connect(self.apply_filters)
        self.table.selectionModel().selectionChanged.connect(self._selection_changed)
        self.context.language_changed.connect(lambda _language: self.retranslate())
        self.retranslate()
        self.load_latest(show_errors=False)

    def _columns(self) -> list[Column]:
        t = self.context.t
        labels = {
            "safe_transfer": t("Transfert sûr"),
            "review": t("À examiner"),
            "likely_keep": t("Probablement conserver"),
            "keep": t("Conserver"),
        }
        return [
            Column(t("Verdict"), lambda row: labels.get(str(row.get("status")), row.get("status") or "—")),
            Column(t("Vétéran"), lambda row: row.get("card_name") or row.get("uma_name") or "—"),
            Column(t("ID"), nested("trained_chara_id"), RIGHT),
            Column(t("Score Uma"), nested("rank_score"), RIGHT),
            Column(t("Copies"), nested("same_card_copy_count"), RIGHT),
            Column(t("Meilleur parent"), nested("best_parent_score"), RIGHT),
            Column(t("Rang parent"), lambda row: f"top {float(row.get('best_parent_percentile') or 100):.1f}%", RIGHT),
            Column(t("Meilleur GP"), nested("best_grandparent_score"), RIGHT),
            Column(t("Rang GP"), lambda row: f"top {float(row.get('best_grandparent_percentile') or 100):.1f}%", RIGHT),
            Column(t("Remplaçant"), nested("dominated_by", "card_name")),
            Column(t("Avance moy."), lambda row: (row.get("dominated_by") or {}).get("mean_score_lead", "—"), RIGHT),
            Column(t("Référencé par"), nested("referenced_by_local_veterans"), RIGHT),
        ]

    def _configure_header(self) -> None:
        header = self.table.horizontalHeader()
        header.setMinimumSectionSize(62)
        for index in range(self.model.columnCount()):
            header.setSectionResizeMode(index, QHeaderView.ResizeMode.ResizeToContents)
        for index in (1, 9):
            if index < self.model.columnCount():
                header.setSectionResizeMode(index, QHeaderView.ResizeMode.Stretch)

    def retranslate(self) -> None:
        t = self.context.t
        self.header.set_text(
            t("Transfer Helper"),
            t("Identifie les copies redondantes sans jamais modifier l’export source ni prendre une décision à ta place."),
        )
        self.safety_text.setText(
            t("« Transfert sûr » exige un remplaçant du même costume et de la même unique, non inférieur dans chaque niche viable et sans perte de patrimoine Spark protégé. Les autres verdicts restent des diagnostics manuels.")
        )
        self.run_button.setText(t("Analyser les vétérans locaux"))
        self.load_button.setText(t("Charger le dernier rapport"))
        self.open_button.setText(t("Ouvrir la sortie"))
        self.filter_label.setText(t("Afficher"))
        self.search.setPlaceholderText(t("Rechercher un nom, un ID ou un remplaçant…"))
        selected = self.status_combo.currentData()
        self.status_combo.blockSignals(True)
        self.status_combo.clear()
        for label, value in (
            ("Tous les verdicts", None),
            ("Transfert sûr", "safe_transfer"),
            ("À examiner", "review"),
            ("Probablement conserver", "likely_keep"),
            ("Conserver", "keep"),
        ):
            self.status_combo.addItem(t(label), value)
        index = self.status_combo.findData(selected)
        self.status_combo.setCurrentIndex(index if index >= 0 else 0)
        self.status_combo.blockSignals(False)
        self._refresh_cards()
        self.apply_filters()

    def _refresh_cards(self) -> None:
        t = self.context.t
        counts = {key: 0 for key in ("safe_transfer", "review", "likely_keep", "keep")}
        for record in self._records:
            key = str(record.get("status") or "")
            if key in counts:
                counts[key] += 1
        self.safe_card.set_content(t("Transfert sûr"), str(counts["safe_transfer"]), t("Remplaçant strict confirmé"), "ok")
        self.review_card.set_content(t("À examiner"), str(counts["review"]), t("Rôle incertain ou Spark à vérifier"), "warning")
        self.likely_card.set_content(t("Probablement conserver"), str(counts["likely_keep"]), t("Niche ou patrimoine Spark fort"), "neutral")
        self.keep_card.set_content(t("Conserver"), str(counts["keep"]), t("Valeur compétitive"), "info")

    def set_records(self, records: list[dict[str, Any]]) -> None:
        self._records = list(records)
        self._refresh_cards()
        self.apply_filters()

    def apply_filters(self, *_args: object) -> None:
        status = self.status_combo.currentData()
        query = self.search.text().strip().casefold()
        rows = []
        for record in self._records:
            if status is not None and record.get("status") != status:
                continue
            replacement = record.get("dominated_by") or {}
            haystack = " ".join(
                str(value or "")
                for value in (
                    record.get("card_name"), record.get("uma_name"),
                    record.get("trained_chara_id"), replacement.get("card_name"),
                    replacement.get("trained_chara_id"),
                )
            ).casefold()
            if query and query not in haystack:
                continue
            rows.append(record)
        selected = self.selected_row()
        selected_id = selected.get("trained_chara_id") if selected else None
        self.model.set_columns(self._columns())
        self.model.set_rows(rows)
        self._configure_header()
        self.count_label.setText(
            self.context.t("{shown} / {total} vétérans")
            .replace("{shown}", str(len(rows)))
            .replace("{total}", str(len(self._records)))
        )
        target = -1
        if selected_id is not None:
            for index, row in enumerate(rows):
                if row.get("trained_chara_id") == selected_id:
                    target = index
                    break
        if target < 0 and rows:
            target = 0
        if target >= 0:
            self.table.selectRow(target)
        else:
            self.detail.setHtml(transfer_detail_html(None, self.context.language))

    def selected_row(self) -> dict[str, Any] | None:
        indexes = self.table.selectionModel().selectedRows()
        return self.model.row(indexes[0].row()) if indexes else None

    def _selection_changed(self, _selected: QItemSelection, _deselected: QItemSelection) -> None:
        self.detail.setHtml(transfer_detail_html(self.selected_row(), self.context.language))

    def start_analysis(self) -> None:
        priority_text = self.context.store.get("skill_priorities_path")
        request = TransferRequest(
            master_path=Path(self.context.master_path).expanduser(),
            veterans_json_path=Path(self.context.veterans_json_path).expanduser(),
            output_dir=Path(self.context.output_dir).expanduser(),
            course_overrides_path=active_course_overrides_path(self.context.course_overrides_path),
            use_custom_scoring=self.context.store.get("use_custom_scoring", "0") in {"1", "true", "True"},
            skill_priorities_path=(Path(priority_text).expanduser() if priority_text else None),
        )
        self.task_requested.emit(
            partial(run_transfer_analysis, request),
            self.context.t("Analyse Transfer Helper…"),
            self._analysis_done,
        )

    def _analysis_done(self, result: object) -> None:
        self.set_records(list(getattr(result, "records", ()) or ()))

    def load_latest(self, *, show_errors: bool = True) -> None:
        path = Path(self.context.output_dir).expanduser() / "transfer_helper_report.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            records = payload.get("records") if isinstance(payload, dict) else None
            if not isinstance(records, list):
                raise ValueError("Le rapport Transfer Helper ne contient pas de liste de résultats.")
            self.set_records([row for row in records if isinstance(row, dict)])
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            if show_errors:
                QMessageBox.information(self, self.context.t("Dernier rapport"), self.context.t(str(exc)))

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.run_button.setEnabled(not busy)
        self.load_button.setEnabled(not busy)

    def open_output(self) -> None:
        output = Path(self.context.output_dir).expanduser()
        try:
            output.mkdir(parents=True, exist_ok=True)
            open_path(output)
        except OSError as exc:
            QMessageBox.critical(self, self.context.t("Erreur"), str(exc))
