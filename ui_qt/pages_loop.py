from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QScrollArea,
    QTableView,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from loop_engine import (
    LoopEngineError,
    LoopFactorOption,
    add_manual_run,
    analyze_outcome,
    analyze_transition,
    build_target_options,
    close_transition,
    configure_draft,
    detect_transition_runs,
    load_linked_veterans,
    load_skill_catalog,
    rank_parent_candidates,
    rank_parent_pairs,
    record_plan,
    record_run_verdict,
    transition_statistics,
)
from loop_models import LoopProject, LoopSkillTarget, LoopTransition
from loop_repository import (
    LoopProjectRepository,
    LoopRepositoryError,
    loop_projects_path,
)
from parent_optimizer import AffinityResolver, OptimizerError, load_ace_options
from scoring_config import ScoringConfigError, load_effective_scoring_config
from ui_qt.components import (
    PageHeader,
    SearchableComboBox,
    ThemedComboBox,
    muted_label,
)
from ui_qt.context import AppContext
from ui_qt.core import (
    default_scoring_path,
    linked_veterans_path,
    user_scoring_overrides_path,
)
from ui_qt.image_assets import image_repository
from ui_qt.lineage_view import RaceCalendarWidget
from ui_qt.models import Column, ResultTableModel

RIGHT = Qt.AlignmentFlag.AlignRight


def _percent(value: object) -> str:
    try:
        return f"{100.0 * float(value):.1f}%"
    except (TypeError, ValueError):
        return "—"


def _short_date(value: object) -> str:
    text = str(value or "")
    return text[:16].replace("T", " ") if text else "—"


def _in_game_score(value: object) -> str:
    try:
        score = max(0, int(round(float(value))))
    except (TypeError, ValueError):
        return "—"
    return f"{score:,}".replace(",", " ") if score else "—"


def _learned_form_text(value: object) -> str:
    return {
        "normal": "Normal",
        "single_circle": "○",
        "double_circle": "◎",
        "gold": "Gold",
        "unknown": "?",
    }.get(str(value or ""), "—")


class LoopPage(QWidget):
    """Closed-loop MVP for planning and recording White-Spark generations."""

    def __init__(self, context: AppContext, parent=None):
        super().__init__(parent)
        self.context = context
        self._projects: list[LoopProject] = []
        self._active_project: LoopProject | None = None
        self._veterans: list[dict[str, Any]] = []
        self._veteran_by_id: dict[int, dict[str, Any]] = {}
        self._trainee_by_card_id: dict[int, dict[str, Any]] = {}
        self._trainee_context_cache: dict[tuple[int, str, str, str], dict[str, Any]] = {}
        self._factor_options: dict[str, LoopFactorOption] = {}
        self._parent_candidate_rows: list[dict[str, Any]] = []
        self._parent_pair_rows: list[dict[str, Any]] = []
        self._current_plan: dict[str, Any] | None = None
        self._current_outcome: dict[str, Any] | None = None
        self._loading = False
        self._restoring_draft = False
        self._detected_run_count = 0
        try:
            _default, _overrides, self._scoring_config = load_effective_scoring_config(
                default_scoring_path(),
                user_scoring_overrides_path(),
            )
        except (OSError, ScoringConfigError):
            self._scoring_config = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(11)
        self.header = PageHeader("", "")
        root.addWidget(self.header)

        project_panel = QFrame()
        project_panel.setObjectName("panel")
        project_layout = QGridLayout(project_panel)
        project_layout.setContentsMargins(14, 10, 14, 10)
        self.project_label = QLabel("")
        self.project_combo = ThemedComboBox()
        self.project_name = QLineEdit()
        self.new_project_button = QPushButton("")
        self.save_project_button = QPushButton("")
        self.duplicate_project_button = QPushButton("")
        self.delete_project_button = QPushButton("")
        self.refresh_button = QPushButton("")
        self.collection_status = muted_label("")
        project_layout.addWidget(self.project_label, 0, 0)
        project_layout.addWidget(self.project_combo, 0, 1, 1, 2)
        project_layout.addWidget(self.project_name, 0, 3, 1, 2)
        project_layout.addWidget(self.new_project_button, 0, 5)
        project_layout.addWidget(self.save_project_button, 0, 6)
        project_layout.addWidget(self.duplicate_project_button, 0, 7)
        project_layout.addWidget(self.delete_project_button, 0, 8)
        project_layout.addWidget(self.collection_status, 1, 0, 1, 8)
        project_layout.addWidget(self.refresh_button, 1, 8)
        project_layout.setColumnStretch(1, 2)
        project_layout.setColumnStretch(2, 2)
        root.addWidget(project_panel)

        self.tabs = QTabWidget()
        self.plan_tab = QWidget()
        self.outcome_tab = QWidget()
        self.history_tab = QWidget()
        self.tabs.addTab(self.plan_tab, "")
        self.tabs.addTab(self.outcome_tab, "")
        self.tabs.addTab(self.history_tab, "")
        root.addWidget(self.tabs, 1)

        self._build_plan_tab()
        self._build_outcome_tab()
        self._build_history_tab()

        self.project_combo.currentIndexChanged.connect(self._project_selected)
        self.new_project_button.clicked.connect(self.new_project)
        self.save_project_button.clicked.connect(self.save_project)
        self.duplicate_project_button.clicked.connect(self.duplicate_project)
        self.delete_project_button.clicked.connect(self.delete_project)
        self.refresh_button.clicked.connect(lambda: self.refresh(show_errors=True))
        self.trainee_combo.currentIndexChanged.connect(
            lambda _index: self._refresh_parent_recommendations()
        )
        self.trainee_combo.currentIndexChanged.connect(self._draft_selection_changed)
        self.parent_1_combo.currentIndexChanged.connect(self._draft_selection_changed)
        self.parent_2_combo.currentIndexChanged.connect(self._draft_selection_changed)
        self.quality_combo.currentIndexChanged.connect(self._draft_selection_changed)
        self.race_budget.valueChanged.connect(self._draft_selection_changed)
        self.g1_signature.editingFinished.connect(lambda: self._draft_selection_changed(-1))
        self.context.configuration_changed.connect(
            lambda *_args: self.refresh(show_errors=False)
        )
        self.context.language_changed.connect(self._language_changed)
        self.retranslate()
        self.refresh(show_errors=False)

    def _build_plan_tab(self) -> None:
        layout = QVBoxLayout(self.plan_tab)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(10)

        targets = QFrame()
        targets.setObjectName("panel")
        target_layout = QGridLayout(targets)
        target_layout.setContentsMargins(14, 10, 14, 10)
        self.target_title = QLabel("")
        self.target_title.setObjectName("sectionTitle")
        self.target_skill_label = QLabel("")
        self.target_skill = SearchableComboBox()
        self.target_policy_label = QLabel("")
        self.target_policy = ThemedComboBox()
        self.learned_form_label = QLabel("")
        self.learned_form = ThemedComboBox()
        self.acquisition_known = QCheckBox("")
        self.acquisition_probability = QDoubleSpinBox()
        self.acquisition_probability.setRange(0.0, 100.0)
        self.acquisition_probability.setDecimals(1)
        self.acquisition_probability.setValue(100.0)
        self.acquisition_probability.setSuffix(" %")
        self.acquisition_probability.setEnabled(False)
        self.add_target_button = QPushButton("")
        self.remove_target_button = QPushButton("")
        target_layout.addWidget(self.target_title, 0, 0, 1, 8)
        target_layout.addWidget(self.target_skill_label, 1, 0)
        target_layout.addWidget(self.target_skill, 1, 1, 1, 3)
        target_layout.addWidget(self.target_policy_label, 1, 4)
        target_layout.addWidget(self.target_policy, 1, 5, 1, 3)
        target_layout.addWidget(self.learned_form_label, 2, 0)
        target_layout.addWidget(self.learned_form, 2, 1)
        target_layout.addWidget(self.acquisition_known, 2, 2, 1, 2)
        target_layout.addWidget(self.acquisition_probability, 2, 4)
        target_layout.addWidget(self.add_target_button, 2, 6)
        target_layout.addWidget(self.remove_target_button, 2, 7)
        target_layout.setColumnStretch(1, 2)
        target_layout.setColumnStretch(2, 1)

        self.target_table = QTableView()
        self.target_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.target_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.target_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.target_table.verticalHeader().setVisible(False)
        self.target_model = ResultTableModel([], [])
        self.target_table.setModel(self.target_model)
        self.target_table.setMaximumHeight(145)
        target_layout.addWidget(self.target_table, 3, 0, 1, 8)
        layout.addWidget(targets)

        transition = QFrame()
        transition.setObjectName("panel")
        transition_layout = QGridLayout(transition)
        transition_layout.setContentsMargins(14, 10, 14, 10)
        self.transition_title = QLabel("")
        self.transition_title.setObjectName("sectionTitle")
        self.trainee_label = QLabel("")
        self.trainee_combo = SearchableComboBox()
        self.parent_1_label = QLabel("")
        self.parent_1_combo = SearchableComboBox()
        self.parent_2_label = QLabel("")
        self.parent_2_combo = SearchableComboBox()
        self.parent_pair_label = QLabel("")
        self.parent_pair_combo = ThemedComboBox()
        self.apply_pair_button = QPushButton("")
        self.parent_ranking_hint = muted_label("")
        self.quality_label = QLabel("")
        self.quality_combo = ThemedComboBox()
        self.race_budget_label = QLabel("")
        self.race_budget = QSpinBox()
        self.race_budget.setRange(1, 40)
        self.race_budget.setValue(28)
        self.surface_label = QLabel("")
        self.surface_combo = ThemedComboBox()
        self.distance_label = QLabel("")
        self.distance_combo = ThemedComboBox()
        self.style_label = QLabel("")
        self.style_combo = ThemedComboBox()
        self.g1_signature_label = QLabel("")
        self.g1_signature = QLineEdit()
        self.analyze_button = QPushButton("")
        self.analyze_button.setObjectName("primary")
        self.save_plan_button = QPushButton("")
        self.save_plan_button.setEnabled(False)
        transition_layout.addWidget(self.transition_title, 0, 0, 1, 8)
        transition_layout.addWidget(self.trainee_label, 1, 0)
        transition_layout.addWidget(self.trainee_combo, 1, 1, 1, 3)
        transition_layout.addWidget(self.quality_label, 1, 4)
        transition_layout.addWidget(self.quality_combo, 1, 5)
        transition_layout.addWidget(self.race_budget_label, 1, 6)
        transition_layout.addWidget(self.race_budget, 1, 7)
        transition_layout.addWidget(self.surface_label, 2, 0)
        transition_layout.addWidget(self.surface_combo, 2, 1)
        transition_layout.addWidget(self.distance_label, 2, 2)
        transition_layout.addWidget(self.distance_combo, 2, 3)
        transition_layout.addWidget(self.style_label, 2, 4)
        transition_layout.addWidget(self.style_combo, 2, 5, 1, 3)
        transition_layout.addWidget(self.parent_1_label, 3, 0)
        transition_layout.addWidget(self.parent_1_combo, 3, 1, 1, 3)
        transition_layout.addWidget(self.parent_2_label, 3, 4)
        transition_layout.addWidget(self.parent_2_combo, 3, 5, 1, 3)
        transition_layout.addWidget(self.parent_pair_label, 4, 0)
        transition_layout.addWidget(self.parent_pair_combo, 4, 1, 1, 5)
        transition_layout.addWidget(self.apply_pair_button, 4, 6, 1, 2)
        transition_layout.addWidget(self.parent_ranking_hint, 5, 0, 1, 8)
        transition_layout.addWidget(self.g1_signature_label, 6, 0)
        transition_layout.addWidget(self.g1_signature, 6, 1, 1, 5)
        transition_layout.addWidget(self.analyze_button, 6, 6)
        transition_layout.addWidget(self.save_plan_button, 6, 7)
        transition_layout.setColumnStretch(2, 1)
        transition_layout.setColumnStretch(5, 1)
        layout.addWidget(transition)

        self.plan_summary = muted_label("")
        layout.addWidget(self.plan_summary)
        self.g1_summary = muted_label("")
        layout.addWidget(self.g1_summary)
        self.g1_calendar = RaceCalendarWidget(
            self.context,
            {"races": []},
            image_repository(self.context),
        )
        self.g1_calendar_scroll = QScrollArea()
        self.g1_calendar_scroll.setWidgetResizable(False)
        self.g1_calendar_scroll.setWidget(self.g1_calendar)
        self.g1_calendar_scroll.setMinimumHeight(300)
        self.g1_calendar_scroll.setMaximumHeight(470)
        layout.addWidget(self.g1_calendar_scroll)
        self.g1_table = QTableView()
        self.g1_table.setAlternatingRowColors(True)
        self.g1_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.g1_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.g1_table.verticalHeader().setVisible(False)
        self.g1_table.setMaximumHeight(170)
        self.g1_model = ResultTableModel([], [])
        self.g1_table.setModel(self.g1_model)
        layout.addWidget(self.g1_table)
        self.plan_table = QTableView()
        self.plan_table.setAlternatingRowColors(True)
        self.plan_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.plan_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.plan_table.verticalHeader().setVisible(False)
        self.plan_model = ResultTableModel([], [])
        self.plan_table.setModel(self.plan_model)
        layout.addWidget(self.plan_table, 1)

        self.acquisition_known.toggled.connect(self.acquisition_probability.setEnabled)
        self.add_target_button.clicked.connect(self.add_target)
        self.remove_target_button.clicked.connect(self.remove_target)
        self.analyze_button.clicked.connect(self.analyze_plan)
        self.save_plan_button.clicked.connect(self.save_plan)
        self.apply_pair_button.clicked.connect(self.apply_recommended_pair)
        for combo in (self.surface_combo, self.distance_combo, self.style_combo):
            combo.currentIndexChanged.connect(self._aptitude_context_changed)

    def _build_outcome_tab(self) -> None:
        layout = QVBoxLayout(self.outcome_tab)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(10)
        selector = QFrame()
        selector.setObjectName("panel")
        selector_layout = QGridLayout(selector)
        selector_layout.setContentsMargins(14, 10, 14, 10)
        self.outcome_title = QLabel("")
        self.outcome_title.setObjectName("sectionTitle")
        self.pending_label = QLabel("")
        self.pending_combo = ThemedComboBox()
        self.candidate_label = QLabel("")
        self.candidate_combo = SearchableComboBox()
        self.analyze_outcome_button = QPushButton("")
        self.analyze_outcome_button.setObjectName("primary")
        self.close_batch_button = QPushButton("")
        selector_layout.addWidget(self.outcome_title, 0, 0, 1, 7)
        selector_layout.addWidget(self.pending_label, 1, 0)
        selector_layout.addWidget(self.pending_combo, 1, 1, 1, 2)
        selector_layout.addWidget(self.candidate_label, 1, 3)
        selector_layout.addWidget(self.candidate_combo, 1, 4)
        selector_layout.addWidget(self.analyze_outcome_button, 1, 5)
        selector_layout.addWidget(self.close_batch_button, 1, 6)
        selector_layout.setColumnStretch(1, 1)
        selector_layout.setColumnStretch(4, 1)
        layout.addWidget(selector)

        self.outcome_summary = muted_label("")
        layout.addWidget(self.outcome_summary)
        self.batch_stats_summary = muted_label("")
        layout.addWidget(self.batch_stats_summary)
        self.batch_stats_table = QTableView()
        self.batch_stats_table.setAlternatingRowColors(True)
        self.batch_stats_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.batch_stats_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.batch_stats_table.verticalHeader().setVisible(False)
        self.batch_stats_table.setMaximumHeight(190)
        self.batch_stats_model = ResultTableModel([], [])
        self.batch_stats_table.setModel(self.batch_stats_model)
        layout.addWidget(self.batch_stats_table)
        self.batch_runs_table = QTableView()
        self.batch_runs_table.setAlternatingRowColors(True)
        self.batch_runs_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.batch_runs_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.batch_runs_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.batch_runs_table.verticalHeader().setVisible(False)
        self.batch_runs_table.setMaximumHeight(210)
        self.batch_runs_model = ResultTableModel([], [])
        self.batch_runs_table.setModel(self.batch_runs_model)
        layout.addWidget(self.batch_runs_table)
        self.outcome_table = QTableView()
        self.outcome_table.setAlternatingRowColors(True)
        self.outcome_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.outcome_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.outcome_table.verticalHeader().setVisible(False)
        self.outcome_model = ResultTableModel([], [])
        self.outcome_table.setModel(self.outcome_model)
        layout.addWidget(self.outcome_table, 1)

        verdict_panel = QFrame()
        verdict_panel.setObjectName("panel")
        verdict_layout = QGridLayout(verdict_panel)
        verdict_layout.setContentsMargins(14, 10, 14, 10)
        self.verdict_label = QLabel("")
        self.verdict_combo = ThemedComboBox()
        self.branch_label = QLabel("")
        self.branch_combo = ThemedComboBox()
        self.replaces_label = QLabel("")
        self.replaces_combo = ThemedComboBox()
        self.note_label = QLabel("")
        self.note_edit = QTextEdit()
        self.note_edit.setMaximumHeight(62)
        self.record_outcome_button = QPushButton("")
        self.record_outcome_button.setObjectName("primary")
        self.record_outcome_button.setEnabled(False)
        verdict_layout.addWidget(self.verdict_label, 0, 0)
        verdict_layout.addWidget(self.verdict_combo, 0, 1)
        verdict_layout.addWidget(self.branch_label, 0, 2)
        verdict_layout.addWidget(self.branch_combo, 0, 3)
        verdict_layout.addWidget(self.replaces_label, 0, 4)
        verdict_layout.addWidget(self.replaces_combo, 0, 5)
        verdict_layout.addWidget(self.note_label, 1, 0)
        verdict_layout.addWidget(self.note_edit, 1, 1, 1, 4)
        verdict_layout.addWidget(self.record_outcome_button, 1, 5)
        verdict_layout.setColumnStretch(1, 1)
        verdict_layout.setColumnStretch(3, 1)
        verdict_layout.setColumnStretch(5, 1)
        layout.addWidget(verdict_panel)

        self.analyze_outcome_button.clicked.connect(self.analyze_selected_outcome)
        self.close_batch_button.clicked.connect(self.close_selected_batch)
        self.record_outcome_button.clicked.connect(self.record_outcome)
        self.verdict_combo.currentIndexChanged.connect(self._verdict_changed)
        self.pending_combo.currentIndexChanged.connect(lambda _index: self._refresh_batch_views())
        self.batch_runs_table.clicked.connect(lambda _index: self._batch_run_selected())

    def _build_history_tab(self) -> None:
        layout = QVBoxLayout(self.history_tab)
        layout.setContentsMargins(0, 10, 0, 0)
        self.history_summary = muted_label("")
        layout.addWidget(self.history_summary)
        self.history_table = QTableView()
        self.history_table.setAlternatingRowColors(True)
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.history_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.history_table.verticalHeader().setVisible(False)
        self.history_model = ResultTableModel([], [])
        self.history_table.setModel(self.history_model)
        layout.addWidget(self.history_table, 1)

    def _repository(self) -> LoopProjectRepository:
        return LoopProjectRepository(loop_projects_path(self.context.output_dir))

    def _language_changed(self, _language: str) -> None:
        self.retranslate()

    def retranslate(self) -> None:
        t = self.context.t
        self.header.set_text(
            t("White Loop Workshop"),
            t("Planifie une génération sur les six membres, puis rattache le descendant réel au portefeuille du projet."),
        )
        self.project_label.setText(t("Projet"))
        self.project_name.setPlaceholderText(t("Nom du projet de looping"))
        self.new_project_button.setText(t("Nouveau"))
        self.save_project_button.setText(t("Enregistrer le projet"))
        self.duplicate_project_button.setText(t("Dupliquer"))
        self.delete_project_button.setText(t("Supprimer"))
        self.refresh_button.setText(t("Actualiser les données"))
        self.tabs.setTabText(0, t("Planifier"))
        self.tabs.setTabText(1, t("Runs du batch"))
        self.tabs.setTabText(2, t("Historique"))
        self.target_title.setText(t("Cibles White Skill"))
        self.target_skill_label.setText(t("Facteur"))
        self.target_policy_label.setText(t("Politique"))
        self.learned_form_label.setText(t("Forme apprise"))
        self.acquisition_known.setText(t("P(acquisition) connue"))
        self.add_target_button.setText(t("Ajouter / mettre à jour"))
        self.remove_target_button.setText(t("Retirer la cible"))
        self.transition_title.setText(t("Transition suivante"))
        self.trainee_label.setText(t("Trainee"))
        self.parent_1_label.setText(t("Parent 1"))
        self.parent_2_label.setText(t("Parent 2"))
        self.parent_pair_label.setText(t("Duo conseillé"))
        self.apply_pair_button.setText(t("Appliquer le duo"))
        self.surface_label.setText(t("Surface cible"))
        self.distance_label.setText(t("Distance cible"))
        self.style_label.setText(t("Style cible"))
        self.quality_label.setText(t("Qualité visée"))
        self.race_budget_label.setText(t("Budget G1"))
        self.g1_signature_label.setText(t("Signature G1"))
        self.g1_signature.setPlaceholderText(t("Noms séparés par des virgules — facultatif"))
        self.analyze_button.setText(t("Analyser la transition"))
        self.save_plan_button.setText(t("Lancer le batch"))
        self.outcome_title.setText(t("Résultats détectés et statistiques du batch"))
        self.pending_label.setText(t("Batch actif"))
        self.candidate_label.setText(t("Ajout manuel"))
        self.analyze_outcome_button.setText(t("Ajouter / analyser"))
        self.close_batch_button.setText(t("Clore le batch"))
        self.verdict_label.setText(t("Verdict"))
        self.branch_label.setText(t("Branche"))
        self.replaces_label.setText(t("Remplace"))
        self.note_label.setText(t("Note"))
        self.record_outcome_button.setText(t("Enregistrer le verdict"))

        self._reset_choice_combo(
            self.target_policy,
            (("Statique — facteur propre requis", "static"), ("Dynamique", "dynamic")),
        )
        self._reset_choice_combo(
            self.learned_form,
            (("Normale", "normal"), ("◎", "circle"), ("Gold", "gold")),
        )
        self._reset_choice_combo(
            self.quality_combo,
            (("B à < SS", "below_ss"), ("SS à < UE+", "ss_to_ue_plus"), ("UE+", "ue_plus")),
        )
        self._reset_choice_combo(
            self.surface_combo,
            (("Turf", "turf"), ("Dirt", "dirt")),
        )
        self._reset_choice_combo(
            self.distance_combo,
            (("Sprint", "sprint"), ("Mile", "mile"), ("Medium", "medium"), ("Long", "long")),
        )
        self._reset_choice_combo(
            self.style_combo,
            (
                ("Front Runner", "front_runner"),
                ("Pace Chaser", "pace_chaser"),
                ("Late Surger", "late_surger"),
                ("End Closer", "end_closer"),
            ),
        )
        self._reset_choice_combo(
            self.verdict_combo,
            (
                ("Promouvoir Core", "promote_core"),
                ("Remplacer dans le Core", "replace_core"),
                ("Garder en branche secondaire", "keep_side"),
                ("Ignorer", "ignore"),
            ),
        )
        self._reset_choice_combo(
            self.branch_combo,
            (
                ("Core", "core"),
                ("Champions Meeting", "cm"),
                ("Infrastructure pink / Dirt", "pink_infra"),
                ("Blue", "blue"),
                ("Réintroduction", "reintroduction"),
                ("Unique", "unique"),
                ("Personnalisée", "custom"),
            ),
        )
        self._refresh_models()
        self._refresh_parent_recommendations()
        self._refresh_project_combo()
        self._refresh_pending_combo()
        self._refresh_replacement_combo()
        self._verdict_changed()

    def _reset_choice_combo(
        self,
        combo: ThemedComboBox,
        choices: tuple[tuple[str, str], ...],
    ) -> None:
        selected = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        for label, value in choices:
            combo.addItem(self.context.t(label), value)
        index = combo.findData(selected)
        combo.setCurrentIndex(max(index, 0))
        combo.blockSignals(False)

    def refresh(self, *, show_errors: bool = True) -> None:
        if self._loading:
            return
        self._loading = True
        self._trainee_context_cache.clear()
        try:
            _default, _overrides, self._scoring_config = load_effective_scoring_config(
                default_scoring_path(),
                user_scoring_overrides_path(),
            )
        except (OSError, ScoringConfigError):
            self._scoring_config = {}
        active_id = self._active_project.project_id if self._active_project else None
        try:
            try:
                self._projects = self._repository().load()
            except LoopRepositoryError as exc:
                self._projects = []
                if show_errors:
                    QMessageBox.warning(
                        self,
                        self.context.t("Projets de looping"),
                        self.context.t(str(exc)),
                    )

            linked_path = linked_veterans_path(self.context.output_dir)
            try:
                _payload, self._veterans = load_linked_veterans(linked_path)
                self._veteran_by_id = {
                    int(member["trained_chara_id"]): member
                    for member in self._veterans
                    if member.get("trained_chara_id") is not None
                }
                catalog = load_skill_catalog(
                    Path(self.context.output_dir).expanduser() / "skill_condition_catalog.json"
                )
                options = build_target_options(self._veterans, catalog)
                self._factor_options = {option.key: option for option in options}
                detected_total = 0
                projects_changed = False
                for project in self._projects:
                    before = project.updated_at
                    detected = detect_transition_runs(project, self._veterans)
                    detected_total += len(detected)
                    projects_changed = projects_changed or project.updated_at != before
                if projects_changed:
                    self._repository().save(self._projects)
                self._detected_run_count = detected_total
                status = (
                    self.context.t("{count} vétérans liés · {skills} facteurs blancs disponibles")
                    .replace("{count}", str(len(self._veterans)))
                    .replace("{skills}", str(len(options)))
                )
                if detected_total:
                    status += " · " + self.context.t("{count} nouveau(x) run(s) de looping détecté(s)").replace(
                        "{count}", str(detected_total)
                    )
                self.collection_status.setText(status)
            except (LoopEngineError, LoopRepositoryError) as exc:
                self._veterans = []
                self._veteran_by_id = {}
                self._factor_options = {}
                self.collection_status.setText(self.context.t(str(exc)))
            self._load_trainees()
            self._populate_data_combos()
            self._active_project = next(
                (project for project in self._projects if project.project_id == active_id),
                self._projects[0] if self._projects else None,
            )
            self._refresh_project_combo()
            self._load_active_project()
        finally:
            self._loading = False

    def _load_trainees(self) -> None:
        self._trainee_by_card_id = {}
        try:
            for option in load_ace_options(self.context.master_path):
                self._trainee_by_card_id[option.card_id] = {
                    "card_id": option.card_id,
                    "chara_id": option.chara_id,
                    "uma_name": option.uma_name,
                    "card_name": option.card_name,
                    "display_name": option.display_name,
                }
        except (OptimizerError, OSError):
            for veteran in self._veterans:
                card_id = int(veteran.get("card_id") or 0)
                if card_id <= 0:
                    continue
                self._trainee_by_card_id.setdefault(
                    card_id,
                    {
                        **{
                            key: veteran.get(key)
                            for key in ("card_id", "chara_id", "uma_name", "card_name")
                        },
                        "display_name": f"{veteran.get('uma_name')} — {veteran.get('card_name')} ({card_id})",
                    },
                )

    def _trainee_for_current_context(
        self,
        trainee: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if not isinstance(trainee, dict):
            return None
        try:
            card_id = int(trainee.get("card_id") or 0)
        except (TypeError, ValueError):
            return dict(trainee)
        surface = str(self.surface_combo.currentData() or "turf")
        distance = str(self.distance_combo.currentData() or "mile")
        style = str(self.style_combo.currentData() or "late_surger")
        cache_key = (card_id, surface, distance, style)
        cached = self._trainee_context_cache.get(cache_key)
        if cached is not None:
            return copy.deepcopy(cached)
        resolver: AffinityResolver | None = None
        try:
            resolver = AffinityResolver(Path(self.context.master_path).expanduser())
            contextual = {
                **trainee,
                **resolver.ace_details(card_id, surface, distance, style),
                "training_aptitudes": resolver.training_aptitudes(card_id),
                "objective_races": resolver.objective_races(
                    int(trainee.get("chara_id") or 0)
                ),
                "surface": surface,
                "distance": distance,
                "style": style,
            }
        except (OSError, OptimizerError, TypeError, ValueError):
            contextual = {
                **trainee,
                "surface": surface,
                "distance": distance,
                "style": style,
            }
        finally:
            if resolver is not None:
                resolver.close()
        self._trainee_context_cache[cache_key] = copy.deepcopy(contextual)
        return contextual

    def _populate_data_combos(self) -> None:
        selected_factor = self.target_skill.currentData()
        self.target_skill.clear()
        for option in self._factor_options.values():
            self.target_skill.addItem(option.name, option.key)
        self._restore_combo(self.target_skill, selected_factor)

        selected_trainee = self.trainee_combo.currentData()
        self.trainee_combo.clear()
        for card_id, trainee in sorted(
            self._trainee_by_card_id.items(),
            key=lambda item: str(item[1].get("display_name") or "").casefold(),
        ):
            self.trainee_combo.addItem(str(trainee.get("display_name") or card_id), card_id)
        self._restore_combo(self.trainee_combo, selected_trainee)

        selected_candidate = self.candidate_combo.currentData()
        self.candidate_combo.clear()
        for veteran in sorted(
            self._veterans,
            key=lambda item: self._veteran_label(item).casefold(),
        ):
            trained_id = int(veteran.get("trained_chara_id") or 0)
            self.candidate_combo.addItem(self._veteran_label(veteran), trained_id)
        self._restore_combo(self.candidate_combo, selected_candidate)
        self._refresh_parent_recommendations()

    def _refresh_parent_recommendations(self) -> None:
        if not hasattr(self, "parent_1_combo"):
            return
        project = self._active_project
        targets = list(project.targets) if project is not None else []
        trainee = self._trainee_for_current_context(self._trainee_by_card_id.get(
            int(self.trainee_combo.currentData() or 0)
        ))
        selected_left = self.parent_1_combo.currentData()
        selected_right = self.parent_2_combo.currentData()
        self._parent_candidate_rows = rank_parent_candidates(
            self._veterans,
            targets,
            exclude_chara_id=(trainee or {}).get("chara_id"),
            limit=80,
        )
        for combo, selected in (
            (self.parent_1_combo, selected_left),
            (self.parent_2_combo, selected_right),
        ):
            combo.blockSignals(True)
            combo.clear()
            for row in self._parent_candidate_rows:
                combo.addItem(self._parent_candidate_label(row), row["trained_chara_id"])
            self._restore_combo(combo, selected)
            combo.blockSignals(False)

        self._parent_pair_rows = rank_parent_pairs(
            self._veterans,
            targets,
            trainee=trainee,
            surface=str(self.surface_combo.currentData() or "turf"),
            distance=str(self.distance_combo.currentData() or "mile"),
            style=str(self.style_combo.currentData() or "late_surger"),
            aptitude_config=self._scoring_config,
            candidate_limit=40,
            limit=12,
        )
        selected_pair = self.parent_pair_combo.currentData()
        self.parent_pair_combo.blockSignals(True)
        self.parent_pair_combo.clear()
        for row in self._parent_pair_rows:
            self.parent_pair_combo.addItem(
                self._parent_pair_label(row),
                f"{row['parent_1_trained_id']}|{row['parent_2_trained_id']}",
            )
        self._restore_combo(self.parent_pair_combo, selected_pair)
        self.parent_pair_combo.blockSignals(False)

        if targets:
            self.parent_ranking_hint.setText(
                self.context.t(
                    "Duo : 80 % looping White ({count} cibles) + 20 % aptitudes "
                    "surface/distance/style ; le score en jeu sert uniquement au repérage."
                ).replace("{count}", str(len(targets)))
            )
        else:
            self.parent_ranking_hint.setText(
                self.context.t(
                    "Ajoute une cible White Skill pour orienter le looping ; en attendant, "
                    "le score de collection est combiné aux aptitudes du profil."
                )
            )

    def _parent_candidate_label(self, row: dict[str, Any]) -> str:
        return self.context.t(
            "#{position} · {name} · ID {trained_id} · {rank} / {game_score} pts · "
            "reco {score}/100 · "
            "{hits}/{total} cibles"
        ).format(
            position=row.get("rank_position", "—"),
            name=row.get("name") or "Vétéran",
            trained_id=row.get("trained_chara_id") or "?",
            rank=row.get("rank") or "—",
            game_score=_in_game_score(row.get("rank_score")),
            score=f"{float(row.get('heuristic_score') or 0.0):.0f}",
            hits=row.get("direct_hits", 0),
            total=row.get("target_count", 0),
        )

    def _parent_pair_label(self, row: dict[str, Any]) -> str:
        aptitude = row.get("aptitude") or {}
        aptitude_parts = []
        for key in ("surface", "distance", "style"):
            payload = aptitude.get(key) or {}
            target = payload.get("target")
            rank = payload.get("initial_rank_label")
            if target and rank:
                aptitude_parts.append(f"{target} {rank}")
        return self.context.t(
            "#{position} · {left} [ID {left_id} · {left_rank} · {left_game} pts] + "
            "{right} [ID {right_id} · {right_rank} · {right_game} pts] · "
            "reco {score}/100 · apt {aptitude} · {coverage}/{maximum} slots"
        ).format(
            position=row.get("rank_position", "—"),
            left=row.get("parent_1_name") or "Parent 1",
            right=row.get("parent_2_name") or "Parent 2",
            left_id=row.get("parent_1_trained_id") or "?",
            right_id=row.get("parent_2_trained_id") or "?",
            left_rank=row.get("parent_1_rank") or "—",
            right_rank=row.get("parent_2_rank") or "—",
            left_game=_in_game_score(row.get("parent_1_in_game_score")),
            right_game=_in_game_score(row.get("parent_2_in_game_score")),
            score=f"{float(row.get('heuristic_score') or 0.0):.0f}",
            aptitude=" / ".join(aptitude_parts) or "—",
            coverage=row.get("lineage_coverage", 0),
            maximum=row.get("lineage_coverage_max", 0),
        )

    def apply_recommended_pair(self) -> None:
        row_index = self.parent_pair_combo.currentIndex()
        if row_index < 0 or row_index >= len(self._parent_pair_rows):
            return
        row = self._parent_pair_rows[row_index]
        self._restore_combo(
            self.parent_1_combo,
            row.get("parent_1_trained_id"),
        )
        self._restore_combo(
            self.parent_2_combo,
            row.get("parent_2_trained_id"),
        )
        self.collection_status.setText(
            self.context.t("Duo recommandé appliqué : {left} + {right}.")
            .replace("{left}", str(row.get("parent_1_name") or "Parent 1"))
            .replace("{right}", str(row.get("parent_2_name") or "Parent 2"))
        )

    @staticmethod
    def _restore_combo(combo: ThemedComboBox, value: object) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)
        elif combo.count():
            combo.setCurrentIndex(0)

    @staticmethod
    def _veteran_label(veteran: dict[str, Any]) -> str:
        name = veteran.get("card_name") or veteran.get("uma_name") or "Vétéran"
        trained_id = veteran.get("trained_chara_id") or "?"
        rank = veteran.get("rank") or "—"
        score = _in_game_score(veteran.get("rank_score"))
        return f"{name} · ID {trained_id} · {rank} / {score} pts"

    def _refresh_project_combo(self) -> None:
        if not hasattr(self, "project_combo"):
            return
        selected = self._active_project.project_id if self._active_project else None
        self.project_combo.blockSignals(True)
        self.project_combo.clear()
        for project in sorted(self._projects, key=lambda item: item.updated_at, reverse=True):
            self.project_combo.addItem(project.name, project.project_id)
        index = self.project_combo.findData(selected)
        self.project_combo.setCurrentIndex(index if index >= 0 else -1)
        self.project_combo.blockSignals(False)

    def _project_selected(self, _index: int) -> None:
        if self._loading:
            return
        project_id = self.project_combo.currentData()
        self._active_project = next(
            (project for project in self._projects if project.project_id == project_id),
            None,
        )
        self._load_active_project()

    def _load_active_project(self) -> None:
        project = self._active_project
        self._current_plan = None
        self._current_outcome = None
        self.save_plan_button.setEnabled(False)
        self.record_outcome_button.setEnabled(False)
        self._restoring_draft = True
        try:
            if project is None:
                self.project_name.clear()
                self._restore_combo(self.surface_combo, "turf")
                self._restore_combo(self.distance_combo, "mile")
                self._restore_combo(self.style_combo, "late_surger")
                self.race_budget.setValue(28)
                self.g1_signature.clear()
                self.g1_summary.clear()
                self.g1_model.set_rows([])
                self.g1_calendar.set_plan({"races": []})
                self._refresh_models()
                self._refresh_parent_recommendations()
                self._refresh_pending_combo()
                self._refresh_replacement_combo()
                self._refresh_batch_views()
                self.duplicate_project_button.setEnabled(False)
                self.delete_project_button.setEnabled(False)
                return
            self.project_name.setText(project.name)
            self._restore_combo(self.surface_combo, project.surface)
            self._restore_combo(self.distance_combo, project.distance)
            self._restore_combo(self.style_combo, project.style)
            self._restore_combo(self.quality_combo, project.quality_band)
            self.race_budget.setValue(project.race_budget)
            self.g1_signature.setText(", ".join(project.g1_signature))
            self.g1_summary.clear()
            self.g1_model.set_rows([])
            self.g1_calendar.set_plan({"races": []})
            self._refresh_models()
            self._refresh_parent_recommendations()
            self._refresh_pending_combo()
            self._refresh_replacement_combo()
            self.duplicate_project_button.setEnabled(True)
            self.delete_project_button.setEnabled(True)
        finally:
            self._restoring_draft = False
        self._restore_draft()
        self._refresh_batch_views()

    def new_project(self) -> None:
        self._active_project = None
        self.project_combo.setCurrentIndex(-1)
        self.project_name.clear()
        self._load_active_project()
        self.project_name.setFocus()

    def _aptitude_context_changed(self, _index: int) -> None:
        if self._loading:
            return
        self._current_plan = None
        self.save_plan_button.setEnabled(False)
        self.g1_summary.clear()
        self.g1_model.set_rows([])
        self.g1_calendar.set_plan({"races": []})
        self._refresh_parent_recommendations()
        self._persist_draft(last_plan=None)

    def _draft_selection_changed(self, _value: object = None) -> None:
        if self._loading or self._restoring_draft or self._active_project is None:
            return
        self._current_plan = None
        self.save_plan_button.setEnabled(False)
        self._persist_draft(last_plan=None)

    def _persist_draft(self, *, last_plan: dict[str, Any] | None) -> None:
        project = self._active_project
        if project is None or self._loading or self._restoring_draft:
            return
        try:
            self._sync_project_fields(project)
            trainee = self._trainee_by_card_id.get(int(self.trainee_combo.currentData() or 0))
            parent_1 = self._veteran_by_id.get(int(self.parent_1_combo.currentData() or 0))
            parent_2 = self._veteran_by_id.get(int(self.parent_2_combo.currentData() or 0))
            configure_draft(
                project,
                trainee=trainee,
                parent_1=parent_1,
                parent_2=parent_2,
                last_plan=last_plan,
            )
            project_id = project.project_id
            self._projects = self._repository().upsert(project)
            self._active_project = next(
                item for item in self._projects if item.project_id == project_id
            )
        except (LoopEngineError, LoopRepositoryError, ValueError):
            # Draft persistence is opportunistic. Explicit save/analyse actions
            # still surface actionable errors to the user.
            return

    def _restore_draft(self) -> None:
        project = self._active_project
        if project is None or project.draft is None:
            return
        draft = project.draft
        self._restoring_draft = True
        try:
            if draft.trainee_card_id is not None:
                index = self.trainee_combo.findData(draft.trainee_card_id)
                if index >= 0:
                    self.trainee_combo.setCurrentIndex(index)
            self._refresh_parent_recommendations()
            for combo, value in (
                (self.parent_1_combo, draft.parent_1_trained_id),
                (self.parent_2_combo, draft.parent_2_trained_id),
            ):
                if value is None:
                    continue
                index = combo.findData(value)
                if index >= 0:
                    combo.setCurrentIndex(index)
            if isinstance(draft.last_plan, dict):
                self._current_plan = copy.deepcopy(draft.last_plan)
                self.plan_model.set_rows(list(self._current_plan.get("skills") or []))
                self._set_g1_plan(self._current_plan.get("g1") or {})
                self.save_plan_button.setEnabled(True)
        finally:
            self._restoring_draft = False

    def _sync_project_fields(self, project: LoopProject) -> None:
        previous_inputs = (
            project.surface,
            project.distance,
            project.style,
            project.quality_band,
            project.race_budget,
            tuple(project.g1_signature),
        )
        name = self.project_name.text().strip()
        if not name:
            raise LoopEngineError("Donne un nom au projet de looping.")
        project.name = name
        project.surface = str(self.surface_combo.currentData() or "turf")
        project.distance = str(self.distance_combo.currentData() or "mile")
        project.style = str(self.style_combo.currentData() or "late_surger")
        project.quality_band = str(self.quality_combo.currentData() or "ss_to_ue_plus")
        project.race_budget = self.race_budget.value()
        project.g1_signature = [
            value.strip()
            for value in self.g1_signature.text().split(",")
            if value.strip()
        ]
        project.touch()
        if previous_inputs != (
            project.surface,
            project.distance,
            project.style,
            project.quality_band,
            project.race_budget,
            tuple(project.g1_signature),
        ):
            self._current_plan = None
            self.save_plan_button.setEnabled(False)
            self.g1_summary.clear()
            self.g1_model.set_rows([])
            self.g1_calendar.set_plan({"races": []})

    def _ensure_project(self) -> LoopProject:
        if self._active_project is None:
            self._active_project = LoopProject.create(self.project_name.text().strip())
        self._sync_project_fields(self._active_project)
        return self._active_project

    def save_project(self) -> None:
        try:
            project = self._ensure_project()
            self._projects = self._repository().upsert(project)
            self._active_project = next(
                item for item in self._projects if item.project_id == project.project_id
            )
            self._refresh_project_combo()
            self._refresh_models()
            self._refresh_parent_recommendations()
            self._refresh_pending_combo()
            self._refresh_replacement_combo()
            self.duplicate_project_button.setEnabled(True)
            self.delete_project_button.setEnabled(True)
            self.collection_status.setText(self.context.t("Projet de looping enregistré."))
        except (LoopEngineError, LoopRepositoryError, ValueError) as exc:
            QMessageBox.warning(self, self.context.t("Projet de looping"), self.context.t(str(exc)))

    def duplicate_project(self) -> None:
        try:
            if self._active_project is None:
                raise LoopEngineError("Sélectionne un projet de looping.")
            self._sync_project_fields(self._active_project)
            self._projects = self._repository().upsert(self._active_project)
            self._active_project = next(
                item
                for item in self._projects
                if item.project_id == self._active_project.project_id
            )
            duplicate = LoopProject.create(
                f"{self._active_project.name} ({self.context.t('copie')})"
            )
            duplicate.targets = copy.deepcopy(self._active_project.targets)
            duplicate.surface = self._active_project.surface
            duplicate.distance = self._active_project.distance
            duplicate.style = self._active_project.style
            duplicate.quality_band = self._active_project.quality_band
            duplicate.race_budget = self._active_project.race_budget
            duplicate.g1_signature = list(self._active_project.g1_signature)
            self._projects = self._repository().upsert(duplicate)
            self._active_project = next(
                item for item in self._projects if item.project_id == duplicate.project_id
            )
            self._refresh_project_combo()
            self._load_active_project()
            self.collection_status.setText(self.context.t("Projet dupliqué."))
        except (LoopEngineError, LoopRepositoryError, ValueError) as exc:
            QMessageBox.warning(self, self.context.t("Projet de looping"), self.context.t(str(exc)))

    def delete_project(self) -> None:
        if self._active_project is None:
            return
        project = self._active_project
        answer = QMessageBox.question(
            self,
            self.context.t("Supprimer le projet"),
            self.context.t(
                "Supprimer « {name} » et son historique de transitions ? Cette action retire aussi sa protection de porteurs."
            ).replace("{name}", project.name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self._projects = self._repository().delete(project.project_id)
            self._active_project = self._projects[0] if self._projects else None
            self._refresh_project_combo()
            self._load_active_project()
            self.collection_status.setText(self.context.t("Projet supprimé."))
        except LoopRepositoryError as exc:
            QMessageBox.warning(self, self.context.t("Projets de looping"), self.context.t(str(exc)))

    def add_target(self) -> None:
        try:
            project = self._ensure_project()
            if not self.target_skill.resolve_current_text():
                raise LoopEngineError("Sélectionne un facteur blanc cible.")
            option = self._factor_options.get(str(self.target_skill.currentData() or ""))
            if option is None:
                raise LoopEngineError("Le facteur blanc sélectionné est introuvable.")
            acquisition = (
                self.acquisition_probability.value() / 100.0
                if self.acquisition_known.isChecked()
                else None
            )
            target = LoopSkillTarget(
                key=option.key,
                name=option.name,
                factor_group_id=option.factor_group_id,
                skill_id=option.skill_id,
                policy=str(self.target_policy.currentData() or "dynamic"),
                learned_form=str(self.learned_form.currentData() or "normal"),
                acquisition_probability=acquisition,
            )
            for index, existing in enumerate(project.targets):
                if existing.key == target.key:
                    project.targets[index] = target
                    break
            else:
                project.targets.append(target)
            project.touch()
            self._projects = self._repository().upsert(project)
            self._active_project = next(
                item for item in self._projects if item.project_id == project.project_id
            )
            self._current_plan = None
            self.save_plan_button.setEnabled(False)
            self._refresh_models()
            self._refresh_parent_recommendations()
        except (LoopEngineError, LoopRepositoryError, ValueError) as exc:
            QMessageBox.warning(self, self.context.t("Cible White Skill"), self.context.t(str(exc)))

    def remove_target(self) -> None:
        if self._active_project is None:
            return
        selected = self.target_table.selectionModel().selectedRows()
        row = self.target_model.row(selected[0].row()) if selected else None
        if row is None:
            return
        key = str(row.get("key") or "")
        self._active_project.targets = [
            target for target in self._active_project.targets if target.key != key
        ]
        self._active_project.touch()
        try:
            self._projects = self._repository().upsert(self._active_project)
            self._active_project = next(
                item
                for item in self._projects
                if item.project_id == self._active_project.project_id
            )
        except LoopRepositoryError as exc:
            QMessageBox.warning(self, self.context.t("Cible White Skill"), self.context.t(str(exc)))
            return
        self._current_plan = None
        self.save_plan_button.setEnabled(False)
        self._refresh_models()
        self._refresh_parent_recommendations()

    def _selected_trainee(self) -> dict[str, Any]:
        if not self.trainee_combo.resolve_current_text():
            raise LoopEngineError("Sélectionne le trainee de la prochaine run.")
        trainee = self._trainee_by_card_id.get(int(self.trainee_combo.currentData() or 0))
        if trainee is None:
            raise LoopEngineError("Le trainee sélectionné est introuvable dans le MDB.")
        return self._trainee_for_current_context(trainee) or trainee

    def _selected_veteran(self, combo: SearchableComboBox) -> dict[str, Any]:
        if not combo.resolve_current_text():
            raise LoopEngineError("Sélectionne un vétéran local valide.")
        veteran = self._veteran_by_id.get(int(combo.currentData() or 0))
        if veteran is None:
            raise LoopEngineError("Le vétéran sélectionné est introuvable dans la collection liée.")
        return veteran

    def _compute_plan(self) -> tuple[LoopProject, dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
        project = self._ensure_project()
        trainee = self._selected_trainee()
        parent_1 = self._selected_veteran(self.parent_1_combo)
        parent_2 = self._selected_veteran(self.parent_2_combo)
        plan = analyze_transition(
            trainee=trainee,
            parent_1=parent_1,
            parent_2=parent_2,
            targets=project.targets,
            quality_band=project.quality_band,
            race_budget=project.race_budget,
            g1_signature=project.g1_signature,
        )
        return project, trainee, parent_1, parent_2, plan

    def analyze_plan(self) -> None:
        try:
            _project, _trainee, _parent_1, _parent_2, plan = self._compute_plan()
            self._current_plan = plan
            self.plan_model.set_rows(list(plan.get("skills") or []))
            self._configure_table(self.plan_table)
            g1 = plan.get("g1") or {}
            self._set_g1_plan(g1)
            summary = self.context.t(
                "Lignée {resolved}/6 · {races} G1 planifiées · bonus optimal +{bonus}."
            )
            summary = (
                summary.replace("{resolved}", str((plan.get("lineage") or {}).get("resolved_slots", 0)))
                .replace("{races}", str(g1.get("scheduled_race_count", 0)))
                .replace("{bonus}", str(g1.get("optimal_bonus", 0)))
            )
            missing = list(g1.get("signature_missing") or [])
            if missing:
                summary += " " + self.context.t("Signature encore absente : {names}.").replace(
                    "{names}", ", ".join(missing)
                )
            warnings = list(plan.get("warnings") or [])
            if warnings:
                summary += " " + " · ".join(self.context.t(item) for item in warnings)
            self.plan_summary.setText(summary)
            self.save_plan_button.setEnabled(True)
            self._persist_draft(last_plan=plan)
        except (LoopEngineError, ValueError) as exc:
            self._current_plan = None
            self.save_plan_button.setEnabled(False)
            QMessageBox.warning(self, self.context.t("Transition de looping"), self.context.t(str(exc)))

    def _set_g1_plan(self, g1: dict[str, Any]) -> None:
        diagnostic = g1.get("diagnostic") if isinstance(g1, dict) else {}
        if not isinstance(diagnostic, dict):
            diagnostic = {}
        variants = diagnostic.get("schedule_variants") or {}
        standard = variants.get("standard") if isinstance(variants, dict) else None
        if not isinstance(standard, dict):
            standard = diagnostic
        self.g1_calendar.set_plan(standard if isinstance(standard, dict) else {"races": []})
        training_aptitudes = diagnostic.get("independent_training_aptitudes") or {}

        def race_aptitudes(race: dict[str, Any]) -> str:
            labels: list[str] = []
            for dimension, key in (
                ("distance", race.get("distance_type")),
                ("surface", race.get("surface")),
            ):
                payload = (training_aptitudes.get(dimension) or {}).get(str(key or ""))
                if not isinstance(payload, dict):
                    continue
                factor_name = payload.get("factor_name") or str(key or "").title()
                rank = payload.get("initial_rank_label") or "—"
                labels.append(f"{factor_name} {rank}")
            return " + ".join(labels) or "—"

        rows: list[dict[str, Any]] = []
        for race in standard.get("scheduled_races") or []:
            if not isinstance(race, dict):
                continue
            planned = race.get("planned_slot") or {}
            rows.append(
                {
                    "year": planned.get("year"),
                    "month": planned.get("month"),
                    "half": planned.get("half"),
                    "name": race.get("name") or "—",
                    "bonus": (
                        race.get("effective_affinity_bonus")
                        if race.get("effective_affinity_bonus") is not None
                        else race.get("affinity_bonus") or 0
                    ),
                    "sources": list(race.get("sources") or []),
                    "shared": bool(race.get("shared")),
                    "objective": bool(race.get("mandatory_objective")),
                    "aptitudes": race_aptitudes(race),
                    "win_probability": (
                        race.get("independent_training_effective_win_probability")
                        if race.get("independent_training_effective_win_probability") is not None
                        else race.get("independent_training_base_win_probability")
                    ),
                    "cutoff_passed": race.get("independent_training_cutoff_passed"),
                    "streak": int(race.get("consecutive_race_count") or 0),
                    "warning": bool(race.get("long_streak_warning")),
                }
            )
        rows.sort(
            key=lambda row: (
                int(row.get("year") or 99),
                int(row.get("month") or 99),
                int(row.get("half") or 99),
                str(row.get("name") or "").casefold(),
            )
        )
        self.g1_model.set_rows(rows)
        self._configure_table(self.g1_table)
        if not rows:
            self.g1_summary.setText(self.context.t("Aucun planning G1 exploitable pour ce duo."))
            return
        summary = (
            self.context.t(
                "Planning G1 optimal : {count} courses · bonus +{bonus} · "
                "{objectives} objectif(s) · {excluded} course(s) non retenue(s)."
            )
            .replace("{count}", str(len(rows)))
            .replace("{bonus}", str(standard.get("optimal_bonus") or 0))
            .replace("{objectives}", str(standard.get("scheduled_objective_race_count") or 0))
            .replace("{excluded}", str(standard.get("excluded_race_count") or 0))
        )
        cutoff = diagnostic.get("g1_win_probability_cutoff")
        if cutoff is not None:
            excluded = list(standard.get("excluded_races") or [])
            below_cutoff = sum(
                race.get("planning_status") == "below_win_cutoff"
                for race in excluded
                if isinstance(race, dict)
            )
            summary += " " + self.context.t(
                "Seuil aptitude G1 {cutoff} · {count} course(s) sous le seuil."
            ).replace("{cutoff}", _percent(cutoff)).replace("{count}", str(below_cutoff))
        self.g1_summary.setText(summary)

    def save_plan(self) -> None:
        try:
            project, trainee, parent_1, parent_2, plan = self._compute_plan()
            trainee_card_id = int(trainee.get("card_id") or 0) or None
            parent_ids = {
                int(parent_1.get("trained_chara_id") or 0),
                int(parent_2.get("trained_chara_id") or 0),
            }
            for other_project in self._projects:
                if other_project.project_id == project.project_id:
                    continue
                for active in other_project.transitions:
                    if not active.active:
                        continue
                    if trainee_card_id is not None and active.trainee_card_id != trainee_card_id:
                        continue
                    if {active.parent_1_trained_id, active.parent_2_trained_id} != parent_ids:
                        continue
                    message = self.context.t(
                        "Un batch identique est déjà actif dans le projet {project} ; "
                        "clôture-le avant d’en lancer un autre."
                    ).replace("{project}", other_project.name)
                    raise LoopEngineError(message)
            transition = record_plan(
                project,
                trainee=trainee,
                parent_1=parent_1,
                parent_2=parent_2,
                plan=plan,
                baseline_trained_ids=self._veteran_by_id.keys(),
            )
            self._projects = self._repository().upsert(project)
            self._active_project = next(
                item for item in self._projects if item.project_id == project.project_id
            )
            self._current_plan = plan
            self._refresh_project_combo()
            self._refresh_pending_combo(selected_id=transition.transition_id)
            self._refresh_replacement_combo()
            self._refresh_models()
            self.tabs.setCurrentWidget(self.outcome_tab)
            QMessageBox.information(
                self,
                self.context.t("Transition enregistrée"),
                self.context.t("Le batch est actif ; les deux parents sont maintenant protégés et les nouveaux résultats seront détectés automatiquement."),
            )
        except (LoopEngineError, LoopRepositoryError, ValueError) as exc:
            QMessageBox.warning(self, self.context.t("Transition de looping"), self.context.t(str(exc)))

    def _refresh_pending_combo(self, selected_id: str | None = None) -> None:
        if not hasattr(self, "pending_combo"):
            return
        selected = selected_id or self.pending_combo.currentData()
        self.pending_combo.blockSignals(True)
        self.pending_combo.clear()
        if self._active_project is not None:
            for transition in reversed(self._active_project.transitions):
                if transition.status != "pending":
                    continue
                label = (
                    f"{transition.trainee_name} · #{transition.parent_1_trained_id} × "
                    f"#{transition.parent_2_trained_id} · {len(transition.runs)} run(s) · "
                    f"{_short_date(transition.created_at)}"
                )
                self.pending_combo.addItem(label, transition.transition_id)
        index = self.pending_combo.findData(selected)
        self.pending_combo.setCurrentIndex(index if index >= 0 else (0 if self.pending_combo.count() else -1))
        self.pending_combo.blockSignals(False)
        self._refresh_batch_views()

    def _pending_transition(self) -> LoopTransition:
        if self._active_project is None:
            raise LoopEngineError("Sélectionne un projet de looping.")
        transition = self._active_project.transition(str(self.pending_combo.currentData() or ""))
        if transition is None or transition.status != "pending":
            raise LoopEngineError("Sélectionne une transition de looping en cours.")
        return transition

    def _refresh_batch_views(self) -> None:
        if not hasattr(self, "batch_stats_model"):
            return
        try:
            transition = self._pending_transition()
        except LoopEngineError:
            self.batch_stats_model.set_rows([])
            self.batch_runs_model.set_rows([])
            self.batch_stats_summary.clear()
            self.outcome_summary.clear()
            self.close_batch_button.setEnabled(False)
            return
        stats = transition_statistics(transition)
        self.batch_stats_model.set_rows(list(stats.get("target_stats") or []))
        run_rows: list[dict[str, Any]] = []
        for run in reversed(transition.runs):
            generated = []
            acquired = []
            for row in run.analysis.get("skills") or []:
                if not isinstance(row, dict):
                    continue
                if row.get("skill_acquired"):
                    form = _learned_form_text(row.get("acquired_form"))
                    acquired.append(f"{row.get('name') or 'Skill'} [{form}]")
                if row.get("factor_generated", row.get("own_factor_present")):
                    generated.append(
                        f"{row.get('name') or 'Factor'} {int(row.get('factor_stars', row.get('own_factor_stars')) or 0)}★"
                    )
            snapshot = run.snapshot
            run_rows.append(
                {
                    "trained_chara_id": run.trained_chara_id,
                    "detected_at": run.detected_at,
                    "rank": snapshot.get("rank") or "—",
                    "rank_score": snapshot.get("rank_score"),
                    "acquired": ", ".join(acquired) or ("—" if run.learned_skills_known else "?"),
                    "generated": ", ".join(generated) or "—",
                    "verdict": run.verdict,
                    "auto_detected": run.auto_detected,
                }
            )
        self.batch_runs_model.set_rows(run_rows)
        summary = self.context.t(
            "{runs} run(s) · facteur cible sur {generated} · ≥2★ sur {two_plus} · statiques complètes sur {static}."
        )
        self.batch_stats_summary.setText(
            summary.replace("{runs}", str(stats.get("run_count", 0)))
            .replace("{generated}", str(stats.get("any_factor_generated_count", 0)))
            .replace("{two_plus}", str(stats.get("any_factor_two_plus_count", 0)))
            .replace("{static}", str(stats.get("all_static_generated_count", 0)))
        )
        self.close_batch_button.setEnabled(True)
        self._configure_table(self.batch_stats_table)
        self._configure_table(self.batch_runs_table)

    def _batch_run_selected(self) -> None:
        selected = self.batch_runs_table.selectionModel().selectedRows()
        row = self.batch_runs_model.row(selected[0].row()) if selected else None
        if not isinstance(row, dict):
            return
        trained_id = int(row.get("trained_chara_id") or 0)
        self._restore_combo(self.candidate_combo, trained_id)
        try:
            transition = self._pending_transition()
        except LoopEngineError:
            return
        run = transition.run(trained_id)
        if run is not None:
            self._show_run_for_review(transition, run)

    def _show_run_for_review(self, transition: LoopTransition, run) -> None:
        analysis = run.analysis
        self._current_outcome = {
            "transition_id": transition.transition_id,
            "candidate_id": run.trained_chara_id,
            "analysis": analysis,
        }
        self.outcome_model.set_rows(list(analysis.get("skills") or []))
        self._configure_table(self.outcome_table)
        provenance = self.context.t(
            {
                "match": "parents vérifiés",
                "match_snapshot": "parents vérifiés par snapshot",
                "mismatch": "parents différents du plan",
                "unknown": "provenance non résolue",
            }.get(str(analysis.get("parent_provenance")), "provenance non résolue")
        )
        summary = self.context.t(
            "Run #{run} · {hits} facteur(s) cible propre(s), {static}/{total} statiques · {provenance}."
        )
        self.outcome_summary.setText(
            summary.replace("{run}", str(run.trained_chara_id))
            .replace("{hits}", str(analysis.get("own_target_hit_count", 0)))
            .replace("{static}", str(analysis.get("static_hit_count", 0)))
            .replace("{total}", str(analysis.get("static_target_count", 0)))
            .replace("{provenance}", provenance)
        )
        suggested = run.verdict or str(analysis.get("suggested_verdict") or "")
        if suggested in {"promote_core", "replace_core", "keep_side", "ignore"}:
            self._restore_combo(self.verdict_combo, suggested)
        if run.branch:
            self._restore_combo(self.branch_combo, run.branch)
        if run.replaces_trained_chara_id is not None:
            self._restore_combo(self.replaces_combo, run.replaces_trained_chara_id)
        self.note_edit.setPlainText(run.note)
        self.record_outcome_button.setEnabled(not bool(run.reviewed_at))
        self._verdict_changed()

    def close_selected_batch(self) -> None:
        try:
            if self._active_project is None:
                raise LoopEngineError("Sélectionne un projet de looping.")
            transition = self._pending_transition()
            close_transition(self._active_project, transition_id=transition.transition_id)
            project_id = self._active_project.project_id
            self._projects = self._repository().upsert(self._active_project)
            self._active_project = next(
                item for item in self._projects if item.project_id == project_id
            )
            self._current_outcome = None
            self.outcome_model.set_rows([])
            self.record_outcome_button.setEnabled(False)
            self._refresh_pending_combo()
            self._refresh_models()
            self._refresh_batch_views()
        except (LoopEngineError, LoopRepositoryError) as exc:
            QMessageBox.warning(self, self.context.t("Batch de looping"), self.context.t(str(exc)))

    def analyze_selected_outcome(self) -> None:
        try:
            if self._active_project is None:
                raise LoopEngineError("Sélectionne un projet de looping.")
            transition = self._pending_transition()
            candidate = self._selected_veteran(self.candidate_combo)
            analysis = analyze_outcome(outcome=candidate, plan=transition.plan)
            if analysis.get("parent_provenance") == "mismatch":
                raise LoopEngineError(
                    "Le descendant n’utilise pas les deux parents de ce batch."
                )
            if analysis.get("trainee_provenance") == "mismatch":
                raise LoopEngineError(
                    "Le descendant ne correspond pas au trainee planifié."
                )
            run = add_manual_run(
                self._active_project,
                transition_id=transition.transition_id,
                outcome=candidate,
            )
            project_id = self._active_project.project_id
            self._projects = self._repository().upsert(self._active_project)
            self._active_project = next(
                item for item in self._projects if item.project_id == project_id
            )
            transition = self._active_project.transition(transition.transition_id) or transition
            run = transition.run(run.trained_chara_id) or run
            self._refresh_batch_views()
            self._show_run_for_review(transition, run)
        except (LoopEngineError, LoopRepositoryError) as exc:
            self._current_outcome = None
            self.record_outcome_button.setEnabled(False)
            QMessageBox.warning(self, self.context.t("Résultat de looping"), self.context.t(str(exc)))

    def _refresh_replacement_combo(self) -> None:
        if not hasattr(self, "replaces_combo"):
            return
        selected = self.replaces_combo.currentData()
        self.replaces_combo.clear()
        if self._active_project is not None:
            for carrier in self._active_project.carriers:
                if not carrier.active or carrier.branch != "core" or carrier.trained_chara_id is None:
                    continue
                name = carrier.snapshot.get("card_name") or carrier.snapshot.get("uma_name") or "Vétéran"
                self.replaces_combo.addItem(f"{name} · #{carrier.trained_chara_id}", carrier.trained_chara_id)
        self._restore_combo(self.replaces_combo, selected)

    def _verdict_changed(self) -> None:
        if not hasattr(self, "verdict_combo"):
            return
        verdict = str(self.verdict_combo.currentData() or "")
        self.replaces_combo.setEnabled(verdict == "replace_core")
        self.branch_combo.setEnabled(verdict == "keep_side")

    def record_outcome(self) -> None:
        try:
            if self._active_project is None:
                raise LoopEngineError("Sélectionne un projet de looping.")
            transition = self._pending_transition()
            if not isinstance(self._current_outcome, dict):
                raise LoopEngineError("Sélectionne d’abord un résultat du batch.")
            trained_id = int(self._current_outcome.get("candidate_id") or 0)
            run = transition.run(trained_id)
            if run is None:
                raise LoopEngineError("Ce résultat n’appartient plus au batch sélectionné.")
            analysis = run.analysis
            if analysis.get("parent_provenance") == "mismatch":
                raise LoopEngineError(
                    "Le descendant n’utilise pas les deux parents de ce batch."
                )
            if analysis.get("trainee_provenance") == "mismatch":
                raise LoopEngineError(
                    "Le descendant ne correspond pas au trainee planifié."
                )
            verdict = str(self.verdict_combo.currentData() or "")
            branch = str(self.branch_combo.currentData() or "custom")
            replacement = (
                int(self.replaces_combo.currentData())
                if verdict == "replace_core" and self.replaces_combo.currentData() is not None
                else None
            )
            record_run_verdict(
                self._active_project,
                transition_id=transition.transition_id,
                trained_chara_id=trained_id,
                verdict=verdict,
                branch=branch,
                replaces_trained_chara_id=replacement,
                note=self.note_edit.toPlainText().strip(),
            )
            project_id = self._active_project.project_id
            transition_id = transition.transition_id
            self._projects = self._repository().upsert(self._active_project)
            self._active_project = next(
                item for item in self._projects if item.project_id == project_id
            )
            self._current_outcome = None
            self.note_edit.clear()
            self.outcome_model.set_rows([])
            self.record_outcome_button.setEnabled(False)
            self._refresh_project_combo()
            self._refresh_pending_combo(selected_id=transition_id)
            self._refresh_replacement_combo()
            self._refresh_models()
            self._refresh_batch_views()
        except (LoopEngineError, LoopRepositoryError, ValueError) as exc:
            QMessageBox.warning(self, self.context.t("Résultat de looping"), self.context.t(str(exc)))

    def _refresh_models(self) -> None:
        t = self.context.t
        project = self._active_project
        targets = [target.to_dict() for target in (project.targets if project else [])]
        self.target_model.set_columns(
            [
                Column(t("White Skill"), lambda row: row.get("name") or "—"),
                Column(t("Politique"), lambda row: t("Statique") if row.get("policy") == "static" else t("Dynamique")),
                Column(t("Forme"), lambda row: {"normal": t("Normale"), "circle": "◎", "gold": "Gold"}.get(str(row.get("learned_form")), "—")),
                Column(t("P(acquisition)"), lambda row: _percent(row.get("acquisition_probability")), RIGHT),
            ]
        )
        self.target_model.set_rows(targets)
        self.g1_model.set_columns(
            [
                Column(
                    t("Tour"),
                    lambda row: (
                        f"G{row.get('year') or '?'} · M{row.get('month') or '?'} / "
                        f"S{row.get('half') or '?'}"
                    ),
                ),
                Column(t("Course"), lambda row: row.get("name") or "—"),
                Column(t("Prime"), lambda row: f"+{row.get('bonus', 0)}", RIGHT),
                Column(
                    t("Origines"),
                    lambda row: " + ".join(row.get("sources") or []) or "—",
                ),
                Column(
                    t("Nature"),
                    lambda row: t("Objectif") if row.get("objective") else t("Affinité"),
                ),
                Column(t("Aptitudes"), lambda row: row.get("aptitudes") or "—"),
                Column(
                    t("P(victoire)"),
                    lambda row: _percent(row.get("win_probability")),
                    RIGHT,
                ),
                Column(
                    t("Risque série"),
                    lambda row: (
                        t("Série de {count}").replace(
                            "{count}", str(row.get("streak") or 0)
                        )
                        if row.get("warning")
                        else "—"
                    ),
                ),
            ]
        )
        self.plan_model.set_columns(
            [
                Column(t("White Skill"), lambda row: row.get("name") or "—"),
                Column(t("Politique"), lambda row: t("Statique") if row.get("policy") == "static" else t("Dynamique")),
                Column(t("Entrée"), lambda row: f"{row.get('input_coverage', 0)}/6", RIGHT),
                Column(t("Étoiles"), lambda row: row.get("input_star_sum", 0), RIGHT),
                Column(t("P(acquisition)"), lambda row: _percent(row.get("acquisition_probability")), RIGHT),
                Column(t("P(génération | apprise)"), lambda row: _percent(row.get("generation_probability_conditional")), RIGHT),
                Column(t("P(génération complète)"), lambda row: _percent(row.get("generation_probability_full")), RIGHT),
                Column(t("P(≥2★ | apprise)"), lambda row: _percent(row.get("probability_two_plus_conditional")), RIGHT),
                Column(t("P(≥2★ complète)"), lambda row: _percent(row.get("probability_two_plus_full")), RIGHT),
                Column(t("Sortie miss → hit"), lambda row: f"{row.get('output_coverage_if_miss', 0)}/3 → {row.get('output_coverage_if_hit', 0)}/3", RIGHT),
            ]
        )
        self.outcome_model.set_columns(
            [
                Column(t("White Skill"), lambda row: row.get("name") or "—"),
                Column(t("Politique"), lambda row: t("Statique") if row.get("policy") == "static" else t("Dynamique")),
                Column(
                    t("Skill acquis"),
                    lambda row: (
                        "?"
                        if row.get("skill_acquired") is None
                        else t("Oui") if row.get("skill_acquired") else t("Non")
                    ),
                ),
                Column(t("Forme acquise"), lambda row: _learned_form_text(row.get("acquired_form"))),
                Column(t("Facteur généré"), lambda row: t("Oui") if row.get("factor_generated", row.get("own_factor_present")) else t("Non")),
                Column(t("Étoiles facteur"), lambda row: row.get("factor_stars", row.get("own_factor_stars", 0)), RIGHT),
                Column(t("Couverture sortie"), lambda row: f"{row.get('output_coverage', 0)}/3", RIGHT),
                Column(t("Gate statique"), lambda row: "—" if row.get("hard_gate_passed") is None else (t("OK") if row.get("hard_gate_passed") else t("Échec"))),
            ]
        )
        self.batch_stats_model.set_columns(
            [
                Column(t("White Skill"), lambda row: row.get("name") or "—"),
                Column(t("Runs"), lambda row: row.get("run_count", 0), RIGHT),
                Column(t("Acquisition"), lambda row: _percent(row.get("acquisition_rate")), RIGHT),
                Column(
                    t("Formes acquises"),
                    lambda row: " / ".join(
                        f"{_learned_form_text(key)}:{value}"
                        for key, value in (row.get("acquired_form_counts") or {}).items()
                        if value
                    ) or "—",
                ),
                Column(t("Gen. | acquis"), lambda row: _percent(row.get("factor_generation_rate_given_acquired")), RIGHT),
                Column(t("Gen. / runs"), lambda row: _percent(row.get("factor_generation_rate_all")), RIGHT),
                Column(t("≥2★ / runs"), lambda row: _percent(row.get("factor_two_plus_rate_all")), RIGHT),
                Column(t("3★ / runs"), lambda row: _percent(row.get("factor_three_star_rate_all")), RIGHT),
                Column(t("Théorie | acquis"), lambda row: _percent(row.get("theoretical_generation_conditional")), RIGHT),
                Column(
                    t("Écart"),
                    lambda row: (
                        "—"
                        if row.get("generation_delta_vs_theory") is None
                        else f"{100.0 * float(row.get('generation_delta_vs_theory')):+.1f} pts"
                    ),
                    RIGHT,
                ),
            ]
        )
        self.batch_runs_model.set_columns(
            [
                Column(t("Date"), lambda row: _short_date(row.get("detected_at"))),
                Column(t("ID"), lambda row: f"#{row.get('trained_chara_id')}", RIGHT),
                Column(t("Rang"), lambda row: row.get("rank") or "—"),
                Column(t("Score"), lambda row: _in_game_score(row.get("rank_score")), RIGHT),
                Column(t("Skills acquis"), lambda row: row.get("acquired") or "—"),
                Column(t("Facteurs cibles"), lambda row: row.get("generated") or "—"),
                Column(t("Verdict"), lambda row: self._verdict_label(str(row.get("verdict") or ""))),
                Column(t("Détection"), lambda row: t("Auto") if row.get("auto_detected") else t("Manuelle")),
            ]
        )
        self.history_model.set_columns(
            [
                Column(t("Date"), lambda row: _short_date(row.get("created_at"))),
                Column(t("Trainee"), lambda row: row.get("trainee_name") or "—"),
                Column(t("Parents"), lambda row: f"#{row.get('parent_1_trained_id')} × #{row.get('parent_2_trained_id')}"),
                Column(t("Statut"), lambda row: t("En cours") if row.get("status") == "pending" else t("Terminée")),
                Column(t("Runs"), lambda row: len(row.get("runs") or []), RIGHT),
                Column(
                    t("Revus"),
                    lambda row: sum(
                        bool(run.get("verdict"))
                        for run in row.get("runs") or []
                        if isinstance(run, dict)
                    ),
                    RIGHT,
                ),
                Column(
                    t("Promotions"),
                    lambda row: sum(
                        run.get("verdict") in {"promote_core", "replace_core"}
                        for run in row.get("runs") or []
                        if isinstance(run, dict)
                    ),
                    RIGHT,
                ),
            ]
        )
        history = [transition.to_dict() for transition in reversed(project.transitions)] if project else []
        self.history_model.set_rows(history)
        active_count = len(project.active_trained_ids()) if project else 0
        pending_count = sum(transition.status == "pending" for transition in project.transitions) if project else 0
        run_count = sum(len(transition.runs) for transition in project.transitions) if project else 0
        self.history_summary.setText(
            t("{active} porteurs actifs · {pending} batch(s) en cours · {total} batch(s) · {runs} run(s) documenté(s).")
            .replace("{active}", str(active_count))
            .replace("{pending}", str(pending_count))
            .replace("{total}", str(len(history)))
            .replace("{runs}", str(run_count))
        )
        for table in (
            self.target_table,
            self.plan_table,
            self.outcome_table,
            self.batch_stats_table,
            self.batch_runs_table,
            self.history_table,
        ):
            self._configure_table(table)

    def _verdict_label(self, verdict: str) -> str:
        return self.context.t(
            {
                "promote_core": "Promouvoir Core",
                "replace_core": "Remplacer dans le Core",
                "keep_side": "Garder en branche secondaire",
                "ignore": "Ignorer",
            }.get(verdict, "—")
        )

    def _branch_label(self, branch: str) -> str:
        return self.context.t(
            {
                "core": "Core",
                "cm": "Champions Meeting",
                "pink_infra": "Infrastructure pink / Dirt",
                "blue": "Blue",
                "reintroduction": "Réintroduction",
                "unique": "Unique",
                "custom": "Personnalisée",
            }.get(branch, "—")
        )

    @staticmethod
    def _configure_table(table: QTableView) -> None:
        header = table.horizontalHeader()
        header.setMinimumSectionSize(64)
        for index in range(table.model().columnCount()):
            header.setSectionResizeMode(index, QHeaderView.ResizeMode.ResizeToContents)
        if table.model().columnCount():
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)

    def set_busy(self, busy: bool) -> None:
        for button in (
            self.new_project_button,
            self.save_project_button,
            self.duplicate_project_button,
            self.delete_project_button,
            self.refresh_button,
            self.add_target_button,
            self.remove_target_button,
            self.analyze_button,
            self.analyze_outcome_button,
            self.close_batch_button,
        ):
            button.setEnabled(not busy)
        self.save_plan_button.setEnabled(not busy and self._current_plan is not None)
        self.record_outcome_button.setEnabled(not busy and self._current_outcome is not None)
