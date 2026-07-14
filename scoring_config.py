from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any, Iterable


class ScoringConfigError(ValueError):
    pass


_MISSING = object()


def read_json_object(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    try:
        with resolved.open("r", encoding="utf-8-sig") as stream:
            payload = json.load(stream)
    except OSError as exc:
        raise ScoringConfigError(f"Impossible de lire le profil de pondération : {resolved}") from exc
    except json.JSONDecodeError as exc:
        raise ScoringConfigError(
            f"JSON de pondération invalide dans {resolved.name}, ligne {exc.lineno}, colonne {exc.colno}."
        ) from exc
    if not isinstance(payload, dict):
        raise ScoringConfigError("Le profil de pondération doit être un objet JSON.")
    return payload


def write_json_object(path: str | Path, payload: dict[str, Any]) -> Path:
    resolved = Path(path).expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    with resolved.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return resolved


def deep_merge(base: Any, overrides: Any) -> Any:
    """Return a deep copy of *base* recursively overwritten by *overrides*."""
    if isinstance(base, dict) and isinstance(overrides, dict):
        merged = copy.deepcopy(base)
        for key, value in overrides.items():
            if key in merged:
                merged[key] = deep_merge(merged[key], value)
            else:
                merged[key] = copy.deepcopy(value)
        return merged
    return copy.deepcopy(overrides)


def diff_from_default(default: Any, current: Any) -> Any:
    """Return a minimal recursive override, or the private _MISSING sentinel."""
    if isinstance(default, dict) and isinstance(current, dict):
        result: dict[str, Any] = {}
        for key, current_value in current.items():
            if key not in default:
                result[key] = copy.deepcopy(current_value)
                continue
            child = diff_from_default(default[key], current_value)
            if child is not _MISSING:
                result[key] = child
        return result if result else _MISSING
    if default == current:
        return _MISSING
    return copy.deepcopy(current)


def build_overrides(default: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    diff = diff_from_default(default, current)
    return {} if diff is _MISSING else diff


def iter_leaf_paths(value: Any, prefix: tuple[str, ...] = ()) -> Iterable[tuple[tuple[str, ...], Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield from iter_leaf_paths(child, prefix + (str(key),))
        return
    yield prefix, value


def count_override_leaves(overrides: dict[str, Any]) -> int:
    return sum(1 for _path, _value in iter_leaf_paths(overrides))


def get_path_value(payload: Any, path: tuple[str, ...]) -> Any:
    current = payload
    for key in path:
        if not isinstance(current, dict) or key not in current:
            raise KeyError(".".join(path))
        current = current[key]
    return current


def set_path_value(payload: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    if not path:
        raise ScoringConfigError("La racine du profil ne peut pas être remplacée depuis cet éditeur.")
    current: dict[str, Any] = payload
    for key in path[:-1]:
        child = current.get(key)
        if not isinstance(child, dict):
            child = {}
            current[key] = child
        current = child
    current[path[-1]] = copy.deepcopy(value)


def _require_dict(config: dict[str, Any], path: tuple[str, ...]) -> dict[str, Any]:
    value = get_path_value(config, path)
    if not isinstance(value, dict):
        raise ScoringConfigError(f"{'.'.join(path)} doit être un objet JSON.")
    return value


def _require_numeric_mapping(config: dict[str, Any], path: tuple[str, ...], *, non_empty: bool = True) -> None:
    mapping = _require_dict(config, path)
    if non_empty and not mapping:
        raise ScoringConfigError(f"{'.'.join(path)} ne peut pas être vide.")
    for key, value in mapping.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ScoringConfigError(f"{'.'.join(path + (str(key),))} doit être numérique.")
        if not math.isfinite(float(value)) or float(value) < 0:
            raise ScoringConfigError(f"{'.'.join(path + (str(key),))} doit être un nombre fini positif ou nul.")


def _validate_thresholds(config: dict[str, Any], path: tuple[str, ...]) -> None:
    points = get_path_value(config, path)
    if not isinstance(points, list) or not points:
        raise ScoringConfigError(f"{'.'.join(path)} doit contenir une liste non vide de paliers [entrée, score].")
    previous_x: float | None = None
    for index, pair in enumerate(points):
        if not isinstance(pair, list) or len(pair) != 2:
            raise ScoringConfigError(f"{'.'.join(path)}[{index}] doit être une paire [entrée, score].")
        x, y = pair
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in (x, y)):
            raise ScoringConfigError(f"{'.'.join(path)}[{index}] doit contenir deux nombres.")
        x_value = float(x)
        y_value = float(y)
        if not math.isfinite(x_value) or not math.isfinite(y_value):
            raise ScoringConfigError(f"{'.'.join(path)}[{index}] contient une valeur non finie.")
        if x_value < 0 or y_value < 0:
            raise ScoringConfigError(f"{'.'.join(path)}[{index}] ne peut pas contenir de valeur négative.")
        if previous_x is not None and x_value < previous_x:
            raise ScoringConfigError(f"{'.'.join(path)} doit être trié par entrée croissante.")
        previous_x = x_value


def validate_scoring_config(config: dict[str, Any]) -> None:
    if not isinstance(config, dict):
        raise ScoringConfigError("Le profil de pondération doit être un objet JSON.")

    for path, value in iter_leaf_paths(config):
        if isinstance(value, bool) or value is None or isinstance(value, str):
            continue
        if isinstance(value, (int, float)):
            if not math.isfinite(float(value)):
                raise ScoringConfigError(f"{'.'.join(path)} contient une valeur non finie.")
            if float(value) < 0:
                raise ScoringConfigError(f"{'.'.join(path)} ne peut pas être négatif.")

    required_numeric_mappings = (
        ("mode_weights", "parent_final"),
        ("mode_weights", "future_grandparent"),
        ("blue_star_quality",),
        ("pink_star_quality",),
        ("pink_dimension_weights",),
        ("pink_need_multiplier",),
        ("white_star_quality",),
        ("unique_star_quality",),
        ("position_transmission",),
        ("white_saturation",),
        ("race_saturation",),
        ("race_factor",),
        ("course_conditions", "floors"),
        ("uma_moe_pair", "weights"),
        ("uma_moe_pair", "preselection_weights"),
    )
    for path in required_numeric_mappings:
        _require_numeric_mapping(config, path)

    blue_by_distance = _require_dict(config, ("blue_stat_weights_by_distance",))
    for distance in ("sprint", "mile", "medium", "long"):
        if distance not in blue_by_distance:
            raise ScoringConfigError(f"blue_stat_weights_by_distance.{distance} est requis.")
        _require_numeric_mapping(config, ("blue_stat_weights_by_distance", distance))

    for path in (
        ("blue_star_quality",),
        ("pink_star_quality",),
        ("white_star_quality",),
        ("unique_star_quality",),
    ):
        mapping = _require_dict(config, path)
        missing = [stars for stars in ("1", "2", "3") if stars not in mapping]
        if missing:
            raise ScoringConfigError(f"{'.'.join(path)} doit définir les étoiles {', '.join(missing)}.")

    threshold_paths = (
        ("affinity", "parent_pair_thresholds"),
        ("affinity", "parent_branch_thresholds"),
        ("affinity", "future_branch_base_thresholds"),
        ("affinity", "future_g1_thresholds"),
        ("uma_moe_pair", "final_branch_thresholds"),
        ("uma_moe_pair", "production_affinity_thresholds"),
        ("uma_moe_pair", "candidate_g1_thresholds"),
        ("uma_moe_pair", "final_parent_potential_thresholds"),
        ("uma_moe_pair", "production_run_affinity_thresholds"),
        ("uma_moe_pair", "gp_triple_preselection_thresholds"),
    )
    for path in threshold_paths:
        _validate_thresholds(config, path)

    modes = _require_dict(config, ("course_conditions", "modes"))
    for key, value in modes.items():
        if value not in {"floor", "override"}:
            raise ScoringConfigError(
                f"course_conditions.modes.{key} doit valoir 'floor' ou 'override'."
            )

    positive_paths = (
        ("white_saturation", "future_grandparent"),
        ("white_saturation", "parent_branch"),
        ("white_saturation", "parent_pair"),
        ("race_saturation", "parent_branch"),
        ("race_saturation", "parent_pair"),
        ("white_generation", "saturation"),
    )
    for path in positive_paths:
        value = get_path_value(config, path)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) <= 0:
            raise ScoringConfigError(f"{'.'.join(path)} doit être strictement positif.")


def validate_skill_priorities_config(config: dict[str, Any]) -> None:
    if not isinstance(config, dict):
        raise ScoringConfigError("Le profil de priorités white doit être un objet JSON.")
    default_weight = config.get("default_weight")
    if isinstance(default_weight, bool) or not isinstance(default_weight, (int, float)):
        raise ScoringConfigError("default_weight doit être numérique.")
    if not math.isfinite(float(default_weight)) or float(default_weight) < 0:
        raise ScoringConfigError("default_weight doit être un nombre fini positif ou nul.")
    skills = config.get("skills")
    if not isinstance(skills, dict):
        raise ScoringConfigError("skills doit être un objet JSON indexé par catalog_key.")
    allowed_dimensions = {
        "surface": {"turf", "dirt"},
        "distance": {"sprint", "mile", "medium", "long"},
        "style": {"front_runner", "pace_chaser", "late_surger", "end_closer"},
    }
    for skill_key, skill in skills.items():
        if not isinstance(skill, dict):
            raise ScoringConfigError(f"skills.{skill_key} doit être un objet JSON.")
        base = skill.get("base")
        if isinstance(base, bool) or not isinstance(base, (int, float)):
            raise ScoringConfigError(f"skills.{skill_key}.base doit être numérique.")
        if not math.isfinite(float(base)) or float(base) < 0:
            raise ScoringConfigError(f"skills.{skill_key}.base doit être positif ou nul.")
        for dimension, allowed_keys in allowed_dimensions.items():
            values = skill.get(dimension)
            if values is None:
                continue
            if not isinstance(values, dict):
                raise ScoringConfigError(f"skills.{skill_key}.{dimension} doit être un objet JSON.")
            unknown = sorted(set(values) - allowed_keys)
            if unknown:
                raise ScoringConfigError(
                    f"skills.{skill_key}.{dimension} contient des clés inconnues : {', '.join(unknown)}."
                )
            for key, value in values.items():
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ScoringConfigError(f"skills.{skill_key}.{dimension}.{key} doit être numérique.")
                if not math.isfinite(float(value)) or float(value) < 0:
                    raise ScoringConfigError(
                        f"skills.{skill_key}.{dimension}.{key} doit être positif ou nul."
                    )


def load_effective_scoring_config(
    default_path: str | Path,
    override_path: str | Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    default = read_json_object(default_path)
    overrides: dict[str, Any] = {}
    if override_path is not None:
        resolved_override = Path(override_path).expanduser().resolve()
        if resolved_override.is_file():
            overrides = read_json_object(resolved_override)
    effective = deep_merge(default, overrides)
    validate_scoring_config(effective)
    return default, overrides, effective


def materialize_effective_scoring_config(
    default_path: str | Path,
    override_path: str | Path | None,
    destination: str | Path,
) -> Path:
    _default, _overrides, effective = load_effective_scoring_config(default_path, override_path)
    return write_json_object(destination, effective)
