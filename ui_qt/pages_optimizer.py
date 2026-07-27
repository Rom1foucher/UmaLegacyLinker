from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Any

from PySide6.QtCore import QItemSelection, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableView,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from lineage_planner import LineagePlannerError, write_lineage_planner_export
from parent_optimizer import OptimizerError, load_ace_options, load_track_options
from ui_qt.components import (
    PageHeader,
    SearchableComboBox,
    muted_label,
    section_label,
    sync_scroll_pane_height,
)
from ui_qt.context import AppContext, LineageContextState
from ui_qt.core import (
    OptimizationRequest,
    latest_rankings_path,
    load_rankings_payload,
    open_path,
    run_optimization,
)
from ui_qt.lineage_settings import LineageRaceEditor
from ui_qt.models import Column, ResultTableModel, nested
from ui_qt.lineage_view import LineageDialog
from ui_qt.presentation import distance_status, profile_summary, result_detail_html


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


class OptimizerPage(QWidget):
    task_requested = Signal(object, str, object)

    def __init__(self, context: AppContext, parent=None):
        super().__init__(parent)
        self.context = context
        self._busy = False
        self._ace_options: list[Any] = []
        self._card_to_chara: dict[int, int] = {}
        self._syncing_lineage = False
        self._last_ace: dict[str, Any] | None = None
        self._last_future_parent: dict[str, Any] | None = None
        self._last_profile: dict[str, Any] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(12)
        self.header = PageHeader("", "")
        root.addWidget(self.header)

        self.context_strip = QFrame()
        self.context_strip.setObjectName("panel")
        context_layout = QHBoxLayout(self.context_strip)
        context_layout.setContentsMargins(13, 8, 13, 8)
        self.context_label = QLabel("")
        self.context_label.setObjectName("muted")
        self.context_label.setWordWrap(True)
        self.refresh_options_button = QPushButton("")
        context_layout.addWidget(self.context_label, 1)
        context_layout.addWidget(self.refresh_options_button)
        root.addWidget(self.context_strip)

        vertical = QSplitter(Qt.Orientation.Vertical)
        vertical.setChildrenCollapsible(False)
        config_scroll = QScrollArea()
        config_scroll.setWidgetResizable(True)
        config_scroll.setFrameShape(QFrame.Shape.NoFrame)
        config_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        config_widget = QWidget()
        config_layout = QVBoxLayout(config_widget)
        config_layout.setContentsMargins(0, 0, 4, 4)
        config_layout.setSpacing(10)

        form_panel = QFrame()
        form_panel.setObjectName("panel")
        form = QGridLayout(form_panel)
        form.setContentsMargins(17, 15, 17, 15)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(9)

        self.ace_label = QLabel("")
        self.ace_combo = self._search_combo()
        self.parent_label = QLabel("")
        self.parent_combo = self._search_combo()
        self.top_n_label = QLabel("")
        self.top_n_spin = QSpinBox()
        self.top_n_spin.setRange(5, 200)
        self.top_n_spin.setValue(self.context.lineage_state().top_n)

        form.addWidget(self.ace_label, 0, 0)
        form.addWidget(self.ace_combo, 1, 0, 1, 2)
        form.addWidget(self.parent_label, 0, 2)
        form.addWidget(self.parent_combo, 1, 2, 1, 2)
        form.addWidget(self.top_n_label, 2, 0)
        form.addWidget(self.top_n_spin, 3, 0)
        form.setColumnStretch(0, 1)
        form.setColumnStretch(1, 1)
        form.setColumnStretch(2, 1)
        form.setColumnStretch(3, 1)
        config_layout.addWidget(form_panel)

        self.race_editor = LineageRaceEditor(self.context)
        # Public aliases keep the page API stable for layout audits and any
        # downstream integrations while the controls themselves are shared.
        self.surface_combo = self.race_editor.surface_combo
        self.distance_combo = self.race_editor.distance_combo
        self.style_combo = self.race_editor.style_combo
        self.course_combo = self.race_editor.course_combo
        self.course_picker = self.race_editor.course_picker
        self.track_combo = self.race_editor.track_combo
        self.rotation_combo = self.race_editor.rotation_combo
        self.season_combo = self.race_editor.season_combo
        self.weather_combo = self.race_editor.weather_combo
        self.ground_combo = self.race_editor.ground_combo
        self.custom_scoring = self.race_editor.custom_scoring
        self.priority_picker = self.race_editor.priority_picker
        self.advanced = self.race_editor.advanced
        config_layout.addWidget(self.race_editor)

        actions = QHBoxLayout()
        self.run_button = QPushButton("")
        self.run_button.setObjectName("primary")
        self.load_button = QPushButton("")
        self.open_button = QPushButton("")
        actions.addWidget(self.run_button)
        actions.addWidget(self.load_button)
        actions.addWidget(self.open_button)
        actions.addStretch(1)
        config_layout.addLayout(actions)
        config_layout.addStretch(1)
        config_scroll.setWidget(config_widget)
        # Le splitter ignore sizeHint() une fois l'utilisateur en train de
        # glisser la poignée : sans plancher explicite, il autorise des
        # tailles où le fond arrondi des panneaux ("panel") et leur contenu
        # se déforment visiblement (coins écrasés, champs qui se chevauchent).
        # Pas de plancher artificiel ici : setChildrenCollapsible(False)
        # empêche déjà d'atteindre zéro pixel, et le minimum naturel de la
        # QScrollArea suffit à laisser l'utilisateur réduire le formulaire
        # jusqu'à ne plus voir que la barre de contexte au-dessus.

        results_widget = QWidget()
        results_widget.setMinimumHeight(280)
        results_layout = QVBoxLayout(results_widget)
        results_layout.setContentsMargins(0, 0, 0, 0)
        results_head = QHBoxLayout()
        self.results_title = section_label("")
        self.results_context = muted_label("")
        self.export_button = QPushButton("")
        self.export_button.setEnabled(False)
        results_head.addWidget(self.results_title)
        results_head.addWidget(self.results_context, 1)
        results_head.addWidget(self.export_button)
        results_layout.addLayout(results_head)
        self.tabs = QTabWidget()
        self.pair_results = ResultPane("pair", context)
        self.branch_results = ResultPane("branch", context)
        self.future_results = ResultPane("future", context)
        self.tabs.addTab(self.pair_results, "")
        self.tabs.addTab(self.branch_results, "")
        self.tabs.addTab(self.future_results, "")
        results_layout.addWidget(self.tabs, 1)

        vertical.addWidget(config_scroll)
        vertical.addWidget(results_widget)
        vertical.setStretchFactor(0, 0)
        vertical.setStretchFactor(1, 1)
        self._config_scroll = config_scroll
        self._vertical_splitter = vertical
        QTimer.singleShot(0, self._sync_config_pane_height)
        root.addWidget(vertical, 1)

        self.refresh_options_button.clicked.connect(self.refresh_options)
        self.run_button.clicked.connect(self.start_optimization)
        self.load_button.clicked.connect(lambda: self.load_latest(show_errors=True))
        self.open_button.clicked.connect(self.open_output)
        self.export_button.clicked.connect(self.export_selected_pair)
        self.ace_combo.currentIndexChanged.connect(self._ace_changed)
        self.parent_combo.currentIndexChanged.connect(self._lineage_selection_changed)
        self.top_n_spin.valueChanged.connect(self._lineage_selection_changed)
        self.race_editor.changed.connect(self.sync_context)
        self.race_editor.layout_changed.connect(
            lambda: QTimer.singleShot(0, self._sync_config_pane_height)
        )
        self.context.lineage_changed.connect(self._sync_lineage_context)
        self.context.configuration_changed.connect(self.sync_context)
        self.context.language_changed.connect(lambda _language: self.retranslate())

        self.retranslate()
        self._sync_lineage_context()
        QTimer.singleShot(0, lambda: self.refresh_options(show_errors=False))
        QTimer.singleShot(50, lambda: self.load_latest(show_errors=False))

    @staticmethod
    def _search_combo() -> SearchableComboBox:
        return SearchableComboBox()

    def retranslate(self) -> None:
        t = self.context.t
        self.header.set_text(
            t("Optimisation de lignée"),
            t("Choisis l’objectif, puis compare les paires, les lignées et les futurs grands-parents dans le même écran."),
        )
        self.refresh_options_button.setText(t("Actualiser depuis le MDB"))
        self.ace_label.setText(t("Ace visé"))
        self.parent_label.setText(t("Parent à produire"))
        self.top_n_label.setText(t("Résultats conservés"))
        self.run_button.setText(t("Calculer les meilleures lignées"))
        self.load_button.setText(t("Charger le dernier résultat"))
        self.open_button.setText(t("Ouvrir la sortie"))
        self.results_title.setText(t("Résultats intégrés"))
        self.export_button.setText(t("Exporter la paire vers Lineage Planner…"))
        self.tabs.setTabText(0, t("Paires finales"))
        self.tabs.setTabText(1, t("Lignées candidates"))
        self.tabs.setTabText(2, t("Futurs grands-parents"))
        self.pair_results.retranslate()
        self.branch_results.retranslate()
        self.future_results.retranslate()
        self.sync_context()

    def sync_context(self) -> None:
        t = self.context.t
        master = Path(self.context.master_path).expanduser()
        data = Path(self.context.veterans_json_path).expanduser()
        self.context_label.setText(
            t("Contexte actif")
            + f" · MDB: {master.name if master.is_file() else t('manquant')}"
            + f" · {t('Collection locale')}: {data.name if data.is_file() else t('manquant')}"
            + f" · {profile_summary(self._current_profile(), self.context.language)}"
            + f" · {t('Preset de course')}: {self.race_editor.current_course_label()}"
        )
        QTimer.singleShot(0, self._sync_config_pane_height)

    def _current_profile(self) -> dict[str, Any]:
        return self.race_editor.current_profile()

    def _sync_config_pane_height(self, *_args: object) -> None:
        sync_scroll_pane_height(
            getattr(self, "_vertical_splitter", None),
            getattr(self, "_config_scroll", None),
        )

    def refresh_options(self, _checked: bool = False, *, show_errors: bool = True) -> None:
        master = Path(self.context.master_path).expanduser()
        try:
            if not master.is_file():
                raise OptimizerError(
                    "Sélectionne un master.mdb valide avant d'actualiser les Ace."
                )
            options = load_ace_options(master)
            tracks = load_track_options(master)
        except Exception as exc:
            if show_errors:
                QMessageBox.warning(self, self.context.t("Configuration incomplète"), self.context.t(str(exc)))
            return

        state = self.context.lineage_state()
        self._ace_options = list(options)
        self._card_to_chara = {option.card_id: option.chara_id for option in options}
        self._syncing_lineage = True
        try:
            for combo, selected in (
                (self.ace_combo, state.ace_card_id),
                (self.parent_combo, state.future_parent_card_id),
            ):
                combo.blockSignals(True)
                combo.clear()
                for option in options:
                    combo.addItem(option.display_name, option.card_id)
                index = combo.findData(selected)
                combo.setCurrentIndex(
                    index
                    if index >= 0 and combo.count()
                    else (0 if combo.count() else -1)
                )
                combo.blockSignals(False)
            self._ensure_distinct_parent()
        finally:
            self._syncing_lineage = False

        self.race_editor.set_track_options(
            sorted(tracks, key=lambda item: item.name.casefold())
        )
        self._lineage_selection_changed()
        self.sync_context()

    def _ensure_distinct_parent(self) -> None:
        ace_id = self.ace_combo.currentData()
        parent_id = self.parent_combo.currentData()
        ace_chara = self._card_to_chara.get(int(ace_id or 0))
        parent_chara = self._card_to_chara.get(int(parent_id or 0))
        if ace_chara is None or parent_chara != ace_chara:
            return
        for index in range(self.parent_combo.count()):
            candidate = _integer(self.parent_combo.itemData(index))
            if self._card_to_chara.get(candidate) != ace_chara:
                self.parent_combo.setCurrentIndex(index)
                break

    def _ace_changed(self, _index: int) -> None:
        if self._syncing_lineage:
            return
        self._ensure_distinct_parent()
        self._lineage_selection_changed()

    def _lineage_selection_changed(self, *_args: object) -> None:
        if self._syncing_lineage:
            return
        changes: dict[str, object] = {"top_n": self.top_n_spin.value()}
        ace_id = _integer(self.ace_combo.currentData())
        parent_id = _integer(self.parent_combo.currentData())
        if ace_id:
            changes["ace_card_id"] = ace_id
        if parent_id:
            changes["future_parent_card_id"] = parent_id
        self.context.update_lineage(**changes)

    def _sync_lineage_context(
        self, _state: LineageContextState | None = None
    ) -> None:
        lineage = self.context.lineage_state()
        corrected_parent_id = 0
        self._syncing_lineage = True
        try:
            for combo, value in (
                (self.ace_combo, lineage.ace_card_id),
                (self.parent_combo, lineage.future_parent_card_id),
            ):
                index = combo.findData(value)
                if index >= 0 and combo.currentIndex() != index:
                    combo.blockSignals(True)
                    combo.setCurrentIndex(index)
                    combo.blockSignals(False)
            self._ensure_distinct_parent()
            corrected_parent_id = _integer(self.parent_combo.currentData())
            self.top_n_spin.blockSignals(True)
            self.top_n_spin.setValue(lineage.top_n)
            self.top_n_spin.blockSignals(False)
        finally:
            self._syncing_lineage = False
        if (
            corrected_parent_id
            and corrected_parent_id != lineage.future_parent_card_id
        ):
            self.context.update_lineage(
                future_parent_card_id=corrected_parent_id
            )
        else:
            self.sync_context()

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.run_button.setEnabled(not busy)
        self.load_button.setEnabled(not busy)
        self.refresh_options_button.setEnabled(not busy)

    def start_optimization(self) -> None:
        self.ace_combo.resolve_current_text()
        self.parent_combo.resolve_current_text()
        self.course_combo.resolve_current_text()
        self.track_combo.resolve_current_text()
        ace_id = _integer(self.ace_combo.currentData())
        parent_id = _integer(self.parent_combo.currentData())
        if ace_id <= 0 or parent_id <= 0:
            QMessageBox.warning(
                self,
                self.context.t("Configuration incomplète"),
                self.context.t("Sélectionne l’Ace et le parent à produire."),
            )
            return
        if self._card_to_chara.get(ace_id) == self._card_to_chara.get(parent_id):
            QMessageBox.warning(
                self,
                self.context.t("Configuration incomplète"),
                self.context.t("L'Ace et le parent à produire doivent être deux personnages différents."),
            )
            return

        profile = self.race_editor.current_profile()
        request = OptimizationRequest(
            master_path=Path(self.context.master_path).expanduser(),
            veterans_json_path=Path(self.context.veterans_json_path).expanduser(),
            output_dir=Path(self.context.output_dir).expanduser(),
            ace_card_id=ace_id,
            future_parent_card_id=parent_id,
            surface=profile["surface"],
            distance=profile["distance"],
            style=profile["style"],
            course_overrides_path=self.race_editor.course_overrides_path(),
            course_key=self.race_editor.current_course_key(),
            course_conditions=self.race_editor.selected_conditions(),
            top_n=self.top_n_spin.value(),
            use_custom_scoring=self.custom_scoring.isChecked(),
            skill_priorities_path=self.race_editor.skill_priorities_path(),
        )
        self.context.update_lineage(
            ace_card_id=ace_id,
            future_parent_card_id=parent_id,
            top_n=request.top_n,
        )
        operation = partial(run_optimization, request)
        self.task_requested.emit(
            operation,
            self.context.t("Optimisation de la lignée…"),
            self._optimization_done,
        )

    def _display_results(
        self,
        *,
        pairs: list[dict[str, Any]],
        branches: list[dict[str, Any]],
        future: list[dict[str, Any]],
        ace: dict[str, Any] | None,
        future_parent: dict[str, Any] | None,
        profile: dict[str, Any] | None,
    ) -> None:
        self._last_ace = ace
        self._last_future_parent = future_parent
        self._last_profile = dict(profile or {})
        self.pair_results.set_rows(
            pairs, self._last_profile, lineage_root=self._last_ace
        )
        self.branch_results.set_rows(
            branches, self._last_profile, lineage_root=self._last_ace
        )
        self.future_results.set_rows(
            future, self._last_profile, lineage_root=self._last_future_parent
        )
        self.results_context.setText(profile_summary(self._last_profile, self.context.language))
        self.export_button.setEnabled(bool(pairs and ace))
        self.tabs.setCurrentIndex(0)

    def _optimization_done(self, result: object) -> None:
        self._display_results(
            pairs=list(getattr(result, "top_parent_pairs", ()) or ()),
            branches=list(getattr(result, "top_parent_candidates", ()) or ()),
            future=list(getattr(result, "top_future_grandparents", ()) or ()),
            ace=getattr(result, "ace", None),
            future_parent=getattr(result, "future_parent", None),
            profile=getattr(result, "profile", None),
        )

    def load_latest(self, *, show_errors: bool = True) -> None:
        path = latest_rankings_path(self.context.output_dir)
        try:
            payload = load_rankings_payload(path)
        except Exception as exc:
            if show_errors:
                QMessageBox.information(self, self.context.t("Dernier résultat"), self.context.t(str(exc)))
            return
        self._display_results(
            pairs=list(payload.get("top_parent_pairs") or []),
            branches=list(payload.get("top_parent_candidates") or []),
            future=list(payload.get("top_future_grandparents") or []),
            ace=payload.get("ace") if isinstance(payload.get("ace"), dict) else None,
            future_parent=(
                payload.get("future_parent")
                if isinstance(payload.get("future_parent"), dict)
                else None
            ),
            profile=payload.get("profile") if isinstance(payload.get("profile"), dict) else {},
        )

    def export_selected_pair(self) -> None:
        row = self.pair_results.selected_row()
        if not row or not self._last_ace:
            QMessageBox.information(
                self,
                self.context.t("Export"),
                self.context.t("Sélectionne d'abord une paire à exporter."),
            )
            return
        parent_1 = row.get("parent_1") or {}
        parent_2 = row.get("parent_2") or {}
        ace_id = _integer(self._last_ace.get("card_id"))
        p1_id = _integer(parent_1.get("card_id"))
        p2_id = _integer(parent_2.get("card_id"))
        suggested = Path(self.context.output_dir).expanduser() / f"uma_moe_lineage_{ace_id}_{p1_id}_{p2_id}.json"
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
                self._last_ace,
                parent_1,
                parent_2,
                master_path=self.context.master_path,
                veterans_json_path=self.context.veterans_json_path,
            )
        except (OSError, ValueError, LineagePlannerError) as exc:
            QMessageBox.critical(self, self.context.t("Erreur d’export"), self.context.t(str(exc)))
            return
        QMessageBox.information(
            self,
            self.context.t("Export terminé"),
            self.context.t("Fichier créé : {path}\n\nDans Lineage Planner, ouvre Save / Load puis importe ce JSON.").replace("{path}", str(path)),
        )

    def open_output(self) -> None:
        output = Path(self.context.output_dir).expanduser()
        try:
            output.mkdir(parents=True, exist_ok=True)
            open_path(output)
        except OSError as exc:
            QMessageBox.critical(self, self.context.t("Erreur"), str(exc))
