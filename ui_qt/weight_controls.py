from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any


CATEGORY_SOURCES: tuple[tuple[str, str], ...] = (
    ("all", "Tous"),
    ("global", "Score global"),
    ("aptitudes", "Aptitudes et Pink Sparks"),
    ("blue", "Blue Sparks"),
    ("white", "White Skills et transmission"),
    ("affinity", "Affinité, Uniques et Races"),
    ("course", "Courses et Green Skills"),
    ("online", "uma.moe"),
    ("transfer", "Transfer Helper"),
    ("other", "Autres"),
)
CATEGORY_ORDER = {key: index for index, (key, _source) in enumerate(CATEGORY_SOURCES)}


def weight_subcategory(path: Sequence[str]) -> tuple[str, str, int]:
    """Return a stable key, visible label source, and curated order."""

    path = tuple(path)
    root = path[0] if path else ""
    leaf = path[-1] if path else ""

    if root == "mode_weights":
        groups = {
            "parent_branch": ("global.parent_branch", "Score d’une branche parent", 10),
            "parent_pair": ("global.parent_pair", "Score de la paire finale", 20),
            "future_grandparent": (
                "global.future_grandparent",
                "Score d’un futur grand-parent",
                30,
            ),
        }
        return groups.get(
            path[1] if len(path) > 1 else "",
            ("global.other", "Autres réglages globaux", 90),
        )

    if root == "blue_stat_weights_by_distance":
        distance = path[1] if len(path) > 1 else ""
        labels = {
            "sprint": "Stats prioritaires · Sprint",
            "mile": "Stats prioritaires · Mile",
            "medium": "Stats prioritaires · Medium",
            "long": "Stats prioritaires · Long",
        }
        order = {"sprint": 10, "mile": 20, "medium": 30, "long": 40}
        return (
            f"blue.stats.{distance}",
            labels.get(distance, "Stats prioritaires"),
            order.get(distance, 45),
        )
    if root == "blue_star_quality":
        return ("blue.star_quality", "Qualité des Blue Sparks par étoiles", 50)
    if root == "blue_score_influence_by_distance":
        return ("blue.influence", "Influence des Blues par distance", 60)
    if root == "blue_neutral_score":
        return ("blue.neutral", "Point neutre des Blues", 70)

    if root == "unique_star_quality":
        return ("affinity.unique_quality", "Qualité des Uniques par étoiles", 10)
    if root in {"star_quality", "race_factor"}:
        return ("affinity.race_quality", "Qualité des Race/Scenario Sparks", 20)
    if root == "race_saturation":
        return ("affinity.race_saturation", "Saturation Race/Scenario", 30)
    if root == "affinity" and leaf in {"g1_common_bonus", "same_character_compatibility"}:
        return ("affinity.bonuses", "Bonus et compatibilité d’affinité", 40)
    if root == "affinity" and leaf.endswith("thresholds"):
        return ("affinity.curves", "Courbes d’affinité et G1", 50)
    if root == "affinity":
        return ("affinity.system", "Mode d’affinité", 60)

    if root == "position_transmission":
        return ("white.position", "Transmission selon la génération", 10)
    if root == "white_saturation":
        return ("white.saturation", "Saturation des White Skills", 20)
    if root == "white_generation":
        return ("white.generation", "Génération des White Skills", 30)
    if (
        root == "white_inheritance"
        and "base_proc_rates" in path
        and "race_base_proc_rates" not in path
    ):
        return ("white.direct_proc", "Procs des White Skills", 40)
    if root == "white_inheritance" and "race_base_proc_rates" in path:
        return ("white.race_proc", "Procs des Race Sparks", 50)
    if root == "white_inheritance":
        return ("white.model", "Modèle d’héritage White", 60)

    if root == "course_conditions" and leaf == "active_green_floor":
        return ("course.general", "Valeur générale des Green Skills", 10)
    if root == "course_conditions" and "floors" in path:
        return ("course.floors", "Valeurs par condition de course", 20)
    if root == "course_conditions":
        return ("course.modes", "Application des valeurs de course", 30)

    if root == "uma_moe_pair" and len(path) > 1 and path[1] == "weights":
        return ("online.final_mix", "Répartition de la paire de GP", 10)
    if (
        root == "uma_moe_pair"
        and len(path) > 1
        and path[1] == "preselection_weights"
    ):
        return ("online.preselection_mix", "Répartition de la présélection GP", 20)
    if root == "uma_moe_pair" and "affinity" in leaf:
        return ("online.affinity_curves", "Courbes d’affinité uma.moe", 30)
    if root == "uma_moe_pair" and leaf.endswith("thresholds"):
        return ("online.potential_curves", "Courbes de potentiel uma.moe", 40)
    if root == "uma_moe_pair":
        return ("online.g1", "Hypothèses et potentiel G1", 50)

    if root == "transfer_helper" and (
        leaf.startswith("include_") or leaf == "upcoming_cm_limit"
    ):
        return ("transfer.scope", "Périmètre d’analyse", 10)
    if root == "transfer_helper" and leaf in {
        "competitive_score_floor",
        "competitive_utility_floor",
        "elite_utility_floor",
        "minimum_absolute_floor_ratio",
    }:
        return ("transfer.thresholds", "Seuils de compétitivité", 20)
    if root == "transfer_helper" and leaf in {
        "dominance_tolerance",
        "dominance_mean_margin",
    }:
        return ("transfer.dominance", "Comparaison des remplaçants", 30)
    if root == "transfer_helper" and leaf in {
        "minimum_competitive_contexts",
        "minimum_distinct_profiles",
    }:
        return ("transfer.repetition", "Répétition des rôles compétitifs", 40)
    if root == "transfer_helper":
        return ("transfer.utility_mix", "Répartition de l’utilité", 50)

    if root == "aptitude_inheritance":
        if "pink_base_proc_rates" in path or leaf in {
            "inspiration_event_count",
            "ignore_multi_rank_procs",
        }:
            return ("aptitudes.proc", "Taux de proc des Pink Sparks", 10)
        if "dimension_weights_by_mode" in path:
            mode = path[2] if len(path) > 2 else ""
            if mode == "parent_pair":
                return (
                    "aptitudes.mix.parent_pair",
                    "Répartition des aptitudes · Paire finale",
                    20,
                )
            return (
                "aptitudes.mix.parent_branch",
                "Répartition des aptitudes · Branche parent",
                30,
            )
        if "partial_scoring" in path:
            return ("aptitudes.partial", "Estimation partielle · Branche parent", 40)
        dimension = path[1] if len(path) > 1 else ""
        dimension_labels = {
            "distance": "Distance",
            "surface": "Surface",
            "style": "Style",
        }
        dimension_order = {"distance": 50, "surface": 80, "style": 100}.get(
            dimension, 120
        )
        if "b_compensation" in path:
            return (
                "aptitudes.distance.compensation",
                "Distance · compensation d’un départ B",
                60,
            )
        if leaf == "s_probability_curve":
            name = dimension_labels.get(dimension, "Aptitude")
            return (
                f"aptitudes.{dimension}.curve",
                f"{name} · courbe de P(S)",
                dimension_order + 10,
            )
        name = dimension_labels.get(dimension, "Aptitude")
        return (
            f"aptitudes.{dimension}.score",
            f"{name} · score des départs A/B",
            dimension_order,
        )

    if root == "future_grandparent_heuristics":
        if "pink_dimension_weights" in path:
            return (
                "aptitudes.gp_dimensions",
                "Futur GP · pertinence des aptitudes",
                130,
            )
        if "pink_star_quality" in path:
            return ("aptitudes.gp_pink_quality", "Futur GP · qualité des Pink Sparks", 140)
        if "pink_need_multiplier" in path:
            return ("aptitudes.gp_need", "Futur GP · besoin en Pink Sparks", 150)
        return (
            "aptitudes.gp_white_quality",
            "Futur GP · qualité des White Skills",
            160,
        )

    return ("other", "Autres réglages", 999)


def weight_sort_key(path: Sequence[str]) -> tuple[int, int, tuple[str, ...]]:
    category = weight_category(path)
    _key, _source, subcategory_order = weight_subcategory(path)
    return (
        CATEGORY_ORDER.get(category, 999),
        subcategory_order,
        tuple(str(part) for part in path),
    )


def relative_group_paths(
    config: dict[str, Any], path: Sequence[str]
) -> tuple[tuple[str, ...], ...]:
    """Return sibling paths that are genuinely normalised together by the engine."""

    path = tuple(path)
    root = path[0] if path else ""
    parent = path[:-1]
    direct_group = (
        (root == "mode_weights" and len(path) == 3)
        or (
            root == "aptitude_inheritance"
            and len(path) == 4
            and path[1] == "dimension_weights_by_mode"
        )
        or (
            root == "uma_moe_pair"
            and len(path) == 3
            and path[1] in {"weights", "preselection_weights"}
        )
    )
    if direct_group:
        value: Any = config
        for key in parent:
            if not isinstance(value, dict):
                return ()
            value = value.get(key)
        if not isinstance(value, dict):
            return ()
        return tuple(
            parent + (str(key),)
            for key, item in value.items()
            if isinstance(item, (int, float)) and not isinstance(item, bool)
        )

    if root == "aptitude_inheritance" and parent == (
        "aptitude_inheritance",
        "partial_scoring",
        "parent_branch",
    ) and path[-1] in {"star_weight", "proc_weight"}:
        return tuple(parent + (key,) for key in ("star_weight", "proc_weight"))

    if root == "transfer_helper" and path[-1] in {
        "utility_absolute_weight",
        "utility_leader_weight",
        "utility_percentile_weight",
    }:
        return tuple(
            ("transfer_helper", key)
            for key in (
                "utility_absolute_weight",
                "utility_leader_weight",
                "utility_percentile_weight",
            )
        )
    return ()


def value_at_path(config: dict[str, Any], path: Sequence[str]) -> Any:
    value: Any = config
    for key in path:
        value = value[str(key)]
    return value


def relative_group_shares(
    config: dict[str, Any], path: Sequence[str]
) -> tuple[tuple[tuple[str, ...], float], ...]:
    paths = relative_group_paths(config, path)
    values = [max(0.0, float(value_at_path(config, item))) for item in paths]
    total = sum(values)
    if not paths:
        return ()
    if total <= 0:
        return tuple((item, 0.0) for item in paths)
    return tuple((item, value / total) for item, value in zip(paths, values))


def redistribute_relative_group(
    config: dict[str, Any], path: Sequence[str], selected_share: float
) -> tuple[tuple[tuple[str, ...], float], ...]:
    """Redistribute the remainder proportionally and return a canonical 100% group."""

    shares = relative_group_shares(config, path)
    selected_path = tuple(path)
    selected_share = max(0.0, min(1.0, float(selected_share)))
    if not any(share > 0 for _item, share in shares) and selected_share <= 0:
        return shares
    others = [(item, share) for item, share in shares if item != selected_path]
    other_total = sum(share for _item, share in others)
    remainder = 1.0 - selected_share
    if others and other_total <= 0:
        other_values = {item: remainder / len(others) for item, _share in others}
    else:
        other_values = {
            item: remainder * share / other_total for item, share in others
        }
    return tuple(
        (item, selected_share if item == selected_path else other_values.get(item, 0.0))
        for item, _share in shares
    )


def weight_category(path: Sequence[str]) -> str:
    """Return the human-facing category for a scoring leaf path."""

    if not path:
        return "other"
    root = path[0]
    if root == "mode_weights":
        return "global"
    if root in {"aptitude_inheritance", "future_grandparent_heuristics"}:
        return "aptitudes"
    if root in {
        "blue_stat_weights_by_distance",
        "blue_star_quality",
        "blue_score_influence_by_distance",
        "blue_neutral_score",
    }:
        return "blue"
    if root in {
        "white_inheritance",
        "white_saturation",
        "white_generation",
        "position_transmission",
    }:
        return "white"
    if root in {
        "affinity",
        "unique_star_quality",
        "star_quality",
        "race_saturation",
        "race_factor",
    }:
        return "affinity"
    if root == "course_conditions":
        return "course"
    if root == "uma_moe_pair":
        return "online"
    if root == "transfer_helper":
        return "transfer"
    return "other"


def is_percentage_setting(path: Sequence[str], value: object) -> bool:
    """Identify scalar factors that should use the shared slider control."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    # Integer score contributions (for example 30 points for P(S)) are not
    # probabilities, even when their historical key contains "weight".
    if isinstance(value, int):
        return False
    if not path:
        return False

    root = path[0]
    leaf = path[-1]
    if root in {
        "mode_weights",
        "blue_stat_weights_by_distance",
        "blue_star_quality",
        "unique_star_quality",
        "position_transmission",
        "star_quality",
        "blue_score_influence_by_distance",
        "race_factor",
    }:
        return True
    if root == "course_conditions":
        return leaf == "active_green_floor" or "floors" in path
    if root == "white_generation":
        return leaf in {"bonus_per_lineage_copy", "saturation"}
    if root == "uma_moe_pair":
        return len(path) > 1 and (
            path[1] in {"weights", "preselection_weights"}
            or leaf == "single_g1_weight_default"
        )
    if root == "transfer_helper":
        return leaf in {
            "competitive_utility_floor",
            "elite_utility_floor",
            "minimum_absolute_floor_ratio",
            "utility_absolute_weight",
            "utility_leader_weight",
            "utility_percentile_weight",
        }
    if root == "aptitude_inheritance":
        return (
            "pink_base_proc_rates" in path
            or "dimension_weights_by_mode" in path
            or leaf
            in {
                "full_proc_probability",
                "star_weight",
                "proc_weight",
                "minimum_probability_a",
                "minimum_probability_s",
            }
        )
    if root == "white_inheritance":
        return (
            "base_proc_rates" in path
            or "race_base_proc_rates" in path
            or leaf == "per_event_probability_cap"
        )
    if root == "future_grandparent_heuristics":
        return len(path) > 1 and path[1] in {
            "pink_dimension_weights",
            "pink_star_quality",
            "pink_need_multiplier",
            "white_star_quality",
        }
    return False


def is_probability_setting(path: Sequence[str]) -> bool:
    """Return whether a displayed percentage has a strict 100% ceiling."""

    if not path:
        return False
    root = path[0]
    leaf = path[-1]
    if "probability" in leaf or any("proc_rate" in segment for segment in path):
        return True
    if root == "transfer_helper" and leaf in {
        "competitive_utility_floor",
        "elite_utility_floor",
        "minimum_absolute_floor_ratio",
    }:
        return True
    if root == "course_conditions" and (
        leaf == "active_green_floor" or "floors" in path
    ):
        return True
    return False


def is_threshold_percentage(path: Sequence[str]) -> bool:
    """Return whether a bounded 0–100% scalar is a threshold, not a probability."""

    if not path:
        return False
    root = path[0]
    leaf = path[-1]
    if root == "course_conditions" and (
        leaf == "active_green_floor" or "floors" in path
    ):
        return True
    return root == "transfer_helper" and leaf in {
        "competitive_utility_floor",
        "elite_utility_floor",
        "minimum_absolute_floor_ratio",
    }


def percentage_limit(path: Sequence[str], *values: object) -> float:
    """Choose a useful slider ceiling while preserving imported values."""

    maximum_value = max(
        (
            float(value)
            for value in values
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        ),
        default=1.0,
    )
    maximum_percent = max(0.0, maximum_value * 100.0)
    if is_probability_setting(path) and maximum_percent <= 100.0:
        return 100.0
    # Start with a readable 0–100% scale. Relative factors may exceed 100%; an
    # imported outlier expands the scale to the next full 100% interval.
    return max(100.0, math.ceil(maximum_percent / 100.0) * 100.0)


def percentage_display(value: object) -> str:
    number = float(value) * 100.0
    rendered = f"{number:.4f}".rstrip("0").rstrip(".")
    return f"{rendered} %"
