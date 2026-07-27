from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QLabel,
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
from ui_qt.components import (
    CollapsibleSection,
    PathPicker,
    SearchableComboBox,
    ThemedComboBox,
    muted_label,
)
from ui_qt.context import AppContext, LineageContextState
from ui_qt.core import active_course_overrides_path


PROFILE_CODES = {
    "surface": ("turf", "dirt"),
    "distance": ("sprint", "mile", "medium", "long"),
    "style": (
        "front_runner",
        "pace_chaser",
        "late_surger",
        "end_closer",
    ),
}

CONDITION_ITEMS: dict[str, list[tuple[str, object]]] = {
    "rotation": [("Non précisé", None), ("Droite", 1), ("Gauche", 2)],
    "season": [
        ("Non précisé", None),
        ("Printemps", [1, 5]),
        ("Été", 2),
        ("Automne", 3),
        ("Hiver", 4),
    ],
    "weather": [
        ("Non précisé", None),
        ("Ensoleillé", 1),
        ("Nuageux", 2),
        ("Pluie", 3),
        ("Neige", 4),
    ],
    "ground_condition": [
        ("Non précisé", None),
        ("Firm", 1),
        ("Good", 2),
        ("Soft", 3),
        ("Heavy", 4),
    ],
}


class LineageRaceEditor(QWidget):
    """Live shared race/scoring controls used by both analysis pages."""

    changed = Signal()
    layout_changed = Signal()

    def __init__(self, context: AppContext, parent=None):
        super().__init__(parent)
        self.context = context
        self._syncing = False
        self._course_definitions: dict[str, dict[str, Any]] = {}
        self._track_options: list[tuple[int, str]] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        self.panel = QFrame()
        self.panel.setObjectName("panel")
        form = QGridLayout(self.panel)
        form.setContentsMargins(17, 14, 17, 15)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)

        self.shared_hint = muted_label("")
        self.shared_hint.setWordWrap(True)
        self.surface_label = QLabel("")
        self.surface_combo = ThemedComboBox()
        self.distance_label = QLabel("")
        self.distance_combo = ThemedComboBox()
        self.style_label = QLabel("")
        self.style_combo = ThemedComboBox()
        self.course_label = QLabel("")
        self.course_combo = SearchableComboBox()

        form.addWidget(self.shared_hint, 0, 0, 1, 2)
        for row, controls in enumerate(
            (
                (
                    (self.surface_label, self.surface_combo),
                    (self.distance_label, self.distance_combo),
                ),
                (
                    (self.style_label, self.style_combo),
                    (self.course_label, self.course_combo),
                ),
            )
        ):
            label_row = 1 + row * 2
            for column, (label, combo) in enumerate(controls):
                form.addWidget(label, label_row, column)
                form.addWidget(combo, label_row + 1, column)
                form.setColumnStretch(column, 1)
        root.addWidget(self.panel)

        self.advanced = CollapsibleSection("")
        advanced = QGridLayout()
        advanced.setHorizontalSpacing(10)
        advanced.setVerticalSpacing(8)
        self.course_file_label = QLabel("")
        self.course_picker = PathPicker(
            self.context.course_overrides_path,
            title="Sélectionner les overrides de course",
            file_filter="JSON (*.json);;Tous les fichiers (*)",
        )
        self.track_label = QLabel("")
        self.track_combo = SearchableComboBox()
        self.rotation_label = QLabel("")
        self.rotation_combo = ThemedComboBox()
        self.season_label = QLabel("")
        self.season_combo = ThemedComboBox()
        self.weather_label = QLabel("")
        self.weather_combo = ThemedComboBox()
        self.ground_label = QLabel("")
        self.ground_combo = ThemedComboBox()
        self.custom_scoring = QCheckBox("")
        self.priority_label = QLabel("")
        self.priority_picker = PathPicker(
            self.context.lineage_state().skill_priorities_path,
            title="Choisir un profil de priorités white",
            file_filter="JSON (*.json);;Tous les fichiers (*)",
        )

        advanced.addWidget(self.course_file_label, 0, 0)
        advanced.addWidget(self.course_picker, 1, 0, 1, 2)
        for row, controls in enumerate(
            (
                (
                    (self.track_label, self.track_combo),
                    (self.rotation_label, self.rotation_combo),
                ),
                (
                    (self.season_label, self.season_combo),
                    (self.weather_label, self.weather_combo),
                ),
            )
        ):
            label_row = 2 + row * 2
            for column, (label, combo) in enumerate(controls):
                advanced.addWidget(label, label_row, column)
                advanced.addWidget(combo, label_row + 1, column)
        advanced.addWidget(self.ground_label, 6, 0)
        advanced.addWidget(self.ground_combo, 7, 0)
        advanced.addWidget(self.custom_scoring, 7, 1)
        advanced.addWidget(self.priority_label, 8, 0)
        advanced.addWidget(self.priority_picker, 9, 0, 1, 2)
        for column in range(2):
            advanced.setColumnStretch(column, 1)
        self.advanced.content_layout.addLayout(advanced)
        root.addWidget(self.advanced)

        self.course_combo.currentIndexChanged.connect(self._course_changed)
        for kind, combo in (
            ("surface", self.surface_combo),
            ("distance", self.distance_combo),
            ("style", self.style_combo),
        ):
            combo.activated.connect(
                lambda _index, selected_kind=kind: self._profile_changed(
                    selected_kind
                )
            )
        self.track_combo.currentIndexChanged.connect(self._track_changed)
        for combo in (
            self.rotation_combo,
            self.season_combo,
            self.weather_combo,
            self.ground_combo,
        ):
            combo.currentIndexChanged.connect(self._advanced_value_changed)
        self.custom_scoring.toggled.connect(self._advanced_value_changed)
        self.priority_picker.path_changed.connect(self._priority_path_changed)
        self.course_picker.path_changed.connect(self._course_path_changed)
        self.advanced.toggle.toggled.connect(
            lambda _checked: self.layout_changed.emit()
        )
        self.context.lineage_changed.connect(self.sync_from_context)
        self.context.configuration_changed.connect(self._configuration_changed)
        self.context.language_changed.connect(lambda _language: self.retranslate())

        self.retranslate()

    @staticmethod
    def _find_data(combo: QComboBox, value: object) -> int:
        for index in range(combo.count()):
            if combo.itemData(index) == value:
                return index
        return -1

    @classmethod
    def _set_combo_data(cls, combo: QComboBox, value: object) -> None:
        index = cls._find_data(combo, value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    @staticmethod
    def _condition_source(combo: QComboBox) -> str:
        return str(
            combo.currentData(Qt.ItemDataRole.UserRole + 1) or "Non précisé"
        )

    def _populate_profile_combo(
        self, combo: QComboBox, kind: str, selected: str
    ) -> None:
        combo.blockSignals(True)
        combo.clear()
        for code, label in zip(
            PROFILE_CODES[kind], profile_values(kind, self.context.language)
        ):
            combo.addItem(label, code)
        index = combo.findData(selected)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.blockSignals(False)

    def _populate_condition_combo(
        self, combo: QComboBox, kind: str, selected_source: str
    ) -> None:
        combo.blockSignals(True)
        combo.clear()
        restore_index = 0
        for source, canonical in CONDITION_ITEMS[kind]:
            combo.addItem(self.context.t(source), canonical)
            index = combo.count() - 1
            combo.setItemData(
                index, source, Qt.ItemDataRole.UserRole + 1
            )
            if source == selected_source:
                restore_index = index
        combo.setCurrentIndex(restore_index)
        combo.blockSignals(False)

    def _populate_track_combo(self, selected: int) -> None:
        self.track_combo.blockSignals(True)
        self.track_combo.clear()
        self.track_combo.addItem(self.context.t("Non précisé"), None)
        for track_id, display_name in self._track_options:
            self.track_combo.addItem(display_name, track_id)
        index = self.track_combo.findData(selected)
        self.track_combo.setCurrentIndex(index if index >= 0 else 0)
        self.track_combo.blockSignals(False)

    def _refresh_course_options(self, selected_key: str) -> bool:
        path = active_course_overrides_path(self.course_picker.text())
        payload = load_course_preset_payload(path)
        self._course_definitions = {
            key: course for key, course in ordered_course_presets(payload)
        }
        self.course_combo.blockSignals(True)
        self.course_combo.clear()
        self.course_combo.addItem(
            self.context.t("Aucun preset — profil manuel"), None
        )
        for key, course in self._course_definitions.items():
            self.course_combo.addItem(
                course_preset_label(key, course, self.context.language), key
            )
        index = self.course_combo.findData(selected_key) if selected_key else 0
        found = index >= 0
        self.course_combo.setCurrentIndex(index if found else 0)
        self.course_combo.blockSignals(False)
        return found

    def retranslate(self) -> None:
        t = self.context.t
        self.shared_hint.setText(
            t(
                "Ces réglages sont partagés en temps réel entre Optimisation de lignée et uma.moe. Les options de scoring sont aussi synchronisées avec Pondérations."
            )
        )
        self.surface_label.setText(t("Surface"))
        self.distance_label.setText(t("Distance"))
        self.style_label.setText(t("Style"))
        self.course_label.setText(t("Preset de course"))
        self.advanced.set_title(t("Options avancées et conditions de course"))
        self.course_file_label.setText(t("Fichier de presets / overrides"))
        self.track_label.setText(t("Hippodrome"))
        self.rotation_label.setText(t("Rotation"))
        self.season_label.setText(t("Saison"))
        self.weather_label.setText(t("Météo"))
        self.ground_label.setText(t("État du terrain"))
        self.custom_scoring.setText(t("Utiliser mes pondérations personnalisées"))
        self.priority_label.setText(t("Priorités individuelles des white skills"))
        self.course_picker.dialog_title = t(
            "Sélectionner les overrides de course"
        )
        self.course_picker.file_filter = (
            f"JSON (*.json);;{t('Tous les fichiers')} (*)"
        )
        self.priority_picker.dialog_title = t(
            "Choisir un profil de priorités white"
        )
        self.priority_picker.file_filter = (
            f"JSON (*.json);;{t('Tous les fichiers')} (*)"
        )
        self.course_picker.set_button_text(t("Parcourir…"))
        self.priority_picker.set_button_text(t("Parcourir…"))
        self.priority_picker.setToolTip(
            t(
                "Ce fichier règle la valeur de chaque white skill par surface, distance et style. Un profil partiel est accepté : il est fusionné avec default_skill_priorities.json avant chaque calcul."
            )
        )
        self.sync_from_context()

    def sync_from_context(
        self, _state: LineageContextState | None = None
    ) -> None:
        # Re-read the store instead of trusting the signal payload: a page can
        # enforce a dependent constraint (for example, distinct Ace/parent)
        # through a nested lineage_changed emission while an older emission is
        # still visiting its remaining slots.
        state = self.context.lineage_state()
        self._syncing = True
        try:
            self.course_picker.set_text(self.context.course_overrides_path)
            self._populate_profile_combo(
                self.surface_combo, "surface", state.surface
            )
            self._populate_profile_combo(
                self.distance_combo, "distance", state.distance
            )
            self._populate_profile_combo(self.style_combo, "style", state.style)
            self._populate_condition_combo(
                self.rotation_combo, "rotation", state.rotation
            )
            self._populate_condition_combo(
                self.season_combo, "season", state.season
            )
            self._populate_condition_combo(
                self.weather_combo, "weather", state.weather
            )
            self._populate_condition_combo(
                self.ground_combo,
                "ground_condition",
                state.ground_condition,
            )
            self._populate_track_combo(state.track_id)
            self._refresh_course_options(state.course_key)
            self.custom_scoring.setChecked(state.use_custom_scoring)
            self.priority_picker.set_text(state.skill_priorities_path)
        finally:
            self._syncing = False
        self.changed.emit()

    def _configuration_changed(self) -> None:
        state = self.context.lineage_state()
        found = self._refresh_course_options(state.course_key)
        if state.course_key and not found:
            self.context.update_lineage(course_key="")
        else:
            self.sync_from_context(state)

    def set_track_options(self, tracks: Iterable[object]) -> None:
        self._track_options = [
            (int(getattr(track, "track_id")), str(getattr(track, "display_name")))
            for track in tracks
        ]
        state = self.context.lineage_state()
        self._populate_track_combo(state.track_id)
        if state.track_id or not state.course_key:
            return
        course = self._course_definitions.get(state.course_key) or {}
        racecourse = str(((course.get("race") or {}).get("racecourse")) or "")
        track_id = self._track_id_for_racecourse(racecourse)
        if track_id:
            self.context.update_lineage(track_id=track_id)

    def _track_id_for_racecourse(self, racecourse: str) -> int:
        if not racecourse:
            return 0
        for track_id, display_name in self._track_options:
            if racecourse_names_match(display_name, racecourse):
                return track_id
        return 0

    def _course_path_changed(self, value: str) -> None:
        if self._syncing:
            return
        self.context.update_paths(course_overrides_path=value)

    def _priority_path_changed(self, value: str) -> None:
        if self._syncing:
            return
        self.context.update_lineage(skill_priorities_path=value)

    def _course_changed(self, index: int) -> None:
        if self._syncing or index < 0:
            return
        key = self.course_combo.currentData()
        course = self._course_definitions.get(str(key)) if key else None
        if not course:
            self.context.update_lineage(course_key="")
            return

        self._syncing = True
        try:
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
            for name, combo in (
                ("rotation", self.rotation_combo),
                ("season", self.season_combo),
                ("weather", self.weather_combo),
                ("ground_condition", self.ground_combo),
            ):
                self._set_combo_data(combo, conditions.get(name))

            selected_track_id = int(conditions.get("track_id") or 0)
            if not selected_track_id:
                racecourse = str(
                    ((course.get("race") or {}).get("racecourse")) or ""
                )
                selected_track_id = self._track_id_for_racecourse(racecourse)
            self._set_combo_data(
                self.track_combo, selected_track_id or None
            )
        finally:
            self._syncing = False

        self.context.update_lineage(
            course_key=str(key),
            surface=str(self.surface_combo.currentData() or "turf"),
            distance=str(self.distance_combo.currentData() or "medium"),
            style=str(self.style_combo.currentData() or "pace_chaser"),
            # Keep an explicit preset track even if the MDB-backed track list
            # has not loaded yet. set_track_options() will display it later.
            track_id=selected_track_id,
            rotation=self._condition_source(self.rotation_combo),
            season=self._condition_source(self.season_combo),
            weather=self._condition_source(self.weather_combo),
            ground_condition=self._condition_source(self.ground_combo),
        )

    def _profile_changed(self, kind: str) -> None:
        if self._syncing:
            return
        value = str(getattr(self, f"{kind}_combo").currentData() or "")
        if not value:
            return
        course_key = str(self.course_combo.currentData() or "")
        course = self._course_definitions.get(course_key) or {}
        preset_value = (course.get("profile") or {}).get(kind)
        if preset_value is not None and value != str(preset_value):
            course_key = ""
            self.course_combo.blockSignals(True)
            self.course_combo.setCurrentIndex(0)
            self.course_combo.blockSignals(False)
        self.context.update_lineage(
            course_key=course_key,
            surface=str(self.surface_combo.currentData() or "turf"),
            distance=str(self.distance_combo.currentData() or "medium"),
            style=str(self.style_combo.currentData() or "pace_chaser"),
        )

    def _advanced_value_changed(self, *_args: object) -> None:
        if self._syncing:
            return
        self.context.update_lineage(
            track_id=int(self.track_combo.currentData() or 0),
            rotation=self._condition_source(self.rotation_combo),
            season=self._condition_source(self.season_combo),
            weather=self._condition_source(self.weather_combo),
            ground_condition=self._condition_source(self.ground_combo),
            use_custom_scoring=self.custom_scoring.isChecked(),
            skill_priorities_path=self.priority_picker.text(),
        )

    def _track_changed(self, index: int) -> None:
        # A searchable combo temporarily uses -1 while the user is typing.
        # Do not publish that transient state and erase the search text.
        if index >= 0:
            self._advanced_value_changed()

    def current_profile(self) -> dict[str, str]:
        return {
            "surface": str(self.surface_combo.currentData() or "turf"),
            "distance": str(self.distance_combo.currentData() or "medium"),
            "style": str(self.style_combo.currentData() or "pace_chaser"),
        }

    def current_course_key(self) -> str | None:
        if not self.course_combo.resolve_current_text():
            self.course_combo.blockSignals(True)
            self.course_combo.setCurrentIndex(0)
            self.course_combo.blockSignals(False)
            self.context.update_lineage(course_key="")
        value = str(self.course_combo.currentData() or "").strip()
        return value or None

    def current_course_label(self) -> str:
        if self.course_combo.currentIndex() < 0:
            return self.context.t("Aucun preset — profil manuel")
        return self.course_combo.currentText()

    def selected_conditions(self) -> dict[str, object]:
        if not self.track_combo.resolve_current_text():
            self.track_combo.blockSignals(True)
            self.track_combo.setCurrentIndex(0)
            self.track_combo.blockSignals(False)
            self.context.update_lineage(track_id=0)
        result: dict[str, object] = {}
        for name, combo in (
            ("track_id", self.track_combo),
            ("rotation", self.rotation_combo),
            ("season", self.season_combo),
            ("weather", self.weather_combo),
            ("ground_condition", self.ground_combo),
        ):
            value = combo.currentData()
            if value is not None:
                result[name] = value
        return result

    def course_overrides_path(self) -> Path | None:
        return active_course_overrides_path(self.course_picker.text())

    def skill_priorities_path(self) -> Path | None:
        value = self.priority_picker.text()
        return Path(value).expanduser() if value else None
