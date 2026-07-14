from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Mapping

COURSE_CATEGORY_ORDER = {
    "champions_meeting_upcoming": 0,
    "team_trials": 1,
    "champions_meeting_archive": 2,
    "other": 3,
}


RACECOURSE_ALIASES = {
    # The Global MDB currently uses "Ohi" while several community datasets
    # and historical CM references use "Ooi". They designate the same track.
    "ooi": "ohi",
    "oi": "ohi",
}


def normalize_racecourse_name(value: object) -> str:
    """Return a comparison-friendly racecourse name.

    Track combobox labels include a numeric MDB id (for example
    ``Ohi (10009)``), while preset files usually contain only the venue name.
    The normalisation also handles the common Ooi/Ohi romanisation mismatch.
    """

    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = text.lower().strip()
    text = re.sub(r"\s*\(\d+\)\s*$", "", text)
    text = re.sub(r"\b(?:racecourse|racetrack|track)\b", "", text)
    normalized = re.sub(r"[^a-z0-9]+", "", text)
    return RACECOURSE_ALIASES.get(normalized, normalized)


def racecourse_names_match(left: object, right: object) -> bool:
    left_name = normalize_racecourse_name(left)
    right_name = normalize_racecourse_name(right)
    if not left_name or not right_name:
        return False
    return (
        left_name == right_name
        or left_name.startswith(right_name)
        or right_name.startswith(left_name)
    )


def resolve_course_overrides_path(
    configured_path: str | Path | None,
    bundled_path: str | Path | None,
) -> Path | None:
    """Resolve the active preset file, falling back from a stale saved path.

    Older versions persisted an absolute path to the bundled JSON. Moving or
    replacing the application made that path stale and left the preset list
    empty. A valid user-selected file still takes priority; otherwise the
    current bundled file is used.
    """

    if configured_path:
        configured = Path(configured_path).expanduser()
        if configured.is_file():
            return configured.resolve()
    if bundled_path:
        bundled = Path(bundled_path).expanduser()
        if bundled.is_file():
            return bundled.resolve()
    return None


def load_course_preset_payload(path: str | Path | None) -> dict[str, Any]:
    if path is None:
        return {"metadata": {}, "courses": {}}
    preset_path = Path(path).expanduser()
    if not preset_path.is_file():
        return {"metadata": {}, "courses": {}}
    try:
        payload = json.loads(preset_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {"metadata": {}, "courses": {}}
    if not isinstance(payload, dict):
        return {"metadata": {}, "courses": {}}
    courses = payload.get("courses")
    if not isinstance(courses, dict):
        payload["courses"] = {}
    return payload


def _cm_number(course_key: str, course: Mapping[str, Any]) -> int | None:
    sequence = course.get("sequence")
    try:
        if sequence is not None:
            return int(sequence)
    except (TypeError, ValueError):
        pass
    match = re.search(r"(?:^|_)cm(\d+)(?:_|$)", course_key.lower())
    return int(match.group(1)) if match else None


def course_preset_sort_key(item: tuple[str, Mapping[str, Any]]) -> tuple[int, int, str]:
    key, course = item
    explicit_order = course.get("display_order")
    try:
        if explicit_order is not None:
            return (-1, int(explicit_order), key.lower())
    except (TypeError, ValueError):
        pass

    category = str(course.get("category") or "other")
    category_order = COURSE_CATEGORY_ORDER.get(category, COURSE_CATEGORY_ORDER["other"])
    sequence = _cm_number(key, course)
    if category == "champions_meeting_upcoming":
        sequence_order = sequence if sequence is not None else 9999
    elif category == "champions_meeting_archive":
        # Most recent archived CM first.
        sequence_order = -(sequence if sequence is not None else 0)
    else:
        try:
            sequence_order = int(course.get("sequence") or 0)
        except (TypeError, ValueError):
            sequence_order = 0
    return (category_order, sequence_order, key.lower())


def ordered_course_presets(payload: Mapping[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    courses = payload.get("courses") or {}
    if not isinstance(courses, Mapping):
        return []
    normalized = [
        (str(key), dict(value))
        for key, value in courses.items()
        if isinstance(value, Mapping)
    ]
    return sorted(normalized, key=course_preset_sort_key)


def course_preset_label(course_key: str, course: Mapping[str, Any], language: str = "en") -> str:
    localized = course.get(f"label_{language}")
    if localized:
        return str(localized)
    label = course.get("label")
    return str(label or course_key)


def course_preset_conditions(course: Mapping[str, Any]) -> dict[str, Any]:
    """Return canonical static race conditions declared by a preset."""

    raw = course.get("conditions") or {}
    if not isinstance(raw, Mapping):
        return {}
    result: dict[str, Any] = {}
    for key in ("rotation", "season", "weather", "ground_condition", "track_id"):
        value = raw.get(key)
        if value is None or value == "":
            continue
        if isinstance(value, list):
            result[key] = [int(item) for item in value]
        else:
            result[key] = int(value)
    return result
