from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from functools import lru_cache, partial
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QListView,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTableView,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from uma_legacy_linker.application import (
    TransferRequest,
    active_course_overrides_path,
    default_scoring_path,
    open_path,
    run_transfer_analysis,
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
from uma_legacy_linker.veteran_identity import (
    canonical_veteran_label,
    format_rank_score,
    technical_veteran_tooltip,
    veteran_name,
)
from ui_qt.accessibility import describe_control, label_control
from ui_qt.avatar import AsyncAvatarProvider
from ui_qt.comparison_dialog import ResultComparisonDialog
from ui_qt.components import ThemedComboBox, muted_label
from ui_qt.context import AppContext
from ui_qt.image_assets import image_repository
from ui_qt.models import Column, ResultTableModel, number
from ui_qt.presentation import transfer_detail_html
from ui_qt.provenance import revision_menu_label
from ui_qt.table_typography import enable_tabular_numbers
from ui_qt.theme import COLORS
from ui_qt.transfer_roster import TransferRosterDelegate, TransferRosterView
from ui_qt.view_state import bind_table_view_state


RIGHT = Qt.AlignmentFlag.AlignRight
STATE_EMPTY = "empty"
STATE_RUNNING = "running"
STATE_READY = "ready"
STATE_STALE = "stale"
STATE_LOADED = "loaded"
STATE_REANALYZE = "reanalyse"
STATE_LABELS = {
    STATE_EMPTY: "Aucun rapport affiché",
    STATE_RUNNING: "Analyse en cours",
    STATE_READY: "Rapport à jour",
    STATE_STALE: "Rapport périmé — les paramètres ont changé",
    STATE_LOADED: "Rapport chargé depuis le disque",
    STATE_REANALYZE: "Rapport ancien — relancer l’analyse",
}
TRANSFER_STATUSES = {"safe_transfer", "recommended_transfer"}
FILTER_LABELS = {"all": "Tout", "transfer": "Transférer", "keep": "Garder"}
CURRENT_REASON_FORMAT = 13


@lru_cache(maxsize=1)
def _locked_icon() -> QIcon:
    pixmap = QPixmap(16, 16)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor(COLORS["muted"]), 1.5))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawArc(4, 1, 8, 10, 0, 180 * 16)
    painter.drawRoundedRect(2, 7, 12, 8, 2, 2)
    painter.drawLine(8, 10, 8, 12)
    painter.end()
    return QIcon(pixmap)


class TransferPage(QWidget):
    task_requested = Signal(object, str, object)

    def __init__(self, context: AppContext, parent=None):
        super().__init__(parent)
        self.context = context
        self._busy = False
        self._records: list[dict[str, Any]] = []
        self._result_state = STATE_EMPTY
        self._result_origin_state = STATE_EMPTY
        self._result_fingerprint = ""
        self._running_fingerprint = ""
        self._state_before_running = STATE_EMPTY
        self._generated_at = ""
        self._calendar_day = ""
        self._calendar_valid_until: datetime | None = None
        self._reason_schema_supported = False
        self._provenance: OutputProvenance | None = None
        self._comparison_model: dict[str, Any] = {}
        self._report_settings: dict[str, Any] = {}
        self._audit_dialog = None

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 24, 18)
        root.setSpacing(12)

        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(8)
        self.result_state = QLabel("")
        self.result_state.setObjectName("pill")
        self.generated_at = muted_label("", wrap=False)
        self.loop_protection_summary = muted_label("", wrap=False)
        self.run_button = QPushButton("")
        self.run_button.setObjectName("primary")
        self.actions_menu = QMenu(self)
        self.history_menu = self.actions_menu.addMenu("")
        self.history_menu.aboutToShow.connect(self._rebuild_history_menu)
        self.scope_action = self.actions_menu.addAction("")
        self.scope_action.triggered.connect(self.open_scope_dialog)
        self.actions_menu.addSeparator()
        self.open_output_action = self.actions_menu.addAction("")
        self.open_output_action.triggered.connect(self.open_output)
        self.menu_button = QPushButton("")
        self.menu_button.setMenu(self.actions_menu)
        status_row.addWidget(self.result_state)
        status_row.addWidget(self.generated_at)
        status_row.addWidget(self.loop_protection_summary)
        status_row.addStretch(1)
        status_row.addWidget(self.run_button)
        status_row.addWidget(self.menu_button)
        root.addLayout(status_row)

        filter_row = QHBoxLayout()
        filter_row.setContentsMargins(0, 0, 0, 0)
        filter_row.setSpacing(6)
        self.filter_group = QButtonGroup(self)
        self.filter_group.setExclusive(True)
        self.filter_buttons: dict[str, QPushButton] = {}
        for key in ("all", "transfer", "keep"):
            button = QPushButton("")
            button.setObjectName("nav")
            button.setCheckable(True)
            self.filter_group.addButton(button)
            self.filter_buttons[key] = button
            filter_row.addWidget(button)
            button.clicked.connect(
                lambda _checked=False, selected=key: self._set_filter(selected)
            )
        stored_filter = self.context.store.get("ui_transfer_filter_v06", "all")
        if stored_filter not in self.filter_buttons:
            stored_filter = "all"
        self.filter_buttons[stored_filter].setChecked(True)
        filter_row.addSpacing(10)
        self.search = QLineEdit()
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(220)
        filter_row.addWidget(self.search, 1)
        root.addLayout(filter_row)

        self.legacy_report_banner = QLabel("")
        self.legacy_report_banner.setObjectName("pillWarning")
        self.legacy_report_banner.setVisible(False)
        root.addWidget(self.legacy_report_banner)

        self.table = QTableView()
        enable_tabular_numbers(self.table)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setSortingEnabled(False)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.model = ResultTableModel([], self._columns())
        self.table.setModel(self.model)
        self._configure_header()
        self._save_table_state = bind_table_view_state(
            self.table,
            self.context.store,
            "ui_table_transfer_v06",
            default_hidden=(),
        )
        self.roster = TransferRosterView()
        self.roster.setObjectName("transferRoster")
        self.roster.setViewMode(QListView.ViewMode.IconMode)
        self.roster.setFlow(QListView.Flow.LeftToRight)
        self.roster.setWrapping(True)
        self.roster.setResizeMode(QListView.ResizeMode.Adjust)
        self.roster.setMovement(QListView.Movement.Static)
        self.roster.setUniformItemSizes(True)
        self.roster.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.roster.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._roster_avatars = AsyncAvatarProvider(
            image_repository(self.context), 92, self
        )
        self._roster_avatars.changed.connect(self.roster.viewport().update)
        self.roster.setItemDelegate(
            TransferRosterDelegate(self.context, self._roster_avatars, self.roster)
        )
        self.roster.setToolTip(self.context.t(
            "Vétérans triés par score décroissant. Double-clique pour ouvrir l’explication."
        ))
        self.views = QStackedWidget()
        self.views.addWidget(self.table)
        self.views.addWidget(self.roster)
        root.addWidget(self.views, 1)

        self.view_group = QButtonGroup(self)
        self.view_group.setExclusive(True)
        self.view_list_button = QPushButton("")
        self.view_grid_button = QPushButton("")
        for button in (self.view_list_button, self.view_grid_button):
            button.setObjectName("nav")
            button.setCheckable(True)
            self.view_group.addButton(button)
        filter_row.addWidget(self.view_list_button)
        filter_row.addWidget(self.view_grid_button)
        self.roster_columns_label = QLabel(self.context.t("Colonnes"))
        self.roster_columns = QSpinBox()
        self.roster_columns.setRange(2, 8)
        try:
            default_columns = int(self.context.store.get("ui_transfer_roster_columns_v01", "5"))
        except (TypeError, ValueError):
            default_columns = 5
        self.roster_columns.setValue(max(2, min(8, default_columns)))
        self.roster_columns.setFixedWidth(64)
        filter_row.addWidget(self.roster_columns_label)
        filter_row.addWidget(self.roster_columns)
        self.roster_columns_label.setVisible(False)
        self.roster_columns.setVisible(False)
        stored_view = self.context.store.get("ui_transfer_view_mode_v01", "list")
        self.view_grid_button.setChecked(stored_view == "grid")
        self.view_list_button.setChecked(stored_view != "grid")
        self.views.setCurrentWidget(self.roster if stored_view == "grid" else self.table)
        self.roster_columns_label.setVisible(stored_view == "grid")
        self.roster_columns.setVisible(stored_view == "grid")
        self.roster.set_fixed_columns(self.roster_columns.value())

        self.run_button.clicked.connect(self.start_analysis)
        self.search.textChanged.connect(self.apply_filters)
        self.table.clicked.connect(self._reason_cell_clicked)
        self.table.activated.connect(lambda index: self.open_audit(self.model.row(index.row())))
        self.table.selectionModel().currentRowChanged.connect(self._selection_changed)
        self.table.customContextMenuRequested.connect(self._show_row_context_menu)
        self.view_list_button.clicked.connect(lambda: self._set_view_mode("list"))
        self.view_grid_button.clicked.connect(lambda: self._set_view_mode("grid"))
        self.roster_columns.valueChanged.connect(self._set_roster_columns)
        self.roster.currentItemChanged.connect(self._roster_selection_changed)
        self.roster.itemActivated.connect(self._roster_item_activated)
        self.roster.customContextMenuRequested.connect(self._show_roster_context_menu)
        self.context.language_changed.connect(self._language_changed)
        self.context.configuration_changed.connect(self._refresh_freshness)
        self.context.lineage_changed.connect(self._refresh_freshness)
        self.setAccessibleName(self.context.t("Transfer Helper"))
        self.retranslate()
        self.load_latest(show_errors=False)

    def _configure_header(self) -> None:
        header = self.table.horizontalHeader()
        header.setMinimumSectionSize(72)
        header.setSectionsMovable(False)
        header.setSectionsClickable(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 116)
        self.table.setColumnWidth(1, 230)
        self.table.setColumnWidth(2, 132)

    def _language_changed(self, _language: str) -> None:
        self.retranslate()

    def _filter_key(self) -> str:
        for key, button in self.filter_buttons.items():
            if button.isChecked():
                return key
        return "all"


    def _reason_label(self, row: dict[str, Any]) -> str:
        reason = row.get("transfer_reason") or {}
        code = str(reason.get("code") or "")
        references = reason.get("refs") or []
        score = lambda ref: format_rank_score(ref.get("rank_score"))
        t = self.context.t
        if code == "replaced_by":
            return t("Remplacée par {score}").replace(
                "{score}", score(references[0]) if references else "—"
            )
        if code == "covered_by":
            if len(references) == 1:
                return t("Couverte par {score}").replace("{score}", score(references[0]))
            if len(references) == 2:
                return (
                    t("Couverte par {first} + {second}")
                    .replace("{first}", score(references[0]))
                    .replace("{second}", score(references[1]))
                )
            return t("Couverte par {count} copies").replace(
                "{count}", str(len(references))
            )
        if code == "outclassed":
            return t("Jamais dans le top")
        if code == "holds_role":
            phrase = t("Tient {subject}").replace(
                "{subject}", str(reason.get("subject") or "")
            )
            more = int(reason.get("more") or 0)
            return phrase + (f" +{more}" if more else "")
        if code == "carries_asset":
            phrase = t("Porte {subject}").replace(
                "{subject}", str(reason.get("subject") or "")
            )
            more = int(reason.get("more") or 0)
            return phrase + (f" +{more}" if more else "")
        if code == "loop_carrier":
            packages = reason.get("loop_packages") or []
            if packages:
                item = packages[0]
                return t("Boucle {preset} {score}/{maximum}").replace(
                    "{preset}", t(str(item.get("preset") or "").title())
                ).replace("{score}", str(item.get("score") or 0)).replace(
                    "{maximum}", str(item.get("maximum") or 0)
                )
            floors = reason.get("loop_floors") or []
            if floors:
                item = floors[0]
                message = "Seule source {skill} ({presence}/3)" if item.get("sole_source") else "Meilleur porteur {skill} ({presence}/3)"
                return t(message).replace("{skill}", str(item.get("skill_name") or "")).replace(
                    "{presence}", str(item.get("presence_count") or 0)
                )
            loop_count = int(reason.get("loop_count") or 0)
            if loop_count > 1:
                return t("Porte {count} boucles").replace("{count}", str(loop_count))
            return t("Porte boucle {subject}").replace(
                "{subject}", str(reason.get("subject") or "")
            )
        if code == "last_copy":
            return t("Dernière copie")
        if code == "protected":
            subject = str(reason.get("subject") or "")
            if subject == "locked_in_game":
                return t("Verrouillée")
            if subject == "memo_present":
                return t("Mémo en jeu")
            return t("Protégée")
        if code == "insufficient":
            return t("À vérifier — couverture insuffisante")
        return ""

    def _reason_tooltip(self, row: dict[str, Any]) -> str:
        reason = row.get("transfer_reason") or {}
        if not reason:
            return ""
        t = self.context.t
        lines: list[str] = []
        for reference in reason.get("refs") or []:
            label = canonical_veteran_label(reference)
            rank_score = format_rank_score(reference.get("rank_score"))
            technical = technical_veteran_tooltip(reference)
            line = f"{rank_score} — {label}"
            if technical:
                line += f" ({technical})"
            lines.append(line)

        raw_gap = reason.get("worst_gap")
        if raw_gap is not None:
            try:
                gap = float(raw_gap)
                gap_text = f"{gap:+.1f}"
                if self.context.language == "fr":
                    gap_text = gap_text.replace(".", ",")
                gap_role = reason.get("gap_role") or {}
                profile = str(gap_role.get("profile") or "")
                if reason.get("code") == "holds_role":
                    loss_text = f"{abs(gap):.1f}"
                    if self.context.language == "fr":
                        loss_text = loss_text.replace(".", ",")
                    detail = t(
                        "Sans elle, la meilleure copie gardée serait à {gap} pt du top."
                    ).replace("{gap}", loss_text)
                else:
                    count = int(reason.get("gap_count") or 0)
                    detail = t("Pire écart parmi {count} rôles : {gap} pt")
                    detail = detail.replace("{count}", str(count)).replace(
                        "{gap}", gap_text
                    )
                    if profile:
                        detail += f" · {profile}"
                lines.append(detail)
            except (TypeError, ValueError):
                pass

        if reason.get("code") == "outclassed" and reason.get("closest_top_gap") is not None:
            try:
                gap = float(reason["closest_top_gap"])
                gap_text = f"{gap:.1f}"
                if self.context.language == "fr":
                    gap_text = gap_text.replace(".", ",")
                profile = str((reason.get("gap_role") or {}).get("profile") or "")
                detail = t("Écart minimal au top : {gap} pt · {profile}")
                lines.append(
                    detail.replace("{gap}", gap_text).replace("{profile}", profile)
                )
            except (TypeError, ValueError):
                pass

        if reason.get("code") == "protected":
            model_reasons = reason.get("model_reasons") or [reason.get("subject")]
            for subject in model_reasons:
                if subject == "locked_in_game":
                    lines.append(t("Protégée par le verrou en jeu."))
                elif subject == "memo_present":
                    lines.append(t("Protégée par un mémo en jeu."))
            if reason.get("model_status") in TRANSFER_STATUSES:
                detail = t("Le modèle la classe comme redondante : {reason}.")
                model_reason = str(reason.get("model_reason") or "").replace("_", " ")
                lines.append(detail.replace("{reason}", model_reason or t("redondante")))
        for loop_skill in reason.get("loop_skills") or []:
            detail = t("{skill} · {presence}/3 présences{direct}")
            detail = detail.replace("{skill}", str(loop_skill.get("label") or ""))
            detail = detail.replace("{presence}", str(loop_skill.get("presence_count") or 0))
            detail = detail.replace(
                "{direct}", " · " + t("Spark directe")
                if loop_skill.get("direct") else " · " + t("branche uniquement")
            )
            lines.append(detail)
            if not loop_skill.get("already_retained_for_performance"):
                lines.append(t("Conservée en plus pour la boucle."))
        for package in reason.get("loop_packages") or []:
            detail = t("Boucle {preset} {score}/{maximum}")
            lines.append(
                detail.replace("{preset}", t(str(package.get("preset") or "").title()))
                .replace("{score}", str(package.get("score") or 0))
                .replace("{maximum}", str(package.get("maximum") or 0))
            )
            if not package.get("already_retained_for_performance"):
                lines.append(t("Conservée en plus pour la boucle."))
        for floor in reason.get("loop_floors") or []:
            message = "Seule source {skill} ({presence}/3)" if floor.get("sole_source") else "Meilleur porteur {skill} ({presence}/3)"
            lines.append(
                t(message).replace("{skill}", str(floor.get("skill_name") or ""))
                .replace("{presence}", str(floor.get("presence_count") or 0))
            )
            if not floor.get("already_retained_for_performance"):
                lines.append(t("Conservée en plus pour la boucle."))
        if reason.get("code") == "insufficient" and reason.get("subject") == "portfolio_coverage_incomplete":
            lines.append(t(
                "La couverture du portefeuille est incomplète : vérification manuelle nécessaire."
            ))
        if not lines and reason.get("subject"):
            lines.append(str(reason["subject"]).replace("_", " "))
        return "\n".join(lines)

    def _verdict_label(self, row: dict[str, Any]) -> str:
        label = "Transférer" if row.get("status") in TRANSFER_STATUSES else "Garder"
        return self.context.t(label)

    def _verdict_tooltip(self, row: dict[str, Any]) -> str:
        key = {
            "safe_transfer": "Transfert strictement sûr",
            "recommended_transfer": "Transfert recommandé",
            "review": "À examiner — garder par prudence",
            "keep": "Nécessaire au portefeuille",
            "protected": "Protégée par verrou ou mémo en jeu",
        }.get(str(row.get("status") or ""), "Garder")
        return self.context.t(key)

    @staticmethod
    def _verdict_color(row: dict[str, Any]) -> QColor:
        status = str(row.get("status") or "")
        if status == "safe_transfer":
            return QColor(COLORS["success"])
        if status in {"recommended_transfer", "review"}:
            return QColor(COLORS["warning"])
        if status == "protected":
            return QColor(COLORS["muted"])
        return QColor(COLORS["info"])

    def _uma_display(self, row: dict[str, Any]) -> str:
        name = str(row.get("uma_name") or veteran_name(row) or "—")
        marker = str(row.get("_duplicate_marker") or "")
        return f"{name} · {marker}" if marker else name

    def _uma_tooltip(self, row: dict[str, Any]) -> str:
        parts = [canonical_veteran_label(row)]
        technical = technical_veteran_tooltip(row)
        if technical:
            parts.append(technical)
        if row.get("_duplicate_marker"):
            parts.append(self.context.t("Une autre copie a le même score en jeu."))
        return "\n".join(parts)

    def _columns(self) -> list[Column]:
        t = self.context.t
        return [
            Column(
                t("Score"),
                lambda row: format_rank_score(row.get("rank_score")),
                RIGHT,
                sort_getter=number("rank_score", default=-1.0),
                tooltip_getter=technical_veteran_tooltip,
            ),
            Column(t("Uma"), self._uma_display, tooltip_getter=self._uma_tooltip),
            Column(
                t("Verdict"),
                self._verdict_label,
                tooltip_getter=self._verdict_tooltip,
                foreground_getter=self._verdict_color,
                decoration_getter=lambda row: _locked_icon() if row.get("is_locked") else QIcon(),
            ),
            Column(
                t("Raison"),
                self._reason_label,
                tooltip_getter=self._reason_tooltip,
            ),
        ]

    def _scope_values(self) -> dict[str, object]:
        store = self.context.store
        try:
            upcoming_limit = int(store.get("transfer_upcoming_cm_limit", "5"))
        except (TypeError, ValueError):
            upcoming_limit = 5
        stored_loop_skills = store.get("transfer_loop_protection_skills", "")
        stored_loop_presets = store.get("transfer_loop_protection_presets", "")
        loop_skills: list[str] | None = None
        try:
            value = json.loads(stored_loop_skills) if isinstance(stored_loop_skills, str) else stored_loop_skills
            if isinstance(value, list) and all(isinstance(item, str) for item in value):
                loop_skills = list(dict.fromkeys(item.strip() for item in value if item.strip()))
        except (TypeError, json.JSONDecodeError):
            loop_skills = None
        if loop_skills is None:
            loop_skills = self._configured_loop_skills()
        loop_presets: list[str] | None = None
        try:
            value = json.loads(stored_loop_presets) if isinstance(stored_loop_presets, str) else stored_loop_presets
            if isinstance(value, list) and all(isinstance(item, str) for item in value):
                loop_presets = list(dict.fromkeys(item.strip() for item in value if item.strip()))
        except (TypeError, json.JSONDecodeError):
            loop_presets = None
        if loop_presets is None:
            loop_presets = self._configured_loop_presets()
        return {
            "analysis_mode": str(store.get("transfer_analysis_mode", "exhaustive")),
            "include_upcoming_cm_context": store.get(
                "transfer_include_upcoming_cm", "1"
            ) in {"1", "true", "True"},
            "upcoming_cm_limit": max(1, min(20, upcoming_limit)),
            "include_team_trials": store.get(
                "transfer_include_team_trials", "0"
            ) in {"1", "true", "True"},
            "include_generic_profiles": store.get(
                "transfer_include_generic_profiles", "0"
            ) in {"1", "true", "True"},
            "loop_protection_skills": loop_skills,
            "loop_protection_presets": loop_presets,
        }

    def _configured_loop_skills(self) -> list[str]:
        active = Path(self.context.output_dir).expanduser() / "active_parent_scoring.json"
        for path in (active, default_scoring_path()):
            try:
                payload = json.loads(path.read_text(encoding="utf-8-sig"))
                skills = (((payload.get("transfer_helper") or {}).get("loop_protection") or {}).get("skills"))
                if isinstance(skills, list):
                    return list(dict.fromkeys(str(key).strip() for key in skills if str(key).strip()))
            except (OSError, json.JSONDecodeError, AttributeError):
                continue
        return []

    def _configured_loop_presets(self) -> list[str]:
        active = Path(self.context.output_dir).expanduser() / "active_parent_scoring.json"
        for path in (active, default_scoring_path()):
            try:
                payload = json.loads(path.read_text(encoding="utf-8-sig"))
                presets = (((payload.get("transfer_helper") or {}).get("loop_protection") or {}).get("presets"))
                if isinstance(presets, list):
                    return list(dict.fromkeys(str(key).strip() for key in presets if str(key).strip()))
            except (OSError, json.JSONDecodeError, AttributeError):
                continue
        return []

    def _loop_skill_catalog(self) -> list[dict[str, Any]]:
        path = Path(self.context.output_dir).expanduser() / "skill_condition_catalog.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return []
        groups = payload.get("white_skill_spark_groups") if isinstance(payload, dict) else None
        return [group for group in groups or [] if isinstance(group, dict) and group.get("catalog_key")]

    def _persist_scope(self, scope: dict[str, object]) -> None:
        loop_skills = scope.get("loop_protection_skills") or []
        loop_presets = scope.get("loop_protection_presets") or []
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
                "transfer_loop_protection_skills": json.dumps(
                    list(loop_skills), ensure_ascii=False
                ),
                "transfer_loop_protection_presets": json.dumps(
                    list(loop_presets), ensure_ascii=False
                ),
            }
        )

    def _current_fingerprint(self) -> str:
        return self.context.transfer_fingerprint(self._scope_values())

    def open_scope_dialog(self) -> None:
        t = self.context.t
        current = self._scope_values()
        dialog = QDialog(self)
        dialog.setWindowTitle(t("Portée de l’analyse"))
        dialog.setMinimumWidth(500)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)

        mode_label = QLabel(t("Mode d’analyse"))
        mode_combo = ThemedComboBox()
        mode_combo.addItem(t("Rapide"), "fast")
        mode_combo.addItem(t("Audit exhaustif (recommandé)"), "exhaustive")
        mode_index = mode_combo.findData(current["analysis_mode"])
        mode_combo.setCurrentIndex(mode_index if mode_index >= 0 else 0)
        mode_combo.setToolTip(t(
            "Le mode rapide repère les redondances ; seul l’audit exhaustif peut conclure à un transfert strictement sûr."
        ))
        label_control(mode_label, mode_combo, mode_combo.toolTip())
        layout.addWidget(mode_label)
        layout.addWidget(mode_combo)

        upcoming = QCheckBox(t("Inclure les prochaines CM"))
        upcoming.setChecked(bool(current["include_upcoming_cm_context"]))
        upcoming_limit = QSpinBox()
        upcoming_limit.setRange(1, 20)
        upcoming_limit.setValue(int(current["upcoming_cm_limit"]))
        upcoming_limit.setSuffix(" " + t("CM max."))
        upcoming_limit.setEnabled(upcoming.isChecked())
        upcoming.toggled.connect(upcoming_limit.setEnabled)
        upcoming.setToolTip(t(
            "Évalue chaque vétéran dans le contexte des prochaines Champion Meetings configurées."
        ))
        upcoming_limit.setToolTip(t(
            "Nombre maximal de prochaines Champion Meetings incluses dans l’analyse."
        ))
        layout.addWidget(upcoming)
        limit_row = QHBoxLayout()
        limit_row.addSpacing(24)
        limit_row.addWidget(upcoming_limit)
        limit_row.addStretch(1)
        layout.addLayout(limit_row)

        team_trials = QCheckBox(t("Inclure Team Trials"))
        team_trials.setChecked(bool(current["include_team_trials"]))
        team_trials.setToolTip(t(
            "Ajoute les rôles des cinq catégories Team Trials aux usages à préserver."
        ))
        generic_profiles = QCheckBox(t("Inclure les profils génériques"))
        generic_profiles.setChecked(bool(current["include_generic_profiles"]))
        generic_profiles.setToolTip(t(
            "Ajoute des profils génériques pour protéger les usages qui ne dépendent pas d’une course planifiée."
        ))
        layout.addWidget(team_trials)
        layout.addWidget(generic_profiles)

        loop_label = QLabel(t("Protéger des boucles de White Sparks"))
        loop_label.setToolTip(t(
            "Conserve les meilleures copies porteuses des White Sparks choisies, en plus des exigences de performance."
        ))
        layout.addWidget(loop_label)
        preset_label = QLabel(t("Presets de boucle (en plus de la sélection libre)"))
        preset_label.setToolTip(t(
            "Chaque preset protège les deux meilleures branches de son package et conserve le meilleur porteur de chaque spark si nécessaire."
        ))
        layout.addWidget(preset_label)
        preset_checks: dict[str, QCheckBox] = {}
        preset_row = QHBoxLayout()
        for key in ("front", "pace", "late", "end"):
            checkbox = QCheckBox(t(key.title()))
            checkbox.setChecked(key in set(current.get("loop_protection_presets") or []))
            checkbox.setToolTip(preset_label.toolTip())
            preset_checks[key] = checkbox
            preset_row.addWidget(checkbox)
        preset_row.addStretch(1)
        layout.addLayout(preset_row)
        describe_control(preset_label, preset_label.text(), preset_label.toolTip())
        for checkbox in preset_checks.values():
            describe_control(checkbox, checkbox.text(), checkbox.toolTip())
        catalog = self._loop_skill_catalog()
        catalog_by_name: dict[str, dict[str, Any]] = {}
        catalog_by_key: dict[str, dict[str, Any]] = {}
        for group in catalog:
            name = str(group.get("spark_name") or group.get("name") or group["catalog_key"])
            catalog_by_name.setdefault(name, group)
            catalog_by_key[str(group["catalog_key"])] = group
        initial_keys = list(current.get("loop_protection_skills") or [])
        selected_loop_list = QListWidget()
        selected_loop_list.setMaximumHeight(112)
        for key in initial_keys:
            group = catalog_by_key.get(key)
            name = str((group or {}).get("spark_name") or (group or {}).get("name") or key)
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, key)
            if group and group.get("direct_support_hint_card_count") == 0:
                item.setText(f"{name} · {t('Aucune carte Support')}")
            selected_loop_list.addItem(item)
        loop_entry = QLineEdit()
        loop_entry.setPlaceholderText(t("Rechercher une White Spark…"))
        loop_entry.setEnabled(bool(catalog))
        loop_entry.setToolTip(loop_label.toolTip())
        completer = QCompleter(sorted(catalog_by_name), dialog)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        loop_entry.setCompleter(completer)
        loop_add = QPushButton(t("Ajouter"))
        loop_remove = QPushButton(t("Retirer"))
        loop_add.setEnabled(bool(catalog))
        loop_remove.setEnabled(True)
        loop_entry_row = QHBoxLayout()
        loop_entry_row.addWidget(loop_entry, 1)
        loop_entry_row.addWidget(loop_add)
        loop_entry_row.addWidget(loop_remove)
        layout.addLayout(loop_entry_row)
        layout.addWidget(selected_loop_list)
        catalog_hint = QLabel(
            t("Catalogue de White Sparks indisponible. Générez-le depuis la page Liens pour choisir des sparks.")
            if not catalog else t("Une spark sans carte Support directe reste sélectionnable.")
        )
        catalog_hint.setWordWrap(True)
        layout.addWidget(catalog_hint)
        describe_control(loop_label, loop_label.text(), loop_label.toolTip())
        describe_control(loop_entry, loop_entry.placeholderText(), loop_entry.toolTip())
        describe_control(catalog_hint, catalog_hint.text())

        def add_loop_skill(_text: str = "") -> None:
            group = catalog_by_name.get(loop_entry.text().strip())
            if group is None:
                group = catalog_by_key.get(loop_entry.text().strip())
            if group is None:
                return
            key = str(group["catalog_key"])
            if any(selected_loop_list.item(i).data(Qt.ItemDataRole.UserRole) == key
                   for i in range(selected_loop_list.count())):
                return
            name = str(group.get("spark_name") or group.get("name") or key)
            if group.get("direct_support_hint_card_count") == 0:
                name = f"{name} · {t('Aucune carte Support')}"
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, key)
            selected_loop_list.addItem(item)
            loop_entry.clear()

        def remove_loop_skill() -> None:
            row = selected_loop_list.currentRow()
            if row >= 0:
                selected_loop_list.takeItem(row)

        loop_add.clicked.connect(lambda _checked=False: add_loop_skill())
        loop_entry.returnPressed.connect(add_loop_skill)
        completer.activated.connect(add_loop_skill)
        loop_remove.clicked.connect(remove_loop_skill)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(t("Appliquer"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(t("Annuler"))
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        describe_control(upcoming, upcoming.text(), upcoming.toolTip())
        describe_control(
            upcoming_limit,
            upcoming.text() + " · " + t("CM max."),
            upcoming_limit.toolTip(),
        )
        describe_control(team_trials, team_trials.text(), team_trials.toolTip())
        describe_control(
            generic_profiles, generic_profiles.text(), generic_profiles.toolTip()
        )

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        selected_loop_skills = [
            str(selected_loop_list.item(i).data(Qt.ItemDataRole.UserRole))
            for i in range(selected_loop_list.count())
        ]
        self._persist_scope({
            "analysis_mode": str(mode_combo.currentData() or "exhaustive"),
            "include_upcoming_cm_context": upcoming.isChecked(),
            "upcoming_cm_limit": upcoming_limit.value(),
            "include_team_trials": team_trials.isChecked(),
            "include_generic_profiles": generic_profiles.isChecked(),
            "loop_protection_skills": selected_loop_skills,
            "loop_protection_presets": [
                key for key, checkbox in preset_checks.items() if checkbox.isChecked()
            ],
        })
        self._refresh_freshness()


    def retranslate(self) -> None:
        t = self.context.t
        self.run_button.setText(t("Analyser"))
        self.run_button.setToolTip(t(
            "Analyse la collection sans modifier ni supprimer aucun vétéran."
        ))
        self.menu_button.setText(t("Menu"))
        self.menu_button.setToolTip(t(
            "Historique, portée de l’analyse et dossier de sortie."
        ))
        self.view_list_button.setText(t("Liste"))
        self.view_grid_button.setText(t("Grille"))
        self.view_list_button.setToolTip(t("Afficher les vétérans sous forme de liste."))
        self.view_grid_button.setToolTip(t("Afficher les vétérans comme dans le roster du jeu."))
        self.roster_columns_label.setText(t("Colonnes"))
        self.roster_columns.setToolTip(t("Nombre de colonnes dans la grille des vétérans."))
        describe_control(
            self.run_button, self.run_button.text(), self.run_button.toolTip()
        )
        describe_control(
            self.menu_button, self.menu_button.text(), self.menu_button.toolTip()
        )
        describe_control(self.view_list_button, self.view_list_button.text(), self.view_list_button.toolTip())
        describe_control(self.view_grid_button, self.view_grid_button.text(), self.view_grid_button.toolTip())
        self.history_menu.setTitle(t("Historique"))
        self.scope_action.setText(t("Portée de l’analyse…"))
        self.open_output_action.setText(t("Ouvrir le dossier de sortie"))
        for key, button in self.filter_buttons.items():
            button.setText(t(FILTER_LABELS[key]))
            description = {
                "all": "Affiche toutes les copies dans leur ordre en jeu.",
                "transfer": "Affiche seulement les copies recommandées au transfert.",
                "keep": "Affiche les copies à garder, protégées ou à vérifier.",
            }[key]
            button.setToolTip(t(description))
            describe_control(button, button.text(), button.toolTip())
        self.search.setPlaceholderText(t("Rechercher par nom ou score…"))
        self.search.setToolTip(t(
            "Recherche dans le nom de l’Uma, le score en jeu et les scores cités."
        ))
        describe_control(self.search, self.search.placeholderText(), self.search.toolTip())
        self.table.setToolTip(t(
            "Clique sur une raison ou appuie sur Entrée pour ouvrir l’explication. Elle suit la sélection ; Échap la ferme."
        ))
        describe_control(
            self.table,
            f"{t('Transfer Helper')} · {t('Résultats')}",
            self.table.toolTip(),
        )
        self.legacy_report_banner.setText(t(
            "Rapport ancien : relance l’analyse pour calculer les raisons de chaque ligne."
        ))
        self._refresh_filter_buttons()
        self._render_result_state()
        self.apply_filters()

    def _refresh_filter_buttons(self) -> None:
        transfer_count = sum(
            row.get("status") in TRANSFER_STATUSES for row in self._records
        )
        counts = {
            "all": len(self._records),
            "transfer": transfer_count,
            "keep": len(self._records) - transfer_count,
        }
        descriptions = {
            "all": "Affiche toutes les copies dans leur ordre en jeu.",
            "transfer": "Affiche seulement les copies recommandées au transfert.",
            "keep": "Affiche les copies à garder, protégées ou à vérifier.",
        }
        for key, button in self.filter_buttons.items():
            button.setText(f"{self.context.t(FILTER_LABELS[key])} ({counts[key]})")
            button.setToolTip(self.context.t(descriptions[key]))
            describe_control(button, button.text(), button.toolTip())

    def _set_filter(self, key: str) -> None:
        if key not in self.filter_buttons:
            key = "all"
        self.filter_buttons[key].setChecked(True)
        self.context.store.update({"ui_transfer_filter_v06": key})
        self.apply_filters()

    @staticmethod
    def _supports_reason_format(
        payload: dict[str, Any],
        records: list[dict[str, Any]],
    ) -> bool:
        metadata = payload.get("metadata") or {}
        try:
            version = int(metadata.get("format_version") or 0)
        except (TypeError, ValueError):
            version = 0
        return version >= CURRENT_REASON_FORMAT and all(
            isinstance(row.get("transfer_reason"), dict)
            and bool(row["transfer_reason"].get("code"))
            and isinstance(row["transfer_reason"].get("roles"), list)
            for row in records
        )

    def _set_result_state(self, state: str) -> None:
        self._result_state = state
        self._render_result_state()

    def _render_result_state(self) -> None:
        state = self._result_state
        self.result_state.setText(self.context.t(STATE_LABELS[state]))
        warning = state in {STATE_STALE, STATE_REANALYZE}
        self.result_state.setObjectName("pillWarning" if warning else "pillAccent")
        self.result_state.style().unpolish(self.result_state)
        self.result_state.style().polish(self.result_state)
        self.generated_at.setText(
            self.context.t("Rapport généré le {date}").replace(
                "{date}", self._generated_at
            )
            if self._generated_at else ""
        )
        self.legacy_report_banner.setVisible(
            self._result_origin_state in {STATE_READY, STATE_LOADED}
            and not self._reason_schema_supported
        )
        describe_control(
            self.result_state,
            self.result_state.text(),
            self.generated_at.text(),
        )

    def _refresh_freshness(self, *_args: object) -> None:
        if self._result_origin_state not in {STATE_READY, STATE_LOADED}:
            return
        if not self._reason_schema_supported:
            self._set_result_state(STATE_REANALYZE)
            return
        calendar_current = (
            not self._calendar_day
            or self._calendar_day == datetime.now().astimezone().date().isoformat()
        ) and (
            not self._calendar_valid_until
            or datetime.now(timezone.utc) < self._calendar_valid_until
        )
        state = (
            self._result_origin_state
            if self._current_fingerprint() == self._result_fingerprint and calendar_current
            else STATE_STALE
        )
        self._set_result_state(state)

    def _capture_report_context(self, payload: dict[str, Any]) -> None:
        self._comparison_model = payload.get("comparison_model") or {}
        self._report_settings = payload.get("settings") or {}
        loop_summary = (payload.get("metadata") or {}).get("loop_protection") or {}
        retained = int(loop_summary.get("retained_copy_count") or 0)
        additional = int(loop_summary.get("additional_retained_copy_count") or 0)
        self.loop_protection_summary.setText(
            self.context.t("{retained} copies gardées pour les boucles, dont {additional} uniquement pour ça").replace(
                "{retained}", str(retained)
            ).replace("{additional}", str(additional))
            if retained else ""
        )
        audit = (payload.get("settings") or {}).get("cm_calendar") or {}
        try:
            self._calendar_valid_until = datetime.fromisoformat(
                str(audit.get("next_transition_utc") or "")
            )
            if self._calendar_valid_until.tzinfo is None:
                self._calendar_valid_until = None
        except ValueError:
            self._calendar_valid_until = None
        try:
            moment = datetime.fromisoformat(str(audit.get("as_of_utc") or ""))
            self._calendar_day = moment.astimezone().date().isoformat()
        except ValueError:
            self._calendar_day = ""

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._refresh_freshness()

    def _prepare_records(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        prepared = [dict(record) for record in records]
        duplicates: dict[tuple[str, float], list[dict[str, Any]]] = defaultdict(list)
        for row in prepared:
            name = str(row.get("uma_name") or veteran_name(row) or "").casefold()
            try:
                score = float(row.get("rank_score"))
            except (TypeError, ValueError):
                continue
            if name:
                duplicates[(name, score)].append(row)
        for copies in duplicates.values():
            if len(copies) < 2:
                continue
            copies.sort(
                key=lambda row: (
                    str(row.get("trained_chara_id") or ""),
                    str(row.get("card_name") or ""),
                )
            )
            for index, row in enumerate(copies, 1):
                row["_duplicate_marker"] = str(index)
        return prepared

    def set_records(self, records: list[dict[str, Any]]) -> None:
        self._records = self._prepare_records(records)
        if self._audit_dialog is not None:
            self._audit_dialog.records = self._records
        self._refresh_filter_buttons()
        self.apply_filters()

    @staticmethod
    def _score_value(row: dict[str, Any]) -> float:
        try:
            return float(row.get("rank_score") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _record_id(row: dict[str, Any]) -> str:
        return str(row.get("trained_chara_id") or "")

    def _search_text(self, row: dict[str, Any]) -> str:
        pieces = [
            str(row.get("uma_name") or ""),
            str(row.get("card_name") or ""),
            canonical_veteran_label(row),
            str(row.get("rank_score") or ""),
            format_rank_score(row.get("rank_score")),
        ]
        for reference in (row.get("transfer_reason") or {}).get("refs") or []:
            pieces.extend([
                str(reference.get("uma_name") or ""),
                str(reference.get("card_name") or ""),
                str(reference.get("rank_score") or ""),
                format_rank_score(reference.get("rank_score")),
            ])
        return " ".join(pieces).casefold()

    def apply_filters(self, *_args: object) -> None:
        filter_key = self._filter_key()
        query = self.search.text().strip().casefold()
        selected = self.selected_row()
        selected_id = self._record_id(selected) if selected else ""
        rows: list[dict[str, Any]] = []
        for record in self._records:
            is_transfer = record.get("status") in TRANSFER_STATUSES
            if filter_key == "transfer" and not is_transfer:
                continue
            if filter_key == "keep" and is_transfer:
                continue
            if query and query not in self._search_text(record):
                continue
            rows.append(record)
        rows.sort(key=lambda row: (
            -self._score_value(row),
            int(row.get("rank") or 0)
            if str(row.get("rank") or "").isdigit() else 0,
            self._record_id(row),
        ))
        self.model.set_columns(self._columns())
        self.model.set_rows(rows)
        self.roster.clear()
        for row in rows:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, row)
            tooltip = self._reason_label(row)
            detail = self._reason_tooltip(row)
            item.setToolTip("\n".join(part for part in (tooltip, detail) if part))
            item.setSizeHint(self.roster.cell_size())
            self.roster.addItem(item)
        target = next(
            (
                index for index, row in enumerate(rows)
                if selected_id and self._record_id(row) == selected_id
            ),
            0 if rows else -1,
        )
        if target >= 0:
            self.table.selectRow(target)
            self.roster.setCurrentRow(target)
            current_item = self.roster.item(target)
            if current_item is not None:
                self.roster.scrollToItem(current_item, QAbstractItemView.ScrollHint.EnsureVisible)

    def selected_row(self) -> dict[str, Any] | None:
        if self.views.currentWidget() is self.roster:
            item = self.roster.currentItem()
            row = item.data(Qt.ItemDataRole.UserRole) if item else None
            return row if isinstance(row, dict) else None
        indexes = self.table.selectionModel().selectedRows()
        return self.model.row(indexes[0].row()) if indexes else None

    def _set_view_mode(self, mode: str) -> None:
        selected = self.selected_row()
        selected_id = self._record_id(selected) if selected else ""
        use_grid = mode == "grid"
        self.views.setCurrentWidget(self.roster if use_grid else self.table)
        self.view_grid_button.setChecked(use_grid)
        self.view_list_button.setChecked(not use_grid)
        self.roster_columns_label.setVisible(use_grid)
        self.roster_columns.setVisible(use_grid)
        self.context.store.update({"ui_transfer_view_mode_v01": "grid" if use_grid else "list"})
        if selected_id:
            self._select_record_id(selected_id)

    def _set_roster_columns(self, columns: int) -> None:
        self.roster.set_fixed_columns(columns)
        self.context.store.update({"ui_transfer_roster_columns_v01": int(columns)})

    def _roster_selection_changed(self, current, _previous) -> None:
        if self._audit_dialog is None or not self._audit_dialog.isVisible() or current is None:
            return
        row = current.data(Qt.ItemDataRole.UserRole)
        if isinstance(row, dict):
            self._audit_dialog.set_candidate(row)

    def _roster_item_activated(self, item) -> None:
        row = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if isinstance(row, dict):
            self.open_audit(row)

    def _show_roster_context_menu(self, position) -> None:
        item = self.roster.itemAt(position)
        if item is None:
            return
        self.roster.setCurrentItem(item)
        menu = QMenu(self)
        audit = menu.addAction(self.context.t("Audit…"))
        audit.triggered.connect(lambda _checked=False, selected=item: self._roster_item_activated(selected))
        menu.exec(self.roster.viewport().mapToGlobal(position))

    def _reason_cell_clicked(self, index) -> None:
        if not index.isValid() or index.column() != 3:
            return
        row = self.model.row(index.row()) or {}
        if not self._comparison_model:
            # Older in-memory callers may not have the frozen report model;
            # keep their cited-copy navigation while the full report opens
            # the role explanation panel.
            references = [
                reference for reference in (row.get("transfer_reason") or {}).get("refs") or []
                if reference.get("trained_chara_id") is not None
            ]
            if len(references) == 1:
                self._select_record_id(self._record_id(references[0]))
                return
            if len(references) > 1:
                menu = QMenu(self)
                for reference in references:
                    action = menu.addAction(
                        f"{format_rank_score(reference.get('rank_score'))} — "
                        f"{reference.get('uma_name') or veteran_name(reference)}"
                    )
                    target_id = self._record_id(reference)
                    action.triggered.connect(
                        lambda _checked=False, selected_id=target_id:
                        self._select_record_id(selected_id)
                    )
                rect = self.table.visualRect(index)
                menu.exec(self.table.viewport().mapToGlobal(rect.bottomLeft()))
                return
        self.open_audit(row)

    def _select_record_id(self, target_id: str) -> None:
        if not target_id:
            return
        visible_ids = {
            self._record_id(self.model.row(index) or {})
            for index in range(self.model.rowCount())
        }
        if target_id not in visible_ids:
            self.search.clear()
            self._set_filter("all")
        for index in range(self.model.rowCount()):
            if self._record_id(self.model.row(index) or {}) == target_id:
                self.table.selectRow(index)
                self.table.scrollTo(
                    self.model.index(index, 0),
                    QAbstractItemView.ScrollHint.EnsureVisible,
                )
                item = self.roster.item(index)
                if item is not None:
                    self.roster.setCurrentItem(item)
                    self.roster.scrollToItem(item, QAbstractItemView.ScrollHint.EnsureVisible)
                return

    def _show_row_context_menu(self, position) -> None:
        index = self.table.indexAt(position)
        if not index.isValid():
            return
        self.table.selectRow(index.row())
        row = self.model.row(index.row())
        if row is None:
            return
        menu = QMenu(self)
        audit = menu.addAction(self.context.t("Audit…"))
        audit.triggered.connect(
            lambda _checked=False, selected=row: self.open_audit(selected)
        )
        menu.exec(self.table.viewport().mapToGlobal(position))

    def open_audit(self, row: dict[str, Any] | None = None) -> None:
        selected = row or self.selected_row()
        if selected is None:
            return
        if self._comparison_model and self._reason_schema_supported:
            from ui_qt.transfer_reason_panel import TransferReasonPanel
            if self._audit_dialog is None:
                self._audit_dialog = TransferReasonPanel(
                    self.context, self._records, self._comparison_model,
                    self._report_settings, self,
                )
            else:
                self._audit_dialog.records = self._records
                self._audit_dialog.comparison_model = self._comparison_model
                self._audit_dialog.settings = self._report_settings
            self._audit_dialog.set_candidate(selected)
            self._audit_dialog.show()
            self._audit_dialog.raise_()
            self._audit_dialog.activateWindow()
            return
        # Old reports do not contain frozen model data for a verified duel.
        dialog = QDialog(self)
        dialog.setWindowTitle(f"{self.context.t('Audit…')} — {canonical_veteran_label(selected)}")
        dialog.resize(1000, 760)
        layout = QVBoxLayout(dialog)
        browser = QTextBrowser(dialog)
        browser.setHtml(transfer_detail_html(selected, self.context.language))
        layout.addWidget(browser, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText(self.context.t("Fermer"))
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def _selection_changed(self, current, _previous) -> None:
        if self._audit_dialog is None or not self._audit_dialog.isVisible() or not current.isValid():
            return
        row = self.model.row(current.row())
        if row is not None:
            self._audit_dialog.set_candidate(row)

    def start_analysis(self) -> None:
        scope = self._scope_values()
        priority_text = self.context.store.get("skill_priorities_path")
        self._state_before_running = self._result_state
        self._running_fingerprint = self.context.transfer_fingerprint(scope)
        self._set_result_state(STATE_RUNNING)
        request = TransferRequest(
            master_path=Path(self.context.master_path).expanduser(),
            veterans_json_path=Path(self.context.veterans_json_path).expanduser(),
            output_dir=Path(self.context.output_dir).expanduser(),
            course_overrides_path=active_course_overrides_path(
                self.context.course_overrides_path
            ),
            use_custom_scoring=self.context.store.get("use_custom_scoring", "0")
            in {"1", "true", "True"},
            skill_priorities_path=(
                Path(priority_text).expanduser() if priority_text else None
            ),
            analysis_mode=str(scope["analysis_mode"]),
            include_upcoming_cm_context=bool(scope["include_upcoming_cm_context"]),
            upcoming_cm_limit=int(scope["upcoming_cm_limit"]),
            include_team_trials=bool(scope["include_team_trials"]),
            include_generic_profiles=bool(scope["include_generic_profiles"]),
            loop_protection_skills=tuple(scope["loop_protection_skills"]),
            loop_protection_presets=tuple(scope["loop_protection_presets"]),
        )
        self.task_requested.emit(
            ProcessTask(partial(run_transfer_analysis, request)),
            self.context.t("Analyse Transfer Helper…"),
            self._analysis_done,
        )


    def _analysis_done(self, result: object) -> None:
        report_path = getattr(result, "report_json_path", None)
        try:
            payload, self._provenance = read_json_output_revision(
                Path(report_path), CURRENT_REVISION
            )
            self._capture_report_context(payload)
            records = [
                row for row in (payload.get("records") or [])
                if isinstance(row, dict)
            ]
            self._reason_schema_supported = self._supports_reason_format(
                payload, records
            )
        except (OSError, TypeError, json.JSONDecodeError, ValueError):
            self._provenance = None
            self._calendar_day = ""
            self._calendar_valid_until = None
            self._comparison_model = {}
            self._report_settings = {}
            records = list(getattr(result, "records", ()) or ())
            self._reason_schema_supported = bool(records) and all(
                isinstance(row.get("transfer_reason"), dict)
                and bool(row["transfer_reason"].get("code"))
                for row in records
            )
        if not records:
            records = list(getattr(result, "records", ()) or ())
        self.set_records(records)
        self._result_fingerprint = self._running_fingerprint
        self._result_origin_state = STATE_READY
        self._generated_at = format_output_timestamp(
            self._provenance.generated_at_utc if self._provenance else ""
        )
        self._refresh_freshness()

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

    def _comparison_renderer(self, item, _dataset: ComparisonDataset) -> str:
        return transfer_detail_html(item.row, self.context.language)

    def _show_comparison_error(self, message: str) -> None:
        QMessageBox.information(
            self,
            self.context.t("Comparaison"),
            self.context.t(message),
        )

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
                raise ValueError(
                    "Le rapport Transfer Helper ne contient pas de liste de résultats."
                )
            self._capture_report_context(payload)
            rows = [row for row in records if isinstance(row, dict)]
            self._reason_schema_supported = self._supports_reason_format(
                payload, rows
            )
            self.set_records(rows)
            self._provenance = provenance
            self._generated_at = format_output_timestamp(
                provenance.generated_at_utc
            )
            self._result_fingerprint = self._current_fingerprint()
            self._result_origin_state = STATE_LOADED
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
        self.menu_button.setEnabled(not busy)
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
