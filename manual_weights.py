from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

SURFACES = ("turf", "dirt")
DISTANCES = ("sprint", "mile", "medium", "long")
STYLES = ("front_runner", "pace_chaser", "late_surger", "end_closer")

Logger = Callable[[str], None]


@dataclass(frozen=True)
class ManualWeightResult:
    weights_path: Path
    course_weights_path: Path | None
    skill_count: int
    configured_skill_count: int
    course_preset_count: int


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as stream:
        return json.load(stream)


def _write_json(path: Path, payload: Any) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _matches(match: dict[str, Any], surface: str, distance: str, style: str) -> bool:
    for key, current in (("surface", surface), ("distance", distance), ("style", style)):
        expected = match.get(key)
        if expected is None:
            continue
        if isinstance(expected, list):
            if current not in expected:
                return False
        elif current != expected:
            return False
    return True


def _mechanically_compatible(hints: dict[str, Any], surface: str, distance: str, style: str) -> bool:
    explicit_styles = set(hints.get("explicit_styles") or [])
    explicit_distances = set(hints.get("explicit_distances") or [])
    explicit_surfaces = set(hints.get("explicit_surfaces") or [])
    return not (
        (explicit_styles and style not in explicit_styles)
        or (explicit_distances and distance not in explicit_distances)
        or (explicit_surfaces and surface not in explicit_surfaces)
    )


def _apply_course_rules(base_weight: float, rules: list[dict[str, Any]], surface: str, distance: str, style: str) -> tuple[float, list[dict[str, Any]]]:
    weight = base_weight
    applied: list[dict[str, Any]] = []
    for rule in rules:
        if not _matches(rule.get("match", {}), surface, distance, style):
            continue
        operation = str(rule.get("operation", "")).lower()
        value = float(rule.get("value", 0.0))
        before = weight
        if operation == "override":
            weight = value
        elif operation == "multiplier":
            weight *= value
        elif operation == "floor":
            weight = max(weight, value)
        elif operation == "cap":
            weight = min(weight, value)
        elif operation == "bonus":
            weight += value
        else:
            raise ValueError(f"Unknown course override operation: {operation!r}")
        weight = max(0.0, min(1.35, weight))
        applied.append({
            "operation": operation,
            "value": value,
            "before": round(before, 6),
            "after": round(weight, 6),
            "reason": rule.get("reason", ""),
        })
    return weight, applied


def _profile_weight(entry: dict[str, Any], surface: str, distance: str, style: str) -> tuple[float, list[str]]:
    base = float(entry.get("base", 0.05))
    reasons = [f"base={base:.3f}"]
    dimension_values: list[float] = []
    for dimension, current in (("surface", surface), ("distance", distance), ("style", style)):
        overrides = entry.get(dimension) or {}
        if current in overrides:
            value = float(overrides[current])
            dimension_values.append(value)
            reasons.append(f"{dimension}:{current}={value:.3f}")
    if dimension_values:
        # Explicit zero is a hard incompatibility. Otherwise combine multiple profile
        # dimensions instead of letting the last one silently overwrite the others.
        base = 0.0 if any(value <= 0.0 for value in dimension_values) else sum(dimension_values) / len(dimension_values)
        reasons.append(f"combined_dimensions={base:.3f}")
    for rule in entry.get("profiles") or []:
        if _matches(rule.get("match", {}), surface, distance, style):
            operation = str(rule.get("operation", "override")).lower()
            value = float(rule.get("value", 0.0))
            if operation == "override":
                base = value
            elif operation == "floor":
                base = max(base, value)
            elif operation == "cap":
                base = min(base, value)
            elif operation == "multiplier":
                base *= value
            elif operation == "bonus":
                base += value
            reasons.append(f"rule:{operation}({value:.3f})")
    # No separate scarcity multiplier: sought-after / hard-to-source skills are already
    # assigned higher manual priorities in default_skill_priorities.json.
    return max(0.0, min(1.35, base)), reasons


def generate_manual_skill_weights(
    skill_catalog_path: str | Path,
    priorities_path: str | Path,
    output_dir: str | Path,
    course_overrides_path: str | Path | None = None,
    logger: Logger | None = None,
) -> ManualWeightResult:
    logger = logger or (lambda _message: None)
    skill_catalog_path = Path(skill_catalog_path)
    priorities_path = Path(priorities_path)
    output_dir = Path(output_dir)
    course_overrides_path = Path(course_overrides_path) if course_overrides_path else None
    for path, label in ((skill_catalog_path, "skill catalog"), (priorities_path, "manual priorities")):
        if not path.is_file():
            raise FileNotFoundError(f"Missing {label}: {path}")
    output_dir.mkdir(parents=True, exist_ok=True)

    catalog = _read_json(skill_catalog_path)
    priorities = _read_json(priorities_path)
    course_overrides = _read_json(course_overrides_path) if course_overrides_path and course_overrides_path.is_file() else {"courses": {}}
    configured = priorities.get("skills") or {}
    baseline = float(priorities.get("default_weight", 0.04))

    skills_by_key: dict[str, dict[str, Any]] = {}
    for skill in catalog.get("skills") or []:
        white = skill.get("white_spark") or {}
        key = str(white.get("catalog_key") or "")
        if key and key not in skills_by_key:
            skills_by_key[key] = skill

    output_skills: dict[str, Any] = {}
    for key, skill in sorted(skills_by_key.items()):
        white = skill.get("white_spark") or {}
        entry = configured.get(key) or {"base": baseline, "rarity": "common"}
        matrix: dict[str, Any] = {}
        for surface in SURFACES:
            matrix[surface] = {}
            for distance in DISTANCES:
                matrix[surface][distance] = {}
                for style in STYLES:
                    if not _mechanically_compatible(skill.get("profile_hints") or {}, surface, distance, style):
                        weight = 0.0
                        reasons = ["mechanical incompatibility from MDB"]
                        status = "mechanical_zero"
                    else:
                        weight, reasons = _profile_weight(entry, surface, distance, style)
                        status = "manual_priority"
                    matrix[surface][distance][style] = {
                        "weight": round(weight, 6),
                        "status": status,
                        "reasons": reasons,
                    }
        output_skills[key] = {
            "spark_name": white.get("spark_name"),
            "description": skill.get("description"),
            "current_mdb": {
                "factor_group_id": white.get("factor_group_id"),
                "factor_ids_by_stars": white.get("factor_ids_by_stars"),
                "inherit_skill_id": skill.get("skill_id"),
            },
            "profile_hints": skill.get("profile_hints") or {},
            "priority": entry,
            "weight_matrix": matrix,
        }

    weights_payload = {
        "metadata": {
            "schema_version": 2,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "purpose": "Manual white-skill priorities for parent and lineage scoring; Umalator and separate scarcity multipliers are not used.",
            "source_skill_catalog": skill_catalog_path.name,
            "source_skill_catalog_sha256": _sha256(skill_catalog_path),
            "source_priorities": priorities_path.name,
            "source_priorities_sha256": _sha256(priorities_path),
            "important": "Weights represent value as a white Spark for the selected profile, not raw in-race performance.",
        },
        "axes": {"surfaces": list(SURFACES), "distances": list(DISTANCES), "styles": list(STYLES)},
        "summary": {
            "skill_count": len(output_skills),
            "configured_skill_count": sum(1 for key in output_skills if key in configured),
            "default_weight": baseline,
        },
        "skills": output_skills,
    }
    weights_path = output_dir / "manual_skill_weights.json"
    _write_json(weights_path, weights_payload)

    course_documents: dict[str, Any] = {}
    for course_key, course in sorted((course_overrides.get("courses") or {}).items()):
        profile = course.get("profile") or {}
        surface = str(profile.get("surface", ""))
        distance = str(profile.get("distance", ""))
        style_filter = profile.get("style")
        styles = [str(style_filter)] if style_filter else list(STYLES)
        if surface not in SURFACES or distance not in DISTANCES:
            continue
        configured_rules = course.get("skills") or {}
        style_payload: dict[str, Any] = {}
        for style in styles:
            skill_weights: dict[str, Any] = {}
            for skill_key, skill_entry in output_skills.items():
                generic_weight = float(skill_entry["weight_matrix"][surface][distance][style]["weight"])
                rules = (configured_rules.get(skill_key) or {}).get("rules") or []
                final_weight, applied = _apply_course_rules(generic_weight, rules, surface, distance, style)
                skill_weights[skill_key] = {
                    "spark_name": skill_entry.get("spark_name"),
                    "generic_weight": generic_weight,
                    "weight": round(final_weight, 6),
                    "course_adjustments": applied,
                }
            style_payload[style] = {"skills": skill_weights}
        course_documents[course_key] = {
            "label": course.get("label", course_key),
            "profile": {"surface": surface, "distance": distance, "styles": styles},
            "race": course.get("race", {}),
            "source": course.get("source"),
            "notes": course.get("notes", ""),
            "configured_skill_count": len(configured_rules),
            "style_weights": style_payload,
        }

    course_path: Path | None = None
    if course_documents:
        course_path = output_dir / "course_skill_weights.json"
        _write_json(course_path, {
            "metadata": {
                "schema_version": 1,
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "purpose": "Exact-course overlays applied on top of manual profile weights.",
                "source_generic_weights": weights_path.name,
                "source_overrides": course_overrides_path.name if course_overrides_path else None,
            },
            "courses": course_documents,
        })

    logger(f"Manual skill weights: {weights_path}")
    if course_path:
        logger(f"Course-specific weights: {course_path}")
    return ManualWeightResult(
        weights_path=weights_path,
        course_weights_path=course_path,
        skill_count=len(output_skills),
        configured_skill_count=sum(1 for key in output_skills if key in configured),
        course_preset_count=len(course_documents),
    )
