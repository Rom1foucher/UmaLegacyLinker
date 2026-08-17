from __future__ import annotations

import copy
import json
from functools import partial
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from lineage_planner import LineagePlannerError, write_lineage_planner_export
from parent_optimizer import (
    DISTANCE_FACTOR_NAMES,
    STYLE_FACTOR_NAMES,
    SURFACE_FACTOR_NAMES,
    OptimizerError,
    load_ace_options,
    load_track_options,
)
from uma_moe import UmaMoeError
from ui_qt.components import (
    PageHeader,
    PathPicker,
    SearchableComboBox,
    SummarySection,
    ThemedComboBox,
    muted_label,
    section_label,
)
from ui_qt.context import AppContext, LineageContextState
from ui_qt.core import (
    OnlineSearchRequest,
    OptimizationRequest,
    VeteranOption,
    latest_rankings_path,
    load_local_veteran_options,
    load_opposing_parent_candidates,
    load_rankings_payload,
    open_path,
    run_online_search,
    run_optimization,
)
from ui_qt.lineage_settings import LineageRaceEditor
from ui_qt.pages_online import CardFilterDialog, OnlineResultsPane
from ui_qt.pages_optimizer import ResultPane
from ui_qt.presentation import profile_summary

RAIL_COLLAPSED_KEY = "search_rail_collapsed"
RAIL_WIDTH = 300
# Below this workspace width the rail and a result pane cannot both stay
# readable, so the rail starts collapsed unless the user decided otherwise.
NARROW_WORKSPACE_WIDTH = 1360


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


class OnlineSearchOptionsDialog(QDialog):
    """Persistent uma.moe search filters, deliberately separated from credentials."""

    def __init__(
        self,
        context: AppContext,
        mode: str,
        ace_options: list[object],
        local_options: list[VeteranOption],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.context = context
        self.mode = "parent" if mode == "parent" else "grandparent"
        self.ace_options = list(ace_options)
        self.local_options = list(local_options)
        self._allowed_ids = _id_set(
            context.store.get("uma_moe_parent_allowed_card_ids")
        )
        self._excluded_ids = _id_set(
            context.store.get("uma_moe_parent_excluded_card_ids")
        )
        self._external_opposing: list[dict[str, Any]] = []
        self.setModal(True)
        self.resize(900, 760)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)
        self.header = section_label("")
        self.header.setWordWrap(False)
        self.header_hint = muted_label("")
        root.addWidget(self.header)
        root.addWidget(self.header_hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 4, 0)
        body_layout.setSpacing(10)

        pair_panel = QFrame()
        pair_panel.setObjectName("panel")
        pair = QGridLayout(pair_panel)
        pair.setContentsMargins(17, 14, 17, 14)
        pair.setHorizontalSpacing(12)
        pair.setVerticalSpacing(8)
        self.pair_title = section_label("")
        self.auto_pairs = QCheckBox("")
        self.auto_pairs.setChecked(
            context.store.get("uma_moe_auto_pairs", "1")
            not in {"0", "false", "False"}
        )
        self.fixed_label = QLabel("")
        self.fixed_combo = SearchableComboBox()
        fixed_selected = _integer(context.store.get("uma_moe_fixed_gp_id"))
        for option in self.local_options:
            self.fixed_combo.addItem(option.display_name, option.trained_chara_id)
        fixed_index = self.fixed_combo.findData(fixed_selected)
        self.fixed_combo.setCurrentIndex(
            fixed_index if fixed_index >= 0 else (0 if self.fixed_combo.count() else -1)
        )
        self.fixed_combo.setDisabled(self.auto_pairs.isChecked())
        self.local_pool_label = QLabel("")
        self.local_pool = QSpinBox()
        self.local_pool.setRange(1, 250)
        self.local_pool.setValue(
            _integer(context.store.get("uma_moe_local_pool", "100"), 100)
        )
        self.remote_pool_label = QLabel("")
        self.remote_pool = QSpinBox()
        self.remote_pool.setRange(1, 500)
        self.remote_pool.setValue(
            _integer(context.store.get("uma_moe_remote_pool", "100"), 100)
        )
        self.fetch_label = QLabel("")
        self.fetch_spin = QSpinBox()
        self.fetch_spin.setRange(100, 2000)
        self.fetch_spin.setSingleStep(100)
        self.fetch_spin.setValue(
            _integer(context.store.get("uma_moe_limit", "500"), 500)
        )
        pair.addWidget(self.pair_title, 0, 0, 1, 3)
        pair.addWidget(self.auto_pairs, 1, 0, 1, 3)
        pair.addWidget(self.fixed_label, 2, 0, 1, 3)
        pair.addWidget(self.fixed_combo, 3, 0, 1, 3)
        for column, (label, widget) in enumerate(
            (
                (self.local_pool_label, self.local_pool),
                (self.remote_pool_label, self.remote_pool),
                (self.fetch_label, self.fetch_spin),
            )
        ):
            pair.addWidget(label, 4, column)
            pair.addWidget(widget, 5, column)
            pair.setColumnStretch(column, 1)
        body_layout.addWidget(pair_panel)

        retrieval_panel = QFrame()
        retrieval_panel.setObjectName("panel")
        retrieval = QGridLayout(retrieval_panel)
        retrieval.setContentsMargins(17, 14, 17, 14)
        retrieval.setHorizontalSpacing(12)
        retrieval.setVerticalSpacing(7)
        self.retrieval_title = section_label("")
        self.retrieval_hint = muted_label("")
        self.prefer_profile = QCheckBox("")
        self.prefer_profile.setChecked(
            context.store.get("uql_prefer_whites", "1")
            not in {"0", "false", "False"}
        )
        self.prefer_lineage = QCheckBox("")
        self.prefer_lineage.setChecked(
            context.store.get("uql_lineage_whites", "1")
            not in {"0", "false", "False"}
        )
        self.surface_cohort = QCheckBox("")
        self.surface_cohort.setChecked(
            context.store.get("uql_surface_cohort", "1")
            not in {"0", "false", "False"}
        )
        self.require_surface = QCheckBox("")
        self.require_distance = QCheckBox("")
        self.require_style = QCheckBox("")
        for widget, key in (
            (self.require_surface, "uql_require_surface"),
            (self.require_distance, "uql_require_distance"),
            (self.require_style, "uql_require_style"),
        ):
            widget.setChecked(context.store.get(key, "0") in {"1", "true", "True"})
        self.pink_label = QLabel("")
        self.pink_spin = QSpinBox()
        self.pink_spin.setRange(1, 3)
        self.pink_spin.setPrefix("≥ ")
        self.pink_spin.setSuffix("★")
        self.pink_spin.setValue(
            _integer(context.store.get("uql_pink_min_stars", "1"), 1)
        )
        retrieval.addWidget(self.retrieval_title, 0, 0, 1, 3)
        retrieval.addWidget(self.retrieval_hint, 1, 0, 1, 3)
        retrieval.addWidget(self.prefer_profile, 2, 0)
        retrieval.addWidget(self.prefer_lineage, 2, 1)
        retrieval.addWidget(self.surface_cohort, 2, 2)
        retrieval.addWidget(self.require_surface, 3, 0)
        retrieval.addWidget(self.require_distance, 3, 1)
        retrieval.addWidget(self.require_style, 3, 2)
        retrieval.addWidget(self.pink_label, 4, 0)
        retrieval.addWidget(self.pink_spin, 4, 1)
        for column in range(3):
            retrieval.setColumnStretch(column, 1)
        body_layout.addWidget(retrieval_panel)

        lineage_panel = QFrame()
        lineage_panel.setObjectName("panel")
        lineage = QGridLayout(lineage_panel)
        lineage.setContentsMargins(17, 14, 17, 14)
        lineage.setHorizontalSpacing(12)
        lineage.setVerticalSpacing(8)
        self.lineage_title = section_label("")
        self.lineage_hint = muted_label("")
        self.lineage_blue_label = QLabel("")
        self.lineage_blue_combo = ThemedComboBox()
        self.lineage_blue_combo.addItem("—", None)
        for name in ("Speed", "Stamina", "Power", "Guts", "Wit"):
            self.lineage_blue_combo.addItem(name, name)
        self.lineage_blue_stars = QSpinBox()
        self.lineage_blue_stars.setRange(0, 9)
        self.lineage_blue_stars.setPrefix("≥ ")
        self.lineage_blue_stars.setSuffix("★")
        self.lineage_pink_label = QLabel("")
        self.lineage_pink_combo = ThemedComboBox()
        self.lineage_pink_combo.addItem("—", None)
        for name in (
            list(SURFACE_FACTOR_NAMES.values())
            + list(DISTANCE_FACTOR_NAMES.values())
            + list(STYLE_FACTOR_NAMES.values())
        ):
            self.lineage_pink_combo.addItem(name, name)
        self.lineage_pink_stars = QSpinBox()
        self.lineage_pink_stars.setRange(0, 9)
        self.lineage_pink_stars.setPrefix("≥ ")
        self.lineage_pink_stars.setSuffix("★")
        self.lineage_blue_stars.setMinimumWidth(116)
        self.lineage_pink_stars.setMinimumWidth(116)
        for combo, key in (
            (self.lineage_blue_combo, "uql_lineage_blue_name"),
            (self.lineage_pink_combo, "uql_lineage_pink_name"),
        ):
            index = combo.findData(context.store.get(key, ""))
            combo.setCurrentIndex(index if index >= 0 else 0)
        self.lineage_blue_stars.setValue(
            _integer(context.store.get("uql_lineage_blue_stars", "0"))
        )
        self.lineage_pink_stars.setValue(
            _integer(context.store.get("uql_lineage_pink_stars", "0"))
        )
        lineage.addWidget(self.lineage_title, 0, 0, 1, 3)
        lineage.addWidget(self.lineage_hint, 1, 0, 1, 3)
        lineage.addWidget(self.lineage_blue_label, 2, 0)
        lineage.addWidget(self.lineage_blue_combo, 2, 1)
        lineage.addWidget(self.lineage_blue_stars, 2, 2)
        lineage.addWidget(self.lineage_pink_label, 3, 0)
        lineage.addWidget(self.lineage_pink_combo, 3, 1)
        lineage.addWidget(self.lineage_pink_stars, 3, 2)
        lineage.setColumnStretch(1, 1)
        body_layout.addWidget(lineage_panel)

        mode_panel = QFrame()
        mode_panel.setObjectName("panel")
        mode_layout = QGridLayout(mode_panel)
        mode_layout.setContentsMargins(17, 14, 17, 14)
        mode_layout.setHorizontalSpacing(12)
        mode_layout.setVerticalSpacing(8)
        self.mode_title = section_label("")
        mode_layout.addWidget(self.mode_title, 0, 0, 1, 3)
        if self.mode == "parent":
            self.required_label = QLabel("")
            self.required_combo = SearchableComboBox()
            self.required_combo.addItem("", None)
            for option in self.ace_options:
                self.required_combo.addItem(option.display_name, option.card_id)
            required = _integer(
                context.store.get("uma_moe_required_parent_card_id")
            )
            required_index = self.required_combo.findData(required)
            self.required_combo.setCurrentIndex(required_index if required_index >= 0 else 0)
            self.allowed_button = QPushButton("")
            self.excluded_button = QPushButton("")
            mode_layout.addWidget(self.required_label, 1, 0, 1, 3)
            mode_layout.addWidget(self.required_combo, 2, 0, 1, 3)
            mode_layout.addWidget(self.allowed_button, 3, 1)
            mode_layout.addWidget(self.excluded_button, 3, 2)
            self.allowed_button.clicked.connect(lambda: self._pick_filter("allowed"))
            self.excluded_button.clicked.connect(lambda: self._pick_filter("excluded"))
        else:
            self.opposing_label = QLabel("")
            self.opposing_combo = SearchableComboBox()
            self.opposing_json_label = QLabel("")
            self.opposing_picker = PathPicker(
                context.store.get("uma_moe_opposing_path"),
                title="Sélectionner un JSON de parent opposé",
                file_filter="JSON (*.json);;Tous les fichiers (*)",
            )
            self.opposing_extract_button = QPushButton("")
            self.g1_budget_label = QLabel("")
            self.g1_budget = QSpinBox()
            self.g1_budget.setRange(0, 40)
            self.g1_budget.setValue(
                _integer(context.store.get("uma_moe_parent_g1_budget", "20"), 20)
            )
            self.g1_weight_label = QLabel("")
            self.g1_weight = QDoubleSpinBox()
            self.g1_weight.setRange(0.0, 1.0)
            self.g1_weight.setSingleStep(0.1)
            self.g1_weight.setDecimals(2)
            try:
                self.g1_weight.setValue(
                    float(
                        context.store.get(
                            "uma_moe_g1_win_probability_cutoff",
                            context.store.get("uma_moe_single_g1_weight", "0.6"),
                        )
                    )
                )
            except ValueError:
                self.g1_weight.setValue(0.6)
            mode_layout.addWidget(self.opposing_label, 1, 0, 1, 3)
            mode_layout.addWidget(self.opposing_combo, 2, 0, 1, 3)
            mode_layout.addWidget(self.opposing_json_label, 3, 0, 1, 3)
            mode_layout.addWidget(self.opposing_picker, 4, 0, 1, 2)
            mode_layout.addWidget(self.opposing_extract_button, 4, 2)
            mode_layout.addWidget(self.g1_budget_label, 5, 0)
            mode_layout.addWidget(self.g1_weight_label, 5, 1)
            mode_layout.addWidget(self.g1_budget, 6, 0)
            mode_layout.addWidget(self.g1_weight, 6, 1)
            self.opposing_extract_button.clicked.connect(
                lambda: self._load_external_opposing(show_errors=True)
            )
            self._load_external_opposing(show_errors=False)
            self._refresh_opposing_options()
        mode_layout.setColumnStretch(0, 1)
        mode_layout.setColumnStretch(1, 1)
        mode_layout.setColumnStretch(2, 1)
        body_layout.addWidget(mode_panel)

        import_panel = QFrame()
        import_panel.setObjectName("panel")
        import_layout = QVBoxLayout(import_panel)
        import_layout.setContentsMargins(17, 14, 17, 14)
        self.import_label = QLabel("")
        self.import_picker = PathPicker(
            context.store.get("uma_moe_response_path"),
            title="Sélectionner une réponse JSON de l’API uma.moe",
            file_filter="JSON (*.json);;Tous les fichiers (*)",
        )
        import_layout.addWidget(self.import_label)
        import_layout.addWidget(self.import_picker)
        body_layout.addWidget(import_panel)
        body_layout.addStretch(1)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)

        self.auto_pairs.toggled.connect(self.fixed_combo.setDisabled)
        context.language_changed.connect(self._language_changed)
        self.retranslate()

    def _language_changed(self, _language: str) -> None:
        self.retranslate()

    def _pick_filter(self, kind: str) -> None:
        selected = self._allowed_ids if kind == "allowed" else self._excluded_ids
        title = self.context.t(
            "Costumes autorisés" if kind == "allowed" else "Costumes exclus"
        )
        options = [(item.card_id, item.display_name) for item in self.ace_options]
        dialog = CardFilterDialog(self.context, options, set(selected), title, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if kind == "allowed":
            self._allowed_ids = dialog.selected_ids()
        else:
            self._excluded_ids = dialog.selected_ids()
        self._refresh_filter_labels()

    def _load_external_opposing(self, *, show_errors: bool) -> None:
        if self.mode != "grandparent":
            return
        path_text = self.opposing_picker.text().strip()
        if not path_text:
            self._external_opposing = []
            self._refresh_opposing_options()
            return
        path = Path(path_text).expanduser()
        if not path.is_file():
            if show_errors:
                QMessageBox.warning(
                    self,
                    self.context.t("Parent opposé (contexte)"),
                    self.context.t("Sélectionne d’abord un JSON de parent opposé."),
                )
            return
        try:
            self._external_opposing = load_opposing_parent_candidates(
                Path(self.context.master_path).expanduser(), path
            )
        except Exception as exc:
            self._external_opposing = []
            if show_errors:
                QMessageBox.warning(
                    self,
                    self.context.t("Parent opposé (contexte)"),
                    self.context.t(str(exc)),
                )
        self._refresh_opposing_options()

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
        if self.mode != "grandparent" or not hasattr(self, "opposing_combo"):
            return
        saved = self.context.store.get("uma_moe_opposing_selection", "none")
        self.opposing_combo.blockSignals(True)
        self.opposing_combo.clear()
        self.opposing_combo.addItem(
            self.context.t("(aucun — recherche GP polyvalente)"), "none"
        )
        for option in self.local_options:
            self.opposing_combo.addItem(
                f"{self.context.t('Local')} — {option.display_name}",
                f"local:{option.trained_chara_id}",
            )
        for index, member in enumerate(self._external_opposing):
            self.opposing_combo.addItem(
                self._external_display(member), f"external:{index}"
            )
        selected = self.opposing_combo.findData(saved)
        if selected < 0:
            legacy = _integer(self.context.store.get("uma_moe_opposing_id"))
            selected = self.opposing_combo.findData(f"local:{legacy}")
        self.opposing_combo.setCurrentIndex(selected if selected >= 0 else 0)
        self.opposing_combo.blockSignals(False)

    def _refresh_filter_labels(self) -> None:
        if self.mode != "parent":
            return
        self.allowed_button.setText(
            f"{self.context.t('Autorisés')} ({len(self._allowed_ids)})"
        )
        self.excluded_button.setText(
            f"{self.context.t('Exclus')} ({len(self._excluded_ids)})"
        )

    def _lineage_filter(
        self, combo: ThemedComboBox, spin: QSpinBox
    ) -> tuple[str, int] | None:
        name = str(combo.currentData() or "").strip()
        stars = int(spin.value())
        return (name, stars) if name and stars > 0 else None

    def values(self) -> dict[str, Any]:
        self.fixed_combo.resolve_current_text()
        fixed = _integer(self.fixed_combo.currentData())
        opposing_id: int | None = None
        opposing_payload: dict[str, Any] | None = None
        opposing_selection = "none"
        if self.mode == "grandparent":
            self.opposing_combo.resolve_current_text()
            opposing_selection = str(self.opposing_combo.currentData() or "none")
            if opposing_selection.startswith("local:"):
                opposing_id = _integer(opposing_selection.split(":", 1)[1]) or None
            elif opposing_selection.startswith("external:"):
                index = _integer(opposing_selection.split(":", 1)[1], -1)
                if 0 <= index < len(self._external_opposing):
                    opposing_payload = copy.deepcopy(self._external_opposing[index])
        required: int | None = None
        if self.mode == "parent":
            self.required_combo.resolve_current_text()
            required_raw = self.required_combo.currentData()
            required = int(required_raw) if required_raw is not None else None
        return {
            "automatic_pairs": self.auto_pairs.isChecked(),
            "fixed_local_id": None if self.auto_pairs.isChecked() else (fixed or None),
            "local_pool_size": self.local_pool.value(),
            "remote_pool_size": self.remote_pool.value(),
            "limit": self.fetch_spin.value(),
            "uql_options": {
                "prefer_profile_whites": self.prefer_profile.isChecked(),
                "prefer_lineage_whites": self.prefer_lineage.isChecked(),
                "require_main_surface": self.require_surface.isChecked(),
                "require_main_distance": self.require_distance.isChecked(),
                "require_main_style": self.require_style.isChecked(),
                "pink_min_stars": self.pink_spin.value(),
                "enable_surface_retrieval": self.surface_cohort.isChecked(),
            },
            "planned_g1_budget": (
                self.g1_budget.value() if self.mode == "grandparent" else 20
            ),
            "g1_win_probability_cutoff": (
                self.g1_weight.value() if self.mode == "grandparent" else 0.6
            ),
            "required_parent_card_id": required,
            "allowed_parent_card_ids": tuple(sorted(self._allowed_ids)),
            "excluded_parent_card_ids": tuple(sorted(self._excluded_ids)),
            "opposing_parent_trained_id": opposing_id,
            "opposing_parent_payload": opposing_payload,
            "opposing_selection": opposing_selection,
            "lineage_blue_filter": self._lineage_filter(
                self.lineage_blue_combo, self.lineage_blue_stars
            ),
            "lineage_pink_filter": self._lineage_filter(
                self.lineage_pink_combo, self.lineage_pink_stars
            ),
            "response_path": self.import_picker.text().strip(),
        }

    def _accept(self) -> None:
        values = self.values()
        required = values["required_parent_card_id"]
        if required in self._excluded_ids:
            QMessageBox.warning(
                self,
                self.context.t("Configuration incomplète"),
                self.context.t("Le costume requis est également exclu."),
            )
            return
        if self._allowed_ids and required is not None and required not in self._allowed_ids:
            QMessageBox.warning(
                self,
                self.context.t("Configuration incomplète"),
                self.context.t(
                    "Le costume requis doit être présent dans les costumes autorisés."
                ),
            )
            return
        blue = values["lineage_blue_filter"]
        pink = values["lineage_pink_filter"]
        options = values["uql_options"]
        self.context.store.update(
            {
                "uma_moe_auto_pairs": int(values["automatic_pairs"]),
                "uma_moe_fixed_gp_id": values["fixed_local_id"] or 0,
                "uma_moe_local_pool": values["local_pool_size"],
                "uma_moe_remote_pool": values["remote_pool_size"],
                "uma_moe_limit": values["limit"],
                "uma_moe_response_path": values["response_path"],
                "uma_moe_parent_g1_budget": values["planned_g1_budget"],
                "uma_moe_g1_win_probability_cutoff": values[
                    "g1_win_probability_cutoff"
                ],
                "uma_moe_required_parent_card_id": required or 0,
                "uma_moe_parent_allowed_card_ids": ",".join(
                    map(str, sorted(self._allowed_ids))
                ),
                "uma_moe_parent_excluded_card_ids": ",".join(
                    map(str, sorted(self._excluded_ids))
                ),
                "uql_prefer_whites": int(options["prefer_profile_whites"]),
                "uql_lineage_whites": int(options["prefer_lineage_whites"]),
                "uql_surface_cohort": int(options["enable_surface_retrieval"]),
                "uql_require_surface": int(options["require_main_surface"]),
                "uql_require_distance": int(options["require_main_distance"]),
                "uql_require_style": int(options["require_main_style"]),
                "uql_pink_min_stars": options["pink_min_stars"],
                "uql_lineage_blue_name": blue[0] if blue else "",
                "uql_lineage_blue_stars": blue[1] if blue else 0,
                "uql_lineage_pink_name": pink[0] if pink else "",
                "uql_lineage_pink_stars": pink[1] if pink else 0,
                "uma_moe_opposing_id": values["opposing_parent_trained_id"] or 0,
                "uma_moe_opposing_selection": values["opposing_selection"],
                "uma_moe_opposing_path": (
                    self.opposing_picker.text().strip()
                    if self.mode == "grandparent"
                    else self.context.store.get("uma_moe_opposing_path")
                ),
            }
        )
        self.accept()

    def retranslate(self) -> None:
        t = self.context.t
        mode_name = t("parents distants" if self.mode == "parent" else "grands-parents distants")
        self.setWindowTitle(t("Options de recherche uma.moe"))
        self.header.setText(t("Options uma.moe") + f" · {mode_name}")
        self.header_hint.setText(
            t(
                "Ces filtres changent la récupération et la combinaison des candidats. La clé et l’URL se règlent dans Paramètres."
            )
        )
        self.pair_title.setText(t("Combinaison local × distant"))
        self.auto_pairs.setText(t("Tester automatiquement toutes les paires local × distant"))
        self.fixed_label.setText(
            t("Parent local fixé (manuel)" if self.mode == "parent" else "GP local fixé (manuel)")
        )
        self.local_pool_label.setText(t("Pool local"))
        self.remote_pool_label.setText(t("Pool distant"))
        self.fetch_label.setText(t("Fetch API"))
        self.retrieval_title.setText(t("Récupération et filtres"))
        self.retrieval_hint.setText(
            t(
                "Les préférences orientent l’API ; les contraintes excluent réellement les candidats avant le classement local exact."
            )
        )
        self.prefer_profile.setText(t("Favoriser les whites du profil"))
        self.prefer_lineage.setText(t("Favoriser leur répétition dans la lignée"))
        self.surface_cohort.setText(t("Cohorte Surface dédiée (récupération API)"))
        self.require_surface.setText(t("Exiger la surface cible"))
        self.require_distance.setText(t("Exiger la distance cible"))
        self.require_style.setText(t("Exiger le style cible"))
        self.pink_label.setText(t("Étoiles pink minimum"))
        self.lineage_title.setText(t("Qualité minimale de la lignée distante"))
        self.lineage_hint.setText(
            t("Somme sur le Main distant et ses deux parents, appliquée avant pagination.")
        )
        self.lineage_blue_label.setText(t("Stat Blue"))
        self.lineage_pink_label.setText(t("Aptitude Pink"))
        for spin in (self.lineage_blue_stars, self.lineage_pink_stars):
            spin.setSpecialValueText(t("désactivé"))
        self.mode_title.setText(
            t("Filtres de costumes")
            if self.mode == "parent"
            else t("Contexte de production du parent")
        )
        if self.mode == "parent":
            self.required_label.setText(t("Costume requis dans la paire"))
            self.required_combo.setItemText(0, t("Aucun costume requis"))
            self._refresh_filter_labels()
        else:
            self.opposing_label.setText(t("Parent opposé (contexte)"))
            self.opposing_json_label.setText(t("JSON du parent opposé"))
            self.opposing_extract_button.setText(t("Extraire les candidats"))
            self.opposing_picker.set_button_text(t("Parcourir…"))
            self.g1_budget_label.setText(t("G1 prévues sur le parent"))
            self.g1_weight_label.setText(
                t("Chance de victoire minimale (Independent Training)")
            )
            self._refresh_opposing_options()
        self.import_label.setText(t("Réponse JSON à classer hors ligne"))
        self.import_picker.set_button_text(t("Parcourir…"))
        save_button = self.buttons.button(QDialogButtonBox.StandardButton.Save)
        cancel_button = self.buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if save_button is not None:
            save_button.setText(t("Enregistrer"))
        if cancel_button is not None:
            cancel_button.setText(t("Annuler"))


class SearchPage(QWidget):
    """Single lineage workspace with one context and two explicit sources."""

    task_requested = Signal(object, str, object)

    def __init__(self, context: AppContext, parent=None) -> None:
        super().__init__(parent)
        self.context = context
        self._busy = False
        self._syncing_lineage = False
        self._ace_options: list[Any] = []
        self._local_options: list[VeteranOption] = []
        self._track_options: list[object] = []
        self._card_to_chara: dict[int, int] = {}
        self._last_ace: dict[str, Any] | None = None
        self._last_future_parent: dict[str, Any] | None = None
        self._last_profile: dict[str, Any] = {}
        self._active_result_kind = ""
        self._rail_state_restored = False

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 24, 18)
        root.setSpacing(10)
        self.header = PageHeader("", "")
        root.addWidget(self.header)

        # The workspace is split rather than stacked. Configuration used to sit
        # above the results and claim a fixed slice of height on every visit,
        # leaving the tables and their rich-text diagnostics — the part actually
        # read — whatever remained. A collapsible rail lets the results own the
        # full height while keeping every setting one click away.
        self.workspace = QSplitter(Qt.Orientation.Horizontal)
        self.workspace.setChildrenCollapsible(False)
        self.workspace.setHandleWidth(6)

        self.rail = QWidget()
        rail_layout = QVBoxLayout(self.rail)
        rail_layout.setContentsMargins(0, 0, 6, 0)
        rail_layout.setSpacing(8)
        self.rail_title = section_label("")
        rail_layout.addWidget(self.rail_title)

        self.rail_scroll = QScrollArea()
        self.rail_scroll.setWidgetResizable(True)
        self.rail_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.rail_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        rail_body = QWidget()
        rail_body_layout = QVBoxLayout(rail_body)
        rail_body_layout.setContentsMargins(0, 0, 0, 0)
        rail_body_layout.setSpacing(8)

        self.section_objective = SummarySection("")
        objective = QGridLayout()
        objective.setHorizontalSpacing(12)
        objective.setVerticalSpacing(6)
        self.ace_label = QLabel("")
        self.ace_combo = SearchableComboBox()
        self.target_label = QLabel("")
        self.target_combo = SearchableComboBox()
        self.top_label = QLabel("")
        self.top_spin = QSpinBox()
        self.top_spin.setRange(5, 200)
        self.top_spin.setValue(context.lineage_state().top_n)
        self.refresh_button = QPushButton("")
        objective.addWidget(self.ace_label, 0, 0, 1, 2)
        objective.addWidget(self.ace_combo, 1, 0, 1, 2)
        objective.addWidget(self.target_label, 2, 0, 1, 2)
        objective.addWidget(self.target_combo, 3, 0, 1, 2)
        objective.addWidget(self.top_label, 4, 0)
        objective.addWidget(self.top_spin, 5, 0)
        objective.addWidget(self.refresh_button, 5, 1)
        objective.setColumnStretch(0, 1)
        objective.setColumnStretch(1, 1)
        self.section_objective.content_layout.addLayout(objective)
        self.section_objective.toggle.setChecked(True)
        rail_body_layout.addWidget(self.section_objective)

        # The editor keeps owning its controls and their synchronisation; the
        # rail only decides where its two groups are shown.
        self.race_editor = LineageRaceEditor(context, self, host_sections=True)
        self.race_editor.shared_hint.setVisible(False)
        self.race_editor.panel.setObjectName("subtlePanel")

        self.section_course = SummarySection("")
        self.section_course.content_layout.addWidget(self.race_editor.panel)
        rail_body_layout.addWidget(self.section_course)

        self.section_conditions = SummarySection("", resettable=True)
        self.section_conditions.content_layout.addWidget(
            self.race_editor.advanced_body
        )
        rail_body_layout.addWidget(self.section_conditions)

        rail_body_layout.addStretch(1)
        self.rail_scroll.setWidget(rail_body)
        rail_layout.addWidget(self.rail_scroll, 1)
        self.workspace.addWidget(self.rail)

        main = QWidget()
        main_layout = QVBoxLayout(main)
        main_layout.setContentsMargins(10, 0, 0, 0)
        main_layout.setSpacing(10)
        ribbon = QHBoxLayout()
        ribbon.setSpacing(8)
        self.rail_toggle = QToolButton()
        self.rail_toggle.setCheckable(True)
        self.rail_toggle.setAutoRaise(True)
        self.context_summary = muted_label("", wrap=False)
        ribbon.addWidget(self.rail_toggle)
        ribbon.addWidget(self.context_summary, 1)
        main_layout.addLayout(ribbon)
        self.workspace.addWidget(main)
        self.workspace.setStretchFactor(0, 0)
        self.workspace.setStretchFactor(1, 1)
        root.addWidget(self.workspace, 1)

        source_layout = QHBoxLayout()
        source_layout.setSpacing(10)
        self.local_card = QFrame()
        self.local_card.setObjectName("panel")
        local = QVBoxLayout(self.local_card)
        local.setContentsMargins(16, 12, 16, 13)
        local.setSpacing(7)
        local_head = QHBoxLayout()
        self.local_title = section_label("")
        self.local_badge = QLabel("")
        self.local_badge.setObjectName("pillAccent")
        local_head.addWidget(self.local_title)
        local_head.addStretch(1)
        local_head.addWidget(self.local_badge)
        self.local_hint = muted_label("")
        local_actions = QHBoxLayout()
        self.local_pairs_button = QPushButton("")
        self.local_pairs_button.setObjectName("primary")
        self.local_parents_button = QPushButton("")
        self.local_future_button = QPushButton("")
        local_actions.addWidget(self.local_pairs_button)
        local_actions.addWidget(self.local_parents_button)
        local_actions.addWidget(self.local_future_button)
        local.addLayout(local_head)
        local.addWidget(self.local_hint)
        local.addLayout(local_actions)

        self.online_card = QFrame()
        self.online_card.setObjectName("panel")
        online = QVBoxLayout(self.online_card)
        online.setContentsMargins(16, 12, 16, 13)
        online.setSpacing(7)
        online_head = QHBoxLayout()
        self.online_title = section_label("")
        self.online_badge = QLabel("")
        self.online_badge.setObjectName("pill")
        online_head.addWidget(self.online_title)
        online_head.addStretch(1)
        self.online_hint = muted_label("")
        online_actions = QHBoxLayout()
        self.online_parent_button = QPushButton("")
        self.online_parent_button.setObjectName("primary")
        self.online_gp_button = QPushButton("")
        self.online_options_button = QPushButton("")
        self.online_options_menu = QMenu(self.online_options_button)
        self.online_parent_options_action = self.online_options_menu.addAction("")
        self.online_gp_options_action = self.online_options_menu.addAction("")
        self.online_options_button.setMenu(self.online_options_menu)
        online_actions.addWidget(self.online_parent_button)
        online_actions.addWidget(self.online_gp_button)
        online_secondary = QHBoxLayout()
        self.online_import_button = QPushButton("")
        self.online_import_menu = QMenu(self.online_import_button)
        self.online_parent_import_action = self.online_import_menu.addAction("")
        self.online_gp_import_action = self.online_import_menu.addAction("")
        self.online_import_button.setMenu(self.online_import_menu)
        self.local_gp_pairs_button = QPushButton("")
        online_secondary.addWidget(self.online_import_button)
        online_secondary.addWidget(self.local_gp_pairs_button)
        online_secondary.addStretch(1)
        compact_button_style = (
            "QPushButton { padding-left: 6px; padding-right: 6px; }"
        )
        for button in (
            self.local_pairs_button,
            self.local_parents_button,
            self.local_future_button,
            self.online_parent_button,
            self.online_gp_button,
            self.online_import_button,
            self.local_gp_pairs_button,
        ):
            button.setStyleSheet(compact_button_style)
        online_head.addWidget(self.online_options_button)
        online_head.addWidget(self.online_badge)
        online.addLayout(online_head)
        online.addWidget(self.online_hint)
        online.addLayout(online_actions)
        online.addLayout(online_secondary)
        source_layout.addWidget(self.local_card, 1)
        source_layout.addWidget(self.online_card, 1)
        main_layout.addLayout(source_layout)

        result_frame = QFrame()
        result_frame.setObjectName("panel")
        result_layout = QVBoxLayout(result_frame)
        result_layout.setContentsMargins(10, 9, 10, 10)
        result_layout.setSpacing(7)
        result_head = QHBoxLayout()
        self.results_title = section_label("")
        self.result_badge = QLabel("")
        self.result_badge.setObjectName("pillAccent")
        self.result_badge.setVisible(False)
        self.results_context = muted_label("")
        self.export_button = QPushButton("")
        self.export_button.setVisible(False)
        self.load_button = QPushButton("")
        self.open_button = QPushButton("")
        result_head.addWidget(self.results_title)
        result_head.addWidget(self.result_badge)
        result_head.addWidget(self.results_context, 1)
        result_head.addWidget(self.export_button)
        result_head.addWidget(self.load_button)
        result_head.addWidget(self.open_button)
        result_layout.addLayout(result_head)

        self.result_stack = QStackedWidget()
        placeholder = QWidget()
        placeholder_layout = QVBoxLayout(placeholder)
        placeholder_layout.setContentsMargins(28, 28, 28, 28)
        self.placeholder_title = QLabel("")
        self.placeholder_title.setObjectName("sectionTitle")
        self.placeholder_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder_hint = muted_label("")
        self.placeholder_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder_layout.addStretch(1)
        placeholder_layout.addWidget(self.placeholder_title)
        placeholder_layout.addWidget(self.placeholder_hint)
        placeholder_layout.addStretch(1)
        self.pair_results = ResultPane("pair", context)
        self.branch_results = ResultPane("branch", context)
        self.future_results = ResultPane("future", context)
        self.online_results = OnlineResultsPane(context)
        for widget in (
            placeholder,
            self.pair_results,
            self.branch_results,
            self.future_results,
            self.online_results,
        ):
            self.result_stack.addWidget(widget)
        result_layout.addWidget(self.result_stack, 1)
        main_layout.addWidget(result_frame, 1)

        self.refresh_button.clicked.connect(
            lambda: self.refresh_options(show_errors=True)
        )
        self.rail_toggle.toggled.connect(self._rail_toggled)
        self.section_conditions.reset_requested.connect(
            self.race_editor.clear_static_conditions
        )
        self.ace_combo.currentIndexChanged.connect(self._ace_changed)
        self.target_combo.currentIndexChanged.connect(self._lineage_selection_changed)
        self.top_spin.valueChanged.connect(self._lineage_selection_changed)
        self.race_editor.changed.connect(self._refresh_context)
        self.local_pairs_button.clicked.connect(lambda: self.start_local("pairs"))
        self.local_parents_button.clicked.connect(lambda: self.start_local("branches"))
        self.local_future_button.clicked.connect(lambda: self.start_local("future"))
        self.online_parent_button.clicked.connect(
            lambda: self.start_online("parent")
        )
        self.online_gp_button.clicked.connect(
            lambda: self.start_online("grandparent")
        )
        self.online_parent_options_action.triggered.connect(
            lambda _checked=False: self.open_online_options("parent")
        )
        self.online_gp_options_action.triggered.connect(
            lambda _checked=False: self.open_online_options("grandparent")
        )
        self.online_parent_import_action.triggered.connect(
            lambda _checked=False: self.start_online_import("parent")
        )
        self.online_gp_import_action.triggered.connect(
            lambda _checked=False: self.start_online_import("grandparent")
        )
        self.local_gp_pairs_button.clicked.connect(
            lambda: self.start_online("grandparent", local_pairs=True)
        )
        self.export_button.clicked.connect(self.export_selected_pair)
        self.load_button.clicked.connect(lambda: self.load_latest(show_errors=True))
        self.open_button.clicked.connect(self.open_output)
        context.lineage_changed.connect(self._sync_lineage_context)
        context.configuration_changed.connect(self._schedule_refresh)
        context.integration_changed.connect(self._refresh_integration)
        context.language_changed.connect(self._language_changed)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self._initial_refresh)
        self._initial_refresh_timer = QTimer(self)
        self._initial_refresh_timer.setSingleShot(True)
        self._initial_refresh_timer.timeout.connect(self._initial_refresh)
        self._initial_result_timer = QTimer(self)
        self._initial_result_timer.setSingleShot(True)
        self._initial_result_timer.timeout.connect(self._initial_result)

        self.retranslate()
        self._sync_lineage_context()
        self._initial_refresh_timer.start(0)
        self._initial_result_timer.start(80)

    def showEvent(self, event) -> None:
        # Width-based inference has to wait for a real geometry: during
        # construction the page is not in its window yet and reports Qt's
        # default size, which would collapse the rail on every machine.
        super().showEvent(event)
        if not self._rail_state_restored:
            self._rail_state_restored = True
            self._restore_rail_state()

    def _restore_rail_state(self) -> None:
        """Apply the stored rail preference, or infer one from the width.

        Below the threshold the rail and a result pane cannot both be readable:
        the diagnostics browser needs its documented minimum before its Spark
        tables are worth rendering. Starting collapsed there keeps the first
        view usable, while an explicit user choice always wins afterwards.
        """
        stored = self.context.store.get(RAIL_COLLAPSED_KEY, "")
        if stored in {"0", "1"}:
            collapsed = stored == "1"
        else:
            window = self.window()
            width = window.width() if window is not None else 0
            collapsed = 0 < width < NARROW_WORKSPACE_WIDTH
        self.set_rail_collapsed(collapsed, persist=False)

    def set_rail_collapsed(self, collapsed: bool, *, persist: bool = True) -> None:
        self.rail.setVisible(not collapsed)
        if self.rail_toggle.isChecked() != collapsed:
            self.rail_toggle.blockSignals(True)
            self.rail_toggle.setChecked(collapsed)
            self.rail_toggle.blockSignals(False)
        if not collapsed:
            self.workspace.setSizes([RAIL_WIDTH, max(1, self.width() - RAIL_WIDTH)])
        self._retranslate_rail_toggle()
        if persist:
            self.context.store.update({RAIL_COLLAPSED_KEY: "1" if collapsed else "0"})

    def _rail_toggled(self, collapsed: bool) -> None:
        self.set_rail_collapsed(collapsed)

    def _retranslate_rail_toggle(self) -> None:
        t = self.context.t
        collapsed = self.rail_toggle.isChecked()
        self.rail_toggle.setText(
            f"⇥  {t('Contexte')}" if collapsed else f"⇤  {t('Contexte')}"
        )
        self.rail_toggle.setToolTip(
            t("Afficher le contexte") if collapsed else t("Masquer le contexte")
        )

    def _initial_refresh(self) -> None:
        self.refresh_options(show_errors=False)

    def _initial_result(self) -> None:
        self.load_latest(show_errors=False)

    def _language_changed(self, _language: str) -> None:
        self.retranslate()

    def _schedule_refresh(self) -> None:
        self._refresh_timer.start(120)

    def refresh_options(self, *, show_errors: bool = True) -> None:
        try:
            master = Path(self.context.master_path).expanduser()
            data = Path(self.context.veterans_json_path).expanduser()
            self._ace_options = list(load_ace_options(master))
            self._local_options = load_local_veteran_options(master, data)
            self._track_options = list(load_track_options(master))
        except Exception as exc:
            if show_errors:
                QMessageBox.warning(
                    self,
                    self.context.t("Configuration incomplète"),
                    self.context.t(str(exc)),
                )
            self._refresh_source_badges()
            return
        self._card_to_chara = {
            option.card_id: option.chara_id for option in self._ace_options
        }
        state = self.context.lineage_state()
        self._syncing_lineage = True
        try:
            for combo, selected in (
                (self.ace_combo, state.ace_card_id),
                (self.target_combo, state.future_parent_card_id),
            ):
                combo.blockSignals(True)
                combo.clear()
                for option in self._ace_options:
                    combo.addItem(option.display_name, option.card_id)
                index = combo.findData(selected)
                combo.setCurrentIndex(
                    index if index >= 0 else (0 if combo.count() else -1)
                )
                combo.blockSignals(False)
            self._ensure_distinct_parent()
        finally:
            self._syncing_lineage = False
        self.race_editor.set_track_options(
            sorted(self._track_options, key=lambda item: item.name.casefold())
        )
        self._lineage_selection_changed()
        self._refresh_source_badges()

    def _ensure_distinct_parent(self) -> None:
        ace_id = _integer(self.ace_combo.currentData())
        parent_id = _integer(self.target_combo.currentData())
        ace_chara = self._card_to_chara.get(ace_id)
        if ace_chara is None or self._card_to_chara.get(parent_id) != ace_chara:
            return
        for index in range(self.target_combo.count()):
            candidate = _integer(self.target_combo.itemData(index))
            if self._card_to_chara.get(candidate) != ace_chara:
                self.target_combo.setCurrentIndex(index)
                return

    def _ace_changed(self, _index: int) -> None:
        if self._syncing_lineage:
            return
        self._ensure_distinct_parent()
        self._lineage_selection_changed()

    def _lineage_selection_changed(self, *_args: object) -> None:
        if self._syncing_lineage:
            return
        changes: dict[str, object] = {"top_n": self.top_spin.value()}
        ace_id = _integer(self.ace_combo.currentData())
        target_id = _integer(self.target_combo.currentData())
        if ace_id:
            changes["ace_card_id"] = ace_id
        if target_id:
            changes["future_parent_card_id"] = target_id
        self.context.update_lineage(**changes)
        self._refresh_context()

    def _sync_lineage_context(
        self, _state: LineageContextState | None = None
    ) -> None:
        state = self.context.lineage_state()
        corrected_parent = 0
        self._syncing_lineage = True
        try:
            for combo, selected in (
                (self.ace_combo, state.ace_card_id),
                (self.target_combo, state.future_parent_card_id),
            ):
                index = combo.findData(selected)
                if index >= 0 and combo.currentIndex() != index:
                    combo.blockSignals(True)
                    combo.setCurrentIndex(index)
                    combo.blockSignals(False)
            self._ensure_distinct_parent()
            corrected_parent = _integer(self.target_combo.currentData())
            self.top_spin.blockSignals(True)
            self.top_spin.setValue(state.top_n)
            self.top_spin.blockSignals(False)
        finally:
            self._syncing_lineage = False
        if corrected_parent and corrected_parent != state.future_parent_card_id:
            self.context.update_lineage(future_parent_card_id=corrected_parent)
        else:
            self._refresh_context()

    def _refresh_context(self, *_args: object) -> None:
        state = self.context.lineage_state()
        profile = self.race_editor.current_profile()
        condition_parts = [
            self.context.t(value)
            for value in (
                state.rotation,
                state.season,
                state.weather,
                state.ground_condition,
            )
            if value and value != "Non précisé"
        ]
        text = profile_summary(profile, self.context.language)
        text += f" · {self.race_editor.current_course_label()}"
        if condition_parts:
            text += " · " + " / ".join(condition_parts)
        self.context_summary.setText(text)
        self._refresh_section_summaries(state, profile)

    def _refresh_section_summaries(
        self, state: LineageContextState, profile: dict[str, str]
    ) -> None:
        """Keep every collapsed section readable.

        A closed section must still answer what the next calculation will use,
        so each header restates its effective values rather than only its name.
        """
        t = self.context.t
        ace = self.ace_combo.currentText().strip()
        target = self.target_combo.currentText().strip()
        objective = " → ".join(part for part in (ace, target) if part)
        top = t("{count} résultats").replace("{count}", str(state.top_n))
        self.section_objective.set_summary(
            f"{objective} · {top}" if objective else t("Aucun Ace sélectionné")
        )

        self.section_course.set_summary(
            profile_summary(profile, self.context.language)
            + f" · {self.race_editor.current_course_label()}"
        )

        static_labels = self.race_editor.static_condition_labels()
        self.section_conditions.set_summary(
            " · ".join(static_labels)
            if static_labels
            else t("Aucune condition fixée")
        )
        self.section_conditions.set_modified(bool(static_labels), t("Modifié"))

    def _refresh_source_badges(self) -> None:
        self.local_badge.setText(
            self.context.t("{count} vétérans").replace(
                "{count}", str(len(self._local_options))
            )
        )
        self._refresh_integration()

    def _refresh_integration(self) -> None:
        status = (
            self.context.t("API configurée")
            if self.context.uma_moe_api_key
            else self.context.t("Clé API absente")
        )
        self.online_badge.setText(status)

    def open_conditions(self) -> None:
        """Reveal the static conditions instead of opening a modal editor.

        Kept as a named entry point so any caller asking for "the conditions"
        lands on them, now that they live in the rail rather than in a dialog.
        """
        self.set_rail_collapsed(False)
        self.section_conditions.toggle.setChecked(True)
        self.rail_scroll.ensureWidgetVisible(self.section_conditions)
        self._refresh_context()

    def _selected_ids(self) -> tuple[int, int]:
        self.ace_combo.resolve_current_text()
        self.target_combo.resolve_current_text()
        return (
            _integer(self.ace_combo.currentData()),
            _integer(self.target_combo.currentData()),
        )

    def _optimization_request(self, kind: str) -> OptimizationRequest:
        ace_id, target_id = self._selected_ids()
        if ace_id <= 0:
            raise OptimizerError("Sélectionne l’Ace cible.")
        if kind == "future" and target_id <= 0:
            raise OptimizerError("Sélectionne le parent à produire.")
        if (
            kind == "future"
            and self._card_to_chara.get(ace_id) == self._card_to_chara.get(target_id)
        ):
            raise OptimizerError(
                "L'Ace et le parent à produire doivent être deux personnages différents."
            )
        profile = self.race_editor.current_profile()
        return OptimizationRequest(
            master_path=Path(self.context.master_path).expanduser(),
            veterans_json_path=Path(self.context.veterans_json_path).expanduser(),
            output_dir=Path(self.context.output_dir).expanduser(),
            ace_card_id=ace_id,
            future_parent_card_id=target_id,
            surface=profile["surface"],
            distance=profile["distance"],
            style=profile["style"],
            course_overrides_path=self.race_editor.course_overrides_path(),
            course_key=self.race_editor.current_course_key(),
            course_conditions=self.race_editor.selected_conditions(),
            top_n=self.top_spin.value(),
            use_custom_scoring=self.race_editor.custom_scoring.isChecked(),
            skill_priorities_path=self.race_editor.skill_priorities_path(),
            search_kind=kind,
        )

    def start_local(self, kind: str) -> None:
        try:
            request = self._optimization_request(kind)
        except (OptimizerError, ValueError) as exc:
            QMessageBox.warning(
                self,
                self.context.t("Configuration incomplète"),
                self.context.t(str(exc)),
            )
            return
        labels = {
            "pairs": "Recherche des paires finales locales…",
            "branches": "Classement des parents locaux…",
            "future": "Classement des grands-parents locaux…",
        }
        self.context.update_lineage(
            ace_card_id=request.ace_card_id,
            future_parent_card_id=request.future_parent_card_id,
            top_n=request.top_n,
        )
        self.task_requested.emit(
            partial(run_optimization, request),
            self.context.t(labels[kind]),
            lambda result: self._local_done(result, kind),
        )

    def _local_done(self, result: object, kind: str) -> None:
        self._last_ace = getattr(result, "ace", None)
        self._last_future_parent = getattr(result, "future_parent", None)
        self._last_profile = dict(getattr(result, "profile", None) or {})
        if kind == "pairs":
            self.pair_results.set_rows(
                list(getattr(result, "top_parent_pairs", ()) or ()),
                self._last_profile,
                lineage_root=self._last_ace,
            )
            widget = self.pair_results
        elif kind == "branches":
            self.branch_results.set_rows(
                list(getattr(result, "top_parent_candidates", ()) or ()),
                self._last_profile,
                lineage_root=self._last_ace,
            )
            widget = self.branch_results
        else:
            self.future_results.set_rows(
                list(getattr(result, "top_future_grandparents", ()) or ()),
                self._last_profile,
                lineage_root=self._last_future_parent,
            )
            widget = self.future_results
        self._show_results(widget, f"local:{kind}", self._last_profile)

    def _online_options_values(self, mode: str) -> dict[str, Any]:
        dialog = OnlineSearchOptionsDialog(
            self.context,
            mode,
            self._ace_options,
            self._local_options,
            self,
        )
        values = dialog.values()
        dialog.deleteLater()
        return values

    def open_online_options(self, mode: str | None = None) -> None:
        mode = mode or self.context.store.get("uma_moe_search_mode", "parent")
        dialog = OnlineSearchOptionsDialog(
            self.context,
            mode,
            self._ace_options,
            self._local_options,
            self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._refresh_integration()
        dialog.deleteLater()

    def start_online_import(self, mode: str | None = None) -> None:
        mode = mode or self.context.store.get("uma_moe_search_mode", "parent")
        self.start_online(mode, use_import=True)

    def start_online(
        self,
        mode: str,
        *,
        use_import: bool = False,
        local_pairs: bool = False,
    ) -> None:
        mode = "parent" if mode == "parent" else "grandparent"
        try:
            ace_id, target_id = self._selected_ids()
            if ace_id <= 0:
                raise UmaMoeError("Sélectionne l’Ace cible.")
            if mode == "grandparent" and target_id <= 0:
                raise UmaMoeError("Sélectionne le parent à produire.")
            options = self._online_options_values(mode)
            required = options["required_parent_card_id"]
            if required in set(options["excluded_parent_card_ids"]):
                raise UmaMoeError("Le costume requis est également exclu.")
            if (
                options["allowed_parent_card_ids"]
                and required is not None
                and required not in set(options["allowed_parent_card_ids"])
            ):
                raise UmaMoeError(
                    "Le costume requis doit être présent dans les costumes autorisés."
                )
            response_text = options["response_path"]
            response = Path(response_text).expanduser() if response_text else None
            if use_import and (response is None or not response.is_file()):
                raise UmaMoeError("Sélectionne une réponse JSON uma.moe à importer.")
            profile = self.race_editor.current_profile()
            request = OnlineSearchRequest(
                search_mode=mode,
                master_path=Path(self.context.master_path).expanduser(),
                veterans_json_path=Path(self.context.veterans_json_path).expanduser(),
                output_dir=Path(self.context.output_dir).expanduser(),
                ace_card_id=ace_id,
                target_parent_card_id=(target_id if mode == "grandparent" else None),
                fixed_local_id=options["fixed_local_id"],
                automatic_pairs=options["automatic_pairs"],
                local_pool_size=options["local_pool_size"],
                remote_pool_size=options["remote_pool_size"],
                surface=profile["surface"],
                distance=profile["distance"],
                style=profile["style"],
                course_overrides_path=self.race_editor.course_overrides_path(),
                course_key=self.race_editor.current_course_key(),
                course_conditions=self.race_editor.selected_conditions(),
                top_n=self.top_spin.value(),
                use_import=use_import,
                response_path=response,
                api_base=self.context.uma_moe_api_base,
                uql="",
                auto_uql=True,
                uql_options=options["uql_options"],
                limit=options["limit"],
                planned_g1_budget=options["planned_g1_budget"],
                g1_win_probability_cutoff=options["g1_win_probability_cutoff"],
                required_parent_card_id=required,
                allowed_parent_card_ids=options["allowed_parent_card_ids"],
                excluded_parent_card_ids=options["excluded_parent_card_ids"],
                token=self.context.uma_moe_api_key,
                use_custom_scoring=self.race_editor.custom_scoring.isChecked(),
                skill_priorities_path=self.race_editor.skill_priorities_path(),
                opposing_parent_trained_id=options[
                    "opposing_parent_trained_id"
                ],
                opposing_parent_payload=options["opposing_parent_payload"],
                local_pair_mode=local_pairs,
                lineage_blue_filter=options["lineage_blue_filter"],
                lineage_pink_filter=options["lineage_pink_filter"],
            )
        except (UmaMoeError, OptimizerError, ValueError) as exc:
            QMessageBox.warning(
                self,
                self.context.t("Configuration incomplète"),
                self.context.t(str(exc)),
            )
            return
        self.context.store.update(
            {
                "uma_moe_search_mode": mode,
                "uma_moe_response_path": options["response_path"],
            }
        )
        updates: dict[str, object] = {
            "ace_card_id": request.ace_card_id,
            "top_n": request.top_n,
        }
        if request.target_parent_card_id:
            updates["future_parent_card_id"] = request.target_parent_card_id
        self.context.update_lineage(**updates)
        label = (
            "Classement des paires de GP locales…"
            if local_pairs
            else "Recherche et classement uma.moe…"
        )
        self.task_requested.emit(
            partial(run_online_search, request),
            self.context.t(label),
            lambda result: self._online_done(result, request),
        )

    def _online_done(self, result: object, request: OnlineSearchRequest) -> None:
        profile = {
            "surface": request.surface,
            "distance": request.distance,
            "style": request.style,
        }
        self.online_results.set_result(result, profile)
        source = "local" if request.local_pair_mode else "uma.moe"
        self._show_results(
            self.online_results,
            f"{source}:online_{request.search_mode}",
            profile,
        )
        response = request.output_dir / "uma_moe_api_response.json"
        if not request.use_import and response.is_file():
            self.context.store.update({"uma_moe_response_path": str(response)})

    def _show_results(
        self,
        widget: QWidget,
        kind: str,
        profile: dict[str, Any] | None,
    ) -> None:
        self._active_result_kind = kind
        self.result_stack.setCurrentWidget(widget)
        labels = {
            "local:pairs": "Local · paires finales",
            "local:branches": "Local · parents",
            "local:future": "Local · grands-parents",
            "uma.moe:online_parent": "uma.moe · parents distants",
            "uma.moe:online_grandparent": "uma.moe · grands-parents distants",
            "local:online_grandparent": "Local · paires de grands-parents",
        }
        self.result_badge.setText(self.context.t(labels.get(kind, kind)))
        self.result_badge.setVisible(True)
        self.results_context.setText(
            profile_summary(dict(profile or {}), self.context.language)
        )
        self.export_button.setVisible(kind == "local:pairs")

    def load_latest(self, *, show_errors: bool = True) -> None:
        output = Path(self.context.output_dir).expanduser()
        candidates = [
            (latest_rankings_path(output), "local"),
            (output / "uma_moe_parent_pairs.json", "online_parent"),
            (output / "uma_moe_grandparent_pairs.json", "online_grandparent"),
        ]
        existing = [(path, kind) for path, kind in candidates if path.is_file()]
        if not existing:
            if show_errors:
                QMessageBox.information(
                    self,
                    self.context.t("Dernier résultat"),
                    self.context.t(
                        "Aucun résultat local ou uma.moe n’a encore été généré."
                    ),
                )
            return
        path, stored_kind = max(existing, key=lambda item: item[0].stat().st_mtime)
        try:
            if stored_kind == "local":
                payload = load_rankings_payload(path)
            else:
                payload = json.loads(path.read_text(encoding="utf-8-sig"))
                if not isinstance(payload, dict):
                    raise ValueError("Le résultat doit être un objet JSON.")
        except Exception as exc:
            if show_errors:
                QMessageBox.warning(
                    self,
                    self.context.t("Dernier résultat"),
                    self.context.t(str(exc)),
                )
            return
        if stored_kind != "local":
            mode = "parent" if stored_kind == "online_parent" else "grandparent"
            metadata = payload.get("metadata") or {}
            profile = metadata.get("profile") or {}
            self.online_results.set_payload(payload, mode)
            is_local_gp = str(metadata.get("pair_mode") or "").startswith("local_")
            source = "local" if is_local_gp else "uma.moe"
            self._show_results(
                self.online_results,
                f"{source}:online_{mode}",
                profile,
            )
            return
        ace = payload.get("ace") if isinstance(payload.get("ace"), dict) else None
        future_parent = (
            payload.get("future_parent")
            if isinstance(payload.get("future_parent"), dict)
            else None
        )
        profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}
        self._last_ace = ace
        self._last_future_parent = future_parent
        self._last_profile = dict(profile)
        kind = str((payload.get("metadata") or {}).get("search_kind") or "all")
        pairs = list(payload.get("top_parent_pairs") or [])
        branches = list(payload.get("top_parent_candidates") or [])
        future = list(payload.get("top_future_grandparents") or [])
        if pairs and kind in {"all", "pairs"}:
            self.pair_results.set_rows(pairs, profile, lineage_root=ace)
            self._show_results(self.pair_results, "local:pairs", profile)
        elif branches and kind in {"all", "branches"}:
            self.branch_results.set_rows(branches, profile, lineage_root=ace)
            self._show_results(self.branch_results, "local:branches", profile)
        elif future:
            self.future_results.set_rows(
                future, profile, lineage_root=future_parent
            )
            self._show_results(self.future_results, "local:future", profile)

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
        suggested = (
            Path(self.context.output_dir).expanduser()
            / f"local_lineage_{ace_id}_{p1_id}_{p2_id}.json"
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
                self._last_ace,
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
            self.context.t("Fichier créé : {path}").replace("{path}", str(path)),
        )

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        for widget in (
            self.refresh_button,
            self.local_pairs_button,
            self.local_parents_button,
            self.local_future_button,
            self.online_parent_button,
            self.online_gp_button,
            self.online_options_button,
            self.online_import_button,
            self.local_gp_pairs_button,
            self.load_button,
        ):
            widget.setEnabled(not busy)

    def open_output(self) -> None:
        output = Path(self.context.output_dir).expanduser()
        try:
            output.mkdir(parents=True, exist_ok=True)
            open_path(output)
        except OSError as exc:
            QMessageBox.critical(self, self.context.t("Erreur"), str(exc))

    def retranslate(self) -> None:
        t = self.context.t
        self.header.set_text(
            t("Recherche de lignées"),
            t(
                "Définis l’objectif une seule fois, puis choisis explicitement la source et le calcul à lancer."
            ),
        )
        self.rail_title.setText(t("Contexte commun"))
        self.section_objective.set_title(t("Objectif"))
        self.section_course.set_title(t("Course et profil"))
        self.section_conditions.set_title(t("Conditions statiques"))
        self.section_conditions.set_reset_text(
            t("Réinitialiser"),
            t("Remet les conditions statiques sur « Non précisé »."),
        )
        self._retranslate_rail_toggle()
        self.refresh_button.setText(t("Actualiser"))
        self.ace_label.setText(t("Ace visé"))
        self.target_label.setText(t("Parent à produire") + " · " + t("pour les recherches GP"))
        self.top_label.setText(t("Résultats"))
        self.local_title.setText(t("Collection locale"))
        self.local_hint.setText(
            t("Aucun accès réseau. Chaque bouton ne calcule que le résultat demandé.")
        )
        self.local_pairs_button.setText(t("Paires finales"))
        self.local_parents_button.setText(t("Parents"))
        self.local_future_button.setText(t("Grands-parents"))
        self.online_title.setText("uma.moe")
        self.online_hint.setText(
            t("Candidats publics combinés à ta collection, puis classés par le moteur exact local.")
        )
        self.online_parent_button.setText(t("Parent distant"))
        self.online_gp_button.setText(t("Grand-parent distant"))
        self.online_options_button.setText(t("Options…"))
        self.online_parent_options_action.setText(t("Options du parent distant…"))
        self.online_gp_options_action.setText(t("Options du grand-parent distant…"))
        self.online_import_button.setText(t("Classer un JSON…"))
        self.online_parent_import_action.setText(t("JSON de parent distant…"))
        self.online_gp_import_action.setText(t("JSON de grand-parent distant…"))
        self.local_gp_pairs_button.setText(t("Paires de GP locales"))
        self.results_title.setText(t("Résultats"))
        self.export_button.setText(t("Exporter vers Lineage Planner…"))
        self.load_button.setText(t("Charger le dernier résultat"))
        self.open_button.setText(t("Ouvrir la sortie"))
        self.placeholder_title.setText(t("Aucune recherche affichée"))
        self.placeholder_hint.setText(
            t("Choisis un calcul local ou uma.moe ci-dessus ; son tableau et son diagnostic apparaîtront ici.")
        )
        self.pair_results.retranslate()
        self.branch_results.retranslate()
        self.future_results.retranslate()
        self.online_results.retranslate()
        self._refresh_context()
        self._refresh_source_badges()
