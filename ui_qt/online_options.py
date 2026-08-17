"""uma.moe search options, as rail sections instead of a modal editor.

Two per-mode dialogs used to write one mostly shared set of keys, so editing
the parent filters silently rewrote the grandparent search. Splitting the
controls is therefore not enough: the storage has to agree with what the
interface claims. Each setting is placed by what it *describes*.

* **The target build → shared.** Retrieval preferences, the minimum Pink
  rating, the remote-lineage minima and the costume allow/exclude lists
  constrain which remote candidates are acceptable at all. Every remote search
  already consumed them jointly; they now say so.
* **One search's strategy → per mode.** Pairing, the fixed local veteran, both
  pool sizes, the fetch limit and the offline import path are decisions about
  *this* search. A fixed parent is not a fixed GP1 — the legacy store even
  used one key for both roles — and a 2 000-candidate parent sweep implies
  nothing about a GP2 scan.

Per-mode keys fall back to their legacy shared value on first read, so an
existing configuration keeps behaving exactly as before until one side is
edited.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Iterable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QGridLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QWidget,
)

from parent_optimizer import (
    DISTANCE_FACTOR_NAMES,
    STYLE_FACTOR_NAMES,
    SURFACE_FACTOR_NAMES,
)
from ui_qt.components import (
    PathPicker,
    SearchableComboBox,
    SummarySection,
    ThemedComboBox,
    muted_label,
)
from ui_qt.context import AppContext
from ui_qt.core import VeteranOption, load_opposing_parent_candidates
from ui_qt.result_panes import CardFilterDialog

PARENT_MODE = "parent"
GRANDPARENT_MODE = "grandparent"

BLUE_FACTOR_NAMES = ("Speed", "Stamina", "Power", "Guts", "Wit")

# Legacy keys shared by both modes. They are still read as the fallback for the
# per-mode keys, and deliberately left in the store as inert history.
LEGACY_STRATEGY_KEYS = {
    "auto_pairs": "uma_moe_auto_pairs",
    "fixed_local_id": "uma_moe_fixed_gp_id",
    "local_pool": "uma_moe_local_pool",
    "remote_pool": "uma_moe_remote_pool",
    "limit": "uma_moe_limit",
    "response_path": "uma_moe_response_path",
}

STRATEGY_DEFAULTS = {
    "auto_pairs": "1",
    "fixed_local_id": "0",
    "local_pool": "100",
    "remote_pool": "100",
    "limit": "500",
    "response_path": "",
}


def mode_key(mode: str, name: str) -> str:
    prefix = "uma_moe_parent" if mode == PARENT_MODE else "uma_moe_gp"
    return f"{prefix}_{name}"


def strategy_value(context: AppContext, mode: str, name: str) -> str:
    """Read a per-mode strategy value, falling back to its legacy shared key.

    The fallback is what keeps the migration silent: until the user edits one
    mode, both modes still resolve to the value the single dialog stored.
    """
    stored = context.store.get(mode_key(mode, name), "")
    if stored != "":
        return stored
    legacy = context.store.get(LEGACY_STRATEGY_KEYS[name], "")
    return legacy if legacy != "" else STRATEGY_DEFAULTS[name]


def _integer(value: object, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _boolean(value: object) -> bool:
    return str(value).strip() not in {"0", "false", "False", ""}


def _id_set(value: str) -> set[int]:
    result: set[int] = set()
    for part in str(value or "").replace(";", ",").split(","):
        candidate = _integer(part, 0)
        if candidate > 0:
            result.add(candidate)
    return result


class OnlineRetrievalSection(SummarySection):
    """Constraints on which remote candidates are acceptable at all.

    Shared by both remote searches, and labelled as such: these values derive
    from the one shared build context exactly like surface or distance do.
    """

    changed = Signal()

    def __init__(self, context: AppContext, parent=None) -> None:
        super().__init__("", parent)
        self.context = context
        self._ace_options: list[Any] = []
        self._allowed_ids = _id_set(
            context.store.get("uma_moe_parent_allowed_card_ids")
        )
        self._excluded_ids = _id_set(
            context.store.get("uma_moe_parent_excluded_card_ids")
        )

        body = QWidget()
        grid = QGridLayout(body)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(7)

        self.hint = muted_label("")
        self.hint.setWordWrap(True)
        self.prefer_profile = QCheckBox("")
        self.prefer_profile.setChecked(_boolean(context.store.get("uql_prefer_whites", "1")))
        self.prefer_lineage = QCheckBox("")
        self.prefer_lineage.setChecked(_boolean(context.store.get("uql_lineage_whites", "1")))
        self.surface_cohort = QCheckBox("")
        self.surface_cohort.setChecked(_boolean(context.store.get("uql_surface_cohort", "1")))
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
        self.pink_spin.setValue(_integer(context.store.get("uql_pink_min_stars", "1"), 1))

        self.lineage_hint = muted_label("")
        self.lineage_blue_label = QLabel("")
        self.lineage_blue_combo = ThemedComboBox()
        self.lineage_blue_combo.addItem("—", None)
        for name in BLUE_FACTOR_NAMES:
            self.lineage_blue_combo.addItem(name, name)
        self.lineage_blue_stars = QSpinBox()
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
        for spin in (self.lineage_blue_stars, self.lineage_pink_stars):
            spin.setRange(0, 9)
            spin.setPrefix("≥ ")
            spin.setSuffix("★")
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

        self.costume_label = QLabel("")
        self.allowed_button = QPushButton("")
        self.excluded_button = QPushButton("")

        grid.addWidget(self.hint, 0, 0, 1, 2)
        grid.addWidget(self.prefer_profile, 1, 0, 1, 2)
        grid.addWidget(self.prefer_lineage, 2, 0, 1, 2)
        grid.addWidget(self.surface_cohort, 3, 0, 1, 2)
        grid.addWidget(self.require_surface, 4, 0, 1, 2)
        grid.addWidget(self.require_distance, 5, 0, 1, 2)
        grid.addWidget(self.require_style, 6, 0, 1, 2)
        grid.addWidget(self.pink_label, 7, 0, 1, 2)
        grid.addWidget(self.pink_spin, 7, 1)
        grid.addWidget(self.lineage_hint, 8, 0, 1, 2)
        grid.addWidget(self.lineage_blue_label, 9, 0, 1, 2)
        grid.addWidget(self.lineage_blue_combo, 10, 0, 1, 2)
        grid.addWidget(self.lineage_blue_stars, 10, 1)
        grid.addWidget(self.lineage_pink_label, 11, 0, 1, 2)
        grid.addWidget(self.lineage_pink_combo, 12, 0)
        grid.addWidget(self.lineage_pink_stars, 12, 1)
        grid.addWidget(self.costume_label, 13, 0, 1, 2)
        grid.addWidget(self.allowed_button, 14, 0)
        grid.addWidget(self.excluded_button, 14, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        for label in body.findChildren(QLabel):
            label.setWordWrap(True)
        self.content_layout.addWidget(body)

        for widget in (
            self.prefer_profile,
            self.prefer_lineage,
            self.surface_cohort,
            self.require_surface,
            self.require_distance,
            self.require_style,
        ):
            widget.toggled.connect(self._value_changed)
        for spin in (self.pink_spin, self.lineage_blue_stars, self.lineage_pink_stars):
            spin.valueChanged.connect(self._value_changed)
        for combo in (self.lineage_blue_combo, self.lineage_pink_combo):
            combo.currentIndexChanged.connect(self._value_changed)
        self.allowed_button.clicked.connect(lambda: self._pick_filter("allowed"))
        self.excluded_button.clicked.connect(lambda: self._pick_filter("excluded"))
        self.retranslate()

    def set_ace_options(self, options: Iterable[Any]) -> None:
        self._ace_options = list(options)

    def _pick_filter(self, kind: str) -> None:
        selected = self._allowed_ids if kind == "allowed" else self._excluded_ids
        title = self.context.t(
            "Costumes autorisés" if kind == "allowed" else "Costumes exclus"
        )
        options = [(item.card_id, item.display_name) for item in self._ace_options]
        dialog = CardFilterDialog(self.context, options, set(selected), title, self)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        if accepted:
            if kind == "allowed":
                self._allowed_ids = dialog.selected_ids()
            else:
                self._excluded_ids = dialog.selected_ids()
        dialog.deleteLater()
        if accepted:
            self._value_changed()

    def _value_changed(self, *_args: object) -> None:
        self.context.update_online_options(self.store_values())
        self.refresh_summary()
        self.changed.emit()

    @staticmethod
    def _lineage_filter(combo: ThemedComboBox, spin: QSpinBox):
        name = str(combo.currentData() or "").strip()
        stars = int(spin.value())
        return (name, stars) if name and stars > 0 else None

    def allowed_ids(self) -> tuple[int, ...]:
        return tuple(sorted(self._allowed_ids))

    def excluded_ids(self) -> tuple[int, ...]:
        return tuple(sorted(self._excluded_ids))

    def values(self) -> dict[str, Any]:
        return {
            "uql_options": {
                "prefer_profile_whites": self.prefer_profile.isChecked(),
                "prefer_lineage_whites": self.prefer_lineage.isChecked(),
                "require_main_surface": self.require_surface.isChecked(),
                "require_main_distance": self.require_distance.isChecked(),
                "require_main_style": self.require_style.isChecked(),
                "pink_min_stars": self.pink_spin.value(),
                "enable_surface_retrieval": self.surface_cohort.isChecked(),
            },
            "allowed_parent_card_ids": self.allowed_ids(),
            "excluded_parent_card_ids": self.excluded_ids(),
            "lineage_blue_filter": self._lineage_filter(
                self.lineage_blue_combo, self.lineage_blue_stars
            ),
            "lineage_pink_filter": self._lineage_filter(
                self.lineage_pink_combo, self.lineage_pink_stars
            ),
        }

    def store_values(self) -> dict[str, object]:
        values = self.values()
        options = values["uql_options"]
        blue = values["lineage_blue_filter"]
        pink = values["lineage_pink_filter"]
        return {
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
            "uma_moe_parent_allowed_card_ids": ",".join(map(str, self.allowed_ids())),
            "uma_moe_parent_excluded_card_ids": ",".join(map(str, self.excluded_ids())),
        }

    def refresh_summary(self) -> None:
        t = self.context.t
        parts: list[str] = []
        if self.surface_cohort.isChecked():
            parts.append(t("cohorte Surface"))
        required = [
            t(label)
            for widget, label in (
                (self.require_surface, "surface"),
                (self.require_distance, "distance"),
                (self.require_style, "style"),
            )
            if widget.isChecked()
        ]
        if required:
            parts.append(t("exigé : {list}").replace("{list}", ", ".join(required)))
        if self.pink_spin.value() > 1:
            parts.append(f"pink ≥ {self.pink_spin.value()}★")
        for combo, spin in (
            (self.lineage_blue_combo, self.lineage_blue_stars),
            (self.lineage_pink_combo, self.lineage_pink_stars),
        ):
            selected = self._lineage_filter(combo, spin)
            if selected:
                parts.append(f"{selected[0]} ≥ {selected[1]}★")
        if self._allowed_ids:
            parts.append(
                t("{count} autorisés").replace("{count}", str(len(self._allowed_ids)))
            )
        if self._excluded_ids:
            parts.append(
                t("{count} exclus").replace("{count}", str(len(self._excluded_ids)))
            )
        self.set_summary(" · ".join(parts) if parts else t("Récupération par défaut"))
        self.set_modified(bool(parts), t("Modifié"))
        self.allowed_button.setText(
            f"{t('Autorisés')} ({len(self._allowed_ids)})"
        )
        self.excluded_button.setText(
            f"{t('Exclus')} ({len(self._excluded_ids)})"
        )

    def retranslate(self) -> None:
        t = self.context.t
        self.set_title(t("uma.moe · Récupération"))
        self.hint.setText(
            t(
                "Ces contraintes s’appliquent aux deux recherches distantes. La clé et l’URL se règlent dans Paramètres."
            )
        )
        self.prefer_profile.setText(t("Favoriser les whites du profil"))
        self.prefer_lineage.setText(t("Favoriser leur répétition dans la lignée"))
        self.surface_cohort.setText(t("Cohorte Surface dédiée"))
        self.require_surface.setText(t("Exiger la surface cible"))
        self.require_distance.setText(t("Exiger la distance cible"))
        self.require_style.setText(t("Exiger le style cible"))
        self.pink_label.setText(t("Étoiles pink minimum"))
        self.lineage_hint.setText(
            t("Somme sur le Main distant et ses deux parents, appliquée avant pagination.")
        )
        self.lineage_blue_label.setText(t("Stat Blue"))
        self.lineage_pink_label.setText(t("Aptitude Pink"))
        for spin in (self.lineage_blue_stars, self.lineage_pink_stars):
            spin.setSpecialValueText(t("désactivé"))
        self.costume_label.setText(t("Filtres de costumes"))
        self.refresh_summary()


class OnlineModeSection(SummarySection):
    """One remote search's own strategy.

    Parent and grandparent searches get their own instance and their own
    stored values, because the same control means a different thing in each:
    the fixed local veteran is the final parent in one and GP1 in the other.
    """

    changed = Signal()

    def __init__(self, context: AppContext, mode: str, parent=None) -> None:
        super().__init__("", parent)
        self.context = context
        self.mode = PARENT_MODE if mode == PARENT_MODE else GRANDPARENT_MODE
        self._ace_options: list[Any] = []
        self._local_options: list[VeteranOption] = []
        self._external_opposing: list[dict[str, Any]] = []
        self._validation_message = ""

        body = QWidget()
        grid = QGridLayout(body)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(7)

        self.auto_pairs = QCheckBox("")
        self.auto_pairs.setChecked(
            _boolean(strategy_value(context, self.mode, "auto_pairs"))
        )
        self.fixed_label = QLabel("")
        self.fixed_combo = SearchableComboBox()
        self.fixed_combo.setDisabled(self.auto_pairs.isChecked())
        self.local_pool_label = QLabel("")
        self.local_pool = QSpinBox()
        self.local_pool.setRange(1, 250)
        self.local_pool.setValue(
            _integer(strategy_value(context, self.mode, "local_pool"), 100)
        )
        self.remote_pool_label = QLabel("")
        self.remote_pool = QSpinBox()
        self.remote_pool.setRange(1, 500)
        self.remote_pool.setValue(
            _integer(strategy_value(context, self.mode, "remote_pool"), 100)
        )
        self.fetch_label = QLabel("")
        self.fetch_spin = QSpinBox()
        self.fetch_spin.setRange(100, 2000)
        self.fetch_spin.setSingleStep(100)
        self.fetch_spin.setValue(
            _integer(strategy_value(context, self.mode, "limit"), 500)
        )

        row = 0
        grid.addWidget(self.auto_pairs, row, 0, 1, 2)
        row += 1
        grid.addWidget(self.fixed_label, row, 0, 1, 2)
        row += 1
        grid.addWidget(self.fixed_combo, row, 0, 1, 2)
        row += 1
        for label, widget in (
            (self.local_pool_label, self.local_pool),
            (self.remote_pool_label, self.remote_pool),
        ):
            grid.addWidget(label, row, 0, 1, 2)
            grid.addWidget(widget, row + 1, 0, 1, 2)
            row += 2
        grid.addWidget(self.fetch_label, row, 0, 1, 2)
        row += 1
        grid.addWidget(self.fetch_spin, row, 0, 1, 2)
        row += 1

        if self.mode == PARENT_MODE:
            self.required_label = QLabel("")
            self.required_combo = SearchableComboBox()
            self.required_combo.addItem("", None)
            grid.addWidget(self.required_label, row, 0, 1, 2)
            row += 1
            grid.addWidget(self.required_combo, row, 0, 1, 2)
            row += 1
            self.required_combo.currentIndexChanged.connect(self._value_changed)
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
            grid.addWidget(self.opposing_label, row, 0, 1, 2)
            row += 1
            grid.addWidget(self.opposing_combo, row, 0, 1, 2)
            row += 1
            grid.addWidget(self.opposing_json_label, row, 0, 1, 2)
            row += 1
            grid.addWidget(self.opposing_picker, row, 0, 1, 2)
            row += 1
            grid.addWidget(self.opposing_extract_button, row, 0, 1, 2)
            row += 1
            for label, widget in (
                (self.g1_budget_label, self.g1_budget),
                (self.g1_weight_label, self.g1_weight),
            ):
                label.setWordWrap(True)
                grid.addWidget(label, row, 0, 1, 2)
                grid.addWidget(widget, row + 1, 0, 1, 2)
                row += 2
            self.opposing_extract_button.clicked.connect(
                lambda: self.load_external_opposing(show_errors=True)
            )
            self.opposing_combo.currentIndexChanged.connect(self._value_changed)
            self.opposing_picker.path_changed.connect(self._opposing_path_changed)
            for spin in (self.g1_budget, self.g1_weight):
                spin.valueChanged.connect(self._value_changed)

        self.import_label = QLabel("")
        self.import_picker = PathPicker(
            strategy_value(context, self.mode, "response_path"),
            title="Sélectionner une réponse JSON de l’API uma.moe",
            file_filter="JSON (*.json);;Tous les fichiers (*)",
        )
        grid.addWidget(self.import_label, row, 0, 1, 2)
        row += 1
        grid.addWidget(self.import_picker, row, 0, 1, 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        # Inline instead of a modal on save: with live persistence there is no
        # save step left to interrupt, and the conflict has to stay visible
        # while the user fixes it.
        self.warning = QLabel("")
        self.warning.setObjectName("pillWarning")
        self.warning.setWordWrap(True)
        self.warning.setVisible(False)
        for label in body.findChildren(QLabel):
            label.setWordWrap(True)
        self.content_layout.addWidget(body)
        self.content_layout.addWidget(self.warning)

        self.auto_pairs.toggled.connect(self._auto_pairs_toggled)
        self.fixed_combo.currentIndexChanged.connect(self._value_changed)
        for spin in (self.local_pool, self.remote_pool, self.fetch_spin):
            spin.valueChanged.connect(self._value_changed)
        self.import_picker.path_changed.connect(self._value_changed)
        self.retranslate()

    def set_options(
        self,
        ace_options: Iterable[Any],
        local_options: Iterable[VeteranOption],
    ) -> None:
        self._ace_options = list(ace_options)
        self._local_options = list(local_options)
        self._repopulate_fixed_combo()
        if self.mode == PARENT_MODE:
            self._repopulate_required_combo()
        else:
            self.load_external_opposing(show_errors=False)
        self.refresh_summary()

    def _repopulate_fixed_combo(self) -> None:
        selected = _integer(strategy_value(self.context, self.mode, "fixed_local_id"))
        self.fixed_combo.blockSignals(True)
        self.fixed_combo.clear()
        for option in self._local_options:
            self.fixed_combo.addItem(option.display_name, option.trained_chara_id)
        index = self.fixed_combo.findData(selected)
        self.fixed_combo.setCurrentIndex(
            index if index >= 0 else (0 if self.fixed_combo.count() else -1)
        )
        self.fixed_combo.blockSignals(False)

    def _repopulate_required_combo(self) -> None:
        selected = _integer(
            self.context.store.get("uma_moe_required_parent_card_id")
        )
        self.required_combo.blockSignals(True)
        self.required_combo.clear()
        self.required_combo.addItem(self.context.t("Aucun costume requis"), None)
        for option in self._ace_options:
            self.required_combo.addItem(option.display_name, option.card_id)
        index = self.required_combo.findData(selected)
        self.required_combo.setCurrentIndex(index if index >= 0 else 0)
        self.required_combo.blockSignals(False)

    def _opposing_path_changed(self, _value: str) -> None:
        self.load_external_opposing(show_errors=True)
        self._value_changed()

    def load_external_opposing(self, *, show_errors: bool) -> None:
        if self.mode != GRANDPARENT_MODE:
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
        except Exception as exc:  # noqa: BLE001 - surfaced to the user as-is
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
        if self.mode != GRANDPARENT_MODE:
            return
        saved = self.context.store.get("uma_moe_opposing_selection", "none")
        self.opposing_combo.blockSignals(True)
        self.opposing_combo.clear()
        self.opposing_combo.addItem(
            self.context.t("(aucun — recherche GP polyvalente)"), "none"
        )
        for option in self._local_options:
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

    def _auto_pairs_toggled(self, checked: bool) -> None:
        self.fixed_combo.setDisabled(checked)
        self._value_changed()

    def _value_changed(self, *_args: object) -> None:
        self.context.update_online_options(self.store_values())
        self.refresh_summary()
        self.changed.emit()

    def values(self) -> dict[str, Any]:
        self.fixed_combo.resolve_current_text()
        fixed = _integer(self.fixed_combo.currentData())
        opposing_id: int | None = None
        opposing_payload: dict[str, Any] | None = None
        opposing_selection = "none"
        required: int | None = None
        if self.mode == GRANDPARENT_MODE:
            self.opposing_combo.resolve_current_text()
            opposing_selection = str(self.opposing_combo.currentData() or "none")
            if opposing_selection.startswith("local:"):
                opposing_id = _integer(opposing_selection.split(":", 1)[1]) or None
            elif opposing_selection.startswith("external:"):
                index = _integer(opposing_selection.split(":", 1)[1], -1)
                if 0 <= index < len(self._external_opposing):
                    opposing_payload = copy.deepcopy(self._external_opposing[index])
        else:
            self.required_combo.resolve_current_text()
            required_raw = self.required_combo.currentData()
            required = int(required_raw) if required_raw is not None else None
        return {
            "automatic_pairs": self.auto_pairs.isChecked(),
            "fixed_local_id": None if self.auto_pairs.isChecked() else (fixed or None),
            "local_pool_size": self.local_pool.value(),
            "remote_pool_size": self.remote_pool.value(),
            "limit": self.fetch_spin.value(),
            "planned_g1_budget": (
                self.g1_budget.value() if self.mode == GRANDPARENT_MODE else 20
            ),
            "g1_win_probability_cutoff": (
                self.g1_weight.value() if self.mode == GRANDPARENT_MODE else 0.6
            ),
            "required_parent_card_id": required,
            "opposing_parent_trained_id": opposing_id,
            "opposing_parent_payload": opposing_payload,
            "opposing_selection": opposing_selection,
            "response_path": self.import_picker.text().strip(),
        }

    def store_values(self) -> dict[str, object]:
        values = self.values()
        stored: dict[str, object] = {
            mode_key(self.mode, "auto_pairs"): int(values["automatic_pairs"]),
            mode_key(self.mode, "fixed_local_id"): values["fixed_local_id"] or 0,
            mode_key(self.mode, "local_pool"): values["local_pool_size"],
            mode_key(self.mode, "remote_pool"): values["remote_pool_size"],
            mode_key(self.mode, "limit"): values["limit"],
            mode_key(self.mode, "response_path"): values["response_path"],
        }
        if self.mode == PARENT_MODE:
            stored["uma_moe_required_parent_card_id"] = (
                values["required_parent_card_id"] or 0
            )
        else:
            stored.update(
                {
                    "uma_moe_parent_g1_budget": values["planned_g1_budget"],
                    "uma_moe_g1_win_probability_cutoff": values[
                        "g1_win_probability_cutoff"
                    ],
                    "uma_moe_opposing_id": values["opposing_parent_trained_id"] or 0,
                    "uma_moe_opposing_selection": values["opposing_selection"],
                    "uma_moe_opposing_path": self.opposing_picker.text().strip(),
                }
            )
        return stored

    def validation_error(
        self, allowed_ids: Iterable[int], excluded_ids: Iterable[int]
    ) -> str:
        if self.mode != PARENT_MODE:
            return ""
        required = self.values()["required_parent_card_id"]
        if required is None:
            return ""
        allowed = set(allowed_ids)
        if required in set(excluded_ids):
            return self.context.t("Le costume requis est également exclu.")
        if allowed and required not in allowed:
            return self.context.t(
                "Le costume requis doit être présent dans les costumes autorisés."
            )
        return ""

    def show_validation(self, message: str) -> None:
        self.warning.setText(message)
        self.warning.setVisible(bool(message))
        self._validation_message = message
        self.refresh_summary()

    def refresh_summary(self) -> None:
        t = self.context.t
        parts: list[str] = []
        if self.auto_pairs.isChecked():
            parts.append(t("appariement auto"))
        else:
            fixed = self.fixed_combo.currentText().strip()
            parts.append(fixed or t("aucun vétéran fixé"))
        parts.append(
            t("{count} candidats API").replace(
                "{count}", str(self.fetch_spin.value())
            )
        )
        parts.append(f"{self.local_pool.value()}×{self.remote_pool.value()}")
        if self.mode == PARENT_MODE:
            if self.values()["required_parent_card_id"] is not None:
                parts.append(
                    t("requis : {name}").replace(
                        "{name}", self.required_combo.currentText().strip()
                    )
                )
        else:
            selection = str(self.opposing_combo.currentData() or "none")
            if selection != "none":
                parts.append(
                    t("opposé : {name}").replace(
                        "{name}", self.opposing_combo.currentText().strip()
                    )
                )
            parts.append(f"G1 {self.g1_budget.value()}")
        self.set_summary(" · ".join(parts))
        # A conflict has to stay visible once the section is closed, so it takes
        # the header badge over the ordinary modified marker.
        self.set_modified(
            bool(self._validation_message),
            t("Conflit") if self._validation_message else "",
            warning=True,
        )

    def retranslate(self) -> None:
        t = self.context.t
        self.set_title(
            t("moe · Parents distants")
            if self.mode == PARENT_MODE
            else t("moe · Grands-parents distants")
        )
        self.auto_pairs.setText(t("Tester toutes les paires local × distant"))
        self.fixed_label.setText(
            t("Parent local fixé (manuel)")
            if self.mode == PARENT_MODE
            else t("GP local fixé (manuel)")
        )
        self.local_pool_label.setText(t("Pool local"))
        self.remote_pool_label.setText(t("Pool distant"))
        self.fetch_label.setText(t("Fetch API"))
        if self.mode == PARENT_MODE:
            self.required_label.setText(t("Costume requis dans la paire"))
            if self.required_combo.count():
                self.required_combo.setItemText(0, t("Aucun costume requis"))
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
        self.refresh_summary()
