from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Any

from PySide6.QtCore import QItemSelection, QTimer, Qt, Signal, QUrl
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableView,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
)

from uma_legacy_linker.backend_process import ProcessTask
from uma_legacy_linker.error_guidance import actionable_error
from uma_legacy_linker.output_history import (
    CURRENT_REVISION,
    OutputProvenance,
    PREVIOUS_REVISION,
    available_output_revisions,
    format_output_timestamp,
    read_json_output_revision,
)
from uma_legacy_linker.result_comparison import (
    TRANSFER_METRICS,
    ComparisonDataset,
    intersect_datasets,
    transfer_comparison_dataset,
)
from ui_qt.accessibility import describe_control, label_control
from ui_qt.components import PageHeader, StatusCard, ThemedComboBox, CollapsibleSection, muted_label
from ui_qt.comparison_dialog import ResultComparisonDialog
from ui_qt.transfer_comparison_dialog import TransferComparisonDialog
from ui_qt.transfer_decision import decision_examples, decision_html
from ui_qt.transfer_decision_panel import TransferDecisionPanel
from ui_qt.context import AppContext
from uma_legacy_linker.application import (
    TransferRequest,
    active_course_overrides_path,
    open_path,
    run_transfer_analysis,
)
from ui_qt.models import Column, ResultTableModel, nested, number
from ui_qt.presentation import transfer_detail_html
from ui_qt.provenance import (
    provenance_tooltip,
    revision_menu_label,
    revision_title,
)
from ui_qt.table_typography import enable_tabular_numbers
from ui_qt.theme import COLORS
from ui_qt.view_state import bind_splitter_state, bind_table_view_state
from uma_legacy_linker.veteran_identity import (
    canonical_veteran_label,
    canonical_veteran_labels,
    game_veteran_label,
    game_rank_label,
    format_rank_score,
)


RIGHT = Qt.AlignmentFlag.AlignRight

STATE_EMPTY = "empty"
STATE_RUNNING = "running"
STATE_READY = "ready"
STATE_STALE = "stale"
STATE_LOADED = "loaded"

TRANSFER_CANDIDATES = "transfer_candidates"
GAME_SCORE_COLUMN = 11

STATE_LABELS = {
    STATE_EMPTY: "Aucun rapport affiché",
    STATE_RUNNING: "Analyse en cours",
    STATE_READY: "Rapport à jour",
    STATE_STALE: "Rapport périmé — les paramètres ont changé",
    STATE_LOADED: "Rapport chargé depuis le disque",
}


class TransferPage(QWidget):
    task_requested = Signal(object, str, object)

    def __init__(self, context: AppContext, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("transferPage")
        self.setStyleSheet(f"#transferPage {{ background-color: {COLORS['background']}; }}")
        self.context = context
        self._busy = False
        self._records: list[dict[str, Any]] = []
        self._comparison_model: dict[str, Any] = {}
        self._decision_examples = []
        self._detail_expanded = False
        self._focused_example = 0
        self._calendar_day = ""
        self._calendar_unknown = False
        self._calendar_valid_until: datetime | None = None
        self._result_state = STATE_EMPTY
        self._result_origin_state = STATE_EMPTY
        self._result_fingerprint = ""
        self._running_fingerprint = ""
        self._state_before_running = STATE_EMPTY
        self._generated_at = ""
        self._provenance: OutputProvenance | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(12)
        self.header = PageHeader("", "")
        root.addWidget(self.header)

        safety = QFrame()
        safety.setObjectName("panel")
        safety_layout = QGridLayout(safety)
        safety_layout.setContentsMargins(16, 12, 16, 12)
        self.safety_text = muted_label("")
        self.mode_label = QLabel("")
        self.mode_combo = ThemedComboBox()
        self.upcoming_cm_check = QCheckBox("")
        self.upcoming_cm_limit = QSpinBox()
        self.upcoming_cm_limit.setRange(1, 20)
        self.team_trials_check = QCheckBox("")
        self.generic_profiles_check = QCheckBox("")
        self.run_button = QPushButton("")
        self.run_button.setObjectName("primary")
        self.load_button = QPushButton("")
        self.history_menu = QMenu(self.load_button)
        self.history_menu.aboutToShow.connect(self._rebuild_history_menu)
        self.load_button.setMenu(self.history_menu)
        self.compare_button = QPushButton("")
        self.open_button = QPushButton("")
        self.result_state = QLabel("")
        self.result_state.setObjectName("pill")
        self.result_state.setWordWrap(True)
        self.revision_badge = QLabel("")
        self.revision_badge.setObjectName("pill")
        self.revision_badge.setVisible(False)
        self.generated_at = muted_label("", wrap=False)
        self.cm_calendar = muted_label("")
        safety_layout.addWidget(self.safety_text, 0, 0, 1, 8)
        self.safety_text.setVisible(False)
        self.scope_section = CollapsibleSection("")
        scope_grid = QGridLayout()
        scope_grid.addWidget(self.mode_label, 0, 0)
        scope_grid.addWidget(self.mode_combo, 0, 1)
        scope_grid.addWidget(self.upcoming_cm_check, 1, 0)
        scope_grid.addWidget(self.upcoming_cm_limit, 1, 1)
        scope_grid.addWidget(self.team_trials_check, 2, 0)
        scope_grid.addWidget(self.generic_profiles_check, 2, 1)
        self.scope_section.content_layout.addLayout(scope_grid)
        safety_layout.addWidget(self.scope_section, 2, 0, 1, 8)
        action_layout = QHBoxLayout()
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.addWidget(self.result_state)
        metadata_layout = QHBoxLayout()
        metadata_layout.addWidget(self.revision_badge)
        metadata_layout.addWidget(self.generated_at)
        metadata_layout.addStretch(1)
        self.scope_section.content_layout.addWidget(self.cm_calendar)
        self.scope_section.content_layout.addLayout(metadata_layout)
        action_layout.addStretch(1)
        action_layout.addWidget(self.run_button)
        action_layout.addWidget(self.load_button)
        action_layout.addWidget(self.open_button)
        safety_layout.addLayout(action_layout, 1, 0, 1, 8)
        root.addWidget(safety)

        self.upcoming_cm_check.setChecked(
            self.context.store.get("transfer_include_upcoming_cm", "1") in {"1", "true", "True"}
        )
        try:
            cm_limit = int(self.context.store.get("transfer_upcoming_cm_limit", "5"))
        except ValueError:
            cm_limit = 5
        self.upcoming_cm_limit.setValue(max(1, min(20, cm_limit)))
        self.team_trials_check.setChecked(
            self.context.store.get("transfer_include_team_trials", "0") in {"1", "true", "True"}
        )
        self.generic_profiles_check.setChecked(
            self.context.store.get("transfer_include_generic_profiles", "0") in {"1", "true", "True"}
        )
        self.upcoming_cm_limit.setEnabled(self.upcoming_cm_check.isChecked())

        cards = QGridLayout()
        cards.setHorizontalSpacing(10)
        self.safe_card = StatusCard("", "0", "")
        self.recommended_card = StatusCard("", "0", "")
        self.review_card = StatusCard("", "0", "")
        self.keep_card = StatusCard("", "0", "")
        self.protected_card = StatusCard("", "0", "")
        for index, card in enumerate((
            self.safe_card,
            self.recommended_card,
            self.review_card,
            self.keep_card,
            self.protected_card,
        )):
            card.title_label.setWordWrap(True)
            card.detail_label.setVisible(False)
            card.layout().setContentsMargins(10, 6, 10, 6)
            card.layout().setSpacing(2)
            cards.addWidget(card, 0, index)
            cards.setColumnStretch(index, 1)
        self.collection_summary = muted_label("")
        self.scope_section.content_layout.addWidget(self.collection_summary)
        self.scope_section.content_layout.addLayout(cards)

        filters = QFrame()
        filters.setObjectName("panel")
        filter_layout = QGridLayout(filters)
        filter_layout.setContentsMargins(12, 8, 12, 8)
        self.filter_label = QLabel("")
        self.family_combo = ThemedComboBox()
        self.family_combo.setMaximumWidth(250)
        self.family_combo.setMinimumWidth(160)
        self.family_combo.setMinimumContentsLength(12)
        self.family_combo.setSizeAdjustPolicy(ThemedComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.family_combo.currentIndexChanged.connect(self.apply_filters)
        self.status_combo = ThemedComboBox()
        self.status_combo.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.status_combo.setMinimumContentsLength(12)
        self.status_combo.setSizeAdjustPolicy(ThemedComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.status_combo.setMaximumWidth(200)
        self.status_combo.setMinimumWidth(160)
        self.family_combo.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.search = QLineEdit()
        self.search.setClearButtonEnabled(True)
        self.count_label = muted_label("")
        filter_layout.addWidget(self.filter_label, 0, 0)
        filter_layout.addWidget(self.status_combo, 0, 1)
        filter_layout.addWidget(self.family_combo, 0, 2)
        filter_layout.addWidget(self.search, 0, 3)
        filter_layout.addWidget(self.count_label, 0, 4)
        filter_layout.setColumnStretch(3, 1)
        self.selection_button = QPushButton("")
        self.selection_button.clicked.connect(self._prepare_transfer_selection)
        self.selection_hint = muted_label("")
        filter_layout.addWidget(self.selection_button, 1, 0, 1, 2)
        filter_layout.addWidget(self.selection_hint, 1, 2, 1, 3)
        root.addWidget(filters)
        self.empty_results = QLabel("")
        self.empty_results.setWordWrap(True)
        self.empty_results.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.reset_filters = QPushButton("")
        self.reset_filters.clicked.connect(self._reset_filters)
        root.addWidget(self.empty_results)
        root.addWidget(self.reset_filters, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.table = QTableView()
        enable_tabular_numbers(self.table)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setDefaultSectionSize(54)
        self.model = ResultTableModel([], self._columns())
        self.table.setModel(self.model)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(-1, Qt.SortOrder.AscendingOrder)
        self.decision_panel = TransferDecisionPanel(context)
        self.decision_panel.actions_layout.addWidget(self.compare_button)
        self.detail = self.decision_panel.browser
        self.detail.anchorClicked.connect(self._decision_link)
        self.decision_panel.example_changed.connect(self._example_changed)
        self.decision_panel.verification_requested.connect(lambda index: self._decision_link(QUrl(f"example:{index}")))
        self.detail.setMinimumWidth(300)
        self.splitter.addWidget(self.table)
        self.splitter.addWidget(self.decision_panel)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setStretchFactor(0, 5)
        self.splitter.setStretchFactor(1, 4)
        self._configure_header()
        bind_splitter_state(
            self.splitter,
            self.context.store,
            "ui_splitter_transfer",
            [700, 560],
        )
        self._save_table_state = bind_table_view_state(
            self.table,
            self.context.store,
            "ui_table_transfer_readable_v3",
            default_hidden=(2, 3, 4, 5, 6, 7, 8, 9, 10),
        )
        root.addWidget(self.splitter, 1)

        self.run_button.clicked.connect(self.start_analysis)
        self.upcoming_cm_check.toggled.connect(self.upcoming_cm_limit.setEnabled)
        self.mode_combo.currentIndexChanged.connect(self._scope_changed)
        self.upcoming_cm_check.toggled.connect(self._scope_changed)
        self.upcoming_cm_limit.valueChanged.connect(self._scope_changed)
        self.team_trials_check.toggled.connect(self._scope_changed)
        self.generic_profiles_check.toggled.connect(self._scope_changed)
        self.compare_button.clicked.connect(self.compare_selected_veteran)
        self.table.doubleClicked.connect(lambda _index: self.compare_selected_veteran())
        self.open_button.clicked.connect(self.open_output)
        self.status_combo.currentIndexChanged.connect(self._status_filter_changed)
        self.search.textChanged.connect(self.apply_filters)
        self.table.selectionModel().selectionChanged.connect(self._selection_changed)
        self.context.language_changed.connect(self._language_changed)
        self.context.configuration_changed.connect(self._refresh_freshness)
        self.context.lineage_changed.connect(self._refresh_freshness)
        self._freshness_timer = QTimer(self)
        self._freshness_timer.timeout.connect(self._refresh_freshness)
        self._freshness_timer.start(60_000)
        self.retranslate()
        self.load_latest(show_errors=False)

    def _language_changed(self, _language: str) -> None:
        self.retranslate()

    def _columns(self) -> list[Column]:
        t = self.context.t
        parent_percentile = number("best_parent_percentile", default=100.0)
        grandparent_percentile = number(
            "best_grandparent_percentile", default=100.0
        )
        labels = {
            "safe_transfer": t("Équivalent dans le modèle"),
            "recommended_transfer": t("Redondant dans le modèle"),
            "review": t("À examiner"),
            "keep": t("Conserver"),
            "protected": t("Protégé"),
        }
        def verdict_label(row: dict[str, Any]) -> str:
            analysis = str(row.get("analysis_status") or row.get("status") or "")
            if row.get("status") == "protected" and row.get("analysis_status"):
                return t("Protégé") + " · " + t("Redondant" if analysis in {"safe_transfer", "recommended_transfer"} else "Utile")
            if analysis == "safe_transfer":
                return t("Équivalent (modèle)")
            if analysis == "recommended_transfer":
                return t("Redondant")
            return labels.get(analysis, analysis or "—")

        def coverage_label(row: dict[str, Any]) -> str:
            replacement = row.get("dominated_by") or {}
            if replacement:
                return canonical_veteran_label(replacement)
            coverage = list(row.get("covered_by_portfolio") or [])
            return ", ".join(
                canonical_veteran_labels(
                    coverage,
                    rank_label=t("Rang").casefold(),
                    blue_label=t("Bleues").casefold(),
                )
            ) or "—"

        def coverage_tooltip(row: dict[str, Any]) -> str:
            replacement = row.get("dominated_by") or {}
            if replacement:
                return game_veteran_label(replacement)
            return ", ".join(
                tooltip
                for tooltip in (
                    game_veteran_label(item)
                    for item in row.get("covered_by_portfolio") or []
                )
                if tooltip
            )

        return [
            Column(t("Verdict"), verdict_label, tooltip_getter=lambda row: labels.get(
                str(row.get("analysis_status") or row.get("status")), "—")),
            Column(
                t("Vétéran"),
                lambda row: str(row.get("card_name") or row.get("uma_name") or "—")
                + "\n" + game_rank_label(row.get("rank")) + " · " + format_rank_score(row.get("rank_score")),
                sort_getter=nested("rank_score"),
                tooltip_getter=game_veteran_label,
            ),
            Column(t("Copies"), nested("same_card_copy_count"), RIGHT),
            Column(t("Indice parent"), nested("best_parent_score"), RIGHT),
            Column(
                t("Rang parent"),
                lambda row: f"top {parent_percentile(row):.1f}%",
                RIGHT,
                sort_getter=parent_percentile,
            ),
            Column(t("Indice GP"), nested("best_grandparent_score"), RIGHT),
            Column(
                t("Rang GP"),
                lambda row: f"top {grandparent_percentile(row):.1f}%",
                RIGHT,
                sort_getter=grandparent_percentile,
            ),
            Column(
                t("Couverture / remplaçant"),
                coverage_label,
                tooltip_getter=coverage_tooltip,
            ),
            Column(t("Avance moy."), lambda row: (row.get("dominated_by") or {}).get("mean_score_lead", "—"), RIGHT),
            Column(t("Référencé par"), nested("referenced_by_local_veterans"), RIGHT),
            Column(t("Protection"), lambda row: t("Protégé — diagnostic seulement")
                   if row.get("manual_protection_reasons") else "—"),
            Column(t("Score en jeu"), lambda row: format_rank_score(row.get("rank_score")), RIGHT,
                   sort_getter=number("rank_score", default=-float("inf"))),
        ]

    def _configure_header(self) -> None:
        header = self.table.horizontalHeader()
        header.setMinimumSectionSize(62)
        for index in range(self.model.columnCount()):
            header.setSectionResizeMode(index, QHeaderView.ResizeMode.Interactive)
        self.table.resizeColumnsToContents()
        for index, width in ((0, 175), (1, 265), (3, 110), (5, 100), (7, 245), (GAME_SCORE_COLUMN, 135)):
            header.resizeSection(index, width)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

    def retranslate(self) -> None:
        t = self.context.t
        self.header.set_text(
            t("Transfer Helper"),
            t("Identifie les copies redondantes sans jamais modifier l’export source ni prendre une décision à ta place."),
        )
        self.safety_text.setText(
            t("Prototype par branche individuelle. Les indices expliquent la redondance ; le coût de refarm et l’usage en course restent à vérifier avant un transfert.")
        )
        self.mode_label.setText(t("Mode d’analyse"))
        selected_mode = self.mode_combo.currentData() or self.context.store.get("transfer_analysis_mode", "exhaustive")
        self.mode_combo.blockSignals(True)
        self.mode_combo.clear()
        self.mode_combo.addItem(t("Rapide"), "fast")
        self.mode_combo.addItem(t("Audit exhaustif (recommandé)"), "exhaustive")
        selected_index = self.mode_combo.findData(selected_mode)
        self.mode_combo.setCurrentIndex(selected_index if selected_index >= 0 else 0)
        self.mode_combo.blockSignals(False)
        self.upcoming_cm_check.setText(t("Inclure les prochaines CM"))
        self.upcoming_cm_limit.setSuffix(" " + t("CM max."))
        self.team_trials_check.setText(t("Inclure Team Trials"))
        self.generic_profiles_check.setText(t("Inclure les profils génériques"))
        self.run_button.setText(t("Analyser les vétérans locaux"))
        self.load_button.setText(t("Historique"))
        self.compare_button.setText(t("Explorer…"))
        self.compare_button.setAccessibleName(t("Comparer les branches…"))
        self.collection_summary.setText(t("Résumé de la collection"))
        self.reset_filters.setText(t("Réinitialiser les filtres"))
        self.open_button.setText(t("Ouvrir la sortie"))
        self.filter_label.setText(t("Afficher"))
        self.search.setPlaceholderText(t("Rechercher un nom, un score ou un remplaçant…"))
        self.mode_combo.setToolTip(
            t("Le mode exhaustif compare tous les Ace compatibles. Il ne certifie pas le coût de refarm ni l’usage actuel en course.")
        )
        self.upcoming_cm_check.setToolTip(
            t("Évalue chaque vétéran dans le contexte des prochaines Champion Meetings configurées.")
        )
        self.upcoming_cm_limit.setToolTip(
            t("Nombre maximal de prochaines Champion Meetings incluses dans l’analyse.")
        )
        self.team_trials_check.setToolTip(
            t("Ajoute les rôles des cinq catégories Team Trials aux usages à préserver.")
        )
        self.generic_profiles_check.setToolTip(
            t("Ajoute des profils génériques pour protéger les usages qui ne dépendent pas d’une course planifiée.")
        )
        self.run_button.setToolTip(
            t("Analyse la collection sans modifier ni supprimer aucun vétéran.")
        )
        self.load_button.setToolTip(
            t("Charge le rapport courant ou l’unique rapport précédent conservé sur le disque.")
        )
        self.compare_button.setToolTip(
            t("Compare le vétéran sélectionné avec son remplaçant ou sa couverture conservée.")
        )
        self.open_button.setToolTip(
            t("Ouvre le dossier contenant le rapport JSON, le CSV et le résumé.")
        )
        self.status_combo.setToolTip(
            t("Filtre le tableau selon le niveau de confiance du diagnostic.")
        )
        self.table.setToolTip(
            t("La couverture désigne le remplaçant ou l’ensemble de vétérans qui préserve les rôles compétitifs de la copie.")
        )
        self.detail.setToolTip(
            t("Le détail explique le verdict, les niches comparées, la dominance et les protections de Sparks appliquées.")
        )
        self.table.horizontalHeader().setToolTip(
            t("Clic droit pour choisir les colonnes affichées ; largeur, ordre et tri sont mémorisés.")
        )
        self.safe_card.setToolTip(
            t("Un remplaçant du même costume et de la même unique couvre toutes les niches viables sans perte de patrimoine Spark protégé.")
        )
        self.recommended_card.setToolTip(
            t("Redondance couverte collectivement par les copies conservées ; un choix manuel reste nécessaire.")
        )
        self.review_card.setToolTip(
            t("Une niche, une couverture incomplète ou une protection de Spark impose une vérification manuelle.")
        )
        self.keep_card.setToolTip(
            t("La copie conserve au moins un rôle compétitif ou un élément stratégique qui n’est pas suffisamment remplacé.")
        )
        self.protected_card.setToolTip(
            t("Un verrou ou un mémo en jeu interdit toute recommandation de transfert, quel que soit le score.")
        )
        selected = (
            self.status_combo.currentData()
            if self.status_combo.count()
            else self.context.store.get("ui_transfer_status_filter") or None
        )
        self.status_combo.blockSignals(True)
        self.status_combo.clear()
        for label, value in (
            ("Tous les verdicts", None),
            ("À transférer", TRANSFER_CANDIDATES),
            ("Équivalent dans le modèle", "safe_transfer"),
            ("Redondant dans le modèle", "recommended_transfer"),
            ("À examiner", "review"),
            ("Conserver", "keep"),
            ("Protégé", "protected"),
        ):
            self.status_combo.addItem(t(label), value)
        index = self.status_combo.findData(selected)
        self.status_combo.setCurrentIndex(index if index >= 0 else 0)
        self.status_combo.blockSignals(False)
        self.selection_button.setText(t("Préparer les transferts"))
        self.selection_hint.setText(t("Dans le jeu : Rating / Desc. Retrouve les copies par leur costume et leur score."))
        self.selection_button.setToolTip(t("Affiche les copies équivalentes ou redondantes, sans les protégées, triées par score en jeu décroissant. Les cas à examiner restent séparés."))
        label_control(
            self.mode_label,
            self.mode_combo,
            self.mode_combo.toolTip(),
        )
        label_control(
            self.filter_label,
            self.status_combo,
            self.status_combo.toolTip(),
        )
        describe_control(
            self.upcoming_cm_check,
            self.upcoming_cm_check.text(),
            self.upcoming_cm_check.toolTip(),
        )
        describe_control(
            self.upcoming_cm_limit,
            f"{self.upcoming_cm_check.text()} · {t('CM max.')}",
            self.upcoming_cm_limit.toolTip(),
        )
        for check in (self.team_trials_check, self.generic_profiles_check):
            describe_control(check, check.text(), check.toolTip())
        describe_control(
            self.search,
            self.search.placeholderText(),
            t("Transfer Helper"),
        )
        describe_control(
            self.table,
            f"{t('Transfer Helper')} · {t('Résultats')}",
            self.table.toolTip(),
        )
        describe_control(
            self.detail,
            f"{t('Transfer Helper')} · {t('Détail')}",
            self.detail.toolTip(),
        )
        self._fill_families()
        self._scope_summary()
        self._refresh_cards()
        self._render_result_state()
        self.apply_filters()
        self._update_compare_button()

    def _scope_values(self) -> dict[str, object]:
        return {
            "analysis_mode": str(self.mode_combo.currentData() or "exhaustive"),
            "include_upcoming_cm_context": self.upcoming_cm_check.isChecked(),
            "upcoming_cm_limit": self.upcoming_cm_limit.value(),
            "include_team_trials": self.team_trials_check.isChecked(),
            "include_generic_profiles": self.generic_profiles_check.isChecked(),
        }

    def _current_fingerprint(self) -> str:
        return self.context.transfer_fingerprint(self._scope_values())

    def _persist_scope(self) -> None:
        scope = self._scope_values()
        self.context.store.update(
            {
                "transfer_analysis_mode": scope["analysis_mode"],
                "transfer_include_upcoming_cm": int(
                    bool(scope["include_upcoming_cm_context"])
                ),
                "transfer_upcoming_cm_limit": scope["upcoming_cm_limit"],
                "transfer_include_team_trials": int(
                    bool(scope["include_team_trials"])
                ),
                "transfer_include_generic_profiles": int(
                    bool(scope["include_generic_profiles"])
                ),
            }
        )

    def _scope_changed(self, *_args: object) -> None:
        self._persist_scope()
        self._scope_summary()
        self._refresh_freshness()

    def _scope_summary(self) -> None:
        t = self.context.t
        parts = [t("Rapide") if self.mode_combo.currentData() == "fast" else t("Exhaustif")]
        if self.upcoming_cm_check.isChecked():
            parts.append(str(self.upcoming_cm_limit.value()) + " " + t("CM max."))
        if self.team_trials_check.isChecked():
            parts.append(t("Team Trials"))
        if self.generic_profiles_check.isChecked():
            parts.append(t("Profils génériques"))
        if self._calendar_unknown:
            parts.append(t("Dates CM à vérifier"))
        self.scope_section.set_title(t("Périmètre de l’analyse") + " · " + " · ".join(parts))
        self.scope_section.toggle.setToolTip(self.cm_calendar.text())

    def _fill_families(self) -> None:
        selected = self.family_combo.currentData()
        groups = {}
        for record in self._records:
            group = record.get("comparison_group")
            if group:
                card_name = str(record.get("card_name") or "—")
                uma_name = str(record.get("uma_name") or "")
                name = uma_name + " · " + card_name if uma_name and uma_name != card_name else card_name
                name, count = groups.get(group, (name, 0))
                groups[group] = (name, count + 1)
        self.family_combo.blockSignals(True)
        self.family_combo.clear()
        self.family_combo.addItem(self.context.t("Tous les costumes"), None)
        for key, (name, count) in sorted(groups.items(), key=lambda item: item[1][0].casefold()):
            self.family_combo.addItem(f"{name} · {count}", key)
            self.family_combo.setItemData(self.family_combo.count()-1, f"{name} · {count}", Qt.ItemDataRole.ToolTipRole)
        self.family_combo.setCurrentIndex(max(0, self.family_combo.findData(selected)))
        self.family_combo.setAccessibleName(self.context.t("Filtrer par costume"))
        self.family_combo.setToolTip(self.context.t("Filtrer par costume"))
        self.family_combo.blockSignals(False)

    def _status_filter_changed(self, *_args: object) -> None:
        self.context.store.update(
            {"ui_transfer_status_filter": self.status_combo.currentData() or ""}
        )
        self.apply_filters()

    def _prepare_transfer_selection(self) -> None:
        # Start with the complete candidate list; the costume/search filters remain usable afterwards.
        self.search.clear()
        self.family_combo.setCurrentIndex(0)
        self.status_combo.setCurrentIndex(self.status_combo.findData(TRANSFER_CANDIDATES))
        self.apply_filters()
        if self.model.rowCount():
            self.table.selectRow(0)
            self.table.scrollToTop()

    def _set_result_state(self, state: str) -> None:
        self._result_state = state
        self._render_result_state()

    def _render_result_state(self) -> None:
        t = self.context.t
        self.result_state.setText(t(STATE_LABELS[self._result_state]))
        self.result_state.setObjectName(
            "pillWarning" if self._result_state == STATE_STALE else "pillAccent"
        )
        self.result_state.style().unpolish(self.result_state)
        self.result_state.style().polish(self.result_state)
        self.generated_at.setText(
            t("Rapport généré le {date}").replace("{date}", self._generated_at)
            if self._generated_at
            else ""
        )
        self.revision_badge.setVisible(self._provenance is not None)
        self.revision_badge.setText(
            revision_title(self._provenance.revision.key, t)
            if self._provenance is not None
            else ""
        )
        self.revision_badge.setToolTip(
            provenance_tooltip(self._provenance, t)
            if self._provenance is not None
            else ""
        )
        describe_control(
            self.revision_badge,
            t("Traçabilité"),
            self.revision_badge.toolTip(),
        )
        describe_control(
            self.result_state,
            self.result_state.text(),
            self.generated_at.text(),
        )

    def _refresh_freshness(self, *_args: object) -> None:
        if self._result_origin_state not in {STATE_READY, STATE_LOADED}:
            return
        state = (
            self._result_origin_state
            if self._current_fingerprint() == self._result_fingerprint and (
                not self._calendar_day or self._calendar_day == datetime.now().astimezone().date().isoformat()
            ) and (
                not self._calendar_valid_until or datetime.now(timezone.utc) < self._calendar_valid_until
            )
            else STATE_STALE
        )
        self._set_result_state(state)

    def _capture_report_context(self, payload: dict[str, Any]) -> None:
        self._comparison_model = payload.get("comparison_model") or {}
        audit = (payload.get("settings") or {}).get("cm_calendar") or {}
        try:
            self._calendar_valid_until = datetime.fromisoformat(str(audit.get("next_transition_utc") or ""))
            if self._calendar_valid_until.tzinfo is None:
                self._calendar_valid_until = None
        except ValueError:
            self._calendar_valid_until = None
        try:
            moment = datetime.fromisoformat(str(audit.get("as_of_utc") or ""))
            self._calendar_day = moment.astimezone().date().isoformat()
        except ValueError:
            self._calendar_day = ""
        entries = []
        t = self.context.t
        for item in audit.get("selected") or []:
            state = item.get("status")
            label = t("En cours") if state == "current" else (
                t("Date connue") if state == "scheduled" else t("Date Global inconnue")
            )
            entries.append(f"CM{item.get('sequence')} · {label}")
        self.cm_calendar.setText(t("Calendrier CM") + " : " + " ; ".join(entries) if entries else "")
        self._calendar_unknown = any(item.get("status") not in {"current", "scheduled"}
                                     for item in audit.get("selected") or [])
        self._scope_summary()
        self._render_decision()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._refresh_freshness()

    def _refresh_cards(self) -> None:
        t = self.context.t
        counts = {
            key: 0
            for key in (
                "safe_transfer",
                "recommended_transfer",
                "review",
                "keep",
                "protected",
            )
        }
        for record in self._records:
            key = str(record.get("status") or "")
            if key in counts:
                counts[key] += 1
        self.safe_card.set_content(t("Équivalent (modèle)"), str(counts["safe_transfer"]), t("Coût et usage en course à vérifier"), "ok")
        self.recommended_card.set_content(t("Redondant"), str(counts["recommended_transfer"]), t("Redondant dans le portefeuille"), "ok")
        self.review_card.set_content(t("À examiner"), str(counts["review"]), t("Rôle incertain ou Spark à vérifier"), "warning")
        self.keep_card.set_content(t("Conserver"), str(counts["keep"]), t("Nécessaire au portefeuille"), "info")
        self.protected_card.set_content(t("Protégé"), str(counts["protected"]), t("Verrou ou mémo en jeu"), "neutral")

    def set_records(self, records: list[dict[str, Any]]) -> None:
        self._records = list(records)
        self._fill_families()
        self._refresh_cards()
        self.apply_filters()
        self._update_compare_button()

    def apply_filters(self, *_args: object) -> None:
        status = self.status_combo.currentData()
        query = self.search.text().strip().casefold()
        rows = []
        for record in self._records:
            if self.family_combo.currentData() and record.get("comparison_group") != self.family_combo.currentData():
                continue
            if status == TRANSFER_CANDIDATES:
                if (record.get("status") not in {"safe_transfer", "recommended_transfer"}
                        or record.get("manual_protection_reasons")
                        or record.get("selected_in_portfolio")):
                    continue
            elif status is not None and record.get("status") != status and (
                status == "protected" or record.get("analysis_status") != status
            ):
                continue
            replacement = record.get("dominated_by") or {}
            coverage = record.get("covered_by_portfolio") or []
            haystack = " ".join(
                str(value or "")
                for value in (
                    record.get("card_name"), record.get("uma_name"),
                    record.get("rank_score"), replacement.get("card_name"),
                    replacement.get("uma_name"), replacement.get("rank_score"),
                    *(item.get("card_name") for item in coverage),
                    *(item.get("rank_score") for item in coverage),
                )
            ).casefold()
            if query and query not in haystack and ''.join(query.split()) not in ''.join(haystack.split()):
                continue
            rows.append(record)
        selected = self.selected_row()
        selected_id = selected.get("trained_chara_id") if selected else None
        self.model.set_columns(self._columns())
        self.model.set_rows(rows)
        if status == TRANSFER_CANDIDATES:
            self.table.setColumnHidden(GAME_SCORE_COLUMN, False)
            self.table.horizontalHeader().moveSection(
                self.table.horizontalHeader().visualIndex(GAME_SCORE_COLUMN), 0
            )
            self.table.sortByColumn(GAME_SCORE_COLUMN, Qt.SortOrder.DescendingOrder)
        sort_column = self.table.horizontalHeader().sortIndicatorSection()
        if sort_column >= 0:
            self.model.sort(
                sort_column,
                self.table.horizontalHeader().sortIndicatorOrder(),
            )
        self.count_label.setText(
            self.context.t("{shown} / {total} vétérans")
            .replace("{shown}", str(len(rows)))
            .replace("{total}", str(len(self._records)))
        )
        has_rows = bool(rows)
        self.splitter.setVisible(has_rows)
        self.empty_results.setVisible(not has_rows)
        self.reset_filters.setVisible(not has_rows and bool(self._records))
        self.empty_results.setText(self.context.t(
            "Aucune copie ne correspond aux filtres. Modifie la recherche ou réinitialise les filtres."
            if self._records else "Lance une analyse ou charge un rapport pour comparer tes copies."
        ))
        target = -1
        if selected_id is not None:
            for index in range(self.model.rowCount()):
                model_row = self.model.row(index) or {}
                if model_row.get("trained_chara_id") == selected_id:
                    target = index
                    break
        if target < 0 and self.model.rowCount():
            target = 0
        if target >= 0:
            self.table.selectRow(target)
        else:
            self.detail.setHtml(transfer_detail_html(None, self.context.language))
        self._update_compare_button()

    def _reset_filters(self) -> None:
        self.search.clear()
        self.status_combo.setCurrentIndex(0)
        self.family_combo.setCurrentIndex(0)

    def selected_row(self) -> dict[str, Any] | None:
        indexes = self.table.selectionModel().selectedRows()
        return self.model.row(indexes[0].row()) if indexes else None

    def _selection_changed(self, _selected: QItemSelection, _deselected: QItemSelection) -> None:
        self._detail_expanded = False
        self._focused_example = 0
        indexes = self.table.selectionModel().selectedRows()
        if indexes:
            self.table.scrollTo(indexes[0])
        self._render_decision()
        self._update_compare_button()

    def _render_decision(self) -> None:
        record = self.selected_row()
        self._decision_examples = decision_examples(record, self._records, self._comparison_model) if record else []
        self._focused_example = max(0, min(self._focused_example, len(self._decision_examples)-1))
        self.decision_panel.set_identity(record, self._records, self._decision_examples, self._focused_example)
        html = decision_html(record, self._decision_examples, self.context.language,
                             self.context.t, self._detail_expanded, model=self._comparison_model,
                             focus=self._focused_example, show_identity=False)
        if self._detail_expanded:
            html += transfer_detail_html(record, self.context.language)
        self.detail.setHtml(html)

    def _example_changed(self, index) -> None:
        self._focused_example = max(0, index)
        self._render_decision()

    def _decision_link(self, url) -> None:
        if url.toString() == "details:toggle":
            self._detail_expanded = not self._detail_expanded
            self._render_decision()
        elif url.scheme() == "example":
            try:
                index = int(url.path())
            except ValueError:
                return
            if self._busy or not 0 <= index < len(self._decision_examples):
                return
            example = self._decision_examples[index]
            selected = self.selected_row()
            if selected is None:
                return
            dialog = TransferComparisonDialog(
                self.context, selected, [example["target"]], self._comparison_model, parent=self,
            )
            if dialog.select_example(example):
                dialog.exec()
            else:
                dialog.deleteLater()

    @staticmethod
    def _record_id(record: dict[str, Any]) -> str:
        return str(record.get("trained_chara_id") or "")

    def _comparison_targets(
        self,
        record: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        if not record:
            return []
        target_ids: list[str] = []
        dominated = record.get("dominated_by")
        if isinstance(dominated, dict):
            target_ids.append(self._record_id(dominated))
        for target in record.get("covered_by_portfolio") or []:
            if isinstance(target, dict):
                target_ids.append(self._record_id(target))
        by_id = {
            self._record_id(candidate): candidate
            for candidate in self._records
            if self._record_id(candidate)
        }
        own_id = self._record_id(record)
        group = record.get("comparison_group")
        if group:
            target_ids.extend(self._record_id(candidate) for candidate in self._records
                              if candidate.get("comparison_group") == group)
        return [
            by_id[target_id]
            for target_id in dict.fromkeys(target_ids)
            if target_id and target_id != own_id and target_id in by_id
        ]

    def _update_compare_button(self) -> None:
        self.decision_panel.verify_button.setEnabled(not self._busy and bool(self._decision_examples))
        self.compare_button.setEnabled(
            not self._busy and bool(self._comparison_targets(self.selected_row()))
        )

    def _comparison_renderer(self, item, _dataset: ComparisonDataset) -> str:
        return transfer_detail_html(item.row, self.context.language)

    def _show_comparison_error(self, message: str) -> None:
        QMessageBox.information(
            self,
            self.context.t("Comparaison"),
            self.context.t(message),
        )

    def compare_selected_veteran(self) -> None:
        selected = self.selected_row()
        targets = self._comparison_targets(selected)
        if selected is None or not targets:
            self._show_comparison_error(
                "Ce vétéran n’a aucun remplaçant ou élément de couverture comparable dans le rapport."
            )
            return
        if self._comparison_model:
            dialog = TransferComparisonDialog(
                self.context, selected, targets, self._comparison_model, parent=self,
            )
            if self._decision_examples:
                dialog.select_example(self._decision_examples[self._focused_example])
            dialog.exec()
            return
        source = transfer_comparison_dataset(
            [selected],
            title=self.context.t("Vétéran évalué"),
            provenance=self._provenance,
        )
        coverage = transfer_comparison_dataset(
            targets,
            title=self.context.t("Couverture conservée"),
            provenance=self._provenance,
        )
        ResultComparisonDialog(
            self.context,
            title="Comparer vétéran et couverture",
            left=source,
            right=coverage,
            metrics=TRANSFER_METRICS,
            renderer=self._comparison_renderer,
            lock_left=True,
            parent=self,
        ).exec()

    def start_analysis(self) -> None:
        priority_text = self.context.store.get("skill_priorities_path")
        analysis_mode = str(self.mode_combo.currentData() or "exhaustive")
        self._persist_scope()
        self._state_before_running = self._result_state
        self._running_fingerprint = self._current_fingerprint()
        self._set_result_state(STATE_RUNNING)
        request = TransferRequest(
            master_path=Path(self.context.master_path).expanduser(),
            veterans_json_path=Path(self.context.veterans_json_path).expanduser(),
            output_dir=Path(self.context.output_dir).expanduser(),
            course_overrides_path=active_course_overrides_path(self.context.course_overrides_path),
            use_custom_scoring=self.context.store.get("use_custom_scoring", "0") in {"1", "true", "True"},
            skill_priorities_path=(Path(priority_text).expanduser() if priority_text else None),
            analysis_mode=analysis_mode,
            include_upcoming_cm_context=self.upcoming_cm_check.isChecked(),
            upcoming_cm_limit=self.upcoming_cm_limit.value(),
            include_team_trials=self.team_trials_check.isChecked(),
            include_generic_profiles=self.generic_profiles_check.isChecked(),
        )
        self.task_requested.emit(
            ProcessTask(partial(run_transfer_analysis, request)),
            self.context.t("Analyse Transfer Helper…"),
            self._analysis_done,
        )

    def _analysis_done(self, result: object) -> None:
        self.set_records(list(getattr(result, "records", ()) or ()))
        self._result_fingerprint = self._running_fingerprint
        self._result_origin_state = STATE_READY
        report_path = getattr(result, "report_json_path", None)
        try:
            _payload, self._provenance = read_json_output_revision(
                Path(report_path), CURRENT_REVISION
            )
            self._capture_report_context(_payload)
        except (OSError, TypeError, json.JSONDecodeError, ValueError):
            self._provenance = None
            self._comparison_model = {}
            self._calendar_day = ""
        self._generated_at = format_output_timestamp(
            self._provenance.generated_at_utc if self._provenance else ""
        )
        self._set_result_state(STATE_READY)

    def load_latest(self, *, show_errors: bool = True) -> None:
        self.load_revision(CURRENT_REVISION, show_errors=show_errors)

    def _report_path(self) -> Path:
        return Path(self.context.output_dir).expanduser() / "transfer_helper_report.json"

    def _rebuild_history_menu(self) -> None:
        self.history_menu.clear()
        revisions = available_output_revisions(self._report_path())
        if not revisions:
            action = self.history_menu.addAction(
                self.context.t("Aucune exécution enregistrée")
            )
            action.setEnabled(False)
            return
        for revision in revisions:
            action = self.history_menu.addAction(
                revision_menu_label(revision, self.context.t)
            )
            action.triggered.connect(
                lambda _checked=False, key=revision.key: self.load_revision(
                    key, show_errors=True
                )
            )
        revision_keys = {revision.key for revision in revisions}
        if {CURRENT_REVISION, PREVIOUS_REVISION}.issubset(revision_keys):
            self.history_menu.addSeparator()
            compare = self.history_menu.addAction(
                self.context.t("Comparer courant ↔ précédent")
            )
            compare.triggered.connect(self.compare_history)

    def compare_history(self) -> None:
        try:
            current_payload, current_provenance = read_json_output_revision(
                self._report_path(), CURRENT_REVISION
            )
            previous_payload, previous_provenance = read_json_output_revision(
                self._report_path(), PREVIOUS_REVISION
            )
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            QMessageBox.warning(
                self,
                self.context.t("Comparaison"),
                actionable_error(exc, translate=self.context.t),
            )
            return
        current_records = current_payload.get("records")
        previous_records = previous_payload.get("records")
        if not isinstance(current_records, list) or not isinstance(previous_records, list):
            self._show_comparison_error(
                "Les deux rapports doivent contenir une liste de résultats."
            )
            return
        current = transfer_comparison_dataset(
            (row for row in current_records if isinstance(row, dict)),
            title=self.context.t("Exécution courante"),
            provenance=current_provenance,
        )
        previous = transfer_comparison_dataset(
            (row for row in previous_records if isinstance(row, dict)),
            title=self.context.t("Exécution précédente"),
            provenance=previous_provenance,
        )
        current, previous = intersect_datasets(current, previous)
        if not current.items:
            self._show_comparison_error(
                "Aucun vétéran identifiable n’est commun aux deux exécutions."
            )
            return
        ResultComparisonDialog(
            self.context,
            title="Comparer avant / après recalcul",
            left=previous,
            right=current,
            metrics=TRANSFER_METRICS,
            renderer=self._comparison_renderer,
            match_identities=True,
            parent=self,
        ).exec()

    def load_revision(
        self,
        revision_key: str,
        *,
        show_errors: bool = True,
    ) -> None:
        try:
            payload, provenance = read_json_output_revision(
                self._report_path(), revision_key
            )
            records = payload.get("records")
            if not isinstance(records, list):
                raise ValueError("Le rapport Transfer Helper ne contient pas de liste de résultats.")
            self.set_records([row for row in records if isinstance(row, dict)])
            self._capture_report_context(payload)
            self._provenance = provenance
            self._generated_at = format_output_timestamp(
                provenance.generated_at_utc
            )
            self._result_fingerprint = self._current_fingerprint()
            self._result_origin_state = STATE_LOADED
            self._set_result_state(STATE_LOADED)
            self._refresh_freshness()
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            if show_errors:
                QMessageBox.information(
                    self,
                    self.context.t("Dernier rapport"),
                    actionable_error(exc, translate=self.context.t),
                )

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.run_button.setEnabled(not busy)
        self.load_button.setEnabled(not busy)
        self._update_compare_button()
        if not busy and self._result_state == STATE_RUNNING:
            self._set_result_state(self._state_before_running)

    def open_output(self) -> None:
        output = Path(self.context.output_dir).expanduser()
        try:
            output.mkdir(parents=True, exist_ok=True)
            open_path(output)
        except OSError as exc:
            QMessageBox.critical(
                self,
                self.context.t("Erreur"),
                actionable_error(exc, translate=self.context.t),
            )
