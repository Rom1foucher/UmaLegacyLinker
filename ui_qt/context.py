from __future__ import annotations

import hashlib
import json

from dataclasses import dataclass, replace
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from i18n import normalise_language, translate_text
from secret_store import resolve_api_key, save_api_key
from uma_moe import DEFAULT_API_BASE
from ui_qt.core import (
    SettingsStore,
    active_course_overrides_path,
    api_key_path,
    auto_detect_extractor,
    auto_detect_master,
    default_output_dir,
    user_scoring_overrides_path,
)

# Search options every remote family reads, versus the ones that belong to a
# single family. The split mirrors ui_qt/online_options.py: a fingerprint that
# folded them together would report a parent search as stale because a
# grandparent setting moved.
SHARED_ONLINE_KEYS = (
    "uql_prefer_whites",
    "uql_lineage_whites",
    "uql_surface_cohort",
    "uql_require_surface",
    "uql_require_distance",
    "uql_require_style",
    "uql_pink_min_stars",
    "uql_lineage_blue_name",
    "uql_lineage_blue_stars",
    "uql_lineage_pink_name",
    "uql_lineage_pink_stars",
    "uma_moe_parent_allowed_card_ids",
    "uma_moe_parent_excluded_card_ids",
)

FAMILY_ONLINE_KEYS = {
    "online_parent": (
        "uma_moe_parent_auto_pairs",
        "uma_moe_parent_fixed_local_id",
        "uma_moe_parent_local_pool",
        "uma_moe_parent_remote_pool",
        "uma_moe_parent_limit",
        "uma_moe_required_parent_card_id",
    ),
    "online_gp": (
        "uma_moe_gp_auto_pairs",
        "uma_moe_gp_fixed_local_id",
        "uma_moe_gp_local_pool",
        "uma_moe_gp_remote_pool",
        "uma_moe_gp_limit",
        "uma_moe_opposing_selection",
        "uma_moe_opposing_id",
        "uma_moe_parent_g1_budget",
        "uma_moe_g1_win_probability_cutoff",
    ),
}



def _stored_integer(value: object, default: int = 0) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _stored_boolean(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class LineageContextState:
    """Configuration shared by the lineage, uma.moe and Weights pages.

    The persisted key names predate the Qt interface and are intentionally kept
    compatible. Giving every consumer one typed view of those keys prevents a
    page from silently keeping a stale copy until a calculation starts.
    """

    ace_card_id: int = 0
    future_parent_card_id: int = 0
    surface: str = "turf"
    distance: str = "medium"
    style: str = "pace_chaser"
    course_key: str = ""
    top_n: int = 30
    track_id: int = 0
    rotation: str = "Non précisé"
    season: str = "Non précisé"
    weather: str = "Non précisé"
    ground_condition: str = "Non précisé"
    use_custom_scoring: bool = False
    skill_priorities_path: str = ""

    @classmethod
    def from_store(cls, store: SettingsStore) -> LineageContextState:
        surface = store.get("optimizer_surface", "turf")
        distance = store.get("optimizer_distance", "medium")
        style = store.get("optimizer_style", "pace_chaser")
        return cls(
            ace_card_id=_stored_integer(store.get("optimizer_ace_card_id")),
            future_parent_card_id=_stored_integer(
                store.get("optimizer_future_parent_card_id")
            ),
            surface=surface if surface in {"turf", "dirt"} else "turf",
            distance=(
                distance
                if distance in {"sprint", "mile", "medium", "long"}
                else "medium"
            ),
            style=(
                style
                if style
                in {
                    "front_runner",
                    "pace_chaser",
                    "late_surger",
                    "end_closer",
                }
                else "pace_chaser"
            ),
            course_key=store.get("optimizer_course_key"),
            top_n=max(
                5,
                min(200, _stored_integer(store.get("optimizer_top_n", "30"), 30)),
            ),
            track_id=_stored_integer(store.get("optimizer_track_id")),
            rotation=store.get("optimizer_rotation", "Non précisé")
            or "Non précisé",
            season=store.get("optimizer_season", "Non précisé")
            or "Non précisé",
            weather=store.get("optimizer_weather", "Non précisé")
            or "Non précisé",
            ground_condition=store.get("optimizer_ground", "Non précisé")
            or "Non précisé",
            use_custom_scoring=_stored_boolean(store.get("use_custom_scoring")),
            skill_priorities_path=store.get("skill_priorities_path"),
        )

    def normalized(self) -> LineageContextState:
        surface = self.surface if self.surface in {"turf", "dirt"} else "turf"
        distance = (
            self.distance
            if self.distance in {"sprint", "mile", "medium", "long"}
            else "medium"
        )
        style = (
            self.style
            if self.style
            in {
                "front_runner",
                "pace_chaser",
                "late_surger",
                "end_closer",
            }
            else "pace_chaser"
        )
        return replace(
            self,
            ace_card_id=_stored_integer(self.ace_card_id),
            future_parent_card_id=_stored_integer(self.future_parent_card_id),
            surface=surface,
            distance=distance,
            style=style,
            course_key=str(self.course_key or "").strip(),
            top_n=max(5, min(200, _stored_integer(self.top_n, 30))),
            track_id=_stored_integer(self.track_id),
            rotation=str(self.rotation or "Non précisé"),
            season=str(self.season or "Non précisé"),
            weather=str(self.weather or "Non précisé"),
            ground_condition=str(self.ground_condition or "Non précisé"),
            use_custom_scoring=bool(self.use_custom_scoring),
            skill_priorities_path=str(self.skill_priorities_path or "").strip(),
        )

    def store_values(self) -> dict[str, object]:
        return {
            "optimizer_ace_card_id": self.ace_card_id,
            "optimizer_future_parent_card_id": self.future_parent_card_id,
            "optimizer_surface": self.surface,
            "optimizer_distance": self.distance,
            "optimizer_style": self.style,
            "optimizer_course_key": self.course_key,
            "optimizer_top_n": self.top_n,
            "optimizer_track_id": self.track_id,
            "optimizer_rotation": self.rotation,
            "optimizer_season": self.season,
            "optimizer_weather": self.weather,
            "optimizer_ground": self.ground_condition,
            "use_custom_scoring": "1" if self.use_custom_scoring else "0",
            "skill_priorities_path": self.skill_priorities_path,
        }


class AppContext(QObject):
    configuration_changed = Signal()
    integration_changed = Signal()
    online_options_changed = Signal()
    lineage_changed = Signal(object)
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
        self.uma_moe_api_base = (
            self.store.get("uma_moe_base", DEFAULT_API_BASE) or DEFAULT_API_BASE
        ).strip()
        self.uma_moe_remember_api_key = _stored_boolean(
            self.store.get("uma_moe_remember_api_key")
        )
        self.uma_moe_api_key = resolve_api_key(
            api_key_path(self.store.path),
            remembered=self.uma_moe_remember_api_key,
        )

    def lineage_state(self) -> LineageContextState:
        return LineageContextState.from_store(self.store)

    def update_lineage(self, **changes: object) -> LineageContextState:
        """Persist a shared lineage edit immediately and notify both pages."""

        current = self.lineage_state()
        unknown = set(changes) - set(LineageContextState.__dataclass_fields__)
        if unknown:
            names = ", ".join(sorted(unknown))
            raise TypeError(f"Unknown lineage setting(s): {names}")
        updated = replace(current, **changes).normalized()
        current_values = current.store_values()
        updated_values = updated.store_values()
        changed_values = {
            key: value
            for key, value in updated_values.items()
            if str(current_values.get(key, "")) != str(value)
        }
        if changed_values:
            self.store.update(changed_values)
            self.lineage_changed.emit(updated)
        return updated

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

    def update_uma_moe_integration(
        self,
        *,
        api_base: str,
        api_key: str,
        remember_api_key: bool,
    ) -> None:
        """Update the long-lived uma.moe integration independently of scoring."""

        resolved_base = api_base.strip() or DEFAULT_API_BASE
        resolved_key = api_key.strip()
        remember = bool(remember_api_key)
        save_api_key(
            api_key_path(self.store.path),
            resolved_key if remember else "",
        )
        self.uma_moe_api_base = resolved_base
        self.uma_moe_api_key = resolved_key
        self.uma_moe_remember_api_key = remember
        self.store.update(
            {
                "uma_moe_base": resolved_base,
                "uma_moe_remember_api_key": int(remember),
            }
        )
        self.integration_changed.emit()

    def _file_signature(self, path: str | Path | None) -> list[object]:
        """Identify a file by path, size and mtime rather than by its bytes.

        Reading the overrides files on every badge refresh would put disk I/O
        on the path of ordinary interactions. Path, size and mtime move
        together with any edit made through the app or outside it.
        """
        if not path:
            return ["", 0, 0]
        candidate = Path(path).expanduser()
        try:
            stat = candidate.stat()
        except OSError:
            return [str(candidate), 0, 0]
        return [str(candidate), stat.st_size, int(stat.st_mtime_ns)]

    def family_fingerprint(self, family: str) -> str:
        """Digest exactly the inputs one result family consumes.

        A single revision counter over the whole context would mark local
        results stale because a uma.moe fetch limit moved — noise that teaches
        the user to ignore the badge. Each family therefore hashes its own
        inputs: everything shared, plus only its own search options.
        """
        state = self.lineage_state().normalized()
        payload: dict[str, object] = {
            "family": family,
            "lineage": {
                name: getattr(state, name)
                for name in sorted(LineageContextState.__dataclass_fields__)
            },
            "master": self._file_signature(self.master_path),
            "data": self._file_signature(self.veterans_json_path),
            "courses": self._file_signature(self.course_overrides_path),
            "skills": self._file_signature(state.skill_priorities_path),
            "scoring": self._file_signature(
                user_scoring_overrides_path() if state.use_custom_scoring else None
            ),
        }
        option_keys = SHARED_ONLINE_KEYS + FAMILY_ONLINE_KEYS.get(family, ())
        if option_keys:
            payload["options"] = {
                key: self.store.get(key, "") for key in sorted(option_keys)
            }
        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha1(canonical.encode("utf-8")).hexdigest()

    def update_online_options(self, values: dict[str, object]) -> None:
        """Persist a uma.moe search-option edit and notify every consumer.

        Routing these writes through the context, rather than letting a widget
        write ``store`` directly, is what lets result panes learn that a search
        input moved without polling the store.
        """
        if not values:
            return
        self.store.update(dict(values))
        self.online_options_changed.emit()

    def path(self, value: str) -> Path:
        return Path(value).expanduser()
