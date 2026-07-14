from __future__ import annotations

import csv
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable


Logger = Callable[[str], None]

SURFACES = ("turf", "dirt")
DISTANCES = ("sprint", "mile", "medium", "long")
STYLES = ("front_runner", "pace_chaser", "late_surger", "end_closer")

# Mechanics that depend heavily on pack simulation, lane movement, or traffic.
TRAFFIC_VARIABLES = {
    "infront_near_lane_time",
    "behind_near_lane_time",
    "blocked_front_continuetime",
    "blocked_side_continuetime",
    "is_move_lane",
    "is_surrounded",
    "lane_type",
    "near_count",
    "overtake_target_time",
}


def _default_logger(message: str) -> None:
    print(message)


@dataclass(frozen=True)
class SimulatorWeightResult:
    weights_path: Path
    review_queue_path: Path
    summary_csv_path: Path
    course_weights_path: Path | None
    skill_count: int
    simulated_skill_count: int
    review_item_count: int
    manually_adjusted_cell_count: int
    positioning_adjusted_cell_count: int
    course_preset_count: int


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _quantile(values: Iterable[float], q: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _profile_key(surface: str, distance: str, style: str) -> str:
    return f"{surface}.{distance}.{style}"


def _matrix(default: Any = None) -> dict[str, dict[str, dict[str, Any]]]:
    return {
        surface: {
            distance: {style: default for style in STYLES}
            for distance in DISTANCES
        }
        for surface in SURFACES
    }


def _robust_value(stats: dict[str, Any]) -> float:
    mean = max(0.0, float(stats.get("mean", 0.0)))
    median = max(0.0, float(stats.get("median", 0.0)))
    positive_rate = float(stats.get("positive_rate", 0.0))
    p90 = float(stats.get("p90", 0.0))
    maximum = float(stats.get("max", 0.0))

    # Umalator's baseline noise in this batch is roughly 0.0002 mean and
    # 0.0053 max. Treat clearly inactive skills as zero.
    if positive_rate == 0.0 and p90 == 0.0 and maximum < 0.01:
        return 0.0
    return 0.75 * mean + 0.25 * median


def _mechanically_compatible(
    hints: dict[str, Any], surface: str, distance: str, style: str
) -> bool:
    explicit_surfaces = set(hints.get("explicit_surfaces") or [])
    explicit_distances = set(hints.get("explicit_distances") or [])
    explicit_styles = set(hints.get("explicit_styles") or [])
    if explicit_surfaces and surface not in explicit_surfaces:
        return False
    if explicit_distances and distance not in explicit_distances:
        return False
    if explicit_styles and style not in explicit_styles:
        return False
    return True


def _matches(rule_match: dict[str, Any], surface: str, distance: str, style: str) -> bool:
    axes = {
        "surface": surface,
        "distance": distance,
        "style": style,
    }
    plural_keys = {
        "surface": "surfaces",
        "distance": "distances",
        "style": "styles",
    }
    for singular, actual in axes.items():
        if singular in rule_match and rule_match[singular] != actual:
            return False
        plural = plural_keys[singular]
        if plural in rule_match and actual not in set(rule_match[plural]):
            return False
    return True


def _apply_rules(
    base_weight: float,
    rules: list[dict[str, Any]],
    surface: str,
    distance: str,
    style: str,
) -> tuple[float, list[dict[str, Any]]]:
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
        else:
            raise ValueError(f"Unknown manual adjustment operation: {operation!r}")
        weight = max(0.0, min(1.2, weight))
        applied.append(
            {
                "operation": operation,
                "value": value,
                "before": round(before, 6),
                "after": round(weight, 6),
                "reason": rule.get("reason", ""),
            }
        )
    return weight, applied


def _extract_condition_variables(skill_entry: dict[str, Any]) -> set[str]:
    variables: set[str] = set()
    for condition in (skill_entry.get("conditions") or {}).values():
        variables.update(condition.get("variables") or [])
    return variables


def _catalog_indexes(catalog: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    by_key: dict[str, Any] = {}
    skill_id_to_key: dict[str, str] = {}
    for skill in catalog.get("skills", []):
        white = skill.get("white_spark")
        if not white or not white.get("is_inherited_hint_variant"):
            continue
        key = str(white["catalog_key"])
        by_key[key] = skill
        skill_id_to_key[str(skill["skill_id"])] = key
    return by_key, skill_id_to_key


def _load_adjustments(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {"skills": {}}
    payload = _read_json(path)
    if not isinstance(payload, dict) or not isinstance(payload.get("skills", {}), dict):
        raise ValueError("Manual adjustments JSON must contain an object named 'skills'.")
    return payload


def _load_course_overrides(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {"courses": {}}
    payload = _read_json(path)
    if not isinstance(payload, dict) or not isinstance(payload.get("courses", {}), dict):
        raise ValueError("Course overrides JSON must contain an object named 'courses'.")
    return payload


def _apply_positioning_rules(
    rules: list[dict[str, Any]],
    surface: str,
    distance: str,
    style: str,
) -> tuple[float, list[dict[str, Any]]]:
    bonus = 0.0
    applied: list[dict[str, Any]] = []
    for rule in rules:
        if not _matches(rule.get("match", {}), surface, distance, style):
            continue
        value = max(0.0, float(rule.get("value", 0.0)))
        before = bonus
        bonus = min(0.30, bonus + value)
        applied.append(
            {
                "value": value,
                "before": round(before, 6),
                "after": round(bonus, 6),
                "reason": rule.get("reason", ""),
            }
        )
    return bonus, applied


def _apply_course_rules(
    base_weight: float,
    rules: list[dict[str, Any]],
    surface: str,
    distance: str,
    style: str,
) -> tuple[float, list[dict[str, Any]]]:
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
        weight = max(0.0, min(1.2, weight))
        applied.append(
            {
                "operation": operation,
                "value": value,
                "before": round(before, 6),
                "after": round(weight, 6),
                "reason": rule.get("reason", ""),
            }
        )
    return weight, applied


def generate_simulator_weights(
    batch_path: str | Path,
    skill_catalog_path: str | Path,
    weights_template_path: str | Path,
    output_dir: str | Path,
    manual_adjustments_path: str | Path | None = None,
    course_overrides_path: str | Path | None = None,
    logger: Logger | None = None,
) -> SimulatorWeightResult:
    logger = logger or _default_logger
    batch_path = Path(batch_path)
    skill_catalog_path = Path(skill_catalog_path)
    weights_template_path = Path(weights_template_path)
    output_dir = Path(output_dir)
    adjustments_path = Path(manual_adjustments_path) if manual_adjustments_path else None
    course_overrides_path = (
        Path(course_overrides_path) if course_overrides_path else None
    )

    for path, label in (
        (batch_path, "Umalator batch"),
        (skill_catalog_path, "skill condition catalog"),
        (weights_template_path, "white skill weights template"),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"Missing {label}: {path}")

    logger("Reading Umalator batch and current MDB skill catalog…")
    batch = _read_json(batch_path)
    catalog = _read_json(skill_catalog_path)
    template = _read_json(weights_template_path)
    adjustments = _load_adjustments(adjustments_path)
    course_overrides = _load_course_overrides(course_overrides_path)

    if int(batch.get("metadata", {}).get("schema_version", 0)) != 2:
        raise ValueError("This importer expects Umalator batch schema_version 2.")

    catalog_by_key, skill_id_to_key = _catalog_indexes(catalog)
    template_skills: dict[str, Any] = template.get("skills", {})
    if not template_skills:
        raise ValueError("The weight template contains no skills.")

    # Map current inherited skill IDs from the template. This deliberately avoids
    # retaining old IDs between MDB updates.
    key_to_skill_id: dict[str, str] = {}
    for key, entry in template_skills.items():
        inherit_id = (entry.get("current_mdb") or {}).get("inherit_skill_id")
        if inherit_id is not None:
            key_to_skill_id[key] = str(inherit_id)

    # Union of parser-incompatible IDs across all profiles.
    skipped_ids: dict[str, list[str]] = {}
    for profile_key, profile in batch.get("profiles", {}).items():
        diagnostics = profile.get("diagnostics") or {}
        for skipped in diagnostics.get("skipped_skills") or []:
            sid = str(skipped.get("skill_id"))
            skipped_ids.setdefault(sid, []).append(str(skipped.get("error", "")))

    # Compute profile-specific p95 scales after excluding explicit mechanical
    # incompatibilities. This keeps profile weights comparable without assuming
    # that one second on Sprint equals one second on Long.
    profile_scales: dict[str, float] = {}
    profile_active_counts: dict[str, int] = {}
    for surface in SURFACES:
        for distance in DISTANCES:
            for style in STYLES:
                profile_key = _profile_key(surface, distance, style)
                profile = batch.get("profiles", {}).get(profile_key)
                if not profile:
                    profile_scales[profile_key] = 1.0
                    profile_active_counts[profile_key] = 0
                    continue
                active_values: list[float] = []
                for sid, stats in (profile.get("skills") or {}).items():
                    key = skill_id_to_key.get(str(sid))
                    if not key:
                        continue
                    skill = catalog_by_key.get(key, {})
                    hints = skill.get("profile_hints") or {}
                    if not _mechanically_compatible(hints, surface, distance, style):
                        continue
                    value = _robust_value(stats)
                    if value > 0.005:
                        active_values.append(value)
                scale = _quantile(active_values, 0.95)
                profile_scales[profile_key] = scale if scale > 0 else 1.0
                profile_active_counts[profile_key] = len(active_values)

    output_skills: dict[str, Any] = {}
    review_candidates: dict[str, dict[str, Any]] = {}
    manually_adjusted_cells = 0
    positioning_adjusted_cells = 0
    simulated_count = 0
    summary_rows: list[dict[str, Any]] = []

    adjustment_skills: dict[str, Any] = adjustments.get("skills", {})

    for key, template_entry in sorted(template_skills.items()):
        skill = catalog_by_key.get(key, {})
        sid = key_to_skill_id.get(key)
        hints = skill.get("profile_hints") or template_entry.get("automatic_profile_hints") or {}
        variables = _extract_condition_variables(skill)
        condition_categories = sorted(set(hints.get("condition_categories") or []))
        is_course_dependent = "course_static" in condition_categories
        adjustment_meta = adjustment_skills.get(key) or {}
        skill_rules = adjustment_meta.get("rules") or []
        positioning_rules = adjustment_meta.get("positioning_rules") or []
        cells = _matrix()
        has_simulation = False
        max_auto_weight = 0.0
        max_final_weight = 0.0
        min_samples: int | None = None
        adjustment_count = 0
        positioning_count = 0

        for surface in SURFACES:
            for distance in DISTANCES:
                for style in STYLES:
                    profile_key = _profile_key(surface, distance, style)
                    profile = batch.get("profiles", {}).get(profile_key)
                    stats = None
                    if profile is not None and sid is not None:
                        stats = (profile.get("skills") or {}).get(sid)

                    compatible = _mechanically_compatible(hints, surface, distance, style)
                    flags: list[str] = []
                    if is_course_dependent:
                        flags.append("course_dependent")
                    if variables & TRAFFIC_VARIABLES:
                        flags.append("traffic_model_sensitive")
                    if sid in skipped_ids:
                        flags.append("umalator_parser_incompatible")

                    if not compatible:
                        auto_weight = 0.0
                        performance_weight = 0.0
                        positioning_bonus = 0.0
                        final_weight = 0.0
                        robust = 0.0
                        status = "mechanical_zero"
                        simulator_payload = stats
                        applied: list[dict[str, Any]] = []
                        positioning_applied: list[dict[str, Any]] = []
                    elif stats is None:
                        auto_weight = None
                        robust = None
                        applied = []
                        positioning_applied = []
                        if skill_rules:
                            performance_weight, applied = _apply_rules(
                                0.0, skill_rules, surface, distance, style
                            )
                        else:
                            performance_weight = None
                        positioning_bonus, positioning_applied = _apply_positioning_rules(
                            positioning_rules, surface, distance, style
                        )
                        if performance_weight is None and not positioning_applied:
                            final_weight = None
                            status = "not_simulated"
                        else:
                            final_weight = min(
                                1.2,
                                max(0.0, float(performance_weight or 0.0) + positioning_bonus),
                            )
                            status = "manual_only"
                        robust = None
                        simulator_payload = None
                    else:
                        has_simulation = True
                        robust = _robust_value(stats)
                        scale = profile_scales[profile_key]
                        auto_weight = max(0.0, min(1.2, robust / scale))
                        performance_weight, applied = _apply_rules(
                            auto_weight, skill_rules, surface, distance, style
                        )
                        positioning_bonus, positioning_applied = _apply_positioning_rules(
                            positioning_rules, surface, distance, style
                        )
                        final_weight = min(
                            1.2, max(0.0, performance_weight + positioning_bonus)
                        )
                        if applied and positioning_applied:
                            status = "manual_and_positioning_adjusted"
                        elif applied:
                            status = "manual_adjusted"
                        elif positioning_applied:
                            status = "positioning_adjusted"
                        else:
                            status = "auto"
                        simulator_payload = {
                            name: stats.get(name)
                            for name in (
                                "samples",
                                "min",
                                "p10",
                                "p25",
                                "median",
                                "mean",
                                "p75",
                                "p90",
                                "max",
                                "positive_rate",
                                "ge_0_1_rate",
                                "ge_0_5_rate",
                                "ge_1_0_rate",
                            )
                        }
                        samples = int(stats.get("samples", 0))
                        min_samples = samples if min_samples is None else min(min_samples, samples)
                        max_auto_weight = max(max_auto_weight, auto_weight)

                    if applied:
                        manually_adjusted_cells += 1
                        adjustment_count += 1
                    if positioning_applied:
                        positioning_adjusted_cells += 1
                        positioning_count += 1
                    if final_weight is not None:
                        max_final_weight = max(max_final_weight, final_weight)

                    cells[surface][distance][style] = {
                        "weight": None if final_weight is None else round(final_weight, 6),
                        "auto_weight": None if auto_weight is None else round(auto_weight, 6),
                        "performance_weight": (
                            None
                            if performance_weight is None
                            else round(performance_weight, 6)
                        ),
                        "positioning_bonus": round(positioning_bonus, 6),
                        "status": status,
                        "raw_robust_value": None if robust is None else round(robust, 9),
                        "profile_p95_scale": round(profile_scales[profile_key], 9),
                        "simulator": simulator_payload,
                        "manual_adjustments": applied,
                        "positioning_adjustments": positioning_applied,
                        "flags": flags,
                    }

        if has_simulation:
            simulated_count += 1

        output_skills[key] = {
            "spark_name": template_entry.get("spark_name"),
            "description": template_entry.get("description"),
            "current_mdb": template_entry.get("current_mdb"),
            "condition_variables": sorted(variables),
            "condition_categories": condition_categories,
            "profile_hints": hints,
            "requires_course_evaluation": is_course_dependent,
            "manual_adjustment_summary": {
                "configured": bool(skill_rules or positioning_rules),
                "adjusted_cell_count": adjustment_count,
                "positioning_adjusted_cell_count": positioning_count,
                "notes": adjustment_meta.get("notes", ""),
            },
            "weight_matrix": cells,
        }

        review_required = bool(
            adjustment_meta.get("review_required", bool(skill_rules))
        )
        if review_required and (skill_rules or positioning_rules):
            review_candidates[key] = {
                "catalog_key": key,
                "spark_name": template_entry.get("spark_name"),
                "priority": adjustment_meta.get("review_priority", "high"),
                "reason": adjustment_meta.get("notes", "Manual adjustment configured."),
                "status": "manual_rule_applied",
                "max_auto_weight": round(max_auto_weight, 6),
                "max_final_weight": round(max_final_weight, 6),
                "condition_variables": sorted(variables),
                "suggested_action": (
                    "Verify the shipped manual/positioning rule against gameplay knowledge."
                ),
            }
        elif sid in skipped_ids:
            review_candidates[key] = {
                "catalog_key": key,
                "spark_name": template_entry.get("spark_name"),
                "priority": "high",
                "reason": "Umalator parser rejected this skill in every profile.",
                "status": "not_simulated_parser_error",
                "errors": sorted(set(skipped_ids[sid])),
                "condition_variables": sorted(variables),
                "suggested_action": "Assign a manual matrix or fix the simulator parser mapping.",
            }
        elif variables & TRAFFIC_VARIABLES and max_auto_weight >= 0.8:
            review_candidates[key] = {
                "catalog_key": key,
                "spark_name": template_entry.get("spark_name"),
                "priority": "medium",
                "reason": (
                    "High simulated value with a traffic/lane condition that may be "
                    "sensitive to pacer count and laneMovement=false."
                ),
                "status": "targeted_sanity_check",
                "max_auto_weight": round(max_auto_weight, 6),
                "condition_variables": sorted(variables & TRAFFIC_VARIABLES),
                "suggested_action": "Check style-specific plausibility; keep auto values if reasonable.",
            }

        summary_rows.append(
            {
                "catalog_key": key,
                "spark_name": template_entry.get("spark_name"),
                "inherit_skill_id": sid or "",
                "simulated": has_simulation,
                "min_samples": "" if min_samples is None else min_samples,
                "max_auto_weight": round(max_auto_weight, 6),
                "max_final_weight": round(max_final_weight, 6),
                "manual_adjusted_cells": adjustment_count,
                "positioning_adjusted_cells": positioning_count,
                "course_dependent": is_course_dependent,
                "review_priority": (review_candidates.get(key) or {}).get("priority", ""),
                "review_status": (review_candidates.get(key) or {}).get("status", ""),
            }
        )

    no_inherit = batch.get("template", {}).get("no_inherit_skill_id") or []
    weights_payload = {
        "metadata": {
            "schema_version": 1,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "purpose": (
                "Profile-specific white skill Spark weights derived from Umalator, "
                "with exact MDB incompatibility filters and small documented manual overrides."
            ),
            "source_batch": batch_path.name,
            "source_batch_sha256": _sha256(batch_path),
            "source_catalog": skill_catalog_path.name,
            "source_catalog_sha256": _sha256(skill_catalog_path),
            "source_template": weights_template_path.name,
            "source_template_sha256": _sha256(weights_template_path),
            "manual_adjustments": adjustments_path.name if adjustments_path else None,
            "manual_adjustments_sha256": (
                _sha256(adjustments_path) if adjustments_path and adjustments_path.is_file() else None
            ),
            "course_overrides": (
                course_overrides_path.name if course_overrides_path else None
            ),
            "course_overrides_sha256": (
                _sha256(course_overrides_path)
                if course_overrides_path and course_overrides_path.is_file()
                else None
            ),
            "normalization": {
                "robust_value": "0.75 * mean + 0.25 * median",
                "inactive_noise_rule": "positive_rate == 0 and p90 == 0 and max < 0.01 => 0",
                "profile_scale": "95th percentile of active, mechanically compatible skills",
                "performance_weight": (
                    "manual_adjust(clamp(robust_value / profile_scale, 0, 1.2))"
                ),
                "positioning_bonus": (
                    "small additive strategic bonus, independently documented and capped at 0.30"
                ),
                "weight": "clamp(performance_weight + positioning_bonus, 0, 1.2)",
                "important": (
                    "mean already includes failed/non-triggered simulations; positive_rate is "
                    "not multiplied a second time."
                ),
            },
            "manual_priority": [
                "mechanical incompatibility from current MDB",
                "documented manual adjustment",
                "Umalator normalized score",
                "small positioning bonus for strategically important placement skills",
                "optional exact-course override",
            ],
        },
        "axes": template.get("axes"),
        "batch_baseline": batch.get("baseline"),
        "profile_normalization": {
            key: {
                "p95_scale": round(value, 9),
                "active_skill_count": profile_active_counts[key],
                "course": (batch.get("profiles", {}).get(key) or {}).get("course"),
            }
            for key, value in profile_scales.items()
        },
        "summary": {
            "template_skill_count": len(template_skills),
            "simulated_skill_count": simulated_count,
            "manual_adjusted_cell_count": manually_adjusted_cells,
            "positioning_adjusted_cell_count": positioning_adjusted_cells,
            "review_item_count": len(review_candidates),
            "no_inherit_skill_id_count": len(no_inherit),
            "parser_incompatible_skill_id_count": len(skipped_ids),
        },
        "skills": output_skills,
    }

    course_documents: dict[str, Any] = {}
    for course_key, course in sorted((course_overrides.get("courses") or {}).items()):
        profile = course.get("profile") or {}
        surface = str(profile.get("surface", ""))
        distance = str(profile.get("distance", ""))
        style_filter = profile.get("style")
        styles = [str(style_filter)] if style_filter else list(STYLES)
        if surface not in SURFACES or distance not in DISTANCES:
            raise ValueError(
                f"Course preset {course_key!r} has invalid surface/distance profile."
            )
        invalid_styles = [style for style in styles if style not in STYLES]
        if invalid_styles:
            raise ValueError(
                f"Course preset {course_key!r} has invalid styles: {invalid_styles}"
            )

        configured_rules: dict[str, Any] = course.get("skills") or {}
        style_payload: dict[str, Any] = {}
        for style in styles:
            skill_weights: dict[str, Any] = {}
            for skill_key, skill_entry in output_skills.items():
                cell = skill_entry["weight_matrix"][surface][distance][style]
                generic_weight = cell.get("weight")
                if generic_weight is None:
                    final_weight = None
                    applied: list[dict[str, Any]] = []
                else:
                    rules = (configured_rules.get(skill_key) or {}).get("rules") or []
                    final_weight, applied = _apply_course_rules(
                        float(generic_weight), rules, surface, distance, style
                    )
                skill_weights[skill_key] = {
                    "spark_name": skill_entry.get("spark_name"),
                    "generic_weight": generic_weight,
                    "weight": None if final_weight is None else round(final_weight, 6),
                    "course_adjustments": applied,
                }
            style_payload[style] = {"skills": skill_weights}

        course_documents[course_key] = {
            "label": course.get("label", course_key),
            "profile": {
                "surface": surface,
                "distance": distance,
                "styles": styles,
            },
            "race": course.get("race", {}),
            "source": course.get("source"),
            "notes": course.get("notes", ""),
            "configured_skill_count": len(configured_rules),
            "style_weights": style_payload,
        }

    course_weights_payload = {
        "metadata": {
            "schema_version": 1,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "purpose": (
                "Exact-course overlays applied on top of generic surface/distance/style weights."
            ),
            "source_generic_weights": "simulator_skill_weights.json",
            "source_overrides": (
                course_overrides_path.name if course_overrides_path else None
            ),
            "important": (
                "Generic weights remain the default. Select one course preset only when "
                "the target race is known."
            ),
        },
        "courses": course_documents,
    }

    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    review_items = sorted(
        review_candidates.values(),
        key=lambda item: (
            priority_order.get(str(item.get("priority")), 9),
            str(item.get("spark_name", "")),
        ),
    )
    review_payload = {
        "metadata": {
            "schema_version": 1,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "purpose": (
                "Small, targeted manual review queue. Most simulated skills are intentionally "
                "left on automatic weights."
            ),
            "source_batch": batch_path.name,
        },
        "review_policy": {
            "critical": "Known material under/over-modeling on an important skill.",
            "high": "No simulation or an explicit manual correction is already required.",
            "medium": "High-value traffic-sensitive skill; quick sanity check recommended.",
        },
        "items": review_items,
        "not_scored_without_inherit_skill_id": no_inherit,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    weights_path = output_dir / "simulator_skill_weights.json"
    review_path = output_dir / "manual_review_queue.json"
    csv_path = output_dir / "simulator_skill_weights_summary.csv"
    course_weights_path = (
        output_dir / "course_skill_weights.json" if course_documents else None
    )
    _write_json(weights_path, weights_payload)
    _write_json(review_path, review_payload)
    if course_weights_path:
        _write_json(course_weights_path, course_weights_payload)

    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary_rows[0].keys()))
        writer.writeheader()
        writer.writerows(summary_rows)

    logger(f"Simulator weights: {weights_path}")
    logger(f"Manual review queue: {review_path}")
    logger(f"Weight summary CSV: {csv_path}")
    if course_weights_path:
        logger(f"Course-specific weights: {course_weights_path}")
    logger(
        f"{simulated_count}/{len(template_skills)} skills simulated; "
        f"{len(review_items)} targeted review items; "
        f"{manually_adjusted_cells} manual cells; "
        f"{positioning_adjusted_cells} positioning cells; "
        f"{len(course_documents)} course presets."
    )

    return SimulatorWeightResult(
        weights_path=weights_path,
        review_queue_path=review_path,
        summary_csv_path=csv_path,
        course_weights_path=course_weights_path,
        skill_count=len(template_skills),
        simulated_skill_count=simulated_count,
        review_item_count=len(review_items),
        manually_adjusted_cell_count=manually_adjusted_cells,
        positioning_adjusted_cell_count=positioning_adjusted_cells,
        course_preset_count=len(course_documents),
    )
