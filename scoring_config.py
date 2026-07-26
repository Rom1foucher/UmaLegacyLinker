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


def migrate_scoring_overrides(
    default: dict[str, Any], overrides: dict[str, Any]
) -> dict[str, Any]:
    """Translate legacy shared parent weights and drop obsolete parent heuristics.

    Old profiles stored ``mode_weights.parent_final`` and exposed fixed star/position
    heuristics for pink Sparks. Parent weights are preserved; obsolete parent pink
    internals are removed so the probability-aware aptitude model cannot be mixed
    with the simple future-grandparent model.
    """
    migrated = copy.deepcopy(overrides)
    try:
        source_schema = int(migrated.get("schema_version") or 0)
    except (TypeError, ValueError):
        source_schema = 0
    if migrated and "schema_version" in default:
        migrated["schema_version"] = copy.deepcopy(default["schema_version"])
    for obsolete_key in ("pink_star_quality", "pink_dimension_weights", "pink_need_multiplier", "distance_s", "white_star_quality"):
        if obsolete_key not in default:
            migrated.pop(obsolete_key, None)
    override_modes = migrated.get("mode_weights")
    if isinstance(override_modes, dict):
        if source_schema < 17:
            # Before V17, target surface and running style shared pink_other.
            # Split an explicit legacy override according to the new defaults so
            # upgrading cannot silently add surface weight or change the user's
            # total pink allocation.
            default_modes = default.get("mode_weights") or {}
            for mode in ("parent_branch", "parent_pair"):
                mode_overrides = override_modes.get(mode)
                if not isinstance(mode_overrides, dict):
                    continue
                if "surface_aptitude" in mode_overrides or "pink_other" not in mode_overrides:
                    continue
                legacy_other = float(mode_overrides.get("pink_other") or 0.0)
                default_mode = default_modes.get(mode) or {}
                surface_default = max(0.0, float(default_mode.get("surface_aptitude") or 0.0))
                other_default = max(0.0, float(default_mode.get("pink_other") or 0.0))
                split_total = surface_default + other_default
                if split_total > 0:
                    mode_overrides["surface_aptitude"] = legacy_other * surface_default / split_total
                    mode_overrides["pink_other"] = legacy_other * other_default / split_total
        future_mode = override_modes.get("future_grandparent")
        if isinstance(future_mode, dict):
            # V31–V35 temporarily split future-GP pinks into the parent-specific
            # probability components. Preserve the user's total pink allocation
            # while restoring the simple GP component schema.
            if "pink" not in future_mode and (
                "distance_s" in future_mode or "pink_other" in future_mode
            ):
                future_mode["pink"] = float(future_mode.get("distance_s", 0.0)) + float(
                    future_mode.get("pink_other", 0.0)
                )
            future_mode.pop("distance_s", None)
            future_mode.pop("pink_other", None)

    online_pair_overrides = migrated.get("uma_moe_pair")
    if isinstance(online_pair_overrides, dict):
        # V36–V39 exposed a second independent set of weights for uma.moe GP
        # pairs. Consolidate it into the canonical future-grandparent mode so
        # local ranking, online ranking and Transfer Helper cannot diverge.
        legacy_online_weights = online_pair_overrides.get("weights")
        if isinstance(legacy_online_weights, dict):
            if not isinstance(override_modes, dict):
                override_modes = {}
                migrated["mode_weights"] = override_modes
            future_mode = override_modes.get("future_grandparent")
            if not isinstance(future_mode, dict):
                future_mode = {}
                override_modes["future_grandparent"] = future_mode
            if not future_mode:
                legacy_mapping = {
                    "final_parent_affinity": "affinity",
                    "production_run_affinity": "g1_potential",
                    "blue": "blue",
                    "pink": "pink",
                    "white_skill": "white_skill",
                    "white_generation": "white_generation",
                    "unique": "unique",
                }
                for old_key, new_key in legacy_mapping.items():
                    if old_key in legacy_online_weights:
                        future_mode[new_key] = copy.deepcopy(
                            legacy_online_weights[old_key]
                        )
        online_pair_overrides.pop("weights", None)
        online_pair_overrides.pop("preselection_weights", None)
        for obsolete_key in (
            "production_affinity_thresholds",
            "planned_g1_budget_default",
            "final_parent_potential_thresholds",
            "single_g1_weight_default",
        ):
            online_pair_overrides.pop(obsolete_key, None)

    race_factor_overrides = migrated.get("race_factor")
    if isinstance(race_factor_overrides, dict):
        # Granted Race-Spark skills now use their actual 1/2/3% inheritance
        # rates inside the white-skill component; the former arbitrary
        # multiplier would otherwise remain visible but have no effect.
        race_factor_overrides.pop("granted_skill_multiplier", None)

    aptitude_overrides = migrated.get("aptitude_inheritance")
    if isinstance(aptitude_overrides, dict):
        dimensions = aptitude_overrides.get("dimension_weights_by_mode")
        if isinstance(dimensions, dict):
            dimensions.pop("future_grandparent", None)
        partial = aptitude_overrides.get("partial_scoring")
        if isinstance(partial, dict):
            partial.pop("future_grandparent", None)

    if not isinstance(override_modes, dict):
        return migrated
    legacy = override_modes.get("parent_final")
    if not isinstance(legacy, dict):
        return migrated

    default_modes = default.get("mode_weights") or {}
    for target_mode in ("parent_branch", "parent_pair"):
        if target_mode in override_modes:
            continue
        baseline = default_modes.get(target_mode) or {}
        mapped: dict[str, Any] = {}
        for key, value in legacy.items():
            if key == "pink":
                continue
            if key in baseline:
                mapped[key] = copy.deepcopy(value)
        if "pink" in legacy:
            pink_total = float(legacy["pink"])
            distance_default = float(baseline.get("distance_s", 0.0))
            surface_default = float(baseline.get("surface_aptitude", 0.0))
            other_default = float(baseline.get("pink_other", 0.0))
            default_total = distance_default + surface_default + other_default
            if default_total > 0:
                mapped["distance_s"] = pink_total * distance_default / default_total
                mapped["surface_aptitude"] = pink_total * surface_default / default_total
                mapped["pink_other"] = pink_total * other_default / default_total
        override_modes[target_mode] = mapped
    override_modes.pop("parent_final", None)
    return migrated


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
    if diff is _MISSING:
        return {}
    if "schema_version" in default:
        diff["schema_version"] = copy.deepcopy(default["schema_version"])
    return diff


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
        ("mode_weights", "parent_branch"),
        ("mode_weights", "parent_pair"),
        ("mode_weights", "future_grandparent"),
        ("blue_star_quality",),
        ("blue_score_influence_by_distance",),
        ("aptitude_inheritance", "pink_base_proc_rates"),
        ("aptitude_inheritance", "dimension_weights_by_mode", "parent_branch"),
        ("aptitude_inheritance", "dimension_weights_by_mode", "parent_pair"),
        ("aptitude_inheritance", "partial_scoring", "parent_branch"),
        ("aptitude_inheritance", "distance", "below_b"),
        ("aptitude_inheritance", "distance", "b_compensation"),
        ("aptitude_inheritance", "surface", "below_b"),
        ("aptitude_inheritance", "style", "below_b"),
        ("uma_moe_parent_search", "preselection"),
        ("future_grandparent_heuristics", "pink_dimension_weights"),
        ("future_grandparent_heuristics", "pink_star_quality"),
        ("future_grandparent_heuristics", "pink_need_multiplier"),
        ("future_grandparent_heuristics", "white_star_quality"),
        ("white_inheritance", "base_proc_rates"),
        ("white_inheritance", "race_base_proc_rates"),
        ("unique_star_quality",),
        ("position_transmission",),
        ("white_saturation",),
        ("race_saturation",),
        ("race_factor",),
        ("course_conditions", "floors"),
    )
    for path in required_numeric_mappings:
        _require_numeric_mapping(config, path)

    required_mode_keys = {
        "parent_branch": {
            "distance_s", "surface_aptitude", "pink_other", "white_skill", "race_scenario", "blue", "unique"
        },
        "parent_pair": {
            "distance_s", "surface_aptitude", "pink_other", "white_skill", "race_scenario", "blue", "unique"
        },
        "future_grandparent": {
            "affinity", "g1_potential", "blue", "pink", "white_skill", "white_generation", "unique"
        },
    }
    mode_weights = _require_dict(config, ("mode_weights",))
    for mode, expected_keys in required_mode_keys.items():
        weights = _require_dict(config, ("mode_weights", mode))
        missing = sorted(expected_keys - set(weights))
        unknown = sorted(set(weights) - expected_keys)
        if missing:
            raise ScoringConfigError(
                f"mode_weights.{mode} doit définir : {', '.join(missing)}."
            )
        if unknown:
            raise ScoringConfigError(
                f"mode_weights.{mode} contient des composantes inconnues : {', '.join(unknown)}."
            )
        if sum(float(value) for value in weights.values()) <= 0:
            raise ScoringConfigError(
                f"mode_weights.{mode} doit contenir au moins un poids strictement positif."
            )

    blue_by_distance = _require_dict(config, ("blue_stat_weights_by_distance",))
    blue_influence = _require_dict(config, ("blue_score_influence_by_distance",))
    for distance in ("sprint", "mile", "medium", "long"):
        if distance not in blue_by_distance:
            raise ScoringConfigError(f"blue_stat_weights_by_distance.{distance} est requis.")
        _require_numeric_mapping(config, ("blue_stat_weights_by_distance", distance))
        if distance not in blue_influence:
            raise ScoringConfigError(f"blue_score_influence_by_distance.{distance} est requis.")

    for path in (
        ("blue_star_quality",),
        ("aptitude_inheritance", "pink_base_proc_rates"),
        ("white_inheritance", "base_proc_rates"),
        ("white_inheritance", "race_base_proc_rates"),
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
        ("uma_moe_pair", "candidate_g1_thresholds"),
        ("uma_moe_pair", "production_run_affinity_thresholds"),
        ("uma_moe_pair", "gp_triple_preselection_thresholds"),
        ("aptitude_inheritance", "distance", "s_probability_curve"),
        ("aptitude_inheritance", "surface", "s_probability_curve"),
        ("aptitude_inheritance", "style", "s_probability_curve"),
        ("white_inheritance", "distinct_skill_probability_curve"),
    )
    for path in threshold_paths:
        _validate_thresholds(config, path)

    aptitude = _require_dict(config, ("aptitude_inheritance",))
    event_count = aptitude.get("inspiration_event_count")
    if isinstance(event_count, bool) or not isinstance(event_count, int) or event_count < 1:
        raise ScoringConfigError("aptitude_inheritance.inspiration_event_count doit être un entier strictement positif.")

    white_inheritance = _require_dict(config, ("white_inheritance",))
    white_event_count = white_inheritance.get("inspiration_event_count")
    if isinstance(white_event_count, bool) or not isinstance(white_event_count, int) or white_event_count < 1:
        raise ScoringConfigError("white_inheritance.inspiration_event_count doit être un entier strictement positif.")
    white_cap = white_inheritance.get("per_event_probability_cap", 1.0)
    if isinstance(white_cap, bool) or not isinstance(white_cap, (int, float)) or not 0 < float(white_cap) <= 1:
        raise ScoringConfigError("white_inheritance.per_event_probability_cap doit être compris entre 0 (exclu) et 1.")
    for index, (probability, utility) in enumerate(white_inheritance["distinct_skill_probability_curve"]):
        if float(probability) > 1:
            raise ScoringConfigError(
                f"white_inheritance.distinct_skill_probability_curve[{index}][0] ne peut pas dépasser 1."
            )
        if float(utility) > 1:
            raise ScoringConfigError(
                f"white_inheritance.distinct_skill_probability_curve[{index}][1] ne peut pas dépasser 1."
            )
    for mode in ("parent_branch", "parent_pair"):
        weights = _require_dict(config, ("aptitude_inheritance", "dimension_weights_by_mode", mode))
        missing = [key for key in ("distance", "surface", "style") if key not in weights]
        if missing:
            raise ScoringConfigError(
                f"aptitude_inheritance.dimension_weights_by_mode.{mode} doit définir : {', '.join(missing)}."
            )
    gp_dimensions = _require_dict(
        config, ("future_grandparent_heuristics", "pink_dimension_weights")
    )
    missing_gp_dimensions = [
        key for key in ("distance", "surface", "style") if key not in gp_dimensions
    ]
    if missing_gp_dimensions:
        raise ScoringConfigError(
            "future_grandparent_heuristics.pink_dimension_weights doit définir : "
            + ", ".join(missing_gp_dimensions)
        )
    for dimension in ("distance", "surface", "style"):
        section = _require_dict(config, ("aptitude_inheritance", dimension))
        for key in (
            "start_a_base_score", "start_a_s_probability_weight",
            "start_b_base_score", "start_b_a_probability_weight", "start_b_s_probability_weight",
        ):
            if key not in section:
                raise ScoringConfigError(f"aptitude_inheritance.{dimension}.{key} est requis.")
        for index, (probability, quality) in enumerate(section["s_probability_curve"]):
            if float(probability) > 1:
                raise ScoringConfigError(
                    f"aptitude_inheritance.{dimension}.s_probability_curve[{index}][0] ne peut pas dépasser 1."
                )
            if float(quality) > 100:
                raise ScoringConfigError(
                    f"aptitude_inheritance.{dimension}.s_probability_curve[{index}][1] ne peut pas dépasser 100."
                )
    surface_section = _require_dict(config, ("aptitude_inheritance", "surface"))
    surface_rank_policy: dict[str, int] = {}
    for key in ("minimum_initial_rank", "preferred_initial_rank"):
        value = surface_section.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 7:
            raise ScoringConfigError(
                f"aptitude_inheritance.surface.{key} doit être un rang entier compris entre 1 (G) et 7 (A)."
            )
        surface_rank_policy[key] = value
    if surface_rank_policy["minimum_initial_rank"] > surface_rank_policy["preferred_initial_rank"]:
        raise ScoringConfigError(
            "aptitude_inheritance.surface.minimum_initial_rank ne peut pas dépasser preferred_initial_rank."
        )
    for key in ("minimum_probability_a", "minimum_probability_s"):
        value = get_path_value(config, ("aptitude_inheritance", "distance", "b_compensation", key))
        if float(value) > 1:
            raise ScoringConfigError(
                f"aptitude_inheritance.distance.b_compensation.{key} ne peut pas dépasser 1."
            )

    _require_dict(config, ("uma_moe_parent_search",))
    retrieval = _require_dict(config, ("uma_moe_parent_search", "retrieval"))
    for key in ("enabled", "surface_cohort_enabled"):
        if not isinstance(retrieval.get(key), bool):
            raise ScoringConfigError(
                f"uma_moe_parent_search.retrieval.{key} doit valoir true ou false."
            )
    for key, value in retrieval.items():
        if key in {"enabled", "surface_cohort_enabled"}:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ScoringConfigError(
                f"uma_moe_parent_search.retrieval.{key} doit être numérique."
            )
    for section_name in ("retrieval", "preselection"):
        section = _require_dict(config, ("uma_moe_parent_search", section_name))
        for key, value in section.items():
            if key in {
                "enabled",
                "surface_cohort_enabled",
                "balanced_branch_divisor",
                "contextual_distance_star_target",
            }:
                continue
            if float(value) > 1:
                raise ScoringConfigError(
                    f"uma_moe_parent_search.{section_name}.{key} ne peut pas dépasser 1."
                )
    divisor = retrieval.get("balanced_branch_divisor")
    if (
        isinstance(divisor, bool)
        or not isinstance(divisor, (int, float))
        or float(divisor) <= 0
    ):
        raise ScoringConfigError(
            "uma_moe_parent_search.retrieval.balanced_branch_divisor doit être strictement positif."
        )
    contextual_distance_target = retrieval.get("contextual_distance_star_target", 6)
    if (
        isinstance(contextual_distance_target, bool)
        or not isinstance(contextual_distance_target, int)
        or not 1 <= contextual_distance_target <= 18
    ):
        raise ScoringConfigError(
            "uma_moe_parent_search.retrieval.contextual_distance_star_target "
            "doit être un entier compris entre 1 et 18."
        )
    contextual_opponent = _require_dict(
        config, ("uma_moe_pair", "contextual_opponent")
    )
    for key, value in contextual_opponent.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ScoringConfigError(
                f"uma_moe_pair.contextual_opponent.{key} doit être numérique."
            )
        if float(value) > 1:
            raise ScoringConfigError(
                f"uma_moe_pair.contextual_opponent.{key} ne peut pas dépasser 1."
            )

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

    transfer = _require_dict(config, ("transfer_helper",))
    for key in (
        "competitive_score_floor",
        "competitive_utility_floor",
        "elite_utility_floor",
        "minimum_absolute_floor_ratio",
        "utility_absolute_weight",
        "utility_leader_weight",
        "utility_percentile_weight",
        "dominance_tolerance",
        "dominance_mean_margin",
    ):
        value = transfer.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ScoringConfigError(f"transfer_helper.{key} doit être numérique.")
        if not math.isfinite(float(value)) or float(value) < 0:
            raise ScoringConfigError(
                f"transfer_helper.{key} doit être un nombre fini positif ou nul."
            )
    for key in ("competitive_utility_floor", "elite_utility_floor", "minimum_absolute_floor_ratio", "utility_absolute_weight", "utility_leader_weight", "utility_percentile_weight"):
        if float(transfer[key]) > 1:
            raise ScoringConfigError(f"transfer_helper.{key} ne peut pas dépasser 1.")
    if float(transfer["elite_utility_floor"]) < float(transfer["competitive_utility_floor"]):
        raise ScoringConfigError("transfer_helper.elite_utility_floor doit être supérieur ou égal au seuil compétitif.")
    if sum(float(transfer[key]) for key in ("utility_absolute_weight", "utility_leader_weight", "utility_percentile_weight")) <= 0:
        raise ScoringConfigError("Les poids d'utilité du Transfer Helper ne peuvent pas tous être nuls.")
    for key in ("minimum_competitive_contexts", "minimum_distinct_profiles"):
        value = transfer.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ScoringConfigError(
                f"transfer_helper.{key} doit être un entier strictement positif."
            )
    for key in (
        "include_course_presets",
        "include_team_trials",
        "include_generic_profiles",
    ):
        if not isinstance(transfer.get(key), bool):
            raise ScoringConfigError(
                f"transfer_helper.{key} doit valoir true ou false."
            )
    upcoming_cm_limit = transfer.get("upcoming_cm_limit")
    if (
        isinstance(upcoming_cm_limit, bool)
        or not isinstance(upcoming_cm_limit, int)
        or upcoming_cm_limit < 0
    ):
        raise ScoringConfigError(
            "transfer_helper.upcoming_cm_limit doit être un entier positif ou nul."
        )


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
    overrides = migrate_scoring_overrides(default, overrides)
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
