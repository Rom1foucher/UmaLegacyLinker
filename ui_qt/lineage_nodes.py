from __future__ import annotations

from typing import Any


SCORING_LINEAGE_POSITIONS = (
    "target",
    "p1",
    "p2",
    "p1-1",
    "p1-2",
    "p2-1",
    "p2-2",
)

GREAT_GRANDPARENT_POSITIONS = (
    "p1-1-1",
    "p1-1-2",
    "p1-2-1",
    "p1-2-2",
    "p2-1-1",
    "p2-1-2",
    "p2-2-1",
    "p2-2-2",
)

VISIBLE_LINEAGE_POSITIONS = SCORING_LINEAGE_POSITIONS + GREAT_GRANDPARENT_POSITIONS

PAIR_POSITION_TO_ROLE = {
    "p1": "parent_1",
    "p2": "parent_2",
    "p1-1": "parent_1_grandparent_1",
    "p1-2": "parent_1_grandparent_2",
    "p2-1": "parent_2_grandparent_1",
    "p2-2": "parent_2_grandparent_2",
}

BRANCH_POSITION_TO_ROLE = {
    "p1": "parent",
    "p1-1": "grandparent_1",
    "p1-2": "grandparent_2",
}

FUTURE_GRANDPARENT_POSITION_TO_ROLE = {
    "p1": "candidate",
}

GRANDPARENT_PAIR_POSITION_TO_ROLE = {
    "p1": "local_gp1",
    "p2": "online_gp2",
}

FACTOR_DISPLAY_GROUP = {
    "blue_stat": 0,
    "red_aptitude": 1,
    "unique": 2,
}

WHITE_DISPLAY_ORDER = {
    "scenario": 0,
    "white_race": 1,
    "white_skill": 2,
    "event": 3,
    "other": 4,
}


def _integer(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _sparks(member: dict[str, Any]) -> list[dict[str, Any]]:
    raw = member.get("sparks")
    if not isinstance(raw, list):
        raw = list((member.get("factors") or {}).get("all") or [])
    result: list[dict[str, Any]] = []
    for factor in raw:
        if not isinstance(factor, dict):
            continue
        result.append(
            {
                "factor_id": _integer(factor.get("factor_id")),
                "factor_group_id": _integer(factor.get("factor_group_id")),
                "skill_id": _integer(factor.get("skill_id")),
                "name": str(factor.get("name") or ""),
                "stars": max(0, _integer(factor.get("stars")) or 0),
                "type": str(factor.get("type") or "other"),
            }
        )
    return sorted(result, key=_spark_display_key)


def _spark_display_key(factor: dict[str, Any]) -> tuple[int, int, int, int, str]:
    factor_type = str(factor.get("type") or "other")
    group = FACTOR_DISPLAY_GROUP.get(factor_type, 3)
    white_order = WHITE_DISPLAY_ORDER.get(factor_type, 5) if group == 3 else 0
    priority_rank = _integer(factor.get("score_priority_rank")) or 999
    return (
        group,
        white_order,
        priority_rank if factor_type in {"white_skill", "white_race"} else 999,
        -max(0, _integer(factor.get("stars")) or 0),
        str(factor.get("name") or "").casefold(),
    )


def _node(member: object) -> dict[str, Any] | None:
    if isinstance(member, str):
        name = member.strip()
        return {"card_name": name, "uma_name": name, "sparks": []} if name else None
    if not isinstance(member, dict):
        return None
    card_name = str(member.get("card_name") or member.get("uma_name") or "").strip()
    uma_name = str(member.get("uma_name") or card_name).strip()
    if not card_name and not uma_name and not member.get("card_id"):
        return None
    result = {
        "trained_chara_id": member.get("trained_chara_id"),
        "card_id": _integer(member.get("card_id")),
        "chara_id": _integer(member.get("chara_id")),
        "uma_name": uma_name,
        "card_name": card_name or uma_name,
        "rank": member.get("rank"),
        "rank_score": member.get("rank_score"),
        "sparks": _sparks(member),
        "g1_count": _integer(member.get("g1_count"))
        or len((member.get("g1_wins") or {}).get("names") or []),
    }
    return result


def _direct_parents(row: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    left = row.get("parent_1") or row.get("fixed_parent") or {}
    right = row.get("parent_2") or row.get("candidate") or {}
    return (
        left if isinstance(left, dict) else {},
        right if isinstance(right, dict) else {},
    )


def _preview(row: dict[str, Any]) -> dict[str, Any]:
    preview = row.get("lineage_preview") or {}
    return preview if isinstance(preview, dict) else {}


def _attach_branch(
    nodes: dict[str, dict[str, Any]],
    position: str,
    member: dict[str, Any],
    preview: dict[str, Any],
) -> None:
    direct = _node(preview.get(position)) or _node(member)
    if direct is not None:
        nodes[position] = direct
    lineage = member.get("when_used_as_parent") or {}
    if not isinstance(lineage, dict):
        lineage = {}
    for index, key in ((1, "grandparent_1"), (2, "grandparent_2")):
        ancestor = (
            _node(preview.get(f"{position}-{index}"))
            or _node(lineage.get(key))
            or _node(member.get(key))
        )
        if ancestor is not None:
            nodes[f"{position}-{index}"] = ancestor
    for descendant in GREAT_GRANDPARENT_POSITIONS:
        if not descendant.startswith(position + "-"):
            continue
        ancestor = _node(preview.get(descendant))
        if ancestor is not None:
            nodes[descendant] = ancestor


def build_result_lineage_nodes(
    root: dict[str, Any] | None,
    row: dict[str, Any],
    mode: str = "pair",
) -> dict[str, dict[str, Any]]:
    """Normalise every ranked-result shape into the same visual tree model.

    ``root`` is the Ace for final-parent results and the parent being produced
    for grandparent results.  The distinction matters visually: a GP pair is
    not presented as if it were a pair of final parents.
    """

    nodes: dict[str, dict[str, Any]] = {}
    target = _node(root or {})
    if target is not None:
        nodes["target"] = target

    preview = _preview(row)
    if mode in {"pair", "online_parent"}:
        left, right = _direct_parents(row)
        role_map = PAIR_POSITION_TO_ROLE
        members = (("p1", left), ("p2", right))
    elif mode in {"grandparent_pair", "online_grandparent"}:
        left = row.get("fixed_grandparent") or {}
        right = row.get("candidate") or {}
        role_map = GRANDPARENT_PAIR_POSITION_TO_ROLE
        members = (
            ("p1", left if isinstance(left, dict) else {}),
            ("p2", right if isinstance(right, dict) else {}),
        )
    elif mode == "branch":
        role_map = BRANCH_POSITION_TO_ROLE
        members = (("p1", row),)
    else:
        role_map = FUTURE_GRANDPARENT_POSITION_TO_ROLE
        members = (("p1", row),)

    for position, member in members:
        _attach_branch(nodes, position, member, preview)

    _attach_existing_visual_diagnostics(nodes, row, role_map)
    return nodes


def build_pair_lineage_nodes(
    ace: dict[str, Any] | None,
    row: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Backward-compatible wrapper for final-parent pair results."""

    return build_result_lineage_nodes(ace, row, "pair")


def _inheritance_affinity_values(row: dict[str, Any]) -> dict[str, float]:
    affinity = row.get("affinity") or {}
    if not isinstance(affinity, dict):
        affinity = {}
    detail = affinity.get("inheritance_affinities") or {}
    values = detail.get("values") if isinstance(detail, dict) else None
    if not isinstance(values, dict):
        component_details = row.get("component_details") or {}
        if not isinstance(component_details, dict):
            component_details = {}
        component = component_details.get("affinity") or {}
        if not isinstance(component, dict):
            component = {}
        detail = component.get("inheritance_affinities") or {}
        values = detail.get("values") if isinstance(detail, dict) else None
        if not isinstance(values, dict):
            partial = component.get("inheritance_affinities_partial")
            values = partial if isinstance(partial, dict) else None
    result: dict[str, float] = {}
    for role, raw in (values or {}).items():
        try:
            result[str(role)] = float(raw)
        except (TypeError, ValueError):
            continue
    return result


def _float(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _white_skill_ranks(white_details: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index the engine's already-ranked White Skill contributions."""

    result: dict[str, dict[str, Any]] = {}
    for rank, item in enumerate(white_details.get("top_skills") or [], start=1):
        if not isinstance(item, dict):
            continue
        key = str(item.get("catalog_key") or "").casefold()
        if key:
            result[key] = {**item, "score_priority_rank": rank}
    return result


def _attach_existing_visual_diagnostics(
    nodes: dict[str, dict[str, Any]],
    row: dict[str, Any],
    position_to_role: dict[str, str],
) -> None:
    """Attach existing affinity and White inheritance diagnostics.

    The UI deliberately performs no inheritance formula here. It only matches
    each visible White Spark to rows already emitted by :func:`_white_score`.
    """

    affinities = _inheritance_affinity_values(row)
    component_details = row.get("component_details") or {}
    if not isinstance(component_details, dict):
        component_details = {}
    white_details = component_details.get("white_skill") or {}
    if not isinstance(white_details, dict):
        white_details = {}
    factor_details = white_details.get("factors") or white_details.get("top_factors") or []
    if not isinstance(factor_details, list):
        factor_details = []
    skill_ranks = _white_skill_ranks(white_details)
    event_count = max(1, _integer(white_details.get("inspiration_event_count")) or 2)

    for position, role in position_to_role.items():
        node = nodes.get(position)
        if not node:
            continue
        if role in affinities:
            node["inheritance_affinity"] = affinities[role]
        for factor in node.get("sparks") or []:
            factor_type = str(factor.get("type") or "")
            if factor_type not in {"white_skill", "white_race"}:
                continue
            name = str(factor.get("name") or "").casefold()
            stars = max(0, _integer(factor.get("stars")) or 0)
            matches = [
                detail
                for detail in factor_details
                if isinstance(detail, dict)
                and str(detail.get("role") or "") == role
                and str(detail.get("source_type") or "") == factor_type
                and str(detail.get("source_factor_name") or "").casefold() == name
                and max(0, _integer(detail.get("stars")) or 0) == stars
            ]
            if not matches:
                continue

            run_probability = next(
                (
                    value
                    for value in (_float(detail.get("proc_probability_over_run")) for detail in matches)
                    if value is not None
                ),
                None,
            )
            if run_probability is not None:
                factor["proc_probability_over_run"] = max(0.0, min(run_probability, 1.0))
                factor["inspiration_event_count"] = event_count

            ranked_matches = [
                skill_ranks[str(detail.get("catalog_key") or "").casefold()]
                for detail in matches
                if str(detail.get("catalog_key") or "").casefold() in skill_ranks
            ]
            if not ranked_matches:
                continue
            best = min(
                ranked_matches,
                key=lambda item: int(item.get("score_priority_rank") or 999),
            )
            contribution = max(0.0, _float(best.get("contribution")) or 0.0)
            priority_rank = int(best.get("score_priority_rank") or 999)
            factor.update(
                {
                    "score_priority_rank": priority_rank,
                    "score_contribution": contribution,
                    "profile_weight": max(0.0, _float(best.get("profile_weight")) or 0.0),
                    "priority_skill_name": str(best.get("name") or factor.get("name") or ""),
                    "is_score_priority": priority_rank <= 3 and contribution > 0.0,
                }
            )

        node["sparks"].sort(key=_spark_display_key)


def spark_badge_totals(node: dict[str, Any]) -> tuple[int, int, int]:
    blue = 0
    pink = 0
    other = 0
    for factor in node.get("sparks") or []:
        if not isinstance(factor, dict):
            continue
        stars = max(0, _integer(factor.get("stars")) or 0)
        factor_type = str(factor.get("type") or "other")
        if factor_type == "blue_stat":
            blue += stars
        elif factor_type == "red_aptitude":
            pink += stars
        else:
            other += stars
    return blue, pink, other
