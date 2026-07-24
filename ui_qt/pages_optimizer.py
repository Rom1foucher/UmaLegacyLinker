from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Any

from PySide6.QtCore import QItemSelection, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
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

from course_presets import (
    course_preset_conditions,
    course_preset_label,
    load_course_preset_payload,
    ordered_course_presets,
    racecourse_names_match,
)
from i18n import profile_values
from lineage_planner import LineagePlannerError, write_lineage_planner_export
from parent_optimizer import OptimizerError, load_ace_options, load_track_options
from ui_qt.components import (
    CollapsibleSection,
    PageHeader,
    PathPicker,
    SearchableComboBox,
    muted_label,
    section_label,
)
from ui_qt.context import AppContext
from ui_qt.core import (
    OptimizationRequest,
    active_course_overrides_path,
    latest_rankings_path,
    load_rankings_payload,
    open_path,
    run_optimization,
)
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
        self._course_definitions: dict[str, dict[str, Any]] = {}
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
        self.refresh_options_button = QPushButton("")
        self.refresh_options_button.setFixedWidth(180)
        context_layout.addWidget(self.context_label, 1)
        context_layout.addWidget(self.refresh_options_button)
        root.addWidget(self.context_strip)

        vertical = QSplitter(Qt.Orientation.Vertical)
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
        self.surface_label = QLabel("")
        self.surface_combo = QComboBox()
        self.distance_label = QLabel("")
        self.distance_combo = QComboBox()
        self.style_label = QLabel("")
        self.style_combo = QComboBox()
        self.course_label = QLabel("")
        self.course_combo = SearchableComboBox()
        self.top_n_label = QLabel("")
        self.top_n_spin = QSpinBox()
        self.top_n_spin.setRange(5, 200)
        self.top_n_spin.setValue(
            _integer(self.context.store.get("optimizer_top_n", "30"), 30)
        )

        form.addWidget(self.ace_label, 0, 0)
        form.addWidget(self.ace_combo, 1, 0, 1, 2)
        form.addWidget(self.parent_label, 0, 2)
        form.addWidget(self.parent_combo, 1, 2, 1, 2)
        form.addWidget(self.surface_label, 2, 0)
        form.addWidget(self.surface_combo, 3, 0)
        form.addWidget(self.distance_label, 2, 1)
        form.addWidget(self.distance_combo, 3, 1)
        form.addWidget(self.style_label, 2, 2)
        form.addWidget(self.style_combo, 3, 2)
        form.addWidget(self.course_label, 2, 3)
        form.addWidget(self.course_combo, 3, 3)
        form.addWidget(self.top_n_label, 4, 0)
        form.addWidget(self.top_n_spin, 5, 0)
        form.setColumnStretch(0, 1)
        form.setColumnStretch(1, 1)
        form.setColumnStretch(2, 1)
        form.setColumnStretch(3, 1)
        config_layout.addWidget(form_panel)

        self.advanced = CollapsibleSection("")
        advanced_grid = QGridLayout()
        advanced_grid.setHorizontalSpacing(10)
        advanced_grid.setVerticalSpacing(8)
        self.course_file_label = QLabel("")
        self.course_picker = PathPicker(
            self.context.course_overrides_path,
            title="Sélectionner les overrides de course",
            file_filter="JSON (*.json);;Tous les fichiers (*)",
        )
        self.track_label = QLabel("")
        self.track_combo = SearchableComboBox()
        self.rotation_label = QLabel("")
        self.rotation_combo = QComboBox()
        self.season_label = QLabel("")
        self.season_combo = QComboBox()
        self.weather_label = QLabel("")
        self.weather_combo = QComboBox()
        self.ground_label = QLabel("")
        self.ground_combo = QComboBox()
        self.custom_scoring = QCheckBox("")
        self.custom_scoring.setChecked(
            self.context.store.get("use_custom_scoring", "0") in {"1", "true", "True"}
        )
        self.priority_label = QLabel("")
        self.priority_picker = PathPicker(
            self.context.store.get("skill_priorities_path"),
            title="Choisir un profil de priorités white",
            file_filter="JSON (*.json);;Tous les fichiers (*)",
        )

        advanced_grid.addWidget(self.course_file_label, 0, 0)
        advanced_grid.addWidget(self.course_picker, 1, 0, 1, 4)
        for column, (label, combo) in enumerate(
            (
                (self.track_label, self.track_combo),
                (self.rotation_label, self.rotation_combo),
                (self.season_label, self.season_combo),
                (self.weather_label, self.weather_combo),
            )
        ):
            advanced_grid.addWidget(label, 2, column)
            advanced_grid.addWidget(combo, 3, column)
        advanced_grid.addWidget(self.ground_label, 4, 0)
        advanced_grid.addWidget(self.ground_combo, 5, 0)
        advanced_grid.addWidget(self.custom_scoring, 5, 1, 1, 3)
        advanced_grid.addWidget(self.priority_label, 6, 0)
        advanced_grid.addWidget(self.priority_picker, 7, 0, 1, 4)
        for column in range(4):
            advanced_grid.setColumnStretch(column, 1)
        self.advanced.content_layout.addLayout(advanced_grid)
        config_layout.addWidget(self.advanced)

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
        config_scroll.setWidget(config_widget)

        results_widget = QWidget()
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
        vertical.setSizes([330, 560])
        root.addWidget(vertical, 1)

        self.refresh_options_button.clicked.connect(self.refresh_options)
        self.course_picker.path_changed.connect(self._course_path_changed)
        self.run_button.clicked.connect(self.start_optimization)
        self.load_button.clicked.connect(lambda: self.load_latest(show_errors=True))
        self.open_button.clicked.connect(self.open_output)
        self.export_button.clicked.connect(self.export_selected_pair)
        self.course_combo.currentIndexChanged.connect(self._course_changed)
        self.surface_combo.activated.connect(self._manual_profile_changed)
        self.distance_combo.activated.connect(self._manual_profile_changed)
        self.style_combo.activated.connect(self._manual_profile_changed)
        self.ace_combo.currentIndexChanged.connect(self._ace_changed)
        self.context.configuration_changed.connect(self.sync_context)
        self.context.language_changed.connect(lambda _language: self.retranslate())

        self._populate_profiles()
        self._populate_condition_options()
        self.retranslate()
        QTimer.singleShot(0, lambda: self.refresh_options(show_errors=False))
        QTimer.singleShot(50, lambda: self.load_latest(show_errors=False))

    @staticmethod
    def _search_combo() -> SearchableComboBox:
        return SearchableComboBox()

    def _populate_profiles(self) -> None:
        for combo, kind, fallback in (
            (self.surface_combo, "surface", "turf"),
            (self.distance_combo, "distance", "medium"),
            (self.style_combo, "style", "pace_chaser"),
        ):
            selected = combo.currentData() or self.context.store.get(f"optimizer_{kind}", fallback)
            combo.blockSignals(True)
            combo.clear()
            for code, label in zip(("turf", "dirt") if kind == "surface" else (
                ("sprint", "mile", "medium", "long") if kind == "distance" else
                ("front_runner", "pace_chaser", "late_surger", "end_closer")
            ), profile_values(kind, self.context.language)):
                combo.addItem(label, code)
            index = combo.findData(selected)
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.blockSignals(False)

    def _add_condition_items(self, combo: QComboBox, values: list[tuple[str, object]]) -> None:
        combo.clear()
        for source, canonical in values:
            combo.addItem(self.context.t(source), canonical)
            combo.setItemData(combo.count() - 1, source, Qt.ItemDataRole.UserRole + 1)

    def _populate_condition_options(self) -> None:
        previous = {
            "rotation": self.rotation_combo.currentData() if self.rotation_combo.count() else None,
            "season": self.season_combo.currentData() if self.season_combo.count() else None,
            "weather": self.weather_combo.currentData() if self.weather_combo.count() else None,
            "ground": self.ground_combo.currentData() if self.ground_combo.count() else None,
        }
        self._add_condition_items(self.rotation_combo, [("Non précisé", None), ("Droite", 1), ("Gauche", 2)])
        self._add_condition_items(self.season_combo, [("Non précisé", None), ("Printemps", [1, 5]), ("Été", 2), ("Automne", 3), ("Hiver", 4)])
        self._add_condition_items(self.weather_combo, [("Non précisé", None), ("Ensoleillé", 1), ("Nuageux", 2), ("Pluie", 3), ("Neige", 4)])
        self._add_condition_items(self.ground_combo, [("Non précisé", None), ("Firm", 1), ("Good", 2), ("Soft", 3), ("Heavy", 4)])
        stored = {
            "rotation": self.context.store.get("optimizer_rotation", "Non précisé"),
            "season": self.context.store.get("optimizer_season", "Non précisé"),
            "weather": self.context.store.get("optimizer_weather", "Non précisé"),
            "ground": self.context.store.get("optimizer_ground", "Non précisé"),
        }
        for key, combo in (
            ("rotation", self.rotation_combo),
            ("season", self.season_combo),
            ("weather", self.weather_combo),
            ("ground", self.ground_combo),
        ):
            target = previous[key]
            index = combo.findData(target)
            if index < 0:
                for candidate in range(combo.count()):
                    if combo.itemData(candidate, Qt.ItemDataRole.UserRole + 1) == stored[key]:
                        index = candidate
                        break
            combo.setCurrentIndex(index if index >= 0 else 0)

    def retranslate(self) -> None:
        t = self.context.t
        self.header.set_text(
            t("Optimisation de lignée"),
            t("Choisis l’objectif, puis compare les paires, les lignées et les futurs grands-parents dans le même écran."),
        )
        self.refresh_options_button.setText(t("Actualiser depuis le MDB"))
        self.ace_label.setText(t("Ace visé"))
        self.parent_label.setText(t("Parent à produire"))
        self.surface_label.setText(t("Surface"))
        self.distance_label.setText(t("Distance"))
        self.style_label.setText(t("Style"))
        self.course_label.setText(t("Preset de course"))
        self.top_n_label.setText(t("Résultats conservés"))
        self.advanced.set_title(t("Options avancées et conditions de course"))
        self.course_file_label.setText(t("Fichier de presets / overrides"))
        self.track_label.setText(t("Hippodrome"))
        self.rotation_label.setText(t("Rotation"))
        self.season_label.setText(t("Saison"))
        self.weather_label.setText(t("Météo"))
        self.ground_label.setText(t("État du terrain"))
        self.custom_scoring.setText(t("Utiliser mes pondérations personnalisées"))
        self.priority_label.setText(t("Priorités individuelles des white skills"))
        self.course_picker.dialog_title = t("Sélectionner les overrides de course")
        self.course_picker.file_filter = f"JSON (*.json);;{t('Tous les fichiers')} (*)"
        self.priority_picker.dialog_title = t("Choisir un profil de priorités white")
        self.priority_picker.file_filter = f"JSON (*.json);;{t('Tous les fichiers')} (*)"
        self.course_picker.set_button_text(t("Parcourir…"))
        self.priority_picker.set_button_text(t("Parcourir…"))
        self.run_button.setText(t("Calculer les meilleures lignées"))
        self.load_button.setText(t("Charger le dernier résultat"))
        self.open_button.setText(t("Ouvrir la sortie"))
        self.results_title.setText(t("Résultats intégrés"))
        self.export_button.setText(t("Exporter la paire vers Lineage Planner…"))
        self.tabs.setTabText(0, t("Paires finales"))
        self.tabs.setTabText(1, t("Lignées candidates"))
        self.tabs.setTabText(2, t("Futurs grands-parents"))
        self._populate_profiles()
        self._populate_condition_options()
        self._refresh_course_options()
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
            + f" · data.json: {data.name if data.is_file() else t('manquant')}"
            + f" · {profile_summary(self._current_profile(), self.context.language)}"
        )
        self.course_picker.set_text(self.context.course_overrides_path)

    def _current_profile(self) -> dict[str, Any]:
        return {
            "surface": self.surface_combo.currentData() or "turf",
            "distance": self.distance_combo.currentData() or "medium",
            "style": self.style_combo.currentData() or "pace_chaser",
        }

    def _refresh_course_options(self) -> None:
        current_key = self.course_combo.currentData() or self.context.store.get("optimizer_course_key")
        path = active_course_overrides_path(self.course_picker.text())
        payload = load_course_preset_payload(path)
        self._course_definitions = {
            key: course for key, course in ordered_course_presets(payload)
        }
        self.course_combo.blockSignals(True)
        self.course_combo.clear()
        self.course_combo.addItem(self.context.t("Profil générique"), None)
        for key, course in self._course_definitions.items():
            self.course_combo.addItem(
                course_preset_label(key, course, self.context.language), key
            )
        index = self.course_combo.findData(current_key)
        self.course_combo.setCurrentIndex(index if index >= 0 else 0)
        self.course_combo.blockSignals(False)

    def _course_path_changed(self, value: str) -> None:
        self.context.update_paths(course_overrides_path=value)
        self._refresh_course_options()

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

        saved_ace = _integer(self.context.store.get("optimizer_ace_card_id", "0"))
        saved_parent = _integer(
            self.context.store.get("optimizer_future_parent_card_id", "0")
        )
        current_ace = self.ace_combo.currentData() or saved_ace
        current_parent = self.parent_combo.currentData() or saved_parent
        self._ace_options = list(options)
        self._card_to_chara = {option.card_id: option.chara_id for option in options}
        for combo, selected in ((self.ace_combo, current_ace), (self.parent_combo, current_parent)):
            combo.blockSignals(True)
            combo.clear()
            for option in options:
                combo.addItem(option.display_name, option.card_id)
            index = combo.findData(selected)
            combo.setCurrentIndex(index if index >= 0 and combo.count() else (0 if combo.count() else -1))
            combo.blockSignals(False)
        self._ensure_distinct_parent()

        saved_track = _integer(self.context.store.get("optimizer_track_id", "0"))
        self.track_combo.clear()
        self.track_combo.addItem(self.context.t("Non précisé"), None)
        for track in sorted(tracks, key=lambda item: item.name.casefold()):
            self.track_combo.addItem(track.display_name, track.track_id)
        track_index = self.track_combo.findData(saved_track)
        self.track_combo.setCurrentIndex(track_index if track_index >= 0 else 0)
        self._refresh_course_options()
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
        self._ensure_distinct_parent()

    def _manual_profile_changed(self, _index: int) -> None:
        if self.course_combo.currentData() is not None:
            self.course_combo.blockSignals(True)
            self.course_combo.setCurrentIndex(0)
            self.course_combo.blockSignals(False)
        self.sync_context()

    @staticmethod
    def _set_combo_data(combo: QComboBox, value: object) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def _course_changed(self, _index: int) -> None:
        key = self.course_combo.currentData()
        course = self._course_definitions.get(str(key)) if key else None
        if not course:
            self.sync_context()
            return
        profile = course.get("profile") or {}
        for combo, kind in (
            (self.surface_combo, "surface"),
            (self.distance_combo, "distance"),
            (self.style_combo, "style"),
        ):
            value = profile.get(kind)
            if value:
                self._set_combo_data(combo, value)
        conditions = course_preset_conditions(course)
        for key_name, combo in (
            ("rotation", self.rotation_combo),
            ("season", self.season_combo),
            ("weather", self.weather_combo),
            ("ground_condition", self.ground_combo),
        ):
            if key_name in conditions:
                self._set_combo_data(combo, conditions[key_name])
        track_id = conditions.get("track_id")
        if track_id is not None:
            self._set_combo_data(self.track_combo, track_id)
        else:
            racecourse = str(((course.get("race") or {}).get("racecourse")) or "")
            for index in range(1, self.track_combo.count()):
                if racecourse_names_match(self.track_combo.itemText(index), racecourse):
                    self.track_combo.setCurrentIndex(index)
                    break
        self.sync_context()

    def _selected_conditions(self) -> dict[str, object]:
        key = self.course_combo.currentData()
        course = self._course_definitions.get(str(key)) if key else None
        conditions = course_preset_conditions(course or {})
        for name, combo in (
            ("track_id", self.track_combo),
            ("rotation", self.rotation_combo),
            ("season", self.season_combo),
            ("weather", self.weather_combo),
            ("ground_condition", self.ground_combo),
        ):
            value = combo.currentData()
            if value is not None:
                conditions[name] = value
        return conditions

    @staticmethod
    def _condition_source(combo: QComboBox) -> str:
        return str(combo.currentData(Qt.ItemDataRole.UserRole + 1) or "Non précisé")

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

        course_path = active_course_overrides_path(self.course_picker.text())
        priority_text = self.priority_picker.text()
        priority_path = Path(priority_text).expanduser() if priority_text else None
        request = OptimizationRequest(
            master_path=Path(self.context.master_path).expanduser(),
            veterans_json_path=Path(self.context.veterans_json_path).expanduser(),
            output_dir=Path(self.context.output_dir).expanduser(),
            ace_card_id=ace_id,
            future_parent_card_id=parent_id,
            surface=str(self.surface_combo.currentData() or "turf"),
            distance=str(self.distance_combo.currentData() or "medium"),
            style=str(self.style_combo.currentData() or "pace_chaser"),
            course_overrides_path=course_path,
            course_key=str(self.course_combo.currentData() or "") or None,
            course_conditions=self._selected_conditions(),
            top_n=self.top_n_spin.value(),
            use_custom_scoring=self.custom_scoring.isChecked(),
            skill_priorities_path=priority_path,
        )
        self.context.store.update(
            {
                "optimizer_ace_card_id": ace_id,
                "optimizer_future_parent_card_id": parent_id,
                "optimizer_surface": request.surface,
                "optimizer_distance": request.distance,
                "optimizer_style": request.style,
                "optimizer_course_key": request.course_key or "",
                "optimizer_top_n": request.top_n,
                "optimizer_track_id": self.track_combo.currentData() or 0,
                "optimizer_rotation": self._condition_source(self.rotation_combo),
                "optimizer_season": self._condition_source(self.season_combo),
                "optimizer_weather": self._condition_source(self.weather_combo),
                "optimizer_ground": self._condition_source(self.ground_combo),
                "use_custom_scoring": "1" if request.use_custom_scoring else "0",
                "skill_priorities_path": priority_text,
            }
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
