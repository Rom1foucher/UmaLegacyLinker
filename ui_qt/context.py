from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from i18n import normalise_language, translate_text
from ui_qt.core import (
    SettingsStore,
    active_course_overrides_path,
    auto_detect_extractor,
    auto_detect_master,
    default_output_dir,
)


class AppContext(QObject):
    configuration_changed = Signal()
    language_changed = Signal(str)

    def __init__(self, store: SettingsStore | None = None, parent=None):
        super().__init__(parent)
        self.store = store or SettingsStore()
        detected_master = auto_detect_master()
        self.master_path = self.store.get("master_path") or (
            str(detected_master) if detected_master else ""
        )
        self.veterans_json_path = self.store.get("json_path")
        self.output_dir = self.store.get("output_dir", str(default_output_dir()))
        detected_extractor = auto_detect_extractor()
        self.extractor_path = self.store.get("extractor_path") or (
            str(detected_extractor) if detected_extractor else ""
        )
        configured_course = self.store.get("course_overrides_path")
        resolved_course = active_course_overrides_path(configured_course)
        self.course_overrides_path = str(resolved_course) if resolved_course else ""
        self.language = normalise_language(self.store.get("ui_language"))

    def t(self, text: object) -> str:
        return str(translate_text(str(text), self.language))

    def update_paths(
        self,
        *,
        master_path: str | None = None,
        veterans_json_path: str | None = None,
        output_dir: str | None = None,
        course_overrides_path: str | None = None,
        extractor_path: str | None = None,
    ) -> None:
        updates: dict[str, object] = {}
        if master_path is not None:
            self.master_path = master_path.strip()
            updates["master_path"] = self.master_path
        if veterans_json_path is not None:
            self.veterans_json_path = veterans_json_path.strip()
            updates["json_path"] = self.veterans_json_path
        if output_dir is not None:
            self.output_dir = output_dir.strip()
            updates["output_dir"] = self.output_dir
        if course_overrides_path is not None:
            self.course_overrides_path = course_overrides_path.strip()
            updates["course_overrides_path"] = self.course_overrides_path
        if extractor_path is not None:
            self.extractor_path = extractor_path.strip()
            updates["extractor_path"] = self.extractor_path
        if updates:
            self.store.update(updates)
            self.configuration_changed.emit()

    def set_language(self, language: str) -> None:
        normalized = normalise_language(language)
        if normalized == self.language:
            return
        self.language = normalized
        self.store.update({"ui_language": normalized})
        self.language_changed.emit(normalized)
        self.configuration_changed.emit()

    def path(self, value: str) -> Path:
        return Path(value).expanduser()
