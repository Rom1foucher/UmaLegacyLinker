"""Reconstruct an exact same-target comparison from a frozen transfer report.

Scores are stored as compact vectors. Detailed factors are hydrated only for
the two veterans the user is comparing, using the report's original model.
No MDB, current overrides, network access or current collection is required.
"""
from __future__ import annotations

from typing import Any

from uma_legacy_linker.parent_optimizer import (
    _affinity_score, _blue_score, _factor_list, _future_grandparent_pink_score,
    _future_grandparent_white_score, _lineage_members, _member_g1, _mode_weights,
    _pink_score, _race_scenario_score, _unique_score, _weighted_total,
    _white_generation_support_score, _white_score,
)


def frozen_veteran(veteran: dict[str, Any]) -> dict[str, Any]:
    def member(source: dict[str, Any]) -> dict[str, Any]:
        return {
            key: source.get(key) for key in
            ("trained_chara_id", "local_trained_chara_id", "card_id", "chara_id", "uma_name", "card_name", "rank_score", "rank")
        } | {
            "factors": {"by_type": {
                kind: [{key: factor.get(key) for key in
                        ("name", "stars", "factor_group_id", "factor_id", "type", "effects", "skill_id")}
                       for factor in factors]
                for kind, factors in ((source.get("factors") or {}).get("by_type") or {}).items()
            }},
            "g1_wins": {"names": sorted(_member_g1(source))},
        }
    result = member(veteran)
    lineage = veteran.get("when_used_as_parent") or {}
    result["when_used_as_parent"] = {
        key: member(lineage[key]) for key in ("grandparent_1", "grandparent_2") if lineage.get(key)
    }
    return result


def comparison_evaluation(
    record: dict[str, Any], model: dict[str, Any], context_key: str,
    ace_index: int, role: str,
) -> dict[str, Any]:
    context = model["contexts"][context_key]
    ace = context["aces"][ace_index]
    veteran = record["comparison_veteran"]
    config = model["config"]
    race_skills = model["race_skills"]
    weights = context["skill_weights"]
    lookup = lambda key: float(weights.get(key, 0.0))
    members = _lineage_members(veteran) if role == "parent" else [(veteran, "grandparent", "candidate")]
    components: dict[str, float] = {}
    details: dict[str, Any] = {}
    components["blue"], details["blue"] = _blue_score(members, context["distance"], config)
    mode = "parent_branch" if role == "parent" else "future_grandparent"
    components["unique"], details["unique"] = _unique_score(members, config, mode)
    if role == "parent":
        if int(veteran.get("chara_id") or 0) == int(ace.get("chara_id") or 0):
            return {"score": None, "components": {}, "details": {}, "ace": ace}
        values = record["comparison_affinities"][str(ace["chara_id"])]
        affinities = dict(zip(("parent", "grandparent_1", "grandparent_2"), values[:3]))
        components["white_skill"], details["white"] = _white_score(
            members, lookup, config, mode, inheritance_affinities=affinities,
            race_skill_map=race_skills, detail_limit=None,
        )
        components["pink"], details["pink"] = _pink_score(
            members, ace, context["surface"], context["distance"], context["style"],
            config, mode=mode, inheritance_affinities=affinities,
        )
        for key in ("distance_s", "surface_aptitude", "pink_other"):
            components[key] = float(details["pink"][key]["score"])
        components["race_scenario"], details["race_scenario"] = _race_scenario_score(
            members, lookup, race_skills, config, mode,
        )
        affinity_cfg = config.get("affinity") or {}
        components["affinity"] = _affinity_score(
            float(values[3]), affinity_cfg.get("parent_branch_thresholds") or [[0, 0], [95, 100]],
        )
    else:
        components["pink"], details["pink"] = _future_grandparent_pink_score(
            members, ace, context["surface"], context["distance"], context["style"], config,
        )
        components["white_skill"], details["white"] = _future_grandparent_white_score(
            members, lookup, config, race_skills, detail_limit=None,
        )
        components["white_generation"], details["white_generation"] = _white_generation_support_score(
            _lineage_members(veteran), lookup, config,
        )
        affinity_cfg = config.get("affinity") or {}
        components["g1_potential"] = _affinity_score(
            len(_member_g1(veteran)), affinity_cfg.get("future_g1_thresholds") or [[0, 0], [20, 100]],
        )
        components["affinity"] = 100.0
    mode_weights = _mode_weights(config, mode)
    denominator = sum(max(0.0, float(v)) for v in mode_weights.values()) or 1.0
    return {
        "score": _weighted_total(components, mode_weights), "components": components,
        "contributions": {key: components.get(key, 0.0) * max(0.0, float(weight)) / denominator
                          for key, weight in mode_weights.items()},
        "weights": mode_weights, "details": details, "ace": ace,
    }


def factor_inventory(record: dict[str, Any], role: str) -> dict[tuple[str, str], dict[str, Any]]:
    veteran = record.get("comparison_veteran") or {}
    members = _lineage_members(veteran) if role == "parent" else [(veteran, "grandparent", "candidate")]
    inventory: dict[tuple[str, str], dict[str, Any]] = {}
    for source, _position, carrier in members:
        for kind in ("blue_stat", "red_aptitude", "white_skill", "white_race", "scenario", "unique"):
            for factor in _factor_list(source, kind):
                # Stable MDB group identity prevents same-label factors merging.
                identity = factor_identity(kind, factor)
                entry = inventory.setdefault((kind, identity), {
                    "type": kind, "name": factor.get("name") or identity,
                    "stars": 0, "carriers": [], "direct_stars": 0,
                })
                stars = int(factor.get("stars") or 0)
                entry["stars"] += stars
                entry["carriers"].append((carrier, stars))
                if source is veteran:
                    entry["direct_stars"] += stars
    return inventory


def factor_identity(kind: str, factor: dict[str, Any]) -> str:
    """Use the displayed stat name for blue totals across mixed group IDs."""
    name = str(factor.get("name") or "").strip()
    if kind == "blue_stat" and name:
        return name.casefold()
    return str(factor.get("factor_group_id") or name)


def white_inventory(evaluation: dict[str, Any]) -> dict[str, dict[str, Any]]:
    detail = (evaluation.get("details") or {}).get("white") or {}
    if detail.get("top_skills") is not None:
        return {str(item["catalog_key"]): item for item in detail["top_skills"]}
    result: dict[str, dict[str, Any]] = {}
    for factor in detail.get("top_factors") or []:
        key = str(factor.get("catalog_key") or "")
        entry = result.setdefault(key, {"name": factor.get("name") or key,
                                       "contribution": 0.0, "carrier_count": 0})
        entry["contribution"] += float(factor.get("contribution") or 0.0)
        entry["carrier_count"] += 1
    return result
